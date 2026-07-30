# 同款替换内嵌媒体与分项重生成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 漫剧视频生成成功后使用鉴权下载并直接在片段表中播放，同时支持首帧、尾帧和视频的独立重生成。

**Architecture:** 远程漫剧 `generate-image` 接口增加向后兼容的可选 `frameIndex=1/2`，缺省仍生成首尾两张图。本地客户端为漫剧受保护媒体提供专用鉴权下载，持久化首尾帧本地路径，并以独立的单帧、单视频重生成流程维护 `video_stale`、`download_failed` 和重试历史；表格只读取已校验的本地媒体，不展示公网地址。

**Tech Stack:** Python 3.12、PySide6、Qt Multimedia、Requests、unittest、FFmpeg/ffprobe、远程 AI CanvasPro `server.py`。

## Global Constraints

- 不在代码、日志、文档或测试中硬编码 API Key、Bearer Token、SSH 密码或数据库连接串。
- 本地客户端不自动重启；用户手动重启后验证。
- 远程 `server.py` 部署前创建带时间戳备份，部署后重启 `ai-canvas.service` 并检查健康状态。
- 不重启中心服，不修改中心服接口。
- 不改变未携带 `frameIndex` 的现有首尾帧双图请求。
- 普通确认弹窗只说明重新生成对象，不显示模型费用、任务数量或金额。
- 视频列和图片工具提示不得显示公网媒体地址。
- 所有网络、媒体校验和播放器异常使用脱敏 JSON 结构化日志记录。
- 任务 JSON 新字段必须可选读取，旧任务仍可打开。
- 最终合成只接受 `status=done` 且当前 `videoPath` 校验通过的片段。
- 声音模式 `auto` 直接保留生成视频自带声音，不读取原视频音轨、不生成或混入 TTS；旧 `source/origin/original/source_audio` 只兼容映射为 `auto`。仅 `tts` 生成并混入分镜 TTS。
- 当前工作区包含用户已有改动；不得覆盖、回滚或提交无关文件。
- 任何提交前重算并更新 `docs/IMPLEMENTATION.md` 中受影响的 `file.py#Lx-Ly` 行号。

## File Map

- Modify: `tools/aicanvas_remote/server_current.py` - 远程 `server.py` 的受控本地副本，增加单帧生成参数过滤。
- Modify: `backend/matrix_native_client.py` - 漫剧鉴权下载、状态迁移、单帧/视频重生成、图片预览和内嵌播放器。
- Modify: `tests/test_aicanvas_frame_billing.py` - `frameIndex` 缺省、单帧和非法值契约测试。
- Modify: `tests/test_video_replacement.py` - 鉴权下载、旧任务恢复、单帧/视频重生成数据流测试。
- Modify: `tests/test_video_replacement_v2.py` - 表格播放器、图片本地预览、按钮和确认提示测试。
- Modify: `tests/test_openapi_contract.py` - 单帧生成请求 Schema 契约测试。
- Modify: `docs/API_REFERENCE.md` - 漫剧单帧请求与任务状态字段。
- Modify: `docs/ARCHITECTURE.md` - 媒体下载、预览和重生成数据流。
- Modify: `docs/DEPLOYMENT.md` - 远程部署、健康检查与回滚。
- Modify: `docs/openapi.yaml` - `generate-image` 的 `frameIndex` / `frame_index` 请求 Schema 与 400 响应。
- Modify: `docs/IMPLEMENTATION.md` - 最终实现位置和准确行号。
- Modify: `docs/TROUBLESHOOTING.md` - 401 根因、冒烟失败点和恢复步骤。
- Modify: `CHANGELOG.md` - 用户可见行为变化。
- Verify only: `migration.sql` - 本次无数据库变化，保持现有文件不变并在发布记录中注明无需迁移。

---

### Task 1: Phase 0 冒烟骨架与 401 复现

**Files:**
- Modify: `tests/test_video_replacement.py`
- Modify: `docs/TROUBLESHOOTING.md`

**Interfaces:**
- Consumes: 现有 `_comic_download_segment_video(job, segment, video_url)` 和 `ComicProjectAdapter._comic_headers()`。
- Produces: 可重复失败的 `test_comic_protected_video_download_requires_adapter_auth`，证明裸下载是根因。

- [ ] **Step 1: 写最小失败测试**

在 `VideoReplacementHelpersTest` 中增加测试。使用假 adapter 记录请求头，模拟裸请求 401、携带 Bearer 后返回视频字节：

```python
def test_comic_protected_video_download_requires_adapter_auth(self):
    adapter = mock.Mock()
    adapter.download_media.side_effect = lambda url, path: Path(path).write_bytes(b"video")
    segment = {"index": 1, "status": "failed"}
    with tempfile.TemporaryDirectory() as td, \
            mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}):
        path = self.client._comic_download_segment_video(
            {"outDir": td}, segment,
            "http://120.26.194.174/data/uploads/comic-drama/result.mp4",
            adapter=adapter,
        )
    adapter.download_media.assert_called_once()
    self.assertEqual(segment["status"], "done")
    self.assertEqual(path, segment["videoPath"])
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_protected_video_download_requires_adapter_auth -v
```

Expected: FAIL，原因是 `_comic_download_segment_video()` 不接受 `adapter`，并仍调用裸 `_wf_download()`。

- [ ] **Step 3: 记录冒烟失败点**

