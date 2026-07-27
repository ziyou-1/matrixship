# 小红书图文同款真实多图发布设计

## 1. 背景

当前“小红书图文同款”已经能完成采集笔记图片、读取图文结构、生成同款预览、确认 AI 占位图，并保存 `type=image_note`、`platform=xhs` 的草稿素材。现有发布链路仍把图文草稿拦截为 `xhs_note_publish_not_supported`，小红书发布适配器也只接收标题，不填写正文和标签。

本设计把图文同款草稿升级为可真实发布的多图笔记，但仍采用本机浏览器方式：打开小红书创作台，自动上传图片并填写标题、正文、标签，最终公开发布前由用户人工确认。

## 2. 已确认范围

- 发布入口放在“图文同款”单独页面内，不跳转到“素材发布”页完成主流程。
- 采用浏览器自动化方式，不接未验证的小红书私有接口。
- 流程为：生成预览 -> 提交待发布 -> 选择小红书账号并人工确认 -> 上传图片、填写正文和标签 -> 确认正式发布 -> 保存成功/失败状态。
- 发布前必须展示并确认：账号、标题、正文、标签、图片。
- AI 占位图必须人工确认后才能发布。
- 缺图时允许系统自动生成 AI 占位图，但占位图默认不可直接发布。
- 第一版只支持单条图文草稿发布，不做批量矩阵发布。

## 3. PRD

### 3.1 用户目标

用户在“图文同款”页面完成一条小红书图文笔记的复刻、替换、审核和发布，不需要再理解素材保存到了哪里，也不需要手动去素材发布页找草稿。

### 3.2 核心流程

1. 用户在内容采集页选择单条小红书笔记，点击“图文同款”。
2. 系统下载笔记图片并进入“图文同款”页面。
3. 用户读取图文结构并生成同款预览。
4. 用户补充替换图；缺图槽位可生成 AI 占位图。
5. 用户确认 AI 占位图、标题、正文、标签和图片顺序。
6. 用户点击“提交待发布”或“发布到小红书”。
7. 页面弹出发布确认区，要求选择小红书账号并二次确认。
8. 系统调用本地 `/api/publish/run`，用浏览器打开小红书创作台。
9. 浏览器自动上传多张图片，填写标题、正文和标签。
10. dry-run 只填表不点发布；正式发布由二次确认后才点击发布。
11. 发布结果写回草稿素材和图文同款任务。

### 3.3 非功能需求

| 项目 | 目标 |
|---|---|
| 单客户端并发 | 发布任务串行，同一时间只允许 1 个浏览器发布任务 |
| QPS | 本地发布 API 按人工操作使用，设计峰值 0.05 QPS；不支持高频发布 |
| 延迟 | dry-run 120 秒内返回填充结果；正式发布 180 秒内返回提交结果或明确错误 |
| 图片数量 | 第一版支持 1-18 张图片，超过时阻断并提示用户裁剪 |
| 文件大小 | 沿用现有素材库文件限制；发布前校验文件存在 |
| GPU/显存 | 发布链路不使用 GPU，显存上限为 0；AI 占位图生成沿用既有生成能力，不在本设计扩容 |
| 可观测 | 每次发布记录 `materialId`、`replacementJobId`、`accountId`、`platform`、`dryRun`、`errorId`、`finalUrl` |
| 可回滚 | 新增功能开关控制图文真实发布；关闭后恢复为只保存草稿 |
| 可追溯 | 草稿、任务、发布响应都保留 `replacementJobId` 和 `sourceTemplateId` |

## 4. 技术选型

| 方案 | 优点 | 风险 | 结论 |
|---|---|---|---|
| A. 图文同款页内发布，复用 `/api/publish/run` 和浏览器适配器 | 用户路径最短；复用现有账号、素材、发布锁；改动集中 | 需要扩展发布参数和小红书表单填充 | 采用 |
| B. 保存草稿后去“素材发布”页发布 | 复用现有发布页 | 用户仍然找不到草稿，流程断裂 | 不采用 |
| C. 新增独立“图文待发布队列” | 适合批量运营 | 第一版范围扩大，队列、状态、风控都要新增 | 暂不采用 |
| D. 接小红书私有发布接口 | 理论上更快 | 接口不稳定、合规和封控风险高 | 不采用 |

## 5. 架构设计

### 5.1 前端/原生客户端

在 `XhsNoteReplacementPage` 中增加发布区：

