# 接口手册

本文档覆盖登录/注册的版本化法律同意、下载入库、转写响应契约，以及“分解视频 -> 同款替换生成”的客户端内部事件。OpenAPI 3.1 契约见 `docs/openapi.yaml`。

## 鉴权

- 本地执行引擎：当 `MATRIX_AGENT_TOKEN_AUTH=1` 时使用 `Authorization: Bearer <MATRIX_AGENT_TOKEN>`。
- 中心服：使用登录后返回的会话 Token，格式同样为 Bearer Token。
- LK888 Key 只存在于中心服环境变量 `LK888_API_KEY`，客户端请求和文档中不得出现真实 Key。
- 中心服登录态返回 `appRole/productRole/roleScope`：`platform_admin` 表示平台管理员，`enterprise_admin` 表示企业家，`normal_user` 表示普通用户；数据范围分别为 `all/org/self`。

## POST /api/auth/login 与 /api/auth/register

客户端登录和注册请求必须携带当前版本的法律同意：

```json
{
  "identifier": "admin",
  "password": "<password>",
  "code": "",
  "legalConsent": {
    "accepted": true,
    "termsVersion": "1.0",
    "privacyVersion": "1.0",
    "acceptedAt": "2026-07-15T12:00:00Z",
    "clientVersion": "1.1.16"
  }
}
```

- `accepted` 必须为 `true`。
- `termsVersion` 和 `privacyVersion` 必须与中心服当前版本完全一致。
- `acceptedAt` 是客户端 UTC ISO-8601 时间；中心服另外记录不可由客户端修改的服务端接受时间。
- 手机号登录继续要求短信验证码；用户名登录只需用户名、密码和法律同意。
- 注册请求使用 `phone` / `password` / `code` / `legalConsent`。

缺少同意时返回 HTTP 428：

```json
{
  "ok": false,
  "error": "legal_consent_required",
  "requiredTermsVersion": "1.0",
  "requiredPrivacyVersion": "1.0",
  "effectiveDate": "2026-07-15"
}
```

版本不一致时 `error` 为 `legal_consent_outdated`。同意成功后，中心服将最新状态写入 `legalConsents`，并生成 `legal.consent.accept` 审计记录。

成功响应会额外返回当前产品角色，供本地客户端隐藏菜单和资金入口：

```json
{
  "ok": true,
  "token": "<session-token>",
  "user": {"id": "u-1", "name": "用户"},
  "organizations": [{"id": "org-a", "role": "member"}],
  "appRole": "normal_user",
  "productRole": "normal_user",
  "roleScope": "self"
}
```

## POST /api/auth/refresh

自动登录刷新会话前，客户端和中心服都检查用户已同意当前协议版本。协议升级后，旧会话刷新返回 HTTP 428，客户端清除自动登录并回到登录页重新确认。

刷新成功响应与登录成功响应保持同一角色契约，包含 `appRole/productRole/roleScope`。

## 三角色权限边界

- 管理员：`platform_admin`，可查看全部企业、用户和平台配置；充值、兑换码、加款、生成兑换码等资金入口仅此角色可用。
- 企业家：`enterprise_admin`，由企业内 `owner/admin` 映射而来，只能查看和管理自己企业范围的数据；不能访问充值、兑换码、用户加款或平台全局用户列表。
- 普通用户：`normal_user`，由企业内 `member` 映射而来，只能查看自己的账号、素材、知识库、任务和发布队列；不能查看企业中心管理内容或资金入口。
- `/api/enterprise/summary` 按角色返回 `scope=all/org/self`；`normal_user` 只统计有 `createdBy/createdByUserId/ownerUserId/userId` 归属到自己的数据。
- `/api/billing/recharge/packages`、`/api/billing/recharge/create`、`/api/billing/recharge/status`、`/api/billing/redeem`、`/api/billing/topup` 和 `/api/admin/redeem-codes/*` 均要求平台管理员。

## POST /api/enterprise/invites/create

本地客户端“企业中心 -> 团队成员 -> 邀请成员”使用该接口创建邀请码。新流程不要求填写手机号或邮箱；管理员必须选择企业，企业管理员固定为自己企业。

请求：
```json
{
  "orgId": "org-a",
  "recipientName": "张三",
  "role": "member",
  "ttlHours": 168
}
```

- `orgId` 必填，决定受邀用户加入哪个企业。
- `recipientName` 可选，仅用于预填邀请码登录页姓名；用户接受邀请码时仍可填写姓名。
- `role` 可为 `member` 或 `admin`；企业管理员只能邀请普通用户，平台管理员可邀请企业管理员。
- 不再提交 `phone` / `email`，即使旧接口仍兼容历史字段。

响应只在创建成功时返回一次明文 `inviteCode`；邀请列表和校验响应不得返回明文邀请码或 token hash。

## POST /api/enterprise/invites/verify

请求：
```json
{"token": "64位十六进制邀请码"}
```

成功时返回脱敏邀请摘要和企业信息，本地客户端只显示企业、角色和有效期，不再显示或预填手机号、邮箱。

## POST /api/enterprise/invites/accept

用户在本地客户端登录页选择“加入企业”后调用。新流程只要求邀请码、姓名和密码。

请求：
```json
{
  "token": "64位十六进制邀请码",
  "name": "张三",
  "password": "new-password-1"
}
```

成功后中心服创建或更新用户、写入该邀请码绑定企业的成员关系，并返回登录 session。历史邀请码如果携带手机号/邮箱且命中已有账号，仍可能返回 `existing_user_login_required`，此时客户端会显示“已有账号的当前密码”字段后重试。

## GET /api/accounts

运行单元：本地执行引擎 `127.0.0.1:9081`。

抖音支持多个本地授权账号并存。响应为数组，每个抖音账号都有独立 `id`、`profileDir`、`cookieReady`、`usable` 和 `capabilities`。新增账号使用稳定本地 ID，例如 `douyin-<hash>`；旧任务未指定账号时仍兼容 `douyin-self`。

```json
[
  {
    "id": "douyin-0123456789abcdef",
    "platform": "douyin",
    "name": "抖音账号 9abcdef",
    "cookieReady": true,
    "usable": true,
    "fans": "1200",
    "followers": "1200",
    "todayPublish": 2,
    "publishedToday": 2,
    "todayPublishDay": "2026-07-28",
    "todayPublishUpdatedAt": 1785235200.0,
    "profileDir": "/absolute/data/douyin_accounts/douyin-0123456789abcdef/dy_profile"
  }
]
```

