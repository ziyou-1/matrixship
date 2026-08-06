import copy
import hashlib
import json
import os
import re
import time
from urllib.parse import urlparse

try:
    from utils.structured_log import json_log as _json_log
except Exception:  # pragma: no cover - logging is best-effort at this boundary
    try:
        from backend.utils.structured_log import json_log as _json_log
    except Exception:
        _json_log = None


_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_INTERNAL_PATH_KEYS = {"outDir", "sourceVideoPath", "videoPath", "outputPath"}
# Provider-owned identifiers/URLs are never exposed raw: they are dropped from
# public payloads and their values scrubbed from any surrounding free text.
_SENSITIVE_ID_KEYS = {
    "providerTaskId", "provider_task_id", "taskId", "task_id",
    "videoUrl", "startFrameUrl", "endFrameUrl", "mediaUrl",
}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_PATH_REDACTION = "[redacted-path]"
_URL_REDACTION = "[redacted-url]"
_CREDENTIAL_RE = re.compile(
    r"(?i)\b(?P<key>authorization|bearer|token|cookie|password)\b"
    r"(?:\s*[:=]\s*|\s+)(?P<value>[^\s,;]+)"
)
_HTTP_URL_RE = re.compile(r"https?://[^\s<>'\"]+")


def _path_variants(value):
    raw = str(value or "").strip()
    if not raw:
        return set()
    variants = {raw}
    if "\\" in raw:
        variants.add(raw.replace("\\", "/"))
    if "/" in raw:
        variants.add(raw.replace("/", "\\"))
    return variants


def _collect_sensitive_strings(value, sensitive):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _INTERNAL_PATH_KEYS and isinstance(child, str):
                sensitive.update(_path_variants(child))
            if key in _SENSITIVE_ID_KEYS and isinstance(child, str):
                token = child.strip()
                if token:
                    sensitive.add(token)
            _collect_sensitive_strings(child, sensitive)
        return
    if isinstance(value, list):
        for item in value:
            _collect_sensitive_strings(item, sensitive)


def _redact_public_url_match(match):
    raw = str(match.group(0) or "").strip()
    parsed = urlparse(raw)
    host = str(parsed.hostname or "").strip()
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme in ("http", "https") and host:
        if parsed.port:
            host = "%s:%s" % (host, parsed.port)
        return "%s://%s/%s" % (scheme, host, _URL_REDACTION)
    return _URL_REDACTION


def _redact_credential_match(match):
    return "%s=[redacted]" % match.group("key")


def _scrub_string(value, sensitive_strings):
    cleaned = str(value)
    for item in sensitive_strings:
        cleaned = cleaned.replace(item, _PATH_REDACTION)
    cleaned = _HTTP_URL_RE.sub(_redact_public_url_match, cleaned)
    return _CREDENTIAL_RE.sub(_redact_credential_match, cleaned)


def _scrub_value(value, sensitive_strings):
    if isinstance(value, dict):
        cleaned = {}
        for key, child in value.items():
            if key in _INTERNAL_PATH_KEYS or key in _SENSITIVE_ID_KEYS:
                continue
            cleaned[key] = _scrub_value(child, sensitive_strings)
        return cleaned
    if isinstance(value, list):
        return [_scrub_value(item, sensitive_strings) for item in value]
    if isinstance(value, str):
        return _scrub_string(value, sensitive_strings)
    return value


def _public_sensitive_strings(job, data_dir=""):
    sensitive = set(_path_variants(data_dir))
    _collect_sensitive_strings(job, sensitive)
    return sorted((item for item in sensitive if item), key=len, reverse=True)


def public_job(job, data_dir=""):
    """Module-level scrubber so web/response layers can redact a raw job
    without holding a ReplacementService instance."""
    return _scrub_value(
        copy.deepcopy(job or {}),
        sensitive_strings=_public_sensitive_strings(job, data_dir),
    )


# ---------------------------------------------------------------------------
# Task 7: persisted terminal metrics + shared-mode circuit breaker
# ---------------------------------------------------------------------------

