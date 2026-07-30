# Changelog

## 2026-07-30 抖音全自动回复复用账号矩阵登录态
### Fixed
- 获客中心进入“私信 / AI 销售”时会同时带入当前选择的抖音账号；全自动收信轮询与后续自动发送使用同一个 `accountId`，避免多账号场景下收信和回复落到不同账号。
- `/api/douyin/dm/inbox` 新增可选 `accountId`。本地收件浏览器会解析对应账号矩阵 profile，以该 profile 播种稳定的 `dy_dm_profile/current`，并在打开客户主页前补充注入该账号 Cookie 缓存，不再依赖未登录的通用 profile。
- 自动收件 Cookie 诊断只返回 `attemptedCount`、`addedCount` 和异常类型，结构化日志只记录账号 ID 与数量，不记录 Cookie、Token、Authorization 或私信正文。

### Verification
- TDD 新增账号传递、浏览器 profile 播种、Cookie 注入顺序和脱敏诊断回归；私信专项通过 54/54，获客页面通过 9/9，OpenAPI 契约通过 5/5，相关 Python 文件语法检查通过。

### Operations
- 本次修改原生客户端、本地执行引擎和本机接口契约；不涉及中心服部署、数据库、Docker 或 SQL 迁移，`migration.sql` 保持 no-op。代码生效需要重启本地客户端和本地执行引擎。
- 回滚时恢复 `backend/matrix_native_client.py`、`backend/api_server.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`tests/test_douyin_dm_auto_reply.py`、`tests/test_openapi_contract.py` 及本次文档即可恢复旧行为。

## 2026-07-30 账户中心账单看板发布门禁
### Added
- 新增本机账单性能冒烟：固定 200 请求、20 workers、逐响应运行时 JSON Schema 校验，正常 30 天查询 P95 门槛为 800 ms。
- 新增 100 请求发布监控与回滚门禁：错误率严格大于 1% 才选择上一稳定中心服镜像，Tag 使用严格正则校验；dry-run 不调用 Docker。

### Operations
- 记录已提交 Git SHA、Tasks 1-5 预任务源码快照 SHA-256 和当前工作区源码哈希，并明确区分源码恢复证据与可部署镜像/客户端包。
- `backend/Dockerfile`、`docker-compose.prod.yml` 拓扑和 `/api/health` 保持不变；`jsonschema==4.23.0` 在本地与部署 requirements 中保持同一锁定。
- 本发布无数据库 DDL/DML，`migration.sql` 只追加 no-op 追溯说明。生产上线前必须登记上一稳定镜像 Tag 与客户端包 SHA-256；错误率超过 1% 时按门禁回滚。

## 2026-07-30 抖音私信真实按钮标签与登录 Cookie 恢复修复
### Fixed
- 客户主页私信按钮的 `innerText/textContent` 同时返回时，标签可能变成“私信 私信”；按钮校验现在接受同一私信文案的重复结果，同时继续拒绝“回关 私信”“关注”等相邻操作，修复真实私信按钮被误判为 `dm_button_not_found`。
- 私信临时浏览器不再只依赖 profile 文件副本恢复登录态；打开客户主页前会从当前账号矩阵账号的本地缓存补充注入抖音 Cookie，并跳过易失效的 `msToken`。诊断只记录尝试数和成功注入数，不记录 Cookie 内容。
- 客户端仅在 `saveLoginPrompt.finalPromptVisible=true` 时提示“保存登录信息弹窗仍可见”，避免弹窗已关闭或本次未出现时继续误报。

### Verification
- 真实浏览器使用当前账号矩阵账号打开指定客户主页，成功自动关闭保存登录信息弹窗、点击 Edge 私信按钮、打开会话并发送“你好”；抖音消息发送接口返回 HTTP 200。
- 私信发送、收信、客户端提示和脱敏日志相关测试通过 47/47，相关 Python 文件语法检查通过；完整测试文件中依赖中心服务导入的 2 项仍被工作区既有 `backend/central_server.py#L10012` 缩进错误阻断。

### Operations
- 本次只修改本地抖音私信发送适配、客户端错误提示、私信回归测试和文档；不涉及中心服接口、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_dm_auto_reply.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为；代码生效需要重启本地客户端和本地执行引擎。

## 2026-07-30 抖音私信保存登录信息弹窗关闭增强
### Fixed
- 私信发送打开客户主页前，会在临时浏览器 profile 里关闭 Chrome/Edge 保存密码气泡，并追加 `--disable-save-password-bubble`，减少浏览器级提示遮挡页面。
- 抖音页面弹出“是否保存登录信息？”时，发送链路不再只识别“保存/取消”，现在会优先点击“以后再说 / 暂不保存 / 不保存 / 暂不 / 关闭 / 跳过 / 稍后 / 稍后再说 / 下次再说”等关闭类按钮；若页面模拟点击无效，会用真实鼠标坐标再点一次。
- 如果保存登录信息弹窗仍挡住客户主页导致 `dm_button_not_found`，浏览器会默认短暂停留 20 秒，客户端提示会说明需要手动点掉弹窗后重试，避免窗口立即关闭无法排查。

### Operations
- 本次只修改本地抖音私信发送适配、客户端错误提示、私信回归测试和文档；不涉及中心服接口、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_dm_auto_reply.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为；代码生效需要重启本地客户端和本地执行引擎。

## 2026-07-30 同款替换 Seedance 素材安全降级
### Fixed
- 漫剧视频生成阶段不再重复提交人物、场景、产品等补充参考图，只保留当前片段首帧和尾帧，降低水印、密集 Logo、电子屏幕文字和促销海报在视频模型阶段触发安全策略的概率。
- Seedance/Ark 返回 `InputImageSensitiveContentDetected.PolicyViolation` 或 `copyright restriction` 时，不再直接把片段判死；系统会提示“素材版权/品牌风险”，并切换到 Vidu Q3 等备用模型继续生成。
- 上传素材预检增加水印、百度百科/平台来源、抖音/小红书截图边框、电子屏幕大段文字、促销海报、第三方品牌和 Logo 过密检查；自有门店 Logo 允许 warning 通过，但会提示用户拍得更干净。

### Operations
- 已失败的旧同款替换任务需要重试失败片段或重新创建任务。本地客户端重启后生效；线上漫剧服务如仍使用旧代码，需要单独部署并重启远程服务。
- 本次不改数据库、OpenAPI、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`.tmp-aicanvas-server-current.py`、`.tmp-aicanvas-server.py`、相关测试和文档即可恢复旧行为。

## 2026-07-30 抖音私信按钮点击误判修复
### Fixed
- 私信发送进入客户主页后，不再只按固定 XPath 命中就点击；程序会先读取按钮文本/可访问标签，确认确实是“私信 / 发私信 / 发消息”后才点击，避免在关注状态不同的主页上把“回关”等相邻按钮当成私信按钮。
- 抖音弹出“是否保存登录信息？”时，发送链路会先自动点击“保存”并等待弹窗消失，再继续查找主页私信按钮；失败诊断新增 `saveLoginPrompt`，避免弹窗遮挡主页导致 `dm_button_not_found` 后浏览器立即关闭。
- 自动点击私信按钮改为多段尝试：先滚动到按钮并做普通点击，再用真实鼠标坐标点击兜底，最后再尝试 DOM 事件点击；每次尝试都会记录 `clickAttempts` 和坐标，避免“代码说点了但页面没反应”时无法追溯。
- 点击后私信面板判断改为必须出现“收起会话 / 发送消息 / 输入消息 / 确认聊天”或真实可编辑输入区等强信号；页面上单独存在“私信/消息”文字不再被误判为面板已打开。
### Operations
- 本次只修改本地抖音私信发送适配、私信回归测试和文档；不涉及中心服接口、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。回滚 `backend/api_server.py`、`tests/test_douyin_dm_auto_reply.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为；代码生效需要重启本地客户端和本地执行引擎。

## 2026-07-30 Agent.模式视频上传图片全部作为参考图
### Changed
- `Agent.模式` 图片模式保持原规则：第 1 张上传图片是待修改图，第 2 张起是参考图。
- `Agent.模式` 视频模式改为：所有上传图片都作为视频生成参考图，界面标签显示为“参考图1/参考图2/...”，不会再把第 1 张图当作待修改图。
- 切换图片/视频模式时，上传区提示和已上传图片标签会同步刷新，视频生成提示词也会明确告诉模型“没有待修改图”。
### Operations
- 本次只修改本地客户端、Agent 模式回归测试和文档；不涉及中心服、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧规则；代码生效需要手动重启本地客户端。

## 2026-07-30 资产库删除文本资产分类
### Changed
- 资产库顶部删除“文本”分类；导入资产只接受图片和视频，不再导入 `.txt/.md/.csv/.json/.log` 作为独立资产。
- 历史 `kind=text` 资产记录会在资产库加载时从资产库索引中清理；不主动删除磁盘上的文本文件。
- 自动化工作流的脚本/分镜文本不再作为独立“文本资产”入库；采集参考视频仍会绑定对应拆解文本，视频卡片里的“文本”按钮保留。
### Operations
- 本次只修改本地客户端、资产库/工作流回归测试和文档；不涉及中心服、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`tests/test_workflow_resilience.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧文本资产分类；代码生效需要手动重启本地客户端。

## 2026-07-30 获客中心使用账号不再空白
### Fixed
- 获客中心进入“寻找线索 / AI 触达”时会主动刷新当前子页账号列表；切换子 Tab 也会刷新，不再因为外层页面未转发 `on_show()` 导致“使用账号”保持空白。
- “使用账号”下拉框新增“正在读取账号...”和“账号加载失败，请刷新账号矩阵”状态，账号接口异常时会有明确提示并写入脱敏结构化日志。
- 本地抖音账号清单 JSON 损坏时，会从 `douyin_accounts/<账号ID>/auth_cookie.json` 和 profile 目录重建最小账号索引，避免已登录账号因为索引文件损坏而全部消失。
### Operations
- 当前 `backend/datas/accounts/boss/douyin_accounts.json` 已用 Python JSON 解析确认可读，本机账号接口可返回 2 个在线抖音账号。代码生效需要重启本地客户端。
- 本次只修改本地客户端、本地执行引擎账号读取、回归测试和文档；不涉及中心服接口、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。回滚相关代码和文档即可恢复旧行为。

## 2026-07-30 自动化工作流参考视频拆解文本可读性优化

### Changed
- 采集参考视频的文本拆解从横向 Markdown 表格优化为镜头卡片式文本，按“镜头 / 画面 / 台词 / 节奏 / 可借鉴点”分行展示。
- 视频理解提示词明确禁止输出 Markdown 表格；如果上游模型仍返回表格，客户端保存前会自动转换成可读卡片格式。

### Operations
- 仅修改本地客户端、工作流回归测试和文档；不涉及中心服接口、数据库结构、OpenAPI、Docker、环境变量或 `migration.sql`。
- 历史已保存的旧拆解文本不会自动改写，新运行的采集参考视频拆解会使用新格式。

## 2026-07-30 资产库按时间分组

### Changed
- 本地资产库改为按创建日期分组展示，同一天的资产放在同一组；列表按最新时间优先排序。
- 日期标题显示“今天”“昨天”或具体日期，资产卡片在标题下方显示具体时间，便于区分同一天导入或生成的素材。

### Operations
- 新写入的资产增加 `createdAt` 数值时间；历史资产继续兼容原 `ts` 字符串和文件修改时间。
- 本次只修改本地客户端资产库、源码契约测试和文档；不涉及中心服、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧的平铺资产列表；代码生效需要手动重启本地客户端。

## 2026-07-30 同款替换预览、漫剧视频扣费与自动声音合成门禁

### Changed
- 视频预览按源视频宽高比显示，竖屏保持竖屏、横屏保持横屏，窗口最大占可用屏幕 82%；表格刷新和播放结束不关闭弹窗，用户手动关闭时才释放播放器。
- 初次视频生成和单段视频重生成在提交前读取漫剧模型价格，按模型计费方式和片段时长从当前本地账户扣费；账户中心流水显示项目/模型、项目片段详情、变动和余额。
- 漫剧自动声音模式的最终合成只检查片段完成、人工确认、本地视频有效和真实音轨；历史音频或视觉质检状态不再误拦截已经确认的可用视频。

### Fixed
- 模型提交或远程等待失败按唯一扣费引用退款；远程生成已成功但本地下载失败时保留实际模型成本，恢复下载不重复扣费。
- 修复竖屏视频被横向裁切、预览随表格单元格销毁以及自动声音片段被旧 `audioStatus/qcStatus` 阻断的问题。

### Operations
- 扣费、退款、预览和合成门禁均保留脱敏结构化日志与任务 JSON 快照。远程公开价格接口暂未提供计费方式和档位配置，客户端优先读取明确字段，缺失时按描述、provider 和模型标识推断；远程若启用非 1 档位系数或不同价格的备用模型结算，需先扩展公开价格/结算契约。
- 仅修改本地客户端、同款替换测试和文档；无中心服、远程漫剧服务、数据库、OpenAPI、Docker、环境变量或 `migration.sql` 变更。回滚这些本地文件即可恢复旧行为；本次不自动重启本地客户端。

## 2026-07-30 自动化工作流采集参考视频全量入库与文本拆解

### Changed
- 自动化工作流采集步骤从“只下载 Top1”改为按 `topN` 下载本次采集到的视频；采集视频仍只进入资产库“采集参考视频”，不会进入发布队列。
- 入库步骤会为每个采集参考视频生成并绑定拆解文本，日志中的 `文本 x/y` 现在包含参考视频拆解文本数量。

### Added
- “采集参考视频”资产卡片新增“文本”入口，可查看对应视频的分镜/台词/节奏拆解。
- 文本弹窗新增“用此文本生成视频”按钮，跳转到 `Agent.模式` 并预填视频生成提示词，用户基于拆解文本重新生成原创视频。