`todayPublish` / `publishedToday` 来自中心服当天发布成功计数，中心服重启后会从状态文件恢复当天计数，跨天自动清零。`fans` / `followers` 是账号资料中的最近一次粉丝字段，不表示后台持续抓取平台粉丝数。

## POST /api/accounts/remove

请求：

```json
{"id": "douyin-0123456789abcdef"}
```

默认只移除本地账号注册表记录，不删除 profile 文件，便于误删后手工恢复。传入 `deleteFiles=true` 时才删除对应 `douyin_accounts/<id>/` 目录。默认账号 `douyin-self` 不允许通过该接口删除。

## POST /api/accounts/rename

运行单元：本地执行引擎 `127.0.0.1:9081`。
用途：只修改本机账号矩阵里的显示昵称，不修改平台账号资料，不返回 Cookie。

请求：
```json
{"id": "douyin-0123456789abcdef", "name": "123"}
```

成功响应：
```json
{"ok": true, "id": "douyin-0123456789abcdef", "name": "123", "updated": true}
```

字段约束：
- `id` / `accountId`：账号矩阵里的本机账号 ID；如果传入中心端组合 ID，会自动取冒号后的本机账号 ID。
- `name` / `nickname` / `displayName`：新的显示名，不能为空，最多保存 40 个字符。

该接口会同步写入账号注册表和 `account_display_meta.json`。后续 `/api/accounts` 返回会优先使用该昵称，内容采集、寻找线索、AI 触达、素材发布和自动化工作流的账号下拉也使用同一显示名。

## POST /api/douyin/download

运行单元：本地执行引擎 `127.0.0.1:9081`。

请求：

```json
{
  "url": "https://www.douyin.com/video/123",
  "accountId": "douyin-0123456789abcdef",
  "save_choice": "all",
  "dryRun": false
}
```

字段约束：

- `url`：必填字符串，抖音作品链接。
- `save_choice`：可选，默认 `all`。
- `dryRun`：可选布尔值；为 `true` 时只解析作品，不下载或入库。

成功响应：

```json
{
  "ok": true,
  "savePath": "/absolute/material/path",
  "files": [{"path": "/absolute/material/path/video.mp4", "kind": "video"}],
  "materialId": "stable-material-id",
  "material": {
    "id": "stable-material-id",
    "repaired": true,
    "duration": 42.18,
    "width": 1080,
    "height": 1920
  }
}
```

失败响应：

```json
{
  "ok": false,
  "error": "download_http_403",
  "stage": "download",
  "context": {"httpStatus": 403, "contentType": "text/html"}
}
```

如果文件已下载但本地素材库入库失败，固定返回 HTTP 500，不暴露原始异常和堆栈：

```json
{
  "ok": false,
  "error": "library_import_failed",
  "stage": "library",
  "errorId": "err-0123456789abcdef"
}
```

状态码：下载 403 返回 HTTP 403；其他下载或媒体校验错误返回 HTTP 502；入库失败返回 HTTP 500。中心服调度同一接口时也使用相同的入库失败契约。

## 小红书采集通用请求字段

适用于本地执行引擎的小红书搜索、笔记下载、读取评论和获客发现：`/api/xhs/search`、`/api/xhs/download`、`/api/xhs/comments`、`/api/finder/discover` 且 `platform=xhs`。

默认模式按动作区分：搜索和笔记下载默认游客采集；读取评论和获客中心小红书寻客必须使用已登录账号，不再先走游客模式。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `guestMode` | boolean | 搜索/下载为 `true`；评论/寻客为 `false` | `true` 表示游客采集，不读取登录账号 profile、Cookie 或授权状态；`false` 表示本次请求使用已登录账号采集。 |
| `accountCollectionConfirmed` | boolean | `false` | 仅当 `guestMode=false` 时有效。读取评论和获客中心小红书寻客必须为 `true`，否则返回 `xhs_account_collection_unconfirmed`。 |

游客采集不写入小红书安全模式计数；确认账号采集会执行风控预检和结果记录。搜索/下载公开访问受限时可能返回 `xhs_guest_login_required`、`xhs_guest_access_limited` 或 `xhs_ip_risk`，客户端会提示用户确认是否“使用账号采集一次”。评论和寻客属于账号动作，调用方应直接传 `guestMode=false`、`accountCollectionConfirmed=true`。

## POST /api/xhs/download

运行单元：本地执行引擎 `127.0.0.1:9081`，或由中心服调度到在线客户端。

请求使用 `url` 或 `noteUrl` 传入小红书笔记链接。返回结果会携带 `note.title`、`note.body`、`note.tags` 和 `savePath`，本地素材库会同步保留这篇笔记在电脑上的下载目录。只有下载结果包含有效素材 `id` 时才返回 `ok=true`；否则返回 HTTP 500 和 `library_import_failed`，不再出现“下载成功但素材为空”的假成功。

## POST /api/finder/discover

运行单元：本地执行引擎 `127.0.0.1:9081`，或由中心服调度到在线客户端。

请求：

```json
{
  "keyword": "丰田汽车",
  "platform": "xhs",
  "videoNum": 5,
  "commentMode": "page"
}
```

小红书搜索页触发安全限制时不再返回“成功但 0 条”，而是返回明确失败：

```json
{
  "ok": false,
  "platform": "xhs",
  "keyword": "丰田汽车",
  "videoCount": 0,
  "commentCount": 0,
  "leadCount": 0,
  "blocked": true,
  "riskCode": "300012",
  "error": "xhs_ip_risk",
  "errorId": "err-0123456789abcdef"
}
```

服务端同时记录 `xhs_collection_search_failed` 结构化日志，日志只包含关键词长度、关键词指纹、调试 URL 指纹和风险码，不记录搜索 URL 查询参数或页面正文原文。

## POST /api/library/update-title

运行单元：本地执行引擎 `127.0.0.1:9081`。

请求：

```json
{
  "id": "material-id",
  "title": "发布标题，可包含话题"
}
```

成功响应：

```json
{
  "ok": true,
  "id": "material-id",
  "title": "发布标题，可包含话题"
}
```

用于“素材与发布”页标题栏编辑。只更新素材 `title`，不改文件、账号或发布状态。素材不存在时返回 HTTP 404、`material_not_found`。

## POST /api/publish/run

运行单元：本地执行引擎 `127.0.0.1:9081`。

请求新增 `publishTitle`：

