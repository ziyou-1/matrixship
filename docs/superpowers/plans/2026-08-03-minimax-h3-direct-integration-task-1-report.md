# MiniMax H3 Direct Integration Task 1 Report

Date: 2026-08-03
Status: RED CONFIRMED

## Scope

Task 1 created only the two focused provider-contract unittest files requested by
the brief. No production adapter was implemented. The tests intentionally import
the future modules directly so the Phase 0 run proves that the implementation is
not present yet.

The tests cover:

- model mapping for `text_to_video`, `image_to_video`, and `first_last_frame`;
- normalization preservation of the two first/last-frame references;
- rejection of local filesystem paths and `data:` URLs;
- submit returning a provider task ID;
- two pending polls followed by a successful poll;
- result retrieval returning an HTTPS file URL;
- download writing provider bytes and returning media metadata;
- provider failure raising a poll-stage error;
- configured timeout raising a timeout error;
- published price lookup for the documented 768P/6-second rows;
- missing published price returning `None`.

Settlement, charging, ledger behavior, and idempotent billing were deliberately
excluded because they belong to Task 5.

## Files Changed

Created:

- `tests/test_minimax_direct.py`
- `tests/test_minimax_pricing.py`
- `docs/superpowers/plans/2026-08-03-minimax-h3-direct-integration-task-1-report.md`

The following files were not modified:

- `backend/central_server.py`
- `tools/aicanvas_remote/server_current.py`
- OpenAPI files
- billing files
- environment files
- deployment files
- `backend/utils/minimax_direct.py`
- `backend/utils/minimax_pricing.py`

Existing unrelated dirty-worktree changes were preserved.

## Test Names

`tests/test_minimax_direct.py`

- `MiniMaxDirectNormalizationTest.test_first_last_frame_maps_to_hailuo_02_and_keeps_two_frames`
- `MiniMaxDirectNormalizationTest.test_text_to_video_and_image_to_video_use_hailuo_23`
- `MiniMaxDirectNormalizationTest.test_image_to_video_rejects_local_paths_and_data_urls`
- `MiniMaxDirectLifecycleTest.test_submit_poll_retrieve_and_download_complete_provider_lifecycle`
- `MiniMaxDirectLifecycleTest.test_failure_status_raises_a_poll_stage_error`
- `MiniMaxDirectLifecycleTest.test_timeout_is_reported_after_configured_deadline`

`tests/test_minimax_pricing.py`

- `MiniMaxPublishedPricingTest.test_768p_six_second_video_uses_published_unit_price`
- `MiniMaxPublishedPricingTest.test_first_last_frame_uses_hailuo_02_published_price`
- `MiniMaxPublishedPricingTest.test_unknown_published_price_returns_none`

## RED Verification

Command:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_direct tests.test_minimax_pricing -v
```

The command was run twice. Both runs exited with code `1` and failed during test
module import with the expected missing implementation modules:

```text
ModuleNotFoundError: No module named 'backend.utils.minimax_direct'
ModuleNotFoundError: No module named 'backend.utils.minimax_pricing'

Ran 2 tests in 0.000s
FAILED (errors=2)
```

This is an import-time RED result, so unittest cannot discover or execute the
individual lifecycle and pricing methods until the later implementation task
creates the two adapter modules. The failure is therefore attributable to the
missing implementation modules, not malformed test setup.

## Self-Review

- The first/last-frame test asserts the exact `MiniMax-Hailuo-02` mapping and
  preserves both references in order.
- Text-to-video and image-to-video assert the exact `MiniMax-Hailuo-2.3` mapping.
- Image references are required to be publicly reachable HTTPS-style references
  by checking local paths and `data:` URLs are rejected.
- The fake provider is deterministic and has no network dependency.
- The lifecycle test exercises submit, three poll responses, retrieve, and
  download in one provider-task flow.
- Failure and timeout tests assert stage-relevant exception categories/messages.
- The pricing tests use `Decimal` values and include an unknown-row no-price
  case.
- No test asserts settlement, charging, ledger writes, or idempotency.
- No credentials, real provider URLs, or secrets are present.
- No commit was attempted; no commit is claimed.

## Contract Concern

The approved Task 1 brief defines the public method names and constructor
parameters but does not fully specify the injected `request_fn` response object
shape or concrete exception classes. These tests establish a minimal deterministic
shape for Task 2: request methods receive method, URL, headers, JSON payload, and
timeout; responses expose `json()`, `headers`, and `content`; poll failures use
`RuntimeError`; and deadline expiry uses `TimeoutError`.

If Task 2 requires a different response or exception contract, that should be
resolved before implementation rather than weakening these provider-lifecycle
assertions.

## Deployment and Rollback Impact

None. This task changed tests and this report only. No process restart, remote
deployment, database migration, OpenAPI update, environment change, or release
artifact was produced. The later implementation/release must retain the existing
MiniMax disable-switch and previous-version rollback path.