### Operations
- 仅修改本地客户端、回归测试和文档；不涉及中心服接口、数据库结构、OpenAPI、Docker、环境变量或 `migration.sql`。
- 回滚 `backend/matrix_native_client.py`、`tests/test_workflow_resilience.py`、`tests/test_asset_library_shared_button.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和本文件即可恢复旧行为。

## 2026-07-30 小红书登录态失效提示改为明确原因
- 小红书采集、下载、图文同款、视频分解和获客/工作流相关本地任务遇到 `xhs_login_required` 时，统一提示为“账号已存在，但登录态已失效。请到账号矩阵重新登录该平台账号后再采集。”
- 该提示用于区分“账号矩阵有账号记录”和“本机 Cookie/profile 仍有效”两件事，避免用户误以为账号矩阵数据丢失。
- 本次只修改本地客户端文案、回归测试和文档；不涉及中心服、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。回滚本地客户端和测试/文档即可恢复旧提示。

## 2026-07-30 同款替换重生、动态时长和素材约束

### Changed
- 漫剧项目按最终口播稿估算视频时长，单段口播最长 15 秒；超长口播按标点无损拆成连续片段并重新压紧时间轴。
- 项目、首尾帧和视频请求显式携带人物、场景、道具分类参考图；上传素材优先于原片冲突实体，原片仅保留动作、镜头、站位和节奏信息。
- 视频列改为窗口化清晰预览，支持播放、进度和音量，关闭时释放独立播放器，不再全屏或移动表格播放器。

### Fixed
- 首帧、尾帧和视频重生按钮在任务忙碌时仍可点击并显示“当前任务正在处理”，不再表现为无响应。
- 重生请求、接受、完成和失败均输出脱敏结构化日志；失败保留旧媒体并记录错误编号。

### Operations
- 仅修改本地客户端、回归测试和文档；无中心服、远程漫剧服务、数据库、OpenAPI、Docker、环境变量或 `migration.sql` 变更。
- 回滚上述本地文件即可恢复旧行为。按用户要求，本次不自动重启本地客户端，由用户手动重启后生效。

## 2026-07-30 自动化工作流支持删除
- 自动化工作流页面新增删除当前工作流入口，点击垃圾桶后会二次确认，再从当前账号的 `workflows.json` 删除该工作流配置并刷新“我的工作流”列表。
- 删除范围限定为工作流定义本身，不删除已生成素材、脚本、发布队列或 `wf_out` 文件；删除启用/定时工作流后，调度器不再执行该工作流。
- 本次只修改本地客户端工作流页面、回归测试和文档；不涉及中心服、数据库结构、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_workflow_account_scope.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和本文件即可恢复旧行为。

## 2026-07-29 同款替换内嵌媒体与分项重生成

### Added

- 漫剧片段的首帧、尾帧改为客户端内本地图片预览，视频列改为本地内嵌播放器；远程结果先鉴权下载并通过媒体校验，页面不再展示公网媒体链接。
- 首帧、尾帧和视频现在可分别重新生成。单独更新任一帧后，现有视频进入 `video_stale` 并显示待重新生成；“重新生成视频”只使用最新双帧、口播稿和声音设置生成视频，不隐式重生成图片。
- 单帧重新生成失败时，已存在且校验通过的旧视频仍可在视频列播放；接口契约同时兼容单任务 `action_flow` 和返回 `task_ids` 的双帧/多帧响应。
- 批量重试会跳过缺首帧或尾帧的片段并继续其他失败视频；远程已完成但本地下载失败的片段使用 pending 仅下载恢复，不重新提交模型、不重复计费。

### Fixed

- 修复受保护漫剧媒体使用裸下载导致 HTTP 401、远程生成成功却被误报失败的问题。401 最多刷新一次漫剧凭证并重试一次，失败状态明确区分为 `download_failed`。
- 声音模式改为显式契约：`auto` 保留 provider 生成视频自带声音，`tts` 使用当前口播稿和所选音色；历史同款替换声音字段兼容归一化为 `auto`，未传模式的漫剧网站保持 legacy TTS。直提与批量视频任务按 `auto/tts/legacy` 隔离重复任务，备用模型沿用对应原声或 TTS 重混行为。
- 最终合成只接受状态为 `done`、本地媒体复检通过且已完成人工审核的当前片段；`video_stale`、`download_failed`、缺失或损坏视频均阻断 concat。

### Operations

- 生成、凭证刷新、下载、媒体校验和播放器错误使用脱敏 JSON 结构化日志；保留任务 ID、片段和错误编号，不记录 Token、完整请求头或敏感媒体地址。
- 远程发布必须先备份并校验 SHA-256，原子替换 `server.py` 后只重启 `ai-canvas.service`，检查 active、8777 监听和登录；错误率大于 1% 或命中硬门禁时自动恢复上一稳定备份。本次无数据库迁移，不修改或执行 `migration.sql`。

## 2026-07-29 自动化工作流强制文本产物
- 自动化工作流改为只生成脚本/分镜/文案文本：新建工作流不再编排图片、视频、语音或发布步骤；历史工作流里的 `image/video/tts/publish` 运行时也会跳过，不调用模型、不扣费、不进入发布队列。
- 历史版本曾把工作流生成的 `.txt/.md/.csv/.json/.log` 文本产物以 `kind=text` 入库；该行为已被 2026-07-30“资产库删除文本资产分类”取代，后续文本只保留为工作流文件或采集参考视频的绑定文本。
- 定时工作流现在只生成文本文件，界面不再提示自动公开视频。本次不涉及数据库、OpenAPI、Docker 或 `migration.sql`，重启本地客户端后生效。

## 2026-07-29 抖音私信原页面浮层输入框识别
- 私信发送前新增账号矩阵登录态预检：先从 `accountId` 或最近可用抖音账号解析 `dy_profile/auth_cookie.json`，确认 profile 存在且 Cookie 有登录标记；不可用时直接返回 `not_authenticated`，不再弹出一个临时未登录浏览器让用户登录。
- 临时私信浏览器现在从解析出的账号矩阵 profile 播种登录态，而不是只依赖进程里的 `DY_PROFILE_DIR`；`/api/douyin/dm` 也会把 `accountId/account` 传入发送链路。
- 私信按钮点击改为优先使用客户主页操作区的精确 XPath：Edge `//*[@id="user_detail_element"]/div/div[2]/div/div[1]/div[3]/div[2]/button[1]`，Chrome `//*[@id="user_detail_element"]/div/div[2]/div/div[1]/div[3]/div[3]/div[1]/button[2]`，避免 `text=私信` 命中错位置。
- 点击私信后新增右侧私信面板确认：必须探测到“收起会话 / 发送消息 / 输入消息”等面板标志才进入输入框发送流程；否则返回 `dm_panel_not_open`，并带回实际点击的选择器。
- 修复私信发送仍提示 `dm_input_not_found`：客户主页点击“私信”后，现在会在原页面私信浮层里先点击底部“发送消息”区域，激活真正的聊天输入框，再填写用户在客户端输入的内容并点击发送。
- 后端 `browser_send_dm()` 现在遍历当前页面的所有 frame 查找私信编辑器，诊断里新增 `frameIndex/frameUrl/focusProbe`，可以区分“私信浮层没打开”“底部输入区未激活”“输入框在 frame 内”等情况；诊断不记录私信正文。
- 客户端发送失败提示优化：`not_authenticated` 会提示到账号矩阵重新登录抖音；`dm_input_not_found` 会显示“已点开私信，但没有识别到底部发送消息输入框”，并附带候选数量，方便继续排查。重启本地客户端和本地执行器后生效；本次不涉及数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 小红书采集默认复用账号矩阵本地登录态
- 内容采集页选择小红书时，搜索、笔记下载、图文同款下载、视频分解下载和评论发布现在默认携带 `guestMode=false/accountCollectionConfirmed=true`，优先使用账号矩阵已经登录并保存在本机的 `xhs_profile`。
- 后端小红书账号采集门禁新增本地登录态检查：账号模式请求如果没有可用 `xhs_profile`，直接返回 `xhs_login_required` 和 `needLogin=true`，避免账号矩阵显示账号但实际没有 Cookie 时误判为风控或空结果。
- 抖音多账号 Cookie/profile 机制保持原有逻辑，本次不迁移、不同步任何 Cookie 到中心服或其他设备；Cookie 仍只保存在当前登录用户的本机数据目录。
- 本次只修改本地客户端、执行引擎门禁、回归测试和文档；不涉及数据库迁移、OpenAPI、Docker 或 `migration.sql`。回滚这些文件即可恢复旧的游客优先采集行为。

## 2026-07-29 抖音私信 dm_child_failed returncode=0
- 修复私信发送提示 `后台浏览器进程失败:dm_child_failed returncode=0`：本地客户端启动时现在同时设置 `DY_DM_ISOLATED=0`，避免打包后的 `MatrixShipAgent.exe` 被当成 Python 解释器执行 `-c` 子进程脚本。
- 后端 `browser_send_dm()` 新增 Python 子进程命令检测；只有确认当前可用 Python `-c` 时才走隔离子进程，否则直接走当前进程浏览器发送逻辑。
- 子进程正常退出但没有输出 `__MATRIX_DM_JSON__` 时返回 `dm_child_no_json_marker`，客户端状态栏会提示“后台浏览器未返回发送结果”，便于区分运行环境问题和抖音页面发送问题。本次不涉及数据库、OpenAPI、Docker 或 `migration.sql`，代码生效需要重启本地客户端和本地执行器。

## 2026-07-29 本地客户端全局移除悬停黑框
- 本地客户端所有按钮、图片、素材卡片、表格项、登录选项、主题/退出和状态区域都不再弹出鼠标悬停黑框。
- 原本写在悬停提示里的说明不再通过黑框展示；保留页面内可见文字、按钮文案、状态栏和弹窗反馈。
- 新增全局回归测试，后续代码中不允许再添加非空 `setToolTip(...)`。本次只修改本地客户端显示、测试和文档，不涉及数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 小红书评论读取改为必须登录
- 内容采集页“小红书 -> 看评论”和获客中心“小红书寻客”不再从游客模式开始尝试，直接使用已登录小红书账号执行，并携带 `guestMode=false/accountCollectionConfirmed=true`。
- 本地接口 `/api/xhs/comments` 和 `/api/finder/discover` 的小红书评论读取默认改为账号模式；未确认账号采集会返回 `xhs_account_collection_unconfirmed`，确认后继续走小红书安全模式预检和计数。
- 搜索、下载、图文同款下载仍保持游客优先；本次只修改本地客户端、接口门禁、回归测试和文档，不涉及数据库、OpenAPI、Docker 或 `migration.sql`。重启本地客户端和本地执行引擎后生效。

## 2026-07-29 小红书图文同款图片悬停黑框移除
- 图文同款的原图缩略图和替换图片槽位不再弹出黑色悬停提示框，鼠标经过图片时不会遮挡画面。
- 点击原图查看、点击替换槽位选择图片的功能保持不变；本次只调整本地客户端显示和对应回归测试，不涉及数据库、接口或部署脚本。

## 2026-07-29 小红书游客采集登录弹窗自动处理
- 小红书游客采集打开网页后，如果出现“手机号登录 / 扫码登录 / 登录后推荐更懂你的笔记”等登录弹窗，系统会先自动尝试关闭一次，再继续搜索、读取评论或下载笔记。
- 小红书关键词搜索现在必须确认进入对应关键词搜索页，或捕获到搜索接口响应后，才会接受页面里的笔记卡片；游客模式停留在发现页/推荐流时不再把无关内容显示为搜索结果。
- 如果登录弹窗无法关闭，采集结果会明确返回 `xhs_guest_login_required`，客户端继续走已有“公开访问受限 -> 使用账号采集一次”的确认流程，不会静默切换登录账号。
- 本次只修改小红书采集适配器、回归测试和文档；不涉及中心服接口、数据库、OpenAPI、Docker 或 `migration.sql`。重启本地执行引擎后生效，回滚仍可设置 `XHS_GUEST_COLLECTION_DEFAULT=0` 或回退本次文件。

## 2026-07-29 企业家团队成员按钮刷新修复
- 企业中心团队成员页现在会在进入页面和收到成员数据回调时重新按当前角色刷新按钮显示状态，避免页面先按默认管理员角色创建后，企业家登录仍残留“添加企业 / 添加成员”按钮。
- 企业家界面只保留“刷新 / 邀请成员”，企业下拉选择也会隐藏；管理员仍显示“刷新 / 添加企业 / 添加成员 / 邀请成员”。
- 本次只修改本地客户端团队成员页、权限回归测试和文档；不涉及中心服接口、数据库结构、OpenAPI、Docker 或 `migration.sql`。重启本地客户端后生效。

## 2026-07-29 同款替换首尾帧云豆扣费
- 同款替换漫剧项目模式现在会在提交首尾帧图片前逐帧扣云豆，能力为 `comic_keyframe_image`，当前价格 `0.14` 云豆/帧，和 LK888 图片生成价格一致；首帧和尾帧会各产生一条可追溯流水。
- 首尾帧提交、等待、下载、结果缺失或取消失败时，会按已扣 `ref` 自动退款；首尾帧已经保存成功后，后续视频生成失败不再退图片费用。
- 中心服登记 `comic_keyframe_image` 为已知能力价格，避免客户端自报金额覆盖平台定价。回滚上述客户端、中心服、测试和文档文件即可；不涉及数据库结构、Docker、OpenAPI 路由或 `migration.sql`。

## 2026-07-29 同款替换删除原片主角预览与确认区
- 同款替换素材区域删除“暂无预览”主角预览框、右侧“漫剧项目模式：使用上传人物图作为角色参考”提示，以及“原片主角确认”下拉行，减少冗余操作。
- 低置信度原片主角识别不再依赖用户手动选择下拉框；如后端返回候选帧，客户端自动使用第一张候选帧作为主角锚定，避免删除 UI 后生成流程被卡住。
- 本次只修改本地客户端 UI、低置信度候选处理、回归测试和文档；不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-07-29 同款替换声音来源改为自动
- 同款替换“声音来源”下拉框移除“原片声音”，新增默认“自动”：不选择 AI 音色时，不生成 TTS、不上传配音、不回填原片音频，直接使用远程模型生成视频自带声音。
- 旧任务或旧字段里的 `source`、`origin`、`original`、`source_audio` 会兼容映射为 `auto`，避免历史任务报错；`tts` 和 `uploaded` 逻辑保持原用途。
- 非口播主角替换片段在 `auto` 模式下不再调用 `_replace_segment_audio_from_source()` 或 `_ensure_segment_audio(source_segment, ...)`；若 FaceFusion 输出丢音轨，只从本次生成的编辑视频回填，不使用原片声音。
- 漫剧项目模式允许 `auto` 作为默认声音来源；上传完整配音仍按原规则前置阻断。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/API_REFERENCE.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 同款替换操作列按钮紧凑化
- 同款替换片段表“操作”列不再使用 72px/92px 文本按钮，改为 30px 圆形图标按钮；“重生”使用循环箭头，“删除”使用垃圾桶，含义保留在悬停提示中。
- 漫剧项目模式下“重生 / 删除”两枚按钮居中排列，间距固定为 4px；普通替换模式下删除按钮也统一为 30px 图标，避免按钮过长或互相重叠。
- 本次只修改本地客户端同款替换表格按钮、回归测试和文档，不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py` 和文档即可恢复旧行为。

## 2026-07-29 获客中心线索表按钮完整居中
- 获客中心“寻找线索”动作列重新加宽：打开主页/复制链接列为 112px，去私信跟进/标记已跟进列为 140px；按钮分别为 92px/92px/118px/118px，避免中文按钮文字被裁切。
- 动作按钮从普通 `QPushButton/QToolButton` 改为表格专用可点击 `QLabel`，避开 Qt 原生按钮绘制边界；结果行高固定为 54px，按钮高度固定为 32px，动作单元格内部二次留白改为 0，保留表格自身 8px item padding 后仍能居中显示。
- 本次只修改本地客户端获客中心表格布局、对应回归测试和文档；不涉及中心服接口、数据库、OpenAPI、Docker 或 `migration.sql`。代码生效需要重启本地客户端。

## 2026-07-29 小红书默认游客采集与账号采集确认
- 小红书内容采集、笔记下载、读取评论、图文同款下载和获客中心寻客默认使用游客浏览器上下文，不再自动读取登录账号 profile、Cookie 或授权状态。
- 当公开访问受限时，客户端弹出“公开访问受限”确认框；只有用户点击“使用账号采集一次”才会以登录账号重试当前动作一次，并继续计入风控中心。
- 本地接口新增 `guestMode` 和 `accountCollectionConfirmed` 请求字段；未确认的账号采集会返回 `xhs_account_collection_unconfirmed`，确认后的账号采集仍执行小红书安全模式预检和记录。
- 新增结构化日志 `xhs_guest_collection_blocked` 和 `xhs_account_collection_confirmed`，只记录动作、错误码、关键词长度、URL 指纹和风控快照，不记录 Cookie、Token、完整 URL 或正文。回滚可设置 `XHS_GUEST_COLLECTION_DEFAULT=0` 后重启本地客户端和本地执行引擎；本次不涉及数据库迁移、新公共路由、Docker 结构或 `migration.sql`。

## 2026-07-29 Seedance 音频时长超限降级
- Seedance R2V 明确返回“音频时长超过模型上限”时，任务不再直接失败，改为退款后进入 Vidu Q3、万相 2.7、Kling V3 Omni、PixVerse V6 备用链。
- 只匹配该精确错误，分辨率和其他参数错误保持显式失败；备用请求移除不兼容音频字段，不截断用户口播稿。
- 真实项目 299 保留已成功片段 1、3，部署后只重生失败片段 2。无数据库迁移，本地客户端不自动重启。

## 2026-07-29 企业家团队成员页隐藏直接添加入口
- 企业家进入“企业中心 -> 团队成员”时，页头只保留“刷新”和“邀请成员”，不再显示“添加企业”和“添加成员”。
- 管理员仍保留“添加企业 / 添加成员 / 邀请成员 / 刷新”；普通用户仍不显示企业中心。
- 本次只修改本地客户端按钮可见性、角色权限回归测试和文档，不涉及中心服接口、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-07-29 抖音私信发送后台失败诊断
- 修复“发送失败:dm_child_failed”只显示外层失败、看不到真实原因的问题：后台临时浏览器子进程现在即使内部异常，也会返回 `dm_child_inner_exception`、异常类型、脱敏截断消息和 `stackTail`。
- 外层 `dm_child_failed` 结果补充 `returncode`、`stderrTail` 和 `stdoutTail`，便于区分浏览器启动失败、登录态/profile 失败、页面脚本异常或运行环境异常。
- 客户端发送失败状态栏不再只拼接外层 `error`，会优先显示后台浏览器异常摘要或 `dm_child_failed returncode`，便于用户下一次截图直接看到可排查信息。
- 本次只修改本地后端私信发送适配、客户端失败展示、私信回归测试和文档；不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。代码生效需要重启本地客户端和本地执行引擎。

## 2026-07-29 同款替换精确分镜项目初始化
- 新任务创建漫剧项目时直接写入本地已确认的片段数量、纯画面描述和最终口播稿，不再先建立空项目后让漫剧分析器二次扩写。
- 同款替换项目初始项目库保持为空，只由本地客户端上传的 1 个人物图、1 个场景图和 1 个道具图填充；普通漫剧项目继续原有分析和自动资产流程。
- 项目 298 仅保留为诊断证据，不再恢复或继续扣费。远程可通过部署前 `server.py` 备份回滚；无数据库迁移，本地客户端不自动重启。

## 2026-07-29 同款替换双帧表格与五模型降级
- 漫剧片段表改为“序号、口播稿、首帧图、尾帧图、视频、操作”，首尾帧缩略图后台加载，口播编辑框固定在单元格内。
- 本地同时等待并保存首尾两个图片任务，自动补全漫剧服务返回的 `/uploads/...` 地址；远程视频已存在时直接下载，不重复提交。
- Seedance 真人拒绝后按 Vidu Q3、万相 2.7、Kling V3 Omni、PixVerse V6 降级；已受理任务明确失败才切换，查询超时、502 和限流继续查询原任务。失败扣费逐次退款，任务响应保留完整降级历史。
- 本次不使用视频口型同步模型，不修改数据库、中心服或 OpenAPI。本地客户端不自动重启；远程发布前生成时间戳备份，错误率超过 1% 或出现重复计费时恢复备份并只重启 8777。

## 2026-07-29 小红书标题限制为 20 字
- 图文同款生成的三套方案标题统一限制在 20 字以内；AI 预填到“标题（必填）”里的标题也会压到 20 字以内。
- 素材发布标题栏提示改为“抖音最多30字，小红书最多20字”；实际点击发布时，抖音取前 30 字，小红书取前 20 字。
- 本次只修改本地客户端、图文同款标题生成规则和回归测试，不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/xhs_note_replacement.py`、`backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py`、`tests/test_native_publish.py` 和文档即可恢复旧行为。