在 `docs/TROUBLESHOOTING.md` 增加“远程视频完成但本地 401”条目，写明：

```text
远程任务、TTS 混音和结果地址均已完成；客户端在写入 videoUrl 后使用不带鉴权的通用下载，受保护媒体路由返回 401，导致链接可见但片段失败。
```

- [ ] **Step 4: 暂不提交**

本任务只建立 RED 证据。由于工作区存在用户改动，不提交中间失败状态。

---

### Task 2: 漫剧专用鉴权媒体下载与旧任务恢复

**Files:**
- Modify: `backend/matrix_native_client.py` near `ComicProjectAdapter` and `_comic_download_segment_video`
- Modify: `tests/test_video_replacement.py`

**Interfaces:**
- Consumes: `ComicProjectAdapter._ensure_comic_token()`、`_comic_absolute_media_url()`、`_breakdown_source_validation()`。
- Produces:
  - `ComicProjectAdapter.download_media(url: str, path: str, max_bytes: int = 0) -> str`
  - `_comic_download_segment_video(job: dict, segment: dict, video_url: str, adapter: ComicProjectAdapter) -> str`
  - `_comic_download_frame_image(job: dict, segment: dict, frame_kind: str, image_url: str, adapter: ComicProjectAdapter) -> str`
  - `_comic_recover_completed_media(job: dict, segment: dict, adapter: ComicProjectAdapter) -> bool`

- [ ] **Step 1: 扩充失败测试**

增加四个测试：

```python
def test_comic_media_download_sends_bearer_and_retries_401_once(self):
    adapter = self.client.ComicProjectAdapter.__new__(self.client.ComicProjectAdapter)
    adapter._comic_token = "old-token"
    adapter._comic_token_expires_at = 9999999999
    adapter._ensure_comic_token = mock.Mock(side_effect=["old-token", "new-token"])
    unauthorized = mock.Mock(status_code=401)
    success = mock.Mock(status_code=200)
    success.raise_for_status.return_value = None
    success.iter_content.return_value = [b"video"]
    adapter._media_get = mock.Mock(side_effect=[unauthorized, success])
    with tempfile.TemporaryDirectory() as td:
        path = str(Path(td) / "result.mp4")
        self.assertEqual(adapter.download_media("http://comic/data/result.mp4", path), path)
        self.assertEqual(Path(path).read_bytes(), b"video")
    self.assertEqual(adapter._media_get.call_count, 2)
    self.assertEqual(adapter._media_get.call_args_list[0].kwargs["headers"]["Authorization"], "Bearer old-token")
    self.assertEqual(adapter._media_get.call_args_list[1].kwargs["headers"]["Authorization"], "Bearer new-token")

def test_comic_video_download_failure_uses_download_failed_status(self):
    adapter = mock.Mock()
    adapter.download_media.side_effect = RuntimeError("comic_media_unauthorized")
    segment = {"index": 1, "status": "running"}
    with tempfile.TemporaryDirectory() as td:
        with self.assertRaisesRegex(RuntimeError, "comic_media_unauthorized"):
            self.client._comic_download_segment_video(
                {"outDir": td}, segment, "http://comic/data/result.mp4", adapter=adapter
            )
    self.assertEqual(segment["status"], "download_failed")
    self.assertEqual(segment["stage"], "download_failed")

def test_comic_completed_remote_video_recovers_without_resubmit(self):
    adapter = mock.Mock()
    adapter.download_media.side_effect = lambda _url, path, **_kwargs: Path(path).write_bytes(b"video") or path
    segment = {
        "index": 1,
        "status": "download_failed",
        "videoUrl": "http://comic/data/result.mp4",
        "comicVideoResult": {"status": "completed"},
    }
    with tempfile.TemporaryDirectory() as td, \
            mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}):
        recovered = self.client._comic_recover_completed_media({"outDir": td}, segment, adapter)
    self.assertTrue(recovered)
    self.assertEqual(segment["status"], "done")
    self.assertTrue(Path(segment["videoPath"]).is_file())
    adapter.submit_storyboard_video.assert_not_called()
```

断言：第一次 401 后清空 token 并重取一次；第二次失败即停止；日志只有 host、文件名、HTTP 状态和错误编号；远程 `completed` 且存在 `videoUrl` 时只下载，不调用 `submit_storyboard_video()`。

- [ ] **Step 2: 运行目标测试确认 RED**

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_media_download_sends_bearer_and_retries_401_once tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_video_download_failure_uses_download_failed_status tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_completed_remote_video_recovers_without_resubmit -v
```

Expected: FAIL，相关方法尚不存在。

- [ ] **Step 3: 实现专用下载**

按以下最小契约实现，实际请求继续使用 `Session(trust_env=False)`：

```python
def download_media(self, url, path, max_bytes=0):
    url = _comic_absolute_media_url(url)
    temp_path = path + ".part"
    for attempt in range(2):
        headers = {"Authorization": "Bearer " + self._ensure_comic_token()}
        response = self._media_get(url, headers=headers, timeout=300, stream=True)
        if response.status_code == 401 and attempt == 0:
            self._comic_token = ""
            self._comic_token_expires_at = 0.0
            continue
        response.raise_for_status()
        _write_stream_with_limit(response, temp_path, max_bytes=max_bytes)
        os.replace(temp_path, path)
        return path
    raise RuntimeError("comic_media_unauthorized")
