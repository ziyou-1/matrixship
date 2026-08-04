import copy
import json
import os
import re
import time


_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_INTERNAL_PATH_KEYS = {"outDir", "sourceVideoPath", "videoPath", "outputPath"}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


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
        job = self.pipeline.build_plan(job)
        job["status"] = "planned"
        self._write_job(job)
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
            raise
        self._write_job(job)
        return self._public_job(job)

    def concat(self, job_id, progress=None):
        job = self._load_job(job_id)
        if not job or job.get("status") != "awaiting_review":
            raise ValueError("replacement_job_not_ready_for_concat")
        job = self.pipeline.concat(job)
        self._write_job(job)
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
        payload = copy.deepcopy(job or {})
        payload["updatedAt"] = self._now()
        if not payload.get("createdAt"):
            payload["createdAt"] = payload["updatedAt"]
        path = self._job_path(payload["id"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
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
        return self._scrub_value(copy.deepcopy(job or {}))

    def _scrub_value(self, value):
        if isinstance(value, dict):
            cleaned = {}
            for key, child in value.items():
                if key in _INTERNAL_PATH_KEYS:
                    continue
                cleaned[key] = self._scrub_value(child)
            return cleaned
        if isinstance(value, list):
            return [self._scrub_value(item) for item in value]
        return value

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