## 2026-07-29 云豆改为 1:1 人民币口径
- 云豆计费统一改为 `1 云豆 = 1 元`：充值 `30 元` 到账 `30 云豆`，不再按旧口径到账 3000 云豆；新用户默认赠豆从 100 调整为 1，保持人民币价值不变。
- 中心服权威能力价格按旧价格除以 100：例如文案 `7 -> 0.07` 云豆、商品视频 `308 -> 3.08` 云豆、数字人 `2520 -> 25.2` 云豆；主库模式下按云豆金额直接乘 `MAINDB_YUAN_TO_POWER` 换算算力。
- 新增 `scripts/migrate_yundou_one_to_one.py`，用于停服后一次性把本地旧状态余额、流水、充值订单和兑换码金额按 `/100` 折算；脚本默认 dry-run，只有加 `--apply` 才会备份并写回。
- 回滚：回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、`backend/legal/user_agreement.md`、`scripts/migrate_yundou_one_to_one.py`、`tests/test_billing_unified.py`、`tests/test_native_billing_rates.py`、`tests/test_legal_agreements.py`、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和本文件；如已执行余额迁移，先停服并用脚本生成的 `.bak-yundou-1to1-*` 备份恢复状态文件。

## 2026-07-29 Agent.模式上传图操作提示改为可见小字
- Agent.模式顶部已上传图片不再使用系统悬浮提示框，避免黑暗/白天主题下 tooltip 文字看不清。
- 缩略图下方小字改为两行：第一行显示“待修改图/参考图”，第二行直接显示“点击替换 / 右键删除”，用户不用悬停也能看到操作提示。
- 本次只修改本地客户端 UI 提示和回归测试，不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py` 和文档即可恢复旧提示。

## 2026-07-29 数字人口播 TTS 不进入素材发布
- 数字人口播里“上传TTS声音”现在只作为生成数字人口播的内部音频使用，不再显示到左侧“素材发布”的素材列表中。
- 新上传的数字人 TTS 音频会带 `hideFromPublish` 和 `source=digital_human_tts` 标记；历史标题以“数字人TTS声音-”开头的音频也会在素材发布里隐藏。
- 本次不删除任何历史音频文件，不影响数字人口播生成，也不影响用户手动上传到素材发布的正常图片/视频素材。

## 2026-07-29 资产库图文同款不再打开 JSON
- 资产库里的“图文模板 / 图文同款”卡片删除第一个“打开”按钮，避免用户直接打开本地模板 JSON 文件。
- 图文模板卡片仍保留“文件夹”和“删除”按钮，方便定位素材目录和清理资产。
- 本次只修改本地客户端资产库卡片按钮和回归测试，不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py` 和文档即可恢复旧行为。

## 2026-07-29 小红书内容采集默认显示浏览器
- 小红书内容采集搜索和笔记下载从默认后台浏览器改为默认显示浏览器，用户可以看到登录、验证码、风控验证和页面跳转过程。
- 内容采集页在选择小红书后，搜索、下载和“图文同款”下载都会提示“正在打开浏览器，请登录/不要关闭窗口”，避免误以为按钮无反应。
- 保留环境变量回滚开关：`XHS_SEARCH_HEADLESS=1` 可让小红书搜索恢复后台模式，`XHS_DOWNLOAD_HEADLESS=1` 可让小红书下载恢复后台模式。
- 本次只修改本地小红书采集浏览器默认值、客户端提示和回归测试，不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/platform_adapters.py`、`backend/matrix_native_client.py`、`tests/test_native_publish.py`、`tests/test_video_replacement_v2.py` 和文档即可恢复旧行为。

## 2026-07-29 Agent.模式上传图片槽位铺满
- Agent.模式顶部上传图片槽位统一为 `112px × 56px`，已上传图片按槽位尺寸居中裁切铺满，不再在左右两侧留下空白。
- “添加图片”空槽位也使用同样的横向宽度，视觉上和已上传图片槽保持一致。
- 本次只修改本地客户端 Agent.模式上传槽位 UI 和回归测试，不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py` 和文档即可恢复旧行为。

## 2026-07-29 小红书图文同款三套正文加长
- 图文同款生成的三套正文候选从短句扩展为更完整的小红书段落，目标长度约 120-180 个中文字符，避免正文太短、信息量不足。
- 三套方案继续保持“种草建议 / 避坑对比 / 本地咨询”三种方向；正文仍不混入 `#标签`，也不恢复“真实体验整理”等固定模板话术。
- 本次只修改图文同款文案生成规则和回归测试，不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/xhs_note_replacement.py`、`tests/test_xhs_note_replacement.py` 和文档即可恢复旧长度。

## 2026-07-28 分解视频打开视频按钮无反馈修复
- “分解视频”页点击“打开视频”时会先确认源视频本地文件仍存在；成功调用系统播放器后会显示“已打开视频文件”，避免用户误以为按钮没反应。
- 如果系统默认播放器无法打开 mp4，会自动打开视频所在文件夹并选中文件，提示用户手动双击；文件已被移动或清理时直接提示“视频文件不存在”。
- 本次只修改本地客户端打开文件兜底、分解视频回归测试和文档，不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_video_breakdown.py` 和文档即可恢复旧行为。

## 2026-07-28 小红书图文同款必填字段 AI 预填
- 图文同款进入新笔记后，会基于原始标题、正文和标签异步调用 AI，自动生成并填入“标题（必填）”“所在地（必填）”“目标客户（必填）”“卖点（可编辑）”。
- 所有 AI 预填内容仍可由用户手动编辑；如果用户已经填写过某个字段，AI 返回结果不会覆盖用户输入。所在地只有在原文或标签能明确判断时才填，判断不出来保持空白，要求用户自己确认。
- “卖点（可编辑）”不再从原笔记标题兜底生成；AI 返回的卖点会过滤 `#标签`，也会过滤与原笔记标题相同或包含原笔记标题的内容。
- 本次只修改本地客户端图文同款页面和回归测试，不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py` 和文档即可恢复旧行为。

## 2026-07-28 漫剧本地项目计费修复
- AI Canvas 本地兜底项目在平台项目表中没有对应记录时，计费改为使用空项目外键并保留 `local_project_id` 追踪信息；已存在的平台项目继续保留原计费关联。
- 计费服务不再把所有数据库完整性错误统一误报为“计费请求重复”；无真实重复记录时返回准确错误并记录脱敏请求指纹。
- 同款替换客户端在远程恢复查询仍无图片/视频任务时，会同时显示最初的提交错误和 `recovery_missing`，不再丢失第一现场。
- 远程代码已备份并通过回归与真实计费冒烟；不涉及数据库结构、OpenAPI、Docker 或 `migration.sql`。按用户要求未自动重启本地客户端。

## 2026-07-28 自动化工作流采集封面改为视频预览
- 自动化工作流下载平台素材时，`cover.jpg`、`thumbnail`、`poster` 等图片不再作为独立资产进入资产库；采集参考素材只登记视频文件。
- 下载封面会写入对应视频资产的 `thumbnail/preview` 元数据，并复制到资产目录作为稳定预览文件；资产库视频卡片优先使用该封面预览，缺失时再回退到视频抽帧。
- 本次只修改本地客户端工作流采集/资产登记/资产卡片展示逻辑、回归测试和文档；不涉及中心服、数据库结构、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_workflow_resilience.py`、`tests/test_asset_library_shared_button.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和本文件即可恢复旧行为。

## 2026-07-28 自动化工作流脚本落盘
- 自动化工作流的 `text/vision/video` 脚本兜底链路现在会把口播脚本、兜底口播脚本或详细分镜脚本保存到账号级 `wf_out` 目录，并在运行日志中显示已保存的 `.txt` 文件名，避免第 2 步失败后只能看到日志摘要、找不到完整脚本文本。
- 新增 `scriptPath/scriptArtifacts/textArtifacts` 运行上下文字段用于追溯脚本文本；这些文本文件不会进入 `artifacts`，不会被当作可发布视频或图片进入发布队列。
- 本次只修改本地客户端工作流执行逻辑、回归测试和文档；不涉及中心服、数据库结构、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_workflow_resilience.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和本文件即可恢复旧行为。

## 2026-07-28 资产库卡片按钮一行紧凑布局
- 资产库素材卡片的按钮改为参考“退出登录”的纯图标小按钮，统一 30px 尺寸并全部放在同一行，按钮名称改为悬浮提示。
- 圆形图标按钮现在会在自身样式里固定 `padding:0` 和最小/最大宽高，不再继承全局普通按钮的 `min-width:76px` 后被撑成长条。
- 卡片底部动作区改为用等权重弹性空白分布按钮，避免按钮都聚集在左侧；3 个或 4 个按钮都会在整行内均匀散开。
- 图片卡片同一行展示“参考 / 打开 / 文件夹 / 删除”四个图标；视频卡片同一行展示“播放 / 文件夹 / 删除”三个图标，保留原有播放、打开、参考、文件夹定位和删除行为。
- 本次只修改本地客户端资产库布局、资产库源码契约测试和文档；不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-07-28 寻找线索操作列
- 获客中心“寻找线索”结果表从 4 列扩展为 8 列，新增“打开主页 / 复制链接 / 去私信跟进 / 标记已跟进”四个显式操作，避免用户依赖隐藏的双击交互。
- “去私信跟进”会把该行主页链接带入“私信 / AI 销售”页面，方便继续半自动或全自动私信跟进；“打开主页”当前仍使用系统默认浏览器打开。
- 四个操作按钮改用 `finderAction` 紧凑样式，按钮高度固定为 24px，线索表行高固定为 34px，避免按钮超出单元格。
- 本次只修改本地客户端 UI 和源码契约测试，不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_finder_page_actions.py`、`CHANGELOG.md` 和 `docs/IMPLEMENTATION.md` 即可。

## 2026-07-28 AI 触达页面说明增强
- 获客中心“AI 触达”页新增功能说明：解释它会按产品关键词搜索相关视频/笔记、读取评论区、筛选咨询/比价/想了解意向客户、生成短评论话术，并通过本机浏览器在评论区回复/评论。
- 页面明确提示“AI 触达不是私信群发”，并说明默认限量、间隔发送，遇到平台风控会停止；状态提示支持自动换行。
- 本次只修改本地客户端 UI 文案和源码契约测试，不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_outreach_page_copy.py` 和本文档即可。

## 2026-07-28 Seedance 真人参考图自动回退
- 漫剧分镜视频使用官方 Ark Seedance 时，只有精确错误 `InputImageSensitiveContentDetected.PrivacyInformation` 会触发一次 `kling-avatar-image2video` 回退；复用已生成首帧和完整口播音频，优先保证授权真人可生成及声音口型同步，不绕过或削弱任何上游审核。
- 失败 Seedance 扣费先退款，Kling Avatar 再独立扣费；任务和查询接口记录请求模型、实际模型、备用模型、回退原因与是否回退，并增加 started/submitted/failed 三类脱敏结构化日志。
- 本地同款替换轮询会提示已切换 Kling Avatar，片段 JSON 和视频列显示实际模型；备用模型失败时同时保留 Seedance 拒绝原因和 Kling 上游错误。显式空的 `COMIC_REAL_PERSON_VIDEO_FALLBACK_MODEL` 可关闭远程回退。
- 不涉及数据库迁移、OpenAPI 或中心服；发布只备份并重启远程 8777 AI Canvas 服务，按用户要求不自动重启本地客户端。

## 2026-07-28 数字人口播音频公网素材上传修复
- `img.yunlingai.net` 公网素材服务已支持 `mp3/wav/m4a/ogg/aac` 和对应音频 MIME；数字人口播“上传TTS声音”在配置 `UPLOAD_API_URL` / `UPLOAD_TOKEN` 时会和图片、视频一样优先直传独立公网素材服务，返回远程模型可读取的 `https://img.yunlingai.net/uploads/...` 地址。
- 本次本地只修改上传分支、回归测试和相关文档；服务端已重建 `image_upload_service`，数据库无迁移。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py` 和相关文档，并按服务端备份 `/root/image-upload-service/backups/20260728-audio-upload/` 恢复即可回到旧行为。

## 2026-07-28 同款替换单主角与远程自动时长
- 所有同款替换模式的人物素材统一为 1 张“主角正脸全身照”：选择器改为单文件，上传和任务保存只保留第一张。修复漫剧任务已经是 `comic_project`，却因公共校验落入旧链路三图分支并提示“正脸、左45°、右45°”的问题。
- 旧任务即使保存了多张人物参考图，也只使用第一张创建一个“主角”，不再要求补齐三张或生成角色2、角色3等重复人物资产。
- 删除本地“生成配音并测量真实时长”步骤及对应适配器调用。每段完整口播稿和用户选择的 AI 音色直接写入漫剧分镜请求，并继续使用 `auto_match_audio_duration=true`，由漫剧生成器按完整台词自动匹配或延长片段。
- 生成前会清除旧任务残留的本地音频准备字段，避免历史 `audioDurationSeconds/audioPrepareStatus/audioWarning` 干扰新链路。旧任务 JSON 仍可打开查看；按用户要求不自动重启本地客户端。
- 远程历史项目 293 已在备份后清理：只保留角色 3“主角”、场景 1 和道具 1，6 个分镜统一绑定上述资产；仅更新项目数据，未修改或重启远程漫剧服务。
- 本次只修改本地客户端、同款替换回归测试和文档，不涉及中心服、远程漫剧服务代码、数据库、OpenAPI、Docker 或 `migration.sql`。回滚这些本地文件即可恢复旧行为。

## 2026-07-28 资产库导入与素材文件夹入口
- 资产库顶部原“打开文件夹”改为“导入资产”，支持多选本地图片/视频并登记到本地资产库；单独的“本地资产”来源按钮已移除，避免只有一个来源时产生误解。
- 每个本地素材卡片在“播放/打开”旁新增“文件夹”按钮，直接打开该素材文件所在目录；原“播放/打开”“参考”“删除”行为保留。
- 本次只修改本地客户端、资产库源码契约测试和文档；不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-07-28 小红书图文同款正文去模板化
- 图文同款生成的三套正文候选去掉“这组图文按真实体验整理”“这次把重点放在…”“先收藏再对比”等固定模板话术，改为种草建议、避坑对比、本地咨询三种更自然的小红书口吻。
- 正文不再强行混入标签；标签仍单独生成，供发布器填入话题/标签输入框或追加到正文兜底。
- 本次只修改图文同款文案生成规则和回归测试，不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/xhs_note_replacement.py`、`tests/test_xhs_note_replacement.py` 和文档即可恢复旧模板。

## 2026-07-28 Agent.模式 LK888 模型映射修复
- Agent.模式现在以内置已确认 LK888 模型表作为权威来源：`doubao-seedance-1-5-pro-251215` 固定显示为 `Seedance 1.5 Pro`，LK888 模型目录只补充本地没有的模型，不再覆盖已确认模型的中文名或默认排序。
- 当 LK888 目录漏掉默认 Seedance 视频模型，或把该模型错标成 `Seedream 3.5 Pro` 等其它名称时，视频模式仍保留并优先展示真实默认模型，避免用户误选错模型后生成。
- 本次只修改本地客户端、Agent.模式回归测试和文档；不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-07-28 同款替换漫剧生成提交恢复
- 漫剧项目模式请求现在默认禁用系统/环境代理，避免本地客户端把 `http://120.26.194.174` 误走到本机代理 `127.0.0.1:7897` 后出现 `Read timed out`。
- 首尾帧或视频提交遇到 `计费请求重复`、本机代理读超时等可恢复错误时，不再立刻把片段标失败；本地会先回查当前漫剧项目分镜，若远程已创建任务 ID 或结果 URL，就继续等待并下载结果。
- 创建漫剧项目的远程等待时间从 60 秒放宽到 240 秒；同时进一步清洗嵌入式原片拆解，把 `**画面：** / **产品：** / **动作：** / **场景：**` 等视觉字段抽出来，跳过 `字幕/OCR/转写`，避免项目创建阶段因剧本内容冗余和远程初始化慢直接超时。
- 本次只修改本地客户端、同款替换测试和文档，不涉及中心服、远程漫剧 `server.py`、数据库、OpenAPI 或 `migration.sql`；按用户要求不自动重启本地客户端。