```

实现时确保异常路径删除 `.part`，结构化日志不记录 Token、完整 URL 查询参数或响应体。

- [ ] **Step 4: 视频状态只在校验后完成**

调整 `_comic_download_segment_video()`：

```python
segment.update({"stage": "downloading_video", "status": "running"})
adapter.download_media(video_url, path)
validation = _breakdown_source_validation(path)
if not validation.get("ok"):
    segment.update({"status": "download_failed", "stage": "download_failed"})
    raise RuntimeError("comic_segment_invalid:%s" % validation.get("code"))
segment.update({"status": "done", "stage": "done", "videoPath": path})
```

不要在下载前把公网地址当成可播放结果；`videoUrl` 可保留在任务 JSON 供追踪，但不得进入表格文本或工具提示。

- [ ] **Step 5: 下载首尾帧并持久化本地路径**

`_comic_download_frame_image()` 根据 `frame_kind` 写入 `startFramePath` 或 `endFramePath`。用 `QImageReader` 或 Pillow 验证图片可解码，失败时保留旧路径并写结构化错误。

- [ ] **Step 6: 旧任务自动恢复**

打开或刷新旧任务时，若远程结果 `completed`、存在 `videoUrl`、缺少有效 `videoPath`，后台调用 `_comic_recover_completed_media()`。恢复只下载和校验，不重新提交模型、不重复计费。

- [ ] **Step 7: 运行测试确认 GREEN**

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_protected_video_download_requires_adapter_auth tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_media_download_sends_bearer_and_retries_401_once tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_video_download_failure_uses_download_failed_status tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_completed_remote_video_recovers_without_resubmit -v
```

Expected: 4 tests PASS。

---

### Task 3: 远程 `frameIndex` 单帧接口扩展

**Files:**
- Modify: `tools/aicanvas_remote/server_current.py` near `_handle_comic_frame_generate_image_proxy`
- Modify: `tests/test_aicanvas_frame_billing.py`
- Modify: `docs/openapi.yaml`
- Modify: `tests/test_openapi_contract.py`

**Interfaces:**
- Consumes: 现有 `POST /api/v1/comic-drama/storyboards/{id}/generate-image` JSON body。
- Produces: 可选 `frameIndex: 1 | 2` 和兼容别名 `frame_index`；缺省仍返回两个 `task_ids`。

- [ ] **Step 1: 写接口契约失败测试**

新增：

```python
def _submit_keyframes(self, frame_index_marker):
    submitted = []
    sent = []
    payload = {"workflow_mode": "keyframes", "quantity": 2, "prompt": "shot"}
    if frame_index_marker is not None:
        payload["frameIndex"] = frame_index_marker
    def fake_urlopen(request, timeout=None):
        submitted.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse("task-%d" % len(submitted))
    with mock.patch.object(self.server, "_comic_storyboard_image_frame_prompts", return_value=["start", "end"]), \
            mock.patch.object(self.server.urllib.request, "urlopen", side_effect=fake_urlopen), \
            mock.patch.object(self.server, "_send_json_with_headers", side_effect=lambda *args: sent.append(args)):
        self.server._handle_comic_frame_generate_image_proxy(
            object(), "/api/v1/comic-drama/storyboards/293001/generate-image",
            "https://platform.example.test/generate-image",
            json.dumps(payload).encode("utf-8"), "keyframes",
        )
    return submitted, sent

def test_keyframes_without_frame_index_still_submit_both_frames(self):
    submitted, _sent = self._submit_keyframes(None)
    self.assertEqual([item["frame_index"] for item in submitted], [1, 2])

def test_keyframes_frame_index_one_submits_only_start_frame(self):
    submitted, _sent = self._submit_keyframes(1)
    self.assertEqual(len(submitted), 1)
    self.assertEqual(submitted[0]["frameIndex"], 1)
    self.assertTrue(submitted[0]["billingRequestId"].endswith(":frame:1"))

def test_keyframes_frame_index_two_submits_only_end_frame(self):
    submitted, _sent = self._submit_keyframes(2)
    self.assertEqual(len(submitted), 1)
    self.assertEqual(submitted[0]["frameIndex"], 2)
    self.assertTrue(submitted[0]["billingRequestId"].endswith(":frame:2"))

def test_keyframes_invalid_frame_index_rejects_without_upstream_or_billing(self):
    submitted, sent = self._submit_keyframes(3)
    self.assertEqual(submitted, [])
    self.assertEqual(sent[-1][1], 400)
    self.assertIn("frameIndex", sent[-1][2]["detail"])

def test_comic_generate_image_openapi_limits_frame_index_to_start_or_end(self):
    text = OPENAPI.read_text(encoding="utf-8")
    path_start = text.index("  /api/v1/comic-drama/storyboards/{storyboard_id}/generate-image:")
    path_end = text.index("\n  /", path_start + 3)
    contract = text[path_start:path_end]
    self.assertIn("frameIndex:", contract)
    self.assertIn("frame_index:", contract)
    self.assertIn("enum: [1, 2]", contract)
    self.assertIn("'400':", contract)
```

单帧测试断言上游只收到一个 payload，且 `frame_index`、`frameIndex` 和 `billingRequestId` 后缀分别是对应的 `1` 或 `2`；非法值断言 HTTP 400 且 `urlopen` 未调用。

