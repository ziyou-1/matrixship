# Changelog

## 2026-08-05 客户端默认连接公网中心服
### Fixed
- 本地客户端 `CENTRAL` 默认值由 `http://127.0.0.1:9080` 改为公网生产中心服 `http://120.26.194.174:9080`。公网下载安装的客户端所在机器没有中心服进程，旧默认值会让登录页直接报 `WinError 10061` / `NewConnectionError`。本机开发调试改为显式设置 `MATRIX_CENTRAL`。

### Changed
- `backend/.env.example` 与 `docs/DEPLOYMENT.md` 的 `MATRIX_CENTRAL` 默认值与说明同步。
- `tests/test_video_breakdown.py` 的两条用例改回断言公网默认值；旧用例 `test_central_defaults_to_local_loopback` 把回环默认值当成正确行为，正是这个回归一直没被发现的原因。

### Verification And Operations
- `tests.test_video_breakdown tests.test_agent_mode_defaults tests.test_start_visible_client_script tests.test_auth_login_modes` 91/91 通过，`py_compile` 通过。
- 仅改源码不生效，必须重新打包 `MatrixShipAgent-Setup.exe` 并重传到服务器；已装旧包的用户需重装或临时设置 `MATRIX_CENTRAL`。不涉及中心服 API、OpenAPI、数据库或 `migration.sql`。

## 2026-08-04 视频替换共享服务熔断、可观测事件与契约
### Added
- 本地终态任务度量与共享模式熔断：`backend/replacement_service.py` 新增 `record_terminal_result`、`circuit_breaker_state`、`shared_mode_allowed`，在 agent 数据目录持久化最近至多 500 条终态任务（仅存 job 哈希）。累计至少 100 个终态任务且失败率严格大于 1%（`failed/total > 0.01`）时新任务切回 `legacy`；正好 1% 不熔断，取消不计为失败，运行中的任务绝不中断。
- 脱敏结构化边界事件：`build_replacement_event`/`emit_replacement_event` 输出 `prepare_started`、`analysis_completed`、`provider_submitted`、`provider_recovered`、`billing_settled`、`video_completed`、`video_failed`、`shared_mode_circuit_opened`、`rollback_requested`，只含 job id、stage、model、provider-task 哈希、status、media-URL 形状和 cost/ref。
### Changed
- `backend/matrix_native_client.py` 的 `replacement_mode_for_new_job()` 现在同时校验 `VIDEO_REPLACEMENT_SERVICE_MODE=shared` 与 `shared_mode_allowed()`：熔断打开时发出 `shared_mode_circuit_opened`/`rollback_requested` 并回退 `legacy`。
- `backend/replacement_web.py::build_video_service` 传入共享 metrics 目录与本地日志器，使网页与 Qt 共用一致的失败率统计；`public_job` 脱敏扩展为丢弃并清洗 provider task id / 媒体 URL 字段，API 响应永不暴露原始 provider task id 或签名 URL。
### Verification And Operations
- RED/GREEN 覆盖 `tests.test_replacement_service`（含 `ReplacementCircuitBreakerTests` 100/2⇒legacy、100/1⇒shared、<100⇒shared、cancelled 不计失败、活动任务不中断、窗口有界；`ReplacementEventRedactionTests` provider 哈希与签名 URL 脱敏）和 `tests.test_replacement_web_mvp`、`tests.test_openapi_contract`。
- 仅本地执行端生效，无中心服/远程/Docker/数据库变更；`migration.sql` 记为无迁移。切换 `VIDEO_REPLACEMENT_SERVICE_MODE` 需重启本地执行端；回滚设为 `legacy` 并重启，保留 job 文件与生成媒体，不删除数据、不重复提交已完成 provider task、不重复结算。发布侧保留上一稳定安装包/Tag 以决定客户端版本回滚。

## 2026-08-04 客户端默认连接公网中心服
### Fixed
- Windows 客户端无 `MATRIX_CENTRAL` / `CENTRAL_URL` 环境变量时，默认中心服从 `http://127.0.0.1:9080` 改为 `http://120.26.194.174:9080`，避免用户从浏览器下载安装后登录请求打到本机空端口并显示 `WinError 10061`。
- 中心服地址改用独立校验，允许生产 HTTP 中心服地址；远程素材和模型服务 URL 仍保留原有 HTTPS/loopback 限制。
- `backend/.env.example` 和部署文档同步公网默认值；本地开发仍可显式设置 `MATRIX_CENTRAL=http://127.0.0.1:9080` 覆盖。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_video_breakdown.VideoBreakdownHelpersTest.test_central_defaults_to_public_production_server` 和 `test_central_env_override_still_supports_local_development`。
- 生效需要重新构建 `MatrixShipAgent-Setup.exe` 并替换远程 `/root/AI-CanvasPro/MatrixShipAgent-Setup.exe`；回滚时恢复 `backend/matrix_native_client.py` 默认值和上一版安装包备份。不涉及中心服 API、OpenAPI、数据库、Docker、密钥或 `migration.sql`。

## 2026-08-04 登录页只保留漫剧账号登录
### Changed
- 本地客户端登录卡标题改为“账号登录”，副文案改为“使用漫剧账号密码登录 AI爆款复刻”，不再展示“加入企业”入口或登录页顶部模式切换。
- 注册和邀请码加入企业控件仅保留为隐藏兼容对象，不加入首页布局；企业中心的邀请提示同步改为建议管理员使用“添加成员”或“重置密码”交付新成员账号。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_native_enterprise_invite.NativeEnterpriseInviteTest.test_login_home_shows_only_account_login_entry`、`test_enterprise_invite_copy_does_not_point_to_login_page` 和 `tests.test_login_centered_layout.LoginCenteredLayoutTest.test_marketing_copy_is_restored_outside_login_card`。
- 本次只影响本地客户端 UI 和测试文档；不改变中心服 API、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。重启本地客户端或重新打包安装包后生效；回滚 `backend/matrix_native_client.py`、相关测试、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 可恢复旧入口。
- 安装包已刷新到远程 `/root/AI-CanvasPro/MatrixShipAgent-Setup.exe`：旧包备份为 `.bak-20260804_160000`，新包 SHA-256 `b7bf94a1f2d6ded8fbaade9b613bf091cacfb4deab1d90835b82f17cd58df096`，公网 `http://120.26.194.174/MatrixShipAgent-Setup.exe` 返回 `Content-Length: 181371458`。

