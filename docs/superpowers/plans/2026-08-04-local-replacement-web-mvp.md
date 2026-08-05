# Local Replacement Web MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local execution server `/replacement` MVP page with video replacement and image-note replacement tabs, backed by local task APIs and a reversible feature flag.

**Architecture:** Keep `backend/api_server.py` as the HTTP routing surface, but move validation, HTML rendering, job persistence, and sanitized response helpers into a new `backend/replacement_web.py` module. The first implementation is a Phase 0 skeleton: it creates traceable local jobs and exposes status without submitting real remote model work; later tasks can connect the skeleton to the existing video and XHS replacement internals behind the same contracts.

**Tech Stack:** Python standard library `http.server`, existing `backend/api_server.py` multipart parser, existing `platform_features.py` feature gates, JSON task files under the local agent data directory, existing `xhs_note_replacement.py` smoke/preview helpers, `unittest`, `py_compile`, OpenAPI 3.1 docs.

## Global Constraints

- `MATRIX_REPLACEMENT_WEB_ENABLED=0` must disable `GET /replacement` and both start APIs.
- No independent `frontend/` project, bundler, or product Web delivery surface may be introduced.
- Logs and persisted job summaries must not contain Cookie, Token, Authorization, full signed URLs, base64 image content, or raw local privacy paths.
- Video replacement payloads must not pass local filesystem paths or `data:image/...` to LK888 or remote AI Canvas.
- Phase 0 must pass with fake links and fake image bytes before connecting real generation.
- API docs and `docs/openapi.yaml` must be updated for new JSON/multipart contracts.
- `docs/IMPLEMENTATION.md` line references must be recalculated before any commit.
- If no database schema is changed, `migration.sql` must be updated as a no-op release note.

---

## File Structure

- Modify: `backend/platform_features.py`
  - Add `MATRIX_REPLACEMENT_WEB_ENABLED` parsing and `replacement_web_enabled(env=None)`.
- Create: `backend/replacement_web.py`
  - Owns feature-disabled payloads, HTML rendering, URL/file validation, safe job IDs, local job persistence, sanitized job summaries, and Phase 0 video/note start helpers.
- Modify: `backend/api_server.py`
  - Imports `replacement_web_enabled` and `replacement_web`.
  - Adds `GET /replacement`, `GET /api/replacement/video/job`, `GET /api/replacement/note/job`.
  - Adds multipart handling for `POST /api/replacement/video/start` and `POST /api/replacement/note/start`.
- Create: `tests/test_replacement_web_mvp.py`
  - Focused unit and route tests for feature gate, HTML, validation, job persistence, API source declarations, and sensitive-data redaction.
- Modify: `docs/openapi.yaml`
  - Add replacement API paths and schemas.
- Modify: `docs/API_REFERENCE.md`
  - Document local `/replacement` page and `/api/replacement/*` contracts.
- Modify: `docs/ARCHITECTURE.md`
  - State this is a local execution page, not a restored independent Web frontend.
- Modify: `docs/DEPLOYMENT.md`
  - Add `MATRIX_REPLACEMENT_WEB_ENABLED`.
- Modify: `docs/TROUBLESHOOTING.md`
  - Add Phase 0 smoke results and common failures.
- Modify: `docs/IMPLEMENTATION.md`
  - Add exact implementation references after code lands, using real `path#Lnumber-Lnumber` ranges from `rg -n` output.
- Modify: `CHANGELOG.md`
  - Add local replacement web MVP entry.
- Modify: `migration.sql`
  - Add no-op note if the implementation keeps local JSON state only.

---

### Task 1: Feature Gate And Phase 0 Tests

**Files:**
- Modify: `backend/platform_features.py`
- Create: `tests/test_replacement_web_mvp.py`

**Interfaces:**
- Consumes: existing `platform_features.env_flag_enabled(name, env=None, default=False) -> bool`
- Produces: `platform_features.replacement_web_enabled(env=None) -> bool`

- [ ] **Step 1: Write failing tests for the feature gate and source declarations**

Add this test file:

```python
# tests/test_replacement_web_mvp.py
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
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebFeatureGateTests -v
```