- [ ] **Step 2: 运行测试确认 RED**

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_aicanvas_frame_billing -v
```

Expected: 原双帧测试 PASS，三个新行为测试 FAIL。

- [ ] **Step 3: 实现严格参数筛选**

在拆分出 `frame_prompts` 后筛选：

```python
raw_frame_index = payload.get("frameIndex", payload.get("frame_index"))
if raw_frame_index not in (None, ""):
    try:
        requested_frame_index = int(raw_frame_index)
    except (TypeError, ValueError):
        requested_frame_index = 0
    if workflow_mode != "keyframes" or requested_frame_index not in (1, 2):
        _send_json_with_headers(handler, 400, {"detail": "frameIndex must be 1 or 2 for keyframes"})
        return True
    indexed_prompts = [(requested_frame_index, frame_prompts[requested_frame_index - 1])]
else:
    indexed_prompts = list(enumerate(frame_prompts, 1))
```

后续循环使用 `for index, frame_prompt in indexed_prompts`。返回 `task_id` 为唯一任务；单帧请求的 `task_ids` 只含一个元素。

- [ ] **Step 4: 同步直接路由行为**

检查 `_expand_comic_storyboard_image_submit_kwargs()` 和直接 `generate-image` 路由。确保它们读取同一筛选结果，避免代理路径支持单帧而直接路径仍生成两张。不得改变无参数双帧分支。

- [ ] **Step 5: 更新 OpenAPI 契约**

在 `docs/openapi.yaml` 增加 `/api/v1/comic-drama/storyboards/{storyboard_id}/generate-image`，请求体同时允许 `frameIndex` 和 `frame_index`，两者均为 `type: integer`、`enum: [1, 2]`；响应列出 200 和 JSON Schema 校验失败的 400。请求体不得包含密钥或账号凭证字段。

- [ ] **Step 6: 运行远程逻辑测试确认 GREEN**

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_aicanvas_frame_billing tests.test_aicanvas_real_person_fallback tests.test_openapi_contract -v
```

Expected: 全部 PASS，现有双帧和备用模型测试无回归。

---

### Task 4: 本地单帧重生成状态机

**Files:**
- Modify: `backend/matrix_native_client.py`
- Modify: `tests/test_video_replacement.py`

**Interfaces:**
- Consumes: `ComicProjectAdapter.submit_storyboard_image(storyboard_id, job, segment, frame_index=None)`、`download_media()`。
- Produces:
  - `_archive_comic_media_attempt(segment: dict, media_kind: str, frame_kind: str = "") -> dict`
  - `_apply_comic_frame_regeneration_result(segment: dict, frame_kind: str, task_id: str, url: str, path: str) -> dict`
  - `VideoReplacementPage.regenerate_comic_frame(row: int, frame_kind: str) -> None`
  - `VideoReplacementPage._run_comic_frame_regeneration(job: dict, segment: dict, frame_kind: str) -> None`

- [ ] **Step 1: 写单帧状态测试**

新增：

```python
def test_comic_adapter_single_frame_payload_uses_frame_index(self):
    adapter = self.client.ComicProjectAdapter.__new__(self.client.ComicProjectAdapter)
    adapter.comic_json = mock.Mock(return_value={"data": {"task_id": "frame-task"}})
    adapter.submit_storyboard_image(201, {"comicProjectId": 88}, {"index": 1}, frame_index=2)
    body = adapter.comic_json.call_args.args[2]
    self.assertEqual(body["frameIndex"], 2)
    self.assertEqual(body["frame_index"], 2)

def test_regenerate_start_frame_only_updates_start_and_marks_video_stale(self):
    segment = {
        "startFrameTaskId": "old-start", "startFrameUrl": "old-start.png", "startFramePath": "old-start.local",
        "endFrameTaskId": "old-end", "endFrameUrl": "old-end.png", "endFramePath": "old-end.local",
        "videoPath": "old.mp4", "status": "done",
    }
    self.client._apply_comic_frame_regeneration_result(
        segment, "start", "new-start", "new-start.png", "new-start.local"
    )
    self.assertEqual(segment["startFrameTaskId"], "new-start")
    self.assertEqual(segment["endFrameTaskId"], "old-end")
    self.assertEqual(segment["status"], "video_stale")
    self.assertNotIn("videoPath", segment)
    self.assertEqual(segment["retryHistory"][-1]["videoPath"], "old.mp4")

def test_regenerate_end_frame_only_updates_end_and_marks_video_stale(self):
    segment = {
        "startFrameTaskId": "old-start", "endFrameTaskId": "old-end",
        "videoPath": "old.mp4", "status": "done",
    }
    self.client._apply_comic_frame_regeneration_result(
        segment, "end", "new-end", "new-end.png", "new-end.local"
    )
    self.assertEqual(segment["startFrameTaskId"], "old-start")
    self.assertEqual(segment["endFrameTaskId"], "new-end")
    self.assertEqual(segment["endFramePath"], "new-end.local")
    self.assertEqual(segment["status"], "video_stale")
```

成功断言：未选中的帧任务、URL、Path 不变；旧视频进入 `retryHistory`；`videoPath` 不再作为当前合成输入；状态为 `video_stale`。失败断言旧媒体仍可查看，错误编号可追踪。