```json
{
  "materialId": "material-id",
  "accountId": "douyin-self",
  "platform": "douyin",
  "dryRun": false,
  "publishTitle": "以素材发布页标题栏内容为准"
}
```

`publishTitle` 可选。存在时真实发布标题以该字段为准；不存在时回退素材库保存的 `title`。正式发布提交前，本地发布器将标题限制为前 30 个字符；素材库保存的原始标题可以更长。

## GET /api/public-media/{materialId}/{fileName}

运行单元：中心服 `127.0.0.1:9080`，经 Cloudflare Tunnel 或正式 HTTPS 域名暴露给 LK888。

当中心服配置了 `PUBLIC_MEDIA_BASE_URL=https://...` 和 `PUBLIC_MEDIA_TOKEN_SECRET` 后，`/api/library/upload` 与 `/api/library` 会在素材响应中额外返回 `publicUrls`。这些 URL 带 `orgId`、`expires` 和 `token`，用于让 LK888 远程读取本地客户端上传的产品图、人脸图、场景图或视频片段。

## POST /api/library/upload

运行单元：本地执行引擎和中心服均支持。请求为 `multipart/form-data`，至少包含一个 `files` 文件；`title` 和 `type` 可选。图文同款草稿同步到中心素材库时会额外携带这些可追溯字段：`platform`、`body`、`tags`、`status`、`sourceTitle`、`sourceBody`、`sourceTags`、`sourceTemplateId`、`replacementJobId`、`localDraftMaterialId`、`importedFromXhsNoteReplacement`。

服务端只接收白名单字段，`tags/sourceTags` 可为 JSON 数组或普通字符串；布尔字段只接受常见 true/false 表达。未知字段会被丢弃，避免把客户端临时状态、Token 或签名 URL 写入素材库。

客户端也支持独立公网素材上传服务，不改变中心服 API：当本机环境或 `backend/.env` 配置了 `UPLOAD_API_URL` 与 `UPLOAD_TOKEN` 时，图片、视频和音频类 `upload_asset_url(path, title, "image"|"video"|"audio")` 会先以 `Authorization: Bearer <UPLOAD_TOKEN>` 上传到 `UPLOAD_API_URL`，并把响应里的公网 URL 或 `PUBLIC_UPLOAD_BASE_URL` / `PUBLIC_IMAGE_BASE_URL + filename/path` 作为 LK888 可拉取素材 URL。当前独立公网服务允许 `jpg/jpeg/png/webp/gif/mp4/mov/webm/mp3/wav/m4a/ogg/aac`，生产单文件上限 500MB。

示例：

```json
{
  "ok": true,
  "id": "mat-1",
  "urls": ["/api/library/file/mat-1/product.png"],
  "publicUrls": [
    "https://temporary.trycloudflare.com/api/public-media/mat-1/product.png?orgId=org-default&expires=1784122600&token=<signature>"
  ]
}
```

`token` 为 HMAC-SHA256 签名，签名内容包含 `orgId`、`materialId`、`fileName` 和 `expires`。过期、签名错误、素材不存在或文件名不属于该素材时返回 403/404。

## 同款替换内部事件

这些事件只在原生 Qt 客户端进程内通过 `BRIDGE.payload` 使用，不是公开 HTTP API。

| 事件 | 方向 | 用途 |
|---|---|---|
| `video_replace_start` | 分解页 -> 同款替换页 | 传递源视频路径、平台、来源链接和完整分解分析状态 |
| `video_replace_plan_ready` | 后台任务 -> 同款替换页 | 返回 `principalActor`、原片主角候选、口播/非口播类型和可编辑脚本 |
| `video_replace_progress` | 后台任务 -> 同款替换页 | 更新 `comic_project`、`comic_assets`、`comic_update_storyboard`、`comic_generate_frames`、`comic_generate_video`、`comic_download_video`、`awaiting_review` 阶段 |
| `video_replace_done` | 后台任务 -> 同款替换页 | 返回成片路径、资产 ID、音频检查、人工审核状态、失败片段和敏感素材清理结果 |

## 同款替换任务契约

同款替换新任务默认走漫剧项目模式，旧 JSON 没有 `replacementMode="comic_project"` 时仍按旧链路查看和重试。客户端不保存真实 LK888 Key，漫剧项目模式通过中心服换取 ticket 后再与漫剧生成器交换 token。

`replacementJob` 仍保存 `principalActor`、`personReferencePaths`、`personReferenceUrls`、`personReferenceFullBodyConfirmed`、`principalReplacementMode`、任务级 `model` 和 `sourceReplacementEntities`；旧 `faceSourcePaths` / `faceSourceUrls` 字段继续读取兼容。`sourceReplacementEntities` 由当前 `breakdownAnalysis.report/visual/frameNotes/ocr/transcript` 动态提取，记录原片人物、产品和场景槽位，不会把“展厅/门店”固定解释为汽车类目。

漫剧项目模式下，人物图映射到角色、产品图映射到道具、场景图映射到场景。每个片段会在本地 JSON 中记录 `comicStoryboardId`、`startFrameTaskId/startFrameUrl/startFramePath`、`endFrameTaskId/endFrameUrl/endFramePath`、`comicVideoTaskId/comicVideoResult/videoUrl/videoPath`，用于双帧展示、单段重生成和问题追踪。`flowchartTaskId/flowchartUrl` 继续读取和写入为首帧兼容别名。

创建项目载荷固定包含 `source_mode="matrix_video_replacement"`、`config.manualAssetsOnly=true`、`config.storyboardCount` 和精确 `storyboards` 数组。每个分镜的 `description/image_prompt/video_prompt` 只包含画面描述，最终口播稿只写入 `audio_prompt.dialogue.text`。远程服务仅在该来源模式下接受分镜种子，项目创建时不自动生成角色、场景或道具；普通漫剧项目会忽略外部分镜种子并保持原分析行为。

`replacementMode="comic_project"` 时：

