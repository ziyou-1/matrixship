# tests/test_replacement_web_mvp.py
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _png_bytes():
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(out, format="PNG")
    return out.getvalue()


class ReplacementWebFeatureGateTests(unittest.TestCase):
    def test_replacement_web_feature_gate_defaults_off_and_is_reversible(self):
        features = importlib.import_module("platform_features")

        self.assertFalse(features.replacement_web_enabled({}))
        self.assertFalse(
            features.replacement_web_enabled({"MATRIX_REPLACEMENT_WEB_ENABLED": "0"})
        )
        self.assertTrue(
            features.replacement_web_enabled({"MATRIX_REPLACEMENT_WEB_ENABLED": "1"})
        )
        self.assertTrue(
            features.replacement_web_enabled({"MATRIX_REPLACEMENT_WEB_ENABLED": "true"})
        )


class ReplacementWebModuleTests(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("replacement_web")

    def test_replacement_page_html_contains_two_tabs_without_marketing_surface(self):
        html = self.mod.replacement_page_html()

        self.assertIn("视频替换", html)
        self.assertIn("图文替换", html)
        self.assertIn("/api/replacement/video/start", html)
        self.assertIn("/api/replacement/note/start", html)
        self.assertIn("/api/replacement/note/save-draft", html)
        self.assertIn("X-Matrix-Agent-Token", html)
        self.assertIn("sessionStorage", html)
        self.assertIn("location.hash", html)
        self.assertIn("matrixReplacementVideoHandoffId", html)
        self.assertIn("/api/replacement/video/handoff", html)
        self.assertIn("loadVideoHandoff", html)
        self.assertNotIn("frontend", html.lower())
        self.assertNotIn("landing", html.lower())

    def test_replacement_page_html_supports_note_preview_copy_editing(self):
        html = self.mod.replacement_page_html()

        self.assertIn('id="note-preview"', html)
        self.assertIn('id="note-copy-options"', html)
        self.assertIn('name="note-copy-choice"', html)
        self.assertIn('id="note-title"', html)
        self.assertIn('id="note-body"', html)
        self.assertIn('id="note-tags"', html)
        self.assertIn("renderNotePreview", html)
        self.assertIn("populateCopyEditor", html)
        self.assertIn("collectCopyOverride", html)
        self.assertIn("selectedCopyIndex", html)
        self.assertIn("copyOverride: collectCopyOverride()", html)

    def test_replacement_page_html_handles_customer_auth_and_phase0_status(self):
        html = self.mod.replacement_page_html()

        self.assertIn("matrixReplacementUserContext", html)
        self.assertIn("formatReplacementError", html)
        self.assertIn("agent_token_required", html)
        self.assertIn("请从本地客户端打开替换网页", html)
        self.assertIn("授权已失效，请回到客户端重新打开", html)
        self.assertIn("本地视频替换任务已创建", html)
        self.assertIn("当前客户预览版暂不执行真实视频生成", html)
        self.assertIn("finally", html)

    def test_native_client_builds_replacement_web_launch_url_without_central_token(self):
        client_path = ROOT / "backend" / "matrix_native_client.py"
        spec = importlib.util.spec_from_file_location(
            "matrix_native_client_replacement_web_url_test",
            client_path,
        )
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)

        with patch.dict(os.environ, {"API_PORT": "9081", "MATRIX_AGENT_TOKEN": "local-agent-token"}, clear=False):
            client.set_session("central-user-token", "org-1", account="customer@example.com")
            client.set_auth_context({
                "user": {"id": "user-1", "displayName": "客户A", "phone": "13800000000"},
                "appRole": "enterprise_admin",
                "roleScope": "org",
            })
            url = client.replacement_web_launch_url()

        self.assertTrue(url.startswith("http://127.0.0.1:9081/replacement#"))
        self.assertIn("token=local-agent-token", url)
        self.assertIn("user=", url)
        self.assertNotIn("central-user-token", url)
        self.assertNotIn("13800000000", url)
        self.assertNotIn("phone", url)

    def test_native_client_builds_handoff_launch_url_without_local_paths_or_secrets(self):
        client_path = ROOT / "backend" / "matrix_native_client.py"
        spec = importlib.util.spec_from_file_location(
            "matrix_native_client_replacement_web_handoff_test",
            client_path,
        )
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)

        with tempfile.TemporaryDirectory() as td:
            local_video = os.path.join(td, "source-video.mp4")
            Path(local_video).write_bytes(b"fake mp4")
            with patch.object(client, "data_dir", return_value=td), patch.dict(
                os.environ,
                {"API_PORT": "9081", "MATRIX_AGENT_TOKEN": "local-agent-token"},
                clear=False,
            ):
                client.set_session("central-user-token", "org-1", account="customer@example.com")
                client.set_auth_context({
                    "user": {"id": "user-1", "displayName": "Customer A", "phone": "13800000000"},
                    "appRole": "enterprise_admin",
                    "roleScope": "org",
                })
                handoff = client.create_replacement_web_handoff({
                    "sourceUrl": "https://example.com/video/1?token=private",
                    "sourceVideoPath": local_video,
                    "platform": "douyin",
                    "breakdownAnalysis": {"meta": {"duration": 12.3}},
                })
                url = client.replacement_web_launch_url(handoff["handoffId"])

        parsed = urlparse(url)
        hash_params = parse_qs(parsed.fragment)
        self.assertEqual(parsed.path, "/replacement")
        self.assertEqual(hash_params["handoffId"], [handoff["handoffId"]])
        self.assertIn("token", hash_params)
        exposed = url
        self.assertNotIn(td, exposed)
        self.assertNotIn("source-video.mp4", exposed)
        self.assertNotIn("central-user-token", exposed)
        self.assertNotIn("13800000000", exposed)
        self.assertNotIn("phone", exposed)

    def test_video_handoff_response_redacts_local_path_and_source_secret(self):
        with tempfile.TemporaryDirectory() as td:
            local_video = os.path.join(td, "source-video.mp4")
            Path(local_video).write_bytes(b"fake mp4")
            created = self.mod.create_video_handoff(
                td,
                {
                    "sourceUrl": "https://example.com/video/1?token=private",
                    "sourceVideoPath": local_video,
                    "platform": "douyin",
                    "breakdownAnalysis": {
                        "meta": {"duration": 12.3},
                        "transcript": {"segments": [{"start": 0, "end": 1.2, "text": "hello"}]},
                    },
                },
                user={"userId": "user-1", "displayName": "Customer A"},
            )

            loaded = self.mod.load_video_handoff(td, created["handoffId"])
            response = self.mod.handoff_response(loaded)
            exposed = json.dumps(response, ensure_ascii=False)

        self.assertTrue(created["ok"])
        self.assertTrue(created["handoffId"].startswith("rwh_"))
        self.assertEqual(response["source"]["host"], "example.com")
        self.assertEqual(response["source"]["scheme"], "https")
        self.assertEqual(response["sourceVideo"]["available"], True)
        self.assertEqual(response["analysis"]["duration"], 12.3)
        self.assertEqual(response["analysis"]["transcriptSegmentCount"], 1)
        self.assertNotIn(td, exposed)
        self.assertNotIn("source-video.mp4", exposed)
        self.assertNotIn("token=private", exposed)

    def test_start_video_job_can_bind_to_existing_handoff_without_source_url_field(self):
        with tempfile.TemporaryDirectory() as td:
            local_video = os.path.join(td, "source-video.mp4")
            Path(local_video).write_bytes(b"fake mp4")
            handoff = self.mod.create_video_handoff(
                td,
                {
                    "sourceUrl": "https://example.com/video/1",
                    "sourceVideoPath": local_video,
                    "platform": "douyin",
                    "breakdownAnalysis": {"meta": {"duration": 8.0}},
                },
            )
            result = self.mod.start_video_job(
                td,
                {"handoffId": handoff["handoffId"], "sellingPoints": "fast"},
                [("characterImage", "face.png", b"fake image bytes")],
            )
            job = self.mod.load_job(td, "video", result["jobId"])
            response = self.mod.job_response(job)

        self.assertTrue(result["ok"])
        self.assertEqual(job["handoffId"], handoff["handoffId"])
        self.assertEqual(job["source"]["host"], "example.com")
        self.assertEqual(job["sourceContext"]["platform"], "douyin")
        self.assertEqual(job["sourceContext"]["duration"], 8.0)
        self.assertTrue(response["sourceContext"]["hasBreakdownAnalysis"])
        self.assertTrue(response["sourceContext"]["sourceVideoAvailable"])

    def test_start_video_job_requires_http_url_and_character_image(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.mod.start_video_job(td, {"sourceUrl": "file:///tmp/a.mp4"}, [])
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "replacement_invalid_source_url")

            result = self.mod.start_video_job(td, {"sourceUrl": "https://example.com/v/1"}, [])
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "replacement_video_missing_character_image")

    def test_start_video_job_creates_sanitized_phase0_job(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.mod.start_video_job(
                td,
                {
                    "sourceUrl": "https://example.com/video/1?token=secret",
                    "script": "hello",
                    "sellingPoints": "fast",
                },
                [("characterImage", "face.png", b"fake image bytes")],
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["jobId"].startswith("rvw_"))
            job = self.mod.load_job(td, "video", result["jobId"])
            self.assertEqual(job["status"], "queued")
            encoded = json.dumps(job, ensure_ascii=False)
            self.assertNotIn("token=secret", encoded)
            self.assertNotIn("fake image bytes", encoded)
            response = self.mod.job_response(job)
            self.assertEqual(response["source"]["host"], "example.com")
            self.assertIn("pathHash", response["source"])
            self.assertEqual(
                response["files"],
                [{"field": "characterImage", "filename": "face.png", "size": len(b"fake image bytes")}],
            )
            self.assertIn("createdAt", response)
            self.assertIn("updatedAt", response)

    def test_source_url_rejects_userinfo_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            video = self.mod.start_video_job(
                td,
                {"sourceUrl": "https://Cookie=secret@example.com/video"},
                [("characterImage", "face.png", b"fake image bytes")],
            )
            note = self.mod.start_note_job(
                td,
                {
                    "sourceUrl": "https://Authorization:BearerSecret@example.com/explore/abc",
                    "businessName": "本地门店",
                },
                [("replacementImages", "one.jpg", b"1")],
            )

            self.assertFalse(video["ok"])
            self.assertEqual(video["error"], "replacement_invalid_source_url")
            self.assertFalse(note["ok"])
            self.assertEqual(note["error"], "replacement_invalid_source_url")

    def test_start_note_job_creates_preview_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.mod.start_note_job(
                td,
                {
                    "sourceUrl": "https://www.xiaohongshu.com/explore/abc123",
                    "businessName": "本地门店",
                    "region": "杭州",
                    "sellingPoints": "预约方便, 到店体验",
                    "audience": "新客",
                    "tone": "真实种草",
                },
                [
                    ("replacementImages", "one.jpg", b"1"),
                    ("replacementImages", "two.jpg", b"2"),
                ],
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["jobId"].startswith("xnr_"))
            job = self.mod.load_job(td, "note", result["jobId"])
            response = self.mod.job_response(job)
            self.assertEqual(len(response["copyCandidates"]), 3)
            self.assertEqual(response["taskType"], "note")
            self.assertEqual(response["source"]["host"], "www.xiaohongshu.com")
            self.assertEqual(
                [{key: item[key] for key in ("field", "filename", "size")} for item in response["files"]],
                [
                    {"field": "replacementImages", "filename": "one.jpg", "size": 1},
                    {"field": "replacementImages", "filename": "two.jpg", "size": 1},
                ],
            )
            self.assertIn("filename=01_one.jpg", response["files"][0]["previewUrl"])
            self.assertIn("filename=02_two.jpg", response["files"][1]["previewUrl"])
            self.assertIsInstance(response["copyCandidates"][0], dict)
            self.assertIn("createdAt", response)
            self.assertIn("updatedAt", response)

    def test_note_job_response_exposes_safe_thumbnail_urls_without_local_paths(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.mod.start_note_job(
                td,
                {"sourceUrl": "https://www.xiaohongshu.com/explore/abc123"},
                [("replacementImages", "cover.png", _png_bytes())],
            )

            self.assertTrue(result["ok"])
            job = self.mod.load_job(td, "note", result["jobId"])
            response = self.mod.job_response(job)
            self.assertEqual(len(response["files"]), 1)
            preview_url = response["files"][0].get("previewUrl")
            self.assertTrue(preview_url.startswith("/api/replacement/file?"))
            self.assertIn("taskType=note", preview_url)
            self.assertIn("jobId=" + result["jobId"], preview_url)
            self.assertIn("filename=01_cover.png", preview_url)
            exposed = json.dumps(response, ensure_ascii=False)
            self.assertNotIn(td, exposed)
            self.assertNotIn("replacement_web_uploads", exposed)

    def test_start_note_job_creates_compatible_xhs_preview_job_with_local_files(self):
        xhs = importlib.import_module("xhs_note_replacement")
        with tempfile.TemporaryDirectory() as td:
            result = self.mod.start_note_job(
                td,
                {
                    "sourceUrl": "https://www.xiaohongshu.com/explore/abc123",
                    "businessName": "Local Shop",
                    "region": "Hangzhou",
                    "sellingPoints": "easy booking, real visit",
                },
                [
                    ("replacementImages", "one.png", _png_bytes()),
                    ("replacementImages", "two.png", _png_bytes()),
                ],
            )

            self.assertTrue(result["ok"])
            xhs_job = xhs.load_job(td, result["jobId"])
            web_job = self.mod.load_job(td, "note", result["jobId"])
            self.assertIsNotNone(xhs_job)
            self.assertEqual(xhs_job["status"], "preview")
            self.assertEqual(len(xhs_job["template"]["imageSlots"]), 2)
            self.assertEqual(len(xhs_job["slotMappings"]), 2)
            self.assertEqual(web_job["xhsJobId"], result["jobId"])
            for mapping in xhs_job["slotMappings"]:
                self.assertEqual(mapping["source"], "asset")
                self.assertTrue(os.path.isfile(mapping["filePath"]))
                self.assertTrue(mapping["filePath"].startswith(os.path.join(td, "replacement_web_uploads")))

    def test_note_job_redacts_sensitive_business_fields_and_filenames(self):
        secrets = [
            "Cookie=secret-cookie",
            "Token=secret-token",
            "Authorization: Bearer secret-auth",
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB",
            "data:text/plain;base64,c2VjcmV0LXBheWxvYWQ=",
            "https://cdn.example.com/a.png?X-Amz-Signature=abc123&token=private",
            "maliciousbase64fragmentABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/==",
        ]
        with tempfile.TemporaryDirectory() as td:
            result = self.mod.start_note_job(
                td,
                {
                    "sourceUrl": "https://www.xiaohongshu.com/explore/abc123",
                    "businessName": "正常门店 " + secrets[0],
                    "region": "杭州 " + secrets[1],
                    "sellingPoints": "预约方便, " + secrets[2] + ", " + secrets[3],
                    "audience": "新客 " + secrets[4],
                    "tone": "真实种草",
                },
                [("replacementImages", "cover_" + secrets[3] + ".jpg", b"1")],
            )

            self.assertTrue(result["ok"])
            job = self.mod.load_job(td, "note", result["jobId"])
            response = self.mod.job_response(job)
            persisted = json.dumps(job, ensure_ascii=False)
            exposed = json.dumps(response, ensure_ascii=False)
            for secret in secrets:
                self.assertNotIn(secret, persisted)
                self.assertNotIn(secret, exposed)
            for value in (persisted, exposed):
                self.assertNotRegex(value, r"(?i)cookie|token|authorization|bearer|data:")
                self.assertNotRegex(value, r"X-Amz-Signature|abc123|private")
            self.assertIn("正常门店", persisted)
            self.assertIn("杭州", persisted)

    def test_job_loader_rejects_cross_type_or_bad_id(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(self.mod.load_job(td, "video", "../bad"))
            self.assertIsNone(self.mod.load_job(td, "unknown", "rvw_abc"))


class ReplacementApiServerRouteTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module("api_server")

    def _handler(self, path, method="GET", body=b"", headers=None):
        handler = self.api.Handler.__new__(self.api.Handler)
        handler.command = method
        handler.path = path
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.request_version = "HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = None
        handler.headers = headers or {}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        return handler

    def _response(self, handler):
        handler.wfile.seek(0)
        raw = handler.wfile.read().decode("utf-8", errors="replace")
        head, _, body = raw.partition("\r\n\r\n")
        status_line = head.splitlines()[0]
        status = int(status_line.split()[1])
        headers = {}
        for line in head.splitlines()[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.lower()] = value.strip()
        return status, headers, body

    def test_replacement_page_shell_opens_without_token_but_start_api_still_requires_token(self):
        with patch.object(self.api, "replacement_web_enabled", return_value=True), patch.object(
            self.api, "token_auth_enabled", return_value=True
        ), patch.object(self.api, "agent_token", return_value="secret-token"):
            page = self._handler("/replacement")
            page.do_GET()
            api = self._handler(
                "/api/replacement/video/start",
                method="POST",
                headers={"Content-Type": "multipart/form-data; boundary=x", "Content-Length": "0"},
            )
            api.do_POST()

        page_status, page_headers, page_body = self._response(page)
        api_status, _api_headers, api_body = self._response(api)
        self.assertEqual(page_status, 200)
        self.assertEqual(page_headers.get("content-type"), "text/html; charset=utf-8")
        self.assertIn("X-Matrix-Agent-Token", page_body)
        self.assertEqual(api_status, 401)
        self.assertEqual(json.loads(api_body)["error"], "agent_token_required")

    def test_replacement_page_is_404_json_when_feature_gate_disabled(self):
        with patch.object(self.api, "ensure_agent_request", return_value=True), patch.object(
            self.api, "replacement_web_enabled", return_value=False
        ):
            handler = self._handler("/replacement")
            handler.do_GET()

        status, headers, body = self._response(handler)
        payload = json.loads(body)
        self.assertEqual(status, 404)
        self.assertEqual(headers.get("content-type"), "application/json; charset=utf-8")
        self.assertEqual(payload["error"], "replacement_web_disabled")

    def test_replacement_page_returns_html_when_feature_gate_enabled(self):
        with patch.object(self.api, "ensure_agent_request", return_value=True), patch.object(
            self.api, "replacement_web_enabled", return_value=True
        ):
            handler = self._handler("/replacement")
            handler.do_GET()

        status, headers, body = self._response(handler)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("content-type"), "text/html; charset=utf-8")
        self.assertIn('data-tab="video"', body)
        self.assertIn('data-tab="note"', body)
        self.assertIn("data-preview-url", body)
        self.assertIn("loadSlotImages", body)
        self.assertIn("URL.createObjectURL", body)
        self.assertIn("authHeaders()", body)

    def test_replacement_job_route_reports_not_found(self):
        with patch.object(self.api, "ensure_agent_request", return_value=True), patch.object(
            self.api, "replacement_web_enabled", return_value=True
        ), patch.object(self.api.replacement_web, "load_job", return_value=None):
            handler = self._handler("/api/replacement/video/job?jobId=rvw_missing")
            handler.do_GET()

        status, _headers, body = self._response(handler)
        payload = json.loads(body)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "replacement_job_not_found")

    def test_replacement_start_routes_are_wired_to_local_job_factories(self):
        source = Path(self.api.__file__).read_text(encoding="utf-8")

        self.assertIn("replacement_web.start_video_job", source)
        self.assertIn("replacement_web.start_note_job", source)
        self.assertIn("/api/replacement/note/save-draft", source)
        self.assertIn("/api/replacement/video/handoff", source)

    def test_replacement_video_handoff_route_returns_safe_context(self):
        replacement = self.api.replacement_web
        with tempfile.TemporaryDirectory() as td:
            local_video = os.path.join(td, "source-video.mp4")
            Path(local_video).write_bytes(b"fake mp4")
            handoff = replacement.create_video_handoff(
                td,
                {
                    "sourceUrl": "https://example.com/video/1?token=private",
                    "sourceVideoPath": local_video,
                    "platform": "douyin",
                    "breakdownAnalysis": {"meta": {"duration": 9.5}},
                },
            )
            handler = self._handler(
                "/api/replacement/video/handoff?handoffId=%s" % handoff["handoffId"]
            )

            with patch.object(self.api, "ensure_agent_request", return_value=True), patch.object(
                self.api, "replacement_web_enabled", return_value=True
            ), patch.object(self.api, "DATA_DIR", td):
                handler.do_GET()

        status, _headers, response_body = self._response(handler)
        payload = json.loads(response_body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["handoffId"], handoff["handoffId"])
        self.assertEqual(payload["source"]["host"], "example.com")
        self.assertTrue(payload["sourceVideo"]["available"])
        self.assertEqual(payload["analysis"]["duration"], 9.5)
        self.assertNotIn(td, response_body)
        self.assertNotIn("source-video.mp4", response_body)
        self.assertNotIn("token=private", response_body)

    def test_disabled_replacement_multipart_does_not_read_request_body(self):
        class ExplodingBody(io.BytesIO):
            def read(self, *args, **kwargs):
                raise AssertionError("disabled replacement route read multipart body")

        with patch.object(self.api, "replacement_web_enabled", return_value=False):
            handler = self._handler(
                "/api/replacement/video/start",
                method="POST",
                headers={"Content-Type": "multipart/form-data; boundary=x", "Content-Length": "999"},
            )
            handler.rfile = ExplodingBody(b"ignored")
            handler.handle_multipart("/api/replacement/video/start")

        status, _headers, body = self._response(handler)
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "replacement_web_disabled")

    def test_replacement_file_route_serves_only_job_upload_images(self):
        replacement = self.api.replacement_web
        with tempfile.TemporaryDirectory() as td:
            start = replacement.start_note_job(
                td,
                {"sourceUrl": "https://www.xiaohongshu.com/explore/abc123"},
                [("replacementImages", "cover.png", _png_bytes())],
            )
            ok_handler = self._handler(
                "/api/replacement/file?taskType=note&jobId=%s&filename=01_cover.png" % start["jobId"]
            )
            bad_handler = self._handler(
                "/api/replacement/file?taskType=note&jobId=%s&filename=../secret.png" % start["jobId"]
            )

            with patch.object(self.api, "ensure_agent_request", return_value=True), patch.object(
                self.api, "replacement_web_enabled", return_value=True
            ), patch.object(self.api, "DATA_DIR", td):
                ok_handler.do_GET()
                bad_handler.do_GET()

            ok_handler.wfile.seek(0)
            ok_raw = ok_handler.wfile.read()
            ok_head, _, ok_body = ok_raw.partition(b"\r\n\r\n")
            self.assertIn(b" 200 ", ok_head.splitlines()[0])
            self.assertIn(b"Content-Type: image/png", ok_head)
            self.assertEqual(ok_body, _png_bytes())

            bad_status, _headers, bad_body = self._response(bad_handler)
            self.assertIn(bad_status, (400, 403, 404))
            self.assertIn(json.loads(bad_body)["error"], ("bad_path", "forbidden", "not_found"))

    def test_replacement_note_save_draft_reuses_xhs_draft_material_flow(self):
        replacement = self.api.replacement_web
        with tempfile.TemporaryDirectory() as td:
            material_dir = os.path.join(td, "materials")
            start = replacement.start_note_job(
                td,
                {
                    "sourceUrl": "https://www.xiaohongshu.com/explore/abc123",
                    "businessName": "Local Shop",
                    "region": "Hangzhou",
                    "sellingPoints": "easy booking, real visit",
                },
                [("replacementImages", "one.png", _png_bytes())],
            )
            body = json.dumps(
                {
                    "jobId": start["jobId"],
                    "selectedCopyIndex": 0,
                    "copyOverride": {
                        "title": "Edited title",
                        "body": "Edited body",
                        "tags": ["edited", "#local"],
                    },
                }
            ).encode("utf-8")
            handler = self._handler(
                "/api/replacement/note/save-draft",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
            )

            with patch.object(self.api, "ensure_agent_request", return_value=True), patch.object(
                self.api, "replacement_web_enabled", return_value=True
            ), patch.object(self.api, "DATA_DIR", td), patch.object(
                self.api, "MATERIALS_DIR", material_dir
            ):
                handler.do_POST()

            status, _headers, response_body = self._response(handler)
            payload = json.loads(response_body)
            web_job = replacement.load_job(td, "note", start["jobId"])
            self.assertEqual(status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["material"]["type"], "image_note")
            self.assertEqual(payload["material"]["title"], "Edited title")
            self.assertEqual(payload["material"]["tags"], ["#edited", "#local"])
            self.assertEqual(web_job["draftMaterialId"], payload["id"])
            self.assertTrue(os.path.isfile(os.path.join(material_dir, payload["id"], payload["material"]["files"][0])))
            exposed = response_body
            self.assertNotIn(td, exposed)
            self.assertNotIn("replacement_web_uploads", exposed)
            self.assertNotIn("filePath", exposed)
            self.assertEqual(payload["job"]["draftMaterialId"], payload["id"])
            self.assertTrue(payload["job"]["slotMappings"][0]["hasFile"])