- [ ] **Step 2: 运行测试确认 RED**

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_adapter_single_frame_payload_uses_frame_index tests.test_video_replacement.VideoReplacementHelpersTest.test_regenerate_start_frame_only_updates_start_and_marks_video_stale tests.test_video_replacement.VideoReplacementHelpersTest.test_regenerate_end_frame_only_updates_end_and_marks_video_stale -v
```

Expected: FAIL，单帧方法和状态尚不存在。

- [ ] **Step 3: 扩展 adapter**

```python
def submit_storyboard_image(self, storyboard_id, job, segment, frame_index=None):
    payload = _comic_storyboard_video_payload(job, segment)
    if frame_index is not None:
        payload["frameIndex"] = int(frame_index)
        payload["frame_index"] = int(frame_index)
    return self.comic_json(
        "POST",
        "/api/v1/comic-drama/storyboards/%d/generate-image" % int(storyboard_id),
        payload,
        120,
    )
```

- [ ] **Step 4: 实现媒体归档和单帧执行器**

归档记录只保存脱敏地址摘要、任务 ID、模型、本地路径、操作时间和操作类型。单帧成功后：

```python
segment[task_key] = task_id
segment[url_key] = image_url
segment[path_key] = image_path
segment["status"] = "video_stale"
segment["stage"] = "video_stale"
segment["videoStaleReason"] = "%s_frame_regenerated" % frame_kind
segment.pop("error", None)
segment.pop("errorId", None)
```

保留旧视频文件但把当前 `videoPath` 移到重试历史，防止最终合成使用旧视频。

- [ ] **Step 5: 运行测试确认 GREEN**

重复 Step 2 命令，Expected: 3 tests PASS；再运行完整 `tests.test_video_replacement`。

---

### Task 5: 视频强制重生成与批量失败重试

**Files:**
- Modify: `backend/matrix_native_client.py`
- Modify: `tests/test_video_replacement.py`

**Interfaces:**
- Consumes: 当前片段的 `startFrameUrl/endFrameUrl`、`script`、音频配置和 `ComicProjectAdapter.submit_storyboard_video()`。
- Produces:
  - `_comic_segments_ready_for_video_retry(segments: list[dict]) -> tuple[list[dict], list[dict]]`
  - `VideoReplacementPage._run_comic_video_regeneration(job: dict, segments: list[dict]) -> None`
  - `VideoReplacementPage.regenerate_selected_segment()` 在漫剧模式下只重生成视频。
  - `VideoReplacementPage.retry_failed_segments()` 在漫剧模式下批量重生成可用双帧完整的失败视频。

- [ ] **Step 1: 写视频重生成失败测试**

新增：

```python
def test_comic_video_regeneration_never_regenerates_frames(self):
    class VideoOnlyAdapter:
        def submit_storyboard_image(self, *_args, **_kwargs):
            raise AssertionError("video regeneration must not submit images")
        def submit_storyboard_video(self, *_args, **_kwargs):
            return {"data": {"task_id": "video-task"}}
        def wait_task_result(self, *_args, **_kwargs):
            return "http://comic/data/new.mp4", {"data": {"status": "completed"}}
        def download_media(self, _url, path, **_kwargs):
            Path(path).write_bytes(b"video")
            return path
    page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
    page._cancel_requested = False
    segment = {
        "index": 1, "comicStoryboardId": 201,
        "startFrameUrl": "start.png", "endFrameUrl": "end.png", "status": "failed",
    }
    with tempfile.TemporaryDirectory() as td, \
            mock.patch.object(self.client, "ComicProjectAdapter", return_value=VideoOnlyAdapter()), \
            mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
            mock.patch.object(self.client, "_save_replacement_job", return_value=None):
        page._run_comic_video_regeneration({"outDir": td, "segments": [segment]}, [segment])
    self.assertEqual(segment["status"], "done")

def test_comic_video_regeneration_uses_latest_frames_script_and_audio(self):
    segment = {
        "startFrameUrl": "new-start.png", "endFrameUrl": "new-end.png",
        "script": "最新口播稿", "audioUrl": "new-audio.mp3",
    }
    payload = self.client._comic_storyboard_video_payload({"audioMode": "tts"}, segment)
    self.assertIn("new-start.png", json.dumps(payload, ensure_ascii=False))
    self.assertIn("new-end.png", json.dumps(payload, ensure_ascii=False))
    self.assertIn("最新口播稿", json.dumps(payload, ensure_ascii=False))

def test_comic_video_payload_preserves_generated_sound_in_auto_mode(self):
    payload = self.client._comic_storyboard_video_payload(
        {"audioMode": "source"},
        {"script": "只作为剧本文字", "startFrameUrl": "start.png", "endFrameUrl": "end.png"},
    )
    self.assertEqual(payload["audio_mode"], "auto")
    self.assertNotIn("audio_prompt", payload)

def test_comic_video_payload_enables_tts_only_for_tts_mode(self):
    payload = self.client._comic_storyboard_video_payload(
        {"audioMode": "tts", "voiceId": "xiaosi"},
        {"script": "需要配音的口播稿", "startFrameUrl": "start.png", "endFrameUrl": "end.png"},
    )
    self.assertEqual(payload["audio_mode"], "tts")
    self.assertEqual(payload["audio_prompt"]["dialogue"]["text"], "需要配音的口播稿")

def test_comic_batch_retry_skips_missing_frames_and_continues_valid_segments(self):
    missing = {"index": 1, "status": "failed", "startFrameUrl": "start.png"}
    ready = {
        "index": 2, "status": "failed",
        "startFrameUrl": "start.png", "endFrameUrl": "end.png",
    }
    runnable, skipped = self.client._comic_segments_ready_for_video_retry([missing, ready])
    self.assertEqual(runnable, [ready])
    self.assertEqual(skipped, [missing])
    self.assertIn("请先重新生成缺失的", missing["error"])
