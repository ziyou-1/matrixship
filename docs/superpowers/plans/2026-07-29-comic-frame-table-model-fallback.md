# Comic Frame Table and Model Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display both comic keyframes in a stable local table and make storyboard video generation fall back safely through Seedance, Vidu, Wan, Kling Omni, and PixVerse.

**Architecture:** The local PyQt client owns frame-task parsing, absolute media URLs, task persistence, and table rendering. The remote AI Canvas service owns provider-specific payloads, billing compensation, transient-error recovery, and ordered model fallback. Existing comic APIs and legacy job JSON remain compatible.

**Tech Stack:** Python 3, PyQt5, `requests`, `unittest`, FastAPI-compatible AI Canvas service, LK888 gateway, Volcengine Ark, JSON task persistence.

## Global Constraints

- Do not automatically restart the local client.
- Back up `/root/AI-CanvasPro/server.py` before remote edits and restart only service port 8777 after deployment.
- Default fallback order is exactly `doubao-seedance-2-0-260128`, `vidu/viduq3-mix_reference2video`, `wan2.7-shouweizhen`, `kling-v3-omni-shouweizhen`, `pixverse-v6-shouweizhen`.
- Explicit provider failure moves to the next model; timeout, 502, and rate limit first query or retry the original task.
- Never log API keys, authorization headers, or raw private media.
- Every new helper and behavior starts with a failing test.
- No database schema change; `migration.sql` records that no migration is required.
- The real smoke test creates a new three-segment task and does not recover project 297 or job `bc1eb925573e407493f8f06240b0b427`.

---

## File Map

- `backend/matrix_native_client.py`: local frame parsing, URL normalization, comic segment orchestration, thumbnail cells, and table sizing.
- `tests/test_video_replacement.py`: local comic helper and orchestration tests.
- `tests/test_video_replacement_v2.py`: local table layout source-contract test.
- `.tmp-aicanvas-server-current.py`: test mirror of remote `/root/AI-CanvasPro/server.py`; updated first, then deployed after backup.
- `tests/test_aicanvas_real_person_fallback.py`: isolated remote fallback-chain and billing tests.
- `docs/ARCHITECTURE.md`, `docs/API_REFERENCE.md`, `docs/DEPLOYMENT.md`: data flow, response fields, configuration, and rollout.
- `docs/IMPLEMENTATION.md`: final source locations with recalculated line numbers.
- `docs/TROUBLESHOOTING.md`: observed failures, root causes, smoke evidence, and rollback.
- `CHANGELOG.md`, `migration.sql`: release trace and no-op migration record.

### Task 1: Phase 0 Local Frame and URL Smoke Skeleton

**Files:**
- Modify: `tests/test_video_replacement.py`
- Modify: `backend/matrix_native_client.py:9561-9588`
- Modify: `docs/TROUBLESHOOTING.md`

**Interfaces:**
- Produces: `_comic_extract_task_ids(payload: dict) -> list[str]`.
- Produces: `_comic_absolute_media_url(value: str, base_url: str | None = None) -> str`.
- Preserves: `_comic_extract_task_id(payload) -> str`, returning the first task for legacy callers.

- [ ] **Step 1: Write the failing helper tests**

```python
def test_comic_extract_task_ids_keeps_start_and_end_order(self):
    payload = {"data": {"task_ids": ["frame-start", "frame-end"]}}
    self.assertEqual(
        self.client._comic_extract_task_ids(payload),
        ["frame-start", "frame-end"],
    )
    self.assertEqual(self.client._comic_extract_task_id(payload), "frame-start")

def test_comic_absolute_media_url_joins_remote_upload_path(self):
    with mock.patch.object(self.client, "_comic_base_url", return_value="https://manju.yunlingai.net"):
        self.assertEqual(
            self.client._comic_absolute_media_url("/uploads/2026/07/clip.mp4"),
            "https://manju.yunlingai.net/uploads/2026/07/clip.mp4",
        )
    self.assertEqual(
        self.client._comic_absolute_media_url("https://cdn.example/frame.png"),
        "https://cdn.example/frame.png",
    )
```

