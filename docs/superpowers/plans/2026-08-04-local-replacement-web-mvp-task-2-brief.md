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

Do not commit in this task. The user confirmed per-task commits are disabled; the controller will make one final commit only after all code, docs, OpenAPI, and `docs/IMPLEMENTATION.md` line references are stable. Leave the working tree changes unstaged.

Do not run `git add` or `git commit` for this task.

---

