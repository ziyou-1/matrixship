### Task 3: Local API Server Routes

**Files:**
- Modify: `backend/api_server.py`
- Modify: `tests/test_replacement_web_mvp.py`

**Interfaces:**
- Consumes:
  - `replacement_web.replacement_page_html() -> str`
  - `replacement_web.replacement_disabled_payload() -> dict`
  - `replacement_web.start_video_job(DATA_DIR, fields, files) -> dict`
  - `replacement_web.start_note_job(DATA_DIR, fields, files) -> dict`
  - `replacement_web.load_job(DATA_DIR, task_type, job_id) -> dict | None`
  - `replacement_web.job_response(job) -> dict`
- Produces: local HTTP routes declared in the design.

- [ ] **Step 1: Write failing route behavior tests**

Append to `tests/test_replacement_web_mvp.py`:

```python
class ReplacementApiServerRouteTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module("api_server")

    def _handler(self, path="/replacement", headers=None):
        handler = object.__new__(self.api.Handler)
        handler.path = path
        handler.headers = headers or {}
        handler.wfile = io.BytesIO()
        sent = []
        handler.send_response = lambda status: sent.append(("status", status))
        handler.send_header = lambda name, value: sent.append(("header", name, value))
        handler.end_headers = lambda: sent.append(("end",))
        handler._sent = sent
        return handler

    def test_replacement_page_respects_feature_flag(self):
        handler = self._handler("/replacement")
        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "replacement_web_enabled", return_value=False):
            self.api.Handler.do_GET(handler)

        self.assertIn(("status", 404), handler._sent)
        body = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(body["error"], "replacement_web_disabled")

    def test_replacement_page_serves_html_when_enabled(self):
        handler = self._handler("/replacement")
        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "replacement_web_enabled", return_value=True):
            self.api.Handler.do_GET(handler)

        self.assertIn(("status", 200), handler._sent)
        self.assertIn(("header", "Content-Type", "text/html; charset=utf-8"), handler._sent)
        body = handler.wfile.getvalue().decode("utf-8")
        self.assertIn("视频替换", body)
        self.assertIn("图文替换", body)

    def test_replacement_job_route_returns_not_found_for_missing_job(self):
        handler = self._handler("/api/replacement/video/job?id=rvw_000000000000000000000000")
        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "replacement_web_enabled", return_value=True), \
                mock.patch.object(self.api.replacement_web, "load_job", return_value=None):
            self.api.Handler.do_GET(handler)

        self.assertIn(("status", 404), handler._sent)
        body = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(body["error"], "replacement_job_not_found")

    def test_multipart_start_routes_are_declared_in_handler(self):
        source = (BACKEND / "api_server.py").read_text(encoding="utf-8")
        self.assertIn("replacement_web.start_video_job", source)
        self.assertIn("replacement_web.start_note_job", source)
```

- [ ] **Step 2: Run route tests and verify they fail**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementApiServerRouteTests -v
```

Expected: FAIL because routes are not implemented.

- [ ] **Step 3: Import `replacement_web`**

In `backend/api_server.py`, add near `import xhs_note_replacement`:

```python
import replacement_web
```

Extend the existing `platform_features` import in `backend/api_server.py`:

```python
from platform_features import (
    is_xhs_platform,
    log_platform_disabled,
    payload_uses_xhs,
    platform_disabled_result,
    replacement_web_enabled,
    xhs_enabled,
)
```

- [ ] **Step 4: Add HTML response helper**

Near `json_response()` in `backend/api_server.py`, add:

```python
def html_response(handler, html_body, status=200):
    body = str(html_body or "").encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    send_cors_headers(handler)
    handler.end_headers()
    handler.wfile.write(body)
```

- [ ] **Step 5: Add GET routes**

In `Handler.do_GET()` after the XHS disabled gate and before `/api/health`, add:

```python
        if path == "/replacement":
            if not replacement_web_enabled():
                return json_response(self, replacement_web.replacement_disabled_payload(), 404)
            json_log(logger, "replacement_web_page_opened", route=path)
            return html_response(self, replacement_web.replacement_page_html())

        if path in ("/api/replacement/video/job", "/api/replacement/note/job"):
            if not replacement_web_enabled():
                return json_response(self, replacement_web.replacement_disabled_payload(), 404)
            task_type = "video" if "/video/" in path else "note"
            job_id = (qs.get("id") or qs.get("jobId") or [""])[0]
            job = replacement_web.load_job(DATA_DIR, task_type, job_id)
            if not job:
                return json_response(self, {"ok": False, "error": "replacement_job_not_found", "stage": "status"}, 404)
            return json_response(self, replacement_web.job_response(job))
```

- [ ] **Step 6: Add multipart start routes**

In `Handler.handle_multipart()`, before `/api/library/upload`, add:

```python
        if path == "/api/replacement/video/start":
            if not replacement_web_enabled():
                return json_response(self, replacement_web.replacement_disabled_payload(), 404)
            result = replacement_web.start_video_job(DATA_DIR, fields, files)
            status = 200 if result.get("ok") else int(result.get("statusCode") or 400)
            json_log(
                logger,
                "replacement_video_start",
                level="info" if result.get("ok") else "warning",
                jobId=result.get("jobId") or "",
                stage=result.get("stage") or "preflight",
                status=result.get("status") or "",
                error=result.get("error") or "",
            )
            return json_response(self, result, status)

        if path == "/api/replacement/note/start":
            if not replacement_web_enabled():
                return json_response(self, replacement_web.replacement_disabled_payload(), 404)
            result = replacement_web.start_note_job(DATA_DIR, fields, files)
            status = 200 if result.get("ok") else int(result.get("statusCode") or 400)
            json_log(
                logger,
                "replacement_note_start",
                level="info" if result.get("ok") else "warning",
                jobId=result.get("jobId") or "",
                stage=result.get("stage") or "preflight",
                status=result.get("status") or "",
                error=result.get("error") or "",
            )
            return json_response(self, result, status)
```

- [ ] **Step 7: Run route tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v
```

Expected: PASS.

- [ ] **Step 8: Run syntax check**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\api_server.py backend\replacement_web.py backend\platform_features.py
```

Expected: PASS with no output.

- [ ] **Step 9: Commit**

Do not commit in this task. The user confirmed per-task commits are disabled; the controller will make one final commit only after all code, docs, OpenAPI, and `docs/IMPLEMENTATION.md` line references are stable. Do not run `git add` or `git commit` for this task.
```

---