Expected: FAIL because `replacement_web_enabled` does not exist.

- [ ] **Step 3: Add the feature gate**

In `backend/platform_features.py`, add:

```python
REPLACEMENT_WEB_ENABLED_ENV = "MATRIX_REPLACEMENT_WEB_ENABLED"
```

Near the other flag helpers, add:

```python
def replacement_web_enabled(env=None):
    return env_flag_enabled(REPLACEMENT_WEB_ENABLED_ENV, env=env)
```

- [ ] **Step 4: Run tests and verify feature gate passes**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebFeatureGateTests -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Do not commit until `docs/IMPLEMENTATION.md` line numbers are current. When ready:

```bash
git add backend/platform_features.py tests/test_replacement_web_mvp.py
git commit -m "feat: gate local replacement web mvp"
```

---

### Task 2: Replacement Web Support Module

**Files:**
- Create: `backend/replacement_web.py`
- Modify: `tests/test_replacement_web_mvp.py`

**Interfaces:**
- Consumes:
  - `xhs_note_replacement.smoke_four_image_replacement(material=None, business_input=None, provided_assets=None) -> dict`
  - local data directory path string
- Produces:
  - `replacement_disabled_payload() -> dict`
  - `replacement_page_html() -> str`
  - `start_video_job(data_dir: str, fields: dict, files: list[tuple[str, str, bytes]]) -> dict`
  - `start_note_job(data_dir: str, fields: dict, files: list[tuple[str, str, bytes]]) -> dict`
  - `load_job(data_dir: str, task_type: str, job_id: str) -> dict | None`
  - `job_response(job: dict) -> dict`

- [ ] **Step 1: Write failing tests for HTML, validation, jobs, and redaction**

Append to `tests/test_replacement_web_mvp.py`:

```python
class ReplacementWebModuleTests(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("replacement_web")

    def test_replacement_page_html_contains_two_tabs_without_marketing_surface(self):
        html = self.mod.replacement_page_html()

        self.assertIn("视频替换", html)
        self.assertIn("图文替换", html)
        self.assertIn("/api/replacement/video/start", html)
        self.assertIn("/api/replacement/note/start", html)
        self.assertNotIn("frontend", html.lower())
        self.assertNotIn("landing", html.lower())

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

    def test_job_loader_rejects_cross_type_or_bad_id(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(self.mod.load_job(td, "video", "../bad"))
            self.assertIsNone(self.mod.load_job(td, "unknown", "rvw_abc"))
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebModuleTests -v
```

Expected: FAIL because `replacement_web.py` does not exist.

- [ ] **Step 3: Create `backend/replacement_web.py`**

Create the module with this implementation:

