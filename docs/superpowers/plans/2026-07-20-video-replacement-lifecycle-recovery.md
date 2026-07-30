# Video Replacement Lifecycle Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover stale local video replacement jobs after client restart and make failed-segment retry clear old false blocking fields before rerun.

**Architecture:** Keep the existing local JSON job store. Add small deterministic helpers in `backend/matrix_native_client.py` so startup recovery and retry cleanup can be tested without launching Qt. Reuse `_save_replacement_job()` for atomic writes and preserve raw error IDs for traceability.

**Tech Stack:** Python 3.12, `unittest`, local `replacement_job.json`, PyQt client runtime.

## Global Constraints

- Do not hardcode API keys, tokens, or database connection strings.
- Keep errors observable through structured logs and persisted job JSON.
- Do not delete user assets or generated successful segment files during recovery.
- Do not clear hard drift blocks such as `visual_drift_retry_exhausted`, `visual_drift_blocked`, or `topic_mismatch`.
- This export has no `.git` repository at the workspace root, so commit steps are documented but cannot be executed here.

---

### Task 1: Stale Running Job Recovery

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_replacement_v2.py`
- Docs: `docs/TROUBLESHOOTING.md`, `docs/IMPLEMENTATION.md`, `CHANGELOG.md`

**Interfaces:**
- Produces: `_recover_stale_replacement_job(job, now=None) -> dict`
- Produces: `recover_stale_video_replacement_jobs(base_dir=None, now=None) -> dict`

- [ ] Write failing tests proving a job with `status="running"` and no active owner becomes `partial` when some segments are `done` and others are stale in-progress.
- [ ] Write failing tests proving a job with no successful segments becomes `failed`.
- [ ] Run the focused tests and confirm the new tests fail before implementation.
- [ ] Implement helper-based recovery that marks stale in-progress segments as `failed`, preserves done segments, and records `recoveredAt`, `recoveryReason`, and `error`.
- [ ] Wire recovery into `setup_env()` after temp cleanup.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Retry Cleanup For Legacy False Blocks

**Files:**
- Modify: `backend/matrix_native_client.py`
- Test: `tests/test_video_replacement_v2.py`
- Docs: `docs/TROUBLESHOOTING.md`, `docs/IMPLEMENTATION.md`, `CHANGELOG.md`

**Interfaces:**
- Produces: `_prepare_replacement_segment_for_retry(segment) -> dict`

- [ ] Write failing tests proving old `role_mismatch`, `structure_mismatch`, and person-background `reference_mismatch` failures are cleaned before retry and converted to `qcWarnings`.
- [ ] Write failing tests proving hard drift blocks are retained and not silently reclassified.
- [ ] Run the focused tests and confirm the new tests fail before implementation.
- [ ] Implement minimal retry preparation and call it from `retry_failed_segments()`.
- [ ] Run the focused tests and confirm they pass.

### Task 3: Verification And Documentation

**Files:**
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: helpers from Tasks 1 and 2.
- Produces: updated operator docs with rollback and verification notes.

- [ ] Run `.venv\Scripts\python.exe -m unittest tests.test_video_replacement_v2 -v`.
- [ ] Run `.venv\Scripts\python.exe -m py_compile backend/matrix_native_client.py`.
- [ ] Recalculate line references for `backend/matrix_native_client.py` and `tests/test_video_replacement_v2.py` in `docs/IMPLEMENTATION.md`.
- [ ] Update `docs/TROUBLESHOOTING.md` with smoke-test findings and rollback notes.
- [ ] Update `CHANGELOG.md` with lifecycle recovery and retry cleanup notes.
