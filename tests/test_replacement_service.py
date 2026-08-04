import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SERVICE_PATH = BACKEND / "replacement_service.py"

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


class FakeSourceResolver:
    def prepare(self, job, request, progress=None):
        job["sourceVideoPath"] = os.path.join(job["outDir"], "source.mp4")
        Path(job["sourceVideoPath"]).write_bytes(b"fake-video")
        job["breakdownAnalysis"] = {"meta": {"duration": 8.0}}
        return job


class FakePipeline:
    def build_plan(self, job):
        job["segments"] = [{"index": 1, "start": 0.0, "end": 8.0, "status": "planned"}]
        return job

    def execute(self, job, selected_segments=None, progress=None):
        segment = job["segments"][0]
        output = os.path.join(job["outDir"], "segment-01.mp4")
        Path(output).write_bytes(b"fake-output")
        segment.update({"status": "done", "videoPath": output, "qcStatus": "passed"})
        job["status"] = "awaiting_review"
        return job

    def concat(self, job):
        output = os.path.join(job["outDir"], "final.mp4")
        Path(output).write_bytes(b"fake-final")
        job.update({"status": "completed", "outputPath": output})
        return job


class FailingPipeline(FakePipeline):
    def execute(self, job, selected_segments=None, progress=None):
        raise RuntimeError("fake provider failed")


class ReplacementServiceContractTests(unittest.TestCase):
    def setUp(self):
        self.module = load_replacement_service_module()
        self.ReplacementService = self.module.ReplacementService

    def _service(self, data_dir, pipeline=None):
        return self.ReplacementService(
            data_dir=data_dir,
            source_resolver=FakeSourceResolver(),
            pipeline=pipeline or FakePipeline(),
        )

    def test_prepare_execute_concat_persists_internal_paths_and_returns_public_job(self):
        with tempfile.TemporaryDirectory() as td:
            service = self._service(td)

            prepared = service.prepare(
                "job-123",
                {"sourceUrl": "https://example.test/video.mp4"},
                [("characterImage", "face.png", b"img")],
            )
            self.assertEqual(prepared["status"], "planned")
            self.assertEqual(prepared["segments"][0]["status"], "planned")
            self.assertNotIn("outDir", prepared)
            self.assertNotIn("sourceVideoPath", prepared)

            running = service.execute("job-123")
            self.assertEqual(running["status"], "awaiting_review")
            self.assertEqual(running["segments"][0]["status"], "done")
            self.assertEqual(running["segments"][0]["qcStatus"], "passed")
            self.assertNotIn("videoPath", json.dumps(running, ensure_ascii=False))

            completed = service.concat("job-123")
            self.assertEqual(completed["status"], "completed")
            self.assertNotIn("outputPath", completed)

            public_job = service.get_job("job-123")
            self.assertEqual(public_job["status"], "completed")
            exposed = json.dumps(public_job, ensure_ascii=False)
            self.assertNotIn("outDir", exposed)
            self.assertNotIn("sourceVideoPath", exposed)
            self.assertNotIn("videoPath", exposed)
            self.assertNotIn("outputPath", exposed)

            job_path = Path(td) / "job-123" / "job.json"
            saved = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "completed")
            self.assertTrue(saved["sourceVideoPath"].endswith("source.mp4"))
            self.assertTrue(saved["segments"][0]["videoPath"].endswith("segment-01.mp4"))
            self.assertTrue(saved["outputPath"].endswith("final.mp4"))
            self.assertFalse((job_path.parent / "job.json.tmp").exists())

    def test_execute_failure_marks_job_failed_without_success_result(self):
        with tempfile.TemporaryDirectory() as td:
            service = self._service(td, pipeline=FailingPipeline())
            service.prepare("job-124", {"sourceUrl": "https://example.test/video.mp4"}, [])

            with self.assertRaisesRegex(RuntimeError, "fake provider failed"):
                service.execute("job-124")

            saved = json.loads((Path(td) / "job-124" / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["error"], "fake provider failed")
            self.assertNotIn("outputPath", saved)
            self.assertNotIn("videoPath", json.dumps(saved, ensure_ascii=False))

            public_job = service.get_job("job-124")
            self.assertEqual(public_job["status"], "failed")
            self.assertEqual(public_job["error"], "fake provider failed")
            self.assertNotIn("outputPath", public_job)

    def test_cancel_updates_status_and_get_job_returns_none_for_missing_job(self):
        with tempfile.TemporaryDirectory() as td:
            service = self._service(td)
            self.assertIsNone(service.get_job("job-404"))

            service.prepare("job-125", {"sourceUrl": "https://example.test/video.mp4"}, [])
            cancelled = service.cancel("job-125")

            self.assertEqual(cancelled["status"], "cancelled")
            saved = json.loads((Path(td) / "job-125" / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "cancelled")

    def test_rejects_invalid_job_id_before_path_construction(self):
        with tempfile.TemporaryDirectory() as td:
            service = self._service(td)

            with self.assertRaisesRegex(ValueError, "invalid_job_id"):
                service.prepare("../escape", {"sourceUrl": "https://example.test/video.mp4"}, [])

            self.assertEqual(list(Path(td).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
