import copy
import os
import re
import time
import uuid
from urllib.parse import urlparse


_PATH_REDACTION = "[redacted-path]"
_URL_REDACTION = "[redacted-url]"
_CREDENTIAL_RE = re.compile(
    r"(?i)\b(?P<key>authorization|bearer|token|cookie|password)\b"
    r"(?:\s*[:=]\s*|\s+)(?P<value>[^\s,;]+)"
)
_HTTP_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
_PRIVATE_KEYS = {
    "outDir",
    "sourceVideoPath",
    "outputPath",
    "videoPath",
    "editedVideoPath",
    "faceSwapPath",
    "sourceFramePath",
    "sourceSegmentPath",
    "sourceSegmentUploadPath",
    "keyframePath",
    "sceneImagePath",
    "startFramePath",
    "endFramePath",
    "replacementAudioPath",
    "personReferencePaths",
    "productSourcePaths",
    "faceSourcePaths",
    "targetFaceReferencePath",
}


class ReplacementPipeline:
    def build_plan(self, job):
        return job

    def execute(self, job, selected_segments=None, progress=None):
        return job

    def retry(self, job, segment_indices, progress=None):
        return job

    def concat(self, job):
        return job


class HybridReplacementPipeline(ReplacementPipeline):
    def __init__(self, helpers=None, runtime=None):
        self.helpers = helpers
        self.runtime = runtime

    def build_plan(self, job):
        job = job if isinstance(job, dict) else {}
        analysis = dict(job.get("breakdownAnalysis") or {})
        duration = self._job_duration(job, analysis)
        out_dir = str(job.get("outDir") or self._job_out_dir()).strip()
        os.makedirs(out_dir, exist_ok=True)
        strict_script_audio = bool(job.get("strictScriptAudio"))
        replacement_mode = self._call("_replacement_job_mode", job)
        segments = copy.deepcopy(job.get("segments") or [])
        if not segments:
            segments = self._call(
                "_build_hybrid_replacement_plan",
                analysis,
                duration,
                segment_seconds=8,
                strict_script_audio=strict_script_audio,
            )
        audio_mode = str(job.get("audioMode") or "auto").strip() or "auto"
        no_person_mode = bool(job.get("noPersonMode"))
        product_notes = str(job.get("productNotes") or "").strip()
        model_notes = str(job.get("modelNotes") or "").strip()
        for segment in segments:
            segment["segmentType"] = (
                "talking"
                if not no_person_mode and self._call(
                    "_replacement_segment_should_talk",
                    segment,
                    audio_mode=audio_mode,
                    strict_script_audio=strict_script_audio,
                )
                else "non_talking"
            )
            segment["prompt"] = self._call(
                "_build_replacement_prompt",
                segment,
                analysis,
                product_notes,
                model_notes,
            )
        if replacement_mode == "comic_project":
            job["principalReplacementMode"] = ""
            segments = self._call("_comic_plan_script_segments", segments, max_speech_sec=15.0)
        job["breakdownAnalysis"] = analysis
        job["duration"] = duration
        job["outDir"] = out_dir
        job["segments"] = segments
        job["pipeline"] = str(job.get("pipeline") or os.getenv("VIDEO_REPLACE_PIPELINE", "hybrid_v2")).strip() or "hybrid_v2"
        job["sourceReplacementEntities"] = copy.deepcopy(
            job.get("sourceReplacementEntities")
            or self._call("_replacement_source_entities_from_analysis", analysis)
        )
        job["startedAt"] = job.get("startedAt") or self._now()
        return job

    def execute(self, job, selected_segments, progress=None):
        job = job if isinstance(job, dict) else {}
        job["startedAt"] = job.get("startedAt") or self._now()
        job["status"] = "running"
        segments = list(job.get("segments") or [])
        total = len(segments)
        chosen = self._resolve_selected_segments(job, selected_segments)
        callbacks = getattr(self._helpers(), "_REPLACEMENT_PROGRESS_CALLBACKS")

        def emit_progress(segment=None, stage="", message="", prompt=None):
            timing = self._call("_replacement_timing_snapshot", job, segment, stage=stage)
            stage_value = timing.get("stage") or stage or str((segment or {}).get("status") or "")
            if segment is not None:
                segment["stage"] = stage_value
                segment["stageLabel"] = timing.get("stageLabel") or self._call("_replacement_stage_label", stage_value)
                segment["elapsedSec"] = timing.get("segmentElapsedSec") or 0
                segment["etaSec"] = timing.get("segmentEtaSec") or 0
            self._persist(job)
            if callable(progress):
                progress(
                    str(job.get("id") or ""),
                    stage_value,
                    message or self._call("_replacement_stage_label", stage_value),
                    (segment or {}).get("index"),
                    self.public_segments(job),
                )

        callbacks[str(job.get("id") or "")] = emit_progress
        try:
            for segment in chosen:
                if self._call("_replacement_cancel_requested", job):
                    self._call("_mark_replacement_job_canceled", job)
                    self._persist(job)
                    return job
                segment["segmentStartedAt"] = self._now()
                segment["segmentEndedAt"] = 0
                segment["elapsedSec"] = 0
                segment["etaSec"] = self._call("_replacement_segment_baseline_sec", segment)
                emit_progress(
                    segment,
                    "editing",
                    "生成片段 %s/%s：准备生成（%.1f-%.1fs）" % (
                        segment.get("index"),
                        total,
                        float(segment.get("start") or 0),
                        float(segment.get("end") or 0),
                    ),
                )
                try:
                    self._run_segment(job, segment)
                except Exception as exc:
                    if self._call("_replacement_cancel_exception", exc) or self._call("_replacement_cancel_requested", job):
                        return job
                    raise
                segment["segmentEndedAt"] = self._now()
                segment["elapsedSec"] = self._call("_replacement_segment_elapsed_sec", segment)
                if segment.get("status") == "done":
                    segment["stage"] = "done"
                    segment["stageLabel"] = self._call("_replacement_stage_label", "done")
                    segment["etaSec"] = 0
                elif segment.get("status") == "failed":
                    segment["etaSec"] = 0
                self._persist(job)
                emit_progress(
                    segment,
                    segment.get("stage") or segment.get("status") or "editing",
                    "片段 %s/%s 状态已更新" % (segment.get("index"), total),
                )
            failed = [item for item in segments if item.get("status") == "failed"]
            if failed:
                job["status"] = "partial"
                job["diagnostics"] = self._call("_replacement_diagnostics_summary", job)
                self._persist(job)
                emit_progress(None, "partial", "有 %d 个片段失败，可点击『重试失败片段』" % len(failed))
                return job
            job["status"] = "awaiting_review"
            self._persist(job)
            emit_progress(None, "awaiting_review", "片段已通过自动检查，请查看首、中、尾帧和试听后确认合成。")
            return job
        finally:
            callbacks.pop(str(job.get("id") or ""), None)

    def retry(self, job, segment_indices, progress=None):
        job = job if isinstance(job, dict) else {}
        wanted = {int(value) for value in (segment_indices or [])}
        failed = [
            segment for segment in (job.get("segments") or [])
            if isinstance(segment, dict)
            and segment.get("status") == "failed"
            and (not wanted or int(segment.get("index") or 0) in wanted)
        ]
        if not failed:
            return job
        failed, retry_normalization = self._call("_normalize_replacement_retry_segments", job, failed)
        retry_summaries = [self._call("_prepare_replacement_segment_for_retry", segment) for segment in failed]
        job["lastRetryPreparation"] = {
            "ts": self._now(),
            "normalization": retry_normalization,
            "segments": [
                {
                    "index": segment.get("index"),
                    "demotedCodes": summary.get("demotedCodes") or [],
                }
                for segment, summary in zip(failed, retry_summaries)
            ],
        }
        self._persist(job)
        return self.execute(job, selected_segments=failed, progress=progress)

    def concat(self, job):
        job = job if isinstance(job, dict) else {}
        block_reasons = self._call("_replacement_final_block_reasons", job.get("segments") or [], job=job)
        if block_reasons:
            raise RuntimeError("replacement_concat_blocked:%s" % "；".join(block_reasons[:3]))
        out_dir = str(job.get("outDir") or self._job_out_dir()).strip()
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, "replacement_final_%s.mp4" % int(self._now()))
        paths = [segment.get("videoPath") for segment in (job.get("segments") or [])]
        final_out = self._call("_prepare_replacement_final_video", job, paths, out)
        asset = self._call("_save_replacement_to_assets", final_out, job)
        if not asset:
            raise RuntimeError("replacement_asset_save_failed")
        job.pop("audioCheck", None)
        job.update({
            "status": "done",
            "outputPath": asset.get("path") or final_out,
            "assetId": asset.get("id") or "",
            "audioValidation": "disabled",
            "reviewStatus": "approved",
        })
        job["sensitiveCleanup"] = self._call("_cleanup_replacement_sensitive_materials", job)
        job["temporaryCleanup"] = self._call("_cleanup_replacement_temporary_materials", job)
        self._persist(job)
        return job

    def public_job(self, job):
        return self._scrub_value(
            copy.deepcopy(job or {}),
            sensitive_strings=self._public_sensitive_strings(job),
        )

    def public_segments(self, job):
        values = self.public_job({"segments": (job or {}).get("segments") or []})
        return values.get("segments") or []

    def _run_segment(self, job, segment):
        runner_name = "_run_hybrid_replacement_segment"
        if str(job.get("pipeline") or "").strip() and str(job.get("pipeline")).strip() != "hybrid_v2":
            runner_name = "_run_replacement_segment"
        try:
            result = self._call(runner_name, job, segment)
            if runner_name == "_run_replacement_segment" and segment.get("status") == "done":
                segment.setdefault("audioStatus", "passed")
                segment.setdefault("qcStatus", "passed")
            if isinstance(result, dict) and not result.get("ok", True):
                self._ensure_segment_failed(job, segment, result.get("error") or "replacement_segment_failed")
            elif segment.get("status") not in ("done", "failed"):
                self._ensure_segment_failed(job, segment, "replacement_segment_incomplete")
        except Exception as exc:
            if self._call("_replacement_cancel_exception", exc) or self._call("_replacement_cancel_requested", job):
                segment.update({
                    "status": "cancel_requested",
                    "stage": "cancel_requested",
                    "stageLabel": "取消中",
                    "etaSec": 0,
                    "error": "",
                    "errorId": "",
                })
                self._call("_mark_replacement_job_canceled", job)
                raise
            self._ensure_segment_failed(job, segment, str(exc) or exc.__class__.__name__, exc=exc)

    def _ensure_segment_failed(self, job, segment, message, exc=None):
        error_text = str(message or "replacement_segment_failed")[:180]
        if not segment.get("errorId"):
            segment["errorId"] = self._call(
                "_replacement_error_id",
                "video_replace_segment_failed",
                exc or RuntimeError(error_text),
                segment_index=segment.get("index"),
                segment_type=segment.get("segmentType") or "unknown",
                source_video=job.get("sourceVideoPath") or "",
            )
        segment["status"] = "failed"
        segment["audioStatus"] = segment.get("audioStatus") if segment.get("audioStatus") == "passed" else "failed"
        segment["qcStatus"] = "failed"
        segment["error"] = error_text

    def _resolve_selected_segments(self, job, selected_segments):
        segments = list(job.get("segments") or [])
        if not selected_segments:
            return segments
        values = []
        by_index = {
            int(segment.get("index") or position + 1): segment
            for position, segment in enumerate(segments)
            if isinstance(segment, dict)
        }
        for item in selected_segments:
            if isinstance(item, dict) and item in segments:
                values.append(item)
                continue
            try:
                index = int((item or {}).get("index") if isinstance(item, dict) else item)
            except (TypeError, ValueError, AttributeError):
                continue
            segment = by_index.get(index)
            if segment is not None and segment not in values:
                values.append(segment)
        return values or segments

    def _public_sensitive_strings(self, job):
        sensitive = set()
        self._collect_sensitive_strings(job, sensitive)
        return sorted((item for item in sensitive if item), key=len, reverse=True)

    def _collect_sensitive_strings(self, value, sensitive):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in _PRIVATE_KEYS and isinstance(child, str):
                    sensitive.update(self._path_variants(child))
                self._collect_sensitive_strings(child, sensitive)
            return
        if isinstance(value, list):
            for item in value:
                self._collect_sensitive_strings(item, sensitive)

    def _path_variants(self, value):
        raw = str(value or "").strip()
        if not raw:
            return set()
        values = {raw}
        if "\\" in raw:
            values.add(raw.replace("\\", "/"))
        if "/" in raw:
            values.add(raw.replace("/", "\\"))
        return values

    def _scrub_value(self, value, sensitive_strings):
        if isinstance(value, dict):
            cleaned = {}
            for key, child in value.items():
                if key in _PRIVATE_KEYS:
                    continue
                cleaned[key] = self._scrub_value(child, sensitive_strings)
            return cleaned
        if isinstance(value, list):
            return [self._scrub_value(item, sensitive_strings) for item in value]
        if isinstance(value, str):
            return self._scrub_string(value, sensitive_strings)
        return value

    def _scrub_string(self, value, sensitive_strings):
        cleaned = str(value)
        for item in sensitive_strings:
            cleaned = cleaned.replace(item, _PATH_REDACTION)
        cleaned = _HTTP_URL_RE.sub(self._redact_public_url_match, cleaned)
        cleaned = _CREDENTIAL_RE.sub(self._redact_credential_match, cleaned)
        return cleaned

    def _redact_public_url_match(self, match):
        raw = str(match.group(0) or "").strip()
        parsed = urlparse(raw)
        host = str(parsed.hostname or "").strip()
        scheme = str(parsed.scheme or "").strip().lower()
        if scheme in ("http", "https") and host:
            if parsed.port:
                host = "%s:%s" % (host, parsed.port)
            return "%s://%s/%s" % (scheme, host, _URL_REDACTION)
        return _URL_REDACTION

    def _redact_credential_match(self, match):
        return "%s=[redacted]" % match.group("key")

    def _persist(self, job):
        saver = getattr(self._helpers(), "_save_replacement_job", None)
        if callable(saver):
            saver(job)

    def _job_duration(self, job, analysis):
        meta = (analysis or {}).get("meta") or {}
        for candidate in (
                meta.get("duration"),
                job.get("duration"),
                job.get("sourceDurationSec")):
            try:
                value = float(candidate or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        source_path = str(job.get("sourceVideoPath") or "").strip()
        if source_path:
            try:
                value = float((self._call("_probe_video", source_path) or {}).get("duration") or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 8.0

    def _job_out_dir(self):
        data_dir = self._call("data_dir")
        return os.path.join(data_dir, "video_replacements", uuid.uuid4().hex)

    def _helpers(self):
        if self.helpers is not None:
            return self.helpers
        import matrix_native_client as default_helpers
        self.helpers = default_helpers
        return self.helpers

    def _call(self, name, *args, **kwargs):
        helper = getattr(self._helpers(), name)
        return helper(*args, **kwargs)

    def _now(self):
        runtime = self.runtime
        if runtime is None:
            runtime = getattr(self._helpers(), "time", time)
        if callable(runtime):
            return float(runtime())
        if hasattr(runtime, "time") and callable(runtime.time):
            return float(runtime.time())
        return time.time()