- `model` 或 `comicVideoModel` 默认使用 `doubao-seedance-2-0-260128`。
- 片段 `script` 是漫剧分镜对白的唯一台词来源。
- 客户端 `audioMode` 使用 `auto` 或 `tts`：`source/origin/original/source_audio` 兼容映射为 `auto`，`voice/ai_voice` 映射为 `tts`。显式 `auto` 保留生成视频自带声音，不生成 TTS；显式 `tts` 按口播稿生成 TTS。远程服务把缺失或未知值规范为兼容 `legacy`，继续历史 TTS 与备用视频重混行为。`uploaded/uploaded_audio/upload` 仍会被前置阻断，直到漫剧后端提供稳定的片段音频接口。
- 片段失败不会抛整个任务；任务会进入 `partial`，`errorId` 保留在片段和任务 JSON 中。
- 漫剧任务查询响应提供 snake_case 和 camelCase 双版本的 `requested_model`、`actual_model`、`fallback_model`、`fallback_reason`、`fallback_applied`、`fallback_candidates`、`fallback_index`、`fallback_history`。降级历史项只包含模型、状态、远程任务 ID 和脱敏错误，不返回密钥或 Authorization。
- 默认视频链为 `doubao-seedance-2-0-260128 -> vidu/viduq3-mix_reference2video -> wan2.7-shouweizhen -> kling-v3-omni-shouweizhen -> pixverse-v6-shouweizhen`。Seedance 真人隐私拒绝或 R2V 明确返回 `InvalidParameter.AudioDurationExceeded` 时启动备用链；已受理任务明确失败才进入下一模型。查询超时、502、429 不触发新模型提交，分辨率和其他普通参数错误也不自动降级。
- 初次视频生成和单段视频重生成在模型提交前调用漫剧 `GET /api/model-prices` 读取价格，并通过中心服既有 `/api/billing/charge` 从当前本地账户扣费。按秒模型金额为 `price_per_call * duration`，按次模型金额为 `price_per_call`；Vidu 请求标识 `vidu/viduq3-mix_reference2video` 可映射到计价标识 `viduq3-cankaosheng`。当前公开价格响应没有 `billing_method/price_tiers`，客户端在缺失时按描述、provider 和模型标识推断，不能覆盖远程未公开的档位系数。
- 每次扣费使用唯一 `comic_video:<job>:project:<project>:seg:<segment>:<attempt>` 引用。提交或等待失败调用 `/api/billing/refund` 按同一引用退款；远程已经返回成功视频时视为模型成本已发生，本地下载失败不退款，后续 pending 下载恢复也不再次扣费。

旧任务继续保持旧链路字段兼容，但新任务的默认行为由 `VIDEO_REPLACE_DEFAULT_MODE=comic_project` 控制。把该变量设为 `legacy` 可紧急回退到旧 LK888 流程。

## POST /api/v1/comic-drama/storyboards/{storyboard_id}/generate-image

该接口由 AI Canvas 通用平台代理入口转发。请求体是 JSON object；不接受或返回 API Key、Cookie、Bearer Token 等凭据字段。

| 字段 | 类型 | 当前行为 |
|---|---|---|
| `workflow_mode` / `workflowMode` | string | 可选：`action_flow`、`keyframes`、`multiframe`。显式值优先。 |
| `quantity` / `count` | integer | workflow 省略时，值 `2` 推断为 `keyframes`，值 `7` 推断为 `multiframe`；随后才回退到待处理工作流或项目配置。 |
| `frameIndex` / `frame_index` | integer | 可选且仅允许 JSON integer `1` 或 `2`，只适用于 `keyframes`。两个别名同时出现时必须相等。字符串、布尔值、浮点数、越界值、冲突别名或非关键帧工作流均返回 400。 |
| `prompt`、`model` | string | 画面提示词和图片模型；不支持当前工作流的模型会返回 400。 |

成功响应始终包含 `data.task_id`。双帧和多帧工作流还包含 `data.task_ids`，列出本次全部任务 ID；`action_flow` 单任务响应可以省略 `task_ids`：

| 请求 | `task_ids` 数量 |
|---|---:|
| `action_flow` | 可省略；使用 `task_id` |
| `keyframes`，省略帧选择器 | 2（首帧、尾帧） |
| `keyframes`，`frameIndex=1` 或 `2` | 1（仅所选帧） |
| 省略 workflow，`quantity=2` | 2（按关键帧处理） |
| `multiframe` 或省略 workflow 且 `count=7` | 7 |

400 响应统一为 `{ "detail": "<校验消息>" }`。帧参数错误当前返回 `frameIndex must be 1 or 2 for keyframes`；图片模型校验失败也使用同一 `detail` 字符串 Schema。OpenAPI 只维护一个路径项和一组 `ComicStoryboardImageGenerateRequest/Response/ValidationError` Schema。

### 漫剧片段本地状态与恢复字段

- `status` 当前可见值包括 `pending/planned`、`running`、`generating_video`、`video_stale`、`failed`、`download_failed`、`done` 和 `cancel_requested`。
- `stage` 当前恢复相关值包括 `downloading_video`、`comic_update_storyboard`、`comic_generate_video`、`comic_download_video`、`video_stale`、`video_retry_blocked_missing_frames`、`download_failed`、`done` 和 `cancel_requested`；`stageLabel` 是客户端展示文本。
- 错误与质检字段为 `error`、`errorId`、`qcStatus`、`retryPrompt`、`retryHistory` 和 `videoStaleReason`。单帧成功后当前视频元数据会归档到 `retryHistory`，片段进入 `video_stale`，最终合成拒绝该状态。
- 远程视频完成而本地下载或校验失败时写入 `pendingComicVideoRecovery`。基础字段为 `status`、`remoteStatus`、`createdAt`、`taskId`、`videoUrl`、`urlSummary`、`result`、`requestedModel`、`actualModel`、`fallbackModel`、`modelFallbackReason`、`modelFallbackApplied`、`audioMode`、`audioSource`、`audioStatus`、`audioMixStatus`、`downloadAttempts`、`lastErrorId`；失败重试另写 `lastDownloadAttemptAt` 和 `downloadStatus`。
- 批量重试只对 `download_failed` 且 pending 状态为 `completed/success/done/succeeded`、同时具有 `taskId` 和 `videoUrl` 的片段执行鉴权下载与媒体校验，不更新分镜、不重新提交生成、不重复计费。成功后提升 candidate 的任务/模型/声音字段并删除 pending；失败则保留 pending 和最新错误编号。
- `auto` 的备用视频结果保留 provider 音轨，任务写 `audioSource=provider_generated`、`audioMixStatus=not_requested`；`tts` 与 `legacy` 执行分镜 TTS 重混，成功写 `audioSource=storyboard_tts`、`audioMixStatus=completed`，处理中或失败分别为 `processing/failed`。
- `comicVideoBilling` 是本地扣费快照，包含 `capability`、`ref`、`model`、`pricedModel`、`billingMethod`、`unitPrice`、`durationSec` 和 `amount`。该字段用于账户流水追溯和失败退款，不携带 Token、Cookie、Authorization 或完整媒体 URL。
- 漫剧 `audioMode=auto` 的最终合成门禁只接受 `status=done`、`reviewApproved=true`、`videoPath` 本地媒体校验通过且 `hasAudio=true` 的片段；旧 `audioStatus/qcStatus` 即使为失败也不单独阻断。其他声音模式继续要求 `audioStatus=passed` 和 `qcStatus=passed`。

