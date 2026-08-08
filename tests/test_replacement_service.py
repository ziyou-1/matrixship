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
ANALYSIS_PATH = BACKEND / "replacement_analysis.py"
PIPELINE_PATH = BACKEND / "replacement_pipeline.py"

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


def load_replacement_analysis_module():
    if not ANALYSIS_PATH.is_file():
        raise AssertionError("replacement_analysis.py is missing")
    spec = importlib.util.spec_from_file_location(
        "replacement_analysis_for_test",
        ANALYSIS_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_replacement_pipeline_module():
    if not PIPELINE_PATH.is_file():
        raise AssertionError("replacement_pipeline.py is missing")
    spec = importlib.util.spec_from_file_location(
        "replacement_pipeline_for_test",
        PIPELINE_PATH,
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
    def __init__(self):
        self.build_plan_calls = 0

    def build_plan(self, job):
        self.build_plan_calls += 1
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

    def retry(self, job, segment_indices, progress=None):
        selected = set(segment_indices or [])
        for segment in job.get("segments") or []:
            if segment.get("index") in selected:
                output = os.path.join(job["outDir"], "segment-%02d-retry.mp4" % int(segment["index"]))
                Path(output).write_bytes(b"fake-retry")
                segment.update({"status": "done", "videoPath": output, "qcStatus": "passed"})
        job["status"] = "awaiting_review"
        return job


class FailingPipeline(FakePipeline):
    def execute(self, job, selected_segments=None, progress=None):
        raise RuntimeError("fake provider failed")


class SensitiveFailingPipeline(FakePipeline):
    def execute(self, job, selected_segments=None, progress=None):
        raise RuntimeError(
            "fake provider failed: out_dir=%s source=%s token=secret-token"
            % (job["outDir"], job["sourceVideoPath"])
        )


class FakeDownloader:
    def __init__(self, filename="downloaded.mp4", payload=b"fake-video"):
        self.filename = filename
        self.payload = payload
        self.calls = []

    def download(self, source_url, job_dir):
        self.calls.append((source_url, job_dir))
        path = os.path.join(job_dir, self.filename)
        Path(path).write_bytes(self.payload)
        return path


class OutsideJobDirDownloader(FakeDownloader):
    def download(self, source_url, job_dir):
        self.calls.append((source_url, job_dir))
        path = Path(job_dir).parent / self.filename
        path.write_bytes(self.payload)
        return str(path)


class FakeVisionRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, prompt, frame_urls, **kwargs):
        self.calls.append({
            "prompt": prompt,
            "frameUrls": list(frame_urls),
            "kwargs": dict(kwargs),
        })
        return "fake visual summary"


class ReplacementServiceContractTests(unittest.TestCase):
    def setUp(self):
        self.module = load_replacement_service_module()
        self.analysis_module = load_replacement_analysis_module()
        self.ReplacementService = self.module.ReplacementService
        self.SourceResolver = self.module.SourceResolver
        self.ReplacementAnalysis = self.analysis_module.ReplacementAnalysis

    def _service(self, data_dir, pipeline=None):
        return self.ReplacementService(
            data_dir=data_dir,
            source_resolver=FakeSourceResolver(),
            pipeline=pipeline or FakePipeline(),
        )

    def _replacement_analysis(
            self,
            downloader=None,
            download_validation=None,
            source_validation=None,
            frame_times=None,
            vision_runner=None):
        frame_times = list(frame_times or [1.0])
        vision = vision_runner or FakeVisionRunner()

        def extract_frames(_video_path, frames_dir, _limit):
            os.makedirs(frames_dir, exist_ok=True)
            frames = []
            for index, stamp in enumerate(frame_times, 1):
                frame_path = Path(frames_dir) / ("frame-%02d.jpg" % index)
                frame_path.write_bytes(b"fake-frame")
                frames.append({"time": stamp, "path": str(frame_path)})
            return frames

        return self.ReplacementAnalysis(
            downloader=downloader or FakeDownloader(),
            download_validator=(download_validation or (lambda path: {
                "ok": True,
                "code": "",
                "path": path,
                "duration": 8.0,
                "width": 720,
                "height": 1280,
            })),
            platform_from_url=lambda url: "xhs" if "xiaohongshu" in str(url) else "douyin",
            source_validator=(source_validation or (lambda path: {
                "ok": True,
                "code": "",
                "path": path,
                "duration": 8.0,
                "width": 720,
                "height": 1280,
            })),
            frame_extractor=extract_frames,
            ocr_runner=lambda frames: {
                "status": "ok",
                "engine": "fake-ocr",
                "text": "字幕 %d" % len(frames),
                "errors": [],
            },
            transcription_runner=lambda _video_path, out_dir, progress=None: {
                "status": "ok",
                "text": "口播测试",
                "segments": [{"start": 0.0, "end": 1.0, "text": "口播测试"}],
                "failedRanges": [],
                "errors": [],
                "retryCount": 0,
                "outDir": out_dir,
            },
            vision_runner=vision,
            report_builder=lambda out: (
                "## 报告\n来源:%s\n时长:%s"
                % (out.get("platform") or "-", (out.get("meta") or {}).get("duration") or 0),
                "分析完成",
            ),
            markdown_builder=lambda out: (
                "# 分解\n%s\n%s"
                % (out.get("sourceUrl") or "", out.get("videoPath") or "")
            ),
            image_data_url=lambda path: "data:image/jpeg;base64,%s" % os.path.basename(path),
            json_logger=lambda *_args, **_kwargs: '{"errorId":"err-analysis-test"}',
            log_event=lambda *_args, **_kwargs: None,
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

    def test_public_job_redacts_internal_paths_and_credentials_embedded_in_error_text(self):
        with tempfile.TemporaryDirectory() as td:
            service = self._service(td, pipeline=SensitiveFailingPipeline())
            service.prepare("job-126", {"sourceUrl": "https://example.test/video.mp4"}, [])

            with self.assertRaisesRegex(RuntimeError, "fake provider failed"):
                service.execute("job-126")

            saved = json.loads((Path(td) / "job-126" / "job.json").read_text(encoding="utf-8"))
            self.assertIn(saved["outDir"], saved["error"])
            self.assertIn(saved["sourceVideoPath"], saved["error"])

            public_job = service.get_job("job-126")
            self.assertEqual(public_job["status"], "failed")
            self.assertIn("fake provider failed", public_job["error"])
            self.assertNotIn(td, public_job["error"])
            self.assertNotIn(saved["outDir"], public_job["error"])
            self.assertNotIn(saved["sourceVideoPath"], public_job["error"])
            self.assertNotIn("secret-token", public_job["error"])

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

    def test_prepare_reuses_handoff_source_and_analysis_without_redownloading(self):
        with tempfile.TemporaryDirectory() as td:
            handoff_video = Path(td) / "handoff-source.mp4"
            handoff_video.write_bytes(b"fake-video")
            analysis = self._replacement_analysis()
            pipeline = FakePipeline()
            service = self.ReplacementService(
                data_dir=td,
                source_resolver=self.SourceResolver(analysis),
                pipeline=pipeline,
            )

            prepared = service.prepare(
                "job-200",
                {
                    "handoff": {
                        "handoffId": "rwh_1234567890abcdef12345678",
                        "sourceUrl": "https://www.douyin.com/video/123?token=secret",
                        "sourceVideoPath": str(handoff_video),
                        "platform": "douyin",
                        "breakdownAnalysis": {
                            "meta": {"duration": 8.0, "width": 1080, "height": 1920},
                            "transcript": {"segments": [{"start": 0.0, "end": 1.0, "text": "hello"}]},
                        },
                    }
                },
                [],
            )

            self.assertEqual(prepared["status"], "planned")
            self.assertEqual(prepared["source"]["host"], "www.douyin.com")
            self.assertEqual(prepared["sourceContext"]["platform"], "douyin")
            self.assertEqual(prepared["sourceContext"]["duration"], 8.0)
            self.assertTrue(prepared["sourceContext"]["hasBreakdownAnalysis"])
            self.assertTrue(prepared["sourceContext"]["sourceVideoAvailable"])
            self.assertNotIn("sourceVideoPath", prepared)
            self.assertEqual(analysis.downloader.calls, [])
            self.assertEqual(pipeline.build_plan_calls, 1)

            saved = json.loads((Path(td) / "job-200" / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["handoffId"], "rwh_1234567890abcdef12345678")
            self.assertEqual(saved["sourceVideoPath"], str(handoff_video))
            self.assertEqual(saved["breakdownAnalysis"]["meta"]["duration"], 8.0)

    def test_prepare_downloads_direct_url_into_job_dir_and_analyzes_it(self):
        with tempfile.TemporaryDirectory() as td:
            downloader = FakeDownloader(filename="source-direct.mp4")
            analysis = self._replacement_analysis(downloader=downloader)
            pipeline = FakePipeline()
            service = self.ReplacementService(
                data_dir=td,
                source_resolver=self.SourceResolver(analysis),
                pipeline=pipeline,
            )

            prepared = service.prepare(
                "job-201",
                {"sourceUrl": "https://www.douyin.com/video/abc123?token=secret"},
                [("characterImage", "face.png", b"img")],
            )

            job_dir = str(Path(td) / "job-201")
            self.assertEqual(downloader.calls, [
                ("https://www.douyin.com/video/abc123?token=secret", job_dir)
            ])
            self.assertEqual(prepared["status"], "planned")
            self.assertEqual(prepared["source"]["host"], "www.douyin.com")
            self.assertEqual(prepared["sourceContext"]["platform"], "douyin")
            self.assertEqual(prepared["sourceContext"]["duration"], 8.0)
            self.assertTrue(prepared["sourceContext"]["sourceVideoAvailable"])
            self.assertIn("sourceVideoPathHash", prepared["sourceContext"])
            self.assertNotIn(job_dir, json.dumps(prepared, ensure_ascii=False))

            saved = json.loads((Path(td) / "job-201" / "job.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["sourceVideoPath"].startswith(job_dir))
            self.assertTrue(saved["sourceVideoPath"].endswith("source-direct.mp4"))
            self.assertEqual(saved["breakdownAnalysis"]["meta"]["duration"], 8.0)
            self.assertEqual(saved["breakdownAnalysis"]["ocr"]["engine"], "fake-ocr")
            self.assertEqual(saved["breakdownAnalysis"]["transcript"]["segments"][0]["text"], "口播测试")
            self.assertEqual(saved["breakdownAnalysis"]["visual"], "fake visual summary")

    def test_visual_analysis_failure_is_recorded_instead_of_becoming_visual_text(self):
        def failing_vision(_prompt, _frame_urls, **_kwargs):
            raise RuntimeError(
                "HTTPSConnectionPool(host='central.yunlingai.net', port=443): "
                "Max retries exceeded with url: /lk888/v1/chat/completions"
            )

        with tempfile.TemporaryDirectory() as td:
            analysis = self._replacement_analysis(
                frame_times=[1.24, 2.47],
                vision_runner=failing_vision,
            )

            result = analysis.analyze(
                os.path.join(td, "source.mp4"),
                source_url="https://www.douyin.com/video/abc123",
                out_dir=os.path.join(td, "analysis"),
            )

            out = result["analysis"]
            self.assertEqual(out["visual"], "")
            self.assertEqual(out["visualStatus"], {
                "status": "failed",
                "errorId": "err-analysis-test",
                "code": "workflow_reference_vision_failed",
                "message": "视觉模型分析失败，详情见结构化日志。",
            })
            self.assertEqual(
                self.analysis_module.breakdown_visual_failure(out)["errorId"],
                "err-analysis-test",
            )

            serialized = json.dumps(out, ensure_ascii=False)
            for leaked in (
                    "视觉模型分析失败（errorId",
                    "central.yunlingai.net",
                    "HTTPSConnectionPool",
                    "/lk888/v1/chat/completions",
            ):
                self.assertNotIn(leaked, serialized)

    def test_successful_visual_analysis_reports_ok_status(self):
        with tempfile.TemporaryDirectory() as td:
            analysis = self._replacement_analysis()

            out = analysis.analyze(
                os.path.join(td, "source.mp4"),
                out_dir=os.path.join(td, "analysis"),
            )["analysis"]

            self.assertEqual(out["visual"], "fake visual summary")
            self.assertEqual(out["visualStatus"]["status"], "ok")
            self.assertEqual(self.analysis_module.breakdown_visual_failure(out), {})

    def test_prepare_returns_structured_failed_job_for_invalid_media_without_planning(self):
        with tempfile.TemporaryDirectory() as td:
            downloader = FakeDownloader(filename="downloaded-invalid.mp4", payload=b"<html>403</html>")
            analysis = self._replacement_analysis(
                downloader=downloader,
                download_validation=lambda path: {
                    "ok": False,
                    "code": "download_html_body",
                    "path": path,
                    "size": len(b"<html>403</html>"),
                    "duration": 0.0,
                    "width": 0,
                    "height": 0,
                },
            )
            pipeline = FakePipeline()
            service = self.ReplacementService(
                data_dir=td,
                source_resolver=self.SourceResolver(analysis),
                pipeline=pipeline,
            )

            prepared = service.prepare(
                "job-202",
                {"sourceUrl": "https://www.douyin.com/video/bad"},
                [("characterImage", "face.png", b"img")],
            )

            self.assertEqual(prepared["status"], "failed")
            self.assertEqual(prepared["error"], "download_html_body")
            self.assertEqual(prepared["source"]["host"], "www.douyin.com")
            self.assertEqual(prepared["sourceContext"]["platform"], "douyin")
            self.assertFalse(prepared["sourceContext"]["sourceVideoAvailable"])
            self.assertNotEqual(prepared["status"], "completed")
            self.assertEqual(pipeline.build_plan_calls, 0)

            saved = json.loads((Path(td) / "job-202" / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["error"], "download_html_body")
            self.assertEqual(saved["breakdownAnalysis"]["validation"]["code"], "download_html_body")
            self.assertEqual(saved["breakdownAnalysis"]["report"].splitlines()[0], "## 分解失败")
            self.assertFalse(Path(saved["sourceVideoPath"]).exists())


    def test_prepare_redacts_private_urls_from_public_job_payloads(self):
        with tempfile.TemporaryDirectory() as td:
            handoff_video = Path(td) / "handoff-private.mp4"
            handoff_video.write_bytes(b"fake-video")
            private_url = "https://private.example/video/abc?sig=secret&token=secret"
            analysis = self._replacement_analysis()
            pipeline = FakePipeline()
            service = self.ReplacementService(
                data_dir=td,
                source_resolver=self.SourceResolver(analysis),
                pipeline=pipeline,
            )

            prepared = service.prepare(
                "job-203",
                {
                    "sourceUrl": private_url,
                    "handoff": {
                        "handoffId": "rwh_aaaaaaaaaaaaaaaaaaaaaaaa",
                        "sourceUrl": private_url,
                        "sourceVideoPath": str(handoff_video),
                        "platform": "douyin",
                        "breakdownAnalysis": {
                            "meta": {"duration": 9.0},
                            "sourceUrl": private_url,
                            "visual": "source: %s" % private_url,
                            "report": "## report\nlink: %s" % private_url,
                        },
                    },
                },
                [],
            )
            public_job = service.get_job("job-203")
            saved = json.loads((Path(td) / "job-203" / "job.json").read_text(encoding="utf-8"))
            prepared_dump = json.dumps(prepared, ensure_ascii=False)
            public_dump = json.dumps(public_job, ensure_ascii=False)
            safe_url = "https://private.example/[redacted-url]"

            self.assertEqual(saved["request"]["sourceUrl"], private_url)
            self.assertIn(private_url, saved["breakdownAnalysis"]["report"])
            self.assertNotIn(private_url, prepared_dump)
            self.assertNotIn(private_url, public_dump)
            self.assertNotIn("sig=secret", prepared_dump)
            self.assertNotIn("token=secret", prepared_dump)
            self.assertNotIn("sig=secret", public_dump)
            self.assertNotIn("token=secret", public_dump)
            self.assertIn(safe_url, prepared_dump)
            self.assertIn(safe_url, public_dump)

    def test_prepare_rejects_direct_download_path_outside_job_dir(self):
        with tempfile.TemporaryDirectory() as td:
            downloader = OutsideJobDirDownloader(filename="outside-source.mp4")
            analysis = self._replacement_analysis(downloader=downloader)
            pipeline = FakePipeline()
            service = self.ReplacementService(
                data_dir=td,
                source_resolver=self.SourceResolver(analysis),
                pipeline=pipeline,
            )

            prepared = service.prepare(
                "job-204",
                {"sourceUrl": "https://www.douyin.com/video/outside"},
                [("characterImage", "face.png", b"img")],
            )

            self.assertEqual(prepared["status"], "failed")
            self.assertEqual(prepared["error"], "replacement_source_outside_job_dir")
            self.assertEqual(prepared["sourceContext"]["platform"], "douyin")
            self.assertFalse(prepared["sourceContext"]["sourceVideoAvailable"])
            self.assertEqual(pipeline.build_plan_calls, 0)

            saved = json.loads((Path(td) / "job-204" / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["error"], "replacement_source_outside_job_dir")
            self.assertEqual(
                saved["breakdownAnalysis"]["validation"]["code"],
                "replacement_source_outside_job_dir",
            )
            self.assertFalse(saved["sourceVideoPath"].startswith(str(Path(td) / "job-204")))


if __name__ == "__main__":
    unittest.main()
