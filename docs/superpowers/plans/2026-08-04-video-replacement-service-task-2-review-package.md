# Review package: c2f0ef7ee2895ae9e1869db41396637ac8e8966e..8d0a468a927b9597b402b66a4f86194b930a912a

## Commits
8d0a468 fix: tighten replacement source redaction
6e7920f refactor: extract replacement video analysis service

## Files changed
 backend/matrix_native_client.py   | 188 +++-------------
 backend/replacement_analysis.py   | 438 +++++++++++++++++++++++++++++++++++++-
 backend/replacement_service.py    |  49 +++++
 tests/test_replacement_service.py | 328 ++++++++++++++++++++++++++++
 tests/test_video_breakdown.py     |  45 ++++
 5 files changed, 890 insertions(+), 158 deletions(-)

## Diff
diff --git a/backend/matrix_native_client.py b/backend/matrix_native_client.py
index 18fcd3d..743509d 100644
--- a/backend/matrix_native_client.py
+++ b/backend/matrix_native_client.py
@@ -17864,185 +17864,61 @@ def _workflow_normalize_reference_breakdown_text(text):
                 break
         blocks.append(
             "镜头 %s｜%s｜%s\n画面：%s\n台词：%s\n节奏：%s。\n可借鉴点：%s" % (
                 shot_no, title, duration, picture, dialogue, rhythm.rstrip("。"), selling
             )
         )
     return "\n\n".join(blocks)
 
 
 def _workflow_analyze_reference_video(video_path, item=None, topic="", out_dir=None, progress=None):
-    """Run the same evidence-backed analysis used by the video breakdown page."""
+    """Compatibility wrapper that delegates workflow analysis to the pure service layer."""
+    from replacement_analysis import ReplacementAnalysis
+
     item = item if isinstance(item, dict) else {}
-    video_path = str(video_path or "").strip()
     source_url = str(
         item.get("note_url") or item.get("work_url") or item.get("url") or ""
     ).strip()
     platform = str(item.get("platform") or "").strip()
-    tmp_root = out_dir or os.path.join(data_dir(), "video_breakdowns", "workflow-" + uuid.uuid4().hex)
-    os.makedirs(tmp_root, exist_ok=True)
-    out = {
-        "platform": platform,
-        "sourceUrl": source_url,
-        "videoPath": video_path,
-    }
-
-    def notify(message):
-        if callable(progress):
-            progress(str(message or ""))
 
-    def diagnostic(message):
-        return {
-            "status": "failed",
-            "code": "workflow_reference_analysis_failed",
-            "text": "",
-            "segments": [],
-            "failedRanges": [],
-            "errors": [],
-            "message": str(message or "")[:240],
-        }
-
-    _workflow_assistant_log(
-        "reference_analysis_started",
-        video=os.path.basename(video_path),
-        topic=topic,
-    )
-    try:
-        notify("校验参考视频…")
-        validation = _breakdown_source_validation(video_path)
-        out["validation"] = validation
-        if not validation.get("ok"):
-            out["meta"] = validation
-            out["ocr"] = {
-                "status": "skipped",
-                "engine": "none",
-                "text": "",
-                "errors": [],
-                "message": "视频真实性校验未通过。",
-            }
-            out["transcript"] = diagnostic("视频真实性校验未通过。")
-            out["report"] = (
-                "## 分解失败\n"
-                "源视频未通过真实性校验，未把不可验证内容交给同款替换。\n\n"
-                "- code: %s" % (validation.get("code") or "media_invalid")
-            )
-            return {
-                "analysis": out,
-                "markdown": _video_breakdown_markdown(out),
-                "message": "参考视频分析失败（视频文件无效）",
-            }
-
-        meta = {
-            "duration": validation.get("duration") or 0,
-            "width": validation.get("width") or 0,
-            "height": validation.get("height") or 0,
-            "path": video_path,
-        }
-        out["meta"] = meta
-        notify("抽取整条视频关键帧…")
-        frames = _extract_breakdown_frames(video_path, os.path.join(tmp_root, "frames"), 16)
-        frame_notes = "\n".join(
-            "[%.2fs] %s" % (f.get("time") or 0, os.path.basename(f.get("path") or ""))
-            for f in frames
-        ) or "未抽取到关键帧"
-        out["frameNotes"] = frame_notes
-
-        notify("识别画面字幕…")
-        out["ocr"] = _ocr_breakdown_frames(frames)
-
-        notify("分片转写整条视频口播…")
-        out["transcript"] = _transcribe_breakdown_audio(
-            video_path,
-            out_dir=os.path.join(tmp_root, "audio"),
-            progress=lambda index, total, start, end, state: notify(
-                "音频转写 %d/%d（%.0f-%.0fs，%s）" % (
+    def transcription_runner(source_path, analysis_out_dir, progress=None):
+        def on_chunk(index, total, start, end, state):
+            if callable(progress):
+                progress("音频转写 %d/%d（%.0f-%.0fs，%s）" % (
                     index + 1, total, start, end, state
-                )
-            ),
-        )
-        out["transcript"].setdefault("retryCount", 0)
-
-        notify("调用视觉模型分析关键帧…")
-        frame_urls = [_image_data_url(f.get("path")) for f in frames[:16]]
-        frame_urls = [url for url in frame_urls if url]
-        if frame_urls:
-            try:
-                out["visual"] = lk888_vision(
-                    "请逐帧深度描述这些短视频关键帧，严格按时间顺序提取人物外观、构图、景别、"
-                    "动作、产品/道具、场景、字幕和镜头节奏；不要臆造关键帧中看不到的内容。",
-                    frame_urls,
-                    max_tokens=2200,
-                    billing_scenario="video_breakdown",
-                    billing_stage="visual_analysis",
-                    billing_detail="workflow assistant key frame visual analysis",
-                )
-            except Exception as exc:
-                raw = json_log(
-                    _CLIENT_JSON_LOGGER,
-                    "workflow_reference_vision_failed",
-                    exc=exc,
-                    code="workflow_reference_vision_failed",
-                    video_path=video_path,
-                )
-                import json as _json
-                error_id = (_json.loads(raw) or {}).get("errorId")
-                out["visual"] = (
-                    "视觉模型分析失败（errorId: %s）: %s\n%s"
-                    % (error_id or "-", str(exc)[:160], frame_notes)
-                )
-        else:
-            out["visual"] = "未抽取到可供视觉模型分析的关键帧。"
+                ))
 
