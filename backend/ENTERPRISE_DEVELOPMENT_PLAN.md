# 矩阵星舰企业版开发计划

目标：把当前脚本型短视频运营工具升级为面向企业客户的多用户 SaaS / 私有化交付系统。产品默认按“企业客户多人使用”设计，而不是按单人本机脚本设计。

## 1. 企业用户视角

### 目标客户
- 中小商家运营团队：多人管理品牌账号、素材、评论线索和发布任务。
- 代运营公司：一个系统服务多个客户，每个客户数据隔离。
- 企业市场部门：需要成员权限、账号资产、任务审计、失败可恢复和数据报表。

### 标准使用路径
1. 企业管理员创建企业工作区。
2. 管理员邀请运营成员，分配角色。
3. 成员在前端自助授权平台账号；系统只保存账号资产状态，不把 Cookie 暴露到前端。
4. 管理员把账号绑定到云端执行节点，节点池负责运行浏览器自动化任务。
5. 运营配置产品关键词、素材库、发布规则、寻客规则。
6. 后台统一调度采集、下载、评论分析、发布任务。
7. 前端展示任务进度、失败原因、账号健康状态、审计日志。
8. 管理员按企业/账号/节点查看用量、成功率和风险提示。

## 2. 架构原则

- 多租户隔离：所有账号、素材、队列、知识库、节点、审计日志都必须带 orgId。
- 账号资产化：账号不是脚本参数，而是企业资产；包含授权时间、Cookie 状态、绑定节点、可用性。
- 节点池执行：用户访问前端不等于任务在用户电脑执行；任务由云端节点按账号绑定关系执行。
- 任务中心化：长动作必须异步化，可查询、可重试、可审计。
- 前置校验：发布前必须检查账号、素材、节点、Cookie、企业配额，失败要给用户可理解原因。
- 最小暴露：前端不显示 Cookie 明文，不直接传底层浏览器 Profile。
- 商业可运维：必须有日志、审计、健康检查、部署文档、备份恢复路径。

## 3. 模块路线图

### P0：稳定当前可用链路
- [x] 修复公网 CORS / same-origin 访问问题。
- [x] 修复登录页编码异常。
- [x] 云端节点和中央调度服务部署到服务器。
- [x] 授权页接入云端浏览器会话。
- [ ] 授权会话恢复：用户刷新页面后能继续上次授权。
- [ ] 登录成功后账号资产自动登记并提示所属企业。

### P1：商业版基础能力
- [x] organizations / users / memberships / auditLogs 基础模型。
- [x] 前端企业中心：企业列表、用户列表、节点池、审计日志。
- [x] 工作区切换：X-Matrix-Org-Id 贯穿前后端。
- [x] 账号资产注册表：accountsRegistry 保存授权账号状态。
- [x] 企业级发布设置：每企业独立的 perAccountPerDay / intervalMin / enabled。
- [x] 发布 preflight：素材、账号、Cookie、节点、配额统一校验。
- [x] 企业中心账号资产总览：可发布 / 待维护 / 离线。
- [ ] 用户身份登录：从固定 API token 升级为企业用户登录态。
- [ ] RBAC：老板、管理员、运营、只读审计。

### P2：规模化运营能力
- [ ] 任务中心：采集、下载、评论分析、发布、授权统一展示。
- [ ] 队列操作：取消、重试、跳过、失败原因筛选。
- [ ] 节点健康评分：在线率、账号数、执行失败率、IP 地域。
- [ ] 寻客中心真实化：关键词找视频、拉评论、意向分析、线索入库。
- [ ] 素材中心：标签、审核状态、去重、使用记录。
- [ ] 线索 CRM：客户意向等级、来源视频、评论内容、跟进人、转化状态。

### P3：企业交付能力
- [ ] 一键部署脚本：前端、中央 API、节点服务、worker、nginx、systemd。
- [ ] 节点一键安装/升级。
- [ ] 数据备份与恢复。
- [ ] 监控告警：服务挂掉、节点离线、账号 Cookie 失效、队列堆积。
- [ ] 套餐/用量限制：企业账号数、每日任务数、节点数、存储空间。
- [ ] API 文档和二次开发接口。

## 4. 当前实现状态（2026-06-30）

### 已落地
- 中央调度服务、节点 API、worker、nginx 已部署到 `39.105.120.104`。
- 前端企业中心已上线，支持企业、用户、节点、审计展示。
- 多租户 orgId 已接入主要接口：账号、素材、队列、发布设置、知识库、健康检查。
- 知识库已支持企业隔离：list / add / upload / delete / ask。
- 节点归属管理已接入：管理员可以把执行节点迁入当前企业。
- 账号资产注册表已接入：节点上报账号后中央服务持久化账号状态。
- 发布入口已前置校验账号可用性，避免用户选择离线或 Cookie 失效账号。
- 发布队列执行前已增加 preflight，防止坏素材、坏账号进入真实执行。
- 企业中心新增账号资产总览，运营人员能看到当前企业账号是否可发布。

### 当前短板
- 还没有真正的企业用户登录和 RBAC；现在仍依赖固定 token。
- 授权会话恢复还不完整，用户刷新/重启后体验不够商业化。
- 队列还缺少取消、重试、失败筛选。
- 寻客中心已有功能入口，但线索还没有完整 CRM 化。
- 数据仍是 JSON 文件持久化，商业版需要迁移到 SQLite/PostgreSQL。

## 5. 下一步开发顺序

1. 完成 P1 收口：用户登录态、RBAC、授权会话恢复。
2. 把任务中心抽象出来：所有长任务进入统一 task/job 模型。
3. 把寻客中心产物改成线索资产：评论 -> 意向评分 -> 线索 -> 跟进状态。
4. 做运维交付：一键部署、备份、服务健康告警。
5. 数据库迁移：JSON 状态迁移到 SQLite/PostgreSQL，保留导入脚本。

## 6. 开发约束

- 新功能不得只做“按钮调用脚本”；必须有企业、用户、账号、任务、审计上下文。
- 前端只拿业务 ID 和状态，不拿 Cookie 明文。
- 每个会触发平台动作的功能都必须有 preflight、限额、失败原因和审计记录。
- 任何跨企业数据读取都视为严重缺陷，接口默认按当前 orgId 过滤。
- 发布和拓客类动作默认走队列，人工确认/可视化状态优先于裸自动化。

## 7. 本轮继续开发记录（2026-06-30）

### P1.9 发布前置校验与账号资产总览
- 后端新增 `/api/publish/preflight`，统一返回账号、素材、企业设置、每日配额校验结果。
- `/api/publish/run` 和 `/api/publish/queue/add` 已接入 preflight，坏账号、坏素材、超配额会直接阻断。
- 队列 worker 在真实执行前再次 preflight，避免排队期间账号或素材状态变化导致误执行。
- 企业中心新增“账号资产总览”，展示当前企业账号的可发布、待维护、离线状态。
- 前端发布队列开始展示可读失败原因，例如 Cookie 失效、素材缺失、每日额度用完。

### P1.10 企业用户登录态骨架
- 后端新增 `sessions` 状态模型。
- 新增 `/api/auth/login`：企业用户可用手机号/用户名 + 密码登录获取 session token。
- 新增 `/api/auth/me`：查询当前登录用户、所属企业和角色。
- 新增 `/api/auth/logout`：注销 session。
- 现有固定 `CENTRAL_USER_TOKEN` 继续兼容，避免线上访问被破坏。
- `/api/enterprise/users/upsert` 支持设置用户密码，返回时不暴露 passwordHash/passwordSalt。
- 审计日志补充 actorUserId / actorName，为后续 RBAC 和客服排障做准备。

### 下一块
- 前端增加企业用户登录页：用户登录后保存 session token，替代手填云端 API Token。
- RBAC 中间层：owner/admin/member/auditor 角色控制企业管理、节点迁移、发布、审计查看权限。
- 授权会话恢复：用户刷新授权页后能恢复当前云端浏览器 session。

### P1.11 RBAC 最小闭环
- 后端新增 `has_role` / `require_role`，支持 owner/admin/member/auditor 等级判断。
- 企业创建/编辑、企业用户创建/编辑、节点迁移已限制为 admin 及以上角色。
- 固定部署 token 作为 root-token 继续保留，方便管理员应急和兼容现有部署。
- 前端新增 `permission_denied` 中文提示，普通运营无权限时给出可理解反馈。

### 下一块
- 把企业中心按钮按角色动态禁用/隐藏。
- 增加角色选择：创建企业用户时可选管理员、运营、审计员。
- 审计日志按角色限制：auditor 可看，member 不可看全局审计。

### P1.12 前端角色感知
- 企业中心显示当前用户在工作区内的角色。
- 普通运营/审计员看到管理动作时有明确“无权限”提示，减少误操作。
- 节点迁移按钮按角色变化：管理员可迁移，普通用户显示无权限。
- 创建企业用户时支持选择角色：运营成员、管理员、审计员。
- 前端动作前增加权限 guard，避免无权限请求反复打到后端。

### 下一块
- 创建用户时支持设置初始密码或发送邀请链接。
- 审计日志按角色裁剪：owner/admin/auditor 可看，member 只看自己的任务。
- 任务中心统一化：把发布、寻客、下载、授权全部归到同一任务模型。

### P1.13 新用户初始密码
- 企业中心创建用户时新增“初始登录密码”输入。
- 创建用户请求会把 password 传给后端，后端只保存 salted hash，不返回明文或 hash。
- 创建成功后前端清空密码字段，避免敏感信息残留。

### 下一块
- 邀请链接/首次登录改密。
- 用户列表增加角色和登录状态筛选。
- 审计日志权限裁剪。

### P1.14 审计日志权限裁剪
- `/api/audit/logs` 按角色返回数据：member 只看自己的审计，auditor/admin/owner 看当前企业审计。
- root-token 支持 `?all=1` 查看全局审计，用于平台管理员排障。
- 旧日志没有 orgId 时不默认跨企业展示，只展示给操作者本人或 root 全局查询。

### 下一块
- 前端审计区展示当前审计范围：个人 / 企业 / 全局。
- 任务中心统一模型。

### P1.15 前端审计范围显示
- 企业中心审计卡片显示当前范围：个人审计、企业审计或全局审计。
- 前端读取 `/api/audit/logs` 返回的 scope，不自行推断权限。

### P1.16 发布队列单条控制与授权会话恢复
- 后端新增 `/api/publish/queue/detail`，返回单条队列、关联中央任务、最近 preflight 结果。
- 后端新增 `/api/publish/queue/cancel`，非运行任务可取消，运行中任务返回明确错误。
- 后端新增 `/api/publish/queue/retry`，失败/已取消任务重试前会重新执行 preflight，避免坏账号/坏素材重新入队。
- `/api/central/tasks` 改为默认按当前企业过滤；root-token 可通过 `all=1` 查看全局任务。
- 前端发布队列新增“详情 / 重试 / 取消”操作，并把队列错误码翻译成运营可理解文案。
- 主系统打开授权页时追加 `?resume=1`，授权页会自动检查未完成的云端会话。
- 授权页新增“重新开始”按钮，卡住时可强制放弃旧会话创建新会话。
- 授权页启动/恢复失败时展示更明确的错误文案，例如登录过期、无可用节点、会话已失效。

### 下一块
- 独立任务中心：把发布、寻客、下载、授权全部统一成可筛选的任务列表。
- 授权页完成后回写主系统提示，减少用户来回刷新。

### P1.17 企业中心任务中心最小版
- 企业中心接入 `/api/central/tasks?limit=30`，按当前企业读取中央任务。
- 新增“中央任务中心”卡片，统一展示账号授权、自动发布、寻客采集、AI 拓客、视频下载、视频搜索、评论抓取等任务。
- 任务列表展示任务类型、底层路径、执行节点、状态、等待时间和错误原因。
- 这是后续独立任务中心页面的最小可用版本。

### 下一块
- 独立任务中心页面：筛选、详情、取消、重试、任务链路追踪。
- 授权完成后向主系统发事件，自动刷新账号资产。

### P1.18 授权完成自动同步账号资产
- 授权页点击“完成并保存”后写入 `matrix_login_saved_ts`，并向主系统窗口发送 `matrix-login-saved` 消息。
- 主系统监听 message/storage 事件，自动刷新健康状态、账号资产和企业中心。
- 用户完成授权后不再需要手动刷新主系统页面。

### P1.19 独立任务中心页面
- 后端新增 `/api/central/tasks/detail`，按企业隔离返回任务详情、脱敏 body、关联队列项。
- 后端新增 `/api/central/tasks/cancel`，只允许取消 queued 任务；running 任务返回明确错误，避免误中断执行节点。
- 前端新增独立导航“任务中心”。
- 任务中心支持按状态筛选：全部、排队中、执行中、失败、完成。
- 任务中心支持按类型筛选：账号授权、自动发布、寻客采集、AI 拓客、视频下载、视频搜索、评论抓取、其他任务。
- 任务中心提供任务详情侧栏，展示任务 ID、类型、状态、节点、创建/更新时间、错误和脱敏执行上下文。
- 任务中心支持取消排队任务，动作写入审计日志。

### 下一块
- 任务重试策略：对部分安全任务支持从原始 body 克隆重试；发布任务仍优先走发布队列 retry。
- 任务链路追踪：任务 -> 队列 -> 账号 -> 节点 -> 审计日志。

### P1.20 任务中心安全重试
- 后端新增 `/api/central/tasks/retry`，从原任务克隆 method/path/body/waitSec/preferred node 创建新任务，并写入 `retryOfTaskId`。
- 后端只允许白名单任务重试：账号授权状态/截图/刷新、搜索、下载、评论抓取、寻客发现等幂等或低风险任务。
- 发布类真实执行任务不走中央任务直接重试，仍要求通过发布队列 retry 重新 preflight，避免重复发布。
- `/api/central/tasks` 和任务详情返回 `retryable`，前端只对可重试任务显示“重试”。
- 所有重试动作写入 `task.retry` 审计日志，包含原任务 ID、新任务 ID、企业工作区和错误码。

