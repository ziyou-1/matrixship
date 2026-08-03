# MiniMax H3 Official Direct Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production-ready MiniMax official direct video generation to the central server and remote comic generator for text-to-video, image-to-video, and first/last-frame video.

**Architecture:** Implement two independent, dependency-light MiniMax clients with the same normalized request/result contract. The central server uses `MINIMAX_CENTER_API_KEY`; the remote comic generator uses `MINIMAX_COMIC_API_KEY`. Both submit, poll, retrieve, download, validate, audio-process, and settle their own tasks without LK888 fallback or cross-service proxying.

**Tech Stack:** Python `urllib`/`requests` patterns already used in the repository, `unittest`, JSON Schema/OpenAPI 3.1, existing `structured_log`, existing MatrixShip state/ledger, existing remote comic TTS/remux helpers.

## Global Constraints

- Official direct API only; do not route MiniMax through LK888.
- Text-to-video and image-to-video use `MiniMax-Hailuo-2.3`; first/last-frame uses `MiniMax-Hailuo-02`.
- Use `MINIMAX_CENTER_API_KEY` and `MINIMAX_COMIC_API_KEY`; never hardcode credentials.
- Production defaults to enabled through `MINIMAX_ENABLED=1`, with the same switch available for emergency shutdown.
- Central and remote concurrency are each limited to 2 active MiniMax tasks.
- Each task has a 900-second timeout and never auto-switches models or resubmits after a provider task ID exists.
- Charge only after successful download and media validation using the official published unit-price table.
- Failed, cancelled, timed-out, safety-rejected, and missing-price tasks are not charged.
- Dialogue uses project TTS as the final audio; no-dialogue output preserves provider audio or silence.
- All boundary logs are JSON, redacted, and include error IDs, stages, task IDs, model IDs, and billing refs.
- Do not modify unrelated dirty-worktree files.
- Recalculate `docs/IMPLEMENTATION.md` line references before any implementation commit.
- Remote deployment requires backup hash, atomic replacement, health check, port check, service status, and rollback evidence.

---

### Task 1: Build the failing Phase 0 provider-contract tests

**Files:**
- Create: `tests/test_minimax_direct.py`
- Create: `tests/test_minimax_pricing.py`

**Interfaces:**
- Tests define the public adapter behavior used by later central and remote integrations.
- The tests must not import the future implementation through test-only shims.

- [ ] **Step 1: Write the RED tests for model mapping and request normalization**

```python
from backend.utils.minimax_direct import (
    actual_model_for_mode,
    normalize_video_request,
)


def test_first_last_frame_maps_to_hailuo_02_and_keeps_two_frames():
    request = normalize_video_request(
        {
            "mode": "first_last_frame",
            "prompt": "walk through a station",
            "images": ["https://assets.test/start.png", "https://assets.test/end.png"],
            "duration": 10,
            "resolution": "768P",
        }
    )

    assert actual_model_for_mode(request["mode"]) == "MiniMax-Hailuo-02"
    assert request["images"] == [
        "https://assets.test/start.png",
        "https://assets.test/end.png",
    ]


def test_image_to_video_rejects_local_paths_and_data_urls():
    for value in ("C:\\temp\\start.png", "data:image/png;base64,abc"):
        try:
            normalize_video_request(
                {"mode": "image_to_video", "prompt": "move", "images": [value]}
            )
        except ValueError as exc:
            assert "public" in str(exc).lower()
        else:
            raise AssertionError("unreachable reference was accepted")
```

