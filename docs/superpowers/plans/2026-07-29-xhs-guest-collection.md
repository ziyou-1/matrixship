# XHS Guest Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Xiaohongshu collection default to guest browsing, and require one-time user confirmation before any collection action uses a logged-in account.

**Architecture:** Add explicit `guestMode` and `accountCollectionConfirmed` request fields to XHS collection paths. Platform adapters choose an ephemeral browser context for guest collection and persistent `xhs_profile` only after confirmation. Native UI sends guest requests by default and retries once with account confirmation only after a user dialog.

**Tech Stack:** Python 3.12, stdlib `unittest`, Playwright sync API, PyQt native client, existing JSON structured logging.

## Global Constraints

- Default XHS collection must use guest mode for search, download, note-replacement download, comment reading, and finder discovery.
- Guest mode must not call `xhs_profile_ready()` and must not read `xhs_profile`, `xhs_auth_state.json`, or login cookies.
- Account collection must require `guestMode=false` and `accountCollectionConfirmed=true`.
- Account collection must still run XHS safety preflight and state recording.
- Comment publishing, private messaging, and material publishing remain logged-in account actions.
- Do not add a database migration. No new public route is required.
- Logs must be structured and redacted; do not log full cookies, tokens, full note body, or full search URL query strings.
- Rollback switch: `XHS_GUEST_COLLECTION_DEFAULT=0` restores legacy collection default after local client and local engine restart.

---

## File Map

- Modify `backend/platform_adapters.py`: add `guest_mode` parameters, guest-login-wall classification, and structured guest block logging.
- Modify `backend/api_server.py`: parse request flags, enforce confirmed account collection, pass guest mode to adapters, and preserve XHS safety gates.
- Modify `backend/matrix_native_client.py`: send `guestMode=true` by default, show one-time confirmation dialogs, retry confirmed account collection, and update user-facing status text.
- Modify tests:
  - `tests/test_xhs_lead_filtering.py`
  - `tests/test_api_download_contract.py`
  - `tests/test_xhs_safety_mode.py`
  - `tests/test_native_publish.py`
- Modify docs:
  - `CHANGELOG.md`
  - `docs/IMPLEMENTATION.md`
  - `docs/TROUBLESHOOTING.md`
  - `docs/DEPLOYMENT.md`
  - `docs/API_REFERENCE.md` if local API request fields are documented there.

---

### Task 1: Adapter Guest Mode Contract

**Files:**
- Modify: `tests/test_xhs_lead_filtering.py`
- Modify: `backend/platform_adapters.py`

**Interfaces:**
- Produces: `xhs_search_notes(keyword, limit=10, data_dir="", guest_mode=True)`
- Produces: `xhs_get_comments(note_url, limit=120, data_dir="", source=None, guest_mode=True)`
- Produces: `xhs_download_note(note_url, base_dir, data_dir="", max_files=20, guest_mode=True)`
- Produces: `discover_xhs_leads_by_keyword(keyword, video_num=5, comment_mode="page", data_dir="", guest_mode=True)`
- Produces: `xhs_guest_collection_default(env=os.environ) -> bool`
- Produces: `xhs_guest_collection_block_error(result, action) -> dict`

- [ ] **Step 1: Write failing adapter tests**

Add tests that assert the source code exposes the new parameters and avoids `xhs_profile_ready()` when guest mode is enabled:

```python
def test_xhs_collection_functions_accept_guest_mode(self):
    src = Path("backend/platform_adapters.py").read_text(encoding="utf-8-sig")
    self.assertIn('def xhs_search_notes(keyword, limit=10, data_dir="", guest_mode=True):', src)
    self.assertIn('def xhs_get_comments(note_url, limit=120, data_dir="", source=None, guest_mode=True):', src)
    self.assertIn('def xhs_download_note(note_url, base_dir, data_dir="", max_files=20, guest_mode=True):', src)
    self.assertIn('def discover_xhs_leads_by_keyword(keyword, video_num=5, comment_mode="page", data_dir="", guest_mode=True):', src)

def test_xhs_guest_mode_does_not_use_profile_ready_for_collection(self):
    src = Path("backend/platform_adapters.py").read_text(encoding="utf-8-sig")
    search_src = src[src.index("def xhs_search_notes("):src.index("def xhs_strict_lead_filter_enabled", src.index("def xhs_search_notes("))]
    comments_src = src[src.index("def xhs_get_comments("):src.index("def discover_xhs_leads_by_keyword(")]
    download_src = src[src.index("def xhs_download_note("):src.index("def xhs_publish_comment(")]
    self.assertIn("persistent=(not guest_mode) and xhs_profile_ready", search_src)
    self.assertIn("persistent=(not guest_mode) and xhs_profile_ready", comments_src)
    self.assertIn("persistent=(not guest_mode) and xhs_profile_ready", download_src)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_lead_filtering -v
```