### 下一块
- 任务链路追踪：任务 -> 队列 -> 账号 -> 节点 -> 审计日志。
- 任务中心增加搜索框：按任务 ID、节点、账号、错误码定位问题。
- 企业用户首页增加“我的待处理”：需要重新授权、失败待重试、队列阻塞。

### P1.21 任务中心问题定位
- `/api/central/tasks` 新增服务端过滤参数：`q`、`status`、`type`，并在企业隔离完成后再筛选，避免跨企业泄露任务。
- `q` 支持匹配任务 ID、路径、方法、执行节点、状态、错误码、企业 ID 和脱敏后的执行上下文。
- 接口返回 `total`、`matched`、`filters`，前端可以展示“匹配 / 总计”。
- 前端任务中心新增搜索框、搜索按钮、清空按钮，并与状态/类型筛选联动。
- 点击状态或类型筛选会直接重新拉取服务端列表，不再只在本地做视觉过滤。

### 下一块
- 任务链路追踪：任务 -> 队列 -> 账号 -> 节点 -> 审计日志。
- 企业用户首页增加“我的待处理”：需要重新授权、失败待重试、队列阻塞。
- 账号资产页增加“维护入口”：失效账号一键进入授权恢复。

### P1.22 任务链路追踪
- `/api/central/tasks/detail` 在原有任务详情基础上返回执行节点 `node`、关联发布队列 `queueItems`、关联审计事件 `auditLogs` 和 `trace` 汇总。
- 关联审计覆盖 `task.dispatch`、`task.retry`、队列操作等关键动作，前端展示成功/失败、动作名、时间和脱敏元数据。
- 任务详情侧栏新增“链路追踪”，运营可以直接看到任务落在哪个节点、是否关联发布队列、是否有审计记录。
- 纯状态类任务没有队列/审计时显示明确空态，避免用户误判为页面失效。

### 下一块
- 企业用户首页增加“我的待处理”：需要重新授权、失败待重试、队列阻塞。
- 账号资产页增加“维护入口”：失效账号一键进入授权恢复。

### P1.23 企业待处理中心
- 后端新增 `/api/enterprise/action-items`，按当前企业工作区聚合账号、节点、中央任务和发布队列的异常。
- 待处理项分为 `critical / warning / info`，并返回 counts、kind 统计、动作类型和关联资源 ID。
- 聚合规则覆盖：账号节点离线、账号 Cookie 失效、节点登录态失效、失败任务、长时间运行/排队任务、失败/取消的发布队列。
- 前端企业中心新增“我的待处理”卡片，展示紧急/待处理/提示数量和最多 6 条待处理事项。
- 待处理动作可直接进入授权恢复、任务详情/重试、队列重试或账号详情。
- 账号资产总览新增“维护”入口，不可用账号一键打开授权恢复页，避免企业客户不知道下一步怎么做。

### 下一块
- 账号授权恢复页根据 `accountId/nodeId` 做更精确的节点选择和提示。
- 待处理中心支持“已忽略/稍后处理”，避免已知问题持续打扰运营。

### P1.24 精准账号授权恢复
- 账号维护入口打开 `/login-douyin.html?resume=1&accountId=...&nodeId=...`，授权页会展示当前维护目标。
- 授权页读取 `accountId / centralAccountId / nodeId / preferredNode` 参数，带目标进入“开始授权 / 恢复会话 / 截图 / 点击 / 输入 / 短信 / 保存”全链路请求。
- 如果传入的是中心账号 ID（`nodeId:localAccountId`），授权页和后端会解析出优先节点，避免分配到错误执行节点。
- 后端 `prepare_task_body` 对 `/api/cloud-login/*` 支持中心账号 ID 转本地账号 ID，并透传 `centralAccountId` 与 `preferredNode`。
- 授权页从待处理入口进入时会清理旧本地会话，避免用户误恢复到另一个账号的历史会话。

### 下一块
- 待处理中心支持“已忽略/稍后处理”，避免已知问题持续打扰运营。
- 授权成功后按 accountId 定向刷新对应账号详情和待处理项。

### P1.25 待处理稍后处理
- 待处理项 ID 改为基于 kind/ref/title 的稳定 ID，支持跨刷新定位同一问题。
- 后端新增 `actionSnoozes` 存储，并在 `/api/enterprise/action-items` 聚合后过滤未到期的稍后处理项。
- 新增 `/api/enterprise/action-items/snooze`，企业用户可把单条待处理隐藏 1-168 小时，默认 24 小时。
- 稍后处理动作写入 `enterprise.action.snooze` 审计日志。
- 前端“我的待处理”每条事项新增“稍后”按钮，点击后刷新企业中心，减少已知问题持续打扰。

### 下一块
- 授权成功后按 accountId 定向刷新对应账号详情和待处理项。
- 待处理中心增加“显示已稍后处理”视图，便于管理员恢复误操作。

### P1.26 授权回写与稍后处理恢复
- 授权页完成保存时写入 `matrix_last_login_account`，并通过 `postMessage` 带回 `accountId/nodeId`。
- 主系统监听授权完成事件后会刷新健康状态、账号资产、企业待处理，并按 `accountId` 自动打开账号详情，减少用户授权后找不到结果的问题。
- `/api/enterprise/action-items` 支持 `includeSnoozed=1`，可把已稍后处理的事项一并返回，并标记 `snoozed/snoozedUntil`。
- 新增 `/api/enterprise/action-items/restore`，管理员/运营可恢复被稍后处理的待办提醒。
- 企业中心“我的待处理”新增“显示已稍后/隐藏已稍后”切换，已稍后事项显示到期时间并提供“恢复提醒”按钮。

### 下一块
- 待处理中心增加按类型筛选和关键字搜索。
- 授权成功后自动清理对应账号的稍后处理项，避免已修复问题仍被隐藏。

### P1.27 待处理筛选与授权修复清理
- `/api/enterprise/action-items` 支持 `q`、`kind`、`severity` 服务端过滤，按企业隔离后再筛选。
- 前端“我的待处理”新增关键字搜索、类型筛选、级别筛选和清空筛选。
- 稍后处理时前端会把 kind/severity/title/ref/action 一并提交，后端保存 snooze 元数据，后续可按账号/节点精确清理。
- 新增 `/api/enterprise/action-items/clear-resource`，可按 `accountId/nodeId` 清理相关稍后处理项。
- 授权页关闭会话时携带 `accountId/centralAccountId/preferredNode`；主系统收到授权完成事件后也会调用 clear-resource，避免账号已重新授权但相关提醒仍被隐藏。

### 下一块
- 企业任务/待处理增加批量操作：批量恢复提醒、批量重试安全任务。
- 账号授权恢复完成后增加“账号健康确认”轮询，直到账号资产状态变为可用再提示完成。
### P1.28 Enterprise action batch operations and auth health confirmation
- Added `/api/enterprise/action-items/batch`, with server-side org/filter re-selection to prevent cross-tenant batch operations.
- Batch actions support restoring snoozed reminders and retrying only safe allowlisted tasks; publish execution is still not directly replayed.
- The Enterprise "Action Items" card now has batch restore and batch retry controls bound to current filters.
- The Douyin authorization page now polls account detail after "finish and save" until the account asset is online and cookie-ready.
- Batch operations are audited as `enterprise.action.batch`.

### P1.29 Enterprise notification center
- Added `/api/enterprise/notifications`, deriving user-facing notifications from action items such as account reauth, node offline, task failure, and blocked queues.
- Added `/api/enterprise/notifications/read` for single/all read state, isolated by enterprise workspace.
- The top notification bell now shows unread count and a dropdown notification list.
- Clicking a notification reuses the original action-item handler, routing users to account auth, task detail/retry, queue handling, or account detail.
- Read state is derived from stable action item IDs, so refreshed pages do not repeatedly disturb users after a notification is acknowledged.

### Next block
- Notification subscription settings by user role.
- Optional enterprise outbound alerts through SMS / WeCom / Feishu webhook for critical incidents.
### P1.30 Per-role notification subscriptions
- Added org-level notification settings at `/api/enterprise/notification-settings`.
- Notifications are now filtered by the current user's role: owner/admin/auditor can receive all severities by default, members receive critical and warning by default.
- Notification read state is now tracked per user while retaining compatibility with older org-level read markers.
- The notification dropdown now includes a settings panel for role severity subscriptions, muted notification kinds, and critical webhook configuration.
- Settings changes require admin-level permission and are recorded in audit logs as `enterprise.notification.settings`.

### Next block
- Actually deliver critical incident webhooks with rate limiting and signed payloads.
- Add clearer customer-facing failure explanations for account authorization and session recovery.
### P1.31 Account authorization diagnosis
- Added `/api/accounts/auth-diagnosis` for customer-readable diagnosis of account authorization state.
- Diagnosis evaluates online execution nodes, target node status, account cookie readiness, running auth tasks, and recent failed cloud-login tasks.
- The Douyin authorization page now has a manual diagnosis button.
- Start/resume/save failures now call diagnosis automatically and write clear next-step suggestions into the page status log.
- This reduces blind retries when QR login, SMS verification, stale sessions, or node assignment fail.

### Next block
- Deliver critical notification webhooks with rate limiting and signed payloads.
- Add an operations dashboard for login sessions: current sessions, stale sessions, force close, and last screenshot time.
### P1.32 Cloud login session operations
- Added `/api/cloud-login/sessions` to aggregate recent cloud-login tasks into operator-facing login sessions.
- Sessions expose account, node, phase, latest status, idle time, last screenshot time, and close eligibility without returning screenshot/base64 payloads.
- Added `/api/cloud-login/sessions/close` for admin-level force close of stuck browser sessions through the normal node dispatch path.
- Enterprise Center now includes a "Login Session Operations" card for support and operations teams.
- The card highlights active/stale sessions and provides a force-close action for sessions that still have a usable session id.

### Next block
- Add signed and rate-limited critical notification webhook delivery.
- Add node capacity/cooldown controls so users see why tasks queue instead of repeatedly retrying.

### P1.33 Node capacity and cooldown controls
- Added node-level capacity settings: max concurrency, manual pause/resume, cooldown seconds, and operator note storage.
- Central scheduler now exposes capacity snapshots for each node, including running count, queued count, available slots, cooldown remaining, and status reason.
- Node polling now respects pause, max concurrency, and cooldown before assigning new work, returning a clear reason when no task is dispatched.
- Enterprise Center node pool now shows capacity status and provides admin controls for pause/resume, concurrency +/- and cooldown +/-60s.
- Capacity changes require admin-level permission and are recorded in audit logs as `node.capacity.update`.

### Next block
- Add signed and rate-limited critical notification webhook delivery.
- Add per-tenant usage quotas and SLA metrics so commercial plans can be enforced cleanly.

### P1.34 Signed critical webhook delivery
- Critical notifications can now be delivered to an enterprise webhook endpoint when enabled in notification settings.
- Delivery uses `X-MatrixShip-Timestamp` and `X-MatrixShip-Signature: sha256=<hmac>` when a secret is configured.
- Webhook delivery is deduplicated per notification and rate-limited by minimum interval and maximum deliveries per hour.
- Backend keeps bounded delivery history per tenant and exposes it through notification settings and `/api/enterprise/webhook-deliveries`.
- Enterprise Center now shows the latest webhook delivery status and provides an admin-only test delivery action.

### Next block
- Add per-tenant usage quotas and SLA metrics so commercial plans can be enforced cleanly.
- Add operator-visible queue aging and stuck-task auto-recovery rules.

### P1.35 Tenant usage and SLA metrics
- Added tenant quota defaults and persisted org quota settings for tasks/day, accounts, nodes, and materials.
- Added `/api/enterprise/usage` with 24h/7d task volume, status/type breakdown, queue count, account readiness, node online rate, average duration, quota usage, and SLA score.
- Added `/api/enterprise/usage/quota` for admin-level quota updates with audit logging.
- Enterprise Center now includes a commercial usage/SLA card so operators can explain plan usage and reliability to customers.

### Next block
- Add operator-visible queue aging and stuck-task auto-recovery rules.
- Add plan enforcement switches for quota-controlled commercial editions.

### P1.36 Queue aging and stuck task recovery
- Added stale task detection for running tasks that exceed wait time plus recovery grace.
- Added queued task aging detection, including tasks assigned to offline nodes and disposable login screenshots that should expire quickly.
- Central scheduler now runs recovery before node polling and before creating new work, releasing stuck running tasks so node capacity is not permanently consumed.
- Added `/api/central/tasks/recovery` for operator visibility and `/api/central/tasks/recover` for admin-triggered recovery with audit logging.
- Enterprise usage now includes task recovery status, and Task Center shows recovery counts plus an admin action to recover stuck tasks.

### Next block
- Add safer plan enforcement switches for quota-controlled commercial editions.
- Add customer-facing account authorization wizard polish and clearer SMS/QR handoff states.

### P1.37 Customer-facing authorization wizard
- The Douyin authorization page now has a four-step enterprise user flow: create session, scan login, SMS verification, and save Cookie.
- Added visible step state transitions for session creation, session restore, QR scan, SMS verification, detected login, and final save.
- Start/resume/new-session buttons now use a shared busy guard so repeated clicks do not create confusing duplicate actions.
- SMS and screenshot refresh logs now provide explicit next-step guidance instead of silent or ambiguous states.
- The page remains free of mojibake artifacts and keeps the existing account diagnosis flow.

### Next block
- Add safer plan enforcement switches for quota-controlled commercial editions.
- Add guided account health polling back into Enterprise Center after users return from authorization.

### P1.38 Safe commercial quota enforcement
- Added safe quota enforcement guards for billable task creation and material uploads.
- Cloud-login/account authorization tasks are excluded from billable task quota enforcement so customers can still repair account sessions even when a plan limit is reached.
- `enterprise_usage` now reports both total task volume and billable task volume; quota usage for tasks/day is based on billable tasks.
- Existing `/api/enterprise/usage/quota` can now be operated from Enterprise Center with an enable/disable enforcement switch and +/- quota controls.
- Quota blocks return clear 429 payloads with resource, used, limit, enforce flag, and customer-readable message.

### Next block
- Add guided account health polling in Enterprise Center after users return from authorization.
- Add per-customer onboarding checklist and empty-state guidance for first-time users.