## 2026-08-04 Installer directory selection
### Fixed
- Windows 安装包不再隐藏安装目录选择页；运行 `MatrixShipAgent-Setup.exe` 时，用户可以在安装向导中修改安装位置。
- 默认安装目录仍保持 `{localappdata}\MatrixShipAgent\app`，默认不需要管理员权限，避免影响普通用户安装。
- 打包脚本会同时查找用户级 Inno Setup 路径 `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`，本机用户安装版也能直接生成安装包。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_web_surface_removed.WebSurfaceRemovedTest.test_installer_allows_user_to_choose_install_directory` 和 `test_build_stays_native_only`，锁定目录选择页开启、默认目录、用户态权限和用户级 Inno Setup 编译器路径。
- 本次只影响 Inno Setup 安装脚本、测试和文档；不改变安装包下载路由、中心服 API、OpenAPI、数据库、Docker、密钥配置或 `migration.sql`。
- 生效需要重新运行 `backend\build_matrix_agent.ps1` 生成新的 `backend\dist\installer\MatrixShipAgent-Setup.exe` 并重新发布；回滚把 `backend\installer\MatrixShipAgent.iss` 的 `DisableDirPage` 改回 `yes` 后重新打包即可。

## 2026-08-04 Local replacement web MVP
### Added
- 本地执行端新增 `/replacement` 网页 MVP，默认由 `MATRIX_REPLACEMENT_WEB_ENABLED=0` 关闭；开启后提供“视频替换”和“图文替换”两个页签，直接通过本机 `/api/replacement/*` 创建本地任务。
- 新增本地 Phase 0 job skeleton：视频替换创建 `rvw_...` queued JSON job；图文替换创建 `xnr_...` preview JSON job，并复用既有图文同款 smoke helper 生成候选文案。
- 新增 OpenAPI/API_REFERENCE 契约，覆盖 `/replacement`、`/api/replacement/video/start`、`/api/replacement/video/job`、`/api/replacement/note/start` 和 `/api/replacement/note/job`。
- `/replacement` 页面外壳支持直接打开链接；真正提交 `/api/replacement/*` 时仍使用本机 agent token，并通过页面输入或 URL hash 写入 `sessionStorage` 后发送 `X-Matrix-Agent-Token`。job 查询响应补齐脱敏 `source/files/createdAt/updatedAt`，图文 `copyCandidates` 保持对象数组结构。
- 原生“同款替换”和“图文同款”页面新增“打开网页版替换”入口，由本地客户端生成 `/replacement#token=...&user=...` 跳转链接；hash 只包含本机执行端 token 和脱敏用户上下文，页面读取后清理地址栏。页面现在会把缺 token、401、校验失败、非 JSON 和网络错误显示为中文提示；视频提交成功时明确提示当前客户预览版只创建本地任务，不执行真实视频生成。
- 原生“同款替换”视频页在已载入分解结果后会写入短期 `rwh_...` 本地 handoff，并打开 `/replacement#token=...&user=...&handoffId=...`；网页通过 token 保护的 `/api/replacement/video/handoff` 读取脱敏摘要，提交视频替换时可用 `handoffId` 绑定真实本地分解上下文。
- handoff 响应和视频 job 只暴露 `source.host/pathHash`、`sourceVideo.available/pathHash`、`analysis.duration/transcriptSegmentCount` 与 `sourceContext` 摘要，不返回本地 `sourceVideoPath`、来源链接查询串、中心 token、手机号、Cookie、签名 URL 或平台授权。
- 图文替换预览现在可通过 `/api/replacement/note/save-draft` 保存为本机 `image_note` 草稿素材；该流程复用既有图文同款草稿保存逻辑，只复制已校验上传图片到本地素材库，不发布、不中心同步、不调用 LK888、不计费。
- `/replacement` 图文页新增本地可视化预览编辑区：生成后展示图片槽位和 3 套候选文案，用户可选择候选、编辑标题/正文/标签，再保存本地草稿。
- 图文替换上传图片现在通过 `/api/replacement/file` 安全加载本地缩略图：job 响应只返回 `files[].previewUrl` 和 `slotMappings[].hasFile`，不暴露本地 `filePath`；页面用带 `X-Matrix-Agent-Token` 的 fetch 转成 blob URL 显示。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_replacement_web_mvp` 的 feature gate、页面 HTML、客户化错误提示、客户端跳转 URL 脱敏、图文预览编辑控件、本地 job 创建/脱敏、图文预览保存本地草稿、API route 和文档契约。
- 本次只影响本地客户端入口、本地执行端、OpenAPI/API 文档、四级文档、CHANGELOG 和 no-op `migration.sql`；`/api/replacement/file` 与 `/api/replacement/video/handoff` 仍受功能开关和本机 token 保护，不触发真实 LK888、远程 AI Canvas、发布、扣费、数据库 DDL/DML、Docker 镜像或密钥配置。
- 生效需要设置 `MATRIX_REPLACEMENT_WEB_ENABLED=1` 并重启本地执行器，同时重启本地客户端以显示“打开网页版替换”按钮；回滚优先把开关恢复为 `0` 并重启。代码级回滚恢复 `backend/matrix_native_client.py`、`backend/api_server.py`、`backend/replacement_web.py`、`backend/platform_features.py`、`tests/test_replacement_web_mvp.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、四级文档、`CHANGELOG.md` 和 `migration.sql`。

## 2026-08-04 Comic tool Windows client download card
### Added
- 远程 AI Canvas `/comic-tool` 创作工具页现在会注入第 4 个「Windows 客户端」工具卡片，按钮直连同源 `/MatrixShipAgent-Setup.exe`，点击后真实下载安装包，不再停留在“即将开放”状态。
- 远程 AI Canvas 新增公开安装包下载路由 `GET/HEAD /MatrixShipAgent-Setup.exe`，响应为 attachment，文件名固定为 `MatrixShipAgent-Setup.exe`；安装包默认从 `AICANVAS_AGENT_INSTALLER`、`MATRIXSHIP_AGENT_INSTALLER` 或项目内 `backend/dist/installer/MatrixShipAgent-Setup.exe` 解析。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_minimax_aicanvas_remote.AiCanvasComicToolDownloadEntryTest`，验证第 4 个工具卡片注入、幂等注入、环境变量安装包路径、无鉴权下载和 attachment 响应头。
- 本次影响远程 AI Canvas 镜像与测试/文档；不改变中心服 API、OpenAPI、数据库、Docker、密钥配置或 `migration.sql`。
- 已部署到远程 `/root/AI-CanvasPro/server.py`，备份为 `/root/AI-CanvasPro/server.py.bak.download-card-test-20260804_094216`；新 `server.py` SHA-256 为 `f086408ce1ad2682fd2ad4133683a02a080441744d7f9e75d3a65bb02e992796`。安装包 `/root/AI-CanvasPro/MatrixShipAgent-Setup.exe` SHA-256 为 `89c52a2f24c082e128ce989d3912a89067540ae5040565a04e2b6378a946a41f`，大小 `181360180` 字节。`ai-canvas.service` 重启后 active，公网 `/comic-tool` 已包含下载卡片注入脚本，公网 `/MatrixShipAgent-Setup.exe` 返回 attachment。
- 二次修复：线上发现“漫剧Agent / Windows客户端 / 漫剧画布”顺序异常和重复风险后，下载卡片注入不再克隆或插入到现有 Agent 卡片后面，改为寻找工具容器并追加独立 Windows 卡片。修复版部署备份为 `/root/AI-CanvasPro/server.py.bak.download-card-append-fix-20260804_101249`；新 `server.py` SHA-256 为 `b3ecc6ebe22e10e7e88a06e4e9a67f26a88bebc9b0415a50acc54703d215540e`。
- 文案修复：Windows 卡片说明改为“云灵星图桌面客户端，用于连接本机执行器、账号矩阵和素材任务；下载的是客户端安装包，不包含漫剧项目文件。”，避免用户误以为下载的是整个漫剧项目。文案修复备份为 `/root/AI-CanvasPro/server.py.bak.download-card-copy-fix-20260804_102740`；新 `server.py` SHA-256 为 `e8644cbc79429d0fbd8fbfacb58c0037a7f4d8572e39c58e22ab763672ce5cc8`。
- 产品定位文案更新：Windows 卡片说明调整为“云灵星图 AI爆款复刻平台 Windows 桌面客户端，用于连接本机执行器、账号矩阵和素材任务；下载的是客户端安装包，不包含漫剧项目文件。”。部署备份为 `/root/AI-CanvasPro/server.py.bak.download-card-platform-copy-20260804_103700`；新 `server.py` SHA-256 为 `ebe4cd1f4810257985c81bc3641b7a870b2d4721f818019b60fc3613d1ec3306`。

## 2026-08-03 账号矩阵新增账号修复 agent token_required
### Fixed
- 本地浏览器 worker 转发 `douyin.login` / `xhs.login` 到本机执行引擎前，会重新读取当前 `MATRIX_AGENT_TOKEN` 或 `agent_token.txt`。新用户登录、账号隔离目录切换或 token 文件刷新后，不再继续使用 worker 初始化时缓存的旧 token，避免账号矩阵点击“添加账号”后显示“登录未完成:agent token_required”。
- `read_local_token()` 改为上下文管理读取 token 文件，避免长期运行 worker 的文件句柄泄漏警告。鉴权仍保持开启，不记录、不展示 token 明文。
- `start-visible-client.bat` 现在双击启动时会在拉起本地客户端前清理旧的 `127.0.0.1:9081` 本地执行器监听，并显式设置 `API_PORT=9081`，避免旧执行器继续使用上一轮 agent token。
- 账号矩阵“登录 / 添加账号”改为由原生客户端直接调用本机执行器 `/api/login/start` 并轮询 `/api/login/status`，不再先经中心服 `/api/local-browser/task` 派发登录任务，减少新用户账号作用域切换时的 token 中转错配点。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_douyin_dm_auto_reply.DouyinDmAutoReplyContractsTest.test_local_worker_refreshes_agent_token_before_login_forward`、`test_local_worker_refreshes_agent_token_file_before_login_forward`、`tests.test_start_visible_client_script.StartVisibleClientScriptTest.test_start_script_restarts_existing_local_executor_before_client` 和 `tests.test_auth_login_modes.AuthLoginModesTest.test_account_matrix_login_uses_local_executor_directly`。
- 本次影响本地浏览器 worker、原生客户端账号矩阵调用链路和本地启动脚本；不改变中心服 API、OpenAPI、数据库、Docker、环境变量密钥或 `migration.sql`。需退出后用 `start-visible-client.bat` 重新启动生效；回滚 `backend/local_browser_worker.py`、`backend/matrix_native_client.py`、`start-visible-client.bat`、相关测试、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 可恢复旧行为。

## 2026-08-03 Asset Library hides note-template filter
### Changed
- Native client Asset Library no longer shows the `note_template` / note-template filter button. Existing note-template asset registration and card compatibility remain, so historical template assets can still render as cards without exposing the filter entry.

### Verification And Operations
- RED/GREEN coverage: `tests.test_asset_library_shared_button.AssetLibrarySharedButtonTest.test_asset_library_hides_note_template_filter_button` and the updated XHS native UI gate assertion.
- Focused native-client tests passed. No OpenAPI, database, Docker, environment variable, remote service, or `migration.sql` impact. Restart the local client to refresh the Asset Library UI.
- Roll back `backend/matrix_native_client.py`, `tests/test_asset_library_shared_button.py`, `tests/test_xhs_note_replacement.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the old filter button.
## 2026-08-03 账户中心分解视频扣费文案与明细居中
### Fixed
- 账户中心“扣费明细”中带 `billingScenario=video_breakdown`、`video_breakdown` 引用或“分解视频”详情的模型扣费统一显示为“分解视频调用”，退款显示为“分解视频调用退款”，不再落到“工作流助手聊天”；普通工作流助手 chat/completion 扣费仍显示为“工作流助手聊天”。
- 账户中心“扣费明细”表头、加载占位行和真实流水单元格统一居中展示，保留实扣金额红/绿色、任务详情无原生 tooltip、详情列拉伸和分页逻辑。
### Verification And Operations
- RED/GREEN 覆盖 `tests.test_account_billing_dashboard.BillingWidgetTests.test_ledger_display_helpers_describe_video_breakdown_model_stages` 和 `tests.test_account_billing_dashboard.AccountPageTests.test_ledger_table_centers_header_loading_and_row_items`；`tests.test_account_billing_dashboard` 30/30 通过，`py_compile` 通过。
- 本次只影响本地客户端账户中心展示、测试和文档；不改变真实扣费数据、中心服 API、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`tests/test_account_billing_dashboard.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 可恢复旧展示。

## 2026-08-03 账号矩阵自助修改密码
### Added
- 本地客户端「账号矩阵」页面右上角新增「修改密码」按钮，企业家和普通用户都可输入当前密码、新密码和确认新密码，自助修改自己的登录密码。
- 客户端复用中心服既有 `POST /api/auth/change-password` 会话接口，不允许替其他用户修改密码；成功后只提示“密码修改成功”，不自动退出登录，不影响账号矩阵里的平台授权账号、本地素材或账号隔离目录。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_auth_login_modes.AuthLoginModesTest.test_account_matrix_exposes_self_service_password_change` 和 `tests.test_openapi_contract.OpenApiContractTest.test_auth_change_password_openapi_documents_self_service_contract`。
- `tests.test_auth_login_modes` 4/4、`tests.test_openapi_contract` 9/9、`py_compile` 和账号矩阵离屏 UI 烟测通过。需重启本地客户端后显示新按钮；中心服已有接口，若运行中的中心服版本不含该接口则也需更新/重启中心服。
- 本次无数据库结构、Docker、环境变量或 `migration.sql` 影响。回滚 `backend/matrix_native_client.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`tests/test_auth_login_modes.py`、`tests/test_openapi_contract.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 可恢复旧入口状态。

## 2026-08-03 素材发布浏览器关闭错误中文化
### Fixed
- 素材发布失败时，若 Playwright 返回 `Locator.set_input_files: Target page, context or browser has been closed`，本地客户端不再直接展示英文异常，改为提示“发布页面或浏览器已关闭，请重新点击发布，并在上传完成前不要关闭抖音发布窗口。”

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_native_publish.NativePublishTest.test_closed_browser_upload_publish_result_is_shown_in_chinese`。
- Native-client-only 错误展示变更；不改变真实发布、浏览器保留、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 可恢复旧提示。

## 2026-08-03 内容采集隐藏图文同款按钮
### Changed
- 本地客户端“内容采集”页底部操作区不再创建或展示“图文同款”按钮；下载、分解、看评论等入口保持不变。
- 历史 `c_note_replace` 结果处理仍保留，避免旧异步事件或既有图文同款草稿交接路径直接报错；左侧导航、后端接口和图文同款页面不在本次范围内。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_content_page_hides_note_replacement_button`，并复查旧交接处理。
- Native-client-only UI 变更；无 OpenAPI、数据库、Docker、环境变量、远程服务或 `migration.sql` 影响。重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 可恢复内容采集页旧按钮。

## 2026-08-03 左下角连接状态文案移除
### Changed
- 本地客户端左下角侧边栏只保留账号名、余额、主题切换和退出按钮，不再显示“已连接 · 数据隔离”或预热状态行。
- 抖音预热仍照常后台执行，预热开始/完成/跳过/失败仍通过 toast 提示，不影响真实连接状态、账号数据隔离或余额自动刷新。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_role_permissions.RolePermissionsTest.test_client_sidebar_does_not_show_connection_isolation_status`。
- Native-client-only UI 展示变化。无中心服 API、OpenAPI、数据库、Docker、环境变量或 `migration.sql` 影响。重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 可恢复旧状态行。

## 2026-08-03 Agent grok-video-3 uses 10s only
### Fixed
- Agent.模式 now exposes `grok-video-3` with only the 10-second duration slot. Saved or stale 5-second requests are normalized to 10 seconds before submitting to LK888, avoiding the `找不到可用的渠道分组` failure for 5s.

### Verification And Operations
- RED/GREEN coverage updated in `tests.test_agent_video_duration.AgentVideoDurationTest.test_agent_grok_video3_payload_matches_lk888`.
- Native-client-only LK888 payload mapping change. No OpenAPI, database, Docker, environment variable, remote service, or `migration.sql` impact. Restart the local client before retesting.
- Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous 5s/10s slots.

## 2026-08-03 Agent video selector removes Kling Motion Control V3
### Changed
- Removed `Kling Motion Control V3` from the Agent.模式 video model selector by excluding `kling-motion-control-v3` from both local fallback rows and LK888 catalog rows.
- Existing generated cards and internal historical payload compatibility are not deleted; restart the local client to refresh the selector.

### Verification And Operations
- RED/GREEN coverage added in `tests.test_agent_video_duration.AgentVideoDurationTest.test_agent_video_catalog_excludes_kling_motion_control_v3_model`.
- Native-client-only selector change. No LK888 backend, OpenAPI, database, Docker, environment variable, remote service, or `migration.sql` impact.
- Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous selectable model.

## 2026-08-03 Agent videos appear in material publish list
### Fixed
- Agent.模式 video cards now upload the generated video into the main 素材发布 material library when the user clicks `加入发布`, so it appears directly in the `素材库与发布` list.
- The existing pending-publish queue row is still kept for compatibility, but old pending rows without a material-library `materialId` no longer force the Agent card into `已加入`; users can click `加入发布` again to sync those older videos into 素材发布.

### Verification And Operations
- RED/GREEN coverage added for Agent video material-library upload, duplicate material upload prevention, pending-queue compatibility, and card joined-state gating.
- Native-client-only change using existing `/api/library/upload`. No LK888 generation payload, OpenAPI shape, database schema, Docker, environment variable, remote service, or `migration.sql` impact. Restart the local client before retesting.
- Roll back `backend/matrix_native_client.py`, `tests/test_agent_mode_defaults.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous pending-queue-only behavior.

## 2026-08-03 Agent video editor placeholder copy
### Fixed
- Removed the `按所选 LK888 视频模型出片` hint from the Agent.模式 video prompt editor placeholder. The editor now only shows `描述你想要的视频素材…` in video mode.

### Verification And Operations
- RED/GREEN coverage added in `tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_video_placeholder_does_not_show_lk888_output_hint`.
- Native-client-only UI copy change. No LK888 request payload, OpenAPI, database, Docker, environment variable, remote service, or `migration.sql` impact. Restart the local client to see the updated placeholder.
- Roll back `backend/matrix_native_client.py`, `tests/test_agent_mode_defaults.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous placeholder copy.

## 2026-08-03 账户中心日期年份选择器可读性修复
### Fixed
- 账户中心“账单概览”和“扣费明细”的日期选择器增加本地深色样式，年份输入、月份/年份导航栏、日期格和选中态都显式设置背景、文字色、边框和选中色。
- 修复深色主题下点击明细日期年份时年份文字和背景对比过低、看不清具体年份的问题。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_account_billing_dashboard.AccountPageTests.test_billing_date_picker_calendar_year_is_readable`；账户中心回归 `tests.test_account_billing_dashboard` 29/29 通过，`py_compile` 通过。
- 额外离屏渲染账户中心页面和日期日历控件 PNG，确认日历控件非空可渲染。现有 `scripts/smoke_account_billing_ui.py` 仍被假账单长文本省略断言拦截，未作为本次通过凭据。
- 本次仅影响本地客户端账户中心日期控件样式和测试；无中心服 API、OpenAPI、数据库、Docker、环境变量或 `migration.sql` 变更。重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`tests/test_account_billing_dashboard.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 可恢复旧样式。

## 2026-08-03 本地客户端登录页改为仅用户名密码
### Changed
- 登录卡片删除“手机号登录需验证码;用户名登录只需密码”提示，账号输入框改为“用户名”，登录模式不再显示短信验证码输入框或“获取验证码”按钮。
- 本地客户端登录提交只发送 `identifier`、`password` 和 `legalConsent`，不再随登录请求携带短信 `code`，11 位数字输入也不会在客户端触发登录验证码分支。
- 注册模式继续保留手机号、短信验证码和设置密码流程；加入企业的邀请码流程不变。中心服 `/api/auth/login` 兼容契约未改，旧客户端或 API 调用方不受本次 UI 改动影响。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_auth_login_modes.AuthLoginModesTest.test_native_client_login_screen_is_username_password_only`；本地客户端重启后生效。
- 本次仅影响原生客户端登录 UI、客户端登录请求体、测试和文档；无 OpenAPI 形状、数据库、Docker、环境变量或 `migration.sql` 变更。回滚 `backend/matrix_native_client.py`、`tests/test_auth_login_modes.py`、`CHANGELOG.md`、`docs/API_REFERENCE.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 可恢复旧登录入口。

## 2026-08-03 账户中心范围错误文案与成功日志降噪
### Fixed
- 账户中心“扣费明细”遇到 `date_range_too_large` 时，前台不再显示 `错误编号 err-*`，直接显示“查询范围最多366天，请重试”。
- 结构化日志工具不再给普通 `INFO` 成功事件自动生成 `errorId`；失败、warning/error/critical 和带异常的日志仍自动生成或保留调用方传入的错误编号。
- 账户中心可见时每 15 秒自动刷新余额、账单概览和扣费明细；因此命令行会持续出现 `billing_analytics_completed` 成功事件。更新后这类成功日志不再带 `errorId`，避免被误判为错误。

### Verification And Operations
- 新增并通过账户中心范围错误展示回归和结构化日志 INFO 成功事件回归；`tests.test_account_billing_dashboard` 28/28、`tests.test_structured_log` 13/13 通过。
- 本次影响本地客户端账户中心 UI 与通用结构化日志工具；不改中心服 API 形状、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。本地客户端需重启后显示新文案；使用同一 `json_log()` 的长驻服务需重启后日志降噪生效。回滚 `backend/matrix_native_client.py`、`backend/utils/structured_log.py`、相关测试和本条文档即可恢复旧行为。

## 2026-08-03 MiniMax H3 official direct integration
### Added
- Added MiniMax official direct video generation for the central server via `POST /api/v1/minimax/video/generate` and `GET /api/v1/minimax/video/tasks/{task_id}`. The provider request uses `POST https://api.minimaxi.com/v2/video_generation`, status polling uses `GET /v2/query/video_generation/{task_id}`, provider model is `MiniMax-H3`, and the center uses the separate `MINIMAX_CENTER_API_KEY`.
- Added the remote AI Canvas comic video model `minimax-h3`, which calls MiniMax official direct submit/status APIs with `MINIMAX_COMIC_API_KEY` and does not route through LK888/APIMart.
- H3 tasks use `awaiting_actual_cost` until official project pricing/currency is confirmed. No local precharge or estimated charge is created.

### Verification And Operations
- Added focused coverage for the central server, direct adapter, unresolved pricing, remote AI Canvas H3 branch, and OpenAPI contract.
- Environment-only secrets: `MINIMAX_CENTER_API_KEY` and `MINIMAX_COMIC_API_KEY`. Do not mix the two keys and do not store them in source or docs.
- No database schema change. `migration.sql` records a no-op release note. Rollback is file-level for local source plus restoring the previous remote `/root/AI-CanvasPro/server.py` backup and restarting `ai-canvas.service`.

## 2026-08-03 Douyin-only platform surface
### Changed
- Xiaohongshu/XHS is disabled by default across the native client, local executor, central server routing, platform adapters, task types, docs, and config. The visible platform surface is now Douyin-only unless `MATRIX_XHS_ENABLED=1` is explicitly set.
- XHS routes and task payloads return HTTP 404 with `error=platform_disabled` before browser automation, adapter execution, or central node selection. The structured log event is `platform_disabled` and keeps only route/task/stage metadata.
- Existing XHS accounts do not need to be retained. Added `scripts/disable_xhs_accounts.py` to dry-run or remove XHS profile/auth/safety state and JSON account rows while preserving Douyin data.

### Verification And Operations
- Added focused RED/GREEN coverage in `tests.test_xhs_platform_disable`; OpenAPI now documents the default XHS gate and `MATRIX_XHS_ENABLED=1` recovery switch.
- Config defaults: `backend/.env.example`, `backend/.env.dev`, `backend/.env.prod`, and `docker-compose.prod.yml` set `MATRIX_XHS_ENABLED=0`.
- No database schema change. `migration.sql` records a no-op release note. Rollback is config-first: set `MATRIX_XHS_ENABLED=1`, restart the native client, local executor, and central server, then rerun XHS smoke checks.

## 2026-08-03 临时 UI 开关与 XHS 能力元数据收口
### Changed
- 账号矩阵默认只构建抖音分组和卡片；本地浏览器执行器与中心服同时过滤 `xhs.*` 注册、轮询、持久化公开响应和允许任务类型，历史状态按读取时过滤，不做破坏性迁移。
- 素材发布默认隐藏“待发布队列”标签但保留队列数据与后台处理；左侧“同款替换”保留为禁用状态并显示“功能完善中，敬请期待”，分解视频、工作流助手和资产库的替换跳转按钮隐藏。
- 数字人口播默认隐藏 TTS 声音上传按钮和声音预览，自动 TTS 音色合成保持可用。
- 新增 `MATRIX_VIDEO_REPLACEMENT_ENABLED`、`MATRIX_PENDING_PUBLISH_UI_ENABLED`、`MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED`，均默认 `0`，设置为 `1` 并重启本地客户端可分别恢复。

### Verification And Operations
- 新增共享开关、显式恢复、UI 状态、配置模板、XHS 能力过滤和账号矩阵回归；定向回归 170/170、四模块编译和空白检查通过。Qt 离屏截图检查通过；重启后 9080/9081 健康，中心服在线能力无 `xhs.*`，本地抖音账号能力 3/4，评论写入因 `comment_login_required` 未就绪；本地与中心 XHS 搜索均返回 404 `platform_disabled`。中心状态先备份并校验 SHA-256，再清理 1 条历史 XHS 账号记录；重启后三运行单元与 dry-run 复查通过。
- 本次不改变风控中心行为；抖音评论每日上限、最小间隔和评论风险暂停仍为硬门禁，发布上限、单机并发、搜索、下载和私信不新增执行限制。
- 无 API 路径或 JSON Schema、OpenAPI、数据库、Docker 镜像结构及 `migration.sql` 行为变更。配置回滚优先把对应 UI 开关改回 `0`；XHS 回滚设 `MATRIX_XHS_ENABLED=1` 并重启三个运行单元。

## 2026-08-03 Agent videos can enter Douyin publish queue
### Added
- Completed Agent.模式 video cards now show a short `加入发布` button next to `播放`. Clicking it adds the generated video to 素材发布 as a Douyin pending item for the user to choose an account and publish.
- The pending item stores `source=agent_mode` and `sourceProdgenId`, uses the Agent prompt as the caption, and defaults to `platform=douyin`.
- Duplicate clicks are idempotent: if the same Agent video is already in the pending queue, the card shows `已加入` and does not create another publish row.

### Verification And Operations
- RED/GREEN coverage added in `tests.test_agent_mode_defaults` for Agent video-to-pending conversion, dedupe, Douyin default, and the completed-video-only card button.
- Native-client-only change. No OpenAPI, database, Docker, environment variable, remote service, LK888 generation, or `migration.sql` impact. Restart the local client before testing the button.
- Roll back `backend/matrix_native_client.py`, `tests/test_agent_mode_defaults.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous Agent card actions.

## 2026-08-03 Agent LK888 video media contracts
### Fixed
- Agent video payloads now use one per-model LK888 media contract for image limits, required reference images, reference videos, and future audio fields.
- Reference-video capable models now upload local videos to public HTTPS URLs before submission. This includes `kling-motion-control-v3`, `wan2.7-cankaosheng`, and `happyhorse-video-edit`; the Agent UI shows the reference-video button for those models instead of only Motion Control.
- Corrected model-specific fields: Hailuo 2.3 uses `model_version=2.3`, `enhance_prompt=Disabled`, and one reference image; HappyHorse R2V uses `ratio` and `720P`; HappyHorse Video Edit uses source-video fields and `audio_setting=origin`; Kling V3 video no longer receives generic `resolution`.
- Vidu Q3 Turbo image requirements, Vidu Q3 reference limits, first/last-frame image requirements, and HappyHorse duration/reference limits are now enforced before LK888 submission.

### Verification And Operations
- `tests.test_agent_video_duration` passes 58/58; `py_compile` and `git diff --check` pass. No real LK888 generation was run, so provider-side acceptance and final media download remain unverified.
- Native-client-only change. No OpenAPI, database, Docker, environment-variable, remote-service, or `migration.sql` impact. Restart the local client before testing Agent video uploads.
- Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous Agent video contracts.

## 2026-08-03 抖音私信转人工后继续收件并支持恢复全自动
### Fixed
- 客户触发“转人工”后，客户端关闭 AI 自动发送，但不再停止每 20 秒一次的收件轮询；后续客户文本、图片、语音等消息仍会立即显示在本地会话框，并标记为 `manual_required`。
- 人工接管状态下不再调用 AI、不进入自动回复队列，避免人工模式下误发消息。
- 人工回复完成后再次勾选“全自动回复”，会清除本次人工接管状态、保留已处理消息指纹，从新消息继续按顺序自动生成和发送。

### Verification And Operations
- 新增两条回归测试，覆盖转人工后持续轮询/显示且不调用 AI，以及重新开启全自动后的状态恢复；`tests.test_douyin_dm_auto_reply` 通过 84/84。
- 仅影响本地原生客户端、专项测试和文档；不涉及 OpenAPI、数据库、Docker、环境变量、远程服务或 `migration.sql`。需要重启本地客户端后生效。
- 回滚 `backend/matrix_native_client.py`、`tests/test_douyin_dm_auto_reply.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-08-03 工作流助手聊天与视频分析结果按账号恢复
### Added
- 工作流助手现在按当前账号保存最近 100 轮用户/助手聊天；切换到其他页面后再返回，聊天、采集结果、完整视频拆解文本和“按这条改造生成”入口会继续显示。
- 助手最终回复中的 `replacementPayloads` 会随历史恢复并重新创建同款替换卡片；进度状态消息不持久化，避免重开页面后显示过期的“运行中”。

### Verification And Operations
- 新增 `tests/test_workflow_assistant_history.py`，覆盖原子写入、账号路径、历史裁剪、损坏 JSON 降级和 replacement payload 恢复。
- 本次仅影响本地客户端、专项测试和文档；无 OpenAPI、数据库、Docker、环境变量、远程服务或 `migration.sql` 变更。重启本地客户端后生效。
- 回滚可恢复 `backend/matrix_native_client.py` 及相关测试/文档，或删除账号目录下的 `workflow_assistant_history.json`。

## 2026-08-01 Agent LK888 online video model menu categories
### Fixed
- Agent video model selection now groups the same loaded model rows that the current-model validator uses. Online-only LK888 rows under categories such as `Omni` and `Other` no longer get picked from one catalog snapshot and then rejected against another snapshot, which previously could reset the UI back to the default Seedance video model.

### Verification And Operations
- RED/GREEN coverage: `tests.test_agent_video_duration.AgentVideoDurationTest.test_agent_video_menu_uses_same_rows_as_current_model_validation` and `test_agent_grouped_models_can_group_loaded_online_only_video_rows` pass.
- Native-client-only change. No OpenAPI, database, Docker, environment variable, remote deployment, or `migration.sql` impact. Restart the local client to load the updated Agent model menu behavior.
- Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous menu grouping path.

## 2026-08-01 Douyin automatic reply serial queue and manual handoff
### Fixed
- Automatic reply still polls every 20 seconds, but each newly detected customer text is now displayed locally and replied to in arrival order. Multiple texts from one poll are no longer merged.
- A sent reply advances the queue only after the prior browser send succeeds, preventing reply ordering errors.
- Images and explicit manual-handoff requests now close automatic reply, add an auditable in-chat system notice, raise the application in the taskbar, and show one non-blocking handoff notification.

### Verification And Operations
- RED/GREEN regression coverage includes serial replies after each send and explicit customer handoff requests. `tests.test_douyin_dm_auto_reply` passed 82/82.
- Native-client-only behavior change. No OpenAPI, database, Docker, environment variable, remote deployment, or `migration.sql` impact. Restart the local client to load it.
- Roll back `backend/matrix_native_client.py`, `tests/test_douyin_dm_auto_reply.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore batch merging and the prior manual-review behavior.

## 2026-08-01 Agent LK888 参考图上限与视频参数对齐
### Fixed
- Agent.模式补齐 LK888 图片模型参考图上限：`qwen-image`、`kling-v3`、`kling-v3-omni`、`wan2.7-image` 按 4 张限制，`kling-image-o1` 按 10 张限制，避免多图参考被错误截断或超量提交。
- `viduq3`、`viduq3-turbo`、`viduq3-turbo-cankaosheng` 统一使用 LK888 支持的 4/8/12/16 秒时长槽位；`wan2.7-cankaosheng` 和 `wan2.7-shouweizhen` 改为 3/6/9/12/15 秒槽位；`Sora-2 Official` 改为 LK888 当前合法的 4/8/12 秒，历史 5 秒任务会自动归一到 4 秒。
- 视频模型按 LK888 专用字段提交：`wan2.7-cankaosheng` 使用 `ratio/resolution/images`，`wan2.7-shouweizhen` 使用首尾帧字段，`sora-2` 使用 `input_reference`，`veo3.1` 固定 8 秒并使用 `generation_mode/generation_type/images/quality`，同时锁定 `pixverse-v6-shouweizhen`、`happyhorse-i2v`、`hailuo-2.3` 的参考图数量和分辨率字段。
- Grok 视频模型补齐 LK888 契约：`grok-video-3` 改用横竖屏 `size` 枚举且不再附带通用参考图字段；`grok-imagine-video-1.5-preview` 加入本地 canonical 规则，按 1-15 秒时长、1 张首帧图、`aspect_ratio/resolution/images` 提交。
- 首尾帧类视频模型的输入槽和生成卡片现在只显示“首帧/尾帧”两个槽位；即使 LK888 在线目录后续返回新的 `*-shouweizhen` 模型，也会按 2 张参考图兜底处理，不再显示第 3 张造成参与生成的错觉。
- 通用 Agent 视频模型列表不再显示 `VIDU Narrated Comic` 和 `VIDU-Music MV`，避免用户在普通视频生成入口选到需要专用输入的 VIDU 模型。

### Verification And Operations
- 新增 Agent 模型参数回归，覆盖图片参考图上限、视频参考图上限、首尾帧可见槽位、Vidu/Wanxiang/Sora-2/Veo 3.1/Grok 时长槽位、视频模型列表排除项和特殊视频 payload 字段。
- 本次只影响本地客户端 Agent LK888 payload 组装、测试和文档；不涉及中心服、OpenAPI、数据库、Docker、环境变量、远程服务或 `migration.sql`。需要重启本地客户端后生效。
- 回滚 `backend/matrix_native_client.py`、`tests/test_agent_video_duration.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧映射。未执行真实 LK888 生成调用，因此没有产生真实模型费用。

## 2026-08-01 SD2.0 全能参考隐藏彩铅预处理
### Fixed
- 同款替换漫剧项目选择 `SD 2.0 全能参考` / `kwvideo-v2-quannengcankao` 时，现在会按 Seedance/SD2.0 链路先调用 `gpt-image-2` 生成隐藏彩铅首帧、尾帧和上传参考图，再把隐藏彩铅 URL 传给 LK888 视频生成。
- 前端仍保留普通首尾帧预览，不把彩铅中间图展示给用户；视频 payload 会优先使用隐藏彩铅参考，避免原始人物、产品、场景图直接泄露到 SD2.0 视频模型。
- 隐藏彩铅首帧或尾帧缺失时，片段会直接失败并显示中文错误，不再绕过 `gpt-image-2` 继续提交视频。

### Verification And Operations
- 新增并通过 SD2.0 全能参考回归：模型识别、隐藏彩铅参考优先、`gpt-image-2` 调用、彩铅首尾帧缺失阻断。
- 本次只影响本地客户端同款替换链路、测试和文档；不涉及中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。需要重启本地客户端；已打包用户需要重新构建/分发客户端。
- 回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-08-01 Agent 动作控制参考视频与 LK888 图片提交契约
### Fixed
- Agent.模式新增 `Kling Motion Control V3` 的参考视频上传按钮；选择该模型时，图片参考和视频参考会先上传为公网 HTTPS URL，再按 LK888 要求传递 `image_url`、`video_url`、`character_orientation=video`、`mode=std`、`keep_original_sound=no`。
- Agent 图像模型保留模型允许范围内的全部参考图片；视频模型按 LK888 上限限制参考图数量，避免首尾帧模型收到超过 2 张图片。
- `Kling 2.6 Pro` 固定使用 `sound=on`，不再发送非法的布尔值。
- 旧同步图片入口 `lk888_image_result()`、`lk888_image()`、`lk888_image_url()` 和 `lk888_image_data_url()` 全部改为提交 `/v1/media/generate` 并直接返回 LK888 原始 JSON，不在入口内轮询或下载。仍需要图片字节的内部流程使用独立等待辅助函数。

### Verification And Operations
- `tests.test_agent_video_duration` 通过 33/33；旧图片入口回归 `tests.test_video_replacement_v2.VideoReplacementV2Test.test_image_result_preserves_public_upstream_url` 与 `test_lk888_image_reference_url_fields_exclude_data_urls` 通过。
- `py_compile` 通过，`git diff --check` 无新增空白错误。
- 仅影响本地客户端和测试/文档，不涉及 OpenAPI、数据库、Docker、环境变量、远程服务或 `migration.sql`。需要重启本地客户端；回滚 `backend/matrix_native_client.py`、相关测试和本条文档记录即可恢复。

## 2026-08-01 Agent LK888 task creation error display cleanup
### Fixed
- Agent.模式 now strips LK888 raw task-creation and task-status fields such as `code`、`data`、`msg`、`status`、`message` and `未拿到任务ID` from user-facing failures.
- Mixed quote / mixed colon payloads like `{code":400,"data":null,"msg"："参考图像（image_url)不能为空"}` and `{”code"：400,"data":null,"msg"："首尾帧模式最多支持2张图片"}` are now normalized to short Chinese prompts only.
- The error sanitizer also normalizes mixed Chinese/English punctuation in extracted reasons so malformed upstream snippets such as `（image_url)` are displayed as `（image_url）`.

### Verification And Operations
- RED/GREEN regression: added two focused `_prodgen_user_error_text()` cases for unquoted `code/msg` JSON-like payloads and mixed-quote payloads, then reran `tests.test_agent_video_duration` end to end.
- `.\.venv-win\Scripts\python.exe -m unittest tests.test_agent_video_duration -v` passed 27/27; `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_agent_video_duration.py` passed.
- Native-client-only display cleanup. No OpenAPI, database, Docker, environment variable, remote deploy, or `migration.sql` impact. Restart the local client to load it. Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, and these docs to restore the previous raw-error display.

## 2026-08-01 同款替换 Seedance 首尾帧彩铅与视频写实风格
### Fixed
- 同款替换漫剧项目模式选择 Seedance 视频模型时，首尾帧图片生成 payload 会显式指定 `gpt-image-2`，并追加彩铅手绘风格要求，让用户上传的人物、产品、场景参考在中间首尾帧阶段呈现彩铅观感。
- 同一个 Seedance 最终视频生成 payload 会追加“真人写实风格”要求，强调人物、服装、产品和场景保持真实拍摄质感，不生成插画或手绘质感。
- Seedance 场景不再自动切备用模型；用户在本地客户端选了什么模型，就只提交什么模型，失败后直接给中文错误提示。

### Verification And Operations
- 新增两条同款替换回归，覆盖 Seedance 图片 payload 的 `gpt-image-2 + 彩铅手绘` 和 Seedance 视频 payload 的 `真人写实`；同时确认非 Seedance payload 不受影响。
- 已通过新增回归、邻近同款替换 prompt 回归和 `py_compile`。本次只修改本地客户端 prompt/payload 组装、远程漫剧镜像、同款替换测试和文档；不涉及中心服、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。
- 生效需要重启本地客户端；远程 AI Canvas 还需要部署更新后的 `server_current.py`/`server.py` 并重启服务。回滚 `backend/matrix_native_client.py`、`tools/aicanvas_remote/server_current.py`、`tests/test_video_replacement.py`、`tests/test_aicanvas_frame_billing.py`、`tests/test_aicanvas_real_person_fallback.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-08-01 Agent Kling 2.6 Pro LK888 sound param
### Fixed
- Agent video generation no longer sends `params.sound=false` for local model `Kling 2.6 Pro` (`kling-v2-6`). LK888 rejects that value during task creation with parameter validation errors, so the client now uses the generic video payload fields for this model.

### Verification And Operations
- RED/GREEN regression: `tests.test_agent_video_duration.AgentVideoDurationTest.test_agent_video_payload_maps_required_lk888_model_params` now asserts the `kling-v2-6` payload has no `sound` field.
- `tests.test_agent_video_duration tests.test_agent_mode_defaults` passed 58/58; `py_compile` passed for `backend/matrix_native_client.py`. No live LK888 generation was executed, so no real model cost was produced.
- Native-client-only LK888 payload mapping change. No OpenAPI, database, Docker, environment variable, or `migration.sql` impact. Restart the local client to load it. Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, and these docs to restore the previous payload.

## 2026-08-01 Agent LK888 upstream saturation display text
### Fixed
- Agent generation failures from LK888 task status now show the user-facing Chinese reason only. A failure such as `kling-image-o1 生成失败:status=Error; message=当前分组上游负载已饱和，请稍后再试` is displayed as `生成失败：当前分组上游负载已饱和，请稍后再试`.
- The raw LK888 status summary is kept in local diagnostics as `rawError` and the client log, but the Agent card no longer exposes `status=`, `message=`, `Error`, or the LK888 model ID to the user.

### Verification And Operations
- Added a regression for `_prodgen_user_error_text()` and reran Agent model/generation regressions: `tests.test_agent_video_duration tests.test_agent_mode_defaults` passed 54/54; `py_compile` passed for `backend/matrix_native_client.py`.
- Native-client-only display change. No OpenAPI, database, Docker, environment variable, or `migration.sql` impact. Restart the local client to load it. Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, and these docs to restore the previous display.

## 2026-08-01 Same-style replacement video recovery rejects image URLs
### Fixed
- Comic same-style replacement video recovery no longer treats storyboard image fields such as `resultUrl`, `url`, or an `.png` end frame as a completed video result after a remote submit timeout.
- The native client now localizes `comic_segment_invalid:media_invalid_duration` to `远程返回的生成片段不是有效视频，请单段重试。` instead of exposing the internal error code in the video cell.

### Verification And Operations
- Added RED/GREEN regressions for video recovery rejecting image-only storyboard payloads and for the Chinese invalid-video display message.
- No remote AI Canvas deploy, OpenAPI, database, Docker, environment variable, or `migration.sql` change. Restart the local client to load the recovery and display changes.
- Roll back `backend/matrix_native_client.py`, `tests/test_video_replacement.py`, `tests/test_video_replacement_v2.py`, and these docs to restore the previous behavior.

## 2026-08-01 工作流助手完整视频分析与口播时间轴
### Fixed
- 工作流助手现在复用完整视频分解链路：关键帧覆盖整条视频时长，音频按 60 秒分片完整转写，OCR、视觉分析和七栏深度报告一起保存。
- 默认不再把视频截断在 600 秒；只有显式设置 `VIDEO_TRANSCRIBE_MAX_SEC` 才限制转写范围。报告会显示实际覆盖秒数，避免把任意上限误报成“前 10 分钟”。
- 采集参考视频同时保存可读拆解文本和结构化 JSON 分析；点击“按此视频改造”时优先读取 `transcript.segments`，同款替换片段表会生成可编辑口播稿。
### Verification And Operations
- 工作流助手/韧性回归 34/34、音频转写回归 22/22、同款替换口播链路专项 3/3 通过；未执行真实 LK888 视频分析调用。
- 本次只影响本地客户端、转写工具、测试和文档；不涉及 OpenAPI、数据库、Docker、`migration.sql` 或远程服务部署。需重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`backend/utils/video_transcription.py`、相关测试和文档即可恢复旧行为。

## 2026-08-01 同款替换 LK888 视频提示词动作来源修正
### Fixed
- 同款替换漫剧项目模式的视频生成请求不会再声称 LK888 已收到或可直接沿用原片动作、站位、镜头关系；本地客户端现在把相关约束改为“参考分镜拆解文本和关键帧近似生成”。
- 上传角色/场景/道具素材时，素材绑定提示仍保持上传素材最高优先级，但“不得沿用原片场景”等容易误导的旧表达改为“不得使用原视频场景”。
- 旧链路实体替换和手动瑕疵重生提示也同步降误导：动作、站位和镜头节奏只参考源视频拆解文本与抽帧结果，不再写成远程模型必然保留原片动作。

### Verification And Operations
- 新增 LK888 storyboard video payload 回归，先确认旧 prompt 会包含“沿用原片/原视频只提供/保留原片动作/原片站位”，修复后断言这些词不再出现在最终 video prompt 中。
- 已通过聚焦同款替换回归和 `py_compile`。本次只修改本地客户端 prompt 组装、同款替换测试和文档；不涉及中心服、远程漫剧服务、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。
- 生效需要重启本地客户端。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧提示词行为。

## 2026-08-01 AI Canvas remote file descriptor exhaustion handling
### Fixed
- Remote AI Canvas platform JSON calls now send `Connection: close` and classify `OSError(24, "Too many open files")` / `URLError(...)` as `503 platform_fd_exhausted` with a structured `platform_json_request_fd_exhausted` log event, instead of returning raw Python internals to the client.
- MatrixShip same-style replacement UI now localizes remote `Too many open files` failures to a Chinese operational message instead of showing `URLError(OSError(24, ...))`.

### Verification And Operations
- Added RED/GREEN regressions for the remote platform request helper and native-client error display.
- Verified with focused display tests, remote AI Canvas frame/TTS tests, real-person fallback tests, `py_compile`, and a remote post-deploy smoke test on `120.26.194.174` (`tests.test_aicanvas_frame_billing`, 43/43 OK).
- Remote AI Canvas was deployed at `20260801_113520`: previous SHA `f53d4d2ace67e12886557f28882fa61d40104083983ced96876b7efeaceb1f78`, new SHA `0cdbbd45b95817883ff0711faa6678b108f3f76a50b57f60c15fb3f54184f2fe`, service `active`, port listeners `1`, `/login` health `200`.
- No OpenAPI, database, Docker, environment variable, or `migration.sql` change. Roll back the remote runtime with `/root/AI-CanvasPro/server.py.bak.comic-inline-media-20260801_113520`, then restart `ai-canvas.service`; roll back `tools/aicanvas_remote/server_current.py`, `backend/matrix_native_client.py`, `tests/test_aicanvas_frame_billing.py`, `tests/test_video_replacement_v2.py`, and these docs to restore the previous source behavior.

## 2026-08-01 Local browser account profile routing
### Fixed
- Growth Center "open profile" now opens the customer URL through the local executor `/api/cloud-login/open-url` with the selected `accountId`, instead of delegating to the Windows default browser. This keeps the browser session aligned with the account matrix profile.
- Douyin AI outreach/comment UI fallback now threads the selected account through comment preflight, cloud-browser session lookup/creation, cookie-cache injection, and readback verification instead of falling back to `douyin-self`.
- Cloud browser login-state persistence now writes Douyin cookies back to the selected account cache when the session is bound to a non-default account.

### Verification And Operations
- Added regression coverage for Finder open-profile routing, cloud open-url account binding, comment preflight account binding, and forced comment UI fallback account binding.
- Requires restarting the local client and local executor to take effect. No database, Docker, environment variable, or `migration.sql` change. OpenAPI/API reference updated for `/api/cloud-login/open-url`. Roll back `backend/api_server.py`, `backend/matrix_native_client.py`, the touched tests, and these docs to restore the previous behavior.

## 2026-08-01 Agent LK888 model endpoint audit
### Fixed
- Agent image generation now builds every known local image model as an LK888 media task payload for `POST /v1/media/generate`; this covers `doubao-seedream-5-0-260128`, `mj_imagine`, Gemini/Nano Banana, Vidu, Kling, Wanxiang, Qwen and GPT image rows without exposing raw LK888 IDs in the UI.
- Agent video generation now normalizes model-specific required params before submit: Seedance uses `audio_duration/ratio/generate_audio`, Vidu Q3 uses supported durations and `model_variant/off_peak`, MJ/Kling/Vidu image models use their required aspect/resolution fields.
- `kling-avatar-image2video` is no longer shown in the generic Agent video model catalog because it requires avatar and `sound_file` inputs. The digital-human flow still calls that model directly with its avatar/audio payload.

### Verification And Operations
- Added regression coverage for media endpoint routing, required image/video params, reference-image payloads, and excluding the digital-human-only model from Agent video choices. Focused digital-human tests keep `kling-avatar-image2video` available only on the digital-human path.
- No live LK888 generation call was made, so no real model cost was produced. This is a native-client-only change; no OpenAPI, database, Docker, environment variable, or `migration.sql` impact. Restart the local client to load the new mapping. Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, `tests/test_agent_mode_defaults.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous behavior.

## 2026-08-01 Agent.模式生成提示词中文直传与扣费标签
### Fixed
- `Agent.模式` 图片和视频最终生成阶段默认直接使用用户确认的中文提示词，不再隐藏调用 `gpt-5.4-xhigh` 扩写成英文后再提交模型，避免生成前额外产生一次不可见的提示词转换扣费。
- 显式“提示词优化”、参考图理解、以及未来按模型兼容性单独启用的提示词转换都会携带 `agent_mode` 业务标签；账户中心扣费明细显示为“Agent.模式 - 提示词优化 / 参考图理解 / 模型兼容提示词转换”，不再落到通用工作流助手文案。
- 保留 `_prodgen_expand_prompt()` 作为显式兼容转换入口，但当前图片/视频生成路径不会默认调用；如后续确认某个模型必须英文提示词，需要单独接入并保留该扣费标签。

### Verification And Operations
- 新增 Agent 图片/视频中文直传回归，断言 `_prodgen_expand_prompt()` 不被调用，并锁定优化、参考图理解、兼容转换的账单 metadata；账户中心新增三类 Agent 阶段文案回归。
- 已通过 `.\.venv-win\Scripts\python.exe -m unittest tests.test_account_billing_dashboard -v`，共 26/26；Agent.模式提示词阶段专项 4/4 通过；`py_compile` 通过。当前完整 `tests.test_agent_video_duration` 受同文件内另一路图片模型端点/参数规则未收口改动阻塞，未执行线上模型联调，也未产生真实 LK888 费用。
- 本次只影响本地客户端、Agent/账户中心测试和文档；不涉及中心服接口、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端；回滚 `backend/matrix_native_client.py`、`tests/test_agent_video_duration.py`、`tests/test_account_billing_dashboard.py` 和本条文档即可恢复旧行为。

## 2026-08-01 Matrix comic storyboard TTS audio boundary
### Fixed
- Matrix video replacement comic projects now treat storyboard `audio_mode=auto` with dialogue as storyboard TTS at the remote AI Canvas layer. Ordinary comic projects keep the existing `auto` behavior and preserve provider-generated audio.
- Matrix storyboard video completion now also remuxes primary provider video results with the prepared storyboard TTS audio, not only fallback results, so LK888/provider ambience or extra speech does not remain in the final storyboard clip.
- Storyboard video tasks now persist `project_source_mode/projectSourceMode`, so Matrix audio handling still works if completion happens after the remote project cache is cold.

### Verification And Operations
- Regression tests now cover Matrix `auto+dialogue` TTS preparation, task source-mode metadata, cache-miss completion, and primary-result TTS remux while preserving ordinary `auto` fallback audio. `tests.test_aicanvas_frame_billing` and `tests.test_aicanvas_real_person_fallback` pass 56/56.
- Local video replacement regressions passed with `.venv/bin/python`. `py_compile` passed for remote AI Canvas mirror, local client, and touched tests. No remote deploy, restart, OpenAPI, database, Docker, environment variable, or `migration.sql` change was performed.
- Roll back `tools/aicanvas_remote/server_current.py`, `tests/test_aicanvas_frame_billing.py`, `tests/test_aicanvas_real_person_fallback.py`, and these docs to restore the previous remote audio semantics. Runtime effect on production AI Canvas still requires a separate audited remote deploy with backup hash and rollback path.

## 2026-08-01 Agent.模式图片模型端点路由修复
### Fixed
- `gemini-3-pro-image-preview` 和 `gemini-3.1-flash-image-preview` 仍作为 Agent 图片模型展示，但不再走 LK888 `/v1/images/generations`；本地客户端会按模型规则改走 `/v1/media/generate` 并轮询任务结果。
- `gpt-image-2` 等同步图片模型继续走 `/v1/images/generations`，避免把所有图片模型都改成异步任务。
- 图片参考图上传后的 URL 会同时进入异步媒体 payload 的 `image_urls/images/reference_images/referenceImages` 及 `params.*` 兼容字段。

### Verification And Operations
- 新增 Gemini 图片预览端点回归，先确认旧实现会把 `gemini-3-pro-image-preview` 调到 `lk888_image()`，修复后改为 `lk888_media_task()`。
- 本次只修改本地客户端 Agent.模式模型路由、回归测试和文档；不涉及中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端；真实 LK888 联调仍需验证异步图片任务返回的结果 URL 可下载。

## 2026-08-01 同款替换远程网络错误中文提示
### Fixed
- 同款替换展示层遇到 `HTTPConnectionPool` / `Read timed out` / 连接失败等远程服务网络异常时，不再把英文异常、错误编号或 requests 内部文本直接显示给用户。
- 超时统一显示“远程服务响应超时，本次生成没有在限定时间内返回。请稍后重试；如果连续出现，请重启本地客户端后再试。”；连接失败统一显示“无法连接远程服务，请检查网络状态或本地客户端是否为最新版本。”。
### Verification And Operations
- 新增两条同款替换展示层回归，先在旧实现下失败，修复后通过；本次只修改本地客户端展示层、同款替换测试和文档。
- 不涉及中心服、远程漫剧服务、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端；回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py` 和本条文档即可恢复旧展示。

## 2026-08-01 账户中心一键刷新
### Fixed
- 本地客户端账户中心标题栏新增紧凑的“刷新”按钮，一次刷新云豆余额、账单统计、趋势图、消费分布、扣费明细和分页总数。
- 刷新保留当前日期范围、分组、类型/状态筛选、每页条数和明细页码；不刷新管理员用户列表，也不改变权限和资金操作。
- 刷新期间按钮显示“刷新中...”并禁用；余额、统计、流水三类当前请求全部成功或失败后恢复。错误响应保留旧数据和现有错误编号，陈旧响应不会结束新一轮刷新；页面隐藏时取消忙碌状态。

### Verification And Operations
- 新增账户中心刷新行为回归，覆盖按钮图标/尺寸、三请求协调、错误完成、陈旧响应、最新请求接管、日期校验和页面隐藏；`tests.test_account_billing_dashboard` 25/25 通过。
- 相关计费、OpenAPI、计费 API、分析回归共 77/77 通过，`py_compile` 和 `git diff --check` 通过；离屏 Qt 几何检查确认按钮为 100×34，忙碌文案不会裁切且不与标题栏重叠。
- 本次只影响本地客户端、账户中心测试和文档；不涉及中心服接口、OpenAPI schema、数据库、Docker、环境变量或 `migration.sql`。需要重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`tests/test_account_billing_dashboard.py` 及本条文档即可恢复旧行为。

## 2026-08-01 账户中心首屏加载占位
### Fixed
- 账户中心刚打开时会立即显示“加载中”和“正在加载...”状态；云豆余额、统计卡片和扣费明细不再先呈现空白或 `—`，避免用户误以为页面没有内容。
- 扣费明细请求返回前会插入一行“正在读取扣费明细...”，真实流水或错误响应回来后仍沿用原有渲染和旧数据保留逻辑；`date_range_too_large` 这类用户可修正参数错误前台不再显示错误编号。

### Verification And Operations
- 新增首屏 loading 回归，先复现 `run_bg` 尚未返回时页面看起来空白的问题，修复后 `tests.test_account_billing_dashboard` 27/27 通过；`py_compile` 通过。
- 本次只影响本地客户端账户中心 UI、测试和文档；不涉及中心服接口、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。需要重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`tests/test_account_billing_dashboard.py` 和本条文档即可恢复旧行为。

## 2026-08-01 Agent.模式图片参考图传给 LK888
### Fixed
- `Agent.模式` 图片模式不再把用户上传的本地图片转成 `data:image/...` 后直接传给 LK888 图片模型；生成前会先上传为远程模型可抓取的 HTTP(S) 图片 URL。
- 图片模式仍保持原顺序规则：第 1 张为待修改图，第 2 张起为参考图；这些图片 URL 会作为 `image_urls` 传入 LK888 图片接口，避免全程模型只收到文字 prompt。
- 参考图上传失败或返回不可抓取 URL 时，任务直接提示“参考图上传失败”，不会静默退化为纯文字出图。

### Verification And Operations
- 新增 Agent 图片参考图 payload 回归和上传失败阻断回归；当前验证使用 mock 上传与 mock LK888 调用，不产生真实 LK888 费用。
- 本次只修改本地客户端、Agent 回归测试和文档；不涉及中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端；回滚相关文件即可恢复旧的本地 data URL 提交行为。

## 2026-07-31 LK888 严格最终实扣（取消全部模型预扣）
### Fixed
- `/v1/media/generate` 异步提交响应即使携带 `billing.amount`、`cost` 或其他金额字段也不扣费，只按任务 ID 写入 `lk888_pending_charges`；必须等任务终态或 LK888 消费明细返回最终 `cost` 后再结算。
- 同款替换首帧、尾帧和视频不再读取远程价格表后本地预扣，也不再执行“失败退款”或“成功后退预扣再冲正”；远程任务成功后只按 LK888 返回的最终 `cost` 扣除同额云豆。
- 本地流水使用远程 `actual_model`；`vidu/viduq3-mix_reference2video` 规范显示为 `viduq3-cankaosheng`，不再把请求模型 `doubao-seedance-*` 误记为实际模型。
- 中心服删除 LK888 固定价/按秒价估算表、`gen_price_yundou()` 和 `LK888_LEGACY_PRECHARGE_ENABLED` 预扣分支。历史 `gen_charges` 只保留旧任务失败退款兼容，不能创建新预扣。
- `/api/billing/charge` 的 LK888 实扣模式直接使用 `amount/meta.actualAmount`，不会再把首尾帧实际费用覆盖为本地 `comic_keyframe_image` 固定价；稳定任务 `ref` 保证重复结算幂等，余额不足允许记为欠费。

### Verification And Operations
- TDD 回归先复现 7 个预扣/模型错误，再补充首尾帧固定价覆盖和“异步提交携带金额仍不得扣费”用例；该异步旁路测试在旧实现下确认失败，修复后专项 3/3 通过。最终完整计费回归 `166/166`、OpenAPI 与账户中心回归 `25/25` 通过，`py_compile` 通过；未执行会产生真实 LK888 费用的线上调用。
- 影响本地客户端、中心服、OpenAPI 描述、测试和文档；无数据库 DDL/DML、Docker 拓扑或 `migration.sql` 变更。生效必须同时重启中心服和本地客户端；回滚为恢复修改前对应文件并同时重启，不再提供运行时预扣开关。

## 2026-07-31 Comic Replacement Motion-Only Prompt Cleanup
### Fixed
- The local client now converts Markdown-style original-video shot breakdowns into a motion-only comic script: shot time, shot scale, uploaded character slot, uploaded prop slot, sanitized action, and rhythm. Original source person appearance, product names, scene names, subtitles, OCR tables, spoken quotes, and promo details are removed before sending `source_text`, storyboard descriptions, image prompts, or LK888 video prompts.
- Storyboard updates now send `camera_movement="静态镜头"` instead of accidentally putting the full visual prompt into the comic generator's camera movement field.
- Continuation prompts are sanitized before entering visual prompts, so "口播/讲解/说话" wording is not passed as video-generation instruction text.

### Verification And Operations
- Added regression coverage for Markdown shot cleanup and camera movement field mapping; `tests.test_video_replacement` 97/97 passed and `py_compile` passed for `backend/matrix_native_client.py` and `tests/test_video_replacement.py`.
- Reconstructed latest local job `e226fdd193f943949ccee2650fbc6146` after the change: old product/scene/person-clothing/subtitle-table/original quote/koubo/promo-detail checks are all false; `camera_movement` is `静态镜头`; character references = 1, prop references = 1, scene references remain 0 because that job did not contain a scene image.
- Scope is local client and tests only. No central server, remote comic `server.py`, OpenAPI, database, Docker, environment variable, or `migration.sql` change. Per user preference, the local client was not restarted; restart the local client manually for runtime effect. Roll back `backend/matrix_native_client.py`, `tests/test_video_replacement.py`, and this changelog entry to restore previous behavior.

## 2026-07-31 抖音评论今日计数与中文风控提示
### Fixed
- 本地执行器把抖音评论风控从单一冷却扩展为账号级台账：`comment_risk_state.json.accounts.<accountId>` 现在记录当天 `commentCount/day`、最近评论时间、风险冷却和风险暂停原因；账号 A 的风险暂停不再误拦截账号 B。
- 抖音发表评论会先检查风险冷却、每日评论上限和最小评论间隔；命中 `douyin_daily_comment_limit`、`douyin_comment_cooldown` 或 `douyin_comment_risk_cooldown` 时返回 `ok=false`、`skipped=true`、`safety` 和中文 `message/userMessage`，不会打开浏览器或调用平台评论接口。`force=true` 和 `safeMode=false` 不再绕过这类硬门禁。
- AI 触达遇到抖音评论日上限、冷却或风险暂停会停止本轮继续评论，并把任务结果标为 `ok=false`，避免任务中心和客户端误显示“触达完成”；该停止规则同样不依赖 `safeMode`。
- 本地客户端风控中心现在读取同一 `comment_risk_state.json`，抖音账号“今日评论”列显示真实当天评论计数；评论发布、AI 触达等前端状态栏优先显示中文 `userMessage/message`，后端 `error` 机器码继续保留用于日志、接口和回归测试；平台风险响应落盘前只保留安全字段和 URL/正文指纹。
### Verification And Operations
- 新增/扩展抖音评论风控回归，覆盖成功计数、每日上限前置拦截、`safeMode=false` 硬拦截、平台风险响应暂停写入、账号级风险隔离、风险响应脱敏落盘、HTTP 429 中文响应、AI 触达停止、风控中心今日评论接入和前端中文提示；`tests.test_douyin_comment_cooldown` 18/18 通过。
- 本次影响本地执行器、本地客户端、测试和文档；不新增数据库表、Docker、环境变量或 `migration.sql`。OpenAPI 不新增路径，仅补充本地任务结果字段说明。生效需要重启本地客户端和本地执行器；回滚 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_comment_cooldown.py` 和本条文档即可恢复旧行为。

## 2026-07-31 分解视频 LK888 实扣对账与任务详情
### Fixed
- 分解视频的 Gemini 音频转写请求现在会带 `video_breakdown/audio_transcription` 业务标签，中心服把 `/v1beta/models/...:generateContent` 识别为 LK888 chat 类待对账调用，等待 LK888 `/v1/skills/usage?detail=1` 返回真实 `cost` 后再按实扣云豆补扣。
- 分解视频的关键帧画面理解和拆解报告生成也会带业务阶段标签；结算到账单流水后保留 `billingScenario/billingStage/billingDetail`，账户中心任务详情显示为“分解视频文本生成 - 音频提取/口播转写/画面理解/拆解报告”等具体用途，不再误显示为“工作流助手聊天”。
- OCR 本地识别不调用 LK888，不新增扣费；若历史或后续流水带 `video_breakdown/ocr` 标签，账户中心会显示为“分解视频文本生成 - OCR转写”。
### Verification And Operations
- 新增账单文案、音频转写请求标签、中心服 `generateContent` 待对账和对账 meta 保留回归；`tests.test_account_billing_dashboard` 18/18、`tests.test_video_transcription tests.test_video_breakdown` 64/64、`tests.test_api_download_contract` 42/42 通过；`py_compile` 通过。
- 本次影响本地客户端、中心服、转写工具、测试和文档；不改变 LK888 金额计算，仍以 LK888 实际 `cost` 为准。不涉及数据库迁移、Docker、环境变量、OpenAPI 路径或 `migration.sql`。生效需要重启中心服和本地客户端；回滚 `backend/matrix_native_client.py`、`backend/central_server.py`、`backend/utils/video_transcription.py`、相关测试和本条文档即可恢复旧行为。

## 2026-07-31 抖音评论冷却控制与风控中心显示
### Fixed
- 本地执行器在抖音发表评论前读取 `risk_config.json` 的 `minInterval` 和 `comment_risk_state.json` 的最近评论时间；普通 API、自动回退 UI、强制 `edge-ui` 评论都会在冷却未结束时返回 `douyin_comment_cooldown` / `comment_cooldown`，并带 `cooldownLeft` 和 `safety`，不会打开浏览器或调用平台发布。
- 发布成功后按 `accountId` 记录 `lastCommentAt`，同时保留旧全局 `lastCommentAt/lastCommentAccountId` 兼容字段；AI 触达会把当前选择的抖音账号传入评论发布链路，命中评论冷却时停止本轮触达。
- 本地客户端风控中心的抖音“冷却”列读取同一 `comment_risk_state.json`，显示评论最小间隔和既有评论风险暂停里的最大剩余秒数。
### Verification And Operations
- 新增抖音评论冷却回归，覆盖成功记录、二次评论拦截、强制 UI 通道拦截和风控中心源码接入；`tests.test_douyin_comment_cooldown` 4/4 通过。
- 本次影响本地执行器、本地客户端、测试和文档；不涉及中心服接口形状、数据库、Docker、环境变量或 `migration.sql`。OpenAPI 不新增路径，`/api/local-browser/task` 的开放 `result` 契约保持不变，仅补充本地任务说明。生效需要重启本地客户端和本地执行器；回滚 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_comment_cooldown.py` 和本条文档即可恢复旧行为。

## 2026-07-31 分解视频口播稿去除相邻重叠
### Fixed
- 视频分解音频转写合并时，会检测相邻转写段“上一段尾部 = 下一段开头”的重复文本，并从后一段删除重复前缀，避免口播稿出现连续片段重复同一句话。
- 同款替换从 `breakdownAnalysis.transcript.segments` 生成片段口播稿时，再做一次跨片段去重；旧任务中已经保存的重叠转写，也会在重新生成替换方案时被清理。
### Verification And Operations
- 新增转写合并和同款替换片段口播稿回归，先在旧实现下失败，修复后通过；`tests.test_video_transcription` 21/21、`tests.test_video_replacement` 95/95、`tests.test_video_breakdown` 42/42 通过。
- 本次只修改本地客户端、转写工具、相关测试和文档；不涉及中心服、远程漫剧服务、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。按用户要求不自动重启本地客户端，生效需要用户手动重启。回滚相关文件即可恢复旧行为。

## 2026-07-31 新用户账号矩阵隐藏无效默认抖音占位
### Fixed
- 本地执行器 `/api/accounts` 在当前用户没有真实抖音登录态时，不再返回离线的默认 `douyin-self` 占位账号，避免新用户登录后误看到“1 个授权账号”。
- 本地客户端合并中心服账号和本机执行器账号时，会过滤无中心归属、无 Cookie、无在线状态的默认 `douyin-self/default` 占位；真实多账号注册表里的抖音账号仍会正常显示，登录态失效时继续标记为离线。
### Verification And Operations
- 新增本地执行器空账号目录和客户端账号合并回归，先在旧实现下复现 `douyin-self` 被展示，修复后通过；账号矩阵/抖音多账号相关 70/70 通过，`py_compile` 通过。
- 本次只修改本地执行器账号列表、本地客户端账号矩阵合并、测试和文档；不涉及中心服接口形状、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端和本地执行器；回滚 `backend/api_server.py`、`backend/matrix_native_client.py`、相关测试和本条文档即可恢复旧行为。

## 2026-07-31 账户中心扣费明细业务化展示
### Changed
- 账户中心“扣费明细”表格改为占满所在区域，任务详情列自动拉伸，避免右侧留下大量空白。
- 账单模型列优先展示 `model/modelId/model_id` 等真实模型 ID；任务详情改为业务描述，例如“数字人生成”“同款替换首帧图”“同款替换尾帧图”“同款替换视频”“agent.模式视频生成”“工作流助手聊天”，不再显示“漫剧视频生成，项目…”或“LK888实际扣费…”等内部文案。
- 扣费明细单元格和表格清空 Qt 原生 tooltip，鼠标悬停任务详情不再弹出黑色提示框。
### Verification And Operations
- 通过 `.\.venv-win\Scripts\python.exe -m unittest tests.test_account_billing_dashboard tests.test_native_tooltips.NativeTooltipPolicyTest -v`，共 18/18 通过；`py_compile` 通过；账户中心扣费明细离屏 UI 冒烟通过。
- 本次只修改本地客户端 UI、测试和文档，不涉及中心服接口形状、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。
- 生效需要重启本地客户端；回滚 `backend/matrix_native_client.py`、`tests/test_account_billing_dashboard.py` 和本次文档记录即可恢复旧展示。

## 2026-07-31 企业中心 KPI 悬浮文案与两行三列布局
### Changed
- 企业中心总览 6 个 KPI 固定为两行三列展示，避免桌面宽度变化时挤成一行或出现不稳定换行。
- “客户企业”卡片悬浮时优先显示当前可查看企业名称，例如“丰田汽车”；“企业用户”显示已加入企业的用户数量；“调度任务”显示当前权限范围内任务总数。
- “在线节点”悬浮说明补充变化时机：本地客户端或执行器启动注册、持续心跳、退出、断网、休眠、切换企业，或超过约 45 秒未上报心跳时都会影响该数量。
### Verification And Operations
- 通过 `.\.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults tests.test_enterprise_task_center_local_browser tests.test_role_permissions`，共 54/54 通过；`py_compile` 通过。
- 本次只修改本地客户端 UI、测试和文档；不涉及中心服接口形状、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端；如上一轮在线节点中心服统计尚未重启，中心服也需要重启。回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py` 和本次文档记录即可恢复旧布局与旧悬浮说明。

## 2026-07-31 素材发布抖音多文件素材拦截
### Fixed
- 素材发布到抖音时，如果当前素材记录包含多个文件，本地执行器会在打开浏览器前返回 `douyin_single_video_required`，不再把多个文件交给抖音单文件视频上传框导致 Playwright 报 `Non-multiple file input can only accept single file`。
- 本地客户端将该错误显示为“抖音视频发布只支持单个视频文件”，并带上当前文件数量，提示用户选择单独的 `.mp4/.mov` 视频素材后重试。
### Verification And Operations
- 新增抖音多文件素材发布拦截和客户端中文提示回归；本次变更影响本地执行器 `/api/publish/run` 和本地客户端错误展示，OpenAPI/API 手册新增可选 `fileCount` 响应字段。
- 无数据库、Docker、环境变量或 `migration.sql` 变更。生效需要重启本地客户端和本地执行器；回滚相关代码、测试和文档即可恢复旧行为。

## 2026-07-31 AI触达 task_timeout 可观测性与长任务超时修复
### Fixed
- AI触达提交到本地浏览器执行后，客户端等待时间从 300 秒调整为 900 秒，与本地 worker 对 `/api/outreach/run` 的长任务超时一致，避免任务还在搜索/读取评论/生成话术/评论时前端先显示 `task_timeout`。
- 中心服本地浏览器任务 housekeeping 新增长任务超时口径，`/api/outreach/run`、寻找线索、发布和下载类长任务默认 900 秒后才允许重新排队，普通任务仍保持 300 秒。
- 客户端 `task_timeout` 返回会携带 `taskId`、最后一次任务状态和最后任务快照；AI触达状态栏改为显示中文排障提示，不再直接暴露 `未完成:task_timeout`。
### Verification And Operations
- 新增 AI触达页面和中心服本地浏览器长任务回归，先在旧实现下失败，修复后通过；本次新增可选环境变量 `CENTRAL_LOCAL_BROWSER_LONG_TASK_TIMEOUT_SEC`，不涉及数据库、OpenAPI、Docker 或 `migration.sql`。
- 生效需要重启中心服和本地客户端；回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_outreach_page_copy.py`、`tests/test_enterprise_task_center_local_browser.py` 和本次文档即可恢复旧行为。

## 2026-07-31 企业中心 KPI 固定口径与在线节点统计
### Fixed
- 企业中心总览固定展示“客户企业 / 企业用户 / 授权账号 / 可用账号 / 在线节点 / 调度任务”六个指标，不再显示与“企业用户”容易重复的“团队成员”卡片。
- “在线节点”现在按实际执行端统计，包含本地浏览器客户端 `localBrowserClients` 和兼容期旧执行节点 `nodes`；企业管理员只看本企业，普通用户直接调 summary 接口也不会拿到企业在线节点数量。
- boss 账号在线节点为空的主要原因是旧统计只看 `STATE.nodes`，而当前 boss 的执行端注册在 `org-toyota` 的 `localBrowserClients`；如果心跳超过默认 45 秒仍会按离线显示。
### Verification And Operations
- 通过 `.\.venv-win\Scripts\python.exe -m unittest tests.test_enterprise_task_center_local_browser tests.test_role_permissions tests.test_agent_mode_defaults`，共 52/52 通过；`py_compile` 通过。
- 本次涉及中心服统计口径、本地客户端 KPI 展示、OpenAPI 说明和文档；不涉及数据库结构、Docker、环境变量或 `migration.sql`。生效需要重启中心服和本地客户端；回滚相关文件即可恢复旧口径。

## 2026-07-31 工作流助手采集视频基础信息展示
### Changed
- 工作流助手采集到参考视频后，聊天结果中每条视频会显示平台、作者、点赞数、评论数、收藏数、分享数、视频时长、视频链接和本地参考视频文件名，方便用户判断哪条热点值得拆解和改造。
### Verification And Operations
- 新增工作流助手回复基础信息回归，先在旧实现下失败，修复后通过；本次只改本地客户端展示、测试和文档，不涉及本地执行器接口、中心服 API、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端。

## 2026-07-31 数字人口播上传素材悬浮删除
### Changed
- 数字人口播的人物形象、场景图和 TTS 声音上传后，预览框左上角新增悬浮显示的 `×` 移除按钮；鼠标移入才显示，移出隐藏，避免常驻控件遮挡素材。
- 点击 `×` 只清空当前页面已选择的人物、场景或声音状态，不删除本地文件，也不删除资产库历史记录；上传失败时不再提前替换原有可用预览。
### Verification And Operations
- 新增数字人口播上传素材悬浮删除源码回归；本次仅修改本地客户端 UI、相关测试和文档，不涉及中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。
- 生效需要手动重启本地客户端；回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧的不可直接移除上传素材状态。

## 2026-07-31 LK888 聊天扣费自动对账与账户中心刷新
### Fixed
- 聊天模型响应只有 `usage`、没有 LK888 实际金额字段时，不再丢失后续扣费链路；中心服会登记 `chat_usage_reconcile` 待对账记录。
- 账户中心查询账单前会自动拉取 LK888 `/v1/skills/usage?detail=1`，按当前用户、模型、时间窗口和 LK888 `task_id/cost` 幂等补扣，仍然不使用本地 token 估算价。
- 账户中心页面可见时每 15 秒刷新余额、概览和当前扣费明细页，视频生成后的最新扣费不需要重启客户端才能看到。
### Verification And Operations
- 新增/调整中心服和账户中心回归，覆盖聊天待对账登记、usage 明细补扣、账单查询前自动补扣和账户中心自动刷新；本次不改 OpenAPI 形状、数据库、Docker、环境变量或 `migration.sql`。
- 生效需要重启中心服和本地客户端；历史上没有 pending 的旧聊天消费不能可靠自动归属，需要管理员人工核对。

## 2026-07-31 Agent.模式视频参考图传给 LK888
### Fixed
- `Agent.模式` 视频生成不再只把上传图片转成视觉文字描述；提交 LK888 视频任务前会先把上传图片上传成远程模型可读取的图片 URL。
- LK888 `/v1/media/generate` 视频 payload 现在同步携带 `image_urls`、`images`、`reference_images`、`referenceImages`、`reference_image_urls` 以及 `params.images/params.image_urls/params.reference_images`，确保视频模型能直接读取用户上传的参考图。
- 视觉描述仍保留为 prompt 辅助信息，但不再替代真实图片输入。参考图上传失败时会直接失败并提示“参考图上传失败”，不会静默退化为纯文字视频。
### Verification And Operations
- 新增 Agent 视频参考图 payload 回归，先在旧实现下失败，修复后通过；同时覆盖参考图上传失败时不提交 LK888 任务。
- 本次只修改本地客户端、Agent 视频测试和文档；不涉及中心服接口形状、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端；回滚相关文件即可恢复旧的纯文字视频提交行为。

## 2026-07-31 企业中心数据悬浮说明
### Added
- 企业中心 KPI 卡片和“任务趋势 / 运行健康 / 账号分布”面板新增自定义悬浮说明，解释每个数据的统计口径；悬浮层使用本地客户端自绘信息卡片，不使用 Qt 原生 `setToolTip(...)`，避免黑色提示框遮挡界面。
- 账号中心旧图标按钮说明改为同一套自定义悬浮说明；请求状态和账单明细单元格清空原生 tooltip，保持全局 UI 策略一致。
### Verification And Operations
- 新增企业中心悬浮说明回归测试，并通过全局原生 tooltip 策略测试。本次只修改本地客户端 UI、测试和文档；不涉及中心服接口、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端；回滚相关文件即可恢复旧显示行为。

## 2026-07-31 同款替换素材审核拒绝自动切备用模型
### Fixed
- 漫剧项目模式生成视频时，如果 Ark/Seedance 返回 `InputImageSensitiveContentDetected.PolicyViolation`、`PrivacyInformation` 或版权/品牌素材审核拒绝，不再把片段直接置为失败；客户端会退回当前视频尝试扣费，并按 `Vidu Q3 多参考 -> 万相 2.7 首尾帧 -> Kling V3 Omni 首尾帧 -> PixVerse V6 首尾帧` 顺序继续尝试。
- 片段 JSON 会记录 `comicVideoFallbacks`、失败模型、远程任务 ID 和脱敏错误摘要；前端只显示“上游模型拒绝了输入参考图，可能涉及真人、版权或品牌内容限制”，不再暴露 `错误编号 err-*` 或上游英文错误码。
### Verification And Operations
- 聚焦回归覆盖 PolicyViolation 识别、进度提示、失败解释、视频轮询后切换 Vidu，以及前端中文错误展示；本次只修改本地客户端、同款替换测试和文档。
- 不涉及中心服、远程漫剧服务、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。按用户要求不自动重启本地客户端；生效需要用户手动重启。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`tests/test_video_replacement_v2.py` 和本条文档即可恢复旧行为。

## 2026-07-31 企业中心任务趋势真实柱状图
### Changed
- 企业中心“任务趋势”不再使用客户端固定比例模拟数据，改为读取中心服 `/api/enterprise/usage` 返回的 `taskTrend7d`，按最近 7 个自然日真实任务创建时间聚合展示。
- `调度任务` KPI 仍表示当前权限范围内的任务总数；趋势图表示近 7 天每日任务量，两者口径已在接口文档中区分。
### Verification And Operations
- 新增后端日桶聚合、前端真实趋势解析和 OpenAPI 覆盖回归，先在旧实现下失败，修复后通过；本次修改中心服、本地客户端、OpenAPI、接口文档和测试，不涉及数据库、Docker、环境变量或 `migration.sql`。生效需要重启中心服和本地客户端；回滚相关文件即可恢复旧模拟趋势。

## 2026-07-31 LK888 聊天扣费删除本地 token 估算
### Fixed
- 中心服 `/lk888/v1/chat/completions` 不再根据响应里的 `usage` token 数做本地估算扣费；只有 LK888 返回 `billing.amount`、`cost`、`consume` 等实际费用字段时才写入本地扣费流水。
- 删除本地聊天 token 费率表和估算函数，避免本地账户中心金额与 LK888 `task-status.cost` 不一致。
### Verification And Operations
- 新增/调整中心服计费回归，先在旧实现下复现“只有 usage 也扣费”，修复后聚焦测试通过；本次修改中心服、测试和文档，不涉及 OpenAPI 形状、数据库、Docker、环境变量或 `migration.sql`。
- 生效需要重启中心服；回滚 `backend/central_server.py`、相关测试和文档即可恢复旧行为。

## 2026-07-31 同款替换前端隐藏错误编号
### Fixed
- 同款替换失败时，状态栏、片段表、视频预览格子和最终弹窗不再把 `错误编号 err-*` 直接展示给用户；已知错误码继续翻译成中文说明，未知上游错误保留 `message/detail/status` 等实际失败内容。
- 任务 JSON、`diagnostics.errorId`、片段 `errorId/remoteErrorId/facefusionErrorId` 和结构化日志仍保留错误编号，用于可追溯排查。
### Verification And Operations
- 新增/调整同款替换展示层回归，先在旧实现下失败，修复后聚焦 10/10 通过；本次只修改本地客户端、同款替换测试和文档，不涉及中心服、远程漫剧服务、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。
- 按用户要求不自动重启本地客户端；生效需要用户手动重启。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py` 和本条文档即可恢复旧展示行为。

## 2026-07-31 分解视频支持直接粘贴链接
### Added
- “分解视频”页顶部新增视频链接输入框和“下载并分解”按钮，用户可直接粘贴抖音或小红书视频链接，客户端后台下载成功后自动进入现有视频分解流程。
- 链接入口自动识别抖音/小红书；小红书链接沿用账号模式参数，下载失败、本地执行器未启动、账号未登录或未找到视频文件时，错误直接显示在分解视频页。
- 分解完成后仍复用原有“替换生成”按钮，把 `sourceVideoPath/sourceUrl/platform/breakdownAnalysis/markdown` 传给同款替换，不新增自动化工作流 JSON。

### Verification And Operations
- 新增分解视频链接入口回归，先在旧实现下失败，修复后 `tests.test_video_breakdown` 42/42 通过；未调用真实抖音/小红书下载。
- 本次只修改本地客户端、分解视频测试和文档；不涉及中心服、远程漫剧服务、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。按用户要求不自动重启本地客户端，生效需要用户手动重启。回滚相关文件即可恢复旧页面。

## 2026-07-31 Agent.模式 LK888 模型对应关系规则完善
### Fixed
- `Agent.模式` 的本地已知模型表现在同时保存显示名、图片/视频类型和视频时长规则；LK888 在线目录返回错配名称、错配类型或多余规则时，不能覆盖本地权威映射。
- 图片生成入口会拒绝已知视频模型状态，视频生成入口会拒绝已知图片模型状态，避免前端看似选择视频模型但最终向 LK888 提交 `gpt-image-2`，或图片任务误提交 Seedance。
- Vidu Q3 / Vidu Q3 Turbo 的 Agent 视频时长规则固定为 8 秒；选择该类模型时本地时长控件同步显示 8 秒，不再显示 5 秒但后台提交 8 秒。Seedance 1.5 Pro 继续使用 5/10 秒规则。
- 前端不展示 LK888 真实模型 ID；模型菜单和当前模型信息仍只显示用户可读名称。
### Verification And Operations
- 新增 Agent 模型规则回归，先在旧实现下失败，覆盖图片/视频模型状态错位、规则表缺失、LK888 目录把 Seedance 错标成 GPT 图片模型等问题；修复后聚焦测试和 Agent 原有回归均通过。
- 本次只修改本地客户端、Agent 视频模型测试和文档；不涉及中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端；回滚相关文件即可恢复旧的目录合并和提交行为。

## 2026-07-31 本地客户端 LK888 扣费四位小数显示
### Fixed
- 账户中心账单金额不再固定保留 2 位小数；LK888 实际扣费按 4 位小数显示，并去掉负零，避免 `0.0016` 在本地客户端显示成 `-0`。
- 账单表格的实扣/变动金额和扣后余额使用同一格式化规则，和 LK888 消费明细的 4 位小数口径对齐。
### Verification And Operations
- 新增账户中心金额格式和账单表格回归，先在旧实现下复现 `-0.0016 -> -0`，修复后通过；中心服 LK888 实际扣费聚焦用例也通过，确认结算路径没有两位取整。
- 本次只修改本地客户端显示层、账户中心测试和文档；不涉及中心服 API 形状、OpenAPI、数据库结构、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端；回滚相关文件即可恢复旧两位显示规则。

## 2026-07-31 Agent.模式 Vidu Q3 视频时长参数修复
### Fixed
- `Agent.模式` 选择 LK888 的 Vidu Q3 / Vidu Q3 Turbo 视频模型时，不再把通用 5 秒时长直接提交给上游；本地提交前会把 `duration` 规范化为当前 LK888 Vidu Q3 可接受的 8 秒，避免返回“参数 duration 的值 5 不合法”且拿不到任务 ID。
- Seedance 等其他 Agent 视频模型仍沿用原来的 5 秒 / 10 秒选择规则。
### Verification And Operations
- 新增 Vidu Q3 时长参数回归，先在旧实现下失败，修复后通过；本次只修改本地客户端、Agent 视频时长测试和文档，不涉及中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端；回滚相关文件即可恢复旧的直接提交时长行为。

## 2026-07-31 本地客户端主题切换保留页面状态
### Fixed
- 侧边栏底部“切换背景/主题”按钮不再通过重建全部页面来刷新外观，改为保留现有页面实例并轻量刷新 Qt 样式和背景绘制，避免工作流助手对话、输入框内容、任务页本地状态在切换后被清空。
### Verification And Operations
- 新增主题切换回归断言，先在旧实现下失败，修复后通过；本次只修改本地客户端 UI、测试和文档，不涉及中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端；回滚相关文件即可恢复旧的全量页面重建行为。

## 2026-07-31 Windows start-visible-client restarts central server
### Changed
- `start-visible-client.bat` now stops any existing process listening on `CENTRAL_PORT` before checking `/api/health` and launching `backend/central_server.py`. Double-clicking the script now reloads current center-server code instead of silently reusing an old 9080 process.
### Verification And Operations
- Added `tests.test_start_visible_client_script` to lock the startup contract. Verified this test and the focused LK888 postpaid billing tests pass.
- This changes only the Windows startup script plus tests and documentation. It does not change OpenAPI, database schema, Docker, environment variables, or `migration.sql`. Rollback restores the previous script behavior where an already-healthy 9080 process is reused.

## 2026-07-31 资产库同款替换口播稿修复
### Fixed
- 从资产库“采集参考视频”点击“按此视频改造”进入同款替换时，现在会把拆解文本解析成 `breakdownAnalysis.transcript.segments`，生成替换方案时可自动带出口播稿，不再只传 `transcript.text` 导致片段 `script` 为空。
### Verification And Operations
- 新增资产库拆解文本转口播分段回归，先在旧实现下失败，修复后通过；本次仅修改本地客户端、测试和文档，不涉及中心服 API、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端，回滚相关文件即可恢复旧行为。

## 2026-07-31 工作流助手改为对话式热点视频拆解
### Changed
- “工作流助手”不再生成工作流 JSON、不再保存到 `workflows.json`、不再跳转或依赖“自动化工作流”页面；用户输入采集/拆解需求后，客户端直接执行热门视频采集、视频理解拆解和当前页结果展示。
- 侧边栏移除“自动化工作流”入口，登录后也不再启动旧工作流定时调度；采集到的原视频仍只作为资产库“采集参考视频”，不会进入发布队列。
- 聊天结果现在包含采集状态、每条参考视频标题、拆解文本、“如何拍出同等价值视频”的原创拍摄建议，并为每条参考视频提供“按这条改造生成”入口，直接进入 `同款替换`。
- 资产库“采集参考视频”的文本弹窗按钮从“用此文本生成视频 / Agent.模式”改为“按此视频改造 / 同款替换”，复用 `video_replace_start` 契约传入源视频、拆解文本和 `breakdownAnalysis`。
### Verification And Operations
- 新增直接助手与资产库同款替换入口回归测试，先在旧实现下失败，修复后相关本地客户端测试通过；`backend/matrix_native_client.py` 语法检查通过。
- 本次只修改本地客户端、测试和文档；不涉及中心服 API、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端；回滚本次文件即可恢复旧入口和旧编排行为。

## 2026-07-31 同款替换漫剧素材优先提示词
### Changed
- 同款替换漫剧项目模式现在把“项目剧本”和“远程模型画面提示词”分开约束：项目 `source_text` 只写分镜画面、镜头、景别、角度、运镜，不再写 `对白：...` 或用户口播稿。
- 传给漫剧首尾帧和视频生成的 prompt 会强绑定上传素材：人物使用项目库角色“主角”，场景使用项目库场景“场景1”，产品使用项目库道具“道具1”；原视频只提供动作、站位、镜头节奏和运镜方式。
- 从原视频拆解中提取动作时会丢弃原片人物外观、原片产品、原片道具、原片场景、字幕和台词；动作里出现的旧产品指向会替换为“上传道具”，降低按原视频实体重新生成的概率。
- 视频生成 payload 也会携带 `character_reference_images/scene_reference_images/prop_reference_images/subject_reference_images` 和负向提示，明确不要生成字幕、对白文字、促销文字或复刻原片实体。

### Verification And Operations
- 新增素材优先回归，先在旧实现下失败，修复后 `tests.test_video_replacement` 93/93 通过；未调用真实远程模型。
- 本次只修改本地客户端、同款替换测试和文档；不涉及中心服、远程漫剧 `server.py`、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。按用户要求不自动重启本地客户端，生效需要用户手动重启。回滚相关文件即可恢复旧提示词。

## 2026-07-31 抖音全自动回复即时合并
### Changed
- “私信 / AI 销售”的全自动回复不再等待固定 5 分钟窗口；每 20 秒检查一次指定客户会话。该阶段曾将同一轮文本合并回复，已由 2026-08-01 的逐条队列替代。
- 首次开启全自动时，只处理最近一次我方消息之后的客户未回复文本，避免重启后回复已经处理过的历史消息。
- 如果同一轮消息中包含图片、语音、视频、卡片、表情等非文本内容，整批转人工处理，不自动回复其中的文本部分。
### Failure Handling
- AI 生成失败或私信发送失败会立即关闭全自动回复，清空本批待回复队列并标记人工处理，不自动重试，避免重复触达或误发。
### Verification And Operations
- 新增自动回复状态机回归测试，先在旧实现下失败，修复后 `tests.test_douyin_dm_auto_reply` 79/79 通过；本次不涉及中心服接口、数据库、OpenAPI schema、Docker、环境变量或 `migration.sql`。
- 生效需要重启本地客户端；回滚 `backend/matrix_native_client.py`、`tests/test_douyin_dm_auto_reply.py` 和本次文档记录即可恢复旧 5 分钟窗口行为。

## 2026-07-31 本地客户端任务中心显示修复
### Fixed
- 任务中心表格改用本地客户端统一表格样式，去掉每个单元格的默认格子框。
- 任务中心时间列现在会在 `updatedAtText/createdAtText` 为空时，使用 `updatedAt/createdAt` 等数值时间戳格式化显示，不再因为接口只返回时间戳而空白。
### Operations
- 本次只修改本地客户端显示层、回归测试和文档；不涉及 Web、中心服、数据库、OpenAPI 或 `migration.sql`。生效需要重启本地客户端，回滚相关文件即可恢复旧显示。

## 2026-07-31 LK888 后付费实际扣费
### Changed
- `/lk888/*` 模型调用从“提交前按本项目估算价预扣”改为“先调用 LK888，拿到 LK888 实际消费后再扣本项目云豆”。后续“LK888 严格最终实扣”变更已把历史估价和预扣入口完全删除。
- 未欠费用户允许本次调用后扣成负数，并在用户和流水上标记欠费；已经欠费的用户再次调用 LK888 模型会返回 402 `account_in_arrears`。
- 异步媒体任务提交成功但没有实际费用时写入 `lk888_pending_charges`；任务状态成功且带实际费用才结算，失败不扣费，成功但无费用继续保留待结算。
### Verification
- 新增后付费回归先失败后通过，覆盖实际费用扣成负数、已欠费拦截、异步任务无预扣挂账和任务状态按实际金额结算；旧预扣开关随后已删除。
- `tests.test_billing_unified` 26/26 通过，LK888 代理聚焦测试 8/8 通过，中心服语法检查通过。
### Operations
- 本阶段只修改中心服扣费逻辑、LK888 代理测试和相关文档；后续严格实扣阶段同步修改了客户端和 OpenAPI 描述，并删除运行时预扣开关。
- 生效需要重启中心服；当前版本还需要同步重启本地客户端，不能让新旧结算进程混跑。

## 2026-07-31 LK888 模型扣费对齐
### Fixed
- 已在当前虚拟环境安装并验证 `passlib`，并把 `passlib[bcrypt]==1.7.4` 与 `PyMySQL==1.1.1` 写入本地和部署 requirements。
- 中心服 LK888 扣费按登录后的 LK888 消费明细对齐到 `1 云豆 = 1 元`：媒体模型支持固定价、按秒价和兜底价；`copywriting` 改为中心服扣费，避免客户端自报金额。
- `/lk888/v1/chat/completions` 成功返回且包含 `usage` 时，中心服按模型 token 单价扣除当前用户云豆；余额不足返回 402，且不记录 Key、Token、Cookie 或上游凭据。
### Verification
- LK888 页面已登录查看消费记录，确认了 Vidu Q3 Turbo、Vidu Q3、GPT Image 2、GPT-5.4、Gemini 和 TTS/视频类模型的计费证据；本机主库 `maindb.ping()` 仍为 false，所以没有使用 live DB 价格表。
- 聚焦扣费回归和聊天代理扣费测试通过，相关中心服和客户端文件语法检查通过。
### Operations
- 本次没有新增接口字段、OpenAPI schema、数据库结构、Docker 拓扑、环境变量或 `migration.sql`；生效需要重启中心服和本地客户端。
- 回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_billing_unified.py`、`tests/test_api_download_contract.py`、两个 requirements 文件和本次文档即可恢复旧扣费规则。

## 2026-07-31 同款替换取消声音验证
### Changed
- 同款替换片段质检、最终合成门禁和合成输出不再检查音轨是否存在、静音比例、平均音量或上传完整配音是否覆盖完整成片时长；无声片段在视频文件有效且人工确认后可以合成并存入资产库。
- 任务完成状态明确记录 `audioValidation=disabled`，片段质检记录 `audio.status=skipped/code=disabled`，并清理历史任务遗留的最终 `audioCheck`，便于区分“未执行声音验证”和“声音验证通过”。
- AI 音色和上传完整配音仍执行原有声音生成/混音流程；输入文件缺失、视频时长不可读取、FFmpeg 混音失败或输出视频损坏仍按功能失败处理。视频文件有效性、视觉质检和人工确认门禁保持不变。

### Verification And Operations
- 新增/调整 5 项声音门禁回归，生产改动前为 5 项失败，改动后 5/5 通过；`tests.test_video_replacement` 完整回归 92/92 通过。`tests.test_video_replacement_v2` 仍有改动前已记录的 5 failures + 2 errors，均为旧原片音轨断言、旧小红书文案断言和缺失测试夹具，不是本次新增回归。
- 本次只修改本地客户端、两组同款替换测试和文档；不涉及中心服、远程漫剧服务、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。回滚上述本地文件即可恢复旧声音门禁。按用户要求未自动重启本地客户端。

## 2026-07-31 抖音详情连接自动重试
### Fixed
- 分解视频前的抖音作品详情请求新增 8 秒连接超时、15 秒读取超时和 1/2/4 秒退避；首次网络失败后最多重试 3 次，只处理连接及超时异常。
- 连续失败统一返回 `douyin_detail_network_failed`，页面精确显示“抖音连接暂时失败，请重试”，不再展示 `HTTPSConnectionPool` 或签名请求地址。

### Security And Contract
- `/api/douyin/download` 详情网络失败返回 HTTP 502、`stage=detail` 和安全 `errorId`；详细原因仅写入脱敏 JSON 日志，使用作品编号指纹且不记录 Cookie、Token、签名值、完整 URL 或原作品编号。
- OpenAPI 和接口手册同步 502 语义；未新增接口、环境变量、数据库结构或 `migration.sql`。

### Verification And Operations
- 新增 5 项聚焦测试先失败后通过，覆盖重试、超时、退避、不重试 HTTP 业务响应、API 契约、日志脱敏和客户端中文提示。
- 回滚本次三个生产文件、三组测试及关联文档即可恢复旧行为。按用户要求未自动重启本地客户端、本地执行引擎或中心服。

## 2026-07-30 抖音全自动回复生产加固
### Fixed
- 编辑客户主页会立即关闭全自动并清空旧客户缓冲、去重和发送状态；所有后台事件绑定会话代次、目标和账号，旧客户的迟到结果不会发送给新客户。
- 手动发送、自动发送和收件轮询统一直连本机 `9081`。首次成功收件锁定实际账号；中心复合账号 ID 会归一化；每个本机账号使用独立稳定浏览器 profile，避免共享临时 profile 反复要求登录。
- 空会话改为 HTTP 200 和 `ok=true/messages=[]/empty=true`；无效目标、登录失效和内部异常分别返回 400、401、500。成功事件不再携带伪错误 `http_200`。
- 小红书线索不会进入当前仅支持抖音主页的私信跟进 MVP。

### Security And Contract
- 本地异常保留脱敏结构化堆栈和安全 `errorId`，响应不返回原始堆栈、子进程输出、客户链接或私信正文。
- 中心服兼容 `douyin.dm` 任务只持久化并公开目标、正文和发送结果指纹；原始参数只在本地执行器领取排队任务时驻留内存。
- OpenAPI 和接口手册同步目标别名、每账号 profile、空会话成功及 200/400/401/500 契约，移除 `dm_inbox_messages_not_found` 错误枚举。

### Verification
- 成功事件和空会话契约回归均先失败后通过；完整私信模块 72/72、获客页面 10/10、OpenAPI 契约 6/6 通过，相关 Python 语法检查退出 0。
- 既有 `utils/dy_util.py` 未关闭文件 `ResourceWarning` 和 `api_server.py` 两条无效转义 `SyntaxWarning` 仍存在，未由本次改动引入。

### Operations
- 本地客户端和本地执行引擎需重启后生效；中心隐私加固需中心服后续按正式发布流程部署。本次不涉及数据库、Docker、环境变量、SQL 或 `migration.sql`。
- 回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`backend/central_server.py`、三组相关测试、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和本条记录即可恢复旧行为。

## 2026-07-30 账户中心账单最终评审阻断修复
### Fixed
- 主库默认启用并记录模块导入失败；只有显式 `MAINDB_ENABLED=0` 才允许隔离 JSON 模式。主库依赖、配置、健康、用量或严格余额读取失败时，新账单接口统一返回脱敏 503，不再显示局部统计或虚假 0 余额。
- 运营方 `user-owner` 通过真实 analytics 与参数化 ledger 路由固定返回 `"inf"`；客户端现有“∞ 运营方”显示契约不变。
- 旧 `/api/account/balance` 同步改用严格余额语义：运营方返回 `"inf"`，主库不可用返回脱敏 503；账户页成功收到 analytics 后不再允许迟到旧余额覆盖权威余额，充值或兑换成功会刷新 analytics。
- 微信订单与兑换码引用规范为 `wxpay:<orderNo>` / `redeem:<code>`，兼容 `paidAt/usedAt`；账本稳定 `ref` 在无其他关联字段时写入公开 `requestId`，消除重复充值并保留扣费/退款关联。
- 两份运行时 requirements 新增精确锁 `PyMySQL==1.1.1` 与 `passlib[bcrypt]==1.7.4`，并保留 `jsonschema==4.23.0`。
### Verification
- 新增回归先复现最终评审的三项阻断及迟到旧余额覆盖；修复后聚焦测试通过。完整套件、冒烟、编译和回滚 dry-run 结果见本次最终验证记录。
### Operations
- `/api/account/balance` 的余额契约扩展为数字或精确字符串 `inf`，并新增 503；OpenAPI 与接口手册已同步。数据库结构和 `migration.sql` 不变。未安装依赖、未重启客户端或中心服、未运行 Docker、未部署、未暂存或提交；生产仍受代表性 MySQL 性能和真实回滚制品门禁约束。

## 2026-07-30 小红书账号矩阵改名同步修复
### Fixed
- 小红书账号矩阵改名现在会同时写入本地执行引擎和中心服账号记录，中心服保存 `displayNameOverride`，后续节点心跳不会再把人工昵称覆盖回默认“小红书账号”。
- 当小红书只有中心旧账号记录、当前本机执行引擎没有可用 `xhs-self` 登录态时，账号矩阵会把该账号标记为登录态失效，不再显示成可直接操作的在线账号。
### Verification
- 新增回归先复现旧问题，再验证中心昵称保留、客户端双写和 OpenAPI 合同。相关聚焦测试与 Python 语法检查通过。
### Operations
- 本次修改本地客户端、中心服账号接口、OpenAPI/接口文档和回归测试；不涉及数据库迁移、Docker、环境变量或 `migration.sql`。生效需要重启中心服、本地执行引擎和本地客户端。回滚上述文件即可恢复旧行为。

## 2026-07-30 小红书真实浏览器冒烟与账号默认口径统一
### Fixed
- 小红书搜索和下载接口默认值与客户端统一为账号模式；未显式确认账号采集时返回 `xhs_account_collection_unconfirmed`，不再由接口默认回到游客采集。
- 账号模式搜索如果实际落到 `explore?source=tourist_search` 游客推荐流，返回 `xhs_login_required`，不再显示“成功但 0 条”。
- 小红书评论和获客寻客的接口测试补齐本机登录态门禁，避免确认账号采集后因测试未声明登录态而误报 429。

### Verification
- 真实浏览器冒烟使用 `boss` 账号 profile：本地 profile 判断为可用，但搜索实际落到游客推荐流；下载和评论因没有搜索结果无法继续；获客寻客返回 0；发布 dry-run 返回 `xhs_creator_login_required`，没有点击真实发布。
- 新增/修改小红书账号模式测试先失败后通过；后续回归与编译见本次交付结果。

### Operations
- 本次修改本地执行引擎、小红书适配器、OpenAPI/接口/排障/实施文档和回归测试；不涉及中心服部署、数据库、Docker 或 SQL 迁移。生效需要重启本地执行引擎和本地客户端。
- 回滚时恢复 `backend/api_server.py`、`backend/platform_adapters.py`、`tests/test_api_download_contract.py`、`tests/test_xhs_lead_filtering.py`、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和本条记录即可。

## 2026-07-30 同款替换口播识别失败提示与重试入口
### Fixed
- 同款替换载入分解结果时，如果音频转写存在失败时间段，会在状态栏明确提示“口播识别失败”，不再让用户误以为系统已经识别出口播稿。
- 同款替换源视频栏新增短按钮“重试口播”，只重试 `transcript.failedRanges` 对应的失败音频区间；重试成功后更新同款替换源分析和当前任务 JSON，提示用户重新生成替换方案。
### Verification
- 新增同款替换口播失败提醒和重试回写测试，先在旧实现下失败，修复后 2/2 通过。
- `py_compile` 通过；完整 `tests.test_video_replacement_v2` 仍有 5 failures + 2 errors，属于既有 XHS 测试夹具和旧“原片声音回填”断言，非本次口播重试链路引入。
### Operations
- 本次只修改本地客户端、同款替换回归测试和文档；不涉及中心服、远程漫剧服务、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。
- 回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为；代码生效需要重启本地客户端。

## 2026-07-30 抖音全自动回复复用账号矩阵登录态
### Fixed
- 获客中心进入“私信 / AI 销售”时会同时带入当前选择的抖音账号；全自动收信轮询与后续自动发送使用同一个 `accountId`，避免多账号场景下收信和回复落到不同账号。
- `/api/douyin/dm/inbox` 新增可选 `accountId`。本地收件浏览器会解析对应账号矩阵 profile，以该 profile 播种稳定的 `dy_dm_profile/current`，并在打开客户主页前补充注入该账号 Cookie 缓存，不再依赖未登录的通用 profile。
- 自动收件 Cookie 诊断只返回 `attemptedCount`、`addedCount` 和异常类型，结构化日志只记录账号 ID 与数量，不记录 Cookie、Token、Authorization 或私信正文。

### Verification
- TDD 新增账号传递、浏览器 profile 播种、Cookie 注入顺序和脱敏诊断回归；聚焦私信回归通过 54/54，完整私信模块通过 58/58，获客页面通过 9/9，OpenAPI 契约通过 6/6，相关 Python 文件语法检查通过。
- 指定客户主页的真实浏览器只读冒烟与重启后的 `9081` 接口复验均得到 `needLogin=false`、账号匹配、Cookie 注入 60/60；页面无可提取消息时返回既定 `dm_inbox_messages_not_found`，没有再进入登录墙，也没有发送新私信。

### Operations
- 本次修改原生客户端、本地执行引擎和本机接口契约；不涉及中心服部署、数据库、Docker 或 SQL 迁移，`migration.sql` 保持 no-op。代码生效需要重启本地客户端和本地执行引擎。
- 回滚时恢复 `backend/matrix_native_client.py`、`backend/api_server.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`tests/test_douyin_dm_auto_reply.py`、`tests/test_openapi_contract.py` 及本次文档即可恢复旧行为。
- 本机旧客户端进程已关闭并通过 `start-visible-client.bat` 重启；本地执行引擎监听 PID 已从 `29684` 切换为 `7012`，`9080` 中心服务保持原进程运行。

## 2026-07-30 账户中心账单看板发布门禁
### Added
- 新增本机账单性能冒烟：固定 200 请求、20 workers、逐响应运行时 JSON Schema 校验，正常 30 天查询 P95 门槛为 800 ms。
- 新增 100 请求发布监控与回滚门禁：错误率严格大于 1% 才选择上一稳定中心服镜像，Tag 使用严格正则校验；dry-run 不调用 Docker。
- 性能冒烟与发布监控均在原始 3xx 响应处拒绝跳转，不发起第二次请求、不转发 Authorization；3xx 直接按无效响应或错误样本处理。

### Operations
- 记录已提交 Git SHA、Tasks 1-5 预任务源码快照 SHA-256 和当前工作区源码哈希，并明确区分源码恢复证据与可部署镜像/客户端包。
- `backend/Dockerfile`、`docker-compose.prod.yml` 拓扑和 `/api/health` 保持不变；`jsonschema==4.23.0` 在本地与部署 requirements 中保持同一锁定。
- 本发布无数据库 DDL/DML，`migration.sql` 只追加 no-op 追溯说明。生产上线前必须登记上一稳定镜像 Tag 与客户端包 SHA-256；错误率超过 1% 时按门禁回滚。
- 新增跳转隔离、全响应有效性、P95 800 ms 精确边界和 CLI dry-run 无网络/子进程回归；本次未重启、未部署、未运行 Docker。

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
- 本次不改数据库、OpenAPI、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tools/aicanvas_remote/server_current.py`、`tools/aicanvas_remote/server_legacy.py`、相关测试和文档即可恢复旧行为。

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

- 本地客户端修复企业中心团队成员表格“操作”列按钮过长或重叠：操作列收窄为固定宽度，行内“重置密码 / 停用”改用紧凑按钮样式；左下角用户信息区保持上下两行，避免账号名、余额、主题切换和退出按钮在侧边栏内互相压住。

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
- “私信 / AI 销售”全自动模式改为每 20 秒检查一次该客户会话；初版只处理客户发来的纯文本消息并按 5 分钟窗口合并生成一次回复。2026-07-31 起曾改为单轮即时合并回复，2026-08-01 已改为按顺序逐条回复；图片、语音、视频、卡片、表情等非文本或明确转人工请求进入人工接管。
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
## 2026-08-01 Douyin DM inbox DOM diagnostics and safety guard

- Local executor inbox polling now returns redacted panel diagnostics: panel state, editor candidate geometry, text bubble counts, and direction counts. Cookie values and message text remain excluded from structured logs.
- Inbox parsing uses the bottom rich-text editor to identify the conversation column, then applies left/right bubble geometry only as a fallback to CSS direction markers.
- Text bubbles with avatar images remain text; common hover-menu actions (`like`, `reply`, `delete`, `copy`, `recall`, `forward`, `report`) are removed so they cannot trigger or pollute an automatic reply.
- When text exists but direction cannot be confirmed, the native client keeps it unprocessed and shows a manual-review status instead of falsely reporting no new text message.
- No OpenAPI, database, Docker, environment variable, or `migration.sql` change. Restart the local client and local executor for runtime effect. Roll back `backend/api_server.py`, `backend/matrix_native_client.py`, `tests/test_douyin_dm_auto_reply.py`, and the matching docs entry to restore the prior parser.
## 2026-08-01 小红书移除账号清理改为删除状态文件
### Fixed
- 小红书账号 `xhs-self` 移除时不再保留 `xhs_auth_state.json` 里的禁用标记，而是优先删除该文件；如果删除失败，才回退写入最小状态占位。
- 移除操作只会清理 `xhs_profile` 下的 `Cookies*` 文件，不会删除 `materials/`、`media_datas/` 等本地素材。
- 回归测试补上了移除后 JSON 消失、cookie 清理和素材保留的覆盖。

### Verification And Operations
- `tests.test_douyin_multi_account` 通过，`py_compile` 通过。
- 仅影响本地账号状态与测试。重启本地客户端后生效。回滚 `backend/api_server.py`、`tests/test_douyin_multi_account.py` 和本条记录即可恢复旧行为。
## 2026-08-03 管理员添加成员不再需要手机号邮箱
### Changed
- 本地客户端“企业中心 -> 团队成员 -> 添加成员”弹窗删除手机号和邮箱输入框，只保留姓名、初始密码和成员角色；提交中心服时不再携带 `phone/email`。
- 中心服 `/api/enterprise/users/upsert` 支持无手机号/邮箱创建成员，自动生成 `user-xxxxxxxxxxxx` 登录账号，并在响应 `credential.identifier` 中返回给管理员复制交付。
- 添加成功后客户端显示“成员已加入当前企业”并展示登录账号；初始密码留空时提示可用“重置密码”生成临时密码。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_role_permissions.RolePermissionsTest.test_platform_admin_add_member_does_not_require_phone_or_email`、`test_enterprise_user_upsert_generates_login_identifier_without_contact_fields` 和 `tests.test_openapi_contract.OpenApiContractTest.test_enterprise_user_upsert_openapi_does_not_require_phone_or_email`。
- `tests.test_openapi_contract` 10/10、相关团队成员权限测试 3/3、`py_compile` 和企业成员页离屏 UI 烟测通过。需重启本地客户端和中心服后生效。
- 本次无数据库结构、Docker、环境变量或 `migration.sql` 影响。回滚 `backend/matrix_native_client.py`、`backend/central_server.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`tests/test_role_permissions.py`、`tests/test_openapi_contract.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 可恢复旧表单。
## 2026-08-03 公开下载页 `/download`
### Added
- 中心服新增内置公开下载页 `/download`，展示“云灵星图 AI 爆款复刻平台 Windows 客户端下载”、公司背书、核心能力、安装步骤和安全支持信息。
- 页面采用深色科技商务风格，右侧为“星图任务中控面板”式能力概览；下载按钮保持禁用状态，文案为“Windows 客户端即将开放下载”，不链接真实安装包。

### Verification And Operations
- RED/GREEN 覆盖 `tests.test_web_surface_removed.WebSurfaceRemovedTest`，锁定页面标题、公司名称、禁用按钮、HTML 响应头、公开路由位置和不暴露 `/MatrixShipAgent-Setup.exe`。
- 本次只影响中心服公开 HTML 页面、测试和文档；不改变安装包直链、OpenAPI JSON 契约、数据库、Docker、环境变量或 `migration.sql`。中心服重启后生效；回滚 `backend/central_server.py`、`tests/test_web_surface_removed.py`、`CHANGELOG.md`、`docs/API_REFERENCE.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 可移除页面。