- [ ] **Step 2: Run the RED tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_direct tests.test_minimax_pricing -v
```

Expected: FAIL because `backend.utils.minimax_direct` does not exist.

- [ ] **Step 3: Add RED tests for the fake provider lifecycle**

The tests must cover:

- submit returns a provider task ID;
- two pending polls followed by success;
- retrieve returns a file URL;
- download writes bytes to a temporary file;
- failure status raises a stage-specific error;
- timeout is reported after the configured deadline.

- [ ] **Step 4: Run the lifecycle RED tests**

Run the same command and confirm the failure is caused by the missing adapter, not malformed test setup.

### Task 2: Implement the minimal direct client and published-price table

**Files:**
- Create: `backend/utils/minimax_direct.py`
- Create: `backend/utils/minimax_pricing.py`
- Modify: `tests/test_minimax_direct.py`
- Modify: `tests/test_minimax_pricing.py`

**Interfaces:**
- `normalize_video_request(payload: dict) -> dict`
- `actual_model_for_mode(mode: str) -> str`
- `MiniMaxDirectClient.submit_video(request: dict) -> str`
- `MiniMaxDirectClient.poll_video(provider_task_id: str) -> dict`
- `MiniMaxDirectClient.retrieve_video(provider_result: dict) -> str`
- `MiniMaxDirectClient.download_video(url: str, destination: Path) -> dict`
- `published_unit_price(model: str, mode: str, duration: int, resolution: str) -> Decimal | None`

- [ ] **Step 1: Implement only the normalization and model map**

The implementation must:

- accept `text_to_video`, `image_to_video`, and `first_last_frame`;
- map the first two modes to `MiniMax-Hailuo-2.3`;
- map first/last-frame to `MiniMax-Hailuo-02`;
- require a non-empty prompt;
- require HTTPS references for image modes;
- require exactly two references for first/last-frame;
- normalize duration and resolution without silently inventing unsupported values.

- [ ] **Step 2: Run the focused tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_direct tests.test_minimax_pricing -v
```

Expected: PASS for normalization and pricing tests; lifecycle tests may still be RED.

- [ ] **Step 3: Implement the dependency-injected HTTP lifecycle**

`MiniMaxDirectClient` must accept `base_url`, `api_key`, `timeout_sec`, `poll_interval_sec`, and an injectable `request_fn` so tests can use a fake provider without network access.

The client must:

- send the API key only in the Authorization header;
- never include local paths or data URLs;
- parse provider task IDs from the documented response shape;
- preserve raw provider metadata only after redaction;
- stop polling at 900 seconds;
- classify `pending`, `success`, `failed`, `cancelled`, and malformed results;
- download only HTTPS URLs;
- return media metadata needed by validation and billing.

- [ ] **Step 4: Run the full Phase 0 client tests**

Run the focused unittest command again. Expected: PASS with no network call.

- [ ] **Step 5: Refactor only after GREEN**

Remove duplicate parsing branches while preserving the test-defined contract. Re-run the same command and confirm all tests remain green.

### Task 3: Add central-server MiniMax task and billing integration

**Files:**
- Modify: `backend/central_server.py`
- Modify: `backend/.env.example`
- Create: `tests/test_minimax_central_server.py`
- Modify: `docs/openapi.yaml`
- Modify: `tests/test_openapi_contract.py`
- Modify: `docs/API_REFERENCE.md`

**Interfaces:**
- `POST /api/v1/minimax/video/generate`
- `GET /api/v1/minimax/video/tasks/{task_id}`
- Central task records must include `businessTaskId`, `providerTaskId`, `requestedModel`, `actualModel`, `mode`, `duration`, `resolution`, `billingRef`, and `status`.

- [ ] **Step 1: Write RED tests for authentication and JSON Schema validation**

Test that:

- unauthenticated generation returns 401;
- missing prompt returns 400;
- image mode with a local path returns 400;
- first/last-frame with one frame returns 400;
- a valid request reaches the injected MiniMax client;
- response fields match the OpenAPI schemas.

- [ ] **Step 2: Run the central RED tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_central_server tests.test_openapi_contract -v
```

Expected: new MiniMax tests fail because the route and runtime schema do not exist.

- [ ] **Step 3: Add environment parsing and the authenticated POST route**

Use the existing central-server authentication and route-dispatch patterns. Reject the request before provider submission when `MINIMAX_ENABLED` is false, the service key is missing, the task limit is full, or the payload schema is invalid.

Persist a provider-specific pending record under `STATE["minimax_pending_charges"]` and call `persist()` after each state transition.

- [ ] **Step 4: Add polling, retrieval, media validation, and status route**

The GET route must:

- return pending without charging;
- return failed without charging;
- download and validate success before settlement;
- return `awaiting_actual_cost` when the published price table has no exact row;
- settle using a stable ref and return the ledger metadata;
- recover an existing provider task without submitting another provider task.

- [ ] **Step 5: Add OpenAPI and runtime contract coverage**

Document request fields, response fields, error responses, and the `awaiting_actual_cost` status in `docs/openapi.yaml` and `docs/API_REFERENCE.md`. Add schema assertions to `tests/test_openapi_contract.py`.

- [ ] **Step 6: Run the central focused suite**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_central_server tests.test_openapi_contract -v
```