### P1.39 Enterprise account health confirmation
- Enterprise Center now starts account-health polling when the authorization page reports a saved login session.
- The poll checks account detail until the node is online and the Cookie is ready, then refreshes accounts and enterprise assets.
- Users now see a visible Enterprise Center banner while authorization assets are syncing, so returning from SMS/QR login is not a silent state.
- The status text maps backend unusable reasons through the existing customer-readable error vocabulary.

### Next block
- Add per-customer onboarding checklist and empty-state guidance for first-time users.
- Add an enterprise audit drill-down around authorization, quota blocks, and account recovery events.

### P1.40 Customer onboarding checklist
- Enterprise Center now shows a customer-facing go-live checklist above SLA metrics.
- The checklist derives readiness from enterprise login, online execution nodes, usable Douyin accounts, content/knowledge assets, and commercial controls.
- Each incomplete item includes a direct action entry, so first-time customers are guided toward the next setup step instead of seeing empty dashboards.
- The feature is frontend-derived from existing state and requires no schema migration.

### Next block
- Add enterprise audit drill-down around authorization, quota blocks, and account recovery events.
- Add customer-level task templates so onboarding can launch safe demo flows without manual configuration.

### P1.41 Enterprise audit drill-down filters
- Enterprise Center audit panel now loads a larger recent audit window and exposes quick filters for all events, authorization chain, quota/risk blocks, and recovery/failure events.
- Audit rows now carry customer-readable event category badges and category-colored borders for faster support triage.
- The implementation reuses existing audit logs and does not require a schema migration.

### Next block
- Add customer-level task templates so onboarding can launch safe demo flows without manual configuration.
- Add role-specific empty states and help copy for operator, admin, and auditor users.

### P1.42 Customer task template entry points
- Enterprise Center now includes commercial quick-start task templates for account authorization, material onboarding, customer discovery analysis, and operations troubleshooting.
- Templates only navigate and prefill safe local UI state; they do not automatically trigger external platform actions.
- The design reduces first-use friction for business users who think in goals rather than technical modules.

### Next block
- Add role-specific empty states and help copy for operator, admin, and auditor users.
- Add a guided customer demo mode that runs only local/sandbox-safe checks.

### P1.43 Role-specific enterprise guidance
- Enterprise Center now shows role-specific guidance for owner, admin, member, and auditor users.
- The banner explains what the current role can operate and which actions require an administrator, reducing confusion in multi-user commercial deployments.
- This is a frontend-only UX improvement and does not change the permission model.

### Next block
- Add a guided customer demo mode that runs only local/sandbox-safe checks.
- Add per-role navigation hiding/soft-disable rules for commercial tenants.

### P1.44 Clean console and role-soft-disabled navigation
- Replaced template-bound SVG path attributes in the main UI with text badge icons so browsers no longer emit invalid path warnings before the template engine hydrates.
- Added role-aware soft-disabled navigation for auditor users: only Enterprise Center and Task Center remain actionable, while operational modules are visibly marked read-only.
- The change keeps owner/admin/member navigation unchanged and does not alter backend permissions.

### Next block
- Add a guided customer demo mode that runs only local/sandbox-safe checks.
- Add per-role route guards for direct URL/module entry when commercial tenant roles are expanded.

### P1.45 Safe customer demo mode
- Enterprise Center now includes a safe customer demo mode that checks central scheduler health, node capacity, account readiness, quota status, task recovery state, and audit availability.
- The demo mode only performs read-only internal API checks and does not trigger external platform search, comments, private messages, publishing, or cloud-login actions.
- Results are shown as customer-readable readiness cards so sales/support can demonstrate system status without risking side effects.

### Next block
- Add per-role route guards for direct URL/module entry when commercial tenant roles are expanded.
- Add tenant-level onboarding completion persistence and first-login welcome state.

### P1.46 Auditor route guard for direct module entry
- Added a shared enterprise module guard so auditor users cannot enter operational modules through default module state, restored sessions, direct setModule calls, or navigation clicks.
- Auditor users are redirected to Enterprise Center with a clear read-only message; Enterprise Center and Task Center remain available.
- Navigation soft-disable now uses the same guard method as route enforcement, keeping visible UI and actual module switching consistent.

### Next block
- Add tenant-level onboarding completion persistence and first-login welcome state.
- Add a customer-facing account authorization completion checklist tied to real account readiness.

### P1.47 Tenant onboarding persistence
- Added tenant-level onboarding persistence via `/api/enterprise/onboarding` backed by `STATE["orgOnboarding"]`.
- Enterprise Center now reads onboarding state, shows a first-delivery welcome card, supports dismissing the welcome prompt, resetting it, and marking onboarding complete only when checklist readiness is satisfied.
- Onboarding state is stored per organization instead of per browser, so commercial customers see consistent onboarding progress across users and devices.
- All onboarding updates are audited with `enterprise.onboarding` events.

### Next block
- Add a customer-facing account authorization completion checklist tied to real account readiness.
- Add tenant-level onboarding step timestamps for support handoff and implementation tracking.

### P1.48 Real onboarding delivery timeline
- `/api/enterprise/onboarding` now returns real readiness steps with first-completed timestamps for workspace, execution node, account authorization, content assets, and quota/alert controls.
- The backend persists first completion times in `STATE["orgOnboarding"][orgId]["steps"]` while keeping current readiness derived from live system state.
- Enterprise Center now shows a delivery timeline under the onboarding checklist, including the account authorization step and its true first-completed time when a usable account is detected.
- This supports customer success and implementation handoff without relying on browser-local state.

### Next block
- Add account authorization repair SLA indicators and stale-login handoff notes.
- Add tenant-level onboarding step owner/assignee fields for implementation tracking.

### P1.49 Account repair SLA and stale-login handoff
- Account assets now carry `repairSla` with state, severity, first broken timestamp, due time, remaining/overdue seconds, and a handoff note for operator/admin ownership.
- Node heartbeat account sync preserves `cookieLostAt` and `offlineSince` so SLA aging is based on the first degradation, not the latest heartbeat.
- Action items for account reauthorization/offline states now include SLA data and customer-success handoff notes; overdue reauthorization escalates to critical.
- Cloud login sessions now include stale/failed/running/closed handoff guidance so support staff know whether to wait, close, or rebuild the session.
- Enterprise Center surfaces SLA pills and handoff notes in account assets, action cards, and login session operations.

### Next block
- Add tenant onboarding owner/assignee fields for implementation tracking.
- Add customer-visible health summary for login/account readiness before publishing tasks are created.

### P1.50 Tenant onboarding owner and handoff tracking
- Onboarding steps now support persisted implementation metadata: owner/assignee, due date, note, status, and metadata update audit fields.
- `/api/enterprise/onboarding` accepts `stepMeta` and `stepsMeta` updates while preserving live readiness and first-completed timestamps.
- Enterprise Center now includes an implementation follow-up board under the onboarding timeline, so customer success can assign each delivery step and record handoff notes.
- This turns onboarding from a static checklist into a customer implementation workspace.

### Next block
- Add customer-visible preflight health summary before creating publish/search/outreach tasks.
- Add implementation owner filters and overdue visual escalation in Enterprise Center.

### P1.51 Customer task preflight health summary
- Added `/api/enterprise/preflight` for customer-visible readiness before publish/search/outreach task creation.
- The API checks central API availability, online execution nodes, usable authorized accounts, quota status, and material readiness.
- Enterprise Center now shows a pre-task health summary card with OK/WARN/BLOCK states and a direct customer-facing summary.
- This reduces failed task creation by surfacing blockers before the user enters an automation flow.

### Next block
- Add implementation owner filters and overdue visual escalation in Enterprise Center.
- Add preflight gating hints inside the individual task creation pages.

### P1.52 Implementation owner filters and overdue escalation
- Enterprise Center implementation follow-up now supports filtering by owner keyword, `overdue`, or `unassigned`.
- Each onboarding implementation step highlights overdue due dates for unfinished delivery work and shows due/soon/empty due-date badges.
- The board surfaces overdue and unassigned counters so customer success can triage commercial onboarding instead of scanning all steps manually.
- This keeps the SaaS handoff model operationally useful for multiple customer tenants.

### Next block
- Add preflight gating hints inside the individual task creation pages.
- Add commercial customer-facing self-service repair prompts for account authorization blockers.

### P1.53 Task-page preflight gating hints
- Automatic publishing, Finder, and AI Outreach pages now show the customer-visible task preflight card directly inside the task creation flow.
- Publish, queue-add, Finder discovery/comment capture, and Outreach run actions now call the shared preflight guard before dispatching cloud tasks.
- Critical blockers such as no usable authorized account stop task creation and write the preflight summary into the page status message instead of creating a doomed backend task.
- This brings the enterprise preflight model from Enterprise Center into day-to-day operator workflows.

### Next block
- Add customer-facing self-service repair prompts for account authorization blockers.
- Add per-module preflight check scoping so publishing treats materials as required while Finder/Outreach treat materials as advisory.

### P1.54 Customer-facing preflight repair prompts
- `/api/enterprise/preflight` now returns `repairActions` that translate readiness blockers into customer-facing recovery actions.
- Publish, Finder, Outreach, and Enterprise Center preflight cards render self-service repair entry points such as Douyin authorization, account matrix review, node checks, material upload, and quota review.
- Task gating messages now tell operators to use the visible repair entry points instead of only reporting a technical blocker.
- This moves the product toward a commercial SaaS support model where tenants can recover common account-readiness issues without contacting the operator for every failed task.

### Next block
- Add per-module preflight check scoping so publishing treats materials as required while Finder/Outreach treat materials as advisory.
- Add customer-facing repair progress state after an authorization window is opened.

### P1.55 Module-scoped task preflight
- `/api/enterprise/preflight` now accepts `scope=general|publish|finder|outreach` and returns module-aware readiness semantics.
- Publishing treats missing material assets as a critical blocker, while Finder and Outreach treat materials as advisory because those flows primarily depend on account and node readiness.
- The frontend now caches scoped preflight results and automatically renders/gates the current module with the matching scope.
- This prevents commercial users from seeing misleading blockers in lead-discovery flows while still protecting publishing from missing media assets.

### Next block
- Add customer-facing repair progress state after an authorization window is opened.
- Add tenant-level preflight history so support can see which blocker stopped each customer task attempt.

### P1.56 Authorization repair progress feedback
- Clicking a preflight account-authorization repair action now leaves an in-page repair progress card instead of only opening a new tab.
- The progress card shows waiting/checking/done states, elapsed time, customer-readable next-step guidance, refresh status, and a close action.
- Existing `matrix-login-saved` events now mark the repair progress as done and continue syncing account assets, account detail, and enterprise readiness.
- This addresses the commercial UX issue where customers believe the system did nothing after opening an authorization window.

### Next block
- Add tenant-level preflight history so support can see which blocker stopped each customer task attempt.
- Add customer-facing task-attempt receipts for blocked actions.

### P1.57 Preflight blocked-attempt history
- Added `/api/enterprise/preflight-attempts` for recording and listing task attempts blocked by preflight checks.
- Task pages now write a blocked-attempt receipt when `ensureTaskPreflight` stops Publish/Finder/Outreach actions.
- Enterprise Center now shows recent blocked attempts with scope, module, summary, blocker detail, and timestamp for customer support evidence.
- This creates an audit trail for "I clicked but nothing happened" support cases and helps implementation teams identify repeated readiness blockers.

### Next block
- Add customer-facing task-attempt receipts that surface the blocked attempt ID/status directly on the task page.
- Add preflight blocker trend metrics by tenant and module.

### P1.58 Customer-facing blocked-attempt receipts
- When a task page is blocked by preflight, the frontend now appends the generated blocked-attempt receipt ID back into the current status message.
- Customers and support staff can quote the `pfa_*` receipt ID and find the same record in Enterprise Center.
- This closes the loop between a customer-visible blocked action and the tenant-level support evidence trail.

### Next block
- Add preflight blocker trend metrics by tenant and module.
- Add export/filter controls for blocked-attempt history.

### P1.59 Preflight blocker trend metrics
- `/api/enterprise/preflight-attempts` now returns `stats` with 24-hour window totals, blocker totals, scope/module distribution, top blocker reasons, latest timestamp, and focus counts for account/material/node/quota blockers.
- Enterprise Center now shows a customer-success trend panel above the blocked-attempt list: 24h blocked attempts, Top module, Top blocker, account-blocker count, and scope distribution bars.
- This lets support and implementation teams distinguish repeated account-authorization issues from material, node, or quota problems without reading individual rows one by one.
- Local validation was tightened to check all script tags, including the `text/x-dc` main logic script, not only plain `<script>` tags.

### Next block
- Add export/filter controls for blocked-attempt history.
- Add queue reliability receipts for scheduled publish tasks similar to preflight blocked-attempt receipts.

### P1.60 Blocked-attempt filters and CSV export
- `/api/enterprise/preflight-attempts` now supports `scope`, `module`, `q`, `limit`, and `windowSec` filters while preserving total/matched counts and stats for the filtered result set.
- Enterprise Center now includes blocked-attempt filter controls for All/Publish/Finder/Outreach, keyword search across ID/module/action/summary/blockers, and CSV export of the current filtered rows.
- This makes the support evidence trail usable when tenants accumulate many blocked attempts and lets customer-success staff hand off filtered evidence outside the app.

### Next block
- Add queue reliability receipts for scheduled publish tasks similar to preflight blocked-attempt receipts.
- Add node/account repair trend metrics tied to SLA overdue states.

### P1.61 Queue receipt visibility
- `/api/publish/queue/add` now returns `receiptId` and the created queue `item` while preserving the existing `id` field.
- The publishing page now shows `queue:{id}` receipts after adding scheduled publish tasks, lists short queue receipts in each queue row, and includes the full queue receipt in queue-detail status text.
- Browser verification used a mocked queue response to validate frontend receipt rendering without creating real publish tasks or modifying the production queue.
- This brings scheduled publishing closer to the same customer-support traceability model as preflight blocked-attempt receipts.

### Next block
- Add node/account repair trend metrics tied to SLA overdue states.
- Add queue stuck/retry receipts in Task Center for failed or recovered queue items.

