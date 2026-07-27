# Web 交付面移除与原生邀请迁移设计

## 1. 背景与目标

项目当前同时包含独立 Web 前端、后端内嵌管理页面和 Windows 本地客户端。正式产品只保留本地客户端，因此需要彻底移除可部署、可访问、可测试的项目 Web 页面，同时保证本地客户端的登录、企业管理、客户端更新、素材、采集、浏览器登录和发布链路不退化。

本次目标是：

- 删除全部活跃 Web 页面、静态资源、页面服务脚本、Web 专用路由和 Web 专用测试。
- 将原先依赖 `join-enterprise.html` 的企业邀请流程完整迁移到本地客户端。
- 保留本地客户端依赖的中心服 API、安装包下载、版本检查和真实浏览器自动化能力。
- 清除当前部署文档中的 Web 启动、部署和排障指引，保留可审计的历史变更记录。

## 2. 已确认需求

- 采用“删除活跃 Web 交付面并迁移必要能力到本地客户端”的方案 A。
- 删除整个 `frontend/` 目录，包括源码、`dist/`、静态依赖、图标、已弃用浏览器扩展和目录内工具。
- 删除 `backend/admin_console.html` 及中心服 `/admin` 页面路由。
- 删除 `backend/tools/dev_proxy.py`、Web 启动脚本、Web 专用测试和 Web 专用运行日志。
- 企业邀请不降级：管理员在客户端生成邀请码；受邀人在客户端输入邀请码并加入企业。
- 邀请流程同时保留未注册用户创建账号、已有用户验证当前密码并加入企业两种情况。
- 不删除本地客户端使用的 HTTP API、客户端安装包下载、版本检查和浏览器自动化代码。

## 3. 非目标

- 不删除 `backend/matrix_native_client.py`、`backend/api_server.py`、`backend/local_browser_worker.py`、`backend/utils/cookie_util.py` 或 `backend/utils/publish_util.py` 中的客户端能力。
- 不删除中心服 `/api/*` 业务接口，仅调整企业邀请返回契约并删除 HTML 页面路由。
- 不删除抖音、小红书登录和发布时由客户端启动的 Edge/Chromium 浏览器。
- 不删除 `/api/version` 或客户端安装包二进制下载能力。
- 不修改业务数据库结构，不迁移或删除现有用户、组织、成员关系、邀请和会话数据。
- 不重构与 Web 移除无关的本地客户端页面或后端模块。

## 4. 方案对比

| 方案 | Web 清理完整度 | 客户端影响 | 残留风险 | 结论 |
|---|---:|---:|---:|---|
| A. 删除活跃 Web 交付面并迁移邀请 | 高 | 无预期功能损失 | 需要修改邀请契约和客户端 UI | 采用 |
| B. 只删除 `frontend/` | 中 | 邀请成员会生成失效链接 | 残留 `/admin`、代理、测试和构建耦合 | 不采用 |
| C. 删除所有 HTTP/浏览器相关代码 | 最高 | 版本更新、API、登录、采集和发布均会损坏 | 违反“不影响本地客户端” | 不采用 |

## 5. 删除与保留边界

### 5.1 删除

- `frontend/` 整个目录。
- `backend/admin_console.html`。
- `backend/tools/dev_proxy.py`。
- `tests/test_web_login_navigation.py`。
- 混合测试文件中的纯 Web 页面断言；保留同文件内的后端和原生客户端测试。
- 中心服 `/admin`、`/admin/` HTML 页面处理分支。
- `enterprise_invite_base_url()`、`enterprise_invite_join_url()` 和响应中的 `joinUrl`。
- 构建脚本中创建或复制到 `frontend/downloads` 的逻辑。
- 当前 Web 启动、部署和页面排障说明，以及 Web 专用设计文档。
- `frontend.restart.log`、`frontend.restart.err.log` 等 Web 专用运行残留。

### 5.2 保留

