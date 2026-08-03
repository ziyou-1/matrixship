import importlib
import importlib.util
import io
import json
import sys
import tempfile
import time
import unittest
import warnings
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CLIENT = BACKEND / "matrix_native_client.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class DouyinCommentCooldownTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cls.api = importlib.import_module("api_server")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_config = self.api.RISK_CONFIG_JSON
        self.old_comment_risk = self.api.COMMENT_RISK_JSON
        self.api.RISK_CONFIG_JSON = str(Path(self.tmp.name) / "risk_config.json")
        self.api.COMMENT_RISK_JSON = str(Path(self.tmp.name) / "comment_risk_state.json")
        self.api._save_json(self.api.RISK_CONFIG_JSON, {
            "dailyPublish": 3,
            "dailyComment": 30,
            "minInterval": 45,
            "concurrency": 2,
        })
        with self.api.CLOUD_LOGIN_LOCK:
            self.api.CLOUD_LOGIN_SESSIONS.clear()
        self.addCleanup(self._restore_paths)

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

    def load_client(self, name="matrix_native_client_douyin_comment_risk_test"):
        spec = importlib.util.spec_from_file_location(name, CLIENT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _restore_paths(self):
        self.api.RISK_CONFIG_JSON = self.old_config
        self.api.COMMENT_RISK_JSON = self.old_comment_risk

    def test_successful_douyin_comment_records_min_interval_state(self):
        auth = self.api.DouyinAuth()
        with mock.patch.object(self.api, "browser_comment_preflight", return_value={"ok": True}), \
                mock.patch.object(self.api, "mark_douyin_capability"), \
                mock.patch.object(self.api.SPIDER.douyin_apis, "publish_comment", return_value={"status_code": 0}):
            result = self.api.publish_comment_to_douyin(
                auth,
                "7312345678901234567",
                "hello",
                account_id="douyin-main",
            )

        state = self.api.load_comment_risk_state()
        usage = state.get("accounts", {}).get("douyin-main", {})
        self.assertTrue(result["ok"])
        self.assertEqual(state.get("lastCommentAccountId"), "douyin-main")
        self.assertGreater(float(state.get("lastCommentAt") or 0), 0)
        self.assertEqual(usage.get("day"), self.api._today())
        self.assertEqual(usage.get("commentCount"), 1)
        self.assertEqual(result.get("safety", {}).get("commentCount"), 1)

    def test_min_interval_blocks_second_douyin_comment_before_publish(self):
        auth = self.api.DouyinAuth()
        self.api.save_comment_risk_state({
            "lastCommentAt": time.time(),
            "lastCommentAccountId": "douyin-main",
        })

        with mock.patch.object(self.api, "browser_comment_preflight") as preflight, \
                mock.patch.object(self.api.SPIDER.douyin_apis, "publish_comment") as publish:
            result = self.api.publish_comment_to_douyin(
                auth,
                "7312345678901234567",
                "hello again",
                account_id="douyin-main",
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["error"], "douyin_comment_cooldown")
        self.assertEqual(result["status"], "comment_cooldown")
        self.assertIn("评论太频繁", result.get("message", ""))
        self.assertNotIn("douyin_comment_cooldown", result.get("message", ""))
        self.assertGreater(result["cooldownLeft"], 0)
        usage = self.api.load_comment_risk_state().get("accounts", {}).get("douyin-main", {})
        self.assertEqual(usage.get("lastBlockedReason"), "douyin_comment_cooldown")
        self.assertEqual(usage.get("lastAction"), "comment_cooldown")
        preflight.assert_not_called()
        publish.assert_not_called()

    def test_min_interval_blocks_forced_ui_douyin_comment_before_browser(self):
        auth = self.api.DouyinAuth()
        self.api.save_comment_risk_state({
            "lastCommentAt": time.time(),
            "lastCommentAccountId": "douyin-main",
        })

        with mock.patch.object(self.api, "publish_comment_via_edge_ui") as edge_ui:
            result = self.api.publish_comment_to_douyin(
                auth,
                "7312345678901234567",
                "hello via ui",
                channel="edge-ui",
                account_id="douyin-main",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "douyin_comment_cooldown")
        self.assertEqual(result["status"], "comment_cooldown")
        self.assertIn("评论太频繁", result.get("userMessage", ""))
        self.assertNotIn("douyin_comment_cooldown", result.get("userMessage", ""))
        self.assertGreater(result["cooldownLeft"], 0)
        edge_ui.assert_not_called()

    def test_daily_comment_limit_blocks_douyin_before_publish(self):
        self.api._save_json(self.api.RISK_CONFIG_JSON, {
            "dailyPublish": 3,
            "dailyComment": 1,
            "minInterval": 0,
            "concurrency": 2,
        })
        self.api.record_douyin_comment_success("douyin-main", {"ok": True}, now=time.time() - 120)
        auth = self.api.DouyinAuth()

        with mock.patch.object(self.api, "browser_comment_preflight") as preflight, \
                mock.patch.object(self.api.SPIDER.douyin_apis, "publish_comment") as publish:
            result = self.api.publish_comment_to_douyin(
                auth,
                "7312345678901234567",
                "limit should block",
                account_id="douyin-main",
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["error"], "douyin_daily_comment_limit")
        self.assertEqual(result["status"], "daily_limit")
        self.assertIn("今日评论已达上限", result.get("message", ""))
        self.assertNotIn("douyin_daily_comment_limit", result.get("message", ""))
        self.assertEqual(result.get("safety", {}).get("commentCount"), 1)
        self.assertEqual(result.get("safety", {}).get("dailyComment"), 1)
        usage = self.api.load_comment_risk_state().get("accounts", {}).get("douyin-main", {})
        self.assertEqual(usage.get("lastBlockedReason"), "douyin_daily_comment_limit")
        self.assertEqual(usage.get("lastAction"), "daily_limit")
        preflight.assert_not_called()
        publish.assert_not_called()

    def test_daily_comment_limit_blocks_even_when_safe_mode_disabled(self):
        self.api._save_json(self.api.RISK_CONFIG_JSON, {
            "dailyPublish": 3,
            "dailyComment": 1,
            "minInterval": 0,
            "concurrency": 2,
        })
        self.api.record_douyin_comment_success("douyin-main", {"ok": True}, now=time.time() - 120)
        auth = self.api.DouyinAuth()

        with mock.patch.object(self.api.SPIDER.douyin_apis, "publish_comment") as publish:
            result = self.api.publish_comment_to_douyin(
                auth,
                "7312345678901234567",
                "limit should still block",
                safe_mode=False,
                account_id="douyin-main",
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["error"], "douyin_daily_comment_limit")
        self.assertEqual(result["status"], "daily_limit")
        self.assertIn("今日评论已达上限", result.get("message", ""))
        publish.assert_not_called()

    def test_preflight_block_returns_chinese_message_and_keeps_backend_code(self):
        self.api._save_json(self.api.RISK_CONFIG_JSON, {
            "dailyPublish": 3,
            "dailyComment": 30,
            "minInterval": 0,
            "concurrency": 2,
        })
        auth = self.api.DouyinAuth()

        with mock.patch.object(
            self.api,
            "browser_comment_preflight",
            return_value={"ok": False, "reason": "comment_verification_required"},
        ), mock.patch.object(self.api.SPIDER.douyin_apis, "publish_comment") as publish:
            result = self.api.publish_comment_to_douyin(
                auth,
                "7312345678901234567",
                "preflight should block",
                channel="api",
                account_id="douyin-main",
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["status"], "preflight_blocked")
        self.assertEqual(result["error"], "comment_verification_required")
        self.assertIn("安全验证", result.get("message", ""))
        self.assertEqual(result.get("message"), result.get("userMessage"))
        self.assertNotIn("comment_verification_required", result.get("message", ""))
        publish.assert_not_called()

    def test_douyin_comment_route_returns_429_with_readable_message_on_daily_limit(self):
        self.api._save_json(self.api.RISK_CONFIG_JSON, {
            "dailyPublish": 3,
            "dailyComment": 1,
            "minInterval": 0,
            "concurrency": 2,
        })
        self.api.record_douyin_comment_success("douyin-main", {"ok": True}, now=time.time() - 120)
        handler = self.make_handler("/api/douyin/comment/publish", {
            "awemeId": "7312345678901234567",
            "content": "limit should block",
            "accountId": "douyin-main",
        })

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "douyin_auth_for_request") as auth_for_request, \
                mock.patch.object(self.api.SPIDER.douyin_apis, "publish_comment") as publish, \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            auth_for_request.return_value.__enter__.return_value = (self.api.DouyinAuth(), "douyin-main")
            auth_for_request.return_value.__exit__.return_value = False
            status, payload = handler.do_POST()

        self.assertEqual(status, 429)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "douyin_daily_comment_limit")
        self.assertIn("今日评论已达上限", payload.get("message", ""))
        self.assertNotIn("douyin_daily_comment_limit", payload.get("message", ""))
        publish.assert_not_called()

    def test_douyin_risk_pause_writes_account_safety_state(self):
        self.api.mark_comment_risk(
            "comment_verification_required",
            {"reason": "comment_verification_required"},
            cooldown_sec=900,
            account_id="douyin-main",
        )

        state = self.api.load_comment_risk_state()
        usage = state.get("accounts", {}).get("douyin-main", {})
        self.assertEqual(usage.get("lastRiskReason"), "comment_verification_required")
        self.assertGreater(float(usage.get("cooldownUntil") or 0), time.time())
        self.assertIn("comment_verification_required", usage.get("pausedReason", ""))

    def test_douyin_risk_pause_does_not_block_other_accounts(self):
        self.api._save_json(self.api.RISK_CONFIG_JSON, {
            "dailyPublish": 3,
            "dailyComment": 30,
            "minInterval": 0,
            "concurrency": 2,
        })

        self.api.mark_comment_risk(
            "comment_verification_required",
            {"reason": "comment_verification_required"},
            cooldown_sec=900,
            account_id="douyin-a",
        )

        blocked = self.api.douyin_comment_safety_preflight("douyin-a")
        allowed = self.api.douyin_comment_safety_preflight("douyin-b")
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["error"], "douyin_comment_risk_cooldown")
        self.assertTrue(allowed["ok"])

    def test_douyin_risk_pause_redacts_persisted_response(self):
        self.api.mark_comment_risk(
            "comment_verification_required",
            {
                "reason": "comment_verification_required",
                "status_code": 8,
                "status_msg": "平台风控",
                "message": "请访问 https://www.douyin.com/video/999?token=secret",
                "url": "https://www.douyin.com/video/7312345678901234567?private=secret",
                "text": "这是页面正文不应该保存",
                "Cookie": "sessionid=secret_cookie",
                "Authorization": "Bearer secret_token",
                "headers": {"Cookie": "sessionid=secret_cookie"},
            },
            cooldown_sec=900,
            account_id="douyin-main",
        )

        saved = self.api.load_comment_risk_state().get("lastResponse", {})
        serialized = json.dumps(saved, ensure_ascii=False)
        self.assertEqual(saved.get("reason"), "comment_verification_required")
        self.assertEqual(saved.get("status_code"), 8)
        self.assertIn("urlFingerprint", saved)
        self.assertIn("textFingerprint", saved)
        self.assertNotIn("https://www.douyin.com/video/7312345678901234567", serialized)
        self.assertNotIn("https://www.douyin.com/video/999", serialized)
        self.assertNotIn("这是页面正文不应该保存", serialized)
        self.assertNotIn("secret_cookie", serialized)
        self.assertNotIn("secret_token", serialized)

    def test_platform_risk_response_writes_pause_even_when_safe_mode_disabled(self):
        self.api._save_json(self.api.RISK_CONFIG_JSON, {
            "dailyPublish": 3,
            "dailyComment": 30,
            "minInterval": 0,
            "concurrency": 2,
        })
        auth = self.api.DouyinAuth()

        with mock.patch.object(
            self.api.SPIDER.douyin_apis,
            "publish_comment",
            return_value={"status_code": 8, "status_msg": "平台风控"},
        ):
            result = self.api.publish_comment_to_douyin(
                auth,
                "7312345678901234567",
                "risk response should pause",
                safe_mode=False,
                account_id="douyin-main",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "risk_blocked")
        self.assertEqual(result["error"], "douyin_comment_risk_cooldown")
        self.assertIn("风险冷却", result.get("message", ""))
        usage = self.api.load_comment_risk_state().get("accounts", {}).get("douyin-main", {})
        self.assertTrue(usage.get("paused"))
        self.assertGreater(float(usage.get("pausedUntil") or 0), time.time())

    def test_ai_outreach_stops_after_douyin_daily_limit_result(self):
        discovery = {
            "videoCount": 2,
            "commentCount": 2,
            "leadCount": 0,
            "videos": [
                {"work_id": "7312345678901234567", "title": "video-a"},
                {"work_id": "7312345678901234568", "title": "video-b"},
            ],
            "leads": [],
        }
        limit_result = {
            "ok": False,
            "status": "daily_limit",
            "error": "douyin_daily_comment_limit",
            "message": "今日评论已达上限，请明天再操作。",
        }

        with mock.patch.object(self.api, "discover_leads_by_keyword_platform", return_value=discovery), \
                mock.patch.object(self.api, "publish_comment_to_platform", return_value=limit_result) as publish:
            summary = self.api.run_ai_outreach(
                self.api.DouyinAuth(),
                "test keyword",
                platform="douyin",
                account_id="douyin-main",
                interval_sec=0,
            )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["status"], "daily_limit")
        self.assertEqual(summary["error"], "douyin_daily_comment_limit")
        self.assertIn("今日评论已达上限", summary.get("message", ""))
        self.assertEqual(len(summary["results"]), 1)
        self.assertEqual(summary["results"][0]["status"], "daily_limit")
        self.assertIn("今日评论已达上限", summary["results"][0].get("message", ""))
        publish.assert_called_once()

    def test_ai_outreach_stops_on_douyin_limit_even_when_safe_mode_disabled(self):
        discovery = {
            "videoCount": 2,
            "commentCount": 2,
            "leadCount": 0,
            "videos": [
                {"work_id": "7312345678901234567", "title": "video-a"},
                {"work_id": "7312345678901234568", "title": "video-b"},
            ],
            "leads": [],
        }
        limit_result = {
            "ok": False,
            "status": "daily_limit",
            "error": "douyin_daily_comment_limit",
            "message": "今日评论已达上限，请明天再操作。",
        }

        with mock.patch.object(self.api, "discover_leads_by_keyword_platform", return_value=discovery), \
                mock.patch.object(self.api, "publish_comment_to_platform", return_value=limit_result) as publish:
            summary = self.api.run_ai_outreach(
                self.api.DouyinAuth(),
                "test keyword",
                platform="douyin",
                account_id="douyin-main",
                interval_sec=0,
                safe_mode=False,
            )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["status"], "daily_limit")
        self.assertEqual(len(summary["results"]), 1)
        publish.assert_called_once()

    def test_risk_center_source_shows_douyin_comment_cooldown(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class RiskControlPage")
        end = src.index("class AssetMultiPicker", start)
        risk_src = src[start:end]

        self.assertIn("load_comment_risk_state", risk_src)
        self.assertIn("_douyin_comment_cooldown_text", risk_src)
        self.assertIn("_douyin_comment_usage_text", risk_src)

    def test_client_error_message_prefers_chinese_douyin_user_message(self):
        client = self.load_client()

        message = client._local_task_error_message({
            "status": "failed",
            "error": "task_failed",
            "result": {
                "error": "douyin_daily_comment_limit",
                "userMessage": "今日评论已达上限，请明天再操作。",
            },
        })

        self.assertEqual(message, "今日评论已达上限，请明天再操作。")
        self.assertNotIn("douyin_daily_comment_limit", message)

    def test_client_error_message_localizes_douyin_comment_codes_without_message(self):
        client = self.load_client("matrix_native_client_douyin_comment_code_message_test")

        message = client._local_task_error_message({
            "status": "failed",
            "result": {
                "error": "douyin_comment_cooldown",
                "safety": {"cooldownLeft": 30},
            },
        })

        self.assertIn("评论太频繁", message)
        self.assertIn("30", message)
        self.assertNotIn("douyin_comment_cooldown", message)

    def test_client_douyin_cooldown_ignores_other_account_global_risk(self):
        client = self.load_client("matrix_native_client_douyin_cooldown_scope_test")
        until = time.time() + 900
        state = {
            "cooldownUntil": until,
            "lastRiskAccountId": "douyin-a",
            "accounts": {
                "douyin-a": {"cooldownUntil": until, "pausedUntil": until},
                "douyin-b": {},
            },
        }

        text = client._douyin_comment_cooldown_text(
            {"id": "douyin-b", "accountId": "douyin-b", "platform": "douyin"},
            state,
        )

        self.assertEqual(text, "-")

    def test_client_error_message_localizes_douyin_preflight_code_without_message(self):
        client = self.load_client("matrix_native_client_douyin_preflight_code_message_test")

        message = client._local_task_error_message({
            "status": "failed",
            "result": {
                "error": "comment_verification_required",
            },
        })

        self.assertIn("安全验证", message)
        self.assertNotIn("comment_verification_required", message)

    def test_comment_preflight_uses_selected_account_cloud_session(self):
        with mock.patch.object(self.api, "find_cloud_session_for_account", return_value=("", None)) as finder, \
                mock.patch.dict(self.api.os.environ, {"DY_COMMENT_PREFLIGHT_HEADLESS": "1"}), \
                mock.patch("playwright.sync_api.sync_playwright", side_effect=RuntimeError("stop-before-browser")):
            with self.assertRaises(RuntimeError):
                self.api.browser_comment_preflight(
                    "7312345678901234567",
                    auth=self.api.DouyinAuth(),
                    account_id="douyin-main",
                )

        finder.assert_called_once_with("douyin-main")

    def test_forced_comment_ui_passes_selected_account_to_cloud_fallback(self):
        self.api._save_json(self.api.RISK_CONFIG_JSON, {
            "dailyPublish": 3,
            "dailyComment": 30,
            "minInterval": 0,
            "concurrency": 2,
        })

        with mock.patch.object(
            self.api,
            "publish_comment_via_cloud_ui",
            return_value={"ok": True, "status": "sent_verified"},
        ) as cloud_ui:
            result = self.api.publish_comment_to_douyin(
                self.api.DouyinAuth(),
                "7312345678901234567",
                "hello from selected profile",
                channel="cloud-ui",
                account_id="douyin-main",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(cloud_ui.call_args.kwargs.get("account_id"), "douyin-main")

    def test_cloud_comment_ui_creates_session_for_selected_account(self):
        created = []

        class FakeSession:
            closed = False

            def __init__(self, session_id, account_id="douyin-self", login_url=None):
                self.id = session_id
                self.account_id = account_id
                self.login_url = login_url
                created.append({"accountId": account_id, "loginUrl": login_url})

            def start(self, timeout=45):
                return None

            def send_comment(self, aweme_id, content, reply_id=""):
                return {"ok": True, "domVerified": True}

            def close(self):
                self.closed = True

        with mock.patch.object(self.api, "find_cloud_session_for_account", return_value=("", None)) as finder, \
                mock.patch.object(self.api, "release_chromium_profile_if_stale") as release, \
                mock.patch.object(self.api, "CloudLoginSession", FakeSession), \
                mock.patch.object(self.api, "verify_comment_visible", return_value={"ok": True}), \
                mock.patch.object(self.api, "ensure_auth_from_cache", return_value=self.api.DouyinAuth()):
            result = self.api.publish_comment_via_cloud_ui(
                self.api.DouyinAuth(),
                "7312345678901234567",
                "hello",
                account_id="douyin-main",
            )

        self.assertTrue(result["ok"])
        finder.assert_called_once_with("douyin-main")
        release.assert_called_once_with(self.api._cloud_profile_dir("douyin-main"))
        self.assertEqual(created[0]["accountId"], "douyin-main")

    def test_cloud_login_open_url_route_uses_selected_account_session(self):
        created = []

        class FakeOpenSession:
            closed = False

            def __init__(self, session_id, account_id="douyin-self", login_url=None):
                self.id = session_id
                self.account_id = account_id
                self.login_url = login_url
                created.append({"accountId": account_id, "loginUrl": login_url})

            def start(self, timeout=45):
                return None

            def open_url(self, url):
                return {"ok": True, "loggedIn": True, "url": url, "accountId": self.account_id}

            def close(self):
                self.closed = True

        handler = self.make_handler("/api/cloud-login/open-url", {
            "accountId": "douyin-main",
            "url": "https://www.douyin.com/user/example",
        })
        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "find_cloud_session_for_account", return_value=("", None)) as finder, \
                mock.patch.object(self.api, "release_chromium_profile_if_stale") as release, \
                mock.patch.object(self.api, "CloudLoginSession", FakeOpenSession), \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["accountId"], "douyin-main")
        self.assertEqual(payload["requestedUrl"], "https://www.douyin.com/user/example")
        finder.assert_called_once_with("douyin-main")
        release.assert_called_once_with(self.api._cloud_profile_dir("douyin-main"))
        self.assertEqual(created[0]["accountId"], "douyin-main")
        self.assertEqual(created[0]["loginUrl"], "https://www.douyin.com/user/example")


if __name__ == "__main__":
    unittest.main()
