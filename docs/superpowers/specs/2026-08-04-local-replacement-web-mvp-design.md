# 本地执行端替换网页 MVP 设计

## 1. 背景与目标

当前 MatrixShip 的视频同款替换和小红书图文同款能力主要在本地客户端和本地执行端内闭环。视频替换依赖本机素材文件、账号状态、素材上传、公网 HTTPS 媒体 URL、远程 AI Canvas/LK888 任务状态；图文替换已有 `backend/xhs_note_replacement.py` 和本地 `/api/xhs-note-replacement/*` 接口。项目在 2026-07-27 之后已移除独立产品 Web 交付面，因此本次不恢复完整 Web 前端工程，只在本地执行端新增一个轻量网页入口。

目标是在本地执行端新增 `GET /replacement` 页面，提供两个标签页：视频替换和图文替换。用户通过浏览器粘贴来源链接、上传替换素材、启动替换任务并查看任务状态。第一版只实现替换功能，不接采集工作台、不接真实发布、不做资产库管理页面，也不替代现有 Qt 客户端页面。

## 2. 用户范围

- 本地已启动执行端的内测用户。
- 用户在浏览器打开 `http://127.0.0.1:<local-port>/replacement`。
- 页面只面向本机使用，不作为公网产品页面发布。
- 页面复用本机账号、浏览器登录态、素材目录和现有本地任务能力。

## 3. 非目标

- 不新增独立 `frontend/` 工程。
- 不恢复旧 Web 产品交付面、`/admin` 页面或 Web 构建链路。
- 不把远程 AI Canvas 变成图文同款宿主。
- 不做真实小红书发布。
- 不做资产库浏览、素材发布队列、账号矩阵管理或批量矩阵生成。
- 不迁移现有 Qt 同款替换和图文同款页面。
- 不允许把本地文件路径、`data:image/...` 或完整签名 URL 直接传给 LK888 或远程模型。

## 4. PRD

### 4.1 视频替换

用户打开视频替换标签页后，可以：

1. 粘贴来源视频链接。
2. 上传人物图、产品图、场景图。
3. 可选填写口播稿、卖点、风格要求。
4. 点击开始替换。
5. 查看任务阶段、错误提示和结果视频。

第一版视频替换复用现有同款替换核心逻辑。Web 层只负责收集输入、上传素材、启动任务和查询状态。

### 4.2 图文替换

用户打开图文替换标签页后，可以：

1. 粘贴小红书图文链接。
2. 上传替换图片。
3. 填写业务名称、地区、卖点、目标客户和语气。
4. 点击生成图文替换。
5. 查看图片槽位、3 套文案候选和草稿状态。

第一版图文替换复用 `backend/xhs_note_replacement.py` 和现有 `/api/xhs-note-replacement/*` 能力。若需要从链接现场下载图文素材，仍由本机执行端使用现有小红书下载逻辑处理。

## 5. 非功能性需求

| 项目 | MVP 目标 |
|---|---|
| 本机并发 | 单用户同一时间最多 1 个视频替换任务和 1 个图文替换任务 |
| API QPS | 本机状态查询支持 5 QPS，启动任务接口按用户点击触发，不做高并发承诺 |
| 页面响应 | `/replacement` HTML 首屏本机返回 p95 小于 300 ms |
| 启动任务响应 | start API 在完成参数校验和本地任务创建后 2 秒内返回 jobId，真实生成异步执行 |
| 状态查询延迟 | 本地任务状态更新后 1 秒内可被查询到 |
| GPU 显存 | 本地端不新增深度学习模型，新增显存占用 0 MiB |
| 文件大小 | 单张上传图片默认不超过 20 MB，视频替换第一版不接收本地视频上传，只接收来源链接 |
| 链接安全 | 仅接受 `http://` 和 `https://` 来源链接，日志中脱敏 query、token 和签名参数 |
| 可观测 | 每个任务记录 jobId、taskType、stage、sourceHost、errorId、providerTaskId 或远程 taskId |
| 可回滚 | `MATRIX_REPLACEMENT_WEB_ENABLED=0` 后隐藏页面和 start API |
| 可追溯 | 本地任务 JSON 记录来源链接摘要、输入素材清单、阶段、错误码、结果 URL 形态 |

