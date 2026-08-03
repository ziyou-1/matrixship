# MatrixShip UI Feature Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide unfinished production UI surfaces, keep Same-style Replacement visibly unavailable, and remove Xiaohongshu capability metadata while preserving environment-variable rollback.

**Architecture:** Extend the existing shared `platform_features.py` gate module with three UI flags and one XHS capability filter. The native client reads those gates at widget construction and navigation boundaries, while the local-browser worker and central server both sanitize XHS task capabilities. Existing pages, queues, jobs, and API routes remain in place for configuration rollback.

**Tech Stack:** Python 3, PySide6 widgets, `unittest`, MatrixShip native client, local-browser worker, central HTTP server.

## Global Constraints

- `MATRIX_XHS_ENABLED=0` hides Xiaohongshu and `MATRIX_XHS_ENABLED=1` restores it after restart.
- `MATRIX_VIDEO_REPLACEMENT_ENABLED=0` leaves Same-style Replacement navigation visible but disabled with `功能完善中，敬请期待`.
- `MATRIX_PENDING_PUBLISH_UI_ENABLED=0` hides only the Pending Publish Queue UI; queue data and processing code remain intact.
- `MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED=0` hides TTS upload UI while automatic TTS remains available.
- Truthy values are exactly `1`, `true`, `yes`, and `on`, case-insensitive.
- Do not modify Risk Control behavior in this implementation.
- Do not change API paths, JSON schemas, database tables, OpenAPI, or `migration.sql`.
- Preserve all unrelated user changes in the dirty worktree; stage only files owned by each task.
- Never log Cookie, Token, Authorization, signed URLs, API keys, or private media URLs.

---

## File Map

- Modify `backend/platform_features.py`: shared environment gates and XHS capability filtering.
- Modify `backend/local_browser_worker.py`: advertise only currently enabled task capabilities.
- Modify `backend/central_server.py`: sanitize incoming, stored, allowed, and public local-browser capabilities.
- Modify `backend/matrix_native_client.py`: Account Matrix filtering and the three temporary UI gates.
- Create `tests/test_ui_feature_visibility.py`: focused default-off and explicit-on UI gate coverage.
- Modify `tests/test_xhs_platform_disable.py`: local-browser and central XHS capability regression coverage.
- Modify `backend/.env.example`, `backend/.env.dev`, `backend/.env.prod`, and `docker-compose.prod.yml`: production-default-off configuration.
- Modify `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`, `docs/IMPLEMENTATION.md`, and `CHANGELOG.md`: behavior, rollout, rollback, and exact source line references.

---

### Task 1: Shared Feature Gates

**Files:**
- Modify: `backend/platform_features.py`
- Create: `tests/test_ui_feature_visibility.py`

**Interfaces:**
- Produces: `video_replacement_enabled(env=None) -> bool`
- Produces: `pending_publish_ui_enabled(env=None) -> bool`
- Produces: `digital_human_tts_upload_enabled(env=None) -> bool`
- Produces: `filter_xhs_capabilities(capabilities, env=None) -> list[str]`
- Preserves: `xhs_enabled(env=None) -> bool`

- [ ] **Step 1: Write failing shared-gate tests**

Create `tests/test_ui_feature_visibility.py` with direct imports from `backend/platform_features.py` and these assertions:

```python
def test_temporary_ui_features_are_default_off_and_explicitly_restorable(self):
    self.assertFalse(self.features.video_replacement_enabled({}))
    self.assertFalse(self.features.pending_publish_ui_enabled({}))
    self.assertFalse(self.features.digital_human_tts_upload_enabled({}))
    self.assertTrue(self.features.video_replacement_enabled({"MATRIX_VIDEO_REPLACEMENT_ENABLED": "1"}))
    self.assertTrue(self.features.pending_publish_ui_enabled({"MATRIX_PENDING_PUBLISH_UI_ENABLED": "true"}))
    self.assertTrue(self.features.digital_human_tts_upload_enabled({"MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED": "on"}))

def test_xhs_capability_filter_preserves_order_and_is_reversible(self):
    caps = ["douyin.search", "xhs.search", "douyin.publish", "xhs.login"]
    self.assertEqual(
        self.features.filter_xhs_capabilities(caps, {"MATRIX_XHS_ENABLED": "0"}),
        ["douyin.search", "douyin.publish"],
    )
    self.assertEqual(
        self.features.filter_xhs_capabilities(caps, {"MATRIX_XHS_ENABLED": "1"}),
        caps,
    )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_ui_feature_visibility -v
```

