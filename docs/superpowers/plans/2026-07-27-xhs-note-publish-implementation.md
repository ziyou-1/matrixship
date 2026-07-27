# 小红书图文同款真实多图发布 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build real multi-image Xiaohongshu publishing from the existing “图文同款” draft flow, using the local browser publisher with explicit human confirmation.

**Architecture:** Keep the feature inside the existing local client and local execution engine. The native “图文同款” page saves an `image_note` draft, confirms account/content/images, then calls `/api/publish/run`; the local API validates AI review and confirmation, passes title/body/tags to the XHS Playwright adapter, and writes publish status back to local JSON state.

**Tech Stack:** Python `unittest`, PyQt native client, local HTTP API in `backend/api_server.py`, Playwright sync API in `backend/platform_adapters.py`, OpenAPI 3.1 docs in `docs/openapi.yaml`.

## Global Constraints

- Use browser automation only; do not add Xiaohongshu private publishing APIs.
- Real publish must require human confirmation of account, title, body, tags, and images.
- AI placeholder images must be manually confirmed before dry-run or live publish.
- Single local publish concurrency only; keep using the existing `PUBLISH_LOCK`.
- First version supports one image-note draft at a time and 1-18 images.
- Do not add database tables; update `migration.sql` only if implementation discovers a real DB migration.
- Add or update tests before implementation changes.
- Update API docs, OpenAPI, implementation notes, troubleshooting, and changelog.
- Keep rollback through `XHS_NOTE_PUBLISH_ENABLED=0` plus existing `XHS_NOTE_REPLACEMENT_ENABLED`.

---

## File Structure

- Modify `backend/xhs_note_replacement.py`: publish feature flag, tag normalization, image-note blocker, publish state helper.
- Modify `backend/api_server.py`: parse `publishBody`/`publishTags`/`confirmImageNote`, validate image-note publish, call adapter with body/tags, write publish status back to local library/job.
- Modify `backend/platform_adapters.py`: extend `xhs_publish_material` to upload image-note files and fill title/body/tags.
- Modify `backend/matrix_native_client.py`: add publish controls to `XhsNoteReplacementPage`, load XHS accounts, build publish payload, dry-run/live publish actions.
- Modify `tests/test_xhs_note_replacement.py`: helper and native page source tests.
- Modify `tests/test_native_publish.py`: local publish API source tests.
- Modify docs: `docs/API_REFERENCE.md`, `docs/openapi.yaml`, `docs/IMPLEMENTATION.md`, `docs/TROUBLESHOOTING.md`, `docs/DEPLOYMENT.md`, `CHANGELOG.md`.

---

### Task 1: Publish Gate Helpers

**Files:**
- Modify: `backend/xhs_note_replacement.py`
- Test: `tests/test_xhs_note_replacement.py`

**Interfaces:**
- Produces: `publish_feature_enabled(env: Mapping[str, str] | None = None) -> bool`
- Produces: `normalize_publish_tags(tags) -> list[str]`
- Produces: `image_note_publish_blocker(material: dict) -> str`
- Produces: `apply_publish_result(material: dict, result: dict, account_id: str, dry_run: bool, error_id: str = "") -> dict`
- Consumed by: `backend/api_server.py` publish validation and state writeback.

- [ ] **Step 1: Write the failing helper tests**

Add these tests to `tests/test_xhs_note_replacement.py` inside `XhsNotePublishGateTests`:

```python
    def test_xhs_note_publish_feature_flag_defaults_true(self):
        self.assertTrue(note.publish_feature_enabled({}))
        self.assertFalse(note.publish_feature_enabled({"XHS_NOTE_PUBLISH_ENABLED": "0"}))
        self.assertFalse(note.publish_feature_enabled({"XHS_NOTE_PUBLISH_ENABLED": "false"}))
        self.assertTrue(note.publish_feature_enabled({"XHS_NOTE_PUBLISH_ENABLED": "1"}))

    def test_confirmed_xhs_image_note_is_publishable(self):
        material = {
            "type": "image_note",
            "platform": "xhs",
            "files": ["01.jpg"],
            "aiImageReview": {"pendingSlots": [], "confirmedSlots": [1]},
        }
        self.assertEqual(note.image_note_publish_blocker(material), "")

    def test_xhs_image_note_requires_files_and_platform(self):
        self.assertEqual(
            note.image_note_publish_blocker({"type": "image_note", "platform": "douyin", "files": ["01.jpg"]}),
            "xhs_note_platform_unsupported",
        )
        self.assertEqual(
            note.image_note_publish_blocker({"type": "image_note", "platform": "xhs", "files": []}),
            "no_files",
        )

    def test_normalize_publish_tags_adds_hash_and_deduplicates(self):
        self.assertEqual(
            note.normalize_publish_tags(["本地门店", " #试驾 ", "##本地门店", "", None]),
            ["#本地门店", "#试驾"],
        )

    def test_apply_publish_result_marks_dry_run_without_published(self):
        material = {"id": "mat-1", "type": "image_note", "platform": "xhs", "published": 0, "status": "draft"}
        updated = note.apply_publish_result(
            material,
            {"ok": True, "filled": True, "published": False, "final_url": "https://creator.xiaohongshu.com/publish"},
            account_id="xhs-self",
            dry_run=True,
        )
        self.assertEqual(updated["status"], "draft")
        self.assertEqual(updated["published"], 0)
        self.assertTrue(updated["publishResult"]["dryRun"])

    def test_apply_publish_result_marks_live_publish_success(self):
        material = {"id": "mat-1", "type": "image_note", "platform": "xhs", "published": 0, "status": "draft"}
        updated = note.apply_publish_result(
            material,
            {"ok": True, "filled": True, "published": True, "final_url": "https://creator.xiaohongshu.com/publish"},
            account_id="xhs-self",
            dry_run=False,
        )
        self.assertEqual(updated["status"], "published")
        self.assertEqual(updated["published"], 1)
        self.assertEqual(updated["publishResult"]["accountId"], "xhs-self")
```

