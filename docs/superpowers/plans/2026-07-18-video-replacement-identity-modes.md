# Video Replacement Identity Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fast, standard, and high identity modes to video replacement so standard mode is the default and uploaded person photos no longer automatically trigger local FaceFusion.

**Architecture:** Keep the existing single-file PyQt implementation in `backend/matrix_native_client.py`, matching current project style. Add small helper functions for identity mode resolution so tests can exercise behavior without launching the UI. Preserve old `enableFaceFusion` tasks by mapping them to high mode when `identityMode` is absent.

**Tech Stack:** Python 3.12, unittest, PyQt widgets, local JSON replacement jobs, LK888 media task proxy, optional local FaceFusion.

## Global Constraints

- Do not hardcode API keys or tokens.
- Do not add database tables or migrations for this feature.
- Default mode must be `standard`.
- `fast` and `standard` must not run local FaceFusion.
- `high` is the only mode that runs local FaceFusion.
- Media validity and audio validity remain hard gates.
- Visual mismatches default to `review_warning` unless `VIDEO_REPLACE_STRICT_VISUAL_QC=1`.
- Existing tasks with `identityMode` use that value.
- Existing tasks without `identityMode` and with `enableFaceFusion=true` behave as `high`.
- Existing tasks without `identityMode` and without `enableFaceFusion=true` behave as `standard`.
- This workspace is not a Git repository; replace commit steps with local verification and, before production rollout, a timestamped backup/snapshot.

---

## File Structure

- `backend/matrix_native_client.py`
  - Add identity mode constants/helpers near `_replacement_enable_facefusion`.
  - Update FaceFusion enablement helpers.
  - Update UI controls in `VideoReplacementPage.__init__`.
  - Update `_build_job()` and `start_generation()` to read and persist `identityMode`.
  - Update FaceFusion timeout display copy.
- `tests/test_video_replacement_v2.py`
  - Replace old auto-FaceFusion tests with explicit identity mode tests.
  - Update non-talking and talking segment tests to require `identityMode=high` before FaceFusion.
  - Update UI/source-string tests for the new mode selector.
- `docs/ARCHITECTURE.md`
  - Update replacement generation boundary to describe three modes and standard default.
- `docs/API_REFERENCE.md`
  - Document `identityMode` in replacement job JSON.
- `docs/DEPLOYMENT.md`
  - Update environment variable descriptions around FaceFusion and rollback.
- `docs/TROUBLESHOOTING.md`
  - Update FaceFusion timeout guidance and mode descriptions.
- `docs/IMPLEMENTATION.md`
  - Recalculate all touched `backend/matrix_native_client.py#L...` and `tests/test_video_replacement_v2.py#L...` references.
- `CHANGELOG.md`
  - Add this behavior change and rollback note.

---

### Task 1: Identity Mode Helper

