# Seedance Real-Person Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover comic-project storyboard video generation when official Ark Seedance rejects an authorized real-person reference image, while preserving dialogue audio/lip sync and exposing the actual fallback model in the local client.

**Architecture:** The remote AI Canvas service recognizes only the exact Ark privacy rejection and performs one recursive resubmission through the existing LK888 Kling Avatar adapter after refunding the failed Seedance charge. The returned task carries traceable fallback metadata. The local client extracts that metadata during polling, shows a specific progress/error message, and persists the requested and actual model on each segment.

**Tech Stack:** Python 3, unittest, AST-isolated remote-service tests, Qt native client, JSON task persistence, SSH deployment to `/root/AI-CanvasPro`.

## Global Constraints

- Do not weaken or bypass provider moderation.
- Trigger fallback only for `InputImageSensitiveContentDetected.PrivacyInformation` from an official Ark Seedance storyboard video submission.
- Default fallback model is `kling-avatar-image2video`; `COMIC_REAL_PERSON_VIDEO_FALLBACK_MODEL` can override or disable it.
- Refund the failed Seedance submission before separately charging the fallback model.
- Fallback at most once.
- Do not log API keys, tokens, passwords, or signed media query strings.
- Do not restart the local client.
- Back up `/root/AI-CanvasPro/server.py` before deployment and keep the backup path for rollback.

---

### Task 1: Remote Fallback Regression Tests

**Files:**
- Create: `tests/test_aicanvas_real_person_fallback.py`
- Test: `.tmp-aicanvas-server-current.py`

**Interfaces:**
- Consumes: `_submit_ai_comic_media_task(...)` from the AI Canvas server mirror.
- Produces: regression coverage for exact privacy matching, one-shot Kling Avatar retry, billing refund, and non-privacy failure behavior.

- [ ] **Step 1: Write the failing exact-privacy fallback test**

Load `_is_ark_real_person_privacy_error`, `_comic_real_person_video_fallback_model`, and `_submit_ai_comic_media_task` from the server AST with controlled stubs. Make `_ark_create_video` raise the exact Ark privacy error and assert that `_submit_comic_gateway_video_task` receives `kling-avatar-image2video`, the original first-frame fields, and the original dialogue audio fields.

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_aicanvas_real_person_fallback.AICanvasRealPersonFallbackTest.test_exact_ark_privacy_error_retries_once_with_kling_avatar -v
```

Expected: FAIL because the helper functions/fallback metadata do not exist and the current code returns an `ai-failed-*` task.

- [ ] **Step 3: Add non-privacy and disabled-fallback tests**

Assert that an unrelated Ark 400 remains failed without calling the gateway, and that an empty `COMIC_REAL_PERSON_VIDEO_FALLBACK_MODEL` disables retry.

- [ ] **Step 4: Run the module and preserve RED evidence**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_aicanvas_real_person_fallback -v
```

Expected: the fallback test fails for missing production behavior; unrelated-error behavior remains unchanged.

### Task 2: Remote One-Shot Fallback Implementation

**Files:**
- Modify: `.tmp-aicanvas-server-current.py:12910-13052`
- Test: `tests/test_aicanvas_real_person_fallback.py`

**Interfaces:**
- Produces: `_is_ark_real_person_privacy_error(error) -> bool`.
- Produces: `_comic_real_person_video_fallback_model() -> str`.
- Extends task dictionaries with `requested_model`, `actual_model`, `fallback_model`, `fallback_reason`, and `fallback_applied`.

- [ ] **Step 1: Implement exact error and configuration helpers**

Add helpers near `_submit_ai_comic_media_task` that inspect only the stable error code and read `COMIC_REAL_PERSON_VIDEO_FALLBACK_MODEL`, defaulting to `kling-avatar-image2video`. Treat an explicitly present empty environment value as disabled.

- [ ] **Step 2: Implement one-shot retry after refund**

Pop an internal `_real_person_privacy_fallback_attempted` marker before provider payload adaptation. On the exact Ark privacy error, refund the original billing context, log `comic_storyboard_video_privacy_fallback_started`, copy the original prepared parameters, set the one-shot marker, and recursively submit with the configured fallback model.

