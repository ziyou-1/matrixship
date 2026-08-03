from pathlib import Path
import importlib.util
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"
API_SERVER = ROOT / "backend" / "api_server.py"
PLATFORM_ADAPTERS = ROOT / "backend" / "platform_adapters.py"


def load_client():
    spec = importlib.util.spec_from_file_location("matrix_native_client_for_native_publish", CLIENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class NativePublishTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client()

    def test_publish_result_requires_real_published_signal_for_live_publish(self):
        result = {
            "status": "done",
            "result": {"ok": True, "filled": True, "published": False, "dryRun": True},
        }

        self.assertFalse(self.client._publish_result_ok(result, dry=False))

    def test_native_publish_button_requests_live_publish_not_dry_run(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class PublishPage")
        publish_start = src.index("    def publish(self):", start)
        publish_end = src.index("    def _title_cell_changed(self, item):", publish_start)
        publish_src = src[publish_start:publish_end]

        self.assertIn('"dryRun": False', publish_src)

    def test_native_publish_uses_title_dialog_as_publish_title_source(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class PublishPage")
        init_start = src.index("    def __init__(self):", start)
        load_start = src.index("    def on_show(self):", init_start)
        init_src = src[init_start:load_start]
        publish_start = src.index("    def publish(self):", start)
        publish_end = src.index("    def _title_cell_changed(self, item):", publish_start)
        publish_src = src[publish_start:publish_end]
        on_start = src.index("    def _on(self, tag, d):", start)
        sales_start = src.index("SALES_STYLES =", on_start)
        on_src = src[on_start:sales_start]

        self.assertIn("self.table.setHorizontalHeaderLabels", init_src)
        self.assertIn("self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)", init_src)
        self.assertIn("self.table.cellDoubleClicked.connect(self._edit_title_dialog)", init_src)
        self.assertIn("dlg = QtWidgets.QDialog(self)", src)
        self.assertIn("editor = QtWidgets.QPlainTextEdit()", src)
        self.assertIn("title_item = self.table.item(r, 0)", publish_src)
        self.assertIn("publish_title_for_run = publish_title[:publish_title_limit]", publish_src)
        self.assertIn('"publishTitle": publish_title_for_run', publish_src)
        self.assertIn("title_item.setFlags(title_item.flags() & ~QtCore.Qt.ItemIsEditable)", on_src)

    def test_native_publish_title_header_shows_platform_title_limits(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class PublishPage")
        init_start = src.index("    def __init__(self):", start)
        load_start = src.index("    def on_show(self):", init_start)
        init_src = src[init_start:load_start]

        self.assertIn("标题（可编辑，抖音最多30字，小红书最多20字）", init_src)

    def test_native_publish_limits_title_length_by_selected_platform(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class PublishPage")
        publish_start = src.index("    def publish(self):", start)
        publish_end = src.index("    def _title_cell_changed(self, item):", publish_start)
        publish_src = src[publish_start:publish_end]

        self.assertIn('publish_title_limit = 20 if platform == "xhs" else 30', publish_src)
        self.assertIn("publish_title_for_run = publish_title[:publish_title_limit]", publish_src)

    def test_local_publish_api_accepts_publish_title_override(self):
        src = API_SERVER.read_text(encoding="utf-8")
        start = src.index("if path == '/api/publish/run':")
        end = src.index("return json_response(self, {'ok': False, 'error': 'not_found'", start)
        publish_run_src = src[start:end]

        self.assertIn("publish_title = str(body.get('publishTitle')", publish_run_src)
        self.assertIn("title_override=publish_title", publish_run_src)

    def test_local_publish_api_accepts_platform_override(self):
        src = API_SERVER.read_text(encoding="utf-8")
        start = src.index("if path == '/api/publish/run':")
        end = src.index("return json_response(self, {'ok': False, 'error': 'not_found'", start)
        publish_run_src = src[start:end]

        self.assertIn("publish_platform = platform_code(body.get('platform')", publish_run_src)
        self.assertIn("run_publish(m, account_id, dry_run=dry, title_override=publish_title, platform=publish_platform)", publish_run_src)

    def test_xhs_publish_receives_image_note_body_and_tags_from_material(self):
        src = API_SERVER.read_text(encoding="utf-8")
        start = src.index("def run_publish(")
        end = src.index("def run_queue_item", start)
        run_src = src[start:end]

        self.assertIn("publish_body = material.get('body'", run_src)
        self.assertIn("publish_tags = material.get('tags'", run_src)
        self.assertIn("body=publish_body", run_src)
        self.assertIn("tags=publish_tags", run_src)

    def test_native_publish_page_allows_platform_account_switching(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class PublishPage")
        init_start = src.index("    def __init__(self):", start)
        load_start = src.index("    def on_show(self):", init_start)
        init_src = src[init_start:load_start]
        load_method_start = src.index("    def load(self):", start)
        upload_start = src.index("    def upload(self):", load_method_start)
        load_src = src[load_method_start:upload_start]
        on_start = src.index("    def _on(self, tag, d):", start)
        sales_start = src.index("SALES_STYLES =", on_start)
        on_src = src[on_start:sales_start]
        publish_start = src.index("    def publish(self):", start)
        publish_end = src.index("    def _title_cell_changed(self, item):", publish_start)
        publish_src = src[publish_start:publish_end]

        self.assertIn("self.platform = QtWidgets.QComboBox()", init_src)
        self.assertIn('self.platform.addItem("抖音", "douyin")', init_src)
        self.assertIn("if xhs_enabled():", init_src)
        self.assertIn("self.platform.addItem(XHS_PLATFORM_LABEL, XHS_PLATFORM_CODE)", init_src)
        self.assertNotIn('self.platform.addItem("小红书", "xhs")', init_src)
        self.assertIn("load_account_matrix_rows()", load_src)
        self.assertIn("self._refresh_publish_accounts()", on_src)
        self.assertNotIn('clean_accounts(d.get("accounts") or [], platform="douyin", ready_only=True)', on_src)
        after_refresh = on_src.split("self._refresh_publish_accounts()", 1)[1]
        self.assertNotIn("self.acc.clear()", after_refresh)
        self.assertNotIn("self.acc.addItem((a.get(\"name\")", after_refresh)
        self.assertIn('"platform": platform', publish_src)

    def test_account_matrix_prefers_local_multi_accounts_over_single_central_row(self):
        rows = self.client.merge_account_sources(
            [
                {
                    "id": "lb-ch-202607151456:douyin-17fdbbef58f7d574",
                    "localAccountId": "douyin-17fdbbef58f7d574",
                    "nodeId": "lb-ch-202607151456",
                    "platform": "douyin",
                    "name": "抖音账号 f7d574",
                    "cookieReady": True,
                    "online": True,
                },
            ],
            [
                {"id": "douyin-17fdbbef58f7d574", "platform": "douyin", "name": "抖音账号 f7d574", "cookieReady": True, "online": True},
                {"id": "douyin-ac8ea75d55e0bf83", "platform": "douyin", "name": "抖音账号 e0bf83", "cookieReady": True, "online": True},
                {"id": "douyin-6fe18651370606e4", "platform": "douyin", "name": "抖音账号 0606e4", "cookieReady": True, "online": True},
            ],
        )

        douyin = self.client.clean_accounts(rows, platform="douyin")

        self.assertEqual([a["id"] for a in douyin], [
            "douyin-17fdbbef58f7d574",
            "douyin-ac8ea75d55e0bf83",
            "douyin-6fe18651370606e4",
        ])
        self.assertEqual(douyin[0]["centralAccountId"], "lb-ch-202607151456:douyin-17fdbbef58f7d574")
        self.assertTrue(all(a.get("source") == "local-browser" for a in douyin))

    def test_account_matrix_filters_offline_default_local_douyin_placeholder(self):
        rows = self.client.merge_account_sources(
            [],
            [
                {
                    "id": "douyin-self",
                    "platform": "douyin",
                    "name": "抖音账号 n-self",
                    "cookieReady": False,
                    "online": False,
                    "needLogin": True,
                    "status": "offline",
                },
                {
                    "id": "douyin-real123456",
                    "platform": "douyin",
                    "name": "抖音账号 123456",
                    "cookieReady": False,
                    "online": False,
                    "needLogin": True,
                    "status": "offline",
                },
            ],
        )

        douyin = self.client.clean_accounts(rows, platform="douyin")

        self.assertEqual([a["id"] for a in douyin], ["douyin-real123456"])

    def test_xhs_central_only_account_is_hidden_without_local_login(self):
        rows = self.client.merge_account_sources(
            [
                {
                    "id": "lb-ch-202607151456:xhs-self",
                    "localAccountId": "xhs-self",
                    "nodeId": "lb-ch-202607151456",
                    "platform": "xhs",
                    "name": "小红书账号",
                    "cookieReady": True,
                    "online": True,
                },
            ],
            [],
        )

        xhs = self.client.clean_accounts(rows, platform="xhs")

        self.assertEqual(xhs, [])

    def test_account_display_name_prefers_real_nickname_over_generated_id(self):
        self.assertEqual(self.client.account_display_name({
            "id": "douyin-17fdbbef58f7d574",
            "platform": "douyin",
            "name": "抖音账号 f7d574",
            "nickname": "123",
            "cookieReady": True,
            "online": True,
        }), "123")

    def test_account_option_label_uses_display_name_and_session_state(self):
        ready = self.client.account_option_label({
            "id": "douyin-17fdbbef58f7d574",
            "platform": "douyin",
            "nickname": "123",
            "cookieReady": True,
            "online": True,
        })
        expired = self.client.account_option_label({
            "id": "douyin-17fdbbef58f7d574",
            "platform": "douyin",
            "nickname": "123",
            "cookieReady": False,
            "online": False,
        })

        self.assertIn("123", ready)
        self.assertIn("可用", ready)
        self.assertIn("登录态失效", expired)
        self.assertNotIn("douyin-17fdbbef58f7d574", ready)

    def test_content_finder_and_outreach_payloads_include_selected_account_id(self):
        src = CLIENT.read_text(encoding="utf-8")

        content_start = src.index("class ContentPage(")
        content_src = src[content_start:src.index("class VideoBreakdownPage(", content_start)]
        finder_start = src.index("class FinderPage(")
        finder_src = src[finder_start:src.index("class OutreachPage", finder_start)]
        outreach_start = src.index("class OutreachPage(")
        outreach_src = src[outreach_start:src.index("class PublishPage", outreach_start)]

        for block in (content_src, finder_src, outreach_src):
            self.assertIn("self.account = QtWidgets.QComboBox()", block)
            self.assertIn('payload["accountId"] = account_id', block)
            self.assertIn("account_option_label(a)", block)

        self.assertIn('BRIDGE.payload.emit("content_accounts", load_account_matrix_rows())', content_src)
        self.assertIn('emit_account_matrix_rows("finder_accounts")', finder_src)
        self.assertIn('emit_account_matrix_rows("outreach_accounts")', outreach_src)

    def test_account_matrix_delete_prefers_local_engine_and_tolerates_missing_central_record(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class AccountsPage")
        end = src.index("class TablePage", start)
        block = src[start:end]
        delete_start = block.index("    def delete(self, account_id")
        delete_src = block[delete_start:block.index("    def rename(", delete_start)]

        self.assertIn('local_api("POST", "/api/accounts/remove"', delete_src)
        self.assertIn('centralAccountId', delete_src)
        self.assertIn('account_not_found', delete_src)
        self.assertNotIn('ok = isinstance(j, dict) and j.get("ok")', delete_src)

    def test_account_matrix_rename_syncs_local_and_central_records(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class AccountsPage")
        end = src.index("class TablePage", start)
        block = src[start:end]
        rename_start = block.index("    def rename(self, account_id")
        rename_src = block[rename_start:block.index("    def _on(self, tag, d):", rename_start)]

        self.assertIn('local_api("POST", "/api/accounts/rename"', rename_src)
        self.assertIn('api("POST", "/api/accounts/rename"', rename_src)
        self.assertIn("centralAccountId", rename_src)
        self.assertIn('account_id if ":" in str(account_id or "") else ""', rename_src)

    def test_native_publish_button_label_follows_selected_platform(self):
        self.assertEqual(self.client._publish_platform_label("xhs"), "小红书")
        self.assertEqual(self.client._publish_platform_label("douyin"), "抖音")

        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class PublishPage")
        refresh_start = src.index("    def _refresh_publish_accounts(self):", start)
        edit_start = src.index("    def _edit_title_dialog(self, row, column):", refresh_start)
        refresh_src = src[refresh_start:edit_start]

        self.assertIn('self.b_pub.setText("发布到" + label)', refresh_src)

    def test_publish_result_message_prefers_nested_platform_error_over_task_failed(self):
        msg = self.client._publish_result_message({
            "status": "failed",
            "error": "task_failed",
            "result": {"ok": False, "error": "upload_input_not_found", "platform": "xhs"},
        })

        self.assertIn("upload_input_not_found", msg)
        self.assertNotIn("task_failed", msg)

    def test_publish_result_message_explains_xhs_creator_login_required(self):
        msg = self.client._publish_result_message({
            "status": "failed",
            "error": "task_failed",
            "result": {"ok": False, "error": "xhs_creator_login_required", "platform": "xhs"},
        })

        self.assertIn("小红书创作者中心未登录", msg)
        self.assertNotIn("task_failed", msg)
        self.assertNotIn("xhs_creator_login_required", msg)

    def test_xhs_publish_browser_is_visible_by_default(self):
        src = PLATFORM_ADAPTERS.read_text(encoding="utf-8")
        start = src.index("def xhs_publish_material(")
        func_src = src[start:]

        self.assertIn('_browser_kwargs(profile, "XHS_PUBLISH_HEADLESS", default_headless=False)', func_src)

    def test_xhs_collection_browser_is_visible_by_default(self):
        src = PLATFORM_ADAPTERS.read_text(encoding="utf-8")
        helper_src = src[src.index("def _xhs_open_context("):src.index("def xhs_login(")]
        search_src = src[src.index("def xhs_search_notes("):src.index("def xhs_strict_lead_filter_enabled", src.index("def xhs_search_notes("))]
        download_src = src[src.index("def xhs_download_note("):src.index("def xhs_publish_comment", src.index("def xhs_download_note("))]

        self.assertIn("default_headless=True", helper_src)
        self.assertIn("default_headless=default_headless", helper_src)
        self.assertIn('headless_env="XHS_SEARCH_HEADLESS"', search_src)
        self.assertIn("default_headless=False", search_src)
        self.assertIn('headless_env="XHS_DOWNLOAD_HEADLESS"', download_src)
        self.assertIn("default_headless=False", download_src)

    def test_xhs_content_collection_uses_saved_account_mode_by_default(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class ContentPage(")
        end = src.index("class VideoBreakdownPage(", start)
        content_src = src[start:end]

        self.assertIn("def _xhs_account_payload(self, payload, platform):", content_src)
        self.assertIn('"guestMode": False', content_src)
        self.assertIn('"accountCollectionConfirmed": True', content_src)
        self.assertIn("账号采集中：使用账号矩阵里已登录的小红书账号", content_src)
        self.assertIn("账号下载中：使用账号矩阵里已登录的小红书账号", content_src)
        self.assertNotIn("游客采集中：不使用登录账号", content_src)
        self.assertNotIn("游客下载中：不使用登录账号", content_src)

    def test_xhs_login_required_explains_saved_account_session_expired(self):
        src = CLIENT.read_text(encoding="utf-8")
        expected = "账号已存在，但登录态已失效。请到账号矩阵重新登录该平台账号后再采集。"

        self.assertIn(expected, src)
        self.assertIn('if error == "xhs_login_required":', src)
        self.assertIn('if text == "xhs_login_required":', src)

    def test_xhs_content_comments_use_account_mode_directly(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("    def comments(self):")
        end = src.index("    def post_comment(self):", start)
        comments_src = src[start:end]

        self.assertIn('"guestMode": False', comments_src)
        self.assertIn('"accountCollectionConfirmed": True', comments_src)
        self.assertIn("账号读取评论中：使用已登录小红书账号", comments_src)
        self.assertNotIn("_xhs_guest_payload", comments_src)
        self.assertNotIn("_remember_xhs_retry", comments_src)

    def test_xhs_guest_collection_has_one_time_account_retry_dialog(self):
        self.assertTrue(self.client._is_xhs_guest_collection_block({
            "status": "failed",
            "result": {"error": "xhs_guest_access_limited", "guestMode": True},
        }))

        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("公开访问受限", src)
        self.assertIn("使用账号采集一次", src)
        self.assertIn('"accountCollectionConfirmed": True', src)
        self.assertIn('"guestMode": False', src)

    def test_xhs_finder_uses_account_mode_for_comment_collection(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class FinderPage(")
        end = src.index("class GrowthPage(", start)
        finder_src = src[start:end]

        self.assertIn('"guestMode": False', finder_src)
        self.assertIn('"accountCollectionConfirmed": True', finder_src)
        self.assertIn("账号寻客中：使用已登录小红书账号读取评论", finder_src)
        self.assertNotIn("游客寻客中：不使用登录账号", finder_src)

    def test_xhs_publish_detects_creator_login_redirect_before_upload_input(self):
        src = PLATFORM_ADAPTERS.read_text(encoding="utf-8")
        start = src.index("def xhs_publish_material(")
        func_src = src[start:]

        self.assertIn("xhs_creator_login_required", func_src)
        self.assertLess(func_src.index("xhs_creator_login_required"), func_src.index('page.locator("input[type=file]")'))

    def test_xhs_publish_waits_for_creator_login_before_returning_error(self):
        src = PLATFORM_ADAPTERS.read_text(encoding="utf-8")
        start = src.index("def xhs_publish_material(")
        func_src = src[start:]

        self.assertIn("_wait_for_xhs_creator_login(page, ctx, creator_url)", func_src)
        self.assertIn("if not _wait_for_xhs_creator_login(page, ctx, creator_url):", func_src)
        self.assertLess(func_src.index("if not _wait_for_xhs_creator_login(page, ctx, creator_url):"), func_src.index("xhs_creator_login_required"))

    def test_xhs_creator_login_wait_uses_visible_login_timeout(self):
        src = PLATFORM_ADAPTERS.read_text(encoding="utf-8")

        self.assertIn("def _wait_for_xhs_creator_login(", src)
        self.assertIn('os.getenv("XHS_CREATOR_LOGIN_TIMEOUT"', src)
        helper_src = src[src.index("def _wait_for_xhs_creator_login("):src.index("def _xhs_profile_has_login_cookie")]
        self.assertIn("input[type=file]", helper_src)

    def test_xhs_creator_login_wait_does_not_refresh_login_page_from_cookies(self):
        src = PLATFORM_ADAPTERS.read_text(encoding="utf-8")
        helper_src = src[src.index("def _wait_for_xhs_creator_login("):src.index("def _xhs_profile_has_login_cookie")]

        self.assertNotIn("page.goto(creator_url", helper_src)
        self.assertNotIn("XHS_STRONG_LOGIN_COOKIES", helper_src)

    def test_xhs_publish_returns_explicit_error_when_publish_not_confirmed(self):
        src = PLATFORM_ADAPTERS.read_text(encoding="utf-8")
        start = src.index("def xhs_publish_material(")
        func_src = src[start:]

        self.assertIn('clicked.get("error") or "publish_unconfirmed"', func_src)

    def test_xhs_publish_accepts_publish_note_button_label(self):
        src = PLATFORM_ADAPTERS.read_text(encoding="utf-8")
        start = src.index("def xhs_publish_material(")
        func_src = src[start:]

        self.assertIn("exactPublishLabels", func_src)
        self.assertIn("'发布笔记'", func_src)
        self.assertNotIn("! /\\u53d1\\u5e03\\u7b14\\u8bb0", func_src)

    def test_xhs_image_note_publish_switches_to_image_tab_before_upload(self):
        src = PLATFORM_ADAPTERS.read_text(encoding="utf-8")
        start = src.index("def xhs_publish_material(")
        func_src = src[start:]

        self.assertIn('material_type_code == "image_note"', func_src)
        self.assertIn("_xhs_select_image_note_tab", func_src)
        self.assertIn("上传图文", func_src)
        self.assertLess(func_src.index("_xhs_select_image_note_tab"), func_src.index('inputs = page.locator("input[type=file]")'))

    def test_xhs_image_note_publish_fills_body_and_tags_separately(self):
        src = PLATFORM_ADAPTERS.read_text(encoding="utf-8")
        start = src.index("def xhs_publish_material(")
        func_src = src[start:]

        self.assertIn('def xhs_publish_material(files, title, material_type="video", dry_run=True, data_dir="", body="", tags=None):', src)
        self.assertIn("body_text", func_src)
        self.assertIn("tag_text", func_src)
        self.assertIn("page.keyboard.type(body_text", func_src)
        self.assertIn("fallbackWithTags", func_src)
        self.assertNotIn("page.keyboard.type(title, delay=10)", func_src)

    def test_native_publish_page_can_open_selected_material_file(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class PublishPage")
        init_start = src.index("    def __init__(self):", start)
        load_start = src.index("    def on_show(self):", init_start)
        init_src = src[init_start:load_start]
        open_start = src.index("    def open_material(self):", start)
        refresh_start = src.index("    def _current_publish_platform(self):", open_start)
        open_src = src[open_start:refresh_start]

        self.assertIn("self.b_open = QtWidgets.QPushButton", init_src)
        self.assertIn("self.b_open.clicked.connect(self.open_material)", init_src)
        self.assertIn("bar.addWidget(self.b_open)", init_src)
        self.assertIn("self._selected_material_open_target(", open_src)
        self.assertIn("_open_path(path)", open_src)
        self.assertIn("self.status.setText", open_src)

    def test_native_publish_material_file_lookup_prefers_video_then_image(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class PublishPage")
        lookup_start = src.index("    def _material_candidate_roots(self, material):", start)
        open_start = src.index("    def open_material(self):", lookup_start)
        lookup_src = src[lookup_start:open_start]

        self.assertIn("video_exts", lookup_src)
        self.assertIn("image_exts", lookup_src)
        self.assertIn("for exts in (video_exts, image_exts)", lookup_src)
        self.assertIn("sourceDownloadPath", lookup_src)
        self.assertIn("os.path.isfile(candidate)", lookup_src)

    def test_native_publish_open_target_uses_folder_for_multi_file_material(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / "one.mp4"
            image = root / "two.jpg"
            video.write_bytes(b"video")
            image.write_bytes(b"image")

            target = self.client.PublishPage._selected_material_open_target(None, {
                "savePath": str(root),
                "files": [{"name": video.name}, {"name": image.name}],
            })

        self.assertEqual(target, str(root))

    def test_native_publish_hides_downloaded_and_mix_material_sources(self):
        visible = self.client.PublishPage._material_visible_in_publish_list

        self.assertTrue(visible(None, {"id": "manual", "title": "手动上传", "files": ["manual.mp4"]}))
        self.assertTrue(visible(None, {
            "id": "xhs-draft",
            "type": "image_note",
            "importedFromXhsNoteReplacement": True,
            "files": ["01.jpg"],
        }))
        self.assertFalse(visible(None, {
            "id": "downloaded",
            "importedFromDownload": True,
            "sourceDownloadPath": "/tmp/downloaded",
            "files": ["source.mp4"],
        }))
        self.assertFalse(visible(None, {
            "id": "mix",
            "source": "混剪短视频",
            "prompt": "混剪 3 个素材",
            "files": ["mix.mp4"],
        }))

    def test_native_publish_hides_digital_human_tts_sound_materials(self):
        visible = self.client.PublishPage._material_visible_in_publish_list

        self.assertFalse(visible(None, {
            "id": "dh-sound",
            "title": "数字人TTS声音-voice.mp3",
            "type": "audio",
            "files": ["voice.mp3"],
        }))
        self.assertFalse(visible(None, {
            "id": "dh-sound-marked",
            "title": "voice.mp3",
            "type": "audio",
            "hideFromPublish": True,
            "source": "digital_human_tts",
            "files": ["voice.mp3"],
        }))

    def test_digital_human_sound_upload_marks_material_hidden_from_publish(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class DigitalHumanPage")
        upload_start = src.index("    def _upload_asset(self, kind, path, title, mtype):", start)
        upload_end = src.index("    def upload_avatar(self):", upload_start)
        upload_src = src[upload_start:upload_end]

        self.assertIn('"hideFromPublish": True', upload_src)
        self.assertIn('"source": "digital_human_tts"', upload_src)
        self.assertIn("upload_asset_url(path, title, mtype, metadata=metadata)", upload_src)

    def test_native_publish_load_filters_material_sources_before_rendering(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class PublishPage")
        on_start = src.index("    def _on(self, tag, d):", start)
        on_end = src.index("SALES_STYLES =", on_start)
        on_src = src[on_start:on_end]

        self.assertIn("self._material_visible_in_publish_list(m)", on_src)

    def test_library_title_update_endpoint_exists_for_title_dialog(self):
        src = API_SERVER.read_text(encoding="utf-8")

        self.assertIn("if path == '/api/library/update-title':", src)
        self.assertIn("m['title'] = title", src)

    def test_live_publish_filled_without_published_is_not_labeled_as_dry_run(self):
        result = {
            "status": "done",
            "result": {
                "ok": False,
                "filled": True,
                "published": False,
                "dryRun": False,
                "error": "publish_upload_pending",
            },
        }

        msg = self.client._publish_result_message(result)

        self.assertNotIn("dryRun", msg)
        self.assertIn("publish_upload_pending", msg)

    def test_security_verify_publish_result_tells_user_to_finish_browser_verification(self):
        result = {
            "status": "done",
            "result": {
                "ok": False,
                "filled": True,
                "published": False,
                "dryRun": False,
                "error": "security_verify_required",
            },
        }

        msg = self.client._publish_result_message(result)

        self.assertIn("\u5b89\u5168\u9a8c\u8bc1", msg)
        self.assertIn("\u6d4f\u89c8\u5668", msg)

    def test_douyin_multi_file_publish_result_explains_single_video_limit(self):
        result = {
            "status": "done",
            "result": {
                "ok": False,
                "published": False,
                "dryRun": False,
                "error": "douyin_single_video_required",
                "fileCount": 2,
            },
        }

        msg = self.client._publish_result_message(result)

        self.assertIn("\u6296\u97f3\u89c6\u9891\u53d1\u5e03\u53ea\u652f\u6301\u5355\u4e2a\u89c6\u9891\u6587\u4ef6", msg)
        self.assertIn("2", msg)

    def test_closed_browser_upload_publish_result_is_shown_in_chinese(self):
        result = {
            "status": "done",
            "result": {
                "ok": False,
                "published": False,
                "dryRun": False,
                "error": "Locator.set_input_files: Target page, context or browser has been closed",
            },
        }

        msg = self.client._publish_result_message(result)

        self.assertIn("\u53d1\u5e03\u9875\u9762\u6216\u6d4f\u89c8\u5668\u5df2\u5173\u95ed", msg)
        self.assertNotIn("Target page, context or browser has been closed", msg)

    def test_local_publish_api_response_preserves_dry_run_flag(self):
        src = API_SERVER.read_text(encoding="utf-8")
        start = src.index("if path == '/api/publish/run':")
        end = src.index("return json_response(self, {'ok': False, 'error': 'not_found'", start)
        publish_run_src = src[start:end]

        self.assertIn("'dryRun': bool(dry)", publish_run_src)

    def test_local_publish_api_response_preserves_xhs_button_diagnostics(self):
        src = API_SERVER.read_text(encoding="utf-8")
        start = src.index("if path == '/api/publish/run':")
        end = src.index("return json_response(self, {'ok': False, 'error': 'not_found'", start)
        publish_run_src = src[start:end]

        self.assertIn("'button': res.get('button')", publish_run_src)
        self.assertIn("'platform': publish_platform", publish_run_src)


if __name__ == "__main__":
    unittest.main()