Replace the old V1 blocker test body:

```python
    def test_image_note_publish_is_blocked_in_v1_even_when_ai_confirmed(self):
        material = {"type": "image_note", "aiImageReview": {"pendingSlots": [], "confirmedSlots": [1]}}
        self.assertEqual(note.image_note_publish_blocker(material), "xhs_note_publish_not_supported")
```

with:

```python
    def test_image_note_publish_no_longer_returns_v1_not_supported(self):
        material = {
            "type": "image_note",
            "platform": "xhs",
            "files": ["01.jpg"],
            "aiImageReview": {"pendingSlots": [], "confirmedSlots": [1]},
        }
        self.assertNotEqual(note.image_note_publish_blocker(material), "xhs_note_publish_not_supported")
```

- [ ] **Step 2: Run the failing tests**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNotePublishGateTests -v
```

Expected: fails because `publish_feature_enabled`, `normalize_publish_tags`, `apply_publish_result`, and the new blocker behavior are not implemented.

- [ ] **Step 3: Implement helper functions**

In `backend/xhs_note_replacement.py`, add `PUBLISH_FEATURE_ENV` near the existing feature flag constants and implement these helpers:

```python
PUBLISH_FEATURE_ENV = "XHS_NOTE_PUBLISH_ENABLED"


def publish_feature_enabled(env: Optional[dict] = None) -> bool:
    env = os.environ if env is None else env
    return str(env.get(PUBLISH_FEATURE_ENV, "1")).strip().lower() not in ("0", "false", "no", "off")


def normalize_publish_tags(tags) -> list[str]:
    if isinstance(tags, str):
        raw = re.split(r"[,，\s]+", tags)
    elif isinstance(tags, (list, tuple, set)):
        raw = list(tags)
    else:
        raw = []
    out = []
    seen = set()
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        text = re.sub(r"^#+", "", text).strip()
        text = re.sub(r"\s+", "", text)
        if not text:
            continue
        tag = "#" + text
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def image_note_publish_blocker(material: dict) -> str:
    material = material or {}
    if material.get("type") != "image_note":
        return ""
    if str(material.get("platform") or "").strip().lower() != "xhs":
        return "xhs_note_platform_unsupported"
    if not (material.get("files") or []):
        return "no_files"
    review = material.get("aiImageReview") or {}
    if review.get("pendingSlots"):
        return "xhs_note_ai_image_unconfirmed"
    return ""


def apply_publish_result(material: dict, result: dict, account_id: str, dry_run: bool, error_id: str = "") -> dict:
    material = dict(material or {})
    result = result or {}
    now_ts = time.time()
    publish_record = {
        "platform": "xhs",
        "accountId": account_id or "",
        "dryRun": bool(dry_run),
        "finalUrl": result.get("final_url") or result.get("finalUrl") or "",
        "error": result.get("error") or "",
        "filled": bool(result.get("filled")),
        "published": bool(result.get("published")),
        "updatedAt": now_ts,
    }
    if error_id:
        publish_record["errorId"] = error_id
    material["publishResult"] = publish_record
    if result.get("published") and not dry_run:
        material["status"] = "published"
        material["published"] = 1
        material["publishedAt"] = now_ts
    elif result.get("ok") or result.get("filled"):
        material["status"] = material.get("status") or "draft"
        material["published"] = int(material.get("published") or 0)
    else:
        material["status"] = "publish_failed"
        material["published"] = int(material.get("published") or 0)
        material["publishError"] = {
            "error": result.get("error") or "publish_failed",
            "errorId": error_id or result.get("errorId") or "",
            "stage": "xhs_publish",
        }
    return material
```

Ensure `backend/xhs_note_replacement.py` imports `re` and `time` if not already present.

- [ ] **Step 4: Run the helper tests**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNotePublishGateTests tests.test_xhs_note_replacement.XhsNoteFourImageSmokeTests -v
```

Expected: all listed tests pass; the four-image smoke still blocks only when AI slots are pending.

- [ ] **Step 5: Commit**

```powershell
git add backend\xhs_note_replacement.py tests\test_xhs_note_replacement.py
git commit -m "feat: allow confirmed xhs image notes through publish gate"
```