Expected: FAIL because the four new helpers do not exist.

- [ ] **Step 3: Implement the minimal shared helpers**

Add constants and helpers to `backend/platform_features.py`:

```python
VIDEO_REPLACEMENT_ENABLED_ENV = "MATRIX_VIDEO_REPLACEMENT_ENABLED"
PENDING_PUBLISH_UI_ENABLED_ENV = "MATRIX_PENDING_PUBLISH_UI_ENABLED"
DIGITAL_HUMAN_TTS_UPLOAD_ENABLED_ENV = "MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED"


def env_flag_enabled(name, env=None, default=False):
    values = os.environ if env is None else env
    raw = values.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in _TRUTHY


def video_replacement_enabled(env=None):
    return env_flag_enabled(VIDEO_REPLACEMENT_ENABLED_ENV, env=env)


def pending_publish_ui_enabled(env=None):
    return env_flag_enabled(PENDING_PUBLISH_UI_ENABLED_ENV, env=env)


def digital_human_tts_upload_enabled(env=None):
    return env_flag_enabled(DIGITAL_HUMAN_TTS_UPLOAD_ENABLED_ENV, env=env)


def filter_xhs_capabilities(capabilities, env=None):
    values = list(capabilities or [])
    if xhs_enabled(env):
        return values
    return [value for value in values if not str(value or "").strip().lower().startswith("xhs.")]
```

Update `xhs_enabled()` to call `env_flag_enabled(XHS_ENABLED_ENV, env=env)` so all flags share one parser.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_ui_feature_visibility tests.test_xhs_platform_disable -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the shared gate**

```powershell
git add backend/platform_features.py tests/test_ui_feature_visibility.py
git commit -m "feat: add temporary MatrixShip UI gates"
```

---

### Task 2: XHS Capability And Account Matrix Filtering

**Files:**
- Modify: `backend/local_browser_worker.py`
- Modify: `backend/central_server.py`
- Modify: `backend/matrix_native_client.py`
- Modify: `tests/test_xhs_platform_disable.py`
- Modify: `tests/test_ui_feature_visibility.py`

**Interfaces:**
- Consumes: `filter_xhs_capabilities(capabilities, env=None)` from Task 1.
- Produces: `advertised_capabilities() -> list[str]` in `local_browser_worker.py`.
- Produces: `sanitize_local_browser_capabilities(value) -> list[str]` in `central_server.py`.
- Produces: `account_matrix_platform_keys() -> tuple[str, ...]` in `matrix_native_client.py`.

- [ ] **Step 1: Add failing capability and Account Matrix tests**

Extend `tests/test_xhs_platform_disable.py`:

```python
def test_local_browser_capabilities_hide_xhs_and_restore_with_flag(self):
    worker = importlib.import_module("local_browser_worker")
    with mock.patch.dict(os.environ, {"MATRIX_XHS_ENABLED": "0"}, clear=False):
        self.assertFalse(any(cap.startswith("xhs.") for cap in worker.advertised_capabilities()))
    with mock.patch.dict(os.environ, {"MATRIX_XHS_ENABLED": "1"}, clear=False):
        self.assertIn("xhs.search", worker.advertised_capabilities())

def test_central_sanitizes_persisted_xhs_capabilities(self):
    with mock.patch.dict(os.environ, {"MATRIX_XHS_ENABLED": "0"}, clear=False):
        public = self.central.public_local_browser_client({
            "id": "lb-test",
            "lastSeen": self.central.now(),
            "capabilities": ["douyin.search", "xhs.search", "xhs.login"],
        })
    self.assertEqual(public["capabilities"], ["douyin.search"])
```

Extend `tests/test_ui_feature_visibility.py`:

```python
def test_account_matrix_platforms_are_douyin_only_by_default(self):
    with mock.patch.dict(os.environ, {"MATRIX_XHS_ENABLED": "0"}, clear=False):
        self.assertEqual(self.client.account_matrix_platform_keys(), ("douyin",))
    with mock.patch.dict(os.environ, {"MATRIX_XHS_ENABLED": "1"}, clear=False):
        self.assertEqual(self.client.account_matrix_platform_keys(), ("douyin", "xhs"))
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable tests.test_ui_feature_visibility -v
```

