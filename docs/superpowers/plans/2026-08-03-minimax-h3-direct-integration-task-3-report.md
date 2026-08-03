# MiniMax H3 Direct Integration Task 3 Report

## Status

RED complete. Only the central-server contract test file was created. No production code, billing implementation, OpenAPI document, environment file, deployment file, or unrelated dirty-worktree file was modified.

The new tests fail because the MiniMax central-server route and its OpenAPI contract do not exist yet. The existing OpenAPI tests continue to pass.

## Files

Created:

- `tests/test_minimax_central_server.py`
- `docs/superpowers/plans/2026-08-03-minimax-h3-direct-integration-task-3-report.md`

Not modified:

- `backend/central_server.py`
- `docs/openapi.yaml`
- billing code and billing tests
- environment and deployment files
- unrelated existing dirty-worktree files

## Contract Coverage

`tests/test_minimax_central_server.py` covers:

- unauthenticated `POST /api/v1/minimax/video/generate` returns HTTP 401;
- missing `prompt` returns HTTP 400;
- image mode with a local path returns HTTP 400 before provider submission;
- `first_last_frame` with only one image returns HTTP 400;
- a valid request reaches an injected `MiniMaxDirectClient`;
- task responses expose:
  - `businessTaskId`
  - `providerTaskId`
  - `requestedModel`
  - `actualModel`
  - `mode`
  - `duration`
  - `resolution`
  - `billingRef`
  - `status`
- the new OpenAPI path and response/request schema names exist.

The tests do not define or call a settlement interface.

## RED Command

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_central_server tests.test_openapi_contract -v
```

Result:

```text
Ran 14 tests in 4.510s

FAILED (failures=7)
```

The seven new MiniMax route tests fail with the current center server response:

```text
AssertionError: 404 != 401
AssertionError: 404 != 400
AssertionError: 404 != 400
AssertionError: 404 != 200
AssertionError: 404 != 400
AssertionError: 404 != 200
```

The OpenAPI contract test fails because the new path is absent:

```text
AssertionError: '/api/v1/minimax/video/generate' not found in document["paths"]
```

The seven existing `tests.test_openapi_contract` tests passed.

## Verification

Additional checks:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile tests\test_minimax_central_server.py
git diff --check -- tests/test_minimax_central_server.py
```

Both commands completed successfully with no output.

The test module imports successfully and starts a temporary local `ThreadingHTTPServer`; failures occur after HTTP routing, so they are not caused by malformed test setup or import errors.

## Self-Review

- The tests use the existing `unittest` style and the real `central_server.Handler` route surface.
- Authentication is isolated by injecting `central_server.current_user` for authenticated cases.
- The provider client is injected through the future `central_server.MiniMaxDirectClient` symbol and is asserted not to be called for invalid local references.
- No settlement, charge, refund, ledger, or billing behavior is asserted.
- The OpenAPI assertion is limited to the new MiniMax path and new schema names; `docs/openapi.yaml` remains unchanged.
- The existing dirty worktree was preserved.

## Unresolved Contract Questions

1. The implementation plan names both `POST /api/v1/minimax/video/generate` and `GET /api/v1/minimax/video/tasks/{task_id}`, but does not explicitly fix whether a successful POST must return HTTP 200, 201, or 202. The route test accepts any of these; the provisional OpenAPI assertion expects a 202 response.
2. The injection seam is not named in the plan. The tests assume the production module will expose or construct `MiniMaxDirectClient` from `backend.central_server`, allowing a test replacement.
3. The exact JSON error payload shape for validation failures is not specified. The tests intentionally assert only status code plus a broad diagnostic keyword.
4. The plan says “response fields” but does not state whether those fields are top-level or nested under `task`. The tests currently expect them at the top level, matching the Task 3 wording.
5. The status route response schema and its pending/failed/success variants still need to be defined before implementation and OpenAPI updates.

## Deployment and Rollback Impact

No restart or deployment is required for this RED-only task. No database migration was added. No rollback action is needed beyond removing the two newly created task-scoped files if the task is abandoned.