---

### Task 2: Local Publish API Contract

**Files:**
- Modify: `backend/api_server.py`
- Test: `tests/test_native_publish.py`

**Interfaces:**
- Consumes: `xhs_note_replacement.publish_feature_enabled`
- Consumes: `xhs_note_replacement.normalize_publish_tags`
- Consumes: `xhs_note_replacement.image_note_publish_blocker`
- Consumes: `xhs_note_replacement.apply_publish_result`
- Produces: extended `run_publish(material, account_id, dry_run, title_override=None, platform=None, body_override=None, tags_override=None)`
- Produces: `/api/publish/run` support for `publishBody`, `publishTags`, `confirmImageNote`.

- [ ] **Step 1: Write failing API source tests**

Add these tests to `tests/test_native_publish.py`:

```python
    def test_local_publish_api_accepts_xhs_image_note_body_tags_and_confirmation(self):
        src = API_SERVER.read_text(encoding="utf-8")
        start = src.index("if path == '/api/publish/run':")
        end = src.index("return json_response(self, {'ok': False, 'error': 'not_found'", start)
        publish_run_src = src[start:end]

        self.assertIn("publish_body = str(body.get('publishBody')", publish_run_src)
        self.assertIn("publish_tags = xhs_note_replacement.normalize_publish_tags", publish_run_src)
        self.assertIn("confirm_image_note = bool_arg(body.get('confirmImageNote'), False)", publish_run_src)
        self.assertIn("xhs_note_manual_confirm_required", publish_run_src)
        self.assertIn("body_override=publish_body", publish_run_src)
        self.assertIn("tags_override=publish_tags", publish_run_src)

    def test_run_publish_passes_xhs_body_and_tags_to_adapter(self):
        src = API_SERVER.read_text(encoding="utf-8")
        start = src.index("def run_publish(")
        end = src.index("def run_queue_item", start)
        run_publish_src = src[start:end]

        self.assertIn("body_override=None", run_publish_src)
        self.assertIn("tags_override=None", run_publish_src)
        self.assertIn("xhs_publish_material(files, publish_title, material.get('type', 'video'), dry_run=dry_run, data_dir=DATA_DIR, body=publish_body, tags=publish_tags)", run_publish_src)

    def test_local_publish_api_updates_image_note_publish_state(self):
        src = API_SERVER.read_text(encoding="utf-8")
        start = src.index("if path == '/api/publish/run':")
        end = src.index("return json_response(self, {'ok': False, 'error': 'not_found'", start)
        publish_run_src = src[start:end]

        self.assertIn("apply_publish_result", publish_run_src)
        self.assertIn("save_library(lib)", publish_run_src)
        self.assertIn("xhs_note_publish_state_saved", publish_run_src)
```

Update the existing `test_local_publish_api_accepts_platform_override` expected call string to include `body_override` and `tags_override`.

- [ ] **Step 2: Run the failing API tests**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_native_publish.NativePublishTest.test_local_publish_api_accepts_xhs_image_note_body_tags_and_confirmation tests.test_native_publish.NativePublishTest.test_run_publish_passes_xhs_body_and_tags_to_adapter tests.test_native_publish.NativePublishTest.test_local_publish_api_updates_image_note_publish_state -v
```

Expected: fails because the API still only accepts title/platform/dry-run.

- [ ] **Step 3: Extend `run_publish`**

Change the signature and XHS call in `backend/api_server.py`:

```python
def run_publish(material, account_id, dry_run, title_override=None, platform=None, body_override=None, tags_override=None):
    """同步执行一次发布（持锁）。返回 publish_util 的结果 dict。"""
    files = material_files(material)
    if not files:
        return {'ok': False, 'error': 'no_files'}
    publish_platform = platform_code(platform or material.get('platform') or ('xhs' if 'xhs' in str(account_id or '').lower() else 'douyin'))
    if not PUBLISH_LOCK.acquire(timeout=2):
        return {'ok': False, 'error': 'publish_busy'}
    try:
        publish_title = material.get('title', '') if title_override is None else str(title_override)
        publish_body = material.get('body', '') if body_override is None else str(body_override)
        publish_tags = xhs_note_replacement.normalize_publish_tags(
            material.get('tags', []) if tags_override is None else tags_override
        )
        if publish_platform == 'xhs':
            res = xhs_publish_material(files, publish_title, material.get('type', 'video'), dry_run=dry_run, data_dir=DATA_DIR, body=publish_body, tags=publish_tags)
        else:
            ...
