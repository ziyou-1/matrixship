# Video Replacement Action Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional action-control switch to video replacement so source-video frames can guide pose, blocking, framing, and camera rhythm without imposing a total source-video duration limit.

**Architecture:** Keep the existing `hybrid_v2` flow in `backend/matrix_native_client.py`. The UI persists `actionControlEnabled`; non-talking replacement segments extract source action frames every 2 seconds, upload them as temporary image assets, append them to the remote reference list, and fall back to the existing standard remote path if extraction or upload fails.

**Tech Stack:** Python 3.12, unittest, PySide6/PyQt-compatible widgets, ffmpeg, LK888 media task proxy, local JSON replacement jobs.

## Global Constraints

- Do not hardcode API keys or tokens.
- Default behavior must remain unchanged unless the user enables the new action-control switch.
- No database migration is needed.
- Keep total video duration unrestricted in replacement planning; generation remains segmented.
- Segment duration remains 8 seconds unless the existing caller passes another value.
- Action frames are guidance for motion, pose, position, framing, and camera only; they are not identity references.
- Extract action frames every 2 seconds, with at most 4 frames per segment.
- If action-frame extraction or upload fails, continue with the existing remote generation path and record a warning in the segment.
- Existing retry and manual-review behavior remains intact.
- Tests and documentation must be updated before final verification.

---

### Task 1: Tests For Action-Control Request Inputs

**Files:**
- Modify: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Consumes: `_build_hybrid_video_edit_request(job, segment, source_video_url)`
- Produces test coverage for action-frame references and prompt wording.

- [ ] Add a test that `actionFrameUrls` are appended after product/person/scene references when `actionControlEnabled=True`.
- [ ] Add assertions that the prompt says action frames are only motion/pose/framing/camera references and not identity references.
- [ ] Run the focused test and verify it fails before implementation.

### Task 2: Tests For Duration Planning

**Files:**
- Modify: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Consumes: `_build_hybrid_replacement_plan(analysis, duration, segment_seconds=8)`

- [ ] Add a test that a 180-second video builds 23 replacement segments instead of failing with `video_replace_duration_exceeded`.
- [ ] Run the focused test and verify it fails before implementation.

### Task 3: Tests For Extraction/Upload Fallback

**Files:**
- Modify: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Consumes: `_run_hybrid_non_talking_segment(job, segment)`
- Produces task JSON fields `actionFramePaths`, `actionFrameUrls`, and `actionControlWarning`.

- [ ] Add a test that enabled action control extracts and uploads action frames before remote generation.
- [ ] Add a test that extraction/upload failure does not fail the segment and records a warning.
- [ ] Run focused tests and verify they fail before implementation.

### Task 4: Implementation

**Files:**
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Produces: `_replacement_action_control_enabled(job)`
- Produces: `_extract_replacement_action_frames(video_path, segment, out_dir, interval_sec=2.0, max_frames=4)`
- Produces: `_prepare_replacement_action_frame_refs(job, segment, out_dir)`

- [ ] Add the UI checkbox `self.action_control`.
- [ ] Persist `actionControlEnabled` in `_build_job()` and `start_generation()`.
- [ ] Remove the total-duration hard gate from `_build_hybrid_replacement_plan()`.
- [ ] Extract and upload action frames only when `actionControlEnabled=True`.
- [ ] Append uploaded action-frame URLs to `_build_hybrid_video_edit_request()` references.
- [ ] Add prompt wording that action frames are not identity references.

### Task 5: Documentation And Verification

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`

- [ ] Document the new switch, job fields, fallback behavior, and no-total-duration policy.
- [ ] Recalculate touched line numbers in `docs/IMPLEMENTATION.md`.
- [ ] Run focused tests, full replacement V2 tests, legacy replacement tests, and Python compile.
- [ ] Report rollback path: disable the UI switch or restore the previous code snapshot.