## 6. 技术选型对比

| 方案 | 做法 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| A. 本地执行端单页，复用现有本地接口和任务逻辑 | `backend/api_server.py` 直接服务 `/replacement` HTML 和少量 JSON API | 改动小，账号、文件、浏览器登录态都在本机；最容易回滚 | UI 简单，长期扩展性一般 | 采用 |
| B. 新增独立前端工程 | 新建 React/Vue 页面调用本地 API | 视觉和交互扩展性强 | 重新引入 Web 构建面，违背近期 Web 面移除方向 | 不采用 |
| C. 中心服挂统一 Web 页面 | 中心服 `/replacement` 做统一账号和任务入口 | 长期适合云端协作和审计 | 第一版要处理本地 worker、文件、账号、远程鉴权，范围过大 | 后续评估 |
| D. 远程 AI Canvas 挂替换页面 | `/comic-tool/replacement` 直接复用远程视频生成 | 视频侧接近远程能力 | 图文、小红书登录态、本地素材都不在远端，契约复杂 | 不采用 MVP |

## 7. 架构

第一版只新增本地执行端 Web 壳层：

```text
Browser /replacement
  -> backend/api_server.py local HTTP handler
    -> video replacement web facade
      -> existing local upload helpers
      -> existing VideoReplacement task logic
      -> remote AI Canvas / LK888 with HTTPS media URLs only
    -> note replacement web facade
      -> existing xhs download/material handoff when needed
      -> backend/xhs_note_replacement.py
      -> existing /api/xhs-note-replacement/* compatible job state
```

Web facade 是薄层，负责：

- 参数校验。
- 素材暂存和上传。
- 任务创建。
- 状态查询。
- 错误脱敏。
- 将用户输入映射到现有替换任务结构。

Web facade 不负责重新实现模型调用、视频合成、图文文案生成或发布。

## 8. 页面设计

`GET /replacement` 返回一个无构建依赖的 HTML 页面，内联少量 CSS 和 JavaScript。页面结构：

- 顶部：标题“替换生成”和本地服务状态。
- 标签页：视频替换、图文替换。
- 视频替换表单：
  - 来源视频链接。
  - 人物图。
  - 产品图。
  - 场景图。
  - 口播稿。
  - 卖点/风格要求。
  - 开始替换按钮。
  - 任务状态区域。
- 图文替换表单：
  - 小红书图文链接。
  - 替换图片多选。
  - 业务名称。
  - 地区。
  - 卖点。
  - 目标客户。
  - 语气。
  - 生成图文替换按钮。
  - 图片槽位和文案候选区域。

页面文字只服务操作本身，不放营销介绍。

## 9. API 契约草案

### 9.1 `GET /replacement`

返回 HTML。关闭 `MATRIX_REPLACEMENT_WEB_ENABLED` 时返回 404 JSON：

```json
{
  "ok": false,
  "error": "replacement_web_disabled"
}
```

### 9.2 `POST /api/replacement/video/start`

请求使用 `multipart/form-data`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `sourceUrl` | string | 是 | 原视频链接，仅允许 HTTP(S) |
| `characterImage` | file | 是 | 人物参考图 |
| `productImage` | file | 否 | 产品参考图 |
| `sceneImage` | file | 否 | 场景参考图 |
| `script` | string | 否 | 用户口播稿 |
| `sellingPoints` | string | 否 | 卖点和风格要求 |

成功响应：

```json
{
  "ok": true,
  "jobId": "rvw_...",
  "taskType": "video",
  "status": "queued",
  "stage": "created"
}
```

失败响应：

```json
{
  "ok": false,
  "error": "replacement_video_invalid_source_url",
  "errorId": "err-...",
  "stage": "preflight"
}
```

### 9.3 `GET /api/replacement/video/job?id=...`

成功响应：

```json
{
  "ok": true,
  "jobId": "rvw_...",
  "taskType": "video",
  "status": "running",
  "stage": "uploading_assets",
  "progressText": "正在上传替换素材",
  "result": {
    "videoUrl": "",
    "localPath": ""
  },
  "error": ""
}
```