Expected: fails because the new function signatures and `guest_mode` logic do not exist yet.

- [ ] **Step 3: Implement adapter guest mode**

Change signatures:

```python
def xhs_search_notes(keyword, limit=10, data_dir="", guest_mode=True):
def xhs_get_comments(note_url, limit=120, data_dir="", source=None, guest_mode=True):
def discover_xhs_leads_by_keyword(keyword, video_num=5, comment_mode="page", data_dir="", guest_mode=True):
def xhs_download_note(note_url, base_dir, data_dir="", max_files=20, guest_mode=True):
```

Replace collection context selection with:

```python
persistent=(not guest_mode) and xhs_profile_ready(data_dir or os.getcwd())
```

Pass `guest_mode` from discovery to search and comment reading:

```python
search = xhs_search_notes(keyword, video_num, data_dir=data_dir, guest_mode=guest_mode)
res = xhs_get_comments(raw_note_url, limit=80 if comment_mode != "all" else 160, data_dir=data_dir, source=v, guest_mode=guest_mode)
```

Add helper:

```python
def xhs_guest_collection_default(env=None):
    env = env or os.environ
    return str(env.get("XHS_GUEST_COLLECTION_DEFAULT", "1")).strip().lower() not in ("0", "false", "no", "off")
```

- [ ] **Step 4: Add guest block classification**

When debug text indicates login wall or access restriction and `guest_mode=True`, return explicit errors:

```python
if guest_mode and result.get("needLogin"):
    result["error"] = "xhs_guest_login_required"
    result["guestMode"] = True
if guest_mode and result.get("blocked") and not result.get("error", "").startswith("xhs_guest_"):
    result["error"] = "xhs_guest_access_limited"
    result["guestMode"] = True
```

Keep `xhs_ip_risk` and `riskCode` in the result when the page provides a concrete platform risk code.

- [ ] **Step 5: Run adapter tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_lead_filtering -v
```

Expected: all XHS lead filtering tests pass.

---

### Task 2: Local API Flags and Safety Enforcement

**Files:**
- Modify: `tests/test_xhs_safety_mode.py`
- Modify: `tests/test_api_download_contract.py`
- Modify: `backend/api_server.py`

**Interfaces:**
- Consumes adapter functions from Task 1.
- Produces: `xhs_collection_guest_mode(body) -> bool`
- Produces: `xhs_account_collection_confirmed(body) -> bool`
- Produces: `xhs_collection_account_gate(action, account_id, guest_mode, confirmed, dry_run=False) -> dict`

- [ ] **Step 1: Write failing API tests**

Add tests covering default guest mode, rejected unconfirmed account collection, and confirmed safety preflight:

```python
def test_xhs_search_defaults_to_guest_mode(self):
    handler = self.make_api_handler({"query": "丰田", "num": 3}, path="/api/xhs/search")
    with mock.patch.object(self.api, "xhs_search_notes", return_value={"ok": True, "items": []}) as search:
        handler.do_POST()
    self.assertTrue(search.call_args.kwargs["guest_mode"])

def test_xhs_account_collection_requires_explicit_confirmation(self):
    handler = self.make_api_handler({"query": "丰田", "guestMode": False}, path="/api/xhs/search")
    handler.do_POST()
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    self.assertFalse(payload["ok"])
    self.assertEqual(payload["error"], "xhs_account_collection_unconfirmed")

def test_xhs_confirmed_account_collection_runs_safety_preflight(self):
    handler = self.make_api_handler({
        "query": "丰田",
        "guestMode": False,
        "accountCollectionConfirmed": True,
    }, path="/api/xhs/search")
    with mock.patch.object(self.api, "xhs_safety_preflight", return_value={"ok": True}) as preflight, \
         mock.patch.object(self.api, "xhs_search_notes", return_value={"ok": True, "items": []}):
        handler.do_POST()
    preflight.assert_called()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_safety_mode tests.test_api_download_contract -v
```

Expected: fails because the API does not parse or enforce the new flags.

- [ ] **Step 3: Implement API helper functions**

Add near XHS safety helpers:

```python
def xhs_collection_guest_mode(body):
    body = body if isinstance(body, dict) else {}
    default_guest = xhs_guest_collection_default(os.environ)
    return bool_arg(body.get("guestMode", default_guest), default_guest)

