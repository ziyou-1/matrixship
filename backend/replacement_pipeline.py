import copy
import hashlib
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


def _helper_module(job):
    helpers = (job or {}).get("_pipelineHelpers")
    if helpers is not None:
        return helpers
    return None


def _helper_attr(job, name, default=None):
    helpers = _helper_module(job)
    if helpers is None:
        return default
    return getattr(helpers, name, default)


def _task_payload(payload):
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        return payload
    return {}


def _first_payload_value(payload, *keys):
    for container in (_task_payload(payload), payload if isinstance(payload, dict) else {}):
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if value not in (None, ""):
                return value
    return ""


def _truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _comic_fallback_metadata(payload):
    return {
        "requestedModel": str(_first_payload_value(payload, "requested_model", "requestedModel", "model") or "").strip(),
        "actualModel": str(_first_payload_value(payload, "actual_model", "actualModel", "model") or "").strip(),
        "fallbackModel": str(_first_payload_value(payload, "fallback_model", "fallbackModel") or "").strip(),
        "modelFallbackReason": str(_first_payload_value(payload, "fallback_reason", "fallbackReason") or "").strip(),
        "modelFallbackApplied": _truthy(_first_payload_value(payload, "fallback_applied", "fallbackApplied")),
    }


def _comic_billing_model_id(model):
    value = str(model or "").strip()
    aliases = {
        "vidu/viduq3-mix_reference2video": "viduq3-cankaosheng",
        "viduq3-mix_reference2video": "viduq3-cankaosheng",
    }
    return aliases.get(value, value)


def _comic_actual_cost_value(payload):
    keys = {
        "cost", "amount", "consume", "consumption", "charge", "fee",
        "actual_amount", "actualAmount", "actual_cost", "actualCost",
        "total_cost", "totalCost", "total_amount", "totalAmount",
    }
    seen = set()

    def walk(value, depth=0, key_hint=""):
        if depth > 5:
            return None
        if isinstance(value, dict):
            for key in (
                    "billing", "charge", "cost", "usage", "data", "result",
                    "price", "payment", "fee"):
                if key in value:
                    found = walk(value.get(key), depth + 1, key)
                    if found is not None:
                        return found
            for key, child in value.items():
                found = walk(child, depth + 1, str(key))
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child, depth + 1, key_hint)
                if found is not None:
                    return found
        elif key_hint in keys:
            try:
                amount = round(float(value or 0), 6)
            except Exception:
                return None
            if amount > 0:
                return amount
        return None

    try:
        marker = id(payload)
        if marker in seen:
            return None
        seen.add(marker)
    except Exception:
        pass
    return walk(payload)


def _comic_extract_task_id(payload):
    value = _first_payload_value(payload, "task_id", "taskId", "id")
    if value not in (None, ""):
        return str(value).strip()
    return ""


def _comic_actual_billing_ref(job, segment, media_kind, task_id, frame_index=None):
    job_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str((job or {}).get("id") or "job"))[:64]
    project_id = re.sub(
        r"[^A-Za-z0-9_.-]+", "_", str((job or {}).get("comicProjectId") or "0")
    )[:24]
    segment_index = re.sub(
        r"[^A-Za-z0-9_.-]+", "_", str((segment or {}).get("index") or "0")
    )[:24]
    task_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(task_id or ""))[:64]
    if media_kind == "keyframe":
        return "comic_keyframe:%s:seg:%s:task:%s:frame:%d:actual" % (
            job_id, segment_index, task_key, int(frame_index or 1)
        )
    return "comic_video:%s:project:%s:seg:%s:task:%s:actual" % (
        job_id, project_id, segment_index, task_key
    )


def _segment_actual_cost_entry(segment, media_kind, frame_index=None):
    segment = segment if isinstance(segment, dict) else {}
    if media_kind == "video":
        value = segment.get("comicVideoBilling")
        return value if isinstance(value, dict) else {}
    key = "startFrameBilling" if int(frame_index or 1) == 1 else "endFrameBilling"
    value = segment.get(key)
    return value if isinstance(value, dict) else {}


def _store_segment_actual_cost(segment, media_kind, billing, frame_index=None):
    segment = segment if isinstance(segment, dict) else {}
    billing = dict(billing or {})
    if media_kind == "video":
        segment["comicVideoBilling"] = billing
        return billing
    key = "startFrameBilling" if int(frame_index or 1) == 1 else "endFrameBilling"
    segment[key] = billing
    billings = list(segment.get("comicFrameBillings") or [])
    slot = max(0, int(frame_index or 1) - 1)
    while len(billings) <= slot:
        billings.append({})
    billings[slot] = billing
    segment["comicFrameBillings"] = billings
    return billing