## 2026-07-28 本地客户端风控中心小红书违规识别
- 风控中心现在会把账号资料中的小红书违规/预警信息，以及本地任务返回的 `xhs_ip_risk`、`300012`、`300031` 等平台风险纳入账号风险判断；命中后显示“高风险”，并展示最近风险和建议动作。
- 小红书任务失败或返回风险码时，会把风险事件持久化到本地 `account_risk_events.json`，后续进入风控中心仍可看到，不再只根据在线状态把账号误判为低风险。
- 本次只修改本地客户端、相关回归测试和文档；不涉及 Web 端、中心服、数据库、OpenAPI 或 `migration.sql`。回滚相关文件并按需删除本地 `account_risk_events.json` 即可恢复旧行为。

## 2026-07-28 同款替换漫剧项目剧本与资产修复
- 同款替换漫剧项目模式现在把项目剧本改成漫剧生成器可解析的短结构：每段只写 `分镜 / 画面 / 对白 / 景别 / 角度 / 音效 / 运镜 / 最终提示词`，并剔除旧 LK888 提示词里的 `源视频锁定`、`原片拆解证据`、`字幕安全`、`人物参考图只用于` 等控制语，避免漫剧端解析出假的角色、场景和道具。
- 上传人物、场景和产品图写入漫剧项目库时补齐 `reference_image/reference_images`；人物资产同步补齐 `voiceName/ttsVoice/voiceStatus/voiceType/voiceProvider/voiceModel/voiceDescription`，让漫剧项目库角色的人物设计里能看到本地选择的音色备注。
- 分镜生成请求会带上 `project_id/projectId`，减少远程按错误作用域查项目导致的 404；`prepare-dialogue-audio` 404 会降级为片段 `audioWarning` 并继续用分镜生成请求里的口播稿生成首尾帧和视频，不再直接把该片段打失败。
- 本次只修改本地客户端、同款替换测试和文档，不涉及中心服、远程漫剧 `server.py`、数据库、OpenAPI 或 `migration.sql`；按用户要求不自动重启本地客户端。已创建过且被旧提示词污染的远程漫剧项目不会自动清理，需要重建新任务或手动清理远程项目库后重试。

## 2026-07-28 小红书创作者登录页等待修复
- 小红书创作者中心登录页现在不会一闪而过：发布流程遇到登录页后会继续保持浏览器可见并等待扫码登录，登录成功后再返回发布页继续上传；只有超时未登录才返回 `xhs_creator_login_required`。本次只改本地发布适配器、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。

## 2026-07-28
### Fixed

- 登录首页现在隐藏“注册”入口，只保留“登录”和“加入企业”两个按钮；内部注册模式对象保留为隐藏兼容逻辑，不影响已有接口和历史代码路径。本次只修改本地客户端、登录/邀请相关测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；重启本地客户端后生效。
- 同款替换漫剧项目模式现在会把“画面描述”和“口播台词”分开传给漫剧生成器：项目剧本 `source_text`、分镜 `description/camera_movement/prompt/keyframes_video_prompt` 会剔除 `口播/对白/旁白/台词/字幕` 行和片段 `script` 原文，最终台词只写入 `dialogue` 与 `audio_prompt.dialogue.text`，避免漫剧编辑器里“画面描述”显示 `口播：...` 并导致视频按台词内容乱生成。本次只修改本地客户端、测试和文档，不涉及中心服、远程漫剧 `server.py`、数据库、OpenAPI 或 `migration.sql`；按用户要求不自动重启本地客户端，代码生效需要用户手动重启本地客户端。
- 小红书发布默认改为弹出可见浏览器，便于用户在创作者中心完成扫码登录；当发布页跳转到 `creator.xiaohongshu.com/login` 或出现 `redirectReason=401` 时，状态栏改为提示“小红书创作者中心未登录，请在打开的浏览器中登录后重试”，不再误显示 `upload_input_not_found`。本次只修改本地发布适配器、原生客户端提示、回归测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；回滚这些文件即可恢复旧行为。
- 同款替换漫剧项目模式生成分镜时，客户端现在会先读取项目详情恢复已有 `comicStoryboardId`，没有分镜时提交分析任务并等待任务完成，再重新拉取项目详情回填分镜 ID；避免 `/projects/{id}/analyze` 异步返回 `task_id` 时被误判为 `comic_storyboard_id_missing:segment_1`。本次只修改本地客户端、测试和文档，不涉及中心服、远程漫剧 `server.py`、数据库、OpenAPI 或 `migration.sql`；按用户要求不自动重启本地客户端，代码生效需要用户手动重启本地客户端。
- 同款替换漫剧项目模式写入人物、场景和道具时，改为调用漫剧项目库集合创建接口，由漫剧后端返回真实资产 ID；不再用本地临时 `matrix-character-*` / `matrix-prop-*` ID 直接 `PUT`，避免出现 `comic_api_http_404: 本地资产不存在`。本次只修改本地客户端、测试和文档，不涉及中心服、远程漫剧 `server.py`、数据库、OpenAPI 或 `migration.sql`；按用户要求不自动重启本地客户端，代码生效需要用户手动重启本地客户端。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-07-27
### Fixed

- 企业中心顶部横幅视频改为稳定资源查找：优先使用当前数据目录 `hero.mp4`，缺失时回退到项目固定 `backend/datas/hero.mp4` 和内置 `assets/login_bg/car-shouye.mp4`，并用 `car-shouye.png` 作为海报兜底；视频缺失、加载失败和播放错误会写入 `enterprise_hero_video_*` 结构化日志。回滚本次客户端、测试和文档改动即可恢复旧行为，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
- 素材发布页的发布按钮现在会随“发布平台”切换：选择小红书时显示“发布到小红书”，选择抖音时显示“发布到抖音”；未选账号提示也按当前平台显示。
- 小红书图文发布失败不再只显示 `task_failed`：本地发布接口会透传平台和按钮点击诊断，客户端优先显示小红书发布器返回的真实错误；未确认发布成功时固定返回 `publish_unconfirmed`。
- 小红书发布器现在识别创作者中心里的“发布笔记”按钮，不再把它排除在候选按钮外；坐标兜底改为按当前浏览器视口计算，避免不同窗口高度时点错位置。
- 企业邀请流程不再要求手机号或邮箱：管理员邀请成员时选择目标企业和角色即可生成邀请码，受邀用户在本地客户端用邀请码、姓名和密码加入对应企业；企业管理员和普通用户的账户中心隐藏手机号绑定区域。回滚本次涉及的中心服、原生客户端、邀请/权限测试和文档即可恢复旧行为；不涉及数据库迁移，`migration.sql` 保持 no-op。

- 内容采集列表现在按平台展示并保留作者、点赞数和收藏数；小红书搜索结果会从响应元数据里补齐作者/点赞/收藏，抖音和小红书表头统一把原“转发数”改为“收藏数”。
- 图文同款里的“标题（必填）”不再自动从原笔记标题填充，必须由用户自己输入；系统仍会根据原笔记正文辅助生成“卖点（可编辑）”。
- 图文同款点击“保存草稿”后会先保存到本机，再同步上传到中心素材库；同步成功后可在“素材发布”看到该 `image_note` 草稿，同步失败会在状态栏明确提示并写入结构化日志 `xhs_note_draft_central_sync_failed`。
- 素材发布页现在会隐藏内容采集下载来源和混剪来源的历史素材；用户手动上传、商品图/视频生成成品、图文同款草稿和待人工处理的发布内容继续保留，不删除任何本地文件。
- 同款替换新任务默认切换为漫剧项目模式：本地客户端上传人物、场景和产品原图后，自动写入漫剧项目库的角色、场景和道具，按每段最终口播稿生成首尾帧和视频；旧任务 JSON 缺少 `replacementMode="comic_project"` 时继续按旧链路打开和查看。
- 同款替换漫剧项目模式的 SSO 现在固定签给漫剧账号 `003`（`user_id=44`），不再要求当前 Matrix 用户映射到漫剧主库用户；中心服 ticket 响应和结构化日志会记录 `comicUserId/comicUsername/comicAccountMode` 便于追踪。
- 修复同款替换旧链路启动顺序：旧任务重新恢复为“上游余额/账号预检通过后再上传参考素材”，余额不足时直接保存 `upstreamPreflight` 诊断并停止，避免无效上传。
- 漫剧项目模式下单个片段失败不再把整任务抛成上传失败；失败片段会保存 `errorId`、进入 `partial` 状态并保留“重试失败片段/单段重生”的恢复入口。

- 小红书采集下载现在会过滤评论区图片，并把原始标题、正文、标签和本地下载目录写入下载结果与素材库，避免“图文同款”进入后原文为空或标题回退成链接/目录名。
- 原生“图文同款”页面改成单页图片框流程：来源素材显示本地目录，替换图一张图一个框，支持多选顺序填充、三套标题/正文/标签方案选择；已移除“AI生成缺图”入口，保存草稿前必须所有槽位都有手动选择的真实图片，缺图返回 `xhs_note_replacement_missing_images`。
- 修复“图文同款处理失败：`xhs_note_save_failed`”：保存草稿分支不再被素材删除分支里的局部 `shutil` 导入影响；替换图复制会按槽位生成唯一文件名，并在 `copy2` 元数据复制失败时降级为普通文件复制。
- 小红书获客搜索命中平台安全限制时不再显示“完成：识别到 0 个客户”；后端返回 `xhs_ip_risk`、`riskCode=300012` 和 `errorId`，原生客户端提示切换可靠网络环境，并写入 `xhs_collection_search_failed` 脱敏结构化日志。

### Operations

- 本次不涉及数据库结构变更，`migration.sql` 保持 no-op。可通过 `XHS_NOTE_REPLACEMENT_ENABLED=0` 快速停用图文同款接口；小红书获客严格过滤仍可通过 `XHS_STRICT_LEAD_FILTER_ENABLED=0` 重启本地执行引擎临时降级。回滚本次涉及的 `backend/platform_adapters.py`、`backend/api_server.py`、`backend/xhs_note_replacement.py`、`backend/matrix_native_client.py`、`tests/test_api_download_contract.py`、`tests/test_xhs_note_replacement.py`、`tests/test_xhs_lead_filtering.py`、`tests/test_agent_mode_defaults.py` 和文档即可恢复旧行为。

## 2026-07-25
### Added

- 新增小红书“图文同款”V1：支持从采集结果或图文素材生成图文结构模板，按业务信息生成 3 组文案候选，优先使用用户/资产图片替换，缺图槽位进入 AI 占位确认状态，最终保存为素材发布里的 `image_note` 草稿并保留任务追溯字段。
- Web 端和原生客户端都新增“图文同款”独立入口；资产库本地过滤新增“图文模板”类型。
- 内容采集页新增单条小红书链接的“一键图文同款”：自动下载笔记图片，下载完成后直接进入图文同款并读取结构。
- “读取图文结构”增加 30 秒超时保护和明确提示；下载结果没有用户图片时提示“未找到图片素材，请先下载笔记”，避免把页面静态图误当成笔记素材。

### Operations

- 本次图文同款只生成草稿，不开放真实小红书多图图文发布；本地和中心服发布预检都会阻断 `image_note`，返回 `xhs_note_ai_image_unconfirmed` 或 `xhs_note_publish_not_supported`。
- 本次不涉及数据库结构变更，`migration.sql` 为 no-op。可通过 `XHS_NOTE_REPLACEMENT_ENABLED=0` 快速停用后端接口；代码回滚恢复 `backend/xhs_note_replacement.py`、`backend/api_server.py`、`backend/central_server.py`、`backend/matrix_native_client.py`、`frontend/index.html`、`tests/test_xhs_note_replacement.py` 和文档即可。

### Fixed
- 小红书获客采集不再把评论容器的普通子节点当作独立用户；无有效主页、空用户名、用户名等于评论的记录会在后端过滤，评论末尾时间、地区、作者、点赞和回复元信息会被清理，同一主页只保留意向最高且点赞优先的记录。
- Agent.模式的视频生成时长不再写死为 5 秒，视频模式可选择 5 秒或 10 秒，并将选择值传递到 LK888 任务参数。

- 同款替换 `tts/uploaded` talking 片段现在会先生成或裁切最终口播音频，按真实音频时长精确到 0.01 秒拆出口播时间表，并把时间表前置到 LK888 视频编辑 prompt；生成后复用同一音频文件本地换音轨，减少声音、字幕和画面口型节奏不一致。

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 同款替换提交 LK888 前改为按当前片段时间范围提取“画面、人物、产品、动作、道具、场景、节奏”镜头约束，并前置到 prompt；原视频字幕、OCR 字幕、原片口播转写以及时间轴表格中的“字幕/信息”列会被过滤。最终视频的字幕和人物台词只使用同款替换片段表中用户输入/修改后的口播稿。
- 同款替换主角整身替换遇到 `scene_mismatch` 或 `principal_motion_mismatch` 且产品/Logo/主角检查已通过时，会把该片段标记为 `sceneFallbackMode=ai_generated` 并自动重试一次；重试请求不再传上传场景图，改用 AI 生成同类场景，但继续传产品图并保留产品形状、颜色、Logo、主要包装文字和产品质检强约束。
- 同款替换 `tts/uploaded` 声音模式不再调用“已有视频口型同步”模型：口播稿台词放入 LK888 视频编辑 prompt，由远程视频模型按新台词生成嘴部动作；下载后本地分别用 AI 音色 TTS 或上传完整配音裁切片段替换音轨，避免最终视频仍保留原片声音，也不再因未配置 `VIDEO_REPLACE_LIPSYNC_MODEL` 中断。
- 同款替换口播稿写入 LK888 prompt 的位置前移：`tts/uploaded` 口型同步底片虽然仍用原片音频生成，但提示词台词来源保留为用户选择的配音模式；口播稿台词规则放在长拆解 prompt 前，避免 1800 字截断后 LK888 没收到新台词。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。
- 同款替换主角整身替换 prompt 现在按声音来源处理台词：原片声音继续保留原片原音和台词；AI 音色配音和上传完整配音会把用户修改后的片段口播稿写入 LK888 生成提示词，并要求后续口型同步以该音频/口播稿为准，避免画面生成阶段仍被旧规则引导沿用原片台词。
- 内容采集选择“小红书”搜索但本地执行节点离线时，状态栏现在按当前平台提示“小红书账号/本地客户端”，不再误写成“需先登录抖音账号”；本次只改客户端文案和回归测试，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
- 小红书笔记下载现在只保留作品主体媒体，过滤 `data:image`、`fe-platform`、`picasso-static` 等页面静态资源和小图标；过滤后没有正文图片或视频时返回 `xhs_no_note_media`，不再把页面装饰图当作素材下载成功。
- 资产库顶部隐藏“漫剧共享库”切换按钮，标题说明同步改为仅展示本地收藏入口；底层共享库逻辑保留，后续可最小回滚恢复。


- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。
- 数字人口播生成视频后默认按用户口播文案本地生成并烧录中文字幕；提交给 LK888/可灵数字人模型的 prompt 同步禁止画面内生成字幕、文字、标题、贴纸文字或水印，减少模型直接把乱码中文字画进视频。

### Operations
- 本次小红书获客过滤只修改本地平台适配器、测试、环境示例和文档，不改变 API Schema、数据库或 `migration.sql`。每条淘汰记录写脱敏 JSON 日志；误过滤时可设置 `XHS_STRICT_LEAD_FILTER_ENABLED=0` 并重启本地执行引擎，完整回滚使用 `backups/xhs-lead-filtering-20260727/` 归档。
- 本次同款替换口播音频时间表约束只修改本地客户端、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；按用户要求本次修改后不自动重启本地客户端。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧的“先生成视频、后换音轨”行为。

- 本次同款替换片段镜头约束与字幕来源修复只修改本地客户端、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；按用户要求本次修改后不自动重启本地客户端。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧 prompt 拼接行为。

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次同款替换场景冲突降级只修改本地客户端、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；按用户要求本次修改后不自动重启本地客户端。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复为场景不一致直接失败。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。
- 本次同款替换口播稿提示词修复只修改本地客户端、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；按用户要求本次修改后不自动重启本地客户端。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md` 和 `docs/IMPLEMENTATION.md` 即可。
- 本次小红书采集图片过滤只修改本地平台适配器、下载契约测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；回滚 `backend/platform_adapters.py`、`tests/test_api_download_contract.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。


- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
- 本次数字人口播字幕修复只修改本地客户端、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可。临时规避可设置 `DIGITAL_HUMAN_BURN_SUBTITLES=0` 并重启本地客户端，恢复为旧的无本地字幕后处理流程。
## 2026-07-24

### Added

- 本地客户端“企业中心 -> 团队成员”新增管理员专用“添加企业”入口，可直接创建企业并刷新企业下拉框；企业家和普通用户不显示该入口。

- 新增 `scripts/seed_toyota_enterprise.py`，用于一次性初始化 `org-toyota / 丰田汽车` 并修正 boss、user01、user02 的企业归属，脚本会先备份中心状态文件且重复执行不再改数据。

- 中心服新增平台管理员专用 `/api/enterprise/memberships/replace`，用于在运行中的中心服里把指定用户移动到指定企业并持久化，避免只改磁盘文件后被旧内存状态覆盖。