def xhs_account_collection_confirmed(body):
    body = body if isinstance(body, dict) else {}
    return bool_arg(body.get("accountCollectionConfirmed"), False)

def xhs_collection_account_gate(action, account_id, guest_mode, confirmed, dry_run=False):
    if guest_mode:
        return {"ok": True, "guestMode": True}
    if not confirmed:
        return {"ok": False, "blocked": True, "error": "xhs_account_collection_unconfirmed", "guestMode": False}
    return xhs_safety_preflight(action, account_id, dry_run=dry_run)
```

- [ ] **Step 4: Apply flags to XHS endpoints**

For `/api/xhs/search`, `/api/xhs/download`, `/api/xhs/comments`, and GET `/api/xhs/comments`:

```python
guest_mode = xhs_collection_guest_mode(body)
confirmed = xhs_account_collection_confirmed(body)
gate = xhs_collection_account_gate("search", account_id, guest_mode, confirmed)
if not gate.get("ok"):
    return json_response(self, {"ok": False, **gate}, 429)
result = xhs_search_notes(query, require_num, data_dir=DATA_DIR, guest_mode=guest_mode)
record = xhs_safety_record("search", account_id, result) if not guest_mode else {"safety": gate.get("safety")}
```

For `/api/finder/discover` with `platform == "xhs"`:

```python
guest_mode = xhs_collection_guest_mode(body)
confirmed = xhs_account_collection_confirmed(body)
gate = xhs_collection_account_gate("comment_read", _xhs_safety_account_id(body.get("accountId") or body.get("account") or ""), guest_mode, confirmed)
if not gate.get("ok"):
    return json_response(self, {"ok": False, **gate}, 429)
data = discover_xhs_leads_by_keyword(keyword, video_num=video_num, comment_mode=comment_mode, data_dir=DATA_DIR, guest_mode=guest_mode)
```

- [ ] **Step 5: Add structured logs**

When a guest result returns `xhs_guest_login_required`, `xhs_guest_access_limited`, `xhs_ip_risk`, or `blocked=True`, log:

```python
json_log(
    logger,
    "xhs_guest_collection_blocked",
    level="warning",
    action=action,
    error=result.get("error") or "",
    riskCode=str(result.get("riskCode") or ""),
    keywordLength=len(query or ""),
    urlFingerprint=hashlib.sha256(str(url or "").encode("utf-8")).hexdigest()[:16] if url else "",
)
```

When confirmed account collection starts, log `xhs_account_collection_confirmed` with action, account ID, and safety snapshot. Do not log full URL or text.

- [ ] **Step 6: Run API tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_safety_mode tests.test_api_download_contract -v
```

Expected: all tests pass.

---

### Task 3: Native Client Guest Requests and One-Time Confirmation

**Files:**
- Modify: `tests/test_native_publish.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Consumes local task payload fields from Task 2.
- Produces: `ContentPage._xhs_retry_with_account(action, payload)`
- Produces: `FinderPage._retry_with_xhs_account(payload)`
- Produces: `_is_xhs_guest_collection_block(error_or_payload) -> bool`

- [ ] **Step 1: Write failing client source tests**

Add tests:

```python
def test_xhs_content_collection_uses_guest_mode_by_default(self):
    src = Path("backend/matrix_native_client.py").read_text(encoding="utf-8-sig")
    content_src = src[src.index("class ContentPage("):src.index("class CopyPage(")]
    self.assertIn('"guestMode": True', content_src)
    self.assertIn("游客采集中：不使用登录账号", content_src)
    self.assertIn("游客下载中：不使用登录账号", content_src)
    self.assertIn("游客读取评论中：不使用登录账号", content_src)

def test_xhs_guest_collection_has_one_time_account_retry_dialog(self):
    src = Path("backend/matrix_native_client.py").read_text(encoding="utf-8-sig")
    self.assertIn("公开访问受限", src)
    self.assertIn("使用账号采集一次", src)
    self.assertIn('"accountCollectionConfirmed": True', src)
    self.assertIn('"guestMode": False', src)

def test_xhs_finder_uses_guest_mode_by_default(self):
    src = Path("backend/matrix_native_client.py").read_text(encoding="utf-8-sig")
    finder_src = src[src.index("class FinderPage("):src.index("class GrowthPage(")]
    self.assertIn('"guestMode": True', finder_src)
    self.assertIn("游客寻客中：不使用登录账号", finder_src)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v