- [ ] **Step 2: Run the tests and record the expected smoke failure**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest `
  tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_extract_task_ids_keeps_start_and_end_order `
  tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_absolute_media_url_joins_remote_upload_path -v
```

Expected: both tests fail because the helpers do not exist. Add the exact failure and command to `docs/TROUBLESHOOTING.md` under `2026-07-29 双帧与相对媒体地址冒烟`.

- [ ] **Step 3: Implement the minimal helpers**

```python
def _comic_extract_task_ids(payload):
    data = _comic_response_data(payload)
    values = []
    if isinstance(data, dict):
        for key in ("task_ids", "taskIds"):
            if isinstance(data.get(key), list):
                values.extend(data.get(key) or [])
        if not values:
            for key in ("task_id", "taskId", "id"):
                if data.get(key) not in (None, ""):
                    values.append(data.get(key))
                    break
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))

def _comic_extract_task_id(payload):
    task_ids = _comic_extract_task_ids(payload)
    return task_ids[0] if task_ids else ""

def _comic_absolute_media_url(value, base_url=None):
    value = str(value or "").strip()
    if not value or value.startswith(("http://", "https://")):
        return value
    return urllib.parse.urljoin((base_url or _comic_base_url()).rstrip("/") + "/", value.lstrip("/"))
```

- [ ] **Step 4: Re-run the focused tests**

Expected: both tests pass and the smoke-failure entry contains the root cause and fix.

- [ ] **Step 5: Commit the local helper slice**

```powershell
git add backend/matrix_native_client.py tests/test_video_replacement.py docs/TROUBLESHOOTING.md
git commit -m "fix: parse comic keyframe tasks and media urls"
```

### Task 2: Wait for Both Frames and Recover Existing Remote Media

**Files:**
- Modify: `tests/test_video_replacement.py`
- Modify: `backend/matrix_native_client.py:9729-9760`
- Modify: `backend/matrix_native_client.py:11058-11225`

**Interfaces:**
- Consumes: `_comic_extract_task_ids()` and `_comic_absolute_media_url()` from Task 1.
- Produces: `_comic_storyboard_frame_urls(storyboard: dict) -> tuple[str, str]`.
- Persists: `startFrameTaskId`, `endFrameTaskId`, `startFrameUrl`, `endFrameUrl`.

- [ ] **Step 1: Write a failing two-frame orchestration test**

Create an adapter stub whose image submit returns `{"data": {"task_ids": ["start-task", "end-task"]}}`; its `wait_task_result` returns `/uploads/start.png`, `/uploads/end.png`, then `/uploads/video.mp4`. Run `_run_comic_project_segments()` and assert:

```python
self.assertEqual(Adapter.calls, [
    "wait:start-task", "wait:end-task", "submit:video", "wait:video-task"
])
self.assertEqual(segment["startFrameTaskId"], "start-task")
self.assertEqual(segment["endFrameTaskId"], "end-task")
self.assertEqual(segment["startFrameUrl"], "https://manju.yunlingai.net/uploads/start.png")
self.assertEqual(segment["endFrameUrl"], "https://manju.yunlingai.net/uploads/end.png")
self.assertEqual(segment["videoUrl"], "https://manju.yunlingai.net/uploads/video.mp4")
```

- [ ] **Step 2: Run the focused test and verify RED**

Expected: only `start-task` is waited and relative URLs remain unresolved.

- [ ] **Step 3: Add frame URL extraction and dual waits**

```python
def _comic_storyboard_frame_urls(storyboard):
    storyboard = storyboard if isinstance(storyboard, dict) else {}
    generated = storyboard.get("generatedImages") or storyboard.get("generated_images") or []
    urls = [
        str(storyboard.get("startFrameUrl") or storyboard.get("start_frame_url") or "").strip(),
        str(storyboard.get("endFrameUrl") or storyboard.get("end_frame_url") or "").strip(),
    ]
    urls.extend(
        str(item.get("url") or item.get("image_url") or "").strip()
        for item in generated if isinstance(item, dict)
    )
    urls = [_comic_absolute_media_url(url) for url in urls if url]
    return (urls + ["", ""])[:2]