### P1.62 Account/node repair trend metrics
- Added `/api/enterprise/repair-metrics`, aggregating account repair SLA state, severity, owner handoff role, overdue count, max overdue age, node online/cookie readiness, and prioritized repair rows per tenant.
- Enterprise Center now shows an account repair trend panel under Account Assets with repair count, SLA overdue count, operator handoff count, node-risk count, owner distribution, and state distribution.
- The panel is customer-success oriented: support can see whether a tenant is blocked by customer authorization, operator handoff, or admin/node recovery without reading each account row.
- Deployment validation covered backend `py_compile`, all frontend script-tag syntax checks, remote API response, and browser rendering with no question-mark encoding regressions.

### Next block
- Add queue stuck/retry receipts in Task Center for failed or recovered queue items.
- Add tenant-facing account repair row drilldown and CSV export.

### P1.63 Queue event receipts in Task Center
- Queue items now carry `receiptId`, `latestEventId`, and an append-only event trail for create/start/defer/fail/publish/cancel/retry/preflight-block states.
- Stale-task recovery now appends `task_recovered` queue events for queue items tied to recovered central tasks, preserving the customer-support chain of custody.
- `/api/publish/queue`, `/api/publish/queue/detail`, and `/api/central/tasks/detail` now expose public queue receipt data without leaking cookie material.
- Task Center link tracing now shows the queue receipt, latest queue event receipt, event label, and event time next to the existing task/audit context.
- Browser validation used mocked task-detail data to verify queue receipts render in Task Center with no question-mark encoding regressions.

### P1.64 Account repair drilldown and CSV export
- `/api/enterprise/repair-metrics` now accepts `state`, `owner`, `severity`, `q`, and `limit` filters while preserving total/matched counts.
- Enterprise Center now has repair row drilldown, state/owner/severity tabs, keyword search, row-level account maintenance entry, and CSV export.
- Browser validation used mocked repair data to verify filters, row rendering, and CSV entry points without touching external platform sessions.

### P1.65 Queue receipt search in Task Center
- Added queue receipt search helpers so `/api/central/tasks` can match task fields, queue receipt IDs, latest queue event IDs, and queue event metadata.
- Task Center search placeholder now explicitly supports queue receipts, letting support staff paste `queue:*` or event receipts and jump to the linked central task.
- Validation covered an isolated backend fake-queue test, live `q=queue:` API smoke test, and browser placeholder rendering.

### P1.66 Saved support links for task and queue receipts
- Added `/api/enterprise/support-links` for creating and listing support links scoped to the current tenant.
- Added `/api/enterprise/support-links/detail` so support staff can reopen a saved task/queue context without exposing cookie or token material.
- Task Center now lets operators save a support link from the task detail panel and copy the resulting URL for internal handoff.
- Queue references can be resolved by queue ID, queue receipt, latest event receipt, or event ID.

### P1.67 Tenant authorization session audit export
- Added `/api/cloud-login/session-audit` to normalize cloud-login sessions into export-ready rows with status, node, account, latest task, idle time, SLA label, and handoff note.
- Enterprise Center now exposes a CSV export button in the login-session operations panel.
- The export is tenant-scoped and role-gated to auditor-or-above access, matching the enterprise support/audit model.

### P1.68 Support-link list, search, and lifecycle controls
- Support links now store note, archived state, open count, and last-opened timestamp.
- `/api/enterprise/support-links` supports search and optional archived-link visibility.
- `/api/enterprise/support-links/detail` updates last-opened metadata when a support link is opened.
- `/api/enterprise/support-links/update` lets auditor-or-above users update notes and archive/restore links.
- Enterprise Center now has a tenant support-link panel with search, copy, open, note, archive, and restore actions.

### P1.69 Support-link owner, SLA, and handoff export
- Support links now include owner role/name, severity, and computed SLA metadata.
- SLA labels distinguish active tracking, due-soon, overdue, needs-review, and closed support links.
- Support-link update now supports owner and severity changes in addition to note/archive lifecycle fields.
- Enterprise Center shows support owner and SLA status per link and adds owner editing.
- Enterprise Center can export the current support-link list as a CSV handoff package for customer-success and operations teams.

### P1.70 Support-link dashboard metrics and bulk operations
- `/api/enterprise/support-links` now returns `stats` for active/archived links, critical/warning/info severity, overdue/due-soon SLA state, opened/unopened links, owner distribution, and SLA distribution.
- Added `/api/enterprise/support-links/bulk` for auditor-or-above bulk operations against the current filter or explicit IDs.
- Bulk operations support assign owner, set severity, archive, restore, and append note while preserving tenant scope and audit logs.
- Enterprise Center now shows support-link metric cards, owner distribution, SLA distribution, and current-filter bulk actions for customer-success operations.

### P1.71 Selected support-link bulk actions
- Enterprise Center support-link rows now include selection controls.
- Operators can select the current page, clear selection, and run bulk operations against selected IDs instead of the whole current filter.
- Existing bulk assign, severity, archive, and restore operations now prefer selected support-link IDs when present and fall back to current-filter bulk handling otherwise.
- Successful bulk operations clear the selection to prevent accidental repeated actions.

### P1.72 Support-case timeline view
- Enterprise Center support links now include a timeline action.
- The timeline view combines support-link lifecycle events, central task creation/update, queue receipt events, and related audit logs from the support-link detail payload.
- Support teams can inspect the case context without leaving Enterprise Center, while the existing open action still jumps into Task Center for deeper task-level debugging.

### P1.73 Selected-link handoff export
- Support-link handoff CSV export now prefers selected support-link IDs when any rows are selected.
- If no rows are selected, export keeps the previous behavior and exports the current loaded support-link list.
- This lets customer-success staff build a precise handoff package without exporting unrelated tenant support cases.

### P1.74 Support-case timeline export and customer summary
- Support-case timeline can now be exported as a CSV package containing support ID, time, event kind, title, and detail.
- Enterprise Center can generate and copy a public-safe customer status summary from the current support case.
- The customer summary intentionally excludes Cookie, Token, node secret, and other sensitive internal material while preserving current status, owner, latest progress, and next step.
- The timeline renderer now reuses the same normalized event builder used by export, reducing drift between on-screen evidence and exported handoff evidence.

### P1.75 Case-type customer summary templates
- Customer-readable support summaries now classify cases into auth/login session, publish task, queue/scheduler, execution node, or general support.
- Each case type gets a safer next-step template that explains the operational focus without exposing internal credentials or node secrets.
- The summary still includes case ID, case type, current state, owner, related task state, latest progress, and next step.

### P1.76 Enterprise health snapshot export
- Enterprise Center now exposes a health snapshot CSV export from the header.
- The snapshot covers auth readiness, cookie-unavailable accounts, cloud-login session risk, central task/queue state, node online/capacity state, support SLA state, and quota/SLA score.
- This creates a customer-success handoff artifact for tenant-level implementation reviews without requiring database access.

### Next block
- Add health snapshot trend comparison against previous export/checkpoint.
- Add auth readiness repair wizard that starts from snapshot blockers and guides customer-safe remediation.

### P1.77 Enterprise health snapshot baseline and trend
- Enterprise Center now supports saving a tenant health baseline in the browser workspace and comparing the current snapshot against that baseline.
- Health trend covers account authorization readiness, cookie-unavailable accounts, cloud-login session risk, queue/task state, node capacity, support SLA, and quota score.
- Operators can distinguish improved, worsened, and changed metrics before a customer handoff, instead of exporting isolated CSV files with no historical context.
- Exporting a health snapshot also records the latest export as a comparison fallback, while explicit baseline saving remains the recommended customer-success workflow.

### P1.78 Authorization repair wizard
- Enterprise Center now has a customer-safe authorization repair wizard starting from the actual blocker chain: enterprise login, node online status, account authorization, Cookie readiness, and cloud-login session health.
- The wizard gives operators one-click repair actions such as opening account authorization, checking node pool state, reviewing stale login sessions, and refreshing verification.
- The flow is designed for SaaS users: users are guided through front-end actions and never need to manually copy Cookie/Profile data.
- The wizard reuses existing preflight repair signals, so task blockers and account repair metrics lead into the same remediation path.

### P1.79 Tenant-shared health baseline persistence
- Added `/api/enterprise/health-snapshots` so tenant health baselines are saved in the central scheduler state instead of only in one operator browser.
- Health snapshots are scoped by `orgId`, require auditor-or-above access, sanitize row fields, retain bounded history, and write audit events.
- Enterprise Center now loads the latest cloud checkpoint on refresh, saves new baselines to the cloud first, and falls back to local browser storage only when the API is unavailable.
- Exported health snapshots also sync a `last_export` record, giving customer-success teams a shared handoff trail across devices.

### P1.80 Bulk cleanup for stuck authorization sessions
- Added `/api/cloud-login/sessions/cleanup` to close only tenant-scoped `stale` or `failed` cloud-login sessions that are safe to close.
- The cleanup API requires admin access, records audit logs, dispatches node close tasks, and returns per-session results, and supports dry-run preview for safe validation.
- Authorization repair wizard now offers a one-click cleanup step when stale or failed sessions are detected, while leaving active/running user sessions untouched.
- This reduces support workload when users restart browsers or abandon login sessions, and gives customer-success teams a safer recovery path before asking users to re-authorize.

### P1.81 Cloud authorization session resume
- Added central `/api/cloud-login/resume` so authorization pages can recover the latest tenant-scoped cloud-login session by account and node even when the browser lost local `sessionId` storage.
- `/api/cloud-login/current` without a `sessionId` now uses the same central session index for backward-compatible recovery instead of relying only on a live node call.
- Login page recovery now calls the central resume API first, then uses the recovered `sessionId` and node to refresh the cloud browser screenshot.
- Resume candidates are scoped by `orgId`, filtered by account/node when provided, prefer active/running sessions, and can include stale sessions so abandoned browser refreshes can still be recovered or consciously restarted.

### P1.82 Enterprise Center continue-authorization entry
- Enterprise Center cloud-login session rows now expose a customer-safe continue-authorization action.
- The action opens `login-douyin.html?resume=1&accountId=...&nodeId=...`, allowing the login page to recover the latest cloud session through `/api/cloud-login/resume`.
- Operators can resume active/stale sessions from the session operations panel without manually copying session IDs.

### P1.83 Exact cloud authorization session resume
- Continue-authorization links now include a tenant-scoped safe `sessionRef` such as `cls-*`, instead of relying only on account/node latest-session matching.
- `/api/cloud-login/resume` accepts `sessionRef` and resumes that exact session when it is active/running/logged-in/stale and still tenant-scoped.
- If the referenced session is closed, missing, or not resumable, the API returns a clear non-resumable result instead of silently resuming another session for the same account.
- The login page reads `sessionRef` from the URL and uses it during automatic resume, so customer-support operators can continue the exact row they clicked.

### P1.84 Customer-safe authorization page token handling
- The Douyin authorization page now hides the raw API/debug token input by default, matching an enterprise end-user workflow.
- The page reads the existing enterprise session token from browser storage and shows a customer-facing login-state hint.
- If the login state is missing, users are told to return to the system homepage and sign in; administrators can append `?debug=1` to expose the token field for troubleshooting.
- Start/resume/status requests now fail fast with a clear enterprise-login message when no token is available, avoiding silent no-op clicks.

### P1.85 Tenant-scoped authorization links
- All front-end entries that open the Douyin authorization page now include the current `orgId` in the URL.
- The authorization page reads `orgId/currentOrgId` from the URL and persists it as the active workspace before making API calls.
- Account maintenance, cloud-login session continuation, and the generic account-auth button now preserve tenant context across new windows and browser refreshes.
- This prevents users in multi-tenant deployments from accidentally authorizing or resuming sessions under the default workspace.

### P1.86 Customer-visible account authorization diagnosis
- `/api/accounts/detail` now returns `authorizationStatus` and `authDiagnosis` for the selected tenant account.
- The diagnosis includes readiness, blocker code, severity, support reference, customer-readable summary, suggestions, handoff note, and next action.
- Account Asset Detail now shows an authorization diagnosis card with suggested next steps, a continue-authorization/repair action, and a copyable support evidence package.
- This turns account maintenance from a raw Cookie/node status into a customer-success workflow: reason -> next action -> evidence for support.

### P1.87 Queue/preflight account authorization diagnosis
- `publish_preflight` now returns `accountAuthorization` and `authDiagnosis`, using the same diagnosis model as account detail.
- Queue retry and queue execution preflight blocks now include `accountAuthRef` in event metadata, linking queue failures to the account authorization repair evidence.
- Queue retry/detail messages now surface the authorization diagnosis summary and support reference when account readiness blocks the task.
- This connects scheduler reliability with customer-facing repair guidance: queue blocked -> reason -> support evidence -> authorization repair action.

### P1.88 Task Center queue authorization repair entry
- Task Center detail now detects queue items carrying `preflight.accountAuthorization`.
- When a task-linked queue item is blocked by account authorization readiness, the detail panel shows a repair card with summary, support reference, blocker reason, suggestions, and copyable evidence.
- Operators can jump directly from task detail to account authorization repair or node recovery, closing the handoff gap between Task Center and Account Assets.
- This makes task/queue support flow customer-safe: task detail -> authorization blocker -> evidence -> repair action.

### P1.89 Task Center queue-only blocker visibility
- `/api/central/tasks` now includes queue items that have not created a central task yet as synthetic queue tasks.
- `/api/central/tasks/detail` can open those synthetic queue tasks and returns the queue item, events, preflight, and authorization repair metadata.
- Task Center can now surface preflight-blocked scheduled publish jobs even when the scheduler stopped them before creating an execution task.
- This closes the queue-only visibility gap: queue blocked -> Task Center row -> queue detail -> authorization repair card.

### P1.90 Task Center queue-only retry and cancel
- Synthetic queue tasks now expose `retryable` and `cancelable` capabilities in the same shape as central execution tasks.
- `/api/central/tasks/retry` and `/api/central/tasks/cancel` now understand `queue:*` task IDs and delegate to the publish queue retry/cancel logic.
- Task Center rows and task detail panels can retry or cancel queue-only publish blockers without forcing the user to jump back to the publish queue page.
- Queue cancellation is surfaced as a distinct `canceled` task state, making support triage clearer than showing every canceled queue row as a generic failure.