## POST /lk888/v1beta/models/{model}:generateContent

运行单元：中心服 `127.0.0.1:9080`。

分解功能使用 Gemini 原生音频输入。请求包含一个文本指令和一个 `audio/mpeg` 的 `inline_data` 分片。中心服验证用户会话后注入 `LK888_API_KEY` 并转发。

客户端期望模型文本严格符合：

```json
{
  "language": "zh-CN",
  "segments": [
    {"startSec": 0.0, "endSec": 1.5, "text": "转写文本"}
  ]
}
```

约束：

- 顶层只能包含 `language` 和 `segments`。
- 分段只能包含 `startSec`、`endSec`、`text`。
- 时间范围为当前分片内的 0 到 60 秒，且 `endSec >= startSec`。
- 非空文本最大 4000 字符。
- 只有响应是明确的非 JSON 自然语言转写文本时，才降级为当前分片的粗时间戳。
- JSON/JSON-like 响应如果解析失败或不符合 Schema，记为该分片转写失败，不将错误说明当成口播。

## GET /api/health

中心服和本地执行引擎都提供该路径：

- 中心服返回 `mode=central`、版本、授权状态和在线节点数。
- 本地执行引擎返回 `agentReady`、授权状态、Cookie 状态、能力列表和数据目录。

## 客户端内部事件（legacy）

这些事件只在原生 Qt 客户端进程内通过 `BRIDGE.payload` 使用，不是公开 HTTP API。

| 事件 | 方向 | 用途 |
|---|---|---|
| `video_replace_start` | 分解页 -> 同款替换页 | 传递源视频路径、平台、来源链接和完整分解分析状态 |
| `video_replace_plan_ready` | 后台任务 -> 同款替换页 | 返回 `principalActor`、原片主角候选、口播/非口播类型和可编辑脚本 |
| `video_replace_progress` | 后台任务 -> 同款替换页 | 更新 `principal_video_edit`、`editing`、`digital_human`、`face_swapping`、`audio_muxing`、`qc`、`awaiting_review` 阶段 |
| `video_replace_done` | 后台任务 -> 同款替换页 | 返回成片路径、资产 ID、音频检查、人工审核状态、失败片段和敏感素材清理结果 |

旧 LK888 链路继续通过中心服 `/lk888` 反代调用媒体模型，客户端不保存真实 LK888 Key。`replacementJob` 还保存 `principalActor`、`personReferencePaths`、`personReferenceUrls`、`personReferenceFullBodyConfirmed`、`principalReplacementMode`、任务级 `model` 和 `sourceReplacementEntities`；旧 `faceSourcePaths` / `faceSourceUrls` 字段继续读取兼容。`sourceReplacementEntities` 由当前 `breakdownAnalysis.report/visual/frameNotes/ocr/transcript` 动态提取，记录原片人物、产品和场景槽位，不能把“展厅/门店”固定解释为汽车类目；开始生成或单段重试会重新计算，避免旧任务 JSON 里的错误槽位继续污染 QC。`principalReplacementMode=source_video_edit` 时，非口播请求默认使用 `happyhorse-video-edit`（或 `VIDEO_REPLACE_PRINCIPAL_MODEL`），如果页面选择了同款替换模型则由 `replacementJob.model` 覆盖，并保留源视频字段；LK888 “SD 2.0 全能参考”的真实模型标识为 `kwvideo-v2-quannengcankao`，云灵页面卡片 ID `76` 不写入生成请求。请求字段名集合写入 `segment.remoteRequestFields`，不写 URL 内容。每个 `segment` 保存 `segmentType`、`script`、`sourceSegmentUrl`、`editedVideoPath`、`audioStatus`、`qcStatus`、`qcWarnings`、`reviewApproved`、实际使用的 `model` 和 `errorId`。声音来源保存为 `audioMode=auto|tts|uploaded`：`auto` 使用生成视频自带声音且不回填原片声音，历史 `source/origin/original/source_audio` 会兼容映射为 `auto`；`tts` 使用 `voiceId` 按片段口播稿生成配音，`uploaded` 使用 `replacementAudioPath/replacementAudioUrl` 在最终成片阶段替换整条音轨且不做音色克隆。主角视觉 QC 另保存 `principalReplacementMatch`、`fullBodyAppearanceMatch`、`otherSubjectsPreserved`、`motionPreserved`；任一为否时硬阻断。任务状态只落本地 JSON，不新增公开 HTTP API 或数据库表。

主角模式的最小任务字段示例：

```json
{
  "principalActor": {
    "status": "detected",
    "bestFrameIndex": 2,
    "bbox": {"x": 100, "y": 100, "width": 300, "height": 700},
    "confidence": 0.92,
    "previewPath": ".../principal_actor_preview.jpg"
  },
  "personReferencePaths": [".../person-full.jpg"],
  "personReferenceUrls": ["https://cdn.example/person-full.jpg"],
  "personReferenceFullBodyConfirmed": true,
  "principalReplacementMode": "source_video_edit",
  "sourceReplacementEntities": {
    "mode": "source_entity_replacement",
    "people": [{"slot": "person_1", "role": "带货人物"}],
    "products": [{"slot": "product_1", "category": "枪灰色多功能淋浴花洒套装"}],
    "scenes": [{"slot": "scene_1", "type": "卫浴产品实体展厅/门店"}],
    "replacementRules": "未上传产品图/场景图时保留原片对应槽位，上传后强制替换为上传素材。"
  }
}
```

漂移防护字段写入同一个 `replacementJob`，用于审计、重试和回滚：