def settle_actual_cost(job, segment, payload, media_kind, task_id, frame_index=None):
    amount = _comic_actual_cost_value(payload)
    fallback_parser = _helper_attr(job, "_comic_task_fallback_metadata")
    fallback = (
        fallback_parser(payload)
        if callable(fallback_parser)
        else _comic_fallback_metadata(payload)
    )
    billing_model = _helper_attr(job, "_comic_video_billing_model_id")
    actual_model = (
        fallback.get("actualModel")
        or fallback.get("fallbackModel")
        or fallback.get("requestedModel")
        or str((segment or {}).get("actualModel") or (segment or {}).get("requestedModel") or (job or {}).get("model") or "").strip()
    )
    if callable(billing_model):
        actual_model = billing_model(actual_model)
    else:
        actual_model = _comic_billing_model_id(actual_model)
    task_id = str(task_id or _comic_extract_task_id(payload) or "").strip()
    stage = "comic_video" if media_kind == "video" else (
        "comic_keyframe_start" if int(frame_index or 1) == 1 else "comic_keyframe_end"
    )
    ref = _comic_actual_billing_ref(job, segment, media_kind, task_id, frame_index=frame_index) if task_id else ""
    existing = _segment_actual_cost_entry(segment, media_kind, frame_index=frame_index)
    if existing and ref and str(existing.get("ref") or "").strip() == ref:
        if existing.get("status") == "settled":
            return existing
        if existing.get("status") == "awaiting_actual_cost" and not amount:
            return existing
    if not amount or not task_id:
        pending = {
            "status": "awaiting_actual_cost",
            "ref": ref,
            "model": actual_model,
            "taskId": task_id,
            "billingScenario": "video_replacement",
            "billingStage": stage,
        }
        logger = _helper_attr(job, "json_log")
        if callable(logger):
            logger(
                _helper_attr(job, "_CLIENT_JSON_LOGGER"),
                "video_replace_comic_billing_awaiting_actual_cost",
                job_id=str((job or {}).get("id") or ""),
                project_id=(job or {}).get("comicProjectId") or "",
                segment_index=(segment or {}).get("index") or "",
                media_kind=media_kind,
                model=actual_model,
                task_id_hash=hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12] if task_id else "",
                actual_cost_present=bool(amount),
            )
        return _store_segment_actual_cost(segment, media_kind, pending, frame_index=frame_index)
    charge = _helper_attr(job, "charge")
    if not callable(charge):
        raise RuntimeError("comic_actual_charge_missing")
    if media_kind == "video":
        capability = _helper_attr(job, "COMIC_VIDEO_GENERATION_CAP", "comic_video_generation")
        media_label = "漫剧视频生成"
    else:
        capability = _helper_attr(job, "COMIC_KEYFRAME_IMAGE_CAP", "comic_keyframe_image")
        media_label = "漫剧首帧图生成" if int(frame_index or 1) == 1 else "漫剧尾帧图生成"
    reason = "%s · 项目%s · 片段%s · %s · LK888实扣" % (
        media_label,
        (job or {}).get("comicProjectId") or "-",
        (segment or {}).get("index") or "-",
        actual_model or "-",
    )
    ok, _balance, error = charge(
        amount,
        reason=reason,
        ref=ref,
        capability=capability,
        allow_arrears=True,
        meta={
            "modelId": actual_model,
            "taskId": task_id,
            "actualAmount": amount,
            "billingScenario": "video_replacement",
            "billingStage": stage,
        },
    )
    if not ok:
        logger = _helper_attr(job, "json_log")
        if callable(logger):
            logger(
                _helper_attr(job, "_CLIENT_JSON_LOGGER"),
                "video_replace_comic_actual_billing_failed",
                job_id=str((job or {}).get("id") or ""),
                project_id=(job or {}).get("comicProjectId") or "",
                segment_index=(segment or {}).get("index") or "",
                media_kind=media_kind,
                model=actual_model,
                amount=amount,
                task_id_hash=hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12],
                error=str(error or "billing_failed")[:80],
            )
        raise RuntimeError(error or "comic_actual_charge_failed")
    settled = {
        "status": "settled",
        "ref": ref,
        "model": actual_model,
        "pricedModel": actual_model,
        "amount": amount,
        "actualAmount": amount,
        "taskId": task_id,
        "billingScenario": "video_replacement",
        "billingStage": stage,
    }
    logger = _helper_attr(job, "json_log")
    if callable(logger):
        logger(
            _helper_attr(job, "_CLIENT_JSON_LOGGER"),
            "video_replace_comic_actual_billing_settled",
            job_id=str((job or {}).get("id") or ""),
            project_id=(job or {}).get("comicProjectId") or "",
            segment_index=(segment or {}).get("index") or "",
            media_kind=media_kind,
            model=actual_model,
            amount=amount,
            task_id_hash=hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12],
        )
    return _store_segment_actual_cost(segment, media_kind, settled, frame_index=frame_index)


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
        if (job or {}).get("_replacementSkipPersist"):
            return
        saver = getattr(self._helpers(), "_save_replacement_job", None)
        if callable(saver):
            # _pipelineHelpers is a transient, non-JSON-serializable proxy that some
            # stages leave on the job while persisting mid-run (e.g. comic project
            # setup). Never write it to job.json; restore it for the caller after.
            had = isinstance(job, dict) and "_pipelineHelpers" in job
            helpers = job.pop("_pipelineHelpers", None) if had else None
            try:
                saver(job)
            finally:
                if had:
                    job["_pipelineHelpers"] = helpers

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


