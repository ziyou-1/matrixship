# tests/test_replacement_web_mvp.py
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
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


class _WebFakeDownloader:
    def __init__(self, filename="source-direct.mp4"):
        self.filename = filename
        self.calls = []

    def download(self, source_url, job_dir):
        self.calls.append((source_url, job_dir))
        path = os.path.join(job_dir, self.filename)
        Path(path).write_bytes(b"fake-video")
        return path


class _WebFakeVideoPipeline:
    def __init__(self, fail_indices=()):
        self.fail_indices = {int(v) for v in fail_indices}
        self.retry_calls = []

    def build_plan(self, job):
        job["segments"] = [
            {"index": 1, "start": 0.0, "end": 8.0, "status": "planned"},
            {"index": 2, "start": 8.0, "end": 16.0, "status": "planned"},
        ]
        return job

    def execute(self, job, selected_segments=None, progress=None):
        for segment in job["segments"]:
            if int(segment["index"]) in self.fail_indices:
                segment.update({"status": "failed", "qcStatus": "failed", "error": "boom"})
            else:
                out = os.path.join(job["outDir"], "segment-%02d.mp4" % int(segment["index"]))
                Path(out).write_bytes(b"seg")
                segment.update({"status": "done", "qcStatus": "passed", "videoPath": out})
        job["status"] = "partial" if any(s["status"] == "failed" for s in job["segments"]) else "awaiting_review"
        return job

    def retry(self, job, segment_indices, progress=None):
        self.retry_calls.append(list(segment_indices or []))
        wanted = {int(v) for v in (segment_indices or [])}
        for segment in job["segments"]:
            if segment["status"] == "failed" and (not wanted or int(segment["index"]) in wanted):
                out = os.path.join(job["outDir"], "segment-%02d-retry.mp4" % int(segment["index"]))
                Path(out).write_bytes(b"seg")
                segment.update({"status": "done", "qcStatus": "passed", "error": "", "videoPath": out})
        job["status"] = "awaiting_review" if all(s["status"] == "done" for s in job["segments"]) else "partial"
        return job

    def concat(self, job):
        out = os.path.join(job["outDir"], "replacement_final.mp4")
        Path(out).write_bytes(b"final-bytes")
        job.update({"status": "completed", "outputPath": out})
        return job


