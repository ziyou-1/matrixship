# Comic Regeneration, Duration, Preview, and Asset Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make comic-project replacement regeneration observable, size each video from the final script with a 15-second speech cap, provide a modal video preview, and force uploaded character/scene/prop references into storyboard generation.

**Architecture:** Keep the change local to `matrix_native_client.py`. Add pure planning and prompt helpers that are independently testable, feed their results into the existing comic project payloads, and add small Qt UI components around the existing `VideoPlayerBox`. The remote API contract is reused by sending duration and typed reference fields it already accepts.

**Tech Stack:** Python 3, PySide6, unittest/pytest, existing Matrix comic adapter and structured JSON logger.

## Global Constraints

- Single speech segment maximum: 15 seconds.
- Overlong scripts split at punctuation into continuous segments; recursively split until every segment is at most 15 seconds.
- Vidu may use its 16-second model slot for a speech segment of up to 15 seconds.
- `audioMode=auto` keeps provider-generated audio and never adds TTS/audio prompt fields.
- Do not restart the local client automatically.
- Do not modify old completed job JSON.
- Do not stage or commit without explicit user instruction.

---

### Task 1: Script Duration Planning and Continuous Splitting

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_replacement.py`
- Test: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Produces: `_comic_plan_script_segments(segments, max_speech_sec=15.0) -> list[dict]`.
- Produces per segment: `speechDurationSec`, `videoDurationSec`, `continuationIndex`, `continuationCount`.
- Consumed by: `VideoReplacementPage._build_job`, `_comic_project_create_payload`, `_comic_storyboard_video_payload`.

- [ ] Write failing tests proving 15 seconds is not split, overlong text is split without character loss, recursively split children remain at most 15 seconds, and indices/timeline are compact.
- [ ] Run the focused tests and verify RED.
- [ ] Implement punctuation-aware grouping using `_estimate_replacement_tts_duration_sec`; copy visual context and add explicit continuation metadata to child segments.
- [ ] Call the planner in `_build_job` after the table's final scripts have been synchronized and before project creation.
- [ ] Add `duration`, `video_duration`, and `videoDuration` to each storyboard/video request from `videoDurationSec`; keep `audio_mode=auto` free of `audio_prompt`.
- [ ] Run focused tests and verify GREEN.

### Task 2: Compact Visual Script and Typed Asset References

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_replacement.py`

**Interfaces:**
- Produces: `_comic_asset_binding_prompt(job) -> str`.
- Produces: `_comic_typed_reference_urls(job) -> dict[str, list[str]]` with `characters`, `scenes`, `props`, and `all`.
- Consumed by: `_comic_visual_prompt_text`, `_comic_storyboard_image_payload`, `_comic_storyboard_video_payload`.

- [ ] Write a failing contract test using a prompt containing an old car, showroom, OCR, global summary, and frame table.
- [ ] Assert the outgoing description contains project-library character/scene/prop binding instructions and only source action/camera/rhythm context.
- [ ] Assert image and video requests contain `character_reference_images`, `scene_reference_images`, `prop_reference_images`, and deduplicated combined references.
- [ ] Run the focused tests and verify RED.
- [ ] Replace broad line retention in `_comic_visual_prompt_text` with extraction of only labeled action, shot, camera, position, and rhythm fields when replacement assets exist.
- [ ] Prefix the compact prompt with explicit project-library binding rules and make uploaded references authoritative over conflicting source text.
- [ ] Add typed reference fields to image/video payloads while preserving start/end frames first in video reference order.
- [ ] Run focused tests and verify GREEN.

### Task 3: Observable Regeneration Buttons

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_replacement.py`
- Test: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Produces: `_comic_regeneration_click_feedback(page, segment, media_kind) -> bool`, returning false when busy after showing feedback.
- Consumed by: `regenerate_comic_frame`, `regenerate_selected_segment`.

- [ ] Write failing tests proving a busy click updates the status instead of silently returning and emits a redacted JSON-log event.
- [ ] Write an offscreen Qt test clicking each frame button and the video button, asserting the correct segment and media kind reach the handler.
- [ ] Run the focused tests and verify RED.
- [ ] Keep regeneration buttons clickable while busy; gate in the handler with visible feedback.
- [ ] Emit structured request/accepted/completed/failed events containing only job ID, project ID, segment index, media kind, and busy state.
- [ ] Ensure every completion path clears `_busy`, refreshes the table, and preserves old media on failure.
- [ ] Run focused tests and verify GREEN.

### Task 4: Non-Fullscreen Video Preview Dialog

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Produces: `ComicVideoPreviewDialog(path, parent=None)`.
- Consumed by: `ComicSegmentVideoCell._open_preview`.

- [ ] Write an offscreen failing test that opens a local validated video path, asserts the dialog is not fullscreen, stays within 82% of the available screen, and releases media on close.
- [ ] Run the focused test and verify RED.
- [ ] Build the modal dialog with a dedicated `VideoPlayerBox`, play/pause, seek, volume, and close controls.
- [ ] Make a click on the table video surface open the dialog; replace the fullscreen button action with preview action.
- [ ] Remove the widget-reparenting fullscreen implementation.
- [ ] Run focused UI tests and verify GREEN.

### Task 5: Documentation and Verification

**Files:**
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Records exact source locations and smoke-test results; no runtime interface.

- [ ] Run syntax compilation for `backend/matrix_native_client.py`.
- [ ] Run the focused replacement test modules.
- [ ] Run the existing comic/audio/media contract tests and classify any unrelated baseline failures.
- [ ] Run a fake-adapter smoke test through script planning, payload creation, typed assets, frame generation, video generation, and preview construction.
- [ ] Update `IMPLEMENTATION.md` with exact current line references after code changes.
- [ ] Record root causes, commands, pass/fail counts, rollback path, and residual model-duration risk in `TROUBLESHOOTING.md` and `CHANGELOG.md`.
- [ ] Inspect `git diff` to confirm no credentials, tokens, protected URLs, old task JSON, or unrelated files were changed.