- “素材与发布”页新增“打开素材”按钮：选中素材后可直接用系统默认程序打开本机素材内容，查找时优先打开视频文件，其次打开图片文件；找不到本机文件时在状态栏提示。

- 本地客户端“企业中心”新增“团队成员”标签页：管理员可切换企业查看并管理成员；企业家固定管理自己企业；普通用户仍看不到企业中心。页面支持添加成员、创建邀请、重置密码、停用/恢复成员，资金、充值、兑换码相关逻辑不开放给企业家或普通用户。

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- 云豆扣费收口到中心服统一定价：`/api/billing/charge` 现在按 `capability` 使用服务端价格，客户端传入金额只作为未知能力的兼容值；主库模式下会按 `1 云豆 = 1 元` 和 `MAINDB_YUAN_TO_POWER` 换算后扣算力，不再对文案、混剪等通用能力直接放行；失败退款继续按 `ref` 幂等处理。

- 本地客户端修复企业中心团队成员表格“操作”列按钮重叠：操作列和行内按钮改为稳定宽度；左下角用户信息区拆为上下两行，避免账号名、余额、主题切换和退出按钮在侧边栏内互相压住。

- 本地客户端所有普通按钮点击后不再上移：全局点击动画对 `QPushButton` 直接跳过 geometry 缩放，覆盖同款替换页“生成替换方案 / 执行替换生成 / 确认片段并合成 / 重试失败片段 / 重生选中片段 / 加入待发布队列”等普通按钮，以及其它页面同类布局按钮。

- Web 版未登录时点击左侧“账号矩阵”现在会进入登录表单，不再被未登录门禁拦回企业中心；其他业务模块仍保持登录拦截。

- 素材发布页新增发布平台切换，账号下拉框按“抖音 / 小红书”分别显示已登录账号；发布请求会显式带上 `platform`，避免小红书账号因默认抖音链路被误判。已授权账号继续保留在 `org-default / user-owner`，不迁移到“丰田汽车”企业。

- 同款替换删除片段前会先保存当前表格里的口播稿，避免已编辑文案在刷新片段表后恢复旧内容；片段表滚轮改为小步像素滚动，避免鼠标往下滑时像翻页一样跳动。

- 删除片段后会把待生成片段时间轴重新压紧，后续片段从 0 秒起按各自时长连续排列，不再保留中间空档。

- 同款替换中某个远程候选模型先失败、后续候选成功时，成功片段会清空当前远程错误字段；旧任务即使残留 fallback 记录，完成状态也不再把它显示成当前错误。

- 同款替换选择“AI 音色配音”时，口播稿预计或实际略长于片段时长不再直接失败；系统会在可接受范围内自动把真实 TTS 音频提速后再回填到片段，默认最高 `1.45x`，超过上限时仍阻断并提示缩短文案或合并片段。

- 同款替换的“AI 音色配音”和“上传完整配音”现在会把有口播稿的片段标记为 talking，但不再进入数字人口播重生成整段视频；链路改为先生成同款替换画面，再用口播音频对已替换视频做已有视频口型同步。上传完整配音会先按片段时间切出对应音频片段并上传给 LK888，确保该片段的视频口型、声音和最终字幕都以口播稿/上传配音为准，同时保留原片动作、产品和场景。原片声音模式继续保留原链路。

- 同款替换标准模式下，主角整身 QC 的 `principal_appearance_mismatch` 不再直接阻断成片：白衬衫、深色职业马甲、职业半裙/西装套装被视觉模型误判为“黑色吊带裙”时，会记录质检提醒和审核帧，交给人工审核；高一致模式或严格视觉质检仍保持硬阻断。QC 提示词同步补充职业套装判定规则。

### Operations

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。

- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。- 本次云豆扣费收口涉及中心服、本地客户端、OpenAPI/接口文档和新增测试，不涉及数据库结构迁移；`migration.sql` 保持 no-op。回滚范围为 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_billing_unified.py`、`tests/test_openapi_contract.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md`。

- 已执行丰田汽车企业数据修正：`boss` 现在是丰田汽车企业家，`user01`、`user02` 现在是丰田汽车普通用户，`19711057505 / user-owner` 仍保留在默认企业；本次不迁移账号矩阵里已授权登录的抖音/小红书账号。数据回滚备份为 `backend/central_data/scheduler_state.json.bak-20260724150901`。

- 本次按钮重叠修复只修改本地客户端布局、权限测试和文档；不涉及中心服、数据库、OpenAPI、充值/兑换码或 `migration.sql`。回滚范围为 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。
- 本次普通按钮位移修复只修改本地客户端、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；重启本地客户端后生效。回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧动画行为。
- 本次企业中心团队成员管理只修改本地客户端、权限测试和文档；复用中心服已有成员/邀请接口，不涉及数据库结构、账号矩阵授权账号迁移、充值/兑换码逻辑、OpenAPI 或 `migration.sql`。回滚范围为 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。
- 本次 Web 左侧栏登录入口修复只修改静态前端源码、dist 产物、测试和文档；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。回滚 `frontend/index.html`、`frontend/dist/index.html`、`tests/test_web_login_navigation.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可。

- 本次素材发布平台切换修复只修改本地客户端、本地 API 和测试/文档；不涉及数据库迁移、账号迁移或 `migration.sql`。回滚范围为 `backend/matrix_native_client.py`、`backend/api_server.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。

- 本次同款替换片段删除和滚轮修复只修改本地客户端、测试和文档；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；代码改动需要重启本地客户端后生效。

- 本次同款替换时间轴压紧和远程候选错误显示修复只修改本地客户端、测试和文档；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；代码改动需要重启本地客户端后生效。

- 本次同款替换 AI 配音自动提速只修改本地客户端、测试和文档；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；代码改动需要重启本地客户端后生效。

- 本次同款替换口型同步规则只修改本地客户端、测试和文档；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。需要配置真正支持“已有视频 + 音频 -> 口型同步视频”的 `VIDEO_REPLACE_LIPSYNC_MODEL` 或 `LK888_VIDEO_LIPSYNC_MODEL` 后，`tts/uploaded` 声音模式才能完整生成；未配置时会返回 `replacement_lipsync_model_missing`，不会回退数字人模型。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；代码改动需要手动重启本地客户端后生效。

- 本次同款替换主角职业装质检误判降级只修改本地客户端、测试和文档；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；代码改动需要手动重启本地客户端后生效。

### Added

- 同款替换内置新增 LK888 “SD 2.0 全能参考”真实模型标识 `kwvideo-v2-quannengcankao`；云灵页面卡片 ID 为 `76`，生成请求使用模型标识而不是页面 ID。

- 同款替换新增任务级 LK888 模型选择：页面只展示适合同款替换的候选模型，默认仍使用 `happyhorse-video-edit`；LK888 模型目录中出现“SD 2.0 全能参考”时会自动作为备选模型加入下拉框。任务 JSON 保存 `model`，生成方案、正式生成和“重生选中片段”都会使用同一个任务模型。

- Agent.模式支持最多 4 张有序图片：可一次多选，也可分批追加；第 1 张标记为“待修改图”，第 2 张起标记为“参考图”，用于风格、人物、场景、材质等参考。新任务保存 `refs` 多图列表并保留旧 `ref=第一张` 字段兼容历史记录。

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- Agent.模式图片生成会把所有上传图片按顺序传给 LK888 图片接口，不再只发送一张参考图；提示词优化和视频模式会合并多图视觉描述，生成记录卡片也展示本次使用的多张图片及中文顺序标签。

### Operations

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。

- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。- 本次同款替换任务级模型选择只修改本地客户端、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；重启本地客户端后生效。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/ARCHITECTURE.md`、`docs/API_REFERENCE.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复固定模型行为。

- 本次 Agent.模式多图参考只修改本地客户端、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；重启本地客户端后生效。回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧单图上传逻辑。

## 2026-07-23

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- 内容采集搜索结果表在“链接”后新增“点赞数 / 转发数 / 视频时长”三列；抖音搜索标准化结果补充 `duration` 字段，页面兼容 `digg_count/share_count/duration` 及常见别名，缺失时显示 `-`。
- “素材与发布”页标题双击编辑改为弹窗编辑：表格内不再进入看不清的蓝底内嵌输入框，弹窗内显示大文本框和当前字数，保存后仍以标题栏内容作为真实发布标题来源，正式发布前按抖音规则取前 30 字。

- 同款替换主角提取遇到视觉模型返回非结构化内容时，不再让 `principal_actor_extract_invalid_response` 直接导致“生成方案失败”。客户端会记录 `video_replace_principal_actor_extract_failed` 的错误号，同时把已抽取的原片候选帧返回到页面，状态置为“需要人工确认”，用户选择原片主角后可继续生成。
- 内容采集选择抖音搜索时，不再只依赖默认 `auth_cookie.json`；当默认缓存缺失或不完整但账号矩阵里有可用抖音账号时，会自动切换到最新可用矩阵账号执行采集，避免账号显示在线却提示 `douyin_auth_incomplete`。
- 本地客户端账号隔离根目录固定：多次登录或切换用户时，账号数据始终写入同一个根目录下的 `accounts/<用户>`，不再生成 `accounts/<用户>/accounts/<用户>` 嵌套路径，避免内容采集重启后读不到账号矩阵 Cookie。
- 企业中心顶部横幅固定使用现有 `backend/datas/hero.mp4`，移除“生成宣传片 / 重新生成”按钮和生成进度监听，避免管理页误触重新生成并覆盖当前视频。
- 同款替换生成远程源片段前新增“字幕安全源片段”：默认把源片段顶部和底部常见字幕/营销大字区域遮罩后再上传给 LK888，避免视频模型复刻原片字幕并生成乱码假字；本地音频回填仍使用未遮罩的原始源片段。主角替换、普通远程编辑、关键帧和旧图生视频提示词统一改为“不要复刻/保留/新增原片字幕，中文字幕只由后期字幕层合成”。
- 同款替换选择“AI 音色配音”时，开始生成前会按片段时长估算每段口播是否能读完；预计超长时直接提示“会被截断”并阻断任务，避免上传参考图和远程生成后才发现尾音被切。TTS 音频下载后还会用真实音频时长二次校验，若音频长于当前片段则返回 `replacement_tts_audio_too_long`，不再把长音频按 8 秒片段静默截断。
- 本地客户端和中心服新增三角色权限体系：管理员为平台级 `platform_admin`，企业家为企业内 `owner/admin` 映射的 `enterprise_admin`，普通用户为 `normal_user`；登录/刷新响应返回 `appRole/productRole/roleScope`，客户端按角色隐藏企业中心和资金入口。
- 本地客户端兼容旧中心服登录响应：当 `admin/test123456` 登录返回 `user-owner` 但缺少 `appRole/productRole/roleScope` 时，客户端仍推断为平台管理员，避免“登录成功但企业中心消失”。
- 充值、兑换码、生成兑换码、用户加款等资金接口统一收口为平台管理员专用；企业家和普通用户即使手动调用也返回 403。
- 手机号自注册用户默认成为普通用户 `member`，不再自动成为自己企业的 `owner`；企业家必须由管理员创建、邀请或显式调整 membership 角色。
- 企业总览、账号矩阵、素材、知识库、待发布队列和中心任务列表按角色过滤：管理员全局，企业家本企业，普通用户只看自己的业务数据。
- 数字人口播图片合成修复 LK888 `images 参数格式错误`：当参考图里包含本地 `data:image` 时，不再把它复制到只接受公网直链的 `images/reference_images/params.images` 字段；场景合成优先使用已上传的公网场景图，避免第 2 张图被判为无效 URL。
- 数字人口播“人物图 + 场景图”中间合成遇到 LK888 内容安全策略拦截时，会自动改用更中性的合成提示词和 1:1 尺寸重试一次；若仍被拦截，页面显示“内容安全策略拦截”的准确中文提示，不再误导为生成超时。
- 数字人口播“人物图 + 场景图”中间合成不再只把公网参考图放入单一 `image_urls` 字段；图片生成请求在参考图全为公网直链时同时携带 `image_urls/images/reference_images/referenceImages/params.images`，避免 LK888 图片接口忽略参考图后退化成纯文生图，导致人物和场景完全跑偏。
- 同款替换页移除“产品镜头锚定”“原片动作控制”“人物一致性”三个已不适配当前主角整身替换链路的入口；新任务固定 `identityMode=standard`、`enableFaceFusion=false`、`actionControlEnabled=false`、`productAnchorEnabled=false`，保持现有远程主角替换主链路不变，避免用户误以为这些控件会改变生成效果。
- 同款替换产品图归一化已移除：产品图上传后直接以用户原图作为参考图，不再调用图像模型做白底抠图/重绘，避免归一化后变成另一个产品；任务 JSON 的 `productPreprocess` 仍记录 `normalized=false`、`error=product_normalize_removed`、`selectedPath` 和上传 URL，便于追溯。
- 同款替换点击“取消任务”后会立刻保存 `status=cancel_requested` 和 `cancelRequested=true`，按钮改为“取消中”并禁用，页面进度提示“当前远程片段结束后停止”；LK888 远程轮询每轮检查本地取消标记，尽量更快退出本地等待。当前仍不调用 LK888 上游任务取消接口。
- Agent.模式新增“提示词优化”确认流：用户输入需求后可先生成中文优化提示词，在可编辑弹窗中确认后再生成；生成记录和生成过程继续显示中文提示词，内部模型提示词改为隐藏字段。
- Agent.模式胶囊按钮点击后不再上移：图标文字按钮退出全局 geometry 缩放点击动画，覆盖风格、数量、比例、模型、提示词优化以及复用同一按钮工厂的资产库/混剪按钮。
- Agent.模式输入区改为参考图在上、提示词多行输入在下：上传参考图不再和文本框挤在同一行，长提示词会自动换行展示；发送、提示词优化和重新编辑均读取多行文本内容。
- 同款替换主角整身替换修复 `principal_video_edit_failed` 的短尾段失败：`happyhorse-video-edit` 的源视频参考片段最短需要约 3 秒，新建方案会把小于 3 秒的最后一段并入上一段；旧任务点击“重试失败片段”时也会把最后失败短段合并到上一段重跑，避免继续提交 1.47 秒这类无效片段。
- “发布到抖音”遇到抖音安全验证时不再提前关窗：去掉对“验证”二字的泛匹配，只识别安全验证/身份验证类明确提示；命中 `security_verify_required` 或 `security_appeal_required` 时保留浏览器窗口，允许用户点击发送验证码并完成人工验证。
- 本地客户端对 `security_verify_required` 显示中文可操作提示，明确要求在打开的浏览器中完成验证后重试，不再只展示“真实发布未完成:security_verify_required”。
- “素材与发布”页标题列支持编辑，真实发布标题以当前标题栏内容为准；发布请求新增 `publishTitle`，并新增 `/api/library/update-title` 保存编辑后的素材标题。
- 发布器正式发布前将标题栏内容限制为前 30 个字符；素材库继续保存标题栏中的完整可编辑内容。

- 同款替换新增声音来源选择：默认保留原片声音；可选择 AI 音色按每段口播稿重新配音；也可上传一条完整配音音频，在最终成片阶段替换整条音轨。上传完整配音不做音色克隆，音频短于成片时会阻断并提示更换音频。
- 同款替换主角链路清除旧“只换身份和脸部”提示词残留，`source_video_edit` 现在明确要求使用上传人物的完整外观，包括脸、发型、服装、体型和配饰，同时只保留源片动作、台词、职业语境、站位和镜头关系。
- 主角视觉 QC 新增 `fullBodyAppearanceMatch` 与 `principal_appearance_mismatch`。如果前几段视频仍保留原片主角的发型、服装、体型或配饰，会硬阻断并进入单段重试/人工确认，不再把这类结果误判为通过。
- 同款替换产品/场景槽位改为“未上传保留原片，上传则强制替换”：`source_video_edit` 主角请求会把人物图、产品图、场景图一起传给 HappyHorse；产品类别冲突不再生成前阻断，只记录 warning；上传场景图后 `scene_mismatch` 会阻断片段，不再以 `scene=source_preferred` 放行。
- 同款替换源视频槽位提取不再把“展厅/门店”默认写成汽车销售/汽车展厅。人物、产品、场景类别改为从分解报告、视觉说明、OCR 和转写中动态提取；旧任务开始生成或单段重试时会按当前 `breakdownAnalysis` 重新计算 `sourceReplacementEntities`，避免花洒、卫浴等视频被汽车标准误判为质检失败。

### Operations

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。

- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。- 本次内容采集指标列只修改本地客户端、本地 API 标准化、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；按用户要求本次修改后不自动重启本地客户端。回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`backend/utils/data_util.py`、`tests/test_video_replacement_v2.py`、`docs/IMPLEMENTATION.md` 和 `CHANGELOG.md` 即可恢复旧三列表格。
- 本次同款替换主角提取降级只修改本地客户端、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；按启动策略只需重启本地客户端。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 后会恢复旧行为，但视觉模型返回非 JSON 时会再次中断方案生成。
- 本次内容采集账号选择修复只修改本地 API、测试和文档，不涉及中心服、数据库或 `migration.sql`；回滚 `backend/api_server.py`、`tests/test_douyin_multi_account.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可恢复旧行为。
- 本次账号隔离根目录固定只修改本地客户端、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`docs/IMPLEMENTATION.md` 和 `CHANGELOG.md` 即可恢复旧行为。
- 本次企业中心横幅固定只修改本地客户端、测试和文档，不涉及中心服、数据库、现有 `backend/datas/hero.mp4` 或 `migration.sql`；回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`docs/IMPLEMENTATION.md` 和 `CHANGELOG.md` 即可恢复旧的重新生成入口。
- 本次同款替换字幕安全源片段只修改本地客户端、测试和文档，不涉及中心服、数据库或 `migration.sql`；可通过 `VIDEO_REPLACE_SUBTITLE_SAFE_SOURCE=0` 临时关闭源片段遮罩并重启本地客户端。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 后会恢复旧行为，但远程模型可能再次把原片字幕生成成乱码假字。
- 本次同款替换 TTS 防截断只修改本地客户端、测试和文档，不涉及中心服、数据库或 `migration.sql`；阈值可通过 `VIDEO_REPLACE_TTS_CHARS_PER_SEC` 调整，默认按约 4.2 字/秒估算。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 后会恢复旧行为，但 AI 配音超长仍可能被片段时长截断。
- 本次三角色权限体系涉及中心服、本地客户端、OpenAPI/文档和新增测试，不涉及数据库结构迁移；`migration.sql` 保持 no-op。回滚范围为 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`docs/ARCHITECTURE.md`、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md`。
- 本次管理员菜单兼容修复只修改本地客户端、测试和文档，不涉及数据库迁移；回滚 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`tests/test_auth_login_modes.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可。回滚后旧中心服未返回角色字段时，管理员可能再次被客户端当作普通用户隐藏企业中心。
- 本次数字人口播安全策略低风险重试只修改本地客户端、测试和文档，不涉及中心服、数据库或 `migration.sql`；回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。
- 本次数字人口播参考图字段兼容修复只修改本地客户端、测试和文档，不涉及中心服、数据库或 `migration.sql`；回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 后会恢复旧的单字段图片合成请求。
- 本次同款替换无效控件移除只修改本地客户端、测试和文档，不涉及中心服、数据库或 `migration.sql`；只需重启本地客户端。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/ARCHITECTURE.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧控件入口。
- 本次同款替换产品图归一化移除和取消任务反馈修复只修改本地客户端、测试和文档，不涉及中心服、数据库或 `migration.sql`；按启动策略只需重启本地客户端。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `docs/DEPLOYMENT.md` 后会恢复旧产品图归一化链路。
- 本次 Agent.模式提示词优化和按钮位移修复只修改本地客户端、测试和文档，不涉及中心服、数据库或 `migration.sql`；回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可。
- 本次 Agent.模式多行输入布局只修改本地客户端、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`；重启本地客户端后生效。回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧单行布局。
- 本次短尾段修复只修改本地客户端、测试和文档，不涉及中心服、数据库或 `migration.sql`；回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可。回滚后 3 秒以下最后片段可能再次触发 `principal_video_edit_failed`。
- 本次抖音安全验证窗口保留修复不涉及数据库迁移；回滚范围为 `backend/utils/publish_util.py`、`backend/matrix_native_client.py`、`tests/test_publish_util_safety.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。回滚后安全验证页仍可能在用户点击“发送验证码”前被关闭。
- 本次素材发布标题编辑修复不涉及数据库迁移；回滚范围为 `backend/matrix_native_client.py`、`backend/api_server.py`、`backend/utils/publish_util.py`、相关测试、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md`。

- 本次同款替换声音来源选择只修改本地客户端、测试和文档，不涉及中心服、数据库或 `migration.sql`；回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md` 和 `docs/IMPLEMENTATION.md` 后恢复固定原片声音。
- 本次只修改本地客户端和测试/文档，不涉及中心服或数据库迁移。回滚可设置 `VIDEO_REPLACE_PRINCIPAL_REPLACEMENT=0` 并重启本地客户端；若只想回退本次产品/场景强制替换，回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py` 和相关文档即可。
- 本次源视频槽位动态提取只修改本地客户端、测试和文档，不涉及中心服、数据库或 `migration.sql`；回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `docs/API_REFERENCE.md` 即可。回滚后可能再次出现源视频产品/场景被旧固定类别污染的误判。

## 2026-07-22

### Added

- 同款替换单主角模式改为源视频编辑链路：方案阶段从原片关键帧提取 `principalActor`（最佳帧、bbox、置信度和预览），页面接受 1-3 张人物参考图并要求至少一张全身图确认；任务保存 `personReferencePaths`、`personReferenceUrls` 和 `principalReplacementMode`。
- `source_video_edit` 任务使用 HappyHorse 原生 `video` + `images` 字段，同时保留兼容视频别名；失败以 `principal_video_edit_failed` 硬阻断，不回退到 Vidu/Wan 参考图视频模型。视觉 QC 新增 `principalReplacementMatch`、`fullBodyAppearanceMatch`、`otherSubjectsPreserved`、`motionPreserved`。
- 主角模式不再强制上传产品图：未提供产品参考时直接以原片产品和场景为准；页面显示原片主角缩略图，低置信度候选首项必须显式选择，避免自动确认错误人物。
- 主角片段生成后无条件回填原片段音轨，并让主角视觉 QC 在没有产品参考图时仍执行；纯产品模式不会误走主角链路，回滚时清除残留的主角自定义模型配置。

### Operations

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。

- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。- 主角链路由 `VIDEO_REPLACE_PRINCIPAL_REPLACEMENT=1`、`VIDEO_REPLACE_PRINCIPAL_MODEL=happyhorse-video-edit` 和 `VIDEO_REPLACE_PRINCIPAL_MIN_CONFIDENCE=0.65` 控制；紧急回滚只需将总开关设为 `0` 并重启本地客户端。本次不涉及中心服代码、数据库迁移或 `migration.sql`。
- 产品图处理默认受限并行度为 `VIDEO_REPLACE_PRODUCT_PARALLEL=2`（上限 3）；本次只改本地客户端，按启动策略重启本地客户端即可，中心服不重启。

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- “发布到抖音”在作品仍上传/自动发布时不再过早关窗：检测到“作品上传中/上传完成后将自动发布”会进入 `DY_PUBLISH_PENDING_TIMEOUT` 长等待，默认 1800 秒；若最终仍 pending，不主动关闭浏览器窗口。

- 本地客户端“发布到抖音”真实发布未完成时不再显示“试发完成”：本机 `/api/publish/run` 响应新增 `dryRun`，客户端只有 `dryRun=true` 才展示试发完成；真实发布未拿到成功信号时显示具体错误码。
- 本地客户端“素材与发布”页“发布到抖音”真实发布误报修复：`CTF_LOCAL_SAFE_PUBLISH` 测试/沙箱绕过不再把登录墙、风控、上传未完成或发布失败结果改写为 `published=true`；真实发布只有拿到抖音强成功信号才会返回发布成功。

- 同款替换不再因为口播稿存在而切入 TTS + 数字人口播链路；`VIDEO_REPLACE_ENABLE_AVATAR_SEGMENTS`、`VIDEO_REPLACE_STRICT_SCRIPT_AUDIO` 和旧任务里的 `strictScriptAudio/talking` 对同款替换执行链路不再生效。口播稿文本框内容仍作为用户最终口播稿保留到片段 `script`，用于字幕和后续唇形同步扩展。
- 同款替换片段表格移除“类型”列和“严格按口播稿生成语音”开关，仅保留可编辑“口播稿”列，避免用户误以为同款替换片段可以手动切换为数字人口播。

### Operations

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。

- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。- 本次上传中窗口保留修复不涉及数据库迁移；回滚范围为 `backend/utils/publish_util.py`、`tests/test_publish_util_safety.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。回滚后大文件或慢网发布仍可能被本地发布器提前关窗。