def _make_fake_video_service(data_dir, pipeline, downloader=None):
    replacement_web = importlib.import_module("replacement_web")
    replacement_service = importlib.import_module("replacement_service")
    replacement_analysis = importlib.import_module("replacement_analysis")

    def extract_frames(_video_path, frames_dir, _limit):
        os.makedirs(frames_dir, exist_ok=True)
        return []

    analysis = replacement_analysis.ReplacementAnalysis(
        downloader=downloader or _WebFakeDownloader(),
        download_validator=lambda path: {"ok": True, "code": "", "path": path, "duration": 8.0, "width": 720, "height": 1280},
        platform_from_url=lambda url: "douyin",
        source_validator=lambda path: {"ok": True, "code": "", "path": path, "duration": 8.0, "width": 720, "height": 1280},
        frame_extractor=extract_frames,
        ocr_runner=lambda frames: {"status": "ok", "engine": "fake-ocr", "text": "", "errors": []},
        transcription_runner=lambda _v, out_dir, progress=None: {"status": "ok", "text": "", "segments": [], "failedRanges": [], "errors": [], "retryCount": 0, "outDir": out_dir},
        vision_runner=lambda *a, **k: "fake visual",
        report_builder=lambda out: ("## report", "ok"),
        markdown_builder=lambda out: out.get("report") or "",
        image_data_url=lambda path: "",
        json_logger=lambda *a, **k: '{"errorId":"e"}',
        log_event=lambda *a, **k: None,
    )
    return replacement_service.ReplacementService(
        data_dir=replacement_web._task_root(data_dir, "video"),
        source_resolver=replacement_service.SourceResolver(analysis),
        pipeline=pipeline,
    )


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
        self.assertIn("/api/replacement/video/prepare", html)
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

    def test_replacement_page_script_has_no_unterminated_string_literals(self):
        # Regression: JS string literals in the page template must escape newlines
        # as \\n. A bare \n in the Python triple-quoted template is parsed into a
        # real newline, which terminates the enclosing single-quoted JS string and
        # breaks the whole <script>. When that happens no event handlers register,
        # so clicking "准备替换任务" does a native form submit and the page reloads.
        import re
        import shutil
        import subprocess
        import tempfile
        import os as _os
        html = self.mod.replacement_page_html()
        script = re.search("<script>(.*)</script>", html, re.S).group(1)
        # `+ '` immediately followed by a newline is an unterminated string literal.
        self.assertNotIn("+ '" + chr(10), script)
        node = shutil.which("node")
        if node:
            handle = tempfile.NamedTemporaryFile(
                "w", suffix=".js", delete=False, encoding="utf-8")
            handle.write(script)
            handle.close()
            try:
                result = subprocess.run(
                    [node, "--check", handle.name],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            finally:
                _os.unlink(handle.name)

    def test_replacement_page_html_has_person_authorization_controls(self):
        html = self.mod.replacement_page_html()
        self.assertIn('name="noPersonMode"', html)
        self.assertIn('name="faceAuthorized"', html)
        self.assertIn('name="personFullBody"', html)
        self.assertIn("纯产品视频", html)
        self.assertIn("授权", html)
        self.assertIn("syncVideoPersonMode", html)

    def test_video_replacement_options_lists_models_audio_and_voices(self):
        options = self.mod.video_replacement_options()
        self.assertIsInstance(options.get("models"), list)
        self.assertIsInstance(options.get("voices"), list)
        audio_values = {m["value"] for m in options.get("audioModes") or []}
        self.assertIn("auto", audio_values)
        self.assertIn("tts", audio_values)

    def test_replacement_page_html_has_model_and_audio_controls(self):
        html = self.mod.replacement_page_html()
        self.assertIn('name="model"', html)
        self.assertIn('name="audioMode"', html)
        self.assertIn('name="voice"', html)
        self.assertIn("loadVideoOptions", html)
        self.assertIn("/api/replacement/video/options", html)

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
                {"handoffId": handoff["handoffId"], "sellingPoints": "fast",
                 "faceAuthorized": "1", "personFullBody": "1"},
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
                    "faceAuthorized": "1",
                    "personFullBody": "1",
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


class ReplacementVideoPageControlTests(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("replacement_web")

    def test_video_panel_exposes_lifecycle_controls_and_polling(self):
        html = self.mod.replacement_page_html()

        # source mode + handoff status
        self.assertIn("loadVideoHandoff", html)
        self.assertIn("matrixReplacementVideoHandoffId", html)
        self.assertIn("matrixReplacementVideoJobId", html)
        # lifecycle routes driven from the page
        self.assertIn("/api/replacement/video/prepare", html)
        self.assertIn("/api/replacement/video/execute", html)
        self.assertIn("/api/replacement/video/retry", html)
        self.assertIn("/api/replacement/video/concat", html)
        self.assertIn("/api/replacement/video/cancel", html)
        self.assertIn("/api/replacement/video/job", html)
        self.assertIn("/api/replacement/video/download", html)
        # editable plan + per-segment status + controls
        self.assertIn('id="video-plan"', html)
        self.assertIn('id="video-segments"', html)
        self.assertIn('id="video-execute"', html)
        self.assertIn('id="video-retry"', html)
        self.assertIn('id="video-cancel"', html)
        self.assertIn('id="video-concat"', html)
        self.assertIn("renderVideoJob", html)
        self.assertIn("pollVideoJob", html)
        # poll cadence: 1s preparation, 2s generation
        self.assertIn("1000", html)
        self.assertIn("2000", html)
        # authenticated download uses header token, never a query token
        self.assertIn("authHeaders()", html)
        self.assertNotIn("token=${", html)

    def test_video_panel_only_uses_sessionstorage_for_handoff_and_job(self):
        html = self.mod.replacement_page_html()
        keys = set(re.findall(r"sessionStorage\.(?:getItem|setItem|removeItem)\(([A-Za-z_]+)", html))
        # TOKEN_KEY/USER_KEY/HANDOFF_KEY/JOB_KEY are the only session keys; token+user predate video MVP
        self.assertTrue({"HANDOFF_KEY", "JOB_KEY"}.issubset(keys))


class ReplacementVideoLifecycleAdapterTests(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("replacement_web")

    def _handoff(self, td):
        local_video = os.path.join(td, "source-video.mp4")
        Path(local_video).write_bytes(b"fake mp4")
        created = self.mod.create_video_handoff(
            td,
            {
                "sourceUrl": "https://www.douyin.com/video/1?token=secret",
                "sourceVideoPath": local_video,
                "platform": "douyin",
                "breakdownAnalysis": {"meta": {"duration": 8.0}},
            },
        )
        return created["handoffId"]

    def test_prepare_with_handoff_without_source_url_plans_job(self):
        with tempfile.TemporaryDirectory() as td:
            handoff_id = self._handoff(td)
            pipeline = _WebFakeVideoPipeline()
            service = _make_fake_video_service(td, pipeline)
            with patch.object(self.mod, "build_video_service", return_value=service):
                result = self.mod.prepare_video_job(
                    td,
                    {"handoffId": handoff_id, "sellingPoints": "fast",
                     "faceAuthorized": "1", "personFullBody": "1"},
                    [("characterImage", "face.png", b"fake image bytes")],
                )

            self.assertTrue(result["ok"])
            self.assertTrue(result["jobId"].startswith("rvw_"))
            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["taskType"], "video")
            self.assertEqual(result["source"]["host"], "www.douyin.com")
            self.assertEqual(result["sourceContext"]["platform"], "douyin")
            self.assertEqual(len(result["segments"]), 2)
            exposed = json.dumps(result, ensure_ascii=False)
            self.assertNotIn(td, exposed)
            self.assertNotIn("token=secret", exposed)

    def test_prepare_rejects_real_face_without_full_body_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            handoff_id = self._handoff(td)
            result = self.mod.prepare_video_job(
                td,
                {"handoffId": handoff_id, "faceAuthorized": "1"},
                [("characterImage", "face.png", b"fake image bytes")],
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "replacement_person_full_body_required")

    def test_prepare_rejects_real_face_without_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            handoff_id = self._handoff(td)
            result = self.mod.prepare_video_job(
                td,
                {"handoffId": handoff_id, "personFullBody": "1"},
                [("characterImage", "face.png", b"fake image bytes")],
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "replacement_face_authorization_required")

    def test_prepare_no_person_mode_skips_character_and_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            handoff_id = self._handoff(td)
            pipeline = _WebFakeVideoPipeline()
            service = _make_fake_video_service(td, pipeline)
            with patch.object(self.mod, "build_video_service", return_value=service):
                result = self.mod.prepare_video_job(
                    td,
                    {"handoffId": handoff_id, "noPersonMode": "1"},
                    [],
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "planned")
            job = self.mod.load_job(td, "video", result["jobId"])
            self.assertTrue(job.get("noPersonMode"))

    def test_prepare_passes_selected_model_audio_and_voice_to_job(self):
        with tempfile.TemporaryDirectory() as td:
            handoff_id = self._handoff(td)
            pipeline = _WebFakeVideoPipeline()
            service = _make_fake_video_service(td, pipeline)
            fake_options = {
                "models": [{"value": "test-model", "label": "T"}],
                "voices": [{"value": "VoiceA", "label": "A"}],
                "audioModes": [{"value": "auto", "label": "auto"}, {"value": "tts", "label": "tts"}],
            }
            with patch.object(self.mod, "build_video_service", return_value=service), \
                    patch.object(self.mod, "video_replacement_options", return_value=fake_options):
                result = self.mod.prepare_video_job(
                    td,
                    {"handoffId": handoff_id, "noPersonMode": "1",
                     "model": "test-model", "audioMode": "tts", "voice": "VoiceA"},
                    [],
                )
            self.assertTrue(result["ok"])
            job = self.mod.load_job(td, "video", result["jobId"])
            self.assertEqual(job.get("model"), "test-model")
            self.assertEqual(job.get("audioMode"), "tts")
            self.assertEqual(job.get("voice"), "VoiceA")

    def test_prepare_with_direct_url_downloads_into_job_dir(self):
        with tempfile.TemporaryDirectory() as td:
            downloader = _WebFakeDownloader()
            pipeline = _WebFakeVideoPipeline()
            service = _make_fake_video_service(td, pipeline, downloader=downloader)
            with patch.object(self.mod, "build_video_service", return_value=service):
                result = self.mod.prepare_video_job(
                    td,
                    {"sourceUrl": "https://www.douyin.com/video/abc?token=secret",
                     "faceAuthorized": "1", "personFullBody": "1"},
                    [("characterImage", "face.png", b"img")],
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["source"]["host"], "www.douyin.com")
            self.assertEqual(len(downloader.calls), 1)
            self.assertNotIn("token=secret", json.dumps(result, ensure_ascii=False))

    def test_prepare_requires_valid_source_and_character_image(self):
        with tempfile.TemporaryDirectory() as td:
            service = _make_fake_video_service(td, _WebFakeVideoPipeline())
            with patch.object(self.mod, "build_video_service", return_value=service):
                bad_url = self.mod.prepare_video_job(
                    td, {"sourceUrl": "file:///tmp/a.mp4"}, [("characterImage", "f.png", b"1")]
                )
                missing_image = self.mod.prepare_video_job(
                    td, {"sourceUrl": "https://www.douyin.com/video/1"}, []
                )

            self.assertFalse(bad_url["ok"])
            self.assertEqual(bad_url["error"], "replacement_invalid_source_url")
            self.assertFalse(missing_image["ok"])
            self.assertEqual(missing_image["error"], "replacement_video_missing_character_image")

    def test_execute_then_concat_completes_and_exposes_safe_download(self):
        with tempfile.TemporaryDirectory() as td:
            handoff_id = self._handoff(td)
            service = _make_fake_video_service(td, _WebFakeVideoPipeline())
            with patch.object(self.mod, "build_video_service", return_value=service):
                prepared = self.mod.prepare_video_job(
                    td, {"handoffId": handoff_id, "faceAuthorized": "1", "personFullBody": "1"}, [("characterImage", "face.png", b"img")]
                )
                job_id = prepared["jobId"]
                executed = self.mod.execute_video_job(td, job_id, {})
                self.assertEqual(executed["status"], "awaiting_review")
                self.assertFalse(executed["download"]["available"])

                completed = self.mod.concat_video_job(td, job_id)
                self.assertEqual(completed["status"], "completed")
                self.assertTrue(completed["download"]["available"])
                self.assertEqual(completed["download"]["filename"], "replacement_final.mp4")

            exposed = json.dumps(completed, ensure_ascii=False)
            self.assertNotIn(td, exposed)
            self.assertNotIn("outputPath", exposed)
            self.assertNotIn("videoPath", exposed)

            fp, error, status = self.mod.final_media_path(td, job_id, "replacement_final.mp4")
            self.assertEqual((error, status), ("", 200))
            self.assertEqual(Path(fp).read_bytes(), b"final-bytes")
            _fp2, bad_error, bad_status = self.mod.final_media_path(td, job_id, "../evil.mp4")
            self.assertIn(bad_status, (400, 403, 404))
            self.assertIn(bad_error, ("bad_path", "forbidden", "not_found"))

    def test_retry_only_reruns_failed_segments(self):
        with tempfile.TemporaryDirectory() as td:
            handoff_id = self._handoff(td)
            pipeline = _WebFakeVideoPipeline(fail_indices=(2,))
            service = _make_fake_video_service(td, pipeline)
            with patch.object(self.mod, "build_video_service", return_value=service):
                prepared = self.mod.prepare_video_job(
                    td, {"handoffId": handoff_id, "faceAuthorized": "1", "personFullBody": "1"}, [("characterImage", "face.png", b"img")]
                )
                job_id = prepared["jobId"]
                partial = self.mod.execute_video_job(td, job_id, {})
                self.assertEqual(partial["status"], "partial")
                self.assertEqual(partial["segments"][1]["status"], "failed")

                retried = self.mod.retry_video_job(td, job_id, [2])
                self.assertEqual(retried["status"], "awaiting_review")
                self.assertEqual(retried["segments"][1]["status"], "done")
                self.assertEqual(pipeline.retry_calls, [[2]])

    def test_cancel_marks_job_cancelled(self):
        with tempfile.TemporaryDirectory() as td:
            handoff_id = self._handoff(td)
            service = _make_fake_video_service(td, _WebFakeVideoPipeline())
            with patch.object(self.mod, "build_video_service", return_value=service):
                prepared = self.mod.prepare_video_job(
                    td, {"handoffId": handoff_id, "faceAuthorized": "1", "personFullBody": "1"}, [("characterImage", "face.png", b"img")]
                )
                cancelled = self.mod.cancel_video_job(td, prepared["jobId"])
            self.assertEqual(cancelled["status"], "cancelled")

    def test_invalid_state_transitions_return_409(self):
        with tempfile.TemporaryDirectory() as td:
            handoff_id = self._handoff(td)
            service = _make_fake_video_service(td, _WebFakeVideoPipeline())
            with patch.object(self.mod, "build_video_service", return_value=service):
                prepared = self.mod.prepare_video_job(
                    td, {"handoffId": handoff_id, "faceAuthorized": "1", "personFullBody": "1"}, [("characterImage", "face.png", b"img")]
                )
                job_id = prepared["jobId"]
                # concat before awaiting_review -> 409
                early_concat = self.mod.concat_video_job(td, job_id)
                self.assertFalse(early_concat["ok"])
                self.assertEqual(early_concat["statusCode"], 409)
                # retry before partial/awaiting_review -> 409
                early_retry = self.mod.retry_video_job(td, job_id, [1])
                self.assertEqual(early_retry["statusCode"], 409)

    def test_execute_missing_job_returns_404(self):
        with tempfile.TemporaryDirectory() as td:
            service = _make_fake_video_service(td, _WebFakeVideoPipeline())
            with patch.object(self.mod, "build_video_service", return_value=service):
                result = self.mod.execute_video_job(td, "rvw_%s" % ("a" * 24), {})
            self.assertFalse(result["ok"])
            self.assertEqual(result["statusCode"], 404)

    def test_video_job_response_redacts_internal_paths_and_credentials(self):
        raw = {
            "id": "rvw_%s" % ("a" * 24),
            "taskType": "video",
            "status": "failed",
            "stage": "editing",
            "outDir": "/private/data/rvw_aaaa",
            "sourceVideoPath": "/private/data/rvw_aaaa/source.mp4",
            "outputPath": "/private/data/rvw_aaaa/final.mp4",
            "source": {"scheme": "https", "host": "www.douyin.com", "pathHash": "abcdef"},
            "error": "boom out=/private/data/rvw_aaaa token=secret-token cookie=abc",
            "segments": [
                {"index": 1, "status": "failed", "videoPath": "/private/data/rvw_aaaa/seg1.mp4",
                 "startFramePath": "/private/data/frame.png", "qcStatus": "failed"},
            ],
        }
        response = self.mod.video_job_response(raw)
        exposed = json.dumps(response, ensure_ascii=False)

        self.assertEqual(response["jobId"], raw["id"])
        self.assertEqual(response["source"]["host"], "www.douyin.com")
        self.assertNotIn("/private/data", exposed)
        self.assertNotIn("secret-token", exposed)
        self.assertNotIn("videoPath", exposed)
        self.assertNotIn("startFramePath", exposed)
        self.assertNotIn("outputPath", exposed)
        self.assertNotIn("sourceVideoPath", exposed)
        self.assertEqual(response["segments"][0]["status"], "failed")

    def test_video_job_response_never_exposes_raw_provider_task_id_or_signed_url(self):
        # Task 7: a secret-like provider URL and raw provider task id must never
        # appear in an API response, even when embedded in free-text error copy.
        raw_task = "provider-task-SECRET-999"
        signed = "https://cdn.example.com/v/out.mp4?X-Amz-Signature=zzz&token=priv"
        raw = {
            "id": "rvw_%s" % ("b" * 24),
            "taskType": "video",
            "status": "failed",
            "error": "generation failed for task %s at %s" % (raw_task, signed),
            "segments": [
                {"index": 1, "status": "failed", "providerTaskId": raw_task, "videoUrl": signed},
            ],
        }
        response = self.mod.video_job_response(raw)
        exposed = json.dumps(response, ensure_ascii=False)

        self.assertNotIn(raw_task, exposed)
        self.assertNotIn("X-Amz-Signature", exposed)
        self.assertNotIn("token=priv", exposed)
        self.assertNotIn("out.mp4", exposed)


class ReplacementVideoLifecycleRouteTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module("api_server")
        self.mod = self.api.replacement_web

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
        status = int(head.splitlines()[0].split()[1])
        return status, json.loads(body) if body else {}

    def _multipart(self, fields, files):
        boundary = "webboundary"
        parts = []
        for key, value in fields.items():
            parts.append(("--" + boundary).encode())
            parts.append(('Content-Disposition: form-data; name="%s"' % key).encode())
            parts.append(b"")
            parts.append(str(value).encode())
        for field, filename, data in files:
            parts.append(("--" + boundary).encode())
            parts.append(('Content-Disposition: form-data; name="%s"; filename="%s"' % (field, filename)).encode())
            parts.append(b"Content-Type: application/octet-stream")
            parts.append(b"")
            parts.append(data)
        parts.append(("--" + boundary + "--").encode())
        parts.append(b"")
        body = b"\r\n".join(parts)
        headers = {
            "Content-Type": "multipart/form-data; boundary=" + boundary,
            "Content-Length": str(len(body)),
        }
        return body, headers

    def _handoff(self, td):
        local_video = os.path.join(td, "source-video.mp4")
        Path(local_video).write_bytes(b"fake mp4")
        created = self.mod.create_video_handoff(
            td,
            {
                "sourceUrl": "https://www.douyin.com/video/1",
                "sourceVideoPath": local_video,
                "platform": "douyin",
                "breakdownAnalysis": {"meta": {"duration": 8.0}},
            },
        )
        return created["handoffId"]

    def test_full_video_lifecycle_over_http_routes(self):
        with tempfile.TemporaryDirectory() as td:
            handoff_id = self._handoff(td)
            service = _make_fake_video_service(td, _WebFakeVideoPipeline(fail_indices=(2,)))
            with patch.object(self.api, "ensure_agent_request", return_value=True), patch.object(
                self.api, "replacement_web_enabled", return_value=True
            ), patch.object(self.api, "DATA_DIR", td), patch.object(
                self.mod, "build_video_service", return_value=service
            ):
                body, headers = self._multipart(
                    {"handoffId": handoff_id, "faceAuthorized": "1", "personFullBody": "1"},
                    [("characterImage", "face.png", b"img")],
                )
                prepare = self._handler("/api/replacement/video/prepare", method="POST", body=body, headers=headers)
                prepare.do_POST()
                prepare_status, prepare_payload = self._response(prepare)
                self.assertEqual(prepare_status, 202)
                self.assertEqual(prepare_payload["status"], "planned")
                job_id = prepare_payload["jobId"]

                jobq = self._handler("/api/replacement/video/job?jobId=%s" % job_id)
                jobq.do_GET()
                jobq_status, jobq_payload = self._response(jobq)
                self.assertEqual(jobq_status, 200)
                self.assertEqual(jobq_payload["taskType"], "video")
                self.assertEqual(jobq_payload["status"], "planned")

                exec_body = json.dumps({"jobId": job_id}).encode()
                execute = self._handler(
                    "/api/replacement/video/execute",
                    method="POST",
                    body=exec_body,
                    headers={"Content-Type": "application/json", "Content-Length": str(len(exec_body))},
                )
                execute.do_POST()
                exec_status, exec_payload = self._response(execute)
                self.assertEqual(exec_status, 202)
                self.assertEqual(exec_payload["status"], "partial")

                # concat before review -> 409
                concat_body = json.dumps({"jobId": job_id}).encode()
                early = self._handler(
                    "/api/replacement/video/concat",
                    method="POST",
                    body=concat_body,
                    headers={"Content-Type": "application/json", "Content-Length": str(len(concat_body))},
                )
                early.do_POST()
                early_status, _early_payload = self._response(early)
                self.assertEqual(early_status, 409)

                retry_body = json.dumps({"jobId": job_id, "segmentIndices": [2]}).encode()
                retry = self._handler(
                    "/api/replacement/video/retry",
                    method="POST",
                    body=retry_body,
                    headers={"Content-Type": "application/json", "Content-Length": str(len(retry_body))},
                )
                retry.do_POST()
                retry_status, retry_payload = self._response(retry)
                self.assertEqual(retry_status, 202)
                self.assertEqual(retry_payload["status"], "awaiting_review")

                concat = self._handler(
                    "/api/replacement/video/concat",
                    method="POST",
                    body=concat_body,
                    headers={"Content-Type": "application/json", "Content-Length": str(len(concat_body))},
                )
                concat.do_POST()
                concat_status, concat_payload = self._response(concat)
                self.assertEqual(concat_status, 202)
                self.assertEqual(concat_payload["status"], "completed")
                self.assertTrue(concat_payload["download"]["available"])

                download = self._handler(
                    "/api/replacement/video/download?jobId=%s&filename=%s"
                    % (job_id, concat_payload["download"]["filename"])
                )
                download.do_GET()
                download.wfile.seek(0)
                dl_head, _, dl_body = download.wfile.read().partition(b"\r\n\r\n")
                self.assertIn(b" 200 ", dl_head.splitlines()[0])
                self.assertEqual(dl_body, b"final-bytes")

                cancel_body = json.dumps({"jobId": job_id}).encode()
                cancel = self._handler(
                    "/api/replacement/video/cancel",
                    method="POST",
                    body=cancel_body,
                    headers={"Content-Type": "application/json", "Content-Length": str(len(cancel_body))},
                )
                cancel.do_POST()
                cancel_status, _cancel_payload = self._response(cancel)
                # completed is terminal; cancel is a safe no-op returning 202 with terminal state
                self.assertEqual(cancel_status, 202)

    def test_video_lifecycle_routes_are_gated_when_feature_disabled(self):
        with patch.object(self.api, "ensure_agent_request", return_value=True), patch.object(
            self.api, "replacement_web_enabled", return_value=False
        ):
            exec_body = json.dumps({"jobId": "rvw_%s" % ("a" * 24)}).encode()
            handler = self._handler(
                "/api/replacement/video/execute",
                method="POST",
                body=exec_body,
                headers={"Content-Type": "application/json", "Content-Length": str(len(exec_body))},
            )
            handler.do_POST()
        status, payload = self._response(handler)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "replacement_web_disabled")


class ReplacementWebDocumentationTests(unittest.TestCase):
    def test_openapi_documents_replacement_web_mvp_contract(self):
        import yaml

        document = yaml.safe_load((ROOT / "docs" / "openapi.yaml").read_text(encoding="utf-8"))
        paths = document["paths"]
        schemas = document["components"]["schemas"]

        for path in (
            "/api/replacement/video/start",
            "/api/replacement/video/prepare",
            "/api/replacement/video/execute",
            "/api/replacement/video/retry",
            "/api/replacement/video/concat",
            "/api/replacement/video/cancel",
            "/api/replacement/video/download",
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
        self.assertIn("ReplacementVideoJobResponse", schemas)

        for lifecycle_path in (
            "/api/replacement/video/prepare",
            "/api/replacement/video/execute",
            "/api/replacement/video/retry",
            "/api/replacement/video/concat",
            "/api/replacement/video/cancel",
        ):
            operation = paths[lifecycle_path]["post"]
            with self.subTest(path=lifecycle_path):
                self.assertIn("202", operation["responses"])
                self.assertIn("404", operation["responses"])
        for lifecycle_path in (
            "/api/replacement/video/execute",
            "/api/replacement/video/retry",
            "/api/replacement/video/concat",
        ):
            with self.subTest(path=lifecycle_path):
                self.assertIn("409", paths[lifecycle_path]["post"]["responses"])
        video_status_enum = schemas["ReplacementVideoJobResponse"]["properties"]["status"]["enum"]
        for state in ("planned", "running", "awaiting_review", "partial", "completed", "failed", "cancelled"):
            self.assertIn(state, video_status_enum)
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
