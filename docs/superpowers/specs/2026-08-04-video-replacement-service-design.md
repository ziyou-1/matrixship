# 视频替换共享服务设计

## 目标

将本地客户端“同款替换”的完整视频生成链路抽取为可调用的本地服务，使 Qt 原生页面和 `/replacement` 网页共用同一套任务、模型、恢复、质检、合成和计费逻辑。

本轮同时覆盖两条现有链路：

- `hybrid_v2`：本地源视频、参考素材上传、逐段视频生成、媒体质检和最终合成。
- `comic_project`：漫剧项目、分镜首尾帧、视频生成、远程任务恢复、模型回退和逐项实际计费。

网页支持两类入口：

1. 原生客户端打开网页时通过短期 `handoffId` 复用已有视频和分解结果。
2. 客户直接粘贴视频链接，服务负责平台校验、本地下载、视频分析和替换方案生成。

本轮不恢复独立 Web 产品前端，不把任务迁移到中心服，不把真实模型调用改成浏览器直连，不接真实发布流程。

## 设计原则

- `job.json` 是 Qt 和网页共享的唯一任务事实源。
- 服务层不依赖 Qt 控件、Qt 信号或浏览器请求上下文。
- 网页层只负责输入收集、状态展示和 API 适配。
- 任务提交成功不等于视频生成成功；必须完成 provider 状态确认、媒体下载和文件校验。
- provider task id、业务 job id、attempt 和 billing ref 必须持久化。
- 恢复任务时先查询已有 provider task，确认无有效结果后才允许重新提交。
- 不预扣费，不按异步提交响应扣费，只按最终实际费用结算。
- 日志使用结构化 JSON，记录任务、阶段、模型、错误编号和 task id 哈希，不记录密钥、Token、Cookie、绝对路径或完整签名 URL。
- 功能受 `MATRIX_REPLACEMENT_WEB_ENABLED` 和 `VIDEO_REPLACEMENT_SERVICE_MODE` 控制。

## 架构

### 组件职责

`backend/replacement_service.py`：

- 创建和恢复视频 job。
- 处理 handoff 或直接链接的源视频解析。
- 复用现有本地下载和证据型视频分析逻辑。
- 生成、保存和校验替换方案。
- 执行 `hybrid_v2` 和 `comic_project` 两条生成链路。
- 管理分段生成、失败重试、取消、人工确认和最终合成。
- 保存 provider task、回退和计费状态。
- 通过回调输出结构化进度，不感知 Qt 或 HTTP。

`backend/replacement_web.py`：

- 渲染 `/replacement` 页面。
- 解析 multipart 输入并校验 JSON 字段。
- 调用共享服务。
- 返回脱敏后的任务响应和本地鉴权下载地址。

`backend/matrix_native_client.py`：

- 保留现有 Qt 页面和用户交互。
- 在 shared 模式下调用共享服务。
- 将服务回调转换为现有 `BRIDGE.payload` 事件。
- 在 legacy 模式下保留现有链路，作为发布初期回滚路径。

`backend/api_server.py`：

- 暴露网页需要的本地鉴权 API。
- 保留 `/replacement` 页面开关和 Agent Token 校验。
- 不把本地源路径、私有媒体 URL 或用户凭据返回给浏览器。

### 源视频流程

```text
handoffId
  -> 读取本地 handoff
  -> 复用有效 sourceVideoPath/breakdownAnalysis
  -> 生成替换方案

直接 sourceUrl
  -> 校验 URL 和平台
  -> 调用现有本地平台下载链路
  -> 校验视频媒体
  -> 抽帧/OCR/音频转写/视觉分析/拆解报告
  -> 生成替换方案
```

如果 handoff 只有视频而没有有效分析结果，仍使用共享分析服务补齐分析，不把原生客户端内存状态作为网页依赖。

### 任务状态

准备阶段：

`source_queued -> downloading -> analyzing -> planned`

生成阶段：

`uploading -> preflight -> running -> partial|awaiting_review`

