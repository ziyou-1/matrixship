# Review Package

## Base

`5e7915b0a8869e3dd19893a1150e0125029f9d33`

## Note

The workspace `.git` directory is read-only, so Task 1 has no commit range. The
following files are untracked additions created by the implementer:

- `tests/test_minimax_direct.py`
- `tests/test_minimax_pricing.py`
- `docs/superpowers/plans/2026-08-03-minimax-h3-direct-integration-task-1-report.md`

## tests/test_minimax_direct.py

```python
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


class MiniMaxDirectNormalizationTest(unittest.TestCase):
    def test_first_last_frame_maps_to_hailuo_02_and_keeps_two_frames(self):
        request = normalize_video_request(
            {
                "mode": "first_last_frame",
                "prompt": "walk through a station",
                "images": [
                    "https://assets.test/start.png",
                    "https://assets.test/end.png",
                ],
                "duration": 10,
                "resolution": "768P",
            }
        )

        self.assertEqual(actual_model_for_mode(request["mode"]), "MiniMax-Hailuo-02")
        self.assertEqual(
            request["images"],
            [
                "https://assets.test/start.png",
                "https://assets.test/end.png",
            ],
        )

    def test_text_to_video_and_image_to_video_use_hailuo_23(self):
        self.assertEqual(
            actual_model_for_mode("text_to_video"),
            "MiniMax-Hailuo-2.3",
        )
        self.assertEqual(
            actual_model_for_mode("image_to_video"),
            "MiniMax-Hailuo-2.3",
        )

    def test_image_to_video_rejects_local_paths_and_data_urls(self):
        for value in ("C:\\temp\\start.png", "data:image/png;base64,abc"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "public"):
                    normalize_video_request(
                        {
                            "mode": "image_to_video",
                            "prompt": "move",
                            "images": [value],
                        }
                    )


class MiniMaxDirectLifecycleTest(unittest.TestCase):
    def test_submit_poll_retrieve_and_download_complete_provider_lifecycle(self):
        provider = FakeProvider(
            [
                FakeProviderResponse({"task_id": "provider-task-1"}),
                FakeProviderResponse({"status": "pending"}),
                FakeProviderResponse({"status": "pending"}),
                FakeProviderResponse(
                    {
                        "status": "success",
                        "file_id": "file-1",
                    }
                ),
                FakeProviderResponse({"file_url": "https://cdn.test/file-1.mp4"}),
                FakeProviderResponse(content=b"fake-mp4-bytes"),
            ]
        )
        client = MiniMaxDirectClient(
            base_url="https://api.test",
            api_key="test-key",
            timeout_sec=900,
            poll_interval_sec=0,
            request_fn=provider.request,
        )
        request = normalize_video_request(
            {
                "mode": "text_to_video",
                "prompt": "walk through a station",
                "duration": 6,
                "resolution": "768P",
            }
        )

        provider_task_id = client.submit_video(request)
        first_poll = client.poll_video(provider_task_id)
        second_poll = client.poll_video(provider_task_id)
        success = client.poll_video(provider_task_id)
        file_url = client.retrieve_video(success)

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "result.mp4"
            metadata = client.download_video(file_url, destination)
            self.assertEqual(destination.read_bytes(), b"fake-mp4-bytes")

        self.assertEqual(provider_task_id, "provider-task-1")
        self.assertEqual(first_poll["status"], "pending")
        self.assertEqual(second_poll["status"], "pending")
        self.assertEqual(success["status"], "success")
        self.assertEqual(file_url, "https://cdn.test/file-1.mp4")
        self.assertEqual(metadata["path"], destination)
        self.assertEqual(metadata["bytes"], len(b"fake-mp4-bytes"))
        self.assertEqual(provider.calls[0]["headers"]["Authorization"], "Bearer test-key")

    def test_failure_status_raises_a_poll_stage_error(self):
        provider = FakeProvider(
            [
                FakeProviderResponse({"status": "failed", "error": "safety_rejected"}),
            ]
        )
        client = MiniMaxDirectClient(
            base_url="https://api.test",
            api_key="test-key",
            timeout_sec=900,
            poll_interval_sec=0,
            request_fn=provider.request,
        )

        with self.assertRaisesRegex(RuntimeError, "poll"):
            client.poll_video("provider-task-failed")

    def test_timeout_is_reported_after_configured_deadline(self):
        provider = FakeProvider([])
        client = MiniMaxDirectClient(
            base_url="https://api.test",
            api_key="test-key",
            timeout_sec=0,
            poll_interval_sec=0,
            request_fn=provider.request,
        )

        with self.assertRaisesRegex(TimeoutError, "timeout"):
            client.poll_video("provider-task-timeout")


if __name__ == "__main__":
    unittest.main()
```

## tests/test_minimax_pricing.py

```python
from decimal import Decimal
import unittest

from backend.utils.minimax_pricing import published_unit_price


class MiniMaxPublishedPricingTest(unittest.TestCase):
    def test_768p_six_second_video_uses_published_unit_price(self):
        self.assertEqual(
            published_unit_price(
                model="MiniMax-Hailuo-2.3",
                mode="text_to_video",
                duration=6,
                resolution="768P",
            ),
            Decimal("0.28"),
        )

    def test_first_last_frame_uses_hailuo_02_published_price(self):
        self.assertEqual(
            published_unit_price(
                model="MiniMax-Hailuo-02",
                mode="first_last_frame",
                duration=6,
                resolution="768P",
            ),
            Decimal("0.28"),
        )

    def test_unknown_published_price_returns_none(self):
        self.assertIsNone(
            published_unit_price(
                model="MiniMax-Hailuo-2.3",
                mode="text_to_video",
                duration=42,
                resolution="768P",
            )
        )


if __name__ == "__main__":
    unittest.main()
```

## Implementer Report

See:

`docs/superpowers/plans/2026-08-03-minimax-h3-direct-integration-task-1-report.md`
