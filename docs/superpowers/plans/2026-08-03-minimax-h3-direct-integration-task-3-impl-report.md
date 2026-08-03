# MiniMax H3 Direct Integration Task 3 Report

Date: 2026-08-03
Status: GREEN

## Scope

Implemented the central-server portion of Task 3 only:

- authenticated MiniMax video submission;
- request validation before provider submission;
- feature flag, center-key, and active-task concurrency gates;
- provider submission through `MiniMaxDirectClient`;
- provider-specific pending state under
  `STATE["minimax_pending_charges"]`;
- trace fields and structured redacted errors;
- task status recovery for `pending`, `failed`, and
  `awaiting_actual_cost`;
- OpenAPI and API reference documentation;
- central environment example settings.

Remote comic-generator files were not modified. No settlement, charge, refund,
or idempotent billing behavior was added.

## Files Changed

- `backend/central_server.py`
- `backend/.env.example`
- `docs/openapi.yaml`
- `docs/API_REFERENCE.md`
- `tests/test_minimax_central_server.py`
- `docs/superpowers/plans/2026-08-03-minimax-h3-direct-integration-task-3-impl-report.md`

Existing unrelated dirty-worktree changes were preserved.

## Runtime Behavior

### POST `/api/v1/minimax/video/generate`

The route now:

1. Requires the existing center-session authentication.
2. Normalizes and validates the request before checking provider configuration
   or submitting anything.
3. Rejects unsupported modes, missing prompts, unsupported duration/resolution,
   local image paths, `data:` URLs, and incomplete first/last-frame requests.
4. Rejects disabled MiniMax configuration with `503 minimax_disabled`.
5. Rejects a missing center key with `503 minimax_not_configured`.
6. Rejects a full active-task limit with `429 minimax_concurrency_limit`.
7. Calls `MiniMaxDirectClient` with the center base URL, center key, 900-second
   timeout, and configured poll interval.
8. Stores provider-specific state in
   `STATE["minimax_pending_charges"]` and persists both submitting and pending
   transitions.
9. Returns `202` with:
   `businessTaskId`, `providerTaskId`, `requestedModel`, `actualModel`, `mode`,
   `duration`, `resolution`, `billingRef`, `status`, and `traceId`.

The provider task ID is retained. There is no automatic model fallback or
automatic resubmission.

### GET `/api/v1/minimax/video/tasks/{task_id}`

The route:

- requires the same authenticated user and organization scope;
- returns persisted pending and failed records;
- converts a persisted provider success state to
  `awaiting_actual_cost`;
- never invokes a billing function;
- does not use `Decimal("0.28")` or another local estimate as a production
  charge;
- returns a structured, scope-safe 404 for missing or inaccessible tasks.

### Error and trace handling

Errors include:

- `ok: false`;
- a stable error code;
- `stage`;
- generated `errorId`;
- generated `traceId`;
- a short, sanitized message where appropriate.

Structured logs include stage, error ID, trace ID, task IDs, model, and mode
without logging the API key, Authorization header, or private provider URL.

## Configuration

Added to `backend/.env.example`:

- `MINIMAX_ENABLED=1`
- `MINIMAX_CENTER_API_BASE=https://api.minimaxi.com`
- `MINIMAX_CENTER_API_KEY=`
- `MINIMAX_MAX_ACTIVE_TASKS=2`
- `MINIMAX_TASK_TIMEOUT_SEC=900`
- `MINIMAX_POLL_INTERVAL_SEC=5`

The production key remains environment-only.

## TDD and Verification

The initial RED run was:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_central_server tests.test_openapi_contract -v
```

Before implementation, the MiniMax central tests failed because the routes,
runtime configuration, and OpenAPI paths were absent. Existing unrelated
OpenAPI tests passed.

The final focused run was the same command:

```text
Ran 18 tests in 7.970s
OK
```

Compilation:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\central_server.py tests\test_minimax_central_server.py
```

Result: exit code `0`.

Diff validation:

```powershell
git diff --check -- backend/central_server.py backend/.env.example docs/openapi.yaml docs/API_REFERENCE.md tests/test_minimax_central_server.py docs/superpowers/plans/2026-08-03-minimax-h3-direct-integration-task-3-impl-report.md
```

Result: exit code `0`.

## OpenAPI and Data Impact

- Added the POST and GET MiniMax paths to `docs/openapi.yaml`.
- Added `MiniMaxVideoGenerateRequest` and
  `MiniMaxVideoTaskResponse` schemas.
- Documented the `awaiting_actual_cost` status and trace fields.
- No database table or column was added.
- No `migration.sql` change is required.
- No billing contract or ledger behavior was changed.

## Remaining Risks and Unresolved Items

- Task 3 does not yet poll the provider, retrieve the file, download media, or
  validate video bytes. Those belong to the later central lifecycle work.
- `awaiting_actual_cost` is intentionally a hold state until the account
  currency and published-price settlement rules are confirmed in Task 5.
- No live MiniMax request was made; provider credentials were not used.
- OpenAPI and runtime now both require `duration` and `resolution` for central
  submission. The shared lower-level adapter remains capable of normalizing
  partial requests for later internal callers.
- No service restart or deployment was performed.

## Rollback

Before wiring later lifecycle and billing behavior, rollback can be performed by
restoring the previous central-server source, environment example, OpenAPI/API
documentation, and central tests. Runtime emergency control is
`MINIMAX_ENABLED=0`, which blocks new submissions without deleting persisted
diagnostics.

No commit was attempted or claimed.