- 小红书账号下拉框：复用 `GET /api/accounts` 和 `clean_accounts(..., platform="xhs", ready_only=True)`。
- 发布预览：展示最终标题、正文、标签和图片槽位。
- 操作按钮：
  - `提交待发布`：保存草稿并停留在页面，标记为可发布状态。
  - `试填到小红书`：`dryRun=true`，上传和填写，不点击发布。
  - `正式发布`：二次确认后 `dryRun=false`。
- 状态提示：
  - AI 图未确认：提示“AI 占位图未确认，请先确认后再发布”。
  - 无账号：提示“未找到已登录的小红书账号，请先到账号矩阵登录”。
  - 缺图片：提示“未找到图片素材，请先保存草稿或补充图片”。

### 5.2 本地 API

扩展 `POST /api/publish/run` 请求参数：

```json
{
  "materialId": "material-id",
  "accountId": "xhs-self",
  "platform": "xhs",
  "dryRun": false,
  "publishTitle": "标题",
  "publishBody": "正文",
  "publishTags": ["#标签1", "#标签2"],
  "confirmImageNote": true
}
```

处理规则：

- `publishTitle` 存在时优先使用，否则回退素材 `title`。
- `publishBody` 存在时优先使用，否则回退素材 `body`。
- `publishTags` 存在时优先使用，否则回退素材 `tags`。
- `type=image_note` 且 `platform=xhs` 时必须检查 `aiImageReview.pendingSlots`。
- 未传 `confirmImageNote=true` 时，真实发布返回 `xhs_note_manual_confirm_required`。
- dry-run 不要求二次确认字段，但仍要求 AI 占位图已确认。

### 5.3 小红书浏览器适配器

扩展 `xhs_publish_material(...)`：

- 入参增加 `body`、`tags`、`account_id` 或 `publish_context`。
- `material_type=image_note` 时按多图笔记处理。
- 上传 `files` 中全部图片，保留顺序。
- 填写标题输入框。
- 填写正文编辑器。
- 标签处理：
  - tags 统一规范为不带重复空格的 `#xxx`。
  - 优先把标签追加到正文末尾，降低创作台标签控件变化导致失败的风险。
  - 如页面存在明确标签输入框，再尝试逐个填充。
- dry-run 返回 `filled=true`、`published=false`。
- 正式发布只在用户二次确认后执行点击发布。

### 5.4 状态回写

发布完成后更新本地素材库中的草稿记录：

```json
{
  "status": "published",
  "published": 1,
  "publishedAt": 1784957762.0,
  "publishResult": {
    "platform": "xhs",
    "accountId": "xhs-self",
    "dryRun": false,
    "finalUrl": "https://creator.xiaohongshu.com/...",
    "error": ""
  }
}
```

失败时保留草稿，不删除文件：

```json
{
  "status": "publish_failed",
  "published": 0,
  "publishError": {
    "error": "upload_input_not_found",
    "errorId": "err-...",
    "stage": "xhs_publish"
  }
}
```

图文同款任务同步记录 `publishStatus`、`publishMaterialId`、`publishAccountId`、`publishError`。

## 6. 发布门禁

`image_note_publish_blocker(material)` 调整为：

- 非 `image_note` 返回空。
- `platform` 不是 `xhs` 返回 `xhs_note_platform_unsupported`。
- `files` 为空返回 `no_files`。
- `aiImageReview.pendingSlots` 非空返回 `xhs_note_ai_image_unconfirmed`。
- 不再对已确认 AI 图统一返回 `xhs_note_publish_not_supported`。

中心服 `publish_preflight` 继续复用该 blocker。这样素材、账号、节点、额度仍走现有预检。

## 7. 错误码

| 错误码 | 场景 | 用户提示 |
|---|---|---|
| `xhs_note_ai_image_unconfirmed` | AI 占位图未确认 | AI 占位图未确认，请先确认后再发布 |
| `xhs_note_manual_confirm_required` | 正式发布缺少二次确认字段 | 请先在发布确认弹窗中确认账号、标题、正文、标签和图片 |
| `xhs_note_platform_unsupported` | 图文草稿不是小红书平台 | 图文同款草稿只能发布到小红书 |
| `xhs_note_too_many_images` | 图片超过 18 张 | 小红书图文最多处理 18 张，请删减后重试 |
| `xhs_publish_body_fill_failed` | 正文编辑器填充失败 | 正文填写失败，请在打开的浏览器中手动补齐 |
| `xhs_publish_tag_fill_failed` | 标签控件填充失败 | 标签填写失败，请检查正文末尾标签或手动补齐 |
| `upload_input_not_found` | 创作台未找到上传控件 | 请确认小红书账号已登录，并重新打开创作台 |