### P1.91 Enterprise login session first
- Added `/api/auth/refresh` and session expiry reporting from `/api/auth/me`, so enterprise browser sessions can be renewed without exposing backend tokens.
- Frontend now stores enterprise user sessions under a dedicated `matrix_user_session_token` key and uses that before any administrator debug token.
- The header hides raw API/debug tokens by default; only an explicit administrator debug toggle reveals the token input.
- The Douyin authorization page now reads the enterprise session token first, so end users can open authorization from the SaaS UI without copying any Cookie/Profile/token value.

### P1.92 Unauthenticated-safe SaaS bootstrap
- The frontend now detects whether an enterprise session or administrator debug token exists before preloading protected business data.
- Unauthenticated visitors land in Enterprise Center with a clear login prompt instead of triggering multiple 401 business API calls.
- Module navigation is guarded: without login, business modules route back to the enterprise login context.
- Background polling for queue/task/enterprise data is disabled until a valid session/debug token is present.

### P1.93 Server-side RBAC hardening
- Enterprise summary is now scoped by the current user's memberships; normal tenant users no longer receive global organizations, users, tasks, queue, node, audit, material, or knowledge-base counts.
- Read APIs for accounts, materials, knowledge base, publish settings, queues, task center, audit logs, node capacity, notifications, and cloud-login sessions now require at least the appropriate tenant role.
- Write APIs for uploads, knowledge base changes, publish settings, publish queue operations, task retry/cancel, notification state, action-item batch operations, and library deletion now enforce server-side roles.
- Frontend task retry/cancel controls respect the current role: auditor users can inspect task evidence but cannot trigger operational changes.

## 5. 企业版当前开发计划（按用户使用路径推进）

### 阶段 A：用户可登录、可授权、可恢复
- 目标：企业用户只需要在前端登录系统，再完成平台账号授权；不接触 Cookie、Profile、服务器脚本。
- 交付项：企业登录态、账号授权页、授权会话恢复、账号资产状态、授权失败修复入口。
- 当前进度：授权会话恢复、账号诊断、任务阻断修复已接入；下一步把登录态从固定 token 升级为企业用户会话。

### 阶段 B：任务可见、可解释、可处理
- 目标：任何采集、下载、分析、发布、授权失败都必须进入任务中心，用户能看到原因和下一步动作。
- 交付项：统一任务列表、队列预检阻断可见、详情页诊断、重试/取消/跳过、客服证据复制。
- 当前进度：队列预检失败已进入任务中心；下一步补任务中心对队列型任务的重试、取消和筛选。

### 阶段 C：账号和节点资产化
- 目标：企业客户按账号和节点管理产能，而不是按某台电脑脚本管理。
- 交付项：账号资产、节点池、节点健康分、绑定关系、容量限制、离线迁移。
- 当前进度：账号资产、节点池、授权诊断已完成基础版；下一步补节点容量评分和账号绑定策略。

### 阶段 D：寻客中心真实业务闭环
- 目标：用户配置产品关键词后，系统自动找视频、拉评论、分析意向、生成线索，而不是让用户复制链接。
- 交付项：关键词任务、视频搜索、评论采集、AI 意向分析、线索 CRM、跟进状态。
- 当前进度：接口和前端入口已有雏形；需要按企业任务中心化重构，避免做成单人脚本按钮。

### 阶段 E：商业交付与运维
- 目标：系统可以交付给多个企业客户使用，客服能排障，管理员能看用量，服务可升级可回滚。
- 交付项：RBAC、套餐配额、审计日志、健康报表、备份恢复、部署升级脚本、告警。
- 当前进度：多租户、审计、健康快照已有基础；下一步补 RBAC 与企业级配额。

### P1.94 Enterprise account authorization UX and SMS click reliability
- The cloud authorization page now gives immediate visual feedback when the customer clicks the SMS verification action: the button enters a pending state and logs the exact result.
- Node-side SMS verification click now uses three deterministic layers: exact text center-click, DOM event dispatch on the clickable parent, and a guarded coordinate fallback for the known identity-verification dialog.
- The SMS endpoint returns `clickMethod` and `externalPromptAccepted` evidence, so support can distinguish locator failure, DOM failure, and native protocol prompt handling.
- Failure cases now automatically trigger account diagnosis from the frontend instead of leaving customers with a silent "no response" state.

### P1.95 Enterprise account authorization health panel
- Added `/api/accounts/authorization-summary` for tenant-scoped account authorization health aggregation.
- The summary reports ready accounts, accounts requiring authorization, node issues, in-progress authorization sessions, online node capacity, and a prioritized top issue.
- The account matrix page now renders an enterprise-facing authorization health panel before the raw platform cards, so customers see business readiness first.
- The panel reuses existing account diagnosis and repair actions, avoiding a separate debugging workflow for normal users.

### P1.96 Finder center task receipt loop
- Finder Center now keeps the latest product-keyword discovery job as a customer-facing task receipt.
- The receipt shows keyword, central task id, execution node, searched videos, collected comments, identified leads, status, and error reason.
- Customers can jump from Finder Center directly into Task Center for execution trace and replay evidence.
- This keeps the workflow product-keyword driven: users do not need to paste video links for the normal discovery path.

### P1.97 Commercial plan entitlements and feature gates
- Added a server-side plan catalog (`trial`, `starter`, `standard`, `pro`, `enterprise`) with per-plan quotas and feature switches.
- Added `/api/enterprise/entitlements` and embedded entitlement data into `/api/enterprise/usage` for frontend consumption.
- Enterprise preflight now includes a plan-capability check, so unavailable modules produce a clear blocker before a customer starts a task.
- Server-side feature gates now protect task dispatch, uploads, knowledge-base operations, publish preflight, and quota controls from plan bypass.
- Enterprise Center now shows the current commercial plan, effective limits, feature switches, and restricted-module count; navigation respects plan-disabled modules.


### P1.98 Customer onboarding delivery cockpit
- Development plan is now explicitly enterprise-first: tenant workspace, node pool, account authorization, materials/knowledge, quota/alerts, then low-risk pilot tasks.
- Added server-side onboarding `delivery` summary so the frontend does not guess customer readiness from local UI state only.
- The delivery summary returns status, progress, blocking next step, next action, customer message, roadmap, and commercial plan context.
- Enterprise Center now renders a customer delivery cockpit with the next action CTA, progress bar, delivery roadmap, and refresh/repair entry.
- The next action is routed by business step: account authorization opens login, assets route to material publishing, controls open SLA settings, node issues focus the node pool, and ready tenants go to Finder pilot.

### P1.99 Role-aware customer delivery actions
- Onboarding next actions now carry a `requiredRole` from the backend, separating customer operators from administrators and auditors.
- Workspace/node/governance delivery steps require admin-level control; account authorization, assets, and pilot tasks can be performed by member operators.
- Enterprise Center blocks the primary delivery CTA for read-only or insufficient roles and gives a clear customer-facing permission message instead of silently failing.

### P2.01 Enterprise account authorization state machine
- Added `/api/cloud-login/flow` as the customer-facing state source for Douyin account authorization.
- The flow endpoint merges node health, account readiness, resumable cloud-login sessions, latest session status, diagnosis, recommended next action, and a four-step progress model.
- The login authorization page now renders a flow panel with headline, detail, current phase, session reference, diagnosis code, and next action.
- The page now syncs the flow before/after start, resume, screenshot, SMS, and final save so customers see actionable feedback instead of silent button clicks.
- The flow model disables unsafe/confusing starts when no execution node is available and prompts resume/restart when a cloud session is already in progress.

### P2.02 Centralized account authorization finish
- Added `/api/cloud-login/finish` so the final authorization save is orchestrated by the central scheduler instead of being manually chained in the browser.
- The endpoint verifies the cloud login session, confirms `loggedIn`, closes the node browser session, clears related action snoozes, returns account detail when available, and includes the latest flow state.
- The authorization page now uses `/api/cloud-login/finish` for the "complete and save" step, while preserving customer feedback and post-save account health polling.
- Missing or not-yet-logged-in sessions now return structured flow evidence for the frontend, rather than only a generic failure string.

### P2.03 Flow-aware authorization controls
- The authorization page button states now follow the server-side flow model.
- Start is disabled when the backend reports no usable execution node; resume is disabled when no resumable session exists; restart is disabled only when the backend marks force-new unsafe.
- This prevents the UI from re-enabling invalid actions after a busy/error transition and makes customer-facing behavior consistent with the central scheduler state.

### P2.04 账号授权保存后的资产同步可见性
- 后端新增 `/api/accounts/authorization-status`，把官方登录状态、云端会话、账号资产登记、节点在线、Cookie 可用性合并成一个客户可读状态。
- `/api/cloud-login/finish` 返回 `authorization` 快照，保存后立即展示“同步中 / 可用 / 节点异常 / 需要重新授权”。
- 授权页新增账号资产同步面板，按登录、会话、资产登记、节点、Cookie 五个阶段展示状态。
- 前端不再只轮询 `/api/accounts/detail`，改为企业级授权状态接口，避免用户点完保存后看不到结果。

### P2.06 企业任务中心摘要
- 后端新增 `/api/enterprise/task-center`，汇总授权、发布、寻客、搜索、下载等云端任务状态。
- 摘要返回健康 / 警告 / 阻塞状态、排队、执行中、失败、需恢复计数和优先处理任务。
- 企业中心的中央任务中心已接入该摘要，用户先看结论和下一步，再看明细。

### P2.07 失败任务归因聚合
- `enterprise_task_center` 新增 `failureGroups`，把失败任务按账号授权、节点/浏览器、素材、限额/策略、网络和平台响应分类。
- 企业中心任务摘要展示失败归因标签，点击可直接进入任务中心查看对应失败。

### P2.08 任务中心批量处理
- 后端新增 `/api/enterprise/task-center/bulk`，支持 `preview / retry / cancel / recover`，可按状态、类型、关键字和失败归因选中任务。
- 前端任务中心新增预览失败、重试失败、取消排队和重试当前归因入口。
- 执行型批量操作前端需要确认，审计员只能预览，恢复卡住任务仍需管理员权限。

### P2.09 批量重试安全护栏
- 批量重试不再直接重试账号授权类失败任务，这类任务需要引导用户重新授权或恢复会话。
- `/api/enterprise/task-center/bulk` 预览结果保留 `retryBlockedReason`，便于后续在前端展示“需重新授权”而不是盲目重试。


### P2.10 Account-auth failure repair path
- `/api/enterprise/task-center` failureGroups now returns affected accounts, affected nodes, sample account/node, repair action, CTA label, customer-readable hint, and retry-safety metadata.
- Account-authorization failures are marked as `open_auth_repair_wizard`; the product no longer tells operators to bulk-retry failures that require a customer login/session repair.
- `/api/central/tasks` now supports `failureGroup` filtering, so Task Center can show exact attribution slices instead of relying on error-text search.
- Enterprise Center routes failure attribution by business action: account auth opens the repair wizard, while node/material/policy groups continue to task review or safe retry paths.

### Next block
- Show `retryBlockedReason` and attribution explanation inside task detail for support copy/paste.
- Let the authorization repair wizard open the affected account maintenance entry directly.
- Add one-click node health check and browser-session cleanup for node-runtime failure groups.


### P2.11 Task-detail failure explanation
- `public_task` now includes `failureCategory`, `retryBlockedReason`, and `retryBlockedLabel` for failed tasks.
- Account-auth failures prioritize `requires_account_reauth` as the retry-blocked reason, even when the low-level task path is not directly retryable.
- Task Center detail now displays a customer-readable failure attribution card with repair CTA and copyable support explanation.
- Support can copy a compact failure explanation containing task id, path, node, account, failure group, repair action, retry block, customer hint, and sanitized error.

### Next block
- Make the failure card deep-link directly into the affected account maintenance panel when account id is available.
- Add node-runtime repair CTA that runs a safe node health probe before retry.
- Add task receipt export into support-link timeline automatically after a user opens a failed task.


### P2.12 Direct repair CTA from task detail
- Failed task detail now detects the affected account from task body metadata.
- For account-auth failure cards, the primary repair CTA opens the affected account maintenance/login flow directly when account id is available.
- If the task does not include an account id, the CTA falls back to the authorization repair wizard and group-level handling.

### Next block
- Add node-runtime repair CTA that probes node health before retry.
- Add visible failure-group filter chip inside Task Center so users know they are viewing an attribution slice.


### P2.13 Node-runtime health probe and safe recovery
- Added `/api/central/node-runtime-probe` for tenant-scoped node diagnostics.
- The probe returns node online state, capacity, local API health, stale task candidates, stale cloud-login sessions, recent task status counts, runtime failure count, issues, suggestions, and severity.
- Admin repair mode runs scoped stale-task recovery for the selected node only; auditor mode can probe but cannot mutate state.
- Task Detail node-runtime repair CTA now calls the probe/repair endpoint instead of only routing users to Enterprise Center.

### Next block
- Add visible failure-group filter chips inside Task Center.
- Add node-runtime repair result card in the UI instead of only writing the summary message.
- Add optional stale authorization-session cleanup scoped by node after the health probe.


### P2.14 Visible failure-group filter state
- Task Center now shows the active failure-attribution filter as a visible chip below the toolbar.
- The chip displays the selected attribution label and customer hint from `failureGroups`.
- Operators can clear only the attribution filter without resetting status/type controls.

### Next block
- Add a persistent node-runtime repair result card after probe/repair.
- Add scoped stale cloud-login session cleanup after node health probe.


### P2.15 Node probe result card and scoped session cleanup
- `bulk_close_cloud_login_sessions` now supports `nodeId` scoping so stale/failed authorization sessions can be cleaned without touching other nodes.
- `/api/central/node-runtime-probe` repair mode now returns `sessionCleanup` and, by default, cleans stale/failed cloud-login sessions for the selected node only.
- Task Detail stores the latest node probe result and renders a node health card with issues, local API health, capacity, stale task counts, and authorization-session cleanup counts.
- The node health card provides explicit actions for re-checking and for repair+cleanup, improving support/operator handoff after node-runtime failures.

### Next block
- Add task support-link timeline auto-append for failed-task probe/repair events.
- Add customer-facing account authorization re-entry from the node probe card when `cookie_unavailable` is present.


