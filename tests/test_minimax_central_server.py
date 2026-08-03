import json
from contextlib import contextmanager
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import central_server


GENERATE_PATH = "/api/v1/minimax/video/generate"
TASK_PATH = "/api/v1/minimax/video/tasks/task-123"
RESPONSE_FIELDS = {
    "businessTaskId",
    "providerTaskId",
    "requestedModel",
    "actualModel",
    "mode",
    "duration",
    "resolution",
    "billingRef",
    "status",
}


@contextmanager
def running_central_server():
    server = central_server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        central_server.Handler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request_json(base_url, path, payload=None, headers=None):
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(
        base_url + path,
        data=body,
        headers=request_headers,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def valid_payload():
    return {
        "prompt": "walk through a station",
        "duration": 4,
        "resolution": "768P",
    }


class MiniMaxCentralServerContractTest(unittest.TestCase):
    def authenticated_headers(self):
        return {
            "Authorization": "Bearer test-session-token",
            "X-Matrix-Org-Id": "org-default",
        }

    def test_generate_requires_authentication(self):
        with running_central_server() as base_url:
            status, payload = request_json(base_url, GENERATE_PATH, valid_payload())

        self.assertEqual(status, 401)
        self.assertEqual(payload.get("error"), "not_authenticated")

    def test_generate_rejects_when_minimax_is_disabled(self):
        client = Mock()
        with patch.object(
            central_server,
            "current_user",
            return_value={"id": "user-1", "_authType": "session"},
        ):
            with patch.object(central_server, "MINIMAX_ENABLED", False):
                with patch.object(central_server, "MiniMaxDirectClient", return_value=client):
                    with running_central_server() as base_url:
                        status, payload = request_json(
                            base_url,
                            GENERATE_PATH,
                            valid_payload(),
                            self.authenticated_headers(),
                        )

        self.assertEqual(status, 503)
        self.assertEqual(payload.get("error"), "minimax_disabled")
        self.assertIn("errorId", payload)
        client.submit_video.assert_not_called()

    def test_generate_rejects_when_center_key_is_missing(self):
        client = Mock()
        with patch.object(
            central_server,
            "current_user",
            return_value={"id": "user-1", "_authType": "session"},
        ):
            with patch.object(central_server, "MINIMAX_ENABLED", True):
                with patch.object(central_server, "MINIMAX_CENTER_API_KEY", ""):
                    with patch.object(central_server, "MiniMaxDirectClient", return_value=client):
                        with running_central_server() as base_url:
                            status, payload = request_json(
                                base_url,
                                GENERATE_PATH,
                                valid_payload(),
                                self.authenticated_headers(),
                            )

        self.assertEqual(status, 503)
        self.assertEqual(payload.get("error"), "minimax_not_configured")
        client.submit_video.assert_not_called()

    def test_generate_rejects_when_active_task_limit_is_full(self):
        client = Mock()
        existing = {
            "task-1": {"status": "pending", "userId": "other-user"},
            "task-2": {"status": "processing", "userId": "other-user"},
        }
        with patch.object(
            central_server,
            "current_user",
            return_value={"id": "user-1", "_authType": "session"},
        ):
            with patch.object(central_server, "MINIMAX_ENABLED", True):
                with patch.object(central_server, "MINIMAX_CENTER_API_KEY", "center-key"):
                    with patch.object(central_server, "MINIMAX_MAX_ACTIVE_TASKS", 2):
                        with patch.dict(
                            central_server.STATE.setdefault("minimax_pending_charges", {}),
                            existing,
                            clear=True,
                        ):
                            with patch.object(central_server, "MiniMaxDirectClient", return_value=client):
                                with running_central_server() as base_url:
                                    status, payload = request_json(
                                        base_url,
                                        GENERATE_PATH,
                                        valid_payload(),
                                        self.authenticated_headers(),
                                    )

        self.assertEqual(status, 429)
        self.assertEqual(payload.get("error"), "minimax_concurrency_limit")
        client.submit_video.assert_not_called()

    def test_generate_rejects_missing_prompt(self):
        body = valid_payload()
        body.pop("prompt")

        with patch.object(
            central_server,
            "current_user",
            return_value={"id": "user-1", "_authType": "session"},
        ):
            with running_central_server() as base_url:
                status, payload = request_json(
                    base_url,
                    GENERATE_PATH,
                    body,
                    self.authenticated_headers(),
                )

        self.assertEqual(status, 400)
        self.assertIn("prompt", str(payload).lower())

    def test_content_rejects_local_path_before_provider_submission(self):
        body = {
            "prompt": "move",
            "duration": 4,
            "resolution": "768P",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": r"C:\temp\start.png"},
                }
            ],
        }

        with patch.object(
            central_server,
            "current_user",
            return_value={"id": "user-1", "_authType": "session"},
        ):
            with patch.object(central_server, "MiniMaxDirectClient", create=True) as client_type:
                with running_central_server() as base_url:
                    status, payload = request_json(
                        base_url,
                        GENERATE_PATH,
                        body,
                        self.authenticated_headers(),
                    )

        self.assertEqual(status, 400)
        self.assertIn("public", str(payload).lower())
        client_type.assert_not_called()

    def test_content_must_be_an_array(self):
        body = {
            "prompt": "walk through a station",
            "duration": 4,
            "resolution": "768P",
            "content": {"type": "image_url"},
        }

        with patch.object(
            central_server,
            "current_user",
            return_value={"id": "user-1", "_authType": "session"},
        ):
            with running_central_server() as base_url:
                status, payload = request_json(
                    base_url,
                    GENERATE_PATH,
                    body,
                    self.authenticated_headers(),
                )

        self.assertEqual(status, 400)
        self.assertIn("content", str(payload).lower())

    def test_valid_request_reaches_injected_minimax_client(self):
        client = Mock()
        client.submit_video.return_value = "provider-task-123"

        with patch.object(
            central_server,
            "current_user",
            return_value={"id": "user-1", "_authType": "session"},
        ):
            with patch.object(central_server, "MINIMAX_ENABLED", True):
                with patch.object(central_server, "MINIMAX_CENTER_API_KEY", "center-key"):
                    with patch.object(
                        central_server,
                        "MiniMaxDirectClient",
                        return_value=client,
                        create=True,
                    ):
                        with patch.dict(
                            central_server.STATE.setdefault("minimax_pending_charges", {}),
                            {},
                            clear=True,
                        ):
                            with running_central_server() as base_url:
                                status, payload = request_json(
                                    base_url,
                                    GENERATE_PATH,
                                    valid_payload(),
                                    self.authenticated_headers(),
                                )

        self.assertIn(status, (200, 201, 202))
        client.submit_video.assert_called_once()
        self.assertEqual(payload["providerTaskId"], "provider-task-123")

    def test_generation_response_exposes_provider_trace_fields(self):
        response = {
            "ok": True,
            "businessTaskId": "business-task-123",
            "providerTaskId": "provider-task-123",
            "requestedModel": "MiniMax H3",
            "actualModel": "MiniMax-H3",
            "mode": "video_generation",
            "duration": 4,
            "resolution": "768P",
            "billingRef": "minimax:center:business-task-123:provider-task-123",
            "status": "awaiting_actual_cost",
        }

        self.assertTrue(RESPONSE_FIELDS.issubset(response))

        with patch.dict(
            central_server.STATE.setdefault("minimax_pending_charges", {}),
            {
                "task-123": dict(
                    response,
                    userId="user-1",
                    orgId="org-default",
                    traceId="trace-123",
                )
            },
            clear=True,
        ):
            with patch.object(
                central_server,
                "current_user",
                return_value={"id": "user-1", "_authType": "session"},
            ):
                with running_central_server() as base_url:
                    status, payload = request_json(
                        base_url,
                        TASK_PATH,
                        headers=self.authenticated_headers(),
                    )

        self.assertEqual(status, 200)
        self.assertTrue(RESPONSE_FIELDS.issubset(payload))

    def test_task_status_polls_official_provider_and_records_result_url_without_charge(self):
        client = Mock()
        client.poll_video.return_value = {
            "status": "success",
            "task": {
                "content": {
                    "url": "https://assets.test/final.mp4",
                }
            },
        }
        client.retrieve_video.return_value = "https://assets.test/final.mp4"
        record = {
            "businessTaskId": "task-123",
            "providerTaskId": "provider-task-123",
            "requestedModel": "MiniMax H3",
            "actualModel": "MiniMax-H3",
            "mode": "video_generation",
            "duration": 4,
            "resolution": "768P",
            "billingRef": "minimax:center:task-123:provider-task-123",
            "status": "pending",
            "userId": "user-1",
            "orgId": "org-default",
            "traceId": "trace-123",
        }

        with patch.dict(
            central_server.STATE.setdefault("minimax_pending_charges", {}),
            {"task-123": record},
            clear=True,
        ):
            with patch.object(
                central_server,
                "current_user",
                return_value={"id": "user-1", "_authType": "session"},
            ):
                with patch.object(central_server, "MINIMAX_CENTER_API_KEY", "center-key"):
                    with patch.object(
                        central_server,
                        "MiniMaxDirectClient",
                        return_value=client,
                        create=True,
                    ):
                        with running_central_server() as base_url:
                            status, payload = request_json(
                                base_url,
                                TASK_PATH,
                                headers=self.authenticated_headers(),
                            )

        self.assertEqual(status, 200)
        client.poll_video.assert_called_once_with("provider-task-123")
        client.retrieve_video.assert_called_once_with(client.poll_video.return_value)
        self.assertEqual(payload.get("status"), "awaiting_actual_cost")
        self.assertEqual(payload.get("resultUrl"), "https://assets.test/final.mp4")
        self.assertNotIn("amount", payload)

    def test_task_status_preserves_failed_and_awaiting_actual_cost_without_charge(self):
        records = {
            "failed-task": {
                "businessTaskId": "business-failed",
                "providerTaskId": "provider-failed",
                "requestedModel": "MiniMax H3",
                "actualModel": "MiniMax-H3",
                "mode": "video_generation",
                "duration": 4,
                "resolution": "768P",
                "billingRef": "minimax:center:business-failed:provider-failed",
                "status": "failed",
                "userId": "user-1",
                "orgId": "org-default",
                "traceId": "trace-failed",
            },
            "cost-task": {
                "businessTaskId": "business-cost",
                "providerTaskId": "provider-cost",
                "requestedModel": "MiniMax H3",
                "actualModel": "MiniMax-H3",
                "mode": "video_generation",
                "duration": 4,
                "resolution": "768P",
                "billingRef": "minimax:center:business-cost:provider-cost",
                "status": "awaiting_actual_cost",
                "userId": "user-1",
                "orgId": "org-default",
                "traceId": "trace-cost",
            },
        }
        with patch.dict(
            central_server.STATE.setdefault("minimax_pending_charges", {}),
            records,
            clear=True,
        ):
            with patch.object(
                central_server,
                "current_user",
                return_value={"id": "user-1", "_authType": "session"},
            ):
                with running_central_server() as base_url:
                    failed_status, failed = request_json(
                        base_url,
                        "/api/v1/minimax/video/tasks/failed-task",
                        headers=self.authenticated_headers(),
                    )
                    cost_status, cost = request_json(
                        base_url,
                        "/api/v1/minimax/video/tasks/cost-task",
                        headers=self.authenticated_headers(),
                    )

        self.assertEqual(failed_status, 200)
        self.assertEqual(failed.get("status"), "failed")
        self.assertEqual(cost_status, 200)
        self.assertEqual(cost.get("status"), "awaiting_actual_cost")
        self.assertNotIn("amount", failed)
        self.assertNotIn("amount", cost)

    def test_openapi_documents_new_minimax_generate_contract(self):
        document = yaml.safe_load(
            (ROOT / "docs" / "openapi.yaml").read_text(encoding="utf-8")
        )

        self.assertIn(GENERATE_PATH, document["paths"])
        operation = document["paths"][GENERATE_PATH]["post"]
        request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        response_schema = operation["responses"]["202"]["content"]["application/json"]["schema"]

        self.assertEqual(
            request_schema,
            {"$ref": "#/components/schemas/MiniMaxVideoGenerateRequest"},
        )
        self.assertEqual(
            response_schema,
            {"$ref": "#/components/schemas/MiniMaxVideoTaskResponse"},
        )
        response_properties = document["components"]["schemas"][
            "MiniMaxVideoTaskResponse"
        ]["properties"]
        request_properties = document["components"]["schemas"][
            "MiniMaxVideoGenerateRequest"
        ]["properties"]
        self.assertTrue(RESPONSE_FIELDS.issubset(response_properties))
        self.assertIn("/api/v1/minimax/video/tasks/{task_id}", document["paths"])
        self.assertIn("awaiting_actual_cost", response_properties["status"]["enum"])
        self.assertNotIn("const", request_properties["model"])
        self.assertIn("resultUrl", response_properties)
        self.assertIn("providerResultUrl", response_properties)


if __name__ == "__main__":
    unittest.main()