_METRICS_FILENAME = "replacement_metrics.json"
_METRICS_WINDOW = 500            # bound the persisted terminal-result window
_CIRCUIT_MIN_SAMPLES = 100       # require >= 100 terminal jobs before opening
_CIRCUIT_FAILURE_THRESHOLD = 0.01  # open only when failed/total is STRICTLY > 1%
_METRICS_DIR_ENV = "MATRIX_AGENT_DATA_DIR"


def _hash_token(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _resolve_metrics_dir(data_dir):
    if data_dir:
        return os.path.abspath(str(data_dir))
    env_dir = os.environ.get(_METRICS_DIR_ENV)
    if env_dir:
        return os.path.abspath(env_dir)
    return os.path.abspath(os.getcwd())


def _metrics_path(data_dir):
    return os.path.join(_resolve_metrics_dir(data_dir), _METRICS_FILENAME)


def _load_metrics(data_dir):
    path = _metrics_path(data_dir)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    results = payload.get("results") if isinstance(payload, dict) else payload
    return [item for item in (results or []) if isinstance(item, dict)]


def _save_metrics(data_dir, results):
    path = _metrics_path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    payload = {"version": 1, "results": results[-_METRICS_WINDOW:]}
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp_path, path)


def _timestamp(runtime=None):
    if runtime is None:
        return time.time()
    if callable(runtime):
        return float(runtime())
    if hasattr(runtime, "time") and callable(runtime.time):
        return float(runtime.time())
    return time.time()


def _summarize_metrics(results):
    terminal = [item for item in results if str(item.get("status") or "").lower() in _TERMINAL_STATUSES]
    total = len(terminal)
    failures = sum(1 for item in terminal if bool(item.get("failure")))
    rate = (failures / total) if total else 0.0
    return total, failures, rate


def record_terminal_result(job, data_dir=None, runtime=None):
    """Append a terminal job outcome to the bounded metrics window.

    Only terminal jobs (``completed``/``failed``/``cancelled``) are recorded; an
    in-flight (non-terminal) job is a no-op and is never mutated. A cancelled job
    is terminal but is NOT counted as a failure. Only a hashed job id is stored.
    """
    job = job if isinstance(job, dict) else {}
    status = str(job.get("status") or "").strip().lower()
    resolved_dir = _resolve_metrics_dir(data_dir)
    if status not in _TERMINAL_STATUSES:
        total, failures, _rate = _summarize_metrics(_load_metrics(resolved_dir))
        return {"recorded": False, "status": status, "total": total, "failures": failures}
    failure = status == "failed"
    entry = {
        "jobHash": _hash_token(job.get("id")),
        "status": status,
        "failure": failure,
        "at": _timestamp(runtime),
    }
    results = _load_metrics(resolved_dir)
    results.append(entry)
    results = results[-_METRICS_WINDOW:]
    _save_metrics(resolved_dir, results)
    total, failures_total, _rate = _summarize_metrics(results)
    return {
        "recorded": True,
        "status": status,
        "failure": failure,
        "total": total,
        "failures": failures_total,
    }


def circuit_breaker_state(data_dir=None):
    """Return the shared-mode circuit state derived from persisted metrics.

    The circuit opens (new jobs fall back to legacy) only when there are at least
    ``_CIRCUIT_MIN_SAMPLES`` terminal jobs AND the failure ratio is STRICTLY
    greater than ``_CIRCUIT_FAILURE_THRESHOLD`` (1%). Exactly 1% does not open it.
    """
    total, failures, rate = _summarize_metrics(_load_metrics(data_dir))
    enough = total >= _CIRCUIT_MIN_SAMPLES
    is_open = enough and (rate > _CIRCUIT_FAILURE_THRESHOLD)
    return {
        "total": total,
        "failures": failures,
        "failureRate": rate,
        "minSamples": _CIRCUIT_MIN_SAMPLES,
        "threshold": _CIRCUIT_FAILURE_THRESHOLD,
        "enoughSamples": enough,
        "open": is_open,
        "allowed": not is_open,
    }


def shared_mode_allowed(data_dir=None):
    """True when a NEW job may use the shared service; False when the breaker is
    open. This never touches jobs already in flight — it only gates new jobs."""
    return not circuit_breaker_state(data_dir)["open"]