### P2.16 Account authorization re-entry from node probe
- Node probe result card now detects `cookie_unavailable` and shows a direct account-authorization maintenance CTA when the failed task contains an account id.
- The CTA reuses the existing `maintainAccount` flow, preserving the same cloud-login/session handoff path as account detail repair.
- Operators no longer need to infer that a node probe warning about Cookie availability should route back to account authorization.

### Next block
- Add failed-task probe/repair events to support-link timelines automatically.
- Add a compact node probe history list for support handoff.

## 8. 企业版产品化开发蓝图（面向客户而不是单机脚本）

### 客户交付目标
- 客户只关心“账号是否可用、任务是否在跑、失败该谁处理、处理后是否可复盘”。系统必须把底层脚本、浏览器、Cookie、节点状态封装成业务状态。
- 前端面向企业多人协作：老板看结果和成本，管理员看账号和节点，运营看任务和线索，客服看支持案例和时间线，审计员看证据链。
- 所有动作默认有企业工作区、操作者、账号资产、执行节点、任务编号、回执编号和审计记录。

### 开发主线
1. 账号授权产品化：用户在前端自助授权，系统自动登记账号资产、Cookie 可用性、绑定节点和授权有效期；授权失败要能恢复会话。
2. 节点池商业化：一个企业可绑定多个节点，一个节点可承载多个账号，但必须有容量、冷却、失败率、IP 地域、在线率和任务隔离。
3. 任务中心统一化：发布、下载、评论抓取、寻客、授权、修复都进入统一任务模型；支持筛选、详情、链路追踪、安全重试和批量处理。
4. 支持案例自动化：任务失败或节点异常时自动沉淀为支持案例，客服能打开时间线看到探测、修复、队列、审计全过程。
5. 寻客中心真实化：由产品关键词自动搜索视频、拉取评论、AI 意向识别、生成线索并进入 CRM 跟进，不要求用户手工复制链接。
6. 运营安全边界：每个外部平台动作都必须有 preflight、限额、冷却、去重、失败可解释和人工可接管入口。
7. 商业交付能力：部署脚本、升级脚本、备份恢复、服务监控、告警通知、套餐配额、审计导出和客户支持链接。

### 当前优先级
- P2.17：把节点探测和修复自动关联到任务支持案例，解决“客户报错后客服无法复盘”的问题。
- P2.18：把支持案例推送到企业首页待处理，并按 ownerRole 分给运营、管理员、客服。
- P2.19：把寻客中心从演示数据切换为真实任务流：关键词搜索视频 -> 评论抓取 -> 意向评分 -> 线索入库。
- P2.20：把账号授权页做成客户可用的自助入口：扫码/短信验证、会话恢复、授权成功自动回写主系统。
- P3.01：把 JSON 状态迁移到 SQLite/PostgreSQL，提供迁移脚本和备份恢复脚本。

### 验收标准
- 企业用户不需要理解脚本目录、Cookie 文件或服务器进程，也能完成授权、发布、寻客和故障处理。
- 任一失败任务都能在 30 秒内定位到企业、账号、节点、队列、失败归因、最后一次探测和下一步处理动作。
- 支持案例可以导出给客服或客户成功团队，且不暴露 Cookie、密码、token 等敏感信息。
- 多企业数据默认隔离；除 root-token 应急模式外，任何接口都不能跨企业读取任务、账号或线索。

## 9. 本轮继续开发记录（2026-06-30）

### P2.17 任务失败自动沉淀支持案例
- 后端 `/api/central/node-runtime-probe` 支持接收 `taskId`，会校验任务归属企业和节点一致性。
- 节点探测/修复动作会把 `taskId`、`nodeId`、问题归因、修复数量、授权会话清理数量写入审计日志。
- 新增任务支持案例自动创建/复用逻辑：同一任务已有活跃支持案例时只更新 meta，不重复创建。
- 支持案例 meta 会记录最近一次节点探测和修复结果，客服打开案例时间线时能看到完整证据链。
- 前端任务详情的“节点健康探测”会把当前任务 ID 一起提交，探测成功后显示支持案例入口。
- 任务详情中可一键跳到企业中心的支持案例时间线，减少客服/运维在多个页面之间来回查找。
### P2.18 支持案例进入企业待处理中心
- 后端 `enterprise_action_items` 现在会聚合当前企业的活跃支持案例，生成 `support_case_open` 待处理项。
- 支持案例待处理项包含 `supportId`、`taskId`、负责人角色、SLA、备注和时间线入口。
- 企业待处理搜索已支持按 `supportId` 定位，便于客服通过客户反馈的支持链接反查。
- 前端待处理筛选新增“支持案例”类型。
- 点击支持案例待处理项会直接打开企业中心支持案例时间线，客服可以继续导出或复制客户摘要。
### P2.19 企业线索资产最小闭环
- 后端新增 `finderLeads` 中央资产表，按 `orgId` 隔离保存寻客评论线索。
- `/api/finder/discover` 成功返回后会自动把高意向/中意向/咨询线索写入中央资产表。
- 新增 `/api/finder/leads` 查询接口，支持按关键词、状态、意向筛选企业线索。
- 新增 `/api/finder/leads/import` 和 `/api/finder/leads/update`，为后续批量导入、CRM 跟进状态更新预留接口。
- 前端进入寻客中心会读取当前企业的线索资产，自动寻客成功后显示“线索资产已入库”。
### P2.20 寻客线索 CRM 状态流
- 企业待处理中心新增 `finder_lead_followup`，高意向/咨询类新线索会进入待处理列表。
- 待处理项可直接跳转到寻客中心并按关键词加载对应企业线索。
- 前端“匹配账号”会把线索状态写回中央服务为 `follow`，刷新页面后仍保留在“待关注”。
- 操作队列“关注 / 私信”会把状态依次推进为 `dm / done`，形成最小 CRM 跟进闭环。
- 手动从评论抓取来的线索在匹配时会先导入中央线索资产，再进入跟进队列。
### P2.21 登录授权会话可恢复运维（已落地）
- 后端 `/api/cloud-login/sessions` 增加 `canResume/recoverable/staleAt/timeToStaleSec/customerAction`，让企业前端能判断会话是否可继续、多久会变成卡住状态、下一步应让客户做什么。
- `/api/cloud-login/sessions/close` 从仅管理员调整为企业成员可关闭本企业授权会话，避免一线运营无法处理卡住扫码/短信验证窗口。
- 账号资产详情新增“当前授权会话”卡片，展示 Session、节点、空闲时间、更新时间、交接说明，并提供继续授权/关闭重建入口。
- 打开授权维护页时主系统同步记录修复进度，用户刷新或切回页面后可以从账号详情或会话运维继续处理，而不是依赖单个临时窗口。
### P2.22 发布队列健康态（已落地）
- 队列列表项增加后端 `health` 摘要：状态、严重级别、阻塞原因、账号授权诊断、下一步动作、空闲/等待时间。
- 列表页直接展示“需处理 / 排队较久 / 发布中”等业务化提示，不再只显示 pending/fail 这种工程状态。
- 当队列被账号授权问题阻塞时，前端显示“修复账号”入口，直接打开对应账号的授权维护页。
- 失败/卡住队列仍保留详情、重试、取消入口，方便运营按回执追踪和售后交接。### P2.23 企业用户化前端与新租户默认交付（已落地）
- 新企业/工作区创建时自动补齐发布设置、套餐配额、通知设置和引导状态，避免商业版客户进入系统后还需要人工初始化脚本配置。
- 授权页新增 `matrix-login-progress` 进度事件：开始授权、恢复会话、等待扫码、短信验证、检测登录、保存完成都会回流主系统。
- 主系统监听授权进度并更新修复进度卡、账号详情提示和企业首页状态，用户无需理解 Cookie/Profile，也能知道下一步该做什么。
- 发布队列空态改为业务引导：无账号引导授权、无素材引导上传、未开自动发布引导开启；不是简单显示“队列为空”。
- 该批次目标是把功能从“开发者自己知道怎么用”改为“企业客户首次进入也能按页面提示走完交付闭环”。

### 下一批次
- 把企业工作区初始化做成显式 onboarding API，支持前端显示“交付检查单”。
- 为授权会话增加服务端事件流/轮询摘要，减少跨窗口消息丢失。
- 将 JSON 状态迁移准备拆成 schema、迁移脚本、备份脚本三步。### P2.24 交付检查单增强（已落地）
- 后端在 `/api/enterprise/onboarding` 中增加 `deliveryChecklist`，按工作区、节点、账号、素材、控制项、发布/寻客预检、队列健康、授权会话交接、支持案例闭环聚合交付状态。
- 检查单输出 score、阻塞项、风险项、通过数、下一检查项和每一项的责任角色/模块/动作，方便按客户成功流程交接。
- 企业中心新增“交付检查”卡片：展示交付分、阻塞项、风险项和每个检查项的处理入口。
- 操作入口按业务跳转：账号问题去授权、素材/队列去自动发布、寻客预检去寻客中心、支持案例回到企业中心处理。
- 这一步把“功能能用”进一步推进为“客户首次交付能验收、客服能复盘、运营能知道下一步”。

### 下一批次
- 把交付检查单支持一键导出为客户验收摘要。
- 给授权页增加服务端进度轮询摘要，避免只依赖跨窗口消息。
- 开始 JSON -> SQLite/PostgreSQL 迁移前置：schema 草案、迁移脚本、回滚脚本。### P2.25 交付验收摘要导出（已落地）
- 新增 `/api/enterprise/delivery-acceptance`，基于企业 onboarding 和 deliveryChecklist 生成脱敏 Markdown 验收摘要。
- 摘要包含工作区、生成时间、交付状态、交付分、阻塞/风险数、交付结论、下一步和完整检查项表格。
- 报告明确不包含 Cookie、Token、短信验证码等敏感信息，适合发给客户或客服/客户成功团队复盘。
- 企业中心“交付检查”卡片新增“导出验收摘要”按钮，前端直接下载 `.md` 文件。
- 这一步补齐商业交付闭环：不仅能检查，还能形成可交接、可验收、可归档的文档产物。

### 下一批次
- 授权页增加服务端进度轮询摘要，降低跨窗口消息丢失风险。
- 交付验收摘要增加公司 Logo/客户名/负责人字段。
- 开始数据层迁移准备：SQLite/PostgreSQL schema 草案和迁移脚本。### P2.26 授权进度服务端回流（已落地）
- 新增 `/api/cloud-login/progress`：授权页可把开始授权、恢复会话、等待扫码、短信验证、检测登录、保存完成、失败等进度事件写入中央服务。
- 主系统不再只依赖 `window.postMessage` 和 `localStorage`，会每 4 秒从中央服务轮询最新授权进度，窗口刷新或跨标签页也能恢复当前进度。
- 企业中心“登录会话运维”新增“最新授权进度”卡片，客服/运营可以看到客户授权停在哪一步、对应账号、节点和更新时间。
- 授权页仍保留本地跨窗口消息，服务端进度作为可靠兜底；两个来源进入同一套 `repairProgress` 状态，避免用户看到两套不一致流程。
- 服务端只保存状态、标签、说明、账号 ID、节点 ID 和短 Session 标识，不保存 Cookie、短信验证码或敏感 Token。

### 下一批次
- 为授权会话增加“继续/关闭/重建”的统一动作审计，形成更完整的授权维护时间线。
- 给发布队列增加批量预检和批量修复入口。
- 开始数据层迁移准备：SQLite/PostgreSQL schema 草案和迁移脚本。### P2.27 授权维护统一时间线（已落地）
- 新增 `/api/cloud-login/timeline`，按企业、账号、节点和 Session 聚合授权维护事件。
- 时间线聚合三类证据：授权页进度事件、云端 `/api/cloud-login/*` 任务、会话关闭/清理等审计动作。
- 企业中心“登录会话运维”每条会话新增“时间线”入口，客服/运营可展开查看授权从创建、扫码、短信、刷新、保存、关闭到失败的完整链路。
- 时间线仅展示脱敏状态、短 Session、账号 ID、节点 ID、任务状态和错误摘要，不展示 Cookie、验证码、Token 等敏感数据。
- 这一步解决“用户说点了没反应/没收到验证码/窗口卡住”时客服无法复盘的问题，把授权维护变成可交接的企业级流程。

### 下一批次
- 发布队列增加批量预检和批量修复入口，把账号授权阻塞、节点离线、素材缺失统一批处理。
- 为账号详情页也接入授权维护时间线，直接从单个账号资产看历史维护过程。
- 开始数据层迁移准备：SQLite/PostgreSQL schema 草案和迁移脚本。
### P2.28 发布队列批量体检与安全修复（已落地）
- 新增 `/api/publish/queue/batch-preflight`，按企业工作区批量扫描待发布/失败队列，逐条执行账号、素材、额度、发布开关等前置校验。
- 批量体检默认只预览，不触发真实发布；“体检并修复”只会更新队列健康证据、把已恢复的失败项重新排队、把仍阻塞的项标记为需处理。
- 每条队列会写入 `batch_preflight_ready / batch_preflight_requeued / batch_preflight_blocked` 回执事件，客服可在队列详情和任务中心复盘。
- 前端发布队列新增“批量体检”和“体检并修复”入口，面向企业运营展示可执行数、阻塞数、重新排队数和下一步建议。
- 这一步把发布队列从“用户逐条点重试”推进为“企业运营可一键体检、客服可追责、管理员可批量恢复”的商业版运维能力。

### 下一批次
- 在账号详情页接入授权维护时间线，直接从单个账号资产看历史授权维护过程。
- 给发布队列批量体检结果增加可下载 CSV，便于客服交接。
- 开始数据层迁移准备：SQLite/PostgreSQL schema 草案和迁移脚本。
### P2.29 账号详情接入授权维护时间线（已落地）
- 账号资产详情新增“授权时间线”入口，运营在单个账号页面即可查看授权进度、云端任务和审计事件，不再必须回到企业中心查会话运维。
- 时间线按当前账号、节点和最近会话自动过滤，支持从账号详情直接定位“扫码/短信/保存/关闭/失败”发生在哪一步。
- 账号详情内复用统一脱敏时间线展示，不暴露 Cookie、验证码、Token 等敏感数据。
- 这一步补齐客服排障的最短路径：客户报某个账号不可用时，先打开账号资产，再看时间线和诊断，而不是让客户描述操作过程。