Expected: PASS.

### Task 4: Add the remote comic-generator MiniMax adapter

**Files:**
- Create: `tools/aicanvas_remote/minimax_direct.py`
- Modify: `tools/aicanvas_remote/server_current.py`
- Create: `tests/test_minimax_aicanvas_remote.py`

**Interfaces:**
- `MiniMaxComicAdapter.submit_storyboard_video(...) -> dict`
- `MiniMaxComicAdapter.poll_storyboard_video(...) -> dict`
- `MiniMaxComicAdapter.download_and_validate(...) -> dict`
- Existing `generate-video` task responses must retain `task_id`, `requestedModel`, `actualModel`, `audioMode`, `billingRef`, and `status`.

- [ ] **Step 1: Write RED tests for remote model selection and reference validation**

Cover:

- text-to-video selects `MiniMax-Hailuo-2.3`;
- image-to-video selects `MiniMax-Hailuo-2.3`;
- first/last-frame selects `MiniMax-Hailuo-02`;
- local paths and data URLs are rejected;
- the second frame is mandatory for first/last-frame;
- MiniMax is not silently replaced by LK888.

- [ ] **Step 2: Run the remote RED tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_aicanvas_remote -v
```

Expected: FAIL because the adapter and provider branch do not exist.

- [ ] **Step 3: Implement the standalone remote adapter**

Keep the remote adapter deployable with the single `server_current.py` artifact. Use the same normalized contract as `backend/utils/minimax_direct.py`, but do not import the central server at runtime.

Read `MINIMAX_COMIC_API_BASE`, `MINIMAX_COMIC_API_KEY`, `MINIMAX_ENABLED`, `MINIMAX_MAX_ACTIVE_TASKS`, and `MINIMAX_TASK_TIMEOUT_SEC` from the environment.

- [ ] **Step 4: Connect the adapter to the existing storyboard video path**

Extend the existing comic model catalog and the existing storyboard submit path. Preserve current storyboard task history and expose the real MiniMax provider task ID in diagnostics.

- [ ] **Step 5: Run remote adapter tests**

Run the focused unittest command again. Expected: PASS.

### Task 5: Integrate storyboard audio and success-only billing

**Files:**
- Modify: `tools/aicanvas_remote/server_current.py`
- Modify: `backend/central_server.py`
- Create: `tests/test_minimax_billing.py`
- Create: `tests/test_minimax_audio.py`

**Interfaces:**
- `settle_minimax_published_unit(...) -> dict`
- `remux_storyboard_tts_if_needed(...) -> dict`

- [ ] **Step 1: Write RED billing tests**

Test:

- submit does not charge;
- failed/cancelled/timed-out/safety-rejected tasks do not charge;
- successful validated task charges once;
- the same billing ref is idempotent;
- missing price creates `awaiting_actual_cost`;
- the ledger includes `billingSource=minimax_published_unit`, `actualModel`, `providerTaskId`, and price-table version.

- [ ] **Step 2: Run billing RED tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_billing -v
```

Expected: FAIL because MiniMax settlement is not implemented.

- [ ] **Step 3: Implement settlement using existing ledger helpers**

Do not call the old LK888 settlement functions with MiniMax records. Add a provider-specific settlement helper that uses the existing stable-ref ledger behavior and `allowArrears` policy already used for model calls.

- [ ] **Step 4: Write and run RED audio tests**

Cover:

- dialogue causes project TTS to replace provider audio;
- no dialogue preserves provider audio;
- no provider audio preserves silence;
- remux failure marks the task failed and does not settle.

- [ ] **Step 5: Implement audio behavior**