```python
# coding: utf-8
import hashlib
import html
import json
import os
import re
import time
import uuid
from urllib.parse import urlparse

import xhs_note_replacement


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024
VIDEO_JOB_RE = re.compile(r"^rvw_[0-9a-f]{24}$")
NOTE_JOB_RE = re.compile(r"^xnr_[0-9a-f]{24}$")
TASK_TYPES = {"video", "note"}


def replacement_disabled_payload():
    return {"ok": False, "error": "replacement_web_disabled"}


def replacement_page_html():
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>替换生成</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f6f7f9; color: #1f2937; }
    main { max-width: 1120px; margin: 0 auto; padding: 24px; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
    h1 { font-size: 24px; margin: 0; letter-spacing: 0; }
    .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
    .tabs button { border: 1px solid #cfd6df; background: white; padding: 9px 14px; border-radius: 6px; cursor: pointer; }
    .tabs button.active { background: #183b56; color: white; border-color: #183b56; }
    section { background: white; border: 1px solid #dde3ea; border-radius: 8px; padding: 18px; }
    label { display: block; font-size: 13px; font-weight: 600; margin: 12px 0 6px; }
    input, textarea { width: 100%; box-sizing: border-box; border: 1px solid #cfd6df; border-radius: 6px; padding: 10px; font: inherit; }
    textarea { min-height: 88px; resize: vertical; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .actions { margin-top: 16px; display: flex; gap: 10px; align-items: center; }
    .primary { background: #16745f; color: white; border: 0; border-radius: 6px; padding: 10px 14px; cursor: pointer; }
    pre { background: #101820; color: #d8f3dc; border-radius: 6px; padding: 12px; overflow: auto; min-height: 90px; }
    [hidden] { display: none !important; }
    @media (max-width: 760px) { main { padding: 14px; } .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<main>
  <header><h1>替换生成</h1><span>本地执行端</span></header>
  <div class="tabs">
    <button type="button" class="active" data-tab="video">视频替换</button>
    <button type="button" data-tab="note">图文替换</button>
  </div>
  <section id="video-panel">
    <form id="video-form">
      <label>来源视频链接</label><input name="sourceUrl" required aria-label="来源视频链接示例 https://example.com/video">
      <div class="grid">
        <div><label>人物图</label><input name="characterImage" type="file" accept="image/*" required></div>
        <div><label>产品图</label><input name="productImage" type="file" accept="image/*"></div>
        <div><label>场景图</label><input name="sceneImage" type="file" accept="image/*"></div>
      </div>
      <label>口播稿</label><textarea name="script"></textarea>
      <label>卖点/风格要求</label><textarea name="sellingPoints"></textarea>
      <div class="actions"><button class="primary">开始替换</button></div>
    </form>
    <pre id="video-status">{}</pre>
  </section>
  <section id="note-panel" hidden>
    <form id="note-form">
      <label>小红书图文链接</label><input name="sourceUrl" required aria-label="小红书图文链接示例 https://www.xiaohongshu.com/explore/id">
      <label>替换图片</label><input name="replacementImages" type="file" accept="image/*" multiple required>
      <div class="grid">
        <div><label>业务名称</label><input name="businessName" required></div>
        <div><label>地区</label><input name="region"></div>
        <div><label>目标客户</label><input name="audience"></div>
      </div>
      <label>卖点</label><textarea name="sellingPoints"></textarea>
      <label>语气</label><input name="tone">
      <div class="actions"><button class="primary">生成图文替换</button></div>
    </form>
    <pre id="note-status">{}</pre>
  </section>
</main>
<script>
const show = (id) => {
  document.querySelectorAll('.tabs button').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === id));
  document.getElementById('video-panel').hidden = id !== 'video';
  document.getElementById('note-panel').hidden = id !== 'note';
};
document.querySelectorAll('.tabs button').forEach(btn => btn.addEventListener('click', () => show(btn.dataset.tab)));
async function submitForm(formId, url, statusId) {
  const form = document.getElementById(formId);
  const status = document.getElementById(statusId);
  const data = new FormData(form);
  status.textContent = '提交中...';
  const res = await fetch(url, {method: 'POST', body: data});
  const json = await res.json();
  status.textContent = JSON.stringify(json, null, 2);
}
document.getElementById('video-form').addEventListener('submit', e => { e.preventDefault(); submitForm('video-form', '/api/replacement/video/start', 'video-status'); });
document.getElementById('note-form').addEventListener('submit', e => { e.preventDefault(); submitForm('note-form', '/api/replacement/note/start', 'note-status'); });
</script>
</body>
</html>"""


def _job_root(data_dir):
    return os.path.join(data_dir, "replacement_web_jobs")


def _task_root(data_dir, task_type):
    if task_type not in TASK_TYPES:
        raise ValueError("invalid_task_type")
    return os.path.join(_job_root(data_dir), task_type)


def _new_video_job_id():
    return "rvw_" + uuid.uuid4().hex[:24]


def _valid_job_id(task_type, job_id):
    job_id = str(job_id or "").strip()
    if task_type == "video":
        return bool(VIDEO_JOB_RE.match(job_id))
    if task_type == "note":
        return bool(NOTE_JOB_RE.match(job_id))
    return False


def _safe_url_parts(value):
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    path_hash = hashlib.sha256(parsed.path.encode("utf-8")).hexdigest()[:12]
    return {"scheme": parsed.scheme, "host": parsed.netloc, "pathHash": path_hash}


def _error(error, stage="preflight", status=400):
    return {"ok": False, "error": error, "stage": stage, "statusCode": status}


def _image_files(files, field_names):
    names = set(field_names)
    return [(field, filename, data) for field, filename, data in files or [] if field in names]


def _validate_images(files):
    for _field, filename, data in files:
        ext = os.path.splitext(str(filename or "").lower())[1]
        if ext not in IMAGE_EXTENSIONS:
            return _error("replacement_unsupported_file_type")
        if len(data or b"") > MAX_IMAGE_BYTES:
            return _error("replacement_upload_too_large")
    return None


def _write_job(data_dir, task_type, job):
    root = os.path.join(_task_root(data_dir, task_type), job["id"])
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "job.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def load_job(data_dir, task_type, job_id):
    if not _valid_job_id(task_type, job_id):
        return None
    path = os.path.join(_task_root(data_dir, task_type), job_id, "job.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None


def job_response(job):
    job = job or {}
    result = {
        "ok": True,
        "jobId": job.get("id") or "",
        "taskType": job.get("taskType") or "",
        "status": job.get("status") or "",
        "stage": job.get("stage") or "",
        "progressText": job.get("progressText") or "",
        "result": job.get("result") or {},
        "error": job.get("error") or "",
    }
    if job.get("taskType") == "note":
        result["imageSlots"] = job.get("imageSlots") or []
        result["copyCandidates"] = job.get("copyCandidates") or []
        result["draftMaterialId"] = job.get("draftMaterialId") or ""
    return result


def start_video_job(data_dir, fields, files):
    url_parts = _safe_url_parts((fields or {}).get("sourceUrl"))
    if not url_parts:
        return _error("replacement_invalid_source_url")
    images = _image_files(files, {"characterImage", "productImage", "sceneImage"})
    validation_error = _validate_images(images)
    if validation_error:
        return validation_error
    if not any(field == "characterImage" for field, _filename, _data in images):
        return _error("replacement_video_missing_character_image")
    job_id = _new_video_job_id()
    now = time.time()
    job = {
        "id": job_id,
        "taskType": "video",
        "status": "queued",
        "stage": "created",
        "progressText": "Phase 0 skeleton job created",
        "source": url_parts,
        "assetCount": len(images),
        "inputs": {
            "hasScript": bool(str((fields or {}).get("script") or "").strip()),
            "hasSellingPoints": bool(str((fields or {}).get("sellingPoints") or "").strip()),
        },
        "result": {"videoUrl": "", "localPath": ""},
        "createdAt": now,
        "updatedAt": now,
    }
    _write_job(data_dir, "video", job)
    return {"ok": True, "jobId": job_id, "taskType": "video", "status": "queued", "stage": "created"}


def start_note_job(data_dir, fields, files):
    url_parts = _safe_url_parts((fields or {}).get("sourceUrl"))
    if not url_parts:
        return _error("replacement_invalid_source_url")
    images = _image_files(files, {"replacementImages"})
    if not images:
        return _error("replacement_note_missing_images")
    validation_error = _validate_images(images)
    if validation_error:
        return validation_error
    selling_points = [
        item.strip()
        for item in re.split(r"[,，\n]+", str((fields or {}).get("sellingPoints") or ""))
        if item.strip()
    ]
    material = {
        "id": "web-note-source",
        "type": "image",
        "platform": "xhs",
        "title": "图文替换来源",
        "sourceUrl": str((fields or {}).get("sourceUrl") or ""),
        "files": [filename for _field, filename, _data in images],
    }
    business_input = {
        "name": (fields or {}).get("businessName") or "你的业务",
        "region": (fields or {}).get("region") or "",
        "sellingPoints": selling_points,
        "audience": (fields or {}).get("audience") or "",
        "tone": (fields or {}).get("tone") or "",
    }
    assets = [
        {"slotIndex": index, "assetId": "web-%d" % index, "filePath": filename}
        for index, (_field, filename, _data) in enumerate(images, start=1)
    ]
    smoke = xhs_note_replacement.smoke_four_image_replacement(
        material=material,
        business_input=business_input,
        provided_assets=assets,
    )
    source_job = smoke["job"]
    job = {
        "id": source_job["id"],
        "taskType": "note",
        "status": source_job.get("status") or "preview",
        "stage": "preview_created",
        "progressText": "Phase 0 note preview created",
        "source": url_parts,
        "imageSlots": (source_job.get("template") or {}).get("imageSlots") or [],
        "copyCandidates": source_job.get("copyCandidates") or [],
        "draftMaterialId": "",
        "createdAt": time.time(),
        "updatedAt": time.time(),
    }
    _write_job(data_dir, "note", job)
    return {"ok": True, "jobId": job["id"], "taskType": "note", "status": "preview", "stage": "preview_created"}
```

