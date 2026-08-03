# MiniMax H3 Official Direct Integration Design

## Status

- Approved: 2026-08-03
- Scope: central server and remote comic generator
- Release mode: direct production release, with an emergency disable switch

## Goal

Integrate MiniMax official direct video APIs into both MatrixShip runtime surfaces:

- The central server calls MiniMax directly with a center-server-specific key.
- The remote comic generator calls MiniMax directly with a comic-service-specific key.
- Both surfaces submit, poll, retrieve, download, validate, log, and settle their own tasks.
- The integration must preserve the project's production requirements: observable, reversible, and traceable.

This design does not route MiniMax through LK888 or through the other MatrixShip service.

## Accepted Decisions

| Area | Decision |
|---|---|
| Provider path | MiniMax official direct API |
| Callers | Central server and remote comic generator both call MiniMax directly |
| Credentials | `MINIMAX_CENTER_API_KEY` and `MINIMAX_COMIC_API_KEY` |
| Text-to-video | `MiniMax-Hailuo-2.3` |
| Image-to-video | `MiniMax-Hailuo-2.3` |
| First/last-frame video | `MiniMax-Hailuo-02` |
| User-facing model label | MiniMax H3 / MiniMax series label |
| Billing | Success-only settlement from the official published unit-price table |
| Failed/cancelled/safety-rejected task | No charge |
| Missing price row | `awaiting_actual_cost`, no charge |
| Audio with dialogue | Replace provider audio with project TTS |
| Audio without dialogue | Keep provider audio; preserve silence if none exists |
| Rollout | Directly available in production |
| Emergency control | `MINIMAX_ENABLED`, enabled in production by default |
| Central-service concurrency | Maximum 2 active MiniMax tasks |
| Remote-service concurrency | Maximum 2 active MiniMax tasks |
| Task timeout | 15 minutes |
| Timeout recovery | Mark failed and retain diagnostics; do not switch models or resubmit automatically |

## Non-Goals

- No automatic fallback from MiniMax to LK888, Seedance, Vidu, or another provider.
- No automatic retry that creates a second provider task after a submit response has returned a task ID.
- No direct exposure of API keys to the native client or browser.
- No use of token counts, local estimates, or guessed prices as final billing input.
- No change to unrelated Agent, Douyin, XHS, publishing, or billing behavior.

## Architecture

### Central server

The central server owns the authenticated MatrixShip-facing task contract and calls MiniMax using `MINIMAX_CENTER_API_KEY`.

Responsibilities:

1. Validate request schema and model/mode compatibility.
2. Convert MatrixShip media references into reachable HTTPS URLs.
3. Submit the MiniMax task.
4. Persist the MatrixShip task ID, provider task ID, requested model, actual model mapping, mode, duration, resolution, and billing reference.
5. Poll the provider task until success, failure, cancellation, or the 15-minute timeout.
6. Retrieve and download the provider file.
7. Validate the downloaded media.
8. Apply project TTS audio when storyboard dialogue exists.
9. Settle the published-unit amount exactly once using a stable billing reference.
10. Return structured public errors and retain redacted diagnostic details.

The central server should reuse the existing authenticated task and ledger conventions. MiniMax pending records must use a provider-specific namespace such as `minimax_pending_charges`; they must not be mixed with LK888 pending records.

### Remote comic generator

The remote comic generator owns the comic storyboard generation path and calls MiniMax using `MINIMAX_COMIC_API_KEY`.

Responsibilities:

1. Accept the existing storyboard video payload.
2. Validate `text`, `image`, and `first/last-frame` modes before provider submission.
3. Upload or publicize local references before MiniMax sees them.
4. Submit and poll through a provider adapter.
5. Persist provider task metadata in the existing comic task state.
6. Download and validate the result before marking the storyboard video complete.
7. Replace provider audio with storyboard TTS when dialogue is present.
8. Report the real provider model ID and billing metadata to the comic task.
9. Emit redacted structured logs at submission, polling, download, validation, audio, settlement, and failure boundaries.

The remote service must remain independently runnable if the central server is unavailable. Its MiniMax call must not silently fall back to LK888.

## Provider Adapter Contract

Both callers implement the same normalized internal contract, even though their storage and authentication boundaries remain independent:

```text
submit_video(request) -> provider_task_id
poll_video(provider_task_id) -> pending | succeeded | failed
retrieve_video(provider_result) -> provider_file_url
download_video(provider_file_url) -> local_media_path
validate_video(local_media_path, expected_duration) -> media_metadata
published_unit_price(model, mode, duration, resolution) -> amount | missing
```

The adapter must preserve:

- `businessTaskId`
- `providerTaskId`
- `requestedModel`
- `actualModel`
- `workflowMode`
- `duration`
- `resolution`
- `aspectRatio`
- `billingRef`
- `failureStage`

The adapter must never log an API key, Authorization header, Cookie, signed URL, or complete private media URL.

## Request Modes

### Text-to-video

- Uses `MiniMax-Hailuo-2.3`.
- Requires a non-empty prompt.
- Uses the storyboard duration, aspect ratio, and supported resolution after normalization.
- Does not send local file paths or data URLs to MiniMax.

### Image-to-video

- Uses `MiniMax-Hailuo-2.3`.
- Requires at least one publicly reachable reference image.
- Retains the existing MatrixShip reference-image role ordering.
- Rejects missing or unreachable references before provider submission.

### First/last-frame video