- 本次真实发布提示修复不涉及数据库迁移；回滚范围为 `backend/matrix_native_client.py`、`backend/api_server.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。回滚后真实发布未完成仍可能被误显示为“试发完成”。
- 本次素材发布误报修复不涉及数据库迁移；回滚范围为 `backend/utils/publish_util.py`、`tests/test_publish_util_safety.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。回滚后若生产环境存在 `CTF_LOCAL_SAFE_PUBLISH=1`，仍可能把未真实发布误报为成功，不建议回滚。

- 本次不涉及数据库迁移，`migration.sql` 无需变更。回滚范围为 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`；回滚后同款替换可能重新受严格口播配置影响而误走数字人口播。

### Added

- 同款替换方案改为显式“源视频实体替换”思路：生成方案时从原视频分解结果提取人物、产品和场景槽位，任务 JSON 写入 `sourceReplacementEntities`；远程视频编辑 prompt 明确将原片人物槽位替换为上传授权人物/虚拟模特，产品和场景槽位按“未上传保留原片，上传强制替换为上传素材”处理。页面标题和生成中提示同步说明“先提取原片人物/产品/场景槽位”。

- 同款替换产品图白底归一化新增一致性校验：归一化图必须与用户原图保持同一产品主体，若图像模型把产品重绘成 GPS、护肤品等错品类，会自动废弃归一化图并回退原图，任务 JSON 写入 `productPreprocess.validation`、`fallbackReason`、`selectedPath` 和结构化日志 `errorId`；页面进度显示“产品图 N/M 归一化异常，已回退原图继续生成”。可用 `VIDEO_REPLACE_PRODUCT_NORMALIZE_VALIDATE=0` 只关闭校验，或用 `VIDEO_REPLACE_PRODUCT_NORMALIZE=0` 直接关闭归一化。
- 同款替换产品图参考链路改为受限并行：上传参考图阶段会并行处理最多 3 张产品图中的 2 张（可用 `VIDEO_REPLACE_PRODUCT_PARALLEL` 调整，默认 `2`，上限 `3`），每张仍执行原图上传、白底抠图归一和归一图上传；前端进度会显示“正在处理产品图 N/M：归一化与上传”和“产品图 N/M 已完成”，避免长时间停在笼统的“上传参考图”。回滚时设置 `VIDEO_REPLACE_PRODUCT_PARALLEL=1` 恢复串行；紧急跳过慢归一化可设置 `VIDEO_REPLACE_PRODUCT_NORMALIZE=0`。本次不涉及数据库迁移。

- 同款替换新增人脸相似度量化质检：片段 QC 复用抽帧与授权人脸做身份相似度评分（0-100），默认阈值 70、高一致模式 80（可用 `VIDEO_REPLACE_FACE_SIMILARITY_MIN`/`_MIN_HIGH` 调整）；低于阈值默认记录 `face_similarity_low` 审核警告不阻断，严格质检模式（`strictVisualQc`）下直接判片段失败；评分服务异常自动降级为人工审核；可用 `VIDEO_REPLACE_FACE_SIMILARITY_QC=0` 或任务字段 `faceSimilarityQcEnabled` 关闭。
- 同款替换页新增“产品镜头锚定”复选框（默认开启），直接控制任务 `productAnchorEnabled`，与 `VIDEO_REPLACE_PRODUCT_ANCHOR` 环境变量联动。

- 同款替换标准一致性模式默认执行本地 FaceFusion 换脸锚定（非口播段）：任务创建时预检本地 FaceFusion 可用则自动启用并强制选择原片目标人物；不可用时降级为仅远程生成并在状态栏提示，不阻断任务。旧任务（无 `enableFaceFusion` 标志）行为不变；高一致模式仍阻断式预检并覆盖口播段换脸。
- 同款替换产品图上传后默认先经图像模型抠图、白底归一，再注入参考图列表，提升远程模型对产品的还原度；归一化失败自动回退原图并在任务 JSON 记录 `productPreprocess` 报告；可用 `VIDEO_REPLACE_PRODUCT_NORMALIZE=0` 关闭。
- 同款替换非口播段新增产品镜头锚定：抽取源片段画面经视觉模型检测产品是否出现，命中则以白底归一化产品图对代表帧做图像编辑替换，合成“产品锚定帧”作为强参考注入视频编辑请求，产品从提示词弱约束升级为像素级锚定；未命中或任何失败自动回退标准链路并写入 `productAnchorWarning`；可用 `VIDEO_REPLACE_PRODUCT_ANCHOR=0` 关闭。

### Operations

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。

- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。- 本次改动不涉及数据库迁移；回滚范围为 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py` 和本文件。临时规避：设置 `VIDEO_REPLACE_PRODUCT_NORMALIZE=0` 与 `VIDEO_REPLACE_PRODUCT_ANCHOR=0`，或使用快速模式（不跑本地换脸）。

## 2026-07-21

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。
- 数字人口播场景图背景质检失败时，自动使用上传场景唯一背景约束重试一次；仍失败才停止生成并退款。
- 场景图错误提示改为明确区分“用户上传的场景图”和“系统合成的数字人图”，客户端状态栏显示中间合成图脱敏 URL，便于追溯实际生成结果。
- 新增背景重试、URL 查询参数脱敏和场景误判回归测试。

## 2026-07-21

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- 本地客户端“素材与发布”页真实发布修复：点击“发布到抖音”时明确传入 `dryRun=false`，不再走默认试发；客户端成功判断改为真实发布只认 `published=true`，`ok=true/filled=true` 但未发布时显示“试发完成，未真实发布”。
- 数字人口播上传场景图后，场景版人物图生成遇到 LK888 图片代理 `502/504/timeout/lk888_proxy_error` 时，会自动降为 `1024x1024` 再重试一次；连续失败时显示中文可操作提示，不再把 `{"ok": false, "error": "lk888_proxy_error"}` 直接暴露给用户。

- 数字人口播场景图改为可选强制换背景：未上传场景图时保持原人物图口播链路；上传场景图时先合成“场景版人物形象图”，再用视觉质检比对上传场景和合成图背景，只有场景一致才进入 TTS 与数字人口播；合成或质检失败会停止生成并走现有退款路径。
- 同款替换 fallback 模型按模型适配视频参数：`happyhorse-*` 下单前将 `resolution=720p` 规范为 `720P`，避免首选参考图模型超时后备用模型直接 400 参数失败。
- 分解视频页“打开视频”失败时会在状态栏提示无法打开文件，不再表现为点击无反应。
- 同款替换后续片段会上传上一段生成结果的审核帧作为连续性参考，用于降低不同片段人物脸部观感、发型和服装跳变。
- 同款替换后期字幕时间轴改为优先按实际片段视频时长计算，减少远程生成片段时长波动导致的字幕漂移。
- 同款替换新增可选“原片动作控制”：默认关闭；开启后每个非口播片段按约 2 秒抽取原片动作关键帧、单段最多 4 张，随产品图/人物图一起传给远程参考图视频模型，用于约束动作、站位、镜头和构图。
- 同款替换取消 V2 固定总时长硬上限，仍按约 8 秒分段串行生成；长视频会产生更多片段，保留失败片段单独重试和人工确认后合成。
- 原片动作控制抽帧或上传失败时不阻断整单，片段写入 `actionControlWarning` 并回退到原标准远程生成链路。
- 同款替换片段表格修复口播稿可读性：口播稿列改为 520px 宽的多行文本框，行高提升到 122px，深色背景下固定白字、蓝色选中态、清晰 focus 边框，并从该文本框读取生成前的编辑内容。
- 同款替换片段表格修复“删除”按钮溢出：操作列固定宽度，删除按钮固定尺寸并居中；其他信息列通过横向滚动承载，避免继续挤压口播稿编辑区。

### Operations

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。

- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。- 本次本地客户端发布修复不涉及数据库迁移；回滚范围为 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。回滚后“素材与发布”页可能重新出现试发被显示为发布成功的风险，不建议生产长期回滚。
- 本次数字人口播图片代理超时重试不涉及数据库迁移；回滚范围为 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。若需要临时规避，可不上传场景图，直接走原人物图口播链路。

- 本次数字人口播强制换背景不涉及数据库迁移；回滚范围为 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `docs/superpowers/specs/2026-07-21-digital-human-forced-scene-background-design.md`。
- 本次同款替换 fallback、跨片段连续性、字幕对齐和打开视频反馈不涉及数据库迁移；回滚范围为 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`tests/test_video_breakdown.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。
- 本次原片动作控制不涉及数据库迁移；回滚方式为取消页面开关、设置 `VIDEO_REPLACE_ACTION_CONTROL=0`，或回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md` 和相关 `docs/`。
- 本次仅调整原生客户端同款替换表格 UI 和对应测试，不涉及数据库迁移；回滚范围为 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。

## 2026-07-20

### Changed

