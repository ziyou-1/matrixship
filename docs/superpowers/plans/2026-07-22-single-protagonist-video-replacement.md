# 单主角整身同款替换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace exactly one source-video protagonist with the uploaded person's full appearance while preserving the source action, camera, timing, and audio.

**Architecture:** Keep the existing local JSON job and serial segment pipeline. Add a planning-stage `principalActor` record generated from source frames, replace the source-video request adapter with a strict `happyhorse-video-edit` adapter, and make a missing/invalid upstream video-edit contract a hard failure rather than a reference-video fallback.

**Tech Stack:** Python 3.12, existing PySide6 UI, Pillow, ffmpeg, LK888 vision/media proxy, `unittest`, JSON structured logging.

## Global Constraints

- Only one protagonist is supported in this release.
- Accept one to three authorized person-reference images, with one full-body image required.
- Preserve source movement, camera, timing, dialogue, and audio; replace the protagonist's complete visual appearance.
- Send only remote-fetchable HTTPS source-video and reference-image URLs to LK888.
- Do not silently fall back to a reference-to-video model when source-video editing fails.
- Do not add local deep-learning weights or hard-code credentials.
- New errors must use `json_log()` and stable error IDs; task JSON must remain recoverable after restart.
- Set `VIDEO_REPLACE_PRINCIPAL_REPLACEMENT=0` to roll back new tasks to the existing reference-video route.

---

### Task 1: Validate the LK888 source-video editing contract

**Files:**
- Create: `tools/smoke_principal_video_edit.py`
- Modify: `docs/TROUBLESHOOTING.md`
- Test: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Consumes: existing session-backed `/lk888/v1/skills/models` and `/lk888/v1/media/generate` routes.
- Produces: `run_principal_video_edit_smoke(source_url, person_url) -> {"ok": bool, "model": str, "taskId": str, "error": str}`.

- [ ] **Step 1: Write the failing request-shape test**

```python
def test_principal_video_edit_payload_keeps_every_source_video_alias(self):
    model, payload = client._build_principal_video_edit_request(
        {"personReferenceUrls": ["https://cdn.example/person.jpg"]},
        {"duration": 8, "prompt": "replace protagonist"},
        "https://cdn.example/source.mp4",
    )
    assert model == "happyhorse-video-edit"
    assert payload["video_url"] == "https://cdn.example/source.mp4"
    assert payload["video_urls"] == ["https://cdn.example/source.mp4"]
    assert payload["reference_video"] == "https://cdn.example/source.mp4"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `./.venv-win/Scripts/python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_video_edit_payload_keeps_every_source_video_alias -v`

Expected: FAIL because `_build_principal_video_edit_request` does not exist.

- [ ] **Step 3: Add the no-secret smoke helper**

```python
def run_principal_video_edit_smoke(source_url, person_url):
    model, payload = _build_principal_video_edit_request(
        {"personReferenceUrls": [person_url], "resolution": "720p", "aspectRatio": "9:16"},
        {"duration": 3, "prompt": "replace one subject"},
        source_url,
    )
    task_id = lk888_media_task(model, payload, ["mp4", "mov", "webm"], tries=1)
    return {"ok": bool(task_id), "model": model, "taskId": str(task_id)}
