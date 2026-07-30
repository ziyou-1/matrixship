import importlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class DouyinDmAutoReplyContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.central = importlib.import_module("central_server")
        cls.worker = importlib.import_module("local_browser_worker")

    def test_central_allows_douyin_dm_inbox_task(self):
        self.assertEqual(
            self.central.LOCAL_BROWSER_TASK_PATHS.get("douyin.dm.inbox"),
            "/api/douyin/dm/inbox",
        )
        self.assertIn("douyin.dm.inbox", self.central.LOCAL_BROWSER_ALLOWED_TYPES)
        self.assertIn("douyin.dm.inbox", self.central.LOCAL_BROWSER_ALL_CAPS)

    def test_local_worker_advertises_douyin_dm_inbox_capability(self):
        self.assertEqual(
            self.worker.TASK_PATHS.get("douyin.dm.inbox"),
            "/api/douyin/dm/inbox",
        )
        self.assertIn("douyin.dm.inbox", self.worker.CAPABILITIES)


class DouyinDmInboxApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = importlib.import_module("api_server")

    def make_handler(self, payload):
        body = json.dumps(payload).encode("utf-8")
        handler = object.__new__(self.api.Handler)
        handler.path = "/api/douyin/dm/inbox"
        handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)
        return handler

    def test_normalize_dm_text_message_has_stable_fingerprint(self):
        msg = self.api._normalize_dm_inbox_message(
            {"direction": "customer", "kind": "text", "text": "想了解价格", "createdAtText": "14:20"},
            0,
        )
        self.assertEqual(msg["direction"], "customer")
        self.assertEqual(msg["kind"], "text")
        self.assertEqual(msg["text"], "想了解价格")
        self.assertTrue(msg["fingerprint"])
        self.assertLessEqual(len(msg["text"]), 1000)

    def test_normalize_dm_text_fingerprint_does_not_depend_on_poll_index(self):
        raw = {"direction": "customer", "kind": "text", "text": "想了解价格", "createdAtText": "14:20"}
        first = self.api._normalize_dm_inbox_message(raw, 0)
        shifted = self.api._normalize_dm_inbox_message(raw, 3)
        self.assertEqual(first["fingerprint"], shifted["fingerprint"])

    def test_normalize_dm_duplicate_text_can_have_distinct_fingerprints(self):
        raw = {"direction": "customer", "kind": "text", "text": "same question", "createdAtText": "", "ordinal": 0}
        duplicate = dict(raw, ordinal=1)
        first = self.api._normalize_dm_inbox_message(raw, 0)
        second = self.api._normalize_dm_inbox_message(duplicate, 1)
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])

    def test_normalize_dm_unknown_direction_is_not_customer(self):
        msg = self.api._normalize_dm_inbox_message({"kind": "text", "text": "system notice"}, 0)
        self.assertEqual(msg["direction"], "unknown")

    def test_normalize_dm_non_text_message_has_empty_text(self):
        msg = self.api._normalize_dm_inbox_message(
            {"direction": "customer", "kind": "image", "text": "ignored raw"},
            1,
        )
        self.assertEqual(msg["kind"], "image")
        self.assertEqual(msg["text"], "")

    def test_dm_button_label_accepts_duplicate_dom_text_but_rejects_adjacent_actions(self):
        self.assertTrue(self.api._is_douyin_dm_button_label("私信 私信"))
        self.assertTrue(self.api._is_douyin_dm_button_label("发消息发消息"))
        self.assertFalse(self.api._is_douyin_dm_button_label("回关 私信"))
        self.assertFalse(self.api._is_douyin_dm_button_label("关注"))

    def test_dm_context_cookies_restore_cache_without_ms_token(self):
        cookies = self.api._douyin_dm_context_cookies(
            "sessionid=login-session; passport_csrf_token=csrf-value; msToken=volatile-token"
        )
        self.assertEqual(
            {item["name"] for item in cookies},
            {"sessionid", "passport_csrf_token"},
        )
        self.assertTrue(all(item["domain"] == ".douyin.com" for item in cookies))
        self.assertTrue(all(item["path"] == "/" for item in cookies))

    def test_dm_inbox_route_requires_target(self):
        handler = self.make_handler({})
        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "missing_target")

    def test_dm_inbox_route_returns_browser_result(self):
        handler = self.make_handler({"target": "https://www.douyin.com/user/sec", "limit": 5})
        result = {
            "ok": True,
            "platform": "douyin",
            "target": "https://www.douyin.com/user/sec",
            "messages": [],
            "nonTextCount": 0,
        }
        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "run_douyin_dm_inbox", return_value=result), \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_dm_inbox_route_passes_account_id_to_browser_path(self):
        handler = self.make_handler({
            "target": "https://www.douyin.com/user/sec",
            "limit": 5,
            "sinceFingerprint": "last-fingerprint",
            "accountId": "douyin-account-1",
        })
        result = {"ok": True, "messages": [], "nonTextCount": 0}
        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "run_douyin_dm_inbox", return_value=result) as run_inbox, \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        run_inbox.assert_called_once_with(
            "https://www.douyin.com/user/sec",
            5,
            "last-fingerprint",
            "douyin-account-1",
        )

    def test_dm_inbox_wrapper_passes_account_id_to_browser_reader(self):
        result = {"ok": True, "messages": []}
        with mock.patch.object(self.api, "browser_read_dm_inbox", return_value=result) as browser_reader:
            actual = self.api.run_douyin_dm_inbox(
                "https://www.douyin.com/user/sec",
                limit=5,
                since_fingerprint="last-fingerprint",
                account_id="douyin-account-1",
            )
        self.assertEqual(actual, result)
        browser_reader.assert_called_once_with(
            "https://www.douyin.com/user/sec",
            limit=5,
            since_fingerprint="last-fingerprint",
            account_id="douyin-account-1",
        )