# ---------------------------------------------------------------------------
# Task 7: redacted structured events at replacement boundaries
# ---------------------------------------------------------------------------

REPLACEMENT_EVENTS = frozenset({
    "prepare_started",
    "analysis_completed",
    "provider_submitted",
    "provider_recovered",
    "billing_settled",
    "video_completed",
    "video_failed",
    "shared_mode_circuit_opened",
    "rollback_requested",
})


def _media_url_shape(value):
    """Reduce a media URL to a scheme://host shape (never a path, query or
    signature). Non-http values collapse to a redaction marker."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    host = parsed.hostname or ""
    if scheme in ("http", "https") and host:
        if parsed.port:
            host = "%s:%s" % (host, parsed.port)
        return "%s://%s" % (scheme, host)
    return _URL_REDACTION


def build_replacement_event(
        event,
        job_id="",
        stage="",
        model="",
        provider_task_id="",
        status="",
        media_url="",
        cost=None,
        ref="",
        failure_stage="",
        detail=None):
    """Build a sanitized event context.

    Provider task ids only appear as a hash; media URLs only as a scheme+host
    shape. The assembled dict is scrubbed again so any credential or URL smuggled
    into a free-text field is redacted. Never carries Token/Cookie/Authorization/
    signed URL/absolute path/raw bytes.
    """
    # Free-text fields are scrubbed for any smuggled URL/credential; the two
    # already-safe computed fields (hash, url shape) are attached afterwards so
    # the whole-dict URL redactor does not mangle them.
    context = {
        "event": str(event or ""),
        "jobId": str(job_id or ""),
        "stage": str(stage or ""),
        "model": str(model or ""),
        "status": str(status or ""),
        "ref": str(ref or ""),
        "failureStage": str(failure_stage or ""),
    }
    if cost is not None:
        try:
            context["cost"] = round(float(cost), 6)
        except (TypeError, ValueError):
            context["cost"] = None
    if isinstance(detail, dict):
        context["detail"] = {str(k): detail[k] for k in detail}
    cleaned = _scrub_value(context, sensitive_strings=[])
    cleaned["providerTaskHash"] = _hash_token(provider_task_id)
    cleaned["mediaUrlShape"] = _media_url_shape(media_url)
    return cleaned


def emit_replacement_event(logger, event, event_sink=None, level="info", **fields):
    """Build a redacted event, hand it to an optional in-process sink and log it
    through the structured logger. Best-effort: logging never raises."""
    payload = build_replacement_event(event, **fields)
    if callable(event_sink):
        try:
            event_sink(payload)
        except Exception:
            pass
    if logger is not None and _json_log is not None:
        try:
            log_fields = {key: value for key, value in payload.items() if key != "event"}
            _json_log(logger, "replacement_%s" % (payload.get("event") or event), level=level, **log_fields)
        except Exception:
            pass
    return payload


class SourceResolver:
    def __init__(self, analysis):
        self.analysis = analysis

    def prepare(self, job, request, progress=None):
        job = job if isinstance(job, dict) else {}
        request = request if isinstance(request, dict) else {}
        resolved = self.analysis.resolve_source(
            request,
            job.get("outDir") or "",
            progress=progress,
        )
        if not isinstance(resolved, dict):
            raise RuntimeError("replacement_source_resolution_invalid")
        for key in (
                "handoffId",
                "platform",
                "sourceUrl",
                "source",
                "sourceVideoPath",
                "sourceContext",
                "breakdownAnalysis",
                "message"):
            if key in resolved:
                job[key] = copy.deepcopy(resolved.get(key))
        # Carry caller control flags (person mode / authorization confirmations)
        # onto the job so the pipeline honors no-person mode and keeps an audit
        # trail of the authorization the user confirmed before submitting.
        for flag in ("noPersonMode", "faceAuthorized", "personFullBody"):
            if flag in request:
                job[flag] = bool(request.get(flag))
        # Model / audio-mode / voice chosen on the web form flow through to the job
        # so the pipeline uses the requested model and audio path (defaults apply
        # when the caller omits them).
        for field in ("model", "audioMode", "voice", "productNotes", "modelNotes"):
            value = str(request.get(field) or "").strip()
            if value:
                job[field] = value
        if resolved.get("status") == "failed":
            job["status"] = "failed"
            job["error"] = str(resolved.get("error") or "media_invalid")
        return job


class ReplacementService:
    def __init__(self, data_dir, source_resolver, pipeline, runtime=None,
                 metrics_dir=None, logger=None, event_sink=None):
        self.data_dir = os.path.abspath(data_dir)
        self.source_resolver = source_resolver
        self.pipeline = pipeline
        self.runtime = runtime
        # metrics_dir is the agent data root shared with the Qt new-job gate; when
        # unset, terminal metrics are not recorded (used by fake-provider tests).
        self.metrics_dir = os.path.abspath(str(metrics_dir)) if metrics_dir else None
        self.logger = logger
        self.event_sink = event_sink

    def _emit_event(self, event, **fields):
        if self.logger is None and self.event_sink is None:
            return None
        return emit_replacement_event(self.logger, event, event_sink=self.event_sink, **fields)

    def _maybe_record_terminal(self, job):
        if not self.metrics_dir:
            return
        status = str((job or {}).get("status") or "").strip().lower()
        if status not in _TERMINAL_STATUSES:
            return
        try:
            record_terminal_result(job, data_dir=self.metrics_dir, runtime=self.runtime)
        except Exception:
            pass

    def prepare(self, job_id, request, files, progress=None):
        job = self._create_job(job_id, request, files)
        self._write_job(job)
        self._emit_event("prepare_started", job_id=job["id"], stage="prepare", status="created")
        job = self.source_resolver.prepare(job, request, progress=progress)
        if job.get("status") == "failed":
            self._write_job(job)
            self._emit_event(
                "video_failed", job_id=job["id"], stage="analysis",
                status="failed", failure_stage="source_resolution",
            )
            self._maybe_record_terminal(job)
            return self._public_job(job)
        job = self.pipeline.build_plan(job)
        job["status"] = "planned"
        self._write_job(job)
        self._emit_event(
            "analysis_completed", job_id=job["id"], stage="analysis",
            status="planned", model=str(job.get("model") or ""),
        )
        return self._public_job(job)

    def execute(self, job_id, overrides=None, progress=None):
        job = self._load_job(job_id)
        if not job or job.get("status") != "planned":
            raise ValueError("replacement_job_not_planned")
        self._apply_overrides(job, overrides or {})
        job["status"] = "running"
        self._write_job(job)
        try:
            selected_segments = (overrides or {}).get("selectedSegments")
            job = self.pipeline.execute(
                job,
                selected_segments=selected_segments or job.get("segments") or [],
                progress=progress,
            )
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc) or exc.__class__.__name__
            self._write_job(job)
            self._emit_event(
                "video_failed", job_id=job["id"], stage="generation",
                status="failed", failure_stage="execute",
                model=str(job.get("model") or ""),
            )
            self._maybe_record_terminal(job)
            raise
        self._write_job(job)
        self._maybe_record_terminal(job)
        return self._public_job(job)

    def retry(self, job_id, segment_indices, progress=None):
        job = self._load_job(job_id)
        if not job:
            raise ValueError("replacement_job_not_found")
        if job.get("status") not in ("partial", "awaiting_review"):
            raise ValueError("replacement_job_not_retryable")
        job["status"] = "running"
        self._write_job(job)
        try:
            job = self.pipeline.retry(job, segment_indices or [], progress=progress)
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc) or exc.__class__.__name__
            self._write_job(job)
            self._emit_event(
                "video_failed", job_id=job["id"], stage="generation",
                status="failed", failure_stage="retry",
                model=str(job.get("model") or ""),
            )
            self._maybe_record_terminal(job)
            raise
        self._write_job(job)
        self._maybe_record_terminal(job)
        return self._public_job(job)

    def regenerate_frame(self, job_id, segment_index, frame_kind, progress=None):
        job = self._load_job(job_id)
        if not job:
            raise ValueError("replacement_job_not_found")
        if job.get("status") not in ("partial", "awaiting_review"):
            raise ValueError("replacement_job_not_ready_for_regenerate")
        result = self.pipeline.regenerate_frame(
            job, int(segment_index), frame_kind, progress=progress)
        if isinstance(result, dict) and isinstance(result.get("job"), dict):
            job = result["job"]
        self._write_job(job)
        return self._public_job(job)

    def concat(self, job_id, progress=None):
        job = self._load_job(job_id)
        if not job or job.get("status") != "awaiting_review":
            raise ValueError("replacement_job_not_ready_for_concat")
        job = self.pipeline.concat(job)
        self._write_job(job)
        self._emit_event(
            "video_completed", job_id=job["id"], stage="concat",
            status=str(job.get("status") or "completed"),
            model=str(job.get("model") or ""),
        )
        self._maybe_record_terminal(job)
        return self._public_job(job)

    def get_job(self, job_id):
        job = self._load_job(job_id)
        if not job:
            return None
        return self._public_job(job)

    def cancel(self, job_id):
        job = self._load_job(job_id)
        if not job:
            raise ValueError("replacement_job_not_found")
        if job.get("status") not in _TERMINAL_STATUSES:
            job["status"] = "cancelled"
            self._write_job(job)
            self._maybe_record_terminal(job)
        return self._public_job(job)

    def _create_job(self, job_id, request, files):
        safe_job_id = self._validate_job_id(job_id)
        now = self._now()
        out_dir = self._job_dir(safe_job_id)
        os.makedirs(out_dir, exist_ok=True)
        request_data = copy.deepcopy(request or {})
        return {
            "id": safe_job_id,
            "status": "created",
            "request": request_data,
            "files": self._normalize_files(files),
            "createdAt": now,
            "updatedAt": now,
            "outDir": out_dir,
        }

    def _apply_overrides(self, job, overrides):
        if not overrides:
            return job
        merged = dict(job.get("overrides") or {})
        merged.update(copy.deepcopy(overrides))
        job["overrides"] = merged
        return job

    def _write_job(self, job):
        source = dict(job or {})
        # Never persist transient, non-JSON-serializable runtime objects (e.g. the
        # pipeline helper proxy some stages leave on the job mid-run).
        source.pop("_pipelineHelpers", None)
        payload = copy.deepcopy(source)
        payload["updatedAt"] = self._now()
        if not payload.get("createdAt"):
            payload["createdAt"] = payload["updatedAt"]
        path = self._job_path(payload["id"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp_path, path)
        job.clear()
        job.update(payload)
        return path

    def _load_job(self, job_id):
        path = self._job_path(job_id)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None

    def _public_job(self, job):
        return public_job(job, self.data_dir)

    def _normalize_files(self, files):
        normalized = []
        for item in files or []:
            if isinstance(item, dict):
                field = str(item.get("field") or "")
                filename = str(item.get("filename") or item.get("name") or "")
                size = int(item.get("size") or 0)
            else:
                parts = list(item) if isinstance(item, (list, tuple)) else [item]
                field = str(parts[0] if len(parts) > 0 else "")
                filename = str(parts[1] if len(parts) > 1 else "")
                blob = parts[2] if len(parts) > 2 else b""
                size = len(blob or b"")
            normalized.append({
                "field": field,
                "filename": filename,
                "size": size,
            })
        return normalized

    def _validate_job_id(self, job_id):
        value = str(job_id or "").strip()
        if not _JOB_ID_RE.match(value):
            raise ValueError("invalid_job_id")
        return value

    def _job_dir(self, job_id):
        safe_job_id = self._validate_job_id(job_id)
        path = os.path.abspath(os.path.join(self.data_dir, safe_job_id))
        data_root = self.data_dir.rstrip("\\/")
        if path != data_root and not path.startswith(data_root + os.sep):
            raise ValueError("invalid_job_id")
        return path

    def _job_path(self, job_id):
        return os.path.join(self._job_dir(job_id), "job.json")

    def _now(self):
        if self.runtime is None:
            return time.time()
        if callable(self.runtime):
            return float(self.runtime())
        if hasattr(self.runtime, "time") and callable(self.runtime.time):
            return float(self.runtime.time())
        return time.time()
