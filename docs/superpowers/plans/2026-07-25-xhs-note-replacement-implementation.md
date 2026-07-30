# 小红书图文同款替换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first version of 小红书图文同款替换: analyze a collected XHS image-note into a reusable template, replace slots with user/asset images or AI placeholders, generate 3 copy variants, save an image-note draft to 素材发布, and save the reusable template/assets to 资产库.

**Architecture:** Add a focused local backend module for image-note replacement state, template extraction, slot mapping, copy candidates, and draft payload construction. Wire that module into existing local material library, central library mirror, web UI, native navigation, and asset library without enabling real XHS multi-image publishing in v1.

**Tech Stack:** Python stdlib HTTP handlers in `backend/api_server.py` and `backend/central_server.py`; JSON state under `backend/datas`; existing material directories; Qt/PySide-style native client in `backend/matrix_native_client.py`; single-file web frontend in `frontend/index.html`; unittest tests under `tests/`.

## Global Constraints

- First version only saves publishable drafts; it does not auto-publish to 小红书.
- Entry points: 小红书采集结果卡片 and 素材发布图文素材详情.
- Left navigation label: `图文同款`.
- 素材发布 filter: add `图文`.
- 资产库 category: add `图文模板`.
- AI missing-image rule: use existing image generation capability; generate 1 image per missing slot; use source slot ratio, default 3:4; failure does not block the whole draft; generated image must be manually confirmed before future real publish.
- Draft behavior: save to 素材发布 and 资产库, default `status=draft`, do not auto-queue.
- Observability: every job records `jobId`, `sourceMaterialId`, `sourceNoteId`, `aiSlotCount`, and structured `errorId` on failure.
- Rollback: feature flag `XHS_NOTE_REPLACEMENT_ENABLED=0` hides entry points and disables endpoints without deleting saved drafts/templates.
- Security: do not log Cookie, Authorization, API keys, Base64 image content, or signed URL query tokens.

---

## File Structure

- Create `backend/xhs_note_replacement.py`: pure helpers for feature flag, template extraction, slot mapping, copy candidates, AI placeholder bookkeeping, atomic job persistence, and draft payload construction.
- Create `tests/test_xhs_note_replacement.py`: helper tests, source-level UI tests, publish gate tests, and fake 4-image smoke test.
- Modify `backend/api_server.py`: local `/api/xhs-note-replacement/*` endpoints, `image_note` draft save, AI confirmation, local publish guard.
- Modify `backend/central_server.py`: preserve `image_note` metadata in mirror flow and add central publish preflight blockers.
- Modify `frontend/index.html`: two entry points, `图文` filter, dedicated `图文同款` page, AI confirmation UI, draft save.
- Modify `backend/matrix_native_client.py`: `图文同款` nav page and `图文模板` asset filter/category.
- Update docs: `docs/API_REFERENCE.md`, `docs/openapi.yaml`, `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`, `docs/IMPLEMENTATION.md`, `CHANGELOG.md`.

## Task 0: Smoke Skeleton and Feature Flag

**Files:**
- Create: `backend/xhs_note_replacement.py`
- Create: `tests/test_xhs_note_replacement.py`
- Modify: `docs/TROUBLESHOOTING.md`

**Interfaces:**
- Produces: `feature_enabled(env: Mapping[str, str] | None = None) -> bool`
- Produces: `new_job_id() -> str`
- Produces: `job_root(data_dir: str) -> str`

- [ ] **Step 1: Write the failing smoke tests**

Add to `tests/test_xhs_note_replacement.py`:

```python
import os
import tempfile
import unittest

from backend import xhs_note_replacement as note


class XhsNoteReplacementSmokeTests(unittest.TestCase):
    def test_feature_enabled_defaults_true_and_env_can_disable(self):
        self.assertTrue(note.feature_enabled({}))
        self.assertFalse(note.feature_enabled({"XHS_NOTE_REPLACEMENT_ENABLED": "0"}))
        self.assertFalse(note.feature_enabled({"XHS_NOTE_REPLACEMENT_ENABLED": "false"}))
        self.assertTrue(note.feature_enabled({"XHS_NOTE_REPLACEMENT_ENABLED": "1"}))

    def test_job_root_is_inside_data_dir(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(note.job_root(td), os.path.join(td, "xhs_note_replacements"))

    def test_new_job_id_is_traceable(self):
        self.assertRegex(note.new_job_id(), r"^xnr_[0-9a-f]{24}$")
```

