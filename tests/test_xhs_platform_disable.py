import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class XhsPlatformDisableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.features = importlib.import_module("platform_features")
        except ModuleNotFoundError:
            cls.features = None
        cls.api = importlib.import_module("api_server")
        cls.central = importlib.import_module("central_server")
        cls.adapters = importlib.import_module("platform_adapters")
        cls.client_source = (BACKEND / "matrix_native_client.py").read_text(encoding="utf-8")

    def make_api_handler(self, payload, path):
        body = json.dumps(payload).encode("utf-8")
        handler = object.__new__(self.api.Handler)
        handler.path = path
        handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)
        return handler

    def test_xhs_is_disabled_by_default_and_can_be_explicitly_restored(self):
        self.assertIsNotNone(self.features, "platform_features module is required")
        self.assertFalse(self.features.xhs_enabled({}))
        self.assertFalse(self.features.xhs_enabled({"MATRIX_XHS_ENABLED": "0"}))
        self.assertTrue(self.features.xhs_enabled({"MATRIX_XHS_ENABLED": "1"}))
        self.assertTrue(self.features.xhs_enabled({"MATRIX_XHS_ENABLED": "true"}))
        self.assertTrue(self.features.is_xhs_platform("xhs"))
        self.assertTrue(self.features.is_xhs_platform("小红书"))
        self.assertFalse(self.features.is_xhs_platform("douyin"))

    def test_disabled_result_has_stable_redacted_contract(self):
        self.assertIsNotNone(self.features, "platform_features module is required")
        result = self.features.platform_disabled_result(
            "xhs",
            route="/api/xhs/search",
            task_type="xhs.search",
            stage="preflight",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "platform_disabled")
        self.assertEqual(result["platform"], "xhs")
        self.assertEqual(result["route"], "/api/xhs/search")
        self.assertEqual(result["taskType"], "xhs.search")
        self.assertNotIn("token", json.dumps(result).lower())
        self.assertNotIn("cookie", json.dumps(result).lower())

    def test_nested_payload_xhs_marker_is_blocked_without_matching_free_text(self):
        self.assertTrue(self.features.payload_uses_xhs({"payload": {"platform": "xhs"}}))
        self.assertTrue(self.features.payload_uses_xhs({"payload": {"accountId": "lb:xhs-self"}}))
        self.assertFalse(self.features.payload_uses_xhs({"platform": "douyin", "title": "xhs note in copy"}))

    def test_local_xhs_search_is_rejected_before_adapter_call(self):
        handler = self.make_api_handler(
            {"query": "丰田", "num": 3, "accountCollectionConfirmed": True},
            "/api/xhs/search",
        )
        with mock.patch.dict(os.environ, {"MATRIX_XHS_ENABLED": "0"}, clear=False), \
                mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "xhs_search_notes") as search, \
                mock.patch.object(
                    self.api,
                    "json_response",
                    side_effect=lambda _handler, payload, status=200: (status, payload),
                ):
            status, payload = handler.do_POST()

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "platform_disabled")
        search.assert_not_called()

    def test_platform_adapter_is_rejected_before_browser_import(self):
        with mock.patch.dict(os.environ, {"MATRIX_XHS_ENABLED": "0"}, clear=False):
            result = self.adapters.xhs_search_notes("丰田", limit=1, data_dir=tempfile.gettempdir())

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "platform_disabled")

    def test_central_xhs_task_is_rejected_before_node_selection(self):
        with mock.patch.dict(os.environ, {"MATRIX_XHS_ENABLED": "0"}, clear=False), \
                mock.patch.object(self.central, "pick_node", return_value=None) as pick_node:
            task, error, status = self.central.create_task(
                "/api/xhs/search",
                body={"platform": "xhs", "query": "丰田"},
            )

        self.assertIsNone(task)
        self.assertEqual(status, 404)
        self.assertEqual(error["error"], "platform_disabled")
        pick_node.assert_not_called()

    def test_local_browser_xhs_task_type_is_disabled(self):
        source = (BACKEND / "central_server.py").read_text(encoding="utf-8")
        self.assertIn("platform_disabled", source)
        self.assertIn("MATRIX_XHS_ENABLED", source)

    def test_local_browser_capabilities_hide_xhs_and_restore_with_flag(self):
        worker = importlib.import_module("local_browser_worker")
        with mock.patch.dict(
            os.environ,
            {"MATRIX_XHS_ENABLED": "0"},
            clear=False,
        ):
            self.assertFalse(
                any(
                    capability.startswith("xhs.")
                    for capability in worker.advertised_capabilities()
                )
            )
        with mock.patch.dict(
            os.environ,
            {"MATRIX_XHS_ENABLED": "1"},
            clear=False,
        ):
            self.assertIn("xhs.search", worker.advertised_capabilities())

    def test_central_sanitizes_persisted_xhs_capabilities(self):
        with mock.patch.dict(
            os.environ,
            {"MATRIX_XHS_ENABLED": "0"},
            clear=False,
        ):
            public = self.central.public_local_browser_client(
                {
                    "id": "lb-test",
                    "lastSeen": self.central.now(),
                    "capabilities": ["douyin.search", "xhs.search", "xhs.login"],
                }
            )
        self.assertEqual(public["capabilities"], ["douyin.search"])

    def test_native_client_only_exposes_douyin_platform_controls(self):
        self.assertIn('self.platform.addItem("抖音", "douyin")', self.client_source)
        self.assertNotIn('self.platform.addItem("小红书", "xhs")', self.client_source)
        self.assertNotIn('applat.addItems(["抖音", "小红书"])', self.client_source)
        self.assertNotIn('self.platform.addItems(["抖音", "小红书"])', self.client_source)
        self.assertNotIn('("🧩 图文同款", lambda: XhsNoteReplacementPage())', self.client_source)

    def test_cleanup_removes_only_xhs_account_state(self):
        try:
            cleanup = importlib.import_module("disable_xhs_accounts")
        except ModuleNotFoundError:
            cleanup = None
        self.assertIsNotNone(cleanup, "disable_xhs_accounts module is required")
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "xhs_profile").mkdir()
            (data_dir / "xhs_profile" / "Cookies").write_text("xhs-cookie", encoding="utf-8")
            (data_dir / "xhs_auth_state.json").write_text("{}", encoding="utf-8")
            (data_dir / "douyin_profile").mkdir()
            (data_dir / "douyin_profile" / "Cookies").write_text("dy-cookie", encoding="utf-8")
            registry = data_dir / "accounts.json"
            registry.write_text(
                json.dumps(
                    [
                        {"id": "xhs-self", "platform": "xhs"},
                        {"id": "douyin-self", "platform": "douyin"},
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            central_state = Path(tmp) / "central.json"
            central_state.write_text(
                json.dumps(
                    {
                        "accountsRegistry": [
                            {"id": "node:xhs-self", "platform": "xhs"},
                            {"id": "node:douyin-self", "platform": "douyin"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            preview = cleanup.cleanup_xhs_state(data_dir, central_state, dry_run=True)
            self.assertEqual(preview["removedLocalAccounts"], 1)
            self.assertTrue((data_dir / "xhs_profile").exists())
            self.assertTrue((data_dir / "douyin_profile").exists())

            result = cleanup.cleanup_xhs_state(data_dir, central_state, dry_run=False)
            self.assertEqual(result["removedLocalAccounts"], 1)
            self.assertFalse((data_dir / "xhs_profile").exists())
            self.assertFalse((data_dir / "xhs_auth_state.json").exists())
            self.assertTrue((data_dir / "douyin_profile").exists())
            accounts = json.loads(registry.read_text(encoding="utf-8"))
            self.assertEqual(accounts, [{"id": "douyin-self", "platform": "douyin"}])
            central = json.loads(central_state.read_text(encoding="utf-8"))
            self.assertEqual(
                central["accountsRegistry"],
                [{"id": "node:douyin-self", "platform": "douyin"}],
            )


if __name__ == "__main__":
    unittest.main()