```

Replace the single image task branch with a loop over the first two task IDs. Normalize every result URL before persistence and before `_wf_download`. Keep `flowchartTaskId` and `flowchartUrl` as aliases of the start frame.

- [ ] **Step 4: Add recovery tests for storyboard fields and completed video**

Assert recovery reads `start_frame_url`, `end_frame_url`, `generatedImages`, and relative `video_url`. Assert a completed remote video is downloaded without calling `submit_storyboard_video` again.

- [ ] **Step 5: Run comic helper and orchestration regression tests**

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit the orchestration slice**

```powershell
git add backend/matrix_native_client.py tests/test_video_replacement.py
git commit -m "fix: persist both comic frames and recover videos"
```

### Task 3: Replace the Flowchart Column with Stable Frame Thumbnails

**Files:**
- Modify: `tests/test_video_replacement_v2.py`
- Modify: `backend/matrix_native_client.py:11554-11688`

**Interfaces:**
- Consumes: `segment.startFrameUrl` and `segment.endFrameUrl` from Task 2.
- Produces: `VideoReplacementPage._make_comic_frame_cell(segment, frame_kind)`.

- [ ] **Step 1: Write the failing table contract test**

```python
def test_comic_segment_table_uses_two_frame_columns_without_editor_overflow(self):
    src = Path(self.client.__file__).read_text(encoding="utf-8")
    self.assertIn('["序号", "口播稿", "首帧图", "尾帧图", "视频", "操作"]', src)
    self.assertNotIn('["序号", "口播稿", "流程图生成", "视频", "操作"]', src)
    editor_block = src[src.index("def _make_segment_script_editor"):src.index("def _segment_script_value")]
    self.assertNotIn("editor.setMinimumWidth(500)", editor_block)
    self.assertIn("setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)", src)
```

- [ ] **Step 2: Run the table test and verify RED**

Expected: old five-column header and 500-pixel minimum width fail the assertions.

- [ ] **Step 3: Implement fixed table sizing**

In comic mode set six columns. Reset every section mode when switching modes, then apply:

```python
header = self.table.horizontalHeader()
for column in range(6):
    header.setSectionResizeMode(column, QtWidgets.QHeaderView.Fixed)
