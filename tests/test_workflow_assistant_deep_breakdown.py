import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_client():
    spec = importlib.util.spec_from_file_location(
        "matrix_native_client_for_workflow_deep_breakdown", CLIENT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorkflowAssistantDeepBreakdownTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client()

    def test_transcription_defaults_to_full_source_duration(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "long-reference.mp4"
            chunk = Path(td) / "chunk-000.mp3"
            video.write_bytes(b"video")
            chunk.write_bytes(b"audio")
            exported = {
                "status": "ok",
                "chunks": [{"start": 0.0, "end": 60.0, "path": str(chunk)}],
                "failedRanges": [],
                "errors": [],
                "duration": 1086.0,
                "limit": 1086.0,
                "truncated": False,
            }
            remote = {
                "status": "ok",
                "chunks": [{
                    "start": 0.0,
                    "end": 60.0,
                    "language": "zh-CN",
                    "segments": [{
                        "startSec": 0.0,
                        "endSec": 2.0,
                        "text": "完整视频口播",
                    }],
                }],
                "segments": [{
                    "startSec": 0.0,
                    "endSec": 2.0,
                    "text": "完整视频口播",
                }],
                "text": "[00:00.000-00:02.000] 完整视频口播",
                "failedRanges": [],
                "errors": [],
            }
            with mock.patch.dict(os.environ, {"VIDEO_TRANSCRIBE_MAX_SEC": ""}, clear=False), \
                    mock.patch.object(self.client, "export_audio_chunks", return_value=exported) as export, \
                    mock.patch.object(self.client, "transcribe_audio_chunks", return_value=remote), \
                    mock.patch.object(self.client, "lk888_config", return_value={
                        "base_url": "http://127.0.0.1:9080/lk888",
                        "api_key": "session-token",
                    }), \
                    mock.patch.object(self.client, "_lk_proxies", return_value=None):
                result = self.client._transcribe_breakdown_audio(
                    str(video), out_dir=str(Path(td) / "audio")
                )

        self.assertEqual(result["duration"], 1086.0)
        self.assertEqual(result["transcribedThroughSec"], 1086.0)
        self.assertFalse(result["truncated"])
        self.assertIsNone(export.call_args.kwargs["max_sec"])

    def test_workflow_reference_analysis_returns_full_structured_breakdown(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "reference.mp4"
            frame = Path(td) / "frame.jpg"
            video.write_bytes(b"video")
            frame.write_bytes(b"frame")
            analysis = {
                "meta": {"duration": 1086.0, "width": 720, "height": 1280},
                "ocr": {"status": "ok", "text": "屏幕字幕"},
                "transcript": {
                    "status": "ok",
                    "text": "[00:00.000-00:02.000] 完整视频口播",
                    "segments": [{
                        "startSec": 0.0,
                        "endSec": 2.0,
                        "text": "完整视频口播",
                    }],
                    "failedRanges": [],
                },
                "visual": "人物和场景完整分析",
                "frameNotes": "[1.00s] frame.jpg",
                "report": "## 内容总览\n完整报告",
            }
            with mock.patch.object(self.client, "_breakdown_source_validation", return_value={
                "ok": True,
                "duration": 1086.0,
                "width": 720,
                "height": 1280,
            }), \
                    mock.patch.object(self.client, "_extract_breakdown_frames", return_value=[{
                        "time": 1.0,
                        "path": str(frame),
                    }]), \
                    mock.patch.object(self.client, "_ocr_breakdown_frames", return_value=analysis["ocr"]), \
                    mock.patch.object(self.client, "_transcribe_breakdown_audio",
                                      return_value=analysis["transcript"]), \
                    mock.patch.object(self.client, "lk888_vision", return_value=analysis["visual"]) as vision, \
                    mock.patch.object(self.client, "_generate_video_breakdown_report",
                                      return_value=(analysis["report"], "分析完成")), \
                    mock.patch.object(self.client, "_video_breakdown_markdown",
                                      return_value="# 视频深度分解报告") as markdown:
                result = self.client._workflow_analyze_reference_video(
                    str(video),
                    item={"title": "参考视频"},
                    topic="热点话题",
                    out_dir=str(Path(td) / "job"),
                )

        self.assertEqual(result["analysis"]["meta"]["duration"], 1086.0)
        self.assertEqual(
            result["analysis"]["transcript"]["segments"][0]["text"],
            "完整视频口播",
        )
        self.assertEqual(result["markdown"], "# 视频深度分解报告")
        vision.assert_called_once()
        self.assertTrue(vision.call_args.args[1][0].startswith("data:image/"))
        markdown.assert_called_once()

    def test_breakdown_markdown_keeps_full_timestamped_transcript(self):
        markdown = self.client._video_breakdown_markdown({
            "meta": {"duration": 1086.0, "width": 720, "height": 1280},
            "ocr": {"status": "ok", "text": ""},
            "transcript": {
                "status": "ok",
                "text": (
                    "[00:00.000-00:02.000] 第一段完整台词。\n"
                    "[18:00.000-18:04.000] 末尾完整台词。"
                ),
                "segments": [
                    {"startSec": 0.0, "endSec": 2.0, "text": "第一段完整台词。"},
                    {"startSec": 1080.0, "endSec": 1084.0, "text": "末尾完整台词。"},
                ],
                "failedRanges": [],
            },
            "report": "## 内容总览\n仅摘要",
        })

        self.assertIn("## 完整口播时间轴", markdown)
        self.assertIn("[00:00.000-00:02.000] 第一段完整台词。", markdown)
        self.assertIn("[18:00.000-18:04.000] 末尾完整台词。", markdown)

    def test_breakdown_markdown_reports_actual_explicit_transcription_limit(self):
        markdown = self.client._video_breakdown_markdown({
            "meta": {"duration": 1086.0},
            "transcript": {
                "status": "partial",
                "truncated": True,
                "duration": 1086.0,
                "transcribedThroughSec": 900.0,
                "text": "[00:00.000-00:02.000] 仅用于范围显示",
            },
            "report": "## 内容总览\n报告",
        })

        self.assertIn("0 至 900.0 秒", markdown)
        self.assertIn("原视频 1086.0 秒", markdown)
        self.assertNotIn("前 10 分钟", markdown)

    def test_assistant_replacement_payload_prefers_structured_transcript_segments(self):
        with tempfile.TemporaryDirectory() as td:
            video = os.path.join(td, "reference.mp4")
            text_path = os.path.join(td, "reference.txt")
            Path(video).write_bytes(b"video")
            Path(text_path).write_text(
                "## 内容总览\n完整报告\n## 字幕与口播\n完整视频口播",
                encoding="utf-8",
            )
            structured = {
                "meta": {"duration": 12.0, "path": video},
                "visual": "完整画面分析",
                "transcript": {
                    "status": "ok",
                    "text": "第一段\n第二段",
                    "segments": [
                        {"startSec": 0.0, "endSec": 4.0, "text": "第一段"},
                        {"startSec": 4.0, "endSec": 8.0, "text": "第二段"},
                    ],
                    "failedRanges": [],
                },
            }
            payloads = self.client._assistant_reference_replacement_payloads({
                "platform": "douyin",
                "referenceArtifacts": [video],
                "referenceTextArtifacts": {video: text_path},
                "referenceAnalyses": {video: structured},
                "collected": [{
                    "title": "参考视频",
                    "work_url": "https://www.douyin.com/video/1",
                }],
            })

        segments = payloads[0]["breakdownAnalysis"]["transcript"]["segments"]
        self.assertEqual(
            segments,
            [
                {"startSec": 0.0, "endSec": 4.0, "text": "第一段"},
                {"startSec": 4.0, "endSec": 8.0, "text": "第二段"},
            ],
        )
        self.assertEqual(
            payloads[0]["breakdownAnalysis"]["meta"]["duration"],
            12.0,
        )

    def test_reference_breakdown_text_parses_timestamped_transcript_lines(self):
        text = (
            "[00:00.000-00:02.000] 台词：先说结论，这条视频为什么能留住人。\n"
            "[00:02.000-00:05.500] 台词/字幕：第二段补充产品证据和使用场景。\n"
        )

        segments = self.client._reference_breakdown_text_to_transcript_segments(text)

        self.assertEqual(
            [
                {"startSec": 0.0, "endSec": 2.0, "text": "先说结论，这条视频为什么能留住人。"},
                {"startSec": 2.0, "endSec": 5.5, "text": "第二段补充产品证据和使用场景。"},
            ],
            segments,
        )

    def test_asset_persists_text_and_structured_breakdown_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / "reference.mp4"
            text = root / "reference.txt"
            analysis = root / "reference-analysis.json"
            assets_dir = root / "assets"
            video.write_bytes(b"video")
            text.write_text("镜头 1｜开场｜2秒\n台词：先说结论。", encoding="utf-8")
            analysis.write_text(
                '{"meta":{"duration":5.5},"transcript":{"segments":[]}}',
                encoding="utf-8",
            )
            assets_dir.mkdir()

            with mock.patch.object(self.client, "_assets_dir", return_value=str(assets_dir)), \
                    mock.patch.object(self.client, "_assets_path", return_value=str(root / "assets.json")), \
                    mock.patch.object(self.client, "save_assets"), \
                    mock.patch.object(self.client, "ASSETS", []):
                asset = self.client.add_asset(
                    str(video),
                    kind="video",
                    source="采集参考视频",
                    category="采集参考视频",
                    text_path=str(text),
                    breakdown_path=str(text),
                    analysis_path=str(analysis),
                )

            self.assertTrue(asset)
            self.assertTrue(os.path.isfile(asset["breakdownPath"]))
            self.assertTrue(os.path.isfile(asset["breakdownAnalysisPath"]))
            self.assertEqual(
                '{"meta":{"duration":5.5},"transcript":{"segments":[]}}',
                Path(asset["breakdownAnalysisPath"]).read_text(encoding="utf-8"),
            )

    def test_library_passes_structured_analysis_sidecar_to_asset_registration(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "reference.mp4"
            text = Path(td) / "reference.txt"
            analysis = Path(td) / "reference-analysis.json"
            video.write_bytes(b"video")
            text.write_text("完整拆解文本", encoding="utf-8")
            analysis.write_text("{}", encoding="utf-8")
            add_asset = mock.Mock(return_value={"id": "asset"})
            ctx = {
                "topic": "Toyota",
                "artifacts": [],
                "referenceArtifacts": [str(video)],
                "referenceTextArtifacts": {str(video): str(text)},
                "referenceAnalysisArtifacts": {str(video): str(analysis)},
                "referenceThumbnails": {},
            }

            with mock.patch.object(
                    self.client,
                    "_workflow_ensure_reference_text_artifacts",
                    return_value={str(video): str(text)}), \
                    mock.patch.object(self.client, "add_asset", add_asset):
                summary = self.client._exec_library({"cap": "library", "params": {}}, ctx)

            self.assertIn("采集参考视频 1/1", summary)
            self.assertEqual(str(analysis), add_asset.call_args.kwargs["analysis_path"])


if __name__ == "__main__":
    unittest.main()