```

假 adapter 的 `submit_storyboard_image()` 必须抛 `AssertionError`，用以证明视频按钮不会重生成图片。缺帧批量测试断言跳过片段保留失败，并产生“请先重新生成缺失的首帧/尾帧”提示；其他片段正常提交视频。

- [ ] **Step 2: 运行测试确认 RED**

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_video_regeneration_never_regenerates_frames tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_video_regeneration_uses_latest_frames_script_and_audio tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_batch_retry_skips_missing_frames_and_continues_valid_segments -v
```

Expected: FAIL，现有 `_run_job_segments()` 会走完整首尾帧和视频链路。

- [ ] **Step 3: 实现强制视频重生成执行器**

流程必须固定为：同步当前口播稿、检查双帧、归档旧视频、更新远程分镜、强制提交新视频、轮询、鉴权下载、校验、设置 `done`。不得复用“已有 `videoUrl` 直接下载”的初始恢复分支。

- [ ] **Step 4: 调整两个按钮入口**

漫剧模式：

```python
if QMessageBox.question(self, "重新生成视频", "确定重新生成片段 %s 的视频吗？" % index) != QMessageBox.Yes:
    return
run_bg(lambda: self._run_comic_video_regeneration(self._job, [segment]))
```

底部批量入口先筛选 `status in ("failed", "download_failed")`，再分为 `ready` 和 `missing_frames`。确认后只运行 `ready`；缺帧列表写入页面提示。旧链路任务继续使用原有行为。

- [ ] **Step 5: 运行测试确认 GREEN**

重复 Step 2，并补跑两个声音模式契约测试。Expected: 5 tests PASS；补跑 `tests.test_video_replacement` 全量。

---

### Task 5A: 自动声音与 AI 音色的远程隔离

**Files:**
- Modify: `tools/aicanvas_remote/server_current.py`
- Modify: `tests/test_aicanvas_frame_billing.py`

**Interfaces:**
- Consumes: Matrix 视频请求中的规范化 `audio_mode=auto|tts` 和现有 `_comic_storyboard_video_params_with_dialogue_audio()`、`_finalize_ai_comic_fallback_video_audio()`。
- Produces: 自动模式保留生成视频自带声音；AI 音色模式保持现有 TTS 生成与备用模型 TTS 重混。

- [ ] **Step 1: 写声音隔离失败测试**

增加远程源测试，断言：

1. `audio_mode=auto` 时 `_comic_storyboard_video_params_with_dialogue_audio()` 不调用 `_submit_comic_storyboard_dialogue_audio()`，返回参数不含 TTS 音频字段。
2. `audio_mode=tts` 时继续调用 TTS 并写入音频参数。
3. 备用模型任务的源参数为 `audio_mode=auto` 时，`_finalize_ai_comic_fallback_video_audio()` 不调用 FFmpeg 重混，保留 provider `result_url`，并写入 `audioSource=provider_generated`。
4. 备用模型任务为 `audio_mode=tts` 时，现有 TTS 强制重混测试继续通过。
5. 未携带 `audio_mode` 的漫剧网页旧请求保持现有默认 TTS 行为，避免改变现有漫剧功能。

- [ ] **Step 2: 运行目标测试确认 RED**

只运行新增声音模式测试和现有 fallback TTS 测试，确认失败点分别是远程函数尚未读取 `audio_mode`，不得以 mock 导入或测试装配失败作为 RED。

- [ ] **Step 3: 实现显式声音模式分支**

`_comic_storyboard_video_params_with_dialogue_audio()` 从请求参数读取并移除内部控制字段：显式 `auto` 直接返回且记录脱敏结构化事件；显式 `tts` 和未传字段继续现有逻辑。任务注册时把规范化声音模式保存到可追踪元数据。`_finalize_ai_comic_fallback_video_audio()` 对显式 `auto` 跳过 TTS 重混并设置 `audio_source/audioSource=provider_generated`、`audio_mix_status/audioMixStatus=not_requested`；仅 `tts` 或兼容旧请求执行现有重混。

- [ ] **Step 4: 运行测试确认 GREEN**

新增声音模式测试和所有现有 fallback TTS 测试必须通过；确认日志不包含音频 URL、Token 或完整请求头。

---

### Task 6: 客户端图片预览和视频列内嵌播放器

**Files:**
- Modify: `backend/matrix_native_client.py` near `VideoPlayerBox`, `_make_comic_frame_cell`, `refresh_segments`
- Modify: `tests/test_video_replacement_v2.py`

**Interfaces:**
- Consumes: `startFramePath`、`endFramePath`、`videoPath`，仅使用已下载和校验的本地文件。
- Produces:
  - `ComicImagePreviewDialog(QtWidgets.QDialog)`
  - `ComicSegmentVideoCell(QtWidgets.QWidget)`
  - `VideoReplacementPage._open_comic_frame_preview(segment: dict, frame_kind: str) -> None`
  - `VideoReplacementPage._make_comic_video_cell(segment: dict) -> QtWidgets.QWidget`

- [ ] **Step 1: 写 UI 契约失败测试**

调整现有源码契约测试并新增：