class DouyinDmInboxBrowserSourceTest(unittest.TestCase):
    def inbox_block(self):
        source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        start = source.index("def browser_read_dm_inbox")
        end = source.index("\ndef list_download_files", start)
        return source[start:end]

    def test_browser_read_dm_inbox_uses_isolated_child_process(self):
        source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        self.assertIn("DY_DM_INBOX_CHILD", source)
        self.assertIn("__MATRIX_DM_INBOX_JSON__", source)

    def test_browser_read_dm_inbox_reports_expected_error_codes(self):
        source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        for code in (
            "dm_inbox_button_not_found",
            "dm_inbox_messages_not_found",
            "not_authenticated",
            "numeric_uid_unsupported_in_browser_dm",
        ):
            with self.subTest(code=code):
                self.assertIn(code, source)

    def test_browser_read_dm_inbox_resolves_and_seeds_selected_account(self):
        block = self.inbox_block()
        self.assertIn("def browser_read_dm_inbox(target, limit=10, since_fingerprint=\"\", account_id='')", block)
        self.assertIn("login_source = _resolve_douyin_dm_login_source(account_id)", block)
        self.assertIn("_seed_login_state_into_profile(profile_dir, login_source.get('profileDir'))", block)
        self.assertLess(
            block.index("login_source = _resolve_douyin_dm_login_source(account_id)"),
            block.index("sync_playwright"),
        )

    def test_browser_read_dm_inbox_forwards_account_to_isolated_child(self):
        block = self.inbox_block()
        self.assertIn("DY_DM_INBOX_ACCOUNT_ID", block)
        self.assertIn("account_id=account_id", block)

    def test_browser_read_dm_inbox_injects_account_cookie_before_navigation(self):
        block = self.inbox_block()
        self.assertIn("_douyin_dm_context_cookies", block)
        self.assertIn("ctx.add_cookies(dm_context_cookies)", block)
        self.assertIn("dmCookieInjection", block)
        self.assertLess(
            block.index("ctx.add_cookies(dm_context_cookies)"),
            block.index("page.goto(profile_url"),
        )

    def test_browser_read_dm_inbox_diagnostics_do_not_expose_cookie_values(self):
        block = self.inbox_block()
        self.assertIn("attemptedCount", block)
        self.assertIn("addedCount", block)
        self.assertNotIn("'cookie':", block)
        self.assertNotIn('"cookie":', block)


