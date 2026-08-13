# Task 7 Implementer Brief — Observability, Circuit Breaker, Contracts & Docs

You are the Task 7 implementer for the MatrixShip video-replacement-service refactor.
Workspace: `E:\Desktop\矩阵星舰_应用前后端与中心服源码_clean_20260710_150252`
Windows; venv python `.venv-win/Scripts/python.exe`.

## Read first
- Plan: `docs/superpowers/plans/2026-08-04-video-replacement-service.md` — implement **Task 7 only** (section "Task 7: Observability, Circuit Breaker, Contracts and Docs"). Do NOT do Task 8.
- Design: `docs/superpowers/specs/2026-08-04-video-replacement-service-design.md`
- Tasks 5+6 are already implemented in the working tree (uncommitted): ReplacementService (prepare/execute/retry/concat/cancel/get_job + module-level public_job) in `backend/replacement_service.py`; web adapters + build_video_service in `backend/replacement_web.py`; video lifecycle routes in `backend/api_server.py`; Qt `ReplacementServiceAdapter` + `replacement_mode_for_new_job()`/`video_replacement_service_shared()` (default legacy) in `backend/matrix_native_client.py`.

## Scope (Task 7)
1. **Persisted terminal metrics + circuit breaker**:
   - `record_terminal_result(job) -> dict`: append a bounded terminal-result window (store under the agent data directory; bound the window size, e.g. last 500). Only terminal jobs (completed/failed/cancelled) count; a cancelled job is not a failure.
   - `shared_mode_allowed() -> bool`: require **at least 100 terminal jobs**; return legacy (False) only when `failed / total > 0.01`. Exactly 1 failure in 100 (==1%) must NOT open the circuit (strictly greater-than). Fewer than 100 terminal jobs => allowed (shared) by default unless the design says otherwise. Never interrupt an already-active job — the breaker only gates NEW jobs.
   - Wire `replacement_mode_for_new_job()` (matrix_native_client.py, Task 6) so a new job uses shared only when both the env opt-in AND `shared_mode_allowed()` agree; when the breaker is open, emit `shared_mode_circuit_opened` / `rollback_requested` and fall back to legacy.
   - Decide placement per the design (likely `backend/platform_features.py` or `backend/replacement_service.py`); keep it importable by both the web layer and the Qt client.
2. **Redacted structured events** at boundaries: `prepare_started`, `analysis_completed`, `provider_submitted`, `provider_recovered`, `billing_settled`, `video_completed`, `video_failed`, `shared_mode_circuit_opened`, `rollback_requested`. Each carries only sanitized context: job id, stage, model, provider-task **hash** (not raw id), status, media-URL **shape**, cost/ref, failure stage. NEVER Token/Cookie/Authorization/signed URL/absolute path/raw bytes.
3. **Contracts + docs** (update ALL of these EXCEPT IMPLEMENTATION.md): `docs/openapi.yaml`, `docs/API_REFERENCE.md`, `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`, `CHANGELOG.md`, `migration.sql` (record: no DB migration). Document exact request fields, response schemas, 200/202/400/401/404/409/500 errors, feature flags (`MATRIX_REPLACEMENT_WEB_ENABLED`, `VIDEO_REPLACEMENT_SERVICE_MODE`), polling, source modes, local download route, restart requirement, circuit-breaker behavior, and stable-version rollback.

## Hard constraints (matrixship-production-guard)
- 1% failure must NOT open the circuit (strict `>`). Do not interrupt active jobs.
- Never log/return secrets or full signed URLs; provider task ids only as hashes in logs/events.
- No precharge / no submit-response charge (billing already settled in pipeline; do not touch it).
- No remote deploy, no DB tables, no new resident port. migration.sql stays a no-op note.
- Keep feature gated; disabled web => 404.

## TDD (required)
1. Failing tests first in `tests/test_replacement_service.py` and `tests/test_replacement_web_mvp.py`:
   - exactly 100 terminal jobs with **two** failures => `shared_mode_allowed()` False (2% > 1%),
   - exactly 100 terminal jobs with **one** failure => True (1% is not > 1%),
   - fewer than 100 terminal jobs => True,
   - an active (non-terminal) job is never interrupted by the breaker,
   - a secret-like provider URL and raw task id never appear in emitted events or API responses (redaction).
2. Run red: `.venv-win/Scripts/python.exe -m unittest tests.test_replacement_service tests.test_replacement_web_mvp -v`
3. Implement to GREEN.
4. Run: `.venv-win/Scripts/python.exe -m unittest tests.test_replacement_web_mvp tests.test_openapi_contract tests.test_replacement_service -v`; `git diff --check`; and
   `rg -n "TODO|TBD|sourceVideoPath|Authorization|signed URL" docs/openapi.yaml docs/API_REFERENCE.md docs/DEPLOYMENT.md docs/TROUBLESHOOTING.md` (expect no private path/credential in public schema).
5. `py_compile` every changed module.

## Do NOT
- Do NOT edit `docs/IMPLEMENTATION.md` at all (the controller does the line-ref recalc + new entries after your code is frozen).
- Do NOT commit / stage / move HEAD / touch unrelated dirty files.
- Do NOT implement Task 8, and do NOT change the note-replacement flow.

## Report back
- New symbols (record_terminal_result, shared_mode_allowed, event emitters) with file:line.
- Circuit-breaker test names + the exact boundary assertions (100/2 => legacy, 100/1 => shared).
- GREEN counts for test_replacement_service / test_replacement_web_mvp / test_openapi_contract.
- Which docs changed. Confirm the rg secret scan is clean.
- Confirm IMPLEMENTATION.md untouched, no commit, no unrelated files.