- `backend/matrix_native_client.py` 及其全部本地业务页面。
- 中心服和本地执行服务的 JSON API。
- `/api/version`、发布配置 API 和安装包二进制下载路由。
- 安装包构建产物位置 `backend/dist/installer/MatrixShipAgent-Setup.exe`。
- Playwright、Edge/Chromium profile、Cookie、登录、采集、评论和发布能力。
- `backend/static/`，该目录包含抖音签名 JavaScript 和 protobuf 运行依赖，不是项目 Web 页面。
- `backend/assets/` 和 `backend/legal/`，它们由本地客户端打包和展示。
- CHANGELOG 和 Git 历史中的审计记录。历史记录可以提及已删除路径，但不得继续给出有效 Web 部署入口。

## 6. 企业邀请原生流程

### 6.1 管理员创建邀请

1. 管理员在本地客户端“团队成员”页面填写受邀人姓名、手机号或邮箱、角色和有效期。
2. 客户端调用 `POST /api/enterprise/invites/create`。
3. 中心服创建 64 位随机邀请码，只持久化 SHA-256 哈希。
4. 响应顶层返回一次性的 `inviteCode`；`invite` 对象不返回明文邀请码，也不返回 `joinUrl`。
5. 客户端显示只读邀请码和复制按钮，提示通过可信渠道交给受邀人。

### 6.2 受邀人加入企业

1. 登录页新增“加入企业”模式，与“登录”“注册”并列。
2. 用户粘贴邀请码并点击校验，客户端调用 `POST /api/enterprise/invites/verify`，把邀请码放入 JSON 请求体，避免代理访问日志记录明文邀请码。
3. 校验成功后显示企业名称、邀请角色和有效期，并用邀请中的姓名、手机号或邮箱预填表单。
4. 未注册用户填写姓名、手机号或邮箱、新密码和确认密码。
5. 客户端首次提交时不假定账号是否存在；若服务端返回 `existing_user_login_required`，客户端显示“当前密码”字段并保留其余输入。已有用户补充当前密码后再次提交，服务端验证当前密码、更新为新密码并加入企业，行为与旧网页保持一致。
6. 客户端调用 `POST /api/enterprise/invites/accept`，成功响应包含会话 token、用户、成员关系和组织信息。
7. 客户端使用现有 `set_session()` 和登录成功切换逻辑直接进入主界面。

为降低迁移风险，邀请码输入框允许粘贴纯邀请码，也允许粘贴历史邀请链接；客户端只在本地提取其中的 `token` 查询参数，不访问旧网页。旧网页本身仍被删除。

## 7. API 契约

### 7.1 创建邀请

`POST /api/enterprise/invites/create`

成功响应：

```json
{
  "ok": true,
  "orgId": "org-example",
  "inviteCode": "64-character-secret",
  "invite": {
    "id": "inv-example",
    "orgId": "org-example",
    "role": "member",
    "recipientName": "张三",
    "recipientPhone": "13800000000",
    "recipientEmail": "",
    "status": "active",
    "expiresAt": 1785200000
  },
  "message": "invite_created"
}
```

约束：

- 响应不得包含 `joinUrl`。
- `invite` 对象不得包含 `token`、`tokenHash` 或 `inviteCode`。
- 明文 `inviteCode` 只在创建成功响应中返回一次。

### 7.2 校验邀请

`POST /api/enterprise/invites/verify`

请求体：

```json
{
  "token": "64-character-secret"
}
```

成功时返回邀请摘要和组织信息，不返回明文邀请码或 token 哈希。旧的 GET 校验路由随 Web 页面一起删除，防止明文邀请码进入 URL、浏览器历史和代理访问日志。

### 7.3 接受邀请

`POST /api/enterprise/invites/accept` 保持现有字段：`token`、`name`、`phone`、`email`、`password`、`currentPassword`。成功后返回会话 token；已有用户当前密码错误时返回 `existing_user_login_required`。

