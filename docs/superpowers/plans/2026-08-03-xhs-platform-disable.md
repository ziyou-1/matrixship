# Xiaohongshu Platform Disable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Disable Xiaohongshu across the native client, local executor, platform adapters, central server, task types, and runtime documentation while keeping an explicit environment switch for future recovery.

**Architecture:** Add one shared platform feature gate that reads `MATRIX_XHS_ENABLED` and defaults to disabled. Every local and central XHS boundary will reject requests before browser, account, task, or persistence work with a redacted structured `platform_disabled` result; the native client will omit XHS controls and normalize all new platform choices to Douyin. A one-time cleanup utility will remove existing local and central XHS account state without touching Douyin or unrelated materials.

**Tech Stack:** Python, `unittest`, PyYAML/OpenAPI source contract tests, Qt native client, JSON-backed local/central state, Docker Compose environment configuration.

## Global Constraints

- Production code must not hard-code secrets; configuration is loaded from environment files.
- XHS is disabled by default and can only be restored with `MATRIX_XHS_ENABLED=1`, `true`, `yes`, or `on`.
- Disabled requests must emit redacted JSON logs with platform, route/task type, and failure stage; no cookies, tokens, authorization headers, or full signed URLs.
- Douyin behavior must remain unchanged.
- Existing XHS account state is not retained; cleanup must be scoped to XHS account IDs, profiles, auth markers, and central account records only.
- Any API contract change must update `docs/openapi.yaml`, `docs/API_REFERENCE.md`, focused tests, and troubleshooting notes.
- Do not commit until `docs/IMPLEMENTATION.md` line references are recalculated.
- Release documentation must state restart requirements and the rollback switch/path.

---

### Task 1: Establish the shared feature gate and failing tests

**Files:**
- Create: `backend/platform_features.py`
- Create: `tests/test_xhs_platform_disable.py`

**Interfaces:**
- `xhs_enabled(env=None) -> bool`
- `platform_disabled_result(platform, route="", task_type="", stage="") -> dict`
- `is_xhs_platform(value) -> bool`
- `require_platform_enabled(platform, route="", task_type="", stage="") -> dict | None`

- [ ] **Step 1: Write the failing tests**

```python
def test_xhs_is_disabled_by_default_and_douyin_is_enabled():
    assert xhs_enabled({}) is False
    assert xhs_enabled({"MATRIX_XHS_ENABLED": "1"}) is True
    assert is_xhs_platform("小红书") is True
    assert is_xhs_platform("douyin") is False
```

```python
def test_disabled_result_is_structured_and_redacted():
    result = platform_disabled_result("xhs", route="/api/xhs/search", task_type="xhs.search", stage="preflight")
    assert result["ok"] is False
    assert result["error"] == "platform_disabled"
    assert result["platform"] == "xhs"
    assert result["route"] == "/api/xhs/search"
    assert "token" not in str(result).lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable -v`

Expected: FAIL because `backend.platform_features` does not yet exist.

- [ ] **Step 3: Implement the minimal feature gate**