- [ ] **Step 4: Run module tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebModuleTests -v
```

Expected: PASS.

- [ ] **Step 5: Run feature gate tests again**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Do not commit until implementation line docs are current. When ready:

```bash
git add backend/replacement_web.py tests/test_replacement_web_mvp.py
git commit -m "feat: add local replacement web support module"
```

---

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

Do not commit until docs line numbers are current. When ready:

```bash
git add backend/api_server.py tests/test_replacement_web_mvp.py
git commit -m "feat: expose local replacement web routes"
```

---

### Task 4: OpenAPI And API Reference

**Files:**
- Modify: `docs/openapi.yaml`
- Modify: `docs/API_REFERENCE.md`
- Modify: `tests/test_replacement_web_mvp.py`

**Interfaces:**
- Consumes: route contracts implemented in Task 3.
- Produces: documented API contract for `/replacement` and `/api/replacement/*`.

- [ ] **Step 1: Write failing documentation contract tests**

Append to `tests/test_replacement_web_mvp.py`:

```python
class ReplacementWebDocumentationTests(unittest.TestCase):
    def test_openapi_documents_replacement_api_paths(self):
        text = (ROOT / "docs" / "openapi.yaml").read_text(encoding="utf-8")

        self.assertIn("/api/replacement/video/start:", text)
        self.assertIn("/api/replacement/video/job:", text)
        self.assertIn("/api/replacement/note/start:", text)
        self.assertIn("/api/replacement/note/job:", text)
        self.assertIn("ReplacementVideoStartResponse", text)
        self.assertIn("ReplacementNoteJobResponse", text)

    def test_api_reference_documents_local_only_replacement_page(self):
        text = (ROOT / "docs" / "API_REFERENCE.md").read_text(encoding="utf-8")

        self.assertIn("GET /replacement", text)
        self.assertIn("MATRIX_REPLACEMENT_WEB_ENABLED", text)
        self.assertIn("本地执行端", text)
        self.assertIn("POST /api/replacement/video/start", text)
        self.assertIn("POST /api/replacement/note/start", text)
```

- [ ] **Step 2: Run docs tests and verify they fail**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebDocumentationTests -v
```

Expected: FAIL because docs do not yet include the new paths.

- [ ] **Step 3: Update `docs/openapi.yaml`**

Add these paths under `paths:`:

```yaml
  /api/replacement/video/start:
    post:
      summary: Start a local video replacement Phase 0 job
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              $ref: '#/components/schemas/ReplacementVideoStartRequest'
      responses:
        '200':
          description: Job created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ReplacementVideoStartResponse'
        '400':
          description: Invalid replacement request
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'

  /api/replacement/video/job:
    get:
      summary: Read a local video replacement job
      parameters:
        - in: query
          name: id
          required: true
          schema:
            type: string
            pattern: '^rvw_[0-9a-f]{24}$'
      responses:
        '200':
          description: Video replacement job status
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ReplacementVideoJobResponse'

  /api/replacement/note/start:
    post:
      summary: Start a local image-note replacement Phase 0 job
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              $ref: '#/components/schemas/ReplacementNoteStartRequest'
      responses:
        '200':
          description: Job created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ReplacementNoteStartResponse'
        '400':
          description: Invalid replacement request
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'

  /api/replacement/note/job:
    get:
      summary: Read a local image-note replacement job
      parameters:
        - in: query
          name: id
          required: true
          schema:
            type: string
            pattern: '^xnr_[0-9a-f]{24}$'
      responses:
        '200':
          description: Image-note replacement job status
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ReplacementNoteJobResponse'
```

Add these schemas under `components.schemas`. If `ErrorResponse` already exists, reuse it and do not duplicate it:

```yaml
    ReplacementVideoStartRequest:
      type: object
      required: [sourceUrl, characterImage]
      properties:
        sourceUrl:
          type: string
          format: uri
        characterImage:
          type: string
          format: binary
        productImage:
          type: string
          format: binary
        sceneImage:
          type: string
          format: binary
        script:
          type: string
        sellingPoints:
          type: string

    ReplacementVideoStartResponse:
      type: object
      required: [ok, jobId, taskType, status, stage]
      properties:
        ok:
          type: boolean
        jobId:
          type: string
          pattern: '^rvw_[0-9a-f]{24}$'
        taskType:
          const: video
        status:
          type: string
        stage:
          type: string

    ReplacementVideoJobResponse:
      type: object
      required: [ok, jobId, taskType, status, stage, result]
      properties:
        ok:
          type: boolean
        jobId:
          type: string
        taskType:
          const: video
        status:
          type: string
        stage:
          type: string
        progressText:
          type: string
        result:
          type: object
          additionalProperties: true
        error:
          type: string

    ReplacementNoteStartRequest:
      type: object
      required: [sourceUrl, replacementImages, businessName]
      properties:
        sourceUrl:
          type: string
          format: uri
        replacementImages:
          type: array
          items:
            type: string
            format: binary
        businessName:
          type: string
        region:
          type: string
        sellingPoints:
          type: string
        audience:
          type: string
        tone:
          type: string

    ReplacementNoteStartResponse:
      type: object
      required: [ok, jobId, taskType, status, stage]
      properties:
        ok:
          type: boolean
        jobId:
          type: string
          pattern: '^xnr_[0-9a-f]{24}$'
        taskType:
          const: note
        status:
          type: string
        stage:
          type: string

    ReplacementNoteJobResponse:
      type: object
      required: [ok, jobId, taskType, status, stage, imageSlots, copyCandidates]
      properties:
        ok:
          type: boolean
        jobId:
          type: string
        taskType:
          const: note
        status:
          type: string
        stage:
          type: string
        progressText:
          type: string
        imageSlots:
          type: array
          items:
            type: object
            additionalProperties: true
        copyCandidates:
          type: array
          items:
            type: object
            additionalProperties: true
        draftMaterialId:
          type: string
        error:
          type: string
```

- [ ] **Step 4: Update `docs/API_REFERENCE.md`**

Add a section near the local execution API sections:

```markdown
## 本地执行端替换网页 MVP

### GET /replacement

本地执行端内嵌 HTML 页面，仅在 `MATRIX_REPLACEMENT_WEB_ENABLED=1` 时开放。该页面不是独立产品 Web 前端，不依赖 `frontend/` 工程，也不恢复旧 `/admin` 页面。页面包含“视频替换”和“图文替换”两个标签页。

关闭开关时返回：

```json
{"ok": false, "error": "replacement_web_disabled"}
```

### POST /api/replacement/video/start

`multipart/form-data`。字段：`sourceUrl`、`characterImage`、`productImage`、`sceneImage`、`script`、`sellingPoints`。Phase 0 仅创建本地 `rvw_` 任务，不提交真实远程模型。

### GET /api/replacement/video/job

查询 `rvw_` 本地任务状态。

### POST /api/replacement/note/start

`multipart/form-data`。字段：`sourceUrl`、`replacementImages`、`businessName`、`region`、`sellingPoints`、`audience`、`tone`。Phase 0 复用图文同款预览骨架生成 `xnr_` 任务和三套文案候选。

### GET /api/replacement/note/job

查询 `xnr_` 本地图文替换任务状态，返回图片槽位和文案候选的安全子集。

所有接口日志必须脱敏来源链接 query、Cookie、Authorization、签名 URL 和 base64 图片内容。
```

- [ ] **Step 5: Run docs tests and OpenAPI contract tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebDocumentationTests -v
.\.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v
```

Expected: PASS. If `tests.test_openapi_contract` fails because the schema shape must match an existing helper convention, adjust `docs/openapi.yaml` only, without weakening the new replacement tests.

- [ ] **Step 6: Commit**

Do not commit until implementation line docs are current. When ready:

```bash
git add docs/openapi.yaml docs/API_REFERENCE.md tests/test_replacement_web_mvp.py
git commit -m "docs: document local replacement web api"
```

---

### Task 5: Production Docs, Smoke Notes, And Release Records

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`
- Modify: `migration.sql`

**Interfaces:**
- Consumes: final code line numbers from Tasks 1-4.
- Produces: production docs consistent with code.

- [ ] **Step 1: Update architecture doc**

Add a concise note to `docs/ARCHITECTURE.md`:

```markdown
### 本地执行端替换网页

本地执行端可在 `MATRIX_REPLACEMENT_WEB_ENABLED=1` 时提供 `/replacement` 页面。该页面由 `backend/api_server.py` 直接服务，复用本机账号、素材目录和替换任务逻辑；它不是独立 `frontend/` Web 产品面，也不恢复旧 `/admin` 页面。视频替换和图文替换任务状态写入本地 JSON，远程模型输入必须先转换为可访问 HTTPS 媒体 URL。
```

- [ ] **Step 2: Update deployment doc**

Add to the environment variable table in `docs/DEPLOYMENT.md`:

```markdown
| `MATRIX_REPLACEMENT_WEB_ENABLED` | 本地执行端是否开放 `/replacement` 替换网页 | `0` | 设置为 `1` 后重启本地执行端生效；关闭后页面和 start API 返回 `replacement_web_disabled` |
```

- [ ] **Step 3: Update troubleshooting with Phase 0 result**

Add to `docs/TROUBLESHOOTING.md`:

```markdown
## 本地 /replacement 替换网页 Phase 0

症状：`GET /replacement` 返回 `replacement_web_disabled`。

处理：确认本地执行端环境变量 `MATRIX_REPLACEMENT_WEB_ENABLED=1`，并重启本地执行端。该开关默认关闭，用于快速回滚本地替换网页入口。

Phase 0 冒烟：使用假视频链接和假人物图调用 `/api/replacement/video/start`，返回 `rvw_` job；使用假小红书链接和两张假图片调用 `/api/replacement/note/start`，返回 `xnr_` job 和三套文案候选。Phase 0 不提交真实远程模型，不产生真实 LK888 费用。
```

- [ ] **Step 4: Update changelog**

Add near the top of `CHANGELOG.md`:

```markdown
## 2026-08-04 本地执行端替换网页 MVP

- 本地执行端新增可开关的 `/replacement` Phase 0 页面，包含“视频替换”和“图文替换”两个标签页；页面只创建本地替换任务并展示状态，不恢复独立 Web 前端、不接真实发布、不做资产库管理。
- 新增 `/api/replacement/video/start`、`/api/replacement/video/job`、`/api/replacement/note/start`、`/api/replacement/note/job` 本地接口；默认由 `MATRIX_REPLACEMENT_WEB_ENABLED=0` 关闭，开启后需重启本地执行端。
- RED/GREEN 覆盖 feature gate、页面 HTML、Phase 0 任务创建、错误校验、OpenAPI/API reference 和日志脱敏边界；`py_compile` 通过。
- 本次影响本地执行端、OpenAPI/API 文档和本地 JSON 任务骨架；不改变中心服数据库、Docker 镜像结构、远程 AI Canvas 部署或真实 LK888 提交逻辑。回滚时关闭 `MATRIX_REPLACEMENT_WEB_ENABLED` 并恢复相关代码/文档即可。
```

- [ ] **Step 5: Update migration no-op**

Append to `migration.sql`:

```sql
-- 2026-08-04 local replacement web MVP: no database schema change.
-- Local /replacement Phase 0 jobs are stored as local JSON under the agent data directory.
```

- [ ] **Step 6: Update implementation line references**

After final code edits, compute exact line references:

```powershell
rg -n "MATRIX_REPLACEMENT_WEB_ENABLED|def replacement_web_enabled" backend\platform_features.py
rg -n "def replacement_page_html|def start_video_job|def start_note_job|def load_job|def job_response" backend\replacement_web.py
rg -n "path == \"/replacement\"|/api/replacement/video/start|/api/replacement/note/start|html_response" backend\api_server.py
rg -n "ReplacementWebFeatureGateTests|ReplacementWebModuleTests|ReplacementApiServerRouteTests|ReplacementWebDocumentationTests" tests\test_replacement_web_mvp.py
```

Add a section to `docs/IMPLEMENTATION.md` using exact line references from the commands above. Each bullet must use the concrete `path#Lnumber-Lnumber` format from the final code after formatting. The section must cover:

- `backend/platform_features.py` feature gate lines.
- `backend/replacement_web.py` HTML, validation, job persistence, start helpers, and response helper lines.
- `backend/api_server.py` HTML route, status routes, start routes, and structured logging lines.
- `tests/test_replacement_web_mvp.py` feature gate, module, route, and docs contract test lines.
- The exact unittest, OpenAPI test, `py_compile`, and Phase 0 smoke commands actually run.
- Rollback instructions: close `MATRIX_REPLACEMENT_WEB_ENABLED`, restart the local execution server, and revert touched code/tests/docs/no-op migration if needed.

Before committing, scan `docs/IMPLEMENTATION.md` for non-final line markers:

```powershell
rg -n "L\\.\\.\\.|Lx|TODO|TBD" docs\IMPLEMENTATION.md
```

Expected: no matches.

- [ ] **Step 7: Run docs tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

Only after line references are recalculated:

```bash
git add docs/ARCHITECTURE.md docs/DEPLOYMENT.md docs/TROUBLESHOOTING.md docs/IMPLEMENTATION.md CHANGELOG.md migration.sql
git commit -m "docs: record local replacement web mvp rollout"
```

---

### Task 6: Final Verification

**Files:**
- No new source files unless previous tasks reveal a bug.

**Interfaces:**
- Consumes: all code and docs from Tasks 1-5.
- Produces: verification evidence for final handoff.

- [ ] **Step 1: Run focused replacement web tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run adjacent XHS note replacement tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteApiSourceTests tests.test_xhs_note_replacement.XhsNotePreviewTests -v
```

Expected: PASS. These prove the new facade did not break the existing graph for image-note replacement.

- [ ] **Step 3: Run OpenAPI contract tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v
```

Expected: PASS.

- [ ] **Step 4: Run syntax check**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\api_server.py backend\replacement_web.py backend\platform_features.py tests\test_replacement_web_mvp.py
```

Expected: PASS with no output.

- [ ] **Step 5: Run diff hygiene**

Run:

```powershell
git diff --check
```

Expected: PASS or only pre-existing unrelated whitespace issues. If it fails on files touched by this plan, fix them before completion.

- [ ] **Step 6: Manual Phase 0 smoke**

Start the local execution server with the feature flag enabled:

```powershell
$env:MATRIX_REPLACEMENT_WEB_ENABLED="1"
.\.venv-win\Scripts\python.exe backend\api_server.py
```

In a separate terminal or browser:

```powershell
Invoke-WebRequest http://127.0.0.1:9080/replacement
```

Expected: HTTP 200 HTML containing `视频替换` and `图文替换`.

If terminal multipart smoke is needed, use a small local image fixture and submit both start endpoints. Do not use real provider credentials or real LK888 generation in Phase 0.

- [ ] **Step 7: Verify rollback switch**

Restart without the flag or set it to `0`:

```powershell
$env:MATRIX_REPLACEMENT_WEB_ENABLED="0"
.\.venv-win\Scripts\python.exe backend\api_server.py
```

Request:

```powershell
Invoke-WebRequest http://127.0.0.1:9080/replacement -SkipHttpErrorCheck
```

Expected: HTTP 404 JSON with `replacement_web_disabled`.

- [ ] **Step 8: Final status summary**

Record:

- changed tiers: local executor and docs/contracts;
- files changed;
- tests and smoke checks run;
- restart required: local execution server restart after changing `MATRIX_REPLACEMENT_WEB_ENABLED`;
- OpenAPI impact: new local replacement API paths;
- database/migration impact: no schema change, no-op `migration.sql`;
- rollback: set `MATRIX_REPLACEMENT_WEB_ENABLED=0`, restart local execution server, or revert touched files;
- remaining risk: Phase 0 does not prove real remote video generation or downloadable provider media.