合成阶段：

`concatenating -> completed`

终止状态：

`failed`、`canceled`、`recovery_required`

任务和片段状态必须原子写入。运行中的任务在客户端重启后根据 job 文件恢复，不依赖进程内变量。

## API 设计

所有接口使用本地 Agent Token。请求和响应均更新到 `docs/openapi.yaml`，并为输入、输出和错误响应补充 JSON Schema。

### `POST /api/replacement/video/prepare`

接收 `multipart/form-data`：

- `handoffId`：可选，短期 handoff ID。
- `sourceUrl`：无 handoff 时必填。
- `characterImage`：人物参考图；纯产品模式可不传。
- `productImage`：可选，最多 3 张。
- `sceneImage`：可选。
- `scenePrompt`：可选场景描述。
- `noPersonMode`：是否纯产品模式。
- `audioMode`：`auto`、`tts` 或 `uploaded`。
- `voiceId`：AI 音色 ID。
- `replacementAudio`：完整配音音频。
- `model`：替换模型。
- `script`、`sellingPoints`：方案生成补充字段。

接口完成输入校验后创建 job，并异步完成源视频下载、分析和替换方案生成，返回 `jobId`、状态和阶段。

### `GET /api/replacement/video/job?jobId=...`

返回：

- `jobId`、`status`、`stage`、`progressText`。
- 脱敏的源平台和源 host。
- 片段时间、脚本、状态、质检状态和错误编号。
- `providerTaskId` 只返回安全标识或哈希，不返回凭据。
- 已完成视频的本地鉴权下载地址。
- `error` 和 `errorId`，不返回原始异常堆栈。

### `POST /api/replacement/video/execute`

接收 `jobId` 和客户确认后的方案编辑内容。只有 `planned` 状态允许执行。服务再次执行输入和授权预检，然后按当前模式运行完整替换链路。

### `POST /api/replacement/video/retry`

接收 `jobId` 和明确失败的片段编号。只允许重试失败片段，不允许网页传入任意 provider task id。服务先执行已有任务恢复检查，再决定是否创建新 attempt。

### `POST /api/replacement/video/concat`

接收 `jobId`。只有所有片段通过媒体和自动质检，并处于 `awaiting_review` 或可兼容的历史状态时，才执行最终合成。

### `POST /api/replacement/video/cancel`

接收 `jobId`，写入取消请求并停止后续片段。已完成 provider 任务不重复提交，也不因取消伪造失败或成功结果。

### 兼容接口

保留 `POST /api/replacement/video/start`，作为旧网页 MVP 的兼容入口。新网页使用 `prepare` 和 `execute` 两步流程，兼容入口不得绕过方案确认或真实服务的任务恢复规则。

## 恢复、回退和计费

### provider 任务恢复

- 每个媒体任务保存 provider task id、requested model、actual model、attempt 和状态。
- 网络超时、进程重启和请求异常优先查询已有 task。
- `comic_project` 的首帧、尾帧和视频任务独立恢复。
- 仅当远程明确无有效结果时允许新的 attempt。
- 模型回退必须记录回退原因、原任务状态和实际模型。
- 已有视频 URL 必须下载并校验后才能将片段标记为完成。

### 实际费用结算

- 不预扣费。
- 不使用提交响应中的估算费用扣费。
- 只从最终 provider payload 读取实际费用。
- 实际费用缺失时记录 `awaiting_actual_cost`，不估算扣费。
- billing ref 采用稳定格式，包含业务 job、片段、媒体类型、provider task 和 actual 标记。
- 同一 ref 只能结算一次；恢复和重试不能产生重复扣费。

## 并发、错误和安全