- 同款替换新增严格口播模式：本地 `backend/.env` 默认启用 `VIDEO_REPLACE_STRICT_SCRIPT_AUDIO=1`，有口播稿的片段会强制走 TTS + 数字人口播链路，不再按非口播片段回填原视频音频；需要回滚时把该变量设为 `0` 并重启客户端。
- Windows 源码部署的本地客户端数据目录默认改为项目内 `backend/datas`，不再默认写入 `%APPDATA%\MatrixShipAgent\data`；启动脚本同步设置 `MATRIX_AGENT_DATA_DIR`、`DY_DATA_DIR` 和 `DY_PROFILE_DIR`。
- 新增 `backend/runtime_paths.py` 数据目录解析与旧 AppData 非破坏性复制，支持 `MATRIX_AGENT_USE_APPDATA=1` 回滚和 `MATRIX_AGENT_SKIP_APPDATA_MIGRATION=1` 跳过复制。

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- 同款替换新增清晰中文字幕后期烧录：视频模型阶段禁止新增字幕/屏幕文字，最终合成阶段根据片段口播稿生成 ASS 字幕并用 ffmpeg 烧录到成片，避免中文由模型生成导致假字、糊字和乱码。
- 原生客户端深色主题增强控件对比度：复选框现在显示边框、选中图标和 hover 态；下载报告等次级按钮增加最小宽度和文字对比；口播稿/提示词文本框聚焦和选中时保持白字可读。
- 同款替换视频片段、关键帧和远程编辑提示词改为中文，保留源视频锁定、产品锁定、人物身份锁定和场景参考可选约束，避免界面报告或任务 JSON 暴露英文片段模板。
- 分解视频前置抖音下载现在会拒绝只有 `msToken` 的不完整登录态，并返回 `douyin_auth_incomplete` / `needLogin=true`；原生客户端会把 `douyin_auth_incomplete` 和历史 `'s_v_web_id'` 映射为“请重新登录抖音”，避免“分解失败：下载未完成”不可读。
- 同款替换开始生成前新增轻量上游预检：先检查本地余额与 LK888 模型入口可用性，余额不足、模型未计价、上游账号未配置、未登录等问题会在上传参考图和远程扣费前阻断，并写入 `upstreamPreflight`、稳定 `errorId` 与中文诊断摘要。
- 同款替换任务失败时新增 `diagnostics` 摘要，包含失败片段编号、片段错误编号、是否可重试和建议操作；失败弹窗会追加“失败片段/建议操作”，减少用户必须翻日志排查的情况。
- 同款替换客户端启动时会扫描本地 `video_replacements/*/replacement_job.json`，把重启后残留的 `running` / `generating` 旧任务恢复为可追踪终态：已有成功片段的任务标记为 `partial`，没有成功片段的任务标记为 `failed`，并在任务 JSON 写入 `recoveredAt`、`recoveryReason` 和片段级恢复原因。
- “重试失败片段”现在会在重新生成前清理旧版误阻断字段，把 `role_mismatch`、`structure_mismatch` 和人物背景类 `reference_mismatch` 转为人工复核提醒并归档到 `retryHistory`，避免旧 JSON 继续以旧规则卡住新重试。
- 同款替换真人模式不再强制上传场景图；场景图和场景描述改为可选增强，远程编辑和视觉 QC 都以源视频场景类型、镜头结构和主题优先，场景参考冲突但主题未跑偏时不再直接判失败。

### Operations

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。

- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。- 新增 `VIDEO_REPLACE_BURN_SUBTITLES` 环境变量，默认开启；如字幕烧录在特定机器上失败，可设为 `0` 临时回滚为旧的无后期字幕流程。可通过 `VIDEO_REPLACE_SUBTITLE_FONT`、`VIDEO_REPLACE_SUBTITLE_FONT_SIZE`、`VIDEO_REPLACE_SUBTITLE_MARGIN_V` 调整字体、字号和底部边距。
- 新增 `VIDEO_REPLACE_UPSTREAM_PREFLIGHT` 环境变量，默认开启；紧急回滚可设为 `0`/`false` 跳过上游预检，但不建议在生产长期关闭。
- 本次字幕烧录修复不涉及数据库迁移；回滚范围为 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。
- 本次界面可读性和中文提示词修复不涉及数据库迁移；回滚范围为 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。
- 本次只调整本地任务生命周期、重试前状态清理和同款替换场景参考策略，不涉及数据库迁移；回滚范围为 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。

## 2026-07-18

### Changed

- 同款替换非口播默认从 `happyhorse-video-edit` 切换为参考图视频候选链：`viduq3-turbo-cankaosheng -> wan2.7-cankaosheng -> viduq3-cankaosheng -> viduq2-cankaosheng -> happyhorse-r2v -> happyhorse-1.1-r2v`；首个模型失败时记录 `remoteErrorId` 并自动尝试下一个模型。
- 同款替换新增快速、标准、高一致三种人物一致性模式；默认标准模式不再因上传人物图自动执行本地 FaceFusion，避免每段 420 秒超时。高一致模式仍可显式启用本地换脸增强，失败后回退远程结果并进入人工审核。
- 视觉 QC 不一致默认降级为人工审核提醒；当前主角槽位链路中，上传场景图后的 `scene_mismatch` 和主角相关 `principal_*` 错误会阻断片段，普通 `product_mismatch`、`face_mismatch` 仍可按审核策略处理。
- 视觉 QC 现在会同时参考原片源片段；当原片该段本来没有清楚出现目标产品时，产品和 Logo 检查标记为 `skipped_source_absent`，允许生成结果不出现产品。
- 同款替换片段状态列显示片段序号、当前阶段、模型名、耗时/剩余、质检提醒和远端错误编号，避免 fallback 掩盖真实远端失败。
- 同款替换新增漂移防护：生成前参考图预检、提示词源视频锁定、生成后主题/角色/结构 QC。人物参考图锁定新主角完整外观，但不能把美妆、食品、直播间等无关行业语境覆盖到汽车等源视频主题。
- 参考图预检规则收窄：人物参考图携带制服、Logo、展厅、直播间或背景上下文时只给 warning，不再生成前阻断；产品图或场景图与源视频类别不同也只预警，上传后由生成后 QC 判定是否完成替换。
- 严重主题漂移在快速、标准、高一致模式下都会阻断；系统默认自动重试一次，第二次仍失败时写入 `visual_drift_retry_exhausted` 并停止最终合成。
- 严重漂移硬阻断范围收窄：只有跨行业、跨品类或完全无关内容触发重试/阻断；`role_mismatch` 和 `structure_mismatch` 在主题保留时默认进入人工复核，避免汽车产品细节段被误判失败。

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- 修复生成替换方案后点击“开始替换生成”无反应的问题；`start_generation()` 现在会先定义 FaceFusion 开关，再执行人物候选和预检判断，不再触发 `NameError: enable_facefusion is not defined`。

### Operations

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。

- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。- 新增 `VIDEO_REPLACE_STRICT_VISUAL_QC`、`VIDEO_REPLACE_DRIFT_GUARD`、`VIDEO_REPLACE_REFERENCE_PREFLIGHT`、`VIDEO_REPLACE_BLOCK_SEVERE_DRIFT`、`VIDEO_REPLACE_DRIFT_AUTO_RETRY`、`VIDEO_REPLACE_DRIFT_MAX_RETRIES`、`VIDEO_REPLACE_PREFLIGHT_BLOCK_SCENE` 环境变量；人物一致性模式和漂移防护不涉及数据库迁移。

## 2026-07-17

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- 同款替换新增“纯产品视频（无人物）”模式；参考视频没有人物时只强制上传产品图，不再强制上传三张人脸或场景图，不要求选择原片人物，并跳过 FaceFusion / 人脸 QC；未提供场景图时跳过场景 QC。
- 同款替换页的失败弹窗、状态栏和片段表错误列改为中文展示；后台任务 JSON 和结构化日志继续保留原始错误码，便于按错误编号追踪。
- 同款替换补齐源片段公网素材缺失的中文错误提示，前台不再直接展示 `video_replace_remote_media_required`。
- 同款替换 talking 片段关键帧生成遇到 LK888 502/504/timeout 时，先用更轻的图片尺寸和更少参考图自动重试一次。
- 关键帧重试仍失败且已有可用人物头像时，记录 `video_replace_keyframe_fallback` / `keyframeErrorId` 并继续数字人口播，避免整个片段卡死在同步图片网关超时。
- 独立公网素材上传服务从图片扩展到图片+视频；`upload_asset_url(..., "video")` 会优先返回 `https://img.yunlingai.net/uploads/...mp4`，避免 LK888 访问不到本地源片段。
- 同款替换非口播/纯产品编辑请求将 `resolution=720p` 规范为 `720P`，避免 `happyhorse-video-edit` 返回参数校验 400。
- 同款替换非口播/纯产品编辑请求补齐 `video_url`、`video_urls`、`reference_video` 和 `params` 内参考视频兼容字段，并把上传后的 `sourceSegmentUrl` 写入任务 JSON，避免快乐马视频编辑因字段漂移误报“必须上传参考视频”。
- 同款替换当时默认不再执行本地 FaceFusion 换脸；上传的人物图会作为远程同款编辑参考与产品图、场景图一起提交，避免单个 8 秒片段在本地换脸阶段卡 30 分钟。
- FaceFusion 超时从硬编码 1800 秒改为 `FACEFUSION_TIMEOUT_SEC`，默认 420 秒，并将 `facefusion_timeout` 与快乐马绿网审核失败转换为可读中文错误。
- 同款替换生成进度细化到关键帧、TTS、数字人、远程编辑、下载、FaceFusion、音频回填和 QC；前端状态栏、进度详情和片段表会显示已用时与预计剩余时间。
- 同款替换默认不再因为识别到台词就逐段生成数字人口播；转写台词只作为脚本文案保留，只有设置 `VIDEO_REPLACE_ENABLE_AVATAR_SEGMENTS=1` 或手动选择口播片段时才走数字人链路。
- 同款替换片段表新增“删除”操作，待生成片段可删除并自动重新编号，用于清理重复分段。
- 远程视觉 QC 超时或异常时不再废弃已生成片段；视频、音频和首中尾帧通过后会标记为待人工审核。

### Operations

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。

- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。- 新增 `VIDEO_REPLACE_KEYFRAME_RETRY_SIZE`、`VIDEO_REPLACE_KEYFRAME_RETRY_REFS`、`VIDEO_REPLACE_KEYFRAME_FALLBACK`、`VIDEO_REPLACE_ENABLE_AVATAR_SEGMENTS`、`VIDEO_REPLACE_ENABLE_FACEFUSION` 和 `FACEFUSION_TIMEOUT_SEC` 环境变量；可在不改代码的情况下调轻量重试、关闭 fallback、显式启用同款替换逐段数字人口播或本地 FaceFusion。
- `img.yunlingai.net` 上传服务允许 `jpg/jpeg/png/webp/gif/mp4/mov/webm`，应用和 Nginx 单文件上限对齐为 500MB；服务器保留 `/root/image-upload-service/backups/20260717-upload-500m/` 文件级回滚备份。
- 本次无数据库结构或数据迁移。

## 2026-07-15

### Added

- 中心服素材库支持签名 `publicUrls`：配置 Cloudflare Tunnel 或正式 HTTPS 域名后，本地上传的产品图、人脸图和场景图可转换为 LK888 可访问的临时 HTTPS 链接。
- 登录页内置可滚动的《用户协议》/《隐私政策》双标签弹窗，源码和 PyInstaller 包均可离线阅读。
- 法律同意版本、客户端 UTC 时间、服务端接受时间和客户端版本的中心审计。
- 抖音本地多账号注册表：新增账号使用独立 profile 和 Cookie 缓存，账号矩阵可同时显示多个抖音账号。

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- 修复“添加新抖音账号”会覆盖并删除旧登录态的问题；现在 `fresh=true` 登录成功后保留旧账号，发布时按 `accountId` 切换对应账号。
- 修复登录页两个协议链接均为 `#`、点击无反应的问题。
- 协议版本升级后，自动登录会回到登录页要求重新确认，不再继续使用过期同意。
- 退出登录改用 Qt `QProcess.startDetached()` 启动独立客户端；macOS 不再因旧进程退出而丢失新登录窗口。
- 新客户端启动失败时保留当前窗口，并显示可追踪 `errorId`，不再静默关闭。
- 同款替换不再将 `127.0.0.1` 产品图、人脸图、场景图和关键帧 URL 直接提交给 LK888/可灵。
- 本地参考图在图片请求内存中临时转 data URL；旧任务的中心素材 URL 也可安全转码，不要求用户重新创建任务。
- 保留 LK888 图片结果的公网 URL；若上游只返回 Base64，数字人改用 multipart 上传本地关键帧。
- 同步图片中心代理超时从 240 秒调整为 480 秒，客户端超时为 540 秒，避免中心服过早返回通用 502。

### Security

- 公网素材链接使用 HMAC-SHA256 签名并包含 `orgId`、素材 ID、文件名和过期时间；未配置密钥时不生成公网链接。
- 登录、注册和会话刷新校验当前法律版本；缺失或过期返回 HTTP 428，不创建新会话。
- 同意记录复用现有脱敏 `audit_logs`，不记录密码、Token 或短信验证码。
- 远程媒体 URL 拒绝 localhost、私网、link-local 和保留地址；仅允许当前中心 `/api/library/file/` 用于旧任务内存转码。
- multipart 请求在中心服解析 `model` / `mode` 非文件字段，确保非管理员计费可追溯。
- 未公开契约的非口播视频 multipart 不盲目启用；本地素材在下单前以 `video_replace_remote_media_required` 阻断。

## 2026-07-14

### Added

- 同款替换 V2 两阶段流程：先生成可编辑片段方案和原片人物候选，再串行执行并等待人工审核后合成。
- 口播片段复用 TTS 和 `kling-avatar-image2video(mode=std)`；非口播片段使用 `happyhorse-video-edit` 后调用独立 FaceFusion。
- 三张授权人脸、场景图/描述、目标人物选择、首中尾 QC 帧、单段重试和取消后中心敏感素材清理。
- 人物、产品/Logo/主要包装文字和场景的远程视觉 QC，以及原子任务 JSON 和 24 小时本地临时目录清理。
- Mac 本地开发用 FaceFusion `3.7.1` 独立虚拟环境、`ghost_2_256` 模型和官方 CLI 兼容启动器。

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- 修复同款替换最终合成强制使用 `anullsrc` 导致原 AAC 音轨被替换为静音；V2 现在保留片段音频、统一为 48kHz 双声道并做约 -16 LUFS / -1 dBTP 处理。
- FaceFusion 丢失音轨时自动从处理前视频回填音频；片段和最终成片无音轨或全静音时阻止合成。
- 同款替换不再把关键帧、产品图和人脸图提交给文生视频 Seedance 路由；默认改用 `viduq3-turbo-cankaosheng` Reference-to-Video 模型。
- 同款替换在提交前拒绝不支持参考图的模型，避免产生无效 `duration` 任务和无参考图的错误成片。
- LK888 异步轮询识别中文“错误/失败/超时/取消”终态，直接返回上游错误而非误报生成超时。

### Security

- FaceFusion 必须在上传素材和计费前通过可执行文件、商用模型目录和许可证引用预检；源码不捆绑人脸模型或许可证。
- 真人脸中心副本在完成或取消后删除，本地任务临时文件默认保留 24 小时后清理。
- 本地标准版配置显式标记为 `DEV-ONLY`；其模型许可未经完整商业审核，不能作为 staging/prod 许可记录。

## 2026-07-13

### Added

- 分解视频后的“同款替换”页面：产品图 + 授权人脸或虚拟模特，按原视频结构分段生成新视频。
- 同款替换生成分段任务、失败片段保留与单独重试、合成前媒体校验和成片自动入资产库。
- 同款替换关键帧锁定链路：每段先基于原视频源帧、产品图和授权人脸/虚拟模特生成替换关键帧，再将关键帧作为视频生成第一参考图。
- 视频深度分解源文件真实性预检。
- Tesseract OCR 优先、RapidOCR 自动回退。
- LK888 Gemini 音频 60 秒分片转写，最多 10 分钟并保留绝对时间戳。
- 转写失败区间、错误编号、重试次数和截断状态报告。
- “重试转写”按钮，只重新导出和处理失败时间段。
- 四级运维文档、OpenAPI 契约和 SHA256 回滚快照。
- 图片素材 Pillow 完整解码校验和损坏图片禁止入库。
- 下载入库失败的统一 `library_import_failed + errorId` 契约。
- 深度报告七栏完整性契约和模型截断自动补全回归测试。

### Changed