上述接口必须同步到 `docs/openapi.yaml` 和 `docs/API_REFERENCE.md`，请求和响应必须有 JSON Schema。

## 8. 错误处理与可观测性

客户端将服务端错误映射为可操作中文提示：

| 错误码 | 客户端提示 |
|---|---|
| `missing_token` / `invalid_invite` | 邀请码无效，请检查后重试 |
| `invite_expired` | 邀请码已过期，请联系管理员重新创建 |
| `invite_revoked` | 邀请已撤销，请联系管理员 |
| `invite_accepted` | 邀请已使用，请直接登录或联系管理员 |
| `organization_inactive` | 企业当前不可加入，请联系管理员 |
| `existing_user_login_required` | 该账号已存在，请输入当前密码 |
| `password_too_short` | 密码至少 8 位 |
| 网络或服务异常 | 无法连接中心服务，请稍后重试 |

中心服通过现有 `add_audit()` 记录 `enterprise.invite.create`、`enterprise.invite.verify` 和 `enterprise.invite.accept`。结构化日志和审计元数据不得记录明文邀请码、密码、会话 token、Cookie 或 Authorization；只记录邀请 ID、组织 ID、用户 ID、状态和错误码。

## 9. 非功能性要求

| 项目 | 目标 |
|---|---|
| 邀请接口吞吐 | 单实例持续 20 QPS，不低于现有 JSON 状态存储能力 |
| 邀请校验/接受延迟 | 服务端处理 p95 小于 500 ms，不含公网传输 |
| 客户端交互 | 提交后 100 ms 内展示忙碌状态；默认请求超时沿用现有 60 秒 |
| 资源占用 | 不新增常驻服务；客户端登录页额外内存小于 20 MB |
| GPU 显存 | 0 MB，本功能不使用 GPU |
| 安全 | 明文邀请码只返回一次；日志、审计和列表接口不得泄露明文 |
| 可观测 | 创建、校验失败、接受结果均有结构化错误码；创建和接受进入审计日志 |
| 可回滚 | 修改前归档所有待删除或待修改文件，生成文件清单和 SHA-256；已跟踪文件还可按提交回滚 |
| 可追溯 | OpenAPI、四级文档、IMPLEMENTATION 行号、CHANGELOG 同步更新 |

## 10. 构建与安装包

- `backend/build_matrix_agent.ps1` 继续生成本地客户端和 Inno Setup 安装包。
- 构建完成后只保留 `backend/dist/installer/MatrixShipAgent-Setup.exe`，不再创建 `frontend/downloads`。
- `backend/central_server.py` 的安装包候选路径保留环境变量 `MATRIXSHIP_AGENT_INSTALLER`、服务端固定部署路径和 `backend/MatrixShipAgent-Setup.exe`；删除 `frontend/downloads` 候选路径。
- `/api/version` 和 `downloadUrl` 保持不变，因此客户端检查更新能力不受影响。

## 11. 文档与部署

- 更新 `docs/ARCHITECTURE.md`：产品入口改为仅本地客户端，数据流删除 Web 前端节点。
- 更新 `docs/API_REFERENCE.md` 和 `docs/openapi.yaml`：写明邀请码契约。
- 更新 `docs/DEPLOYMENT.md`：删除 Web 静态服务和代理部署步骤，保留中心服、执行节点和客户端安装包部署。
- 更新 `docs/TROUBLESHOOTING.md`：记录 Web 移除冒烟结果、邀请迁移排障和回滚方法。
- 更新 `docs/IMPLEMENTATION.md`：使用最终文件行号记录删除点和原生邀请逻辑。
- 更新 `LOCAL_TEST.md`、`MIGRATION.md`、`CHANGELOG.md` 和 `migration.sql`；数据库无结构变化，`migration.sql` 明确为 no-op。
- 删除只描述已下线 Web 页面交互的设计文档；混合历史记录保留为审计材料，但标记 Web 部分已退役。

## 12. 测试与质量门禁