```

Do not change the existing Douyin branch except for preserving its current behavior.

- [ ] **Step 4: Extend `/api/publish/run` validation**

Inside the `if path == '/api/publish/run':` block, after `publish_title`, add:

```python
                publish_body = str(body.get('publishBody') if body.get('publishBody') is not None else m.get('body', '')).strip()
                publish_tags = xhs_note_replacement.normalize_publish_tags(body.get('publishTags') if body.get('publishTags') is not None else m.get('tags', []))
                confirm_image_note = bool_arg(body.get('confirmImageNote'), False)
                if publish_platform == 'xhs' and m.get('type') == 'image_note':
                    if not xhs_note_replacement.publish_feature_enabled():
                        return json_response(self, {'ok': False, 'error': 'feature_disabled'}, 404)
                    blocker = xhs_note_replacement.image_note_publish_blocker(m)
                    if blocker:
                        raw_log = json_log(logger, 'xhs_note_publish_preflight_blocked', endpoint=path, materialId=material_id, accountId=account_id, error=blocker)
                        return json_response(self, {'ok': False, 'error': blocker, 'errorId': (json.loads(raw_log) or {}).get('errorId'), 'stage': 'publish_preflight'}, 400)
                    if len(m.get('files') or []) > 18:
                        return json_response(self, {'ok': False, 'error': 'xhs_note_too_many_images', 'stage': 'publish_preflight'}, 400)
                    if not dry and not confirm_image_note:
                        return json_response(self, {'ok': False, 'error': 'xhs_note_manual_confirm_required', 'stage': 'publish_preflight'}, 400)
```

Then call:

```python
                res = run_publish(m, account_id, dry_run=dry, title_override=publish_title, platform=publish_platform, body_override=publish_body, tags_override=publish_tags)
```

After handling `publish_busy`, write back image-note state:

```python
                if publish_platform == 'xhs' and m.get('type') == 'image_note':
                    updated = xhs_note_replacement.apply_publish_result(m, res, account_id, dry)
                    with STATE_LOCK:
                        lib = load_library()
                        lib = [updated if item.get('id') == material_id else item for item in lib]
                        save_library(lib)
                    json_log(logger, 'xhs_note_publish_state_saved', level='info', endpoint=path, materialId=material_id, accountId=account_id, dryRun=dry, published=bool(res.get('published')))
```

Keep response keys backward compatible: `ok`, `filled`, `published`, `dryRun`, `error`, `finalUrl`, `steps`, `shot`.

- [ ] **Step 5: Run API tests**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v
```

Expected: all native publish tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend\api_server.py tests\test_native_publish.py
git commit -m "feat: extend local publish API for xhs image notes"
```

---

### Task 3: XHS Browser Publisher Body And Tags

**Files:**
- Modify: `backend/platform_adapters.py`
- Test: `tests/test_native_publish.py`

**Interfaces:**
- Consumes: `xhs_publish_material(files, title, material_type="video", dry_run=True, data_dir="", body="", tags=None)`
- Produces: dry-run result with `filled=True`, `published=False`, `platform="xhs"`.
- Produces: live result with `published=True` only after click attempt succeeds.

- [ ] **Step 1: Write failing adapter source test**

Add this test to `tests/test_native_publish.py`:

```python
    def test_xhs_publish_adapter_accepts_body_tags_and_preserves_multi_image_order(self):
        adapter = (ROOT / "backend" / "platform_adapters.py").read_text(encoding="utf-8")
        start = adapter.index("def xhs_publish_material(")
        end = adapter.index("def ", start + 1) if "def " in adapter[start + 1:] else len(adapter)
        publish_src = adapter[start:end]

        self.assertIn('body=""', publish_src)
        self.assertIn("tags=None", publish_src)
        self.assertIn("full_body", publish_src)
        self.assertIn("set_input_files(files)", publish_src)
        self.assertIn("publish_body", publish_src)
        self.assertIn("publish_tags", publish_src)
        self.assertIn("xhs_publish_body_fill_failed", publish_src)
```

- [ ] **Step 2: Run the failing adapter test**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_native_publish.NativePublishTest.test_xhs_publish_adapter_accepts_body_tags_and_preserves_multi_image_order -v
```

Expected: fails because `xhs_publish_material` does not accept `body` or `tags`.

- [ ] **Step 3: Extend the adapter signature and body construction**

In `backend/platform_adapters.py`, change the function signature:

```python
def xhs_publish_material(files, title, material_type="video", dry_run=True, data_dir="", body="", tags=None):
```

At the top of the function after title normalization:

```python
    publish_body = compact_text(body or "", 4000)
    publish_tags = []
    for tag in tags or []:
        t = str(tag or "").strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t.lstrip("#").strip()
        if t and t not in publish_tags:
            publish_tags.append(t)
    tag_text = " ".join(publish_tags)
    full_body = (publish_body + ("\n\n" + tag_text if tag_text else "")).strip()
```

- [ ] **Step 4: Fill title, body, and tags in the browser**

Keep the existing upload logic. Replace the broad first `page.evaluate` fill block with a two-field fill block that receives both `title` and `full_body`:

```python
            fill_result = page.evaluate(
                """({title, full_body}) => {
                  const visible = el => {
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 20 && r.height > 12 && st.display !== 'none' && st.visibility !== 'hidden';
                  };
                  const textOf = el => String(el.value || el.innerText || el.textContent || '').trim();
                  const setText = (el, text) => {
                    el.focus();
                    if (el.isContentEditable) {
                      document.execCommand('selectAll', false, null);
                      document.execCommand('insertText', false, text);
                    } else {
                      const tag = (el.tagName || '').toUpperCase();
                      const proto = tag === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                      if (desc && desc.set) desc.set.call(el, text); else el.value = text;
                      el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:text}));
                      el.dispatchEvent(new Event('change', {bubbles:true}));
                    }
                  };
                  const boxes = Array.from(document.querySelectorAll('textarea,input:not([type=file]):not([type=hidden]),[contenteditable=true],[role=textbox]')).filter(visible);
                  let titleFilled = false;
                  let bodyFilled = !full_body;
                  for (const el of boxes.slice(0, 12)) {
                    const hint = ((el.placeholder || el.getAttribute('aria-label') || el.getAttribute('title') || '') + ' ' + (el.className || '')).toString();
                    if (!titleFilled && /标题|title/i.test(hint)) {
                      setText(el, title);
                      titleFilled = true;
                      continue;
                    }
                    if (!bodyFilled && /正文|描述|内容|说点什么|添加正文|caption|description/i.test(hint)) {
                      setText(el, full_body);
                      bodyFilled = true;
                    }
                  }
                  if (!titleFilled && boxes[0]) {
                    setText(boxes[0], title);
                    titleFilled = true;
                  }
                  if (!bodyFilled && boxes[1]) {
                    setText(boxes[1], full_body);
                    bodyFilled = true;
                  }
                  return {titleFilled, bodyFilled};
                }""",
                {"title": title, "full_body": full_body},
            )
            if full_body and not bool((fill_result or {}).get("bodyFilled")):
                return {"ok": False, "filled": False, "published": False, "error": "xhs_publish_body_fill_failed", "platform": "xhs", "final_url": page.url}
```

Keep the existing title fallback blocks after this if they still help; make sure they do not overwrite the正文 with title.

- [ ] **Step 5: Run adapter source test**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_native_publish.NativePublishTest.test_xhs_publish_adapter_accepts_body_tags_and_preserves_multi_image_order -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add backend\platform_adapters.py tests\test_native_publish.py
git commit -m "feat: fill xhs image note body and tags"
```

---

### Task 4: Native 图文同款 Publish Controls

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_xhs_note_replacement.py`

**Interfaces:**
- Consumes: local `/api/accounts`
- Consumes: local `/api/publish/run`
- Consumes: saved draft material id from `/api/xhs-note-replacement/save-draft`
- Produces: `XhsNoteReplacementPage.load_publish_accounts()`
- Produces: `XhsNoteReplacementPage.publish_to_xhs(dry_run: bool)`
- Produces: source-visible strings `试填到小红书`, `正式发布`, `confirmImageNote`, `publishBody`, `publishTags`.

- [ ] **Step 1: Write failing native source tests**

Add these tests to `XhsNoteNativeUiTests` in `tests/test_xhs_note_replacement.py`:

```python
    def test_native_note_replacement_has_xhs_publish_controls(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, "backend", "matrix_native_client.py"), encoding="utf-8") as f:
            src = f.read()
        start = src.index("class XhsNoteReplacementPage")
        end = src.index("class VideoReplacementPage", start)
        page_src = src[start:end]

        self.assertIn("self.publish_account = QtWidgets.QComboBox()", page_src)
        self.assertIn('QtWidgets.QPushButton("试填到小红书")', page_src)
        self.assertIn('QtWidgets.QPushButton("正式发布")', page_src)
        self.assertIn("def load_publish_accounts(self):", page_src)
        self.assertIn("def publish_to_xhs(self, dry_run):", page_src)
        self.assertIn('"publishBody": publish_body', page_src)
        self.assertIn('"publishTags": publish_tags', page_src)
        self.assertIn('"confirmImageNote": True', page_src)

    def test_native_note_replacement_blocks_publish_before_ai_confirmation(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, "backend", "matrix_native_client.py"), encoding="utf-8") as f:
            src = f.read()
        start = src.index("class XhsNoteReplacementPage")
        end = src.index("class VideoReplacementPage", start)
        page_src = src[start:end]

        self.assertIn("AI 占位图未确认，请先确认后再发布", page_src)
        self.assertIn("未找到已登录的小红书账号，请先到账号矩阵登录", page_src)
        self.assertIn("请先保存草稿", page_src)
```

- [ ] **Step 2: Run failing native UI tests**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeUiTests -v
```

Expected: the new tests fail because publish controls are not present.

- [ ] **Step 3: Add state and controls**

In `XhsNoteReplacementPage.__init__`, add:

```python
        self._draft_material = {}
        self._publish_accounts = []
