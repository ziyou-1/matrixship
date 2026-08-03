from pathlib import Path
import tempfile
import unittest

from backend.utils.minimax_direct import (
    MiniMaxDirectClient,
    actual_model_for_mode,
    normalize_video_request,
)


class FakeProviderResponse:
    def __init__(self, payload=None, content=b"", content_type="video/mp4"):
        self.payload = payload
        self.content = content
        self.headers = {"Content-Type": content_type}

    def json(self):
        return self.payload


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "json": json,
                "timeout": timeout,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class MiniMaxH3NormalizationTest(unittest.TestCase):
    def test_h3_request_uses_fixed_model_and_preserves_multimodal_content(self):
        request = normalize_video_request(
            {
                "model": "some-client-label",
                "prompt": "walk through a station",
                "duration": 4,
                "resolution": "2K",
                "content": [
                    {"type": "text", "text": "A station at sunrise"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://assets.test/start.png"},
                    },
                ],
            }
        )

        self.assertEqual(actual_model_for_mode(None), "MiniMax-H3")
        self.assertEqual(request["model"], "MiniMax-H3")
        self.assertEqual(request["duration"], 4)
        self.assertEqual(request["resolution"], "2K")
        self.assertEqual(
            request["content"][1]["image_url"]["url"],
            "https://assets.test/start.png",
        )

    def test_h3_accepts_duration_four_through_fifteen_and_only_supported_resolutions(self):
        for duration in (4, 15):
            request = normalize_video_request(
                {
                    "prompt": "move",
                    "duration": duration,
                    "resolution": "768P",
                }
            )
            self.assertEqual(request["duration"], duration)

        with self.assertRaisesRegex(ValueError, "duration"):
            normalize_video_request(
                {"prompt": "move", "duration": 3, "resolution": "768P"}
            )
        with self.assertRaisesRegex(ValueError, "duration"):
            normalize_video_request(
                {"prompt": "move", "duration": 16, "resolution": "768P"}
            )
        with self.assertRaisesRegex(ValueError, "resolution"):
            normalize_video_request(
                {"prompt": "move", "duration": 4, "resolution": "1080P"}
            )

    def test_h3_rejects_local_and_data_urls_inside_content(self):
        for value in (r"C:\temp\start.png", "data:image/png;base64,abc"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "public"):
                    normalize_video_request(
                        {
                            "prompt": "move",
                            "duration": 4,
                            "resolution": "768P",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": value},
                                }
                            ],
                        }
                    )

    def test_h3_rejects_loopback_and_private_https_content_urls(self):
        for value in (
            "https://localhost/start.png",
            "https://127.0.0.1/start.png",
            "https://10.0.0.8/start.png",
            "https://169.254.10.20/start.png",
            "https://192.168.1.10/start.png",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "public"):
                    normalize_video_request(
                        {
                            "prompt": "move",
                            "duration": 4,
                            "resolution": "768P",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": value},
                                }
                            ],
                        }
                    )


class MiniMaxH3LifecycleTest(unittest.TestCase):
    def make_client(self, responses, timeout_sec=900):
        provider = FakeProvider(responses)
        client = MiniMaxDirectClient(
            base_url="https://api.minimaxi.com",
            api_key="test-key",
            timeout_sec=timeout_sec,
            poll_interval_sec=0,
            request_fn=provider.request,
        )
        return client, provider

    def valid_request(self):
        return {
            "prompt": "walk through a station",
            "duration": 4,
            "resolution": "768P",
            "content": [{"type": "text", "text": "A station at sunrise"}],
        }

    def test_client_requires_https_base_url(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            MiniMaxDirectClient(
                base_url="http://api.minimaxi.com",
                api_key="test-key",
                request_fn=FakeProvider([]).request,
            )

    def test_submit_poll_retrieve_and_download_complete_h3_lifecycle(self):
        client, provider = self.make_client(
            [
                FakeProviderResponse({"task_id": "h3-task-1"}),
                FakeProviderResponse({"status": "Pending"}),
                FakeProviderResponse(
                    {
                        "status": "Success",
                        "task_id": "h3-task-1",
                        "content": {"url": "https://cdn.test/h3-task-1.mp4"},
                    }
                ),
                FakeProviderResponse(content=b"fake-h3-mp4"),
            ]
        )

        provider_task_id = client.submit_video(self.valid_request())
        pending = client.poll_video(provider_task_id)
        success = client.poll_video(provider_task_id)
        file_url = client.retrieve_video(success)

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "result.mp4"
            metadata = client.download_video(file_url, destination)
            self.assertEqual(destination.read_bytes(), b"fake-h3-mp4")

        self.assertEqual(provider_task_id, "h3-task-1")
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(success["status"], "success")
        self.assertEqual(file_url, "https://cdn.test/h3-task-1.mp4")
        self.assertEqual(metadata["bytes"], len(b"fake-h3-mp4"))
        self.assertEqual(
            provider.calls[0]["url"],
            "https://api.minimaxi.com/v2/video_generation",
        )
        self.assertEqual(provider.calls[0]["json"]["model"], "MiniMax-H3")
        self.assertEqual(
            provider.calls[1]["url"],
            "https://api.minimaxi.com/v2/query/video_generation/h3-task-1",
        )
        self.assertEqual(provider.calls[0]["headers"]["Authorization"], "Bearer test-key")

    def test_submit_provider_error_is_reported_at_submit_stage(self):
        client, _provider = self.make_client(
            [FakeProviderResponse({"base_resp": {"status_code": 1004, "status_msg": "bad request"}})]
        )

        with self.assertRaisesRegex(RuntimeError, "submit"):
            client.submit_video(self.valid_request())

    def test_poll_provider_failure_is_reported_at_poll_stage(self):
        client, _provider = self.make_client(
            [FakeProviderResponse({"status": "Fail", "base_resp": {"status_msg": "safety"}})]
        )

        with self.assertRaisesRegex(RuntimeError, "poll"):
            client.poll_video("h3-task-failed")

    def test_retrieve_requires_https_task_content_url(self):
        client, _provider = self.make_client([])

        with self.assertRaisesRegex(ValueError, "HTTPS"):
            client.retrieve_video({"status": "success", "content": {"url": "http://cdn.test/video.mp4"}})

    def test_download_rejects_non_https_url(self):
        client, _provider = self.make_client([])

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                client.download_video("data:video/mp4;base64,abc", Path(temp_dir) / "video.mp4")

    def test_timeout_is_reported_after_configured_deadline(self):
        client, _provider = self.make_client([], timeout_sec=0)

        with self.assertRaisesRegex(TimeoutError, "timeout"):
            client.poll_video("h3-task-timeout")


if __name__ == "__main__":
    unittest.main()
