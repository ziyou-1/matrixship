# Digital Human Forced Scene Background Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make uploaded digital-human scene images force a background replacement before talking-head generation.

**Architecture:** Add a small scene-composition helper around existing `lk888_image_result(..., image_urls=...)` plus a visual scene QC helper around `lk888_vision()`. Call both from `generate_digital_human()` before TTS when `scene_url` is present, then pass the composed image URL into `lk888_digital_human()` only if QC passes.

**Tech Stack:** Python unittest, PyQt UI text in `backend/matrix_native_client.py`, LK888 image generation and digital-human media task helpers.

## Global Constraints

- No hardcoded secrets.
- Scene image is optional.
- Uploaded scene image means forced background replacement.
- Scene replacement or scene-QC failure stops generation before TTS and triggers the existing refund path.
- No database migration is required.

---

### Task 1: Add Forced Scene Background Tests

**Files:**
- Modify: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Consumes: `generate_digital_human(avatar_url, script, voice_id=None, mode="std", sound_url=None, scene_url=None)`
- Produces: tests for `_compose_digital_human_scene_avatar_url(...)`

- [x] **Step 1: Write failing tests**

Add tests that run `generate_digital_human()` synchronously by patching `run_bg`, `try_charge`, `lk888_tts_voice`, `lk888_digital_human`, `_wf_download`, and `BRIDGE.payload.emit`.

- [x] **Step 2: Verify red**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_image_composes_background_before_tts tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_without_scene_skips_background_composition tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_rejects_private_scene_before_tts -v
```

Expected: at least the scene-composition tests fail because the helper and call order do not exist yet.

### Task 2: Implement Forced Scene Background

**Files:**
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Produces: `_compose_digital_human_scene_avatar_url(avatar_url, scene_url, size="1024x1536") -> str`
- Consumes: `lk888_image_result(prompt, size, image_urls)`

- [x] **Step 1: Add helper**

Create a helper that validates the scene URL, converts local avatar files to data URLs, calls `lk888_image_result()` with `[avatar_reference, scene_url]`, and returns the generated public URL.

- [x] **Step 2: Wire helper into generation**

In `generate_digital_human()`, call the helper before TTS when `scene_url` is provided. Use the returned image URL as `avatar_input` for `lk888_digital_human()`.

- [x] **Step 3: Update UI text**

Change scene upload text and status text to show forced background behavior.

- [x] **Step 4: Verify green**

Run the same targeted unittest command and ensure it passes.

### Task 3: Documentation And Verification

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`

**Interfaces:**
- Produces: updated release notes, implementation index, troubleshooting entry, and rollback scope.

- [x] **Step 1: Update docs**

Document the strong-scene behavior, failure mode, and rollback scope.

- [x] **Step 2: Compile and test**

Run:

```powershell
.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py
.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_image_composes_background_before_tts tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_without_scene_skips_background_composition tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_rejects_private_scene_before_tts -v
```

Expected: compile succeeds and all targeted tests pass.
