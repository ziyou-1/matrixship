import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

import requests


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class FakeAuth:
    cookie = {
        "s_v_web_id": "verify-secret",
        "sessionid": "cookie-secret",
    }
    msToken = "ms-token-secret"


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.text = json.dumps(payload)
        self.status_code = status_code


class DouyinDetailRetryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("dy_apis.douyin_api")

    def _call(self, side_effect):
        with mock.patch.object(
            self.module.Params, "with_web_id", autospec=True,
            side_effect=lambda params, *_args, **_kwargs: params,
        ), mock.patch.object(
            self.module.Params, "with_a_bogus", autospec=True,
            side_effect=lambda params, *_args, **_kwargs: params,
        ), mock.patch.object(
            self.module.requests, "get", side_effect=side_effect,
        ) as request_get, mock.patch.object(
            self.module.time, "sleep",
        ) as sleep:
            result = self.module.DouyinAPI.get_work_info(
                FakeAuth(), "https://www.douyin.com/video/7664121621367812857"
            )
        return result, request_get, sleep

    def test_detail_request_retries_network_errors_with_bounded_timeout(self):
        result, request_get, sleep = self._call([
            requests.ConnectionError("temporary connection failure"),
            requests.Timeout("temporary read timeout"),
            FakeResponse({"aweme_detail": {"aweme_id": "7664121621367812857"}}),
        ])

        self.assertEqual(result["aweme_detail"]["aweme_id"], "7664121621367812857")
        self.assertEqual(request_get.call_count, 3)
        self.assertEqual(
            [call.kwargs.get("timeout") for call in request_get.call_args_list],
            [(8, 15), (8, 15), (8, 15)],
        )
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_detail_request_raises_stable_error_after_three_retries(self):
        failures = [
            requests.ConnectionError(
                "HTTPSConnectionPool(host='www.douyin.com'): "
                "https://www.douyin.com/aweme/v1/web/aweme/detail/?a_bogus=signed-secret"
            )
            for _ in range(4)
        ]

        with self.assertRaises(self.module.DouyinDetailNetworkError) as raised:
            self._call(failures)

        self.assertEqual(str(raised.exception), "douyin_detail_network_failed")
        self.assertEqual(raised.exception.attempts, 4)
        self.assertEqual(raised.exception.aweme_id, "7664121621367812857")
        self.assertEqual(raised.exception.cause_type, "ConnectionError")

    def test_detail_request_does_not_retry_http_application_response(self):
        result, request_get, sleep = self._call([
            FakeResponse({"status_code": 4, "status_msg": "invalid request"}, status_code=400),
        ])

        self.assertEqual(result["status_code"], 4)
        self.assertEqual(request_get.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
