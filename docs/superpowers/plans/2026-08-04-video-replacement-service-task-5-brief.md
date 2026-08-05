# Task 5 Implementer Brief — Web API Lifecycle & Customer Page

You are the Task 5 implementer for the MatrixShip video-replacement-service refactor.
Workspace: `E:\Desktop\矩阵星舰_应用前后端与中心服源码_clean_20260710_150252`
Windows PowerShell venv python: `.\.venv-win\Scripts\python.exe`

## Read first (full context)
- Plan: `docs/superpowers/plans/2026-08-04-video-replacement-service.md` — implement **Task 5 only** (do NOT do Task 6/7/8).
- Design: `docs/superpowers/specs/2026-08-04-video-replacement-service-design.md`
- Existing code you extend: `backend/replacement_service.py` (ReplacementService: prepare/execute/concat/get_job/cancel — add `retry`), `backend/replacement_web.py` (has start_video_job Phase 0 + handoff), `backend/replacement_pipeline.py` (Hybrid + ComicProject pipelines), `backend/api_server.py` (current `/api/replacement/*` routes near the replacement handlers), `backend/replacement_analysis.py` (SourceResolver source).
- Tests to extend: `tests/test_replacement_web_mvp.py`, `tests/test_replacement_service.py`.

## Scope (Task 5 interfaces)
In `backend/replacement_web.py` add web adapters that drive a `ReplacementService`:
- `prepare_video_job(data_dir, fields, files) -> dict`
- `execute_video_job(data_dir, job_id, overrides) -> dict`
- `retry_video_job(data_dir, job_id, segment_indices) -> dict`
- `concat_video_job(data_dir, job_id) -> dict`
- `cancel_video_job(data_dir, job_id) -> dict`
- `video_job_response(job) -> dict` — never exposes internal paths, tokens, cookies, signed URLs, or credentials.

Add `ReplacementService.retry(job_id, segment_indices, progress=None)` in `backend/replacement_service.py` (delegates to `pipeline.retry`; only valid from `partial`/`awaiting_review` states; persists; returns public job).

In `backend/api_server.py` wire routes, keeping the existing `MATRIX_REPLACEMENT_WEB_ENABLED` gate and agent-token auth:
```
POST /api/replacement/video/prepare -> 202
POST /api/replacement/video/execute -> 202
GET  /api/replacement/video/job?jobId=... -> 200
POST /api/replacement/video/retry   -> 202
POST /api/replacement/video/concat  -> 202
POST /api/replacement/video/cancel  -> 202
```
Keep `POST /api/replacement/video/start` as a **compat alias** that CANNOT bypass plan confirmation. Validate task ID, filename and root for any final-media download. Invalid state transitions return HTTP 409.

Upgrade **only the video portion** of the page HTML/JS in `replacement_web.py`:
- Use `sessionStorage` only for `handoffId` and `jobId`.
- Poll every 1s during preparation, every 2s during generation.
- Show safe progress, per-segment statuses, retry-failed, cancel, concat, and final authenticated download (token in header, never in query).
- Do NOT change the note-replacement flow.

## Hard constraints (matrixship-production-guard)
- Provider submit success != generation success; the web layer only orchestrates the service, never calls providers directly.
- No LK888/remote/publish/billing side effects in this task; execute runs through the injected pipeline (fake-provider in tests).
- job.json is the single cross-process source of truth; writes stay atomic (service already does `os.replace`).
- Never log or return Token, Cookie, Authorization, signed URLs, data: URLs, absolute local paths, or raw media bytes. Redact in `video_job_response` and structured logs.
- Feature stays gated; disabled => 404 `replacement_web_disabled`.
- Do NOT precharge or charge from submit responses (that logic lives in the pipeline; do not add any here).

## TDD (required)
1. Write FAILING tests first in `tests/test_replacement_web_mvp.py` (+ `tests/test_replacement_service.py` for `retry`) covering: handoff prepare without sourceUrl, direct-URL prepare, authenticated execute/retry/concat/cancel, job polling, invalid-state 409, response redaction (no internal path/credential), and page HTML controls (source mode, progress, editable plan, execute, retry-failed, cancel, concat, handoff status). Use injected fakes for source resolver + pipeline; do not hit real providers.
2. Run them and confirm RED:
   `.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v`
3. Implement minimal code to GREEN.
4. Update `docs/openapi.yaml` for the new routes/schemas (202/400/401/404/409/500), and confirm `tests.test_openapi_contract` + `tests.test_replacement_web_mvp` pass.
5. `py_compile` all touched modules; `git diff --check`.

## Do NOT
- Do NOT commit, stage, move HEAD, or touch unrelated dirty files.
- Do NOT modify note flow, Qt client (Task 6), circuit breaker (Task 7), or other tasks' files.
- Do NOT edit `docs/IMPLEMENTATION.md` line numbers (the controller recalculates before commit).

## Report back (return as your final message)
- Exact new/changed functions and routes.
- Test names added and the GREEN counts for `test_replacement_web_mvp` / `test_replacement_service` / `test_openapi_contract`.
- Any deviation from the plan and why.
- Confirm no commit was made and no unrelated files were touched.