class DouyinDmClientAutoReplySourceTest(unittest.TestCase):
    def test_client_contains_merge_window_state_and_since_fingerprint(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        self.assertIn("_auto_pending_texts", source)
        self.assertIn("_auto_last_reply_at", source)
        self.assertIn("_auto_last_fingerprint", source)
        self.assertIn("sinceFingerprint", source)
        self.assertIn("DM_AUTO_REPLY_POLL_MS = 20000", source)
        self.assertIn("DM_AUTO_REPLY_MERGE_WINDOW_SEC = 300", source)
        self.assertIn("_auto_baseline_pending", source)

    def test_client_manual_required_does_not_auto_send_non_text(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        self.assertIn("manual_required", source)
        self.assertIn("收到非文本私信，请人工查看该客户会话。", source)
        self.assertIn("_auto_handle_inbox_messages", source)

    def test_client_auto_reply_uses_existing_send_path(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        self.assertIn("self.send_reply(reply)", source)
        self.assertIn("douyin.dm.inbox", source)
        self.assertIn("_auto_flush_buffer", source)

    def test_client_inbox_poll_uses_local_api_not_central_task_result(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        start = source.index("def _auto_poll(self):")
        end = source.index("    def _on(self, tag, d):", start)
        block = source[start:end]
        self.assertIn('local_api("POST", "/api/douyin/dm/inbox"', block)
        self.assertNotIn('submit_local_task("douyin.dm.inbox"', block)

    def test_client_uses_same_account_for_inbox_poll_and_send(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        start = source.index("class DMPage")
        end = source.index("class CopywritingPage", start)
        block = source[start:end]
        self.assertIn('"accountId": self._dm_account_id', block)
        send_start = block.index("def send_reply")
        send_end = block.index("\n    def toggle_auto", send_start)
        send_block = block[send_start:send_end]
        self.assertIn('submit_local_task(', send_block)
        self.assertIn('"douyin.dm"', send_block)
        self.assertIn('{"target": t, "content": c, "accountId": self._dm_account_id}', send_block)
        self.assertIn('self._dm_account_id = str((d or {}).get("accountId") or "").strip()', block)

    def test_finder_followup_passes_selected_account_to_dm_page(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        start = source.index("class FinderPage")
        end = source.index("class OutreachPage", start)
        block = source[start:end]
        self.assertIn('"accountId": self._selected_finder_account_id()', block)

    def test_client_skips_non_customer_messages_and_bounds_seen_set(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        self.assertIn('if direction != "customer":', source)
        self.assertIn("self._seen.discard(old_fp)", source)

    def test_client_send_failure_restores_buffer_and_removes_unsent_history(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        self.assertIn("_auto_sending_text", source)
        self.assertIn("hist.pop()", source)
        self.assertIn('stage="send"', source)

    def test_client_send_failure_status_surfaces_child_diagnostics(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        self.assertIn("def _dm_send_error_text", source)
        self.assertIn("dm_child_inner_exception", source)
        self.assertIn("dm_child_no_json_marker", source)
        self.assertIn("returncode", source)
        self.assertIn("stackTail", source)
        self.assertIn("_dm_send_error_text(d, rr)", source)

    def test_client_send_failure_explains_dm_input_not_found(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        start = source.index("def _dm_send_error_text")
        end = source.index("\n    def gen_reply", start)
        block = source[start:end]
        self.assertIn("dm_input_not_found", block)
        self.assertIn("已点开私信", block)
        self.assertIn("editorCandidateCount", block)
        self.assertIn("frameIndex", block)

    def test_client_send_failure_explains_dm_panel_not_open(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        start = source.index("def _dm_send_error_text")
        end = source.index("\n    def gen_reply", start)
        block = source[start:end]
        self.assertIn("dm_panel_not_open", block)
        self.assertIn("私信按钮已点击", block)
        self.assertIn("clickedSelector", block)

    def test_client_send_failure_explains_dm_button_not_found_and_save_prompt(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        start = source.index("def _dm_send_error_text")
        end = source.index("\n    def gen_reply", start)
        block = source[start:end]
        self.assertIn("dm_button_not_found", block)
        self.assertIn("保存登录信息", block)
        self.assertIn("saveLoginPrompt", block)
        self.assertIn('prompt.get("finalPromptVisible")', block)
        self.assertIn("browserKeptOpenMs", block)
        self.assertIn("手动点掉弹窗", block)

    def test_client_send_failure_explains_dm_not_authenticated(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        start = source.index("def _dm_send_error_text")
        end = source.index("\n    def gen_reply", start)
        block = source[start:end]
        self.assertIn("not_authenticated", block)
        self.assertIn("账号矩阵", block)
        self.assertIn("重新登录抖音", block)

    def test_client_disables_dm_isolated_child_for_packaged_runtime(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        start = source.index("def setup_env")
        end = source.index("\ndef account_key", start)
        block = source[start:end]
        self.assertIn('os.environ.setdefault("DY_SEARCH_ISOLATED", "0")', block)
        self.assertIn('os.environ.setdefault("DY_DM_ISOLATED", "0")', block)

    def test_client_ai_failure_logs_message_fingerprint_before_restoring_buffer(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        start = source.index('stage="ai"')
        block_start = source.rfind('if d.get("auto")', 0, start)
        block = source[block_start:start + 500]
        self.assertLess(
            block.index("failed_message_fp = self._auto_flushing_message_fingerprint()"),
            block.index("self._auto_flushing_texts = []"),
        )
        self.assertIn("messageFingerprint=failed_message_fp", block)

    def test_client_stops_auto_reply_on_login_or_dm_permission_errors(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        self.assertIn("DM_AUTO_REPLY_FATAL_INBOX_ERRORS", source)
        self.assertIn("not_authenticated", source)
        self.assertIn("dm_inbox_button_not_found", source)
        self.assertIn("_stop_auto_reply_for_inbox_error", source)
        start = source.index('if tag == "dm_inbox":')
        end = source.index('            msgs = res.get("messages")', start)
        block = source[start:end]
        self.assertIn("_stop_auto_reply_for_inbox_error(err)", block)
        self.assertNotIn("return\n            msgs", block)

    def test_dm_inbox_uses_stable_profile_instead_of_per_poll_temp_profile(self):
        source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        start = source.index("def browser_read_dm_inbox")
        end = source.index("\ndef list_download_files", start)
        block = source[start:end]
        self.assertIn('os.path.join(profile_base, "current")', block)
        self.assertNotIn("tempfile.mkdtemp", block)
        self.assertNotIn("shutil.rmtree(profile_dir", block)


class DouyinDmSendBrowserSourceTest(unittest.TestCase):
    def dm_send_block(self):
        source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        start = source.index("def browser_send_dm")
        end = source.index("\ndef _dm_text_fingerprint", start)
        return source[start:end]

    def test_browser_send_dm_waits_for_rich_editor_candidates(self):
        block = self.dm_send_block()
        self.assertIn("DY_DM_EDITOR_WAIT_MS", block)
        self.assertIn("while time.time() < deadline", block)
        for selector in (
            '[role="textbox"]',
            '[contenteditable="plaintext-only"]',
            '[contenteditable="true"]',
            "textarea",
            "input",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, block)

    def test_browser_send_dm_reports_safe_editor_diagnostics(self):
        block = self.dm_send_block()
        self.assertIn("dmEditorDiagnostics", block)
        self.assertIn("editorCandidateCount", block)
        self.assertNotIn("contentFingerprint", block)

    def test_browser_send_dm_checks_account_matrix_login_before_opening_browser(self):
        block = self.dm_send_block()
        self.assertIn("_resolve_douyin_dm_login_source", block)
        self.assertIn("dm_login_profile_not_ready", block)
        self.assertIn("not_authenticated", block)
        self.assertIn("needLogin", block)
        self.assertLess(block.index("_resolve_douyin_dm_login_source"), block.index("sync_playwright"))

    def test_browser_send_dm_seeds_from_resolved_account_profile(self):
        source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        block = self.dm_send_block()
        self.assertIn("login_source = _resolve_douyin_dm_login_source", block)
        self.assertIn("_seed_login_state_into_profile(profile_dir, login_source.get('profileDir'))", block)
        self.assertIn("default_douyin_comment_account_id", source)
        self.assertIn("douyin_account_paths", source)

    def test_browser_send_dm_injects_resolved_account_cookie_before_navigation(self):
        block = self.dm_send_block()
        self.assertIn("_douyin_dm_context_cookies", block)
        self.assertIn("ctx.add_cookies(dm_context_cookies)", block)
        self.assertIn("dmCookieInjection", block)
        self.assertLess(
            block.index("ctx.add_cookies(dm_context_cookies)"),
            block.index("page.goto(profile_url"),
        )

    def test_browser_send_dm_excludes_search_boxes_before_typing(self):
        block = self.dm_send_block()
        self.assertIn("search_box_rejected", block)
        self.assertIn("isSearchLike", block)
        self.assertIn("search", block)
        self.assertIn("搜索", block)
        self.assertIn("r.top < 120", block)

    def test_browser_send_dm_prioritizes_profile_dm_button_xpaths(self):
        block = self.dm_send_block()
        self.assertIn("dm_profile_button_selectors", block)
        chrome_xpath = '//*[@id="user_detail_element"]/div/div[2]/div/div[1]/div[3]/div[3]/div[1]/button[2]'
        edge_xpath = '//*[@id="user_detail_element"]/div/div[2]/div/div[1]/div[3]/div[2]/button[1]'
        self.assertIn(chrome_xpath, block)
        self.assertIn(edge_xpath, block)
        self.assertLess(block.index(edge_xpath), block.index('text=私信'))
        self.assertIn("dmButtonSelector", block)

    def test_browser_send_dm_validates_xpath_button_text_before_clicking(self):
        block = self.dm_send_block()
        self.assertIn("dm_button_rejected", block)
        self.assertIn("is_dm_button_label", block)
        self.assertIn("rejectedButtons", block)
        self.assertLess(block.index("is_dm_button_label"), block.index("dm_button.click"))

    def test_browser_send_dm_retries_profile_dm_click_with_real_coordinates(self):
        block = self.dm_send_block()
        self.assertIn("click_profile_dm_button", block)
        self.assertIn("clickAttempts", block)
        self.assertIn("page.mouse.click", block)
        self.assertIn("clickedPanelOpened", block)
        self.assertIn("scroll_into_view_if_needed", block)
        self.assertNotIn("btn.click(timeout=8000, force=True)", block)

    def test_browser_send_dm_handles_save_login_prompt_before_finding_dm_button(self):
        block = self.dm_send_block()
        self.assertIn("dismiss_douyin_save_login_prompt", block)
        self.assertIn("是否保存登录信息", block)
        self.assertIn("saveLoginPrompt", block)
        self.assertLess(block.index("dismiss_douyin_save_login_prompt"), block.index("for sel in dm_profile_button_selectors"))

    def test_browser_send_dm_dismisses_save_login_prompt_variants(self):
        block = self.dm_send_block()
        for text in ("以后再说", "暂不保存", "暂不", "关闭", "跳过"):
            with self.subTest(text=text):
                self.assertIn(text, block)
        self.assertIn("page.mouse.click", block)
        self.assertIn("realMouseClick", block)
        self.assertIn("--disable-save-password-bubble", block)
        self.assertIn("credentials_enable_service", block)
        self.assertIn("password_manager_enabled", block)
        self.assertIn("DY_DM_KEEP_BROWSER_ON_BLOCKED_PROMPT_MS", block)

    def test_browser_send_dm_requires_panel_open_after_button_click(self):
        block = self.dm_send_block()
        self.assertIn("dm_panel_probe_js", block)
        self.assertIn("dm_panel_not_open", block)
        self.assertIn("panelOpened", block)
        self.assertIn("收起会话", block)
        self.assertIn("strongMarkers", block)
        self.assertIn("panelOpened: strongMarkers.length > 0", block)
        self.assertNotIn("if (text.includes('私信') || text.includes('消息')) score += 80;", block)

    def test_browser_send_dm_clicks_conversation_send_button(self):
        block = self.dm_send_block()
        self.assertIn("dm_send_button_not_found", block)
        self.assertIn("dm_send_button_click_js", block)
        self.assertIn("发送", block)
        self.assertIn("editorRect", block)
        self.assertIn("buttonCandidates", block)

    def test_browser_send_dm_activates_bottom_composer_before_scanning(self):
        block = self.dm_send_block()
        self.assertIn("dm_editor_focus_js", block)
        self.assertIn("发送消息", block)
        self.assertIn("focusCandidateCount", block)
        self.assertIn("r.top > vh * 0.55", block)

    def test_browser_send_dm_scans_frames_for_editor(self):
        block = self.dm_send_block()
        self.assertIn("scan_dm_editor_contexts", block)
        self.assertIn("for frame_index, frame in enumerate(page.frames)", block)
        self.assertIn("editor_context", block)
        self.assertIn("frameIndex", block)

    def test_browser_send_dm_child_process_wraps_inner_exceptions(self):
        block = self.dm_send_block()
        self.assertIn("dm_child_inner_exception", block)
        self.assertIn("traceback.format_exc", block)
        self.assertIn("stackTail", block)
        self.assertIn("returncode", block)

    def test_browser_send_dm_skips_isolated_child_when_python_c_is_unavailable(self):
        block = self.dm_send_block()
        self.assertIn("_python_c_child_cmd()", block)
        self.assertIn("child_cmd is not None", block)
        self.assertIn("dm_child_no_json_marker", block)

    def test_dm_route_passes_account_id_to_send_path(self):
        source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        start = source.index("if path == '/api/douyin/dm':")
        end = source.index("if path == '/api/douyin/dm/inbox':", start)
        block = source[start:end]
        self.assertIn("body.get('accountId')", block)
        self.assertIn("body.get('account')", block)
        self.assertIn("run_douyin_dm(", block)


class DouyinDmAutoReplyObservabilityTest(unittest.TestCase):
    def client_event_chunks(self, event):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        chunks = []
        start = 0
        needle = '"%s"' % event
        while True:
            idx = source.find(needle, start)
            if idx < 0:
                break
            block_start = source.rfind("json_log(", 0, idx)
            chunks.append(source[block_start:idx + 700])
            start = idx + len(needle)
        return chunks

    def test_observability_events_are_present(self):
        api_source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        client_source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        combined = api_source + "\n" + client_source
        for event in (
            "douyin_dm_inbox_poll_started",
            "douyin_dm_inbox_poll_finished",
            "douyin_dm_auto_reply_buffered",
            "douyin_dm_auto_reply_sent",
            "douyin_dm_auto_reply_manual_required",
            "douyin_dm_auto_reply_failed",
        ):
            with self.subTest(event=event):
                self.assertIn(event, combined)

    def test_dm_logs_and_audit_use_fingerprints_not_raw_messages(self):
        api_source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        client_source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        central_source = (ROOT / "backend" / "central_server.py").read_text(encoding="utf-8")
        combined = api_source + "\n" + client_source + "\n" + central_source
        self.assertIn("_dm_text_fingerprint", api_source)
        self.assertIn("_safe_text_fingerprint", client_source)
        self.assertIn("targetFingerprint", combined)
        self.assertIn("messageFingerprint", combined)
        self.assertIn("safe_local_browser_payload", central_source)
        self.assertIn("safe_local_browser_result", central_source)

    def test_central_dm_inbox_result_storage_redacts_target_and_message_text(self):
        central = importlib.import_module("central_server")
        result = {
            "ok": True,
            "platform": "douyin",
            "target": "https://www.douyin.com/user/sec-secret",
            "messages": [
                {"id": "m1", "fingerprint": "fp1", "direction": "customer", "kind": "text", "text": "raw customer text"}
            ],
            "nonTextCount": 0,
        }
        safe = central.safe_local_browser_result("douyin.dm.inbox", result)
        dumped = json.dumps(safe, ensure_ascii=False)
        self.assertNotIn("sec-secret", dumped)
        self.assertNotIn("raw customer text", dumped)
        self.assertEqual(safe["messages"][0]["text"], "")
        self.assertIn("targetFingerprint", safe)
        self.assertIn("textFingerprint", safe["messages"][0])

    def test_client_dm_auto_reply_logs_include_fingerprints_and_safe_error_codes(self):
        for event in (
            "douyin_dm_auto_reply_buffered",
            "douyin_dm_auto_reply_manual_required",
            "douyin_dm_auto_reply_sent",
        ):
            chunks = self.client_event_chunks(event)
            self.assertTrue(chunks, event)
            for chunk in chunks:
                with self.subTest(event=event):
                    self.assertIn("targetFingerprint=", chunk)
                    self.assertIn("messageFingerprint=", chunk)

        failed_chunks = self.client_event_chunks("douyin_dm_auto_reply_failed")
        self.assertTrue(failed_chunks)
        for chunk in failed_chunks:
            with self.subTest(event="douyin_dm_auto_reply_failed"):
                self.assertIn("targetFingerprint=", chunk)
                self.assertIn("messageFingerprint=", chunk)
                self.assertIn("errorCode=", chunk)
                self.assertNotIn("error=str(", chunk)
