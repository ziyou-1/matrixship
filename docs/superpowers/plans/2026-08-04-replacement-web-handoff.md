# Replacement Web Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind `/replacement` video replacement jobs to the native client's already-loaded same-style replacement context.

**Architecture:** Add a small local handoff file contract written by the native client and read by the local executor. The browser receives only a short `handoffId` in the hash, then calls token-protected local APIs to read safe context and submit a bound local job.

**Tech Stack:** Python stdlib, existing `backend/matrix_native_client.py`, existing `backend/replacement_web.py`, existing `backend/api_server.py`, `unittest`.

## Global Constraints

- Do not trigger LK888, remote AI Canvas, publishing, database migrations, or billing in this phase.
- Keep feature gated by `MATRIX_REPLACEMENT_WEB_ENABLED`.
- Never expose central tokens, local paths, phone numbers, cookies, Authorization headers, signed URLs, or raw media bytes in the URL or API response.
- Use TDD: each behavior gets a failing test before production code.
- Update OpenAPI/API docs, CHANGELOG, TROUBLESHOOTING, DEPLOYMENT, ARCHITECTURE, IMPLEMENTATION, and `migration.sql` if the API surface changes.

---

### Task 1: Native Handoff Writer

**Files:**
- Modify: `tests/test_replacement_web_mvp.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Produces: `create_replacement_web_handoff(source: dict, ttl_sec: int = 3600) -> dict`
- Produces: `replacement_web_launch_url(handoff_id: str = "") -> str`

- [ ] Write failing tests that assert the native launch URL includes `handoffId` when supplied and never exposes local paths or center tokens.
- [ ] Implement atomic local handoff JSON writes under `data_dir()/replacement_web_handoffs`.
- [ ] Verify focused unittest fails before code and passes after code.

### Task 2: Local Executor Handoff Reader

**Files:**
- Modify: `tests/test_replacement_web_mvp.py`
- Modify: `backend/replacement_web.py`
- Modify: `backend/api_server.py`

**Interfaces:**
- Produces: `create_video_handoff(data_dir: str, source: dict, user: dict | None = None, ttl_sec: int = 3600) -> dict`
- Produces: `load_video_handoff(data_dir: str, handoff_id: str) -> dict | None`
- Updates: `start_video_job(data_dir, fields, files)` reads optional `handoffId`

- [ ] Write failing tests for safe handoff response and bound video job creation.
- [ ] Add `GET /api/replacement/video/handoff?handoffId=...`.
- [ ] Update the page JavaScript to persist/read/pass `handoffId`.
- [ ] Verify focused unittest fails before code and passes after code.

### Task 3: Contracts And Docs

**Files:**
- Modify: `docs/openapi.yaml`
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`
- Modify: `migration.sql`

- [ ] Document `GET /api/replacement/video/handoff` and the optional `handoffId` field.
- [ ] Record rollout, rollback, smoke test result, and no database migration.
- [ ] Recalculate `docs/IMPLEMENTATION.md` line references after code changes.

### Task 4: Verification

- [ ] Run `.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v`.
- [ ] Run `.\.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v`.
- [ ] Run `.\.venv-win\Scripts\python.exe -m py_compile backend\api_server.py backend\replacement_web.py backend\platform_features.py backend\matrix_native_client.py tests\test_replacement_web_mvp.py`.
- [ ] Run `git diff --check`.
- [ ] Smoke check local `/replacement` and the new handoff endpoint with the feature flag enabled.