- 同款替换生成点击体验增强：开始后按钮显示“生成中…”，显示进度条；缺产品图、缺模特、真人脸未授权、完成和失败都会弹窗提示。
- 同款替换片段表新增关键帧列，可追踪每段用于图生视频的锁定帧。
- 分解视频完成后可直接进入同款替换生成，传递源视频、平台、来源链接和完整分析状态。
- 抖音视频下载携带登录态和浏览器请求头，先写 `.part`，校验后原子替换。
- 下载 403 时只刷新一次签名直链。
- 本地和中心素材库拒绝无效视频与图片；历史坏素材事务化原地修复并保留素材 ID。
- 视频校验从元数据探测升级为 ffmpeg 全量解码，超时预算按时长动态计算。
- 分解页任务固定串行，任务结束后清理关键帧和音频临时目录。
- 深度报告生成预算从 2600 提升到 4800 token；报告标题会去重合并、固定排序，缺失/空栏目使用当前视觉、OCR 和口播证据确定性补齐。

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- 修复同款替换场景下坏片段可能被误用于合成的问题；现在片段生成后和合成前都会校验媒体真实性。
- 修复模型成功返回截断报告时缺少“仿拍脚本”和“Agent.模式提示词”。
- 修复模型返回中间漏栏、乱序或重复栏目时报告顺序和唯一性不稳定，以及 AI 完全失败时丢失口播/关键帧证据。
- 修复用户名登录仍被客户端 11 位手机号前置校验拦截。
- 修复视频首帧抽取失败时备用海报仍显示居中播放图标。
- 修复 local-browser 下载任务在中心素材镜像完成前过早显示 `done`。

### Security

- 真人脸图替换入口要求用户确认已获得授权；虚拟模特路径不要求真人授权。
- 新增结构化 JSON 错误日志和稳定 `errorId`。
- 日志脱敏 Cookie、Authorization、API Key、Token、Base64 和签名 URL 查询值。
- 源码和示例文件不包含真实密钥。
- LK888 反代强制 HTTPS 证书/主机名验证，不跟随重定向并拦截跨源最终 URL。

## 2026-07-24

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- 同款替换新增“重生选中片段”：可对人工审核发现瑕疵的单个片段填写瑕疵说明并只重生该片段；说明会写入下一次远程生成提示词，旧视频路径和质检状态进入 `retryHistory`，便于追溯。
- 同款替换开始生成前新增字幕预检：自动识别疑似 OCR/转写乱码、截图中类似“详经地”的可疑词，以及未人工确认的口播稿；用户确认后才继续生成。
- 同款替换最终中文字幕烧录新增固定字体目录：优先使用 `VIDEO_REPLACE_SUBTITLE_FONT_FILE` 或 Windows 常见中文字体，ffmpeg subtitles filter 带 `fontsdir`，降低中文字体回退和渲染异常概率。

### Operations

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。

- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。- 新增环境变量 `VIDEO_REPLACE_SUBTITLE_FONT_FILE`；不涉及中心服接口、数据库迁移或 OpenAPI 变更。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可。回滚后仍可通过手动编辑片段口播稿规避字幕错字，但不会有单段瑕疵说明重生和固定字体目录烧录。

## 2026-07-20 Production Verification Follow-up

### Fixed

- 中心状态文件读取和写入新增防误覆盖保护：`scheduler_state.json` 支持 UTF-8 BOM 读取，坏 JSON/非对象状态会阻断中心服启动，不再静默初始化默认企业；已有完整状态也不会被 `1/1/1` 默认骨架覆盖。
- 新增 `tools/repair_scheduler_state.py`，用于只读校验、无 BOM 规范化写回和从备份恢复中心状态，避免用 PowerShell 直接写 JSON 引入 BOM 或被运行态覆盖。
- 用户端余额显示不再只依赖登录或重启刷新；本地客户端登录后会每 30 秒自动拉取一次后端余额，管理员充值后用户侧最多等待一个刷新周期即可看到变化。
- LK888 反代任务状态退款判断补充识别中文失败状态（如“错误/失败/超时/已取消”）；同款替换等 AI 生成任务轮询到这类失败状态时，会按原扣费 ref 触发幂等退款并移除任务扣费挂账。

- 素材发布页“打开素材”现在会区分单文件和多文件素材：单文件继续打开文件，多个本机文件时打开素材所在文件夹，避免只打开第一个视频或图片。- Restored Git traceability on the Windows workspace by removing only the explicit DENY ACL from the empty `.git` directory and reinitializing repository metadata.
- Rebuilt Windows validation on Python 3.12.13 because Python 3.14 is incompatible with the pinned OCR dependency chain.
- Hardened ffmpeg/ffprobe subprocess decoding with UTF-8 replacement handling so Windows GBK defaults no longer make media QC fail.
- Preserved POSIX-style replacement output paths when jobs use POSIX `outDir` values, while retaining Windows compatibility.
- Fixed Windows local startup to use the project `.venv-win\Scripts\python.exe` Python 3.12 environment explicitly.
- Repaired Docker Desktop production-smoke execution on Windows 10 by switching the validation machine to the Hyper-V backend, keeping Docker settings as UTF-8 without BOM, and avoiding reads from the user Docker credential config during validation.

### Added

- Added production Docker artifacts for the central service: `backend/Dockerfile`, `docker-compose.prod.yml`, and `/api/health` healthchecks.
- Added local-only `backend/.env.prod` placeholders for compose smoke testing; real secrets remain outside source control.
- Expanded OpenAPI coverage for account balance, billing ledger, local browser status/task, central nodes, and enterprise task center endpoints.
- Added tests for deployment ignores, Docker healthchecks, compose configuration, and OpenAPI production observability coverage.

### Operations

- 中心服每次启动会先创建 `scheduler_state.json.bak-startup-*`；如确需清空重建状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`，默认禁止坏文件回落到默认骨架。
- 本次状态保护修复修改 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py` 和文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启中心服。
- 本次余额刷新和 LK888 失败退款修复修改 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py` 及文档；不涉及 OpenAPI、数据库结构或 `migration.sql`。代码生效需要重启本地客户端和中心服；回滚上述文件即可恢复旧行为。

- 本次素材发布打开目录修复只修改本地客户端、测试和文档；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。- `.venv-win/` and `.tmp-validation/` are local-only validation directories and are ignored by Git.
- `ffmpeg` / `ffprobe` were installed and verified on the Windows validation host via Chocolatey.
- Docker Hub direct pulls timed out from the validation host; `python:3.12-slim` was temporarily seeded from `docker.1ms.run/library/python:3.12-slim` and tagged locally for the compose build.
- Real compose startup was verified with image `matrix-ship-central:prod-smoke-20260720`, container `clean_20260710_150252-matrix-central-1`, Docker health status `healthy`, and `/api/health` returning `ok=true`.
- No database schema or data migration is required for this release; `migration.sql` remains a no-op traceability marker.
- Rollback unit is the previous stable image tag for Docker deployment, plus source-level rollback of the touched backend/docs/tests files if running outside containers.






## 2026-07-28 小红书创作服务平台刷新循环修复
- 修复小红书发布登录等待期间反复刷新创作服务平台的问题：等待函数不再用残留 cookie 触发循环跳转，登录完成后最多重新进入一次发布页。新增发布回归测试；本次只修改本地发布适配器、测试和文档，不涉及中心服、数据库、OpenAPI 或 `migration.sql`。回滚相关文件即可恢复旧行为。
## 2026-07-28

### Fixed

- 本地客户端左下角云豆余额旁的主题/退出按钮改为短固定图标按钮，避免继承全局按钮宽度后与余额文本重叠。
- 账号矩阵“今日发布”现在从中心服真实发布成功计数回填，并写入中心状态文件，重启后当天计数不会丢失；跨天会自动清零。
- 账号矩阵“总粉丝量 / 今日发布”汇总兼容空值、纯数字、`万`、`k` 等格式，避免账号资料字段不是纯数字时刷新异常。

### Operations

- 本次修改涉及 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_account_matrix_metrics.py` 和文档；不涉及数据库结构、OpenAPI 新接口或 `migration.sql`。代码生效需要重启中心服和本地客户端。
- 本次侧边栏控件修复只涉及本地客户端、角色权限测试和文档；生效需要重启本地客户端。
- 总粉丝量仍读取账号资料中的最近一次 `fans/followers` 字段，本次没有新增主动抓取平台粉丝数的定时任务。
## 2026-07-28 workflow account-scope reload
- Fixed automation workflow visibility after login: the native client now reloads account-scoped local state immediately after `apply_account_scope(acc)`, and the workflow page reloads `workflows.json` before rendering or manual refresh. This makes admin/user-owner workflows stored under `backend/datas/accounts/user-owner/workflows.json` appear in "My workflows".
- Added `tests/test_workflow_account_scope.py` regression coverage and kept existing workflow resilience tests runnable with BOM-safe source reading. No database migration, OpenAPI, Docker, or central-server change is involved; rollback is limited to the local client, tests, and docs.

## 2026-07-28 抖音私信全自动回复 MVP

- 新增 `douyin.dm.inbox` 本地浏览器任务和 `/api/douyin/dm/inbox` 本地接口，用用户本机浏览器打开指定客户私信会话并读取最近消息；MVP 只支持一个指定客户主页链接，不做全量私信列表扫描。
- “私信 / AI 销售”全自动模式改为每 20 秒检查一次该客户会话；只处理客户发来的纯文本消息，5 分钟内合并生成一次回复并复用现有 `douyin.dm` 发送链路；图片、语音、视频、卡片、表情等非文本消息只提示人工查看。
- 补齐可观测性和审计：收件箱轮询记录 `douyin_dm_inbox_poll_started/finished`，客户端自动回复记录 buffered/sent/manual_required/failed 事件；结构化日志使用 `targetFingerprint`、`messageFingerprint` 和 `errorCode`，不记录客户主页原文或私信正文。
- 自动收信正文只在本机客户端使用；中心服 `douyin.dm.inbox` 任务结果持久化增加脱敏兜底，只保存目标指纹、消息指纹、正文指纹、消息类型/方向、数量和错误码。
- 自动回复专用浏览器改为复用固定 `dy_dm_profile/current` 资料目录；当检测到未登录、客户不可私信、本地执行器不可用等致命收件箱错误时，客户端会关闭“全自动回复”并提示重新登录或人工查看，避免每轮轮询反复弹浏览器窗口。
- 本次不涉及数据库结构变更；`migration.sql` 保持 no-op。回滚相关后端、客户端、测试和文档文件即可恢复旧的半自动私信行为；代码生效需要重启本地客户端、本地执行引擎和中心服。
## 2026-07-28 小红书图文素材发布修复
- 小红书 `image_note` 图文素材发布现在会先自动切到“上传图文/图片”入口，再上传多张图片；发布器新增正文和标签填充，正文不再复用标题，标签优先填话题/标签控件，找不到入口时追加到正文末尾兜底。
- 本次只修改本地发布适配器、本地 API 发布入口、回归测试和文档；不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。回滚相关文件即可恢复旧行为。
## 2026-07-28 workflow collected video reference category
- Automation workflow collection downloads are now reference-only: collected platform videos are stored as `采集参考视频` assets and never enter the publish queue.
- The asset library now has a `采集参考视频` filter, and asset records persist a compatible `category` field.
- Workflow publishing still requires a generated video from a `video` step; reference-only workflows return a clear “未生成可发布视频” message. No database migration, OpenAPI, central-server, Docker, or `migration.sql` change is involved.

## 2026-07-28 小红书图文同款资产库模板
- `图文同款` 保存草稿后会同步登记到 `资产库 -> 图文模板`，保留草稿标题、正文、标签、原笔记来源、图片槽位和同款任务信息，并用第一张草稿图片作为预览。缺少本地草稿图片或资产库登记失败时会写入结构化日志，便于排查。
- 本次只修改本地客户端、图文同款回归测试和文档；不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。代码生效需要重启本地客户端。

## 2026-07-28 抖音私信发送输入框识别修复
- 修复“私信 / AI 销售”手动发送或全自动回复发送时报 `dm_input_not_found` 的问题：本机浏览器发送链路现在会等待并识别更多抖音私信编辑器形态，包括 `role=textbox`、`textarea`、`input`、`contenteditable=true/plaintext-only`。
- 新增安全诊断与结构化日志：找不到编辑器时返回 `dmEditorDiagnostics` 并记录 `douyin_dm_send_editor_not_found`，只包含候选数量和页面/元素元信息，不记录私信正文。
- 本次只修改本地后端发送适配、回归测试和文档；不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。代码生效需要重启本地客户端和本地执行引擎。

## 2026-07-29 小红书图文同款方案编辑
- 图文同款页面不再展示模板 ID、来源笔记 ID 等技术信息，只保留用户能理解的结构读取提示。
- 生成的三套方案现在可以分别编辑标题、正文和标签；切换方案会保留各自编辑内容，保存草稿时使用当前选中方案的编辑后内容。
- 本次修改本地客户端、本机保存接口、图文同款回归测试和文档；不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。代码生效需要重启本地客户端和本地执行引擎。

## 2026-07-29 获客中心寻找线索按钮固定
- 修复“寻找线索”表格动作按钮没有稳定固定在单元格中的问题：动作列改为固定列宽，按钮改为固定尺寸，并通过单元格容器居中显示。
- 窄窗口下表格使用横向滚动条保留动作按钮完整宽度，不再让按钮被全局样式撑开、压缩或跨格。
- 本次只修改本地客户端、获客中心回归测试和文档；不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。代码生效需要重启本地客户端。

## 2026-07-29 抖音私信发送误触搜索框修复
- 修复私信发送时把回复内容输入到抖音搜索框的问题：发送链路现在会排除搜索框和顶部导航输入框，只选择私信会话区域的编辑器。
- 输入完成后优先点击私信编辑器附近的“发送”按钮；如果只命中疑似搜索输入框且找不到私信发送按钮，会直接报 `dm_send_button_not_found`，不再按 Enter 触发搜索。
- 本次只修改本地后端发送适配、私信回归测试和文档；不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。代码生效需要重启本地客户端和本地执行引擎。
## 2026-07-29 小红书安全模式

- 风控中心的每日发布上限、每日评论上限、最小执行间隔现在会实际拦截小红书动作，不再只停留在界面配置；覆盖小红书搜索、下载、读取评论、发表评论、素材发布和获客评论发送。
- 新增本地状态文件 `backend/datas/xhs_safety_state.json`，按账号记录当天发布/评论次数、最后动作时间和平台风险暂停状态；风控中心同步展示“今日发布 / 今日评论 / 冷却”。
- 当小红书返回 IP 风险、验证码、安全验证、创作者登录失效或 300012/300031 等风险信号时，系统会把账号标记为暂停，避免继续自动采集、评论或发布。
- 本次不新增数据库迁移、OpenAPI 新接口或 Docker 结构变更。回滚可设置 `XHS_SAFETY_MODE=0` 并重启本地客户端/本地执行引擎，或回退 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_xhs_safety_mode.py`、`tests/test_api_download_contract.py` 和本次文档。
## 2026-07-29 漫剧备用模型音轨修复

### Fixed

- Vidu、万相、Kling、PixVerse 等备用视频模型现在只负责生成画面；远程视频下载完成后会丢弃模型音轨，并强制合入对应分镜已生成的 TTS。
- TTS 长于视频时冻结最后一帧直到台词结束；视频长于 TTS 时补静音，不再截断完整口播。
- 混音失败不再把模型原声视频误报为成功；任务记录分镜 TTS 音轨来源、混音状态、原模型结果 URL 和结构化成功/失败日志。
- 新混音文件使用 `/data/uploads/` 账号隔离媒体地址，避免文件已生成但页面无法按用户作用域读取。

### Operations

- 仅修改并重启远程 `ai-canvas.service`，不重启本地客户端或中心服；无数据库迁移、Docker、环境变量或新接口变更。
- 发布前备份 `/root/AI-CanvasPro/server.py`；回滚时恢复该备份并重启 `ai-canvas.service`。
- 项目 299 片段 2 已使用现有 Vidu 视频与现有 TTS 完成无模型调用重混；原视频 URL 和状态文件备份均保留。
## 2026-07-29 同款替换漫剧角色参考图优先

### Fixed

- 修复同款替换中“用户上传女生角色图，但原视频是男销售，生成视频融合成长发男生”的问题。本地客户端传给漫剧生成器的画面提示词现在会在有人物参考图时清理原片人物外观词，只保留动作、站位、镜头关系和汽车销售职业语境。
- 漫剧 `source_text/storyboards/video_prompt` 会明确写入“人物完整外观以上传角色参考图为准”，并去掉 `...(truncated)`；画面提示词不再被本地客户端硬限制为 240 字。

### Operations

- 仅修改本地客户端提示词清洗逻辑、回归测试和文档；不涉及中心服 API、OpenAPI、数据库迁移、Docker 或 `migration.sql`。生效需要重新启动本地客户端，并重新生成同款替换任务。
# 2026-07-30 任务中心纳入本地客户端任务
### Changed
- 任务中心现在同时显示中心调度任务、发布队列任务和本地客户端浏览器任务；内容采集、获客、自动化工作流采集/下载、素材发布等本地执行操作会进入任务中心。
- 企业中心任务数和 24h/7d 用量统计纳入本地客户端任务；小红书搜索、下载、评论会按搜索/下载/评论分类展示。
- 本地执行端离线时，任务创建失败也会记录为失败任务，任务中心可看到 `local_browser_offline` 原因。
- 本地客户端任务中心优先显示中文类型、中文状态和账号/节点名称。

### Operations
- 修改范围：中心服任务汇总、任务中心显示、回归测试和文档；不涉及数据库迁移、Docker、环境变量或 `migration.sql`。
- 生效需要重启中心服和本地客户端。回滚相关文件即可恢复旧行为。