Expected: FAIL because the three new interfaces do not exist and public capabilities still contain XHS.

- [ ] **Step 3: Filter local-browser worker advertisements**

In `backend/local_browser_worker.py`, import `filter_xhs_capabilities`, add:

```python
def advertised_capabilities():
    return filter_xhs_capabilities(CAPABILITIES)
```

Use `advertised_capabilities()` in both `LocalBrowserWorker.register()` and `LocalBrowserWorker.poll()` payloads. Keep `TASK_PATHS`, `LOGIN_TYPES`, and `CAPABILITIES` intact so `MATRIX_XHS_ENABLED=1` restores behavior after restart.

- [ ] **Step 4: Filter central allowed, incoming, stored, and public capabilities**

In `backend/central_server.py`, import `filter_xhs_capabilities` and add:

```python
def sanitize_local_browser_capabilities(value):
    caps = value if isinstance(value, list) else []
    if not caps:
        caps = list(LOCAL_BROWSER_LEGACY_CAPS)
    return filter_xhs_capabilities(caps)
```

Build `LOCAL_BROWSER_ALLOWED_TYPES`, `LOCAL_BROWSER_ALL_CAPS`, and `LOCAL_BROWSER_LEGACY_CAPS` through `filter_xhs_capabilities()`. Call `sanitize_local_browser_capabilities()` from:

- `public_local_browser_client()` before returning `capabilities`.
- `local_browser_register()` before persisting `caps`.
- `local_browser_poll()` before persisting or matching `caps`.

This read-time filter removes historical XHS metadata without mutating private state or requiring a migration.

- [ ] **Step 5: Make Account Matrix use the same XHS gate**

In `backend/matrix_native_client.py`, add:

```python
def account_matrix_platform_keys():
    return ("douyin", "xhs") if xhs_enabled() else ("douyin",)
```

Update `AccountsPage._build()` to:

- Filter cleaned rows to `account_matrix_platform_keys()`.
- Build `groups` only for enabled platform keys.
- Use `used or len(platform_keys)` for the `接入平台` KPI.
- Create platform cards only for enabled platform keys.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable tests.test_ui_feature_visibility tests.test_douyin_dm_auto_reply -v
```

Expected: all tests pass; Douyin capabilities remain advertised.

- [ ] **Step 7: Commit XHS metadata filtering**

```powershell
git add backend/local_browser_worker.py backend/central_server.py backend/matrix_native_client.py tests/test_xhs_platform_disable.py tests/test_ui_feature_visibility.py
git commit -m "fix: remove disabled XHS capability metadata"
```

---

### Task 3: Native Client Temporary UI States

**Files:**
- Modify: `backend/matrix_native_client.py`
- Modify: `tests/test_ui_feature_visibility.py`
- Modify: `tests/test_digital_human_navigation.py`

**Interfaces:**
- Consumes: the three UI feature helpers from Task 1.
- Produces: `nav_feature_enabled(name) -> bool`.
- Produces: `SAME_STYLE_REPLACEMENT_TOOLTIP = "功能完善中，敬请期待"`.

- [ ] **Step 1: Add failing tests for tab, navigation, hidden entries, and TTS UI**

Add tests that run with `QT_QPA_PLATFORM=offscreen` and a shared `QApplication`:

```python
def test_publish_workspace_hides_pending_queue_by_default(self):
    with mock.patch.dict(os.environ, {"MATRIX_PENDING_PUBLISH_UI_ENABLED": "0"}, clear=False):
        page = self.client.PublishWorkspacePage()
    self.assertEqual([page.tabs.tabText(i) for i in range(page.tabs.count())], ["素材库与发布"])
    self.assertNotIn("📤 待发布队列", page.nav_aliases)

def test_same_style_replacement_navigation_is_disabled_by_default(self):
    with mock.patch.dict(os.environ, {"MATRIX_VIDEO_REPLACEMENT_ENABLED": "0"}, clear=False):
        self.assertFalse(self.client.nav_feature_enabled("🧬 同款替换"))
    with mock.patch.dict(os.environ, {"MATRIX_VIDEO_REPLACEMENT_ENABLED": "1"}, clear=False):
        self.assertTrue(self.client.nav_feature_enabled("🧬 同款替换"))

