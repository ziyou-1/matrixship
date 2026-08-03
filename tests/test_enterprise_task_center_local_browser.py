import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SERVER = BACKEND / "central_server.py"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_server_module():
    spec = importlib.util.spec_from_file_location("central_server_task_center_under_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EnterpriseTaskCenterLocalBrowserTest(unittest.TestCase):
    def setUp(self):
        self.server = load_server_module()
        self.ts = 1_800_000_000.0
        self.state = {
            "organizations": [{"id": "org-a", "name": "Org A", "status": "active"}],
            "users": [
                {"id": "u-admin", "name": "Boss", "status": "active"},
                {"id": "u-member", "name": "User 01", "status": "active"},
                {"id": "u-other", "name": "User 02", "status": "active"},
            ],
            "memberships": [
                {"id": "m-admin", "orgId": "org-a", "userId": "u-admin", "role": "admin", "status": "active"},
                {"id": "m-member", "orgId": "org-a", "userId": "u-member", "role": "member", "status": "active"},
                {"id": "m-other", "orgId": "org-a", "userId": "u-other", "role": "member", "status": "active"},
            ],
            "tasks": {},
            "localBrowserTasks": {
                "lbt-search": {
                    "id": "lbt-search",
                    "orgId": "org-a",
                    "type": "douyin.search",
                    "payload": {"keyword": "汽车", "accountId": "douyin-1"},
                    "status": "done",
                    "clientId": "local-client-1",
                    "createdBy": "u-member",
                    "createdAt": self.ts - 120,
                    "updatedAt": self.ts - 60,
                    "finishedAt": self.ts - 60,
                    "result": {"ok": True, "items": [{"title": "demo"}]},
                },
                "lbt-other": {
                    "id": "lbt-other",
                    "orgId": "org-a",
                    "type": "xhs.search",
                    "payload": {"keyword": "美妆", "accountId": "xhs-1"},
                    "status": "done",
                    "clientId": "local-client-1",
                    "createdBy": "u-other",
                    "createdAt": self.ts - 90,
                    "updatedAt": self.ts - 30,
                    "finishedAt": self.ts - 30,
                    "result": {"ok": True, "items": [{"title": "other"}]},
                },
            },
            "localBrowserClients": {
                "local-client-1": {"id": "local-client-1", "orgId": "org-a", "lastSeen": self.ts},
            },
            "queue": [],
            "nodes": {},
            "accountsRegistry": [],
            "library": [],
            "kb": [],
            "auditLogs": [],
            "sessions": [],
        }
        self.state_patch = mock.patch.object(self.server, "STATE", self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.now_patch = mock.patch.object(self.server, "now", return_value=self.ts)
        self.now_patch.start()
        self.addCleanup(self.now_patch.stop)

    def test_task_center_includes_local_browser_tasks_for_enterprise_admin(self):
        payload = self.server.enterprise_task_center("org-a", user={"id": "u-admin"})

        recent_ids = [item["id"] for item in payload["recent"]]
        self.assertIn("lbt-search", recent_ids)
        self.assertIn("lbt-other", recent_ids)
        self.assertEqual(payload["counts"]["total"], 2)
        search_row = next(item for item in payload["recent"] if item["id"] == "lbt-search")
        self.assertEqual(search_row["type"], "search")
        self.assertEqual(search_row["accountId"], "douyin-1")
        self.assertEqual(search_row["status"], "done")

    def test_task_center_limits_normal_user_to_own_local_browser_tasks(self):
        payload = self.server.enterprise_task_center("org-a", user={"id": "u-member"})

        recent_ids = [item["id"] for item in payload["recent"]]
        self.assertEqual(recent_ids, ["lbt-search"])
        self.assertEqual(payload["counts"]["total"], 1)

    def test_enterprise_usage_and_summary_count_local_browser_tasks(self):
        usage = self.server.enterprise_usage("org-a")
        summary = self.server.enterprise_summary({"id": "u-admin"})

        self.assertEqual(usage["tasks24h"], 2)
        self.assertEqual(usage["tasks7d"], 2)
        self.assertEqual(summary["counts"]["tasks"], 2)

    def test_enterprise_summary_counts_online_local_browser_clients_as_nodes(self):
        self.state["localBrowserClients"] = {
            "lb-org-a": {"id": "lb-org-a", "orgId": "org-a", "lastSeen": self.ts, "capabilities": ["douyin.search"]},
            "lb-org-b": {"id": "lb-org-b", "orgId": "org-b", "lastSeen": self.ts, "capabilities": ["douyin.search"]},
            "lb-stale": {"id": "lb-stale", "orgId": "org-a", "lastSeen": self.ts - 600, "capabilities": ["douyin.search"]},
        }

        usage = self.server.enterprise_usage("org-a")
        summary = self.server.enterprise_summary({"id": "u-admin"})

        self.assertEqual(usage["onlineNodes"], 1)
        self.assertEqual(summary["counts"]["nodesOnline"], 1)

    def test_enterprise_usage_returns_real_daily_task_trend(self):
        self.state["tasks"] = {
            "central-old": {
                "id": "central-old",
                "orgId": "org-a",
                "path": "/api/publish",
                "status": "done",
                "createdBy": "u-admin",
                "createdAt": self.ts - 2 * 86400,
                "updatedAt": self.ts - 2 * 86400,
            },
            "central-outside-window": {
                "id": "central-outside-window",
                "orgId": "org-a",
                "path": "/api/publish",
                "status": "done",
                "createdBy": "u-admin",
                "createdAt": self.ts - 8 * 86400,
                "updatedAt": self.ts - 8 * 86400,
            },
        }

        usage = self.server.enterprise_usage("org-a")

        trend = usage["taskTrend7d"]
        self.assertEqual(len(trend), 7)
        self.assertEqual(sum(x["count"] for x in trend), 3)
        self.assertEqual(trend[-1]["count"], 2)
        self.assertEqual(trend[-3]["count"], 1)
        self.assertTrue(all("date" in x and "label" in x for x in trend))

    def test_offline_local_browser_attempt_is_recorded_as_failed_task(self):
        self.state["localBrowserTasks"] = {}
        self.state["localBrowserClients"] = {}

        with mock.patch.object(self.server, "require_role", return_value=True), \
                mock.patch.object(self.server, "current_user", return_value={"id": "u-member"}), \
                mock.patch.object(self.server, "persist", return_value=None), \
                mock.patch.object(self.server, "add_audit", return_value=None):
            payload, status = self.server.local_browser_create_task(
                mock.Mock(headers={}),
                {"orgId": "org-a", "type": "douyin.search", "payload": {"keyword": "汽车"}},
            )

        self.assertEqual(status, 409)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "local_browser_offline")
        failed_tasks = list(self.state["localBrowserTasks"].values())
        self.assertEqual(len(failed_tasks), 1)
        self.assertEqual(failed_tasks[0]["status"], "failed")
        self.assertEqual(failed_tasks[0]["error"], "local_browser_offline")
        center = self.server.enterprise_task_center("org-a", user={"id": "u-member"})
        self.assertEqual(center["recent"][0]["status"], "failed")

    def test_long_local_browser_outreach_task_is_not_requeued_after_default_timeout(self):
        self.state["localBrowserTasks"] = {
            "lbt-outreach": {
                "id": "lbt-outreach",
                "orgId": "org-a",
                "type": "outreach.run",
                "status": "running",
                "clientId": "local-client-1",
                "createdBy": "u-member",
                "createdAt": self.ts - 360,
                "startedAt": self.ts - 360,
                "updatedAt": self.ts - 360,
                "payload": {"keyword": "car"},
                "result": {},
            },
            "lbt-search": {
                "id": "lbt-search",
                "orgId": "org-a",
                "type": "douyin.search",
                "status": "running",
                "clientId": "local-client-1",
                "createdBy": "u-member",
                "createdAt": self.ts - 360,
                "startedAt": self.ts - 360,
                "updatedAt": self.ts - 360,
                "payload": {"keyword": "car"},
                "result": {},
            },
        }

        changed = self.server.local_browser_housekeeping_locked()

        self.assertTrue(changed)
        self.assertEqual(self.state["localBrowserTasks"]["lbt-outreach"]["status"], "running")
        self.assertEqual(self.state["localBrowserTasks"]["lbt-outreach"]["clientId"], "local-client-1")
        self.assertEqual(self.state["localBrowserTasks"]["lbt-search"]["status"], "queued")
        self.assertEqual(self.state["localBrowserTasks"]["lbt-search"]["error"], "local_browser_task_requeued")


if __name__ == "__main__":
    unittest.main()
