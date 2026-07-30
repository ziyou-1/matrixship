import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "backend" / "utils" / "media_validation.py"


def load_module():
    if not MODULE_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("media_validation_under_test", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_test_video(path):
    import imageio_ffmpeg

    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


class MediaValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = load_module()

    def require_module(self):
        self.assertIsNotNone(self.media, "backend/utils/media_validation.py is missing")

    def test_html_named_mp4_is_rejected(self):
        self.require_module()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "video.mp4"
            path.write_text("<html><h1>403 Forbidden</h1></html>", encoding="utf-8")

            result = self.media.validate_video_file(str(path), "text/html")

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "download_unexpected_content_type")

    def test_html_body_is_rejected_even_with_video_content_type(self):
        self.require_module()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "video.mp4"
            path.write_text("<!doctype html><title>denied</title>", encoding="utf-8")

            result = self.media.validate_video_file(str(path), "video/mp4")

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "download_html_body")

    def test_valid_generated_mp4_reports_metadata(self):
        self.require_module()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "video.mp4"
            make_test_video(path)

            result = self.media.validate_video_file(str(path), "video/mp4")

        self.assertTrue(result["ok"])
        self.assertGreater(result["duration"], 0)
        self.assertEqual(result["width"], 320)
        self.assertEqual(result["height"], 240)
        self.assertTrue(result["hasVideo"])

    def test_truncated_mp4_with_parseable_metadata_is_rejected(self):
        self.require_module()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "video.mp4"
            make_test_video(path)
            complete = path.read_bytes()
            path.write_bytes(complete[:int(len(complete) * 0.9)])

            metadata = self.media.probe_media(str(path))
            result = self.media.validate_video_file(str(path), "video/mp4")

        self.assertTrue(metadata["hasVideo"])
        self.assertGreater(metadata["duration"], 0)
        self.assertEqual(metadata["width"], 320)
        self.assertEqual(metadata["height"], 240)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "media_decode_failed")

    def test_decode_timeout_budget_scales_with_duration_and_is_bounded(self):
        self.require_module()
        cases = (
            (10.0, 60),
            (120.0, 90),
            (100.2, 75.15),
            (1000.0, 600),
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "video.mp4"
            path.write_bytes(b"placeholder-video")
            for duration, expected in cases:
                metadata = {
                    "duration": duration,
                    "width": 320,
                    "height": 240,
                    "hasVideo": True,
                    "hasAudio": False,
                }
                with self.subTest(duration=duration), \
                        mock.patch.dict(os.environ, {"MEDIA_DECODE_TIMEOUT_SEC": ""}), \
                        mock.patch.object(self.media, "probe_media", return_value=metadata), \
                        mock.patch.object(
                            self.media.subprocess,
                            "run",
                            return_value=subprocess.CompletedProcess([], 0),
                        ) as run:
                    result = self.media.validate_video_file(
                        str(path),
                        "video/mp4",
                        ffmpeg_exe="ffmpeg",
                    )

                    self.assertTrue(result["ok"])
                    self.assertAlmostEqual(run.call_args.kwargs["timeout"], expected)

    def test_positive_decode_timeout_environment_value_takes_priority(self):
        self.require_module()
        metadata = {
            "duration": 1000.0,
            "width": 320,
            "height": 240,
            "hasVideo": True,
            "hasAudio": False,
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "video.mp4"
            path.write_bytes(b"placeholder-video")
            with mock.patch.dict(os.environ, {"MEDIA_DECODE_TIMEOUT_SEC": "37.5"}), \
                    mock.patch.object(self.media, "probe_media", return_value=metadata), \
                    mock.patch.object(
                        self.media.subprocess,
                        "run",
                        return_value=subprocess.CompletedProcess([], 0),
                    ) as run:
                result = self.media.validate_video_file(
                    str(path),
                    "video/mp4",
                    ffmpeg_exe="ffmpeg",
                )

        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args.kwargs["timeout"], 37.5)

    def test_invalid_or_non_positive_decode_timeout_environment_values_fall_back(self):
        self.require_module()
        for configured in ("invalid", "0", "-3", "nan", "inf"):
            with self.subTest(configured=configured), \
                    mock.patch.dict(os.environ, {"MEDIA_DECODE_TIMEOUT_SEC": configured}):
                timeout = self.media._decode_timeout_seconds(80.0)

                self.assertEqual(timeout, 60.0)

    def test_invalid_or_non_finite_duration_uses_safe_default_timeout(self):
        self.require_module()
        for duration in (None, "", "invalid", float("nan"), float("inf"), float("-inf")):
            with self.subTest(duration=duration), \
                    mock.patch.dict(os.environ, {"MEDIA_DECODE_TIMEOUT_SEC": ""}):
                try:
                    timeout = self.media._decode_timeout_seconds(duration)
                except Exception as exc:
                    self.fail(f"duration {duration!r} raised {type(exc).__name__}: {exc}")

                self.assertEqual(timeout, 60.0)

    def test_decode_timeout_returns_stable_error_code(self):
        self.require_module()
        metadata = {
            "duration": 120.0,
            "width": 320,
            "height": 240,
            "hasVideo": True,
            "hasAudio": False,
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "video.mp4"
            path.write_bytes(b"placeholder-video")
            timeout_error = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=90)
            with mock.patch.dict(os.environ, {"MEDIA_DECODE_TIMEOUT_SEC": ""}), \
                    mock.patch.object(self.media, "probe_media", return_value=metadata), \
                    mock.patch.object(
                        self.media.subprocess,
                        "run",
                        side_effect=timeout_error,
                    ) as run:
                result = self.media.validate_video_file(
                    str(path),
                    "video/mp4",
                    ffmpeg_exe="ffmpeg",
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "media_decode_timeout")
        self.assertEqual(run.call_args.kwargs["timeout"], 90)

    def test_decode_process_exception_returns_decode_failed(self):
        self.require_module()
        metadata = {
            "duration": 120.0,
            "width": 320,
            "height": 240,
            "hasVideo": True,
            "hasAudio": False,
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "video.mp4"
            path.write_bytes(b"placeholder-video")
            with mock.patch.object(self.media, "probe_media", return_value=metadata), \
                    mock.patch.object(
                        self.media.subprocess,
                        "run",
                        side_effect=OSError("decoder unavailable"),
                    ):
                result = self.media.validate_video_file(
                    str(path),
                    "video/mp4",
                    ffmpeg_exe="ffmpeg",
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "media_decode_failed")

    def test_decode_process_nonzero_exit_returns_decode_failed(self):
        self.require_module()
        metadata = {
            "duration": 120.0,
            "width": 320,
            "height": 240,
            "hasVideo": True,
            "hasAudio": False,
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "video.mp4"
            path.write_bytes(b"placeholder-video")
            with mock.patch.object(self.media, "probe_media", return_value=metadata), \
                    mock.patch.object(
                        self.media.subprocess,
                        "run",
                        return_value=subprocess.CompletedProcess([], 1),
                    ):
                result = self.media.validate_video_file(
                    str(path),
                    "video/mp4",
                    ffmpeg_exe="ffmpeg",
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "media_decode_failed")

    def test_missing_file_returns_structured_error(self):
        self.require_module()
        result = self.media.validate_video_file("/tmp/matrixship-no-such-video.mp4")

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "media_missing_file")

    def test_quarantine_preserves_file_and_reason(self):
        self.require_module()
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "video.mp4"
            source.write_bytes(b"bad-video")
            root = Path(td) / "quarantine"

            target = Path(self.media.quarantine_file(str(source), str(root), "material-1", "html_body"))

            self.assertFalse(source.exists())
            self.assertTrue(target.is_file())
            self.assertEqual(target.read_bytes(), b"bad-video")
            self.assertTrue((target.parent / "metadata.json").is_file())

    def test_cleanup_quarantine_removes_only_expired_directories(self):
        self.require_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / "m1" / "old"
            fresh = root / "m2" / "fresh"
            old.mkdir(parents=True)
            fresh.mkdir(parents=True)
            (old / "video.mp4").write_bytes(b"old")
            (fresh / "video.mp4").write_bytes(b"fresh")
            expired = time.time() - (9 * 86400)
            os.utime(old, (expired, expired))

            removed = self.media.cleanup_quarantine(str(root), retention_days=7)

            self.assertEqual(removed, 1)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())


if __name__ == "__main__":
    unittest.main()