header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
self.table.setColumnWidth(0, 52)
self.table.setColumnWidth(2, 132)
self.table.setColumnWidth(3, 132)
self.table.setColumnWidth(4, 176)
self.table.setColumnWidth(5, 172)
self.table.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
self.table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
```

Remove the editor minimum width; use `QSizePolicy.Ignored, QSizePolicy.Expanding` so the editor remains inside its cell.

- [ ] **Step 4: Implement asynchronous thumbnail cells**

Create a fixed-size `QToolButton` for each frame, display `生成中` or `未生成` until media is available, fetch remote image bytes with the existing background-worker pattern, and apply a cropped `QPixmap`. Clicking a loaded cell opens the absolute frame URL. Do not perform `requests.get()` on the UI thread.

- [ ] **Step 5: Run the focused and full local UI contract tests**

```powershell
.\.venv-win\Scripts\python.exe -m unittest `
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_comic_segment_table_uses_two_frame_columns_without_editor_overflow `
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_replacement_segment_table_uses_readable_script_editor_and_fixed_actions -v
.\.venv-win\Scripts\python.exe -m py_compile backend/matrix_native_client.py
```

Expected: tests and compilation pass.

- [ ] **Step 6: Commit the UI slice**

```powershell
git add backend/matrix_native_client.py tests/test_video_replacement_v2.py
git commit -m "feat: show comic start and end frames"
```

### Task 4: Implement the Remote Five-Model Fallback State Machine

**Files:**
- Modify: `tests/test_aicanvas_real_person_fallback.py`
- Modify: `.tmp-aicanvas-server-current.py:12920-13177`

**Interfaces:**
- Produces: `_comic_real_person_video_fallback_models() -> tuple[str, ...]`.
- Produces: `_comic_video_fallback_params(model: str, original: dict) -> dict`.
- Persists: `requested_model`, `actual_model`, `fallback_model`, `fallback_index`, `fallback_history`, `fallback_reason`, `fallback_applied`.

- [ ] **Step 1: Extend the isolated server loader**

Load the two new helpers into the AST test module. Change the gateway stub to accept a per-model outcome mapping and record every submitted model and sanitized parameter key.

- [ ] **Step 2: Write failing ordered-fallback tests**

```python
def test_privacy_rejection_falls_back_through_configured_models_in_order(self):
    module = load_server(gateway_outcomes={
        "vidu/viduq3-mix_reference2video": RuntimeError("provider rejected"),
        "wan2.7-shouweizhen": RuntimeError("provider rejected"),
        "kling-v3-omni-shouweizhen": RuntimeError("provider rejected"),
        "pixverse-v6-shouweizhen": {"task_id": "pixverse-task"},
    })
    task = self._submit(module)
    self.assertEqual([call["model"] for call in module.gateway_calls], [
        "vidu/viduq3-mix_reference2video",
        "wan2.7-shouweizhen",
        "kling-v3-omni-shouweizhen",
        "pixverse-v6-shouweizhen",
    ])
    self.assertEqual(task["actual_model"], "pixverse-v6-shouweizhen")
    self.assertEqual(len(task["fallback_history"]), 4)
```

Add separate tests that Vidu is first, Wan/Kling/PixVerse receive exactly two frame inputs, unsupported audio keys are absent, and all failures preserve the complete history.

- [ ] **Step 3: Write failing transient-error tests**

Simulate 502, timeout, and rate-limit responses with an existing remote task ID. Assert the service polls/retries that ID and does not submit the next model while the original task later becomes completed.

- [ ] **Step 4: Implement configuration and model adapters**

```python
COMIC_REAL_PERSON_VIDEO_FALLBACK_MODELS = (
    "vidu/viduq3-mix_reference2video",
    "wan2.7-shouweizhen",
    "kling-v3-omni-shouweizhen",
    "pixverse-v6-shouweizhen",
)

def _comic_real_person_video_fallback_models():
    key = "COMIC_REAL_PERSON_VIDEO_FALLBACK_MODELS"
    if key in os.environ:
        return tuple(item.strip() for item in os.environ.get(key, "").split(",") if item.strip())
    return COMIC_REAL_PERSON_VIDEO_FALLBACK_MODELS
```

The Vidu adapter keeps deduplicated frame and manual-asset references within its seven-image limit. Wan, Kling Omni, and PixVerse keep only start/end frame fields and remove `sound_file`, `audio_file`, `reference_audio_file`, and `lip_sync_required`.

- [ ] **Step 5: Implement bounded fallback and billing compensation**

Use one loop with one submission per candidate. Refund only a failed billed request, append a structured history item before moving on, and register one final task containing the complete history. Retain the original requested Seedance model in all responses.

- [ ] **Step 6: Add structured event assertions**

Assert logs include `project_id`, `storyboard_id`, `requested_model`, `actual_model`, `fallback_index`, `remote_task_id`, `error_code`, and `elapsed_ms`; assert no API key or authorization header appears.

- [ ] **Step 7: Run remote fallback tests**

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_aicanvas_real_person_fallback -v
.\.venv-win\Scripts\python.exe -m py_compile .tmp-aicanvas-server-current.py
```

Expected: all tests pass and no warning is emitted.