```python
def test_comic_frame_click_opens_local_preview_not_public_url(self):
    src = CLIENT.read_text(encoding="utf-8")
    block = src[src.index("def _make_comic_frame_cell"):src.index("def _make_segment_script_editor")]
    self.assertIn("_open_comic_frame_preview", block)
    self.assertNotIn("_open_url", block)

def test_comic_frame_cells_have_independent_regenerate_buttons(self):
    src = CLIENT.read_text(encoding="utf-8")
    block = src[src.index("def _make_comic_frame_cell"):src.index("def _make_segment_script_editor")]
    self.assertIn('regenerate_comic_frame(row, "start")', block)
    self.assertIn('regenerate_comic_frame(row, "end")', block)

def test_comic_video_column_uses_inline_player_not_url_text(self):
    src = CLIENT.read_text(encoding="utf-8")
    block = src[src.index("def refresh_segments(self):"):src.index("def open_output(self):")]
    self.assertIn("_make_comic_video_cell(seg)", block)
    self.assertNotIn('or seg.get("videoUrl")', block)

def test_comic_inline_player_does_not_autoplay(self):
    src = CLIENT.read_text(encoding="utf-8")
    start = src.index("class ComicSegmentVideoCell")
    block = src[start:src.index("class ", start + 10)]
    self.assertIn("autoplay=False", block)
    self.assertNotIn("self.player.play()", block)

def test_comic_row_action_is_named_regenerate_video(self):
    src = CLIENT.read_text(encoding="utf-8")
    block = src[src.index("def refresh_segments(self):"):src.index("def open_output(self):")]
    self.assertIn('tip="重新生成视频"', block)
    self.assertNotIn('tip="重生"', block)
```

断言 `refresh_segments()` 不再把 `seg.get("videoUrl")` 传入 `QTableWidgetItem`，帧点击不调用 `_open_url()`，播放器从 `videoPath` 加载且初始化后不调用 `play()`。

- [ ] **Step 2: 运行测试确认 RED**

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_comic_frame_click_opens_local_preview_not_public_url tests.test_video_replacement_v2.VideoReplacementV2Test.test_comic_frame_cells_have_independent_regenerate_buttons tests.test_video_replacement_v2.VideoReplacementV2Test.test_comic_video_column_uses_inline_player_not_url_text tests.test_video_replacement_v2.VideoReplacementV2Test.test_comic_inline_player_does_not_autoplay -v
```

Expected: FAIL，当前帧按钮打开公网地址，视频列是文本。

- [ ] **Step 3: 为 `VideoPlayerBox` 增加非自动播放加载能力**

保留现有 `play(path)` 行为，新增：

```python
def set_media(self, path, autoplay=False, loop=False):
    self._ensure_player(loop=loop)
    self.current_path = path
    self.player.setSource(QtCore.QUrl.fromLocalFile(path))
    if autoplay:
        self.player.play()
```

旧调用 `play(path)` 委托 `set_media(path, autoplay=True, loop=True)`，避免影响数字人口播预览。

- [ ] **Step 4: 实现图片单元格和本地预览**

图片单元格包含缩略图按钮和刷新图标。点击缩略图调用 `_open_comic_frame_preview()`；本地路径缺失时显示“正在获取图片”，后台鉴权下载完成后刷新，不打开网页。刷新按钮分别调用 `regenerate_comic_frame(row, "start")` 和 `regenerate_comic_frame(row, "end")`。

- [ ] **Step 5: 实现视频单元格**

`ComicSegmentVideoCell` 固定尺寸，包含播放器、播放/暂停、进度、音量和全屏图标。无有效 `videoPath` 时按状态显示“待生成”“待重新生成”“正在获取视频”或准确错误。页面刷新和销毁时停止并释放旧 player。

- [ ] **Step 6: 实现普通确认文案**

首帧、尾帧和视频分别只显示：

```text
确定重新生成片段 X 的首帧吗？
确定重新生成片段 X 的尾帧吗？
确定重新生成片段 X 的视频吗？
```

不得出现费用、任务数量或预计金额。

- [ ] **Step 7: 运行 UI 测试确认 GREEN**

重复 Step 2，Expected: 4 tests PASS；补跑 `tests.test_video_replacement_v2` 全量。

---

### Task 7: 文档、全量门禁与远程部署

**Files:**
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/openapi.yaml`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `CHANGELOG.md`
- Deploy source: `tools/aicanvas_remote/server_current.py`
- Deploy target: remote `/root/AI-CanvasPro/server.py`

**Interfaces:**
- Consumes: Tasks 1-6 的最终函数、字段、测试结果和准确行号。
- Produces: 可追踪发布记录、远程稳定版本备份、健康服务和可执行回滚命令。

- [ ] **Step 1: 更新四级文档和变更记录**

记录以下准确内容：

- `API_REFERENCE.md`：`frameIndex` Schema、返回 `task_ids` 数量、非法参数 400、片段新增状态和 Path 字段。
- `openapi.yaml`：为漫剧 `generate-image` 请求增加 `frameIndex` 和 `frame_index`，类型为整数、枚举为 `[1, 2]`；增加非法值 400 响应 Schema。
- `ARCHITECTURE.md`：远程生成 -> 鉴权下载 -> 校验 -> 本地预览/播放 -> 合成。
- `DEPLOYMENT.md`：远程备份、上传、服务重启、健康检查、回滚。
- `TROUBLESHOOTING.md`：401 根因、识别方法、“远程已生成/本地获取失败”错误处理。
- `CHANGELOG.md`：用户看到的播放器、图片预览和三个重生成入口。
- `migration.sql`：无数据库变化，不修改。