Reuse the existing remote storyboard TTS preparation and remux helpers. Persist `audioMode`, `audioSource`, `audioStatus`, and `audioMixStatus`.

- [ ] **Step 6: Run billing and audio tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_billing tests.test_minimax_audio -v
```

Expected: PASS.

### Task 6: Add environment, documentation, and Phase 0 smoke tooling

**Files:**
- Modify: `backend/.env.example`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `CHANGELOG.md`
- Create: `scripts/smoke_minimax_direct.py`
- Create: `tests/test_minimax_smoke.py`

**Interfaces:**
- `scripts/smoke_minimax_direct.py --fake` must run without secrets and exercise all three modes.
- `scripts/smoke_minimax_direct.py --live` must refuse to run unless the requested service key is present in the process environment.

- [ ] **Step 1: Write the RED smoke test**

The fake smoke must assert the sequence:

```text
validate -> submit -> poll -> retrieve -> download -> validate_media -> settle_billing -> complete
```

It must also assert timeout, missing-price, duplicate-settlement, and dialogue remux failure behavior.

- [ ] **Step 2: Run the RED smoke test**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_smoke -v
```

Expected: FAIL until the provider, billing, and audio pieces are wired together.

- [ ] **Step 3: Implement the fake-provider smoke runner**

The runner must use deterministic fake URLs and bytes, redact all URLs in logs, and never call MiniMax when `--fake` is selected.

- [ ] **Step 4: Run Phase 0**

Run:

```powershell
.\.venv-win\Scripts\python.exe scripts\smoke_minimax_direct.py --fake
```

Expected: a success summary with all three modes and no real provider cost.

- [ ] **Step 5: Record failures and operational guidance**

Add only observed failures and their fixes to `docs/TROUBLESHOOTING.md`. Update `CHANGELOG.md` with the direct integration, exact billing source, environment variables, and rollback switch.

### Task 7: Full verification and direct production release

**Files:**
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/TROUBLESHOOTING.md`

- [ ] **Step 1: Run focused tests and compile checks**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_direct tests.test_minimax_pricing tests.test_minimax_central_server tests.test_minimax_aicanvas_remote tests.test_minimax_billing tests.test_minimax_audio tests.test_minimax_smoke tests.test_openapi_contract -v
.\.venv-win\Scripts\python.exe -m py_compile backend\utils\minimax_direct.py backend\utils\minimax_pricing.py backend\central_server.py tools\aicanvas_remote\minimax_direct.py tools\aicanvas_remote\server_current.py
git diff --check
```

Expected: all focused tests pass; compile and diff checks are clean.

- [ ] **Step 2: Run live MiniMax smoke separately for each service key**

Run only with the environment explicitly configured:

```powershell
.\.venv-win\Scripts\python.exe scripts\smoke_minimax_direct.py --live --service center
.\.venv-win\Scripts\python.exe scripts\smoke_minimax_direct.py --live --service comic
```

Record provider task IDs, model IDs, statuses, download validation, and final billing refs without logging secrets or full signed URLs.

- [ ] **Step 3: Recalculate implementation line references**

After all source edits, use `rg -n` to recalculate every MiniMax entry in `docs/IMPLEMENTATION.md`. Do not copy stale line numbers from this plan.

- [ ] **Step 4: Deploy with a rollback checkpoint**

Before deployment:

- save the previous central-server source/image identifier;
- copy and hash the remote `server.py`;
- verify both service-specific environment variables are present without printing values;
- set `MINIMAX_ENABLED=1`.

Deploy atomically, restart the affected service, verify `/api/health`, remote login/health, process status, and port listeners, then run the post-deploy fake and live smoke checks.

- [ ] **Step 5: Verify rollback path**

Confirm that setting `MINIMAX_ENABLED=0` blocks new MiniMax submissions while preserving task diagnostics and existing recovery records. Record the exact restore command and backup hash in `docs/TROUBLESHOOTING.md`.

- [ ] **Step 6: Commit only the scoped implementation**

Stage only the MiniMax source, tests, environment example, docs, and smoke script. Do not stage unrelated dirty-worktree files. Before committing, verify `docs/IMPLEMENTATION.md` line references and `git diff --cached --check`.
