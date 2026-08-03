import importlib
import io
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse
import urllib.error
import urllib.request
import urllib.response
import warnings
from email.message import Message
import requests


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class ApiDownloadContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cls.api = importlib.import_module("api_server")
            cls.central = importlib.import_module("central_server")
            cls.adapters = importlib.import_module("platform_adapters")

    def setUp(self):
        self.xhs_enabled_patch = mock.patch.dict(os.environ, {"MATRIX_XHS_ENABLED": "1"})
        self.xhs_enabled_patch.start()
        self.addCleanup(self.xhs_enabled_patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old_xhs_safety_state = getattr(self.api, "XHS_SAFETY_STATE_JSON", "")
        self.api.XHS_SAFETY_STATE_JSON = str(Path(self.tmp.name) / "xhs_safety_state.json")
        self.addCleanup(self._restore_xhs_safety_state)

    def _restore_xhs_safety_state(self):
        self.api.XHS_SAFETY_STATE_JSON = self._old_xhs_safety_state

    def make_api_handler(self, payload, path="/api/douyin/download"):
        body = json.dumps(payload).encode("utf-8")
        handler = object.__new__(self.api.Handler)
        handler.path = path
        handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)
        return handler

    def make_central_handler(self, payload):
        body = json.dumps(payload).encode("utf-8")
        handler = object.__new__(self.central.Handler)
        handler.path = "/api/douyin/download"
        handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)
        return handler

    def test_douyin_download_returns_library_failure_when_material_has_no_id(self):
        for material in (None, {"title": "missing-id"}):
            with self.subTest(material=material):
                handler = self.make_api_handler({"url": "https://www.douyin.com/video/1"})
                with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                        mock.patch.object(self.api, "require_auth", return_value=object()), \
                        mock.patch.object(self.api, "download_douyin_work_with_refresh", return_value=({"title": "work"}, "/tmp/download")), \
                        mock.patch.object(self.api, "list_download_files", return_value=[{"name": "video.mp4"}]), \
                        mock.patch.object(self.api, "import_download_to_library", return_value=material), \
                        mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
                    status, payload = handler.do_POST()

                self.assertEqual(status, 500)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["stage"], "library")
                self.assertEqual(payload["error"], "library_import_failed")

    def test_douyin_detail_network_failure_returns_stable_redacted_contract(self):
        handler = self.make_api_handler({
            "url": "https://www.douyin.com/video/7664121621367812857"
        })
        cause = requests.ConnectionError(
            "HTTPSConnectionPool(host='www.douyin.com'): "
            "https://www.douyin.com/aweme/v1/web/aweme/detail/"
            "?a_bogus=signed-secret&msToken=token-secret Cookie=cookie-secret"
        )
        error = self.api.DouyinDetailNetworkError(
            "7664121621367812857", attempts=4, cause=cause
        )
        logged = []

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "require_auth", return_value=object()), \
                mock.patch.object(
                    self.api, "download_douyin_work_with_refresh", side_effect=error
                ), mock.patch.object(
                    self.api.logger, "error", side_effect=lambda raw: logged.append(raw)
                ), mock.patch.object(
                    self.api, "json_response",
                    side_effect=lambda _handler, payload, status=200: (status, payload),
                ):
            status, payload = handler.do_POST()

        self.assertEqual(status, 502)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "douyin_detail_network_failed")
        self.assertEqual(payload["stage"], "detail")
        self.assertTrue(str(payload.get("errorId") or "").startswith("err-"))
        self.assertNotIn("trace", payload)
        self.assertEqual(len(logged), 1)
        log_payload = json.loads(logged[0])
        self.assertEqual(log_payload["event"], "douyin_detail_network_failed")
        self.assertEqual(log_payload["attempt"], 4)
        self.assertEqual(log_payload["maxAttempts"], 4)
        self.assertEqual(log_payload["causeType"], "ConnectionError")
        self.assertEqual(log_payload["host"], "www.douyin.com")
        self.assertNotIn("7664121621367812857", logged[0])
        self.assertNotIn("signed-secret", logged[0])
        self.assertNotIn("token-secret", logged[0])
        self.assertNotIn("cookie-secret", logged[0])

    def test_xhs_download_returns_library_failure_when_material_has_no_id(self):
        handler = self.make_api_handler(
            {
                "url": "https://www.xiaohongshu.com/explore/note-1",
                "accountCollectionConfirmed": True,
            },
            path="/api/xhs/download",
        )
        upstream = {
            "ok": True,
            "savePath": "/tmp/xhs-download",
            "note": {"title": "note"},
        }
        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "xhs_profile_ready", return_value=True), \
                mock.patch.object(self.api, "xhs_download_note", return_value=upstream), \
                mock.patch.object(self.api, "import_download_to_library", return_value=None), \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 500)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload.get("stage"), "library")
        self.assertEqual(payload.get("error"), "library_import_failed")

    def test_xhs_search_default_requires_account_confirmation(self):
        handler = self.make_api_handler(
            {"query": "\u4e30\u7530", "num": 3},
            path="/api/xhs/search",
        )

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "xhs_search_notes", return_value={"ok": True, "items": []}) as search, \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 429)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "xhs_account_collection_unconfirmed")
        search.assert_not_called()

    def test_xhs_confirmed_search_uses_account_mode(self):
        handler = self.make_api_handler(
            {
                "query": "\u4e30\u7530",
                "num": 3,
                "accountCollectionConfirmed": True,
            },
            path="/api/xhs/search",
        )

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "xhs_profile_ready", return_value=True), \
                mock.patch.object(self.api, "xhs_safety_preflight", return_value={"ok": True, "safety": {}}) as preflight, \
                mock.patch.object(self.api, "xhs_safety_record", return_value={"ok": True, "safety": {}}), \
                mock.patch.object(self.api, "xhs_search_notes", return_value={"ok": True, "items": []}) as search, \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        preflight.assert_called()
        self.assertFalse(search.call_args.kwargs["guest_mode"])

    def test_xhs_account_collection_requires_explicit_confirmation(self):
        handler = self.make_api_handler(
            {"query": "\u4e30\u7530", "guestMode": False},
            path="/api/xhs/search",
        )

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "xhs_search_notes") as search, \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 429)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "xhs_account_collection_unconfirmed")
        search.assert_not_called()

    def test_xhs_confirmed_account_collection_runs_safety_preflight(self):
        handler = self.make_api_handler(
            {
                "query": "\u4e30\u7530",
                "guestMode": False,
                "accountCollectionConfirmed": True,
            },
            path="/api/xhs/search",
        )

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "xhs_profile_ready", return_value=True), \
                mock.patch.object(self.api, "xhs_safety_preflight", return_value={"ok": True, "safety": {}}) as preflight, \
                mock.patch.object(self.api, "xhs_safety_record", return_value={"ok": True, "safety": {}}), \
                mock.patch.object(self.api, "xhs_search_notes", return_value={"ok": True, "items": []}) as search, \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        preflight.assert_called()
        self.assertFalse(search.call_args.kwargs["guest_mode"])

    def test_xhs_comments_default_requires_account_confirmation(self):
        handler = self.make_api_handler(
            {"url": "https://www.xiaohongshu.com/explore/note-1"},
            path="/api/xhs/comments",
        )

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "xhs_get_comments") as comments, \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 429)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "xhs_account_collection_unconfirmed")
        comments.assert_not_called()

    def test_xhs_confirmed_comments_use_account_mode(self):
        handler = self.make_api_handler(
            {
                "url": "https://www.xiaohongshu.com/explore/note-1",
                "accountCollectionConfirmed": True,
            },
            path="/api/xhs/comments",
        )

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "xhs_profile_ready", return_value=True), \
                mock.patch.object(self.api, "xhs_safety_preflight", return_value={"ok": True, "safety": {}}) as preflight, \
                mock.patch.object(self.api, "xhs_safety_record", return_value={"ok": True, "safety": {}}), \
                mock.patch.object(self.api, "xhs_get_comments", return_value={"ok": True, "items": []}) as comments, \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        preflight.assert_called()
        self.assertFalse(comments.call_args.kwargs["guest_mode"])

    def test_xhs_finder_default_requires_account_confirmation(self):
        handler = self.make_api_handler(
            {"keyword": "\u4e30\u7530", "platform": "xhs"},
            path="/api/finder/discover",
        )

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "discover_leads_by_keyword_platform") as discover, \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 429)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "xhs_account_collection_unconfirmed")
        discover.assert_not_called()

    def test_xhs_confirmed_finder_uses_account_mode(self):
        handler = self.make_api_handler(
            {
                "keyword": "\u4e30\u7530",
                "platform": "xhs",
                "accountCollectionConfirmed": True,
            },
            path="/api/finder/discover",
        )

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "xhs_profile_ready", return_value=True), \
                mock.patch.object(self.api, "xhs_safety_preflight", return_value={"ok": True, "safety": {}}) as preflight, \
                mock.patch.object(self.api, "xhs_safety_record", return_value={"ok": True, "safety": {}}), \
                mock.patch.object(self.api, "discover_leads_by_keyword_platform", return_value={"ok": True, "leads": []}) as discover, \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        preflight.assert_called()
        self.assertFalse(discover.call_args.kwargs["guest_mode"])

    def test_xhs_download_filters_page_static_images_before_download(self):
        raw = [
            {
                "url": "data:image/png;base64,AAAA",
                "kind": "image",
                "width": 300,
                "height": 300,
            },
            {
                "url": "https://fe-platform.xhscdn.com/platform/nav-icon.webp",
                "kind": "image",
                "width": 220,
                "height": 220,
            },
            {
                "url": "https://picasso-static.xiaohongshu.com/fe-platform/search.png",
                "kind": "image",
                "width": 300,
                "height": 300,
            },
            {
                "url": "https://sns-webpic-qc.xhscdn.com/202607250928/note-main-image",
                "kind": "image",
                "width": 720,
                "height": 960,
            },
            {
                "url": "https://sns-video-qc.xhscdn.com/stream/note-main-video.mp4",
                "kind": "video",
                "width": 720,
                "height": 1280,
            },
        ]

        filtered = self.adapters._xhs_filter_note_media(raw, max_files=20)

        self.assertEqual(
            [x["url"] for x in filtered],
            [
                "https://sns-webpic-qc.xhscdn.com/202607250928/note-main-image",
                "https://sns-video-qc.xhscdn.com/stream/note-main-video.mp4",
            ],
        )

    def test_xhs_download_filters_comment_images_before_download(self):
        raw = [
            {
                "url": "https://sns-webpic-qc.xhscdn.com/202607250928/note-main-image",
                "kind": "image",
                "width": 720,
                "height": 960,
            },
            {
                "url": "https://sns-webpic-qc.xhscdn.com/202607250928/comment/comment-image",
                "kind": "image",
                "width": 720,
                "height": 960,
            },
        ]

        filtered = self.adapters._xhs_filter_note_media(raw, max_files=20)

        self.assertEqual([x["url"] for x in filtered], ["https://sns-webpic-qc.xhscdn.com/202607250928/note-main-image"])

    def test_xhs_note_copy_normalizer_splits_body_and_tags(self):
        normalized = self.adapters._xhs_normalize_note_copy(
            title="原始标题",
            body="正文第一段\n正文第二段 #试驾 #昆山",
            tags=["汽车", "#昆山"],
        )

        self.assertEqual(normalized["title"], "原始标题")
        self.assertEqual(normalized["body"], "正文第一段\n正文第二段")
        self.assertEqual(normalized["tags"], ["#汽车", "#昆山", "#试驾"])

    def test_xhs_download_import_receives_note_copy_and_source_path(self):
        handler = self.make_api_handler(
            {
                "url": "https://www.xiaohongshu.com/explore/note-copy",
                "accountCollectionConfirmed": True,
            },
            path="/api/xhs/download",
        )
        upstream = {
            "ok": True,
            "savePath": "/tmp/xhs_note-copy",
            "noteId": "note-copy",
            "title": "原始标题",
            "body": "正文内容",
            "tags": ["#试驾"],
            "files": [{"name": "01.jpg", "path": "/tmp/xhs_note-copy/01.jpg", "size": 10, "url": "https://cdn.example/01.jpg"}],
        }
        seen = {}

        def import_download(save_path, work=None, source_url="", platform=""):
            seen.update({"save_path": save_path, "work": dict(work or {}), "source_url": source_url, "platform": platform})
            return {
                "id": "mat-xhs-copy",
                "platform": "xhs",
                "sourceDownloadPath": save_path,
                "files": ["01.jpg"],
                "title": (work or {}).get("title"),
                "body": (work or {}).get("body"),
                "tags": (work or {}).get("tags"),
            }

        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "xhs_profile_ready", return_value=True), \
                mock.patch.object(self.api, "xhs_download_note", return_value=dict(upstream)), \
                mock.patch.object(self.api, "import_download_to_library", side_effect=import_download), \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(seen["save_path"], "/tmp/xhs_note-copy")
        self.assertEqual(seen["work"]["title"], "原始标题")
        self.assertEqual(seen["work"]["body"], "正文内容")
        self.assertEqual(seen["work"]["tags"], ["#试驾"])
        self.assertEqual(payload["material"]["sourceDownloadPath"], "/tmp/xhs_note-copy")

    def test_xhs_download_returns_no_note_media_when_only_page_static_images_exist(self):
        meta = self.adapters._xhs_download_meta(
            "6a63fe0f00000000050381dd",
            "https://www.xiaohongshu.com/explore/6a63fe0f00000000050381dd",
            "/tmp/xhs_6a63fe0f00000000050381dd",
            [
                {
                    "name": "",
                    "path": "",
                    "size": 0,
                    "url": "data:image/png;base64,AAAA",
                    "kind": "image",
                    "error": "unsupported_inline_image",
                },
                {
                    "name": "",
                    "path": "",
                    "size": 0,
                    "url": "https://picasso-static.xiaohongshu.com/fe-platform/search.png",
                    "kind": "image",
                    "error": "xhs_static_media_skipped",
                },
            ],
        )

        self.assertFalse(meta["ok"])
        self.assertEqual(meta["error"], "xhs_no_note_media")
        self.assertEqual(meta["stage"], "download")
        self.assertEqual(meta["files"], [])
    def test_local_download_redacts_library_exception_and_returns_contract_error(self):
        handler = self.make_api_handler({"url": "https://www.douyin.com/video/1"})
        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "require_auth", return_value=object()), \
                mock.patch.object(self.api, "download_douyin_work_with_refresh", return_value=({"title": "work"}, "/tmp/download")), \
                mock.patch.object(self.api, "list_download_files", return_value=[{"name": "video.mp4"}]), \
                mock.patch.object(self.api, "import_download_to_library", side_effect=OSError("disk full sk-test-secret-value")), \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 500)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload.get("stage"), "library")
        self.assertEqual(payload.get("error"), "library_import_failed")
        self.assertTrue(str(payload.get("errorId") or "").startswith("err-"))
        self.assertNotIn("disk full", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("sk-test-secret-value", json.dumps(payload, ensure_ascii=False))

    def test_central_download_returns_library_failure_when_mirror_has_no_id(self):
        upstream = {
            "ok": True,
            "material": {"id": "remote-1", "files": ["video.mp4"]},
        }
        task = {"id": "task-1", "nodeId": "node-1"}
        for mirrored in (None, {"title": "missing-id"}):
            with self.subTest(mirrored=mirrored):
                handler = self.make_central_handler({"orgId": "org-default"})
                with mock.patch.object(self.central, "require_role", return_value=True), \
                        mock.patch.object(self.central, "require_feature", return_value=True), \
                        mock.patch.object(self.central, "dispatch_task_sync", return_value=(dict(upstream), 200, task)), \
                        mock.patch.object(self.central, "mirror_download_material_to_library", return_value=mirrored), \
                        mock.patch.object(self.central, "add_audit", return_value=None), \
                        mock.patch.object(self.central, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
                    status, payload = handler.do_POST()

                self.assertEqual(status, 500)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["stage"], "library")
                self.assertEqual(payload["error"], "library_import_failed")

    def test_central_download_redacts_library_exception_and_returns_contract_error(self):
        upstream = {
            "ok": True,
            "material": {"id": "remote-1", "files": ["video.mp4"]},
        }
        task = {"id": "task-1", "nodeId": "node-1"}
        handler = self.make_central_handler({"orgId": "org-default"})
        with mock.patch.object(self.central, "require_role", return_value=True), \
                mock.patch.object(self.central, "require_feature", return_value=True), \
                mock.patch.object(self.central, "dispatch_task_sync", return_value=(dict(upstream), 200, task)), \
                mock.patch.object(self.central, "mirror_download_material_to_library", side_effect=OSError("disk full sk-test-secret-value")), \
                mock.patch.object(self.central, "add_audit", return_value=None), \
                mock.patch.object(self.central, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 500)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload.get("stage"), "library")
        self.assertEqual(payload.get("error"), "library_import_failed")
        self.assertTrue(str(payload.get("errorId") or "").startswith("err-"))
        self.assertNotIn("disk full", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("sk-test-secret-value", json.dumps(payload, ensure_ascii=False))

    def _complete_local_browser_download(self, mirror_result=None, mirror_error=None):
        task_id = "lbt-download-contract"
        client_id = "local-client-1"
        state = {
            "localBrowserTasks": {
                task_id: {
                    "id": task_id,
                    "orgId": "org-default",
                    "type": "douyin.download",
                    "payload": {"url": "https://www.douyin.com/video/1"},
                    "status": "running",
                    "clientId": client_id,
                    "createdAt": 1.0,
                    "updatedAt": 1.0,
                },
            },
            "localBrowserClients": {
                client_id: {"id": client_id, "orgId": "org-default", "lastSeen": 1.0},
            },
        }
        body = {
            "taskId": task_id,
            "clientId": client_id,
            "orgId": "org-default",
            "ok": True,
            "result": {
                "ok": True,
                "material": {"id": "local-material-1", "files": ["video.mp4"]},
                "materialId": "local-material-1",
            },
        }
        side_effect = mirror_error if mirror_error is not None else None
        with mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "require_role", return_value=True), \
                mock.patch.object(self.central, "mirror_download_material_to_library", return_value=mirror_result, side_effect=side_effect), \
                mock.patch.object(self.central, "persist", return_value=None), \
                mock.patch.object(self.central, "add_event", return_value=None), \
                mock.patch.object(self.central, "add_audit", return_value=None):
            return self.central.local_browser_result(mock.Mock(headers={}), body)

    def test_local_browser_download_fails_when_center_mirror_has_no_id(self):
        payload, status = self._complete_local_browser_download(
            mirror_result={"title": "missing-id"}
        )

        task = payload["task"]
        self.assertEqual(status, 200)
        self.assertEqual(task.get("status"), "failed")
        self.assertEqual(task.get("error"), "library_import_failed")
        self.assertFalse(task["result"].get("ok"))
        self.assertEqual(task["result"].get("stage"), "library")
        self.assertTrue(str(task["result"].get("errorId") or "").startswith("err-"))

    def test_local_browser_download_redacts_center_mirror_exception(self):
        payload, status = self._complete_local_browser_download(
            mirror_error=OSError("disk full sk-test-secret-value")
        )

        task = payload["task"]
        serialized = json.dumps(task, ensure_ascii=False)
        self.assertEqual(status, 200)
        self.assertEqual(task.get("status"), "failed")
        self.assertEqual(task.get("error"), "library_import_failed")
        self.assertFalse(task["result"].get("ok"))
        self.assertEqual(task["result"].get("stage"), "library")
        self.assertTrue(str(task["result"].get("errorId") or "").startswith("err-"))
        self.assertNotIn("disk full", serialized)
        self.assertNotIn("sk-test-secret-value", serialized)

    def test_local_browser_download_is_not_done_until_center_mirror_finishes(self):
        task_id = "lbt-download-finalization"
        client_id = "local-client-1"
        state = {
            "localBrowserTasks": {
                task_id: {
                    "id": task_id,
                    "orgId": "org-default",
                    "type": "douyin.download",
                    "payload": {"url": "https://www.douyin.com/video/1"},
                    "status": "running",
                    "clientId": client_id,
                    "createdAt": 1.0,
                    "updatedAt": 1.0,
                },
            },
            "localBrowserClients": {
                client_id: {"id": client_id, "orgId": "org-default", "lastSeen": 1.0},
            },
        }
        body = {
            "taskId": task_id,
            "clientId": client_id,
            "orgId": "org-default",
            "ok": True,
            "result": {
                "ok": True,
                "material": {"id": "local-material-1", "files": ["video.mp4"]},
                "materialId": "local-material-1",
            },
        }
        mirror_started = threading.Event()
        release_mirror = threading.Event()
        completed = []

        def slow_mirror(*_args, **_kwargs):
            mirror_started.set()
            if not release_mirror.wait(5):
                raise AssertionError("mirror release timed out")
            return {"id": "central-material-1", "orgId": "org-default", "files": ["video.mp4"]}

        with mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "require_role", return_value=True), \
                mock.patch.object(self.central, "mirror_download_material_to_library", side_effect=slow_mirror), \
                mock.patch.object(self.central, "persist", return_value=None), \
                mock.patch.object(self.central, "add_event", return_value=None), \
                mock.patch.object(self.central, "add_audit", return_value=None):
            thread = threading.Thread(
                target=lambda: completed.append(
                    self.central.local_browser_result(mock.Mock(headers={}), body)
                )
            )
            thread.start()
            self.assertTrue(mirror_started.wait(5))
            with self.central.LOCK:
                in_flight_status = state["localBrowserTasks"][task_id]["status"]
            release_mirror.set()
            thread.join(5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(in_flight_status, "running")
        payload, status = completed[0]
        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["status"], "done")
        self.assertEqual(payload["task"]["result"]["materialId"], "central-material-1")
        self.assertTrue(payload["task"]["result"]["libraryImported"])

    def test_local_browser_comments_result_with_dict_comments_finishes_done(self):
        task_id = "lbt-comments-finalization"
        client_id = "local-client-1"
        state = {
            "localBrowserTasks": {
                task_id: {
                    "id": task_id,
                    "orgId": "org-default",
                    "type": "douyin.comments",
                    "payload": {"url": "https://www.douyin.com/video/1"},
                    "status": "running",
                    "clientId": client_id,
                    "createdAt": 1.0,
                    "updatedAt": 1.0,
                },
            },
            "localBrowserClients": {
                client_id: {"id": client_id, "orgId": "org-default", "lastSeen": 1.0},
            },
        }
        body = {
            "taskId": task_id,
            "clientId": client_id,
            "orgId": "org-default",
            "ok": True,
            "result": {
                "ok": True,
                "comments": {"status_code": 0, "comments": [{"cid": "c1", "text": "hello"}]},
                "items": [{"id": "c1", "text": "hello"}],
                "count": 1,
            },
        }

        with mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "require_role", return_value=True), \
                mock.patch.object(self.central, "persist", return_value=None), \
                mock.patch.object(self.central, "add_event", return_value=None), \
                mock.patch.object(self.central, "add_audit", return_value=None):
            payload, status = self.central.local_browser_result(mock.Mock(headers={}), body)

        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["status"], "done")
        self.assertEqual(payload["task"]["items"], [{"id": "c1", "text": "hello"}])
        self.assertEqual(payload["task"]["comments"], [{"id": "c1", "text": "hello"}])

    def test_lk888_tls_defaults_verify_certificate_and_hostname(self):
        captured = {}
        secret = "lk888-test-secret"

        def fail_upstream(_request, timeout, context):
            captured["timeout"] = timeout
            captured["context"] = context
            raise RuntimeError("upstream rejected " + secret)

        fake_opener = mock.Mock()

        def fail_opener(_request, timeout):
            captured["timeout"] = timeout
            raise RuntimeError("upstream rejected " + secret)

        def build_test_opener(*handlers):
            for candidate in handlers:
                context = getattr(candidate, "_context", None)
                if context is not None:
                    captured["context"] = context
            return fake_opener

        fake_opener.open.side_effect = fail_opener

        old_context = self.central._LK_SSLCTX
        self.central._LK_SSLCTX = None
        try:
            with mock.patch.dict(os.environ, {
                "LK888_API_KEY": secret,
                    "LK888_BASE_URL": "https://api.lk888.ai",
            }, clear=False), \
                    mock.patch.object(self.central, "current_user", return_value={"id": "user-owner"}), \
                    mock.patch.object(self.central.urllib.request, "build_opener", side_effect=build_test_opener), \
                    mock.patch.object(self.central.urllib.request, "urlopen", side_effect=fail_upstream), \
                    mock.patch.object(self.central, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
                handler = mock.Mock(headers={})
                status, payload = self.central.lk888_proxy(
                    handler, "GET", urlparse("/lk888/v1/models")
                )
        finally:
            self.central._LK_SSLCTX = old_context

        context = captured["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(status, 502)
        self.assertNotIn(secret, json.dumps(payload, ensure_ascii=False))

    def test_lk888_sync_image_proxy_uses_client_aligned_timeout(self):
        captured = {}

        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def geturl(self):
                return "https://api.lk888.ai/v1/images/generations"

            def read(self):
                return b'{"data":[]}'

        def fake_open(_request, _context, timeout):
            captured["timeout"] = timeout
            return FakeResponse()

        body = json.dumps({"model": "gpt-image-2", "prompt": "test"}).encode("utf-8")
        handler = mock.Mock()
        handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        with mock.patch.dict(os.environ, {
                "LK888_API_KEY": "test-key", "LK888_BASE_URL": "https://api.lk888.ai"
        }, clear=False), mock.patch.object(
                self.central, "current_user", return_value={"id": "user-owner"}
        ), mock.patch.object(self.central, "_lk888_open", side_effect=fake_open):
            self.central.lk888_proxy(
                handler, "POST", urlparse("/lk888/v1/images/generations")
            )

        self.assertEqual(captured["timeout"], 480)

    def test_lk888_multipart_fields_preserve_model_and_mode_for_billing(self):
        request = requests.Request(
            "POST",
            "https://example.test",
            data={
                "model": "kling-avatar-image2video",
                "mode": "std",
                "sound_file": "https://cdn.example.com/voice.wav",
            },
            files={"image": ("avatar.png", b"image-bytes", "image/png")},
        ).prepare()

        fields = self.central._lk888_multipart_fields(
            request.body, request.headers["Content-Type"]
        )

        self.assertEqual(fields["model"], "kling-avatar-image2video")
        self.assertEqual(fields["mode"], "std")
        self.assertNotIn("image", fields)

    def test_lk888_rejects_non_https_upstream(self):
        old_context = self.central._LK_SSLCTX
        self.central._LK_SSLCTX = None
        try:
            with mock.patch.dict(os.environ, {
                "LK888_API_KEY": "lk888-test-secret",
                "LK888_BASE_URL": "http://api.lk888.ai",
            }, clear=False), \
                    mock.patch.object(self.central, "current_user", return_value={"id": "user-owner"}), \
                    mock.patch.object(self.central.urllib.request, "build_opener") as build_opener_mock, \
                    mock.patch.object(self.central.urllib.request, "urlopen") as urlopen_mock, \
                    mock.patch.object(self.central, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
                handler = mock.Mock(headers={})
                status, payload = self.central.lk888_proxy(
                    handler, "GET", urlparse("/lk888/v1/models")
                )
        finally:
            self.central._LK_SSLCTX = old_context

        self.assertEqual(status, 503)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "lk888_tls_required")
        build_opener_mock.assert_not_called()
        urlopen_mock.assert_not_called()

    def test_lk888_redacts_key_echoed_by_upstream(self):
        secret = "lk888-upstream-echo-secret"

        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self):
                return json.dumps({"authorization": "Bearer " + secret}).encode("utf-8")

        class FakeHandler:
            def __init__(self):
                self.headers = {}
                self.wfile = io.BytesIO()
                self.status = None

            def send_response(self, status):
                self.status = status

            def send_header(self, _name, _value):
                return None

            def end_headers(self):
                return None

        old_context = self.central._LK_SSLCTX
        self.central._LK_SSLCTX = None
        fake_opener = mock.Mock()
        fake_opener.open.return_value = FakeResponse()
        try:
            with mock.patch.dict(os.environ, {
                "LK888_API_KEY": secret,
                "LK888_BASE_URL": "https://api.lk888.ai",
            }, clear=False), \
                    mock.patch.object(self.central, "current_user", return_value={"id": "user-owner"}), \
                    mock.patch.object(self.central.urllib.request, "build_opener", return_value=fake_opener), \
                    mock.patch.object(self.central.urllib.request, "urlopen", return_value=FakeResponse()):
                handler = FakeHandler()
                self.central.lk888_proxy(handler, "GET", urlparse("/lk888/v1/models"))
        finally:
            self.central._LK_SSLCTX = old_context

        self.assertEqual(handler.status, 200)
        self.assertNotIn(secret.encode("utf-8"), handler.wfile.getvalue())
        self.assertIn(b"[REDACTED]", handler.wfile.getvalue())

    def test_lk888_chat_completion_without_cost_does_not_charge_usage_tokens(self):
        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def geturl(self):
                return "https://api.lk888.ai/v1/chat/completions"

            def read(self):
                return json.dumps({
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 2000},
                }).encode("utf-8")

        class FakeHandler:
            def __init__(self, body):
                self.headers = {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                }
                self.rfile = io.BytesIO(body)
                self.wfile = io.BytesIO()
                self.status = None

            def send_response(self, status):
                self.status = status

            def send_header(self, _name, _value):
                return None

            def end_headers(self):
                return None

        body = json.dumps({"model": "gpt-5.4-xhigh", "messages": []}).encode("utf-8")
        state = {
            "users": [{"id": "u1", "name": "User", "status": "active", "balance": 1.0}],
            "ledger": [],
        }
        with mock.patch.dict(os.environ, {
            "LK888_API_KEY": "test-key",
            "LK888_BASE_URL": "https://api.lk888.ai",
        }, clear=False), \
                mock.patch.object(self.central, "current_user", return_value={"id": "u1"}), \
                mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "persist", lambda: None), \
                mock.patch.object(self.central, "maindb_on", return_value=False), \
                mock.patch.object(self.central, "_lk888_open", return_value=FakeResponse()):
            handler = FakeHandler(body)
            self.central.lk888_proxy(handler, "POST", urlparse("/lk888/v1/chat/completions"))

        self.assertEqual(handler.status, 200)
        self.assertEqual(state["ledger"], [])
        self.assertEqual(state["users"][0]["balance"], 1.0)
        pending = state.get("lk888_pending_charges") or {}
        self.assertEqual(len(pending), 1)
        item = next(iter(pending.values()))
        self.assertEqual(item["userId"], "u1")
        self.assertEqual(item["model"], "gpt-5.4-xhigh")
        self.assertEqual(item["status"], "awaiting_lk888_usage_cost")
        self.assertEqual(item["source"], "chat_usage_reconcile")

    def test_lk888_generate_content_audio_transcription_registers_pending_actual_charge(self):
        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def geturl(self):
                return "https://api.lk888.ai/v1beta/models/gemini-3.1-pro-preview:generateContent"

            def read(self):
                return json.dumps({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}).encode("utf-8")

        class FakeHandler:
            def __init__(self, body):
                self.headers = {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                    "X-Matrix-Billing-Scenario": "video_breakdown",
                    "X-Matrix-Billing-Stage": "audio_transcription",
                    "X-Matrix-Billing-Detail": "audio chunk 0.000-60.000",
                }
                self.rfile = io.BytesIO(body)
                self.wfile = io.BytesIO()
                self.status = None

            def send_response(self, status):
                self.status = status

            def send_header(self, _name, _value):
                return None

            def end_headers(self):
                return None

        body = json.dumps({"contents": []}).encode("utf-8")
        state = {
            "users": [{"id": "u1", "name": "User", "status": "active", "balance": 1.0}],
            "ledger": [],
        }
        with mock.patch.dict(os.environ, {
            "LK888_API_KEY": "test-key",
            "LK888_BASE_URL": "https://api.lk888.ai",
        }, clear=False), \
                mock.patch.object(self.central, "current_user", return_value={"id": "u1"}), \
                mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "persist", lambda: None), \
                mock.patch.object(self.central, "maindb_on", return_value=False), \
                mock.patch.object(self.central, "_lk888_open", return_value=FakeResponse()):
            handler = FakeHandler(body)
            self.central.lk888_proxy(
                handler,
                "POST",
                urlparse("/lk888/v1beta/models/gemini-3.1-pro-preview:generateContent"),
            )

        self.assertEqual(handler.status, 200)
        pending = state.get("lk888_pending_charges") or {}
        self.assertEqual(len(pending), 1)
        item = next(iter(pending.values()))
        self.assertEqual(item["userId"], "u1")
        self.assertEqual(item["model"], "gemini-3.1-pro-preview")
        self.assertEqual(item["source"], "chat_usage_reconcile")
        self.assertEqual(item["billingScenario"], "video_breakdown")
        self.assertEqual(item["billingStage"], "audio_transcription")
        self.assertEqual(item["billingDetail"], "audio chunk 0.000-60.000")

    def test_lk888_usage_detail_settles_pending_chat_cost_by_model_and_time(self):
        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def geturl(self):
                return "https://api.lk888.ai/v1/skills/usage?days=1&detail=1"

            def read(self):
                return json.dumps({
                    "records": [
                        {
                            "task_id": 90109143,
                            "model": "gpt-5.4-xhigh",
                            "state": "success",
                            "cost": 0.0282,
                            "created_at": "2026-07-31T14:51:47+08:00",
                        }
                    ]
                }).encode("utf-8")

        class FakeHandler:
            def __init__(self):
                self.headers = {}
                self.wfile = io.BytesIO()
                self.status = None

            def send_response(self, status):
                self.status = status

            def send_header(self, _name, _value):
                return None

            def end_headers(self):
                return None

        state = {
            "users": [{"id": "u1", "name": "User", "status": "active", "balance": 1.0}],
            "ledger": [],
            "lk888_pending_charges": {
                "chat-local-1": {
                    "userId": "u1",
                    "model": "gpt-5.4-xhigh",
                    "ref": "lk888-chat:chat-local-1",
                    "status": "awaiting_lk888_usage_cost",
                    "source": "chat_usage_reconcile",
                    "createdAt": 1785480706.0,
                    "ts": 1785480706.0,
                }
            },
        }
        with mock.patch.dict(os.environ, {
            "LK888_API_KEY": "test-key",
            "LK888_BASE_URL": "https://api.lk888.ai",
        }, clear=False), \
                mock.patch.object(self.central, "current_user", return_value={"id": "u1"}), \
                mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "persist", lambda: None), \
                mock.patch.object(self.central, "maindb_on", return_value=False), \
                mock.patch.object(self.central, "_lk888_open", return_value=FakeResponse()):
            handler = FakeHandler()
            self.central.lk888_proxy(handler, "GET", urlparse("/lk888/v1/skills/usage?days=1&detail=1"))

        self.assertEqual(handler.status, 200)
        self.assertEqual(state["users"][0]["balance"], 0.9718)
        self.assertEqual(state["ledger"][0]["delta"], -0.0282)
        self.assertEqual(state["ledger"][0]["ref"], "lk888:90109143")
        self.assertEqual(state["ledger"][0]["taskId"], "90109143")
        self.assertEqual(state["lk888_pending_charges"], {})

    def test_lk888_usage_detail_preserves_pending_billing_context_on_ledger(self):
        state = {
            "users": [{"id": "u1", "name": "User", "status": "active", "balance": 1.0}],
            "ledger": [],
            "lk888_pending_charges": {
                "chat-local-breakdown": {
                    "userId": "u1",
                    "model": "gemini-3.1-pro-preview",
                    "ref": "lk888-chat:chat-local-breakdown",
                    "status": "awaiting_lk888_usage_cost",
                    "source": "chat_usage_reconcile",
                    "billingScenario": "video_breakdown",
                    "billingStage": "visual_analysis",
                    "billingDetail": "key frame analysis",
                    "createdAt": 1785480682.0,
                    "ts": 1785480682.0,
                }
            },
        }
        payload = {"records": [{
            "task_id": "usage-breakdown-1",
            "model": "gemini-3.1-pro-preview",
            "state": "success",
            "cost": 0.0019,
        }]}
        with mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "persist", lambda: None), \
                mock.patch.object(self.central, "maindb_on", return_value=False):
            settled = self.central.settle_lk888_pending_chat_usage_records(payload, user_id="u1")

        self.assertEqual(settled, 1)
        self.assertEqual(state["ledger"][0]["ref"], "lk888:usage-breakdown-1")
        self.assertEqual(state["ledger"][0]["billingScenario"], "video_breakdown")
        self.assertEqual(state["ledger"][0]["billingStage"], "visual_analysis")
        self.assertEqual(state["ledger"][0]["billingDetail"], "key frame analysis")
        self.assertEqual(state["lk888_pending_charges"], {})

    def test_billing_dashboard_reconciles_pending_lk888_chat_usage_before_rows(self):
        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self):
                return json.dumps({
                    "records": [
                        {
                            "task_id": 90108406,
                            "model": "gemini-3.1-pro-preview",
                            "state": "success",
                            "cost": 0.0019,
                            "created_at": "2026-07-31T14:51:21+08:00",
                        }
                    ]
                }).encode("utf-8")

        state = {
            "users": [{"id": "u1", "name": "User", "status": "active", "balance": 1.0}],
            "ledger": [],
            "lk888_pending_charges": {
                "chat-local-2": {
                    "userId": "u1",
                    "model": "gemini-3.1-pro-preview",
                    "ref": "lk888-chat:chat-local-2",
                    "status": "awaiting_lk888_usage_cost",
                    "source": "chat_usage_reconcile",
                    "createdAt": 1785480682.0,
                    "ts": 1785480682.0,
                }
            },
        }
        with mock.patch.dict(os.environ, {
            "LK888_API_KEY": "test-key",
            "LK888_BASE_URL": "https://api.lk888.ai",
        }, clear=False), \
                mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "persist", lambda: None), \
                mock.patch.object(self.central, "maindb_on", return_value=False), \
                mock.patch.object(self.central, "_lk888_open", return_value=FakeResponse()):
            payload = self.central.billing_dashboard_payload(
                "u1",
                {"startDate": "2026-07-31", "endDate": "2026-07-31", "page": 1, "pageSize": 20},
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(state["users"][0]["balance"], 0.9981)
        self.assertEqual(payload["ledger"][0]["change"], -0.0019)
        self.assertEqual(payload["ledger"][0]["modelId"], "gemini-3.1-pro-preview")
        self.assertEqual(state["lk888_pending_charges"], {})

    def test_lk888_actual_charge_can_create_arrears_after_success(self):
        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def geturl(self):
                return "https://api.lk888.ai/v1/chat/completions"

            def read(self):
                return json.dumps({
                    "choices": [{"message": {"content": "ok"}}],
                    "billing": {"amount": 0.05},
                }).encode("utf-8")

        class FakeHandler:
            def __init__(self, body):
                self.headers = {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                }
                self.rfile = io.BytesIO(body)
                self.wfile = io.BytesIO()
                self.status = None

            def send_response(self, status):
                self.status = status

            def send_header(self, _name, _value):
                return None

            def end_headers(self):
                return None

        body = json.dumps({"model": "gpt-5.4-xhigh", "messages": []}).encode("utf-8")
        state = {
            "users": [{"id": "u1", "name": "User", "status": "active", "balance": 0.01}],
            "ledger": [],
        }
        with mock.patch.dict(os.environ, {
            "LK888_API_KEY": "test-key",
            "LK888_BASE_URL": "https://api.lk888.ai",
        }, clear=False), \
                mock.patch.object(self.central, "current_user", return_value={"id": "u1"}), \
                mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "persist", lambda: None), \
                mock.patch.object(self.central, "maindb_on", return_value=False), \
                mock.patch.object(self.central, "_lk888_open", return_value=FakeResponse()):
            handler = FakeHandler(body)
            self.central.lk888_proxy(handler, "POST", urlparse("/lk888/v1/chat/completions"))

        self.assertEqual(handler.status, 200)
        self.assertEqual(state["users"][0]["balance"], -0.04)
        self.assertTrue(state["users"][0]["arrears"])
        self.assertEqual(state["ledger"][0]["delta"], -0.05)
        self.assertTrue(state["ledger"][0]["arrears"])

    def test_lk888_proxy_blocks_new_calls_when_user_is_already_in_arrears(self):
        body = json.dumps({"model": "gpt-5.4-xhigh", "messages": []}).encode("utf-8")

        class FakeHandler:
            def __init__(self, body):
                self.headers = {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                }
                self.rfile = io.BytesIO(body)
                self.wfile = io.BytesIO()
                self.status = None

            def send_response(self, status):
                self.status = status

            def send_header(self, _name, _value):
                return None

            def end_headers(self):
                return None

        state = {
            "users": [{"id": "u1", "name": "User", "status": "active", "balance": -0.01, "arrears": True}],
            "ledger": [],
        }
        with mock.patch.dict(os.environ, {
            "LK888_API_KEY": "test-key",
            "LK888_BASE_URL": "https://api.lk888.ai",
        }, clear=False), \
                mock.patch.object(self.central, "current_user", return_value={"id": "u1"}), \
                mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "maindb_on", return_value=False), \
                mock.patch.object(self.central, "_lk888_open") as upstream:
            handler = FakeHandler(body)
            self.central.lk888_proxy(handler, "POST", urlparse("/lk888/v1/chat/completions"))

        self.assertEqual(handler.status, 402)
        self.assertIn(b"account_in_arrears", handler.wfile.getvalue())
        upstream.assert_not_called()

    def test_lk888_async_generate_registers_pending_without_precharge(self):
        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def geturl(self):
                return "https://api.lk888.ai/v1/media/generate"

            def read(self):
                return json.dumps({"data": {"task_id": "task-actual-1"}}).encode("utf-8")

        class FakeHandler:
            def __init__(self, body):
                self.headers = {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                }
                self.rfile = io.BytesIO(body)
                self.wfile = io.BytesIO()
                self.status = None

            def send_response(self, status):
                self.status = status

            def send_header(self, _name, _value):
                return None

            def end_headers(self):
                return None

        body = json.dumps({"model": "doubao-seedance-1-5-pro-251215", "params": {}}).encode("utf-8")
        state = {
            "users": [{"id": "u1", "name": "User", "status": "active", "balance": 1.0}],
            "ledger": [],
        }
        with mock.patch.dict(os.environ, {
            "LK888_API_KEY": "test-key",
            "LK888_BASE_URL": "https://api.lk888.ai",
        }, clear=False), \
                mock.patch.object(self.central, "current_user", return_value={"id": "u1"}), \
                mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "persist", lambda: None), \
                mock.patch.object(self.central, "maindb_on", return_value=False), \
                mock.patch.object(self.central, "_lk888_open", return_value=FakeResponse()):
            handler = FakeHandler(body)
            self.central.lk888_proxy(handler, "POST", urlparse("/lk888/v1/media/generate"))

        self.assertEqual(handler.status, 200)
        self.assertEqual(state["users"][0]["balance"], 1.0)
        self.assertEqual(state["ledger"], [])
        pending = state.get("lk888_pending_charges") or {}
        self.assertEqual(pending["task-actual-1"]["userId"], "u1")
        self.assertEqual(pending["task-actual-1"]["model"], "doubao-seedance-1-5-pro-251215")

    def test_lk888_async_submit_cost_field_and_legacy_env_cannot_trigger_precharge(self):
        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def geturl(self):
                return "https://api.lk888.ai/v1/media/generate"

            def read(self):
                return json.dumps({
                    "data": {"task_id": "task-legacy-1"},
                    "billing": {"amount": 10.898},
                }).encode("utf-8")

        class FakeHandler:
            def __init__(self, body):
                self.headers = {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                }
                self.rfile = io.BytesIO(body)
                self.wfile = io.BytesIO()
                self.status = None

            def send_response(self, status):
                self.status = status

            def send_header(self, _name, _value):
                return None

            def end_headers(self):
                return None

        body = json.dumps({"model": "doubao-seedance-1-5-pro-251215", "params": {}}).encode("utf-8")
        state = {
            "users": [{"id": "u1", "name": "User", "status": "active", "balance": 20.0}],
            "ledger": [],
            "gen_charges": {},
        }
        with mock.patch.dict(os.environ, {
            "LK888_API_KEY": "test-key",
            "LK888_BASE_URL": "https://api.lk888.ai",
            "LK888_LEGACY_PRECHARGE_ENABLED": "1",
        }, clear=False), \
                mock.patch.object(self.central, "current_user", return_value={"id": "u1"}), \
                mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "persist", lambda: None), \
                mock.patch.object(self.central, "maindb_on", return_value=False), \
                mock.patch.object(self.central, "_lk888_open", return_value=FakeResponse()):
            handler = FakeHandler(body)
            self.central.lk888_proxy(handler, "POST", urlparse("/lk888/v1/media/generate"))

        self.assertEqual(handler.status, 200)
        self.assertEqual(state["users"][0]["balance"], 20.0)
        self.assertEqual(state["ledger"], [])
        self.assertNotIn("task-legacy-1", state.get("gen_charges") or {})
        pending = state.get("lk888_pending_charges") or {}
        self.assertEqual(pending["task-legacy-1"]["status"], "pending")
        self.assertEqual(pending["task-legacy-1"]["model"], "doubao-seedance-1-5-pro-251215")

    def test_lk888_task_status_settles_pending_with_actual_cost(self):
        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def geturl(self):
                return "https://api.lk888.ai/v1/skills/task-status?task_id=task-actual-1"

            def read(self):
                return json.dumps({
                    "data": {
                        "task_id": "task-actual-1",
                        "status": "success",
                        "cost": 5.57,
                        "requested_model": "doubao-seedance-1-5-pro-251215",
                        "actual_model": "vidu/viduq3-mix_reference2video",
                    }
                }).encode("utf-8")

        class FakeHandler:
            def __init__(self):
                self.headers = {}
                self.wfile = io.BytesIO()
                self.status = None

            def send_response(self, status):
                self.status = status

            def send_header(self, _name, _value):
                return None

            def end_headers(self):
                return None

        state = {
            "users": [{"id": "u1", "name": "User", "status": "active", "balance": 1.0}],
            "ledger": [],
            "lk888_pending_charges": {
                "task-actual-1": {
                    "userId": "u1",
                    "ref": "lk888:task-actual-1",
                    "model": "doubao-seedance-1-5-pro-251215",
                    "ts": 1,
                }
            },
        }
        with mock.patch.dict(os.environ, {
            "LK888_API_KEY": "test-key",
            "LK888_BASE_URL": "https://api.lk888.ai",
        }, clear=False), \
                mock.patch.object(self.central, "current_user", return_value={"id": "u1"}), \
                mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "persist", lambda: None), \
                mock.patch.object(self.central, "maindb_on", return_value=False), \
                mock.patch.object(self.central, "_lk888_open", return_value=FakeResponse()):
            handler = FakeHandler()
            self.central.lk888_proxy(
                handler, "GET", urlparse("/lk888/v1/skills/task-status?task_id=task-actual-1")
            )

        self.assertEqual(handler.status, 200)
        self.assertEqual(state["users"][0]["balance"], -4.57)
        self.assertTrue(state["users"][0]["arrears"])
        self.assertEqual(state["ledger"][0]["delta"], -5.57)
        self.assertEqual(state["ledger"][0]["ref"], "lk888:task-actual-1")
        self.assertEqual(state["ledger"][0]["modelId"], "viduq3-cankaosheng")
        self.assertTrue(state["ledger"][0]["arrears"])
        self.assertEqual(state["lk888_pending_charges"], {})

    def test_lk888_redirect_handler_never_issues_second_request(self):
        secret = "lk888-redirect-secret"

        for location in (
            "http://api.lk888.ai/v1/models",
            "https://other.example/v1/models",
        ):
            with self.subTest(location=location):
                seen = []

                class RedirectingTransport(urllib.request.BaseHandler):
                    handler_order = 100

                    def https_open(self, request):
                        seen.append((request.full_url, request.get_header("Authorization")))
                        if len(seen) > 1:
                            raise AssertionError("redirect issued a second HTTPS request")
                        headers = Message()
                        headers["Location"] = location
                        response = urllib.response.addinfourl(
                            io.BytesIO(b"redirect"), headers, request.full_url, 302
                        )
                        response.msg = "Found"
                        return response

                    def http_open(self, request):
                        seen.append((request.full_url, request.get_header("Authorization")))
                        raise AssertionError("redirect issued an HTTP request")

                opener = urllib.request.build_opener(
                    self.central._LK888NoRedirectHandler(),
                    RedirectingTransport(),
                )
                request = urllib.request.Request("https://api.lk888.ai/v1/models")
                request.add_header("Authorization", "Bearer " + secret)

                with self.assertRaises(urllib.error.HTTPError) as raised:
                    opener.open(request)

                self.assertEqual(raised.exception.code, 302)
                self.assertEqual(seen, [("https://api.lk888.ai/v1/models", "Bearer " + secret)])

    def test_lk888_proxy_returns_fixed_error_for_redirect(self):
        secret = "lk888-redirect-secret"
        requests = []

        class RedirectOpener:
            def open(self, request, timeout):
                requests.append((request.full_url, request.get_header("Authorization"), timeout))
                headers = Message()
                headers["Location"] = "https://other.example/v1/models"
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "Found",
                    headers,
                    io.BytesIO(("Bearer " + secret).encode("utf-8")),
                )

        old_context = self.central._LK_SSLCTX
        self.central._LK_SSLCTX = None
        try:
            with mock.patch.dict(os.environ, {
                "LK888_API_KEY": secret,
                "LK888_BASE_URL": "https://api.lk888.ai",
            }, clear=False), \
                    mock.patch.object(self.central, "current_user", return_value={"id": "user-owner"}), \
                    mock.patch.object(self.central.urllib.request, "build_opener", return_value=RedirectOpener()), \
                    mock.patch.object(self.central.urllib.request, "urlopen", side_effect=AssertionError("legacy urlopen used")), \
                    mock.patch.object(self.central, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
                handler = mock.Mock(headers={})
                status, payload = self.central.lk888_proxy(
                    handler, "GET", urlparse("/lk888/v1/models")
                )
        finally:
            self.central._LK_SSLCTX = old_context

        self.assertEqual(status, 502)
        self.assertEqual(payload, {"ok": False, "error": "lk888_upstream_error"})
        self.assertNotIn(secret, json.dumps(payload))
        self.assertEqual(len(requests), 1)

    def test_lk888_proxy_rejects_non_https_or_cross_host_final_url(self):
        class FinalUrlResponse:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __init__(self, final_url):
                self.final_url = final_url

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def geturl(self):
                return self.final_url

            def read(self):
                return b"{}"

        for final_url in (
            "http://api.lk888.ai/v1/models",
            "https://other.example/v1/models",
        ):
            with self.subTest(final_url=final_url):
                opener = mock.Mock()
                opener.open.return_value = FinalUrlResponse(final_url)
                old_context = self.central._LK_SSLCTX
                self.central._LK_SSLCTX = None
                try:
                    with mock.patch.dict(os.environ, {
                        "LK888_API_KEY": "lk888-final-url-secret",
                        "LK888_BASE_URL": "https://api.lk888.ai",
                    }, clear=False), \
                            mock.patch.object(self.central, "current_user", return_value={"id": "user-owner"}), \
                            mock.patch.object(self.central.urllib.request, "build_opener", return_value=opener), \
                            mock.patch.object(self.central, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
                        handler = mock.Mock(headers={})
                        status, payload = self.central.lk888_proxy(
                            handler, "GET", urlparse("/lk888/v1/models")
                        )
                finally:
                    self.central._LK_SSLCTX = old_context

                self.assertEqual(status, 502)
                self.assertEqual(payload, {"ok": False, "error": "lk888_upstream_error"})

    def test_public_media_url_is_signed_https_and_verifiable(self):
        now = 1784119000
        with mock.patch.dict(os.environ, {
            "PUBLIC_MEDIA_BASE_URL": "https://temporary.trycloudflare.com",
            "PUBLIC_MEDIA_TOKEN_SECRET": "public-media-secret",
            "PUBLIC_MEDIA_TTL_SEC": "600",
        }, clear=False), mock.patch.object(self.central.time, "time", return_value=now):
            url = self.central.public_media_url("mat-1", "product.png", org_id="org-default")

            parsed = urlparse(url)
            qs = dict((k, v[0]) for k, v in parse_qs(parsed.query).items())
            self.assertEqual(parsed.scheme, "https")
            self.assertEqual(parsed.netloc, "temporary.trycloudflare.com")
            self.assertEqual(parsed.path, "/api/public-media/mat-1/product.png")
            self.assertEqual(qs["orgId"], "org-default")
            self.assertEqual(qs["expires"], str(now + 600))

            ok, reason = self.central.verify_public_media_token(
                "mat-1", "product.png", qs["orgId"], qs["expires"], qs["token"], now=now + 10
            )
            self.assertTrue(ok, reason)

            ok, reason = self.central.verify_public_media_token(
                "mat-1", "product.png", qs["orgId"], qs["expires"], qs["token"], now=now + 601
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "expired")


if __name__ == "__main__":
    unittest.main()