class ComicProjectReplacementPipeline(HybridReplacementPipeline):
    def execute(self, job, selected_segments, progress=None):
        job = job if isinstance(job, dict) else {}
        job["startedAt"] = job.get("startedAt") or self._now()
        job["status"] = "running"
        adapter = self._comic_adapter()
        self._ensure_project_ready(job, adapter, progress=progress)
        assets = job.get("comicAssets") or {}
        segments = list(job.get("segments") or [])
        chosen = self._resolve_selected_segments(job, selected_segments)
        total = len(segments)
        for segment in chosen:
            if self._comic_cancel_requested(job):
                self._call("_mark_replacement_job_canceled", job)
                self._persist(job)
                return job
            try:
                self._run_comic_segment(job, segment, adapter, assets, total, progress=progress)
            except Exception as exc:
                if self._comic_cancel_requested(job, exc=exc):
                    self._call("_mark_replacement_job_canceled", job)
                    self._persist(job)
                    return job
                self._fail_comic_segment(job, segment, exc)
                self._emit_comic_progress(
                    job,
                    segment,
                    "failed",
                    "片段 %s/%s 生成失败，可单段重试" % (segment.get("index"), total),
                    progress=progress,
                )
        failed = [item for item in segments if item.get("status") == "failed"]
        if failed:
            job["status"] = "partial"
            job["diagnostics"] = self._call("_replacement_diagnostics_summary", job)
            self._persist(job)
            return job
        job["status"] = "awaiting_review"
        self._persist(job)
        self._emit_comic_progress(
            job,
            None,
            "awaiting_review",
            "漫剧片段已生成，请审核后合成。",
            progress=progress,
        )
        return job

    def retry(self, job, segment_indices, progress=None):
        job = job if isinstance(job, dict) else {}
        wanted = {int(value) for value in (segment_indices or [])}
        allow_pending_recovery = bool(job.pop("_comicAllowPendingVideoRecovery", True))
        candidates = [
            segment for segment in (job.get("segments") or [])
            if isinstance(segment, dict)
            and (
                (wanted and int(segment.get("index") or 0) in wanted)
                or (
                    not wanted
                    and segment.get("status") in ("failed", "download_failed")
                )
            )
        ]
        if not candidates:
            return job
        if wanted:
            ready = []
            for segment in candidates:
                pending_recovery = (
                    self._call("_comic_pending_video_recovery", segment)
                    if allow_pending_recovery and segment.get("status") == "download_failed"
                    else {}
                )
                if pending_recovery:
                    ready.append(segment)
                    continue
                missing_message = self._call("_comic_video_missing_frames_message", segment)
                if missing_message:
                    segment["error"] = missing_message
                    segment["retryPrompt"] = missing_message
                    segment["stage"] = "video_retry_blocked_missing_frames"
                    continue
                ready.append(segment)
        else:
            ready, _skipped = self._call("_comic_segments_ready_for_video_retry", candidates)
        if not ready:
            job["status"] = "partial"
            job["diagnostics"] = self._call("_replacement_diagnostics_summary", job)
            self._persist(job)
            return job
        job["status"] = "running"
        adapter = self._comic_adapter()
        total = len(job.get("segments") or ready)
        for segment in ready:
            if self._comic_cancel_requested(job):
                self._call("_mark_replacement_job_canceled", job)
                self._persist(job)
                return job
            try:
                self._retry_comic_video(
                    job,
                    segment,
                    adapter,
                    total,
                    progress=progress,
                    allow_pending_recovery=allow_pending_recovery,
                )
            except Exception as exc:
                if self._comic_cancel_requested(job, exc=exc):
                    self._call("_mark_replacement_job_canceled", job)
                    self._persist(job)
                    return job
                self._fail_comic_video_retry(job, segment, exc)
                self._emit_comic_progress(
                    job,
                    segment,
                    segment.get("status") or "failed",
                    "片段 %s/%s 视频重新生成失败（错误编号 %s）" % (
                        segment.get("index"), total, segment.get("errorId") or "-"
                    ),
                    progress=progress,
                )
        remaining = [
            segment for segment in (job.get("segments") or [])
            if segment.get("status") in ("failed", "download_failed")
        ]
        if remaining:
            job["status"] = "partial"
            job["diagnostics"] = self._call("_replacement_diagnostics_summary", job)
            self._persist(job)
            return job
        job["status"] = "awaiting_review"
        self._persist(job)
        self._emit_comic_progress(
            job,
            None,
            "awaiting_review",
            "漫剧视频已重新生成，请审核后合成。",
            progress=progress,
        )
        return job

    def regenerate_frame(self, job, segment_index, frame_kind, progress=None):
        job = job if isinstance(job, dict) else {}
        segment = None
        for item in (job.get("segments") or []):
            if int((item or {}).get("index") or 0) == int(segment_index or 0):
                segment = item
                break
        if not isinstance(segment, dict):
            raise ValueError("comic_segment_not_found")
        kind = str(frame_kind or "").strip().lower()
        if kind not in ("start", "end"):
            raise ValueError("comic_frame_kind_invalid")
        adapter = self._comic_adapter()
        project_id = int(job.get("comicProjectId") or 0)
        storyboard_id = int(segment.get("comicStoryboardId") or 0)
        if not project_id:
            raise RuntimeError("comic_project_id_missing")
        if not storyboard_id:
            raise RuntimeError("comic_storyboard_id_missing")
        self._call("_comic_find_storyboard", adapter.get_project(project_id), storyboard_id)
        assets = job.get("comicAssets") or {}
        if not assets and hasattr(adapter, "upsert_manual_assets"):
            assets = adapter.upsert_manual_assets(project_id, job)
            job["comicAssets"] = assets
        self._emit_comic_progress(
            job,
            segment,
            "comic_update_storyboard",
            "片段 %s：同步当前口播稿和素材绑定…" % (segment.get("index") or "?"),
            progress=progress,
        )
        adapter.update_storyboard(storyboard_id, job, segment, assets, include_audio=False)
        frame_index = 1 if kind == "start" else 2
        self._emit_comic_progress(
            job,
            segment,
            "comic_generate_flowchart",
            "片段 %s：重新生成%s帧…" % (segment.get("index") or "?", "首" if frame_index == 1 else "尾"),
            progress=progress,
        )
        submitted = adapter.submit_storyboard_image(
            storyboard_id, job, segment, frame_index=frame_index
        )
        task_id = self._call("_comic_extract_task_id", submitted)
        if not task_id:
            raise RuntimeError("comic_frame_task_id_missing")
        image_url, payload = adapter.wait_task_result(
            task_id,
            cancel_check=self._call("_replacement_cancel_check", job),
        )
        self._settle_actual_cost(job, segment, payload, "keyframe", task_id, frame_index=frame_index)
        image_url = self._call("_comic_absolute_media_url", image_url)
        if not image_url:
            raise RuntimeError("comic_frame_url_missing")
        path_key = "startFramePath" if kind == "start" else "endFramePath"
        candidate = dict(segment)
        candidate[path_key] = ""
        image_path = self._call(
            "_comic_download_frame_image", job, candidate, kind, image_url, adapter, True
        )
        if not image_path:
            raise RuntimeError("comic_frame_download_failed")
        result_segment = self._call(
            "_apply_comic_frame_regeneration_result", segment, kind, task_id, image_url, image_path
        )
        self._persist(job)
        return {"job": job, "segment": result_segment, "frameKind": kind}

    def _comic_adapter(self):
        adapter_factory = getattr(self._helpers(), "ComicProjectAdapter")
        return adapter_factory()

    def _comic_cancel_requested(self, job, exc=None):
        if exc is not None and self._call("_replacement_cancel_exception", exc):
            return True
        return bool(self._call("_replacement_cancel_requested", job))

    def _emit_comic_progress(self, job, segment, stage, message, progress=None):
        timing = self._call("_replacement_timing_snapshot", job, segment, stage=stage)
        stage_value = timing.get("stage") or stage or str((segment or {}).get("status") or "")
        if isinstance(segment, dict):
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
                (segment or {}).get("index") if isinstance(segment, dict) else None,
                self.public_segments(job),
            )

    def _ensure_project_ready(self, job, adapter, progress=None):
        job["_pipelineHelpers"] = self._helpers()
        try:
            segments = job.get("segments") or []
            if not job.get("comicProjectId"):
                self._emit_comic_progress(job, None, "comic_project", "创建漫剧项目…", progress=progress)
                created = adapter.create_project(job)
                project_id = self._call("_comic_extract_id", created)
                if not project_id:
                    raise RuntimeError("comic_project_id_missing")
                job["comicProjectId"] = int(project_id)
                job["comicProjectUrl"] = self._call("_comic_base_url") + "/comic-drama/editor?projectId=%s" % project_id
                self._persist(job)
            project_id = int(job.get("comicProjectId") or 0)
            if any(not segment.get("comicStoryboardId") for segment in segments):
                self._emit_comic_progress(job, None, "comic_project", "读取漫剧项目分镜…", progress=progress)
                storyboards = self._call("_comic_storyboards_from_payload", adapter.get_project(project_id))
                if storyboards:
                    self._call("_comic_assign_storyboard_ids", job, storyboards)
                    self._persist(job)
            if any(not segment.get("comicStoryboardId") for segment in segments):
                self._emit_comic_progress(job, None, "comic_project", "分析剧本并生成分镜…", progress=progress)
                analyzed = adapter.analyze_project(project_id)
                storyboards = self._call("_comic_storyboards_from_payload", analyzed)
                if storyboards:
                    self._call("_comic_assign_storyboard_ids", job, storyboards)
                if any(not segment.get("comicStoryboardId") for segment in segments):
                    analyze_task_id = self._call("_comic_extract_task_id", analyzed)
                    if analyze_task_id:
                        adapter.wait_task_done(
                            analyze_task_id,
                            cancel_check=self._call("_replacement_cancel_check", job),
                            progress=lambda _attempt, _payload: self._emit_comic_progress(
                                job,
                                None,
                                "comic_project",
                                "分析剧本并生成分镜…",
                                progress=progress,
                            ),
                        )
                    storyboards = self._call("_comic_storyboards_from_payload", adapter.get_project(project_id))
                    self._call("_comic_assign_storyboard_ids", job, storyboards)
                self._persist(job)
            if not job.get("comicAssets") and hasattr(adapter, "upsert_manual_assets"):
                self._emit_comic_progress(job, None, "comic_assets", "写入人物、场景和道具到漫剧项目库…", progress=progress)
                job["comicAssets"] = adapter.upsert_manual_assets(project_id, job)
                self._persist(job)
            elif not job.get("comicAssets"):
                job["comicAssets"] = {}
        finally:
            job.pop("_pipelineHelpers", None)

    def _run_comic_segment(self, job, segment, adapter, assets, total, progress=None):
        storyboard_id = segment.get("comicStoryboardId")
        if not storyboard_id:
            raise RuntimeError("comic_storyboard_id_missing:segment_%s" % (segment.get("index") or "?"))
        existing_video_url = self._call("_comic_absolute_media_url", segment.get("videoUrl") or "")
        if existing_video_url:
            self._emit_comic_progress(
                job,
                segment,
                "comic_download_video",
                "片段 %s/%s：恢复已生成视频…" % (segment.get("index"), total),
                progress=progress,
            )
            remote_storyboard = self._call(
                "_comic_find_storyboard",
                adapter.get_project(int(job.get("comicProjectId") or 0)),
                storyboard_id,
            )
            start_frame_url, end_frame_url = self._call("_comic_storyboard_frame_urls", remote_storyboard)
            segment["startFrameUrl"] = self._call("_comic_absolute_media_url", segment.get("startFrameUrl") or start_frame_url)
            segment["endFrameUrl"] = self._call("_comic_absolute_media_url", segment.get("endFrameUrl") or end_frame_url)
            segment["flowchartUrl"] = segment.get("startFrameUrl") or segment.get("flowchartUrl") or ""
            self._call("_comic_download_frame_image", job, segment, "start", segment.get("startFrameUrl"), adapter)
            self._call("_comic_download_frame_image", job, segment, "end", segment.get("endFrameUrl"), adapter)
            if self._call("_comic_recover_completed_media", job, segment, adapter):
                self._persist(job)
                self._emit_comic_progress(
                    job,
                    segment,
                    "done",
                    "片段 %s/%s：视频完成" % (segment.get("index"), total),
                    progress=progress,
                )
                return
        segment["status"] = "running"
        self._emit_comic_progress(
            job,
            segment,
            "comic_update_storyboard",
            "片段 %s/%s：写入口播稿和素材绑定…" % (segment.get("index"), total),
            progress=progress,
        )
        adapter.update_storyboard(int(storyboard_id), job, segment, assets)
        for stale_audio_key in ("audioUrl", "audioDurationSeconds", "audioPrepareStatus", "audioWarning"):
            segment.pop(stale_audio_key, None)
        self._emit_comic_progress(
            job,
            segment,
            "comic_generate_flowchart",
            "片段 %s/%s：生成首尾帧…" % (segment.get("index"), total),
            progress=progress,
        )
        image_task_ids = []
        frame_urls = []
        frame_payloads = []
        try:
            image_task = adapter.submit_storyboard_image(int(storyboard_id), job, segment)
            image_task_ids = list(self._call("_comic_extract_task_ids", image_task) or [])
        except Exception as submit_exc:
            if not self._call("_comic_generation_submit_can_recover", submit_exc):
                raise
            recovered = self._call(
                "_comic_recover_storyboard_media",
                adapter,
                int(job.get("comicProjectId") or 0),
                storyboard_id,
                "image",
                submit_exc,
            )
            image_task_ids = list(recovered.get("task_ids") or [])
            if not image_task_ids and recovered.get("task_id"):
                image_task_ids = [recovered.get("task_id")]
            frame_urls = [
                self._call("_comic_absolute_media_url", value)
                for value in (recovered.get("frame_urls") or [])
                if value
            ]
            recovered_payload = recovered.get("payload") or {}
            if recovered_payload:
                frame_payloads.append(recovered_payload)
                recovered_task_id = (image_task_ids or [""])[0] or self._call("_comic_extract_task_id", recovered_payload)
                self._settle_actual_cost(
                    job,
                    segment,
                    recovered_payload,
                    "keyframe",
                    recovered_task_id,
                    frame_index=1,
                )
            segment["comicRecoveryStatus"] = "recovered"
            segment["comicRecoveryReason"] = str(submit_exc)[:180]
            self._emit_comic_progress(
                job,
                segment,
                "comic_generate_flowchart",
                "片段 %s/%s：远程已接收，正在回查首尾帧任务…" % (segment.get("index"), total),
                progress=progress,
            )
        if not image_task_ids and not frame_urls:
            raise RuntimeError("comic_image_task_id_missing:storyboard_%s" % storyboard_id)
        segment["startFrameTaskId"] = image_task_ids[0] if image_task_ids else ""
        segment["endFrameTaskId"] = image_task_ids[1] if len(image_task_ids) > 1 else ""
        segment["flowchartTaskId"] = segment["startFrameTaskId"]
        for frame_index, image_task_id in enumerate(image_task_ids[:2]):
            if frame_index < len(frame_urls) and frame_urls[frame_index]:
                continue
            frame_url, frame_payload = adapter.wait_task_result(
                image_task_id,
                cancel_check=self._call("_replacement_cancel_check", job),
                progress=lambda _attempt, _payload, s=segment: self._emit_comic_progress(
                    job,
                    s,
                    "comic_generate_flowchart",
                    "片段 %s/%s：首尾帧生成中…" % (s.get("index"), total),
                    progress=progress,
                ),
            )
            while len(frame_urls) <= frame_index:
                frame_urls.append("")
            frame_urls[frame_index] = self._call("_comic_absolute_media_url", frame_url)
            frame_payloads.append(frame_payload)
            self._settle_actual_cost(
                job,
                segment,
                frame_payload,
                "keyframe",
                image_task_id,
                frame_index=frame_index + 1,
            )
        if len(frame_urls) < 2 or not frame_urls[1]:
            remote_storyboard = self._call(
                "_comic_find_storyboard",
                adapter.get_project(int(job.get("comicProjectId") or 0)),
                storyboard_id,
            )
            remote_frame_urls = self._call("_comic_storyboard_frame_urls", remote_storyboard)
            for frame_index, frame_url in enumerate(remote_frame_urls):
                if frame_url and (len(frame_urls) <= frame_index or not frame_urls[frame_index]):
                    while len(frame_urls) <= frame_index:
                        frame_urls.append("")
                    frame_urls[frame_index] = frame_url
        frame_urls = (frame_urls + ["", ""])[:2]
        segment["startFrameUrl"] = frame_urls[0]
        segment["endFrameUrl"] = frame_urls[1]
        segment["flowchartUrl"] = frame_urls[0]
        segment["flowchartResult"] = self._call("_comic_response_data", frame_payloads[0]) if frame_payloads else {}
        segment["comicFrameResults"] = [
            self._call("_comic_response_data", payload) for payload in frame_payloads
        ]
        self._call("_comic_download_frame_image", job, segment, "start", segment.get("startFrameUrl"), adapter)
        self._call("_comic_download_frame_image", job, segment, "end", segment.get("endFrameUrl"), adapter)
        if self._call("_comic_model_is_seedance", self._call("_comic_video_model", job)):
            self._emit_comic_progress(
                job,
                segment,
                "comic_colored_pencil_refs",
                "片段 %s/%s：生成隐藏彩铅参考图…" % (segment.get("index"), total),
                progress=progress,
            )
            self._call("_prepare_comic_colored_pencil_references", job, segment)
        self._persist(job)
        self._emit_comic_progress(
            job,
            segment,
            "comic_generate_video",
            "片段 %s/%s：生成视频…" % (segment.get("index"), total),
            progress=progress,
        )
        video_url = ""
        video_payload = {}
        video_task_id = ""
        for video_model in self._call("_comic_project_video_model_candidates", job):
            job["comicVideoModel"] = video_model
            job["model"] = video_model
            segment["model"] = video_model
            try:
                video_task = adapter.submit_storyboard_video(int(storyboard_id), job, segment)
                video_task_id = self._call("_comic_extract_task_id", video_task)
                recovered_video_url = ""
                recovered_video_payload = {}
            except Exception as submit_exc:
                if not self._call("_comic_generation_submit_can_recover", submit_exc):
                    raise
                recovered = self._call(
                    "_comic_recover_storyboard_media",
                    adapter,
                    int(job.get("comicProjectId") or 0),
                    storyboard_id,
                    "video",
                    submit_exc,
                )
                video_task_id = recovered.get("task_id") or ""
                recovered_video_url = recovered.get("url") or ""
                recovered_video_payload = recovered.get("payload") or {}
                segment["comicRecoveryStatus"] = "recovered"
                segment["comicRecoveryReason"] = str(submit_exc)[:180]
                self._emit_comic_progress(
                    job,
                    segment,
                    "comic_generate_video",
                    "片段 %s/%s：远程已接收，正在回查视频任务…" % (segment.get("index"), total),
                    progress=progress,
                )
            segment["comicVideoTaskId"] = video_task_id
            try:
                if recovered_video_url:
                    video_url, video_payload = recovered_video_url, recovered_video_payload
                else:
                    video_url, video_payload = adapter.wait_task_result(
                        video_task_id,
                        cancel_check=self._call("_replacement_cancel_check", job),
                        progress=lambda _attempt, _payload, s=segment: self._emit_comic_progress(
                            job,
                            s,
                            "comic_generate_video",
                            self._call(
                                "_comic_task_progress_message",
                                _payload,
                                "片段 %s/%s：视频生成中…" % (s.get("index"), total),
                            ),
                            progress=progress,
                        ),
                        tries=int(job.get("tries") or 240),
                        sleep_sec=5,
                    )
                break
            except Exception as video_exc:
                fallback_reason = self._call("_comic_seedance_safety_fallback_reason", video_exc)
                segment.setdefault("comicVideoFallbacks", []).append({
                    "model": video_model,
                    "taskId": video_task_id,
                    "fallbackReason": fallback_reason,
                    "error": str(video_exc)[:240],
                })
                raise
        fallback_metadata = self._call("_comic_task_fallback_metadata", video_payload)
        requested_model = fallback_metadata.get("requestedModel") or str(segment.get("model") or job.get("model") or "").strip()
        actual_model = fallback_metadata.get("actualModel") or requested_model
        segment["requestedModel"] = requested_model
        segment["actualModel"] = actual_model
        segment["modelFallbackReason"] = fallback_metadata.get("modelFallbackReason") or ""
        segment["modelFallbackApplied"] = bool(fallback_metadata.get("modelFallbackApplied"))
        video_url = self._call("_comic_absolute_media_url", video_url)
        if not video_url:
            raise RuntimeError("comic_video_url_missing")
        self._settle_actual_cost(job, segment, video_payload, "video", video_task_id)
        segment["videoUrl"] = video_url
        segment["comicVideoResult"] = self._call("_comic_response_data", video_payload)
        self._emit_comic_progress(
            job,
            segment,
            "comic_download_video",
            "片段 %s/%s：下载视频结果…" % (segment.get("index"), total),
            progress=progress,
        )
        self._call("_comic_download_segment_video", job, segment, video_url, adapter)
        self._persist(job)
        self._emit_comic_progress(
            job,
            segment,
            "done",
            "片段 %s/%s：视频完成" % (segment.get("index"), total),
            progress=progress,
        )

    def _retry_comic_video(self, job, segment, adapter, total, progress=None, allow_pending_recovery=True):
        storyboard_id = segment.get("comicStoryboardId")
        new_task_id = ""
        new_video_url = ""
        download_started = False
        pending_recovery = (
            self._call("_comic_pending_video_recovery", segment)
            if allow_pending_recovery and segment.get("status") == "download_failed"
            else {}
        )
        if pending_recovery:
            new_task_id = str(pending_recovery.get("taskId") or "").strip()
            new_video_url = str(pending_recovery.get("videoUrl") or "").strip()
            candidate = self._call("_comic_video_candidate_from_pending", segment, pending_recovery)
            download_started = True
            segment.update({
                "status": "running",
                "stage": "comic_download_video",
                "stageLabel": self._call("_replacement_stage_label", "comic_download_video"),
            })
            self._persist(job)
            self._emit_comic_progress(
                job,
                segment,
                "comic_download_video",
                "片段 %s/%s：恢复下载并校验已生成视频…" % (segment.get("index"), total),
                progress=progress,
            )
            self._call("_comic_download_segment_video", job, candidate, new_video_url, adapter)
            candidate.pop("pendingComicVideoRecovery", None)
            candidate.pop("comicRecoveryStatus", None)
            candidate.pop("comicRecoveryReason", None)
            segment.update(candidate)
            segment.pop("pendingComicVideoRecovery", None)
            self._persist(job)
            self._emit_comic_progress(
                job,
                segment,
                "done",
                "片段 %s/%s：视频完成" % (segment.get("index"), total),
                progress=progress,
            )
            return
        missing_message = self._call("_comic_video_missing_frames_message", segment)
        if missing_message:
            error_id = self._call(
                "_replacement_error_id",
                "video_replace_comic_video_frames_missing",
                RuntimeError("comic_video_frames_missing"),
                job_id=job.get("id") or "",
                segment_index=segment.get("index") or "",
                storyboard_id=storyboard_id or "",
            )
            segment.update({
                "status": "failed",
                "stage": "video_retry_blocked_missing_frames",
                "stageLabel": self._call("_replacement_stage_label", "failed"),
                "error": missing_message,
                "errorId": error_id or segment.get("errorId") or "",
                "retryPrompt": missing_message,
            })
            self._persist(job)
            return
        if not storyboard_id:
            raise RuntimeError("comic_storyboard_id_missing")
        archived = self._call("_archive_comic_media_attempt", segment, "video")
        if archived:
            history = list(segment.get("retryHistory") or [])
            history.append(archived)
            segment["retryHistory"] = history
        segment.update({
            "status": "generating_video",
            "stage": "comic_update_storyboard",
            "stageLabel": self._call("_replacement_stage_label", "comic_update_storyboard"),
        })
        self._persist(job)
        self._emit_comic_progress(
            job,
            segment,
            "comic_update_storyboard",
            "片段 %s/%s：同步当前口播稿、素材和声音设置…" % (segment.get("index"), total),
            progress=progress,
        )
        adapter.update_storyboard(
            int(storyboard_id), job, segment, job.get("comicAssets") or {}, include_audio=True
        )
        self._emit_comic_progress(
            job,
            segment,
            "comic_generate_video",
            "片段 %s/%s：重新生成视频…" % (segment.get("index"), total),
            progress=progress,
        )
        submitted = adapter.submit_storyboard_video(int(storyboard_id), job, segment)
        new_task_id = self._call("_comic_extract_task_id", submitted)
        if not new_task_id:
            raise RuntimeError("comic_video_task_id_missing")
        new_video_url, video_payload = adapter.wait_task_result(
            new_task_id,
            cancel_check=self._call("_replacement_cancel_check", job),
            progress=lambda _attempt, _payload, s=segment: self._emit_comic_progress(
                job,
                s,
                "comic_generate_video",
                self._call(
                    "_comic_task_progress_message",
                    _payload,
                    "片段 %s/%s：视频生成中…" % (s.get("index"), total),
                ),
                progress=progress,
            ),
            tries=int(job.get("tries") or 240),
            sleep_sec=5,
        )
        new_video_url = self._call("_comic_absolute_media_url", new_video_url)
        if not new_video_url:
            raise RuntimeError("comic_video_url_missing")
        self._settle_actual_cost(job, segment, video_payload, "video", new_task_id)
        pending_recovery = self._call("_comic_pending_video_recovery_metadata", job, new_task_id, new_video_url, video_payload)
        segment["pendingComicVideoRecovery"] = pending_recovery
        self._persist(job)
        candidate = self._call("_comic_video_candidate_from_pending", segment, pending_recovery)
        download_started = True
        self._emit_comic_progress(
            job,
            segment,
            "comic_download_video",
            "片段 %s/%s：下载并校验新视频…" % (segment.get("index"), total),
            progress=progress,
        )
        self._call("_comic_download_segment_video", job, candidate, new_video_url, adapter)
        candidate.pop("comicRecoveryStatus", None)
        candidate.pop("comicRecoveryReason", None)
        candidate.pop("pendingComicVideoRecovery", None)
        segment.update(candidate)
        segment.pop("pendingComicVideoRecovery", None)
        self._persist(job)
        self._emit_comic_progress(
            job,
            segment,
            "done",
            "片段 %s/%s：视频完成" % (segment.get("index"), total),
            progress=progress,
        )

    def _fail_comic_segment(self, job, segment, exc):
        storyboard_id = segment.get("comicStoryboardId")
        error_id = self._call(
            "_replacement_error_id",
            "video_replace_comic_segment_failed",
            exc,
            job_id=job.get("id") or "",
            segment_index=segment.get("index") or "",
            storyboard_id=storyboard_id or "",
        )
        failure_update = {
            "status": "failed",
            "stage": "failed",
            "stageLabel": self._call("_replacement_stage_label", "failed"),
            "error": self._call("_comic_task_failure_message", {"data": {"errorMessage": str(exc)}})[:240],
            "errorId": error_id,
            "qcStatus": "failed",
        }
        if segment.get("stage") != "download_failed":
            failure_update["audioStatus"] = "failed"
        segment.update(failure_update)
        self._persist(job)

    def _fail_comic_video_retry(self, job, segment, exc):
        storyboard_id = segment.get("comicStoryboardId")
        error_id = self._call(
            "_replacement_error_id",
            "video_replace_comic_video_regeneration_failed",
            exc,
            job_id=job.get("id") or "",
            segment_index=segment.get("index") or "",
            storyboard_id=storyboard_id or "",
            task_id=segment.get("comicVideoTaskId") or "",
        )
        pending_recovery = self._call("_comic_pending_video_recovery", segment)
        failure_status = "download_failed" if pending_recovery else "failed"
        if failure_status == "download_failed" and pending_recovery:
            pending_recovery["downloadAttempts"] = int(pending_recovery.get("downloadAttempts") or 0) + 1
            pending_recovery["lastDownloadAttemptAt"] = self._now()
            pending_recovery["lastErrorId"] = error_id
            pending_recovery["downloadStatus"] = "failed"
            segment["pendingComicVideoRecovery"] = pending_recovery
        if segment.get("comicVideoTaskId") or segment.get("videoUrl"):
            history = list(segment.get("retryHistory") or [])
            history.append({
                "operationType": "comic_video_regeneration_attempt",
                "operationAt": self._now(),
                "mediaKind": "video",
                "taskId": segment.get("comicVideoTaskId") or "",
                "urlSummary": self._call("_comic_media_url_summary", segment.get("videoUrl") or ""),
                "status": failure_status,
                "errorId": error_id,
            })
            segment["retryHistory"] = history
        segment.update({
            "status": failure_status,
            "stage": failure_status,
            "stageLabel": self._call("_replacement_stage_label", "failed"),
            "error": "远程视频已生成，本地获取失败" if failure_status == "download_failed" else "comic_video_regeneration_failed",
            "errorId": error_id,
            "qcStatus": "failed",
        })
        self._persist(job)

    def _settle_actual_cost(self, job, segment, payload, media_kind, task_id, frame_index=None):
        job["_pipelineHelpers"] = self._helpers()
        try:
            return settle_actual_cost(
                job,
                segment,
                payload,
                media_kind,
                task_id,
                frame_index=frame_index,
            )
        finally:
            job.pop("_pipelineHelpers", None)