Implement the four functions above and use `backend.utils.structured_log` only for safe event fields.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable -v`

Expected: PASS.

### Task 2: Gate the local executor and platform adapters

**Files:**
- Modify: `backend/platform_adapters.py`
- Modify: `backend/api_server.py`
- Test: `tests/test_xhs_platform_disable.py`
- Test: `tests/test_api_download_contract.py`

**Interfaces:**
- All public XHS adapter operations return `platform_disabled_result(...)` before opening a browser.
- All `/api/xhs/*`, `/api/xhs-note-replacement/*`, and XHS branches of `/api/finder/discover`, `/api/publish/run`, and local browser task dispatch reject while disabled.
- Douyin routes and task types continue to use existing behavior.

- [ ] **Step 1: Add failing route and adapter tests**

Cover `/api/xhs/search`, `/api/xhs/download`, `/api/xhs/comments`, `/api/xhs/comment/publish`, `/api/xhs/login`, `/api/xhs-note-replacement/template`, `platform=xhs` finder, `platform=xhs` publish, and `xhs.*` local task types. Assert no adapter/browser function is called.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable tests.test_api_download_contract -v`

Expected: the new tests fail because the existing XHS routes still execute.

- [ ] **Step 3: Add preflight gates**

Use the shared gate at the earliest route/task boundary, preserving existing response shape fields where callers need them and adding `error=platform_disabled`, `platform=xhs`, `stage=preflight`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable tests.test_api_download_contract -v`

Expected: PASS with no browser calls.

### Task 3: Gate central server contracts and task types

**Files:**
- Modify: `backend/central_server.py`
- Modify: `backend/maindb.py` only if central account cleanup requires its persistence helper
- Test: `tests/test_xhs_platform_disable.py`
- Test: `tests/test_openapi_contract.py`

**Interfaces:**
- Central account listing, account registration, account rename/remove, XHS task creation, and XHS local-browser task dispatch exclude or reject XHS while disabled.
- Douyin account and task behavior remains available.

- [ ] **Step 1: Add failing central tests**

Assert central account responses contain no XHS records, XHS task creation returns `platform_disabled`, and Douyin task creation remains accepted.

- [ ] **Step 2: Run RED**

Run: `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable tests.test_openapi_contract -v`

Expected: FAIL on current central behavior.

- [ ] **Step 3: Implement central gates**

Apply the same shared feature gate to central request parsing and task-type validation. Do not log raw task payloads or account cookies.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable tests.test_openapi_contract -v`

Expected: PASS.

### Task 4: Hide XHS in the native client

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_xhs_platform_disable.py`
- Test: `tests/test_native_publish.py`
- Test: `tests/test_finder_page_actions.py`

**Interfaces:**
- Account Matrix, content collection, finder, publish, workflow assistant, scheduler, video-link parsing, risk center, and XHS note replacement controls are absent when `MATRIX_XHS_ENABLED` is disabled.
- New client payloads only select `douyin`; legacy XHS payloads fail locally with `platform_disabled`.

- [ ] **Step 1: Add failing source/behavior tests**

Assert platform selectors contain only Douyin, XHS note replacement navigation is hidden, XHS accounts are filtered, XHS video URLs are rejected, and Douyin controls remain present.

- [ ] **Step 2: Run RED**

Run: `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable tests.test_native_publish tests.test_finder_page_actions -v`

Expected: FAIL because the current client exposes XHS controls and parsing.

- [ ] **Step 3: Implement client visibility and payload guards**

Read the shared feature gate at runtime, remove XHS widgets/actions from construction, filter XHS account rows, and return a safe disabled status for stale or manually supplied XHS payloads.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable tests.test_native_publish tests.test_finder_page_actions -v`

Expected: PASS.

### Task 5: Configure the switch and clean existing XHS state

**Files:**
- Modify: `backend/.env.example`
- Modify: `backend/.env.dev`
- Modify: `backend/.env.prod`
- Modify: `docker-compose.prod.yml`
- Create: `scripts/disable_xhs_accounts.py`
- Modify: `migration.sql`
- Test: `tests/test_xhs_platform_disable.py`

**Interfaces:**
- `MATRIX_XHS_ENABLED=0` is present in all environment templates and is passed to production containers.
- `scripts/disable_xhs_accounts.py --data-dir ... --central-state ... --dry-run` reports scoped XHS paths and records without deleting.
- Without `--dry-run`, the script deletes XHS profile/auth/account records only and is idempotent; Douyin records and unrelated materials remain untouched.
- `migration.sql` documents the release marker and does not delete local JSON/profile files implicitly.

- [ ] **Step 1: Add failing cleanup tests**

Create temporary local/central state with `xhs-self`, `xhs-*`, `platform=xhs`, and Douyin fixtures. Assert dry-run identifies only XHS and apply removes only XHS.

- [ ] **Step 2: Run RED**

Run: `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable -v`

Expected: FAIL because the cleanup utility is missing.

- [ ] **Step 3: Implement and configure**

Use safe path resolution under the supplied data roots; refuse paths outside the supplied roots; write a JSON summary with counts and no sensitive values.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable -v`

Expected: PASS.

### Task 6: Update API/docs/release records and verify

**Files:**
- Modify: `docs/openapi.yaml`
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`
- Modify: `migration.sql`
- Test: `tests/test_openapi_contract.py`

- [ ] **Step 1: Update contracts and operations docs**

Document `MATRIX_XHS_ENABLED`, `platform_disabled`, disabled XHS route/task behavior, restart requirements, cleanup command, and rollback by setting the switch to `1` plus reverting the release files.

- [ ] **Step 2: Recalculate line references**

Use `rg -n` after all source edits and update every new `backend/...#Lx-Ly` reference in `docs/IMPLEMENTATION.md` and troubleshooting records.

- [ ] **Step 3: Run full verification**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_platform_disable tests.test_openapi_contract tests.test_native_publish tests.test_finder_page_actions -v
.\.venv-win\Scripts\python.exe -m py_compile backend\platform_features.py backend\platform_adapters.py backend\api_server.py backend\central_server.py backend\matrix_native_client.py scripts\disable_xhs_accounts.py
```

Expected: all focused tests pass and `py_compile` exits with code 0. Real browser login is not required for this disable gate; a local executor and central healthcheck restart remain operational steps.

- [ ] **Step 4: Record rollback and residual risk**

Confirm the release can be rolled back by restoring the changed files and setting `MATRIX_XHS_ENABLED=1`, then record that running client/executor/central processes must be restarted.