所有异常日志必须结构化输出，并脱敏 URL token、Cookie、Authorization 和本地敏感路径。

## 8. API 契约与文档

实施时需要同步：

- `docs/API_REFERENCE.md`：更新 `/api/publish/run` 请求字段和图文发布说明。
- `docs/openapi.yaml`：补充 `publishBody`、`publishTags`、`confirmImageNote` 的 JSON Schema。
- `docs/IMPLEMENTATION.md`：记录实现位置，使用 `backend/xxx.py#Lx-Ly` 格式。
- `docs/TROUBLESHOOTING.md`：记录 dry-run、正式发布、AI 未确认、账号未登录等排障项。
- `CHANGELOG.md`：记录“图文同款真实多图发布”。

不新增数据库表，不需要 `migration.sql`。如果实施中发现中心服需要新增持久化字段，再单独补迁移脚本。

## 9. 测试策略

### 9.1 失败测试先行

实施前先补失败测试：

- AI 占位图未确认时 `/api/publish/run` 返回 `xhs_note_ai_image_unconfirmed`。
- AI 占位图已确认后 `image_note_publish_blocker` 不再返回 `xhs_note_publish_not_supported`。
- `/api/publish/run` 能把 `publishBody`、`publishTags` 传入 `xhs_publish_material`。
- 小红书图文发布 dry-run 不点击发布，只返回 `filled=true`。
- 原生图文同款页面包含账号选择、试填、正式发布和二次确认文案。

### 9.2 冒烟测试

用 4 张假图片构造 `image_note`：

1. 生成预览。
2. 确认 AI 占位图。
3. 保存草稿。
4. 选择 `xhs-self`。
5. 调用 dry-run。
6. 验证接口返回 `filled=true`、`published=false`。
7. 验证草稿未被标记为已发布。

正式发布由于会真实对外提交，自动化测试只覆盖到二次确认和适配器调用边界，不在单元测试里点击真实发布。

### 9.3 回归测试

- 抖音视频发布不受影响。
- 小红书视频/普通素材发布不受影响。
- 内容采集一键进入图文同款不受影响。
- 图文同款保存草稿不受影响。
- 中心服发布预检仍能阻断无账号、无节点、超额发布。

## 10. 可观测性

新增结构化日志事件：

- `xhs_note_publish_requested`
- `xhs_note_publish_preflight_blocked`
- `xhs_note_publish_filled`
- `xhs_note_publish_submitted`
- `xhs_note_publish_failed`
- `xhs_note_publish_state_saved`

关键字段：

- `materialId`
- `replacementJobId`
- `sourceTemplateId`
- `accountId`
- `dryRun`
- `imageCount`
- `tagCount`
- `error`
- `errorId`
- `stage`

日志不得输出 Cookie、Authorization、完整本地私密目录或带 token 的 URL。

## 11. 回滚方案

- 增加独立开关 `XHS_NOTE_PUBLISH_ENABLED`，默认启用；设置为 `0/false/no/off` 后图文真实发布入口禁用。
- 保留 `XHS_NOTE_REPLACEMENT_ENABLED` 控制图文同款整体入口。
- 回滚代码时恢复：
  - `backend/platform_adapters.py`
  - `backend/api_server.py`
  - `backend/central_server.py`
  - `backend/xhs_note_replacement.py`
  - `backend/matrix_native_client.py`
  - `tests/test_xhs_note_replacement.py`
  - 相关 docs 和 `CHANGELOG.md`
- 已保存草稿继续保留，不自动删除。
- 失败发布只写状态，不删除原图，用户可手动重试。

## 12. 第一版不做

- 不做批量图文矩阵发布。
- 不做定时自动发布图文。
- 不绕过浏览器人工确认。
- 不接小红书私有接口。
- 不自动切换多个小红书账号 profile。
- 不承诺识别小红书发布成功后的最终笔记 URL，第一版只保存创作台返回 URL 和提交状态。

## 13. 用户审核点

本设计采用方案 A：在“图文同款”页面内完成保存、账号确认、dry-run 和正式发布。实施前需要确认本设计文档范围无误，再进入 implementation plan 和测试先行实现。