- [ ] **Step 2: 重算实现文档行号**

使用 `rg -n` 查找最终函数，将 `docs/IMPLEMENTATION.md` 更新为实际 `backend/matrix_native_client.py#Lx-Ly`、`tools/aicanvas_remote/server_current.py#Lx-Ly` 和测试行号。不得保留旧偏移或范围占位符。

- [ ] **Step 3: 运行语法和目标回归**

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tools/aicanvas_remote/server_current.py tests\test_video_replacement.py tests\test_video_replacement_v2.py tests\test_aicanvas_frame_billing.py
.\.venv-win\Scripts\python.exe -m unittest tests.test_aicanvas_frame_billing tests.test_video_replacement tests.test_video_replacement_v2 tests.test_aicanvas_real_person_fallback tests.test_openapi_contract -v
git diff --check
```

Expected: 编译退出码 0；全部测试 PASS；`git diff --check` 无输出。若现有无关测试失败，记录完整失败名并证明与本次改动无关，不得静默忽略。

- [ ] **Step 4: 创建远程回滚备份**

通过现有 SSH 运维方式执行，凭证从安全环境读取，不写入命令历史或文件：

```bash
stamp=$(date +%Y%m%d_%H%M%S)
cp /root/AI-CanvasPro/server.py "/root/AI-CanvasPro/server.py.bak.comic-frame-index-${stamp}"
sha256sum /root/AI-CanvasPro/server.py
```

记录备份路径和发布前 SHA-256 到 `docs/DEPLOYMENT.md` 的本次发布记录。

- [ ] **Step 5: 部署远程兼容扩展并检查健康**

上传经过测试的 `tools/aicanvas_remote/server_current.py` 到临时路径，校验 SHA-256 后原子替换 `/root/AI-CanvasPro/server.py`，随后：

```bash
systemctl restart ai-canvas.service
systemctl is-active ai-canvas.service
ss -ltnp | grep -q ':8777 '
curl --fail --silent --output /dev/null http://127.0.0.1:8777/login
```

Expected: 服务为 `active`，8777 正常监听，登录页返回 2xx 或 3xx。当前远程服务没有独立 `/health` 路由，因此同时使用进程状态、端口监听和 HTTP 登录页作为部署门禁。任一检查失败时立即恢复备份，不继续客户端真实测试。

- [ ] **Step 6: 远程接口冒烟**

使用测试项目或 mock 上游验证：无 `frameIndex` 返回两个任务；`frameIndex=1` 只返回首帧任务；`frameIndex=2` 只返回尾帧任务；非法值返回 400 且无新计费记录。日志只核对任务 ID 和参数摘要，不输出素材地址或 Token。

- [ ] **Step 7: 当前任务 300 只下载恢复**

打开本地任务 `5a8c84d4aa1f40239b49435abae6fd08` 时执行旧任务恢复：三段只鉴权下载现有远程视频，不重新生成、不重复计费。验证三个 `videoPath` 存在、媒体校验通过、表格显示播放器，随后自动合成仍使用三段当前视频。

- [ ] **Step 8: 客户端人工验收**

不自动重启本地客户端。通知用户手动重启后依次验证：

1. 视频列直接播放，不显示公网链接。
2. 点击首帧、尾帧在客户端内预览。
3. 重生成首帧只更新首帧并将视频标记为待重新生成。
4. 重生成尾帧只更新尾帧并将视频标记为待重新生成。
5. 重新生成视频使用最新双帧、口播稿和音频。
6. 批量重试跳过缺帧片段并继续其他失败视频。

- [ ] **Step 9: 最终提交前门禁**

重新运行 Step 2 行号校验和 Step 3 全量验证。只暂存本计划涉及的文件，检查 `git diff --cached --name-only` 不包含用户无关改动后再提交：

```powershell
git add backend/matrix_native_client.py tools/aicanvas_remote/server_current.py tests/test_video_replacement.py tests/test_video_replacement_v2.py tests/test_aicanvas_frame_billing.py tests/test_openapi_contract.py docs/API_REFERENCE.md docs/ARCHITECTURE.md docs/DEPLOYMENT.md docs/openapi.yaml docs/IMPLEMENTATION.md docs/TROUBLESHOOTING.md CHANGELOG.md docs/superpowers/specs/2026-07-29-comic-inline-media-regeneration-design.md docs/superpowers/plans/2026-07-29-comic-inline-media-regeneration.md
git diff --cached --name-only
git commit -m "feat: add inline comic media regeneration"
```

提交前必须确认 `docs/IMPLEMENTATION.md` 的行号与提交内容完全一致。

## Rollback

1. 本地回滚：恢复本次提交前的 `backend/matrix_native_client.py`；新增任务字段为可选，不需要数据迁移。
2. 远程回滚：把 `/root/AI-CanvasPro/server.py.bak.comic-frame-index-<timestamp>` 恢复为 `/root/AI-CanvasPro/server.py`，重启 `ai-canvas.service` 并检查健康。
3. 回滚判据：部署后错误率超过 1%、无参数双帧请求行为变化、重复计费、401 恢复循环超过一次、播放器导致页面持续卡死或崩溃。
4. 回滚后保留结构化错误日志和任务 JSON，不删除用户项目或已生成媒体。