### 下一批次
- 给发布队列批量体检结果增加 CSV 导出和客服交接摘要。
- 把账号授权时间线入口接入支持案例详情，支持案例打开时自动关联对应账号。
- 开始数据层迁移准备：SQLite/PostgreSQL schema 草案和迁移脚本。
### P2.30 发布队列体检结果导出（已落地）
- 发布队列新增“导出体检”入口，运营或客服可把最近一次批量体检结果导出为 CSV。
- 若当前页面还没有体检结果，导出会先自动执行一次只读批量体检，再生成交接表。
- CSV 包含队列编号、账号、素材、前后状态、是否可执行、阻塞原因、下一步动作、支持证据号和告警信息，便于客服交接和客户成功复盘。
- 导出过程不触发真实发布，不包含 Cookie、验证码、Token 等敏感数据。

### 下一批次
- 把账号授权时间线入口接入支持案例详情，支持案例打开时自动关联对应账号。
- 给企业中心增加“客户交付包”汇总下载，把验收摘要、队列体检、账号诊断合并为一个交付材料。
- 开始数据层迁移准备：SQLite/PostgreSQL schema 草案和迁移脚本。
### P2.31 支持案例自动关联账号授权时间线（已落地）
- 支持案例详情现在会从任务、队列、回执和 meta 中自动提取关联账号与节点，并返回 `accountContext`、`accountAuthorization` 和 `authTimeline`。
- 客服打开支持案例时，页面会自动合并账号授权事件到案例时间线，并同步展开关联账号的授权维护时间线。
- 支持案例卡片新增关联账号状态块和“账号授权时间线”入口，客服无需再手工复制账号 ID 去账号矩阵查询。
- 客户可读摘要中补充“关联账号”状态，便于客户成功团队解释问题是账号授权、节点、队列还是素材导致。
- 全链路继续脱敏：只展示账号 ID/节点 ID/状态/错误摘要，不暴露 Cookie、验证码、Token 或节点密钥。

### 下一批次
- 给企业中心增加“客户交付包”汇总下载，把验收摘要、队列体检、账号诊断合并为一个交付材料。
- 开始数据层迁移准备：SQLite/PostgreSQL schema 草案和迁移脚本。

## P2.32 客户交付包（已实现）

- 企业视角：客户不只需要看功能是否可用，还需要一份能给客户、实施、售后共用的交付凭证。
- 后端：新增 `GET /api/enterprise/delivery-package`，聚合交付验收、账号授权诊断、发布队列体检、活跃支持案例、用量与额度，输出 Markdown 交付包。
- 前端：交付检查卡片增加【导出客户交付包】入口，使客户和售后可以直接下载当前工作区的交付状态。
- 安全边界：交付包明确不包含 Cookie、Token、短信验证码等敏感信息，只用于运营对账和售后闭环。


## P2.33 客户交付风险闭环（已实现）

- 企业视角：客户不关心技术中间态，只关心是否有明确阻塞、谁负责、下一步做什么。
- 后端：新增 `GET /api/enterprise/delivery-risks`，聚合交付检查失败项和企业行动项，输出阻塞/风险/提示、责任角色、建议动作和下一个需处理项。
- 前端：企业中心新增【客户交付风险闭环】卡片，展示风险数、状态标签、责任角色和处理按钮。
- 操作链路：风险卡片可直接定位到账号授权、发布队列、寻客中心或企业节点/售后区域，避免只给客户看虚拟数据。


## P2.34 客户试运行 Runbook（已实现）

- 企业视角：交付后不能直接把功能全部打开给客户，应有低频、小样本、有回执的试运行流程。
- 后端：新增 `GET /api/enterprise/pilot-runbook`，基于交付检查、风险闭环、发布/寻客预检和用量状态，输出试运行是否可开始、阶段进度和安全默认值。
- 前端：企业中心新增【客户试运行 Runbook】卡片，按阶段展示企业权限、账号授权、素材话术、干跑回执、寻客小样本和验收复盘。
- 默认策略：试运行采用 1 条样本、60min 间隔、先干跑再扩展的客户可接受交付流程。


## P2.35 客户级账号授权交接（已实现）

- 企业视角：客户登录账号时不应看到底层脚本错误或 Cookie 概念，而是看到是否需要授权、是否卡住、该由谁处理。
- 后端：新增 `GET /api/accounts/auth-handoff`，聚合账号授权汇总、云端登录会话和交接建议，输出客户提示、实施提示、下一步动作和授权流程。
- 前端：账号矩阵页新增【客户授权交接】卡片，展示可用账号、需授权、进行中、卡住/失败数量，并将每个条目导向授权、恢复会话或节点检查。
- 用户化改造：交接流程明确为打开授权、扫码/短信验证、完成并保存、刷新确认，避免让客户复制 Cookie 或理解脚本细节。


## P2.36 卡住授权会话关闭重开（已实现）

- 问题：授权会话长时间无更新时，单纯显示“恢复会话”会让客户反复回到卡死画面。
- 后端：`/api/accounts/auth-handoff` 对超过 1 小时无更新的 stale 授权会话返回 `cleanup_and_restart`，指导客户关闭重开。
- 前端：账号授权交接卡片支持【关闭重开】，先调用云端会话关闭接口，成功后自动打开新授权向导。
- 客户体验：客户不需要理解会话 ID、Cookie 或脚本占用，只需按钮重新授权。


## P2.37 发布队列与授权交接联动（已实现）

- 问题：发布队列被账号 Cookie/授权阻塞时，不能只显示“发布失败”，客户需要直接看到哪个队列被哪个账号阻塞、下一步怎么处理。
- 后端：新增 `GET /api/publish/queue/auth-handoff`，基于队列健康、发布预检和 `/api/accounts/auth-handoff` 聚合出队列授权阻塞摘要。
- 前端：发布队列区新增【队列授权阻塞】卡片，展示队列总数、授权阻塞数、可体检数和关联项数。
- 操作闭环：队列行上的“修复账号”优先跳到队列对应的授权交接项，支持关闭重开 stale 会话、继续授权或检查节点。

## P2.38 客户启动中心聚合（已实现）

- 新增 `/api/enterprise/customer-startup`：从企业工作区、账号授权交接、发布队列授权、素材准备、交付风险和试运行 Runbook 聚合客户启动状态。
- 前端企业中心新增“客户启动中心”：用户登录后只看一个下一步 CTA，不再在账号、队列、素材、风控卡片之间自行判断。
- 下一步动作支持账号授权/关闭重开、素材上传、队列处理、低频试运行、交付风险闭环，面向客户交付而非个人脚本使用。
- 回归要求：`central_server.py` 通过 py_compile；前端全部 `<script>` 块通过 `node --check`；页面无 `question-mark placeholder` 编码退化。
## P2.39 客户启动回执（已实现）

- 新增 `/api/enterprise/customer-startup/receipt`：把客户启动中心状态导出为 Markdown 回执。
- 回执包含工作区、启动状态、当前最应做动作、启动卡片、阻塞风险、安全默认值，不包含 Cookie、Token、短信验证码。
- 前端客户启动中心新增“导出启动回执”按钮，用于售前交付、客户成功交接和售后复盘。
## P2.40 客户启动阻塞清单（已实现）

- 客户启动中心新增阻塞清单，将后端 `blockers` 显示为可点击处理项。
- 每个阻塞项保留来源、标题、说明和动作按钮，点击后复用统一启动动作路由，直达授权、队列、素材或风险闭环入口。
- 目标是让客户成功/运营人员按业务责任处理，不需要理解底层脚本、Cookie 或节点实现细节。
## P2.41 授权重启后的自动轮询与成功回执（已实现）

- 新增 `/api/accounts/authorization-watch`：聚合账号授权状态、云端登录会话、客户启动中心、授权交接信息，给前端一个可轮询的安全状态源。
- 前端新增授权观察器：用户点击授权、继续授权或关闭重开后，系统每 6 秒自动确认授权状态，不再要求用户手动刷新或猜测 Cookie 是否生效。
- 授权成功后自动刷新账号资产、客户启动中心和发布队列，并在页面显示“授权已确认，可继续试运行/队列”的交付回执。
- 手动“刷新状态”改为调用授权观察器，避免只看全局 CookieReady 导致误判。
## P2.42 授权重启单一事务接口（已实现）

- 新增 `/api/accounts/authorization-restart`：由中央调度统一完成“选择旧会话、关闭旧会话、生成新授权入口、返回观察地址”。
- 前端“关闭重开”改为调用该事务接口，不再在浏览器里串联多个易失败步骤。
- 接口即使旧会话已经不存在，也会返回新的授权入口和观察地址，降低客户点击后无反应的概率。
- 所有重启动作写入审计日志 `account.authorization.restart`，便于商业版售后追踪。


## Enterprise SaaS Commercial Development Plan (2026-06-30 baseline)

### Product position
- Build this as a multi-tenant SaaS product, not a single-machine personal script.
- Customer-facing UI must expose business workflows: enterprise login, account authorization, asset preparation, queue trial run, finder leads, support receipts.
- Backend owns cookies, node sessions, retry state, queue state, audit evidence and customer-safe messages.

### Tenant and permission model
- Every customer company is an org. Accounts, materials, queues, tasks, knowledge docs, leads, audit logs and support cases must be isolated by orgId.
- Roles: owner/admin/member/auditor. Members see business actions; admins see nodes, quotas, authorization and receipts; auditors are read-only.
- Critical actions must write audit logs: authorization restart, queue recovery, batch preflight, material import, task retry, support-case closure.

### Customer workflow priority
1. Customer startup center: one page tells the customer whether the workspace can start and what to do next.
2. Account authorization: customer scans QR or completes SMS verification; the product never asks them to handle cookies.
3. Publish queue: customer sees asset, account, status, preflight and recovery advice instead of script logs.
4. Finder center: product keyword drives video search and comment analysis; users should not manually paste links as the main path.
5. Customer success: every failure can produce a receipt with evidence id, reason, owner role and next action.

### Engineering phases
- P2: wrap current capabilities into enterprise workflows: startup receipt, auth recovery, queue recovery, low-frequency trial run, audit loop.
- P3: migrate data to SQLite/PostgreSQL with org/user/account/material/queue/task/audit/support schema and migration scripts.
- P4: commercial node-pool scheduling: quota, assignment, capacity slots, cooldown, failure isolation, health dashboard.
- P5: plans and billing: accounts, nodes, daily tasks, finder quota, AI usage, support SLA.
- P6: customer self-service operations: session timeline, delivery package, webhook alerts, import/export.

### Current implementation rules
- No new feature should be local-only. It must go through central API, orgId isolation, role permission, audit evidence and business-facing UI wording.
- Real external actions default to low frequency, preflight, receipt and human-visible confirmation.
- Every batch must pass: backend py_compile, frontend script check, question-mark encoding check, remote smoke test and key-string verification.

## P2.43 Queue Recovery Advice (implemented)

- Backend added `/api/publish/queue/recovery-advice`, aggregating queue state, material readiness, account authorization handoff and batch-preflight preview.
- Customer startup center now receives `queueRecovery`, so auth completion can flow into queue recovery guidance.
- Publish queue UI now shows a Queue Recovery Advice card with queue count, actionable count, ready count and blocked count.
- Actions are converted into customer-facing buttons: handle authorization, batch preflight, repair queue, export preflight, upload assets, browse assets.
- Product goal: the customer follows the next button and does not need to understand scripts, cookies, nodes or queue status codes.


## P2.44 Startup Center Queue Recovery Exposure (implemented)

- Customer startup center now renders queue recovery status directly inside the startup card.
- The sub-card uses `queueRecovery` from `/api/enterprise/customer-startup` first, then falls back to the queue recovery advice state.
- It shows recovery status, message, four recovery metrics and up to three next-action buttons.
- Actions reuse the same queue recovery dispatcher as the publish queue page, so behavior stays consistent across customer startup and autopub modules.
- Product goal: a customer can enter the enterprise center and see the next queue step without navigating to publish queue first.


## P2.45 Commercial Readiness Check (implemented)

- Backend added `/api/enterprise/commercial-readiness` for tenant launch readiness.
- The endpoint checks tenant boundary, enterprise roles, node pool, account authorization, asset readiness, queue recovery, audit evidence, plan quota and customer startup state.
- It returns status, score, cards, checks and nextAction without exposing cookies, tokens, SMS codes or node secrets.
- Enterprise center now loads this endpoint and renders a Commercial Launch Check card for admins and customer-success operators.
- Product goal: before a customer goes live, the team can see one business checklist instead of reading scattered script and server state.


## P3.0 Data Layer Migration Baseline (implemented)

- Added `migrations/001_enterprise_core_schema.sql` as the first enterprise database schema baseline.
- Tables cover organizations, users, memberships, nodes, accounts, materials, publish queues, central tasks, audit logs, support links, finder leads, knowledge docs and cloud login sessions.
- Added `migrations/export_state_to_sqlite.py` to export the current JSON scheduler state into a SQLite preview database without mutating production.
- Local smoke test exported the current state into `migrations/matrixship-preview.db` successfully.
- Product goal: prepare the commercial version for durable multi-tenant storage while keeping the current JSON runtime stable until table-by-table cutover.


## P2.46 Cloud Login Session Watchdog (implemented)

- Backend added `/api/cloud-login/session-watchdog` to aggregate cloud login sessions into a customer-safe reliability status.
- It classifies active, stale, failed, closeable and resumable sessions and returns cards, nextAction and action buttons.
- Enterprise center now loads the watchdog and renders it at the top of the Login Session Operations area.
- Operators can continue authorization, start a new authorization or clean stale/failed sessions from a single card.
- Product goal: login authorization should feel like a managed enterprise workflow, not manual browser/session debugging.


## P2.47 Publish Queue Scheduler Watchdog (implemented)

