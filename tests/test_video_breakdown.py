from pathlib import Path
import importlib.util
import inspect
import json
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import os


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"
REPLACEMENT_ANALYSIS = ROOT / "backend" / "replacement_analysis.py"


def load_client():
    spec = importlib.util.spec_from_file_location("matrix_native_client_for_video_breakdown", CLIENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class VideoBreakdownHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client()

    def test_find_video_file_from_material_path(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "video.mp4"
            video.write_bytes(b"fake")
            result = {
                "material": {"path": str(video), "kind": "video"},
                "files": [{"path": str(Path(td) / "cover.jpg"), "kind": "image"}],
            }

            self.assertEqual(self.client._find_video_file_from_download(result), str(video))

    def test_central_defaults_to_local_loopback(self):
        with mock.patch.dict(os.environ, {
            "MATRIX_CENTRAL": "",
            "CENTRAL_URL": "",
        }, clear=False):
            client = load_client()

        # Default matches the shipped start-visible-client.bat, which starts and
        # targets a local central server on 127.0.0.1:9080. Deployments that use a
        # remote central server set MATRIX_CENTRAL explicitly (see override test).
        self.assertEqual(client.CENTRAL, "http://127.0.0.1:9080")

    def test_central_env_override_supports_remote_central(self):
        with mock.patch.dict(os.environ, {
            "MATRIX_CENTRAL": "http://120.26.194.174:9080",
            "CENTRAL_URL": "",
        }, clear=False):
            client = load_client()

        self.assertEqual(client.CENTRAL, "http://120.26.194.174:9080")

    def test_find_video_file_from_files_list(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "clip.mov"
            video.write_bytes(b"fake")
            result = {"files": [{"path": str(video), "kind": "video"}]}

            self.assertEqual(self.client._find_video_file_from_download(result), str(video))

    def test_find_video_file_returns_empty_for_image_only_download(self):
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "cover.jpg"
            image.write_bytes(b"fake")

            self.assertEqual(
                self.client._find_video_file_from_download({"files": [{"path": str(image), "kind": "image"}]}),
                "",
            )

    def test_download_auth_error_is_localized_for_breakdown_status(self):
        self.assertIn(
            "重新登录抖音",
            self.client._localize_download_task_error("douyin_auth_incomplete"),
        )
        self.assertIn(
            "重新登录抖音",
            self.client._localize_download_task_error("'s_v_web_id'"),
        )

    def test_douyin_detail_network_error_is_localized_for_breakdown_status(self):
        self.assertEqual(
            self.client._video_breakdown_download_failure_text("douyin_detail_network_failed"),
            "抖音连接暂时失败，请重试",
        )

    def test_video_breakdown_markdown_contains_source_and_report(self):
        md = self.client._video_breakdown_markdown({
            "platform": "douyin",
            "sourceUrl": "https://www.douyin.com/video/123",
            "videoPath": "/tmp/video.mp4",
            "meta": {"duration": 12.5, "width": 1080, "height": 1920},
            "ocr": {"status": "disabled", "text": ""},
            "transcript": {"status": "disabled", "text": ""},
            "report": "## 内容总览\n这是一个测试报告",
        })

        self.assertIn("# 视频深度分解报告", md)
        self.assertIn("https://www.douyin.com/video/123", md)
        self.assertIn("/tmp/video.mp4", md)
        self.assertIn("12.5", md)
        self.assertIn("这是一个测试报告", md)

    def test_video_breakdown_markdown_contains_transcription_diagnostics(self):
        md = self.client._video_breakdown_markdown({
            "platform": "douyin",
            "sourceUrl": "https://www.douyin.com/video/123",
            "videoPath": "/tmp/video.mp4",
            "meta": {"duration": 700, "width": 1080, "height": 1920},
            "ocr": {"status": "ok", "engine": "rapidocr", "text": "字幕"},
            "transcript": {
                "status": "partial",
                "truncated": True,
                "retryCount": 1,
                "failedRanges": [{
                    "start": 60.0, "end": 120.0, "code": "remote_timeout", "errorId": "err-test-1"
                }],
                "text": "[00:00.000-00:01.000] 口播",
            },
            "report": "## 内容总览\n测试",
        })

        self.assertIn("VIDEO_TRANSCRIBE_MAX_SEC", md)
        self.assertIn("60.0-120.0s", md)
        self.assertIn("remote_timeout", md)
        self.assertIn("err-test-1", md)
        self.assertIn("重试次数: 1", md)
        self.assertIn("OCR 引擎: rapidocr", md)

    def test_breakdown_open_video_reports_open_failure(self):
        page = self.client.VideoBreakdownPage.__new__(self.client.VideoBreakdownPage)
        page._video_path = "E:/missing/video.mp4"
        page.status = mock.Mock()

        with mock.patch.object(self.client.os.path, "isfile", return_value=True), \
                mock.patch.object(self.client, "_open_path", return_value=False), \
                mock.patch.object(self.client, "_reveal_path", return_value=False):
            page.open_video()

        page.status.setText.assert_called_once()
        self.assertIn("无法打开视频文件", page.status.setText.call_args.args[0])

    def test_breakdown_open_video_reports_success_when_player_launches(self):
        page = self.client.VideoBreakdownPage.__new__(self.client.VideoBreakdownPage)
        page._video_path = "E:/videos/source.mp4"
        page.status = mock.Mock()

        with mock.patch.object(self.client.os.path, "isfile", return_value=True), \
                mock.patch.object(self.client, "_open_path", return_value=True) as open_path:
            page.open_video()

        open_path.assert_called_once_with("E:/videos/source.mp4")
        self.assertIn("已打开视频文件", page.status.setText.call_args.args[0])

    def test_breakdown_open_video_reveals_file_when_player_launch_fails(self):
        page = self.client.VideoBreakdownPage.__new__(self.client.VideoBreakdownPage)
        page._video_path = "E:/videos/source.mp4"
        page.status = mock.Mock()

        with mock.patch.object(self.client.os.path, "isfile", return_value=True), \
                mock.patch.object(self.client, "_open_path", return_value=False), \
                mock.patch.object(self.client, "_reveal_path", return_value=True) as reveal_path:
            page.open_video()

        reveal_path.assert_called_once_with("E:/videos/source.mp4")
        self.assertIn("已打开视频所在文件夹", page.status.setText.call_args.args[0])

    def test_breakdown_open_video_reports_missing_file(self):
        page = self.client.VideoBreakdownPage.__new__(self.client.VideoBreakdownPage)
        page._video_path = "E:/missing/video.mp4"
        page.status = mock.Mock()

        with mock.patch.object(self.client.os.path, "isfile", return_value=False), \
                mock.patch.object(self.client, "_open_path") as open_path:
            page.open_video()

        open_path.assert_not_called()
        self.assertIn("视频文件不存在", page.status.setText.call_args.args[0])

    def test_breakdown_source_validation_rejects_html_mp4(self):
        self.assertTrue(hasattr(self.client, "_breakdown_source_validation"))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "video.mp4"
            path.write_text("<html>403 Forbidden</html>", encoding="utf-8")
            result = self.client._breakdown_source_validation(str(path))

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "download_html_body")

    def test_video_breakdown_prompt_requests_deep_sections(self):
        prompt = self.client._video_breakdown_prompt(
            {"duration": 8, "width": 720, "height": 1280},
            "00:00 画面有产品",
            "字幕文本",
            "口播文本",
        )

        self.assertIn("时间轴镜头拆解", prompt)
        self.assertIn("营销结构", prompt)
        self.assertIn("Agent.模式提示词", prompt)
        self.assertIn("字幕文本", prompt)
        self.assertIn("口播文本", prompt)

    def test_report_completion_restores_sections_truncated_by_model(self):
        truncated_report = """## 内容总览
粉底液全天测评。

## 时间轴镜头拆解
00:00 展示产品。

## 字幕与口播
记录暴汗测试过程。

## 营销结构
实测建立信任。

## 爆点分析
运动暴汗与持妆效果形成冲突。
"""
        data = {
            "meta": {"duration": 169.47, "width": 720, "height": 1280},
            "visual": "人物展示法汀妮粉底液并进行运动暴汗测试。",
            "frameNotes": "[00:03] 产品瓶身特写",
            "ocr": {"status": "ok", "text": "全天不补妆挑战"},
            "transcript": {
                "status": "ok",
                "text": "[00:04.000-00:07.000] 今天测试这款粉底液",
            },
        }

        with mock.patch.object(self.client, "lk888_chat", return_value=truncated_report) as chat:
            report, message = self.client._generate_video_breakdown_report(data)

        expected_sections = (
            "内容总览", "时间轴镜头拆解", "字幕与口播", "营销结构",
            "爆点分析", "仿拍脚本", "Agent.模式提示词",
        )
        for title in expected_sections:
            self.assertEqual(report.count("## %s" % title), 1, title)
        self.assertIn("法汀妮粉底液", report)
        self.assertIn("全天不补妆挑战", report)
        self.assertIn("今天测试这款粉底液", report)
        self.assertGreaterEqual(chat.call_args.kwargs["max_tokens"], 4200)
        self.assertEqual(message, "分析完成（已自动修复报告栏目）")

    def test_report_failure_fallback_keeps_all_sections_in_contract_order(self):
        data = {
            "meta": {"duration": 20, "width": 720, "height": 1280},
            "visual": "人物在室内展示产品。",
            "frameNotes": "[00:02] 产品近景",
            "ocr": {"status": "ok", "text": "实测开始"},
            "transcript": {"status": "ok", "text": "[00:03.000-00:05.000] 口播实测结果"},
        }

        with mock.patch.object(self.client, "lk888_chat", side_effect=RuntimeError("upstream timeout")), \
                mock.patch.object(self.client, "json_log", return_value='{"errorId":"err-report-test"}'):
            report, message = self.client._generate_video_breakdown_report(data)

        positions = [report.index("## %s" % title) for title in self.client.VIDEO_BREAKDOWN_SECTION_TITLES]
        self.assertEqual(positions, sorted(positions))
        timeline = report[positions[1]:positions[2]]
        speech = report[positions[2]:positions[3]]
        self.assertIn("人物在室内展示产品", timeline)
        self.assertIn("[00:02] 产品近景", timeline)
        self.assertIn("实测开始", speech)
        self.assertIn("口播实测结果", speech)
        self.assertEqual(message, "分析完成（AI汇总已降级）")

    def test_report_completion_inserts_missing_middle_sections_in_order(self):
        report = """## 内容总览
测试总览。

## 营销结构
实测建立信任。

## 爆点分析
前后效果对比。

## 仿拍脚本
按原片节奏拍摄。

## Agent.模式提示词
生成同主题短视频。
"""
        completed, missing = self.client._ensure_video_breakdown_report_sections(report, {
            "visual": "人物展示产品",
            "ocr": {"text": "实测字幕"},
            "transcript": {"text": "[00:01.000-00:02.000] 开始测试"},
        })

        positions = [completed.index("## %s" % title) for title in self.client.VIDEO_BREAKDOWN_SECTION_TITLES]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(missing, ["时间轴镜头拆解", "字幕与口播"])

    def test_report_completion_normalizes_out_of_order_duplicate_sections(self):
        report = """## Agent.模式提示词
生成提示词。

## 内容总览
第一版总览。

## 营销结构
营销分析。

## 内容总览
补充总览证据。

## 时间轴镜头拆解
时间轴。

## 字幕与口播
字幕口播。

## 爆点分析
爆点。

## 仿拍脚本
仿拍。
"""
        normalized, repaired = self.client._ensure_video_breakdown_report_sections(report, {})

        positions = [normalized.index("## %s" % title) for title in self.client.VIDEO_BREAKDOWN_SECTION_TITLES]
        self.assertEqual(positions, sorted(positions))
        for title in self.client.VIDEO_BREAKDOWN_SECTION_TITLES:
            self.assertEqual(normalized.count("## %s" % title), 1, title)
        self.assertIn("第一版总览", normalized)
        self.assertIn("补充总览证据", normalized)
        self.assertTrue(repaired)

    def test_probe_video_parses_ffmpeg_stderr(self):
        fake = subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=1,
            stdout="",
            stderr="Duration: 00:00:12.50, start: 0.000000\nStream #0:0: Video: h264, yuv420p, 720x1280",
        )
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "clip.mp4"
            video.write_bytes(b"fake")
            with mock.patch.object(self.client.subprocess, "run", return_value=fake):
                meta = self.client._probe_video(str(video))

        self.assertEqual(meta["duration"], 12.5)
        self.assertEqual(meta["width"], 720)
        self.assertEqual(meta["height"], 1280)

    def test_ocr_empty_input_and_missing_video_transcription(self):
        ocr = self.client._ocr_breakdown_frames([{"path": "/tmp/missing.jpg"}])
        transcript = self.client._transcribe_breakdown_audio("")

        self.assertEqual(ocr["status"], "empty")
        self.assertIn("未识别", ocr["message"])
        self.assertEqual(transcript["status"], "failed")
        self.assertEqual(transcript["code"], "media_missing_file")

    def require_ocr_runtime_contract(self):
        signature = inspect.signature(self.client._ocr_breakdown_frames)
        self.assertIn("tesseract_cmd", signature.parameters)
        self.assertIn("rapid_engine", signature.parameters)
        self.assertIn("pytesseract_module", signature.parameters)
        self.assertIn("image_module", signature.parameters)

    def test_ocr_rapid_fallback_reports_partial_results(self):
        self.require_ocr_runtime_contract()
        calls = []

        def rapid_engine(path):
            calls.append(path)
            if len(calls) == 2:
                raise RuntimeError("frame failed")
            return ([[[0, 0, 1, 1], "注意事项", 0.99]], 0.01)

        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "one.jpg"
            second = Path(td) / "two.jpg"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            result = self.client._ocr_breakdown_frames(
                [{"time": 1, "path": str(first)}, {"time": 2, "path": str(second)}],
                tesseract_cmd="",
                rapid_engine=rapid_engine,
            )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["engine"], "rapidocr")
        self.assertIn("[1.00s] 注意事项", result["text"])
        self.assertEqual(len(result["errors"]), 1)

    def test_ocr_reports_unavailable_when_no_engine_exists(self):
        self.require_ocr_runtime_contract()
        with tempfile.TemporaryDirectory() as td:
            frame = Path(td) / "frame.jpg"
            frame.write_bytes(b"fake")
            result = self.client._ocr_breakdown_frames(
                [{"time": 0, "path": str(frame)}],
                tesseract_cmd="",
                rapid_engine=False,
            )

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["errors"][0]["code"], "ocr_engine_unavailable")

    def test_ocr_tesseract_uses_environment_language_and_config(self):
        self.require_ocr_runtime_contract()
        captured = {}

        class FakePytesseract:
            class pytesseract:
                tesseract_cmd = ""

            @staticmethod
            def image_to_string(image, lang=None, config=None):
                captured.update({"image": image, "lang": lang, "config": config})
                return "字幕文本"

        class FakeImage:
            @staticmethod
            def open(path):
                return "image:" + path

        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {
            "VIDEO_OCR_LANG": "chi_sim+eng",
            "VIDEO_OCR_CONFIG": "--oem 3 --psm 11",
        }, clear=False):
            frame = Path(td) / "frame.jpg"
            frame.write_bytes(b"fake")
            result = self.client._ocr_breakdown_frames(
                [{"time": 3.5, "path": str(frame)}],
                tesseract_cmd="/runtime/tesseract",
                pytesseract_module=FakePytesseract,
                image_module=FakeImage,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["engine"], "tesseract")
        self.assertEqual(captured["lang"], "chi_sim+eng")
        self.assertEqual(captured["config"], "--oem 3 --psm 11")

    def test_ocr_tesseract_all_runtime_failures_fall_back_to_rapidocr(self):
        self.require_ocr_runtime_contract()
        rapid_calls = []

        class FailingPytesseract:
            class pytesseract:
                tesseract_cmd = ""

            @staticmethod
            def image_to_string(_image, lang=None, config=None):
                del lang, config
                raise RuntimeError("Error opening data file chi_sim.traineddata")

        class FakeImage:
            @staticmethod
            def open(path):
                return "image:" + path

        def rapid_engine(path):
            rapid_calls.append(path)
            return ([[[0, 0, 1, 1], "Rapid 恢复文本", 0.99]], 0.01)

        with tempfile.TemporaryDirectory() as td:
            frames = []
            for index in range(2):
                frame = Path(td) / ("frame-%d.jpg" % index)
                frame.write_bytes(b"fake")
                frames.append({"time": float(index), "path": str(frame)})
            result = self.client._ocr_breakdown_frames(
                frames,
                tesseract_cmd="/runtime/tesseract",
                rapid_engine=rapid_engine,
                pytesseract_module=FailingPytesseract,
                image_module=FakeImage,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["engine"], "rapidocr")
        self.assertEqual(len(rapid_calls), 2)
        self.assertIn("Rapid 恢复文本", result["text"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["fallbackErrors"]), 2)

    def test_ocr_rapid_fallback_keeps_recovered_text_when_one_frame_still_fails(self):
        self.require_ocr_runtime_contract()

        class FailingPytesseract:
            class pytesseract:
                tesseract_cmd = ""

            @staticmethod
            def image_to_string(_image, lang=None, config=None):
                del lang, config
                raise RuntimeError("Failed loading language")

        class FakeImage:
            @staticmethod
            def open(path):
                return "image:" + path

        rapid_calls = []

        def rapid_engine(path):
            rapid_calls.append(path)
            if len(rapid_calls) == 2:
                raise RuntimeError("rapid frame failed")
            return ([[[0, 0, 1, 1], "已恢复字幕", 0.99]], 0.01)

        with tempfile.TemporaryDirectory() as td:
            frames = []
            for index in range(2):
                frame = Path(td) / ("frame-%d.jpg" % index)
                frame.write_bytes(b"fake")
                frames.append({"time": float(index), "path": str(frame)})
            result = self.client._ocr_breakdown_frames(
                frames,
                tesseract_cmd="/runtime/tesseract",
                rapid_engine=rapid_engine,
                pytesseract_module=FailingPytesseract,
                image_module=FakeImage,
            )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["engine"], "rapidocr")
        self.assertIn("已恢复字幕", result["text"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(len(result["fallbackErrors"]), 2)

    def test_export_audio_returns_empty_when_input_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self.client._export_audio_for_breakdown("/tmp/no-such-video.mp4", td), "")

    def test_cleanup_skips_active_owner_and_removes_expired_inactive_jobs(self):
        self.assertTrue(hasattr(self.client, "write_video_breakdown_job_owner"))
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "video_breakdowns"
            active = root / "active-job"
            dead = root / "dead-job"
            ownerless = root / "ownerless-job"
            fresh = root / "fresh-ownerless-job"
            for path in (active, dead, ownerless, fresh):
                path.mkdir(parents=True)
                (path / "chunk.mp3").write_bytes(b"stale")
            active_process = subprocess.Popen([
                sys.executable, "-c", "import time; time.sleep(30)"
            ])
            dead_process = subprocess.Popen([sys.executable, "-c", "pass"])
            dead_process.wait(timeout=5)
            old = time.time() - 7200
            try:
                active_owner = self.client.write_video_breakdown_job_owner(
                    str(active), pid=active_process.pid, created_at=old
                )
                self.client.write_video_breakdown_job_owner(
                    str(dead), pid=dead_process.pid, created_at=old
                )
                os.utime(ownerless, (old, old))

                with mock.patch.dict(os.environ, {
                    "VIDEO_BREAKDOWN_TEMP_RETENTION_SEC": "3600",
                }, clear=False):
                    result = self.client.cleanup_video_breakdown_temp_root(td)

                self.assertEqual(active_owner["pid"], active_process.pid)
                owner_payload = json.loads((active / "owner.json").read_text(encoding="utf-8"))
                self.assertEqual(owner_payload["pid"], active_process.pid)
                self.assertTrue(active.exists())
                self.assertFalse(dead.exists())
                self.assertFalse(ownerless.exists())
                self.assertTrue(fresh.exists())
                self.assertTrue(root.exists())
                self.assertEqual(result["skippedActive"], 1)
                self.assertEqual(result["removed"], 2)
            finally:
                active_process.terminate()
                active_process.wait(timeout=5)

    def test_setup_env_runs_retention_cleanup_without_removing_temp_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "video_breakdowns"
            fresh = root / "fresh-job"
            fresh.mkdir(parents=True)
            (fresh / "chunk.mp3").write_bytes(b"fresh")

            with mock.patch.object(self.client, "data_dir", return_value=td), \
                    mock.patch.dict(os.environ, {
                        "VIDEO_BREAKDOWN_TEMP_RETENTION_SEC": "3600",
                    }, clear=False):
                self.client.setup_env()

            self.assertTrue(root.exists())
            self.assertTrue(fresh.exists())

    def require_transcription_runtime_contract(self):
        signature = inspect.signature(self.client._transcribe_breakdown_audio)
        self.assertIn("out_dir", signature.parameters)
        self.assertIn("only_ranges", signature.parameters)
        self.assertIn("progress", signature.parameters)
        self.assertTrue(hasattr(self.client, "export_audio_chunks"))
        self.assertTrue(hasattr(self.client, "transcribe_audio_chunks"))

    def test_transcription_wrapper_uses_lk888_config_and_preserves_failures(self):
        self.require_transcription_runtime_contract()
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {
            "VIDEO_TRANSCRIBE_MODEL": "gemini-test",
            "VIDEO_TRANSCRIBE_CHUNK_SEC": "60",
            "VIDEO_TRANSCRIBE_MAX_SEC": "600",
            "VIDEO_TRANSCRIBE_TIMEOUT_SEC": "180",
            "VIDEO_TRANSCRIBE_RETRIES": "2",
        }, clear=False):
            video = Path(td) / "video.mp4"
            video.write_bytes(b"fake")
            chunk = Path(td) / "chunk-060.mp3"
            chunk.write_bytes(b"audio")
            exported = {
                "status": "ok",
                "chunks": [{"start": 60.0, "end": 120.0, "path": str(chunk)}],
                "duration": 700,
                "truncated": True,
            }
            remote = {
                "status": "failed",
                "chunks": [],
                "text": "",
                "segments": [],
                "failedRanges": [{"start": 60.0, "end": 120.0, "code": "remote_timeout"}],
                "errors": [{"start": 60.0, "end": 120.0, "code": "remote_timeout"}],
            }
            with mock.patch.object(self.client, "export_audio_chunks", return_value=exported) as export, \
                    mock.patch.object(self.client, "transcribe_audio_chunks", return_value=remote) as transcribe, \
                    mock.patch.object(self.client, "lk888_config", return_value={
                        "base_url": "http://127.0.0.1:9080/lk888", "api_key": "session-token"
                    }), mock.patch.object(self.client, "_lk_proxies", return_value=None):
                result = self.client._transcribe_breakdown_audio(
                    str(video), out_dir=str(Path(td) / "audio"),
                    only_ranges=[{"start": 60.0, "end": 120.0}], progress=lambda *_args: None,
                )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["failedRanges"][0]["code"], "remote_timeout")
        export.assert_called_once()
        self.assertEqual(transcribe.call_args.kwargs["model"], "gemini-test")
        self.assertEqual(transcribe.call_args.kwargs["only_ranges"], [{"start": 60.0, "end": 120.0}])

    def test_transcription_wrapper_merges_audio_export_failures_with_remote_success(self):
        self.require_transcription_runtime_contract()
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "video.mp4"
            video.write_bytes(b"fake")
            exported = {
                "status": "partial",
                "chunks": [{"start": 0.0, "end": 60.0, "path": str(Path(td) / "chunk.mp3")}],
                "failedRanges": [{
                    "start": 60.0,
                    "end": 120.0,
                    "code": "audio_export_failed",
                    "errorId": "err-export",
                }],
                "errors": [{
                    "start": 60.0,
                    "end": 120.0,
                    "code": "audio_export_failed",
                    "errorId": "err-export",
                }],
                "duration": 120.0,
                "truncated": False,
            }
            remote = {
                "status": "ok",
                "chunks": [{
                    "start": 0.0,
                    "end": 60.0,
                    "language": "zh-CN",
                    "segments": [{"startSec": 0.0, "endSec": 1.0, "text": "成功口播"}],
                }],
                "text": "[00:00.000-00:01.000] 成功口播",
                "segments": [{"startSec": 0.0, "endSec": 1.0, "text": "成功口播"}],
                "failedRanges": [],
                "errors": [],
            }
            with mock.patch.object(self.client, "export_audio_chunks", return_value=exported), \
                    mock.patch.object(self.client, "transcribe_audio_chunks", return_value=remote), \
                    mock.patch.object(self.client, "lk888_config", return_value={
                        "base_url": "http://127.0.0.1:9080/lk888", "api_key": "session-token"
                    }), mock.patch.object(self.client, "_lk_proxies", return_value=None):
                result = self.client._transcribe_breakdown_audio(
                    str(video), out_dir=str(Path(td) / "audio")
                )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["code"], "transcription_partial")
        self.assertEqual(result["failedRanges"], exported["failedRanges"])
        self.assertEqual(result["errors"], exported["errors"])
        self.assertIn("成功口播", result["text"])

    def test_transcription_wrapper_preserves_failed_ranges_when_all_exports_fail(self):
        self.require_transcription_runtime_contract()
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "video.mp4"
            video.write_bytes(b"fake")
            exported = {
                "status": "failed",
                "code": "audio_export_failed",
                "chunks": [],
                "failedRanges": [{
                    "start": 0.0,
                    "end": 60.0,
                    "code": "audio_export_failed",
                    "errorId": "err-export",
                }],
                "errors": [{
                    "start": 0.0,
                    "end": 60.0,
                    "code": "audio_export_failed",
                    "errorId": "err-export",
                }],
                "duration": 60.0,
                "truncated": False,
            }
            with mock.patch.object(self.client, "export_audio_chunks", return_value=exported):
                result = self.client._transcribe_breakdown_audio(
                    str(video), out_dir=str(Path(td) / "audio")
                )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failedRanges"], exported["failedRanges"])
        self.assertEqual(result["errors"], exported["errors"])

    def test_video_breakdown_page_continues_after_audio_export_failure(self):
        exported = {
            "status": "failed",
            "code": "audio_export_failed",
            "chunks": [],
            "failedRanges": [{
                "start": 0.0,
                "end": 60.0,
                "code": "audio_export_failed",
                "errorId": "err-export",
            }],
            "errors": [{
                "start": 0.0,
                "end": 60.0,
                "code": "audio_export_failed",
                "errorId": "err-export",
            }],
            "duration": 60.0,
            "truncated": False,
        }
        previous_bridge = self.client.BRIDGE
        page = None
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(
                os.environ, {"QT_QPA_PLATFORM": "offscreen"}, clear=False):
            video = Path(td) / "video.mp4"
            frame = Path(td) / "frame.jpg"
            video.write_bytes(b"fake-video")
            frame.write_bytes(b"fake-frame")
            app = self.client.QtWidgets.QApplication.instance()
            if app is None:
                app = self.client.QtWidgets.QApplication([])
            self.client.BRIDGE = self.client.Bridge()
            page = self.client.VideoBreakdownPage()
            try:
                with mock.patch.object(self.client, "data_dir", return_value=td), \
                        mock.patch.object(self.client, "write_video_breakdown_job_owner",
                                          create=True) as write_owner, \
                        mock.patch.object(self.client, "_breakdown_source_validation", return_value={
                            "ok": True, "duration": 60.0, "width": 720, "height": 1280,
                        }), mock.patch.object(self.client, "_extract_breakdown_frames", return_value=[{
                            "time": 1.0, "path": str(frame),
                        }]), mock.patch.object(self.client, "_ocr_breakdown_frames", return_value={
                            "status": "ok", "engine": "rapidocr", "text": "字幕", "errors": [],
                        }), mock.patch.object(self.client, "export_audio_chunks", return_value=exported), \
                        mock.patch.object(self.client, "_ffmpeg_exe", return_value="ffmpeg-test"), \
                        mock.patch.object(self.client, "lk888_vision", return_value="视觉分析") as vision, \
                        mock.patch.object(self.client, "_generate_video_breakdown_report",
                                          return_value=("## 报告\n已降级完成", "分析完成")) as report:
                    page.start({"videoPath": str(video), "sourceUrl": "local-test"})
                    job_dir = Path(td) / "video_breakdowns" / page._job
                    deadline = time.time() + 5.0
                    while time.time() < deadline and (page._busy or job_dir.exists()):
                        app.processEvents()
                        time.sleep(0.01)
                    app.processEvents()

                transcript = page._analysis["transcript"]
                self.assertFalse(page._busy)
                self.assertFalse(job_dir.exists())
                write_owner.assert_called_once_with(str(job_dir))
                self.assertEqual(transcript["status"], "failed")
                self.assertEqual(transcript["failedRanges"], exported["failedRanges"])
                self.assertTrue(page.b_retry.isEnabled())
                vision.assert_called_once()
                report.assert_called_once()
                self.assertIn("已降级完成", page.report.toPlainText())
            finally:
                if page is not None:
                    page.deleteLater()
                self.client.BRIDGE = previous_bridge
                del app

    def test_retry_transcription_writes_owner_and_completes_async_lifecycle(self):
        previous_bridge = self.client.BRIDGE
        page = None
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(
                os.environ, {"QT_QPA_PLATFORM": "offscreen"}, clear=False):
            video = Path(td) / "video.mp4"
            video.write_bytes(b"fake-video")
            app = self.client.QtWidgets.QApplication.instance()
            if app is None:
                app = self.client.QtWidgets.QApplication([])
            self.client.BRIDGE = self.client.Bridge()
            page = self.client.VideoBreakdownPage()
            page._video_path = str(video)
            page._analysis = {
                "validation": {"ok": True},
                "transcript": {
                    "status": "partial",
                    "retryCount": 0,
                    "chunks": [],
                    "failedRanges": [{
                        "start": 60.0,
                        "end": 120.0,
                        "code": "remote_timeout",
                        "errorId": "err-old",
                    }],
                    "errors": [{
                        "start": 60.0,
                        "end": 120.0,
                        "code": "remote_timeout",
                        "errorId": "err-old",
                    }],
                },
            }
            page._markdown = "# previous"
            retried = {
                "status": "ok",
                "chunks": [{
                    "start": 60.0,
                    "end": 120.0,
                    "language": "zh-CN",
                    "segments": [{"startSec": 0.0, "endSec": 1.0, "text": "重试成功"}],
                }],
                "failedRanges": [],
                "errors": [],
                "duration": 120.0,
                "truncated": False,
            }
            try:
                with mock.patch.object(self.client, "data_dir", return_value=td), \
                        mock.patch.object(self.client, "write_video_breakdown_job_owner",
                                          create=True) as write_owner, \
                        mock.patch.object(self.client, "_transcribe_breakdown_audio",
                                          return_value=retried), \
                        mock.patch.object(self.client, "_generate_video_breakdown_report",
                                          return_value=("## updated", "分析完成")):
                    page.retry_transcription()
                    job_dir = Path(td) / "video_breakdowns" / page._job
                    deadline = time.time() + 5.0
                    while time.time() < deadline and (page._busy or job_dir.exists()):
                        app.processEvents()
                        time.sleep(0.01)
                    app.processEvents()

                self.assertFalse(page._busy)
                self.assertFalse(job_dir.exists())
                write_owner.assert_called_once_with(str(job_dir))
                self.assertEqual(page._analysis["transcript"]["status"], "ok")
                self.assertEqual(page._analysis["transcript"]["errors"], [])
                self.assertIn("重试成功", page._analysis["transcript"]["text"])
            finally:
                if page is not None:
                    page.deleteLater()
                self.client.BRIDGE = previous_bridge
                del app

    def test_retry_transcription_falls_back_to_full_video_when_failed_ranges_missing(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "video.mp4"
            video.write_bytes(b"fake-video")
            previous_bridge = self.client.BRIDGE
            app = self.client.QtWidgets.QApplication.instance()
            if app is None:
                app = self.client.QtWidgets.QApplication([])
            self.client.BRIDGE = self.client.Bridge()
            page = self.client.VideoBreakdownPage()
            page._video_path = str(video)
            page._analysis = {
                "validation": {"ok": True},
                "meta": {"duration": 120.0},
                "transcript": {
                    "status": "failed",
                    "retryCount": 0,
                    "chunks": [],
                    "failedRanges": [],
                    "errors": [],
                },
            }
            page._markdown = "# previous"
            retried = {
                "status": "ok",
                "chunks": [{
                    "start": 0.0,
                    "end": 120.0,
                    "language": "zh-CN",
                    "segments": [{"startSec": 0.0, "endSec": 1.0, "text": "整段重试成功"}],
                }],
                "failedRanges": [],
                "errors": [],
                "duration": 120.0,
                "truncated": False,
            }
            try:
                with mock.patch.object(page.status, "setText", wraps=page.status.setText) as set_text, \
                        mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                        mock.patch.object(self.client, "data_dir", return_value=td), \
                        mock.patch.object(self.client, "write_video_breakdown_job_owner",
                                          create=True) as write_owner, \
                        mock.patch.object(self.client, "_transcribe_breakdown_audio",
                                          return_value=retried) as transcribe_audio, \
                        mock.patch.object(self.client, "_generate_video_breakdown_report",
                                          return_value=("## updated", "分析完成")):
                    page.retry_transcription()

                args, kwargs = transcribe_audio.call_args
                self.assertEqual(kwargs.get("only_ranges"), [{
                    "start": 0.0,
                    "end": 120.0,
                    "code": "transcription_retry_full",
                    "errorId": "",
                }])
                self.assertTrue(any("整段视频重试" in str(call.args[0]) for call in set_text.call_args_list))
                self.assertFalse(page._busy)
                self.assertTrue(write_owner.called)
                self.assertEqual(page._analysis["transcript"]["status"], "ok")
                self.assertIn("整段重试成功", page._analysis["transcript"]["text"])
            finally:
                if page is not None:
                    page.deleteLater()
                self.client.BRIDGE = previous_bridge
                del app

    def test_theme_toggle_waits_for_video_breakdown_done_signal(self):
        previous_bridge = self.client.BRIDGE
        page = None
        with mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}, clear=False):
            app = self.client.QtWidgets.QApplication.instance()
            if app is None:
                app = self.client.QtWidgets.QApplication([])
            self.client.BRIDGE = self.client.Bridge()
            page = self.client.VideoBreakdownPage()
            page._job = "busy-theme-job"
            page._busy = True

            class FakeWindow:
                pass

            window = FakeWindow()
            window._page_widgets = [page]
            window._toast = mock.Mock()
            window._rebuild_pages = mock.Mock()
            window._refresh_theme_ui = mock.Mock()
            window._theme_btn = self.client.QtWidgets.QPushButton()
            window.conn_name = self.client.QtWidgets.QLabel()
            window._logout_btn = None
            try:
                with mock.patch.object(self.client, "apply_theme") as apply_theme, \
                        mock.patch.object(self.client, "save_theme_pref") as save_theme:
                    self.client.MainWindow.toggle_theme(window)

                    apply_theme.assert_not_called()
                    save_theme.assert_not_called()
                    window._rebuild_pages.assert_not_called()
                    window._refresh_theme_ui.assert_not_called()
                    window._toast.assert_called_once()

                    self.client.BRIDGE.payload.emit("video_breakdown_done", {
                        "job": "busy-theme-job",
                        "markdown": "# done",
                        "message": "分析完成",
                        "analysis": {
                            "validation": {"ok": True},
                            "transcript": {"failedRanges": []},
                        },
                    })
                    app.processEvents()
                    self.assertFalse(page._busy)

                    self.client.MainWindow.toggle_theme(window)

                    apply_theme.assert_called_once()
                    save_theme.assert_called_once()
                    window._rebuild_pages.assert_not_called()
                    window._refresh_theme_ui.assert_called_once()
            finally:
                if page is not None:
                    page.deleteLater()
                self.client.BRIDGE = previous_bridge
                del app

    def test_merge_transcription_retry_preserves_successes_and_replaces_failures(self):
        self.assertTrue(hasattr(self.client, "_merge_transcription_retry"))
        previous = {
            "status": "partial",
            "duration": 180.0,
            "truncated": False,
            "retryCount": 0,
            "chunks": [{
                "start": 0.0,
                "end": 60.0,
                "language": "zh-CN",
                "segments": [{"startSec": 0.0, "endSec": 1.0, "text": "第一段"}],
            }],
            "failedRanges": [{"start": 60.0, "end": 120.0, "code": "remote_timeout"}],
            "errors": [{"start": 60.0, "end": 120.0, "code": "remote_timeout"}],
        }
        retried = {
            "status": "ok",
            "chunks": [{
                "start": 60.0,
                "end": 120.0,
                "language": "zh-CN",
                "segments": [{"startSec": 0.0, "endSec": 1.0, "text": "第二段"}],
            }],
            "failedRanges": [],
            "errors": [],
        }

        merged = self.client._merge_transcription_retry(previous, retried)

        self.assertEqual(merged["status"], "ok")
        self.assertEqual(merged["retryCount"], 1)
        self.assertEqual(merged["failedRanges"], [])
        self.assertEqual(merged["errors"], [])
        self.assertIn("第一段", merged["text"])
        self.assertIn("第二段", merged["text"])

    def test_merge_transcription_retry_restores_matching_errors_with_failed_ranges(self):
        previous_error = {
            "start": 60.0,
            "end": 120.0,
            "code": "remote_timeout",
            "errorId": "err-old-timeout",
        }
        previous = {
            "status": "partial",
            "retryCount": 1,
            "chunks": [{
                "start": 0.0,
                "end": 60.0,
                "language": "zh-CN",
                "segments": [{"startSec": 0.0, "endSec": 1.0, "text": "已成功"}],
            }],
            "failedRanges": [dict(previous_error)],
            "errors": [dict(previous_error, detail="previous retry timed out")],
        }
        retried = {
            "status": "failed",
            "chunks": [],
            "failedRanges": [],
            "errors": [],
            "message": "重试未产生新分片结果。",
        }

        merged = self.client._merge_transcription_retry(previous, retried)

        self.assertEqual(merged["status"], "partial")
        self.assertEqual(merged["failedRanges"], [previous_error])
        self.assertEqual(merged["errors"], previous["errors"])
        self.assertEqual(merged["errors"][0]["errorId"], "err-old-timeout")

    def test_native_ui_has_breakdown_entry_points(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn("class VideoBreakdownPage(BasePage):", src)
        self.assertIn('self.b_break = QtWidgets.QPushButton("分解")', src)
        self.assertIn('("🔬 分解视频", lambda: VideoBreakdownPage())', src)
        self.assertIn('"video_breakdown_start"', src)

    def test_breakdown_page_accepts_direct_video_link_for_download_and_analysis(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn('self.link_input.setPlaceholderText("粘贴抖音/小红书视频链接，下载后自动分解")', src)
        self.assertIn('self.b_link_breakdown = QtWidgets.QPushButton("下载并分解")', src)
        self.assertIn("def start_link_breakdown(self):", src)
        self.assertIn('submit_local_task(pf + ".download"', src)
        self.assertIn('"video_breakdown_link_download"', src)
        self.assertIn('"video_breakdown_start"', src)

    def test_breakdown_link_platform_detection_respects_xhs_feature_gate(self):
        self.assertEqual(
            self.client._video_breakdown_platform_from_url("https://www.douyin.com/video/123"),
            "douyin",
        )
        with mock.patch.dict(
            os.environ,
            {"MATRIX_XHS_ENABLED": "0"},
            clear=False,
        ):
            self.assertEqual(
                self.client._video_breakdown_platform_from_url(
                    "https://www.xiaohongshu.com/explore/abc"
                ),
                "douyin",
            )
        with mock.patch.dict(
            os.environ,
            {"MATRIX_XHS_ENABLED": "1"},
            clear=False,
        ):
            self.assertEqual(
                self.client._video_breakdown_platform_from_url(
                    "https://www.xiaohongshu.com/explore/abc"
                ),
                "xhs",
            )
            self.assertEqual(
                self.client._video_breakdown_platform_from_url("https://xhslink.com/a/b"),
                "xhs",
            )

    def test_native_ui_has_transcription_retry_and_temp_cleanup(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn('self.b_retry = QtWidgets.QPushButton("重试转写")', src)
        self.assertIn("def retry_transcription(self):", src)
        self.assertIn("only_ranges=failed_ranges", src)
        self.assertIn("shutil.rmtree(tmp, ignore_errors=True)", src)

    def test_requests_do_not_disable_tls_verification(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertNotIn("verify=False", src)
        self.assertNotIn("verify = False", src)

    def test_native_ui_serializes_video_breakdown_jobs(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn("self._busy = False", src)
        self.assertIn("if self._busy:", src)
        self.assertIn("self._busy = True", src)

    def test_workflow_reference_analysis_wrapper_delegates_to_replacement_analysis(self):
        import replacement_analysis as replacement_analysis_module

        expected = {
            "analysis": {
                "platform": "douyin",
                "sourceUrl": "https://example.test/video/123",
                "videoPath": "E:/tmp/source.mp4",
                "meta": {"duration": 9.0},
            },
            "markdown": "# delegated",
            "message": "分析完成",
        }

        with tempfile.TemporaryDirectory() as td, mock.patch.object(
                replacement_analysis_module.ReplacementAnalysis,
                "analyze",
                return_value=expected) as analyze:
            result = self.client._workflow_analyze_reference_video(
                "E:/tmp/source.mp4",
                item={
                    "url": "https://example.test/video/123",
                    "platform": "douyin",
                },
                topic="测试主题",
                out_dir=td,
                progress=mock.Mock(),
            )

        self.assertEqual(result, expected)
        analyze.assert_called_once()
        self.assertEqual(analyze.call_args.args[0], "E:/tmp/source.mp4")
        self.assertEqual(analyze.call_args.kwargs["source_url"], "https://example.test/video/123")
        self.assertEqual(analyze.call_args.kwargs["platform"], "douyin")
        self.assertEqual(analyze.call_args.kwargs["out_dir"], td)

    def test_replacement_analysis_module_stays_qt_free(self):
        src = REPLACEMENT_ANALYSIS.read_text(encoding="utf-8")

        self.assertIn("class ReplacementAnalysis", src)
        self.assertNotIn("PySide6", src)
        self.assertNotIn("QtWidgets", src)
        self.assertNotIn("QtCore", src)


if __name__ == "__main__":
    unittest.main()