```

After the existing draft controls, add a publish card:

```python
        publish_card = QtWidgets.QFrame()
        publish_card.setObjectName("card")
        pl = QtWidgets.QGridLayout(publish_card)
        pl.setContentsMargins(16, 14, 16, 14)
        pl.setHorizontalSpacing(12)
        pl.setVerticalSpacing(10)
        self.publish_account = QtWidgets.QComboBox()
        self.publish_account.setMinimumWidth(260)
        self.b_publish_accounts = QtWidgets.QPushButton("刷新账号")
        self.b_publish_accounts.setObjectName("ghost")
        self.b_publish_accounts.clicked.connect(self.load_publish_accounts)
        self.b_publish_dry = QtWidgets.QPushButton("试填到小红书")
        self.b_publish_dry.setObjectName("ghost")
        self.b_publish_dry.clicked.connect(lambda: self.publish_to_xhs(True))
        self.b_publish_live = QtWidgets.QPushButton("正式发布")
        self.b_publish_live.setObjectName("primary")
        self.b_publish_live.clicked.connect(lambda: self.publish_to_xhs(False))
        pl.addWidget(QtWidgets.QLabel("小红书账号"), 0, 0)
        pl.addWidget(self.publish_account, 0, 1)
        pl.addWidget(self.b_publish_accounts, 0, 2)
        pl.addWidget(self.b_publish_dry, 1, 1)
        pl.addWidget(self.b_publish_live, 1, 2)
        self.v.addWidget(publish_card)
```

- [ ] **Step 4: Add account loading**

Add methods inside `XhsNoteReplacementPage`:

```python
    def load_publish_accounts(self):
        self.publish_account.clear()
        self.publish_account.addItem("正在读取小红书账号…")

        def work():
            code, data = self._local_api("GET", "/api/accounts", None, 30)
            rows = data if isinstance(data, list) else ((data or {}).get("value") or (data or {}).get("accounts") or [])
            accounts = clean_accounts(rows if isinstance(rows, list) else [], platform="xhs", ready_only=True)
            BRIDGE.payload.emit("xhs_note_replace", {"action": "publish_accounts", "code": code, "accounts": accounts})
        run_bg(work)

    def _refresh_publish_account_box(self, accounts):
        self._publish_accounts = accounts if isinstance(accounts, list) else []
        self.publish_account.clear()
        if not self._publish_accounts:
            self.publish_account.addItem("未找到已登录的小红书账号，请先到账号矩阵登录")
            return
        for account in self._publish_accounts:
            self.publish_account.addItem(account.get("name") or account.get("handle") or account.get("id") or "小红书账号")
```

Call `self.load_publish_accounts()` from `on_show()` if this page has one; otherwise add:

```python
    def on_show(self):
        self.load_publish_accounts()