class ReplacementWebDocumentationTests(unittest.TestCase):
    def test_openapi_documents_replacement_web_mvp_contract(self):
        import yaml

        document = yaml.safe_load((ROOT / "docs" / "openapi.yaml").read_text(encoding="utf-8"))
        paths = document["paths"]
        schemas = document["components"]["schemas"]

        for path in (
            "/api/replacement/video/start",
            "/api/replacement/video/handoff",
            "/api/replacement/video/job",
            "/api/replacement/note/start",
            "/api/replacement/note/job",
            "/api/replacement/note/save-draft",
            "/api/replacement/file",
        ):
            with self.subTest(path=path):
                self.assertIn(path, paths)

        self.assertIn("ReplacementStartResponse", schemas)
        self.assertIn("ReplacementVideoHandoffResponse", schemas)
        self.assertIn("ReplacementJobResponse", schemas)
        self.assertEqual(paths["/replacement"]["get"].get("security"), [])
        self.assertEqual(
            schemas["ReplacementJobResponse"]["properties"]["copyCandidates"]["items"]["type"],
            "object",
        )
        file_properties = schemas["ReplacementJobResponse"]["properties"]["files"]["items"]["properties"]
        self.assertEqual(file_properties["previewUrl"]["type"], "string")
        self.assertIn("/api/replacement/file", file_properties["previewUrl"]["description"])
        slot_properties = schemas["ReplacementJobResponse"]["properties"]["slotMappings"]["items"]["properties"]
        self.assertIn("hasFile", slot_properties)
        self.assertNotIn("filePath", slot_properties)
        self.assertEqual(
            paths["/api/replacement/video/start"]["post"]["requestBody"]["content"][
                "multipart/form-data"
            ]["schema"]["$ref"],
            "#/components/schemas/ReplacementVideoStartRequest",
        )
        self.assertEqual(
            paths["/api/replacement/note/start"]["post"]["requestBody"]["content"][
                "multipart/form-data"
            ]["schema"]["$ref"],
            "#/components/schemas/ReplacementNoteStartRequest",
        )

    def test_api_reference_documents_local_replacement_web_mvp_boundaries(self):
        text = (ROOT / "docs" / "API_REFERENCE.md").read_text(encoding="utf-8")

        self.assertIn("GET /replacement", text)
        self.assertIn("MATRIX_REPLACEMENT_WEB_ENABLED=1", text)
        self.assertIn("/api/replacement/video/start", text)
        self.assertIn("/api/replacement/video/handoff", text)
        self.assertIn("/api/replacement/note/start", text)
        self.assertIn("/api/replacement/file", text)
        self.assertIn("/api/replacement/note/save-draft", text)
        self.assertIn("previewUrl", text)
        self.assertIn("Phase 0", text)
        self.assertIn("不触发真实 LK888", text)