- [ ] **Step 2: Run the failing smoke tests**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteReplacementSmokeTests -v`

Expected: FAIL because module/functions do not exist.

- [ ] **Step 3: Implement minimal helper skeleton**

Create `backend/xhs_note_replacement.py`:

```python
import os
import uuid
from typing import Mapping, Optional

FEATURE_ENV = "XHS_NOTE_REPLACEMENT_ENABLED"


def feature_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    source = os.environ if env is None else env
    raw = str(source.get(FEATURE_ENV, "1") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def new_job_id() -> str:
    return "xnr_" + uuid.uuid4().hex[:24]


def job_root(data_dir: str) -> str:
    return os.path.join(data_dir, "xhs_note_replacements")
```

- [ ] **Step 4: Verify smoke tests pass**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteReplacementSmokeTests -v`

Expected: PASS.

- [ ] **Step 5: Record Phase 0 smoke result**

Append to `docs/TROUBLESHOOTING.md`:

```markdown
- 图文同款替换 Phase 0：新增功能开关与任务目录骨架，`tests.test_xhs_note_replacement.XhsNoteReplacementSmokeTests` 通过；后续任务在该骨架上补模板、草稿和门禁。
```

## Task 1: Template and Slot Analysis Helpers

**Files:**
- Modify: `backend/xhs_note_replacement.py`
- Modify: `tests/test_xhs_note_replacement.py`

**Interfaces:**
- Consumes: `new_job_id()` from Task 0.
- Produces: `build_template(material: dict, source_note: dict | None = None) -> dict`
- Produces: `infer_slot_role(index: int, total: int, name: str = "") -> str`

- [ ] **Step 1: Write failing template tests**

Add:

```python
class XhsNoteTemplateTests(unittest.TestCase):
    def test_build_template_uses_material_files_and_source_fields(self):
        material = {
            "id": "mat-xhs-1",
            "type": "image",
            "platform": "xhs",
            "title": "原始标题",
            "body": "原始正文",
            "tags": ["#汽车", "#昆山"],
            "sourceUrl": "https://www.xiaohongshu.com/explore/abc",
            "files": ["01.jpg", "02.jpg", "03.jpg", "04.jpg"],
        }
        tpl = note.build_template(material)
        self.assertEqual(tpl["sourcePlatform"], "xhs")
        self.assertEqual(tpl["sourceMaterialId"], "mat-xhs-1")
        self.assertEqual(tpl["sourceNoteId"], "abc")
        self.assertEqual([s["role"] for s in tpl["imageSlots"]], ["cover", "product", "detail", "cta"])
        self.assertEqual(tpl["originalCopy"]["title"], "原始标题")

    def test_infer_slot_role_for_short_and_long_notes(self):
        self.assertEqual(note.infer_slot_role(1, 1), "cover")
        self.assertEqual(note.infer_slot_role(2, 6), "product")
        self.assertEqual(note.infer_slot_role(5, 6), "result")
        self.assertEqual(note.infer_slot_role(6, 6), "cta")
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteTemplateTests -v`

Expected: FAIL because functions are missing.

- [ ] **Step 3: Implement template helpers**

Add to `backend/xhs_note_replacement.py`:

```python
import re
import time
from urllib.parse import urlparse


def _note_id_from_url(url: str) -> str:
    path = urlparse(str(url or "")).path.strip("/")
    parts = [p for p in path.split("/") if p]
    if "explore" in parts:
        idx = parts.index("explore")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return parts[-1] if parts else ""


def infer_slot_role(index: int, total: int, name: str = "") -> str:
    if index <= 1:
        return "cover"
    if total <= 2:
        return "cta" if index == total else "product"
    if index == total:
        return "cta"
    if index == total - 1 and total >= 5:
        return "result"
    if index == 2:
        return "product"
    if re.search(r"scene|store|shop|门店|场景", str(name or ""), re.I):
        return "scene"
    return "detail"


def build_template(material: dict, source_note: dict | None = None) -> dict:
    material = material or {}
    source_note = source_note or {}
    files = [str(x or "") for x in (material.get("files") or []) if str(x or "").strip()]
    source_url = material.get("sourceUrl") or source_note.get("url") or source_note.get("noteUrl") or ""
    total = len(files)
    slots = []
    for idx, name in enumerate(files, start=1):
        role = infer_slot_role(idx, total, name)
        slots.append({"index": idx, "role": role, "sourceFile": name, "analysis": "%s槽位，来自原图第%d张" % (role, idx), "ratio": material.get("ratio") or "3:4"})
    return {
        "id": "tpl_" + uuid.uuid4().hex[:24],
        "sourcePlatform": material.get("platform") or "xhs",
        "sourceNoteId": source_note.get("noteId") or material.get("noteId") or _note_id_from_url(source_url),
        "sourceMaterialId": material.get("id") or "",
        "sourceUrl": source_url,
        "imageSlots": slots,
        "copyStructure": {"titlePattern": "原始标题结构", "bodyPattern": ["开头钩子", "卖点", "场景", "行动引导"], "tagPattern": ["行业词", "地域词", "需求词"]},
        "originalCopy": {"title": material.get("title") or source_note.get("title") or "", "body": material.get("body") or source_note.get("body") or "", "tags": material.get("tags") or source_note.get("tags") or []},
        "createdAt": time.time(),
    }
```

- [ ] **Step 4: Verify helper tests pass**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement -v`

Expected: PASS for smoke and template tests.

## Task 2: Slot Mapping, AI Placeholder State, and Copy Candidates

**Files:**
- Modify: `backend/xhs_note_replacement.py`
- Modify: `tests/test_xhs_note_replacement.py`

**Interfaces:**
- Consumes: `build_template(material)`.
- Produces: `build_replacement_preview(template: dict, business_input: dict, provided_assets: list[dict]) -> dict`
- Produces: `copy_candidates(template: dict, business_input: dict) -> list[dict]`

- [ ] **Step 1: Write failing preview test**

Add:

```python
class XhsNotePreviewTests(unittest.TestCase):
    def test_preview_prefers_assets_and_marks_missing_slots_ai_pending(self):
        tpl = {"id": "tpl-1", "imageSlots": [{"index": 1, "role": "cover", "ratio": "3:4"}, {"index": 2, "role": "product", "ratio": "1:1"}]}
        preview = note.build_replacement_preview(
            tpl,
            {"name": "广汽丰田", "sellingPoints": ["省油", "到店试驾"], "region": "昆山", "audience": "家用车客户", "tone": "真实种草"},
            [{"slotRole": "cover", "assetId": "as-1", "filePath": "cover.jpg"}],
        )
        self.assertEqual(preview["slotMappings"][0]["source"], "asset")
        self.assertEqual(preview["slotMappings"][1]["source"], "ai_placeholder")
        self.assertEqual(preview["slotMappings"][1]["confirmationStatus"], "pending")
        self.assertEqual(preview["aiSlotCount"], 1)
        self.assertEqual(len(preview["copyCandidates"]), 3)
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNotePreviewTests -v`

Expected: FAIL.

- [ ] **Step 3: Implement preview helpers**

Add deterministic helper code:

```python
def _asset_for_role(role: str, assets: list[dict]) -> dict | None:
    for asset in assets or []:
        if str(asset.get("slotRole") or asset.get("role") or "") == role:
            return asset
    return None


def copy_candidates(template: dict, business_input: dict) -> list[dict]:
    business_input = business_input or {}
    name = business_input.get("name") or "你的业务"
    region = business_input.get("region") or "本地"
    selling = [str(x) for x in (business_input.get("sellingPoints") or []) if str(x).strip()]
    first = selling[0] if selling else "核心卖点"
    audience = business_input.get("audience") or "目标客户"
    return [
        {"title": "%s｜%s也能轻松选" % (region, first), "body": "如果你正在关注%s，这组图文按真实体验整理：%s。适合%s先收藏再对比。" % (name, "、".join(selling) or first, audience), "tags": ["#%s" % region, "#%s" % name, "#同城种草"]},
        {"title": "为什么大家都在看%s" % name, "body": "这次把重点放在%s：%s。图片里按封面、细节和行动引导整理，方便你快速判断是否适合。" % (name, "、".join(selling) or first), "tags": ["#小红书图文", "#%s" % first, "#%s" % region]},
        {"title": "%s避坑清单：先看这几点" % name, "body": "别只看表面，重点看%s。我们按真实使用场景拆成几张图，适合%s做决策前参考。" % ("、".join(selling) or first, audience), "tags": ["#避坑", "#%s" % name, "#%s" % region]},
    ]


def build_replacement_preview(template: dict, business_input: dict, provided_assets: list[dict]) -> dict:
    mappings = []
    ai_count = 0
    for slot in template.get("imageSlots") or []:
        role = slot.get("role") or "detail"
        asset = _asset_for_role(role, provided_assets)
        if asset:
            mappings.append({"slotIndex": slot.get("index"), "slotRole": role, "source": "asset", "assetId": asset.get("assetId") or asset.get("id") or "", "filePath": asset.get("filePath") or asset.get("path") or "", "confirmationStatus": "confirmed"})
        else:
            ai_count += 1
            mappings.append({"slotIndex": slot.get("index"), "slotRole": role, "source": "ai_placeholder", "ratio": slot.get("ratio") or "3:4", "filePath": "", "confirmationStatus": "pending"})
    return {"templateId": template.get("id"), "slotMappings": mappings, "copyCandidates": copy_candidates(template, business_input), "selectedCopyIndex": 0, "aiSlotCount": ai_count}
```

- [ ] **Step 4: Verify tests**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement -v`

Expected: PASS.

## Task 3: Local API Endpoints and Draft Save Transaction

**Files:**
- Modify: `backend/xhs_note_replacement.py`
- Modify: `backend/api_server.py`
- Modify: `tests/test_xhs_note_replacement.py`

**Interfaces:**
- Produces endpoints: `POST /api/xhs-note-replacement/template`, `/preview`, `/confirm-ai-image`, `/save-draft`; `GET /api/xhs-note-replacement/job?id=...`.
- Produces: `save_job(data_dir: str, job: dict) -> str`
- Produces: `load_job(data_dir: str, job_id: str) -> dict | None`
- Produces: `build_draft_material_payload(job: dict, saved_files: list[str]) -> dict`

- [ ] **Step 1: Write failing persistence and draft tests**

Add:

```python
class XhsNoteJobPersistenceTests(unittest.TestCase):
    def test_save_and_load_job_is_atomic_json(self):
        with tempfile.TemporaryDirectory() as td:
            job = {"id": "xnr_1234567890abcdef12345678", "status": "draft", "slotMappings": []}
            path = note.save_job(td, job)
            self.assertTrue(path.endswith("replacement_job.json"))
            self.assertEqual(note.load_job(td, job["id"])["id"], job["id"])

    def test_draft_material_payload_marks_image_note_and_ai_review(self):
        job = {"id": "xnr_1234567890abcdef12345678", "templateId": "tpl-1", "slotMappings": [{"slotIndex": 1, "source": "asset", "filePath": "01.jpg", "confirmationStatus": "confirmed"}, {"slotIndex": 2, "source": "ai_placeholder", "filePath": "02.jpg", "confirmationStatus": "pending"}], "copyCandidates": [{"title": "标题", "body": "正文", "tags": ["#标签"]}], "selectedCopyIndex": 0}
        payload = note.build_draft_material_payload(job, ["01.jpg", "02.jpg"])
        self.assertEqual(payload["type"], "image_note")
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["aiImageReview"]["pendingSlots"], [2])
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteJobPersistenceTests -v`

Expected: FAIL.

- [ ] **Step 3: Implement persistence and payload helpers**

Add JSON atomic write/load helpers and draft payload construction. The helper must validate `job_id` with regex `^xnr_[0-9a-f]{24}$`, write to `xhs_note_replacements/<jobId>/replacement_job.json.tmp`, then `os.replace` to `replacement_job.json`.

- [ ] **Step 4: Add local API route source test**

Add:

```python
class XhsNoteApiSourceTests(unittest.TestCase):
    def test_local_api_declares_xhs_note_replacement_routes(self):
        root = os.path.dirname(os.path.dirname(__file__))
        src = open(os.path.join(root, "backend", "api_server.py"), encoding="utf-8").read()
        self.assertIn("/api/xhs-note-replacement/template", src)
        self.assertIn("/api/xhs-note-replacement/save-draft", src)
```

- [ ] **Step 5: Wire `backend/api_server.py`**

Import `backend.xhs_note_replacement as xhs_note_replacement`. Add `GET /api/xhs-note-replacement/job` before `/api/library`. Add POST handlers before download routes. `save-draft` must create a new material with `type=image_note`, `platform=xhs`, `status=draft`, `body`, `tags`, `aiImageReview`, `sourceTemplateId`, and `replacementJobId`. It must copy only replacement files from `slotMappings.filePath`, not original XHS source files unless those paths are explicitly selected replacement assets.

- [ ] **Step 6: Verify local API/helper tests**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement -v`

Expected: PASS.

## Task 4: Central Mirror and Publish Preflight Gates

**Files:**
- Modify: `backend/xhs_note_replacement.py`
- Modify: `backend/api_server.py`
- Modify: `backend/central_server.py`
- Modify: `tests/test_xhs_note_replacement.py`

**Interfaces:**
- Produces blocker errors: `xhs_note_ai_image_unconfirmed`, `xhs_note_publish_not_supported`.

- [ ] **Step 1: Write failing publish gate tests**

Add:

```python
class XhsNotePublishGateTests(unittest.TestCase):
    def test_unconfirmed_ai_image_has_specific_blocker(self):
        material = {"type": "image_note", "aiImageReview": {"pendingSlots": [1]}}
        self.assertEqual(note.image_note_publish_blocker(material), "xhs_note_ai_image_unconfirmed")

    def test_image_note_publish_is_blocked_in_v1_even_when_ai_confirmed(self):
        material = {"type": "image_note", "aiImageReview": {"pendingSlots": [], "confirmedSlots": [1]}}
        self.assertEqual(note.image_note_publish_blocker(material), "xhs_note_publish_not_supported")
```

- [ ] **Step 2: Implement blocker helper**

Add `image_note_publish_blocker(material: dict) -> str`. If material type is not `image_note`, return empty string. If `aiImageReview.pendingSlots` is non-empty, return `xhs_note_ai_image_unconfirmed`. Otherwise return `xhs_note_publish_not_supported`.

- [ ] **Step 3: Wire local and central preflight**

In `backend/api_server.py` inside `/api/publish/run`, before `run_publish(...)`, call the blocker and return HTTP 400 with `stage=publish_preflight`. In `backend/central_server.py`, add the same check inside `publish_preflight(...)` after `material_ready(...)`.

- [ ] **Step 4: Preserve metadata in central mirror**

In `mirror_download_material_to_library(...)`, copy these optional keys from node material to central item: `body`, `tags`, `status`, `aiImageReview`, `sourceTemplateId`, `replacementJobId`, `importedFromXhsNoteReplacement`.

- [ ] **Step 5: Verify publish and download regressions**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement tests.test_api_download_contract -v`

Expected: PASS.

## Task 5: Web Frontend Entry Points and 图文同款 Page

**Files:**
- Modify: `frontend/index.html`
- Modify: `tests/test_xhs_note_replacement.py`

**Interfaces:**
- Produces actions: `openXhsNoteReplaceFromResult`, `openXhsNoteReplaceFromMaterial`, `xhsNoteGeneratePreview`, `xhsNoteSaveDraft`, `xhsNoteConfirmAi`.

- [ ] **Step 1: Write failing web source test**

Add:

```python
class XhsNoteWebUiTests(unittest.TestCase):
    def test_frontend_has_two_entry_points_page_and_filter(self):
        root = os.path.dirname(os.path.dirname(__file__))
        src = open(os.path.join(root, "frontend", "index.html"), encoding="utf-8").read()
        self.assertIn("openXhsNoteReplaceFromResult", src)
        self.assertIn("openXhsNoteReplaceFromMaterial", src)
        self.assertIn("xhsNoteGeneratePreview", src)
        self.assertIn("xhsNoteSaveDraft", src)
        self.assertIn("图文同款", src)
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteWebUiTests -v`

Expected: FAIL.

- [ ] **Step 3: Add state and actions**

Add state keys for `xhsNoteReplace`, `xhsNoteBusy`, `xhsNoteMsg`, `xhsNoteBusiness`, `xhsNotePreview`, `xhsNoteSelectedCopy`, and `libraryFilter`. Add actions that call the new API endpoints and refresh `loadLibrary()` after saving.

- [ ] **Step 4: Add UI entry points and page**

Add `图文同款` button in `dyResultsView` for XHS result cards. Add `图文同款` button in `libraryView` for XHS non-video materials. Add a dedicated `xhsNoteReplace` module/page with left original template, middle replacement config, right preview and AI confirmation status. Add `图文` filter to the material library view.

- [ ] **Step 5: Verify web source test**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteWebUiTests -v`

Expected: PASS.

## Task 6: Native Navigation and Asset Library Category

**Files:**
- Modify: `backend/matrix_native_client.py`
- Modify: `tests/test_xhs_note_replacement.py`

**Interfaces:**
- Produces nav entry: `("🧩 图文同款", lambda: XhsNoteReplacementPage())`
- Produces asset kind/category: `note_template` displayed as `图文模板`.

- [ ] **Step 1: Write failing native source test**

Add:

```python
class XhsNoteNativeUiTests(unittest.TestCase):
    def test_native_client_has_note_replacement_nav_and_asset_template_filter(self):
        root = os.path.dirname(os.path.dirname(__file__))
        src = open(os.path.join(root, "backend", "matrix_native_client.py"), encoding="utf-8").read()
        self.assertIn("class XhsNoteReplacementPage", src)
        self.assertIn('("🧩 图文同款", lambda: XhsNoteReplacementPage())', src)
        self.assertIn('("note_template", "图文模板"', src)
```

- [ ] **Step 2: Run and confirm failure**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeUiTests -v`

Expected: FAIL.

- [ ] **Step 3: Add native page and nav entry**

Add `XhsNoteReplacementPage` near `VideoReplacementPage`. Keep it minimal: source material ID input, business fields, generate preview, save draft, and visible draft-only status. Add nav item under “内容生产”.

- [ ] **Step 4: Extend asset library**

Allow `add_asset(..., kind="note_template")`. Add `("note_template", "图文模板", "grid")` to local asset filters. Render template assets as text/template cards, not image thumbnails.

- [ ] **Step 5: Verify native source test**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeUiTests -v`

Expected: PASS.

## Task 7: End-to-End Smoke, Docs, and Regression

**Files:**
- Modify: `tests/test_xhs_note_replacement.py`
- Modify: docs listed in File Structure

**Interfaces:**
- Consumes all prior task outputs.

- [ ] **Step 1: Add fake 4-image smoke test**

Add a test that builds a template from `files=["01.jpg","02.jpg","03.jpg","04.jpg"]`, supplies cover/product assets, leaves two AI placeholders, builds draft payload, asserts `type=image_note`, `pendingSlots` has two slots, and `image_note_publish_blocker(...) == "xhs_note_ai_image_unconfirmed"`.

- [ ] **Step 2: Run targeted suite**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement -v`

Expected: PASS.

- [ ] **Step 3: Run impacted regression suites**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_api_download_contract tests.test_material_repair tests.test_native_publish tests.test_xhs_note_replacement -v`

Expected: PASS.

- [ ] **Step 4: Compile touched Python files**

Run: `.venv-win\Scripts\python.exe -m py_compile backend\xhs_note_replacement.py backend\api_server.py backend\central_server.py backend\matrix_native_client.py tests\test_xhs_note_replacement.py`

Expected: exit code 0. Existing unrelated warnings are acceptable only if already present before this feature.

- [ ] **Step 5: Update docs**

Update `docs/API_REFERENCE.md`, `docs/openapi.yaml`, `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`, `docs/IMPLEMENTATION.md`, and `CHANGELOG.md`. `IMPLEMENTATION.md` must include exact `src/file.py#Lx-Ly` references after code lands.

- [ ] **Step 6: Final verification**

Run the unittest command from Step 3 and the py_compile command from Step 4 again. Expected: both pass.

## Self-Review

- Spec coverage: covers both entry points, dedicated page, 3 copy candidates, AI placeholders, manual AI confirmation, draft-only material save, 素材发布 `图文` filter, 资产库 `图文模板`, publish gates, observability fields, rollback feature flag, tests, and docs.
- Scope control: excludes real XHS multi-image publishing, batch matrix generation, complex AI layout/editing, and cross-account template permissions.
- Type consistency: uses `type="image_note"`, asset `kind="note_template"`, `aiImageReview.pendingSlots`, `replacementJobId`, `sourceTemplateId`, and `xnr_...` job IDs consistently.
- Placeholder scan: no placeholder markers or open-ended implementation instructions remain.

## Task 8: Native Download Handoff and Source Image Display

**Files:**
- Modify: `backend/matrix_native_client.py`
- Modify: `tests/test_xhs_note_replacement.py`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`

**Interfaces:**
- Produces: `_xhs_note_source_image_headers(url: str, central_base: str = "") -> dict`
- Produces: `_xhs_note_read_limited_response(response, max_bytes: int) -> bytes`
- Produces: `_xhs_note_source_image_entries(material: dict, central_base: str = "") -> list[dict]`
- Produces: `_xhs_note_slot_rows(job: dict, preview: dict) -> list[dict]`
- Extends: `XhsNoteReplacementPage` with an authenticated source-image thumbnail strip and full-image preview.

- [x] **Step 1: Add failing helper and native widget tests**

Test that a material containing JPG/PNG and MP4 files resolves only images, that `xhs_note_replace_start` is received by the page, and that two local source images create two thumbnail controls.

- [x] **Step 2: Run tests and confirm the missing helper/event connection failures**

Run: `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests -v`

Expected: FAIL because `_xhs_note_source_image_entries` and the source-image controls do not exist, and the page is not connected to `BRIDGE.payload`.

- [x] **Step 3: Implement source image resolution and display**

Resolve local files first, then authenticated central `/api/library/file/<materialId>/<filename>` URLs. Keep signed URLs aligned outside template `files`, limit remote loading to four concurrent streams and 20 MB per image, render stable-size thumbnail buttons, open a full-image dialog on activation, and emit structured logs without signed URLs or credentials when loading fails.

- [x] **Step 4: Render template slots before replacement preview**

Use `_xhs_note_slot_rows` so `template.imageSlots` populate the table immediately. Once preview mappings exist, replace the source labels with user-image or AI-placeholder status.

- [x] **Step 5: Reset stale note state and verify**

On a new collection handoff, invalidate earlier template/image/preview/confirm/save responses, capture each action's job ID before background execution, and clear prior source fields, thumbnails, table rows, copy candidates, and replacement image paths before loading the new material.

- [x] **Step 6: Run native smoke, regression tests, and update line references**

Run the focused native display tests, the full XHS note suite, impacted download/native publish suites, and `py_compile`. Update exact `#Lx-Ly` references in `docs/IMPLEMENTATION.md` only after code line numbers are final.

Verification evidence (2026-07-27):
- `XhsNoteNativeDisplayTests`: 14 tests passed, including real collection navigation handoff, local/central thumbnails, full-image activation, signed-URL normalization, streamed size enforcement, external credential isolation, template-slot rendering, and stale action reset.
- Impacted regression command: 99 tests passed.
- `py_compile` passed for `backend/matrix_native_client.py` and `tests/test_xhs_note_replacement.py`.
- Native smoke used downloaded material `e3e0b68c6a364e30bbf05ea256dbc2ec`: 4 source images, 4 thumbnails, and 4 slot rows rendered.