- [ ] **Step 3: Attach trace metadata and combined failure context**

Set fallback metadata on both successful and failed fallback task dictionaries, persist it, and log submitted/failed events without full signed URLs. Preserve the fallback task's provider error and add a concise privacy reason.

- [ ] **Step 4: Run focused and existing AI Canvas tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_aicanvas_real_person_fallback tests.test_aicanvas_frame_billing -v
```

Expected: all tests pass.

### Task 3: Native Client Fallback Status and Persistence

**Files:**
- Modify: `backend/matrix_native_client.py:9200-9600`
- Modify: `backend/matrix_native_client.py:10790-10855`
- Modify: `backend/matrix_native_client.py:11220-11270`
- Test: `tests/test_video_replacement.py`

**Interfaces:**
- Produces: `_comic_task_fallback_metadata(payload) -> dict`.
- Produces: `_comic_task_progress_message(payload, default_message) -> str`.
- Produces: `_comic_task_failure_message(payload) -> str`.
- Persists segment fields `requestedModel`, `actualModel`, `modelFallbackReason`, and `modelFallbackApplied`.

- [ ] **Step 1: Write failing helper tests**

Test a completed task payload with fallback metadata and assert the progress text says `Seedance 拒绝真人参考图，已切换 Kling Avatar，正在生成视频`. Test a failed fallback payload and assert the message contains both the privacy rejection and fallback provider failure.

- [ ] **Step 2: Run helper tests and verify RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_task_progress_reports_real_person_model_fallback tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_task_failure_keeps_fallback_reason -v
```

Expected: FAIL because helper functions do not exist.

- [ ] **Step 3: Implement extraction and messages**

Read snake_case and camelCase aliases from the response `data` object. Translate the exact privacy fallback into user-facing Chinese while retaining the actual fallback error for troubleshooting.

- [ ] **Step 4: Integrate polling and segment persistence**

Use the progress helper in `wait_task_result` callbacks. After a video URL is returned, persist requested/actual model metadata before download. On failure, raise the concise extracted remote error instead of the truncated whole payload. Display the actual model in the comic video table status when present.

- [ ] **Step 5: Run focused and full replacement tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement tests.test_video_replacement_v2 -v
```

Expected: all tests pass.

### Task 4: Documentation, Deployment, and Smoke Verification

**Files:**
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `CHANGELOG.md`
- Deploy mirror to: `/root/AI-CanvasPro/server.py`

**Interfaces:**
- Consumes: tested server mirror and native-client behavior from Tasks 2-3.
- Produces: traceable release notes, configuration reference, rollback record, and deployed remote behavior.

- [ ] **Step 1: Update documentation with exact line references**

Document the trigger, `COMIC_REAL_PERSON_VIDEO_FALLBACK_MODEL`, billing behavior, local status fields, tests, and rollback command path. Recalculate `IMPLEMENTATION.md` line references after source edits.

- [ ] **Step 2: Run static verification**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile .tmp-aicanvas-server-current.py backend\matrix_native_client.py tests\test_aicanvas_real_person_fallback.py tests\test_video_replacement.py
git diff --check
```

Expected: exit code 0; existing unrelated warnings, if any, are reported separately.

- [ ] **Step 3: Back up and deploy the remote service**

Verify local/remote SHA-256 before replacement. Copy remote `server.py` to a timestamped backup, upload the tested mirror, run remote `py_compile`, then restart only the 8777 AI Canvas process using the existing service start mechanism.

- [ ] **Step 4: Health check and one-segment real smoke test**

Confirm port 8777 and the public health/project API respond. Resubmit only project 294 storyboard `294001`; verify the task exposes `fallback_applied=true`, `actual_model=kling-avatar-image2video`, reaches a remote task state instead of immediate `ai-failed-*`, and eventually returns a video URL or a new explicit upstream failure.

- [ ] **Step 5: Final regression and rollback evidence**

Re-run the focused local suites after deployment. Record the remote backup path and do not restart the local client. If deployment health fails, restore the backup and restart 8777 before reporting.
