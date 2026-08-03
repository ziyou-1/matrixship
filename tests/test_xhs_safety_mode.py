import importlib
import io
import json
import os
import tempfile
import time
import unittest
import warnings
from pathlib import Path
from unittest import mock
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CLIENT = BACKEND / "matrix_native_client.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class XhsSafetyModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cls.api = importlib.import_module("api_server")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env_patch = mock.patch.dict(os.environ, {"MATRIX_XHS_ENABLED": "1"})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.old_config = self.api.RISK_CONFIG_JSON
        self.old_state = self.api.XHS_SAFETY_STATE_JSON
        self.api.RISK_CONFIG_JSON = str(Path(self.tmp.name) / "risk_config.json")
        self.api.XHS_SAFETY_STATE_JSON = str(Path(self.tmp.name) / "xhs_safety_state.json")
        self.api._save_json(self.api.RISK_CONFIG_JSON, {
            "dailyPublish": 1,
            "dailyComment": 1,
            "minInterval": 45,
            "concurrency": 2,
        })
        self.addCleanup(self._restore_paths)

    def _restore_paths(self):
        self.api.RISK_CONFIG_JSON = self.old_config
        self.api.XHS_SAFETY_STATE_JSON = self.old_state

    def make_handler(self, path, payload):
        body = json.dumps(payload).encode("utf-8")
        handler = object.__new__(self.api.Handler)
        handler.path = path
        handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)
        return handler

    def test_publish_limit_blocks_xhs_before_browser_publish(self):
        self.api.xhs_safety_record("publish", "xhs-self", {"ok": True, "published": True}, now=time.time())
        material = {"id": "mat-1", "platform": "xhs", "type": "image_note", "files": ["01.jpg"], "title": "标题"}

        with mock.patch.object(self.api, "material_files", return_value=["01.jpg"]), \
                mock.patch.object(self.api, "xhs_publish_material") as publish:
            result = self.api.run_publish(material, "xhs-self", dry_run=False, platform="xhs")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "xhs_daily_publish_limit")
        publish.assert_not_called()

    def test_comment_limit_blocks_xhs_comment_endpoint(self):
        self.api.xhs_safety_record("comment", "xhs-self", {"ok": True}, now=time.time())
        handler = self.make_handler("/api/xhs/comment/publish", {
            "url": "https://www.xiaohongshu.com/explore/note-a",
            "content": "想了解一下",
        })

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "xhs_publish_comment") as publish_comment, \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 429)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "xhs_daily_comment_limit")
        publish_comment.assert_not_called()

    def test_min_interval_blocks_xhs_download_endpoint(self):
        self.api.xhs_safety_record("search", "xhs-self", {"ok": True}, now=time.time())
        handler = self.make_handler("/api/xhs/download", {
            "url": "https://www.xiaohongshu.com/explore/note-a",
            "guestMode": False,
            "accountCollectionConfirmed": True,
        })

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "xhs_profile_ready", return_value=True), \
                mock.patch.object(self.api, "xhs_download_note") as download, \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 429)
        self.assertEqual(payload["error"], "xhs_safety_interval")
        download.assert_not_called()

    def test_account_collection_requires_saved_xhs_profile(self):
        with mock.patch.object(self.api, "xhs_profile_ready", return_value=False):
            gate = self.api.xhs_collection_account_gate(
                "search",
                "xhs-self",
                guest_mode=False,
                confirmed=True,
            )

        self.assertFalse(gate["ok"])
        self.assertEqual(gate["error"], "xhs_login_required")
        self.assertTrue(gate["needLogin"])

    def test_risk_response_pauses_xhs_account(self):
        self.api.xhs_safety_record("search", "xhs-self", {
            "ok": False,
            "error": "xhs_ip_risk",
            "riskCode": "300012",
        }, now=1000)

        blocked = self.api.xhs_safety_preflight("download", "xhs-self", now=1100)

        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["error"], "xhs_safety_paused")
        self.assertIn("300012", blocked["safety"]["pausedReason"])

    def test_risk_center_source_shows_xhs_usage_columns(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class RiskControlPage")
        end = src.index("class AssetMultiPicker", start)
        risk_src = src[start:end]

        self.assertIn("今日发布", risk_src)
        self.assertIn("今日评论", risk_src)
        self.assertIn("冷却", risk_src)
        self.assertIn("load_xhs_safety_state", risk_src)


if __name__ == "__main__":
    unittest.main()