```

The command-line wrapper must accept optional `--source-url` and `--person-url`. When omitted, it must scan the newest local `video_replacements/*/replacement_job.json`, select the first remote-fetchable `sourceSegmentUrl` and authorized `modelFaceUrl`/`faceSourceUrls` pair, refuse loopback URLs, print only status/model/task ID, and exit non-zero on an upstream contract failure. It must never print the selected URLs.

- [ ] **Step 4: Run the smoke script with two existing authorized public URLs**

Run: `./.venv-win/Scripts/python.exe tools/smoke_principal_video_edit.py`

Expected: `ok=true` and a valid LK888 task result URL, or a documented upstream schema failure with no code fallback.

- [ ] **Step 5: Record the exact observed result**

Add one dated entry to `docs/TROUBLESHOOTING.md` stating the accepted source-video field combination, model, duration, and sanitized failure behavior.

### Task 2: Add principal-actor extraction and full-body reference validation

**Files:**
- Modify: `backend/matrix_native_client.py:VideoReplacementPage.generate_plan`, `backend/matrix_native_client.py:VideoReplacementPage.pick_face`, `backend/matrix_native_client.py:VideoReplacementPage.start_generation`
- Modify: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Produces: `_extract_replacement_principal_actor(source_path, analysis, out_dir) -> dict`.
- Produces: `_validate_person_reference_paths(paths) -> list[str]`.
- Persists: `job["principalActor"]`, `job["personReferencePaths"]`, `job["personReferenceUrls"]`, `job["principalReplacementMode"]`.

- [ ] **Step 1: Write failing extraction tests**

```python
def test_principal_actor_extractor_crops_the_vision_selected_frame(self):
    # Mock six source frames and a structured LK888 vision response with bbox 0..1000.
    actor = client._extract_replacement_principal_actor("source.mp4", {}, temp_dir)
    self.assertEqual(actor["status"], "detected")
    self.assertTrue(os.path.isfile(actor["previewPath"]))
    self.assertEqual(actor["bestFrameIndex"], 2)

def test_person_reference_validation_requires_a_full_body_image(self):
    with self.assertRaisesRegex(RuntimeError, "person_reference_full_body_required"):
        client._validate_person_reference_paths([])
```

- [ ] **Step 2: Run these tests and verify failure**

Run: `./.venv-win/Scripts/python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_actor_extractor_crops_the_vision_selected_frame tests.test_video_replacement_v2.VideoReplacementV2Test.test_person_reference_validation_requires_a_full_body_image -v`

Expected: FAIL with missing helper errors.

- [ ] **Step 3: Implement minimum extractor and validation**

```python
def _extract_replacement_principal_actor(source_path, analysis, out_dir):
    frames = _extract_breakdown_frames(source_path, os.path.join(out_dir, "principal_actor"), 6)
    response = lk888_vision(PRINCIPAL_ACTOR_PROMPT, [_image_data_url(f["path"]) for f in frames], max_tokens=500)
    actor = _parse_principal_actor_response(response, frames)
    return _crop_principal_actor_preview(actor, frames, out_dir)

def _validate_person_reference_paths(paths):
    selected = [str(path) for path in (paths or []) if path and os.path.isfile(path)][:3]
    if not selected:
        raise RuntimeError("person_reference_full_body_required")
    return selected
```

The parser must clamp normalized boxes, reject malformed model JSON, return `status="manual_required"` when confidence is below the configured threshold, and log model failures with `video_replace_principal_actor_extract_failed`.

- [ ] **Step 4: Update UI inputs and task creation**

Change only the existing person-reference controls: explain that 1-3 authorized full-body images are accepted, show detected main-actor preview/status, and block start until a person reference and `principalActor.status in {"detected", "manual"}` exist. Preserve legacy face fields when reading old jobs.

- [ ] **Step 5: Run focused tests**

Run: `./.venv-win/Scripts/python.exe -m unittest tests.test_video_replacement_v2 -k principal -v`

Expected: PASS.

### Task 3: Route principal replacement through strict source-video editing

**Files:**
- Modify: `backend/matrix_native_client.py:_replacement_model_candidates`
- Modify: `backend/matrix_native_client.py:_build_hybrid_video_edit_request`
- Modify: `backend/matrix_native_client.py:_replacement_remote_video_payload_for_model`
- Modify: `backend/matrix_native_client.py:_run_hybrid_non_talking_segment`
- Modify: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Produces: `_principal_replacement_enabled(job) -> bool`.
- Produces: `_build_principal_video_edit_request(job, segment, source_video_url) -> tuple[str, dict]`.
- Error codes: `principal_video_edit_unavailable`, `principal_video_edit_failed`, `principal_source_actor_required`.

- [ ] **Step 1: Write failing source-video route tests**

```python
def test_principal_route_sends_source_video_to_happyhorse(self):
    job = {"principalReplacementMode": "source_video_edit", "personReferenceUrls": ["https://x/person.jpg"]}
    model, payload = client._build_hybrid_video_edit_request(job, {"duration": 8}, "https://x/source.mp4")
    self.assertEqual(model, "happyhorse-video-edit")
    self.assertEqual(payload["video_urls"], ["https://x/source.mp4"])

def test_principal_route_does_not_strip_source_video_fields(self):
    payload = {"video_url": "https://x/source.mp4", "video_urls": ["https://x/source.mp4"], "image_urls": ["https://x/person.jpg"]}
    self.assertIn("video_url", client._replacement_remote_video_payload_for_model(payload, "happyhorse-video-edit"))

def test_principal_route_does_not_fallback_to_reference_models(self):
    self.assertEqual(client._replacement_model_candidates({"principalReplacementMode": "source_video_edit"}), ["happyhorse-video-edit"])
```

- [ ] **Step 2: Run tests and verify failure**

Run: `./.venv-win/Scripts/python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_route_sends_source_video_to_happyhorse tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_route_does_not_strip_source_video_fields tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_route_does_not_fallback_to_reference_models -v`

Expected: FAIL because the current route strips `source_video_url` and selects reference-video candidates.

- [ ] **Step 3: Implement strict request adapter**

```python
def _build_principal_video_edit_request(job, segment, source_video_url):
    source = _require_remote_media_url(source_video_url, "principal_source_video_required")
    refs = _require_remote_media_urls(job.get("personReferenceUrls"), "principal_person_reference_required")
    return "happyhorse-video-edit", {
        "prompt": _build_principal_replacement_prompt(job, segment),
        "video_url": source,
        "video_urls": [source],
        "reference_video": source,
        "image_urls": refs,
        "params": {"video_url": source, "duration": _segment_duration(segment), "resolution": "720P", "aspect_ratio": "9:16"},
    }
```

`_replacement_remote_video_payload_for_model()` must only strip local metadata. For the principal route it must preserve every source video alias. `_run_hybrid_non_talking_segment()` must emit a `principal_video_edit` stage, persist `remoteRequestFields`, and fail the segment when the one allowed model fails.

- [ ] **Step 4: Run source-route and regression tests**

Run: `./.venv-win/Scripts/python.exe -m unittest tests.test_video_replacement_v2 tests.test_video_replacement -v`

Expected: PASS, except documented pre-existing timeout tests run separately with a bounded timeout.

### Task 4: Add quality gates, configuration, documentation, and restart verification

**Files:**
- Modify: `backend/matrix_native_client.py:_run_replacement_visual_qc`, `_run_replacement_segment_qc`
- Modify: `backend/.env.example`, `backend/.env.prod`
- Modify: `docs/ARCHITECTURE.md`, `docs/API_REFERENCE.md`, `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`, `docs/IMPLEMENTATION.md`, `CHANGELOG.md`
- Test: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Adds visual QC fields `principalReplacementMatch`, `otherSubjectsPreserved`, `motionPreserved`.
- Adds configuration `VIDEO_REPLACE_PRINCIPAL_REPLACEMENT`, `VIDEO_REPLACE_PRINCIPAL_MODEL`, `VIDEO_REPLACE_PRINCIPAL_MIN_CONFIDENCE`.

- [ ] **Step 1: Write failing QC and configuration tests**

```python
def test_principal_visual_qc_requires_replacement_and_other_subject_preservation(self):
    result = client._parse_principal_visual_qc('{"principalReplacementMatch":false,"otherSubjectsPreserved":true,"motionPreserved":true}')
    self.assertFalse(result["ok"])
    self.assertEqual(result["code"], "principal_replacement_mismatch")

def test_principal_replacement_is_disabled_by_explicit_rollback_flag(self):
    with mock.patch.dict(os.environ, {"VIDEO_REPLACE_PRINCIPAL_REPLACEMENT": "0"}, clear=False):
        self.assertFalse(client._principal_replacement_enabled({}))
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `./.venv-win/Scripts/python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_visual_qc_requires_replacement_and_other_subject_preservation tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_replacement_is_disabled_by_explicit_rollback_flag -v`

Expected: FAIL with missing helpers.

- [ ] **Step 3: Implement QC and configuration**

Extend the visual-QC JSON prompt only for `principalReplacementMode="source_video_edit"`. A failed principal replacement is a hard block; unavailable visual QC is `deferred` and requires manual review. Add environment documentation and do not place tokens or model paths in example files.

- [ ] **Step 4: Update production documentation and line references**

Document source-video request aliases, task JSON fields, health/rollback behavior, the exact feature flag, smoke command, and the risks of model-side multiple-person mistakes. Recalculate changed `docs/IMPLEMENTATION.md` line references before any commit.

- [ ] **Step 5: Verify and restart**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement_v2.py
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2 tests.test_video_replacement -v
```

Then restart the local client only, check `http://127.0.0.1:9080/api/health` and `http://127.0.0.1:9081/api/health`, and verify the page displays the full-body reference requirement and source-video principal-edit stage.

## Plan Self-Review

- Spec coverage: Tasks 1-4 cover contract validation, actor extraction, person references, strict source-video generation, quality gates, UI, observability, rollback, docs, tests, and restart.
- Placeholder scan: no deferred implementation tasks or unspecified interfaces remain; actual API field aliases and errors are named.
- Type consistency: all later tasks consume `principalActor`, `personReferenceUrls`, `principalReplacementMode`, `_principal_replacement_enabled()`, and `_build_principal_video_edit_request()` as defined above.