def test_secondary_replacement_entries_are_hidden_by_default(self):
    source = CLIENT.read_text(encoding="utf-8")
    self.assertIn("self.b_replace.setVisible(video_replacement_enabled())", source)
    self.assertIn("go.setVisible(video_replacement_enabled())", source)
    self.assertIn("use_btn.setVisible(video_replacement_enabled())", source)
```

Extend `tests/test_digital_human_navigation.py` with a widget test asserting that `b_upload_sound` and `sound_frame` are hidden and visible instructions do not mention uploading sound when the flag is `0`; repeat with `1` and assert both controls are restored.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv-win\Scripts\python.exe -m unittest tests.test_ui_feature_visibility tests.test_digital_human_navigation -v
```

Expected: FAIL because the temporary UI gates are not wired into widgets.

- [ ] **Step 3: Gate Pending Publish Queue UI**

Import `pending_publish_ui_enabled` and construct `PublishWorkspacePage` with:

```python
tabs = [("素材库与发布", lambda: PublishPage())]
if pending_publish_ui_enabled():
    tabs.append(("待发布队列", lambda: PendingPublishPage()))
super().__init__(tabs)
```

Set the instance `nav_aliases` to include `📤 待发布队列` only when the flag is enabled. Do not delete `PendingPublishPage`, `PENDING`, queue files, or scheduler calls.

- [ ] **Step 4: Disable Same-style Replacement navigation and hide secondary entries**

Import `video_replacement_enabled`, define `nav_feature_enabled(name)`, and update all three navigation boundaries:

- Main sidebar construction: attach `attach_hover_info(button, "同款替换", SAME_STYLE_REPLACEMENT_TOOLTIP)` to the replacement button.
- `_apply_role_visibility()`: keep the replacement button visible but call `setEnabled(nav_feature_enabled(name))`.
- `_goto_nav()` and `_nav()`: return without changing pages when `nav_feature_enabled(name)` is false.

Hide, rather than disable, secondary buttons:

```python
self.b_replace.setVisible(video_replacement_enabled())
go.setVisible(video_replacement_enabled())
use_btn.setVisible(video_replacement_enabled())
```

Do not remove `VideoReplacementPage` or generation code.

- [ ] **Step 5: Hide Digital Human TTS upload UI**

Import `digital_human_tts_upload_enabled`, compute `tts_upload_visible` in `DigitalHumanPage.__init__()`, and apply:

```python
self.sound_frame.setVisible(tts_upload_visible)
self.b_upload_sound.setVisible(tts_upload_visible)
```

When disabled, use visible copy that mentions only the required avatar, optional scene, and automatic synthesis from the voice selector. Keep `_sound_url`, upload handlers, and existing persisted-job behavior unchanged.

- [ ] **Step 6: Run focused UI tests and verify GREEN**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv-win\Scripts\python.exe -m unittest tests.test_ui_feature_visibility tests.test_digital_human_navigation tests.test_native_publish tests.test_video_breakdown -v
```

Expected: all tests pass.

- [ ] **Step 7: Render and inspect an offscreen native UI screenshot**

Run a short Qt smoke script using the repository virtual environment to render Account Matrix, Material Publish, Digital Human, and the sidebar to a PNG under `.tmp-ui-smoke/`. Verify with image inspection that:

- No Xiaohongshu Account Matrix card is visible.
- No Pending Publish Queue tab is visible.
- Same-style Replacement remains visible and grey.
- No TTS upload button or empty sound frame is visible.
- Text and controls do not overlap.

- [ ] **Step 8: Commit native UI behavior**

```powershell
git add backend/matrix_native_client.py tests/test_ui_feature_visibility.py tests/test_digital_human_navigation.py
git commit -m "feat: gate unfinished native client features"
```

---

### Task 4: Configuration, Documentation, And Runtime Proof

**Files:**
- Modify: `backend/.env.example`
- Modify: `backend/.env.dev`
- Modify: `backend/.env.prod`
- Modify: `docker-compose.prod.yml`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: all four environment flags and runtime behavior from Tasks 1-3.
- Produces: production-default-off configuration and documented rollback commands.

- [ ] **Step 1: Add configuration contract assertions**

Extend `tests/test_ui_feature_visibility.py` to read all environment templates and `docker-compose.prod.yml`, asserting that the three new keys exist with default `0`. Keep the existing XHS configuration assertions.

- [ ] **Step 2: Run the configuration test and verify RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_ui_feature_visibility -v
```