```json
{
  "driftGuardConfig": {
    "enabled": true,
    "preflightEnabled": true,
    "blockSevereDrift": true,
    "autoRetry": true,
    "maxRetries": 1
  },
  "referencePreflight": {
    "status": "passed",
    "blocked": false,
    "code": "ok",
    "sourceCategory": "卫浴产品介绍型短视频",
    "sourceRole": "带货人物",
    "sourceProductCategory": "枪灰色多功能淋浴花洒套装",
    "referenceRisks": []
  },
  "segments": [
    {
      "visualDriftQc": {
        "topicMatch": true,
        "roleMatch": true,
        "structureMatch": true,
        "severeDrift": false,
        "reason": ""
      },
      "driftRetryCount": 0,
      "retryReason": "",
      "blockedReason": ""
    }
  ]
}
```

- `referencePreflight.status`：`skipped`、`passed`、`warning`、`blocked` 或 `deferred`。`blocked` 会在远程视频生成前停止任务。
- `driftGuardConfig.enabled=false` 时，预检、严重漂移阻断和自动重试都关闭。
- 人物参考图中的行业制服、Logo、展厅、直播间或背景上下文只降级为 `warning`；系统继续把人物图当作身份参考，并在生成提示中忽略其背景和道具。
- 产品图与源视频产品类别不一致时只记录 `warning`，不再生成前阻断，因为上传产品图表示强制替换原片产品。场景图与源视频场景不一致时同样只做预检提醒；真正生成后若上传场景没有被采用，会由视觉 QC 返回 `scene_mismatch`。
- `visualDriftQc.severeDrift=true` 或 `topicMatch=false` 会返回 `visual_drift_blocked` 并进入严重漂移自动重试；`roleMatch=false` 返回 `role_mismatch`，`structureMatch=false` 返回 `structure_mismatch`，默认只作为人工复核提醒。
- `driftRetryCount` 是片段级自动重试次数，默认最多 1。仅 `visual_drift_blocked`、`topic_mismatch` 或 `severeDrift=true` 这类硬漂移会触发自动重试；重试后仍漂移时写入 `blockedReason=visual_drift_retry_exhausted` 并阻断最终合成。

图片参考输入优先使用 `publicUrls` 中的公网 HTTPS 代理地址；未配置公网代理时，关键帧仍可在请求内临时使用 `data:image/...`。旧任务的本中心 `/api/library/file/...` 会在内存中读取并转码，不持久化 Base64。数字人头像优先使用独立公网素材上传服务或上游返回的公网 URL；没有公网 URL 时，本地文件才转为 `data:image/...;base64,...` 并通过 `/lk888/v1/media/generate` JSON `params.image` 提交。同款替换源视频片段在配置独立公网素材上传服务后会先上传成 `https://img.yunlingai.net/uploads/...mp4`，否则继续依赖中心服 `publicUrls`，缺失公网 URL 时阻断。中心服仍保留 multipart 非文件字段解析以兼容其他媒体接口计费。

## 错误码

| 错误码 | 含义 | 处理 |
|---|---|---|
| `download_http_403` | 当前签名直链或鉴权被拒绝 | 自动刷新直链一次；再次失败需重登抖音 |
| `download_unexpected_content_type` | 下载结果为 HTML/JSON/文本 | 禁止落盘和入库 |
| `download_html_body` | 文件内容是错误页 | 禁止落盘和入库 |
| `media_missing_video_stream` | ffmpeg 未发现视频流 | 隔离或拒绝素材 |
| `media_invalid_duration` | 时长无效 | 拒绝素材 |
| `media_invalid_dimensions` | 宽高无效 | 拒绝素材 |
| `media_decode_failed` | ffmpeg 全量解码失败 | 拒绝或修复素材 |
| `media_decode_timeout` | ffmpeg 全量解码超时 | 按动态预算重试或调整环境变量 |
| `media_image_decode_failed` | 图片不能被 Pillow 完整解码 | 禁止入库 |
| `library_import_failed` | 本地或中心素材事务失败 | 根据 `errorId` 查找脱敏 JSON 日志 |
| `ocr_engine_unavailable` | Tesseract 和 RapidOCR 均不可用 | 报告降级，不阻断视觉分析 |
| `remote_timeout` | 单个转写分片超时 | 保留失败时间段，可点击重试 |
| `transcription_partial` | 部分分片成功 | 报告标注缺失范围 |
| `lk888_not_configured` | 中心服没有 LK888 配置或会话 | 检查中心服环境变量和登录状态 |
| `lk888_upstream_error` | LK888 上游重定向、降级 HTTP 或跨域被策略拦截 | 不跟随跳转，检查上游配置 |
| `video_replace_segment_failed` | 同款替换单个视频片段生成或下载校验失败 | 保留成功片段，点击“重试失败片段” |
| `video_replace_concat_failed` | 同款替换片段合成失败 | 根据 `errorId` 查日志，确认所有片段均通过媒体校验 |
| `video_replace_action_control_fallback` | 原片动作关键帧抽取或上传失败 | 片段自动回退到原标准远程生成链路；检查 `actionControlWarning` 和素材上传服务 |
| `video_replace_avatar_not_remote_or_local` | 数字人头像既不是可读本地文件，也不是公网 URL | 重新生成关键帧或重新选择人脸图 |
| `video_replace_sound_not_public` | TTS 没有返回远程可读音频 URL | 重试该口播片段 |
| `video_replace_reference_download_failed` | 旧任务的中心素材无法在本地读取 | 确认素材未删除或重新上传 |
| `video_replace_remote_media_required` | 非口播远程编辑只收到 localhost/私网素材 | 配置公网媒体基址后再下单，当前不会扣生成费 |
| `principal_source_video_required` / `principal_person_reference_required` | 主角源视频或人物参考图不是可由 LK888 读取的 HTTPS URL | 检查公网上传服务和任务字段，不提交本地路径 |
| `principal_video_edit_unavailable` | 主角源视频编辑模型不可用或契约不完整 | 停止片段，确认任务 JSON 的 `model` 是否在 LK888 目录可用、余额是否充足；可切换同款替换模型后重生片段 |
| `principal_video_edit_failed` | 主角源视频编辑上游失败 | 保留 `remoteRequestFields` 和 `errorId`，只重试该片段，不切换参考图模型 |
| `principal_replacement_mismatch` / `principal_appearance_mismatch` / `principal_other_subjects_changed` / `principal_motion_mismatch` | 主角身份、完整外观、其他人物或原片动作未通过视觉 QC | 阻断合成，检查首中尾帧后单段重试或人工确认 |
| `image_result_url_not_public` | 图片上游返回了不可供远程模型读取的 URL | 停止后续任务并检查上游网关 |
| `facefusion_not_configured` | FaceFusion 可执行文件不存在或不可执行 | 配置独立商用环境的 `FACEFUSION_BIN` |
| `facefusion_models_missing` | 商用许可模型目录缺失 | 配置 `FACEFUSION_MODEL_DIR`，不要捆绑许可不明权重 |
| `facefusion_license_missing` | 未填写许可证记录引用 | 配置 `FACEFUSION_LICENSE_REF` 后再执行 |
| `facefusion_failed` | 本地 FaceFusion 失败或超时，片段已回退到远程视频 | 查看 `facefusionErrorId`，人工审核是否接受未换脸结果 |
| `audio_missing` / `audio_silent` | 片段或成片无音轨、全静音 | 单段重试；FaceFusion 丢音轨时检查音频回填日志 |
| `face_mismatch` | 自动视觉 QC 判断人物不一致 | 调整授权人脸照片或单段重试 |
| `product_mismatch` | 产品、Logo 或主要包装文字不匹配 | 更换清晰产品参考图并单段重试 |
| `scene_mismatch` | 场景不符合参考图/描述 | 调整场景图或描述并单段重试 |
| `reference_mismatch` | 生成前参考图预检判断产品图或强阻断场景图与源视频主题/产品类别冲突 | 更换产品图或场景图；人物图行业/背景上下文只作为提醒，不默认阻断 |
| `visual_drift_blocked` | 生成结果严重偏离原片主题或商品类别 | 系统自动重试一次；仍失败时保留片段 JSON 与 `errorId`，不合成 |
| `topic_mismatch` | 生成主题与源视频行业/商品不一致 | 缩短片段或强化源视频锁定提示后单段重试 |
| `role_mismatch` | 生成人物角色与源视频角色不一致，但主题仍保留 | 默认进入人工复核；若开启严格 QC，再检查人物参考图是否带入冲突角色或场景 |
| `structure_mismatch` | 镜头结构或营销结构变化，但主题仍保留 | 默认进入人工复核；若开启严格 QC，再调整分段、减少参考图干扰后重试 |
| `visual_drift_retry_exhausted` | 严重漂移自动重试后仍失败 | 阻断合成，人工检查首中尾帧和参考素材后再重试 |
| `task status=错误` | LK888 已明确拒绝任务参数或模型能力 | 客户端立即停止轮询并显示上游消息，不再误报超时 |