- 同一用户本机同时最多运行一个视频替换 job。
- job 锁必须跨 Qt 和网页生效，不能只依赖进程内布尔变量。
- 所有异常写入结构化日志，包含错误编号、任务 ID、阶段、模型和必要上下文。
- 用户响应只返回可操作中文错误，不返回堆栈、Token、Cookie、路径或完整私有 URL。
- 上传素材先写入受控任务目录，再上传为 provider 可访问的 HTTPS 媒体地址。
- 禁止向 provider 发送本地路径、`data:image` 或不可访问的私有地址。
- 本地文件下载使用已有 Token 保护的文件路由，并进行任务 ID、文件名和目录校验。

## 测试与质量门禁

### Phase 0 冒烟骨架

在实现完整服务前，使用短视频 fixture、fake downloader、fake analyzer 和 fake provider 跑通：

`链接/handoff -> job -> 分析 -> 方案 -> 执行 -> 查询 -> 合成`

必须验证失败任务不会显示生成成功，且 provider task 恢复不会重复提交。

### 单元和契约测试

- `hybrid_v2` 方案、分段生成、媒体质检和合成。
- `comic_project` 分镜、首尾帧、视频、恢复和模型回退。
- Qt adapter 与 Web adapter 共用同一个 job。
- 任务重启恢复、取消和失败片段重试。
- 实际计费 ref 幂等和 `awaiting_actual_cost`。
- OpenAPI JSON Schema 与实际响应一致。
- 本地路径、Token、Cookie 和签名 URL 脱敏。
- 保留并运行现有视频替换回归测试。

### 冒烟验证

- 临时端口验证 `/replacement` 和所有视频 API。
- handoff 入口执行一次准备流程。
- 直接链接入口执行一次下载和分析流程。
- fake provider 验证完整流程。
- 真实 provider 生成单独记录为 live smoke，不以 fake 结果代替。

## 上线、熔断与回滚

### 切换

使用 `VIDEO_REPLACEMENT_SERVICE_MODE=legacy|shared`：

1. 首次发布让网页使用 `shared`，Qt 保持 `legacy`。
2. 完成网页本地真实链路验证。
3. 再将 Qt 切换到 `shared`。
4. 重启本地执行端后生效。

不修改中心服、远程 AI Canvas 或数据库结构。文档、CHANGELOG 和 `migration.sql` 必须记录本次无数据库迁移。

### 自动熔断

本地执行端持久化最近任务统计。累计至少 100 个终态任务后，如果 shared service 错误率超过 1%，自动将新任务切回 `legacy`，不强制中断当前运行任务，并写入结构化日志。

当前本地执行端没有集中版本编排，因此本机熔断不等于跨客户自动恢复旧安装包。发布侧仍需保留上一稳定版本镜像或安装包 Tag，并根据日志决定版本回滚。

### 回滚

1. 设置 shared service 为 `legacy`。
2. 重启本地执行端。
3. 保留已有 job 文件和生成媒体，保证可追溯。
4. 若仍异常，恢复上一稳定客户端版本。
5. 不删除任务数据，不重复执行已完成 provider task，不重复结算费用。

## 非功能需求

- 本地 handoff/job API p95 小于 300 ms，不包含模型生成和视频分析。
- 本地任务并发：同一用户最多 1 个视频替换任务。
- 网页轮询：准备阶段 1 秒，生成阶段 2 秒。
- 图片单文件默认不超过 20 MB；视频源使用平台下载限制和既有媒体校验。
- 不新增常驻端口，不新增 GPU 服务。
- GPU/显存上限沿用现有 provider 和本地分析链路，不在网页层增加 batch。
- 所有跨边界事件可通过 job ID、provider task ID 哈希和错误编号追溯。

## 变更与回滚范围

预计涉及：

- `backend/replacement_service.py`
- `backend/replacement_web.py`
- `backend/matrix_native_client.py`
- `backend/api_server.py`
- 视频替换和网页 API 测试
- OpenAPI、API、架构、部署、排障、实现文档
- `CHANGELOG.md`
- `migration.sql`（记录无数据库迁移）

不涉及：

- 中心服业务 API 实现。
- 远程 AI Canvas 服务部署。
- 数据库表结构。
- 客户浏览器直连 provider。

