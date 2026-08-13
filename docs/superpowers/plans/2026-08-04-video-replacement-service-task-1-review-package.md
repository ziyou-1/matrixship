# Review package: 0905b375edc4f1c2d522a266427d32d00627f351..c2f0ef7ee2895ae9e1869db41396637ac8e8966e

## Commits
c2f0ef7 test: redact replacement service public errors
62fa0ba test: add video replacement service contract

## Files changed
 backend/replacement_analysis.py   |   3 +
 backend/replacement_pipeline.py   |   9 ++
 backend/replacement_service.py    | 230 ++++++++++++++++++++++++++++++++++++++
 tests/test_replacement_service.py | 185 ++++++++++++++++++++++++++++++
 4 files changed, 427 insertions(+)

## Diff
diff --git a/backend/replacement_analysis.py b/backend/replacement_analysis.py
new file mode 100644
index 0000000..ce396b9
--- /dev/null
+++ b/backend/replacement_analysis.py
@@ -0,0 +1,3 @@
+class ReplacementAnalysis:
+    def analyze(self, job, request=None, progress=None):
+        return job
diff --git a/backend/replacement_pipeline.py b/backend/replacement_pipeline.py
new file mode 100644
index 0000000..f18629a
--- /dev/null
+++ b/backend/replacement_pipeline.py
@@ -0,0 +1,9 @@
+class ReplacementPipeline:
+    def build_plan(self, job):
+        return job
+
+    def execute(self, job, selected_segments=None, progress=None):
+        return job
+
+    def concat(self, job):
+        return job
diff --git a/backend/replacement_service.py b/backend/replacement_service.py
new file mode 100644
index 0000000..1ea7d46
--- /dev/null
+++ b/backend/replacement_service.py
@@ -0,0 +1,230 @@
+import copy
+import json
+import os
+import re
+import time
+
+
+_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
+_INTERNAL_PATH_KEYS = {"outDir", "sourceVideoPath", "videoPath", "outputPath"}
+_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
+_PATH_REDACTION = "[redacted-path]"
+_CREDENTIAL_RE = re.compile(
+    r"(?i)\b(?P<key>authorization|bearer|token|cookie|password)\b"
+    r"(?:\s*[:=]\s*|\s+)(?P<value>[^\s,;]+)"
+)
+
+
+class ReplacementService:
+    def __init__(self, data_dir, source_resolver, pipeline, runtime=None):
+        self.data_dir = os.path.abspath(data_dir)
+        self.source_resolver = source_resolver
+        self.pipeline = pipeline
+        self.runtime = runtime
+
+    def prepare(self, job_id, request, files, progress=None):
+        job = self._create_job(job_id, request, files)
+        self._write_job(job)
+        job = self.source_resolver.prepare(job, request, progress=progress)
+        job = self.pipeline.build_plan(job)
+        job["status"] = "planned"
+        self._write_job(job)
+        return self._public_job(job)
+
+    def execute(self, job_id, overrides=None, progress=None):
+        job = self._load_job(job_id)
+        if not job or job.get("status") != "planned":
+            raise ValueError("replacement_job_not_planned")
+        self._apply_overrides(job, overrides or {})
+        job["status"] = "running"
+        self._write_job(job)
+        try:
+            selected_segments = (overrides or {}).get("selectedSegments")
+            job = self.pipeline.execute(
+                job,
+                selected_segments=selected_segments or job.get("segments") or [],
+                progress=progress,
+            )
+        except Exception as exc:
+            job["status"] = "failed"
+            job["error"] = str(exc) or exc.__class__.__name__
+            self._write_job(job)
+            raise
+        self._write_job(job)
+        return self._public_job(job)
+
+    def concat(self, job_id, progress=None):
+        job = self._load_job(job_id)
+        if not job or job.get("status") != "awaiting_review":
+            raise ValueError("replacement_job_not_ready_for_concat")
+        job = self.pipeline.concat(job)
+        self._write_job(job)
+        return self._public_job(job)
+
+    def get_job(self, job_id):
+        job = self._load_job(job_id)
+        if not job:
+            return None
+        return self._public_job(job)
+
+    def cancel(self, job_id):
+        job = self._load_job(job_id)
+        if not job:
+            raise ValueError("replacement_job_not_found")
+        if job.get("status") not in _TERMINAL_STATUSES:
+            job["status"] = "cancelled"
+            self._write_job(job)
+        return self._public_job(job)
+
+    def _create_job(self, job_id, request, files):
+        safe_job_id = self._validate_job_id(job_id)
+        now = self._now()
+        out_dir = self._job_dir(safe_job_id)
+        os.makedirs(out_dir, exist_ok=True)
+        request_data = copy.deepcopy(request or {})
+        return {
+            "id": safe_job_id,
+            "status": "created",
+            "request": request_data,
+            "files": self._normalize_files(files),
+            "createdAt": now,
+            "updatedAt": now,
+            "outDir": out_dir,
+        }
+
+    def _apply_overrides(self, job, overrides):
+        if not overrides:
+            return job
+        merged = dict(job.get("overrides") or {})
+        merged.update(copy.deepcopy(overrides))
+        job["overrides"] = merged
+        return job
+
+    def _write_job(self, job):
+        payload = copy.deepcopy(job or {})
+        payload["updatedAt"] = self._now()
+        if not payload.get("createdAt"):
+            payload["createdAt"] = payload["updatedAt"]
+        path = self._job_path(payload["id"])
+        os.makedirs(os.path.dirname(path), exist_ok=True)
+        tmp_path = path + ".tmp"
+        with open(tmp_path, "w", encoding="utf-8") as handle:
+            json.dump(payload, handle, ensure_ascii=False, indent=2)
+        os.replace(tmp_path, path)
+        job.clear()
+        job.update(payload)
+        return path
+
+    def _load_job(self, job_id):
+        path = self._job_path(job_id)
+        if not os.path.isfile(path):
+            return None
+        with open(path, "r", encoding="utf-8") as handle:
+            payload = json.load(handle)
+        return payload if isinstance(payload, dict) else None
+
+    def _public_job(self, job):
+        return self._scrub_value(
+            copy.deepcopy(job or {}),
+            sensitive_strings=self._public_sensitive_strings(job),
+        )
+
+    def _scrub_value(self, value, sensitive_strings):
+        if isinstance(value, dict):
+            cleaned = {}
+            for key, child in value.items():
+                if key in _INTERNAL_PATH_KEYS:
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
+        return _CREDENTIAL_RE.sub(self._redact_credential_match, cleaned)
+
+    def _redact_credential_match(self, match):
+        return "%s=[redacted]" % match.group("key")
+
+    def _public_sensitive_strings(self, job):
+        sensitive = set(self._path_variants(self.data_dir))
+        self._collect_sensitive_strings(job, sensitive)
+        return sorted(
+            (item for item in sensitive if item),
+            key=len,
+            reverse=True,
+        )
+
+    def _collect_sensitive_strings(self, value, sensitive):
+        if isinstance(value, dict):
+            for key, child in value.items():
+                if key in _INTERNAL_PATH_KEYS and isinstance(child, str):
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
+        variants = {raw}
+        if "\\" in raw:
+            variants.add(raw.replace("\\", "/"))
+        if "/" in raw:
+            variants.add(raw.replace("/", "\\"))
+        return variants
+
+    def _normalize_files(self, files):
+        normalized = []
+        for item in files or []:
+            if isinstance(item, dict):
+                field = str(item.get("field") or "")
+                filename = str(item.get("filename") or item.get("name") or "")
+                size = int(item.get("size") or 0)
+            else:
+                parts = list(item) if isinstance(item, (list, tuple)) else [item]
+                field = str(parts[0] if len(parts) > 0 else "")
+                filename = str(parts[1] if len(parts) > 1 else "")
+                blob = parts[2] if len(parts) > 2 else b""
+                size = len(blob or b"")
+            normalized.append({
+                "field": field,
+                "filename": filename,
+                "size": size,
+            })
+        return normalized
+
+    def _validate_job_id(self, job_id):
+        value = str(job_id or "").strip()
+        if not _JOB_ID_RE.match(value):
+            raise ValueError("invalid_job_id")
+        return value
+
+    def _job_dir(self, job_id):
+        safe_job_id = self._validate_job_id(job_id)
+        path = os.path.abspath(os.path.join(self.data_dir, safe_job_id))
+        data_root = self.data_dir.rstrip("\\/")
+        if path != data_root and not path.startswith(data_root + os.sep):
+            raise ValueError("invalid_job_id")
+        return path
+
+    def _job_path(self, job_id):
+        return os.path.join(self._job_dir(job_id), "job.json")
+
+    def _now(self):
+        if self.runtime is None:
+            return time.time()
+        if callable(self.runtime):
+            return float(self.runtime())
+        if hasattr(self.runtime, "time") and callable(self.runtime.time):
+            return float(self.runtime.time())
+        return time.time()
diff --git a/tests/test_replacement_service.py b/tests/test_replacement_service.py
new file mode 100644
index 0000000..845089f
--- /dev/null
+++ b/tests/test_replacement_service.py
@@ -0,0 +1,185 @@
+import importlib.util
+import json
+import os
+from pathlib import Path
+import sys
+import tempfile
+import unittest
+
+
+ROOT = Path(__file__).resolve().parents[1]
+BACKEND = ROOT / "backend"
+SERVICE_PATH = BACKEND / "replacement_service.py"
+
+if str(BACKEND) not in sys.path:
+    sys.path.insert(0, str(BACKEND))
+
+
+def load_replacement_service_module():
+    if not SERVICE_PATH.is_file():
+        raise AssertionError("replacement_service.py is missing")
+    spec = importlib.util.spec_from_file_location(
+        "replacement_service_for_test",
+        SERVICE_PATH,
+    )
+    module = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(module)
+    return module
+
+
+class FakeSourceResolver:
+    def prepare(self, job, request, progress=None):
+        job["sourceVideoPath"] = os.path.join(job["outDir"], "source.mp4")
+        Path(job["sourceVideoPath"]).write_bytes(b"fake-video")
+        job["breakdownAnalysis"] = {"meta": {"duration": 8.0}}
+        return job
+
+
+class FakePipeline:
+    def build_plan(self, job):
+        job["segments"] = [{"index": 1, "start": 0.0, "end": 8.0, "status": "planned"}]
+        return job
+
+    def execute(self, job, selected_segments=None, progress=None):
+        segment = job["segments"][0]
+        output = os.path.join(job["outDir"], "segment-01.mp4")
+        Path(output).write_bytes(b"fake-output")
+        segment.update({"status": "done", "videoPath": output, "qcStatus": "passed"})
+        job["status"] = "awaiting_review"
+        return job
+
+    def concat(self, job):
+        output = os.path.join(job["outDir"], "final.mp4")
+        Path(output).write_bytes(b"fake-final")
+        job.update({"status": "completed", "outputPath": output})
+        return job
+
+
+class FailingPipeline(FakePipeline):
+    def execute(self, job, selected_segments=None, progress=None):
+        raise RuntimeError("fake provider failed")
+
+
+class SensitiveFailingPipeline(FakePipeline):
+    def execute(self, job, selected_segments=None, progress=None):
+        raise RuntimeError(
+            "fake provider failed: out_dir=%s source=%s token=secret-token"
+            % (job["outDir"], job["sourceVideoPath"])
+        )
+
+
+class ReplacementServiceContractTests(unittest.TestCase):
+    def setUp(self):
+        self.module = load_replacement_service_module()
+        self.ReplacementService = self.module.ReplacementService
+
+    def _service(self, data_dir, pipeline=None):
+        return self.ReplacementService(
+            data_dir=data_dir,
+            source_resolver=FakeSourceResolver(),
+            pipeline=pipeline or FakePipeline(),
+        )
+
+    def test_prepare_execute_concat_persists_internal_paths_and_returns_public_job(self):
+        with tempfile.TemporaryDirectory() as td:
+            service = self._service(td)
+
+            prepared = service.prepare(
+                "job-123",
+                {"sourceUrl": "https://example.test/video.mp4"},
+                [("characterImage", "face.png", b"img")],
+            )
+            self.assertEqual(prepared["status"], "planned")
+            self.assertEqual(prepared["segments"][0]["status"], "planned")
+            self.assertNotIn("outDir", prepared)
+            self.assertNotIn("sourceVideoPath", prepared)
+
+            running = service.execute("job-123")
+            self.assertEqual(running["status"], "awaiting_review")
+            self.assertEqual(running["segments"][0]["status"], "done")
+            self.assertEqual(running["segments"][0]["qcStatus"], "passed")
+            self.assertNotIn("videoPath", json.dumps(running, ensure_ascii=False))
+
+            completed = service.concat("job-123")
+            self.assertEqual(completed["status"], "completed")
+            self.assertNotIn("outputPath", completed)
+
+            public_job = service.get_job("job-123")
+            self.assertEqual(public_job["status"], "completed")
+            exposed = json.dumps(public_job, ensure_ascii=False)
+            self.assertNotIn("outDir", exposed)
+            self.assertNotIn("sourceVideoPath", exposed)
+            self.assertNotIn("videoPath", exposed)
+            self.assertNotIn("outputPath", exposed)
+
+            job_path = Path(td) / "job-123" / "job.json"
+            saved = json.loads(job_path.read_text(encoding="utf-8"))
+            self.assertEqual(saved["status"], "completed")
+            self.assertTrue(saved["sourceVideoPath"].endswith("source.mp4"))
+            self.assertTrue(saved["segments"][0]["videoPath"].endswith("segment-01.mp4"))
+            self.assertTrue(saved["outputPath"].endswith("final.mp4"))
+            self.assertFalse((job_path.parent / "job.json.tmp").exists())
+
+    def test_execute_failure_marks_job_failed_without_success_result(self):
+        with tempfile.TemporaryDirectory() as td:
+            service = self._service(td, pipeline=FailingPipeline())
+            service.prepare("job-124", {"sourceUrl": "https://example.test/video.mp4"}, [])
+
+            with self.assertRaisesRegex(RuntimeError, "fake provider failed"):
+                service.execute("job-124")
+
+            saved = json.loads((Path(td) / "job-124" / "job.json").read_text(encoding="utf-8"))
+            self.assertEqual(saved["status"], "failed")
+            self.assertEqual(saved["error"], "fake provider failed")
+            self.assertNotIn("outputPath", saved)
+            self.assertNotIn("videoPath", json.dumps(saved, ensure_ascii=False))
+
+            public_job = service.get_job("job-124")
+            self.assertEqual(public_job["status"], "failed")
+            self.assertEqual(public_job["error"], "fake provider failed")
+            self.assertNotIn("outputPath", public_job)
+
+    def test_public_job_redacts_internal_paths_and_credentials_embedded_in_error_text(self):
+        with tempfile.TemporaryDirectory() as td:
+            service = self._service(td, pipeline=SensitiveFailingPipeline())
+            service.prepare("job-126", {"sourceUrl": "https://example.test/video.mp4"}, [])
+
+            with self.assertRaisesRegex(RuntimeError, "fake provider failed"):
+                service.execute("job-126")
+
+            saved = json.loads((Path(td) / "job-126" / "job.json").read_text(encoding="utf-8"))
+            self.assertIn(saved["outDir"], saved["error"])
+            self.assertIn(saved["sourceVideoPath"], saved["error"])
+
+            public_job = service.get_job("job-126")
+            self.assertEqual(public_job["status"], "failed")
+            self.assertIn("fake provider failed", public_job["error"])
+            self.assertNotIn(td, public_job["error"])
+            self.assertNotIn(saved["outDir"], public_job["error"])
+            self.assertNotIn(saved["sourceVideoPath"], public_job["error"])
+            self.assertNotIn("secret-token", public_job["error"])
+
+    def test_cancel_updates_status_and_get_job_returns_none_for_missing_job(self):
+        with tempfile.TemporaryDirectory() as td:
+            service = self._service(td)
+            self.assertIsNone(service.get_job("job-404"))
+
+            service.prepare("job-125", {"sourceUrl": "https://example.test/video.mp4"}, [])
+            cancelled = service.cancel("job-125")
+
+            self.assertEqual(cancelled["status"], "cancelled")
+            saved = json.loads((Path(td) / "job-125" / "job.json").read_text(encoding="utf-8"))
+            self.assertEqual(saved["status"], "cancelled")
+
+    def test_rejects_invalid_job_id_before_path_construction(self):
+        with tempfile.TemporaryDirectory() as td:
+            service = self._service(td)
+
+            with self.assertRaisesRegex(ValueError, "invalid_job_id"):
+                service.prepare("../escape", {"sourceUrl": "https://example.test/video.mp4"}, [])
+
+            self.assertEqual(list(Path(td).iterdir()), [])
+
+
+if __name__ == "__main__":
+    unittest.main()
