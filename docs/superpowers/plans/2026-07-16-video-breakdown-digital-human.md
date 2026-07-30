# Video Breakdown To Digital Human Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users send a completed video breakdown into the digital human page with extracted narration and an editable avatar description.

**Architecture:** Reuse the existing Qt `BRIDGE.payload` event pattern. `VideoBreakdownPage` emits a new `digital_human_seed` payload; `DigitalHumanPage` consumes it and fills the existing topic, avatar description, and script fields without automatically generating media.

**Tech Stack:** Python, PyQt, unittest, existing LK888 helper functions.

## Global Constraints

- Do not call remote generation automatically from the breakdown page.
- Keep the generated avatar description editable in the existing `avatar_desc` input.
- Prefer transcript text; fall back to the markdown report when transcript text is unavailable.
- Keep rollback limited to `backend/matrix_native_client.py`, tests, and docs.

---

### Task 1: Add Breakdown To Digital Human Seed Contract

**Files:**
- Modify: `tests/test_digital_human_navigation.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Produces: `_digital_human_seed_from_breakdown(analysis: dict, markdown: str) -> dict`
- Produces: `BRIDGE.payload.emit("digital_human_seed", seed)`
- Consumes: existing `VideoBreakdownPage._analysis`, `VideoBreakdownPage._markdown`, and `DigitalHumanPage.avatar_desc`.

- [ ] **Step 1: Write the failing tests**

Add tests that assert the helper extracts script/avatar description and that the Qt page receives `digital_human_seed`.

- [ ] **Step 2: Run the tests to verify failure**

Run: `.venv/bin/python -m unittest tests.test_digital_human_navigation -v`
Expected: failures for missing helper and missing event handling.

- [ ] **Step 3: Implement the minimal bridge**

Add a `生成数字人口播` button to `VideoBreakdownPage`, emit `goto_nav` plus `digital_human_seed`, add the helper, and handle the event in `DigitalHumanPage._on`.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/python -m unittest tests.test_digital_human_navigation -v`
Expected: pass.

- [ ] **Step 5: Run adjacent regression tests**

Run: `.venv/bin/python -m unittest tests.test_video_breakdown tests.test_video_replacement -v`
Expected: pass.

### Task 2: Documentation And Verification

**Files:**
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`

**Interfaces:**
- Consumes: final line numbers from `nl -ba backend/matrix_native_client.py`.

- [ ] **Step 1: Update implementation line references**

Recalculate line numbers for breakdown, digital human, and tests.

- [ ] **Step 2: Add troubleshooting note**

Document the new bridge, rollback scope, and smoke verification.

- [ ] **Step 3: Run syntax check**

Run: `.venv/bin/python -m py_compile backend/matrix_native_client.py`
Expected: exit 0.