```

Expected: fails because current UI payloads do not include guest flags and no retry dialog exists.

- [ ] **Step 3: Add shared guest block detector**

Near existing local error helpers:

```python
def _is_xhs_guest_collection_block(payload):
    payload = payload if isinstance(payload, dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    error = str(result.get("error") or payload.get("error") or "")
    return error in ("xhs_guest_login_required", "xhs_guest_access_limited", "xhs_ip_risk") or (
        bool(result.get("blocked")) and bool(result.get("guestMode"))
    )
```

- [ ] **Step 4: Send guest payloads by default**

Content page XHS payloads must include:

```python
"guestMode": True,
"accountCollectionConfirmed": False,
```

Finder page XHS payload must include the same fields only when platform is `xhs`.

Update status text to the spec text for XHS search, download, note replacement, comments, and finder.

- [ ] **Step 5: Add one-time confirmation retry**

For guest-blocked search/download/comments/note replacement/finder responses:

```python
box = QtWidgets.QMessageBox(self)
box.setWindowTitle("公开访问受限")
box.setText("小红书公开访问受限，本次采集需要登录账号。\n为降低账号风险，系统不会自动使用账号采集。\n你可以选择“使用账号采集一次”，该操作会计入风控中心。")
use_account = box.addButton("使用账号采集一次", QtWidgets.QMessageBox.AcceptRole)
box.addButton("取消", QtWidgets.QMessageBox.RejectRole)
box.exec()
if box.clickedButton() != use_account:
    self.status.setText("已取消账号采集")
    return
```

Retry current action with copied payload:

```python
payload["guestMode"] = False
payload["accountCollectionConfirmed"] = True
```

Do not store this decision on the page object as a default.

- [ ] **Step 6: Run client tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v
```

Expected: all native publish/client source tests pass.

---

### Task 4: Documentation, Rollback, and Verification

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/API_REFERENCE.md` if endpoint request docs need the new fields.

**Interfaces:**
- Consumes implemented behavior from Tasks 1-3.
- Produces traceable release notes and rollback instructions.

- [ ] **Step 1: Update docs**

Add entries covering:

- Default XHS guest collection behavior.
- One-time account collection confirmation.
- New request fields `guestMode` and `accountCollectionConfirmed`.
- New rollback switch `XHS_GUEST_COLLECTION_DEFAULT=0`.
- Safety mode still applies to confirmed account collection.
- No database migration, no new public route, no Docker structure change.

- [ ] **Step 2: Recompute implementation line numbers**

Use `rg -n` for:

```powershell
rg -n "def xhs_search_notes|def xhs_get_comments|def discover_xhs_leads_by_keyword|def xhs_download_note|def xhs_collection_guest_mode|class ContentPage|class FinderPage|xhs_guest_collection_blocked" backend docs
```

Update `docs/IMPLEMENTATION.md` references in `file#Lx-Ly` format with current line numbers.

- [ ] **Step 3: Run focused regression**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_safety_mode tests.test_xhs_lead_filtering tests.test_api_download_contract tests.test_native_publish -v
```

Expected: all tests pass.

- [ ] **Step 4: Run broader XHS regression**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_safety_mode tests.test_xhs_note_replacement tests.test_native_publish tests.test_api_download_contract tests.test_xhs_lead_filtering tests.test_agent_mode_defaults -v
```

Expected: all tests pass.

- [ ] **Step 5: Run compile and diff checks**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\platform_adapters.py backend\api_server.py backend\matrix_native_client.py tests\test_xhs_safety_mode.py tests\test_xhs_lead_filtering.py tests\test_api_download_contract.py tests\test_native_publish.py
git diff --check -- backend/platform_adapters.py backend/api_server.py backend/matrix_native_client.py tests/test_xhs_safety_mode.py tests/test_xhs_lead_filtering.py tests/test_api_download_contract.py tests/test_native_publish.py docs/IMPLEMENTATION.md docs/TROUBLESHOOTING.md docs/DEPLOYMENT.md docs/API_REFERENCE.md CHANGELOG.md
```

Expected: compile exits 0; diff check has no whitespace errors. Existing `SyntaxWarning` in unrelated regex strings may remain.

---

## Self-Review

- Spec coverage: default guest collection, one-time account confirmation, safety preflight, UI copy, observability, rollback, and tests are covered.
- Placeholder scan: no unfinished placeholder markers are intentionally left.
- Type consistency: request fields are consistently `guestMode` and `accountCollectionConfirmed`; adapter parameter is consistently `guest_mode`.
- Scope: limited to XHS collection and finder discovery. Publishing, private messaging, and comment publishing remain logged-in account actions.
