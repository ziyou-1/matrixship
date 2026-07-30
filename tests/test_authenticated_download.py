from concurrent.futures import ThreadPoolExecutor
import importlib
import inspect
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import warnings


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class FakeAuth:
    cookie = {"sessionid": "cookie-value"}


class FakeResponse:
    def __init__(self, status_code=206, content_type="video/mp4", body=b"video-bytes"):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.body = body
        self.close_count = 0

    def iter_content(self, chunk_size=1024):
        del chunk_size
        yield self.body

    def close(self):
        self.close_count += 1


class CapturingLogger:
    def __init__(self):
        self.rows = []

    def error(self, value):
        self.rows.append(value)


def part_files(path):
    return list(Path(path).glob("*.part"))


def load_data_util():
    return importlib.import_module("utils.data_util")


class AuthenticatedDownloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_util = load_data_util()

    def require_new_download_contract(self):
        signature = inspect.signature(self.data_util.download_media)
        self.assertIn("auth", signature.parameters)
        self.assertIn("source_url", signature.parameters)
        self.assertTrue(hasattr(self.data_util, "MediaDownloadError"))
        self.assertTrue(hasattr(self.data_util, "validate_video_file"))

    def test_video_download_passes_auth_and_browser_headers(self):
        self.require_new_download_contract()
        captured = {}
        response = FakeResponse()

        def fake_get(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return response

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.data_util.requests, "get", side_effect=fake_get), \
                mock.patch.object(self.data_util, "validate_video_file", return_value={
                    "ok": True, "code": "ok", "duration": 1.0,
                    "width": 320, "height": 240, "hasVideo": True, "hasAudio": True,
                }):
            result = self.data_util.download_media(
                td,
                "video",
                "https://video.example/file.mp4?token=secret",
                "video",
                auth=FakeAuth(),
                source_url="https://www.douyin.com/video/1",
            )

            final_path = Path(td) / "video.mp4"
            self.assertTrue(final_path.is_file())
            self.assertEqual(part_files(td), [])

        self.assertEqual(captured["cookies"], FakeAuth.cookie)
        self.assertEqual(captured["headers"]["Referer"], "https://www.douyin.com/")
        self.assertEqual(captured["headers"]["Range"], "bytes=0-")
        self.assertIn("video/*", captured["headers"]["Accept"])
        self.assertTrue(captured["headers"]["User-Agent"])
        self.assertEqual(result["path"], str(final_path))
        self.assertEqual(response.close_count, 1)

    def test_success_response_is_closed_for_200_and_206(self):
        self.require_new_download_contract()
        for status in (200, 206):
            with self.subTest(status=status):
                response = FakeResponse(status_code=status)
                with tempfile.TemporaryDirectory() as td, \
                        mock.patch.object(self.data_util.requests, "get", return_value=response), \
                        mock.patch.object(self.data_util, "validate_video_file", return_value={
                            "ok": True, "code": "ok", "duration": 1.0,
                            "width": 320, "height": 240, "hasVideo": True, "hasAudio": False,
                        }):
                    result = self.data_util.download_media(
                        td, "video", "https://video.example/v.mp4", "video"
                    )

                    self.assertEqual(result["httpStatus"], status)
                    self.assertEqual(part_files(td), [])
                self.assertEqual(response.close_count, 1)

    def test_403_raises_typed_error_and_leaves_no_files(self):
        self.require_new_download_contract()
        response = FakeResponse(status_code=403, content_type="text/html", body=b"forbidden")
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            self.data_util.requests,
            "get",
            return_value=response,
        ), mock.patch.object(self.data_util, "json_log", return_value=""):
            with self.assertRaises(self.data_util.MediaDownloadError) as raised:
                self.data_util.download_media(
                    td, "video", "https://video.example/v.mp4", "video", auth=FakeAuth()
                )

            self.assertEqual(raised.exception.code, "download_http_403")
            self.assertFalse((Path(td) / "video.mp4").exists())
            self.assertEqual(part_files(td), [])
        self.assertEqual(response.close_count, 1)

    def test_http_error_closes_response_and_leaves_no_temp_files(self):
        self.require_new_download_contract()
        response = FakeResponse(status_code=500, content_type="text/plain", body=b"upstream error")
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.data_util.requests, "get", return_value=response), \
                mock.patch.object(self.data_util, "json_log", return_value=""):
            with self.assertRaises(self.data_util.MediaDownloadError) as raised:
                self.data_util.download_media(
                    td, "video", "https://video.example/v.mp4", "video", auth=FakeAuth()
                )

            self.assertEqual(raised.exception.code, "download_http_error")
            self.assertFalse((Path(td) / "video.mp4").exists())
            self.assertEqual(part_files(td), [])
        self.assertEqual(response.close_count, 1)

    def test_validation_rejection_preserves_existing_file_and_cleans_random_temp(self):
        self.require_new_download_contract()
        response = FakeResponse(body=b"downloaded-but-invalid")
        with tempfile.TemporaryDirectory() as td:
            final_path = Path(td) / "video.mp4"
            final_path.write_bytes(b"known-good")
            with mock.patch.object(self.data_util.requests, "get", return_value=response), \
                    mock.patch.object(self.data_util, "validate_video_file", return_value={
                        "ok": False, "code": "media_decode_failed", "path": "temporary-download",
                    }), mock.patch.object(self.data_util, "json_log", return_value=""):
                with self.assertRaises(self.data_util.MediaDownloadError) as raised:
                    self.data_util.download_media(
                        td, "video", "https://video.example/v.mp4", "video", auth=FakeAuth()
                    )

            self.assertEqual(raised.exception.code, "media_decode_failed")
            self.assertEqual(final_path.read_bytes(), b"known-good")
            self.assertEqual(part_files(td), [])
        self.assertEqual(response.close_count, 1)

    def test_stream_failure_preserves_existing_file_and_cleans_random_temp(self):
        self.require_new_download_contract()

        class FailingStreamResponse(FakeResponse):
            def iter_content(self, chunk_size=1024):
                del chunk_size
                yield b"partial-video"
                raise RuntimeError("stream interrupted")

        response = FailingStreamResponse()
        with tempfile.TemporaryDirectory() as td:
            final_path = Path(td) / "video.mp4"
            final_path.write_bytes(b"known-good")
            with mock.patch.object(self.data_util.requests, "get", return_value=response), \
                    mock.patch.object(self.data_util, "json_log", return_value=""):
                with self.assertRaises(self.data_util.MediaDownloadError) as raised:
                    self.data_util.download_media(
                        td, "video", "https://video.example/v.mp4", "video", auth=FakeAuth()
                    )

            self.assertEqual(raised.exception.code, "download_exception")
            self.assertEqual(final_path.read_bytes(), b"known-good")
            self.assertEqual(part_files(td), [])
        self.assertEqual(response.close_count, 1)

    def test_cleanup_failure_is_structured_and_preserves_business_error(self):
        self.require_new_download_contract()
        response = FakeResponse(body=b"invalid-video")
        captured_logger = CapturingLogger()
        cleanup_error = OSError(
            "cleanup blocked: https://files.example/remove?token=cleanup-secret&expires=123"
        )

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(self.data_util.requests, "get", return_value=response), \
                    mock.patch.object(self.data_util, "validate_video_file", return_value={
                        "ok": False, "code": "media_decode_failed",
                    }), mock.patch.object(self.data_util.os, "remove", side_effect=cleanup_error), \
                    mock.patch.object(self.data_util, "logger", captured_logger):
                with self.assertRaises(self.data_util.MediaDownloadError) as raised:
                    self.data_util.download_media(
                        td, "video", "https://video.example/v.mp4?token=request-secret", "video"
                    )

            payloads = [json.loads(row) for row in captured_logger.rows]
            cleanup_logs = [row for row in payloads if row.get("event") == "media_temp_cleanup_failed"]

            self.assertEqual(raised.exception.code, "media_decode_failed")
            self.assertEqual(len(cleanup_logs), 1)
            cleanup_log = cleanup_logs[0]
            self.assertTrue(cleanup_log["errorId"].startswith("err-"))
            self.assertIn("OSError", cleanup_log["stack"])
            self.assertTrue(cleanup_log["path"].endswith(".part"))
            self.assertNotIn("cleanup-secret", json.dumps(cleanup_log))
            self.assertNotIn("=123", json.dumps(cleanup_log))
        self.assertEqual(response.close_count, 1)

    def test_concurrent_downloads_use_unique_temp_files_and_serialize_publish(self):
        self.require_new_download_contract()
        state_lock = threading.Lock()
        validation_paths = []
        responses = []
        replace_lock_states = []
        active_validations = 0
        max_active_validations = 0
        real_replace = self.data_util.os.replace

        def fake_get(url, **kwargs):
            del kwargs
            response = FakeResponse(body=url.rsplit("/", 1)[-1].encode("ascii"))
            with state_lock:
                responses.append(response)
            return response

        def fake_validate(path, content_type):
            del content_type
            nonlocal active_validations, max_active_validations
            with state_lock:
                validation_paths.append(path)
                active_validations += 1
                max_active_validations = max(max_active_validations, active_validations)
            time.sleep(0.05)
            with state_lock:
                active_validations -= 1
            return {
                "ok": True, "code": "ok", "duration": 1.0,
                "width": 320, "height": 240, "hasVideo": True, "hasAudio": False,
            }

        def observed_replace(source, target):
            key = self.data_util.os.path.realpath(self.data_util.os.path.abspath(target))
            with self.data_util._FINAL_PATH_LOCKS_GUARD:
                entry = self.data_util._FINAL_PATH_LOCKS.get(key)
                lock_is_held = bool(entry and entry[0].locked())
            with state_lock:
                replace_lock_states.append(lock_is_held)
            return real_replace(source, target)

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.data_util.requests, "get", side_effect=fake_get), \
                mock.patch.object(self.data_util, "validate_video_file", side_effect=fake_validate), \
                mock.patch.object(self.data_util.os, "replace", side_effect=observed_replace):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        self.data_util.download_media,
                        td, "video", f"https://video.example/{suffix}", "video",
                    )
                    for suffix in ("first", "second")
                ]
                results = [future.result(timeout=5) for future in futures]

            final_path = Path(td) / "video.mp4"
            temp_files = [item for item in Path(td).iterdir() if item.name.endswith(".part")]

            self.assertTrue(final_path.is_file())
            self.assertIn(final_path.read_bytes(), {b"first", b"second"})
            self.assertEqual([result["path"] for result in results], [str(final_path)] * 2)
            self.assertEqual(len(validation_paths), 2)
            self.assertEqual(len(set(validation_paths)), 2)
            self.assertEqual(max_active_validations, 1)
            self.assertEqual(replace_lock_states, [True, True])
            self.assertEqual(temp_files, [])
            self.assertTrue(all(response.close_count == 1 for response in responses))
        self.assertEqual(self.data_util._FINAL_PATH_LOCKS, {})

    def test_concurrent_rejection_cleans_only_its_own_temp_file(self):
        self.require_new_download_contract()
        downloads_ready = threading.Barrier(2)
        validation_paths = []
        responses = []
        state_lock = threading.Lock()

        class CoordinatedResponse(FakeResponse):
            def iter_content(self, chunk_size=1024):
                del chunk_size
                downloads_ready.wait(timeout=5)
                yield self.body

        def fake_get(url, **kwargs):
            del kwargs
            response = CoordinatedResponse(body=url.rsplit("/", 1)[-1].encode("ascii"))
            with state_lock:
                responses.append(response)
            return response

        def fake_validate(path, content_type):
            del content_type
            with state_lock:
                validation_paths.append(path)
            if Path(path).read_bytes() == b"bad":
                return {"ok": False, "code": "media_decode_failed"}
            return {
                "ok": True, "code": "ok", "duration": 1.0,
                "width": 320, "height": 240, "hasVideo": True, "hasAudio": False,
            }

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.data_util.requests, "get", side_effect=fake_get), \
                mock.patch.object(self.data_util, "validate_video_file", side_effect=fake_validate), \
                mock.patch.object(self.data_util, "json_log", return_value=""):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        self.data_util.download_media,
                        td, "video", f"https://video.example/{suffix}", "video",
                    )
                    for suffix in ("good", "bad")
                ]
                outcomes = []
                for future in futures:
                    try:
                        outcomes.append(future.result(timeout=5))
                    except self.data_util.MediaDownloadError as exc:
                        outcomes.append(exc)

            final_path = Path(td) / "video.mp4"
            errors = [item for item in outcomes if isinstance(item, self.data_util.MediaDownloadError)]
            successes = [item for item in outcomes if isinstance(item, dict)]
            temp_files = [item for item in Path(td).iterdir() if item.name.endswith(".part")]

            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].code, "media_decode_failed")
            self.assertEqual(len(successes), 1)
            self.assertEqual(successes[0]["path"], str(final_path))
            self.assertEqual(final_path.read_bytes(), b"good")
            self.assertEqual(len(validation_paths), 2)
            self.assertEqual(len(set(validation_paths)), 2)
            self.assertEqual(temp_files, [])
            self.assertTrue(all(response.close_count == 1 for response in responses))
        self.assertEqual(self.data_util._FINAL_PATH_LOCKS, {})

    def test_api_refreshes_work_once_after_403(self):
        self.require_new_download_contract()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            warnings.simplefilter("ignore", SyntaxWarning)
            api_server = importlib.import_module("api_server")
        self.assertTrue(hasattr(api_server, "download_douyin_work_with_refresh"))
        first = {"work_id": "1", "video_addr": "https://video.example/expired"}
        second = {"work_id": "1", "video_addr": "https://video.example/fresh"}
        error = self.data_util.MediaDownloadError("download_http_403")

        with mock.patch.object(api_server.SPIDER, "spider_work", side_effect=[first, second]) as spider, \
                mock.patch.object(api_server, "download_work", side_effect=[error, "/tmp/saved"]) as download:
            work, save_path = api_server.download_douyin_work_with_refresh(
                FakeAuth(), "https://www.douyin.com/video/1", "all"
            )

        self.assertEqual(work, second)
        self.assertEqual(save_path, "/tmp/saved")
        self.assertEqual(spider.call_count, 2)
        self.assertEqual(download.call_count, 2)
        self.assertIs(download.call_args_list[0].kwargs["auth"], download.call_args_list[1].kwargs["auth"])


if __name__ == "__main__":
    unittest.main()