### 9.4 `POST /api/replacement/note/start`

请求使用 `multipart/form-data`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `sourceUrl` | string | 是 | 小红书图文链接 |
| `replacementImages` | file[] | 是 | 替换图片 |
| `businessName` | string | 是 | 业务名称 |
| `region` | string | 否 | 地区 |
| `sellingPoints` | string | 否 | 卖点，换行或逗号分隔 |
| `audience` | string | 否 | 目标客户 |
| `tone` | string | 否 | 语气 |

成功响应：

```json
{
  "ok": true,
  "jobId": "xnr_...",
  "taskType": "note",
  "status": "preview",
  "stage": "preview_created"
}
```

### 9.5 `GET /api/replacement/note/job?id=...`

响应复用图文同款 job 结构的安全子集：

```json
{
  "ok": true,
  "jobId": "xnr_...",
  "taskType": "note",
  "status": "preview",
  "stage": "preview_created",
  "imageSlots": [],
  "copyCandidates": [],
  "draftMaterialId": ""
}
```

正式实施时需要同步 `docs/openapi.yaml` 和 `docs/API_REFERENCE.md`，每个请求和响应都要有 JSON Schema 或 multipart 字段约束说明。

## 10. 数据流

### 10.1 视频替换

1. 页面提交 `sourceUrl` 和素材文件。
2. 后端校验链接 scheme、文件类型、文件大小。
3. 后端保存本地任务 JSON，生成 `rvw_` jobId。
4. 后端把素材上传成公网可访问 HTTPS URL。
5. 后端调用现有视频替换任务封装。
6. 现有链路调用远程 AI Canvas 或 LK888。
7. 后端轮询或读取任务状态，并更新本地 JSON。
8. 页面轮询 `GET /api/replacement/video/job` 展示状态。
9. 成功后展示结果视频 URL 或本地路径。

### 10.2 图文替换

1. 页面提交小红书图文链接、替换图片和业务信息。
2. 后端校验链接和图片。
3. 若链接尚未转成素材，后端调用现有本机小红书图文下载或材料构造能力。
4. 后端调用 `xhs_note_replacement.build_template()`。
5. 后端把替换图片映射到图文槽位。
6. 后端调用 `build_replacement_preview()` 生成槽位和文案候选。
7. 后端保存 `xnr_` job。
8. 页面展示槽位、文案候选和草稿状态。

## 11. 错误处理

| 错误码 | 场景 | 用户提示 |
|---|---|---|
| `replacement_web_disabled` | 功能开关关闭 | 替换网页未启用 |
| `replacement_invalid_source_url` | 链接为空或非 HTTP(S) | 请填写有效链接 |
| `replacement_upload_too_large` | 文件超过限制 | 图片过大，请压缩后重试 |
| `replacement_unsupported_file_type` | 文件类型不支持 | 请上传 PNG、JPG、JPEG、WEBP 图片 |
| `replacement_video_missing_character_image` | 视频替换缺人物图 | 请上传人物参考图 |
| `replacement_note_missing_images` | 图文替换缺替换图片 | 请上传至少一张替换图片 |
| `replacement_asset_upload_failed` | 素材上传公网 URL 失败 | 素材上传失败，请稍后重试 |
| `replacement_remote_submit_failed` | 远程模型提交失败 | 替换任务提交失败，请稍后重试 |
| `replacement_job_not_found` | 查询不到任务 | 任务不存在或已清理 |

异常日志必须使用结构化 JSON，包含 `errorId`、`stage`、`jobId`、`taskType` 和脱敏上下文。不得记录 Cookie、Token、Authorization、完整签名 URL、base64 图片内容或本地绝对隐私路径。

## 12. 可观测性

新增事件：

- `replacement_web_page_opened`
- `replacement_video_start`
- `replacement_note_start`
- `replacement_job_status`
- `replacement_asset_upload_failed`
- `replacement_remote_submit_failed`
- `replacement_job_failed`
- `replacement_job_completed`

每条事件记录：

- `jobId`
- `taskType`
- `stage`
- `sourceHost`
- `assetCount`
- `providerTaskId` 或远程 `taskId`
- `status`
- `errorId`
- `durationMs`