```

- [ ] **Step 5: Add publish payload and action**

Add:

```python
    def _selected_copy_for_publish(self):
        copies = (self._job or {}).get("copyCandidates") or []
        idx = int((self._job or {}).get("selectedCopyIndex") or 0)
        return copies[idx] if 0 <= idx < len(copies) else {}

    def _publish_tags_for_selected_copy(self):
        tags = self._selected_copy_for_publish().get("tags") or []
        return [str(x).strip() for x in tags if str(x).strip()]

    def _has_unconfirmed_ai_slots(self):
        for mapping in (self._job or {}).get("slotMappings") or []:
            if mapping.get("source") == "ai_placeholder" and mapping.get("confirmationStatus") != "confirmed":
                return True
        return False

    def publish_to_xhs(self, dry_run):
        material = self._draft_material or {}
        material_id = material.get("id") or (self._job or {}).get("publishDraftMaterialId") or ""
        if not material_id:
            self.status.setText("请先保存草稿，再发布到小红书")
            return
        if self._has_unconfirmed_ai_slots():
            self.status.setText("AI 占位图未确认，请先确认后再发布")
            return
        if self.publish_account.currentIndex() < 0 or not self._publish_accounts:
            self.status.setText("未找到已登录的小红书账号，请先到账号矩阵登录")
            return
        account = self._publish_accounts[self.publish_account.currentIndex()]
        account_id = account.get("id") or "xhs-self"
        copy = self._selected_copy_for_publish()
        publish_title = str(copy.get("title") or material.get("title") or self.source_title.text().strip() or "图文同款草稿").strip()
        publish_body = str(copy.get("body") or material.get("body") or self.source_body.toPlainText().strip()).strip()
        publish_tags = self._publish_tags_for_selected_copy() or material.get("tags") or []
        if not dry_run:
            image_count = len(material.get("files") or [])
            detail = "账号：%s\n标题：%s\n正文：%s\n标签：%s\n图片：%d 张\n\n确认正式发布到小红书？" % (
                account.get("name") or account_id,
                publish_title[:80],
                publish_body[:160],
                " ".join(publish_tags),
                image_count,
            )
            confirm = QtWidgets.QMessageBox.question(
                self, "正式发布确认", detail,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if confirm != QtWidgets.QMessageBox.Yes:
                return
        payload = {
            "accountId": account_id,
            "materialId": material_id,
            "platform": "xhs",
            "dryRun": bool(dry_run),
            "publishTitle": publish_title,
            "publishBody": publish_body,
            "publishTags": publish_tags,
            "confirmImageNote": True,
        }
        self.status.setText("正在试填到小红书…" if dry_run else "正在正式发布到小红书…")

        def work():
            code, data = self._local_api("POST", "/api/publish/run", payload, 180 if dry_run else 240)
            BRIDGE.payload.emit("xhs_note_replace", {"action": "publish", "dryRun": bool(dry_run), "code": code, "data": data})
        run_bg(work)
```

- [ ] **Step 6: Handle save/accounts/publish events**

In `_on`, add:

```python
        if payload.get("action") == "publish_accounts":
            self._refresh_publish_account_box(payload.get("accounts") or [])
            return
```

When `action == "save"`, store:

```python
            self._draft_material = body.get("material") or {}
```

When `action == "publish"`, before the generic success message:

```python
        if action == "publish":
            if body.get("published"):
                self.status.setText("小红书正式发布已提交。")
            elif body.get("filled"):
                self.status.setText("试填完成：已上传图片并填写内容，请在浏览器中核对。")
            else:
                self.status.setText("小红书发布未完成：%s" % self._xhs_note_error_text(body.get("error") or "publish_failed"))
            return
```

Also map new errors in `_xhs_note_error_text`:

```python
        if error == "xhs_note_ai_image_unconfirmed":
            return "AI 占位图未确认，请先确认后再发布"
        if error == "xhs_note_manual_confirm_required":
            return "请先在发布确认中确认账号、标题、正文、标签和图片"
        if error == "xhs_note_too_many_images":
            return "小红书图文最多处理 18 张，请删减后重试"
```

- [ ] **Step 7: Run native UI tests**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeUiTests tests.test_xhs_note_replacement.XhsNoteNativeFlowTests -v
```

Expected: pass.

- [ ] **Step 8: Commit**

```powershell
git add backend\matrix_native_client.py tests\test_xhs_note_replacement.py
git commit -m "feat: add xhs note publish controls"
```

---

### Task 5: Documentation And API Reference

**Files:**
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/openapi.yaml`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Documents: `/api/publish/run` request fields `publishBody`, `publishTags`, `confirmImageNote`.
- Documents: `XHS_NOTE_PUBLISH_ENABLED`.
- Documents: rollback files and troubleshooting errors.

- [ ] **Step 1: Write docs contract checks**

Add these source-level tests to `tests/test_native_publish.py`:

```python
    def test_docs_describe_xhs_image_note_publish_contract(self):
        api_ref = (ROOT / "docs" / "API_REFERENCE.md").read_text(encoding="utf-8")
        openapi = (ROOT / "docs" / "openapi.yaml").read_text(encoding="utf-8")
        deploy = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")

        self.assertIn("publishBody", api_ref)
        self.assertIn("publishTags", api_ref)
        self.assertIn("confirmImageNote", api_ref)
        self.assertIn("XHS_NOTE_PUBLISH_ENABLED", deploy)
        self.assertIn("publishBody", openapi)
        self.assertIn("publishTags", openapi)
        self.assertIn("confirmImageNote", openapi)
```

- [ ] **Step 2: Run failing docs test**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_native_publish.NativePublishTest.test_docs_describe_xhs_image_note_publish_contract -v
```

Expected: fails until docs are updated.

- [ ] **Step 3: Update API docs**

In `docs/API_REFERENCE.md`, update `POST /api/publish/run` request example to:

```json
{
  "materialId": "material-id",
  "accountId": "xhs-self",
  "platform": "xhs",
  "dryRun": false,
  "publishTitle": "标题",
  "publishBody": "正文",
  "publishTags": ["#标签1", "#标签2"],
  "confirmImageNote": true
}
```

Add field notes:

- `publishBody`: optional; for XHS image notes, overrides material `body`.
- `publishTags`: optional array/string; normalized to `#标签` and appended to body if the creator tag control is unavailable.
- `confirmImageNote`: required for live `image_note` publish; dry-run can omit it.
- `xhs_note_ai_image_unconfirmed`: AI placeholders remain pending.
- `xhs_note_manual_confirm_required`: live image-note publish was requested without explicit confirmation.

- [ ] **Step 4: Update OpenAPI**

In `docs/openapi.yaml`, under `/api/publish/run` request properties, add:

```yaml
                publishBody:
                  type: string
                  description: Body override for Xiaohongshu image-note publishing. When omitted, the material body is used.
                publishTags:
                  oneOf:
                    - type: array
                      items: {type: string}
                    - type: string
                  description: Tags for Xiaohongshu image notes. Values are normalized to #tag form.
                confirmImageNote:
                  type: boolean
                  default: false
                  description: Required for live Xiaohongshu image-note publishing after the user confirms account, title, body, tags, and images.
```

- [ ] **Step 5: Update deployment and troubleshooting**

In `docs/DEPLOYMENT.md`, add `XHS_NOTE_PUBLISH_ENABLED` beside the existing image-note replacement flag:

```markdown
| `XHS_NOTE_PUBLISH_ENABLED` | `1` | Controls real Xiaohongshu image-note publish from the 图文同款 page. Set to `0/false/no/off` to keep draft generation but disable real publishing. |
```

In `docs/TROUBLESHOOTING.md`, add:

```markdown
## 小红书图文同款真实发布排障（2026-07-27）

- `xhs_note_ai_image_unconfirmed`: 先在图文同款页确认所有 AI 占位图，再试填或正式发布。
- `xhs_note_manual_confirm_required`: 正式发布必须经过页面二次确认，不能直接从接口绕过。
- `xhs_note_too_many_images`: 第一版最多处理 18 张图片，删减后重试。
- `upload_input_not_found`: 小红书创作台没有出现上传控件，先到账号矩阵重新登录小红书账号。
- 回滚：设置 `XHS_NOTE_PUBLISH_ENABLED=0` 并重启本地客户端；草稿保留，可继续保存但不会真实发布。
```

- [ ] **Step 6: Update implementation notes and changelog**

In `docs/IMPLEMENTATION.md`, add a new dated section after implementation is complete. First compute the real line spans with:

```powershell
rg -n "publish_feature_enabled|normalize_publish_tags|apply_publish_result|def image_note_publish_blocker" backend\xhs_note_replacement.py
rg -n "def run_publish|publishBody|confirmImageNote|xhs_note_publish_state_saved" backend\api_server.py
rg -n "def xhs_publish_material|full_body|xhs_publish_body_fill_failed" backend\platform_adapters.py
rg -n "publish_to_xhs|load_publish_accounts|试填到小红书|正式发布" backend\matrix_native_client.py
rg -n "test_xhs_note_publish_feature_flag_defaults_true|test_native_note_replacement_has_xhs_publish_controls" tests\test_xhs_note_replacement.py
rg -n "test_local_publish_api_accepts_xhs_image_note_body_tags_and_confirmation|test_docs_describe_xhs_image_note_publish_contract" tests\test_native_publish.py
```

Then write bullets using the actual `path#Lstart-Lend` spans printed by the commands. Include the exact verification commands that were run and their pass/fail result. Do not commit `docs/IMPLEMENTATION.md` until every line reference points to a real line span.

In `CHANGELOG.md`, add:

```markdown
## 2026-07-27

- 小红书图文同款草稿支持通过本机浏览器进行多图试填和人工确认后的正式发布。
- `/api/publish/run` 增加 `publishBody`、`publishTags`、`confirmImageNote`，并保留 AI 占位图未确认门禁。
- 新增 `XHS_NOTE_PUBLISH_ENABLED` 回滚开关。
```

- [ ] **Step 7: Run docs tests**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_native_publish.NativePublishTest.test_docs_describe_xhs_image_note_publish_contract -v
```

Expected: pass.

- [ ] **Step 8: Commit**

```powershell
git add docs\API_REFERENCE.md docs\openapi.yaml docs\DEPLOYMENT.md docs\TROUBLESHOOTING.md docs\IMPLEMENTATION.md CHANGELOG.md tests\test_native_publish.py
git commit -m "docs: document xhs image note publish"
```

---

### Task 6: Final Verification

**Files:**
- Read/verify only unless failures require fixes.

**Interfaces:**
- Verifies all previous tasks together.
- Produces final pass/fail report.

- [ ] **Step 1: Run focused unit tests**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement tests.test_native_publish -v
```

Expected: all tests pass.

- [ ] **Step 2: Run existing publish/download regression set**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_api_download_contract tests.test_material_repair tests.test_native_publish tests.test_xhs_note_replacement -v
```

Expected: all tests pass.

- [ ] **Step 3: Run syntax checks**

Run:

```powershell
.venv-win\Scripts\python.exe -m py_compile backend\xhs_note_replacement.py backend\api_server.py backend\platform_adapters.py backend\matrix_native_client.py tests\test_xhs_note_replacement.py tests\test_native_publish.py
```

Expected: exit code 0.

- [ ] **Step 4: Inspect docs line refs**

Run:

```powershell
rg -n "L[x]-L[y]|T[O]DO|T[B]D|待[定]" docs\IMPLEMENTATION.md docs\API_REFERENCE.md docs\DEPLOYMENT.md docs\TROUBLESHOOTING.md CHANGELOG.md
```

Expected: no placeholder line refs or placeholder markers remain.

- [ ] **Step 5: Check staged diff**

Run:

```powershell
git status --short
git diff --stat HEAD
```

Expected: only intended files from this plan are changed.

- [ ] **Step 6: Final commit if fixes were needed**

If Task 6 required any fixes, commit them:

```powershell
git add backend\xhs_note_replacement.py backend\api_server.py backend\platform_adapters.py backend\matrix_native_client.py tests\test_xhs_note_replacement.py tests\test_native_publish.py docs\API_REFERENCE.md docs\openapi.yaml docs\DEPLOYMENT.md docs\TROUBLESHOOTING.md docs\IMPLEMENTATION.md CHANGELOG.md
git commit -m "test: verify xhs image note publishing"
```

If no fixes were needed after Task 5, do not create an empty commit.

---

## Self-Review

- Spec coverage: covered page entry, browser mode, human confirmation, AI image gate, body/tags API, publish state writeback, observability, rollback, tests, docs, and first-version exclusions.
- Placeholder scan: plan avoids unresolved implementation placeholders and requires real line references before documentation is committed.
- Type consistency: `publishBody`, `publishTags`, `confirmImageNote`, `body_override`, `tags_override`, `publish_feature_enabled`, `normalize_publish_tags`, and `apply_publish_result` are consistently named across tasks.