Expected: FAIL because the new flags are absent from configuration files.

- [ ] **Step 3: Add production-default-off configuration**

Add these variables to `.env.example`, `.env.dev`, and `.env.prod`, preserving each file's existing syntax:

```text
MATRIX_VIDEO_REPLACEMENT_ENABLED=0
MATRIX_PENDING_PUBLISH_UI_ENABLED=0
MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED=0
```

Add matching `${VARIABLE:-0}` entries to `docker-compose.prod.yml`.

- [ ] **Step 4: Update documentation and exact implementation line references**

Document:

- Default hidden/disabled UI states and environment recovery in `ARCHITECTURE.md` and `DEPLOYMENT.md`.
- Troubleshooting checks for stale clients, unexpected visible controls, and capability metadata in `TROUBLESHOOTING.md`.
- Release summary and rollback in `CHANGELOG.md`.
- Exact final `file#Lx-Ly` references for every changed production/config/test block in `IMPLEMENTATION.md`, recalculated after all source edits.
- Risk Control's current partial Douyin coverage without claiming new enforcement.

State explicitly that OpenAPI, database schema, Docker image structure, and `migration.sql` have no behavioral change.

- [ ] **Step 5: Run the complete focused regression and syntax gate**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv-win\Scripts\python.exe -m unittest tests.test_ui_feature_visibility tests.test_xhs_platform_disable tests.test_digital_human_navigation tests.test_native_publish tests.test_douyin_dm_auto_reply tests.test_openapi_contract -v
.\.venv-win\Scripts\python.exe -m py_compile backend/platform_features.py backend/local_browser_worker.py backend/central_server.py backend/matrix_native_client.py
git diff --check
```

Expected: tests pass, compilation exits `0`, and `git diff --check` reports no whitespace errors. Existing non-fatal `SyntaxWarning` output must be recorded rather than hidden.

- [ ] **Step 6: Restart and smoke all three runtime tiers**

Restart only the confirmed MatrixShip processes with:

```text
MATRIX_XHS_ENABLED=0
MATRIX_VIDEO_REPLACEMENT_ENABLED=0
MATRIX_PENDING_PUBLISH_UI_ENABLED=0
MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED=0
```

Verify:

- `GET http://127.0.0.1:9080/api/health` returns `200` and `ok=true`.
- `GET http://127.0.0.1:9081/api/health` returns `200`, `agentReady=true`, and Douyin capabilities remain ready.
- `GET /api/local-browser/status` reports one online local client and zero advertised `xhs.*` capabilities.
- Local and central `POST /api/xhs/search` return `404 platform_disabled` without opening a browser.
- The new native client process is responding and the UI screenshot matches Task 3.

- [ ] **Step 7: Commit configuration and release documentation**

```powershell
git add backend/.env.example backend/.env.dev backend/.env.prod docker-compose.prod.yml docs/ARCHITECTURE.md docs/DEPLOYMENT.md docs/TROUBLESHOOTING.md docs/IMPLEMENTATION.md CHANGELOG.md tests/test_ui_feature_visibility.py
git commit -m "docs: publish temporary feature visibility rollout"
```

---

## Final Review Checklist

- [ ] Every default-off behavior has a matching explicit-on restoration test.
- [ ] Same-style Replacement is visible only as a disabled navigation item and cannot be reached programmatically.
- [ ] Video Breakdown, Workflow Assistant, and Asset Library replacement jump buttons are hidden.
- [ ] Pending Publish Queue data and background behavior are untouched.
- [ ] Digital Human automatic TTS remains functional.
- [ ] No online or persisted public capability list exposes `xhs.*` while disabled.
- [ ] Douyin comment risk enforcement remains unchanged.
- [ ] OpenAPI and database schemas are unchanged.
- [ ] `IMPLEMENTATION.md` line references match final files.
- [ ] Runtime restart and smoke evidence is recorded before completion is claimed.