`sourceUrl` 只记录 host 和路径摘要，不记录 query 和 fragment。

## 13. 回滚方案

- 新增 `MATRIX_REPLACEMENT_WEB_ENABLED`，默认关闭或按发布策略确认后开启。
- 关闭开关后：
  - `/replacement` 返回 404 JSON。
  - `/api/replacement/video/start` 和 `/api/replacement/note/start` 返回 `replacement_web_disabled`。
  - 已存在任务 JSON 保留，便于审计，不自动删除。
- 回滚代码文件时恢复 `backend/api_server.py`、新增测试、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md`、`CHANGELOG.md` 和本设计相关实施文档。
- 不新增数据库表；若后续实现确认仍使用本地 JSON，`migration.sql` 写 no-op。

## 14. Phase 0 冒烟测试

实现完整生产代码前，先做最小骨架：

1. `GET /replacement` 返回两个标签页和空表单。
2. 使用假视频链接、假图片文件调用 `POST /api/replacement/video/start`。
3. API 只创建本地 `rvw_` job，不调用真实远程模型。
4. `GET /api/replacement/video/job` 返回 `queued`。
5. 使用假小红书链接、两张假图片调用 `POST /api/replacement/note/start`。
6. API 复用 `xhs_note_replacement.smoke_four_image_replacement()` 或等价安全骨架创建预览。
7. `GET /api/replacement/note/job` 返回 3 套文案候选。
8. 将失败点记录到 `docs/TROUBLESHOOTING.md`，修复后再进入完整实现。

## 15. 测试策略

### 15.1 单元测试

- 功能开关关闭时 `/replacement` 和 start API 不可用。
- `/replacement` HTML 包含视频替换和图文替换两个标签。
- 视频 start API 拒绝空链接、非 HTTP(S) 链接和缺人物图。
- 视频 start API 不把本地路径或 data URL 写入远程 payload。
- 图文 start API 拒绝空链接和空图片。
- 图文 start API 生成 `xnr_` job 和 3 套文案候选。
- 错误日志不包含 Cookie、Authorization、签名 query 或 base64。

### 15.2 回归测试

- 现有 Qt `VideoReplacementPage` 入口不变。
- 现有 Qt `XhsNoteReplacementPage` 入口和历史 `xhs_note_replace_start` 兼容不变。
- 现有 `/api/xhs-note-replacement/*` 测试继续通过。
- 现有 `/api/health`、安装包下载、账号矩阵和平台开关测试不受影响。

### 15.3 手工验收

1. 启动本地执行端。
2. 打开 `http://127.0.0.1:<local-port>/replacement`。
3. 视频替换提交假链接和图片后得到 jobId。
4. 图文替换提交假链接和图片后看到文案候选。
5. 关闭 `MATRIX_REPLACEMENT_WEB_ENABLED` 后页面和 start API 被阻断。

## 16. 文档影响

实施时需要同步：

- `docs/ARCHITECTURE.md`：说明这是本地执行端内嵌页面，不恢复独立 Web 前端。
- `docs/API_REFERENCE.md`：新增 `/replacement` 和 `/api/replacement/*`。
- `docs/openapi.yaml`：新增 API schema。
- `docs/DEPLOYMENT.md`：新增 `MATRIX_REPLACEMENT_WEB_ENABLED` 和本地端访问说明。
- `docs/TROUBLESHOOTING.md`：记录 Phase 0 冒烟结果、常见失败和回滚方式。
- `docs/IMPLEMENTATION.md`：实施后以 `path#Lx-Ly` 格式记录实际代码位置。
- `CHANGELOG.md`：记录新增本地替换网页 MVP。
- `migration.sql`：若无数据库变更，写明 no-op。

## 17. 验收标准

- 本地 `/replacement` 页面可打开，并展示两个替换标签页。
- 视频替换和图文替换均能提交任务并返回 jobId。
- 页面能查询任务状态并显示用户可读错误。
- 所有新增错误日志结构化且脱敏。
- 开关关闭后入口可回滚。
- 相关单测、回归测试、`py_compile` 和 Phase 0 冒烟通过。
- OpenAPI、API reference、部署、排障、实现行号和 changelog 与代码一致。