### Task 5: Documentation, Deployment, and Rollback Gate

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `CHANGELOG.md`
- Modify: `migration.sql`

- [ ] **Step 1: Update contracts and operational docs**

Document the six table columns, dual-frame fields, relative URL normalization, five-model chain, transient-error rule, response fallback history, environment variable, health check, and no-lip-sync limitation.

- [ ] **Step 2: Recalculate implementation line references**

Use `rg -n` after all source edits and update every affected `path#Lx-Ly` entry in `docs/IMPLEMENTATION.md`. Run a scan confirming old references to the one-model Kling fallback are removed or explicitly marked historical.

- [ ] **Step 3: Record release and no-op migration**

Add a dated `CHANGELOG.md` entry. Set `migration.sql` to a comment-only entry stating that this release changes JSON fields and remote task metadata without database DDL.

- [ ] **Step 4: Run local quality gates**

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement tests.test_video_replacement_v2 tests.test_aicanvas_real_person_fallback -v
.\.venv-win\Scripts\python.exe -m py_compile backend/matrix_native_client.py .tmp-aicanvas-server-current.py
```

Expected: all tests pass.

- [ ] **Step 5: Back up and deploy the remote service**

On `120.26.194.174`, copy `/root/AI-CanvasPro/server.py` to `/root/AI-CanvasPro/server.py.bak.<timestamp>`, upload the verified mirror, restart only the 8777 service, and verify the public health endpoint returns HTTP 200. Record backup path and health output in `docs/TROUBLESHOOTING.md`.

- [ ] **Step 6: Commit the production and documentation slice**

Stage only files changed for this feature, inspect `git diff --cached --check`, and commit with:

```powershell
git commit -m "feat: add resilient comic video fallback chain"
```

### Task 6: New Three-Segment Real End-to-End Test

**Files:**
- Read: `backend/datas/accounts/user-owner/video_replacements/*/replacement_job.json`
- Read: remote `/root/AI-CanvasPro/user/comic_projects_local.json`
- Modify: `docs/TROUBLESHOOTING.md`

- [ ] **Step 1: Create a new job without restoring the old one**

Use source video `https://www.douyin.com/video/7657719110507299769`, keep only the first three segments, and upload:

- Character: `E:/Desktop/数字人/1.png`
- Prop: `E:/Desktop/数字人/美妆主播带货图生成需求-7.png`
- Scene: `E:/Desktop/数字人/汽车之家.jpg`

- [ ] **Step 2: Observe both systems once per second**

Track local stages, frame task IDs, frame URLs, video task ID, requested/actual model, fallback history, and elapsed time. In parallel inspect the corresponding comic project, storyboard frame tasks, and video tasks. Do not submit duplicate jobs while a remote task is pending.

- [ ] **Step 3: Validate every segment artifact**

For each segment confirm two non-empty, downloadable image URLs and one non-empty video URL. Validate downloaded MP4 duration, dimensions, video stream, and playable bytes. Confirm the local table data maps start and end frames to the correct storyboard.

- [ ] **Step 4: Validate fallback behavior when triggered**

If Seedance rejects the authorized real-person image, assert the next submitted model is Vidu Q3. If a transient provider error occurs, assert the same task is queried before any next-model submission. Compare billing records to unique submissions and stop the test if duplicate charging is observed.

- [ ] **Step 5: Apply the 1% rollback gate**

If a code-caused error affects any of the three segments, stop expansion, preserve logs, restore the remote backup, restart 8777, and verify health. If the issue is a verified provider failure and the next model succeeds without duplicate billing, record it as an expected fallback rather than rolling back.

- [ ] **Step 6: Record final evidence**

Add job ID, comic project ID, storyboard IDs, actual models, task IDs, media validation results, billing uniqueness result, and remaining provider risks to `docs/TROUBLESHOOTING.md`. Do not restart the local client automatically; report that a manual restart is required to see the new table layout.
