# Video Replacement Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the full video replacement chain prefer reference-video models, avoid hard visual-QC blocks, run FaceFusion only for uploaded-person digital-human clips, and show truthful progress/errors.

**Architecture:** Keep the existing single-client PyQt/Python architecture. Add small helpers in `backend/matrix_native_client.py` so model selection, QC policy, FaceFusion policy, and progress summaries are testable without launching the UI.

**Tech Stack:** Python 3.12, unittest, PyQt, local JSON replacement jobs, LK888 media task proxy, optional local FaceFusion.

## Global Constraints

- Do not hardcode API keys or tokens.
- Preserve structured error IDs and existing task JSON format.
- Remote visual mismatch should become an operator warning, not a hard block.
- Media validity and audio validity remain hard gates.
- Local FaceFusion must stay bounded by `FACEFUSION_TIMEOUT_SEC`.

---

### Task 1: Reference Model Routing

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Produces: `_replacement_model_candidates(job) -> list[str]`
- Produces: `_build_hybrid_video_edit_request(job, segment, source_video_url) -> tuple[str, dict]`

- [ ] Write tests proving the hybrid non-talking route defaults to `viduq3-turbo-cankaosheng`, includes product/person/source references, and exposes fallback candidates.
- [ ] Run the new tests and confirm they fail before implementation.
- [ ] Implement the minimal model candidate helper and request payload change.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Softer Visual QC

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Produces: `_replacement_visual_qc_blocks(job) -> bool`

- [ ] Write tests proving media/audio failures still fail, while `product_mismatch`, `face_mismatch`, and `visual_qc_failed` become warnings by default.
- [ ] Run the tests and confirm failure.
- [ ] Implement default warning behavior with an opt-in strict switch.
- [ ] Run focused tests and confirm pass.

### Task 3: Digital-Human FaceFusion Policy

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Produces: `_replacement_enable_digital_human_facefusion(job, segment) -> bool`

- [ ] Write tests proving uploaded-person talking clips run FaceFusion after digital-human download, while non-talking clips do not unless explicitly enabled.
- [ ] Run the tests and confirm failure.
- [ ] Implement FaceFusion after digital-human download with timeout-preserving fallback to the original digital-human video.
- [ ] Run focused tests and confirm pass.

### Task 4: Truthful Status And Errors

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_replacement_v2.py`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `_replacement_segment_status_text(job, segment) -> str`
- Produces: `remoteError`, `remoteErrorId`, `qcWarnings`, `fallbackReason` fields in segment JSON when applicable.

- [ ] Write tests proving fallback does not erase the original remote error and status text includes segment index, stage, elapsed time, model, warnings, and error IDs.
- [ ] Run the tests and confirm failure.
- [ ] Implement status helper and preserve remote errors.
- [ ] Update docs with line references and rollback notes.
- [ ] Run full replacement test suites and Python compile checks.
