# Review package: 8d0a468..8fd30f4

## Commits
8fd30f4 fix: sanitize canceled replacement events
9f27ce3 fix: close hybrid replacement review findings
0d854de refactor: extract hybrid replacement pipeline

## Files changed
 backend/matrix_native_client.py                    | 264 ++++++-------
 backend/replacement_pipeline.py                    | 426 ++++++++++++++++++++
 ...8-04-video-replacement-service-task-3-report.md | 168 ++++++++
 tests/test_replacement_service.py                  |  23 ++
 tests/test_video_replacement.py                    |  18 +-
 tests/test_video_replacement_v2.py                 | 431 +++++++++++++++++++++
 6 files changed, 1193 insertions(+), 137 deletions(-)

## Diff
diff --git a/backend/matrix_native_client.py b/backend/matrix_native_client.py
index 743509d..9e87922 100644
--- a/backend/matrix_native_client.py
+++ b/backend/matrix_native_client.py
@@ -7,20 +7,21 @@ MatrixShipAgent.exe。界面在客户端里用原生控件绘制;平台自动化
 
 原生客户端模块映射。各模块均已接本地引擎/后端与真实生成流水线(软文/爆款/商品图·视频/
 数字人/混剪/工作流均真调 lk888 或 ffmpeg;采集/发布/寻客/拓客经本机 Edge 执行);
 计费(云豆余额/扣费/失败退款/兑换码充值)已接通。唯「AI 销售」目前仅手动单发私信,
 自动回复话术待补。
 """
 
 import os
 import sys
 import time
+import copy
 import hashlib
 import threading
 import queue
 import uuid
 import subprocess
 import shutil
 import concurrent.futures
 import ipaddress
 import mimetypes
 import re
@@ -11588,20 +11589,43 @@ def _replacement_segment_status_text(job, segment):
     return " · ".join(parts)
 
 
 def _replacement_emit_stage(job, segment, stage, message="", prompt=None):
     job_id = str((job or {}).get("id") or "")
     callback = _REPLACEMENT_PROGRESS_CALLBACKS.get(job_id)
     if callable(callback):
         callback(segment, stage, message or _replacement_stage_label(stage), prompt=prompt)
 
 
+class _ReplacementHelperProxy:
+    def __init__(self, namespace):
+        self._namespace = namespace
+
+    def __getattr__(self, name):
+        try:
+            return self._namespace[name]
+        except KeyError as exc:
+            raise AttributeError(name) from exc
+
+
+_REPLACEMENT_HELPERS = _ReplacementHelperProxy(globals())
+
+
+def _replacement_hybrid_pipeline():
+    from replacement_pipeline import HybridReplacementPipeline
+    return HybridReplacementPipeline(helpers=_REPLACEMENT_HELPERS, runtime=time)
+
+
+def _replacement_public_job(job):
+    return _replacement_hybrid_pipeline().public_job(job)
+
+
 def _replacement_cancel_requested(job):
     return bool((job or {}).get("cancelRequested")) or str((job or {}).get("status") or "") == "cancel_requested"
 
 
 def _replacement_cancel_check(job):
     return lambda: _replacement_cancel_requested(job)
 
 
 def _replacement_cancel_exception(exc):
     return "lk888_task_cancelled" in str(exc or "")
@@ -11610,21 +11634,21 @@ def _replacement_cancel_exception(exc):
 def _mark_replacement_job_canceled(job, message="任务已取消，中心人脸素材已清理"):
     job = job or {}
     job["status"] = "canceled"
     cleanup = _cleanup_replacement_sensitive_materials(job)
     temporary_cleanup = _cleanup_replacement_temporary_materials(job)
     job["sensitiveCleanup"] = cleanup
     job["temporaryCleanup"] = temporary_cleanup
     _save_replacement_job(job)
     if BRIDGE is not None:
         BRIDGE.payload.emit("video_replace_done", {
-            "jobId": job.get("id"), "message": message, "job": job,
+            "jobId": job.get("id"), "message": message, "job": _replacement_public_job(job),
         })
     return job
 
 
 def _delete_replacement_segment(job, segment_index):
     job = job or {}
     try:
         target = int(segment_index)
     except (TypeError, ValueError):
         return False
@@ -15157,49 +15181,37 @@ class VideoReplacementPage(BasePage):
                     list(self._job.get("sensitiveMaterialIds") or []) + ids
                 ))
                 _save_replacement_job(self._job)
         scene_url = ""
         if self._scene_path:
             scene_url, _resp = upload_asset_url(self._scene_path, "同款替换场景图", "image")
         return product_urls, face_urls, scene_url, list(dict.fromkeys(sensitive_ids))
 
     def _build_job(self):
         analysis = self._source.get("breakdownAnalysis") or {}
-        meta = analysis.get("meta") or {}
-        duration = float(meta.get("duration") or 0) or float(_probe_video(self._source.get("sourceVideoPath") or "").get("duration") or 8)
         out_dir = self._job.get("outDir") or os.path.join(data_dir(), "video_replacements", uuid.uuid4().hex)
         os.makedirs(out_dir, exist_ok=True)
         replacement_mode = _replacement_job_mode(self._job)
         no_person_mode = bool(self.no_person_mode.isChecked())
-        identity_mode = "standard"
         strict_script_audio = False
         selected_model = self._selected_replacement_model()
         if replacement_mode == "comic_project" and (
                 not selected_model or selected_model == _LK888_PRINCIPAL_VIDEO_MODEL):
             selected_model = _COMIC_PROJECT_VIDEO_DEFAULT
         principal_mode = str(self._job.get("principalReplacementMode") or "").strip()
         principal_enabled = bool(
             not no_person_mode
             and replacement_mode != "comic_project"
             and principal_mode == "source_video_edit"
             and _env_enabled("VIDEO_REPLACE_PRINCIPAL_REPLACEMENT", "1")
         )
         audio_mode = self._selected_audio_mode()
-        segments = self._job.get("segments") or _build_hybrid_replacement_plan(
-            analysis, duration, segment_seconds=8, strict_script_audio=strict_script_audio)
-        for segment in segments:
-            segment["segmentType"] = (
-                "talking"
-                if not no_person_mode and _replacement_segment_should_talk(
-                    segment, audio_mode=audio_mode, strict_script_audio=strict_script_audio)
-                else "non_talking"
-            )
         job = {
             "id": self._job.get("id") or uuid.uuid4().hex,
             "replacementMode": replacement_mode,
             "sourceVideoPath": self._source.get("sourceVideoPath") or "",
             "sourceUrl": self._source.get("sourceUrl") or "",
             "platform": self._source.get("platform") or "",
             "breakdownAnalysis": analysis,
             "productImageUrls": list(self._product_urls),
             "productSourcePaths": list(self._product_paths),
             "productPreprocess": list(self._job.get("productPreprocess") or []),
@@ -15220,50 +15232,42 @@ class VideoReplacementPage(BasePage):
             ),
             "principalReplacementMode": "source_video_edit" if principal_enabled else "",
             "identityMode": "standard",
             "enableFaceFusion": False,
             "sensitiveMaterialIds": [] if no_person_mode else list(self._job.get("sensitiveMaterialIds") or []),
             "noPersonMode": no_person_mode,
             "productNotes": "uploaded product reference images: " + ", ".join(os.path.basename(p) for p in self._product_paths),
             "modelNotes": "no human subject; product-only video" if no_person_mode else (
                 "authorized full-body person references" if principal_enabled else (
                     "authorized model face" if self._face_url else "virtual model identity")),
-            "segments": segments,
+            "segments": copy.deepcopy(self._job.get("segments") or []),
             "outDir": out_dir,
             "pipeline": "comic_project" if replacement_mode == "comic_project" else (
                 self._job.get("pipeline") or os.getenv("VIDEO_REPLACE_PIPELINE", "hybrid_v2")
             ),
             "aspectRatio": "9:16",
             "resolution": "720p",
             "audioMode": audio_mode,
             "voiceId": self._selected_voice_id(),
             "replacementAudioPath": getattr(self, "_replacement_audio_path", "") or self._job.get("replacementAudioPath") or "",
             "replacementAudioUrl": getattr(self, "_replacement_audio_url", "") or self._job.get("replacementAudioUrl") or "",
             "digitalHumanMode": "std",
             "strictScriptAudio": strict_script_audio,
             "actionControlEnabled": False,
             "productAnchorEnabled": False,
             "model": selected_model,
             "status": "running",
             "startedAt": self._job.get("startedAt") or time.time(),
             "outputPath": "",
             "assetId": "",
         }
-        if replacement_mode == "comic_project":
-            job["principalReplacementMode"] = ""
-        for seg in segments:
-            seg["prompt"] = _build_replacement_prompt(
-                seg, analysis, job["productNotes"], job["modelNotes"])
-        if replacement_mode == "comic_project":
-            segments = _comic_plan_script_segments(segments, max_speech_sec=15.0)
-            job["segments"] = segments
-        return job
+        return _replacement_hybrid_pipeline().build_plan(job)
 
     def start_generation(self):
         if self._busy:
             self.status.setText("已有替换生成任务正在运行")
             QtWidgets.QMessageBox.information(self, "替换生成", "已有替换生成任务正在运行，请等待当前任务完成。")
             return
         if not self._job.get("segments"):
             self._warn_generation_blocked("请先点击『生成替换方案』并检查片段。")
             return
         replacement_mode = _replacement_job_mode(self._job)
@@ -15375,21 +15379,21 @@ class VideoReplacementPage(BasePage):
                 job = self._build_job()
                 self._job = job
                 replacement_mode = _replacement_job_mode(job)
                 upstream_preflight = None
                 def emit_ref_progress(message):
                     BRIDGE.payload.emit("video_replace_progress", {
                         "jobId": job["id"],
                         "stage": "product_refs",
                         "message": message,
                         "timing": _replacement_timing_snapshot(job, None, stage="product_refs"),
-                        "segments": job.get("segments") or [],
+                        "segments": _replacement_hybrid_pipeline().public_segments(job),
                     })
 
                 if replacement_mode != "comic_project":
                     upstream_preflight = _replacement_upstream_preflight(job)
                     job["upstreamPreflight"] = upstream_preflight
                     if not upstream_preflight.get("ok"):
                         error_id = _replacement_error_id(
                             "video_replace_upstream_preflight_blocked",
                             RuntimeError(upstream_preflight.get("code") or "upstream_preflight_failed"),
                             source_video=job.get("sourceVideoPath") or "",
@@ -15400,21 +15404,21 @@ class VideoReplacementPage(BasePage):
                             "errorId": error_id,
                         })
                         job["diagnostics"] = _replacement_diagnostics_summary(job, upstream_preflight)
                         _save_replacement_job(job)
                         BRIDGE.payload.emit("video_replace_done", {
                             "jobId": job["id"],
                             "message": "%s（错误编号 %s）" % (
                                 upstream_preflight.get("summary") or "上游预检未通过",
                                 error_id or "-",
                             ),
-                            "job": job,
+                            "job": _replacement_public_job(job),
                         })
                         return
 
                 self._product_urls, self._face_urls, self._scene_url, sensitive_ids = self._upload_refs(lambda message: emit_ref_progress(message))
                 if no_person_mode:
                     self._face_urls = []
                     self._face_url = ""
                     sensitive_ids = []
                 else:
                     self._face_url = self._face_urls[0]
@@ -15444,128 +15448,100 @@ class VideoReplacementPage(BasePage):
                     job.update({
                         "status": "failed",
                         "error": preflight.get("reason") or "参考图与源视频主题冲突",
                         "errorId": error_id,
                     })
                     job["diagnostics"] = _replacement_diagnostics_summary(job, preflight)
                     _save_replacement_job(job)
                     BRIDGE.payload.emit("video_replace_done", {
                         "jobId": job["id"],
                         "message": "参考图与原视频主题冲突，已停止生成（错误编号 %s）" % (error_id or "-"),
-                        "job": job,
+                        "job": _replacement_public_job(job),
                     })
                     return
                 BRIDGE.payload.emit("video_replace_progress", {
                     "jobId": job["id"], "stage": "editing", "message": "开始串行生成片段…",
                     "timing": _replacement_timing_snapshot(job, None, stage="editing"),
-                    "segments": job["segments"],
+                    "segments": _replacement_hybrid_pipeline().public_segments(job),
                 })
                 self._run_job_segments(job, [s for s in job["segments"]])
             except Exception as exc:
                 error_id = _replacement_error_id("video_replace_upload_failed", exc)
                 cleanup = _cleanup_replacement_sensitive_materials(self._job)
                 failure_job = dict(self._job or {}, status="failed", error=str(exc)[:240],
                                    errorId=error_id, sensitiveCleanup=cleanup)
                 failure_job["diagnostics"] = _replacement_diagnostics_summary(failure_job)
                 try:
                     _save_replacement_job(failure_job)
                 except Exception:
                     pass
                 BRIDGE.payload.emit("video_replace_done", {
                     "jobId": (self._job or {}).get("id") or "",
                     "message": "替换生成失败（错误编号 %s）:%s" % (error_id or "-", str(exc)[:120]),
-                    "job": failure_job,
+                    "job": _replacement_public_job(failure_job),
                 })
         run_bg(work)
 
     def _run_job_segments(self, job, selected_segments):
-        job["startedAt"] = job.get("startedAt") or time.time()
-        job["status"] = "running"
-        total = len(job.get("segments") or [])
+        if _replacement_job_mode(job) == "comic_project":
+            def emit_progress(segment=None, stage="", message="", prompt=None):
+                timing = _replacement_timing_snapshot(job, segment, stage=stage)
+                if segment is not None:
+                    segment["stage"] = timing.get("stage") or stage or segment.get("status") or ""
+                    segment["stageLabel"] = timing.get("stageLabel") or ""
+                    segment["elapsedSec"] = timing.get("segmentElapsedSec") or 0
+                    segment["etaSec"] = timing.get("segmentEtaSec") or 0
+                BRIDGE.payload.emit("video_replace_progress", {
+                    "jobId": job["id"],
+                    "stage": timing.get("stage") or stage or "",
+                    "message": message or _replacement_stage_label(stage),
+                    "timing": timing,
+                    "segments": job.get("segments") or [],
+                    "prompt": prompt if prompt is not None else ((segment or {}).get("prompt") or ""),
+                })
+            self._run_comic_project_segments(job, selected_segments, emit_progress)
+            return
+
+        pipeline = _replacement_hybrid_pipeline()
 
-        def emit_progress(segment=None, stage="", message="", prompt=None):
+        def emit_progress(job_id, stage, message, segment_index, segments):
+            segment = None
+            if segment_index is not None:
+                for item in (job.get("segments") or []):
+                    if int(item.get("index") or 0) == int(segment_index or 0):
+                        segment = item
+                        break
             timing = _replacement_timing_snapshot(job, segment, stage=stage)
-            if segment is not None:
-                segment["stage"] = timing.get("stage") or stage or segment.get("status") or ""
-                segment["stageLabel"] = timing.get("stageLabel") or ""
-                segment["elapsedSec"] = timing.get("segmentElapsedSec") or 0
-                segment["etaSec"] = timing.get("segmentEtaSec") or 0
+            prompt = ""
+            if segment_index is not None:
+                for item in segments or []:
+                    if int((item or {}).get("index") or 0) == int(segment_index or 0):
+                        prompt = str((item or {}).get("prompt") or "")
+                        break
             BRIDGE.payload.emit("video_replace_progress", {
-                "jobId": job["id"],
+                "jobId": job_id,
                 "stage": timing.get("stage") or stage or "",
                 "message": message or _replacement_stage_label(stage),
                 "timing": timing,
-                "segments": job.get("segments") or [],
-                "prompt": prompt if prompt is not None else ((segment or {}).get("prompt") or ""),
+                "segments": segments or [],
+                "prompt": prompt,
             })
 
-        _REPLACEMENT_PROGRESS_CALLBACKS[str(job.get("id") or "")] = emit_progress
-        try:
-            if _replacement_job_mode(job) == "comic_project":
-                self._run_comic_project_segments(job, selected_segments, emit_progress)
-                return
-            for seg in selected_segments:
-                if self._cancel_requested or _replacement_cancel_requested(job):
-                    _mark_replacement_job_canceled(job)
-                    return
-                seg["segmentStartedAt"] = time.time()
-                seg["segmentEndedAt"] = 0
-                seg["elapsedSec"] = 0
-                seg["etaSec"] = _replacement_segment_baseline_sec(seg)
-                emit_progress(seg, "editing", "生成片段 %s/%s：准备生成（%.1f-%.1fs）" % (
-                    seg.get("index"), total, seg.get("start") or 0, seg.get("end") or 0))
-                try:
-                    if (job.get("pipeline") or os.getenv("VIDEO_REPLACE_PIPELINE", "hybrid_v2")) == "hybrid_v2":
-                        _run_hybrid_replacement_segment(job, seg)
-                    else:
-                        _run_replacement_segment(job, seg)
-                        if seg.get("status") == "done":
-                            seg.update({"audioStatus": "passed", "qcStatus": "passed"})
-                except Exception as exc:
-                    if self._cancel_requested or _replacement_cancel_requested(job) or _replacement_cancel_exception(exc):
-                        seg.update({"status": "cancel_requested", "stage": "cancel_requested",
-                                    "stageLabel": "取消中", "etaSec": 0})
-                        _mark_replacement_job_canceled(job)
-                        return
-                    raise
-                seg["segmentEndedAt"] = time.time()
-                seg["elapsedSec"] = _replacement_segment_elapsed_sec(seg)
-                if seg.get("status") == "done":
-                    seg.update({"stage": "done", "stageLabel": _replacement_stage_label("done"), "etaSec": 0})
-                elif seg.get("status") == "failed":
-                    seg.update({"etaSec": 0})
-                _save_replacement_job(job)
-                emit_progress(seg, seg.get("stage") or seg.get("status") or "editing", "片段 %s/%s 状态已更新" % (
-                    seg.get("index"), total))
-            failed = [s for s in job.get("segments") or [] if s.get("status") == "failed"]
-            if failed:
-                job["status"] = "partial"
-                job["diagnostics"] = _replacement_diagnostics_summary(job)
-                _save_replacement_job(job)
-                BRIDGE.payload.emit("video_replace_done", {
-                    "jobId": job["id"],
-                    "message": "有 %d 个片段失败，可点击『重试失败片段』" % len(failed),
-                    "job": job,
-                    "failedSegments": failed,
-                })
-                return
-            job["status"] = "awaiting_review"
-            _save_replacement_job(job)
-            BRIDGE.payload.emit("video_replace_progress", {
+        result = pipeline.execute(job, selected_segments, progress=emit_progress)
+        if result.get("status") == "partial":
+            failed = [item for item in (job.get("segments") or []) if item.get("status") == "failed"]
+            BRIDGE.payload.emit("video_replace_done", {
                 "jobId": job["id"],
-                "stage": "awaiting_review",
-                "message": "片段已通过自动检查，请查看首、中、尾帧和试听后确认合成。",
-                "timing": _replacement_timing_snapshot(job, None, stage="awaiting_review"),
-                "segments": job.get("segments") or [],
+                "message": "有 %d 个片段失败，可点击『重试失败片段』" % len(failed),
+                "job": _replacement_public_job(job),
+                "failedSegments": pipeline.public_job({"segments": failed}).get("segments") or [],
             })
-        finally:
-            _REPLACEMENT_PROGRESS_CALLBACKS.pop(str(job.get("id") or ""), None)
 
     def _run_comic_project_segments(self, job, selected_segments, emit_progress):
         adapter = ComicProjectAdapter()
         segments = job.get("segments") or []
         selected_segments = list(selected_segments or [])
         job["status"] = "running"
         if not job.get("comicProjectId"):
             emit_progress(None, "comic_project", "创建漫剧项目…")
             created = adapter.create_project(job)
             project_id = _comic_extract_id(created)
@@ -15916,52 +15892,39 @@ class VideoReplacementPage(BasePage):
             self._warn_generation_blocked(
                 "暂时不能合成：" + "；".join(block_reasons[:3])
             )
             return
         self._busy = True
         self._set_generation_feedback(True, "正在合成视频…")
 
         def work():
             job = self._job
             try:
-                out = os.path.join(job.get("outDir") or data_dir(), "replacement_final_%s.mp4" % int(time.time()))
-                paths = [s.get("videoPath") for s in job.get("segments") or []]
-                final_out = _prepare_replacement_final_video(job, paths, out)
-                asset = _save_replacement_to_assets(final_out, job)
-                if not asset:
-                    raise RuntimeError("replacement_asset_save_failed")
-                job.pop("audioCheck", None)
-                job.update({
-                    "status": "done",
-                    "outputPath": asset.get("path") or final_out,
-                    "assetId": asset.get("id") or "",
+                job = _replacement_hybrid_pipeline().concat(job)
+                self._job = job
+                BRIDGE.payload.emit("video_replace_done", {
+                    "jobId": job["id"],
+                    "message": "替换生成完成，已存入资产库",
+                    "job": _replacement_public_job(job),
                     "audioValidation": "disabled",
                     "reviewStatus": "approved",
-                })
-                cleanup = _cleanup_replacement_sensitive_materials(job)
-                temporary_cleanup = _cleanup_replacement_temporary_materials(job)
-                job["sensitiveCleanup"] = cleanup
-                job["temporaryCleanup"] = temporary_cleanup
-                _save_replacement_job(job)
-                BRIDGE.payload.emit("video_replace_done", {
-                    "jobId": job["id"], "message": "替换生成完成，已存入资产库", "job": job,
-                    "audioValidation": "disabled", "reviewStatus": "approved",
-                    "sensitiveCleanup": cleanup, "temporaryCleanup": temporary_cleanup,
+                    "sensitiveCleanup": job.get("sensitiveCleanup") or {},
+                    "temporaryCleanup": job.get("temporaryCleanup") or {},
                 })
             except Exception as exc:
                 error_id = _replacement_error_id("video_replace_concat_failed", exc, source_video=job.get("sourceVideoPath") or "")
                 job["status"] = "failed"
                 _save_replacement_job(job)
                 BRIDGE.payload.emit("video_replace_done", {
                     "jobId": job["id"],
                     "message": "合成失败（错误编号 %s）:%s" % (error_id or "-", str(exc)[:120]),
-                    "job": job,
+                    "job": _replacement_public_job(job),
                 })
         run_bg(work)
 
     def retry_failed_segments(self):
         if self._busy:
             return
         if _replacement_job_mode(self._job) == "comic_project":
             self._sync_segment_scripts_from_table()
             failed = [
                 s for s in (self._job.get("segments") or [])
@@ -16005,39 +15968,68 @@ class VideoReplacementPage(BasePage):
             run_bg(lambda: self._run_comic_video_regeneration(
                 self._job, ready, allow_pending_recovery=True
             ))
             return
         failed = [s for s in (self._job.get("segments") or []) if s.get("status") == "failed"]
         if not failed:
             self.status.setText("没有失败片段可重试")
             self.b_retry_failed.setEnabled(False)
             QtWidgets.QMessageBox.information(self, "替换生成", "没有失败片段可重试。")
             return
-        failed, retry_normalization = _normalize_replacement_retry_segments(self._job, failed)
-        retry_summaries = [_prepare_replacement_segment_for_retry(segment) for segment in failed]
-        self._job["lastRetryPreparation"] = {
-            "ts": time.time(),
-            "normalization": retry_normalization,
-            "segments": [
-                {
-                    "index": segment.get("index"),
-                    "demotedCodes": summary.get("demotedCodes") or [],
-                }
-                for segment, summary in zip(failed, retry_summaries)
-            ],
-        }
-        _save_replacement_job(self._job)
         self._busy = True
         self.b_retry_failed.setEnabled(False)
         self.status.setText("正在重试失败片段…")
         self._set_generation_feedback(True, "正在重试失败片段…")
-        run_bg(lambda: self._run_job_segments(self._job, failed))
+        pipeline = _replacement_hybrid_pipeline()
+
+        def emit_progress(job_id, stage, message, segment_index, segments):
+            segment = None
+            if segment_index is not None:
+                for item in (self._job.get("segments") or []):
+                    if int(item.get("index") or 0) == int(segment_index or 0):
+                        segment = item
+                        break
+            timing = _replacement_timing_snapshot(self._job, segment, stage=stage)
+            prompt = ""
+            if segment_index is not None:
+                for item in segments or []:
+                    if int((item or {}).get("index") or 0) == int(segment_index or 0):
+                        prompt = str((item or {}).get("prompt") or "")
+                        break
+            BRIDGE.payload.emit("video_replace_progress", {
+                "jobId": job_id,
+                "stage": timing.get("stage") or stage or "",
+                "message": message or _replacement_stage_label(stage),
+                "timing": timing,
+                "segments": segments or [],
+                "prompt": prompt,
+            })
+
+        def work():
+            pipeline.retry(
+                self._job,
+                segment_indices=[segment.get("index") for segment in failed],
+                progress=emit_progress,
+            )
+            if self._job.get("status") == "partial":
+                failed_segments = [
+                    item for item in (self._job.get("segments") or [])
+                    if item.get("status") == "failed"
+                ]
+                BRIDGE.payload.emit("video_replace_done", {
+                    "jobId": self._job.get("id") or "",
+                    "message": "有 %d 个片段失败，可点击『重试失败片段』" % len(failed_segments),
+                    "job": _replacement_public_job(self._job),
+                    "failedSegments": pipeline.public_job({"segments": failed_segments}).get("segments") or [],
+                })
+
+        run_bg(work)
 
     def _comic_regeneration_click_allowed(self, segment, media_kind):
         segment = segment if isinstance(segment, dict) else {}
         kind = str(media_kind or "").strip()
         json_log(
             _CLIENT_JSON_LOGGER,
             "video_replace_comic_regeneration_requested",
             job_id=str((self._job or {}).get("id") or ""),
             project_id=(self._job or {}).get("comicProjectId") or "",
             segment_index=segment.get("index") or "",
diff --git a/backend/replacement_pipeline.py b/backend/replacement_pipeline.py
index f18629a..967ba70 100644
--- a/backend/replacement_pipeline.py
+++ b/backend/replacement_pipeline.py
@@ -1,9 +1,435 @@
+import copy
+import os
+import re
+import time
+import uuid
+from urllib.parse import urlparse
+
+
+_PATH_REDACTION = "[redacted-path]"
+_URL_REDACTION = "[redacted-url]"
+_CREDENTIAL_RE = re.compile(
+    r"(?i)\b(?P<key>authorization|bearer|token|cookie|password)\b"
+    r"(?:\s*[:=]\s*|\s+)(?P<value>[^\s,;]+)"
+)
+_HTTP_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
+_PRIVATE_KEYS = {
+    "outDir",
+    "sourceVideoPath",
+    "outputPath",
+    "videoPath",
+    "editedVideoPath",
+    "faceSwapPath",
+    "sourceFramePath",
+    "sourceSegmentPath",
+    "sourceSegmentUploadPath",
+    "keyframePath",
+    "sceneImagePath",
+    "startFramePath",
+    "endFramePath",
+    "replacementAudioPath",
+    "personReferencePaths",
+    "productSourcePaths",
+    "faceSourcePaths",
+    "targetFaceReferencePath",
+}
+
+
 class ReplacementPipeline:
     def build_plan(self, job):
         return job
 
     def execute(self, job, selected_segments=None, progress=None):
         return job
 
+    def retry(self, job, segment_indices, progress=None):
+        return job
+
+    def concat(self, job):
+        return job
+
+
+class HybridReplacementPipeline(ReplacementPipeline):
+    def __init__(self, helpers=None, runtime=None):
+        self.helpers = helpers
+        self.runtime = runtime
+
+    def build_plan(self, job):
+        job = job if isinstance(job, dict) else {}
+        analysis = dict(job.get("breakdownAnalysis") or {})
+        duration = self._job_duration(job, analysis)
+        out_dir = str(job.get("outDir") or self._job_out_dir()).strip()
+        os.makedirs(out_dir, exist_ok=True)
+        strict_script_audio = bool(job.get("strictScriptAudio"))
+        replacement_mode = self._call("_replacement_job_mode", job)
+        segments = copy.deepcopy(job.get("segments") or [])
+        if not segments:
+            segments = self._call(
+                "_build_hybrid_replacement_plan",
+                analysis,
+                duration,
+                segment_seconds=8,
+                strict_script_audio=strict_script_audio,
+            )
+        audio_mode = str(job.get("audioMode") or "auto").strip() or "auto"
+        no_person_mode = bool(job.get("noPersonMode"))
+        product_notes = str(job.get("productNotes") or "").strip()
+        model_notes = str(job.get("modelNotes") or "").strip()
+        for segment in segments:
+            segment["segmentType"] = (
+                "talking"
+                if not no_person_mode and self._call(
+                    "_replacement_segment_should_talk",
+                    segment,
+                    audio_mode=audio_mode,
+                    strict_script_audio=strict_script_audio,
+                )
+                else "non_talking"
+            )
+            segment["prompt"] = self._call(
+                "_build_replacement_prompt",
+                segment,
+                analysis,
+                product_notes,
+                model_notes,
+            )
+        if replacement_mode == "comic_project":
+            job["principalReplacementMode"] = ""
+            segments = self._call("_comic_plan_script_segments", segments, max_speech_sec=15.0)
+        job["breakdownAnalysis"] = analysis
+        job["duration"] = duration
+        job["outDir"] = out_dir
+        job["segments"] = segments
+        job["pipeline"] = str(job.get("pipeline") or os.getenv("VIDEO_REPLACE_PIPELINE", "hybrid_v2")).strip() or "hybrid_v2"
+        job["sourceReplacementEntities"] = copy.deepcopy(
+            job.get("sourceReplacementEntities")
+            or self._call("_replacement_source_entities_from_analysis", analysis)
+        )
+        job["startedAt"] = job.get("startedAt") or self._now()
+        return job
+
+    def execute(self, job, selected_segments, progress=None):
+        job = job if isinstance(job, dict) else {}
+        job["startedAt"] = job.get("startedAt") or self._now()
+        job["status"] = "running"
+        segments = list(job.get("segments") or [])
+        total = len(segments)
+        chosen = self._resolve_selected_segments(job, selected_segments)
+        callbacks = getattr(self._helpers(), "_REPLACEMENT_PROGRESS_CALLBACKS")
+
+        def emit_progress(segment=None, stage="", message="", prompt=None):
+            timing = self._call("_replacement_timing_snapshot", job, segment, stage=stage)
+            stage_value = timing.get("stage") or stage or str((segment or {}).get("status") or "")
+            if segment is not None:
+                segment["stage"] = stage_value
+                segment["stageLabel"] = timing.get("stageLabel") or self._call("_replacement_stage_label", stage_value)
+                segment["elapsedSec"] = timing.get("segmentElapsedSec") or 0
+                segment["etaSec"] = timing.get("segmentEtaSec") or 0
+            self._persist(job)
+            if callable(progress):
+                progress(
+                    str(job.get("id") or ""),
+                    stage_value,
+                    message or self._call("_replacement_stage_label", stage_value),
+                    (segment or {}).get("index"),
+                    self.public_segments(job),
+                )
+
+        callbacks[str(job.get("id") or "")] = emit_progress
+        try:
+            for segment in chosen:
+                if self._call("_replacement_cancel_requested", job):
+                    self._call("_mark_replacement_job_canceled", job)
+                    self._persist(job)
+                    return job
+                segment["segmentStartedAt"] = self._now()
+                segment["segmentEndedAt"] = 0
+                segment["elapsedSec"] = 0
+                segment["etaSec"] = self._call("_replacement_segment_baseline_sec", segment)
+                emit_progress(
+                    segment,
+                    "editing",
+                    "生成片段 %s/%s：准备生成（%.1f-%.1fs）" % (
+                        segment.get("index"),
+                        total,
+                        float(segment.get("start") or 0),
+                        float(segment.get("end") or 0),
+                    ),
+                )
+                try:
+                    self._run_segment(job, segment)
+                except Exception as exc:
+                    if self._call("_replacement_cancel_exception", exc) or self._call("_replacement_cancel_requested", job):
+                        return job
+                    raise
+                segment["segmentEndedAt"] = self._now()
+                segment["elapsedSec"] = self._call("_replacement_segment_elapsed_sec", segment)
+                if segment.get("status") == "done":
+                    segment["stage"] = "done"
+                    segment["stageLabel"] = self._call("_replacement_stage_label", "done")
+                    segment["etaSec"] = 0
+                elif segment.get("status") == "failed":
+                    segment["etaSec"] = 0
+                self._persist(job)
+                emit_progress(
+                    segment,
+                    segment.get("stage") or segment.get("status") or "editing",
+                    "片段 %s/%s 状态已更新" % (segment.get("index"), total),
+                )
+            failed = [item for item in segments if item.get("status") == "failed"]
+            if failed:
+                job["status"] = "partial"
+                job["diagnostics"] = self._call("_replacement_diagnostics_summary", job)
+                self._persist(job)
+                emit_progress(None, "partial", "有 %d 个片段失败，可点击『重试失败片段』" % len(failed))
+                return job
+            job["status"] = "awaiting_review"
+            self._persist(job)
+            emit_progress(None, "awaiting_review", "片段已通过自动检查，请查看首、中、尾帧和试听后确认合成。")
+            return job
+        finally:
+            callbacks.pop(str(job.get("id") or ""), None)
+
+    def retry(self, job, segment_indices, progress=None):
+        job = job if isinstance(job, dict) else {}
+        wanted = {int(value) for value in (segment_indices or [])}
+        failed = [
+            segment for segment in (job.get("segments") or [])
+            if isinstance(segment, dict)
+            and segment.get("status") == "failed"
+            and (not wanted or int(segment.get("index") or 0) in wanted)
+        ]
+        if not failed:
+            return job
+        failed, retry_normalization = self._call("_normalize_replacement_retry_segments", job, failed)
+        retry_summaries = [self._call("_prepare_replacement_segment_for_retry", segment) for segment in failed]
+        job["lastRetryPreparation"] = {
+            "ts": self._now(),
+            "normalization": retry_normalization,
+            "segments": [
+                {
+                    "index": segment.get("index"),
+                    "demotedCodes": summary.get("demotedCodes") or [],
+                }
+                for segment, summary in zip(failed, retry_summaries)
+            ],
+        }
+        self._persist(job)
+        return self.execute(job, selected_segments=failed, progress=progress)
+
     def concat(self, job):
+        job = job if isinstance(job, dict) else {}
+        block_reasons = self._call("_replacement_final_block_reasons", job.get("segments") or [], job=job)
+        if block_reasons:
+            raise RuntimeError("replacement_concat_blocked:%s" % "；".join(block_reasons[:3]))
+        out_dir = str(job.get("outDir") or self._job_out_dir()).strip()
+        os.makedirs(out_dir, exist_ok=True)
+        out = os.path.join(out_dir, "replacement_final_%s.mp4" % int(self._now()))
+        paths = [segment.get("videoPath") for segment in (job.get("segments") or [])]
+        final_out = self._call("_prepare_replacement_final_video", job, paths, out)
+        asset = self._call("_save_replacement_to_assets", final_out, job)
+        if not asset:
+            raise RuntimeError("replacement_asset_save_failed")
+        job.pop("audioCheck", None)
+        job.update({
+            "status": "done",
+            "outputPath": asset.get("path") or final_out,
+            "assetId": asset.get("id") or "",
+            "audioValidation": "disabled",
+            "reviewStatus": "approved",
+        })
+        job["sensitiveCleanup"] = self._call("_cleanup_replacement_sensitive_materials", job)
+        job["temporaryCleanup"] = self._call("_cleanup_replacement_temporary_materials", job)
+        self._persist(job)
         return job
+
+    def public_job(self, job):
+        return self._scrub_value(
+            copy.deepcopy(job or {}),
+            sensitive_strings=self._public_sensitive_strings(job),
+        )
+
+    def public_segments(self, job):
+        values = self.public_job({"segments": (job or {}).get("segments") or []})
+        return values.get("segments") or []
+
+    def _run_segment(self, job, segment):
+        runner_name = "_run_hybrid_replacement_segment"
+        if str(job.get("pipeline") or "").strip() and str(job.get("pipeline")).strip() != "hybrid_v2":
+            runner_name = "_run_replacement_segment"
+        try:
+            result = self._call(runner_name, job, segment)
+            if runner_name == "_run_replacement_segment" and segment.get("status") == "done":
+                segment.setdefault("audioStatus", "passed")
+                segment.setdefault("qcStatus", "passed")
+            if isinstance(result, dict) and not result.get("ok", True):
+                self._ensure_segment_failed(job, segment, result.get("error") or "replacement_segment_failed")
+            elif segment.get("status") not in ("done", "failed"):
+                self._ensure_segment_failed(job, segment, "replacement_segment_incomplete")
+        except Exception as exc:
+            if self._call("_replacement_cancel_exception", exc) or self._call("_replacement_cancel_requested", job):
+                segment.update({
+                    "status": "cancel_requested",
+                    "stage": "cancel_requested",
+                    "stageLabel": "取消中",
+                    "etaSec": 0,
+                    "error": "",
+                    "errorId": "",
+                })
+                self._call("_mark_replacement_job_canceled", job)
+                raise
+            self._ensure_segment_failed(job, segment, str(exc) or exc.__class__.__name__, exc=exc)
+
+    def _ensure_segment_failed(self, job, segment, message, exc=None):
+        error_text = str(message or "replacement_segment_failed")[:180]
+        if not segment.get("errorId"):
+            segment["errorId"] = self._call(
+                "_replacement_error_id",
+                "video_replace_segment_failed",
+                exc or RuntimeError(error_text),
+                segment_index=segment.get("index"),
+                segment_type=segment.get("segmentType") or "unknown",
+                source_video=job.get("sourceVideoPath") or "",
+            )
+        segment["status"] = "failed"
+        segment["audioStatus"] = segment.get("audioStatus") if segment.get("audioStatus") == "passed" else "failed"
+        segment["qcStatus"] = "failed"
+        segment["error"] = error_text
+
+    def _resolve_selected_segments(self, job, selected_segments):
+        segments = list(job.get("segments") or [])
+        if not selected_segments:
+            return segments
+        values = []
+        by_index = {
+            int(segment.get("index") or position + 1): segment
+            for position, segment in enumerate(segments)
+            if isinstance(segment, dict)
+        }
+        for item in selected_segments:
+            if isinstance(item, dict) and item in segments:
+                values.append(item)
+                continue
+            try:
+                index = int((item or {}).get("index") if isinstance(item, dict) else item)
+            except (TypeError, ValueError, AttributeError):
+                continue
+            segment = by_index.get(index)
+            if segment is not None and segment not in values:
+                values.append(segment)
+        return values or segments
+
+    def _public_sensitive_strings(self, job):
+        sensitive = set()
+        self._collect_sensitive_strings(job, sensitive)
+        return sorted((item for item in sensitive if item), key=len, reverse=True)
+
+    def _collect_sensitive_strings(self, value, sensitive):
+        if isinstance(value, dict):
+            for key, child in value.items():
+                if key in _PRIVATE_KEYS and isinstance(child, str):
+                    sensitive.update(self._path_variants(child))
+                self._collect_sensitive_strings(child, sensitive)
+            return
+        if isinstance(value, list):
+            for item in value:
+                self._collect_sensitive_strings(item, sensitive)
+
+    def _path_variants(self, value):
+        raw = str(value or "").strip()
+        if not raw:
+            return set()
+        values = {raw}
+        if "\\" in raw:
+            values.add(raw.replace("\\", "/"))
+        if "/" in raw:
+            values.add(raw.replace("/", "\\"))
+        return values
+
+    def _scrub_value(self, value, sensitive_strings):
+        if isinstance(value, dict):
+            cleaned = {}
+            for key, child in value.items():
+                if key in _PRIVATE_KEYS:
+                    continue
+                cleaned[key] = self._scrub_value(child, sensitive_strings)
+            return cleaned
+        if isinstance(value, list):
+            return [self._scrub_value(item, sensitive_strings) for item in value]
+        if isinstance(value, str):
+            return self._scrub_string(value, sensitive_strings)
+        return value
+
+    def _scrub_string(self, value, sensitive_strings):
+        cleaned = str(value)
+        for item in sensitive_strings:
+            cleaned = cleaned.replace(item, _PATH_REDACTION)
+        cleaned = _HTTP_URL_RE.sub(self._redact_public_url_match, cleaned)
+        cleaned = _CREDENTIAL_RE.sub(self._redact_credential_match, cleaned)
+        return cleaned
+
+    def _redact_public_url_match(self, match):
+        raw = str(match.group(0) or "").strip()
+        parsed = urlparse(raw)
+        host = str(parsed.hostname or "").strip()
+        scheme = str(parsed.scheme or "").strip().lower()
+        if scheme in ("http", "https") and host:
+            if parsed.port:
+                host = "%s:%s" % (host, parsed.port)
+            return "%s://%s/%s" % (scheme, host, _URL_REDACTION)
+        return _URL_REDACTION
+
+    def _redact_credential_match(self, match):
+        return "%s=[redacted]" % match.group("key")
+
+    def _persist(self, job):
+        saver = getattr(self._helpers(), "_save_replacement_job", None)
+        if callable(saver):
+            saver(job)
+
+    def _job_duration(self, job, analysis):
+        meta = (analysis or {}).get("meta") or {}
+        for candidate in (
+                meta.get("duration"),
+                job.get("duration"),
+                job.get("sourceDurationSec")):
+            try:
+                value = float(candidate or 0)
+            except (TypeError, ValueError):
+                value = 0.0
+            if value > 0:
+                return value
+        source_path = str(job.get("sourceVideoPath") or "").strip()
+        if source_path:
+            try:
+                value = float((self._call("_probe_video", source_path) or {}).get("duration") or 0)
+            except (TypeError, ValueError):
+                value = 0.0
+            if value > 0:
+                return value
+        return 8.0
+
+    def _job_out_dir(self):
+        data_dir = self._call("data_dir")
+        return os.path.join(data_dir, "video_replacements", uuid.uuid4().hex)
+
+    def _helpers(self):
+        if self.helpers is not None:
+            return self.helpers
+        import matrix_native_client as default_helpers
+        self.helpers = default_helpers
+        return self.helpers
+
+    def _call(self, name, *args, **kwargs):
+        helper = getattr(self._helpers(), name)
+        return helper(*args, **kwargs)
+
+    def _now(self):
+        runtime = self.runtime
+        if runtime is None:
+            runtime = getattr(self._helpers(), "time", time)
+        if callable(runtime):
+            return float(runtime())
+        if hasattr(runtime, "time") and callable(runtime.time):
+            return float(runtime.time())
+        return time.time()
diff --git a/docs/superpowers/plans/2026-08-04-video-replacement-service-task-3-report.md b/docs/superpowers/plans/2026-08-04-video-replacement-service-task-3-report.md
new file mode 100644
index 0000000..2caefa4
--- /dev/null
+++ b/docs/superpowers/plans/2026-08-04-video-replacement-service-task-3-report.md
@@ -0,0 +1,168 @@
+# 2026-08-04 Task 3 Report - hybrid_v2 pipeline extraction
+
+## Scope
+- Task base: `8d0a468`
+- Tier: native client / local replacement pipeline
+- Goal: finish Task 3 from the existing working tree, keep prior Task 3 extraction work, and fix the focused `tests.test_video_replacement_v2` loader failure without touching unrelated dirty changes.
+
+## Root cause
+- `backend/matrix_native_client.py` created `HybridReplacementPipeline` with `helpers=sys.modules[__name__]`.
+- `tests.test_video_replacement_v2` loads `matrix_native_client.py` through `importlib.util.module_from_spec(...)` under the temporary name `matrix_native_client_for_replacement_v2` without inserting that name into `sys.modules`.
+- `_replacement_hybrid_pipeline()` and `_replacement_public_job()` therefore raised `KeyError` during `_build_job()` and preflight-failure cleanup.
+
+## Fix
+- Kept the existing Task 3 extraction intact.
+- Replaced the direct `sys.modules[__name__]` lookup with a live `_ReplacementHelperProxy(globals())` adapter so helper resolution still tracks the active module namespace, including test-time monkeypatches, without requiring the temporary loader name to exist in `sys.modules`.
+- Checked the surrounding Task 3 helper path and found no second `sys.modules[__name__]` usage in the hybrid pipeline bridge.
+
+## Changed files
+- `backend/replacement_pipeline.py`
+- `backend/matrix_native_client.py`
+- `tests/test_replacement_service.py`
+- `tests/test_video_replacement.py`
+- `tests/test_video_replacement_v2.py`
+- `docs/superpowers/plans/2026-08-04-video-replacement-service-task-3-report.md`
+
+## Verification
+
+### Focused repro before fix
+```text
+.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2 -q
+
+FAILED (errors=2)
+- KeyError: 'matrix_native_client_for_replacement_v2'
+- failing sites: _replacement_hybrid_pipeline(), _replacement_public_job()
+```
+
+### Focused suite after fix
+```text
+.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2 -q
+
+----------------------------------------------------------------------
+Ran 269 tests in 13.279s
+
+OK
+```
+
+### Required verification commands
+```text
+.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_replacement tests.test_video_replacement_v2 -q
+
+----------------------------------------------------------------------
+Ran 385 tests in 11.623s
+
+OK
+```
+
+```text
+.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_pipeline.py backend\matrix_native_client.py tests\test_replacement_service.py
+
+[exit 0]
+```
+
+```text
+git diff --check
+
+[exit 0]
+note: only LF->CRLF working-tree warnings were emitted for unrelated existing dirty files; no diff-check errors were reported.
+```
+
+## Operational impact
+- Restart/deploy required: none performed in this task.
+- OpenAPI / database / Docker / migration impact: none.
+- Rollback path: revert the Task 3 commit `refactor: extract hybrid replacement pipeline`.
+
+## Remaining risk
+- Verification is source-level only; no native client restart or real LK888 / remote AI Canvas smoke was performed in this task.
+
+## Fix Follow-up
+
+### Review findings addressed
+- Added `sourceSegmentPath` and `sourceSegmentUploadPath` to the hybrid pipeline private scrub list so public job/progress payloads do not expose absolute local segment paths.
+- Updated `HybridReplacementPipeline.execute()` to return the canceled job when segment execution raises the known cancel signal, instead of bubbling that path into the caller's generic failure handler.
+- Added focused regressions for public payload scrubbing and execute-time cancellation.
+
+### Focused regression output
+```text
+.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_pipeline_public_payloads_hide_internal_segment_paths tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_pipeline_execute_returns_canceled_job_after_segment_cancellation -v
+test_hybrid_pipeline_public_payloads_hide_internal_segment_paths (tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_pipeline_public_payloads_hide_internal_segment_paths) ... ok
+test_hybrid_pipeline_execute_returns_canceled_job_after_segment_cancellation (tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_pipeline_execute_returns_canceled_job_after_segment_cancellation) ... ok
+
+----------------------------------------------------------------------
+Ran 2 tests in 0.229s
+
+OK
+```
+
+### Required verification output
+```text
+.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_replacement tests.test_video_replacement_v2 -q
+======================================================================
+FAIL: test_keyframe_references_migrate_existing_central_library_urls_in_memory (tests.test_video_replacement_v2.VideoReplacementV2Test.test_keyframe_references_migrate_existing_central_library_urls_in_memory)
+----------------------------------------------------------------------
+Traceback (most recent call last):
+  File "E:\Desktop\�����ǽ�_Ӧ��ǰ��������ķ�Դ��_clean_20260710_150252\tests\test_video_replacement_v2.py", line 1620, in test_keyframe_references_migrate_existing_central_library_urls_in_memory
+    self.assertEqual(len(refs), 3)
+AssertionError: 0 != 3
+
+----------------------------------------------------------------------
+Ran 387 tests in 10.081s
+
+FAILED (failures=1)
+```
+
+```text
+.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_pipeline.py backend\matrix_native_client.py tests\test_replacement_service.py
+```
+
+```text
+git diff --check
+warning: in the working copy of 'CHANGELOG.md', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'backend/.env.example', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'backend/api_server.py', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'backend/build_matrix_agent.ps1', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'backend/installer/MatrixShipAgent.iss', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'backend/matrix_native_client.py', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'backend/platform_features.py', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'backend/replacement_pipeline.py', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'docs/API_REFERENCE.md', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'docs/ARCHITECTURE.md', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'docs/DEPLOYMENT.md', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'docs/IMPLEMENTATION.md', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'docs/TROUBLESHOOTING.md', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'docs/openapi.yaml', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'docs/superpowers/plans/2026-08-04-video-replacement-service-task-3-report.md', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'migration.sql', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'tests/test_login_centered_layout.py', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'tests/test_minimax_aicanvas_remote.py', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'tests/test_native_enterprise_invite.py', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'tests/test_video_breakdown.py', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'tests/test_video_replacement_v2.py', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'tests/test_web_surface_removed.py', LF will be replaced by CRLF the next time Git touches it
+warning: in the working copy of 'tools/aicanvas_remote/server_current.py', LF will be replaced by CRLF the next time Git touches it
+```
+
+## Cancellation Event Follow-up
+
+- Changed the cancellation terminal event to emit `_replacement_public_job(job)` while keeping the persisted internal job unchanged.
+- Added `test_cancel_completion_event_uses_public_job_without_internal_paths` to verify that local paths remain available internally but are absent from `video_replace_done`.
+
+```text
+.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_cancel_completion_event_uses_public_job_without_internal_paths tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_pipeline_public_payloads_hide_internal_segment_paths tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_pipeline_execute_returns_canceled_job_after_segment_cancellation -v
+
+----------------------------------------------------------------------
+Ran 3 tests in 0.430s
+
+OK
+```
+
+```text
+$env:MATRIX_CENTRAL='http://127.0.0.1:9080'; .\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_replacement tests.test_video_replacement_v2 -q
+
+----------------------------------------------------------------------
+Ran 388 tests in 11.665s
+
+OK
+```
+
+The explicit `MATRIX_CENTRAL` value isolates Task 3 from an unrelated dirty working-tree change that points the client default at the remote central service; the legacy migration test uses `127.0.0.1:9080` as its fixture origin.
diff --git a/tests/test_replacement_service.py b/tests/test_replacement_service.py
index c741a33..8f55bba 100644
--- a/tests/test_replacement_service.py
+++ b/tests/test_replacement_service.py
@@ -4,20 +4,21 @@ import os
 from pathlib import Path
 import sys
 import tempfile
 import unittest
 
 
 ROOT = Path(__file__).resolve().parents[1]
 BACKEND = ROOT / "backend"
 SERVICE_PATH = BACKEND / "replacement_service.py"
 ANALYSIS_PATH = BACKEND / "replacement_analysis.py"
+PIPELINE_PATH = BACKEND / "replacement_pipeline.py"
 
 if str(BACKEND) not in sys.path:
     sys.path.insert(0, str(BACKEND))
 
 
 def load_replacement_service_module():
     if not SERVICE_PATH.is_file():
         raise AssertionError("replacement_service.py is missing")
     spec = importlib.util.spec_from_file_location(
         "replacement_service_for_test",
@@ -33,20 +34,32 @@ def load_replacement_analysis_module():
         raise AssertionError("replacement_analysis.py is missing")
     spec = importlib.util.spec_from_file_location(
         "replacement_analysis_for_test",
         ANALYSIS_PATH,
     )
     module = importlib.util.module_from_spec(spec)
     spec.loader.exec_module(module)
     return module
 
 
+def load_replacement_pipeline_module():
+    if not PIPELINE_PATH.is_file():
+        raise AssertionError("replacement_pipeline.py is missing")
+    spec = importlib.util.spec_from_file_location(
+        "replacement_pipeline_for_test",
+        PIPELINE_PATH,
+    )
+    module = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(module)
+    return module
+
+
 class FakeSourceResolver:
     def prepare(self, job, request, progress=None):
         job["sourceVideoPath"] = os.path.join(job["outDir"], "source.mp4")
         Path(job["sourceVideoPath"]).write_bytes(b"fake-video")
         job["breakdownAnalysis"] = {"meta": {"duration": 8.0}}
         return job
 
 
 class FakePipeline:
     def __init__(self):
@@ -64,20 +77,30 @@ class FakePipeline:
         segment.update({"status": "done", "videoPath": output, "qcStatus": "passed"})
         job["status"] = "awaiting_review"
         return job
 
     def concat(self, job):
         output = os.path.join(job["outDir"], "final.mp4")
         Path(output).write_bytes(b"fake-final")
         job.update({"status": "completed", "outputPath": output})
         return job
 
+    def retry(self, job, segment_indices, progress=None):
+        selected = set(segment_indices or [])
+        for segment in job.get("segments") or []:
+            if segment.get("index") in selected:
+                output = os.path.join(job["outDir"], "segment-%02d-retry.mp4" % int(segment["index"]))
+                Path(output).write_bytes(b"fake-retry")
+                segment.update({"status": "done", "videoPath": output, "qcStatus": "passed"})
+        job["status"] = "awaiting_review"
+        return job
+
 
 class FailingPipeline(FakePipeline):
     def execute(self, job, selected_segments=None, progress=None):
         raise RuntimeError("fake provider failed")
 
 
 class SensitiveFailingPipeline(FakePipeline):
     def execute(self, job, selected_segments=None, progress=None):
         raise RuntimeError(
             "fake provider failed: out_dir=%s source=%s token=secret-token"
diff --git a/tests/test_video_replacement.py b/tests/test_video_replacement.py
index 6fd3ba2..4cf6818 100644
--- a/tests/test_video_replacement.py
+++ b/tests/test_video_replacement.py
@@ -1165,26 +1165,42 @@ class VideoReplacementHelpersTest(unittest.TestCase):
     def test_comic_retry_entries_use_video_only_runner_and_keep_legacy_runner(self):
         src = CLIENT.read_text(encoding="utf-8")
         retry_block = src[
             src.index("    def retry_failed_segments(self):"):
             src.index("    def regenerate_comic_frame", src.index("    def retry_failed_segments(self):"))
         ]
         regenerate_block = src[
             src.index("    def regenerate_selected_segment(self):"):
             src.index("    def cancel_generation", src.index("    def regenerate_selected_segment(self):"))
         ]
+        build_block = src[
+            src.index("    def _build_job(self):"):
+            src.index("    def start_generation", src.index("    def _build_job(self):"))
+        ]
+        run_block = src[
+            src.index("    def _run_job_segments(self, job, selected_segments):"):
+            src.index("    def _run_comic_project_segments", src.index("    def _run_job_segments(self, job, selected_segments):"))
+        ]
+        concat_block = src[
+            src.index("    def confirm_and_concat(self):"):
+            src.index("    def retry_failed_segments", src.index("    def confirm_and_concat(self):"))
+        ]
 
         self.assertIn('status") in ("failed", "download_failed")', retry_block)
         self.assertIn("_comic_segments_ready_for_video_retry", retry_block)
         self.assertIn("_run_comic_video_regeneration", retry_block)
         self.assertIn("allow_pending_recovery=True", retry_block)
-        self.assertIn("_run_job_segments", retry_block)
+        self.assertIn("HybridReplacementPipeline", src)
+        self.assertIn(".build_plan(", build_block)
+        self.assertIn(".execute(", run_block)
+        self.assertIn(".retry(", retry_block)
+        self.assertIn(".concat(", concat_block)
         self.assertIn("_sync_segment_scripts_from_table", regenerate_block)
         self.assertIn('QMessageBox.question(', regenerate_block)
         self.assertIn('"重新生成视频"', regenerate_block)
         self.assertIn("_run_comic_video_regeneration", regenerate_block)
         self.assertIn("_run_job_segments", regenerate_block)
         self.assertIn(
             'retry_statuses = ("failed", "download_failed") if '
             '_replacement_job_mode(self._job) == "comic_project" else ("failed",)',
             src,
         )
diff --git a/tests/test_video_replacement_v2.py b/tests/test_video_replacement_v2.py
index c46bc30..2c6b134 100644
--- a/tests/test_video_replacement_v2.py
+++ b/tests/test_video_replacement_v2.py
@@ -8,20 +8,21 @@ import subprocess
 import shutil
 import sys
 import tempfile
 import types
 import unittest
 from unittest import mock
 
 
 ROOT = Path(__file__).resolve().parents[1]
 CLIENT = ROOT / "backend" / "matrix_native_client.py"
+PIPELINE = ROOT / "backend" / "replacement_pipeline.py"
 
 
 class _DummyQtMeta(type):
     def __getattr__(cls, _name):
         return 0
 
 
 class _DummyQtObject(metaclass=_DummyQtMeta):
     def __init__(self, *args, **kwargs):
         self._value = ""
@@ -225,20 +226,27 @@ def load_client():
         try:
             from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
         except Exception:
             install_qt_stubs()
     spec = importlib.util.spec_from_file_location("matrix_native_client_for_replacement_v2", CLIENT)
     mod = importlib.util.module_from_spec(spec)
     spec.loader.exec_module(mod)
     return mod
 
 
+def load_replacement_pipeline():
+    spec = importlib.util.spec_from_file_location("replacement_pipeline_for_video_replacement", PIPELINE)
+    mod = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(mod)
+    return mod
+
+
 def fake_qt_multimedia_backend():
     from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
 
     multimedia = types.ModuleType("PySide6.QtMultimedia")
     multimedia_widgets = types.ModuleType("PySide6.QtMultimediaWidgets")
 
     class FakeQMediaPlayer:
         instances = []
 
         class Loops:
@@ -347,20 +355,21 @@ def mean_volume_db(client, path):
         check=False,
     )
     match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", completed.stderr or "")
     return float(match.group(1)) if match else float("-inf")
 
 
 class VideoReplacementV2Test(unittest.TestCase):
     @classmethod
     def setUpClass(cls):
         cls.client = load_client()
+        cls.pipeline_module = load_replacement_pipeline()
 
     def test_mix_clips_preserves_non_silent_audio_when_requested(self):
         with tempfile.TemporaryDirectory() as td:
             first = Path(td) / "first.mp4"
             second = Path(td) / "second.mp4"
             output = Path(td) / "output.mp4"
             make_tone_video(self.client, first, frequency=440)
             make_tone_video(self.client, second, frequency=880)
 
             self.client.mix_clips(
@@ -1163,20 +1172,442 @@ class VideoReplacementV2Test(unittest.TestCase):
             },
         }
 
         plan = self.client._build_hybrid_replacement_plan(
             analysis, 12.0, segment_seconds=8, strict_script_audio=True)
 
         self.assertEqual(plan[0]["segmentType"], "non_talking")
         self.assertEqual(plan[0]["script"], "strict spoken script")
         self.assertEqual(plan[1]["segmentType"], "non_talking")
 
+    def test_hybrid_pipeline_build_plan_preserves_source_entities_and_scripts(self):
+        with tempfile.TemporaryDirectory() as td:
+            analysis = {
+                "meta": {"duration": 12.0},
+                "transcript": {
+                    "segments": [{"startSec": 1.0, "endSec": 5.0, "text": "strict spoken script"}],
+                },
+                "report": "人物：门店销售，产品：汽车，场景：展厅",
+            }
+            job = {
+                "id": "job-plan",
+                "outDir": td,
+                "sourceVideoPath": str(Path(td) / "source.mp4"),
+                "breakdownAnalysis": analysis,
+                "productNotes": "uploaded product reference images: product.png",
+                "modelNotes": "authorized model face",
+                "audioMode": "tts",
+                "strictScriptAudio": True,
+                "noPersonMode": False,
+                "pipeline": "hybrid_v2",
+            }
+
+            pipeline = self.pipeline_module.HybridReplacementPipeline(helpers=self.client)
+            planned = pipeline.build_plan(job)
+
+        self.assertEqual(planned["pipeline"], "hybrid_v2")
+        self.assertEqual(planned["sourceReplacementEntities"], self.client._replacement_source_entities_from_analysis(analysis))
+        self.assertEqual(planned["segments"][0]["script"], "strict spoken script")
+        self.assertEqual(planned["segments"][0]["segmentType"], "talking")
+
+    def test_hybrid_pipeline_execute_keeps_successful_fake_segments_done_and_passed(self):
+        with tempfile.TemporaryDirectory() as td:
+            output = Path(td) / "segment-01.mp4"
+            saved = []
+            progress_events = []
+            job = {
+                "id": "job-success",
+                "outDir": td,
+                "pipeline": "hybrid_v2",
+                "sourceVideoPath": str(Path(td) / "source.mp4"),
+                "segments": [{
+                    "index": 1,
+                    "start": 0.0,
+                    "end": 8.0,
+                    "duration": 8.0,
+                    "status": "planned",
+                    "audioStatus": "pending",
+                    "qcStatus": "pending",
+                    "script": "新的产品口播",
+                    "prompt": "stable presenter",
+                }],
+            }
+            pipeline = self.pipeline_module.HybridReplacementPipeline(helpers=self.client)
+
+            def fake_save(value):
+                saved.append(json.loads(json.dumps(value, ensure_ascii=False)))
+
+            def fake_stage(job_value, segment, stage="", **_kwargs):
+                return {
+                    "stage": stage or str((segment or {}).get("status") or ""),
+                    "stageLabel": stage or str((segment or {}).get("status") or ""),
+                    "segmentElapsedSec": 0,
+                    "segmentEtaSec": 0,
+                }
+
+            def fake_runner(_job, segment):
+                output.write_bytes(b"segment")
+                segment.update({
+                    "status": "done",
+                    "audioStatus": "passed",
+                    "qcStatus": "passed",
+                    "videoPath": str(output),
+                    "providerTaskId": "task-seg-1",
+                })
+                return {"ok": True, "segment": segment, "path": str(output)}
+
+            with mock.patch.object(self.client, "_save_replacement_job", side_effect=fake_save), \
+                    mock.patch.object(self.client, "_replacement_timing_snapshot", side_effect=fake_stage), \
+                    mock.patch.object(self.client, "_run_hybrid_replacement_segment", side_effect=fake_runner):
+                result = pipeline.execute(
+                    job,
+                    selected_segments=job["segments"],
+                    progress=lambda job_id, stage, message, segment_index, segments: progress_events.append({
+                        "jobId": job_id,
+                        "stage": stage,
+                        "message": message,
+                        "segmentIndex": segment_index,
+                        "segments": segments,
+                    }),
+                )
+
+        self.assertEqual(result["status"], "awaiting_review")
+        self.assertEqual(result["segments"][0]["status"], "done")
+        self.assertEqual(result["segments"][0]["qcStatus"], "passed")
+        self.assertEqual(result["segments"][0]["providerTaskId"], "task-seg-1")
+        self.assertTrue(any(event["stage"] == "awaiting_review" for event in progress_events))
+        self.assertGreaterEqual(len(saved), 2)
+
+    def test_hybrid_pipeline_public_payloads_hide_internal_segment_paths(self):
+        with tempfile.TemporaryDirectory() as td:
+            source_segment = Path(td) / "source-segment.mp4"
+            source_segment_safe = Path(td) / "source-segment.subtitle-safe.mp4"
+            segment_video = Path(td) / "segment-01.mp4"
+            for path in (source_segment, source_segment_safe, segment_video):
+                path.write_bytes(b"segment")
+            job = {
+                "id": "job-public",
+                "outDir": td,
+                "pipeline": "hybrid_v2",
+                "sourceVideoPath": str(Path(td) / "source.mp4"),
+                "segments": [{
+                    "index": 1,
+                    "start": 0.0,
+                    "end": 8.0,
+                    "duration": 8.0,
+                    "status": "done",
+                    "audioStatus": "passed",
+                    "qcStatus": "passed",
+                    "videoPath": str(segment_video),
+                    "sourceSegmentPath": str(source_segment),
+                    "sourceSegmentUploadPath": str(source_segment_safe),
+                    "script": "稳定片段",
+                }],
+            }
+            pipeline = self.pipeline_module.HybridReplacementPipeline(helpers=self.client)
+
+            public_job = pipeline.public_job(job)
+            public_segments = pipeline.public_segments(job)
+
+        public_dump = json.dumps(public_job, ensure_ascii=False)
+        segments_dump = json.dumps(public_segments, ensure_ascii=False)
+        self.assertNotIn("sourceSegmentPath", public_dump)
+        self.assertNotIn("sourceSegmentUploadPath", public_dump)
+        self.assertNotIn(str(source_segment), public_dump)
+        self.assertNotIn(str(source_segment_safe), public_dump)
+        self.assertNotIn("sourceSegmentPath", segments_dump)
+        self.assertNotIn("sourceSegmentUploadPath", segments_dump)
+        self.assertNotIn(str(source_segment), segments_dump)
+        self.assertNotIn(str(source_segment_safe), segments_dump)
+
+    def test_hybrid_pipeline_execute_marks_partial_and_never_promotes_invalid_media_to_review(self):
+        with tempfile.TemporaryDirectory() as td:
+            saved = []
+            job = {
+                "id": "job-invalid",
+                "outDir": td,
+                "pipeline": "hybrid_v2",
+                "sourceVideoPath": str(Path(td) / "source.mp4"),
+                "segments": [
+                    {
+                        "index": 1,
+                        "start": 0.0,
+                        "end": 8.0,
+                        "duration": 8.0,
+                        "status": "planned",
+                        "audioStatus": "pending",
+                        "qcStatus": "pending",
+                        "script": "第一段",
+                    },
+                    {
+                        "index": 2,
+                        "start": 8.0,
+                        "end": 16.0,
+                        "duration": 8.0,
+                        "status": "planned",
+                        "audioStatus": "pending",
+                        "qcStatus": "pending",
+                        "script": "第二段",
+                    },
+                ],
+            }
+            pipeline = self.pipeline_module.HybridReplacementPipeline(helpers=self.client)
+
+            def fake_save(value):
+                saved.append(json.loads(json.dumps(value, ensure_ascii=False)))
+
+            def fake_stage(job_value, segment, stage="", **_kwargs):
+                return {
+                    "stage": stage or str((segment or {}).get("status") or ""),
+                    "stageLabel": stage or str((segment or {}).get("status") or ""),
+                    "segmentElapsedSec": 0,
+                    "segmentEtaSec": 0,
+                }
+
+            def fake_runner(_job, segment):
+                if segment["index"] == 1:
+                    segment.update({
+                        "status": "done",
+                        "audioStatus": "passed",
+                        "qcStatus": "passed",
+                        "videoPath": str(Path(td) / "segment-01.mp4"),
+                    })
+                    Path(segment["videoPath"]).write_bytes(b"segment")
+                    return {"ok": True, "segment": segment, "path": segment["videoPath"]}
+                segment.update({
+                    "status": "failed",
+                    "audioStatus": "failed",
+                    "qcStatus": "failed",
+                    "error": "segment_invalid:download_html_body",
+                    "errorId": "err-invalid-seg-2",
+                })
+                return {
+                    "ok": False,
+                    "segment": segment,
+                    "error": segment["error"],
+                    "errorId": segment["errorId"],
+                }
+
+            with mock.patch.object(self.client, "_save_replacement_job", side_effect=fake_save), \
+                    mock.patch.object(self.client, "_replacement_timing_snapshot", side_effect=fake_stage), \
+                    mock.patch.object(self.client, "_run_hybrid_replacement_segment", side_effect=fake_runner):
+                result = pipeline.execute(job, selected_segments=job["segments"])
+
+        self.assertEqual(result["status"], "partial")
+        self.assertEqual(result["segments"][0]["status"], "done")
+        self.assertEqual(result["segments"][1]["status"], "failed")
+        self.assertNotEqual(result["status"], "awaiting_review")
+        self.assertTrue(any(item["status"] == "partial" for item in saved))
+
+    def test_hybrid_pipeline_execute_returns_canceled_job_after_segment_cancellation(self):
+        with tempfile.TemporaryDirectory() as td:
+            saved = []
+            job = {
+                "id": "job-cancel",
+                "outDir": td,
+                "pipeline": "hybrid_v2",
+                "sourceVideoPath": str(Path(td) / "source.mp4"),
+                "segments": [{
+                    "index": 1,
+                    "start": 0.0,
+                    "end": 8.0,
+                    "duration": 8.0,
+                    "status": "planned",
+                    "audioStatus": "pending",
+                    "qcStatus": "pending",
+                    "script": "取消段",
+                }],
+            }
+            pipeline = self.pipeline_module.HybridReplacementPipeline(helpers=self.client)
+
+            def fake_save(value):
+                saved.append(json.loads(json.dumps(value, ensure_ascii=False)))
+
+            def fake_stage(job_value, segment, stage="", **_kwargs):
+                return {
+                    "stage": stage or str((segment or {}).get("status") or ""),
+                    "stageLabel": stage or str((segment or {}).get("status") or ""),
+                    "segmentElapsedSec": 0,
+                    "segmentEtaSec": 0,
+                }
+
+            def fake_runner(_job, _segment):
+                raise RuntimeError("lk888_task_cancelled")
+
+            with mock.patch.object(self.client, "_save_replacement_job", side_effect=fake_save), \
+                    mock.patch.object(self.client, "_replacement_timing_snapshot", side_effect=fake_stage), \
+                    mock.patch.object(self.client, "_run_hybrid_replacement_segment", side_effect=fake_runner):
+                result = pipeline.execute(job, selected_segments=job["segments"])
+
+        self.assertEqual(result["status"], "canceled")
+        self.assertEqual(result["segments"][0]["status"], "cancel_requested")
+        self.assertTrue(any(item["status"] == "canceled" for item in saved))
+
+    def test_cancel_completion_event_uses_public_job_without_internal_paths(self):
+        with tempfile.TemporaryDirectory() as td:
+            root = Path(td)
+            internal_paths = [
+                str(root),
+                str(root / "source.mp4"),
+                str(root / "output.mp4"),
+                str(root / "segment-01.mp4"),
+                str(root / "source-segment-01.mp4"),
+                str(root / "uploaded-source-segment-01.mp4"),
+            ]
+            job = {
+                "id": "job-cancel-public-event",
+                "status": "cancel_requested",
+                "outDir": internal_paths[0],
+                "sourceVideoPath": internal_paths[1],
+                "outputPath": internal_paths[2],
+                "segments": [{
+                    "index": 1,
+                    "status": "cancel_requested",
+                    "videoPath": internal_paths[3],
+                    "sourceSegmentPath": internal_paths[4],
+                    "sourceSegmentUploadPath": internal_paths[5],
+                    "diagnostics": {"detail": "canceled at " + internal_paths[4]},
+                }],
+            }
+            saved = []
+            emitted = []
+            bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
+                emit=lambda tag, payload: emitted.append((tag, payload))
+            ))
+
+            with mock.patch.object(
+                    self.client,
+                    "_cleanup_replacement_sensitive_materials",
+                    return_value={"ok": True, "deleted": [], "failed": []},
+                ), mock.patch.object(
+                    self.client,
+                    "_cleanup_replacement_temporary_materials",
+                    return_value={"ok": True, "deleted": [], "failed": []},
+                ), mock.patch.object(
+                    self.client,
+                    "_save_replacement_job",
+                    side_effect=lambda value: saved.append(json.loads(json.dumps(value, ensure_ascii=False))),
+                ), mock.patch.object(self.client, "BRIDGE", bridge):
+                result = self.client._mark_replacement_job_canceled(job)
+
+        self.assertIs(result, job)
+        self.assertEqual(result["status"], "canceled")
+        self.assertEqual(saved[-1]["sourceVideoPath"], internal_paths[1])
+        self.assertEqual(saved[-1]["segments"][0]["sourceSegmentPath"], internal_paths[4])
+        self.assertEqual(emitted[-1][0], "video_replace_done")
+        public_payload = json.dumps(emitted[-1][1], ensure_ascii=False)
+        for private_key in (
+                "outDir", "sourceVideoPath", "outputPath", "videoPath",
+                "sourceSegmentPath", "sourceSegmentUploadPath",
+            ):
+            self.assertNotIn(private_key, public_payload)
+        for internal_path in internal_paths:
+            self.assertNotIn(internal_path, public_payload)
+
+    def test_hybrid_pipeline_retry_only_replays_requested_failed_segment(self):
+        with tempfile.TemporaryDirectory() as td:
+            saved = []
+            progress_events = []
+            segment_one = {
+                "index": 1,
+                "start": 0.0,
+                "end": 8.0,
+                "duration": 8.0,
+                "status": "done",
+                "audioStatus": "passed",
+                "qcStatus": "passed",
+                "videoPath": str(Path(td) / "segment-01.mp4"),
+                "script": "保留成功片段",
+            }
+            Path(segment_one["videoPath"]).write_bytes(b"ok")
+            segment_two = {
+                "index": 2,
+                "start": 8.0,
+                "end": 16.0,
+                "duration": 8.0,
+                "status": "failed",
+                "audioStatus": "failed",
+                "qcStatus": "failed",
+                "error": "provider submit failed",
+                "errorId": "err-seg-2",
+                "script": "失败片段 A",
+            }
+            segment_three = {
+                "index": 3,
+                "start": 16.0,
+                "end": 24.0,
+                "duration": 8.0,
+                "status": "failed",
+                "audioStatus": "failed",
+                "qcStatus": "failed",
+                "error": "provider submit failed",
+                "errorId": "err-seg-3",
+                "script": "失败片段 B",
+            }
+            job = {
+                "id": "job-retry",
+                "outDir": td,
+                "pipeline": "hybrid_v2",
+                "sourceVideoPath": str(Path(td) / "source.mp4"),
+                "segments": [segment_one, segment_two, segment_three],
+            }
+            pipeline = self.pipeline_module.HybridReplacementPipeline(helpers=self.client)
+
+            def fake_save(value):
+                saved.append(json.loads(json.dumps(value, ensure_ascii=False)))
+
+            def fake_stage(job_value, segment, stage="", **_kwargs):
+                return {
+                    "stage": stage or str((segment or {}).get("status") or ""),
+                    "stageLabel": stage or str((segment or {}).get("status") or ""),
+                    "segmentElapsedSec": 0,
+                    "segmentEtaSec": 0,
+                }
+
+            def fake_runner(_job, segment):
+                if segment["index"] != 3:
+                    raise AssertionError("retry should only rerun the requested failed segment")
+                output = Path(td) / "segment-03-retry.mp4"
+                output.write_bytes(b"retry")
+                segment.update({
+                    "status": "done",
+                    "audioStatus": "passed",
+                    "qcStatus": "passed",
+                    "videoPath": str(output),
+                    "providerTaskId": "task-seg-3-retry",
+                })
+                return {"ok": True, "segment": segment, "path": str(output)}
+
+            with mock.patch.object(self.client, "_save_replacement_job", side_effect=fake_save), \
+                    mock.patch.object(self.client, "_replacement_timing_snapshot", side_effect=fake_stage), \
+                    mock.patch.object(self.client, "_run_hybrid_replacement_segment", side_effect=fake_runner):
+                result = pipeline.retry(
+                    job,
+                    segment_indices=[3],
+                    progress=lambda job_id, stage, message, segment_index, segments: progress_events.append({
+                        "jobId": job_id,
+                        "stage": stage,
+                        "message": message,
+                        "segmentIndex": segment_index,
+                        "segments": segments,
+                    }),
+                )
+
+        self.assertEqual(result["status"], "partial")
+        self.assertEqual(result["segments"][0]["status"], "done")
+        self.assertEqual(result["segments"][1]["status"], "failed")
+        self.assertEqual(result["segments"][2]["status"], "done")
+        self.assertEqual(result["segments"][2]["qcStatus"], "passed")
+        self.assertEqual(result["segments"][2]["providerTaskId"], "task-seg-3-retry")
+        self.assertEqual(job["lastRetryPreparation"]["segments"], [{"index": 3, "demotedCodes": []}])
+        self.assertTrue(any(event["segmentIndex"] == 3 for event in progress_events))
+
     def test_talking_segment_reuses_existing_tts_and_kling_digital_human(self):
         segment = {"index": 1, "segmentType": "talking", "script": "新的产品口播", "keyframeUrl": "https://x/key.png"}
         job = {"voiceId": "Zephyr", "digitalHumanMode": "std", "sceneImageUrl": "https://x/scene.png"}
         with mock.patch.object(self.client, "lk888_tts_voice", return_value="https://x/voice.mp3") as tts, \
                 mock.patch.object(self.client, "lk888_digital_human", return_value="https://x/talking.mp4") as human:
             url = self.client._run_hybrid_talking_segment(job, segment)
 
         self.assertEqual(url, "https://x/talking.mp4")
         self.assertEqual(segment["ttsUrl"], "https://x/voice.mp3")
         tts.assert_called_once()