-        notify("生成完整拆解报告…")
-        report, message = _generate_video_breakdown_report(out)
-        out["report"] = report
-        markdown = _video_breakdown_markdown(out)
-        _workflow_assistant_log(
-            "reference_analysis_completed",
-            video=os.path.basename(video_path),
-            duration=meta.get("duration") or 0,
-            transcript_status=(out.get("transcript") or {}).get("status") or "",
-            transcript_segments=len((out.get("transcript") or {}).get("segments") or []),
-            transcript_failed_ranges=len((out.get("transcript") or {}).get("failedRanges") or []),
-            report_chars=len(report or ""),
+        return _transcribe_breakdown_audio(
+            source_path,
+            out_dir=analysis_out_dir,
+            progress=on_chunk,
         )
-        return {"analysis": out, "markdown": markdown, "message": message or "分析完成"}
-    except Exception as exc:
-        raw = json_log(
-            _CLIENT_JSON_LOGGER,
-            "workflow_reference_analysis_failed",
-            exc=exc,
-            code="workflow_reference_analysis_failed",
-            video_path=video_path,
-        )
-        import json as _json
-        error_id = (_json.loads(raw) or {}).get("errorId")
-        out["meta"] = out.get("meta") or {}
-        out["ocr"] = out.get("ocr") or {
-            "status": "failed",
-            "engine": "none",
-            "text": "",
-            "errors": [],
-            "message": str(exc)[:160],
-        }
-        out["transcript"] = out.get("transcript") or diagnostic(str(exc))
-        out["report"] = "## 分解失败\nerrorId: %s\n\n%s" % (
-            error_id or "-", str(exc)[:500]
-        )
-        return {
-            "analysis": out,
-            "markdown": _video_breakdown_markdown(out),
-            "message": "参考视频分析失败（错误编号 %s）" % (error_id or "-"),
-        }
-    finally:
-        if out_dir is None:
-            shutil.rmtree(tmp_root, ignore_errors=True)
+
+    analysis = ReplacementAnalysis(
+        source_validator=_breakdown_source_validation,
+        frame_extractor=_extract_breakdown_frames,
+        ocr_runner=_ocr_breakdown_frames,
+        transcription_runner=transcription_runner,
+        vision_runner=lk888_vision,
+        report_builder=_generate_video_breakdown_report,
+        markdown_builder=_video_breakdown_markdown,
+        image_data_url=_image_data_url,
+        json_logger=lambda event, **fields: json_log(_CLIENT_JSON_LOGGER, event, **fields),
+        log_event=lambda event, **fields: _workflow_assistant_log(event, topic=topic, **fields),
+    )
+    return analysis.analyze(
+        video_path,
+        source_url=source_url,
+        platform=platform,
+        out_dir=out_dir or "",
+        progress=progress,
+    )
 
 
 def _workflow_save_reference_analysis_artifact(ctx, video_path, analysis):
     if not isinstance(analysis, dict):
         return ""
     import json as _json
     topic = ctx.get("topic") or ctx.get("wfname") or "采集参考视频"
     base = "%s_%s_%s" % (
         time.strftime("%Y%m%d_%H%M%S"),
         _workflow_filename_part(topic),
diff --git a/backend/replacement_analysis.py b/backend/replacement_analysis.py
index ce396b9..b97b79e 100644
--- a/backend/replacement_analysis.py
+++ b/backend/replacement_analysis.py
@@ -1,3 +1,437 @@
+import copy
+import hashlib
+import json
+import os
+import shutil
+import time
+import uuid
+from urllib.parse import urlparse
+
+
+def _path_hash(value):
+    raw = str(value or "").strip()
+    if not raw:
+        return ""
+    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
+
+
+def _safe_url_parts(value):
+    raw = str(value or "").strip()
+    if not raw:
+        return {}
+    parsed = urlparse(raw)
+    if parsed.scheme not in ("http", "https") or not parsed.hostname:
+        return {}
+    host = parsed.hostname or ""
+    if parsed.port:
+        host = "%s:%s" % (host, parsed.port)
+    return {
+        "scheme": parsed.scheme,
+        "host": host,
+        "pathHash": _path_hash(parsed.path or "/"),
+    }
+
+
+def _analysis_duration(analysis):
+    meta = analysis.get("meta") if isinstance(analysis, dict) else {}
+    try:
+        return float((meta or {}).get("duration") or 0)
+    except (TypeError, ValueError):
+        return 0.0
+
+
+def _path_within_dir(path, root):
+    raw_path = os.path.abspath(str(path or "").strip())
+    raw_root = os.path.abspath(str(root or "").strip())
+    if not (raw_path and raw_root):
+        return False
+    try:
+        return os.path.commonpath([raw_path, raw_root]) == raw_root
+    except ValueError:
+        return False
+
+
 class ReplacementAnalysis:
-    def analyze(self, job, request=None, progress=None):
-        return job
+    def __init__(
+            self,
+            downloader=None,
+            download_validator=None,
+            platform_from_url=None,
+            source_validator=None,
+            frame_extractor=None,
+            ocr_runner=None,
+            transcription_runner=None,
+            vision_runner=None,
+            report_builder=None,
+            markdown_builder=None,
+            image_data_url=None,
+            json_logger=None,
+            log_event=None,
+            work_root=None):
+        self.downloader = downloader
+        self.download_validator = download_validator or (lambda _path: {"ok": True})
+        self.platform_from_url = platform_from_url or (lambda _url: "")
+        self.source_validator = source_validator or (lambda _path: {"ok": True})
+        self.frame_extractor = frame_extractor or (lambda _video_path, _frames_dir, _limit: [])
+        self.ocr_runner = ocr_runner or (lambda _frames: {
+            "status": "disabled",
+            "engine": "none",
+            "text": "",
+            "errors": [],
+        })
+        self.transcription_runner = transcription_runner or (lambda _video_path, out_dir, progress=None: {
+            "status": "disabled",
+            "text": "",
+            "segments": [],
+            "failedRanges": [],
+            "errors": [],
+            "retryCount": 0,
+            "outDir": out_dir,
+        })
+        self.vision_runner = vision_runner or (lambda _prompt, _frame_urls, **_kwargs: "")
+        self.report_builder = report_builder or (lambda out: (out.get("report") or "", "分析完成"))
+        self.markdown_builder = markdown_builder or (lambda out: out.get("report") or "")
+        self.image_data_url = image_data_url or (lambda _path: "")
+        self.json_logger = json_logger or (lambda *_args, **_kwargs: '{"errorId":"-"}')
+        self.log_event = log_event or (lambda *_args, **_kwargs: None)
+        self.work_root = work_root or self._default_work_root
+
+    def resolve_source(self, request, job_dir, progress=None):
+        request = request if isinstance(request, dict) else {}
+        job_dir = os.path.abspath(str(job_dir or ""))
+        os.makedirs(job_dir, exist_ok=True)
+
+        handoff = request.get("handoff") if isinstance(request.get("handoff"), dict) else None
+        if handoff is None and request.get("sourceVideoPath"):
+            handoff = request
+        if self._valid_handoff_video(handoff):
+            return self._resolved_payload(
+                source_url=handoff.get("sourceUrl") or handoff.get("url") or "",
+                platform=handoff.get("platform") or "",
+                source_video_path=handoff.get("sourceVideoPath") or "",
+                analysis=handoff.get("breakdownAnalysis") or {},
+                handoff_id=handoff.get("handoffId") or handoff.get("id") or "",
+            )
+
+        source_url = str(request.get("sourceUrl") or "").strip()
+        if not source_url:
+            raise ValueError("replacement_source_required")
+        if self.downloader is None or not hasattr(self.downloader, "download"):
+            raise RuntimeError("replacement_source_downloader_missing")
+
+        platform = str(self.platform_from_url(source_url) or request.get("platform") or "").strip()
+        source_video_path = os.path.abspath(self.downloader.download(source_url, job_dir))
+        if not _path_within_dir(source_video_path, job_dir):
+            analysis = self._source_rejection_analysis(
+                source_video_path,
+                source_url,
+                platform,
+                "replacement_source_outside_job_dir",
+                "downloaded source escaped job dir",
+            )
+            return self._failed_payload(source_url, platform, source_video_path, analysis)
+        validation = copy.deepcopy(self.download_validator(source_video_path) or {})
+        if not validation.get("ok"):
+            self._cleanup_invalid_source(source_video_path, job_dir)
+            analysis = self._invalid_analysis(
+                source_video_path,
+                source_url,
+                platform,
+                validation,
+                "参考视频分析失败（视频文件无效）",
+            )
+            return self._failed_payload(source_url, platform, source_video_path, analysis)
+
+        result = self.analyze(
+            source_video_path,
+            source_url=source_url,
+            platform=platform,
+            out_dir=os.path.join(job_dir, "analysis"),
+            progress=progress,
+        )
+        analysis = copy.deepcopy((result or {}).get("analysis") or {})
+        analysis_validation = analysis.get("validation") if isinstance(analysis.get("validation"), dict) else {}
+        if analysis_validation.get("ok") is False:
+            return self._failed_payload(source_url, platform, source_video_path, analysis)
+        return self._resolved_payload(
+            source_url=source_url,
+            platform=platform,
+            source_video_path=source_video_path,
+            analysis=analysis,
+            message=(result or {}).get("message") or "",
+        )
+
+    def analyze(self, video_path, source_url="", platform="", out_dir="", progress=None):
+        video_path = os.path.abspath(str(video_path or "").strip())
+        source_url = str(source_url or "").strip()
+        platform = str(platform or "").strip()
+        out = {
+            "platform": platform,
+            "sourceUrl": source_url,
+            "videoPath": video_path,
+        }
+        tmp_root = os.path.abspath(out_dir or self.work_root())
+        os.makedirs(tmp_root, exist_ok=True)
+
+        def notify(message):
+            if callable(progress):
+                progress(str(message or ""))
+
+        self.log_event(
+            "reference_analysis_started",
+            video=os.path.basename(video_path),
+            source_url=source_url,
+            platform=platform,
+        )
+        try:
+            notify("校验参考视频…")
+            validation = copy.deepcopy(self.source_validator(video_path) or {})
+            out["validation"] = validation
+            if not validation.get("ok"):
+                failed = self._invalid_analysis(
+                    video_path,
+                    source_url,
+                    platform,
+                    validation,
+                    "参考视频分析失败（视频文件无效）",
+                )
+                return {
+                    "analysis": failed,
+                    "markdown": self.markdown_builder(failed),
+                    "message": "参考视频分析失败（视频文件无效）",
+                }
+
+            out["meta"] = {
+                "duration": validation.get("duration") or 0,
+                "width": validation.get("width") or 0,
+                "height": validation.get("height") or 0,
+                "path": video_path,
+            }
+            notify("抽取整条视频关键帧…")
+            frames = self.frame_extractor(video_path, os.path.join(tmp_root, "frames"), 16) or []
+            out["frameNotes"] = "\n".join(
+                "[%.2fs] %s" % (frame.get("time") or 0, os.path.basename(frame.get("path") or ""))
+                for frame in frames
+            ) or "未抽取到关键帧"
+
+            notify("识别画面字幕…")
+            out["ocr"] = copy.deepcopy(self.ocr_runner(frames) or {})
+
+            notify("分片转写整条视频口播…")
+            out["transcript"] = copy.deepcopy(self.transcription_runner(
+                video_path,
+                os.path.join(tmp_root, "audio"),
+                progress=progress,
+            ) or {})
+            out["transcript"].setdefault("retryCount", 0)
+
+            notify("调用视觉模型分析关键帧…")
+            frame_urls = [self.image_data_url(frame.get("path")) for frame in frames[:16]]
+            frame_urls = [url for url in frame_urls if url]
+            if frame_urls:
+                try:
+                    out["visual"] = self.vision_runner(
+                        "请逐帧深度描述这些短视频关键帧，严格按时间顺序提取人物外观、构图、景别、动作、产品/道具、场景、字幕和镜头节奏；不要臆造关键帧中看不到的内容。",
+                        frame_urls,
+                        max_tokens=2200,
+                        billing_scenario="video_breakdown",
+                        billing_stage="visual_analysis",
+                        billing_detail="workflow assistant key frame visual analysis",
+                    )
+                except Exception as exc:
+                    error_id = self._log_error(
+                        "workflow_reference_vision_failed",
+                        exc=exc,
+                        code="workflow_reference_vision_failed",
+                        video_path=video_path,
+                    )
+                    out["visual"] = "视觉模型分析失败（errorId: %s）: %s\n%s" % (
+                        error_id or "-",
+                        str(exc)[:160],
+                        out.get("frameNotes") or "",
+                    )
+            else:
+                out["visual"] = "未抽取到可供视觉模型分析的关键帧。"
+
+            notify("生成完整拆解报告…")
+            report, message = self.report_builder(out)
+            out["report"] = report
+            markdown = self.markdown_builder(out)
+            self.log_event(
+                "reference_analysis_completed",
+                video=os.path.basename(video_path),
+                duration=(out.get("meta") or {}).get("duration") or 0,
+                transcript_status=(out.get("transcript") or {}).get("status") or "",
+                transcript_segments=len((out.get("transcript") or {}).get("segments") or []),
+                report_chars=len(report or ""),
+            )
+            return {
+                "analysis": out,
+                "markdown": markdown,
+                "message": message or "分析完成",
+            }
+        except Exception as exc:
+            error_id = self._log_error(
+                "workflow_reference_analysis_failed",
+                exc=exc,
+                code="workflow_reference_analysis_failed",
+                video_path=video_path,
+            )
+            out["meta"] = out.get("meta") or {}
+            out["ocr"] = out.get("ocr") or {
+                "status": "failed",
+                "engine": "none",
+                "text": "",
+                "errors": [],
+                "message": str(exc)[:160],
+            }
+            out["transcript"] = out.get("transcript") or self._diagnostic_transcript(str(exc))
+            out["report"] = "## 分解失败\nerrorId: %s\n\n%s" % (error_id or "-", str(exc)[:500])
+            return {
+                "analysis": out,
+                "markdown": self.markdown_builder(out),
+                "message": "参考视频分析失败（错误编号 %s）" % (error_id or "-"),
+            }
+        finally:
+            if not out_dir:
+                shutil.rmtree(tmp_root, ignore_errors=True)
+
+    def _valid_handoff_video(self, handoff):
+        if not isinstance(handoff, dict):
+            return False
+        source_video_path = str(handoff.get("sourceVideoPath") or "").strip()
+        return bool(source_video_path and os.path.isfile(source_video_path))
+
+    def _invalid_analysis(self, video_path, source_url, platform, validation, message):
+        validation = copy.deepcopy(validation or {})
+        return {
+            "platform": str(platform or "").strip(),
+            "sourceUrl": str(source_url or "").strip(),
+            "videoPath": os.path.abspath(str(video_path or "").strip()),
+            "validation": validation,
+            "meta": validation,
+            "ocr": {
+                "status": "skipped",
+                "engine": "none",
+                "text": "",
+                "errors": [],
+                "message": "视频真实性校验未通过。",
+            },
+            "transcript": self._diagnostic_transcript("视频真实性校验未通过。"),
+            "visual": "",
+            "report": (
+                "## 分解失败\n"
+                "源视频未通过真实性校验，未把不可验证内容交给同款替换。\n\n"
+                "- code: %s"
+            ) % (validation.get("code") or "media_invalid"),
+            "error": validation.get("code") or "media_invalid",
+            "message": str(message or "")[:160],
+        }
+
+    def _diagnostic_transcript(self, message):
+        return {
+            "status": "failed",
+            "code": "workflow_reference_analysis_failed",
+            "text": "",
+            "segments": [],
+            "failedRanges": [],
+            "errors": [],
+            "message": str(message or "")[:240],
+        }
+
+    def _source_rejection_analysis(self, video_path, source_url, platform, code, message):
+        validation = {
+            "ok": False,
+            "code": str(code or "replacement_source_rejected"),
+            "path": os.path.abspath(str(video_path or "").strip()),
+            "duration": 0.0,
+            "width": 0,
+            "height": 0,
+        }
+        return {
+            "platform": str(platform or "").strip(),
+            "sourceUrl": str(source_url or "").strip(),
+            "videoPath": validation["path"],
+            "validation": validation,
+            "meta": validation,
+            "ocr": {
+                "status": "skipped",
+                "engine": "none",
+                "text": "",
+                "errors": [],
+                "message": str(message or "")[:160],
+            },
+            "transcript": self._diagnostic_transcript(message),
+            "visual": "",
+            "report": "## Source Rejected\n- code: %s" % validation["code"],
+            "error": validation["code"],
+            "message": str(message or "")[:160],
+        }
+
+    def _resolved_payload(self, source_url, platform, source_video_path, analysis, handoff_id="", message=""):
+        source_url = str(source_url or "").strip()
+        platform = str(platform or "").strip()
+        source_video_path = os.path.abspath(str(source_video_path or "").strip())
+        analysis = copy.deepcopy(analysis or {})
+        return {
+            "status": "ok",
+            "error": "",
+            "message": str(message or ""),
+            "handoffId": str(handoff_id or "").strip(),
+            "platform": platform,
+            "sourceUrl": source_url,
+            "source": _safe_url_parts(source_url),
+            "sourceVideoPath": source_video_path,
+            "breakdownAnalysis": analysis,
+            "sourceContext": {
+                "handoffId": str(handoff_id or "").strip(),
+                "platform": platform,
+                "duration": _analysis_duration(analysis),
+                "hasBreakdownAnalysis": bool(analysis),
+                "sourceVideoAvailable": bool(source_video_path and os.path.isfile(source_video_path)),
+                "sourceVideoPathHash": _path_hash(source_video_path),
+            },
+        }
+
+    def _failed_payload(self, source_url, platform, source_video_path, analysis):
+        resolved = self._resolved_payload(
+            source_url=source_url,
+            platform=platform,
+            source_video_path=source_video_path,
+            analysis=analysis,
+            message=(analysis or {}).get("message") or "",
+        )
+        resolved["status"] = "failed"
+        resolved["error"] = (
+            ((analysis or {}).get("validation") or {}).get("code")
+            or (analysis or {}).get("error")
+            or "media_invalid"
+        )
+        resolved["sourceContext"]["sourceVideoAvailable"] = False
+        return resolved
+
+    def _cleanup_invalid_source(self, source_video_path, job_dir):
+        source_video_path = os.path.abspath(str(source_video_path or "").strip())
+        job_dir = os.path.abspath(str(job_dir or "").strip())
+        if not (source_video_path and job_dir):
+            return
+        if source_video_path != job_dir and not source_video_path.startswith(job_dir + os.sep):
+            return
+        if os.path.isfile(source_video_path):
+            try:
+                os.remove(source_video_path)
+            except OSError:
+                pass
+
+    def _log_error(self, event, **fields):
+        raw = self.json_logger(event, **fields)
+        try:
+            payload = json.loads(raw or "{}")
+        except Exception:
+            payload = {}
+        return str(payload.get("errorId") or "-")
+
+    def _default_work_root(self):
+        return os.path.abspath(
+            os.path.join(os.getcwd(), "output", "replacement-analysis-" + uuid.uuid4().hex)
+        )
diff --git a/backend/replacement_service.py b/backend/replacement_service.py
index 1ea7d46..1b9aa9d 100644
--- a/backend/replacement_service.py
+++ b/backend/replacement_service.py
@@ -1,38 +1,75 @@
 import copy
 import json
 import os
 import re
 import time
+from urllib.parse import urlparse
 
 
 _JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
 _INTERNAL_PATH_KEYS = {"outDir", "sourceVideoPath", "videoPath", "outputPath"}
 _TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
 _PATH_REDACTION = "[redacted-path]"
+_URL_REDACTION = "[redacted-url]"
 _CREDENTIAL_RE = re.compile(
     r"(?i)\b(?P<key>authorization|bearer|token|cookie|password)\b"
     r"(?:\s*[:=]\s*|\s+)(?P<value>[^\s,;]+)"
 )
+_HTTP_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
+
+
+class SourceResolver:
+    def __init__(self, analysis):
+        self.analysis = analysis
+
+    def prepare(self, job, request, progress=None):
+        job = job if isinstance(job, dict) else {}
+        request = request if isinstance(request, dict) else {}
+        resolved = self.analysis.resolve_source(
+            request,
+            job.get("outDir") or "",
+            progress=progress,
+        )
+        if not isinstance(resolved, dict):
+            raise RuntimeError("replacement_source_resolution_invalid")
+        for key in (
+                "handoffId",
+                "platform",
+                "sourceUrl",
+                "source",
+                "sourceVideoPath",
+                "sourceContext",
+                "breakdownAnalysis",
+                "message"):
+            if key in resolved:
+                job[key] = copy.deepcopy(resolved.get(key))
+        if resolved.get("status") == "failed":
+            job["status"] = "failed"
+            job["error"] = str(resolved.get("error") or "media_invalid")
+        return job
 
 
 class ReplacementService:
     def __init__(self, data_dir, source_resolver, pipeline, runtime=None):
         self.data_dir = os.path.abspath(data_dir)
         self.source_resolver = source_resolver
         self.pipeline = pipeline
         self.runtime = runtime
 
     def prepare(self, job_id, request, files, progress=None):
         job = self._create_job(job_id, request, files)
         self._write_job(job)
         job = self.source_resolver.prepare(job, request, progress=progress)
+        if job.get("status") == "failed":
+            self._write_job(job)
+            return self._public_job(job)
         job = self.pipeline.build_plan(job)
         job["status"] = "planned"
         self._write_job(job)
         return self._public_job(job)
 
     def execute(self, job_id, overrides=None, progress=None):
         job = self._load_job(job_id)
         if not job or job.get("status") != "planned":
             raise ValueError("replacement_job_not_planned")
         self._apply_overrides(job, overrides or {})
@@ -140,22 +177,34 @@ class ReplacementService:
         if isinstance(value, list):
             return [self._scrub_value(item, sensitive_strings) for item in value]
         if isinstance(value, str):
             return self._scrub_string(value, sensitive_strings)
         return value
 
     def _scrub_string(self, value, sensitive_strings):
         cleaned = str(value)
         for item in sensitive_strings:
             cleaned = cleaned.replace(item, _PATH_REDACTION)
+        cleaned = _HTTP_URL_RE.sub(self._redact_public_url_match, cleaned)
         return _CREDENTIAL_RE.sub(self._redact_credential_match, cleaned)
 
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
     def _redact_credential_match(self, match):
         return "%s=[redacted]" % match.group("key")
 
     def _public_sensitive_strings(self, job):
         sensitive = set(self._path_variants(self.data_dir))
         self._collect_sensitive_strings(job, sensitive)
         return sorted(
             (item for item in sensitive if item),
             key=len,
             reverse=True,
diff --git a/tests/test_replacement_service.py b/tests/test_replacement_service.py
index 845089f..c741a33 100644
--- a/tests/test_replacement_service.py
+++ b/tests/test_replacement_service.py
@@ -3,47 +3,64 @@ import json
 import os
 from pathlib import Path
 import sys
 import tempfile
 import unittest
 
 
 ROOT = Path(__file__).resolve().parents[1]
 BACKEND = ROOT / "backend"
 SERVICE_PATH = BACKEND / "replacement_service.py"
+ANALYSIS_PATH = BACKEND / "replacement_analysis.py"
 
 if str(BACKEND) not in sys.path:
     sys.path.insert(0, str(BACKEND))
 
 
 def load_replacement_service_module():
     if not SERVICE_PATH.is_file():
         raise AssertionError("replacement_service.py is missing")
     spec = importlib.util.spec_from_file_location(
         "replacement_service_for_test",
         SERVICE_PATH,
     )
     module = importlib.util.module_from_spec(spec)
     spec.loader.exec_module(module)
     return module
 
 
+def load_replacement_analysis_module():
+    if not ANALYSIS_PATH.is_file():
+        raise AssertionError("replacement_analysis.py is missing")
+    spec = importlib.util.spec_from_file_location(
+        "replacement_analysis_for_test",
+        ANALYSIS_PATH,
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
+    def __init__(self):
+        self.build_plan_calls = 0
+
     def build_plan(self, job):
+        self.build_plan_calls += 1
         job["segments"] = [{"index": 1, "start": 0.0, "end": 8.0, "status": "planned"}]
         return job
 
     def execute(self, job, selected_segments=None, progress=None):
         segment = job["segments"][0]
         output = os.path.join(job["outDir"], "segment-01.mp4")
         Path(output).write_bytes(b"fake-output")
         segment.update({"status": "done", "videoPath": output, "qcStatus": "passed"})
         job["status"] = "awaiting_review"
         return job
@@ -61,32 +78,137 @@ class FailingPipeline(FakePipeline):
 
 
 class SensitiveFailingPipeline(FakePipeline):
     def execute(self, job, selected_segments=None, progress=None):
         raise RuntimeError(
             "fake provider failed: out_dir=%s source=%s token=secret-token"
             % (job["outDir"], job["sourceVideoPath"])
         )
 
 
+class FakeDownloader:
+    def __init__(self, filename="downloaded.mp4", payload=b"fake-video"):
+        self.filename = filename
+        self.payload = payload
+        self.calls = []
+
+    def download(self, source_url, job_dir):
+        self.calls.append((source_url, job_dir))
+        path = os.path.join(job_dir, self.filename)
+        Path(path).write_bytes(self.payload)
+        return path
+
+
+class OutsideJobDirDownloader(FakeDownloader):
+    def download(self, source_url, job_dir):
+        self.calls.append((source_url, job_dir))
+        path = Path(job_dir).parent / self.filename
+        path.write_bytes(self.payload)
+        return str(path)
+
+
+class FakeVisionRunner:
+    def __init__(self):
+        self.calls = []
+
+    def __call__(self, prompt, frame_urls, **kwargs):
+        self.calls.append({
+            "prompt": prompt,
+            "frameUrls": list(frame_urls),
+            "kwargs": dict(kwargs),
+        })
+        return "fake visual summary"
+
+
 class ReplacementServiceContractTests(unittest.TestCase):
     def setUp(self):
         self.module = load_replacement_service_module()
+        self.analysis_module = load_replacement_analysis_module()
         self.ReplacementService = self.module.ReplacementService
+        self.SourceResolver = self.module.SourceResolver
+        self.ReplacementAnalysis = self.analysis_module.ReplacementAnalysis
 
     def _service(self, data_dir, pipeline=None):
         return self.ReplacementService(
             data_dir=data_dir,
             source_resolver=FakeSourceResolver(),
             pipeline=pipeline or FakePipeline(),
         )
 
+    def _replacement_analysis(
+            self,
+            downloader=None,
+            download_validation=None,
+            source_validation=None,
+            frame_times=None):
+        frame_times = list(frame_times or [1.0])
+        vision = FakeVisionRunner()
+
+        def extract_frames(_video_path, frames_dir, _limit):
+            os.makedirs(frames_dir, exist_ok=True)
+            frames = []
+            for index, stamp in enumerate(frame_times, 1):
+                frame_path = Path(frames_dir) / ("frame-%02d.jpg" % index)
+                frame_path.write_bytes(b"fake-frame")
+                frames.append({"time": stamp, "path": str(frame_path)})
+            return frames
+
+        return self.ReplacementAnalysis(
+            downloader=downloader or FakeDownloader(),
+            download_validator=(download_validation or (lambda path: {
+                "ok": True,
+                "code": "",
+                "path": path,
+                "duration": 8.0,
+                "width": 720,
+                "height": 1280,
+            })),
+            platform_from_url=lambda url: "xhs" if "xiaohongshu" in str(url) else "douyin",
+            source_validator=(source_validation or (lambda path: {
+                "ok": True,
+                "code": "",
+                "path": path,
+                "duration": 8.0,
+                "width": 720,
+                "height": 1280,
+            })),
+            frame_extractor=extract_frames,
+            ocr_runner=lambda frames: {
+                "status": "ok",
+                "engine": "fake-ocr",
+                "text": "字幕 %d" % len(frames),
+                "errors": [],
+            },
+            transcription_runner=lambda _video_path, out_dir, progress=None: {
+                "status": "ok",
+                "text": "口播测试",
+                "segments": [{"start": 0.0, "end": 1.0, "text": "口播测试"}],
+                "failedRanges": [],
+                "errors": [],
+                "retryCount": 0,
+                "outDir": out_dir,
+            },
+            vision_runner=vision,
+            report_builder=lambda out: (
+                "## 报告\n来源:%s\n时长:%s"
+                % (out.get("platform") or "-", (out.get("meta") or {}).get("duration") or 0),
+                "分析完成",
+            ),
+            markdown_builder=lambda out: (
+                "# 分解\n%s\n%s"
+                % (out.get("sourceUrl") or "", out.get("videoPath") or "")
+            ),
+            image_data_url=lambda path: "data:image/jpeg;base64,%s" % os.path.basename(path),
+            json_logger=lambda *_args, **_kwargs: '{"errorId":"err-analysis-test"}',
+            log_event=lambda *_args, **_kwargs: None,
+        )
+
     def test_prepare_execute_concat_persists_internal_paths_and_returns_public_job(self):
         with tempfile.TemporaryDirectory() as td:
             service = self._service(td)
 
             prepared = service.prepare(
                 "job-123",
                 {"sourceUrl": "https://example.test/video.mp4"},
                 [("characterImage", "face.png", b"img")],
             )
             self.assertEqual(prepared["status"], "planned")
@@ -173,13 +295,219 @@ class ReplacementServiceContractTests(unittest.TestCase):
 
     def test_rejects_invalid_job_id_before_path_construction(self):
         with tempfile.TemporaryDirectory() as td:
             service = self._service(td)
 
             with self.assertRaisesRegex(ValueError, "invalid_job_id"):
                 service.prepare("../escape", {"sourceUrl": "https://example.test/video.mp4"}, [])
 
             self.assertEqual(list(Path(td).iterdir()), [])
 
+    def test_prepare_reuses_handoff_source_and_analysis_without_redownloading(self):
+        with tempfile.TemporaryDirectory() as td:
+            handoff_video = Path(td) / "handoff-source.mp4"
+            handoff_video.write_bytes(b"fake-video")
+            analysis = self._replacement_analysis()
+            pipeline = FakePipeline()
+            service = self.ReplacementService(
+                data_dir=td,
+                source_resolver=self.SourceResolver(analysis),
+                pipeline=pipeline,
+            )
+
+            prepared = service.prepare(
+                "job-200",
+                {
+                    "handoff": {
+                        "handoffId": "rwh_1234567890abcdef12345678",
+                        "sourceUrl": "https://www.douyin.com/video/123?token=secret",
+                        "sourceVideoPath": str(handoff_video),
+                        "platform": "douyin",
+                        "breakdownAnalysis": {
+                            "meta": {"duration": 8.0, "width": 1080, "height": 1920},
+                            "transcript": {"segments": [{"start": 0.0, "end": 1.0, "text": "hello"}]},
+                        },
+                    }
+                },
+                [],
+            )
+
+            self.assertEqual(prepared["status"], "planned")
+            self.assertEqual(prepared["source"]["host"], "www.douyin.com")
+            self.assertEqual(prepared["sourceContext"]["platform"], "douyin")
+            self.assertEqual(prepared["sourceContext"]["duration"], 8.0)
+            self.assertTrue(prepared["sourceContext"]["hasBreakdownAnalysis"])
+            self.assertTrue(prepared["sourceContext"]["sourceVideoAvailable"])
+            self.assertNotIn("sourceVideoPath", prepared)
+            self.assertEqual(analysis.downloader.calls, [])
+            self.assertEqual(pipeline.build_plan_calls, 1)
+
+            saved = json.loads((Path(td) / "job-200" / "job.json").read_text(encoding="utf-8"))
+            self.assertEqual(saved["handoffId"], "rwh_1234567890abcdef12345678")
+            self.assertEqual(saved["sourceVideoPath"], str(handoff_video))
+            self.assertEqual(saved["breakdownAnalysis"]["meta"]["duration"], 8.0)
+
+    def test_prepare_downloads_direct_url_into_job_dir_and_analyzes_it(self):
+        with tempfile.TemporaryDirectory() as td:
+            downloader = FakeDownloader(filename="source-direct.mp4")
+            analysis = self._replacement_analysis(downloader=downloader)
+            pipeline = FakePipeline()
+            service = self.ReplacementService(
+                data_dir=td,
+                source_resolver=self.SourceResolver(analysis),
+                pipeline=pipeline,
+            )
+
+            prepared = service.prepare(
+                "job-201",
+                {"sourceUrl": "https://www.douyin.com/video/abc123?token=secret"},
+                [("characterImage", "face.png", b"img")],
+            )
+
+            job_dir = str(Path(td) / "job-201")
+            self.assertEqual(downloader.calls, [
+                ("https://www.douyin.com/video/abc123?token=secret", job_dir)
+            ])
+            self.assertEqual(prepared["status"], "planned")
+            self.assertEqual(prepared["source"]["host"], "www.douyin.com")
+            self.assertEqual(prepared["sourceContext"]["platform"], "douyin")
+            self.assertEqual(prepared["sourceContext"]["duration"], 8.0)
+            self.assertTrue(prepared["sourceContext"]["sourceVideoAvailable"])
+            self.assertIn("sourceVideoPathHash", prepared["sourceContext"])
+            self.assertNotIn(job_dir, json.dumps(prepared, ensure_ascii=False))
+
+            saved = json.loads((Path(td) / "job-201" / "job.json").read_text(encoding="utf-8"))
+            self.assertTrue(saved["sourceVideoPath"].startswith(job_dir))
+            self.assertTrue(saved["sourceVideoPath"].endswith("source-direct.mp4"))
+            self.assertEqual(saved["breakdownAnalysis"]["meta"]["duration"], 8.0)
+            self.assertEqual(saved["breakdownAnalysis"]["ocr"]["engine"], "fake-ocr")
+            self.assertEqual(saved["breakdownAnalysis"]["transcript"]["segments"][0]["text"], "口播测试")
+            self.assertEqual(saved["breakdownAnalysis"]["visual"], "fake visual summary")
+
+    def test_prepare_returns_structured_failed_job_for_invalid_media_without_planning(self):
+        with tempfile.TemporaryDirectory() as td:
+            downloader = FakeDownloader(filename="downloaded-invalid.mp4", payload=b"<html>403</html>")
+            analysis = self._replacement_analysis(
+                downloader=downloader,
+                download_validation=lambda path: {
+                    "ok": False,
+                    "code": "download_html_body",
+                    "path": path,
+                    "size": len(b"<html>403</html>"),
+                    "duration": 0.0,
+                    "width": 0,
+                    "height": 0,
+                },
+            )
+            pipeline = FakePipeline()
+            service = self.ReplacementService(
+                data_dir=td,
+                source_resolver=self.SourceResolver(analysis),
+                pipeline=pipeline,
+            )
+
+            prepared = service.prepare(
+                "job-202",
+                {"sourceUrl": "https://www.douyin.com/video/bad"},
+                [("characterImage", "face.png", b"img")],
+            )
+
+            self.assertEqual(prepared["status"], "failed")
+            self.assertEqual(prepared["error"], "download_html_body")
+            self.assertEqual(prepared["source"]["host"], "www.douyin.com")
+            self.assertEqual(prepared["sourceContext"]["platform"], "douyin")
+            self.assertFalse(prepared["sourceContext"]["sourceVideoAvailable"])
+            self.assertNotEqual(prepared["status"], "completed")
+            self.assertEqual(pipeline.build_plan_calls, 0)
+
+            saved = json.loads((Path(td) / "job-202" / "job.json").read_text(encoding="utf-8"))
+            self.assertEqual(saved["status"], "failed")
+            self.assertEqual(saved["error"], "download_html_body")
+            self.assertEqual(saved["breakdownAnalysis"]["validation"]["code"], "download_html_body")
+            self.assertEqual(saved["breakdownAnalysis"]["report"].splitlines()[0], "## 分解失败")
+            self.assertFalse(Path(saved["sourceVideoPath"]).exists())
+
+
+    def test_prepare_redacts_private_urls_from_public_job_payloads(self):
+        with tempfile.TemporaryDirectory() as td:
+            handoff_video = Path(td) / "handoff-private.mp4"
+            handoff_video.write_bytes(b"fake-video")
+            private_url = "https://private.example/video/abc?sig=secret&token=secret"
+            analysis = self._replacement_analysis()
+            pipeline = FakePipeline()
+            service = self.ReplacementService(
+                data_dir=td,
+                source_resolver=self.SourceResolver(analysis),
+                pipeline=pipeline,
+            )
+
+            prepared = service.prepare(
+                "job-203",
+                {
+                    "sourceUrl": private_url,
+                    "handoff": {
+                        "handoffId": "rwh_aaaaaaaaaaaaaaaaaaaaaaaa",
+                        "sourceUrl": private_url,
+                        "sourceVideoPath": str(handoff_video),
+                        "platform": "douyin",
+                        "breakdownAnalysis": {
+                            "meta": {"duration": 9.0},
+                            "sourceUrl": private_url,
+                            "visual": "source: %s" % private_url,
+                            "report": "## report\nlink: %s" % private_url,
+                        },
+                    },
+                },
+                [],
+            )
+            public_job = service.get_job("job-203")
+            saved = json.loads((Path(td) / "job-203" / "job.json").read_text(encoding="utf-8"))
+            prepared_dump = json.dumps(prepared, ensure_ascii=False)
+            public_dump = json.dumps(public_job, ensure_ascii=False)
+            safe_url = "https://private.example/[redacted-url]"
+
+            self.assertEqual(saved["request"]["sourceUrl"], private_url)
+            self.assertIn(private_url, saved["breakdownAnalysis"]["report"])
+            self.assertNotIn(private_url, prepared_dump)
+            self.assertNotIn(private_url, public_dump)
+            self.assertNotIn("sig=secret", prepared_dump)
+            self.assertNotIn("token=secret", prepared_dump)
+            self.assertNotIn("sig=secret", public_dump)
+            self.assertNotIn("token=secret", public_dump)
+            self.assertIn(safe_url, prepared_dump)
+            self.assertIn(safe_url, public_dump)
+
+    def test_prepare_rejects_direct_download_path_outside_job_dir(self):
+        with tempfile.TemporaryDirectory() as td:
+            downloader = OutsideJobDirDownloader(filename="outside-source.mp4")
+            analysis = self._replacement_analysis(downloader=downloader)
+            pipeline = FakePipeline()
+            service = self.ReplacementService(
+                data_dir=td,
+                source_resolver=self.SourceResolver(analysis),
+                pipeline=pipeline,
+            )
+
+            prepared = service.prepare(
+                "job-204",
+                {"sourceUrl": "https://www.douyin.com/video/outside"},
+                [("characterImage", "face.png", b"img")],
+            )
+
+            self.assertEqual(prepared["status"], "failed")
+            self.assertEqual(prepared["error"], "replacement_source_outside_job_dir")
+            self.assertEqual(prepared["sourceContext"]["platform"], "douyin")
+            self.assertFalse(prepared["sourceContext"]["sourceVideoAvailable"])
+            self.assertEqual(pipeline.build_plan_calls, 0)
+
+            saved = json.loads((Path(td) / "job-204" / "job.json").read_text(encoding="utf-8"))
+            self.assertEqual(saved["status"], "failed")
+            self.assertEqual(saved["error"], "replacement_source_outside_job_dir")
+            self.assertEqual(
+                saved["breakdownAnalysis"]["validation"]["code"],
+                "replacement_source_outside_job_dir",
+            )
+            self.assertFalse(saved["sourceVideoPath"].startswith(str(Path(td) / "job-204")))
+
 
 if __name__ == "__main__":
     unittest.main()
diff --git a/tests/test_video_breakdown.py b/tests/test_video_breakdown.py
index ea4f667..01f9024 100644
--- a/tests/test_video_breakdown.py
+++ b/tests/test_video_breakdown.py
@@ -6,20 +6,21 @@ import subprocess
 import sys
 import tempfile
 import time
 import unittest
 from unittest import mock
 import os
 
 
 ROOT = Path(__file__).resolve().parents[1]
 CLIENT = ROOT / "backend" / "matrix_native_client.py"
+REPLACEMENT_ANALYSIS = ROOT / "backend" / "replacement_analysis.py"
 
 
 def load_client():
     spec = importlib.util.spec_from_file_location("matrix_native_client_for_video_breakdown", CLIENT)
     mod = importlib.util.module_from_spec(spec)
     spec.loader.exec_module(mod)
     return mod
 
 
 class VideoBreakdownHelpersTest(unittest.TestCase):
@@ -1129,13 +1130,57 @@ class VideoBreakdownHelpersTest(unittest.TestCase):
         self.assertNotIn("verify=False", src)
         self.assertNotIn("verify = False", src)
 
     def test_native_ui_serializes_video_breakdown_jobs(self):
         src = CLIENT.read_text(encoding="utf-8")
 
         self.assertIn("self._busy = False", src)
         self.assertIn("if self._busy:", src)
         self.assertIn("self._busy = True", src)
 
+    def test_workflow_reference_analysis_wrapper_delegates_to_replacement_analysis(self):
+        import replacement_analysis as replacement_analysis_module
+
+        expected = {
+            "analysis": {
+                "platform": "douyin",
+                "sourceUrl": "https://example.test/video/123",
+                "videoPath": "E:/tmp/source.mp4",
+                "meta": {"duration": 9.0},
+            },
+            "markdown": "# delegated",
+            "message": "分析完成",
+        }
+
+        with tempfile.TemporaryDirectory() as td, mock.patch.object(
+                replacement_analysis_module.ReplacementAnalysis,
+                "analyze",
+                return_value=expected) as analyze:
+            result = self.client._workflow_analyze_reference_video(
+                "E:/tmp/source.mp4",
+                item={
+                    "url": "https://example.test/video/123",
+                    "platform": "douyin",
+                },
+                topic="测试主题",
+                out_dir=td,
+                progress=mock.Mock(),
+            )
+
+        self.assertEqual(result, expected)
+        analyze.assert_called_once()
+        self.assertEqual(analyze.call_args.args[0], "E:/tmp/source.mp4")
+        self.assertEqual(analyze.call_args.kwargs["source_url"], "https://example.test/video/123")
+        self.assertEqual(analyze.call_args.kwargs["platform"], "douyin")
+        self.assertEqual(analyze.call_args.kwargs["out_dir"], td)
+
+    def test_replacement_analysis_module_stays_qt_free(self):
+        src = REPLACEMENT_ANALYSIS.read_text(encoding="utf-8")
+
+        self.assertIn("class ReplacementAnalysis", src)
+        self.assertNotIn("PySide6", src)
+        self.assertNotIn("QtWidgets", src)
+        self.assertNotIn("QtCore", src)
+
 
 if __name__ == "__main__":
     unittest.main()
