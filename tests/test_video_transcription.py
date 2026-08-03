import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
MODULE_PATH = ROOT / "backend" / "utils" / "video_transcription.py"


def load_module():
    if not MODULE_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("video_transcription_under_test", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


def gemini_payload(transcript):
    return {
        "candidates": [{
            "content": {
                "parts": [{"text": json.dumps(transcript, ensure_ascii=False)}]
            }
        }]
    }


def gemini_text_payload(text):
    return {
        "candidates": [{
            "content": {
                "parts": [{"text": text}]
            }
        }]
    }


class VideoTranscriptionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transcription = load_module()

    def require_module(self):
        self.assertIsNotNone(
            self.transcription,
            "backend/utils/video_transcription.py is missing",
        )

    def test_chunk_ranges_are_60_seconds_and_truncated_at_600(self):
        self.require_module()
        short = self.transcription.build_chunk_ranges(125, chunk_sec=60, max_sec=600)
        long = self.transcription.build_chunk_ranges(720, chunk_sec=60, max_sec=600)

        self.assertEqual(short["ranges"], [
            {"start": 0.0, "end": 60.0},
            {"start": 60.0, "end": 120.0},
            {"start": 120.0, "end": 125.0},
        ])
        self.assertFalse(short["truncated"])
        self.assertEqual(long["ranges"][-1], {"start": 540.0, "end": 600.0})
        self.assertTrue(long["truncated"])

    def test_service_url_policy_allows_loopback_http_and_remote_https(self):
        self.require_module()

        for value in (
                "http://127.0.0.1:9080",
                "http://localhost:9080/lk888",
                "http://[::1]:9080",
                "https://central.example.com/api"):
            with self.subTest(value=value):
                self.assertEqual(self.transcription.validate_service_url(value), value)

    def test_service_url_policy_rejects_remote_http(self):
        self.require_module()

        for value in ("http://118.178.32.71:9080", "http://example.com/api"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "https"):
                    self.transcription.validate_service_url(value)

    def test_export_audio_chunks_uses_expected_ffmpeg_ranges(self):
        self.require_module()
        commands = []

        def fake_run(cmd, **kwargs):
            del kwargs
            commands.append(cmd)
            Path(cmd[-1]).write_bytes(b"mp3")

        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "video.mp4"
            video.write_bytes(b"fake")
            result = self.transcription.export_audio_chunks(
                str(video),
                str(Path(td) / "chunks"),
                chunk_sec=60,
                max_sec=600,
                probe_fn=lambda _path: {"duration": 125, "hasAudio": True},
                run_fn=fake_run,
                ffmpeg_exe="ffmpeg-test",
            )

        self.assertEqual(len(result["chunks"]), 3)
        self.assertEqual([row["start"] for row in result["chunks"]], [0.0, 60.0, 120.0])
        self.assertIn("-b:a", commands[0])
        self.assertIn("64k", commands[0])

    def test_export_audio_chunks_only_creates_requested_retry_ranges(self):
        self.require_module()
        commands = []

        def fake_run(cmd, **kwargs):
            del kwargs
            commands.append(cmd)
            Path(cmd[-1]).write_bytes(b"mp3")

        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "video.mp4"
            video.write_bytes(b"fake")
            result = self.transcription.export_audio_chunks(
                str(video),
                str(Path(td) / "chunks"),
                chunk_sec=60,
                max_sec=600,
                only_ranges=[{"start": 60.0, "end": 120.0}],
                probe_fn=lambda _path: {"duration": 180, "hasAudio": True},
                run_fn=fake_run,
                ffmpeg_exe="ffmpeg-test",
            )

        self.assertEqual(len(commands), 1)
        self.assertEqual(
            [(row["start"], row["end"]) for row in result["chunks"]],
            [(60.0, 120.0)],
        )

    def test_export_audio_chunks_keeps_successes_when_one_range_fails(self):
        self.require_module()

        def fake_run(cmd, **kwargs):
            del kwargs
            if cmd[cmd.index("-ss") + 1] == "60.000":
                raise subprocess.CalledProcessError(1, cmd, stderr=b"decode failed")
            Path(cmd[-1]).write_bytes(b"mp3")

        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "video.mp4"
            video.write_bytes(b"fake")
            result = self.transcription.export_audio_chunks(
                str(video),
                str(Path(td) / "chunks"),
                chunk_sec=60,
                max_sec=600,
                probe_fn=lambda _path: {"duration": 180, "hasAudio": True},
                run_fn=fake_run,
                ffmpeg_exe="ffmpeg-test",
            )

        self.assertEqual(result["status"], "partial")
        self.assertEqual([row["start"] for row in result["chunks"]], [0.0, 120.0])
        self.assertEqual(result["failedRanges"][0]["start"], 60.0)
        self.assertEqual(result["failedRanges"][0]["code"], "audio_export_failed")
        self.assertEqual(result["errors"], result["failedRanges"])
        self.assertTrue(result["failedRanges"][0]["errorId"].startswith("err-"))

    def test_export_audio_chunks_returns_failed_ranges_when_all_ranges_fail(self):
        self.require_module()

        def fake_run(cmd, **kwargs):
            del kwargs
            raise subprocess.TimeoutExpired(cmd, timeout=30)

        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "video.mp4"
            video.write_bytes(b"fake")
            result = self.transcription.export_audio_chunks(
                str(video),
                str(Path(td) / "chunks"),
                chunk_sec=60,
                max_sec=600,
                probe_fn=lambda _path: {"duration": 120, "hasAudio": True},
                run_fn=fake_run,
                ffmpeg_exe="ffmpeg-test",
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["chunks"], [])
        self.assertEqual(len(result["failedRanges"]), 2)
        self.assertEqual(
            {row["code"] for row in result["failedRanges"]},
            {"audio_export_timeout"},
        )

    def test_transcription_schema_is_strict(self):
        self.require_module()
        valid = self.transcription.validate_transcription_response({
            "language": "zh-CN",
            "segments": [{"startSec": 1.5, "endSec": 4.0, "text": "测试"}],
        })
        unknown = self.transcription.validate_transcription_response({
            "language": "zh-CN",
            "segments": [],
            "extra": True,
        })
        reversed_time = self.transcription.validate_transcription_response({
            "language": "zh-CN",
            "segments": [{"startSec": 5, "endSec": 4, "text": "测试"}],
        })

        self.assertTrue(valid["ok"])
        self.assertFalse(unknown["ok"])
        self.assertFalse(reversed_time["ok"])

    def test_merge_adds_chunk_offsets_to_timestamps(self):
        self.require_module()
        merged = self.transcription.merge_transcription_segments([{
            "start": 120.0,
            "end": 180.0,
            "language": "zh-CN",
            "segments": [{"startSec": 1.5, "endSec": 4.0, "text": "测试文本"}],
        }])

        self.assertEqual(merged["segments"][0]["startSec"], 121.5)
        self.assertEqual(merged["segments"][0]["endSec"], 124.0)
        self.assertIn("[02:01.500-02:04.000] 测试文本", merged["text"])

    def test_merge_transcription_segments_removes_adjacent_text_overlap(self):
        self.require_module()
        repeated = "就这个法汀妮的粉底液啊，我自用三四年了，真的巨好用。"
        merged = self.transcription.merge_transcription_segments([
            {
                "start": 0.0,
                "end": 60.0,
                "language": "zh-CN",
                "segments": [{
                    "startSec": 0.0,
                    "endSec": 8.0,
                    "text": "我想过它会卖69、59、49啊，但是没想到它居然能便宜到这个价格。" + repeated,
                }],
            },
            {
                "start": 60.0,
                "end": 120.0,
                "language": "zh-CN",
                "segments": [{
                    "startSec": 0.0,
                    "endSec": 8.0,
                    "text": repeated + "你们看它上脸这个流动性啊，特别的水润。",
                }],
            },
        ])

        texts = [row["text"] for row in merged["segments"]]
        self.assertEqual(texts[1], "你们看它上脸这个流动性啊，特别的水润。")
        self.assertEqual(merged["text"].count(repeated), 1)

    def test_remote_failures_retry_twice_and_return_partial(self):
        self.require_module()
        calls = []

        def request_fn(url, **kwargs):
            calls.append((url, kwargs))
            if len(calls) == 1:
                return FakeResponse(gemini_payload({
                    "language": "zh-CN",
                    "segments": [{"startSec": 0, "endSec": 2, "text": "第一段"}],
                }))
            raise TimeoutError("remote timeout")

        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "chunk_000.mp3"
            second = Path(td) / "chunk_060.mp3"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            result = self.transcription.transcribe_audio_chunks(
                [
                    {"start": 0.0, "end": 60.0, "path": str(first)},
                    {"start": 60.0, "end": 120.0, "path": str(second)},
                ],
                "http://127.0.0.1:9080/lk888",
                "session-token",
                "gemini-test",
                timeout=1,
                retries=2,
                request_fn=request_fn,
                sleep_fn=lambda _seconds: None,
            )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["failedRanges"]), 1)
        self.assertEqual(result["failedRanges"][0]["start"], 60.0)
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0][1]["headers"]["Authorization"], "Bearer session-token")
        self.assertIs(calls[0][1]["verify"], True)
        self.assertIn("第一段", result["text"])

    def test_real_non_json_text_uses_coarse_timestamps(self):
        self.require_module()

        def request_fn(_url, **_kwargs):
            return FakeResponse(gemini_text_payload("这是一段真实的口播文本。"))

        with tempfile.TemporaryDirectory() as td:
            chunk = Path(td) / "chunk.mp3"
            chunk.write_bytes(b"audio")
            result = self.transcription.transcribe_audio_chunks(
                [{"start": 60.0, "end": 120.0, "path": str(chunk)}],
                "http://127.0.0.1:9080/lk888",
                "session-token",
                "gemini-test",
                timeout=1,
                retries=0,
                request_fn=request_fn,
                sleep_fn=lambda _seconds: None,
            )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["coarseTimestamps"])
        self.assertEqual(result["segments"][0]["startSec"], 60.0)
        self.assertEqual(result["segments"][0]["endSec"], 120.0)
        self.assertIn("真实的口播文本", result["text"])

    def test_transcription_requests_can_tag_billing_stage(self):
        self.require_module()
        calls = []

        def request_fn(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(gemini_payload({
                "language": "zh-CN",
                "segments": [{"startSec": 0.0, "endSec": 1.0, "text": "测试口播"}],
            }))

        with tempfile.TemporaryDirectory() as td:
            chunk = Path(td) / "chunk.mp3"
            chunk.write_bytes(b"audio")
            result = self.transcription.transcribe_audio_chunks(
                [{"start": 0.0, "end": 60.0, "path": str(chunk)}],
                "http://127.0.0.1:9080/lk888",
                "session-token",
                "gemini-test",
                timeout=1,
                retries=0,
                request_fn=request_fn,
                sleep_fn=lambda _seconds: None,
                billing_context={
                    "scenario": "video_breakdown",
                    "stage": "audio_transcription",
                    "detail": "audio chunk 0.000-60.000",
                },
            )

        self.assertEqual(result["status"], "ok")
        headers = calls[0][1]["headers"]
        self.assertEqual(headers["X-Matrix-Billing-Scenario"], "video_breakdown")
        self.assertEqual(headers["X-Matrix-Billing-Stage"], "audio_transcription")
        self.assertEqual(headers["X-Matrix-Billing-Detail"], "audio chunk 0.000-60.000")

    def test_valid_schema_refusal_segment_is_marked_failed(self):
        self.require_module()

        def request_fn(_url, **_kwargs):
            return FakeResponse(gemini_payload({
                "language": "en-US",
                "segments": [{
                    "startSec": 0.0,
                    "endSec": 2.0,
                    "text": "I cannot transcribe this audio file.",
                }],
            }))

        with tempfile.TemporaryDirectory() as td:
            chunk = Path(td) / "chunk.mp3"
            chunk.write_bytes(b"audio")
            result = self.transcription.transcribe_audio_chunks(
                [{"start": 0.0, "end": 60.0, "path": str(chunk)}],
                "http://127.0.0.1:9080/lk888",
                "session-token",
                "gemini-test",
                timeout=1,
                retries=0,
                request_fn=request_fn,
                sleep_fn=lambda _seconds: None,
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["chunks"], [])
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["failedRanges"][0]["code"], "transcription_refused")

    def test_parseable_invalid_schema_json_is_not_coarse_transcript(self):
        self.require_module()

        def request_fn(_url, **_kwargs):
            return FakeResponse(gemini_text_payload(json.dumps({
                "error": "upstream returned no segments",
            })))

        with tempfile.TemporaryDirectory() as td:
            chunk = Path(td) / "chunk.mp3"
            chunk.write_bytes(b"audio")
            result = self.transcription.transcribe_audio_chunks(
                [{"start": 0.0, "end": 60.0, "path": str(chunk)}],
                "http://127.0.0.1:9080/lk888",
                "session-token",
                "gemini-test",
                timeout=1,
                retries=0,
                request_fn=request_fn,
                sleep_fn=lambda _seconds: None,
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["chunks"], [])
        self.assertEqual(result["segments"], [])
        self.assertFalse(result["coarseTimestamps"])

    def test_json_like_decode_failure_is_marked_invalid_json(self):
        self.require_module()

        for value in (
                '```json\n{"language":"zh-CN","segments":[\n```',
                '[{"startSec":0,"text":"broken"}',
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError, "transcription_invalid_json"):
                    self.transcription._parse_candidate(value, 60.0)

    def test_transcription_rejects_remote_http_before_request(self):
        self.require_module()
        calls = []

        def request_fn(_url, **_kwargs):
            calls.append(True)
            return FakeResponse()

        with self.assertRaisesRegex(ValueError, "https"):
            self.transcription.transcribe_audio_chunks(
                [],
                "http://remote.example.com/lk888",
                "session-token",
                "gemini-test",
                timeout=1,
                retries=0,
                request_fn=request_fn,
            )

        self.assertEqual(calls, [])

    def test_json_like_response_preserves_invalid_json_failure_code(self):
        self.require_module()

        def request_fn(_url, **_kwargs):
            return FakeResponse(gemini_text_payload('{"language":"zh-CN","segments":['))

        with tempfile.TemporaryDirectory() as td:
            chunk = Path(td) / "chunk.mp3"
            chunk.write_bytes(b"audio")
            result = self.transcription.transcribe_audio_chunks(
                [{"start": 0.0, "end": 60.0, "path": str(chunk)}],
                "http://127.0.0.1:9080/lk888",
                "session-token",
                "gemini-test",
                timeout=1,
                retries=0,
                request_fn=request_fn,
                sleep_fn=lambda _seconds: None,
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failedRanges"][0]["code"], "transcription_invalid_json")

    def test_obvious_refusal_is_retried_then_marked_failed(self):
        self.require_module()
        calls = []

        def request_fn(_url, **kwargs):
            calls.append(kwargs)
            return FakeResponse(gemini_text_payload(
                "I cannot transcribe this audio because I am unable to access it."
            ))

        with tempfile.TemporaryDirectory() as td:
            chunk = Path(td) / "chunk.mp3"
            chunk.write_bytes(b"audio")
            result = self.transcription.transcribe_audio_chunks(
                [{"start": 0.0, "end": 60.0, "path": str(chunk)}],
                "http://127.0.0.1:9080/lk888",
                "session-token",
                "gemini-test",
                timeout=1,
                retries=1,
                request_fn=request_fn,
                sleep_fn=lambda _seconds: None,
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["chunks"], [])
        self.assertEqual(result["failedRanges"][0]["code"], "transcription_refused")
        self.assertEqual(result["failedRanges"][0]["start"], 0.0)

    def test_chinese_ai_error_explanation_is_not_accepted_as_transcript(self):
        self.require_module()

        with self.assertRaisesRegex(RuntimeError, "transcription_refused"):
            self.transcription._parse_candidate(
                "作为 AI，我无法访问或转写该音频。",
                60.0,
            )

    def test_unable_to_error_explanation_is_not_accepted_as_transcript(self):
        self.require_module()

        with self.assertRaisesRegex(RuntimeError, "transcription_refused"):
            self.transcription._parse_candidate(
                "I am sorry, but I am unable to fulfill this transcription request.",
                60.0,
            )

    def test_english_transcription_explanation_is_not_accepted_as_transcript(self):
        self.require_module()

        with self.assertRaisesRegex(RuntimeError, "transcription_invalid_response"):
            self.transcription._parse_candidate(
                "**JSON Transcription of Chinese Video**\n"
                "Okay, so I need to create a JSON transcription for this short Chinese video.",
                60.0,
            )

    def test_only_ranges_retries_failed_chunk(self):
        self.require_module()
        calls = []

        def request_fn(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(gemini_payload({
                "language": "zh-CN",
                "segments": [{"startSec": 0, "endSec": 1, "text": "重试成功"}],
            }))

        with tempfile.TemporaryDirectory() as td:
            chunks = []
            for start in (0.0, 60.0, 120.0):
                path = Path(td) / ("chunk_%03d.mp3" % start)
                path.write_bytes(b"audio")
                chunks.append({"start": start, "end": start + 60.0, "path": str(path)})
            result = self.transcription.transcribe_audio_chunks(
                chunks,
                "http://127.0.0.1:9080/lk888",
                "session-token",
                "gemini-test",
                timeout=1,
                retries=0,
                only_ranges=[{"start": 60.0, "end": 120.0}],
                request_fn=request_fn,
                sleep_fn=lambda _seconds: None,
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["chunks"][0]["start"], 60.0)
        self.assertEqual(result["status"], "ok")


if __name__ == "__main__":
    unittest.main()