- Uses `MiniMax-Hailuo-02`.
- Requires exactly the validated start/end frame contract used by the storyboard mode.
- Rejects a missing end frame before provider submission.
- Does not treat an image-only result as a completed video.

## Audio Contract

- If storyboard dialogue exists, prepare the project TTS track and remux it as the only final dialogue track.
- If storyboard dialogue does not exist, preserve the MiniMax provider audio when present.
- If the provider returns no audio and no storyboard dialogue exists, keep the output silent.
- Audio replacement or remux failure is a task failure and must not be hidden as a successful video.
- Persist `audioMode`, `audioSource`, `audioStatus`, and `audioMixStatus`.

## Billing Contract

MiniMax does not provide a task-level cost field in the selected integration path. The project therefore settles successful, validated tasks against the official published unit-price table.

Settlement rules:

1. Do not precharge on submit.
2. Do not charge from a submit response.
3. Do not charge failed, cancelled, timed-out, or safety-rejected tasks.
4. Charge only after the result is downloaded and media validation succeeds.
5. Use the actual model mapping, mode, duration, and resolution to select the published unit.
6. Use a stable idempotency reference containing the service, business task ID, provider task ID, and attempt.
7. If no exact price row exists, store `awaiting_actual_cost` and do not deduct.
8. Record `billingSource=minimax_published_unit`, `actualModel`, `providerTaskId`, `amount`, and the price-table version.

The central server and remote comic generator must not settle the same business task twice. Recovery after a download failure may retry download and validation using the existing provider task, but may not submit a new provider task.

## Configuration

Each environment must define separate configuration for the two callers:

```text
MINIMAX_ENABLED=1
MINIMAX_CENTER_API_BASE=<official API base>
MINIMAX_CENTER_API_KEY=<center-only secret>
MINIMAX_COMIC_API_BASE=<official API base>
MINIMAX_COMIC_API_KEY=<comic-service-only secret>
MINIMAX_MAX_ACTIVE_TASKS=2
MINIMAX_TASK_TIMEOUT_SEC=900
MINIMAX_POLL_INTERVAL_SEC=<bounded polling interval>
```

The real values belong in environment-specific secret configuration for `dev`, `staging`, and `prod`. They must not be committed to source, test fixtures, logs, or documentation.

## Error Handling and Observability

Every provider boundary emits a structured JSON event with:

- service name
- business task ID
- provider task ID, when available
- requested and actual model
- workflow mode
- duration/resolution
- stage
- status
- retry or recovery decision
- billing reference
- redacted error code and message

User-facing errors remain short and actionable. Provider response bodies, stack traces, and context are retained only in sanitized diagnostics.

Required stages:

```text
validate
publicize_references
submit
poll
retrieve
download
validate_media
prepare_tts
remux_audio
settle_billing
complete
```

## API and Documentation

If the central server adds or exposes a new MiniMax task endpoint, it must be added to:

- `docs/openapi.yaml`
- `docs/API_REFERENCE.md`
- request and response JSON Schema validation
- `tests/test_openapi_contract.py`

The implementation must also update:

- `docs/ARCHITECTURE.md`
- `docs/DEPLOYMENT.md`
- `docs/TROUBLESHOOTING.md`
- `docs/IMPLEMENTATION.md`
- `CHANGELOG.md`

`migration.sql` is required only if the implementation adds a new database table or column. If existing state, task, ledger, and persistence-mirror structures are sufficient, the implementation must document that no migration is needed.

## Rollback

The release must preserve:

- the previous central-server source or image
- the previous remote `server.py` backup and hash
- the previous environment configuration
- the MiniMax disable switch state

Rollback sequence:

1. Set `MINIMAX_ENABLED=0`.
2. Stop new MiniMax submissions.
3. Allow existing downloads/recovery to finish or mark them for manual recovery.
4. Restore the previous central-server and remote-service versions.
5. Restart both services.
6. Verify health endpoints and confirm no new MiniMax tasks are being submitted.
7. Reconcile any `awaiting_actual_cost` records manually.

## Phase 0 Smoke Test

Before complete implementation:

1. Build a minimal provider adapter with a fake MiniMax HTTP server.
2. Run one text-to-video task through submit, poll, retrieve, download, validation, and settlement.
3. Run one first/last-frame task with fake start/end references.
4. Run one dialogue task through TTS replacement.
5. Verify failure, timeout, missing-price, and duplicate-settlement behavior.
6. Record each failure and fix in `docs/TROUBLESHOOTING.md`.

The first real MiniMax smoke test must be separately identified as a live provider call and must not be treated as proof of remote deployment.

## Verification Plan

- Unit tests for model mapping and normalized request payloads.
- Contract tests for JSON Schema and OpenAPI.
- Provider polling tests for pending, success, failure, timeout, and malformed responses.
- Media tests for download, duration, MIME type, and image-as-video rejection.
- Audio tests for TTS replacement, provider-audio preservation, silence, and remux failure.
- Billing tests for published-unit selection, missing-price hold, stable-ref idempotency, and no-charge failure paths.
- `py_compile` for touched Python files.
- Local Phase 0 smoke with the fake provider.
- Live MiniMax smoke only when the environment contains the correct service-specific key.
- Remote deployment smoke with backup hash, service status, health endpoint, port check, and rollback evidence.

## Open Implementation Constraints

- Do not change unrelated dirty worktree files.
- Do not commit API keys or generated signed URLs.
- Do not claim live provider or remote deployment success from unit tests alone.
- Recalculate all `docs/IMPLEMENTATION.md` line references before any implementation commit.