- Backend added `/api/publish/queue/watchdog` as a read-only queue scheduler reliability summary.
- It detects pending, running, stalled, failed and completed queue items, plus publish task pressure and online node availability.
- Autopub now loads this endpoint and renders a Queue Scheduler Watchdog card before queue authorization/recovery details.
- Actions reuse existing batch preflight, repair and export flows, so the watchdog gives guidance without mutating queue state by itself.
- Product goal: queue reliability should be visible to customers and operators as business status, not hidden in worker logs.


## P3.1 SQLite Persistence Mirror (implemented)

- `central_server.py` now mirrors bounded JSON runtime state into `central_data/matrixship_mirror.db` after `persist()`.
- Mirror failure is non-blocking: JSON remains the source of truth and business operations continue even if SQLite write fails.
- Mirrored domains include organizations, users, memberships, nodes, accounts, materials, publish queue, central tasks, audit logs, support links, finder leads, knowledge docs and cloud login progress.
- Backend added `/api/enterprise/persistence-health` with optional `refresh=1` to force a mirror refresh and report table counts, DB size and last mirror state.
- Enterprise center now shows a Data Persistence Mirror card, so admins can verify durable storage readiness from the frontend.
- Product goal: prepare commercial multi-tenant persistence without risky runtime cutover; next step is table-by-table read/write migration.

## P3.2 Durable Audit Persistence (implemented)

- `add_audit()` now persists audit events immediately after they are appended, so customer operations, support actions and system decisions survive process restarts.
- JSON remains the runtime source of truth; audit persistence failure is isolated and does not block the business operation that produced the audit event.
- SQLite mirror writes are throttled by `CENTRAL_SQLITE_MIRROR_MIN_INTERVAL_SEC` to avoid adding database overhead to every audited request.
- The persistence health endpoint still supports `refresh=1` for operator verification and database count reconciliation.
- Product goal: every customer-visible action should have durable evidence without turning the current JSON runtime into a risky big-bang database migration.

## P2.48 One-click Authorization Recovery (implemented)

- Backend added `/api/accounts/authorization-recover` as a customer-facing recovery command on top of the lower-level session close/restart primitives.
- The command selects the stale/failed authorization session for the account, generates a recovery id, returns a new login handoff URL and records audit evidence.
- `/api/cloud-login/session-watchdog` now exposes a primary `recover_authorization` action before raw cleanup, so customers see a business action instead of session internals.
- Frontend Watchdog actions can call one-click recovery, open the customer authorization page and keep polling the authorization watch path.
- Product goal: login recovery should be a self-service enterprise workflow with evidence id, not a support-only manual script operation.

## P2.49 Cloud Login Command Receipts (implemented)

- Central dispatch now adds `centralTaskId`, `dispatchNodeId`, `dispatchPath`, `dispatchStatus` and `receiptId` to cloud-login command responses.
- The Douyin authorization page renders command receipts for click, type, key, refresh and receive-SMS operations.
- Receive-SMS failures now show whether the node task ran, which node handled it, which click method was used and whether a text target was matched.
- Several legacy mojibake messages on the authorization page were replaced with stable Unicode-escaped Chinese strings.
- Product goal: customers and support can tell the difference between ?button was not sent?, ?node did not respond? and ?node ran but did not find the SMS option?.

## P2.50 Customer Entry Login Guard (implemented)

- The default customer entry now shows a clear enterprise login guard when no enterprise user session exists.
- The guard explains tenant isolation, customer-side authorization and cloud-node execution before exposing operational workflows.
- Existing module-level permission checks remain in place; non-enterprise modules still redirect unauthenticated users back to the enterprise/login area.
- Product goal: customers who only receive the URL understand they must log in first and do not confuse the SaaS frontend with a single-user local script.

## P2.51 Customer Workspace Provisioning (implemented)

- Backend added `/api/enterprise/workspace/provision` for commercial customer onboarding.
- The endpoint creates or updates the customer organization, owner user, owner membership and default delivery configuration in one audited operation.
- It returns a one-time delivery payload containing login identifier, initial password, orgId, login URL and next actions.
- Enterprise center now exposes a one-click customer workspace form and a delivery card with copy/open-login actions.
- Product goal: onboarding a new paying customer should be a repeatable SaaS workflow, not a sequence of internal admin scripts.

## P2.52 Customer Workspace Archive (implemented)

- Backend added `/api/enterprise/workspace/archive` to archive customer workspaces without deleting historical evidence.
- Archiving sets the organization to `archived`, archives memberships and can disable users that only belonged to that workspace.
- Enterprise customer list now exposes an archive action for admins, excluding the default workspace.
- Product goal: commercial operations need a reversible stop-service path for test customers, churned customers and migrated customers.

## P2.53 Enterprise User Lifecycle (implemented)

- Backend added `/api/enterprise/users/reset-password` for audited password reset and one-time credential delivery.
- Backend added `/api/enterprise/users/status` for disabling and restoring members; disabling revokes active sessions immediately.
- Enterprise user list now exposes reset password and disable/restore actions for admins.
- Reset credentials reuse the delivery card so customer success can copy a clean handoff payload.
- Product goal: customer staff changes can be handled from the SaaS UI without editing JSON, database rows or scripts.

## P2.54 Customer Self-service Password Change (implemented)

- Backend added `/api/auth/change-password` for session-authenticated enterprise users.
- The endpoint verifies the current password, enforces an 8-character minimum, updates the password hash and revokes other active sessions for the same user while keeping the current session alive.
- Every attempt is audited through `auth.change_password` without recording password material.
- The customer entry header now exposes a `Change password` self-service flow for normal enterprise sessions, with inline validation and customer-safe success/error messages.
- Product goal: customers can manage their own account security without asking the platform owner to reset credentials or edit server state.

## P2.55 Initial Password Change Prompt (implemented)

- Workspace provisioning and admin password reset now mark delivered credentials with `passwordChangeRequired=true` by default.
- Self-service password change clears `passwordChangeRequired` and returns the updated public user object to the frontend.
- The customer frontend automatically opens the password-change panel after login or session restore when an initial/reset password is detected.
- Product goal: delivered credentials are treated as temporary handoff credentials, moving account security ownership to the customer immediately after first login.

## P2.56 Customer Session Security Center (implemented)

- Backend added `/api/auth/sessions` for session-authenticated users to list their own active enterprise-login sessions.
- Backend added `/api/auth/sessions/revoke-others` to revoke every other session for the same user while keeping the current session alive.
- Revocation is audited through `auth.sessions.revoke_others` and never exposes tokens.
- The customer account security panel now shows active sessions, current/other labels, IP/user-agent hints and one-click revoke-other-session action.
- Product goal: customers can contain account sharing, lost devices and staff handoff risks without asking the platform owner to edit server state.

## P2.57 Enterprise Security Audit View (implemented)

- Backend added `/api/enterprise/security-audit` as an enterprise-facing aggregation endpoint for login, account security, authorization and workspace operation events.
- The endpoint enforces tenant/RBAC boundaries, supports time range, category and keyword filters, and returns customer-safe cards, counts, top actors/actions and normalized rows.
- Failed login attempts can be correlated back to the tenant when the identifier belongs to a tenant member, without exposing passwords, session tokens, cookies or browser profiles.
- Enterprise center now renders a Security Audit card with category tabs, keyword search and CSV export for customer admins/auditors.
- Product goal: customer administrators can answer "who logged in, who changed account security, and what authorization actions happened" from the frontend instead of asking support to read server logs.

## P2.58 Enterprise Member Invite Links (implemented)

- Backend added an `enterpriseInvites` state bucket and invitation token hash storage; full invitation tokens are only returned at creation time.
- Backend added `/api/enterprise/invites/create`, `/api/enterprise/invites`, `/api/enterprise/invites/verify` and `/api/enterprise/invites/accept`.
- Invitation creation is restricted to tenant admins/owners, while verification and acceptance are public-by-token and never expose admin sessions, cookies or node secrets.
- Accepting an invitation creates or binds the enterprise user, attaches the membership role, creates a normal user session and marks the invitation as accepted so it cannot be reused.
- Existing user protection prevents anonymous invitation acceptance from resetting an already-passworded account without the current password.
- Enterprise center now has a customer-facing member self-service invite card with link generation, copy/open actions and recent invite status rows.
- Added `/join-enterprise.html` for employees to set their own password and join the tenant from the invite link.
- Product goal: customer teams can expand their own workspace through controlled invite links instead of asking the platform owner to manually create every user.

## P2.59 Enterprise Invite Revocation (implemented)

- Backend added `/api/enterprise/invites/revoke` for tenant admins/owners to revoke active or expired invite links.
- Revocation is tenant-scoped and audited through `enterprise.invite.revoke`; accepted invitations cannot be retroactively revoked and must be handled through member disable/restore controls.
- Enterprise center invite rows now expose a revoke action only for active invitations and refresh the invite list after operation.
- Product goal: customer administrators can safely recover from mis-sent invitation links without contacting platform support or editing backend state.

## P2.60 Customer Session Renewal and Expiry Visibility (implemented)

- Backend now returns `expiresInSec` and `sessionTtlSec` on `/api/auth/me`, `/api/auth/refresh` and `/api/auth/sessions` rows.
- Frontend customer entry shows the active enterprise session remaining time beside the logged-in user and inside the account security panel.
- Users can manually renew the current session from the UI; the existing `/api/auth/refresh` endpoint remains the single renewal path and does not expose tokens in page text.
- Frontend runs a lightweight session maintenance timer: expired sessions are cleared locally, and sessions with less than 12 hours remaining are renewed automatically.
- Product goal: business users should not lose work because a hidden enterprise session expired, and support can see whether the browser is authenticated without reading localStorage.


## P2.61 Publish Queue Operation Receipts (implemented)

- Backend queue cancel, retry and detail endpoints now return a customer-facing operation receipt with receiptId, latestEventId, queue status, summary, next action and recent queue events.
- Failed retry/cancel paths also return receipts, so support can diagnose blocked operations without asking users to reproduce ambiguous browser behavior.
- Frontend publish queue now shows an operation receipt card after cancel, retry or detail actions, with copy-to-clipboard support for customer-service handoff.
- Product goal: queue operations become auditable SaaS actions instead of one-person script button clicks; customers and support share the same receipt evidence.


## P2.62 Publish Queue Receipt Lookup (implemented)

- Frontend publish queue now includes a receipt/queue ID lookup control next to queue operations.
- The lookup reuses the queue detail endpoint, so customer support can paste a copied receiptId/latestEventId and open the same receipt card without reading backend logs.
- Product goal: copied operation receipts become a practical customer-service workflow, closing the loop from customer-visible error to support investigation.


## P2.63 Unified Task Center Customer Rows (implemented)

- Backend task serialization now adds customer-facing operation fields: operation key/label, business title, status hint, primary resource, queue/task receiptId, latestEventId, next action label and support reference.
- Enterprise task-center summary rows now reuse the same customer fields, so the enterprise overview and the full task center describe the same task in the same language.
- Frontend task rows now show business title, status guidance and receipt instead of exposing internal API path as the primary label.
- Task rows include copy-to-clipboard receipt output for customer support handoff, while retaining detail/retry/cancel controls under existing RBAC.
- Product goal: customers can understand "what is happening, what evidence should I send to support, and what can I do next" without knowing backend routes or node internals.


## P2.64 Task-Center Authorization Repair Entry (implemented)

- Backend task serialization now promotes `repairAction` so the frontend can route account-authorization failures by structured metadata instead of parsing error strings.
- The task-center primary action button now opens the authorization repair path for account-auth failures: if an account is known it opens the account maintenance login page; otherwise it opens the enterprise authorization repair wizard.
- Auditor roles are kept read-only: clicking an authorization repair task opens details and shows a no-permission message instead of launching a login/repair flow.
- Other task types continue to open task detail, preserving existing retry/cancel controls.
- Product goal: failed authorization tasks become guided customer recovery flows rather than support-only diagnostics.


## P2.65 Task Detail Customer Receipt CTA (implemented)

- Task detail now shows a customer-facing summary card above raw JSON: business title, status hint, receiptId and the next action CTA.
- The summary CTA reuses the same structured task routing as the task-center row, so authorization failures can be repaired from detail views opened by notifications, search, receipts or support links.
- Task detail now includes a copyable detail receipt with taskId, receiptId, latestEventId, queueId, operation, status, next action, repair action, node and error.
- Existing failure explanation and CSV trace export remain available for support and operations staff.
- Product goal: every task detail view is self-service and support-ready, not just a raw backend diagnostic panel.


## P2.66 Task Receipt Search and Auto-Locate (implemented)

- Backend task search now indexes customer-facing task fields including receiptId, latestEventId, operation label, business title, status hint, repair action and support reference.
- Task search now accepts normalized `task:<id>` and `queue:<id>` references in addition to raw taskId, queueId and queue latest event IDs.
- Task detail lookup now accepts `task:<id>` receipts directly.
- Frontend task search copy now explicitly tells users they can paste task receipts, queue receipts and latestEventId values.
- When task search returns a single match, the frontend automatically opens task detail; empty results explain whether the user should use task-center search or the publish-queue receipt lookup.
- Product goal: support and customers can paste the evidence they already copied and land on the correct task without knowing backend identifiers.


## P2.67 Finder Discovery Task Receipt (implemented)

- Synchronous central task dispatch now returns `taskReceiptId` and `latestEventId` for completed, failed and accepted-waiting tasks.
- Finder auto-discovery stores this receipt in the latest finder job card, alongside video/comment/lead counts and execution node information.
- Finder job cards now expose copyable discovery receipts, so customer support can locate the exact discovery run from the task center.
- The "查看任务" action now navigates by receipt when available, reusing task-center receipt search and detail lookup.
- Product goal: product-keyword discovery is a traceable enterprise task, not a silent one-off scrape button.


## P2.68 Outreach Task Receipt (implemented)

- AI outreach runs now store the returned central task id, task receipt, latest event id, node id, keyword and outcome counts in the frontend state.
- The outreach panel now shows a customer-facing receipt card after a run, with actions to open the task center detail or copy the receipt.
- Outreach receipts include scanned video count, target count, sent count, status, node and error summary for support handoff.
- Failed central calls also create a local failed job state so the UI does not silently lose the execution context.
- Product goal: AI outreach sending/preview actions become auditable enterprise tasks rather than opaque button clicks.