### 12.1 Phase 0 基线冒烟

实现前运行：

- 中心服和本地客户端相关 Python 编译检查。
- `/api/health` 最小中心服冒烟。
- 现有登录、权限、企业成员、版本更新和客户端启动相关测试。

任何失败先记录到 `docs/TROUBLESHOOTING.md`，确认是基线问题还是本次回归后再继续。

### 12.2 自动化测试

- 新增 Web 交付面删除测试：`frontend/`、`admin_console.html`、`dev_proxy.py` 不存在；中心服不再处理 `/admin`；构建脚本不含 `frontend/downloads`。
- 新增邀请 API 测试：创建只返回顶层 `inviteCode`；GET 校验路由已删除；POST 校验、列表和审计不泄露；新用户和已有用户均能接受；过期、撤销、已使用和错误密码返回稳定错误码。
- 新增邀请码规范化测试：纯邀请码和历史 URL 均可提取，其他输入拒绝。
- 新增客户端邀请模式测试：字段显隐、校验、提交、错误映射、成功会话接入。
- 删除纯 Web 测试；混合测试只删除 Web 断言，后端和本地客户端断言继续运行。
- 运行完整相关单元测试、Python 编译检查和文档引用扫描。

### 12.3 冒烟验收

1. 管理员客户端创建邀请并复制邀请码。
2. 新用户客户端校验邀请码、创建账号、加入企业并自动登录。
3. 已有用户输入当前密码和新密码，加入企业并自动登录。
4. 启动中心服，确认 `/api/health` 正常且 `/admin` 返回 404 JSON。
5. 确认客户端版本检查仍能读取 `downloadUrl`。
6. 确认本地抖音/小红书登录、采集和发布入口仍存在且相关测试通过。
7. 扫描项目活跃源码，不存在可部署 HTML 页面或 `frontend/` 路径依赖。

## 13. 回滚方案

当前工作区的大部分客户端、后端和文档文件尚未纳入 Git，因此不能假设 `git revert` 能恢复修改前内容。首次编辑前必须把所有待删除文件和所有待修改文件归档到 `backups/web-removal-20260727/web-surface.zip`，并生成 `backups/web-removal-20260727/manifest.sha256`。清单包含原相对路径、文件大小和 SHA-256；生成后立即解压到临时目录并逐项复核哈希。`backups/` 已被 Git 忽略，归档不参与运行、构建或部署。

回滚顺序：

1. 停止中心服和本地客户端。
2. 已被 Git 跟踪的文件回滚本次代码提交；未跟踪或修改前未入库的文件从校验通过的压缩包恢复。
3. 恢复旧邀请响应中的 `joinUrl` 和 `/admin` 页面路由。
4. 重新运行中心服健康检查、旧 Web 静态检查和客户端登录冒烟。
5. 若客户端邀请迁移异常但不能整体回滚，暂时隐藏“加入企业”模式；管理员仍可使用现有“添加成员”功能直接创建成员账号。

本次无数据库迁移，回滚不修改用户、组织、成员关系、邀请或会话数据。

## 14. 验收标准

- 活跃产品源码中不存在 `frontend/` 目录、项目 HTML 页面、Web 静态服务脚本或 `/admin` 页面路由；Git 历史、忽略的回滚归档和第三方依赖不属于该扫描范围。
- Web 专用测试已删除，混合测试中的 Web 断言已清理。
- 本地客户端所有原有业务页面和浏览器自动化能力保留。
- 管理员创建邀请后得到邀请码，不再得到网页链接。
- 新用户和已有用户都能在本地客户端完成邀请加入并自动登录。
- 客户端版本检查和安装包下载能力保留。
- 相关测试、编译检查、中心服健康检查和引用扫描通过。
- OpenAPI、四级文档、IMPLEMENTATION 行号、CHANGELOG 和 no-op `migration.sql` 与代码一致。
- 回滚归档清单和 SHA-256 可验证。