## 生产观测与运营接口

以下接口已同步到 `docs/openapi.yaml`，用于生产排障、余额核对、节点观测和本地浏览器任务追踪。

| 接口 | 方法 | 权限 | 用途 |
|---|---|---|---|
| `/api/account/balance` | GET | 已登录用户 | 查询当前用户余额。 |
| `/api/billing/analytics` | GET | 已登录用户 | 查询当前用户账单看板的消费指标、趋势和分类分布。 |
| `/api/billing/ledger` | GET | 已登录用户 | 未提供已识别账单看板参数时兼容返回最近 100 条原始流水和余额；提供至少一个已识别参数时返回分页标准化流水。 |
| `/api/billing/charge` | POST | 已登录用户 | 按中心服能力价格扣费；当前口径为 `1 云豆 = 1 元`，请求可带 `capability`、`reason`、`amount`、`ref`，已知能力以中心服价格为准，余额不足返回 402。`comic_keyframe_image` 用于同款替换首尾帧图片，单价与 LK888 图片生成一致。 |
| `/api/billing/refund` | POST | 已登录用户 | 按 `ref` 幂等退回真实发生过的扣费；找不到可退流水时返回成功且退款 0。 |
| `/api/local-browser/status` | GET | 组织 member | 查询本地浏览器客户端在线状态和最近任务。 |
| `/api/local-browser/task` | GET/POST | 组织 member | 查询或创建本地浏览器任务。 |
| `/api/central/nodes` | GET | 组织 auditor | 查询在线节点和注册节点；root token 可通过 `all=1` 查看全量节点。 |
| `/api/enterprise/task-center` | GET | 组织 auditor | 查询企业任务中心汇总、失败分组和最近任务；包含中心调度任务、发布队列任务和本地客户端浏览器任务。 |

`GET /api/billing/analytics` 接受可选 `startDate`、`endDate`（`YYYY-MM-DD`）和 `groupBy=day|month`，默认以 `Asia/Shanghai` 的最近 30 个日历日按天聚合；包含首尾日在内的范围最多 366 天。指标只统计 `charged` 的视频、图片、配音和其他消费，充值不计入消费；模型用量退款会展开为独立的 `refunded/refund` 记录，也不计入消费。`dailyAverage` 以实际有消费的日期数为分母，零消费日期不稀释均值。余额可以是数值，也可以是精确字符串 `inf`。

`GET /api/billing/ledger` 的严格筛选模式接受同样的日期范围，以及 `type=video|image|voice|other|recharge|refund`、`status=charged|refunded|recharged|failed`、`page`（最小 1）和 `pageSize=20|50|100`。只要提供 `startDate`、`endDate`、`type`、`status`、`page`、`pageSize` 中至少一个已识别账单看板参数，就使用该严格模式；`BillingLedgerRow.balanceAfter` 对不能可靠重建的历史流水为 `null`，并且必须返回 `pagination.page/pageSize/total/totalPages`。未提供任何这六个已识别参数时，接口继续返回兼容的原始最近 100 条流水，不要求旧流水具有标准化行字段；无关查询参数同样保留该历史响应。两条接口均只读取当前已认证用户的数据，不能通过参数扩大到账户、组织或管理员范围。

无效日期、枚举或分页参数及超过 366 天的范围返回 400 `ErrorResponse`；未认证返回 401；服务端成功响应未通过内部账单 schema 校验时返回 500 `internal_billing_response_error`；配置完成但不可用的账单数据源返回 503 `billing_data_source_failed`。500/503 均提供可关联结构化日志的 `errorId`，不暴露数据源连接信息或凭据。

`/api/enterprise/task-center` 的最近任务列表会把 `localBrowserTasks` 归一化为普通任务行；内容采集、获客、工作流采集/下载、素材发布等通过本地客户端执行的任务会显示在同一个任务中心里。企业家看到本企业范围，普通用户只看到自己创建的任务。离线导致无法执行的本地任务也会记录为失败，便于排查“点击后没反应”的问题。

