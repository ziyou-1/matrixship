# Video Breakdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one-click deep video breakdown from content collection: download, import, jump to a new breakdown page, extract frames/audio metadata, generate a temporary report, and allow local Markdown export.

**Architecture:** Keep the feature client-side in `backend/matrix_native_client.py`, reusing the existing local-browser download task, ffmpeg helper, `lk888_vision`, and `lk888_chat`. Add pure helper functions for video-file selection, ffmpeg probing, frame extraction, prompt/report building, and markdown export so they can be unit tested without launching the PySide UI.

**Tech Stack:** Python 3.12, PySide6, requests, imageio-ffmpeg/ffmpeg, pytest, existing LK888 center proxy.

## Global Constraints

- Do not hardcode API keys or secrets; continue using the existing `lk888_config()` and center `/lk888` proxy.
- Report is temporary UI state only; do not write analysis into asset library or knowledge base.
- Download still imports the video into the existing asset library through the existing download endpoint.
- OCR and audio transcription must degrade without blocking the report if optional dependencies or APIs are unavailable.
- No database migration is required.
- The current folder is not a git repository, so implementation steps cannot create commits.

---

### Task 1: Testable Breakdown Helpers

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_breakdown.py`

**Interfaces:**
- Produces: `VIDEO_EXTS: tuple[str, ...]`
- Produces: `_find_video_file_from_download(result: dict) -> str`
- Produces: `_video_breakdown_markdown(data: dict) -> str`
- Produces: `_video_breakdown_prompt(meta: dict, frame_notes: str, ocr_text: str, transcript: str) -> str`

- [ ] **Step 1: Write failing tests**

Create `tests/test_video_breakdown.py` with tests for selecting a video from a download result, refusing image-only results, and rendering a Markdown report with source link and model output.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_breakdown.py -q`
Expected: FAIL because helper functions are not defined.

- [ ] **Step 3: Implement minimal helpers**

Add pure helpers near the existing ffmpeg/video helper section in `backend/matrix_native_client.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_video_breakdown.py -q`
Expected: PASS.

### Task 2: Local Video Processing Helpers

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_breakdown.py`

**Interfaces:**
- Produces: `_probe_video(path: str) -> dict`
- Produces: `_extract_breakdown_frames(path: str, out_dir: str, max_frames: int = 16) -> list[dict]`
- Produces: `_export_audio_for_breakdown(path: str, out_dir: str) -> str`
- Produces: `_ocr_breakdown_frames(frames: list[dict]) -> dict`
- Produces: `_transcribe_breakdown_audio(audio_path: str) -> dict`

- [ ] **Step 1: Add tests for command construction and graceful degradation**

Mock subprocess or use a tiny generated local mp4 for smoke-safe coverage.

- [ ] **Step 2: Verify test failure**

Run: `python -m pytest tests/test_video_breakdown.py -q`
Expected: FAIL because processing helpers are not defined.

- [ ] **Step 3: Implement processing helpers**

Use `_ffmpeg_exe()` and `subprocess.run()`. OCR and transcription return structured disabled states when optional support is unavailable.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_video_breakdown.py -q`
Expected: PASS.

### Task 3: UI Page and Content Entry

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_breakdown.py`

**Interfaces:**
- Produces: `VideoBreakdownPage(BasePage)`
- Consumes: `BRIDGE.payload` tags `video_breakdown_start` and `goto_nav`
- Modifies: `ContentPage` to include a `分解` button.
- Modifies: `NAV` to include `("🔬 分解视频", lambda: VideoBreakdownPage())` directly after content collection.

- [ ] **Step 1: Add tests for navigation labels and ContentPage method availability**

Use static/source assertions to avoid launching full UI in headless test runs.

- [ ] **Step 2: Verify test failure**

Run: `python -m pytest tests/test_video_breakdown.py -q`
Expected: FAIL because page/button are missing.

- [ ] **Step 3: Implement UI**

Add the button, one-click download-and-jump flow, page progress UI, report display, and report download action.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_video_breakdown.py -q`
Expected: PASS.

### Task 4: Smoke Verification and Docs

**Files:**
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/superpowers/specs/2026-07-11-video-breakdown-design.md` if implementation details differ.

**Interfaces:**
- Consumes all helpers and UI from Tasks 1-3.

- [ ] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_video_breakdown.py tests/test_agent_mode_defaults.py -q`
Expected: PASS.

- [ ] **Step 2: Run syntax check**

Run: `python -m py_compile backend/matrix_native_client.py`
Expected: PASS.

- [ ] **Step 3: Run a local ffmpeg smoke check**

Generate or reuse a tiny local mp4 and call `_probe_video()` / `_extract_breakdown_frames()` without AI network calls.

- [ ] **Step 4: Update troubleshooting**

Add failures and degradation notes for download/no video/OCR/audio/AI failures.
