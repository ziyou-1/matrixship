# Comic Single Character Auto Duration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restrict comic replacement tasks to one protagonist image and delegate complete dialogue audio timing to the comic generator.

**Architecture:** Keep the existing `ComicProjectAdapter` boundary. Normalize person references to the first URL when building manual assets, remove the local dialogue-audio preparation stage, and send complete dialogue plus voice through existing storyboard payloads with remote automatic duration matching.

**Tech Stack:** Python 3, PySide6, unittest, JSON state files, remote AI Canvas comic API.

## Global Constraints

- Do not restart the local client automatically.
- Preserve legacy task JSON readability.
- Do not log credentials, tokens, or full sensitive media payloads.
- Back up project `293` state before cleanup.

---

### Task 1: Regression tests

**Files:**
- Modify: `tests/test_video_replacement.py`

**Interfaces:**
- Consumes: `_comic_project_manual_assets(job)` and `VideoReplacementPage._run_comic_project_segments(...)`.
- Produces: regression coverage for one protagonist and no local audio preparation call.

- [ ] Add a test asserting multiple legacy person URLs create exactly one `主角` asset from the first URL.
- [ ] Add a test adapter whose `prepare_dialogue_audio` raises if called, then assert a segment still reaches image and video generation.
- [ ] Run both tests and confirm they fail for the intended old behavior.

### Task 2: Minimal local implementation

**Files:**
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Consumes: existing task fields `personReferencePaths`, `personReferenceUrls`, `voiceId`, and segment `script`.
- Produces: one manual character and storyboard generation payloads containing full dialogue and voice.

- [ ] Change the person picker to a single-file picker and update visible copy to require one clear front-facing full-body image.
- [ ] Store and upload at most one person image for new tasks.
- [ ] Normalize legacy person URL arrays to their first item in `_comic_project_manual_assets`.
- [ ] Remove the `prepare_dialogue_audio` stage and all duration mutation based on pre-generated audio.
- [ ] Preserve `auto_match_audio_duration=True` and complete `audio_prompt.dialogue` in generation payloads.
- [ ] Run the targeted tests and confirm they pass.

### Task 3: Documentation and regression

**Files:**
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: final source line numbers and test results.
- Produces: traceable implementation references and rollback instructions.

- [ ] Recalculate final source line references and update `docs/IMPLEMENTATION.md`.
- [ ] Record the old multi-role and duplicate billing/TTS failure symptoms in `docs/TROUBLESHOOTING.md`.
- [ ] Record the behavior change in `CHANGELOG.md`.
- [ ] Run the full `tests.test_video_replacement` suite.

### Task 4: Project 293 cleanup

**Files:**
- Remote backup of the active comic state JSON.

**Interfaces:**
- Consumes: remote project ID `293`.
- Produces: project state containing protagonist `3`, scene `1`, prop `1`, with storyboard bindings preserved.

- [ ] Identify the active persisted state file and create a timestamped backup.
- [ ] Remove character IDs `1`, `2`, `4`, and `5` from project `293` using structured JSON parsing.
- [ ] Normalize storyboard character references to ID `3` while preserving scene and prop references.
- [ ] Read the saved project state back and verify counts and bindings.
- [ ] Do not restart the local client; restart the remote service only if remote code, rather than data alone, changes.