这些接口的响应 Schema 分别为 `AccountBalance`、`BillingAnalytics`、`LegacyBillingLedgerResponse`、`BillingLedgerResponse`、`LocalBrowserStatus`、`LocalBrowserTask`、`CentralNodes` 和 `EnterpriseTaskCenter`。OpenAPI 的 Ledger 200 使用互斥 `oneOf`：仅历史分支保留顶层 `additionalProperties: true` 和任意原始行字段；严格参数化分支与运行时 Draft 2020-12 schema 一致，要求分页且禁止未声明字段。

## 小红书图文同款

运行单元：本地执行引擎 `127.0.0.1:9081`。功能开关为 `XHS_NOTE_REPLACEMENT_ENABLED`，默认启用；设置为 `0/false/no/off` 时以下接口返回 `feature_disabled`。

### GET /api/xhs-note-replacement/job

按 `id` 或 `jobId` 查询本地 JSON 任务。找不到任务返回 HTTP 404、`not_found`。

### POST /api/xhs-note-replacement/template

从已采集素材或客户端传入的 `sourceNote` 构建图文结构模板。

请求示例：

```json
{
  "materialId": "mat-xhs-1",
  "sourceNote": {
    "url": "https://www.xiaohongshu.com/explore/abc",
    "title": "原笔记标题",
    "body": "原笔记正文",
    "tags": ["#本地", "#种草"]
  }
}
```

响应包含 `jobId`、`template` 和 `job`。模板只记录槽位、原文结构、来源素材本地路径和来源 ID，不执行发布。

### POST /api/xhs-note-replacement/preview

按模板和业务输入生成替换预览。`providedAssets` 优先按 `slotIndex` 匹配图片槽位，其次按 `slotRole/role` 匹配；缺图槽位仅作为待补齐占位，内部仍标记为 `source=ai_placeholder` 且 `confirmationStatus=pending`。当前客户端会在生成预览前要求用户手动补齐替换图片，不再提供“AI生成缺图”入口。

### POST /api/xhs-note-replacement/confirm-ai-image

兼容历史任务的待补齐占位槽位确认接口；可选 `filePath` 用于补充人工选择后的本地图片路径。当前客户端不再通过该接口生成或确认 AI 缺图，缺图应直接手动选择替换图片。

### POST /api/xhs-note-replacement/save-draft

将预览任务保存为 `type=image_note`、`platform=xhs`、`status=draft` 的素材。草稿会带上兼容历史占位状态的 `aiImageReview`、`sourceTitle`、`sourceBody`、`sourceTags`、`sourceTemplateId`、`replacementJobId`、`importedFromXhsNoteReplacement=true`，供素材发布和资产库追溯。原生客户端保存本机草稿成功后会再调用中心 `/api/library/upload` 同步到中心素材库；同步失败不会回滚本机草稿，但会在客户端状态栏提示。若任一替换槽位没有真实图片文件，返回 HTTP 400 和 `xhs_note_replacement_missing_images`。

V1 明确不支持真实发布图文笔记：`/api/publish/run` 遇到未补齐历史占位的 `image_note` 会返回 `xhs_note_ai_image_unconfirmed`；未开放真实发布时返回 `xhs_note_publish_not_supported`。

## POST /api/douyin/dm/inbox

运行单元：本地执行引擎 `127.0.0.1:9081`，通常由中心服 `douyin.dm.inbox` 本地浏览器任务调度到用户自己的电脑执行。

用途：MVP 只读取一个指定客户主页链接对应的抖音私信会话，用于“全自动回复”每 20 秒检查一次新消息。该接口只返回最近消息和脱敏指纹；纯文本消息可进入 5 分钟合并回复窗口，图片、语音、视频、卡片、表情等非文本消息只触发人工查看，不自动发送。

请求：
```json
{
  "target": "https://www.douyin.com/user/MS4wLjABAAAA...",
  "accountId": "douyin-account-id",
  "limit": 10,
  "sinceFingerprint": "last-message-fp"
}
```

- `target` 必填：客户抖音主页链接或 `sec_uid`；纯数字 uid 不支持自动打开私信入口。
- `accountId` 可选：账号矩阵中的本地抖音账号 ID。从获客中心进入私信页时传当前所选账号；未传时，本地执行引擎选择最新的可用抖音账号。收信和自动回复必须使用同一个账号 ID。
- `limit` 可选：1-20，默认 10。
- `sinceFingerprint` 可选：上一条已处理消息指纹；如果页面还能看到该指纹，接口只返回它之后的新消息。

成功响应：
```json
{
  "ok": true,
  "platform": "douyin",
  "target": "https://www.douyin.com/user/MS4wLjABAAAA...",
  "accountId": "douyin-account-id",
  "dmCookieInjection": {
    "attemptedCount": 12,
    "addedCount": 12
  },
  "messages": [
    {
      "id": "9f7f1b2c3d4e5a6b",
      "fingerprint": "9f7f1b2c3d4e5a6b",
      "direction": "customer",
      "kind": "text",
      "text": "想了解价格",
      "createdAtText": "14:20"
    }
  ],
  "nonTextCount": 0,
  "sinceFingerprint": "last-message-fp",
  "limit": 10
}
```

失败或需人工处理：
```json
{
  "ok": false,
  "needLogin": true,
  "error": "not_authenticated",
  "messages": [],
  "nonTextCount": 0
}
```

常见错误：`missing_target`、`numeric_uid_unsupported_in_browser_dm`、`not_authenticated`、`dm_inbox_button_not_found`、`dm_inbox_messages_not_found`、`dm_inbox_child_failed`、`dm_inbox_child_exception`。

审计与日志：本地收件日志可记录 `accountId`、`targetFingerprint`、`limit`、Cookie 尝试数/注入数和错误类型；客户端自动回复日志使用 `targetFingerprint`、`messageFingerprint` 和 `errorCode` 关联排障。不记录 Cookie 值、Token、Authorization、客户主页原文或私信正文。

### 隐私边界补充

`/api/douyin/dm/inbox` 是本机执行引擎接口，私信正文只允许在用户本机客户端进程内用于 5 分钟合并和 AI 回复生成。原生客户端全自动收信直接调用 `127.0.0.1:9081`，不通过中心服任务结果传递正文。

如果外部仍通过中心服创建 `douyin.dm.inbox` 本地浏览器任务，中心服持久化的任务结果必须经过脱敏：不保存 `target` 原文，不保存 `messages[].text` 原文，只保存 `targetFingerprint`、`messageCount`、`messages[].fingerprint`、`messages[].textFingerprint`、`direction`、`kind`、`createdAtText`、`nonTextCount` 和错误码等排障字段。