**Files:**
- Modify: `tests/test_video_replacement_v2.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Produces: `_replacement_identity_mode(job: dict | None = None) -> str`
- Produces: `_replacement_identity_mode_label(mode: str) -> str`
- Updates: `_replacement_enable_facefusion(job: dict | None = None) -> bool`
- Updates: `_replacement_enable_digital_human_facefusion(job: dict | None = None, segment: dict | None = None) -> bool`

- [ ] **Step 1: Replace the old auto-enable FaceFusion test with failing identity mode tests**

In `tests/test_video_replacement_v2.py`, replace `test_uploaded_person_enables_facefusion_without_env_opt_in` with:

```python
    def test_identity_mode_defaults_to_standard_and_uploaded_person_does_not_enable_facefusion(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            job = {
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
                "faceSourceUrls": ["https://x/f1.png", "https://x/f2.png", "https://x/f3.png"],
            }

            self.assertEqual(self.client._replacement_identity_mode(job), "standard")
            self.assertFalse(self.client._replacement_enable_facefusion(job))

    def test_identity_mode_high_enables_facefusion_and_old_jobs_remain_compatible(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(self.client._replacement_enable_facefusion({
                "identityMode": "high",
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }))
            self.assertTrue(self.client._replacement_enable_facefusion({
                "enableFaceFusion": True,
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }))
            self.assertFalse(self.client._replacement_enable_facefusion({
                "identityMode": "standard",
                "enableFaceFusion": True,
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }))
            self.assertFalse(self.client._replacement_enable_facefusion({
                "identityMode": "high",
                "noPersonMode": True,
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }))

    def test_digital_human_facefusion_only_runs_in_high_identity_mode(self):
        segment = {"segmentType": "talking"}
        with mock.patch.dict(os.environ, {"VIDEO_REPLACE_DIGITAL_HUMAN_FACEFUSION": "1"}, clear=True):
            self.assertFalse(self.client._replacement_enable_digital_human_facefusion({
                "identityMode": "standard",
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }, segment))
            self.assertTrue(self.client._replacement_enable_digital_human_facefusion({
                "identityMode": "high",
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }, segment))
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_identity_mode_defaults_to_standard_and_uploaded_person_does_not_enable_facefusion \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_identity_mode_high_enables_facefusion_and_old_jobs_remain_compatible \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_facefusion_only_runs_in_high_identity_mode -v
```

Expected: fail because `_replacement_identity_mode` does not exist and uploaded person currently enables FaceFusion.

- [ ] **Step 3: Implement the minimal identity helpers**

In `backend/matrix_native_client.py`, replace `_replacement_enable_facefusion()` and `_replacement_enable_digital_human_facefusion()` with:

```python
_REPLACEMENT_IDENTITY_MODES = ("fast", "standard", "high")


def _replacement_identity_mode(job=None):
    job = job or {}
    raw = str(job.get("identityMode") or "").strip().lower()
    if raw in _REPLACEMENT_IDENTITY_MODES:
        return raw
    if job.get("enableFaceFusion") is True or str(job.get("enableFaceFusion") or "").strip().lower() in ("1", "true", "yes", "on"):
        return "high"
    return "standard"


def _replacement_identity_mode_label(mode):
    mode = str(mode or "").strip().lower()
    if mode == "fast":
        return "快速模式"
    if mode == "high":
        return "高一致模式"
    return "标准模式"


def _replacement_enable_facefusion(job=None):
    job = job or {}
    if _replacement_no_person_mode(job):
        return False
    return _replacement_identity_mode(job) == "high"


def _replacement_enable_digital_human_facefusion(job=None, segment=None):
    job = job or {}
    segment = segment or {}
    if _replacement_no_person_mode(job):
        return False
    if segment.get("segmentType") != "talking":
        return False
    if not (job.get("faceSourcePaths") or []):
        return False
    return _replacement_identity_mode(job) == "high"
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the same command from Step 2.

Expected: all three tests pass.

- [ ] **Step 5: Run adjacent FaceFusion helper tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_facefusion_preflight_requires_bin_models_and_license \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_facefusion_runs_without_shell_and_keeps_target_reference \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_facefusion_timeout_is_configurable_and_shorter_than_old_default -v
```

Expected: pass.

---

### Task 2: Segment Execution Uses Identity Mode

**Files:**
- Modify: `tests/test_video_replacement_v2.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Consumes: `_replacement_identity_mode(job) -> str`
- Consumes: `_replacement_enable_facefusion(job) -> bool`
- Consumes: `_replacement_enable_digital_human_facefusion(job, segment) -> bool`
- Produces: non-talking and talking execution that only runs FaceFusion in `identityMode=high`

- [ ] **Step 1: Update non-talking tests to express the new modes**

In `tests/test_video_replacement_v2.py`, rename `test_non_talking_segment_can_opt_into_facefusion_by_env` to `test_non_talking_segment_runs_facefusion_only_in_high_identity_mode`.

In that test's `job`, add:

```python
            "identityMode": "high",
            "enableFaceFusion": True,
```

Remove `mock.patch.dict(os.environ, {"VIDEO_REPLACE_ENABLE_FACEFUSION": "1"})` from the `with` block.

- [ ] **Step 2: Add a failing test that standard mode skips FaceFusion even with uploaded person photos**

Add this test near the non-talking FaceFusion tests:

```python
    def test_standard_identity_mode_skips_facefusion_even_with_uploaded_person(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "prompt": "preserve motion",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "identityMode": "standard",
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/product.png"],
            "sceneImageUrl": "https://x/scene.png",
            "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            "targetFaceReferencePath": "/tmp/target.jpg",
        }
        order = []

        with mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/source.mp4", {"id": "source-temp"})), \
                mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: path), \
                mock.patch.object(self.client, "_run_facefusion") as facefusion, \
                mock.patch.object(self.client, "_ensure_segment_audio", side_effect=lambda before, after: order.append("audio") or after), \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={"ok": True, "frames": ["a.jpg"]}):
            path = self.client._run_hybrid_non_talking_segment(job, segment)

        facefusion.assert_not_called()
        self.assertEqual(order, ["audio"])
        self.assertTrue(path.endswith("edited_01.mp4"))
        self.assertEqual(segment["faceSwapPath"], "")
```

- [ ] **Step 3: Update talking FaceFusion test to require high mode**

In `test_talking_segment_runs_facefusion_for_uploaded_person_and_falls_back_on_timeout`, add to `job`:

```python
                "identityMode": "high",
                "enableFaceFusion": True,
```

Add this new test after it:

```python
    def test_standard_talking_segment_skips_digital_human_facefusion(self):
        with tempfile.TemporaryDirectory() as td:
            segment = {
                "index": 1,
                "segmentType": "talking",
                "script": "新的产品口播",
                "prompt": "stable presenter",
                "audioStatus": "pending",
                "qcStatus": "pending",
            }
            job = {
                "identityMode": "standard",
                "outDir": td,
                "segments": [segment],
                "modelFaceUrl": "https://x/face.png",
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }
            order = []

            with mock.patch.object(self.client, "_ensure_replacement_keyframe", side_effect=lambda _job, item: order.append("keyframe") or item.update({"keyframeUrl": "https://x/key.png"}) or "https://x/key.png"), \
                    mock.patch.object(self.client, "_run_hybrid_talking_segment", side_effect=lambda _job, _segment: order.append("digital_human") or "https://x/talking.mp4"), \
                    mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: Path(path).write_bytes(b"mp4")), \
                    mock.patch.object(self.client, "_run_facefusion") as facefusion, \
                    mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={
                        "ok": True, "frames": ["first.jpg", "middle.jpg", "last.jpg"],
                        "checks": {"media": "passed", "audio": "passed"},
                    }):
                result = self.client._run_hybrid_replacement_segment(job, segment)

        self.assertTrue(result["ok"])
        self.assertEqual(order, ["keyframe", "digital_human"])
        facefusion.assert_not_called()
        self.assertTrue(segment["videoPath"].endswith("digital_human_01.mp4"))
```

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_standard_identity_mode_skips_facefusion_even_with_uploaded_person \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_non_talking_segment_runs_facefusion_only_in_high_identity_mode \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_talking_segment_runs_facefusion_for_uploaded_person_and_falls_back_on_timeout \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_standard_talking_segment_skips_digital_human_facefusion -v
```

Expected: new standard-mode tests fail before Task 1 implementation; after Task 1 they should pass or expose places still depending on old env behavior.

- [ ] **Step 5: Make minimal implementation adjustments**

If Task 1 helper changes are present, `_run_hybrid_non_talking_segment()` and `_run_hybrid_replacement_segment()` should already branch correctly through `_replacement_enable_facefusion()` and `_replacement_enable_digital_human_facefusion()`. If tests reveal old env-only assumptions, remove those assumptions and rely only on `identityMode` helpers.

- [ ] **Step 6: Run the focused tests and verify GREEN**

Run the same command from Step 4.

Expected: pass.

---

### Task 3: UI And Job JSON Persist The Mode

**Files:**
- Modify: `tests/test_video_replacement_v2.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Consumes: `_replacement_identity_mode(job) -> str`
- Produces: `VideoReplacementPage.identity_mode`
- Produces: job field `identityMode`
- Produces: job field `enableFaceFusion` derived from `identityMode == "high"`

- [ ] **Step 1: Update UI source-string test**

In `test_v2_ui_has_plan_review_scene_and_three_face_inputs`, add:

```python
        self.assertIn('self.identity_mode = QtWidgets.QComboBox()', src)
        self.assertIn('self.identity_mode.addItem("标准：远程生成 + 一致性审核", "standard")', src)
        self.assertIn('self.identity_mode.addItem("快速：只远程生成", "fast")', src)
        self.assertIn('self.identity_mode.addItem("高一致：远程生成 + 本地换脸增强", "high")', src)
        self.assertIn('"identityMode": identity_mode', src)
        self.assertIn('enable_facefusion = identity_mode == "high"', src)
```

In `test_start_generation_defines_facefusion_gate_before_preflight`, replace:

```python
        self.assertIn("enable_facefusion = (not no_person_mode) and _replacement_enable_facefusion(facefusion_job)", body)
```

with:

```python
        self.assertIn('identity_mode = self.identity_mode.currentData() or "standard"', body)
        self.assertIn('enable_facefusion = identity_mode == "high"', body)
```

- [ ] **Step 2: Run the UI/source tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_v2_ui_has_plan_review_scene_and_three_face_inputs \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_start_generation_defines_facefusion_gate_before_preflight -v
```

Expected: fail because the mode selector and new string snippets do not exist.

- [ ] **Step 3: Add the mode selector to the refs grid**

In `VideoReplacementPage.__init__`, after `self.no_person_mode` creation, add:

```python
        self.identity_mode = QtWidgets.QComboBox()
        self.identity_mode.setToolTip("选择人物一致性策略：标准模式默认不跑本地换脸，高一致模式才执行 FaceFusion")
        self.identity_mode.addItem("标准：远程生成 + 一致性审核", "standard")
        self.identity_mode.addItem("快速：只远程生成", "fast")
        self.identity_mode.addItem("高一致：远程生成 + 本地换脸增强", "high")
```

Add it to the grid after `no_person_mode` and before `b_virtual`:

```python
        refs_l.addWidget(QtWidgets.QLabel("人物一致性"), 5, 0)
        refs_l.addWidget(self.identity_mode, 5, 1)
        refs_l.addWidget(self.b_virtual, 6, 0)
        refs_l.addWidget(self.model_lab, 6, 1)
```

Adjust the existing `b_virtual` and `model_lab` grid row from `5` to `6`.

- [ ] **Step 4: Update `_build_job()` to persist identity mode**

In `_build_job()`, before building `facefusion_job`, add:

```python
        identity_mode = self.identity_mode.currentData() or "standard"
```

Change the `facefusion_job` construction to include:

```python
                              identityMode=identity_mode,
                              enableFaceFusion=(identity_mode == "high"),
```

Change:

```python
        enable_facefusion = (not no_person_mode) and _replacement_enable_facefusion(facefusion_job)
```

to:

```python
        enable_facefusion = (not no_person_mode) and identity_mode == "high"
```

Add these fields to `job`:

```python
            "identityMode": identity_mode,
            "enableFaceFusion": enable_facefusion,
```

Keep the existing `enableFaceFusion` key but ensure there is only one final instance in the dict.

- [ ] **Step 5: Update `start_generation()` to read mode before preflight**

In `start_generation()`, after `no_person_mode`, add:

```python
        identity_mode = self.identity_mode.currentData() or "standard"
```

Update `facefusion_job` to include the mode and derived flag:

```python
                              identityMode=identity_mode,
                              enableFaceFusion=(identity_mode == "high"),
```

Change:

```python
        enable_facefusion = (not no_person_mode) and _replacement_enable_facefusion(facefusion_job)
```

to:

```python
        enable_facefusion = (not no_person_mode) and identity_mode == "high"
```

Before setting `targetFaceReferencePath`, add:

```python
        self._job["identityMode"] = identity_mode
        self._job["enableFaceFusion"] = enable_facefusion
```

- [ ] **Step 6: Run the UI/source tests and verify GREEN**

Run the same command from Step 2.

Expected: pass.

---

### Task 4: User-Facing Copy And Status

**Files:**
- Modify: `tests/test_video_replacement_v2.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Consumes: `_replacement_identity_mode(job) -> str`
- Consumes: `_replacement_identity_mode_label(mode) -> str`
- Updates: `_localize_replacement_display_text(text: str) -> str`
- Updates: `_replacement_segment_status_text(job: dict, segment: dict) -> str`

- [ ] **Step 1: Update FaceFusion timeout localization test**

In `test_replacement_error_display_localizes_facefusion_timeout_and_green_check`, replace:

```python
        self.assertIn("本地换脸超时", timeout_display)
```

with:

```python
        self.assertIn("本地换脸增强超时", timeout_display)
        self.assertIn("已回退远程同款结果", timeout_display)
```

- [ ] **Step 2: Add a failing status text test for identity mode**

Add after `test_segment_status_text_includes_model_warnings_and_remote_error`:

```python
    def test_segment_status_text_includes_identity_mode(self):
        job = {"identityMode": "standard", "segments": [{"index": 1}]}
        segment = {"index": 1, "status": "video_edit", "model": "viduq3-turbo-cankaosheng"}

        text = self.client._replacement_segment_status_text(job, segment)

        self.assertIn("标准模式", text)
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_replacement_error_display_localizes_facefusion_timeout_and_green_check \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_segment_status_text_includes_identity_mode -v
```

Expected: fail because copy and status text still use the old wording/no mode.

- [ ] **Step 4: Update the FaceFusion timeout display copy**

In `_REPLACEMENT_ERROR_DISPLAY`, replace the `facefusion_timeout` value with:

```python
    "facefusion_timeout": "本地换脸增强超时：已回退远程同款结果，可继续审核；如需提高一致性，请缩短片段、调低换脸配置，或切换高性能换脸环境。",
```

- [ ] **Step 5: Add identity mode to segment status text**

In `_replacement_segment_status_text()`, after the `parts = [...]` line, add:

```python
    parts.append(_replacement_identity_mode_label(_replacement_identity_mode(job)))
```

- [ ] **Step 6: Run the focused tests and verify GREEN**

Run the same command from Step 3.

Expected: pass.

---

### Task 5: Documentation, Line Numbers, And Release Notes

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: implemented `identityMode` behavior
- Produces: production documentation aligned with code

- [ ] **Step 1: Update `docs/ARCHITECTURE.md`**

Update the replacement boundary bullets so they state:

```markdown
- 同款替换提供三种人物一致性模式：快速模式只走远程同款；标准模式为默认，走远程同款并执行一致性 QC；高一致模式才在远程结果后执行本地 FaceFusion。
- 上传三张授权人物图时，人物图默认作为远程参考和 QC 基准，不再自动触发本地 FaceFusion。只有 `identityMode=high` 时才执行 FaceFusion；纯产品模式始终跳过。
```

- [ ] **Step 2: Update `docs/API_REFERENCE.md`**

In the replacement job JSON paragraph, include:

```markdown
`identityMode` 取值为 `fast`、`standard`、`high`。默认 `standard`；旧任务没有 `identityMode` 但 `enableFaceFusion=true` 时按 `high` 兼容。新任务中 `enableFaceFusion` 由 `identityMode == "high"` 派生。
```

- [ ] **Step 3: Update `docs/DEPLOYMENT.md`**

Update the FaceFusion environment variable rows so they state:

```markdown
| `VIDEO_REPLACE_ENABLE_FACEFUSION` | `0` | 旧任务兼容开关；新任务由 `identityMode=high` 显式启用本地 FaceFusion，上传人物图不再自动启用 |
| `VIDEO_REPLACE_DIGITAL_HUMAN_FACEFUSION` | `0` | 已由 `identityMode=high` 统一控制；保留该变量仅作历史兼容说明 |
```

If the current table still documents `VIDEO_REPLACE_DIGITAL_HUMAN_FACEFUSION` default as `1`, change it to match the new behavior.

- [ ] **Step 4: Update `docs/TROUBLESHOOTING.md`**

In the FaceFusion timeout section, replace the default strategy paragraph with:

```markdown
- 默认策略：同款替换新增快速、标准、高一致三种人物一致性模式。默认标准模式不执行本地 FaceFusion，只将上传人物图作为远程参考和一致性 QC 基准。只有选择高一致模式时才会在远程结果后执行本地 FaceFusion；超时或失败会回退远程结果并进入人工审核。
- `facefusion_timeout:<秒数>`：高一致模式下本地换脸增强超过配置时间。系统已回退远程同款结果，可继续审核；如必须提高一致性，缩短片段、降低 FaceFusion 配置或切换高性能换脸环境后单段重试。
```

- [ ] **Step 5: Recalculate `docs/IMPLEMENTATION.md` line numbers**

Run:

```bash
rg -n "def _replacement_identity_mode|def _replacement_enable_facefusion|def _replacement_enable_digital_human_facefusion|class VideoReplacementPage|def _build_job|def start_generation|def _run_hybrid_non_talking_segment|def _run_hybrid_replacement_segment|_REPLACEMENT_ERROR_DISPLAY|def _replacement_segment_status_text" backend/matrix_native_client.py
rg -n "test_identity_mode_defaults|test_identity_mode_high|test_digital_human_facefusion_only|test_standard_identity_mode|test_non_talking_segment_runs_facefusion_only|test_standard_talking_segment|test_segment_status_text_includes_identity_mode|test_v2_ui_has_plan_review|test_start_generation_defines" tests/test_video_replacement_v2.py
```

Update only the relevant bullets in `docs/IMPLEMENTATION.md`. Keep the existing `path#Lx-Ly` format. Do not leave stale line numbers for touched sections.

- [ ] **Step 6: Update `CHANGELOG.md`**

Add an unreleased bullet near the top:

```markdown
- 同款替换新增快速、标准、高一致三种人物一致性模式；默认标准模式不再因上传人物图自动执行本地 FaceFusion，避免每段 420 秒超时。高一致模式仍可显式启用本地换脸增强，失败后回退远程结果并进入人工审核。
```

- [ ] **Step 7: Documentation verification**

Run:

```bash
rg -n "当前默认已关闭本地 FaceFusion|上传三张授权人物图时，非口播片段会在远程参考图视频结果下载后自动尝试本地 FaceFusion|VIDEO_REPLACE_DIGITAL_HUMAN_FACEFUSION.*`1`" docs/ARCHITECTURE.md docs/API_REFERENCE.md docs/DEPLOYMENT.md docs/TROUBLESHOOTING.md docs/IMPLEMENTATION.md CHANGELOG.md backend/matrix_native_client.py
```

Expected: no stale wording that contradicts the new default standard mode.

---

### Task 6: Final Verification

**Files:**
- Verify: `backend/matrix_native_client.py`
- Verify: `tests/test_video_replacement_v2.py`
- Verify: `tests/test_video_replacement.py`
- Verify: docs listed in Task 5

**Interfaces:**
- Consumes: all previous tasks
- Produces: verified implementation ready for user review

- [ ] **Step 1: Run focused identity mode tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_identity_mode_defaults_to_standard_and_uploaded_person_does_not_enable_facefusion \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_identity_mode_high_enables_facefusion_and_old_jobs_remain_compatible \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_facefusion_only_runs_in_high_identity_mode \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_standard_identity_mode_skips_facefusion_even_with_uploaded_person \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_non_talking_segment_runs_facefusion_only_in_high_identity_mode \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_standard_talking_segment_skips_digital_human_facefusion \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_segment_status_text_includes_identity_mode -v
```

Expected: pass.

- [ ] **Step 2: Run full replacement V2 test suite**

Run:

```bash
.venv/bin/python -m unittest tests.test_video_replacement_v2 -v
```

Expected: pass.

- [ ] **Step 3: Run legacy replacement tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_video_replacement -v
```

Expected: pass.

- [ ] **Step 4: Compile the client**

Run:

```bash
.venv/bin/python -m py_compile backend/matrix_native_client.py
```

Expected: no output and exit code 0.

- [ ] **Step 5: Smoke-test the helper behavior directly**

Run:

```bash
.venv/bin/python - <<'PY'
import os, sys
sys.path.insert(0, "backend")
import matrix_native_client as m
uploaded = {"faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"]}
print("default", m._replacement_identity_mode(uploaded), m._replacement_enable_facefusion(uploaded))
print("fast", m._replacement_identity_mode({"identityMode": "fast", **uploaded}), m._replacement_enable_facefusion({"identityMode": "fast", **uploaded}))
print("standard", m._replacement_identity_mode({"identityMode": "standard", **uploaded}), m._replacement_enable_facefusion({"identityMode": "standard", **uploaded}))
print("high", m._replacement_identity_mode({"identityMode": "high", **uploaded}), m._replacement_enable_facefusion({"identityMode": "high", **uploaded}))
PY
```

Expected output:

```text
default standard False
fast fast False
standard standard False
high high True
```

- [ ] **Step 6: Report remaining risk**

Final report must include:
- Changed behavior: default standard mode no longer runs FaceFusion.
- Verification commands and results.
- Rollback path: restore previous code snapshot or set default mode to high if old behavior is required.
- Remaining risk: remote reference models still cannot guarantee perfect identity in fast/standard modes; high mode depends on local FaceFusion performance and licensing.
