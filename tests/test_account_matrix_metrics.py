import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SERVER = BACKEND / "central_server.py"
CLIENT = BACKEND / "matrix_native_client.py"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_server_module():
    spec = importlib.util.spec_from_file_location("central_server_account_metrics_under_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_client_module():
    spec = importlib.util.spec_from_file_location("matrix_native_client_account_metrics_under_test", CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AccountMatrixMetricsTest(unittest.TestCase):
    def setUp(self):
        self.server = load_server_module()
        self.state = {
            "organizations": [{"id": "org-a", "name": "Org A", "status": "active"}],
            "users": [{"id": "user-owner", "name": "Platform", "status": "active"}],
            "memberships": [
                {"id": "m-owner", "orgId": "org-a", "userId": "user-owner", "role": "owner", "status": "active"},
            ],
            "accountsRegistry": [
                {
                    "id": "node-1:douyin-main",
                    "localAccountId": "douyin-main",
                    "orgId": "org-a",
                    "platform": "douyin",
                    "online": True,
                    "cookieReady": True,
                    "fans": "1200",
                },
            ],
            "tasks": {},
            "events": [],
            "auditLogs": [],
            "nodes": {},
            "library": [],
            "kb": [],
            "queue": [],
            "sessions": [],
            "publishRuntime": {"day": self.server.today_key(), "last_ts": 0, "counts": {}, "last_ts_by_org": {}},
        }
        self.state_patch = mock.patch.object(self.server, "STATE", self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.runtime_patch = mock.patch.object(self.server, "PUBLISH_RT", self.state["publishRuntime"])
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)
        self.persist_calls = 0

        def fake_persist():
            self.persist_calls += 1

        self.persist_patch = mock.patch.object(self.server, "persist", fake_persist)
        self.persist_patch.start()
        self.addCleanup(self.persist_patch.stop)

    def test_accounts_include_today_publish_from_publish_runtime(self):
        self.server.record_publish_success("org-a", "node-1:douyin-main")
        self.server.record_publish_success("org-a", "douyin-main")

        rows = self.server.accounts_for_response("org-a", user={"id": "user-owner"})

        self.assertEqual(rows[0]["todayPublish"], 2)
        self.assertEqual(rows[0]["publishedToday"], 2)
        self.assertEqual(rows[0]["todayPublishDay"], self.server.today_key())
        self.assertGreater(self.persist_calls, 0)

    def test_publish_runtime_is_loaded_from_state_after_restart(self):
        state = {
            "publishRuntime": {
                "day": self.server.today_key(),
                "last_ts": 123,
                "counts": {"org-a:node-1:douyin-main": 3},
                "last_ts_by_org": {"org-a": 123},
            }
        }

        normalized = self.server.publish_runtime_from_state(state)

        self.assertEqual(normalized["day"], self.server.today_key())
        self.assertEqual(normalized["counts"]["org-a:node-1:douyin-main"], 3)

    def test_client_metric_number_accepts_plain_and_chinese_units(self):
        client = load_client_module()

        self.assertEqual(client._account_metric_number("1200"), 1200)
        self.assertEqual(client._account_metric_number("1.2万"), 12000)
        self.assertEqual(client._account_metric_number(""), 0)
