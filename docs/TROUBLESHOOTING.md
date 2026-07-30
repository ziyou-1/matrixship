## 2026-07-30 Douyin DM inbox account scope
- Symptom: auto-reply inbox polling or manual DM send may use a different Douyin account than the Finder lead selected account, causing `not_authenticated`, `dm_panel_not_open`, or stale-cookie behavior.
- Fix: Finder follow-up carries `accountId`; DMPage uses that same account for manual send and `/api/douyin/dm/inbox`; the inbox route resolves the selected profile and injects selected-account cookies before navigation. Diagnostics record counts and account IDs only, never Cookie values or message text.
- Check: verify request payload contains `accountId`, `dmCookieInjection.addedCount` is greater than zero, and the selected account is still logged in under Account Matrix. If the target field is edited manually, the inherited account is cleared and latest usable Douyin account selection applies.
- Rollback: revert the API, client, OpenAPI, tests, and this entry. No database or migration change is involved; restart the local client and local executor after code rollback.

﻿# Troubleshooting

## 2026-07-30 账单发布验证、性能或回滚门禁失败

- 本次首次 `Start-Process` 在创建中心进程前失败，错误为父环境同时含 `Path` 与 `PATH`，PowerShell 构造大小写不敏感环境字典时报告重复键。只在验证 PowerShell 进程内合并为单一 `Path` 后，隐藏窗口 Python 3.12.13 探针正常退出；未修改系统环境。第二次中心进程已健康启动，但验证端把多行脚本传给 `python -c` 时引号被 PowerShell 剥离；改为通过标准输入交给 Python 后通过。两次尝试均确认 19080 无残留监听，已创建的隔离进程在 `finally` 中清理。
- 最终隔离冒烟结果：health、analytics、参数化 ledger、无参数 legacy ledger 均为 200；未鉴权 analytics 为 401；367 天查询为 400；analytics/ledger 响应通过运行时 Schema。性能请求 200/200 有效、20 workers、P95 520.217 ms，低于 800 ms 门槛；PID 25720 清理后 `processAlive=false`。
- 性能冒烟只能连接本机回环地址。先确认使用项目虚拟环境 `.venv-win\Scripts\python.exe`，再确认 `backend/requirements.txt` 与 `backend/requirements.deploy.txt` 都锁定 `jsonschema==4.23.0`。若出现 `ModuleNotFoundError` 或 `ImportError`，先检查该虚拟环境和 requirements 锁定，不要临时安装未批准依赖。
- 隔离中心服必须同时设置 `CENTRAL_LOAD_DOTENV=0`、测试专用 `CENTRAL_USER_TOKEN`、`CENTRAL_PORT=19080` 和隔离 `CENTRAL_DATA_DIR`；进程必须隐藏启动并在 `finally` 中终止。不得停止或重启生产中心服、客户端或本地执行器。
- 期望门禁为：健康检查 200；analytics 与参数化 ledger 鉴权请求 200 且匹配 OpenAPI/运行时 Schema；无凭据请求 401；367 天查询 400；性能 200/200 响应有效、20 workers、P95 不超过 800 ms。
- 达到 50,001 条主库模型用量记录会触发 `billing_record_limit_exceeded`；超过 366 天会触发 `date_range_too_large`。这两项是拒绝不完整或过大统计的保护，不应通过放宽上限绕过。
- 回滚监控只在固定 100 请求窗口错误率 `> 0.01` 时选择回滚；1/100 不回滚，2/100 回滚。Tag 含空格、斜杠、前导连字符或超过 128 字符时必须拒绝。
- dry-run 输出必须是脱敏 JSON，包含 `rollback=true`、`executed=false`、上一镜像 Tag 和固定参数列表，不得出现 Token、Authorization 值或启动 Docker。演练 Tag `stable-previous` 不是生产制品证据。
- 本次发布的源码恢复证据见 `docs/DEPLOYMENT.md` 中 Git SHA、预任务源码快照 SHA-256 和当前工作区源码哈希。生产回滚仍必须使用发布单登记的上一稳定中心镜像与客户端包；只有源码快照时暂停发布，不要把源码文件冒充可部署制品。
- 回滚：脚本和文档级回退可移除 `scripts/smoke_billing_performance.py`、`scripts/monitor_billing_rollout.py`、`tests/test_billing_rollout_guard.py` 及 Task 6 文档条目。完整账单功能回滚按源码快照恢复中心服/客户端并移除 Tasks 1-5 新增文件；真实进程、镜像和客户端包恢复需要单独审批。本发布无数据库 DDL/DML。

## 2026-07-30 同款替换 5 段视频全部失败：Seedance/Ark 素材版权或品牌风险
- 现象：同款替换任务状态为 `partial`，多个片段视频生成失败；错误包含 `comic_task_failed:ark 400 Bad Request`、`InputImageSensitiveContentDetected.PolicyViolation` 或 `copyright restriction`。失败消息可能提到输入图片 `content[1] content[3] content[5]` 与版权限制相关。
- 定位：最新失败任务 `854f074f38464b12b23c8ebaa92e9e1b` 的第 2/3/4 段在视频提交阶段失败，不是公网 URL、余额或下载失败。旧视频请求同时携带首帧、尾帧、人物参考图、场景参考图、产品参考图，容易把百度百科水印、展厅密集 Logo、电子屏幕文字、促销海报等风险一起带进 Seedance/Ark 视频阶段。
- 修复：`backend/matrix_native_client.py#L11152-L11207` 改为视频阶段只传当前片段首尾帧；`backend/matrix_native_client.py#L11300-L11340` 和 `.tmp-aicanvas-server-current.py#L12973-L12994` 把 `PolicyViolation/copyright restriction` 纳入备用模型降级；`backend/matrix_native_client.py#L20364-L20425` 在上传/生成前预检水印、百度百科/平台来源、电子屏幕、促销海报、第三方品牌和 Logo 过密。
- 用户素材建议：人物图使用已授权真人或虚拟模特，避免平台水印、百科截图、直播间界面和第三方商品背景；场景图可以保留自有品牌门店 Logo，但不要让 Logo 满墙、屏幕大段文字、促销海报或其他品牌商标占据画面；产品图用自有清晰照片，保留外形、颜色、包装文字和 Logo，避免网页截图和水印。
- 恢复：已失败旧任务不会自动变成功，需要重试失败片段或重新创建任务。本地客户端重启后生效；线上漫剧服务如仍使用旧代码，需要单独部署并重启远程服务。回滚 `backend/matrix_native_client.py`、`.tmp-aicanvas-server-current.py`、`.tmp-aicanvas-server.py` 及对应测试/文档即可恢复旧行为。

## 2026-07-30 抖音客户主页已打开但没有自动点击“私信”
- 现象：后台浏览器已经打开客户主页，页面弹出“是否保存登录信息？”或右上方能看到“私信”按钮，但客户端提示 `dm_button_not_found`、`dm_panel_not_open` 或 `dm_input_not_found`。实际可能是弹窗遮住主页，或私信按钮没有被页面真正响应。
- 根因：真实页面把同一按钮的 `innerText` 和 `textContent` 合并后返回“私信 私信”，旧校验只接受严格等于“私信”，因此把正确按钮写入 `rejectedButtons`；修正标签后又确认 profile 文件复制成功不等于网页登录态完整恢复，旧逻辑因 `seeded_login=true` 跳过 Cookie 注入，页面实际仍可能显示“未登录”，点击私信不会打开面板。保存登录信息弹窗和固定 XPath 变化是此前已处理的其他分支。
- 修复：`backend/api_server.py#L1772-L1786` 接受同一私信文案重复但拒绝相邻操作；`backend/api_server.py#L1955-L1975` 在访问主页前从当前账号矩阵账号补充注入 Cookie 并排除 `msToken`；`backend/api_server.py#L2004-L2174` 使用新标签校验继续选择真实私信按钮。弹窗关闭仍由 `backend/api_server.py#L2022-L2162` 处理；客户端 `backend/matrix_native_client.py#L7716-L7731` 只在 `finalPromptVisible=true` 时提示弹窗仍可见。
- 排查：先看 `dmCookieInjection.addedCount`，应大于 0 且不含错误；再看 `saveLoginPrompt.finalPromptVisible`，`true` 才表示失败时弹窗仍挡住页面；`rejectedButtons.label="私信 私信"` 说明仍在运行旧代码；`mouse_coordinate_click` 成功但 `panelOpened=false` 且页面显示“未登录”，说明当前账号 Cookie 已失效，应到账号矩阵重新登录。诊断和结构化日志不得记录 Cookie 值或私信正文。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v`，应通过完整私信回归；相关文件还需通过 `.\.venv-win\Scripts\python.exe -m py_compile backend\api_server.py backend\matrix_native_client.py tests\test_douyin_dm_auto_reply.py`。
- 回滚：回滚 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_dm_auto_reply.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本条记录即可；不涉及数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-30 Task 4 billing OpenAPI contract mismatch

- Symptom: generated clients reject a valid dashboard response, treat a legacy response as paginated, route an unrelated query parameter to the wrong mode, or cannot handle `internal_billing_response_error`.
- Diagnose: compare `docs/openapi.yaml` with `backend/billing_analytics.py#L269-L282` first. Analytics permits only `startDate`, `endDate`, and `groupBy=day|month`; strict ledger permits exactly `startDate`, `endDate`, `type`, `status`, `page >= 1`, and `pageSize=20|50|100`. Confirm the route checks only those six recognized dashboard parameters in `backend/central_server.py#L14119-L14139`; unrelated parameters preserve the raw legacy response.
- Validate: run `.\.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v`; this parses and resolves OpenAPI component references, validates representative analytics, strict-ledger, and raw legacy-ledger payloads, and compares strict OpenAPI surface/enums to the runtime Draft 2020-12 schemas. Then run the billing analytics and dashboard API suites before publishing documentation.
- Semantics: consumption excludes recharges and refunds, refund model-usage rows are represented as separate `refund/refunded` rows, and the daily average excludes zero-consumption days. The date range is operationally capped at 366 inclusive days. A 503 `billing_data_source_failed` must contain only a correlating `errorId`, never source credentials or connection data.
- RED/GREEN: review-fix RED ran `tests.test_openapi_contract.OpenApiContractTest.test_billing_dashboard_openapi_matches_runtime_query_and_response_contracts` and failed because both endpoints lacked documented 500 responses. GREEN and final-suite evidence is retained in `.tmp-validation/sdd/task-4-implementer-report.md`.
- Recovery: restore only the Task 4 documentation/test hunks if the published contract diverges from runtime. This task did not start or restart a process, make a production request, run a migration, or produce an image; retain the prior stable image tag for the later application release and roll back that release if new endpoint errors exceed 1%.

## 2026-07-30 Task 3 billing dashboard API failures
- Symptom: parameterized `/api/billing/analytics` or `/api/billing/ledger` returns 400, 500, or 503 while the legacy no-query ledger still works.
- Query diagnosis: HTTP 400 includes `error`, `message`, and `errorId`. Check date format/order, the 366-day maximum, `groupBy=day|month`, supported type/status values, page greater than zero, and `pageSize` in `20/50/100`. Unknown parameters are rejected on the new path; `userId` is never accepted because identity comes only from the authenticated current user.
- Response diagnosis: HTTP 500 `internal_billing_response_error` means the server generated a success payload that failed its response schema. Treat this as an internal defect, correlate `errorId` with `billing_response_invalid`, and do not ask the client to change its query.
- Source diagnosis: HTTP 503 `billing_data_source_failed` means a configured main DB could not establish readiness, its `configured()` check failed, its usage read failed, returned a malformed collection, or reached the 50,001-row overflow sentinel. No partial totals are returned. An absent or explicitly unconfigured main DB remains supported.
- Observability: correlate the response `errorId` with JSON events `billing_query_rejected`, `billing_response_invalid`, or `billing_data_source_failed`. Completion event `billing_analytics_completed` contains only the approved non-secret context; headers, tokens, signed URLs, and raw query values are excluded.
- Compatibility: `tests/test_billing_dashboard_api.py#L498-L552` locks the source branch and exercises the real `json_response` serializer for ledger requests containing none of the six new parameters; emitted UTF-8 bytes, status, shape, order, latest-100 limit, and helper bypass are verified.
- RED/GREEN: the remaining-findings focused RED was 4 tests with three expected failures; focused GREEN is 4/4. Final full-suite, compile, and diff-check results are retained in the Task 3 implementer report.
- Rollback: remove only Task 3 center-server hunks, the Task 3 test module, and these documentation/report entries. No restart or deployment was performed; a future release must retain the previous stable image tag and restore it if the new endpoint error rate exceeds 1%.

## 2026-07-30 Agent.模式视频模式仍显示“待修改图”
- 现象：在 `Agent.模式` 选择视频生成后，上传第 1 张图片仍显示“待修改图”，或生成视频时像是在修改第 1 张图。
- 根因：旧客户端复用了图片模式的上传语义，把第 1 张图当作编辑目标；但视频生成没有“待修改图”概念，上传图片应全部作为视频参考图。
- 修复：`backend/matrix_native_client.py#L16745-L16770` 将参考图描述改为模式感知；`backend/matrix_native_client.py#L16909-L16923` 视频生成传入 `is_video=True`；`backend/matrix_native_client.py#L22759-L22813` 结果卡片按视频模式显示“参考图1/参考图2/...”；`backend/matrix_native_client.py#L23408-L23486` 上传区视频模式标签和提示改为“参考图1/参考图2/...”，模式切换时会刷新。
- 处理：重启本地客户端后进入 `Agent.模式`，切到视频模式再上传图片；如果仍看到“待修改图”，检查运行中的客户端是否已包含上述代码。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_video_uploads_are_all_reference_images tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_generation_uses_all_uploaded_images_in_order -v`，应全部通过。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py` 和本条文档即可恢复旧规则；不涉及数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-30 资产库仍看到“文本”分类或独立文本卡片
- 现象：资产库顶部还显示“文本”筛选，或资产库里仍出现单独的文本素材卡片。
- 根因：旧客户端曾允许 `.txt/.md/.csv/.json/.log` 作为 `kind=text` 独立资产入库；现在采集参考视频已经在视频资产上绑定拆解文本，不再需要单独文本资产分类。
- 修复：`backend/matrix_native_client.py#L16959-L17036` 在加载资产库时清理历史 `kind=text` 记录，并阻止后续新增文本资产；`backend/matrix_native_client.py#L23865-L23899` 删除文本导入类型；`backend/matrix_native_client.py#L24010-L24144` 删除独立文本卡片和打开入口。采集参考视频的绑定文本仍通过视频卡片“文本”按钮查看。
- 处理：重启本地客户端后进入资产库刷新；如果仍看到文本卡片，检查运行中的客户端是否已包含上述代码。磁盘上的原始文本文件不会被本次清理主动删除，只是不再显示为资产库资产。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_asset_library_shared_button.AssetLibrarySharedButtonTest.test_text_assets_are_removed_from_asset_library tests.test_workflow_resilience.WorkflowResilienceTest.test_text_artifact_kind_is_not_standalone_asset tests.test_workflow_resilience.WorkflowResilienceTest.test_library_does_not_store_text_artifacts_as_standalone_assets tests.test_workflow_resilience.WorkflowResilienceTest.test_library_generates_and_attaches_reference_breakdown_text_per_video -v`，应全部通过。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`tests/test_workflow_resilience.py` 和本条文档即可恢复旧文本分类；不涉及数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-30 获客中心“使用账号”为空
- 现象：进入“获客中心 -> 寻找线索”后，“使用账号”下拉框完全空白，没有显示已登录账号，也没有“未找到已登录账号”的提示。
- 根因：`FinderPage/OutreachPage` 是 `GrowthPage` 内部 Tab，旧版切到“获客中心”时只触发外层页面显示，没有调用当前子 Tab 的 `on_show()`，所以账号加载没有执行。若本地执行引擎未启动或账号清单 JSON 损坏，旧版也会吞掉加载失败，表现仍像空框。
- 修复：`GrowthPage` 进入页面和切换 Tab 时会刷新当前子页；账号框初始化和刷新前显示“正在读取账号...”，加载失败时显示“账号加载失败，请刷新账号矩阵”。本地抖音账号清单损坏时会从账号 profile 目录恢复最小索引。
- 排查：先重启本地客户端；进入“账号矩阵”确认抖音账号显示在线；再回到“获客中心”。若仍失败，查看客户端日志中的 `account_matrix_load_failed` 或本地引擎日志中的 `douyin_accounts_registry_recovered`。当前 `boss` 目录账号接口已确认能返回 2 个在线抖音账号。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_finder_page_actions.FinderAccountLoadingTest -v` 和 `.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_multi_account.DouyinMultiAccountTest.test_load_douyin_accounts_recovers_from_profile_dirs_when_registry_json_is_corrupt -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`tests/test_finder_page_actions.py`、`tests/test_douyin_multi_account.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本条记录即可；不涉及数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-30 Task 2 main-DB billing traceability
- Scope: model-usage reads are bounded by a user ID and a half-open time range; successful future main-DB topups and model refunds also write a positive local state-ledger row for audit and Task 3 analytics.
- RED evidence: `tests.test_billing_unified` ran 21 tests with 5 errors and 2 failures before implementation. The failures covered the missing usage-reader entry point, missing positive ledger rows, and WeChat/redeem paths marking state as credited or used after a failed main-DB balance update.
- Retry boundary: WeChat orders remain `credited=false` and redeem codes remain `active` until `maindb.topup()` returns `ok=true`; failed updates add no positive ledger row. A repeated model refund returning zero preserves the existing idempotent success response and adds no duplicate row.
- GREEN evidence: `./.venv-win/Scripts/python.exe -m unittest tests.test_billing_unified -v` passed 21/21. `./.venv-win/Scripts/python.exe -m py_compile backend/maindb.py backend/central_server.py tests/test_billing_unified.py` exited 0.
- Review-fix evidence: a direct isolated-source regression proved `_exec(...)->(_, 0)` makes `maindb.topup()` return `ok=false`, and the center topup path consequently writes no positive ledger. A transaction-begin failure in `refund_generation()` now rolls back and propagates; the existing center exception path returns a failure without a ledger, while explicit `(false, 0)` remains the idempotent no-op. RED was 24 tests with these two expected failures; GREEN passed 24/24.
- Test environment: `.venv-win` has no `pymysql` and neither locked requirements file declares it. The direct SQL-contract test loads `maindb.py` with only driver/auth import stubs and patches `_q`; it verifies query construction without connecting to a database. No dependency or lockfile change is included in this task.
- Rollback: revert `backend/maindb.py`, the Task 2 hunks in `backend/central_server.py`, `tests/test_billing_unified.py`, and these two documentation entries. No schema, migration, deployment, remote service, or process restart was changed.

## 2026-07-30 账号矩阵移除账号失败 `account_not_found`
- 现象：账号矩阵里能看到抖音/小红书账号，但点击移除后提示 `移除失败:account_not_found`，看起来像所有账号都删不了。
- 根因：账号矩阵显示的是中心端账号和本机执行引擎账号合并后的结果；旧客户端点击移除时只调用中心端 `/api/accounts/remove`。很多账号实际只存在于本机执行引擎 `127.0.0.1:9081` 的 cookie/profile 注册表里，中心端查不到这些本机账号 ID，就返回 `account_not_found`。
- 修复：账号矩阵删除现在优先调用本机执行引擎 `/api/accounts/remove`；如果账号带有 `centralAccountId`，再尽量同步删除中心端记录。中心端返回 `account_not_found` 或 `accountnotfound` 时不再判定整体失败，因为本机账号删除才是账号矩阵移除的主结果。
- 默认账号边界：抖音默认账号 `douyin-self` 现在也允许移除，移除时写入本地禁用标记并清空内存登录态；默认不物理删除 cookie/profile 文件，重新登录抖音后会清除禁用标记并恢复显示。小红书 `xhs-self` 没有多账号注册表，移除时写入 `xhs_auth_state.json` 的禁用标记，让账号矩阵刷新后不再显示；重新登录小红书后会重新写入登录状态并恢复显示。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_douyin_multi_account tests.test_xhs_safety_mode` 通过 58 项；`.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py backend\api_server.py backend\platform_adapters.py` 通过。
- 回滚：回退 `backend/matrix_native_client.py`、`backend/api_server.py`、`backend/platform_adapters.py`、`tests/test_native_publish.py`、`tests/test_douyin_multi_account.py` 和本文档即可；不涉及数据库迁移、Docker、`migration.sql` 或中心端 schema 变更。

## 2026-07-30 账号矩阵多账号昵称与任务账号选择
- 现象：账号矩阵里多个抖音账号显示成 `douyin-17fdbbef58f7d574` 或 `抖音账号 f7d574` 这类临时名；内容采集、寻找线索、AI 触达、自动化工作流执行时也没有明确选择使用哪个账号。
- 根因：本地账号注册表只保存了账号 ID 和 cookie/profile，登录流程不一定能从平台页面自动解析真实昵称；业务页面提交搜索、下载、评论、触达任务时没有统一传 `accountId`，后端只能使用默认登录态。
- 修复：账号显示统一走 `account_display_name()` 和 `account_option_label()`，优先显示 `nickname/displayName/name` 中的真实昵称；账号矩阵新增“改名”按钮，保存到本地执行引擎 `/api/accounts/rename`；内容采集、寻找线索、AI 触达、素材发布、自动化工作流都使用账号下拉，任务 payload 带所选 `accountId`。
- 行为边界：改名只修改本机当前 Matrix 用户数据目录下的显示名，不修改平台昵称，不返回 cookie；如果账号存在但登录态不可用，页面提示“账号已存在，但登录态已失效。请到账号矩阵重新登录该平台账号后再采集。”。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_douyin_multi_account tests.test_workflow_account_scope tests.test_finder_page_actions` 通过 63 项；运行 `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py backend\api_server.py` 通过。
- 回滚：回退 `backend/matrix_native_client.py`、`backend/api_server.py`、`tests/test_native_publish.py`、`tests/test_douyin_multi_account.py`、`tests/test_workflow_account_scope.py` 和本文档即可；不涉及数据库迁移、Docker、`migration.sql` 或中心端 schema 变更。

## 2026-07-30 自动化工作流参考视频文本拆解显示成大表格
- 现象：点击资产库“采集参考视频”的“文本”按钮后，内容是很宽的 Markdown 表格，镜头信息被挤在一行里，用户难以阅读和复用。
- 根因：视频理解模型可能按“镜头序号/画面内容/台词/字幕/节奏/预估时长/可借鉴卖点”的横向表格输出；字段多且单元格内容长，在桌面弹窗里可读性很差。
- 修复：`backend/matrix_native_client.py#L15021-L15044` 的提示词禁止 Markdown 表格，要求直接输出镜头卡片；`backend/matrix_native_client.py#L14963-L15019` 在保存前把常见 Markdown 表格兜底转换成卡片式文本。
- 预期格式：`镜头 1｜价格钩子｜4秒`，下面分行显示 `画面：...`、`台词：...`、`节奏：...`、`可借鉴点：...`。文本可直接用于“用此文本生成视频”。
- 排查：如果新生成的文本仍是表格，确认运行中的本地客户端包含 `_workflow_normalize_reference_breakdown_text()`，并确认入库前调用的是新版 `_workflow_ensure_reference_text_artifacts()`。历史已保存的旧文本不会自动重写。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_workflow_resilience.WorkflowResilienceTest.test_reference_breakdown_markdown_table_is_normalized_to_readable_cards -v`，应通过。
- 回滚：恢复 `backend/matrix_native_client.py` 和相关测试/文档即可；无数据库迁移、OpenAPI、Docker 或 `migration.sql` 变化。

## 2026-07-30 账号矩阵抖音平台只显示 1 个账号
- 现象：boss 企业家账号的账号矩阵里，抖音卡片只显示 `1 个授权账号`，且账号行是 `lb-ch-202607151456`，但本机账号目录里实际存在多个抖音授权账号。
- 根因：本地客户端账号矩阵和素材发布页面只读取中心端 `/api/accounts`。中心端当时只登记了 1 条本地浏览器节点账号，而本机执行引擎 `127.0.0.1:9081 /api/accounts` 已能返回 boss 当前数据目录下的 4 个抖音账号。中心端登记和本机 cookie 账号不同步时，页面就只显示中心端那 1 条。
- 修复：`backend/matrix_native_client.py#L1020-L1085` 新增账号合并逻辑，优先使用本机执行引擎账号作为显示和发布选择来源，并把匹配到的中心账号 ID 保存在 `centralAccountId` 里；`backend/matrix_native_client.py#L4939` 让账号矩阵读取合并后的账号；`backend/matrix_native_client.py#L6603-L6626` 让素材发布使用同一套合并账号，并在发布任务里区分本机账号 ID 和中心账号 ID。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_account_matrix_metrics tests.test_douyin_multi_account`，账号合并、素材发布账号切换、账号指标和抖音多账号相关用例通过。
- 回滚：回退 `backend/matrix_native_client.py` 中的账号合并函数、账号矩阵/素材发布调用点，以及 `tests/test_native_publish.py` 中新增的账号合并测试即可；不涉及数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-30 资产库没有按时间放在一起
- 现象：资产库里的素材仍然平铺显示，或者同一天导入/生成的素材没有放在同一个日期标题下。
- 根因：旧客户端没有按资产时间分组渲染；历史资产可能只有 `ts` 字符串，没有新的 `createdAt` 数值时间；如果文件被移动或复制，文件修改时间也可能影响兜底排序。
- 修复：`backend/matrix_native_client.py#L16558-L16606` 新资产写入 `createdAt`；`backend/matrix_native_client.py#L23476-L23574` 按 `createdAt/updatedAt/mtime/ts/文件修改时间` 解析时间并渲染“今天/昨天/YYYY-MM-DD”分组；`backend/matrix_native_client.py#L23585-L23672` 在卡片上显示具体 `HH:mm`。
- 处理：确认已重启本地客户端；如果老资产显示“时间未知”，检查 `assets.json` 里是否缺少 `createdAt` 和 `ts`，以及素材文件是否仍在本机路径中。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_asset_library_shared_button.AssetLibrarySharedButtonTest.test_asset_library_groups_local_assets_by_date tests.test_asset_library_shared_button.AssetLibrarySharedButtonTest.test_asset_cards_show_created_time tests.test_asset_library_shared_button.AssetLibrarySharedButtonTest.test_add_asset_records_created_at_for_time_grouping -v`，应全部通过。
- 回滚：回退 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py` 和本条文档即可恢复旧的平铺列表；不涉及数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-30 漫剧视频未扣费、竖屏预览变横屏或合成被旧质检误拦截
- 现象：漫剧视频生成后账户中心没有清晰的视频模型消费记录；竖屏视频在预览弹窗中被横向裁切；视频播放结束时弹窗随表格刷新消失；`audioMode=auto` 的视频已经有声音并通过人工确认，仍提示“音频或质量检查未通过”。
- 根因：旧客户端没有按漫剧视频模型和分镜时长执行本地扣费；播放器使用 `cover` 填满固定横屏框且弹窗父对象是会刷新的表格单元格；最终合成沿用旧 LK888 链路的 `audioStatus/qcStatus` 硬门禁，而自动声音模式应以当前生成视频的真实音轨为准。
- 修复：`backend/matrix_native_client.py#L735-L925` 在每次新视频模型提交前读取漫剧价格并生成唯一扣费引用，提交/等待失败时按原引用退款，远程成功后的本地下载恢复不重复扣费；`backend/matrix_native_client.py#L2327-L2800` 使用保持宽高比的 `contain` 预览并将弹窗挂在稳定页面窗口上，播放结束不自动关闭；`backend/matrix_native_client.py#L20758-L20794` 对漫剧自动声音模式改查片段完成状态、人工确认、本地视频有效性和真实音轨。
- 账户中心：消费流水的“项目/模型”显示扣费原因中的模型，“任务详情”把 `comic_video:*` 引用显示为“项目 N · 片段 N · 漫剧视频”；失败退款以同一引用产生对应正向流水，便于追溯。
- 扣费边界：模型任务提交失败或远程明确失败会退款；远程生成已完成但本地下载/校验失败不会退款，因为模型成本已实际发生；点击恢复下载不会再次扣费。片段 JSON 的 `comicVideoBilling` 保存模型、计价模型、按秒/按次、单价、时长、金额和扣费引用。
- 价格风险：远程正式计费引擎支持 `price_per_call * duration * tier multiplier`，但当前 `/api/model-prices` 公开结果没有 `billing_method` 和 `price_tiers`。本地优先读取明确字段，缺失时根据描述、provider 和模型标识推断；如果账单与漫剧后台不一致，应先检查远程是否启用了分辨率、质量、版本、声音或口型档位，以及首选模型是否降级为不同价格的备用模型，不要在远程任务完成后硬编码补差价。
- 验证：运行 `tests.test_video_replacement`，再执行 `tests.test_video_replacement_v2` 中 `test_comic_video_preview_size_preserves_portrait_and_landscape_ratios` 与 `test_comic_video_preview_uses_stable_window_parent`，最后对客户端和两份测试执行语法检查。
- 回滚：恢复本地客户端、两份同款替换测试和本条文档即可；不需要回滚远程漫剧服务、中心服、数据库、OpenAPI、Docker 或 `migration.sql`。代码生效需用户手动重启本地客户端，本次不自动重启。

## 2026-07-30 提示“账号已存在，但登录态已失效”
- 现象：内容采集、获客中心或工作流里的小红书平台动作提示“账号已存在，但登录态已失效。请到账号矩阵重新登录该平台账号后再采集。”
- 含义：账号矩阵里的账号记录还在，但当前本机可用于自动化操作的 Cookie/profile 不可用。账号记录和浏览器登录态是两层数据，前者存在不代表后者一定有效。
- 常见原因：小红书 Cookie 过期、平台要求重新扫码/验证、当前 Matrix 登录用户的数据目录不同、本机 `xhs_profile` 被清理，或本地执行引擎仍停留在旧进程。
- 处理：进入账号矩阵，重新登录对应小红书账号；登录完成后重启本地客户端和本地执行引擎，再重新采集。若平台弹出验证，必须在浏览器里完成验证。
- 边界：Cookie 只保存在当前电脑和当前登录用户的数据目录下，不会同步给同企业其他成员，也不会从管理员电脑同步到普通用户电脑。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish.NativePublishTest.test_xhs_login_required_explains_saved_account_session_expired -v` 应通过。
- 回滚：回退 `backend/matrix_native_client.py`、`tests/test_native_publish.py` 和本条文档即可恢复旧提示；不涉及数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-30 自动化工作流采集 3 条但资产库只有 1 个参考视频且文本 0/0
- 现象：运行 `collect -> library` 两步工作流时，日志显示 `采集到 3 条`，但后续只显示 `采集参考视频 1/1`，并且 `文本 0/0`；资产库“采集参考视频”里只有 Top1 视频，没有每条视频对应的拆解文本按钮。
- 根因：旧版 `_exec_collect()` 只下载搜索结果的第一条 Top1；两步工作流没有显式 `vision` 步骤，旧版 `_exec_library()` 只登记已有文本产物，不会主动为采集参考视频做文本拆解。
- 修复：`backend/matrix_native_client.py#L14557-L14635` 按 `topN` 下载每条采集结果，全部作为参考视频入库；`backend/matrix_native_client.py#L14434-L14514` 为每个参考视频生成拆解文本；`backend/matrix_native_client.py#L14682-L14721` 把拆解文本作为视频资产元数据绑定。
- 资产库行为：`backend/matrix_native_client.py#L23198-L23336` 会在带 `textPath/breakdownPath` 的“采集参考视频”卡片上显示“文本”按钮；点击后可查看拆解内容，并用“用此文本生成视频”跳转到 `Agent.模式` 预填视频生成提示词。
- 预期日志：如果 `topN=3` 且 3 条都下载成功，应显示 `已下载 3/3 到采集参考素材`，入库阶段应显示类似 `文本 3/3, ... 采集参考视频 3/3`。如果某条视频理解和兜底都失败，该视频仍入库，但不会显示文本按钮，并会记录 `workflow reference breakdown` 日志。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_workflow_resilience tests.test_asset_library_shared_button -v`，应全部通过。
- 回滚：恢复 `backend/matrix_native_client.py`、相关测试和本条文档即可回到旧行为；无数据库迁移、OpenAPI、Docker 或 `migration.sql` 变化。

## 2026-07-30 同款替换重生无响应、片段过短、预览全屏与素材跑偏
- 现象：点击首帧、尾帧或视频“重新生成”看起来没有反应；约 12 秒口播只生成约 4 秒视频；视频列点击后全屏播放；分镜描述仍混入原片人物、汽车或展厅，导致上传素材优先级不明确。
- 根因：行内重生按钮在 `_busy=True` 时被直接禁用，处理函数也曾静默返回；漫剧项目使用固定 `duration_per_shot=5`，且请求未携带每段最终口播时长；视频预览通过重新挂载表格播放器并调用全屏；旧画面提示词保留了全局总结、OCR 和原片实体文本。
- 修复：`backend/matrix_native_client.py#L8789-L8880` 按最终口播稿估时，15 秒以内选择对应时长，超过 15 秒按标点递归拆成连续片段且不丢字；`backend/matrix_native_client.py#L10467-L10677` 将时长写入项目和视频请求。
- 修复：`backend/matrix_native_client.py#L10173-L10464` 写入人物、场景、道具的强制项目库绑定并发送分类参考图，原片只提供动作、镜头和节奏；`backend/matrix_native_client.py#L13147-L14070` 让重生按钮始终可点击并提供状态反馈及脱敏 JSON 事件。
- 修复：`backend/matrix_native_client.py#L2398-L2636` 使用独立播放器打开普通模态预览，最大尺寸为屏幕可用区域的 82%，关闭即释放媒体资源。
- 验证：`tests.test_video_replacement` 81/81 通过；语法检查通过；新增按钮真实点击、忙碌反馈、视频预览、资源释放、时长拆分和素材契约测试均通过。
- 已知基线：`tests.test_video_replacement_v2` 全量为 5 failures + 2 errors。4 条失败仍断言旧“回填原片音轨”行为，与当前已确认的 `audioMode=auto` 规则冲突；1 条失败和 2 条错误属于内容采集/XHS 测试夹具（缺 `_xhs_retry_context` 或旧页面文案），不在本次修改范围。本次相关用例均单独通过。
- 远程风险：本地请求已携带期望时长，但具体备用模型可能只支持离散时长槽位；远程服务仍需将不超过 15 秒的口播映射到模型可用槽位，例如 Vidu 可使用 16 秒生成槽位。若供应商忽略时长字段，应检查远程任务请求和实际模型元数据，不应再次在本地截断口播。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`tests/test_video_replacement_v2.py` 及本次文档记录；无需回滚中心服、漫剧服务、数据库、OpenAPI、Docker 或环境变量。用户将手动重启本地客户端。

## 2026-07-30 自动化工作流不需要后无法删除
- 现象：自动化工作流页可以启用、暂停、运行和修改参数，但不需要的工作流只能留在“我的工作流”列表里，无法直接清理。
- 根因：`WorkflowPage` 只提供刷新、运行和保存改动入口，没有从账号级 `workflows.json` 删除选中工作流的 UI 操作。
- 修复：`backend/matrix_native_client.py#L14895-L14899` 新增删除按钮；`backend/matrix_native_client.py#L14948-L14969` 增加确认删除逻辑，确认后 `WORKFLOWS.pop(row)`、`save_workflows()` 并刷新列表；`backend/matrix_native_client.py#L21811-L21820` 确保图标按钮不再生成非空 Qt tooltip。
- 行为边界：删除只移除工作流定义，不删除已生成素材、脚本、发布队列或 `wf_out` 文件；如果删除的是定时/启用工作流，后续调度自然不会再命中它。
- 验证：运行 `py -3 -m unittest tests.test_workflow_account_scope -v`，应全部通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_workflow_account_scope.py` 和本条文档/变更日志即可；不涉及数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 自动化工作流只生成文本、不生成视频
- 现象：自动化工作流运行后，图像生成、视频生成、语音合成或发布步骤显示已跳过；资产库里新增的是“文本”分类下的脚本/分镜，而不是视频素材。
- 根因：当前产品规则已强制把自动化工作流改为文本型，只做素材拆解、分镜/脚本生成和文本入资产库。历史工作流里即使还保留 `image/video/tts/publish` 步骤，运行时也不会调用模型、不会扣费、不会进入发布队列。
- 修复：`backend/matrix_native_client.py#L13699-L14132` 限制新工作流编排并跳过媒体/发布步骤；`backend/matrix_native_client.py#L22329-L22597` 在资产库新增“文本”分类和应用内文本阅读窗口。
- 排查：如果仍看到视频或语音模型被调用，先确认运行中的本地客户端源码包含 `文本型工作流:已跳过` 和 `禁止编排 image/video/tts/publish`；然后重启本地客户端与执行引擎。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_workflow_resilience tests.test_asset_library_shared_button -v` 应通过。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_workflow_resilience.py`、`tests/test_asset_library_shared_button.py` 和本节文档即可；不涉及数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 账号矩阵有小红书账号但内容采集仍提示登录
- 现象：账号矩阵里能看到小红书账号，但进入内容采集、小红书下载、图文同款下载、视频分解下载或评论发布时，仍提示需要登录小红书账号。
- 根因：账号矩阵中的账号记录只说明本地保存过账号信息；实际采集要依赖当前 Matrix 登录用户数据目录下的 `xhs_profile` 浏览器登录态。这个 profile 可能不存在、已过期、被平台登出，或当前客户端还在使用旧的本地执行引擎进程。
- 修复：`backend/matrix_native_client.py#L5260-L5414` 已让小红书采集入口默认使用账号矩阵本机登录态；`backend/api_server.py#L3519-L3536` 会在缺少可用 `xhs_profile` 时明确返回 `xhs_login_required/needLogin=true`。
- 处理：先在账号矩阵重新登录对应小红书账号，让本机生成新的 `xhs_profile`；然后重启本地客户端和本地执行引擎。若仍提示登录，说明 Cookie 被小红书判定失效或风控，需要在弹出的浏览器里重新完成扫码/验证。
- 注意：Cookie 只保存在本机、当前登录用户的数据目录下，不同步到中心服、企业空间或其他电脑。管理员在自己客户端添加的授权账号，不会自动变成其他企业用户电脑上的可用 Cookie。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish.NativePublishTest.test_xhs_content_collection_uses_saved_account_mode_by_default tests.test_xhs_safety_mode.XhsSafetyModeTest.test_account_collection_requires_saved_xhs_profile -v`，应全部通过。
- 回滚：回退 `backend/matrix_native_client.py`、`backend/api_server.py`、`tests/test_native_publish.py`、`tests/test_xhs_safety_mode.py` 和本条文档即可恢复旧的游客优先行为；不涉及数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 本地客户端鼠标悬停出现黑色提示框
- 现象：鼠标放到按钮、图片、素材卡片、登录选项、主题/退出按钮、状态文字或表格项上，会弹出系统黑色提示框，遮挡当前界面。
- 根因：本地客户端使用 Qt 原生 `setToolTip(...)` 提供悬停说明；当前主题下 tooltip 显示为黑框，且容易遮挡用户正在查看的内容。
- 修复：`backend/matrix_native_client.py#L4193-L24740` 已把所有 tooltip 统一清空，只保留页面内可见文字、按钮文案和状态栏反馈。
- 排查：运行 `rg -n "setToolTip\\(" backend\\matrix_native_client.py`，所有结果都应是 `setToolTip("")`。如后续新增说明，不要再用 tooltip，改为页面内小字、按钮文案、状态栏或弹窗。
- 验证：`tests/test_native_tooltips.py#L1-L33` 会禁止新增非空 tooltip；运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_tooltips -v` 应通过。
- 回滚：回退 `backend/matrix_native_client.py`、`tests/test_native_tooltips.py`、`CHANGELOG.md` 和本节文档即可；不涉及数据库、OpenAPI、Docker、中心服接口或 `migration.sql`。

## 2026-07-29 小红书看评论或获客中心要求登录账号
- 现象：内容采集页点击“小红书 -> 看评论”或获客中心选择“小红书”寻客时，状态提示为“账号读取评论中 / 账号寻客中”，并要求本地小红书账号已登录。
- 根因：小红书评论区和评论型获客数据通常不对游客稳定开放。按当前业务规则，这两类功能不再从游客模式开始尝试，直接使用已登录小红书账号，并计入风控中心。
- 修复：`backend/matrix_native_client.py#L4373-L4547` 和 `backend/matrix_native_client.py#L5387-L5404` 已让客户端直接发送 `guestMode=false/accountCollectionConfirmed=true`；`backend/api_server.py#L5644-L5669`、`backend/api_server.py#L6047-L6074`、`backend/api_server.py#L6262-L6278` 已让评论读取接口默认走账号确认门禁。
- 排查：如果返回 `xhs_account_collection_unconfirmed`，说明调用方没有传 `accountCollectionConfirmed=true`；如果返回 `xhs_login_required`，先到账号中心登录小红书；如果返回 `xhs_safety_interval`、`xhs_safety_daily_limit` 或 `xhs_safety_paused`，按风控中心限制处理。
- 风控关系：搜索、下载和图文同款下载仍是游客优先；看评论和获客中心小红书寻客是账号行为，会写入小红书安全模式计数。
- 回滚：恢复游客优先评论读取需回滚 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_native_publish.py`、`tests/test_api_download_contract.py`、`CHANGELOG.md` 和本节文档；不涉及数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 小红书图文同款图片悬停出现黑色提示框
- 现象：进入“图文同款”后，鼠标放到原图缩略图或替换图片槽位上，会弹出一条黑色悬停提示框，遮挡图片区域。
- 根因：这些图片控件使用了 Qt 原生 tooltip，原图按钮写入“查看原图”，替换槽位写入“选择第 N 张替换图片/替换图文件名”。系统主题会把 tooltip 渲染成黑框。
- 修复：`backend/matrix_native_client.py#L8917-L9115` 已清空图文同款原图缩略图和替换图片槽位的 tooltip，点击查看原图、点击选择替换图的功能不变。
- 排查：如果重启后仍出现黑框，先确认运行中的本地客户端源码包含这些 `button.setToolTip("")`；若黑框出现在其他页面，需要按对应控件继续查找 `setToolTip(...)`。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_collection_handoff_renders_downloaded_source_thumbnails tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_replacement_slots_fill_multiple_files_in_order -v` 应通过。
- 回滚：回退 `backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py` 和本条文档记录即可；不涉及数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 小红书游客搜索结果和关键词不一致
- 现象：内容采集页选择小红书并搜索“丰田汽车”，列表里却出现与汽车无关的标题，像是小红书发现页/推荐流内容。
- 根因：未登录游客访问时，小红书 PC 页面可能不真正进入关键词搜索结果页，而是停在发现页推荐流。旧逻辑只要页面里有笔记卡片就会采集，导致把推荐流误当成关键词搜索结果。
- 修复：`backend/platform_adapters.py#L605-L622` 新增搜索 URL 关键词校验；`backend/platform_adapters.py#L624-L834` 要求捕获到 `/search/notes` 接口响应，或确认当前 URL 是对应关键词的 `search_result` 页面后，才接受页面笔记。否则返回 `message=xhs_search_result_unverified` 并触发游客受限流程。
- 处理：普通用户看到“公开访问受限”后，可选择“使用账号采集一次”；如果取消，系统不会展示无关推荐流，也不会消耗账号风控次数。
- 排查：如果仍出现明显无关结果，确认本地执行引擎已经重启；保留截图和 `backend/datas/**/debug/xhs-search-unverified-*` 快照，检查小红书是否改了搜索 URL 或搜索接口名称。
- 回滚：回滚 `backend/platform_adapters.py`、`tests/test_xhs_lead_filtering.py`、`CHANGELOG.md` 和本节文档即可；不涉及数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 小红书游客采集时浏览器弹出登录框
- 现象：内容采集页显示“小红书游客采集 / 不使用登录账号”，但打开的小红书网页出现“手机号登录”“扫码登录”或“登录后推荐更懂你的笔记”的弹窗。
- 根因：游客采集只表示系统不主动读取登录账号 profile、Cookie 或授权状态；小红书网页仍可能对公开访问弹出登录墙。旧逻辑没有先处理这个网页弹窗，导致用户看到登录框遮住页面。
- 修复：`backend/platform_adapters.py#L166-L220` 新增登录弹窗自动关闭；搜索、读取评论和笔记下载加载页面后都会先尝试关闭一次，搜索跳转后会再检查一次。关闭成功后继续游客采集；关闭失败时返回 `xhs_guest_login_required`，客户端弹出“公开访问受限”确认框。
- 排查：如果仍看到登录框，先确认本地执行引擎已重启；再看客户端是否弹出“公开访问受限”。有确认框时，说明公开访问被平台限制，用户可选择“使用账号采集一次”或取消。没有确认框且一直卡住时，保留截图和本地 `backend/datas/**/debug/xhs-*` 快照继续排查页面结构变化。
- 回滚：临时恢复旧默认账号采集可设置 `XHS_GUEST_COLLECTION_DEFAULT=0` 并重启本地客户端和本地执行引擎；代码级回滚恢复 `backend/platform_adapters.py`、`tests/test_xhs_lead_filtering.py`、`CHANGELOG.md` 和本节文档。不涉及数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 企业家团队成员页仍显示“添加企业 / 添加成员”
- 现象：左下角账号角色已经显示为“企业家”，但进入“企业中心 -> 团队成员”后，页头仍出现“添加企业”和“添加成员”按钮。
- 根因：本地客户端启动时默认角色曾是 `platform_admin`，团队成员页如果在登录角色刷新前创建，只在初始化时判断一次按钮可见性；后续登录成企业家后没有重新应用角色状态，导致管理员按钮残留。
- 修复：`backend/matrix_native_client.py#L3589-L3594` 新增 `_apply_role_visibility()`；`backend/matrix_native_client.py#L3597-L3598` 和 `backend/matrix_native_client.py#L3705-L3706` 在进入页面和成员数据回调时重新隐藏企业家不可见按钮。
- 排查：重启本地客户端后，用 boss/企业家账号进入团队成员页，应只看到“刷新 / 邀请成员”，不应看到“添加企业 / 添加成员”和企业切换下拉框。如果仍显示，说明运行的不是当前工作区代码，或客户端没有重启。
- 验证命令：`python -m unittest tests.test_role_permissions.RolePermissionsTest.test_enterprise_members_page_reapplies_role_visibility_after_login -v`。
- 回滚：回退 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`；不涉及中心服、数据库迁移或 `migration.sql`。

## 2026-07-29 同款替换生成首尾帧但云豆没有扣费
- 现象：同款替换里“生成首尾帧”已经产出首帧图和尾帧图，但账户中心没有出现对应云豆扣费流水。
- 根因：这条链路调用漫剧服务 `/api/v1/comic-drama/storyboards/{id}/generate-image`，旧逻辑没有先走 Matrix `/api/billing/charge`；只有 LK888 反代 `/v1/images/generations` 会由中心服自动扣费。
- 修复：`backend/matrix_native_client.py#L11819-L11901` 和 `backend/matrix_native_client.py#L11959-L11961` 在提交首尾帧前按 `comic_keyframe_image` 逐帧扣费；`backend/central_server.py#L2928-L2939` 把该能力定价为 `0.14` 云豆，和 LK888 图片生成价一致。失败、取消、等待失败或结果缺失时按原 `ref` 退款。
- 排查：在账户流水里查 `ref` 前缀 `comic_keyframe:`，应看到同一片段的 `frame:1` 和 `frame:2` 两条负数流水；如果失败，应看到对应退款流水。管理员 `user-owner` 仍按中心服规则免扣。
- 验证命令：`python -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_charges_each_generated_keyframe_before_submit tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_refunds_charged_keyframes_when_frame_wait_fails tests.test_billing_unified.UnifiedBillingTest.test_capability_prices_are_one_yundou_per_yuan -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_video_replacement.py`、`tests/test_billing_unified.py`、`docs/API_REFERENCE.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md`；不涉及数据库迁移或 `migration.sql`。

## 2026-07-29 同款替换页面还看到“暂无预览”或“原片主角确认”
- 现象：同款替换素材区域仍显示左侧“暂无预览”框、右侧“漫剧项目模式：使用上传人物图作为角色参考”，或还有“原片主角确认”下拉框。
- 根因：旧页面保留了原片主角预览和人工确认入口；当前流程已改为以上传主角人物图作为替换身份来源，低置信度原片主角候选由客户端自动使用第一张候选帧，不再需要用户在页面确认。
- 修复：`backend/matrix_native_client.py#L10436-L10494` 已删除这组三个界面元素；`backend/matrix_native_client.py#L10717-L10731` 自动确认低置信度候选帧。
- 排查：如果重启后仍显示这些内容，说明运行的不是当前工作区版本，或本地客户端没有重启。检查源码里不应再有 `self.principal_actor_preview = QtWidgets.QLabel("暂无预览")`、`refs_l.addWidget(QtWidgets.QLabel("原片主角确认")` 或 `self.target_person = QtWidgets.QComboBox()`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及中心服、数据库或 `migration.sql`。

## 2026-07-29 同款替换声音来源没有“原片声音”
- 现象：同款替换“声音来源”下拉框只看到“自动 / AI 音色配音 / 上传完整配音”，不再有“原片声音”；选择“自动”后片段不会生成 TTS。
- 原因：新规则下“不选择 AI 音色”代表使用远程模型生成视频自带声音，系统不再把原片片段音频回填到新视频里，避免用户以为仍在复用原片原声。
- 排查：查看任务 JSON 的 `audioMode`。`auto` 表示保留生成视频自带声音；历史任务里的 `source/origin/original/source_audio` 会兼容映射为 `auto`；`tts` 表示逐段 AI 音色配音；`uploaded` 表示最终整条音轨替换。
- 注意：`auto` 不会读取或混入原片声音。如果生成模型返回的视频本身无声，后续音频 QC 仍可能提示 `audio_missing` 或 `audio_silent`，这时应重试片段，或改选 AI 音色/上传完整配音。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/API_REFERENCE.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及中心服、数据库或 `migration.sql`。

## 2026-07-29 同款替换操作列“重生/删除”按钮过长或重叠
- 现象：同款替换片段表右侧“操作”列中，“重生”和“删除”两个按钮显示成长条，窄列下互相压住或文字重叠。
- 根因：旧漫剧项目模式在 172px 操作列里同时放两个 72px 文本按钮，加上布局边距后空间不足；普通替换模式删除按钮也使用 92px 文本按钮，容易被全局按钮样式和表格宽度共同挤压。
- 修复：`backend/matrix_native_client.py#L12232-L12277` 统一改成 30px 圆形图标按钮，重生为循环箭头，删除为垃圾桶；按钮含义写入 tooltip，布局间距固定 4px 并居中显示。
- 排查：如果重启后仍显示长条按钮，确认运行中的客户端源码不再包含 `QtWidgets.QPushButton("重生")`、`QtWidgets.QPushButton("删除")`、`setFixedSize(72, 30)` 或 `setFixedSize(92, 30)`；若仍存在，说明运行的不是当前工作区版本或客户端尚未重启。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_replacement_segment_actions_use_compact_icon_buttons -v` 应通过；完整相关验证可运行同款替换表格三项测试和 `py_compile`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节文档即可；不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 小红书游客采集受限或提示账号采集未确认
- 现象：内容搜索、小红书笔记下载或图文同款下载返回 `xhs_guest_login_required`、`xhs_guest_access_limited`、`xhs_ip_risk`，客户端弹出“公开访问受限”；如果外部直接调用账号采集接口但没有确认字段，会返回 `xhs_account_collection_unconfirmed`。
- 根因：小红书搜索、下载和图文同款下载现在默认游客模式，系统不会自动使用登录账号。只有公开访问受限且用户明确点击“使用账号采集一次”后，当前动作才会以登录账号重试一次。读取评论和获客中心小红书寻客已经改为直接账号模式。
- 处理：普通用户在弹窗中选择“使用账号采集一次”即可继续本次操作；如果取消，任务会停止，不会消耗账号风控次数。接口调用方必须同时传 `guestMode=false` 和 `accountCollectionConfirmed=true`，否则会被本地执行引擎拒绝。
- 可观测：游客受限会记录 `xhs_guest_collection_blocked`，只包含动作、错误码、风险码、关键词长度和 URL 指纹；确认账号采集会记录 `xhs_account_collection_confirmed` 和安全快照。不要在日志中查找完整 Cookie、Token、正文或完整 URL，这些字段会被脱敏或不会记录。
- 风控关系：游客采集不写入 `xhs_safety_state.json` 计数；确认账号采集、读取评论和获客中心小红书寻客仍受每日上限、评论上限、冷却间隔和账号暂停状态限制。如果返回 `xhs_safety_interval` 或 `xhs_safety_paused`，按“小红书安全模式”章节处理。
- 回滚：临时恢复旧默认行为可设置 `XHS_GUEST_COLLECTION_DEFAULT=0` 并重启本地客户端和本地执行引擎。代码级回滚恢复 `backend/platform_adapters.py`、`backend/api_server.py`、`backend/matrix_native_client.py`、相关测试和本节文档即可；不涉及数据库迁移、OpenAPI 新路由、Docker 或 `migration.sql`。

## 2026-07-29 Seedance 提示音频时长必须小于等于 15.2 秒
- 现象：首尾帧已经完成，视频提交后立即失败，错误包含 `InvalidParameter`、`audio duration (seconds)`、`less than or equal to 15.2` 和 `doubao-seedance-2-0 in r2v`。真实任务片段 2 的错误编号为 `err-2688d3e4d1bf48d9`。
- 根因：漫剧生成器把完整口播音频传给 Seedance R2V，但该模型对本次请求给出的音频上限是 15.2 秒；旧降级入口只识别真人隐私拒绝，因此不会切到不使用该音频字段的 Vidu/首尾帧备用模型。
- 修复：只把上述完整特征匹配为 `InvalidParameter.AudioDurationExceeded` 并进入 `Seedance -> Vidu Q3 -> 万相 2.7 -> Kling V3 Omni -> PixVerse V6`。备用请求移除音频字段，保留完整口播稿与项目音色配置；分辨率、缺字段等普通参数错误不降级。
- 排查：查看任务 `fallbackReason/fallbackHistory`；修复后应看到 Seedance 失败退款、Vidu 为下一条 submitted 记录。本次仅重生失败片段 2，片段 1、3 的视频路径和远程任务保持不变。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_aicanvas_real_person_fallback -v` 应通过 8 项；完整相关回归 272/272 通过。
- 回滚：恢复发布前 `server.py` 时间戳备份并重启 `ai-canvas.service`；不涉及数据库、中心服或本地客户端重启。

## 2026-07-29 同款替换新建 3 片段却出现多余角色、道具和 6 个分镜
- 现象：真实测试项目 298 预期只有 3 个片段、1 个角色、1 个场景和 1 个道具，实际项目库出现 4 个角色、2 个道具和 6 个分镜。
- 根因：客户端先创建只有 `source_text` 的空项目，再调用 `/analyze`。漫剧分析器把结构化 3 段剧本再次扩写，并在手动素材上传前自动创建占位角色、场景和道具，随后手动素材又追加一遍。
- 修复：同款替换项目创建载荷增加 `source_mode=matrix_video_replacement`、`manualAssetsOnly=true`、精确 `storyboardCount` 和 `storyboards`。远程创建函数只在该来源模式下直接建立对应数量的分镜并保持资产库为空；普通漫剧项目仍走原分析流程。
- 排查：新任务创建后、提交任何图片或视频生成前，检查项目必须恰好有 3 个分镜，资产上传完成后必须恰好有 1 个带 `Zephyr` 音色的角色、1 个场景和 1 个道具。若数量异常，停止任务，不要恢复项目 298，也不要继续产生模型费用。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_payload_uses_keyframes_and_manual_assets tests.test_aicanvas_matrix_project_seed -v`；完整相关回归运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement tests.test_video_replacement_v2 tests.test_aicanvas_real_person_fallback tests.test_aicanvas_matrix_project_seed -v`，当前结果 272/272。
- 回滚：恢复远程部署前 `server.py` 备份并重启 `ai-canvas.service`；回滚本地客户端载荷和新增测试。无数据库迁移，按用户要求不自动重启本地客户端。

## 2026-07-29 小红书标题超过 20 字
- 现象：图文同款生成的方案标题或 AI 预填的“标题（必填）”超过 20 字；或者素材发布选择小红书后仍按 30 字提交标题。
- 根因：旧实现只沿用了抖音 30 字标题限制，图文同款候选标题由业务名、地区和卖点直接拼接，长业务名会生成超过小红书限制的标题；素材发布页表头也只提示 30 字，发布时固定 `publish_title[:30]`。
- 修复：`backend/xhs_note_replacement.py#L8-L110` 将图文同款标题限制为 20 字；`backend/matrix_native_client.py#L4633-L4635` 和 `backend/matrix_native_client.py#L8969-L8969` 限制 AI 预填标题；`backend/matrix_native_client.py#L5649-L5722` 让素材发布提示和实际截断按平台区分。
- 排查：如果界面仍显示超长标题，先确认是否在查看旧草稿或旧预览结果；旧任务 JSON 不会自动重写，需要重新点击“生成同款预览”。如果发布仍按 30 字，确认本地客户端已重启并且素材发布标题列包含“抖音最多30字，小红书最多20字”。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNotePreviewTests.test_copy_candidate_titles_fit_xhs_title_limit tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_collection_handoff_ai_prefill_title_fits_xhs_limit -v` 和 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish.NativePublishTest.test_native_publish_title_header_shows_platform_title_limits tests.test_native_publish.NativePublishTest.test_native_publish_limits_title_length_by_selected_platform -v` 应通过。
- 回滚：回滚 `backend/xhs_note_replacement.py`、`backend/matrix_native_client.py`、相关测试和本节文档即可；不涉及数据库迁移、OpenAPI 或部署脚本。

## 2026-07-29 Agent.模式上传图悬浮黑框内容看不见
- 现象：鼠标放到 Agent.模式顶部已上传图片上时，出现一个很长的黑色悬浮提示框，但里面的文字几乎看不清。
- 根因：系统 tooltip 在当前深色界面和白天主题里可读性不稳定；即使缩短文字，用户仍可能只看到黑框。
- 修复：`backend/matrix_native_client.py#L20488-L20494` 清空按钮 tooltip，把操作提示改为缩略图下方可见小字“点击替换 / 右键删除”。
- 排查：如果重启后仍出现黑框，确认运行中的源码在 `_make_ref_cell()` 内包含 `btn.setToolTip("")`，并且 QLabel 文案包含“点击替换 / 右键删除”。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_asset_library_shared_button.AssetLibrarySharedButtonTest.test_agent_reference_thumbnail_shows_inline_usage_hint -v` 应通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节文档即可恢复旧长提示。

## 2026-07-29 资产库图文同款打开 JSON
- 现象：资产库中保存的“图文模板 / 图文同款”卡片第一个按钮会直接打开本地 `.json` 模板文件，用户容易误以为这是可编辑素材内容。
- 根因：图文模板资产本质是本地模板 JSON，加上缩略图元数据；旧卡片复用了普通图片/视频资产的“打开”动作，导致直接调用系统默认程序打开 JSON。
- 修复：`backend/matrix_native_client.py#L21033-L21037` 删除 `note_template` 卡片的“打开”按钮，只保留“文件夹”和“删除”。
- 排查：如果重启后仍能从图文模板卡片直接打开 JSON，确认运行中的源码在 `elif kind == "note_template":` 分支下不再包含 `lambda: self.open_asset(a)`。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_asset_library_shared_button.AssetLibrarySharedButtonTest.test_note_template_asset_cards_do_not_open_json_directly -v` 应通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节文档即可；回滚后图文模板卡片会恢复“打开 JSON”入口。

## 2026-07-29 小红书内容采集不弹出浏览器
- 现象：在内容采集页选择“小红书”后点击搜索、下载或图文同款，用户看不到小红书浏览器窗口，无法处理登录、验证码或风控验证。
- 根因：旧实现中 `_xhs_open_context()` 默认 `default_headless=True`，小红书搜索使用 `XHS_SEARCH_HEADLESS`，下载使用 `XHS_DOWNLOAD_HEADLESS`，但两者没有显式改默认值，因此采集链路默认后台运行；小红书发布单独传了 `default_headless=False`，所以发布会弹浏览器而采集不会。
- 修复：`backend/platform_adapters.py#L99-L107` 保留默认参数并允许调用方指定；`backend/platform_adapters.py#L522-L535` 和 `backend/platform_adapters.py#L1500-L1513` 将小红书搜索/下载默认改为显示浏览器。`backend/matrix_native_client.py#L5117-L5159` 同步增加采集页状态提示。
- 排查：如果重启后仍不弹窗，先确认运行环境没有设置 `XHS_SEARCH_HEADLESS=1` 或 `XHS_DOWNLOAD_HEADLESS=1`；再确认运行中的本地执行引擎加载的是当前工作区代码，并且浏览器没有被系统最小化或弹到其他屏幕。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish.NativePublishTest.test_xhs_collection_browser_is_visible_by_default -v` 和 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_xhs_collection_actions_explain_visible_browser -v` 应通过。
- 回滚：临时回滚可设置 `XHS_SEARCH_HEADLESS=1`、`XHS_DOWNLOAD_HEADLESS=1` 并重启本地执行引擎；代码回滚恢复 `backend/platform_adapters.py`、`backend/matrix_native_client.py`、相关测试和本节文档即可。本次不涉及数据库迁移、OpenAPI 或部署脚本。

## 2026-07-29 Agent.模式上传图片槽位左右留白
- 现象：Agent.模式顶部“待修改图 / 添加图片”槽位里，已上传图片只显示在中间一小块，左右两边有明显空白。
- 根因：旧上传槽按钮固定为 `56px × 56px`，缩略图只生成 `52px × 52px` 后居中显示；在横向上传框视觉里会显得内容没有铺满。
- 修复：`backend/matrix_native_client.py#L19437-L19439` 统一槽位尺寸；`backend/matrix_native_client.py#L20266-L20307` 将上传图和添加图按钮都改为 `112px × 56px`，上传图按槽位尺寸居中裁切铺满，按钮样式去掉内边距。
- 排查：如果重启后仍有左右空白，确认运行中的源码包含 `REF_SLOT_W = 112`、`REF_SLOT_H = 56`、`pm.scaled(REF_SLOT_W, REF_SLOT_H, QtCore.Qt.KeepAspectRatioByExpanding` 和 `btn.setIconSize(QtCore.QSize(REF_SLOT_W, REF_SLOT_H))`；若缺任一项，说明运行的不是当前工作区版本或本地客户端尚未重启。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_reference_slots_fill_horizontal_content_area -v` 应通过；再运行相关 `py_compile`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节文档即可；回滚后上传缩略图会恢复旧的 52px 居中显示。

## 2026-07-29 双帧任务与相对媒体地址冒烟
- 现象：漫剧图片接口返回首帧和尾帧两个 `task_ids` 时，本地只保存第一个任务；远程视频已生成但返回 `/uploads/...` 时，客户端下载报 `Invalid URL`。
- RED：运行双帧与 URL 两项最小测试，分别因缺少 `_comic_extract_task_ids` 和 `_comic_absolute_media_url` 报 `AttributeError`。
- 根因：旧 helper 把 `task_ids` 列表压缩成首项；下载链路直接使用远程返回值，没有基于漫剧服务器地址补全相对路径。
- 修复：新增有序去重的任务 ID 列表解析，并保留 `_comic_extract_task_id` 首项兼容；新增媒体 URL 规范化 helper，绝对 HTTP(S) 地址保持不变。
- 验证：运行 `\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_extract_task_ids_keeps_start_and_end_order tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_absolute_media_url_joins_remote_upload_path -v`，结果 2/2 通过；`py_compile backend/matrix_native_client.py` 退出码 0。
- 回滚：恢复 `backend/matrix_native_client.py`、对应测试和本节文档；本阶段不涉及远程服务、数据库或进程重启。

## 2026-07-28 分解视频点击“打开视频”没有反应
- 现象：分解视频完成后点击“打开视频”，页面没有明显变化，用户不知道是播放器没弹出、视频文件被清理，还是按钮未触发。
- 根因：旧 `VideoBreakdownPage.open_video()` 只调用系统默认打开函数；`os.startfile()` 成功返回后不更新状态栏，默认播放器没有弹窗或没有 mp4 关联时看起来像按钮没反应；源视频文件被移动或清理时也缺少前置判断。
- 修复：`backend/matrix_native_client.py#L5573-L5587` 先校验本地视频文件存在，再打开；成功、文件缺失、打开失败均写状态栏。`backend/matrix_native_client.py#L12043-L12065` 新增文件管理器定位兜底，播放器打不开时自动打开视频所在文件夹并选中文件。
- 排查：如果状态栏提示“视频文件不存在”，需要重新从内容采集下载并分解；如果提示“已打开视频文件”但没弹播放器，检查系统默认 mp4 播放器；如果提示“已打开视频所在文件夹”，请手动双击该文件或安装/设置默认播放器。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_breakdown -v` 应通过 39 项；再运行 `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_breakdown.py`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_breakdown.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节文档即可；不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-28 资产库素材卡片按钮重叠
- 现象：资产库素材卡片底部按钮挤压，或“播放 / 文件夹 / 删除”虽然已经没有文字，但按钮外框仍被撑成长条并互相覆盖；修窄后又全部聚集在左侧。
- 根因：资产卡片宽度固定为 232px；旧文字按钮本身过宽。第一次改成图标按钮后，公共圆形按钮仍继承全局 `QPushButton min-width:76px` 和 padding，导致 30px 图标按钮外框继续显示成长条；修成固定图标按钮后，动作行仍按默认从左到右追加，空白都留在右侧。
- 修复：`backend/matrix_native_client.py#L19553-L19565` 让 `_round_icon_btn()` 自身固定布局策略，并在局部样式里写死 `padding:0`、`min/max-width/height`；`backend/matrix_native_client.py#L20730-L20800` 继续用 30px 纯图标按钮，并通过 `_add_asset_action_buttons()` 在按钮前后与按钮之间加入等权重弹性空白，让按钮均匀分布在整行。
- 排查：如果重启后仍重叠或靠左聚集，先确认运行中的客户端源码包含 `padding:0;min-width:%dpx;max-width:%dpx;min-height:%dpx;max-height:%dpx;`、`actions.setSpacing(0)`、`_add_asset_action_buttons` 和 `actions.addStretch(1)`；若缺任一项，说明运行的不是当前工作区版本或本地客户端尚未重启。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_asset_library_shared_button -v` 应通过 6 项；再运行 `py_compile` 和 `git diff --check` 确认语法与空白检查无异常。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节文档即可；回滚后资产卡片按钮会恢复旧布局，窄卡片下可能再次变高或重叠。

## 2026-07-29 Seedance 首尾帧视频降级链
- 现象：首尾帧和完整 TTS 音频已经生成，但视频提交立即失败，错误包含 `InputImageSensitiveContentDetected.PrivacyInformation` 或“input image may contain real person”，没有拿到 Ark 远程任务 ID，最终视频也无法拼接。
- 根因：官方 Ark Seedance 对输入参考图执行真人隐私审核；即使素材已获用户授权，上游仍可能拒绝该真人参考图。这不是首尾帧、口播稿、音频或本地拼接失败，也不能通过修改提示词绕过。
- 修复：精确命中真人隐私错误后按 `Vidu Q3 多参考 -> 万相 2.7 首尾帧 -> Kling V3 Omni 首尾帧 -> PixVerse V6 首尾帧` 依次尝试。Vidu 保留最多七张参考图，其余模型只发送首尾两张图并删除不支持的音频和口型字段。
- 观测：响应包含 `fallback_applied`、`requested_model`、`actual_model`、`fallback_candidates`、`fallback_index` 和 `fallback_history`。已受理的备用任务明确失败时，本地任务 ID 不变并推进下一模型；每个失败扣费仅退款一次。
- 排查：仍直接得到 `ai-failed-*` 时检查 8777 是否加载新 `server.py`，以及复数环境变量是否被显式设为空。查询超时、502 或限流期间不要再次点击生成，应继续查询已有远程任务，避免重复计费。
- 验证：RED 阶段旧单模型分支因 `fallback_attempted` 未定义产生 4 个错误，且远程失败不会续切；修复后 `tests.test_aicanvas_real_person_fallback` 7/7 通过。完整 `tests.test_video_replacement + tests.test_video_replacement_v2 + tests.test_aicanvas_real_person_fallback` 共 269/269 通过，两个 Python 文件编译通过。
- 回滚：恢复本次部署生成的 `/root/AI-CanvasPro/server.py.bak.<timestamp>` 后只重启 8777；或显式设置空的 `COMIC_REAL_PERSON_VIDEO_FALLBACK_MODELS` 并重启 8777 临时关闭降级。本次不涉及数据库、OpenAPI、中心服或本地客户端进程。

## 2026-07-28 漫剧项目出现多个同一人物或停在本地配音测时长
- 现象：上传同一人物的多张照片后，漫剧项目库出现“主角、角色2、角色3”；或者生成进度停在“生成配音并测量真实时长”，台词稍长时本地先修改时长或阻断生成。
- 根因：旧客户端把每张人物参考图都转换成独立角色，并在首尾帧生成前调用本地 `prepare-dialogue-audio`，用临时音频时长覆盖片段时长。这与“一个人物只创建一个主角、完整台词交给漫剧端自动延长”的新规则冲突。
- 修复：`backend/matrix_native_client.py#L9082-L9133` 只用第一张人物图创建“主角”；`backend/matrix_native_client.py#L10106-L10120` 把所有同款替换模式统一为单图选择；`backend/matrix_native_client.py#L10698-L10763` 删除本地配音准备阶段并清理历史音频准备字段；`backend/matrix_native_client.py#L9136-L9165` 把完整台词、AI 音色和 `auto_match_audio_duration=true` 直接交给漫剧生成器。
- 排查：新任务中 `personReferencePaths/personReferenceUrls` 应最多各有 1 项，漫剧项目库应只有一个由本地同步的“主角”。若进度仍显示本地配音测时长，说明运行的是旧客户端进程；本次按用户要求未自动重启，需要用户手动重启后新建任务验证。旧远程项目不会因本地代码更新自动删除重复角色。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement tests.test_video_replacement_v2 -q`，应分别通过 32 项和 219 项；再运行 `py_compile` 和 `git diff --check`。
- 回滚：回滚 `backend/matrix_native_client.py`、两套同款替换测试和本次文档条目即可恢复旧行为；本次没有修改中心服、远程漫剧服务代码、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-28 漫剧任务上传一张人物图仍提示需要三张
- 现象：任务已选择一张“主角正脸全身照”，点击生成仍弹出“旧版同款替换需要三张授权人脸照片：正脸、左45°、右45°”。
- 根因：任务 JSON 已是 `replacementMode=comic_project`，但 `start_generation()` 会在漫剧模式把 `principal_enabled` 设为 `False`，随后错误进入没有模式限制的 `elif len(self._face_paths) != 3` 分支。因此这是公共校验条件错误，不是任务模式、人物图片或远程漫剧服务错误。
- 修复：所有同款替换模式统一只接受一张人物图；单文件选择、上传、任务字段和开始生成校验均只保留第一张，删除三图拦截和提示。产品图仍保持原有 1-3 张规则。
- 验证：`tests.test_video_replacement.VideoReplacementHelpersTest.test_video_replacement_uses_one_person_reference_in_every_mode` 已先复现失败再通过；完整回归见交付结果。
- 回滚：恢复本地客户端、两套同款替换测试及本节文档即可。该改动不涉及中心服、远程漫剧、数据库或接口契约；按用户要求不自动重启本地客户端。

## 2026-07-28 资产库点击顶部按钮只打开文件夹但没有导入素材
- 现象：用户在资产库点击顶部“打开文件夹”，系统只打开本地目录；即使在文件夹里选择或复制了图片/视频，资产库页面也没有新增素材。
- 根因：旧按钮只调用 `_open_path(_assets_dir())` 打开存储目录，不会调用 `add_asset()`，因此不会复制文件、写入 `assets.json` 或刷新资产库列表。“本地资产”按钮也只是单一来源切换，占位意义大于实际功能。
- 修复：`backend/matrix_native_client.py#L20176-L20184` 将顶部入口改为“导入资产”，并移除“本地资产”按钮；`backend/matrix_native_client.py#L20253-L20287` 选择本地图片/视频后调用 `add_asset()` 登记入库；`backend/matrix_native_client.py#L20346-L20354`、`backend/matrix_native_client.py#L20371-L20377` 在每个素材卡片增加“文件夹”按钮，用于打开该素材所在目录。
- 排查：导入后若列表没有变化，先确认选择的是 `.png/.jpg/.jpeg/.webp/.gif/.bmp/.mp4/.mov/.webm/.m4v`；再检查当前账号数据目录下 `assets.json` 是否写入新记录、`assets/` 目录是否有复制后的文件。顶部“导入资产”只进入本地资产库，不同步中心素材库，也不会自动出现在“素材发布”。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_asset_library_shared_button -v`，应通过 2 项；再运行 `py_compile`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节即可；不涉及数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-28 Agent.模式 Seedance 显示成 Seedream 或默认模型消失
- 现象：Agent.模式点击 LK888 模型后，默认视频模型 `doubao-seedance-1-5-pro-251215` 被显示成 `Seedream 3.5 Pro` 等错误名称；或 LK888 目录临时漏掉该模型时，视频模式默认模型不再出现在列表前部。
- 根因：旧实现直接信任 LK888 目录返回的 `display_name` 和目录内容。LK888 页面内部数字 ID、目录显示名和本地生成接口使用的字符串模型 ID 是不同层面的标识；当目录错标或缺项时，本地 UI 会把真实 Seedance 模型误显示成其它模型，容易误导生成。
- 修复：`backend/matrix_native_client.py#L1757-L1758` 建立本地权威模型映射与顺序表；`backend/matrix_native_client.py#L1954-L1973` 标签查询优先使用本地权威中文名；`backend/matrix_native_client.py#L2015-L2042` 模型列表先插入本地已确认模型，LK888 目录只追加补充项。
- 排查：打开 Agent.模式模型列表，确认视频模型里 `Seedance 1.5 Pro` 仍存在且排在本地确认模型区域；若仍显示 `Seedream 3.5 Pro`，说明运行中的本地客户端不是本修复版本或尚未重启。不要用 LK888 页面数字 ID 25/75 判断本地生成模型，本地 `/v1/media/generate` 使用字符串模型 ID。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_canonical_model_label_overrides_lk888_catalog_mismatch tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_video_models_keep_canonical_defaults_before_catalog_additions -v`，两项应通过；再运行完整 `tests.test_agent_mode_defaults` 和 `py_compile`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节即可；不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-28 同款替换漫剧生成提示计费重复或请求超时
- 现象：点击“开始替换生成”后，片段在首尾帧生成前失败，错误包含 `comic_api_http_502:{'detail': '计费请求重复'}`；再次开始生成可能变成 `HTTPConnectionPool(host='127.0.0.1', port=7897): Read timed out. (read timeout=120)`；新任务也可能在还没有 `comicProjectId` 时失败，错误为 `HTTPConnectionPool(host='120.26.194.174', port=80): Read timed out. (read timeout=60)`。
- 根因：`计费请求重复` 是远程漫剧服务/上游计费幂等保护返回的业务错误，不一定来自用户重复点击；本机 `127.0.0.1:7897` 超时说明运行中的本地客户端请求漫剧服务时吃到了系统或环境代理，代理链路 120 秒没有返回；`120.26.194.174 read timeout=60` 则发生在创建漫剧项目阶段，旧客户端只给远程项目初始化 60 秒，且剧本文本里还可能保留嵌入式原片拆解和字幕字段，导致远程创建更慢。
- 修复：`backend/matrix_native_client.py#L8466-L8510` 清洗嵌入式拆解，只保留视觉字段并跳过字幕/OCR；`backend/matrix_native_client.py#L9039-L9114` 禁用漫剧请求的环境代理，并识别 `计费请求重复`、`Read timed out` 和本机代理超时为可恢复提交异常；`backend/matrix_native_client.py#L9117-L9224` 把创建漫剧项目的超时放宽到 240 秒；`backend/matrix_native_client.py#L10516-L10580` 在首尾帧/视频提交失败时回查项目分镜，找到任务 ID 或结果 URL 后继续等待，不再直接失败。
- 排查：查看任务 JSON。若片段有 `comicRecoveryStatus=recovered` 和 `comicRecoveryReason`，说明本地已从远程分镜恢复；若仍失败且错误为 `comic_image_recovery_missing` 或 `comic_video_recovery_missing`，说明远程既拒绝了提交，也没有暴露可继续等待的任务 ID，需要稍后单段重试或重建漫剧项目。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_visual_prompt_extracts_embedded_breakdown_without_subtitles tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_create_uses_long_timeout_for_remote_project_build tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_default_request_ignores_environment_proxy tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_recovers_duplicate_billing_image_submit_from_storyboard_task tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_recovers_proxy_timeout_image_submit_from_storyboard_task -v`，五项应通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节即可；本次不涉及中心服、远程漫剧 `server.py`、OpenAPI、数据库或 `migration.sql`。按用户要求不自动重启本地客户端。

## 2026-07-28 小红书账号已经提示违规但风控中心仍显示低风险
- 现象：小红书账号在平台内已经出现“账号违规提示/账号违规预警”，提示涉及第三方工具、脚本、自动浏览、自动查看或自动发布，但本地客户端“风控中心”仍把该账号显示为“低风险”。
- 根因：旧风控中心只按账号在线状态、Cookie 状态和可用性判断风险。小红书任务返回的 `xhs_ip_risk`、`riskCode=300012/300031`，以及账号资料里可能携带的 `riskEvents/platformRisks/lastRisk` 没有进入账号风险评分。
- 修复：`backend/matrix_native_client.py#L879-L947` 会把小红书任务中的平台风险保存到本地 `account_risk_events.json`；`backend/matrix_native_client.py#L1019-L1041` 会优先按账号风险证据计算“高风险”；`backend/matrix_native_client.py#L19922-L20024` 会在风控中心展示“最近风险”和“建议动作”。
- 排查：进入风控中心前先重启本地客户端，确保运行的是包含本修复的版本。若账号仍显示低风险，检查账号数据或任务返回里是否实际包含 `账号违规提示`、`第三方工具/脚本`、`xhs_ip_risk`、`300012` 或 `300031`；如果这些文字只存在于小红书 App/网页通知里、没有被本地客户端采集到，当前版本无法自动识别。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_risk_summary_marks_xhs_account_violation_as_high_risk tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_risk_summary_applies_persisted_xhs_task_risk_to_same_platform -v`，应 2/2 通过；再运行完整 `tests.test_agent_mode_defaults` 回归和 `py_compile`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md`、`CHANGELOG.md` 即可恢复旧判断；必要时删除运行数据目录下的 `account_risk_events.json` 清空本地风险缓存。本次不涉及数据库迁移、OpenAPI 或 Web 端。

## 2026-07-28 登录首页仍显示注册按钮
- 现象：首页登录卡顶部仍出现“注册”，不符合当前只保留“登录 / 加入企业”的入口要求。
- 根因：旧实现把 `self.tab_reg` 和另外两个模式按钮一起加入 `tabrow`，并且标题仍写成“登录 / 注册”。
- 修复：登录卡现在只把 `self.tab_login` 和 `self.tab_invite` 加入顶部按钮行；`self.tab_reg` 保留为隐藏对象以兼容内部旧注册模式和既有逻辑，但不在首页显示。
- 排查：检查运行中的客户端源码是否包含 `backend/matrix_native_client.py#L21258-L21279` 的新逻辑；若仍显示注册按钮，说明当前客户端未重启或运行的不是这个工作区版本。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_enterprise_invite tests.test_login_centered_layout tests.test_auth_login_modes -v`；Qt 冒烟应输出 `LOGIN_HOME_TABS True False True`。
- 回滚：回滚 `backend/matrix_native_client.py`、相关测试和本文档即可恢复旧的“登录 / 注册 / 加入企业”三入口。

## 2026-07-28 小红书创作服务平台一直刷新
- 现象：点击“发布到小红书”后，创作服务平台浏览器已经打开，但登录页或创作者中心页面会反复刷新，用户还没来得及完成扫码/登录，页面又被重新跳转。
- 根因：等待登录函数把浏览器里已有的 `id_token/customerClientId` 等残留 cookie 当成“创作者中心已登录”的强信号，并在等待循环里反复执行 `page.goto(creator_url)`。如果小红书创作者中心实际仍未登录，平台会再次重定向到登录页，于是形成“跳发布页 -> 回登录页 -> 再跳发布页”的刷新循环。
- 修复：`_wait_for_xhs_creator_login()` 等待期间只观察当前页面是否出现上传入口或 URL 是否离开登录页，不再因为 cookie 在循环内刷新页面；等待结束后，发布流程最多再进入一次创作者发布页，仍被重定向到登录页时返回 `xhs_creator_login_required`。
- 排查：修复生效后，登录页应保持稳定，不会连续刷新。若仍停在登录页，请先在浏览器中完成小红书创作者中心登录；若超过等待时间，会提示“小红书创作者中心未登录，请在打开的浏览器中登录后重试。”需要更长扫码时间时，可设置 `XHS_CREATOR_LOGIN_TIMEOUT` 后重启本地客户端/执行引擎。
- 验证：新增回归用例先在旧实现下失败，确认问题来自等待函数内部 `page.goto(creator_url)`；修复后 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v` 26/26 通过。
- 回滚：回滚 `backend/platform_adapters.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。

## 2026-07-28 小红书创作者登录页打开后立即关闭
- 现象：点击“发布到小红书”后浏览器能弹出小红书创作者中心，但还没来得及扫码登录，浏览器窗口就被自动关闭。
- 根因：发布函数识别到创作者中心登录页后立即返回 `xhs_creator_login_required`；函数退出时 `finally: ctx.close()` 会关闭 Playwright 持久浏览器上下文，导致登录页刚出现就关闭。
- 修复：发布流程遇到创作者中心登录页时不再立刻返回，而是在当前可见浏览器中等待登录，默认最多 180 秒；期间轮询上传入口、URL 和小红书登录 cookie。检测到登录成功后自动重新进入创作者发布页并继续上传，超时后才返回 `xhs_creator_login_required`。
- 排查：如果仍过快关闭，确认本地客户端和本地执行引擎已经重启；需要临时延长扫码时间时，可设置 `XHS_CREATOR_LOGIN_TIMEOUT` 为更大的秒数后重启。
- 验证：先运行新增测试观察旧实现 2 项失败；修复后 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v` 25/25 通过，`py_compile` 退出码 0。
- 回滚：回滚 `backend/platform_adapters.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。

## 2026-07-28 小红书发布没有弹出浏览器且失败
- 现象：素材发布页选择小红书后，点击“发布到小红书”没有弹出浏览器，状态栏显示 `发布失败:upload_input_not_found`。
- 根因：小红书发布使用 `XHS_PUBLISH_HEADLESS` 控制浏览器可见性，旧默认值为后台模式；发布页实际跳转到 `creator.xiaohongshu.com/login?...redirectReason=401...` 时，用户看不到登录页面，程序继续检查上传控件并返回 `upload_input_not_found`。
- 修复：小红书发布默认改为可见浏览器；打开创作者中心后先检查是否跳到登录页，若是则返回 `xhs_creator_login_required`；客户端把该错误显示为“小红书创作者中心未登录，请在打开的浏览器中登录后重试。”
- 排查：若仍无法发布，先在弹出的浏览器里完成小红书创作者中心登录，再重试；若没有弹窗，检查运行环境是否显式设置了 `XHS_PUBLISH_HEADLESS=1`。
- 验证：先运行新增测试观察旧实现失败，再修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v`，应 23/23 通过。
- 回滚：回滚 `backend/platform_adapters.py`、`backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。

## 2026-07-28 同款替换漫剧项目剧本混乱或项目库缺上传素材
- 现象：漫剧生成器新建项目后，剧本里的“画面描述”像口播稿或旧 LK888 提示词；项目库出现 `发型/服装/体型/直播间/化妆品/房间/包` 等假角色、假场景、假道具；或者用户上传的人物、场景、产品图在项目库里不明显，角色的人物设计里看不到本地选择音色。
- 根因：旧本地客户端把同款替换 LK888 长提示词直接传给漫剧 `source_text` 和分镜 `description/prompt`，漫剧端会把提示词里的控制语当成剧本实体解析；本地上传资产虽然写到了项目库，但缺少漫剧端常用的 `reference_image/reference_images` 和 `voiceName/ttsVoice/voice*` 字段，展示和后续绑定不稳定。`prepare-dialogue-audio` 404 则通常是远程按当前作用域没找到对应项目或分镜。
- 修复：`backend/matrix_native_client.py#L8466-L8517` 把项目剧本改成短结构，画面只放视觉描述，对白单独放用户最终口播稿；`backend/matrix_native_client.py#L8553-L8604` 补齐人物、场景、道具图片字段和角色音色字段；`backend/matrix_native_client.py#L8607-L8645` 给分镜生成请求补 `project_id/projectId`；`backend/matrix_native_client.py#L10185-L10191` 将 `prepare-dialogue-audio` 404 降级为 `audioWarning` 后继续生成。
- 排查：打开本地任务 `video_replacements/<job-id>/replacement_job.json`。新任务应有 `replacementMode="comic_project"`、`comicProjectId`、`comicAssets.characters/scenes/props`，每段有 `comicStoryboardId`；项目剧本里应出现 `分镜/画面/对白`，不应出现 `源视频锁定`、`原片拆解证据`、`字幕安全` 等旧提示词。若远程项目已经被旧版本污染，重新运行本地修复不会自动删除远程假资产，需要新建任务或手动清理该漫剧项目后重试。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement -v`，应 26/26 通过；重点用例包括干净剧本、上传资产字段、`project_id/projectId` 传递和音频准备 404 降级。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节即可；本次不涉及中心服、远程漫剧 `server.py`、数据库、OpenAPI 或 `migration.sql`。按用户要求不自动重启本地客户端，代码生效需要用户手动重启本地客户端。

## 2026-07-27 企业中心横幅视频有时候显示、有时候不显示
- 现象：进入本地客户端“企业中心”时，顶部横幅有时能播放视频，有时只显示紫色渐变背景和“云灵星图 · AI爆款复刻平台”文字。
- 根因：旧实现只读取 `data_dir()/hero.mp4`。不同启动方式会让 `data_dir()` 指向不同目录；当当前目录没有 `hero.mp4`，或 Qt 多媒体后端未及时解码首帧时，页面只能退回渐变背景，且没有固定海报图和结构化日志辅助定位。
- 修复：`VideoHero` 现在按 `data_dir()/hero.mp4`、`backend/datas/hero.mp4`、内置 `assets/login_bg/car-shouye.mp4` 查找视频，并先显示 `assets/login_bg/car-shouye.png` 固定海报；视频缺失、加载失败、播放错误和媒体状态变化会写入 `enterprise_hero_video_*` JSON 日志。
- 排查：查看本地客户端日志中的 `enterprise_hero_video_missing`、`enterprise_hero_video_load_failed`、`enterprise_hero_video_playback_failed` 和 `enterprise_hero_video_media_status`。如果视频文件缺失，先确认 `backend/datas/hero.mp4` 或 `backend/assets/login_bg/car-shouye.mp4` 是否存在；如果只有播放错误，优先检查当前机器 Qt 多媒体解码能力。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults -v` 和 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_agent_mode_defaults.py`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md`、`CHANGELOG.md`；不涉及中心服、数据库或 OpenAPI。

## 2026-07-27 选择小红书但按钮显示发布到抖音且发布失败

- 现象：素材发布页“发布平台”已经选择小红书，但右侧按钮仍显示“发布到抖音”；点击后状态栏显示“真实发布未完成:task_failed”。
- 根因 1：按钮文案在 `PublishPage.__init__()` 中写死为“发布到抖音”，平台下拉切换时只刷新账号列表，没有刷新按钮文字和未选账号提示。
- 根因 2：中心本地浏览器任务失败时外层错误是兜底 `task_failed`，客户端旧文案优先显示外层错误，掩盖了本地小红书发布器的真实错误。
- 根因 3：本次失败任务已确认 `payload.platform=xhs`，并打开到 `https://creator.xiaohongshu.com/publish/publish?source=official`；小红书发布器旧按钮识别排除了“发布笔记”，随后固定坐标 `700,856` 兜底在不同视口下可能点不到真正发布按钮，最终没有确认发布成功。
- 修复：平台切换时同步执行 `self.b_pub.setText("发布到" + label)`；发布结果文案优先显示内层平台错误；小红书发布器把“发布笔记”作为精确候选按钮，坐标兜底改为按当前视口计算，未确认成功时返回 `publish_unconfirmed` 并透传 `button` 诊断。
- 排查：若重启后仍失败，状态栏应显示 `publish_unconfirmed`、`publish_button_not_found`、`upload_input_not_found` 或其它真实错误，不应再只显示 `task_failed`。继续查看中心任务详情中的 `result.button`，判断是按钮未找到、坐标兜底未确认，还是上传控件不存在。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v` 应 20/20 通过；再运行相关素材发布和图文同款回归。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/platform_adapters.py`、`backend/api_server.py`、`tests/test_native_publish.py` 和本节文档。回滚后小红书平台下按钮可能重新显示“发布到抖音”，发布失败也可能继续只显示 `task_failed`。

## 2026-07-27 企业邀请码仍要求手机号或邮箱

- 现象：管理员创建邀请时还看到手机号/邮箱输入框，或受邀用户在“加入企业”时仍被提示“请填写姓名及手机号或邮箱”。
- 根因：本地客户端和中心服没有同步到免手机号邮箱邀请契约；旧实现会在 `accept_enterprise_invite()` 中用 `missing_identifier` 拦截无手机号/邮箱的接受请求，登录页也会把隐藏/旧账号字段提交成 `phone/email`。
- 修复：中心服接受邀请码只要求 `token/name/password`；本地客户端邀请弹窗改为选择企业和角色，不再填写手机号/邮箱；登录页邀请码模式隐藏并清空手机号/邮箱字段，提交体不包含 `phone/email`。账户中心手机号绑定面板也只对平台管理员显示。
- 排查：确认运行中的客户端版本包含 `backend/matrix_native_client.py#L3402-L3457` 和 `backend/matrix_native_client.py#L21216-L21428` 的新逻辑；确认中心服包含 `backend/central_server.py#L7531-L7611` 中移除 `missing_identifier` 硬校验后的逻辑。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_enterprise_invites tests.test_native_enterprise_invite tests.test_role_permissions -v`，应 28/28 通过。
- 回滚：回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、三份相关测试和本节文档；回滚后邀请流程会重新要求手机号或邮箱，企业管理员/普通用户账户中心会重新显示手机号绑定区域。

## 2026-07-27 同款替换漫剧项目模式生成失败

- 现象：新同款替换任务停在 `comic_project`、`comic_assets`、`comic_prepare_audio`、`comic_generate_flowchart` 或 `comic_generate_video`；片段显示 `video_replace_comic_segment_failed`、`comic_project_id_missing`、`comic_storyboard_id_missing`、`comic_sso_ticket_missing`、`comic_sso_token_missing` 或 `comic_api_http_4xx/5xx`。
- 根因：新任务默认 `replacementMode="comic_project"`，本地客户端需要先向中心服换取漫剧 SSO ticket，再到漫剧生成器交换 token，之后创建项目、分析分镜、写入人物/场景/道具、准备配音、生成首尾帧和视频。任一远程接口没有返回项目 ID、分镜 ID、任务 ID 或可下载视频 URL，都会把当前片段标记为失败；其他片段不再被整体抛弃，任务进入 `partial`。
- 排查：查看 `video_replacements/<job-id>/replacement_job.json`。正常链路应出现 `comicProjectId`、`comicProjectUrl`、`comicAssets`、每段 `comicStoryboardId`、`flowchartTaskId/flowchartUrl`、`comicVideoTaskId/videoUrl` 和最终 `videoPath`。若缺少 `comicProjectId`，先查中心服 `/api/comic/auth/ticket` 和漫剧 `/api/v2/auth/exchange-matrix-ticket`；中心服 ticket 响应应包含 `comicUserId=44`、`comicUsername=003`、`comicAccountMode=fixed`。若仍出现 `comic_sso_user_not_mapped`，说明运行中的中心服仍是旧映射逻辑，需要手动重启中心服或检查是否回滚。若缺少 `comicStoryboardId`，先查漫剧项目分析返回的 `storyboards`；若缺少 `videoUrl`，先查远程视频任务结果。
- 音频边界：漫剧项目模式当前只允许 `AI 音色配音`。`source` 原片声音和 `uploaded` 上传完整配音会被前置阻断，因为当前链路还没有“上传完整配音 -> 片段对白音频 -> 漫剧口型/字幕同步”的稳定接口。看到“漫剧项目模式暂不支持上传完整配音保证口型同步”不是故障，先切回 AI 音色配音。
- 模型/参数错误：如果错误里出现 `resolution 720P 不合法`、`参数验证失败` 或上游 LK888 模型名，说明仍在走旧 LK888 链路或远程漫剧服务把参数透传给了不兼容模型。新任务应优先确认 `replacementMode="comic_project"`；需要快速回退时设置 `VIDEO_REPLACE_DEFAULT_MODE=legacy` 并手动重启本地客户端。
- 回滚：本地回滚需要恢复 `backend/central_server.py`、`backend/matrix_native_client.py` 和相关测试/文档，或设置 `VIDEO_REPLACE_DEFAULT_MODE=legacy` 让新任务回到旧链路；不涉及数据库迁移。若只回滚中心服固定账号策略，运行中的中心服需要手动重启后才会生效；若修改的是远程漫剧 `server.py`，也需要重启对应漫剧服务进程。

## 2026-07-27 小红书图文同款原文缺失或保存空素材

- 现象：内容采集后点击“图文同款”，来源素材只显示素材 ID 或标题像链接；原始标题、正文、标签为空；保存草稿时出现 `xhs_note_save_failed`，或素材发布里没有可用图片。
- 根因：小红书下载链路旧版只保存媒体文件，没有把笔记标题、正文、标签和本地下载目录写入素材；媒体过滤也没有排除 `/comment/` 评论区图片；图文同款旧界面用路径文本框传替换图，保存接口会跳过空路径后继续生成草稿，导致空图草稿或保存失败。保存草稿接口还被同一个 `do_POST()` 中素材删除分支的局部 `import shutil` 影响，Python 将 `shutil` 判定为未初始化局部变量，成功路径复制替换图时会直接抛出 `UnboundLocalError`，界面显示 `xhs_note_save_failed`。
- 修复：`xhs_download_note()` 只保留用户发布的正文媒体，过滤评论区图片，并把 `note.title/body/tags/savePath` 写入 `meta.json` 和素材库；图文同款页改为一张原图对应一个替换图片框，支持多选顺序填充，缺图必须手动选择替换图片，不再提供“AI生成缺图”入口；保存草稿前校验所有槽位必须存在可读取图片，缺图返回 `xhs_note_replacement_missing_images`。保存草稿复制替换图改为使用模块级 `shutil`，一张槽位一个唯一文件名；`copy2` 元数据复制失败时降级为普通文件复制。
- 排查：查看下载目录 `backend/datas/accounts/<账号>/media_datas/xhs_<noteId>/meta.json`，确认 `note.title`、`note.body`、`note.tags`、`savePath` 和 `files[].url`；若 `files[].url` 含 `/comment/`，说明运行的不是本修复版本；若保存草稿失败，先确认每个替换图片框都有缩略图。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteSaveDraftApiTests.test_save_draft_falls_back_when_metadata_copy_fails -v`；完整回归运行 `.venv-win\Scripts\python.exe -m unittest tests.test_api_download_contract tests.test_xhs_note_replacement -v`。
- 回滚：回滚 `backend/platform_adapters.py`、`backend/api_server.py`、`backend/xhs_note_replacement.py`、`backend/matrix_native_client.py`、`tests/test_api_download_contract.py`、`tests/test_xhs_note_replacement.py`、`docs/API_REFERENCE.md`、`docs/ARCHITECTURE.md`、`docs/IMPLEMENTATION.md`、`CHANGELOG.md` 和本节；不涉及数据库迁移，`migration.sql` 无需修改。

## 2026-07-27 原生邀请页布局与截图验证

- 现象 1：请求把原生邀请页缩到 900×700 后，实际窗口宽度变成 1062，卡片几何看似在窗口内但窗口已超出目标宽度。
- 根因 1：登录页左侧宣传区固定宽 520 像素，首次布局时仍可见，Qt 根据宣传区、间距、登录卡和页边距计算出 1062 像素最小宽度；旧 `resizeEvent()` 因窗口已被最小宽度撑大，无法进入 `< 940` 的隐藏分支。
- 修复 1：创建宣传区后立即按登录页当前宽度设置初始可见性，后续仍由 `resizeEvent()` 控制。新增运行时布局测试确认 900×700 实际尺寸不变、卡片完整位于视口内且可见控件互不相交。
- 现象 2：`QT_QPA_PLATFORM=offscreen` 下首次 `QWidget.grab()` 得到全黑 PNG。
- 根因 2：登录页首次显示会执行 340 ms 淡入，截图在透明度仍为 0 时抓取；此外 `offscreen` 插件不可靠加载 Windows 中文字体，不能作为“文字可读”的最终视觉证据。
- 修复 2：几何回归继续使用 `offscreen`；最终视觉验收改用 Windows Qt 平台、`WA_DontShowOnScreen`、禁用测试实例首次淡入，并用 `QImage + QWidget.render()` 屏幕外绘制。1240×780 与 900×700 截图像素采样分别包含 5852 和 3744 种颜色，卡片均在视口内，中文控件可读且无重叠。
- 安全检查：从登录切换到邀请模式时，旧版会把记住的登录密码留在“设置新密码”字段。新增失败测试后改为进入邀请模式即清空密码和确认密码；最终截图与测试均确认密码为空。
- 独立审查问题 1：校验或接受请求发出后切换到登录/注册模式，旧响应仍可能覆盖当前登录字段或建立邀请会话。修复为每次请求和模式切换递增请求代次，响应必须同时匹配当前 `invite` 模式和最新代次；模式切换会恢复按钮并清空已验证状态。
- 独立审查问题 2：邀请成功只更新内存会话，磁盘仍保留上一个账号的记住密码和自动登录 Token，重启后可能自动进入旧账号。修复为成功时将认证偏好改写为新账号，`remember=false`、`autologin=false`、`password=''`、`token=''`，并保存当前协议版本；测试断言不持久化旧凭据。
- 复核问题：即使不切换模式，接受请求期间仍可编辑邀请码或再次校验，可能出现服务端接受 A、界面显示 B，或新校验使 A 的成功响应过期。修复为接受期间锁定邀请身份、账号字段和三个模式按钮，校验入口在主按钮禁用时直接返回；接受响应除请求代次外还必须匹配提交码、已验证码和当前显示码。
- 验证：运行 `$env:QT_QPA_PLATFORM='offscreen'; .\.venv-win\Scripts\python.exe -m unittest tests.test_native_enterprise_invite -v`，以及计划中的登录、权限、协议、布局和成功过场回归。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_enterprise_invite.py`、`docs/IMPLEMENTATION.md` 和本节；若同时回滚原生邀请入口，必须一并恢复 Web 邀请交付面。

## 2026-07-27 Web 交付面移除基线

- 环境：Windows PowerShell 5.1、Python 3.12.13，Qt 使用 `QT_QPA_PLATFORM=offscreen`；本节所有结果均在生产代码首次修改前取得。
- 回滚：已生成 `backups/web-removal-20260727/web-surface.zip`、逐文件 `manifest.sha256` 和归档 `archive.sha256`。38 个目标展开为 73 个文件，其中 `frontend/` 为 36 个文件；独立解压后 73/73 文件的路径、大小和 SHA-256 一致。归档 SHA-256 为 `fbf0989fef5727f461d6424fa24eacea4385d73e078528266997af403b794097`。
- 归档失败 1：Windows PowerShell 5.1 的 `Set-Content -Encoding UTF8` 会给 `targets.txt` 写入 BOM，`tar.exe -T` 将其解析为非法首路径并退出 1。目标清单改用 ASCII 后，单文件编码探针通过。
- 归档失败 2：Windows PowerShell 5.1 基于 .NET Framework，不支持 `[IO.Path]::GetRelativePath()`；第一次生成的 73 行清单全部缺少相对路径，因此该 ZIP 未通过验收并在工作区绝对路径校验后删除。改为先验证文件位于工作区，再用工作区前缀长度 `Substring()` 取相对路径；同时启用 `$ErrorActionPreference='Stop'`，随后从零重新归档并通过独立恢复校验。
- 编译：`py_compile` 覆盖中心服、原生客户端、本地 API、启动器、worker 和本地浏览器 worker，退出 0。现有 `backend/api_server.py:1386`、`:1402` 中嵌入的 JavaScript 正则分别触发 `invalid escape sequence '\s'` 和 `invalid escape sequence '\/'` 告警，本次基线不修改该无关逻辑。
- 回归：定向 119 项首次运行 118 项通过，`test_source_image_entries_accept_url_only_signed_images` 一次返回 0 个条目；该项单独运行、所属 8 项测试类、同进程重复顺序以及原 119 项命令完整复跑均通过，且图片扩展集合没有测试期写入。该瞬态未稳定复现，因此未修改原生客户端逻辑；最终基线为 119/119 通过。
- 健康冒烟：Windows PowerShell 5.1 的 `Start-Process` 因当前环境同时包含 `Path`/`PATH` 而拒绝构造环境字典；此外 `backend/.env` 使用 `override=True`，会把测试端口覆盖为 9080。最终启动器对测试进程禁用 dotenv 文件加载，显式使用临时数据目录和 19079，并直接调用基础 Python 配合虚拟环境 `site-packages`，避免 Windows venv 启动器产生不可单独回收的子进程。`GET /api/health` 返回 `ok=true`、`mode=central`、`nodeCount=0`，进程停止后 19079 端口关闭。原有 9080 服务 PID 47572 启动于 2026-07-25，本次未终止或修改。
- 邀请 API TDD：新增 4 项契约测试在旧实现上出现 3 个 `KeyError: inviteCode` 和 1 个 GET 校验路由断言失败，证明测试能识别旧网页契约。首次实现后，两个接受邀请用例因把用户 ID 字符串传给只接受用户字典的 `user_memberships()` 而报 `AttributeError`；改为复用既有 `user_memberships(out_user)` 契约后，邀请、权限和登录定向回归 18/18 通过。
- 门禁：后续任一步出现回归时先停止并与该归档比对。恢复前必须停止中心服和客户端，先校验 `archive.sha256`，再解压到临时目录并按 `manifest.sha256` 逐项核对；不得直接覆盖当前工作区。

## 2026-07-25 同款替换口播音频和画面口型节奏不同步
- 现象：最终片段的声音已经是用户口播稿或上传配音，但画面人物嘴部节奏仍像原视频，或者一句话在固定 8 秒内说完后口型明显慢半拍/快半拍。
- 根因：当前没有可用的“已有视频 + 音频 -> 口型同步视频”模型；旧链路只能把口播稿文字放进 LK888 视频编辑 prompt，再在生成后本地换音轨。远程模型没有收到最终音频真实时长和分句时间分布，容易只按文本大意生成说话动作。
- 修复：`tts/uploaded` 片段现在先生成 TTS 或裁切上传完整配音，探测真实音频时长到 0.01 秒，再按片段 `script` 切分出台词时间表并前置到 LK888 prompt。视频生成完成后本地复用同一个音频文件封装音轨，保证提示词时间表和最终声音来源一致。
- 排查：查看任务 JSON 的片段字段。应出现 `dialogueAudioMode=tts/uploaded`、`dialogueAudioDurationSec`、`dialogueTiming` 和 `dialogueTimingPrompt`；`ttsPath` 或 `uploadedAudioSegmentPath` 应在视频生成前已有。prompt 前部应出现“口播时间表”和“本段最终口播音频时长”。
- 边界：这是远程视频生成的节奏约束，不是帧级口型同步。若模型仍不严格跟随，优先缩短单段文案、减少每句信息量，或切成更短片段后单段重生。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_dialogue_timing_prompt_uses_centisecond_audio_schedule tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_prompt_frontloads_dialogue_timing_before_saved_prompt tests.test_video_replacement_v2.VideoReplacementV2Test.test_tts_talking_segment_edits_video_then_replaces_audio_without_lipsync_model tests.test_video_replacement_v2.VideoReplacementV2Test.test_uploaded_talking_segment_replaces_audio_with_clipped_upload_without_lipsync_model -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及中心服、数据库或接口契约。
## 2026-07-25 同款替换复刻原视频字幕或人物仍说原台词
- 现象：生成结果保留或复刻了原视频顶部/底部字幕、OCR 识别字、营销大字，或者选择 AI 音色/上传完整配音后人物画面仍被原片口播内容影响。
- 根因：旧 prompt 把整段分解报告、OCR 和原片转写一起作为“原片拆解证据”传给 LK888；时间轴表格中的“字幕/信息”列也会混入 prompt，和用户修改后的片段口播稿形成冲突。
- 修复：现在只按当前片段时间范围提取镜头拆解中的画面、人物、产品、动作、道具、场景和节奏，并前置发送；“字幕/信息”、OCR、原片字幕和原片口播转写会被过滤。AI 音色和上传完整配音模式下，人物台词和最终字幕都只以片段表的用户口播稿为准；自动模式保留生成视频自带声音，不再回填原片声音。
- 排查：打开任务 JSON 的片段 `prompt`。应出现“当前片段原片镜头约束”，不应出现原片 OCR/旧字幕/原片口播原文；`tts/uploaded` 片段的主角 prompt 应出现“用户修改后的口播稿为准”或“与上传配音和口播稿一致”。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_replacement_prompt_frontloads_current_shot_breakdown_without_source_subtitles tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_prompt_keeps_user_script_as_only_dialogue_source_when_breakdown_has_old_subtitles -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及中心服、数据库或接口契约。
## 2026-07-25 同款替换上传场景与原片动作冲突导致片段失败
- 现象：片段提示 `scene_mismatch` 或 `principal_motion_mismatch`，例如生成结果跑到户外公路，未采用上传的室内门店场景，或没有沿用原片车内方向盘/展示动作。
- 根因：上传场景图和原片动作有时天然冲突。继续强制使用上传场景图会让远程模型在“照搬场景”和“沿用原片动作”之间摇摆，导致反复失败。
- 修复：当产品、Logo 和主角替换检查已经通过，只剩场景/动作冲突时，系统会把该片段标记为 `sceneFallbackMode=ai_generated` 并自动重试一次。重试时不再把上传场景图传给 LK888，prompt 改为 AI 生成同类场景；产品图仍继续传入，产品外形、颜色、Logo、主要包装文字和产品 QC 不放松。
- 排查：查看任务 JSON 的片段字段。出现 `sceneFallbackMode=ai_generated`、`sceneFallbackReason` 和 `sceneFallbackHistory` 表示已经触发过降级；如果降级后仍失败，优先看 `qcChecks.product/logoText/principalReplacement`，产品或人物失败不会继续放行。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_scene_fallback_removes_scene_ref_but_keeps_product_ref tests.test_video_replacement_v2.VideoReplacementV2Test.test_visual_qc_skips_uploaded_scene_check_when_ai_scene_fallback_active tests.test_video_replacement_v2.VideoReplacementV2Test.test_scene_or_motion_mismatch_can_retry_with_ai_scene_when_product_passed -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及中心服、数据库或接口契约。回滚后上传场景不一致会恢复为直接失败。
## 2026-07-25 内容采集选小红书却提示需先登录抖音
- 现象：在本地客户端「内容采集」选择“小红书”搜索，例如搜索“广汽丰田汽车”，页面返回 `搜索失败:local_browser_offline(需先登录抖音账号)`。
- 根因：搜索请求已经正确发成 `xhs.search`，真正失败码是中心服未找到当前用户/企业下在线的本地浏览器执行节点；但客户端状态栏旧文案把 `local_browser_offline` 统一拼成“需先登录抖音账号”，导致小红书场景误导用户。
- 修复：`backend/matrix_native_client.py#L4090-L4113` 按平台生成错误提示；`backend/matrix_native_client.py#L4261-L4262` 的内容采集搜索失败状态改用该 helper。小红书离线时提示启动本地客户端并确认小红书账号已登录，抖音仍提示抖音。
- 排查：账号矩阵里有账号资料不等于本地执行节点在线。若仍返回 `local_browser_offline`，先确认本地客户端/worker 正在运行、已绑定当前登录用户和企业，且本地节点 45 秒内有心跳。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_xhs_content_search_offline_error_names_xhs_not_douyin -v`；`.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement_v2.py`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及中心服、数据库或接口契约。
## 2026-07-25 小红书下载到的不是作品图片而是页面图标
- 现象：内容采集下载小红书笔记后，目录里出现足球、搜索图标、横幅、页面提示图等文件，例如 `fe-platform.xhscdn.com/platform/...`、`picasso-static.xiaohongshu.com/...` 或 `data:image/png;base64,...`，看起来不是用户发布作品里的图片。
- 根因：旧版 `xhs_download_note()` 直接遍历 `document.images` 下载整页图片，只按 `avatar/profile/emoji/icon/sprite` 做弱过滤；当笔记主体没有正确取到或页面上有静态资源、广告位、内嵌 base64 图时，这些非作品资源也会被保存，并且只要写出文件就返回 `ok=true`。
- 修复：小红书下载改为从笔记详情主体候选容器收集媒体，过滤 `data:`、`blob:`、`fe-platform`、`picasso-static`、头像/图标/雪碧图和尺寸过小图片；过滤后没有有效正文图片或视频时返回 `xhs_no_note_media`，不再导入素材库。
- 排查：查看下载目录的 `meta.json`。如果返回 `error=xhs_no_note_media`，说明过滤后没有识别到有效正文媒体；若仍有误入库，优先检查 `meta.json` 中有效文件 URL 是否来自 `fe-platform`、`picasso-static`、`data:` 或笔记主体之外的域名/容器。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_api_download_contract -v`。
- 回滚：回滚 `backend/platform_adapters.py`、`tests/test_api_download_contract.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-25 数字人口播画面出现乱码大字或错误字幕
- 现象：数字人口播视频里出现大号中文、乱码字、错字字幕或贴纸文字，和用户输入的口播文案不一致。
- 根因：旧链路只把口播文案用于 TTS 音频，数字人视频阶段没有本地字幕层；画面里的文字通常是上游图像/视频模型根据参考图或提示词“画”出来的，不是本地 ASS 字幕。
- 修复：`lk888_digital_human()` 的模型 prompt 追加禁止画面文字/字幕/水印的约束；视频下载完成后，`_burn_digital_human_subtitles()` 根据用户口播文案生成 UTF-8 ASS 中文字幕并用 ffmpeg 烧录，最终返回字幕版视频路径。
- 失败兜底：如果本地 ffmpeg 字幕烧录失败，会记录结构化日志 `digital_human_subtitle_burn_failed`，`subtitleStatus=failed`，并保留原始数字人视频路径，不让已生成的视频作废。
- 配置：`DIGITAL_HUMAN_BURN_SUBTITLES=0` 可临时关闭数字人口播字幕后处理；`DIGITAL_HUMAN_SUBTITLE_FONT`、`DIGITAL_HUMAN_SUBTITLE_FONT_SIZE`、`DIGITAL_HUMAN_SUBTITLE_MARGIN_V` 可调整字体、字号和底部边距，未设置时复用同款替换字幕配置。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_prompt_forbids_model_generated_text tests.test_video_replacement_v2.VideoReplacementV2Test.test_generate_digital_human_burns_local_chinese_subtitles_after_download tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_subtitle_ass_uses_script_text_and_video_duration -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档，或临时设置 `DIGITAL_HUMAN_BURN_SUBTITLES=0` 后重启本地客户端。
## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 同款替换职业套装被误判为吊带裙导致 QC 失败
- 现象：片段实际生成结果是白衬衫、深色职业马甲和职业半裙/套装，但页面提示 `principal_appearance_mismatch`，理由类似“未采用参考图中的职业套装，变成了黑色吊带裙”，并返回“质检失败：片段未通过自动质量检查”。
- 根因：主角整身替换的视觉 QC 只看首中尾审核帧后返回结构化判断。该任务的审核帧里主角确实是职业套装，但视觉模型把深色职业马甲/职业半裙组合误读成吊带裙；旧逻辑又把所有 `principal_*` 错误都作为硬阻断，导致肉眼正常的视频也失败。
- 修复：`principal_appearance_mismatch` 在标准/快速模式下降级为人工审核提醒，仍保存 `qcWarnings` 和审核帧；高一致模式或 `strictVisualQc=true` 继续硬阻断。`principal_replacement_mismatch`、`principal_other_subjects_changed`、`principal_motion_mismatch` 不放宽，仍直接失败。
- 提示词：视觉 QC 明确写入“白衬衫搭配深色职业马甲、西装外套、西装裤或职业半裙属于职业套装，不要误判为吊带裙”，降低同类误判。
- 排查：打开任务目录下 `qc_frames/qc_XX_first.jpg`、`qc_XX_middle.jpg`、`qc_XX_last.jpg` 复核审核帧；如果帧里确实是职业套装，新代码下标准模式应只显示质检提醒并允许人工审核。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_visual_qc_sends_person_references_and_blocks_mismatch tests.test_video_replacement_v2.VideoReplacementV2Test.test_standard_principal_appearance_mismatch_is_manual_review_warning tests.test_video_replacement_v2.VideoReplacementV2Test.test_high_principal_appearance_mismatch_still_blocks -v`，并补跑完整 `tests.test_video_replacement_v2`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。代码改动需要手动重启本地客户端后生效。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 同款替换最终视频口型、声音、字幕不一致
- 现象：最终视频声音仍是原视频声音，或口播稿没有影响远程生成画面的嘴部动作。
- 根因：旧链路把口播稿放在长 prompt 后部，可能被截断；同时 `tts/uploaded` 片段曾依赖额外的已有视频口型同步模型，未配置时不会产出最终换音轨结果。
- 新规则：`auto` 自动模式保留远程生成视频自带声音，不生成 TTS、不回填原片声音；历史 `source` 会兼容映射为 `auto`。`tts` AI 音色配音模式会把每段口播稿放入 LK888 视频编辑 prompt 前部，远程生成后本地用所选音色 TTS 替换该片段音轨；`uploaded` 上传完整配音模式要求每段口播稿与上传音频一致，远程生成后按片段时间裁切上传配音并本地替换音轨。
- 排查：查看任务 JSON 片段字段。`segmentType=talking` 表示有口播稿且声音模式为 `tts/uploaded`；`prompt` 前部应出现“本段人物说话台词必须…”和口播稿内容；`ttsUrl/ttsPath` 表示 AI 音色音频已生成，`uploadedAudioSegmentPath` 表示上传完整配音已按片段裁切；`audioMode=tts/uploaded` 且 `audioStatus=passed` 表示最终片段已完成本地换音轨。
- 旧错误：`replacement_lipsync_model_missing` 只适用于历史已有视频口型同步 helper；当前同款替换 `tts/uploaded` 主链路不再因为未配置 `VIDEO_REPLACE_LIPSYNC_MODEL` 中断。
- 字幕规则：最终字幕仍从片段 `script` 生成 ASS 并烧录，不使用原视频字幕。字幕出错时优先修改片段表里的口播稿，再重新生成或重生该片段。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。代码改动需要手动重启本地客户端后生效。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 同款替换 AI 音色提示 11.2 秒或尾音被截断
- 现象：8 秒片段中使用“AI 音色配音”时，页面提示某段口播预计需要 11.2 秒，用户担心固定片段时长内读不完，或者旧版本生成后尾音被截断。
- 根因：旧逻辑只按保守字数和标点停顿估算时长，预计超过片段时长就直接阻断；即使真实 TTS 只略长于视频，也没有自动提速处理，避免截断只能手动删文案或调整片段。
- 修复：开始生成前允许“预计时长 <= 片段时长 * `VIDEO_REPLACE_TTS_MAX_SPEED` + 0.25 秒”的口播继续生成；TTS 下载后再按真实音频时长计算所需语速，默认不超过 `1.45x` 时自动用 ffmpeg `atempo` 提速后回填。比如 11.2 秒放进 8 秒，需要约 `1.40x`，在默认上限内会继续生成并自动压进片段。
- 仍会失败的情况：如果真实音频需要超过 `1.45x` 才能塞进片段，系统会返回 `replacement_tts_audio_too_long`，并提示缩短该段口播稿或合并/延长片段；不建议无限加速，否则听感会明显变赶。
- 排查：查看任务 JSON 对应片段的 `ttsTimingStatus`；`sped_up` 表示已自动提速，`normal` 表示无需提速，`too_long` 表示超过上限。可用 `ttsOriginalDurationSec`、`ttsRequiredSpeed`、`ttsMaxSpeed` 和 `ttsSpeed` 追踪实际处理。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；或临时把 `VIDEO_REPLACE_TTS_MAX_SPEED=1.0` 后重启本地客户端，恢复“不自动提速”的保守策略。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 企业中心只显示默认企业，没有丰田汽车
- 现象：管理员或 boss 登录后进入“企业中心 -> 团队成员”，企业下拉框只看到“默认企业”，boss、user01、user02 仍显示在默认企业中，看不到预期的“丰田汽车”。
- 根因：中心状态文件里当时只有 `org-default / 默认企业` 和 `org-9918a7f2bae2 / 用户8702的企业`，没有 `org-toyota / 丰田汽车`；同时 boss、user01、user02 的 membership 都绑定在 `org-default`，所以页面显示默认企业是按真实数据渲染，不是客户端显示错误。
- 修复：`backend/matrix_native_client.py#L3032-L3322` 在团队成员页增加管理员专用“添加企业”入口，复用 `/api/enterprise/orgs/upsert` 创建企业；`backend/central_server.py#L6849-L6920`、`backend/central_server.py#L15041-L15047` 新增运行态成员替换接口 `/api/enterprise/memberships/replace`；`scripts/seed_toyota_enterprise.py#L1-L158` 已把 `org-toyota / 丰田汽车` 写入中心数据，并把 boss 设为企业家、user01/user02 设为普通用户。
- 数据边界：`19711057505 / user-owner` 保留在默认企业；账号矩阵里已经授权登录的抖音/小红书账号没有迁移到丰田汽车。
- 验证：运行 `.venv-win\Scripts\python.exe scripts\seed_toyota_enterprise.py --dry-run` 应返回 `changed=false`；抽查 `backend/central_data/scheduler_state.json` 应看到 `org-toyota / 丰田汽车`，且 boss/user01/user02 的 `orgId` 为 `org-toyota`。
- 回滚：使用 `backend/central_data/scheduler_state.json.bak-20260724150901` 覆盖当前 `backend/central_data/scheduler_state.json` 可恢复迁移前企业归属；回滚代码时同步恢复 `backend/matrix_native_client.py`、`backend/central_server.py`、`scripts/seed_toyota_enterprise.py`、`tests/test_role_permissions.py`、`CHANGELOG.md` 和本文档。恢复后需重启中心服和本地客户端。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 普通按钮点击后自动上移
- 现象：同款替换页“生成替换方案 / 执行替换生成 / 确认片段并合成 / 重试失败片段 / 重生选中片段 / 加入待发布队列”等普通按钮，点击后会短暂或持续向上偏移；其它页面使用 `QPushButton` 且由布局管理的按钮也可能出现同类问题。
- 根因：全局 `wire_animations()` 给普通 `QPushButton` 安装了点击缩放动画，动画通过修改控件 `geometry` 实现。普通按钮由 Qt layout 管理，点击后按钮文字、启用状态或布局重算会和手动 geometry 动画互相覆盖，造成位置跳动。
- 修复：`backend/matrix_native_client.py#L2235-L2238` 在 `_scale()` 中对所有 `QPushButton` 直接跳过 geometry 缩放；导航按钮本来就不走该全局过滤器，其它非按钮动画不受影响。
- 排查：如果还有按钮跳动，先查是否存在独立的 `QPropertyAnimation(..., b"geometry")` 或手写 `setGeometry()` 作用在按钮上；本次扫描剩余 geometry 操作为视频/登录成功动画等非按钮区域。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_all_qpushbuttons_skip_geometry_press_animation -v`，并补跑 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_agent_mode_defaults.py`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 企业中心里找不到团队成员或看不到同企业用户
- 现象：管理员或企业家想把多名普通用户放到同一个企业，但本地客户端只有企业中心总览，看不到成员管理入口；或者普通用户登录后找不到企业成员列表。
- 原因：企业不是角色，而是数据归属范围；同企业关系体现在用户 membership 的同一个 `orgId` 上。普通用户没有企业管理权限，不能自己把别人加入企业；管理员和企业家才应该在企业中心内操作团队成员。
- 修复：`backend/matrix_native_client.py#L3474-L3904` 的“企业中心 -> 团队成员”页按角色显示页头按钮：管理员可切换企业并使用“添加企业 / 添加成员 / 邀请成员 / 刷新”；企业家固定当前企业，只显示“刷新 / 邀请成员”；普通用户仍隐藏企业中心。
- 操作：管理员登录后进入“企业中心 -> 团队成员”，先选择企业，再点击“添加成员”或“邀请成员”；企业家登录后只能通过“邀请成员”把用户加入自己企业，不提供直接“添加企业”或“添加成员”按钮；普通用户无需操作，也不应看到该入口。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_role_permissions` 和 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py backend\central_server.py` 均通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及数据库结构、账号矩阵授权账号迁移、充值/兑换码或 `migration.sql`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 企业中心团队成员按钮和左下角用户区重叠
- 现象：团队成员表格“操作”列里“重置密码”和“停用/恢复”按钮互相压住；左下角头像、账号名、余额、主题切换、退出按钮在窄侧边栏里重叠。
- 原因：团队成员表格沿用了全列 `Stretch`，当页面宽度不足时最后一列被压窄；侧边栏底部把用户信息、余额和两个图标按钮放在同一行，220px 宽度不足时控件没有稳定的换行空间。
- 修复：`backend/matrix_native_client.py#L3071-L3072` 固定操作列宽度；`backend/matrix_native_client.py#L3173-L3177` 固定两个行内按钮宽度；`backend/matrix_native_client.py#L18744-L18787` 把左下角底部改成上下两行，上行身份信息，下行余额和图标按钮。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_role_permissions` 和 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py` 均通过；Qt 离屏渲染 `.tmp-validation/team-members-layout.png` 中操作列按钮已分开显示。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及中心服、数据库、充值/兑换码或 `migration.sql`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 同款替换删除片段后口播稿回退、片段表滚轮跳动
- 现象：在同款替换片段表里编辑过前几段口播稿后，删除某个片段会触发表格刷新，之前编辑但尚未进入生成流程的文案恢复成旧内容；鼠标滚轮滑动片段表时，上方内容像翻页一样快速跳走。
- 根因：口播稿编辑器里的文本只存在于表格控件中，删除片段前没有统一同步回任务 JSON；片段表虽然使用像素滚动，但垂直滚动条没有显式设置小步滚动距离，不同鼠标和 Qt 默认步长下会出现接近翻页的体感。
- 修复：口播稿编辑器 `textChanged` 时实时写回当前片段；删除片段前再次从表格逐行同步脚本；片段表垂直滚动条设置 `singleStep=24`、`pageStep=122`。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_replacement_segment_table_uses_readable_script_editor_and_fixed_actions tests.test_video_replacement_v2.VideoReplacementV2Test.test_delete_replacement_segment_preserves_current_edited_scripts -v`，并补跑 `tests.test_video_replacement_v2` 全量回归。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；仅影响本地客户端，回滚或修复后重启本地客户端生效。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 同款替换删除后时间轴未压紧、成功片段仍显示远程错误
- 现象：删除一个待生成片段后，剩余片段时间仍保留原来的空档，例如删除 8-16 秒那段后，第 3 段仍显示 `16.0-24.0s` 而不是紧接着前一段；另一个现象是片段视频已经成功生成并落盘，但列表里仍显示 `kwvideo-v2-quannengcankao` 的失败错误。
- 根因：删除逻辑以前只重排了 `index`，没有重算 `start/end`；远程候选模型循环里，前一个模型失败后写入了 `remoteError/remoteErrorId`，后一个模型即使成功拿到视频，也没有清掉这些旧字段，完成状态仍会把旧 fallback 错误当成当前错误显示。
- 修复：删除后按剩余片段 `duration` 从 0 秒重新压紧时间轴；远程候选成功后清空 `remoteError/remoteErrorId`，并且完成状态不再展示残留的 fallback 错误。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_delete_replacement_segment_reindexes_pending_segments tests.test_video_replacement_v2.VideoReplacementV2Test.test_non_talking_segment_falls_back_to_next_reference_model_and_records_remote_error tests.test_video_replacement_v2.VideoReplacementV2Test.test_segment_status_text_hides_remote_fallback_error_after_success -v`，并补跑 `tests.test_video_replacement_v2` 全量回归。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；仅影响本地客户端，回滚或修复后重启本地客户端生效。
## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 SD 2.0 全能参考 resolution=720P 参数验证失败
- 现象：同款替换选择 `SD 2.0 全能参考` / `kwvideo-v2-quannengcankao` 后，片段报 `kwvideo-v2-quannengcankao 未拿到任务ID: {"code":400,"data":{"详情":"参数 resolution 的值 720P 不合法"},"msg":"参数验证失败"}`，随后本地汇总为 `principal_video_edit_failed`。
- 根因：主角整身替换链路复用了 `happyhorse-video-edit` 的分辨率规则，把页面默认 `720p` 规范成了大写 `720P`；但 `kwvideo-v2-quannengcankao` 需要小写 `720p`，上游在创建任务前直接拒绝，所以没有任务 ID。
- 修复：`backend/matrix_native_client.py` 的 `_lk888_video_edit_resolution()` 改为按模型适配：`happyhorse-*` 继续使用 `720P/1080P`，`kwvideo-v2-quannengcankao` 等非 happyhorse 模型保持小写 `720p/1080p`；主角整身请求和 fallback payload 都传入实际模型名。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_video_edit_payload_keeps_lowercase_resolution_for_kwvideo_model tests.test_video_replacement_v2.VideoReplacementV2Test.test_principal_video_edit_payload_uses_model_native_video_and_images_fields tests.test_video_replacement_v2.VideoReplacementV2Test.test_remote_video_payload_normalizes_happyhorse_resolution_without_changing_primary_payload -v`，并补跑 `tests.test_video_replacement_v2` 全量。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py` 和本文档即可；代码改动只影响本地客户端，回滚或修复后都需要重启本地客户端。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 SD 2.0 全能参考模型标识确认
- 现象：LK888/云灵后台显示“SD 2.0 全能参考”，但需要确认同款替换下拉框和任务 JSON 里应该写什么模型。
- 结论：云灵页面卡片 ID 是 `76`，真实生成模型标识是 `kwvideo-v2-quannengcankao`；同款替换任务 JSON、片段 `segment.model` 和远程请求都应使用 `kwvideo-v2-quannengcankao`，不是数字 ID `76`。
- 排查：如果页面没有该选项，先确认本地客户端已重启；如果任务仍用旧模型，看任务 JSON 的 `model` 是否被旧任务保存为 `happyhorse-video-edit`，切换模型后需要重生对应片段。
- 回滚：把任务模型切回 `happyhorse-video-edit` 并重生失败片段；代码层面回滚 `backend/matrix_native_client.py` 和 `tests/test_video_replacement_v2.py` 即可移除内置备选。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 同款替换任务模型切换后仍然跑偏
- 现象：同款替换里明明已经切了模型，或者想把整个任务从 `happyhorse-video-edit` 换成更稳的 LK888 参考视频模型，但成片还是出现明显瑕疵、主体跑偏，或者页面里看不到“SD 2.0 全能参考”。
- 原因：当前链路是任务级 `model`，不是单段临时参数；如果 LK888 目录没有把某个视频模型暴露出来，客户端不会硬塞一个未知模型 ID。`SD 2.0 全能参考` 只有在目录里识别到匹配项时才会出现在备选里。
- 处理：
  - 在“同款替换模型”里直接切换整个任务的模型。
  - 优先用当前任务里实际可用的参考视频模型，不要把纯文生视频或图片模型当替代项。
  - 如果某段一直瑕疵大，切模型后要重新生成该段，不要沿用旧段结果。
- 排查：
  - 看任务 JSON 的 `model`，确认不是默认值被回写。
  - 看对应 `segment.model`，确认单段实际请求用了什么模型。
  - 看 `remoteErrorId` 和 `principal_video_edit_failed`，确认是模型契约问题还是远程生成失败。
  - 看 `video_replace_models` 列表，确认 LK888 目录是否真的返回了可用参考视频模型。
- 回滚：把任务级 `model` 切回 `happyhorse-video-edit`，重新生成失败片段；如果要暂时绕过模型选择，直接重启本地客户端后清空任务里已保存的模型值。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 同款替换片段瑕疵重生与中文字幕错字
- 现象：单个片段生成后出现手部变形、产品 Logo 变糊、脸部不稳定、局部脏点等瑕疵；或最终中文字幕出现“详经地”等可疑错字、OCR/转写乱码。
- 根因：局部画面瑕疵不一定会被自动视觉 QC 判定为严重跑偏；如果直接重试，远程模型不知道上一版具体问题，可能再次生成类似瑕疵。中文字幕来源是片段 `script`，如果原视频分解阶段 OCR/转写识别错，最终 ASS 字幕会照错字烧录。
- 修复：同款替换片段表新增“重生选中片段”，用户填写上一版瑕疵后只重生该片段，并把瑕疵说明写入下一次远程提示词；开始生成前新增字幕文本预检，疑似乱码、可疑词和未确认口播稿会要求人工确认；最终字幕烧录优先使用固定中文字体目录，避免字体回退。
- 操作：生成方案后先检查片段表“口播稿”，发现错字直接改；如果成片审核发现某段瑕疵，选中该片段，点击“重生选中片段”，填写“上一版问题”，等待该段完成后再确认合成。
- 回滚：回滚 `backend/matrix_native_client.py` 和对应测试/文档；或临时设置 `VIDEO_REPLACE_BURN_SUBTITLES=0` 关闭最终字幕烧录。字体问题可通过设置 `VIDEO_REPLACE_SUBTITLE_FONT_FILE` 指向受控中文字体文件后重启本地客户端。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_prepare_manual_defect_regeneration_adds_prompt_guard tests.test_video_replacement_v2.VideoReplacementV2Test.test_subtitle_preflight_flags_suspicious_or_unreviewed_text tests.test_video_replacement_v2.VideoReplacementV2Test.test_subtitle_burn_uses_fixed_font_directory_when_available -v`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 Agent.模式只能上传一张图或多图参考未生效
- 现象：用户想在 Agent.模式中上传 1 张待修改图和多张参考图，例如“第一张改成第二张风格，人物换成第三张人物”，旧页面只能保留一张参考图，生成时其余图片不会传给 LK888。
- 根因：旧状态只保存单个 `ref`，上传按钮使用 `getOpenFileName()`，生成层也只把单张本地图转成 `image_urls`；即使底层图片接口支持多图，上层也没有把多图顺序传下去。
- 修复：`backend/matrix_native_client.py#L14935-L15049` 输入区维护最多 4 张 `refs`，可一次多选或分批追加，标签固定为“待修改图 / 参考图1 / 参考图2...”；`backend/matrix_native_client.py#L15084-L15129` 新任务保存 `refs` 并保留旧 `ref`；`backend/matrix_native_client.py#L9479-L9545` 图片生成按顺序把所有图片转成 `image_urls` 传给 LK888。
- 排查：生成时查看本地结构化日志 `lk888_image_reference_payload`，`reference_count` 应等于上传图片数量。若仍为 1，确认当前客户端是否已重启；若为多张但效果不稳定，提示词必须明确引用图片顺序，例如“以第1张为待修改图，参考第2张的风格，替换为第3张中的人物”。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_supports_ordered_multi_image_references tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_generation_uses_all_uploaded_images_in_order -v`，并补跑 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 Agent.模式上传图后输入框只显示一行
- 现象：Agent.模式上传参考图后，缩略图和提示词输入框挤在同一行，长中文提示词只能横向显示，看起来像输入框被压扁或不能多行展示。
- 根因：旧 composer 用同一个横向布局同时放 `ref_slot` 和 `QLineEdit`。`QLineEdit` 本身只支持单行，参考图按钮还会占用同一行宽度，导致长提示词无法按容器宽度换行。
- 修复：`backend/matrix_native_client.py#L14697-L14719` 将参考图槽放入独立 `ref_strip`，输入控件改为 `QPlainTextEdit` 并启用 `WidgetWidth` 自动换行；`backend/matrix_native_client.py#L14935-L15066` 同步把发送、提示词优化和重新编辑改为读写多行文本。
- 排查：如果重启后仍是旧布局，确认当前运行的是本仓库的本地客户端进程；若文本仍不换行，检查源码中是否仍存在 `midrow.addWidget(self.ref_slot` 或 `self.inp = QtWidgets.QLineEdit()`。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_prompt_input_is_multiline_below_reference_strip -v`，并补跑 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 内容采集提示需先登录抖音账号但账号矩阵显示在线
- 现象：账号矩阵里抖音账号显示“在线”，但在「内容采集」选择抖音搜索时返回 `douyin_auth_incomplete(需先登录抖音账号)`。
- 根因：账号矩阵读取的是多账号注册表和各账号独立 Cookie；内容采集 `/api/finder/discover` 旧逻辑只读取默认 `auth_cookie.json`。当默认缓存不存在或只有 `msToken`，但矩阵账号目录下存在可用抖音 Cookie 时，采集接口没有自动切换账号。
- 修复：`backend/api_server.py#L4994-L5015` 在抖音内容采集前复用默认可用账号选择逻辑，未显式传 `accountId` 时进入账号矩阵中最新可用抖音账号的 Cookie/profile 作用域；找不到可用账号时再回退默认鉴权并提示登录。
- 验证：`tests/test_douyin_multi_account.py#L125-L179` 覆盖默认缓存不完整但矩阵账号可用时，内容采集会拿到矩阵账号的 `sessionid` 和 profile。
- 回滚：回滚 `backend/api_server.py`、`tests/test_douyin_multi_account.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及中心服、数据库或 `migration.sql`。回滚后内容采集会再次只依赖默认登录缓存。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 素材发布看不到小红书账号或无法切换账号
- 现象：管理员账号矩阵里已有两个授权账号，但「素材发布」页只显示抖音账号，无法切换到小红书账号；容易误以为两个账号都应该出现在同一个下拉框里。
- 根因：本地客户端发布页旧逻辑只按抖音过滤账号，并且加载账号后还会重复清空和重填账号下拉框；本地发布接口也主要靠账号 ID 推断平台，没有接收客户端显式选择的平台。
- 修复：`backend/matrix_native_client.py#L4211-L4301` 新增发布平台下拉框，按当前平台过滤已登录账号，并删除加载后的重复填充逻辑；`backend/api_server.py#L2735-L2746` 和 `backend/api_server.py#L5350-L5363` 接收 `platform` 后按抖音/小红书进入对应发布链路。
- 数据归属：当前两个已授权账号仍是 `org-default / user-owner`，不迁移到“丰田汽车”；如果想在丰田汽车企业下发布，需要由该企业账号重新授权或由管理员明确绑定新的企业账号。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_douyin_multi_account`，并补跑 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py backend\api_server.py`。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`tests/test_native_publish.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库结构、账号迁移或 `migration.sql`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 同款替换 AI 音色配音尾部被截断
- 现象：同款替换选择“AI 音色配音”后，某段人物台词在约 8 秒片段内读不完，成片尾部口播被直接切掉。
- 根因：同款替换默认按约 8 秒分段生成；旧逻辑把每段 TTS 音频按对应视频片段时长合成，音频长于视频时会按视频时长收尾，导致尾部被截断。
- 修复：`backend/matrix_native_client.py#L6031-L6079` 新增生成前口播时长估算；`backend/matrix_native_client.py#L7072-L7075` 在开始生成前阻断明显超长片段；`backend/matrix_native_client.py#L11651-L11678` 在 TTS 下载后用真实音频时长兜底，超长时返回 `replacement_tts_audio_too_long`，不再进入截断式合成。
- 排查：查看任务 JSON 的 `audioMode`、片段 `duration/script/ttsDurationSec/ttsTimingStatus/ttsTimingError`。如果 `audioMode=auto`，使用的是生成视频自带声音，不走这套 TTS 校验；旧 `audioMode=source` 会兼容映射为 `auto`。如果 `audioMode=uploaded`，整条音轨仍按最终成片时长校验。
- 配置：`VIDEO_REPLACE_TTS_CHARS_PER_SEC` 默认约 `4.2` 字/秒，值越大越宽松；生产建议只在确认当前 TTS 音色实际语速后调整。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_tts_duration_preflight_flags_segment_script_that_will_be_cut tests.test_video_replacement_v2.VideoReplacementV2Test.test_tts_audio_mode_rejects_real_audio_longer_than_segment_before_mux tests.test_video_replacement_v2.VideoReplacementV2Test.test_start_generation_blocks_tts_script_that_exceeds_segment_duration -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。回滚后 AI 配音超长仍可能被片段时长截断。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 数字人口播报 `images 参数格式错误`
- 现象：上传人物图和场景图后，LK888 图片生成返回 `images 参数格式错误：第2个元素不是有效的图片URL（须以 http:// 或 https:// 开头的公网直链）`。
- 根因：上一版为了兼容 LK888 参考图字段，把参考图同时复制到 `images/reference_images/params.images`。但数字人口播合成曾优先把本地场景图转成 `data:image/...`，而 `images` 字段只接受公网 `http/https` 直链，于是第 2 张场景图被上游直接判为格式错误。
- 修复：`backend/matrix_native_client.py#L1183-L1237` 保留 `image_urls` 原始参考列表，但只有当所有参考图都是公网直链时才写入 `images/reference_images/referenceImages/params.images`；`backend/matrix_native_client.py#L4877-L4892` 数字人口播场景合成改用已上传的公网场景 URL 作为生成参考，避免把本地 data URL 放进 LK888 URL 字段。
- 排查：如果仍报同类错误，检查结构化日志 `lk888_image_reference_payload` 的 `fields`。若包含 `images`，对应参考图必须全部是 `http://` 或 `https://` 开头的公网图片；如果含 `data:image`，字段列表应只有 `image_urls`。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_lk888_image_reference_url_fields_exclude_data_urls tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_composition_uses_public_scene_url_for_lk888 -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及数据库迁移或 `migration.sql`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 数字人口播提示被内容安全策略阻止
- 现象：数字人口播上传人物图和场景图后，中间合成失败，LK888 返回“您的提示已被内容安全策略阻止。请调整提示并再试一次。”；旧页面可能把该错误误提示为“场景换背景图片生成超时”。
- 根因：原合成提示词包含“脸部、人物身份、完整保留”等强身份锁定表达，叠加人物参考图后容易被上游安全策略判定为真人身份复刻或换脸类请求。这和网络超时不同，也不代表参考图没有上传。
- 修复：`backend/matrix_native_client.py#L4832-L4930` 新增安全策略错误识别和低风险提示词重试；第一次被拦截时记录 `digital_human_scene_avatar_policy_retry`，改用更中性的“整体外观与穿着风格、自然放入场景”提示词和 `1024x1024` 再试一次。`backend/matrix_native_client.py#L5118-L5125` 对连续拦截显示准确中文提示。
- 排查：如果仍失败，优先更换更中性的参考图，避免证件照、过度暴露、未成年人、明显名人/网红照片或带敏感文字的场景图；同时查看结构化日志是否出现 `digital_human_scene_avatar_policy_retry`。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_policy_block_retries_with_safer_prompt tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_policy_block_shows_actionable_message -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及数据库迁移或 `migration.sql`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 数字人口播中间合成人物和场景完全跑偏
- 现象：数字人口播上传人物图和场景图后，中间合成图像像纯文生图，人物身份、服装和场景都与上传参考完全不一致；LK888 后台也看不到参考图字段。
- 根因：图片生成请求此前只写入 `image_urls`。如果 LK888 `/v1/images/generations` 对该字段不识别，就会只收到提示词，看不到人物图和场景图，最终退化为“按文字生成一个相似题材画面”。
- 修复：`backend/matrix_native_client.py#L1183-L1237` 在参考图全为公网直链时同时写入 `image_urls/images/reference_images/referenceImages/params.images` 等兼容字段，并记录 `lk888_image_reference_payload` 结构化日志，方便确认请求中参考图数量和字段名。
- 排查：重新生成时查看本地结构化日志是否出现 `lk888_image_reference_payload`，其中 `reference_count` 应为 `2`。若参考图全是公网直链，字段列表应包含 `images` 和 `params.images`；若含本地 data URL，字段列表只应包含 `image_urls`。若仍为 0 或日志缺失，说明生成入口没有传入人物图/场景图。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_composition_sends_reference_images_in_compatible_fields -v`，确认自动合成请求携带两张参考图的兼容字段。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及数据库迁移或 `migration.sql`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 同款替换产品图归一化后变成另一个产品
- 现象：用户上传的产品图经过白底归一化后，变成 GPS、护肤品、钱包等另一个产品，后续视频替换参考也跟着跑偏。
- 根因：旧链路会调用图像模型重绘白底产品图。即使提示词要求保持产品一致，图像模型仍可能把主体理解错并生成新产品；后续视频模型拿到的是错图，不是用户原图。
- 修复：`backend/matrix_native_client.py#L10794-L10856` 已移除产品图归一化调用，产品图直接并行上传用户原图；任务 JSON 的 `productPreprocess` 会记录 `error=product_normalize_removed`、`normalized=false`、`selectedPath` 和 `uploadUrl`。
- 排查：如果页面仍提示“归一化与上传”或任务 JSON 出现 `normalizedPath/product_1_white.png`，说明本地客户端还没重启或仍在运行旧代码。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py` 和相关文档即可；不涉及数据库迁移。回滚后可能再次出现产品被图像模型重绘的问题。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 同款替换点击取消任务后看起来没反应
- 现象：生成中点击“取消任务”后，页面仍停在远程生成阶段，用户感觉按钮没有反应。
- 根因：旧链路只在片段开始前检查取消；如果当前正在 LK888/HappyHorse 远程轮询，取消标记没有立即保存，也没有刷新按钮和进度提示。
- 修复：`backend/matrix_native_client.py#L7247-L7285` 点击取消后立即保存 `status=cancel_requested` 和 `cancelRequested=true`，按钮改为“取消中”；`backend/matrix_native_client.py#L1289-L1337` 的远程轮询每轮检查取消标记并退出本地等待。
- 边界：当前没有调用 LK888 上游取消接口，已经提交到上游的任务可能仍会在 LK888 侧继续跑；本地客户端会尽快停止等待、清理本地敏感/临时素材，并把任务标为取消。
- 排查：查看任务 JSON，如果 `status=cancel_requested` 表示点击已生效；如果最终变成 `canceled` 表示本地清理完成。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 Agent.模式胶囊按钮点击后上移
- 现象：Agent.模式中点击“3D 渲染”等胶囊按钮后，按钮会短暂或持续向上偏移；同一排里风格、数量、比例、模型、提示词优化等按钮都可能受影响。
- 根因：全局 `wire_animations()` 会给 `QPushButton` 安装点击缩放动画，动画通过修改控件 `geometry` 实现；这些胶囊按钮由 `QHBoxLayout` 管理，并且点击后可能改文字触发布局重算，布局和手动 geometry 动画互相覆盖，导致位置跳动。
- 修复：`backend/matrix_native_client.py#L2117-L2119` 让点击动画跳过 `_no_press_scale` 控件；`backend/matrix_native_client.py#L13853-L13855` 让 `_icon_text_btn()` 生成的图标文字按钮统一设置 `_no_press_scale=True`。圆形固定按钮仍保留点击动画。
- 排查：若其他页面仍有按钮点击跳动，先查该按钮是否直接 `QPushButton(...)` 创建并由布局管理，同时点击后会 `setText()`；此类按钮也应改为 `_icon_text_btn()` 或设置 `_no_press_scale=True`。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_icon_text_buttons_skip_geometry_press_animation -v`，并补跑 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及数据库迁移或 `migration.sql`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 Agent.模式提示词优化后仍显示英文或直接生成
- 现象：用户在 Agent.模式输入需求后，想先优化提示词再生成；旧链路会在点击发送后直接生成，并在生成中面板/tooltip 里展示内部英文模型提示词。
- 根因：商品图/视频生成只有发送入口，提示词扩写发生在扣费和生成线程内部，缺少用户确认步骤；`expandedPrompt` 同时承担“用户可见提示词”和“模型入参”的职责，导致界面显示英文。
- 修复：`backend/matrix_native_client.py#L9082-L9121` 新增中文提示词优化；`backend/matrix_native_client.py#L14106-L14155` 新增可编辑确认弹窗；`backend/matrix_native_client.py#L14262-L14264`、`backend/matrix_native_client.py#L14516-L14549`、`backend/matrix_native_client.py#L14578-L14592` 接入“提示词优化”按钮和确认后生成；`backend/matrix_native_client.py#L9124-L9207` 将用户可见中文 `visiblePrompt/expandedPrompt` 与隐藏模型 `modelPrompt` 分离。
- 排查：如果点击“提示词优化”无反应，先确认输入框不为空且按钮没有停留在“优化中…”；如弹出失败提示，可直接点发送使用原输入生成。若生成卡片仍显示英文，检查 `prodgen.json` 里的当前记录 `prompt/visiblePrompt/expandedPrompt` 是否为中文，以及客户端是否已重启加载新代码。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_prompt_optimization_confirms_chinese_before_generation -v`，并补跑 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及数据库迁移或 `migration.sql`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 同款替换 `principal_video_edit_failed`：最后片段短于上游最低时长
- 现象：片段视频内容本身可能没有明显问题，但任务失败显示 `principal_video_edit_failed`，例如错误编号 `err-c42570f3e17d4474`。现场失败段为第 3 段，时间 `16.0s - 17.47s`，参考视频只有约 `1.47s`。
- 根因：主角整身替换走 `happyhorse-video-edit` 的源视频编辑模式。该模式要求参考视频至少约 3 秒，1.5 秒左右的尾段会被上游直接拒绝，返回“参考视频仅 1.5 秒，至少需要 3 秒（建议 3～15 秒）”。这不是提示词跑偏，也不是产品/场景图导致的质检误判。
- 修复：新建方案在 `backend/matrix_native_client.py#L9781-L9823` 合并小于 3 秒的最后一段；旧任务点击“重试失败片段”时在 `backend/matrix_native_client.py#L7174-L7200`、`backend/matrix_native_client.py#L10997-L11071` 把失败短尾合并到上一段并重跑上一段，任务 JSON 写入 `lastRetryPreparation.normalization` 和 `retryHistory`。
- 排查：查看 `replacement_job.json` 的 `segments[-1].duration`、`start/end`、`remoteError`、`errorId`。若最后失败段短于 3 秒，重试后应只剩合并后的上一段，例如 `8.0s - 17.47s`，不应再提交 `16.0s - 17.47s`。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_plan_merges_tail_shorter_than_remote_video_minimum tests.test_video_replacement_v2.VideoReplacementV2Test.test_retry_normalization_merges_legacy_too_short_tail_into_previous_segment -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。回滚后 3 秒以下最后片段会再次失败。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 同款替换花洒/卫浴视频被汽车标准误判质检失败
- 现象：同款替换生成视频本身看起来正常，但片段被自动质检拦截，例如错误编号 `err-bb00a5e6dbbb4af1`，页面提示“质检失败：片段未通过自动质量检查，请查看审核帧后单段重试”。本次样例源视频是抖音 `7664925980469185378`，实际产品为“枪灰色多功能淋浴花洒套装”，场景为卫浴产品实体展厅/门店。
- 根因：旧的源视频槽位提取把“展厅/门店”这类通用场景默认推成“汽车销售/汽车/汽车展厅”。后置视觉 QC 拿错误的源视频产品和场景标准去审核花洒视频，导致生成内容没有明显问题也可能被判为 `product_mismatch`、`scene_mismatch` 或片段质检失败。
- 修复：`backend/matrix_native_client.py#L9864-L9926` 从分解报告、视觉说明、OCR 和转写动态提取 `sourceCategory/sourceProductCategory/sourceScene`；`backend/matrix_native_client.py#L9929-L9975` 生成真实源视频人物/产品/场景槽位；`backend/matrix_native_client.py#L6791-L6791` 开始生成或单段重试时重新计算 `sourceReplacementEntities`，不再复用旧任务里可能写错的“汽车”槽位。
- 排查：打开任务 JSON，检查 `breakdownAnalysis.report/visual`、`sourceReplacementEntities.products[].category`、`sourceReplacementEntities.scenes[].type` 和 `referencePreflight.sourceProductCategory`。如果源视频是花洒/卫浴，但这些字段出现汽车、汽车展厅等内容，说明运行中的客户端还没加载新代码或任务仍在使用旧槽位。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_source_context_uses_actual_breakdown_product_instead_of_car_fallback -v`，并补跑 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2 -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/API_REFERENCE.md` 和本文档即可；不涉及数据库迁移。回滚后同类非汽车展厅视频仍可能被错误按汽车场景审核。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 同款替换上传完整配音无法合成
- 现象：同款替换选择“上传完整配音”后，最终合成失败并提示 `replacement_uploaded_audio_too_short`、`replacement_uploaded_audio_missing` 或音频合成失败。
- 根因：上传完整配音是整条成片音轨替换，不是音色克隆；系统会在字幕烧录后用该音频替换最终视频声音。音频短于成片时不会循环补齐，会直接阻断，避免后半段无声或错位。
- 修复：上传一条不短于最终成片时长的 `mp3/wav/m4a/ogg` 配音；如果选择“AI 音色配音”，需要每个片段都有口播稿，否则会提示 `replacement_tts_script_missing`。
- 排查：查看任务 JSON 的 `audioMode`、`voiceId`、`replacementAudioPath`、`replacementAudioUrl`、`finalAudioMode` 和片段 `ttsUrl/ttsPath`。`audioMode=auto` 表示保留生成视频自带声音，旧 `source` 会兼容映射为 `auto`；`tts` 表示逐段 AI 音色配音，`uploaded` 表示最终整条音轨替换。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_tts_audio_mode_replaces_segment_audio_without_source_mux tests.test_video_replacement_v2.VideoReplacementV2Test.test_uploaded_audio_mode_replaces_final_audio_after_subtitles -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文档即可；不涉及数据库迁移。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 抖音安全验证页在发送验证码前被关闭
- 现象：点击“发布到抖音”后，抖音创作者中心弹出安全验证/身份验证页面；用户还没来得及点击“发送验证码”，浏览器窗口就被本地发布器关闭，客户端显示 `security_verify_required` 或“真实发布未完成”。
- 根因：旧发布结果检测把页面上任意可见“验证”二字都映射为 `security_verify_required`，因此“发送验证码/验证码登录/安全验证”都会立刻触发失败；随后 `finally` 未把该状态视为人工处理状态，继续关闭 Playwright 浏览器上下文并删除临时 profile。
- 修复：`backend/utils/publish_util.py#L538-L540` 只匹配“安全验证 / 身份验证 / 验证身份”，不再泛匹配“验证”；`backend/utils/publish_util.py#L619-L621` 遇到 `security_verify_required` 或 `security_appeal_required` 时保留浏览器窗口；`backend/matrix_native_client.py#L7652-L7655` 显示“请在打开的浏览器中完成验证后重试”。
- 排查：看到该提示时不要认为已经发布成功；在保留的抖音浏览器窗口里完成验证码/滑块/账号安全处理，再回到客户端重试发布。只有页面出现“发布成功/发布完成/已成功发布”才算程序确认真实发布。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_publish_util_safety tests.test_native_publish -v`。
- 回滚：回滚 `backend/utils/publish_util.py`、`backend/matrix_native_client.py`、`tests/test_publish_util_safety.py`、`tests/test_native_publish.py` 和本文档即可；不涉及数据库迁移。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 素材发布打开素材找不到文件
- 现象：在“素材与发布”里选中素材后点击“打开素材”，状态栏提示“素材文件不存在或尚未同步到本机”，或者提示无法打开素材文件。
- 根因：素材列表来自中心素材库，但真实媒体文件可能位于下载源目录、本机素材库目录或中心服本机素材目录；如果当前机器不是素材所在机器，或素材文件已经被清理/隔离，本机无法直接打开。若文件存在但打不开，通常是系统没有关联默认播放器或图片查看器。
- 修复：`backend/matrix_native_client.py#L4595-L4606` 新增“打开素材”按钮；`backend/matrix_native_client.py#L4668-L4724` 按素材文件名查找本机可用文件，优先打开视频，其次打开图片，找不到或打开失败时给状态栏提示。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 和 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_native_publish.py`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库迁移或接口变更。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-24 素材发布标题双击后看不清
- 现象：在“素材与发布”表格里双击标题栏后，标题进入表格内嵌编辑状态，输入框沿用选中行蓝色背景，长标题和浅色文字叠在一起，用户无法清楚编辑。
- 根因：标题列通过 `Qt.ItemIsEditable` 和表格 `DoubleClicked/SelectedClicked` 触发 Qt 默认单元格编辑器；该编辑器没有单独样式，和当前深色主题的选中行状态冲突。
- 修复：`backend/matrix_native_client.py#L4046-L4051` 将素材表格设为不可内嵌编辑，并把双击标题列改为打开编辑标题弹窗；`backend/matrix_native_client.py#L4121-L4168` 新增大文本框弹窗、字数提示和保存逻辑，保存后仍写回 `/api/library/update-title`，发布时继续读取标题栏内容并提交前 30 个字符。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库迁移或接口变更。回滚后标题会恢复表格内嵌编辑框，仍可能看不清。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 素材发布标题编辑后没有按新标题发布
- 现象：在“素材与发布”表格里修改标题后点击“发布到抖音”，抖音发布页仍使用素材入库时的旧标题，或正式发布标题长度不符合预期。
- 根因：旧客户端只提交 `materialId`，本机 `/api/publish/run` 再从素材库读取 `title`；表格标题列不可编辑。新流程虽然允许保存完整标题，但正式发布必须遵循抖音标题最多 30 个字符的限制。
- 修复：`backend/matrix_native_client.py#L4046-L4168` 允许通过标题弹窗编辑标题并把当前标题栏文本作为 `publishTitle` 提交，同时保存完整标题到素材库；`backend/api_server.py#L5293-L5308` 新增标题更新接口；`backend/api_server.py#L5342-L5354` 使用 `publishTitle` 覆盖素材标题；`backend/utils/publish_util.py#L444-L445` 在正式发布填写前截取前 30 个字符。
- 排查：双击标题单元格，在弹出的“编辑标题”窗口里修改并保存后再点“发布到抖音”；发布页使用标题栏内容的前 30 个字符，素材库仍保留完整标题。若仍是旧标题，先重启本地客户端和执行引擎，确认已加载新代码。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_publish_util_safety tests.test_native_publish -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`backend/utils/publish_util.py`、相关测试和文档；不涉及数据库迁移。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 抖音还在上传/自动发布时窗口被关闭
- 现象：点击“发布到抖音”后，抖音创作者中心窗口已经进入“作品上传中”或“上传完成后将自动发布”，但本地发布流程超时后把窗口关闭，导致用户看到内容还没发布完就中断。
- 根因：旧逻辑用同一个 `DY_PUBLISH_TIMEOUT` 同时控制“等待发布按钮可点”和“等待抖音最终发布成功”。进入作品管理页后，大文件或慢网可能长时间停在“作品上传中/上传完成后将自动发布”；超时后代码设置 `publish_upload_pending`，但 `finally` 仍执行 `ctx.close()` 并删除临时 profile，实际把仍在上传的窗口关掉。
- 修复：`backend/utils/publish_util.py#L151-L159` 新增 `DY_PUBLISH_PENDING_TIMEOUT`，默认 1800 秒；`backend/utils/publish_util.py#L543-L598` 检测到上传中会延长等待；`backend/utils/publish_util.py#L614-L660` 最终仍是 `publish_upload_pending` 时不主动关闭浏览器窗口或删除临时 profile。
- 排查：如果窗口长时间停在上传中，先等待抖音完成；需要更长等待时设置 `DY_PUBLISH_PENDING_TIMEOUT`，单位秒，例如 `3600`。只有看到“发布成功/发布完成/已成功发布”才算程序确认成功。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/utils/publish_util.py`、`tests/test_publish_util_safety.py` 和本文档即可；不涉及数据库迁移。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-22 单主角整身替换 Phase 0 原生字段已验证

- 目标：验证 `happyhorse-video-edit` 是否接受“一个公网源视频片段 + 1 张授权人物参考图”，只替换一个主角的完整外观并保留原动作、镜头、背景和音频。
- 有效请求契约：模型原生字段为 `video`、`images`、`resolution=720P`、`audio_setting=origin`、`watermark=false`；为兼容中心服适配层同时保留 `video_url`、`video_urls`、`reference_video`、`image_urls` 和 `params` 内对应字段。请求只发送公网 HTTPS URL，日志只记录字段名和 `errorId`。
- 真实冒烟：使用 `happyhorse-video-edit` 生成的 `720x1280` 视频时长 `8.04s`，音频为 48kHz 双声道，平均音量约 `-12.3 dB`；女性全身参考成功替换原男性主角，原动作、站位、展厅、车辆、字幕结构和音频保留。结果样本保存在 `tmp_lk888_principal_native.mp4`，仅用于本地验证。
- 对照失败：只发送通用 `video_urls + image_urls` 时任务仍返回视频，但人物参考图被忽略，输出仍为原男性主角。根因是兼容层没有把通用 `image_urls` 映射为模型需要的 `images`，不是客户端上传失败。
- 生产链路：新任务写入 `principalReplacementMode=source_video_edit` 后只允许 `happyhorse-video-edit`（或配置模型）；失败返回 `principal_video_edit_failed` 并停止片段，不回退到 Vidu/Wan/参考图生视频。设置 `VIDEO_REPLACE_PRINCIPAL_REPLACEMENT=0` 后回滚到旧链路。
- 已知风险：视觉模型可能把多人画面中的错误人物当作主角，或把上传人物的背景带入结果；页面现在展示主角预览、低置信度人工确认，并用 `principalReplacementMatch`、`fullBodyAppearanceMatch`、`otherSubjectsPreserved`、`motionPreserved` 做后置硬 QC。多人映射不在本版本范围内。
- 历史余额阻断：早期冒烟曾因 LK888 `code=402`、余额不足而未创建任务；余额补充后已按上述原生字段完成验证。再次遇到 402 时应在上游充值/核对计费，不得用旧参考图链路伪装成功。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-22 主角替换不应要求产品图或自动确认错误人物

- 现象：用户只上传人物参考图时仍被提示“请先上传产品图”，或者低置信度识别后未操作候选就直接开始生成。
- 根因：主角整身替换的目标是把原片主角替换为上传人物，同时保留原片产品、场景、动作和音轨；产品图不是该模式的必需输入。旧版低置信度主角需要用户在页面手动确认候选帧，容易增加冗余操作。
- 修复：`VIDEO_REPLACE_PRINCIPAL_REPLACEMENT=1` 的任务允许产品图为空；页面不再显示原片主角缩略图和确认下拉框，低置信度时自动使用第一张候选帧作为主角锚定。没有产品参考图时仍会将待审核视频、原片片段和人物参考图送入主角视觉 QC，且不会虚构不存在的场景媒体。
- 音频：HappyHorse 返回结果下载后，主角片段会用源片段音轨原子回填；如果源片段没有可用音轨，片段会失败并保留错误编号，不会静默生成无声成片。
- 排查：查看任务 JSON 的 `principalActor.status`、`principalActor.previewPath`、`personReferenceFullBodyConfirmed`、`principalReplacementMode` 和片段 `audioStatus`；`manual_required` 必须在页面选择候选帧，`principal_video_edit_failed` 不会回退到旧参考图模型。
- 回滚：将 `VIDEO_REPLACE_PRINCIPAL_REPLACEMENT=0` 并重启本地客户端；中心服不需要重启。本次没有数据库迁移。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2`、`.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement -v` 和 `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-22 点击发布到抖音后仍显示“试发完成，未真实发布”
- 现象：用户点击本地客户端“素材与发布”页的“发布到抖音”，按钮请求已经携带 `dryRun=false`，但状态栏仍显示“试发完成，未真实发布”。
- 根因：本机发布器在真实发布中也可能返回 `filled=true/published=false`，例如上传仍在进行、未拿到“发布成功”强信号、登录态失效或风控验证。旧客户端只要看到 `filled=true/published=false` 就显示“试发完成”，没有检查响应里的 `dryRun`，导致真实发布未完成被误描述成试发。
- 修复：`backend/api_server.py#L5328-L5331` 回传 `dryRun`；`backend/matrix_native_client.py#L7485-L7495` 只有 `dryRun=true` 才显示“试发完成”，真实发布未完成会显示具体错误码；`backend/matrix_native_client.py#L4125-L4127` 状态栏统一使用该判断。
- 排查：如果修复后仍未真实发布，状态栏会出现 `publish_upload_pending`、`publish_unconfirmed`、`not_logged_in`、`security_verify_required` 等实际原因。按错误码处理登录、风控或等待上传完成，不要再把它当作试发路径。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`tests/test_native_publish.py` 和本文档即可；不涉及数据库迁移。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-22 发布到抖音按钮显示成功但作品未真实发布
- 现象：左侧“素材发布 / 素材与发布”中点击“发布到抖音”后，客户端可能显示成功或任务完成，但抖音创作者中心/作品列表没有真实新增作品。
- 根因：`backend/utils/publish_util.py` 中保留了测试/沙箱用的 `CTF_LOCAL_SAFE_PUBLISH` 绕过逻辑；当发布遇到登录墙、风控、失败 toast 或“上传完成后将自动发布”等未完成状态时，该绕过仍可能把真实发布结果改成 `ok=true`、`published=true`，导致上层误以为已真正发布。
- 修复：`backend/utils/publish_util.py#L400-L405` 在登录墙/风控墙绕过时强制 `published=false`，真实发布保持失败；`backend/utils/publish_util.py#L604-L609` 在最终失败/风控/上传未完成绕过时保留错误码并强制 `published=false`。本地客户端原有 `_publish_result_ok(..., dry=False)` 只认 `published=true`，因此不会再把这类绕过当成真实发布成功。
- 排查：如果仍未发布，先检查任务返回的 `error` 是否为 `not_logged_in`、`risk_blocked`、`security_verify_required`、`publish_upload_pending` 或 `publish_unconfirmed`；再确认本地客户端、执行 worker 和抖音创作者中心登录态正常。不要用 `CTF_LOCAL_SAFE_PUBLISH=1` 作为生产发布规避手段。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_publish_util_safety -v` 和 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v`。
- 回滚：回滚 `backend/utils/publish_util.py`、`tests/test_publish_util_safety.py` 和本文档即可；不涉及数据库迁移。回滚后 `CTF_LOCAL_SAFE_PUBLISH=1` 环境仍可能把未真实发布误报成成功。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-22 同款替换有口播稿时误走数字人口播
- 现象：同款替换中用户已在“口播稿”文本框编辑最终文案，但执行后片段状态显示 TTS、数字人口播或 `kling-avatar-image2video`，短视频片段耗时被放大，动作也不像原视频。
- 根因：旧链路把 `VIDEO_REPLACE_STRICT_SCRIPT_AUDIO=1`、`VIDEO_REPLACE_ENABLE_AVATAR_SEGMENTS=1` 或旧任务里的 `segmentType=talking` 解释为“同款替换片段要走 TTS + 数字人口播”。这与当前业务定义冲突：同款替换应保持原视频动作、镜头、站位和节奏，口播稿只是用户最终文案。
- 修复：`backend/matrix_native_client.py#L5820-L5821` 固定同款替换片段不转数字人口播；`backend/matrix_native_client.py#L9486-L9518` 生成方案时只保留 `script`，`segmentType` 固定 `non_talking`；`backend/matrix_native_client.py#L11232-L11239` 执行时把旧 `talking` 片段归一到同款替换链路；`backend/matrix_native_client.py#L6227-L6249` 和 `backend/matrix_native_client.py#L7001-L7025` 移除“类型”列，仅保留可编辑口播稿。
- 排查：如果仍看到 TTS/数字人口播状态，先确认本地客户端已重启并加载新代码；再检查任务 JSON 的片段是否在执行时被写回 `segmentType=non_talking`。不要再通过 `VIDEO_REPLACE_STRICT_SCRIPT_AUDIO` 控制同款替换嘴型，它不再属于同款替换执行入口。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_plan_ignores_avatar_segments_env_for_replacement tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_plan_keeps_scripted_segments_in_replacement_pipeline tests.test_video_replacement_v2.VideoReplacementV2Test.test_strict_script_audio_does_not_route_replacement_to_digital_human tests.test_video_replacement_v2.VideoReplacementV2Test.test_mock_hybrid_pipeline_builds_audible_twelve_second_video`；同时运行 `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement_v2.py`。
- 回滚：回滚 `backend/matrix_native_client.py` 与 `tests/test_video_replacement_v2.py` 及本文档即可；不涉及数据库迁移。回滚后同款替换可能重新受严格口播配置影响进入数字人口播。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-22 同款替换产品图明明正确却被判成 GPS/护肤品

- 现象：用户上传的产品图本身是正确品类，例如花洒/淋浴套装，但生成前失败为 `reference_mismatch`，页面提示“参考图与原视频主题冲突”，任务 JSON 的 `referencePreflight.referenceRisks` 却显示产品图是 GPS 导航设备、护肤精华等无关产品。
- 根因：产品图链路先调用图像模型做白底归一化。旧逻辑只要图像生成接口返回成功，就把归一化图当作产品参考继续上传；如果上游图像模型把花洒重绘成 GPS 或护肤品，后续参考图预检看到的就是错图，而不是用户原图。
- 修复：2026-07-23 起产品图归一化已整体移除，`backend/matrix_native_client.py#L10794-L10856` 直接上传用户原图；页面不再显示“归一化异常，已回退原图继续生成”。
- 排查：查看任务 JSON 的 `productPreprocess`。新任务应记录 `error=product_normalize_removed`、`normalized=false`、`selectedPath` 和 `uploadUrl`；如果仍出现 `normalizedPath/product_1_white.png`，说明本地客户端还在跑旧代码。
- 回滚：回滚 2026-07-23 的产品图归一化移除改动会恢复旧白底归一化链路，但不建议在生产中回滚。本次不涉及数据库迁移。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_product_image_normalization_returns_original_without_calling_image_model tests.test_video_replacement_v2.VideoReplacementV2Test.test_product_ref_processing_uploads_original_images_without_normalization -v`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-22 同款替换“上传参考图”耗时很久

- 现象：点击开始生成后，页面长时间显示“上传参考图”，用户会误以为只是普通文件上传很慢。
- 根因：旧产品图参考链路会上传原图、调用图像模型做白底归一化，再上传归一化结果；如果有多张产品图，等待时间会被图像生成放大。
- 修复：2026-07-23 起 `backend/matrix_native_client.py#L10794-L10856` 只并行上传用户原图，不再做白底归一化；`VIDEO_REPLACE_PRODUCT_PARALLEL` 只控制原图上传并行度。
- 排查：任务 JSON 的 `productPreprocess` 中会记录每张图的 `index`、`uploadUrl`、`elapsedSec`、`normalized=false` 和 `error=product_normalize_removed`。如果页面仍提示“归一化与上传”，先重启本地客户端。
- 回滚：设置 `VIDEO_REPLACE_PRODUCT_PARALLEL=1` 并重启本地客户端，可把产品图原图上传恢复为串行；本次不涉及数据库迁移。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_product_refs_are_processed_with_limited_parallelism_and_ordered_results tests.test_video_replacement_v2.VideoReplacementV2Test.test_product_ref_processing_uploads_original_images_without_normalization -v` 覆盖并行上限、结果顺序和直接原图上传。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-21 用户只上传一张场景图但合成背景跑偏

- 现象：用户上传的是汽车展厅等单张场景图，但系统合成的数字人中间图可能被图片模型生成成户外、公园、绿地或其他场景；旧提示中的“第1张/第2张图”指的是用户场景图和系统合成图，不是用户上传了两张场景图。
- 处理：`backend/matrix_native_client.py#L4798-L4880` 首次背景质检失败时会自动按“上传场景图是唯一背景来源”强约束重试一次；第二次仍不一致才停止 TTS 和数字人视频生成，并退款。
- 诊断：客户端状态栏会显示“系统中间合成图：...”并携带去掉查询参数的 URL；结构化日志记录 `digital_human_scene_background_retry`、`digital_human_scene_background_mismatch` 及质检原因，不记录签名查询参数。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_mismatch_retries_with_strict_uploaded_scene tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_trace_url_removes_signed_query tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_error_and_status_identify_system_composed_image -v`。
- 回滚：只需回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本节文档；不涉及数据库迁移。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-21 本地客户端发布显示成功但抖音没有真实发布

- 现象：本地客户端“素材与发布”页点击“发布到抖音”后底部显示“发布成功”，但抖音创作者中心/作品列表没有真实发布记录。
- 根因：本地客户端提交 `publish.run` 时没有显式传入 `dryRun=false`，而本机 `/api/publish/run` 默认 `dryRun=true`，因此可能只完成上传和填标题；同时客户端成功判断此前把 `result.ok=true` 也当成发布成功，导致试发成功被误显示为真实发布成功。
- 修复：`backend/matrix_native_client.py#L4093-L4101` 的发布 payload 明确包含 `dryRun=false`；`backend/matrix_native_client.py#L7480-L7487` 的 `_publish_result_ok(..., dry=False)` 只认 `published=true`；若返回 `filled=true` 但 `published=false`，页面显示“试发完成，未真实发布”。
- 验证：`tests/test_native_publish.py#L22-L37` 覆盖真实发布判断和本地发布按钮 payload 契约；运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v`。
- 回滚：回滚 `backend/matrix_native_client.py` 与 `tests/test_native_publish.py` 对应改动即可；不涉及数据库迁移。回滚后会恢复“试发可能被误判为发布成功”的风险。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-21 数字人口播场景图生成 502 lk888_proxy_error

- 现象：数字人口播上传场景图后，生成失败显示 `图片生成502: {"ok": false, "error": "lk888_proxy_error"}`，通常发生在“合成场景版人物图”阶段，最终数字人视频尚未开始。
- 根因：上传场景图启用强制换背景后，客户端会先调用 `gpt-image-2` 同步生成“人物 + 场景”的首帧图。中心服 `/lk888/v1/images/generations` 代理等待 LK888 上游图片生成时发生 `TimeoutError`，于是返回 502。该问题不代表本地客户端未启动，也不代表场景图没有上传。
- 修复：`backend/matrix_native_client.py#L4688-L4734` 新增图片网关类异常识别和轻量重试，首次 `1024x1536` 失败后记录 `digital_human_scene_avatar_retry` 结构化日志，并用 `1024x1024` 再试一次；连续失败时抛出 `digital_human_scene_avatar_image_timeout`。`backend/matrix_native_client.py#L4832-L4833` 将页面提示改为“场景换背景图片生成超时”，给出稍后重试、不上传场景图或更换清晰简单场景图的建议。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_composition_retries_proxy_timeout_with_square_size tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_image_timeout_shows_actionable_message`；同时运行数字人口播场景图相关 9 条定向测试。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 到上一稳定版本；不涉及数据库迁移。临时规避可不上传场景图，直接使用原人物图生成口播。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-21 同款替换 fallback 400、跨片段人物跳变和字幕漂移

- 现象：片段状态先显示 `viduq3-turbo-cankaosheng ... 网络异常：连接超时`，随后备用模型 `happyhorse-1.1-r2v` 报 `参数 resolution 的值 720p 不合法`。
- 根因：这是两类错误叠加。首选参考图模型是网络/上游超时；备用 `happyhorse-*` 模型此前复用了小写 `720p`，但该模型要求大写 `720P`，因此 fallback 直接 400。
- 修复：fallback 每次按候选模型重新构建远程 payload，`happyhorse-*` 下单前把 `resolution` 规范为 `720P`，原始主模型 payload 保持不变。
- 现象：同款替换不同片段的人物脸部观感、发型或服装不一致。
- 修复：非口播后续片段会上传上一段生成结果的最后一张审核帧作为 `continuityFrameUrl`，提示词要求保持同一个新人设、脸部观感、发型和服装连续；上传失败只记录 `continuityFrameWarning`，不阻断生成。
- 现象：后期字幕与画面/音频不稳定或逐段漂移。
- 修复：字幕事件优先使用每个片段实际生成视频的 `videoPath` 探测时长来排布，而不是只使用计划的 8 秒片段时长。这样远程模型输出略长/略短时，最终字幕时间轴会跟拼接后的视频更一致。
- 回滚：回滚 `backend/matrix_native_client.py` 的模型 payload 适配、连续性参考和字幕事件时长探测，或暂时关闭 `VIDEO_REPLACE_BURN_SUBTITLES=0` 只回滚后期字幕烧录。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-21 分解视频页点击“打开视频”无反应

- 现象：分解视频完成后点击“打开视频”，系统没有明显反馈。
- 根因：打开文件依赖系统默认播放器或文件关联；旧逻辑 `_open_path()` 失败只写日志，页面状态栏不提示。
- 修复：`open_video()` 检查 `_open_path()` 返回值，失败时显示“无法打开视频文件，请检查文件是否存在或系统默认播放器。”
- 排查：确认 `videoPath` 文件仍存在；如果文件存在但仍打不开，检查 Windows 默认播放器/文件关联。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-23 同款替换页面不再显示产品锚定/动作控制/人物一致性

- 现象：同款替换页只保留上传人物、产品、场景和声音来源等当前主链路入口，不再显示“产品镜头锚定”“原片动作控制”“人物一致性”。
- 原因：当前新任务走单主角整身远程替换链路，这三个入口不会有效改变主角替换结果；为避免误导用户，新任务固定写入 `identityMode=standard`、`enableFaceFusion=false`、`actionControlEnabled=false`、`productAnchorEnabled=false`。
- 排查：如果旧任务 JSON 里仍有这些字段，按旧任务兼容逻辑查看；新建任务应以上述固定值为准。若页面仍显示旧控件，说明本地客户端未重启或仍在运行旧进程。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py` 和相关文档后重启本地客户端；不涉及中心服、数据库或 `migration.sql`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-21 同款替换原片动作控制

- 现象：开启“原片动作控制”后，生成结果更贴近原视频站位、指向、转身和镜头构图，但人物脸仍可能不是强锁定。
- 原因：动作关键帧只作为动作、姿态、站位、镜头和构图参考；人物身份仍由上传的授权人物图和人物一致性模式控制，不等同于 FaceFusion 换脸。
- 回退：页面取消勾选“原片动作控制”，或将 `VIDEO_REPLACE_ACTION_CONTROL=0` 后重启客户端。已生成片段可继续人工审核或单段重试。
- 排查：片段 JSON 中 `actionFrameUrls` 表示已成功上传动作帧；`actionControlWarning` 表示抽帧或上传失败，系统已自动回退到原标准远程生成链路，不应阻断整单。
- 长视频说明：同款替换不再按固定总时长拒绝任务，但仍按约 8 秒切片。长视频会产生更多远程生成片段，耗时、费用和人工确认次数会同步增加。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-21 同款替换口播稿文本框看不清、删除按钮超出表格

- 现象：同款替换生成方案后，片段表格里的“口播稿”文字在选中或编辑时不清楚；右侧“删除”按钮被表格边界裁切或超出操作列。
- 根因：片段表格把口播稿作为普通单行 `QTableWidgetItem` 显示，长中文只能横向挤压；表格最后一列被设置为自动拉伸，操作列没有稳定宽度和按钮容器，导致按钮在窄窗口下被裁切。
- 修复：`backend/matrix_native_client.py#L5938-L5964` 固定表格滚动、列宽和行高，口播稿列固定 520px，操作列固定 120px；`backend/matrix_native_client.py#L6681-L6745` 将口播稿列改成 `QPlainTextEdit` 多行编辑器，编辑器最小宽度 500px、最小高度 104px，从编辑器读取生成前脚本，并把删除按钮放入固定宽度居中容器。
- 验证：`tests/test_video_replacement_v2.py#L221-L232` 覆盖口播稿多行编辑器、表格滚动/列宽、删除按钮固定尺寸和脚本读取 helper。
- 回滚：仅回滚表格布局、`_make_segment_script_editor()`、`_segment_script_value()` 与对应测试。回滚后口播稿会重新退回单行显示，删除按钮仍可能在窄窗口下被裁切。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 生成视频里的中文字幕看不清、像乱码或假字

- 现象：同款替换生成的视频中，中文卖点字、包装字或字幕变成糊字、假字、错字，截图中可见文字边缘扭曲且无法稳定识别。
- 根因：远程视频生成模型把中文当作画面纹理生成，而不是使用真实字体渲染。中文、小字号、运动模糊、手持产品、反光和 720p 压缩会让模型更容易生成不可读文字。
- 修复：远程生成前默认生成“字幕安全源片段”，把源片段顶部 16% 和底部 26% 常见字幕/营销大字区域遮罩后再上传给 LK888；模型提示词阶段禁止复刻、保留或新增顶部/底部字幕、营销大字、弹幕式文字和屏幕贴纸文字；最终合成阶段由本地生成 ASS 字幕并通过 ffmpeg 烧录。字幕使用 `Microsoft YaHei`、白字黑描边、底部固定边距，来源为片段 `script` 口播稿。
- 排查：查看任务 JSON 的 `sourceSegmentPath`、`sourceSegmentUploadPath` 和 `sourceSegmentSubtitleSafeStatus`。`sourceSegmentPath` 应保留原始源片段用于音频回填，`sourceSegmentUploadPath` 应指向 `source_XX_subtitle_safe.mp4`；若 `sourceSegmentSubtitleSafeStatus=failed`，说明本地 ffmpeg 遮罩失败，远程模型可能仍会看到原片字幕。
- 配置：`VIDEO_REPLACE_SUBTITLE_SAFE_SOURCE=1` 默认开启；临时关闭时设为 `0` 并重启本地客户端。`VIDEO_REPLACE_BURN_SUBTITLES=0` 只会关闭最终后期字幕烧录，不会解决远程模型复刻原片字幕的问题。
- 验证：`tests/test_video_replacement_v2.py#L1191-L1218` 覆盖主角/普通远程编辑提示词禁止复刻字幕并要求后期字幕层；`tests/test_video_replacement_v2.py#L1936-L1997` 覆盖 ASS 字幕生成和最终合成前烧录流程；`tests/test_video_replacement_v2.py#L2120-L2168` 覆盖上传字幕安全源片段、音频回填仍用原片段，以及 ffmpeg 生成有效安全源片段。
- 回滚：设置 `VIDEO_REPLACE_SUBTITLE_SAFE_SOURCE=0` 并重启本地客户端可临时跳过源片段遮罩；设置 `VIDEO_REPLACE_BURN_SUBTITLES=0` 会关闭最终后期字幕烧录。完整回滚 `backend/matrix_native_client.py` 和对应测试/文档后，远程模型可能再次把原片字幕生成成糊字或假字。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 原生客户端深色主题下勾选框、按钮或文本框看不清

- 现象：同款替换页的“我确认已获得该真人脸图授权”勾选框几乎不可见；“下载报告”等次级按钮文字对比度不足；口播稿或提示词文本框点击/选中文本后文字难以辨认。
- 根因：全局 Qt 样式只覆盖了部分输入控件和按钮，未给 `QCheckBox::indicator` 设置足够明显的边框、选中图标和 hover 态；`QPlainTextEdit/QTextEdit` 的选中文字颜色未固定；`QPushButton#ghost` 在深色背景下缺少稳定最小宽度和高对比文字。
- 修复：`backend/matrix_native_client.py#L1744-L1784` 更新全局 QSS，补齐复选框指示器、按钮、文本框 focus/selection/disabled、表格选中态的可读样式。
- 验证：`tests/test_video_replacement_v2.py#L210-L225` 覆盖深色主题必须包含复选框图标、文本框选中颜色、表格选中颜色和次级按钮最小宽度；运行定向测试通过。
- 回滚：仅回滚 `build_qss()` 的样式改动和对应测试。回滚后不影响生成链路，但深色主题下控件可见性会退回旧问题。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 同款替换片段提示词显示英文

- 现象：同款替换生成方案或任务报告里出现 `Create a new e-commerce short-video segment...` 等英文视频片段提示词，不符合中文客户端体验。
- 根因：同款替换的基础片段 prompt 已中文化，但关键帧 prompt、视频 prompt 和混合远程编辑 prompt 仍保留英文约束；部分测试也仍断言旧英文模板。
- 修复：`backend/matrix_native_client.py#L9832-L10314` 将源视频锁定、跑偏重试、片段、关键帧、图生视频和远程编辑约束统一为中文；`backend/matrix_native_client.py#L12556-L12558` 的重复锁定检测改为识别 `源视频锁定：`。
- 验证：`tests/test_video_replacement.py#L40-L164` 和 `tests/test_video_replacement_v2.py#L696-L735`、`tests/test_video_replacement_v2.py#L2252-L2268` 覆盖中文片段提示词、关键帧锁定、源视频锁定、场景参考可选约束。
- 回滚：回滚上述提示词函数和测试即可。回滚后生成链路可运行，但任务 JSON 和上游 prompt 会重新出现英文模板。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 读取评论返回结果但旧 Web 入口显示 task_timeout（历史记录）

- 现象：旧 Web 内容采集入口点击“看评论”后显示 `读取失败: task_timeout`；中心服 `/api/local-browser/status` 可看到 Windows 本地节点在线，且对应 `douyin.comments` 任务已有 `result.ok=true` 和评论结果，但任务状态仍停在 `running`。
- 根因：抖音评论接口返回的 `result.comments` 是对象结构，例如 `{status_code, comments:[...]}`。中心服 `local_browser_result()` 保存任务时把 `result.comments` 当列表执行 `[:500]`，触发 `KeyError: slice(...)`。异常发生前任务已被写成 `running` 并保存了部分结果，后续没有机会标记 `done`，客户端轮询直到超时。
- 修复：`backend/central_server.py#L12464-L12479` 新增本地浏览器结果列表归一化；`backend/central_server.py#L12893-L12899` 保存 `items/comments/leads` 时只切片列表，并在 `comments` 是对象时回退使用已规范化的 `items` 或嵌套评论列表。
- 验证：`tests/test_api_download_contract.py#L295-L336` 覆盖 `douyin.comments` 返回对象型 `comments` 时任务必须结束为 `done`；运行 `.venv-win\Scripts\python.exe -m unittest tests.test_api_download_contract` 通过。
- 回滚：仅回滚 `backend/central_server.py` 的本地浏览器结果列表归一化与对应测试。回滚后评论任务可能继续出现“结果已有但状态 running，页面 task_timeout”的表现。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 读取评论使用默认无效抖音 Cookie

- 现象：本地客户端“看评论/读取评论”任务进入本地浏览器队列后失败或反复重排，登录窗口默认打开 Chrome，但评论读取仍提示失败。
- 根因：本地客户端提交 `douyin.comments` 时没有携带 `accountId`，服务端 `/api/douyin/comments` 直接读取默认 `auth_cookie.json`。当默认缓存只剩 `msToken`、而账号矩阵里存在最新可用抖音账号时，评论接口没有切换到该账号的 `auth_cookie.json`。
- 修复：`backend/api_server.py#L344-L366` 新增 `default_douyin_comment_account_id()`，按 `lastLoginAt/updatedAt` 优先选择账号矩阵中最新且 Cookie 缓存含登录标记的抖音账号；`backend/api_server.py#L4745-L4765` 和 `backend/api_server.py#L5113-L5151` 的 GET/POST 评论接口在未显式传入账号时优先进入该账号作用域，找不到可用账号时保留旧的默认鉴权逻辑。
- 验证：`tests/test_douyin_multi_account.py#L103-L121` 覆盖默认缓存无效但账号矩阵账号可用时的自动选择；运行 `.venv-win\Scripts\python.exe -m unittest tests.test_douyin_multi_account` 通过。
- 回滚：仅回滚 `backend/api_server.py` 中默认评论账号选择函数和两个 `/api/douyin/comments` 接入点，并回滚对应测试。回滚后旧行为会恢复为只读默认 `auth_cookie.json`，未传 `accountId` 的读取评论仍可能失败。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 分解失败：下载未完成 's_v_web_id'

- 现象：内容采集里点击分解抖音视频后，界面显示 `分解失败: 下载未完成 's_v_web_id'`，分解页不会进入 OCR、转写或报告生成。
- 根因：分解前必须先把原视频下载到本地。Windows 迁移后，当前账号的抖音缓存可能只剩 `msToken`，缺少 `sessionid`、`sid_guard`、`s_v_web_id`、`verifyFp`、`ttwid` 等真实登录和浏览器指纹字段。旧入口只检查“是否有 cookie”，导致不完整登录态继续进入抖音下载 API，底层访问 `auth.cookie['s_v_web_id']` 时抛出 KeyError。
- 修复：`backend/api_server.py#L446-L463` 新增抖音登录态完整性判断，`backend/api_server.py#L2943-L2954` 的 `require_auth()` 在只有 `msToken` 或缺少浏览器指纹时直接返回 `douyin_auth_incomplete`，外层统一按 HTTP 401、`needLogin=true` 处理。`backend/matrix_native_client.py#L8635-L8643` 将 `douyin_auth_incomplete` 和历史 `'s_v_web_id'` 映射为重新登录抖音提示，`backend/matrix_native_client.py#L3630-L3636` 在分解下载失败时使用该文案。
- 排查：访问 `/api/health`，若 `cookieReady=false`，先在本地客户端“账号矩阵”重新登录抖音；不要手工复制或拼接 cookie。若本地数据目录出现 `backend/datas/accounts/user-owner/accounts/user-owner` 嵌套，优先检查启动脚本是否重复设置账号数据目录。
- 验证：`python -m unittest tests.test_douyin_multi_account.DouyinMultiAccountTest.test_require_auth_rejects_ms_token_only_cookie` 覆盖只有 `msToken` 时拒绝进入下载链路；`python -m unittest tests.test_video_breakdown.VideoBreakdownHelpersTest.test_download_auth_error_is_localized_for_breakdown_status` 覆盖客户端错误文案。
- 回滚：只需回滚 `backend/api_server.py` 中完整性校验和错误映射改动；但回滚后会恢复不可读的 `'s_v_web_id'` 失败表现，不建议生产长期回滚。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 同款替换成片没有按口播稿说话

- 现象：分解报告里有口播稿，同款替换成片画面已生成，但听到的文字仍像原视频音频，或没有严格按照新口播稿朗读。
- 根因：旧默认策略为了降低首段耗时和上游失败率，会把识别到台词的片段仍标记为 `non_talking`；非口播链路会生成同款画面后回填源片段音频，口播稿只作为视觉生成提示和任务 JSON 记录，不会强制生成新的音频轨。
- 修复：新增 `VIDEO_REPLACE_STRICT_SCRIPT_AUDIO` 和页面“严格按口播稿生成语音”开关。开启后，有 `script` 的片段会强制转为 `talking`，走 `TTS -> 数字人口播 -> 下载 -> 音频/视觉 QC`，不再回填原视频音频。
- 排查：查看 `backend/datas/video_replacements/<job-id>/replacement_job.json`。若片段 `segmentType=non_talking`，该片段不会按口播稿重新说话；若 `strictScriptAudio=true` 且有 `script`，片段应为 `talking` 并包含 `ttsUrl`。
- 回滚：将 `VIDEO_REPLACE_STRICT_SCRIPT_AUDIO=0` 写入 `backend/.env` 或进程环境并重启客户端；也可以在页面取消“严格按口播稿生成语音”。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 Windows 生产验证环境问题

- 现象：在 Windows 上安装 `backend/requirements.txt` 时，系统 Python 3.14 会卡在 `rapidocr-onnxruntime==1.4.4` 依赖解析或安装失败。
- 根因：当前 OCR 依赖链尚未支持 Python 3.14。项目依赖按 Python 3.12 验证，不能把 3.14 作为生产验证解释器。
- 修复：使用 Codex 工作区内置 Python 3.12.13 重建 `.venv-win/`，再安装 `backend/requirements.txt`。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_deployment_security tests.test_openapi_contract -v`。
- 回滚：删除或停用 `.venv-win/` 后重新按 Python 3.12 创建；不要提交虚拟环境目录。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 ffmpeg 输出在 Windows GBK 环境解码失败

- 现象：同款替换媒体校验或音频 QC 在 Windows 上抛出 `UnicodeDecodeError`，表现为片段校验误失败。
- 根因：`ffmpeg/ffprobe` 输出中可能包含非 GBK 字节，`subprocess.run(..., text=True)` 默认使用系统编码解码，在中文 Windows 环境下会按 GBK 读取。
- 修复：`probe_media()`、`_replacement_audio_qc()`、`_probe_video()` 以及测试辅助 `mean_volume_db()` 显式使用 `encoding="utf-8", errors="replace"`。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2 -v`。
- 回滚：仅回滚上述解码参数相关代码；若回滚后 Windows 再现该问题，应恢复 UTF-8 replacement 策略。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 Git 可追溯性恢复

- 现象：项目根目录存在 `.git`，但 `git status` 返回 `fatal: not a git repository`。
- 根因：空 `.git` 目录带有显式 DENY ACL，Git 无法读取或初始化仓库元数据。
- 修复：只移除 `.git` 目录上的显式 DENY ACE，然后执行 `git init` 恢复最小可追溯能力。未执行提交，也未删除用户文件。
- 验证：`git status --short` 可正常返回工作区状态。
- 回滚：不建议回滚 ACL 修复；如必须回退，先备份当前 `.git` 元数据并确认不会破坏可追溯性。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 本地验证临时目录污染

- 现象：测试或验证脚本可能在根目录留下临时验证数据。
- 根因：本地冒烟验证需要可写临时目录，默认系统临时目录在受限环境中不可控。
- 修复：统一使用 `.tmp-validation/` 保存项目级临时验证文件，并加入 `.gitignore`。
- 验证：`tests.test_deployment_security` 检查 `.tmp-validation/`、虚拟环境、日志、数据目录和 `.env` 均被忽略。
- 回滚：若需要清理 `.tmp-validation/`，先确认目录仅包含可再生成的验证文件；不要使用递归删除清理未知路径。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 Windows Docker/WSL 生产冒烟修复

- 现象：Docker Desktop 启动后 `docker info` 报 `no connected VM` 或普通权限访问 `//./pipe/docker_engine` 被拒绝；compose 构建又可能卡在拉取 `python:3.12-slim`。
- 根因：验证机为 Windows 10 Pro 21H2 build `19044.1766`，Store WSL `2.7.10.0` 已安装但该系统版本不支持完整 Store WSL 状态命令，Docker Desktop WSL 后端不可用；同时 Docker Hub `auth.docker.io` / `registry-1.docker.io` 访问超时。
- 修复：启用 Hyper-V、VirtualMachinePlatform、WSL 和 HypervisorPlatform 可选功能后重启；将 Docker Desktop 切换为 Hyper-V 后端，并确保 `%APPDATA%\Docker\settings-store.json` 以 UTF-8 无 BOM 写入。验证时使用 `.tmp-validation\docker-config\config.json` 空配置，避免读取用户 Docker 凭据；Docker Hub 不通时先从 `docker.1ms.run/library/python:3.12-slim` 拉取并标记为本地 `python:3.12-slim`。
- 验证：`docker compose -f docker-compose.prod.yml --env-file backend\.env.prod up -d --build` 成功创建 `matrix-ship-central:prod-smoke-20260720`；`curl.exe -fsS http://127.0.0.1:9080/api/health` 返回 `ok=true`；`docker compose ... ps` 显示 `clean_20260710_150252-matrix-central-1` 为 `Up ... (healthy)`；`docker inspect --format "{{json .State.Health}}" clean_20260710_150252-matrix-central-1` 返回 `Status=healthy`、`FailingStreak=0`。
- 回滚：Docker Desktop 设置变更前备份在 `.tmp-validation\settings-store.before-hyperv-20260720-130646.json`；如需恢复，先停止 Docker Desktop，再用无 BOM 写回备份。不要删除 `matrix-central-data` 卷、不要删除镜像、不要注销 WSL 发行版，除非发布负责人明确批准。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## LK888 访问不了本地上传图片/视频/音频

- 现象：产品图、人物图、场景图、源视频片段或 TTS 音频上传后，本地客户端拿到的是中心服 `/api/library/file/...` 或本地/内网 URL，LK888 远程模型无法拉取，导致同款替换、数字人或参考图视频生成失败。
- 根因：原链路只依赖中心素材库 `publicUrls`；当中心服未配置公网素材代理时，远程模型拿不到本地上传内容。`https://img.yunlingai.net/api/upload` 已提供稳定公网图片、视频和音频 URL。
- 修复：`backend/matrix_native_client.py#L1226-L1305` 保留独立公网素材上传分支。配置 `UPLOAD_API_URL` 和 `UPLOAD_TOKEN` 后，`upload_asset_url(..., mtype="image"|"video"|"audio")` 会优先带 `Authorization: Bearer <UPLOAD_TOKEN>` 上传图片、视频或音频，并返回 `https://img.yunlingai.net/uploads/...` 给 LK888。
- 配置：本机环境变量或 `backend/.env` 中设置：
  - `UPLOAD_API_URL=https://img.yunlingai.net/api/upload`
  - `PUBLIC_UPLOAD_BASE_URL=https://img.yunlingai.net/uploads`
  - `PUBLIC_IMAGE_BASE_URL=https://img.yunlingai.net/uploads`
  - `UPLOAD_TOKEN=<server token>`
- 服务端限制：公网服务允许 `jpg/jpeg/png/webp/gif/mp4/mov/webm/mp3/wav/m4a/ogg/aac`，应用与 Nginx 单文件上限均为 500MB。`400 unsupported_file_type` 表示扩展名不在白名单；`413 file_too_large` 表示超过上限。
- Token 获取：服务器可用 `ssh root@120.26.194.174 "sed -n 's/^UPLOAD_TOKEN=//p' /root/image-upload-service/.env"` 查看；不要写入代码或 `.env.example`。
- 回滚：删除本机 `UPLOAD_API_URL` / `UPLOAD_TOKEN` 配置并重启客户端，即回到中心服素材上传；代码回滚范围为 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py` 和相关 docs。
- 验证命令：
  - `.venv/bin/python -m unittest tests.test_video_replacement_v2 -v`
  - `.venv/bin/python -m unittest tests.test_digital_human_navigation -v`
  - `.venv/bin/python -m py_compile backend/matrix_native_client.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 数字人口播未上传音色时报 Gemini TTS 未拿到任务 ID

- 现象：只上传人物和场景、不上传 TTS 声音时，点击生成返回 `gemini-2.5-pro-preview-tts 未拿到任务ID: {"ok": false, "error": "lk888_proxy_error"}`。
- 根因：未上传声音时，客户端会先根据页面音色自动调用 `gemini-2.5-pro-preview-tts` 生成语音。当前失败发生在语音合成下单阶段，中心服 LK888 反代返回 `lk888_proxy_error`，可灵数字人视频尚未开始生成。
- 修复：`backend/matrix_native_client.py#L4575-L4592` 捕获 Gemini 命名音色 TTS 异常，写结构化日志 `digital_human_tts_voice_fallback`，并自动降级到 `doubao-tts-2.0`，继续生成公网音频 URL。
- 降级影响：降级后音色不再严格等同页面选择的 Gemini 命名音色，但可以保证不上传音色文件时流程继续；上传 TTS 声音文件仍会跳过自动 TTS，不受影响。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_digital_human_navigation.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 到上一稳定快照。
- 验证命令：
  - `.venv/bin/python -m unittest tests.test_digital_human_navigation -v`
  - `.venv/bin/python -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_talking_segment_reuses_existing_tts_and_kling_digital_human tests.test_video_replacement_v2.VideoReplacementV2Test.test_talking_segment_rejects_loopback_avatar_before_tts -v`
  - `.venv/bin/python -m py_compile backend/matrix_native_client.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## Gemini 降级 Doubao 后仍报 lk888_proxy_error

- 现象：Gemini TTS 降级后继续返回 `doubao-tts-2.0 未拿到任务ID: {"ok": false, "error": "lk888_proxy_error"}`。
- 根因：本地中心服直连 `https://api.lk888.ai` 时 TLS 握手超时，失败发生在 LK888 代理网络层，尚未到模型参数校验或任务创建。
- 修复：在 `120.26.194.174` 的 `ai_education_nginx` 增加 `https://img.yunlingai.net/lk888-upstream/` 固定上游代理，并将本地 `backend/.env` 的 `LK888_BASE_URL` 改为该入口；本地中心服仍负责注入 LK888 key。
- 验证：公网代理不带 `Authorization` 返回 401，带假 key 返回 LK888 `invalid_api_key`；本地 `LK888_BASE_URL + /v1/models` 使用真实 key 返回 200；本地中心服 `/lk888/v1/models` 使用有效 session 返回 200。
- 回滚：恢复本地 `.env` 备份 `backend/.env.bak_lk888_proxy_*`，服务器恢复 `/root/ai-education-platform/nginx/nginx.conf.bak.lk888-upstream-*` 并 reload Nginx。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## Kling 数字人报请求体不是有效 UTF-8

- 现象：`kling-avatar-image2video 未拿到任务ID: {"code":400,"data":{"详情":"请求体不是有效的 UTF-8编码..."}}`，通常发生在上传本地人物图并带中文 prompt 的数字人生成。
- 根因：`kling-avatar-image2video` 对本地人物图请求要求 UTF-8 JSON body；旧实现把本地头像作为 multipart `image` 文件字段提交，中文 prompt + multipart body 会被上游按非 JSON/非 UTF-8 请求体拒绝。代理层也已修正为 `proxy_set_header Content-Type $http_content_type;`，避免其他 multipart 接口丢失 `boundary`。
- 修复：`backend/matrix_native_client.py#L4873-L4886` 生成时优先使用已上传到公网素材服务的头像 URL；只有没有可远程访问 URL 时，才由 `backend/matrix_native_client.py#L4596-L4618` 将本地头像转为 `data:image/...;base64,...` 兜底提交。
- 验证：真实 key 探针确认 JSON + `data:image/png;base64,...` 能创建 LK888 task；新增 `tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_sends_local_avatar_as_json_data_url` 锁定本地头像 JSON data URL 契约。
- 回滚：恢复 `backend/matrix_native_client.py` 和相关测试/文档；服务器代理回滚点为 `/root/ai-education-platform/nginx/nginx.conf.bak.lk888-content-type-*`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 数字人口播报“文件不是有效的base64格式”

- 现象：点击数字人口播生成后返回 `kling-avatar-image2video 生成失败：status=错误；message=文件不是有效的base64格式`。
- 根因：数字人口播页上传或 AI 生成形象后同时存在公网头像 URL 和本地缓存图；旧链路在真实生成时可能走到本地/base64 兜底。部分 LK888/可灵路由对该包装更敏感，会把图片字段判定为非法 base64。
- 修复：`backend/matrix_native_client.py#L4660-L4886`、`backend/matrix_native_client.py#L4926-L4954` 保存本地人物图路径 `_avatar_path` 和公网头像 URL `_avatar_url`；点击生成时优先传公网头像 URL；没有公网 URL 时才用本地 data URL 兜底。
- 降级/安全：如果本地文件不存在，仍回退到原远程 URL；场景图不参与本次修复，必要时可先不上传场景图验证人物图链路。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_digital_human_navigation.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 到上一稳定快照；不涉及数据库迁移。
- 验证命令：
  - `.venv/bin/python -m unittest tests.test_digital_human_navigation -v`
  - `.venv/bin/python -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_sends_local_avatar_as_json_data_url -v`
  - `.venv/bin/python -m py_compile backend/matrix_native_client.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 分解视频结果不能直接带到数字人口播

- 现象：分解视频完成后只能进入“同款替换”，数字人口播页仍需要手动复制口播稿和重新填写人物形象描述。
- 修复：`backend/matrix_native_client.py#L3543-L3958` 新增“生成数字人口播”入口，完成分解后发送 `digital_human_seed`；`backend/matrix_native_client.py#L7638-L7662` 优先从转写口播抽取脚本，并根据视觉/报告生成可编辑形象描述；`backend/matrix_native_client.py#L4908-L4915` 在数字人口播页接收 seed 后只填入主题、形象描述和口播稿，不自动生成媒体。
- 可观测/安全：该入口不调用远程生成、不扣数字人额度；用户必须先确认或修改形象描述，再手动生成/上传人物形象并点击生成。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_digital_human_navigation.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 到上一稳定快照；不涉及数据库迁移，`migration.sql` 无需变更。
- 验证命令：
  - `.venv/bin/python -m unittest tests.test_digital_human_navigation -v`
  - `.venv/bin/python -m unittest tests.test_video_breakdown tests.test_video_replacement -v`
  - `.venv/bin/python -m py_compile backend/matrix_native_client.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 用户协议或隐私政策点击无反应

- 现象：登录页展示《用户协议》和《隐私政策》，但点击不打开任何内容。
- 根因：旧客户端两个链接的 `href` 都是 `#`，没有绑定 `linkActivated`，项目也没有内置协议文本。
- 外部参考页限制：`http://120.26.194.174/legal/terms` 和 `/legal/privacy` 使用明文 HTTP；HTTPS 为自签名证书。两个地址返回完整 SPA 外壳，不适合作为正式客户端的实时法律文本源。
- 修复：正文以 Markdown 内置到 `backend/legal/`，客户端用可滚动双标签弹窗离线展示；PyInstaller 同步包含 `legal/` 目录。
- 内容校准：运营主体为“云灵星图数字科技有限公司”，云豆规则为 `1 云豆 = 1 元`；协议 v1.0 生效日期为 2026-07-15。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 登录返回 legal_consent_required 或 legal_consent_outdated

- HTTP 428 + `legal_consent_required`：请求没有 `legalConsent`、用户未勾选同意，或 `acceptedAt` 格式不正确。
- HTTP 428 + `legal_consent_outdated`：客户端提交的协议或隐私政策版本和中心服不一致。
- 处理：确认客户端与中心服加载相同的 `LEGAL_TERMS_VERSION`、`LEGAL_PRIVACY_VERSION` 和正文，然后重启两个进程。
- 自动登录：协议升级后旧自动登录会被清除，回到登录页重新勾选是预期行为。
- 审计：成功同意会生成 `legal.consent.accept`。如登录成功但无该事件，检查中心服是否仍在运行旧代码。
- Phase 0 冒烟：初次直接请求参考 URL 只得到 6662 字节 SPA HTML，无法提取正文；通过浏览器渲染后取得参考文本，并改为本地文档避免网络依赖。
- 验证命令：
	  - `PYTHONPATH=backend .venv/bin/python -m unittest tests.test_legal_agreements -v`
	  - `.venv/bin/python -m py_compile backend/matrix_native_client.py backend/central_server.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## Web 版点击左侧栏后仍停在企业页（历史记录，已退役）

- 状态：该 Web 入口已随 `2026-07-27 Web 交付面移除` 下线；当前登录入口只保留原生客户端。
- 历史根因：旧 Web 未登录门禁会拦截业务模块，且 Web 登录请求未提交中心服要求的 `legalConsent`。
- 当前排查：如用户无法登录，请从原生客户端登录页检查账号、密码、协议同意和中心服 `/api/auth/login` 响应；不要再访问 `frontend` 静态页。
- 回滚：如需恢复历史 Web 登录入口，必须先校验 `backups/web-removal-20260727/archive.sha256`，再整体恢复 Web 归档和对应提交。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 退出登录后客户端直接关闭

- 现象：点击“退出登录”后主窗口消失，但没有出现新的登录界面；客户端日志只有退出记录，没有新的启动段。
- 根因：登录成功后登录页会释放背景视频和图像缓存，因此退出时需要重启进程来保证账号数据目录隔离。旧实现用 `subprocess.Popen()` 启动子进程后立即退出 Qt，macOS 下子进程没有真正脱离原终端会话。
- 修复：`backend/matrix_native_client.py#L135-L174` 用 `QProcess.startDetached()` 创建独立进程，`backend/matrix_native_client.py#L12998-L13030` 只在启动成功后关闭旧客户端。启动失败会保留当前窗口并显示 `errorId`。
- 可观测：成功日志事件为 `client_logout_restart_started`，失败为 `client_logout_restart_failed`；后者包含脱敏堆栈和稳定错误编号。
- 回滚：恢复上一个稳定快照中的 `backend/matrix_native_client.py`并重启客户端；不涉及数据库或用户数据迁移。
- 验证命令：
  - `.venv/bin/python -m unittest tests.test_client_logout -v`
  - `.venv/bin/python -m py_compile backend/matrix_native_client.py tests/test_client_logout.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 同款替换图片 502/504 或可灵提示无法获取文件

- 现象：关键帧报 `图片生成 502: lk888_proxy_error`、`图片生成 504: <html><h1>504 Gateway Time-out</h1>`，或 `kling-avatar-image2video` 返回“当我们试图获取文件内容时，出现了问题”。
- 根因：旧链路将产品、人脸、场景和关键帧的 `http://127.0.0.1:9080/api/library/file/...` 直接交给远程模型。远程服务的 `127.0.0.1` 不是用户 Mac，因此无法取文件；同步图片请求还会在中心服 240 秒旧超时处返回通用 502。V2 talking 片段关键帧会携带多张本地参考图转 `data:image` 并生成 `1024x1792` 竖图，上游代理或 LK888 图片模型排队/超时时可能返回 HTML 504。
- 修复：本地/中心图片在请求内存中临时转 data URL；保留 LK888 返回的公网关键帧 URL；可灵数字人优先使用公网 URL，没有公网 URL 时用 JSON `params.image=data:image/...;base64,...` 兜底。旧任务也可读取本中心素材并在内存中转码。关键帧遇到 502/504/timeout 会先用 `VIDEO_REPLACE_KEYFRAME_RETRY_SIZE` 和 `VIDEO_REPLACE_KEYFRAME_RETRY_REFS` 轻量重试一次；talking 片段仍失败且已有可用人物头像时，记录 `video_replace_keyframe_fallback` / `keyframeErrorId` 后继续数字人口播。
- 安全门禁：非当前中心的 localhost/私网 URL 不会读取或提交。音频仍必须是公网 URL。主角模式下非口播只下单 `happyhorse-video-edit` 源视频编辑；设置 `VIDEO_REPLACE_PRINCIPAL_REPLACEMENT=0` 才回到参考图视频模型。没有公网素材时仍在扣费前返回 `video_replace_remote_media_required`。
- 主角模式若 `happyhorse-video-edit` 未拿到任务 ID、返回参数错误或生成失败，任务应写入 `principal_video_edit_failed`，并保留 `remoteRequestFields`、当前 `model` 和 `remoteErrorId`；不能用旧参考图模型结果伪装成功。只有显式回滚开关关闭后，才按 `viduq3-turbo-cankaosheng -> wan2.7-cankaosheng -> viduq3-cankaosheng -> viduq2-cankaosheng -> happyhorse-r2v -> happyhorse-1.1-r2v` 候选链排查。
- 查证：任务 JSON 中 `keyframeUrl` 应为公网 URL 或空字符串；本地文件只保存在 `keyframePath`，中心库预览地址保存在 `keyframeLibraryUrl`。
- 回滚：设置 `VIDEO_REPLACE_KEYFRAME_FALLBACK=0` 可关闭 talking 降级；设置 `VIDEO_REPLACE_KEYFRAME_RETRY_REFS` 或 `VIDEO_REPLACE_KEYFRAME_RETRY_SIZE` 可调轻量重试强度。代码回滚范围为 `backend/matrix_native_client.py` 和 `tests/test_video_replacement_v2.py`；不涉及数据库迁移。
- 回归测试：
  - `.venv/bin/python -m unittest tests.test_video_replacement_v2 -v`
  - `.venv/bin/python -m unittest tests.test_video_replacement -v`
  - `.venv/bin/python -m py_compile backend/matrix_native_client.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 同款替换 V2 无法执行或合成

- `facefusion_not_configured`：`FACEFUSION_BIN` 为空、文件不存在或不可执行。此错误发生在上传和扣费前。
- `facefusion_models_missing`：`FACEFUSION_MODEL_DIR` 不是有效目录。只部署经过商业许可审查的模型，不要从源码或未知网盘补权重。
- `facefusion_license_missing`：缺少内部许可证记录引用。填写 `FACEFUSION_LICENSE_REF` 后重启客户端。
- `facefusion_requires_three_source_faces`：这是未启用的底层 FaceFusion 工具错误码；当前同款替换固定 `enableFaceFusion=false`，人物素材统一为一张清晰正脸全身照，不会要求正脸、左45°、右45°三张照片。只有绕过当前页面直接调用旧 FaceFusion 工具时才可能看到该错误码。
- `principal_actor_extract_failed` / `principal_actor_extract_invalid_response`：原片主角视觉定位失败或返回非结构化 JSON。当前客户端会记录 `video_replace_principal_actor_extract_failed`，并把已抽取的候选帧带回任务；若 `principalActor.status=manual_required` 且有候选帧，客户端会自动使用第一张候选帧继续生成。若页面仍直接显示“生成方案失败”，说明运行中的本地客户端未加载新代码，需要重启本地客户端。
- `principal_replacement_mismatch` / `principal_appearance_mismatch` / `principal_other_subjects_changed` / `principal_motion_mismatch`：主角身份、完整外观、其他人物保留或动作镜头保持未通过视觉 QC，属于主角模式硬阻断，不会按普通 `face_mismatch` 警告放行。若生成结果仍保留原片主角发型、服装、体型或配饰，应记录为 `principal_appearance_mismatch` 后单段重试。
- 默认策略：同款替换新增快速、标准、高一致三种人物一致性模式。默认标准模式不执行本地 FaceFusion，只将上传人物图作为远程参考和一致性 QC 基准。只有选择高一致模式时才会在远程结果后执行本地 FaceFusion；超时或失败会回退远程结果并进入人工审核。
- `facefusion_timeout:<秒数>`：高一致模式下本地换脸增强超过配置时间。系统已回退远程同款结果，可继续审核；如必须提高一致性，缩短片段、降低 FaceFusion 配置或切换高性能换脸环境后单段重试。
- `happyhorse-video-edit 生成失败` 且包含 `绿网检查失败`：上游内容审核未通过，通常不是本地文件缺失。更换参考视频片段、产品图、人物图或场景图后单段重试。
- 参考视频没有人物时，勾选“纯产品视频（无人物）”。该模式只强制上传产品图，不上传人脸、不要求选择原片目标人物、不执行 FaceFusion，也不会因为 `face_mismatch` 阻断；场景图可不传，未提供场景图时场景 QC 记为跳过，提供场景图时仍检查场景一致性。
- `video_replace_remote_media_required`：非口播远程编辑需要让上游读取源片段视频；如果中心服没有 `PUBLIC_MEDIA_BASE_URL` / `PUBLIC_MEDIA_TOKEN_SECRET`，上传后的源片段仍是本地或私网地址，客户端会在扣生成费前阻断。配置公网素材代理并重启中心服后重试。
- `audio_missing` / `audio_silent`：先检查单段 `audioStatus`。非口播段若 FaceFusion 丢音轨，程序会从 FaceFusion 前的编辑视频重新映射 AAC；仍失败时只重试该片段。
- `product_mismatch`：视觉 QC 判断产品形状、颜色、Logo 或主要包装文字不一致。默认只作为黄色质检提醒进入人工审核；设置 `VIDEO_REPLACE_STRICT_VISUAL_QC=1` 才会阻断片段。质检会同时查看原片源片段；若原片该段本来没有清楚出现目标产品，`sourceProductVisible=false` 时产品和 Logo 检查标记为 `skipped_source_absent`，不会因为生成结果没产品而报错。建议使用光线均匀、无遮挡、包装文字清晰的 1-3 张产品图。
- `facefusion_failed`：非口播或 talking 片段的本地 FaceFusion 失败/超时。默认作为 `review_warning`，保留未换脸的远程/数字人视频继续审核；根据 `facefusionErrorId` 查日志确认是超时、模型缺失还是输入脸图不可用。
- `face_mismatch`：视觉 QC 判断人脸不稳定或不是授权人物。默认只作为黄色质检提醒进入人工审核；严格质检开启时才会失败。建议重新选择原片目标人物，并更换角度更准确的人脸照片。
- `scene_mismatch`：只有上传场景图时才检查场景替换。未上传场景图时保留原片场景并跳过场景匹配；上传场景图后，远程编辑必须把原片场景槽位替换为上传场景，视觉 QC 发现仍保留原场景或生成了其他场景时会阻断片段。
- `reference_mismatch`：生成前参考图预检现在不因产品/场景类别与源视频不同而阻断，因为上传产品图或场景图表示强制替换对应槽位。人物图里的产品、行业、展厅、直播间或背景上下文仍只作为 warning。临时回滚可设置 `VIDEO_REPLACE_REFERENCE_PREFLIGHT=0`，总回滚用 `VIDEO_REPLACE_DRIFT_GUARD=0`。
- `visual_drift_blocked`：生成结果偏离原视频主题，例如汽车销售讲解变成美妆或食品带货。系统会自动强化源视频锁定并重试一次；如果仍失败，不进入最终合成。排查 `replacement_job.json` 中的 `visualDriftQc`、`driftRetryCount` 和 `qcWarnings[].reason`。
- `visual_drift_retry_exhausted`：严重漂移重试后仍失败，片段写入 `blockedReason=visual_drift_retry_exhausted`。处理方式是缩短片段、减少冲突参考图、重新上传更干净的人物图或产品图后单段重试；不建议直接关闭阻断进入生产成片。
- `topic_mismatch`：主题或商品类别已经偏离源视频，属于硬漂移，会自动重试并在重试耗尽后阻断。`role_mismatch` / `structure_mismatch` 默认只是人工复核提醒：例如汽车产品特写段没有人物、车内特写变成车身细节、字幕或讲解结构变化，但仍是汽车主题时，不会直接失败；只有设置 `VIDEO_REPLACE_STRICT_VISUAL_QC=1` 才会按严格质检阻断。
- `visual_qc_deferred`：视频、音频和首中尾帧已通过本地门禁，但远程视觉 QC 服务超时或异常。片段不会被判失败，会进入人工审核；请检查首中尾帧、试听音频后再确认合成。
- 前台失败弹窗、状态栏和片段表只显示中文说明；任务文件和结构化日志继续保留 `replacement_qc_failed:*` 等原始错误码。排查时根据页面“错误编号”检索日志。
- 状态停在 `awaiting_review` 是正常门禁。查看每段首、中、尾帧并试听，点击“确认片段并合成”后才会生成资产库成片。
- 任务文件位于 `~/.matrix_ship_agent/data/video_replacements/<job-id>/replacement_job.json`。本地临时文件默认 24 小时后在下次启动时清理，资产库成片位于独立稳定目录，不受影响。
- 任务重启后仍显示 `running`：客户端启动时会扫描 `video_replacements/*/replacement_job.json`。若任务没有当前进程内的活跃生成线程，旧 `running` / `generating` / `retrying` 片段会写入 `stale_client_restart_recovery` 并转为 `failed`；任务已有成功片段时整体为 `partial`，否则整体为 `failed`，避免页面误以为仍在后台执行。
- 旧版 `role_mismatch` / `structure_mismatch` / 人物背景类 `reference_mismatch` 阻断：点击“重试失败片段”会先把旧错误快照写入 `retryHistory`，清理 `error`、`blockedReason`、`visualDriftQc`、旧失败时间等字段，并把可降级原因转为 `qcWarnings` 人工复核提醒。`visual_drift_retry_exhausted`、`visual_drift_blocked` 和 `topic_mismatch` 等硬漂移记录只归档不静默改判。
- 根据页面 `errorId` 在 `~/.matrix_ship_agent/logs/client-YYYYMMDD.log` 查找结构化 JSON 日志。日志不包含 API Key、Token 或人脸二进制内容。
- 本地标准版日志出现 `facefusion_dev_target_selection_degraded` 是预期警告：官方 `3.7.1` 不支持独立 `--reference-face-path`，开发兼容器会选择画面中最大的一张脸。请仅用单人测试视频，不要用此模式验收多人精确换脸。
- 标准版项目和其模型许可并不等同于商业授权。`DEV-ONLY-OPENRAIL-AS-FACEFUSION-3.7.1` 只是开发环境标识，不能解锁生产部署。
- 若模型下载意外占用数 GB，检查是否运行了 `force-download --download-scope lite`。该命令会遍历所有处理器，不是单一换脸处理器的最小下载命令。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 到上一稳定快照；本次无 `migration.sql`，不需要数据库回滚。回滚前保留受影响 `replacement_job.json`，便于按 `recoveredAt`、`lastRetryPreparation` 和 `retryHistory` 追溯。

专项验证：

```bash
PYTHONPATH=.venv/lib/python3.12/site-packages python -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_recover_stale_running_replacement_job_marks_partial tests.test_video_replacement_v2.VideoReplacementV2Test.test_recover_stale_running_replacement_job_marks_failed_without_done_segments tests.test_video_replacement_v2.VideoReplacementV2Test.test_prepare_replacement_segment_for_retry_demotes_legacy_false_blocks tests.test_video_replacement_v2.VideoReplacementV2Test.test_prepare_replacement_segment_for_retry_retains_hard_drift_history -v
PYTHONPATH=.venv/lib/python3.12/site-packages python -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_v2_ui_has_plan_review_scene_and_three_face_inputs tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_video_edit_prompt_treats_scene_reference_as_optional_source_compatible tests.test_video_replacement_v2.VideoReplacementV2Test.test_visual_qc_treats_scene_reference_as_optional_when_source_topic_matches -v
PYTHONPATH=.venv/lib/python3.12/site-packages python -m py_compile backend/matrix_native_client.py tests/test_video_replacement_v2.py
```

Windows 本地导出包的完整 `tests.test_video_replacement_v2 -v` 受环境限制：仓库自带 `.venv` 是 macOS 路径，PySide6 wheel 也为 macOS 构建；使用 Codex 捆绑 Python + `.venv/lib/python3.12/site-packages` 可跑专项测试。2026-07-20 当前完整模块结果为 91 个用例中本次方案 1/2/3 和审查补测的 13 个专项用例通过，但模块整体仍有 12 个错误和 2 个旧模拟流水线断言失败；错误主要来自缺少 FFmpeg 和旧用例硬编码 `/tmp` 导致的 Windows 权限问题，两个断言失败表现为旧模拟同款流水线返回 `ok=false`，未纳入本次方案 1/2/3 范围。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 同款替换开始前提示上游余额不足或账号不可用

- 现象：点击“开始替换生成”后，还没有上传参考图或生成片段就弹出上游余额不足、模型未配置价格、上游账号未配置、未登录或 LK888 网关不可用。
- 根因：同款替换现在会在参考图上传和远程扣费前执行轻量上游预检：先读本地余额，再请求中心服 `/lk888/v1/models`。余额为 0、HTTP 402、401/403、503 或网关类失败会被转换成中文诊断，并写入任务 JSON 的 `upstreamPreflight`。
- 处理：余额不足先充值；`model_not_priced` 联系管理员配置模型价格；`lk888_not_configured` 检查中心服 `LK888_BASE_URL` / `LK888_API_KEY`；`not_authenticated` 重新登录客户端；网关类错误可稍后重试。
- 诊断摘要：失败任务会写入 `diagnostics.summary`、`diagnostics.errorId`、`diagnostics.retryable`、`diagnostics.nextAction`、`diagnostics.failedSegments` 和 `diagnostics.segmentErrorIds`。前台失败弹窗会追加失败片段和建议操作，日志仍可按 `errorId` 追踪。
- 回滚：仅需把 `VIDEO_REPLACE_UPSTREAM_PREFLIGHT=0` 写入本机环境或 `backend/.env` 并重启客户端即可跳过预检；代码回滚范围为 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`，不涉及数据库迁移。
- 验证命令：`python -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_upstream_preflight_blocks_zero_balance_before_generation tests.test_video_replacement_v2.VideoReplacementV2Test.test_replacement_error_display_localizes_upstream_billing_codes tests.test_video_replacement_v2.VideoReplacementV2Test.test_replacement_diagnostics_summary_counts_failed_segments tests.test_video_replacement_v2.VideoReplacementV2Test.test_start_generation_runs_upstream_preflight_before_uploading_references -v`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 同款替换第一片段处理很久

- 现象：一分钟视频在「同款替换」执行后，第一个片段停留很久，用户只能看到整体进度条转圈。
- 根因：第一个片段通常会先完成参考素材上传、源片段上传和远程生成任务下单。默认同款替换已改为非数字人口播链路；若显式开启 `VIDEO_REPLACE_ENABLE_AVATAR_SEGMENTS=1` 或手动把片段类型改为“口播”，该片段才会串行执行关键帧、TTS、数字人口播、下载和 QC。远程模型排队和轮询占大头，不代表客户端卡死。
- 修复：`backend/matrix_native_client.py#L5035-L5328` 新增耗时/ETA helper、默认数字人口播开关和片段删除 helper，`backend/matrix_native_client.py#L5457-L5458` 在表格新增“操作”列，`backend/matrix_native_client.py#L5824-L5901` 为每个片段记录开始/结束时间并发送 timing payload，`backend/matrix_native_client.py#L8521-L8564` 默认将有台词分段保留为非数字人口播同款替换，`backend/matrix_native_client.py#L9148-L9199` 将远程视觉 QC 超时降级为人工审核。
- 排查：查看页面状态栏当前阶段；若显示“远程视频编辑中（轮询 N 次）”，说明正在等待 LK888 视频编辑任务结果。若显示“生成数字人口播视频”，说明环境变量或片段类型启用了数字人口播。若长时间停在“上传源片段”，优先检查公网上传服务和 `UPLOAD_TOKEN`；若停在“执行人脸替换”，检查 FaceFusion 本地配置和输入人脸。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 到上一稳定快照；不涉及数据库迁移。
- 验证命令：
  - `.venv/bin/python -m unittest tests.test_video_replacement_v2 -v`
  - `.venv/bin/python -m unittest tests.test_video_replacement -v`
  - `.venv/bin/python -m py_compile backend/matrix_native_client.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 自动化工作流拆解失败后视频生成报剧本不足

- 现象：运行「自动化工作流」时，采集成功后第 2 步报 `contents is required`，第 3 步 `vidu-jieshuoman` 随后报“剧本内容不少于50个字符”，最终没有产物入库。
- 根因：工作流 `collect -> vision -> video -> library` 没有单独的 `text` 台词步骤，视频剧本依赖 `vision` 写入 `ctx["script"]`。当多模态上游不接受当前请求或素材 URL 不可直接读取时，`ctx["script"]` 为空，后续视频生成继续拿空脚本下单。
- 修复：`backend/matrix_native_client.py#L5427-L5523` 抽出工作流口播脚本兜底生成；`vision` 失败或结果过短时自动用采集标题、主题和知识库生成不少于 50 字脚本；`video` 下单前再次校验脚本长度，过短则先补脚本，仍不足时不调用视频模型。
- 回归测试：`tests/test_workflow_resilience.py#L50-L144` 覆盖多模态失败兜底和视频下单前脚本扩写，避免再次把空/短剧本传给 `vidu-jieshuoman`。
- 验证命令：
  - `python3 -m unittest tests.test_workflow_resilience -v`
  - `python3 -m py_compile backend/matrix_native_client.py tests/test_workflow_resilience.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 数字人口播上传场景图后没有换背景

- 现象：本地客户端“数字人口播”上传人物形象和场景图后，生成视频仍接近人物原图背景，或者没有明显采用上传场景。
- 根因：旧链路只把场景图作为 `scene_image/background_image` 和提示词弱参考传给 `kling-avatar-image2video`；第一次强制换背景修复只检查了“是否生成出合成图”，没有校验合成图背景是否真的采用上传场景，导致湖景等跑偏中间图被继续送入口播。
- 修复：`backend/matrix_native_client.py#L4640-L4682` 新增场景一致性质检；`backend/matrix_native_client.py#L4685-L4715` 生成场景版人物图时优先使用本地场景 data URL；`backend/matrix_native_client.py#L4744-L4804` 在 TTS 前执行“合成 -> 质检”硬门禁。上传场景图后必须先生成“人物站在上传场景中”的新形象图，并确认背景与上传场景一致，成功后才生成口播视频；失败则停止并退款，不继续生成错误背景视频。
- 前置条件：场景图必须先通过公网素材服务或中心服 `publicUrls` 变成远程模型可读取的 HTTPS URL。若为 `127.0.0.1`、内网、本地路径，会在 TTS 前返回 `digital_human_scene_not_public`。
- 回归测试：`tests/test_video_replacement_v2.py#L531-L676` 覆盖强制换背景调用顺序、场景不一致时停止、合成优先使用本地场景 data URL、质检 JSON 解析、无场景图跳过、私网场景阻断和 UI 文案。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `docs/superpowers/specs/2026-07-21-digital-human-forced-scene-background-design.md` 到上一稳定版本；不涉及数据库迁移。
- 验证命令：
  - `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_image_composes_background_before_tts tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_mismatch_stops_before_tts tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_composition_prefers_local_scene_data_url tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_background_verifier_rejects_mismatch tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_without_scene_skips_background_composition tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_rejects_private_scene_before_tts tests.test_video_replacement_v2.VideoReplacementV2Test.test_digital_human_scene_upload_copy_explains_forced_background -v`
  - `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 数字人口播上传人物/场景后生成超时

- 现象：本地客户端“数字人口播”使用上传的人物形象和场景图生成时，长时间等待后提示 `生成失败:kling-avatar-image2video 生成超时`。
- 根因：旧版 LK888 异步任务轮询只识别带 `.mp4/.mov` 后缀的结果 URL；若可灵返回 `video_url`、`output_url` 等无后缀签名下载链接，会一直识别不到结果。当前解析入口位于 `backend/matrix_native_client.py#L1013-L1074`，数字人入口位于 `backend/matrix_native_client.py#L4359-L4370`。
- 修复：新增 LK888 任务结果 URL 解析 helper，支持 `video_url/output_url/result_url/download_url/file_url` 等字段；失败/超时时带出 `task_id` 和最后状态摘要；数字人 `kling-avatar-image2video` 轮询放宽到 300 次，并放宽界面错误信息长度。
- 回归测试：`tests/test_lk888_media_task_parsing.py#L23-L38` 覆盖无 `.mp4/.mov` 后缀的 `video_url` 返回值，确保不会误报超时。
- 验证命令：
  - `.venv/bin/python -m unittest tests/test_lk888_media_task_parsing.py`
  - `.venv/bin/python -m py_compile backend/matrix_native_client.py`
  - `.venv/bin/python -m unittest discover tests`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 知识库包含注意事项，但问答返回暂无相关信息

- 现象：资料知识库中存在“注意事项”段落，询问“有什么注意事项吗？”时，问答仍可能回复暂无相关信息。
- 根因：旧版知识库检索主要依赖中文单字交集打分，并且返回 source 时固定截取 chunk 开头。若“注意事项”位于 chunk 后半段，客户端再次截断上下文后，模型拿不到关键正文。
- 当前实现：`backend/central_server.py#L1859-L1940` 负责短语加权和命中位置片段；`backend/matrix_native_client.py#L793-L814` 为每条 source 保留最多 900 字上下文。
- 修复：为中文知识库问题增加短语权重和标题样式加权，并在命中短语时返回围绕短语的片段；本地客户端知识库上下文保留到 900 字，避免再次截掉命中段落。
- 回归测试：`tests/test_kb_search.py#L18-L59` 覆盖“注意事项在 chunk 后半段”的场景，要求搜索结果优先返回真实资料，并包含注意事项正文；同时检查本地客户端保留足够的知识库 source 上下文。
- 验证命令：
  - `.venv/bin/python -m unittest tests/test_kb_search.py`
  - `.venv/bin/python -m unittest tests/test_agent_mode_defaults.py`
  - `.venv/bin/python -m unittest tests/test_library_video_playback.py`
  - `.venv/bin/python -m py_compile backend/central_server.py backend/matrix_native_client.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 用户名密码登录不应要求短信验证码

- 规则：`backend/central_server.py#L2210-L2216` 将 11 位纯数字识别为手机号登录；只有“手机号 + 密码”登录需要短信验证码，“用户名/账号名 + 密码”登录不需要验证码。
- 后端入口：`backend/central_server.py#L13470-L13492` 在密码校验通过后，按本次登录标识判断是否进入短信验证码校验。
- 客户端入口：`backend/matrix_native_client.py#L10968-L10975` 允许输入手机号或用户名；`backend/matrix_native_client.py#L11256-L11287` 只在注册时强制手机号格式，非手机号用户名登录只要求账号和密码。11 位纯数字标识按手机号处理，以避免与手机号登录产生歧义。
- 回归测试：`tests/test_auth_login_modes.py#L18-L36` 覆盖手机号需要验证码、用户名不需要验证码、客户端不再无条件要求验证码。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 用户名登录页仍显示验证码输入框

- 现象：输入 `admin` 后，如果点击“获取验证码”，页面提示“请输入 11 位手机号”，容易误以为用户名登录仍要求手机号。
- 根因：用户名登录后端已不要求验证码，但旧客户端 UI 始终显示验证码输入框和“获取验证码”按钮。
- 修复：登录账号输入框 `backend/matrix_native_client.py#L10968-L10975` 监听文本变化；`backend/matrix_native_client.py#L11115-L11121` 在登录模式下仅当输入 11 位手机号时显示验证码区，用户名登录时自动隐藏并清空验证码。`do_login()` 不再在模式分支前无条件校验手机号。
- 回归测试：`tests/test_auth_login_modes.py#L30-L39` 检查客户端不再对用户名登录显示/要求验证码。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 视频缩略图只显示播放占位图或中心播放按钮

- 现象：资产库或 Agent.模式里视频卡片显示深色背景和播放按钮，或视频首帧中间叠了播放按钮。
- 根因：旧版本地资产卡片直接使用 `_video_thumb()` 生成占位海报，没有读取视频第一帧。
- 修复：`backend/matrix_native_client.py#L8167-L8188` 使用 ffmpeg 抽取纯首帧并缓存，抽帧失败的备用海报也不再叠播放按钮；Agent.模式结果 `backend/matrix_native_client.py#L8464-L8464`、资产库卡片 `backend/matrix_native_client.py#L9156-L9156`、资产选择弹窗 `backend/matrix_native_client.py#L8982-L8982`、混剪时间线 `backend/matrix_native_client.py#L9702-L9702` 和生成结果 `backend/matrix_native_client.py#L9776-L9776` 均使用同一首帧函数。
- 回归测试：`tests/test_agent_mode_defaults.py#L29-L37` 检查视频卡片使用真实视频缩略图函数，且首帧函数内部不叠 `_play_badge`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 内容采集一键分解视频失败或报告不完整

- 现象：在「内容采集」输入抖音/小红书链接后点「分解」，可能提示下载失败、未找到视频文件，或报告里显示 OCR/音频转写未启用。
- 根因：一键分解先复用本机浏览器下载任务，再从下载结果中找本地视频文件；若作品是图集、平台风控、账号未登录、下载结果只有封面图，就无法进入视频抽帧。深度分析中的 OCR 和音频转写是可选增强，缺少 `pytesseract/PIL` 或本地转写接口时会降级，不阻断关键帧和 AI 汇总。
- 修复：新增「分解」按钮和「分解视频」页；`backend/matrix_native_client.py` 中 `_find_video_file_from_download()` 统一从 `material/files/savePath` 查找视频，`_probe_video()` / `_extract_breakdown_frames()` 使用随项目依赖提供的 ffmpeg 读取基础信息和关键帧，`_ocr_breakdown_frames()` / `_transcribe_breakdown_audio()` 返回结构化降级状态。
- 回归测试：`tests/test_video_breakdown.py` 覆盖视频文件选择、图集/图片下载不误判为视频、报告 Markdown、Prompt 栏目、ffmpeg 输出解析、OCR/转写降级、UI 入口存在。
- 验证命令：
  - `.venv/bin/python -m unittest tests.test_video_breakdown -v`
  - `.venv/bin/python -m unittest tests.test_video_breakdown tests.test_agent_mode_defaults tests.test_library_video_playback -v`
  - `.venv/bin/python -m py_compile backend/matrix_native_client.py`
  - 使用 ffmpeg 生成 1 秒测试视频后调用 `_probe_video()` 和 `_extract_breakdown_frames()` 做本地冒烟验证。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 同款替换生成失败或无法合成

- 现象：在「分解视频」完成后点击「替换生成」，上传产品图和模特图后，片段生成失败、合成失败，或成片没有自动进入资产库。
- 根因：同款替换是“按分解报告重生成”，不是原片像素级修补。产品图必须先上传到中心素材库取得公网 URL；真人脸图必须确认授权；当前版本会先生成替换关键帧再图生视频，但远程模型仍可能弱遵循参考图，无法承诺像素级一致；每个片段生成后和合成前都会进行媒体真实性校验，任何坏片段都会阻止最终合成。
- 修复：`backend/matrix_native_client.py#L3722-L3733` 从分解页传递完整分析状态；`backend/matrix_native_client.py#L4780-L5699` 新增「同款替换」页面、授权人脸/虚拟模特、开始生成显式反馈、关键帧列、失败片段重试和自动入资产库；`backend/matrix_native_client.py#L7399-L7752` 实现 8 秒分段、源帧抽取、替换关键帧生成、关键帧优先图生视频、片段校验、合成前校验和资产库登记。
- 回归测试：`tests/test_video_replacement.py#L24-L204` 覆盖分段、prompt、替换关键帧优先生视频、失败片段可重试、合成前校验、资产库登记、UI 入口和开始生成反馈。
- 验证命令：
  - `.venv/bin/python -m unittest tests.test_video_replacement -v`
  - `.venv/bin/python -m unittest tests.test_video_replacement tests.test_video_breakdown tests.test_agent_mode_defaults tests.test_library_video_playback -v`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 同款替换提示 Seedance `duration` 对 t2v 无效

- 现象：片段任务返回 `doubao-seedance-1-5-pro-251215 ... status=错误; message=请求中指定的参数 duration 对于 t2v 中的模型 ... 无效`，旧客户端随后显示“生成超时”。
- 根因：该 LK888 路由将此 Seedance 模型按文生视频处理；同款替换却传入了参考图和 `duration`。这既不是网络超时，也不能保证产品图和人脸图被用作视频参考。
- 修复：`backend/matrix_native_client.py#L7532-L7558` 只允许 Reference-to-Video 模型进入同款替换，默认使用 `viduq3-turbo-cankaosheng` 并传递关键帧、产品图和模特图；`backend/matrix_native_client.py#L1069-L1077` 把中文“错误”视为任务终态并立即返回实际消息。
- 回归测试：`tests/test_video_replacement.py#L146-L177` 覆盖参考图模型、关键帧/产品/人脸引用和文生视频预拦截；`tests/test_lk888_media_task_parsing.py#L40-L43` 覆盖中文错误终态。
- 验证命令：
  - `.venv/bin/python -m unittest tests.test_video_replacement tests.test_lk888_media_task_parsing -v`
  - `.venv/bin/python -m py_compile backend/matrix_native_client.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 视频深度分解可靠性增强 Phase 0 冒烟

- 抖音下载：问题作品重新获取直链后，携带当前账号 Cookie、项目浏览器 User-Agent、`Referer`、`Accept` 和 `Range` 请求，返回 `206 video/mp4`；1024 字节样本被识别为 ISO MP4。说明 403 根因是下载器缺少浏览器请求上下文，不是作品不存在。
- Gemini 转写：使用 macOS 中文语音合成生成测试音频，经中心服 `/lk888/v1beta/models/gemini-3.1-pro-preview:generateContent` 上传 MP3，成功返回“这是矩阵星舰视频转写测试”。说明现有中心服会话和 LK888 Gemini 原生音频入口可用。
- OCR 首选安装失败：Mac 未安装 Homebrew，官方非交互安装器因没有无密码 `sudo` 权限退出；用户态 Micromamba 下载又被当前网络超时拦截。源码不得假装 Tesseract 已可用。
- OCR 自动回退：虚拟环境安装 `Pillow==11.3.0`、`pytesseract==0.3.13` 和 `rapidocr-onnxruntime==1.4.4`；RapidOCR 成功识别合成图片“注意事项 测试字幕”。运行时设计为 Tesseract 可用时优先使用，否则自动使用 RapidOCR。
- 备份清单：首次 `shasum` 因系统不支持 `C.UTF-8` locale 失败，改用 `LC_ALL=C LANG=C` 后成功生成 7 个源文件的 SHA256 清单。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 分解报告没有画面、OCR 或口播

- 先看报告“来源”区。若时长或分辨率为 `-`，并出现 `download_html_body`，说明本地 `.mp4` 实际是平台错误页，必须重新下载，不能继续分析。
- 新链路会在抽帧前调用 ffmpeg 真实性校验。无效文件不会入库；同源历史坏素材会进入 `quarantine/<material-id>/<timestamp>/`，新文件修复原记录并保留 ID。
- OCR 报告会显示实际引擎。`tesseract` 表示系统依赖可用；`rapidocr` 表示自动回退；`none` 表示两种引擎都不可用。
- 音频转写为 `partial` 时，报告列出失败区间、错误码和 `errorId`。点击“重试转写”只处理这些区间，不重复下载、抽帧或 OCR。
- 视频超过 10 分钟时只转写前 10 分钟，报告会明确写“仅分析前 10 分钟”。
- 验证命令：
  - `.venv/bin/python -m unittest tests.test_video_breakdown tests.test_video_transcription -v`
  - `.venv/bin/python -m unittest discover tests -v`
  - `.venv/bin/python -m py_compile backend/utils/media_validation.py backend/utils/structured_log.py backend/utils/video_transcription.py backend/utils/data_util.py backend/api_server.py backend/central_server.py backend/matrix_native_client.py`

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 真实视频深度分解验收

- 验收来源：抖音作品 `7654103220528119291`，本地与中心素材 ID 分别保持为 `6b52a85093b64245880cc2b47ddccd9f`、`177a724243a54e138cbe332977c238fa`。
- 下载结果：38,159,854 字节，169.47 秒，720x1280，音视频流完整且 ffmpeg 全量解码通过；旧 350 字节 HTML 伪视频已进入本地和中心 quarantine，没有重复素材记录或遗留 `.part/.incoming`。
- 分解结果：抽取 16 个关键帧；RapidOCR 识别 276 字；3 个 60 秒内音频分片全部成功，合并为 55 个绝对时间戳片段、2034 字；视觉分析返回 2171 字；临时帧和音频目录在结束后清理。
- 最终化时序：local-browser 任务 `lbt-229d307340014ece98a62955d343c245` 在中心镜像结束前保持 `running`，首次返回 `done` 时已同时包含 `libraryImported=true` 和中心素材 ID。正式网页/原生客户端路径是 `/api/local-browser/task`；直接调用旧云节点 `/api/douyin/download` 可能返回 `no_online_node`。
- 会话误用：验收脚本第一次 401 是直接读取了 `auth.json` 中以 `b:` 开头的编码 token。脚本必须调用 `matrix_native_client.load_auth_pref()` 解码会话；不得打印、复制或硬编码 token。客户端正式链路没有该问题。
- 重启验收：客户端新进程启动后，9081 使用本机 agent token 返回 200；local-browser 在线；抖音账号 `cookieReady=true`、64 个 Cookie、`usable=true`，小红书账号 `cookieReady=true`、16 个 Cookie。目标视频再次通过完整 ffmpeg 解码，元数据仍为 169.47 秒、720x1280、38,159,854 字节。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 深度报告末尾栏目缺失

- 现象：视觉、OCR 和转写均成功，但模型报告只到“爆点分析”，缺少“仿拍脚本”和“Agent.模式提示词”。
- 根因：报告调用原预算为 2600 token；模型成功返回被截断文本时，旧代码直接当作完成，只在整个调用抛异常时才降级，没有校验七栏契约。
- 修复：`backend/matrix_native_client.py#L7026-L7220` 将七栏固定为输出契约，解析模型标题、合并重复栏目正文并按固定顺序重建；缺失或空栏目使用当前视觉、关键帧、OCR 和带时间戳口播确定性补充。`backend/matrix_native_client.py#L7338-L7384` 将预算提高到 4800，并对任何栏目修复写结构化日志；完全失败时也保留全部证据并输出七栏。
- 回归测试：`tests/test_video_breakdown.py#L121-L259` 覆盖末尾截断、中间漏栏、乱序/重复标题和 AI 完全失败，检查七栏各出现一次、顺序固定、重复正文不丢失、降级证据完整且预算不少于 4200。
- 现场 API 验收：通过 `load_auth_pref()` + `set_session()` 注入正式管理员会话后，最新规范化器实测返回 3061 字报告，七栏各出现一次且顺序正确，状态为“分析完成”，未触发降级。独立脚本若只 import 模块却不调用 `set_session()`，会正确得到 `not_authenticated`，不能据此判断客户端 API 故障。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 下载显示成功，但素材没有入库

- 现象：小红书下载响应为 HTTP 200 和 `ok=true`，但 `material/materialId` 为空；或本地/中心入库异常直接暴露磁盘错误和堆栈。
- 根因：旧版 XHS 路由没有检查入库返回的素材 ID，入库函数抛异常时又落入通用 500 响应。图片分支同时只检查扩展名，损坏 JPEG 也可能进入素材库。
- 修复：抖音、小红书和中心镜像入库都要求非空 ID；返回值无效或事务抛异常时固定返回 HTTP 500、`library_import_failed`、`stage=library` 和脱敏 `errorId`。图片入库前执行 Pillow 完整解码。
- 回归验证：`tests/test_api_download_contract.py` 覆盖 XHS 假成功和本地/中心异常契约；`tests/test_material_repair.py` 使用真实 JPEG，并覆盖损坏图片拒绝入库。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 修复代码已通过测试，界面仍是旧行为

- 先比较进程启动时间与源文件修改时间。Python/Qt 进程不会自动热加载已修改的模块。
- 本次现场发现中心服和客户端均是 7 月 11 日启动的旧进程，新代码测试通过但尚未进入实际运行进程。
- 重启后必须同时验证 `/api/health`、在线 Cookie-ready 节点、实际下载文件的 ffmpeg 全量解码，不能只看进程或端口存在。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 转写重试仍失败

- `remote_timeout`：上游单分片超过 `VIDEO_TRANSCRIBE_TIMEOUT_SEC`，可再次重试；不要同时启动多个分解任务。
- `lk888_not_configured`：检查中心服进程是否加载 `LK888_BASE_URL` 和 `LK888_API_KEY`，并确认客户端已登录中心服。
- HTTP 401：中心会话失效，先重新登录客户端。不要把真实 Key 写入客户端代码。
- 根据报告中的 `errorId` 搜索 `~/.matrix_ship_agent/logs/client-YYYYMMDD.log`。日志包含完整堆栈，但认证信息已脱敏。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 恢复和回滚

- 初始快照：`backups/video-breakdown-reliability-20260711_190142/`。
- 最终已验证快照：`backups/video-breakdown-final-20260713_132558/`。当前桌面沙箱中 `rsync -R` 可能以 `setpgid: Operation not permitted` 退出，应使用 `mkdir -p` + `cp` 保留目录结构；这不是源码或磁盘故障。
- 每个 checkpoint 的 `SHA256SUMS.txt` 用于确认恢复文件版本。
- macOS 执行 `shasum` 若因 `C.UTF-8` locale 失败，使用 `env LC_ALL=C LANG=C` 生成和校验清单。
- 回滚代码前停止中心服和客户端；恢复后重新运行全量测试和健康检查。
- 不要直接恢复隔离目录中的 HTML 伪视频。任何素材恢复前都必须先运行 `validate_video_file()`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 云豆扣费未发生或退款异常

- 现象：文案、混剪等通用能力执行成功，但账户余额没有减少；或任务失败后重复点击退款导致担心重复加款。
- 根因：旧逻辑在主库模式下对客户端发起的 `/api/billing/charge` 直接放行，避免把云豆金额误当算力扣，但也导致通用能力没有真实扣费。
- 当前规则：`/api/billing/charge` 统一由中心服按 `capability` 定价；已知能力不信任客户端 `amount`。云豆钱包按 `1 云豆 = 1 元` 直接扣云豆，主库钱包按云豆金额与 `MAINDB_YUAN_TO_POWER` 换算为算力后原子扣减。
- 退款规则：失败退款必须携带原扣费 `ref`；中心服只退真实发生过且未退过的流水。重复退款返回成功但 `refunded=0`，不会凭空加款。
- 排查：查看 `/api/billing/ledger` 是否有对应 `ref` 的负数流水；主库通用扣费流水会标记 `wallet=maindb_generic`。余额不足应返回 HTTP 402 和 `insufficient_balance`。
- 验证命令：`python -m unittest tests.test_billing_unified tests.test_openapi_contract -v`。
- 回滚：回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_billing_unified.py`、`tests/test_openapi_contract.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md`；不涉及数据库结构或 `migration.sql`。
## 2026-07-29 云豆 1:1 规则迁移
- 现象：将扣除规则改为 `1 云豆 = 1 元` 后，如果旧余额不折算，历史用户余额会被放大成原来的 100 倍人民币价值。
- 修复：中心服充值档位改为 `1 元到账 1 云豆`，能力价格按旧价 `/100` 保存；例如文案扣 `0.07 云豆`、商品视频扣 `3.08 云豆`、数字人扣 `25.2 云豆`。本地客户端充值弹窗和用户协议同步新口径。
- 历史余额处理：停掉中心服和本地客户端后，先运行 `.venv-win\Scripts\python.exe scripts\migrate_yundou_one_to_one.py` 预览；确认无误再运行 `.venv-win\Scripts\python.exe scripts\migrate_yundou_one_to_one.py --apply`。脚本会先生成 `.bak-yundou-1to1-*` 备份，再把本地状态里的用户余额、普通云豆流水、充值订单和兑换码金额按 `/100` 折算；已经迁移过会跳过。
- 验证：管理员充值 `30 元` 应到账 `30 云豆`；普通用户执行文案扣费应从余额扣 `0.07 云豆`；再次运行迁移脚本应返回 `already_migrated`。
- 回滚：先停服，用 `.bak-yundou-1to1-*` 备份覆盖 `backend/central_data/scheduler_state.json`；再回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、`backend/legal/user_agreement.md`、`scripts/migrate_yundou_one_to_one.py`、扣费测试和相关文档。
## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 三角色权限冒烟与排查

- 现象：普通用户登录后看不到“企业中心”。这是预期行为；普通用户只使用创作、发布、采集、任务等业务模块，企业成员和企业全量数据只给企业家/管理员。
- 现象：`admin/test123456` 登录成功但仍看不到“企业中心”。优先检查 `/api/auth/login` 是否返回 `appRole=platform_admin` 或 `productRole=platform_admin`；如果运行中的旧中心服没有返回角色字段，客户端会按 `user.id=user-owner` 兼容推断为平台管理员。若仍不显示，重启中心服和本地客户端，确认运行进程已加载最新 `backend/matrix_native_client.py`。
- 现象：企业家或普通用户看不到微信充值、兑换码、生成兑换码、用户加款。资金入口已收口为平台管理员专用；手动请求 `/api/billing/recharge/*`、`/api/billing/redeem`、`/api/billing/topup` 或 `/api/admin/redeem-codes/*` 应返回 403。
- 现象：普通用户在账号矩阵、素材、知识库或任务中心看不到同企业其他人的数据。按当前权限设计，普通用户只看 `createdBy/createdByUserId/ownerUserId/userId` 指向自己的数据。
- 现象：普通用户新建内容后列表为空。优先检查创建接口是否写入 `createdBy` 或 `createdByUserId`；旧历史数据如果没有归属字段，会对普通用户隐藏，需由管理员补归属或由企业家查看。
- 冒烟验证：使用 `.venv-win\Scripts\python.exe -m unittest tests.test_role_permissions` 验证三角色映射、注册默认普通用户、企业总览范围和客户端入口守卫。
- 环境注意：若系统 Python 报 `ModuleNotFoundError: loguru`，先使用项目虚拟环境 `.venv-win\Scripts\python.exe`；按文件路径加载中心服测试时需要 `PYTHONPATH=backend`。

## 2026-07-25 素材发布多文件素材只打开了第一个文件
- 现象：在“素材与发布”中选中包含多个文件的素材，点击“打开素材”时只打开第一个命中的视频或图片，用户无法直接看到同一素材下的其它文件。
- 根因：旧逻辑 `_selected_material_file()` 只返回首个本机文件路径，`open_material()` 直接把该文件交给系统默认程序打开，没有区分单文件素材和多文件素材。
- 修复：新增 `_selected_material_files()` 和 `_selected_material_open_target()`；单文件素材继续打开文件，多文件素材改为打开文件夹。多个命中文件不在同一目录时，优先打开素材候选根目录，找不到则打开第一个命中文件所在目录。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本文件即可；不涉及数据库迁移。
## 2026-07-20 Windows 本地视频和客户端数据仍在 C 盘

- 现象：迁移到 Windows 后，部分同款替换任务、浏览器 profile、日志或下载素材仍出现在 `%APPDATA%\MatrixShipAgent\data`。
- 根因：旧版本本地客户端、启动脚本和 worker 默认使用 Windows AppData；迁移源码到 E 盘不会自动迁移本机执行节点数据。
- 修复：`backend/runtime_paths.py` 统一本地数据目录，Windows 源码部署默认写入 `backend/datas`；`start-local-test.ps1` 和 `backend/start-matrix-agent.bat` 显式设置 `MATRIX_AGENT_DATA_DIR`、`DY_DATA_DIR`、`DY_PROFILE_DIR`。
- 迁移策略：首次启动从旧 AppData 目录非破坏性复制缺失文件到新目录，不删除旧数据。
- 验证：运行 `python -m unittest tests.test_agent_mode_defaults -v`，确认默认目录、环境变量覆盖和启动脚本契约通过。
- 回滚：设置 `MATRIX_AGENT_USE_APPDATA=1` 可恢复旧 AppData 默认目录；设置 `MATRIX_AGENT_SKIP_APPDATA_MIGRATION=1` 可禁用旧目录复制。




## 2026-07-25 管理员充值后用户余额必须重启才变化
- 现象：管理员给用户加云豆后，目标用户本地客户端侧栏余额仍显示旧值，重启后才变化。
- 根因：后端 `/api/account/balance` 返回的是实时余额，但本地客户端侧栏只在登录时刷新；账户中心 `on_show()` 会刷新，普通业务页没有周期性刷新。
- 修复：登录成功后启动余额刷新定时器，每 30 秒调用 `fetch_balance()` 并通过 `BRIDGE.payload` 更新侧栏；退出登录时停止定时器。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_role_permissions.RolePermissionsTest.test_client_refreshes_sidebar_balance_periodically_after_login -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_role_permissions.py` 和相关文档；回滚后用户端仍需要进入账户中心或重启才能看到管理员充值后的侧栏余额变化。

## 2026-07-25 LK888 返回中文“错误”导致失败任务未退款
- 现象：同款替换片段生成失败，`replacement_job.json` 中片段 `status=failed`、`videoPath` 为空、错误为 `principal_video_edit_failed`，但账本里仍保留 `gen:*` 扣费，`STATE['gen_charges']` 也残留 task_id。
- 根因：客户端能识别 LK888 task-status 的中文失败状态 `错误/失败/超时/已取消`，但中心服反代退款判断只识别英文 `failed/error/timeout/canceled`，导致客户端停止任务时中心服没有执行退款。
- 修复：中心服新增 `lk888_proxy_task_flags()` 统一解析中英文失败/完成状态；轮询到失败后按原扣费 `ref` 调用 `refund_user_by_ref()`，幂等退款成功再移除 `gen_charges`。
- 现场注意：如果中心服正在运行，直接修改 `backend/central_data/scheduler_state.json` 可能被运行进程旧内存覆盖；需要通过运行中的中心服接口处理，或停止中心服后再做数据修正并重启。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_billing_unified.UnifiedBillingTest.test_lk888_proxy_task_flags_treat_chinese_error_status_as_failed -v`。
- 回滚：回滚 `backend/central_server.py`、`tests/test_billing_unified.py` 和相关文档；回滚后 LK888 中文失败状态可能再次无法触发自动退款。

- 图文同款替换 Phase 0：新增功能开关与任务目录骨架，`tests.test_xhs_note_replacement.XhsNoteReplacementSmokeTests` 通过；后续任务在该骨架上补模板、草稿和门禁。

## 2026-07-25 中心状态文件被默认骨架覆盖
- 现象：管理员登录后企业中心只剩“默认企业”，账户中心用户管理只剩 `admin`，原有 `boss/user01/user02/丰田汽车` 全部消失。
- 根因：`scheduler_state.json` 被工具以带 BOM 或损坏 JSON 写回后，旧中心服用普通 `utf-8` 读取失败；旧逻辑吞掉异常并初始化 `org-default/user-owner` 默认骨架，随后 `persist()` 把默认骨架覆盖到正式状态文件。
- 修复：中心服状态读取改用 `utf-8-sig`，状态文件存在但解析失败时抛 `StateLoadError` 阻断启动；写入前保护完整状态，拒绝默认骨架覆盖；启动前自动生成 `scheduler_state.json.bak-startup-*`。
- 安全恢复：停止中心服后使用 `.venv-win\Scripts\python.exe tools\repair_scheduler_state.py --restore backend\central_data\scheduler_state.json.bak-xxxx`，不要用 PowerShell `ConvertTo-Json | Set-Content` 直接写运行状态文件。
- 校验：运行 `.venv-win\Scripts\python.exe tools\repair_scheduler_state.py`，确认输出中的 `organizations/users/memberships` 数量符合预期；再运行 `.venv-win\Scripts\python.exe -m unittest tests.test_billing_unified -v`。
- 回滚：只有确认要清空重建环境时，才临时设置 `CENTRAL_ALLOW_STATE_REINIT=1` 并重启中心服；正常生产/测试环境不要开启该开关。
## 2026-07-28 数字人口播上传 TTS 声音提示公网素材上传失败 400
- 现象：数字人口播点击“上传TTS声音”选择 `mp3/wav/m4a/ogg/aac` 后，状态栏提示 `公网素材上传失败:400`，还没有进入可灵数字人视频生成。
- 根因：本机配置了 `UPLOAD_API_URL=https://img.yunlingai.net/api/upload` 后，旧客户端把 `mtype=audio` 发到独立公网素材服务；当时服务端只允许 `jpg/jpeg/png/webp/gif/mp4/mov/webm`，拒收音频扩展名并返回 400。
- 修复：公网素材服务 `/root/image-upload-service` 已支持 `mp3/wav/m4a/ogg/aac` 和对应音频 MIME，`image_upload_service` 已重建；本地 `backend/matrix_native_client.py#L1300-L1305` 保持音频和图片、视频一样优先走 `UPLOAD_API_URL`，返回 `https://img.yunlingai.net/uploads/...`。
- 排查：上传响应的 `url` 应为 `https://img.yunlingai.net/uploads/...`，并且 `curl -I <url>` 返回 HTTP 200 与 `Content-Type: audio/...`。如果仍提示“音频地址不是远程模型可读取的公网地址”，优先检查客户端是否已重启、`.env` 是否配置 `UPLOAD_API_URL` / `UPLOAD_TOKEN`。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_upload_asset_url_uses_external_public_upload_service_for_audio -v`；服务端运行 `PYTHONPATH=. pytest tests/test_upload_service.py -q`，并用 `https://img.yunlingai.net/api/upload` 上传 mp3 后访问返回的 URL。
- 回滚：本地回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py` 和本文件；服务端恢复 `/root/image-upload-service/backups/20260728-audio-upload/` 下的备份后重建 `image_upload_service`。


## 小红书图文同款冒烟记录（2026-07-25）

冒烟链路：4 张小红书图文假素材 -> 构建模板 -> 用 2 张替换图生成预览 -> 缺失 2 个槽位进入 AI 占位状态 -> 保存为 `image_note` 草稿 payload -> 发布预检返回 `xhs_note_ai_image_unconfirmed`。

验证命令：`.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteFourImageSmokeTests -v`，结果 OK。

常见问题：

| 现象 | 处理 |
|---|---|
| 点击保存草稿后返回 `feature_disabled` | 检查 `XHS_NOTE_REPLACEMENT_ENABLED` 是否被设为 `0/false/no/off`，恢复后重启本地客户端。 |
| 草稿生成但发布失败 `xhs_note_ai_image_unconfirmed` | 这是预期保护，先在图文同款页确认或替换缺图槽位；V1 仍不会真实发布图文。 |
| 草稿发布失败 `xhs_note_publish_not_supported` | V1 未接入小红书多图图文真实发布，需等待后续版本开放。 |
| 保存草稿返回 `xhs_note_save_failed` | 根据响应 `errorId` 查结构化日志，重点确认素材文件仍存在、账号数据目录可写。 |

## 内容采集一键进入图文同款（2026-07-25）

- 在「内容采集」中选中单条小红书链接，点击「图文同款」后，原生客户端会先下载该笔记的用户图片，再进入图文同款页面并读取图文结构；Web 端入口已退役。
- 如果提示「未找到图片素材，请先下载笔记」，说明当前下载结果没有用户发布图片；请确认这条笔记确实是图文笔记，必要时先点击「下载」检查素材。页面静态图、搜索图标和横幅不会被当作笔记素材。
- 如果提示「读取图文结构超时」，请确认本机执行引擎在线，并确认笔记已经下载完成后重试。单次读取最多等待 30 秒，超时后可再次点击「读取图文结构」。
- 回滚：如需恢复历史 Web 图文同款入口，必须先校验 `backups/web-removal-20260727/archive.sha256` 并整体恢复 Web 归档；常规回滚只需回滚原生客户端、后端、测试和文档改动。

## 原生图文同款跳转后不显示已下载内容（2026-07-27）

- 现象：在桌面客户端“内容采集”选中小红书链接并点击“图文同款”，页面已跳转，但来源素材、已下载图片和图片槽位为空。
- 根因：原生 `XhsNoteReplacementPage` 之前没有连接全局 `BRIDGE.payload`，因此没有接收 `xhs_note_replace_start`；页面也缺少原图缩略图区域，且槽位表只读取生成预览后的 `slotMappings`。
- 修复：页面接收采集事件后立即清理上一条任务，带入素材信息，显示全部下载图片及数量，自动读取结构；模板返回后直接按 `template.imageSlots` 显示槽位，点击缩略图可查看大图。
- 远程图片：本机文件优先直接读取；中心服 `/api/library/file/` 图片使用当前登录态后台加载。远程响应最多 4 路并发，按 64 KB 分块读取，单图累计超过 20 MB 会立即中止。外部签名 CDN 地址不会携带 `X-Matrix-User-Token` 或企业标识，中心认证请求不自动跨域重定向；签名 URL 与模板 `files` 分离，不把查询 token 写入任务槽位。
- 观测：远程图片加载失败会记录 JSON 结构化事件 `xhs_note_source_image_load_failed`，包含脱敏后的 `materialId`、`imageIndex`、`fileName` 和异常堆栈，不记录签名 URL 或凭据。
- 排查：先确认页面“原笔记图片”数量；若为 0，检查下载结果 `material.files` 是否包含 JPG/PNG/WebP 等图片，并检查同索引 `material.urls`。若数量正确但缩略图加载失败，按上述事件名查询客户端日志，并确认中心素材文件仍可访问。
- 生效：Python 桌面客户端不会热加载源码。修改后必须关闭当前客户端并重新启动，再从“内容采集”点击“图文同款”验证。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests -v`，应通过 14 项；再运行 `.venv-win\Scripts\python.exe -m unittest tests.test_api_download_contract tests.test_material_repair tests.test_native_publish tests.test_xhs_note_replacement -v`，应通过 99 项，并执行 Python 编译检查。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 与 Task 8 计划记录并重启客户端；不涉及数据迁移，已下载素材和现有图文任务无需删除。

## 图文同款保存草稿后素材发布看不到（2026-07-27）

- 现象：图文同款页面点击“保存草稿”提示本机保存成功，但切到“素材发布”后列表没有这条图文草稿。
- 根因：“保存草稿”旧链路只写入本机 `/api/xhs-note-replacement/save-draft` 返回的本地素材；而“素材发布”主列表读取的是中心素材库 `/api/library`，本机草稿没有同步到中心库，所以列表不可见。
- 修复：保存草稿成功后立即把草稿图片文件上传到中心素材库，并携带 `type=image_note`、`platform=xhs`、`status=draft`、标题/正文/标签、来源笔记和任务 ID 等追溯字段。同步成功时状态栏显示中心素材 ID；同步失败时本机草稿仍保留，并显示“同步到『素材发布』失败：<原因>”。
- 观测：中心同步异常会写 JSON 结构化日志 `xhs_note_draft_central_sync_failed`，包含本地草稿 ID、脱敏后的文件名数量、错误类型和堆栈，不记录用户 token 或签名图片 URL。
- 排查：若仍看不到，先确认状态栏是否提示中心同步失败；再检查中心服是否启动、当前登录态是否有效、草稿图片文件是否仍存在。中心服离线时只能保存本机草稿，恢复中心服后需要重新点击保存草稿触发同步。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`backend/central_server.py`、`backend/local_browser_worker.py`、相关测试和文档即可恢复旧行为；不涉及数据库迁移。

## 2026-07-27 小红书获客采集假数据基线

- 现象：获客中心出现主页链接为 `-`、用户名为空或等于评论、同一个主页重复，以及评论末尾带时间、地区、作者、`赞`、`回复`的记录。
- 根因：`backend/platform_adapters.py` 把评论容器内普通 `div` 也作为候选，并在压平换行后猜测用户名和正文；归一化阶段未校验主页，跨笔记按“用户名 + 评论”去重。
- Phase 0：假数据调用 `_xhs_normalize_comment()` 后三类无效记录全部被接受，证明现有代码缺少过滤行为。Windows 默认 GBK 标准输出无法打印 emoji，测试命令必须显式把 stdout 配置为 UTF-8；这不是业务模块导入失败。
- 预期修复：在采集层收紧评论节点，清洗尾部元信息，按主页校验和去重，并为每条淘汰记录写脱敏 JSON 日志。
- 回滚基线：修改前文件位于 `backups/xhs-lead-filtering-20260727/pre-edit/`，清单位于 `backups/xhs-lead-filtering-20260727/manifest.sha256`；先校验清单后恢复。
- 过滤原因码：`missing_profile_url`、`invalid_profile_url`、`empty_user`、`user_equals_comment`、`empty_comment`、`result_limit_exceeded`、`parse_failed`（解析异常原因）；兼容去重原因码为 `duplicate_user_comment`，主页去重原因为 `duplicate_profile`、`duplicate_profile_replaced`。
- 日志排查：查询 `xhs_collected_record_filtered`、`xhs_collected_record_deduplicated`、`xhs_collected_record_parse_failed`、`xhs_collection_filter_summary`、`xhs_collection_page_navigation_failed`、`xhs_note_collection_failed`；日志只包含长度、稳定错误码和 SHA-256 截断指纹，不包含用户名、评论、完整主页、query token 或原始异常文本；异常日志包含固定脱敏消息的新堆栈。
- 小红书显示“识别到 0 个客户”时先看调试快照：若 `backend/datas/accounts/<user>/debug/xhs-search-*.png` 显示“安全限制 / IP存在风险 / 300012”，说明搜索阶段被平台拦截，没有进入评论抓取。修复后接口会返回 `ok=false`、`error=xhs_ip_risk`、`riskCode=300012`，原生客户端显示“小红书安全限制：当前网络/IP存在风险，请切换可靠网络环境后重试”。排查日志事件为 `xhs_collection_search_failed`，其中只记录关键词长度、关键词指纹、调试 URL 指纹和风险码。
- 质量门禁：单次最多保留 300 条结果，原始候选固定上限为 900；汇总日志中的 `candidateDuplicateCount` 表示滚动采样时重复遇到的同一 DOM 记录。300 条候选过滤的测试硬门禁为 50ms 和 5MB 额外内存。DOM selector 已收紧，普通容器 `div` 不再作为候选；单笔记和跨笔记均按主页归并。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_lead_filtering tests.test_agent_mode_defaults tests.test_structured_log tests.test_openapi_contract tests.test_douyin_multi_account -v`，实际 79/79 通过；Python 编译检查和 `git diff --check` 退出成功。假数据冒烟返回 2 条有效主页记录，搜索风控模拟会返回 `xhs_ip_risk` 而不是正常 0 条，修改前六文件哈希复核无差异。
- 紧急降级：设置 `XHS_STRICT_LEAD_FILTER_ENABLED=0`（也接受 `false/no/off`）并重启本地执行引擎；降级会恢复兼容过滤行为，可能再次出现低质量结果，仅用于短期排障。

## 2026-07-28 同款替换漫剧项目资产同步报“本地资产不存在”

- 现象：同款替换新任务已成功创建漫剧项目，但随后报 `err-9a71d2e515ef4c43`，任务 JSON 中可见 `comic_api_http_404:{'detail': '本地资产不存在', 'localDev': True}`，页面只显示“生成失败，请根据错误编号查看日志”。
- 根因：本地客户端把上传的人物、场景、道具用临时 ID（如 `matrix-character-1`）直接调用项目资产详情更新接口 `PUT /api/v1/comic-drama/projects/{projectId}/{collection}/{assetId}`。漫剧后端会把该接口当作“更新已存在资产”，项目库里不存在这个临时资产 ID 时返回 404。
- 修复：`ComicProjectAdapter.upsert_manual_assets()` 改为先调用集合创建接口 `POST /api/v1/comic-drama/projects/{projectId}/{characters|scenes|props}`，把 `reference_image` 和 `reference_images` 一起传给漫剧后端；随后读取后端返回的真实资产 ID，并写回当前任务中的 `id` / `asset_id`，后续分镜绑定不再使用临时 ID。
- 排查：先打开 `backend/datas/accounts/<user>/video_replacements/<jobId>/replacement_job.json`，确认 `pipeline=comic_project`、`comicProjectId` 已存在且失败阶段在 `comic_assets` 附近；再按 `errorId` 到 `backend/datas/logs/client-*.log` 查 `upsert_manual_assets` 堆栈。如果看到 `本地资产不存在`，优先检查是否仍在运行旧客户端进程。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement -v`，应通过 24 项；运行 `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement.py`，应退出码 0。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本条故障记录即可恢复旧行为；本次不涉及中心服、远程漫剧 `server.py`、数据库迁移、OpenAPI 或环境变量。

## 2026-07-28 同款替换漫剧项目报 `comic_storyboard_id_missing`

- 现象：同款替换片段直接失败，提示 `错误编号 err-37cbd0f7358a4a6a；comic_storyboard_id_missing:segment_1`，任务 JSON 中已有 `comicProjectId` 和 `comicAssets`，但失败片段缺少 `comicStoryboardId`。
- 根因：漫剧 `/api/v1/comic-drama/projects/{projectId}/analyze` 是异步分析接口，当前后端可能只返回 `task_id`，真正的 `storyboards` 要等分析任务完成后再从项目详情读取。旧客户端把分析接口当同步接口使用，没拿到 `storyboards` 就继续进入片段生成，最终在写入分镜前报 `comic_storyboard_id_missing`。旧任务重试时如果已有 `comicProjectId` 但没有 `comicStoryboardId`，旧逻辑也会跳过重新分析，导致重复失败。
- 修复：片段生成前先读取项目详情恢复已有 `storyboards`；仍没有分镜时提交分析任务并等待任务完成，然后再次拉取项目详情，按分镜 `sequence/index` 或片段顺序回填 `comicStoryboardId`。已有项目重试和新建项目首次生成都会走这条恢复逻辑。
- 排查：打开 `backend/datas/accounts/<user>/video_replacements/<jobId>/replacement_job.json`，确认 `comicProjectId` 是否存在、每个片段是否有 `comicStoryboardId`。若 `comicAssets` 有值但片段缺 `comicStoryboardId`，优先检查是否仍在运行旧客户端。日志中若只看到 `comic_storyboard_id_missing` 而没有远程分析失败，说明问题在本地客户端没有等待/回填分镜。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_existing_project_recovers_missing_storyboard_ids tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_waits_async_analyze_task_before_using_storyboards -v`；完整回归运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement -v`，应通过 24 项。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本条故障记录即可；不涉及中心服、远程漫剧 `server.py`、数据库迁移、OpenAPI 或环境变量。按用户要求不自动重启本地客户端，生效需要手动重启本地客户端。

## 2026-07-28 同款替换漫剧编辑器“画面描述”出现 `口播：...`

- 现象：漫剧生成器项目里，分镜表的“画面描述”显示 `口播：哈哈哈哈哈...` 或直接显示用户口播稿；后续首尾帧/视频生成可能把台词当成画面动作、人物行为或场景内容，导致画面跑偏。
- 根因：本地客户端创建漫剧项目 `source_text` 时同时拼了 `口播：<segment.script>` 和 `画面：<segment.prompt>`；分镜视频 payload 又直接复用原始 `segment.prompt/description` 写入 `prompt/description/keyframes_video_prompt`。当分解结果或历史任务 prompt 中含有口播行时，台词就进入了视觉字段。
- 修复：新增 `_comic_visual_prompt_text()` 专门生成视觉提示，过滤 `口播/对白/旁白/台词/字幕` 行和片段 `script` 原文；项目剧本、分镜 `description/camera_movement/prompt/keyframes_video_prompt` 只使用视觉提示，最终台词只写入 `dialogue` 与 `audio_prompt.dialogue.text`。
- 排查：如果漫剧端已存在旧项目，打开当前任务 JSON 查看片段 `comicProjectId` 是否已创建。旧项目/旧分镜已经写入过污染文本时，本地新代码不会自动修改远程历史内容，需要重建新任务，或删除/重新分析该漫剧项目后再生成。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement -v`，应通过 24 项；运行 `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement.py`，应退出码 0。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本条故障记录即可；本次不涉及中心服、远程漫剧 `server.py`、数据库迁移、OpenAPI、`migration.sql` 或环境变量。按用户要求不自动重启本地客户端，生效需要手动重启本地客户端。
## 2026-07-28 同款替换漫剧首尾帧报 `comic_image_recovery_missing`

- 现象：漫剧项目已创建，但首尾帧生成立即失败，片段显示 `comic_image_recovery_missing:storyboard_<id>`；结构化日志中更早的错误是 `comic_api_http_502:{'detail':'计费请求重复'}`。
- 根因：项目 `296` 由 AI Canvas 本地兜底存储创建，平台 `comic_drama_projects` 表中不存在该 ID；计费日志写入 `project_id=296` 时触发外键错误。旧计费服务把所有 `IntegrityError` 都误报为“计费请求重复”，客户端随后恢复查询不到未创建的图片任务，最终覆盖了首个错误。
- 修复：计费入口先校验平台项目；存在时继续保留外键，不存在时以 `project_id=NULL` 记账并在描述/结构化日志中保留 `local_project_id`。计费完整性错误只有在真实找到同 `request_id` 日志时才按幂等返回，否则显示“计费记录写入失败”并写入脱敏请求指纹。客户端恢复失败时同时保留原始提交错误和 `recovery_missing`。
- 验证：远程 `tests.test_billing_actual_cost_settlement tests.test_aicanvas_billing_guard` 6/6 通过；真实计费冒烟对本地项目 `296` 返回 HTTP 200 且落库 `project_id=NULL`，对已存在平台项目 `295` 落库 `project_id=295`。两条测试记录随后已关闭，均未调用图片模型。本地客户端完整回归 37/37 通过。
- 回滚：远程恢复 `/root/ai-education-platform/backend/api/routes/aicanvas.py.bak.local-project-billing-20260728-1700` 和 `backend/services/billing_service.py.bak.local-project-billing-20260728-1700`；本地回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py` 和本次文档。不涉及数据库结构、OpenAPI 或环境变量；按用户要求不自动重启本地客户端。

## 2026-07-28 左下角余额和按钮重叠
- 现象：本地客户端左下角云豆余额旁的主题/退出按钮显示成横向长按钮，余额较长时按钮互相挤压或重叠。
- 根因：全局 `QPushButton` 样式设置了 `min-width:76px` 和较大横向 padding，侧边栏底部的图标按钮虽然调用了 `setFixedSize()`，但仍受全局按钮样式影响；余额标签也没有宽度上限。
- 修复：`backend/matrix_native_client.py#L2259-L2292` 为 `QPushButton#iconbtn` 设置独立短按钮样式，固定 `26px × 26px`；`backend/matrix_native_client.py#L23136-L23152` 给余额标签设置 `92px` 最大宽度，并把主题/退出按钮改为短固定尺寸。
- 排查：如果仍重叠，确认运行的是重启后的新客户端；检查样式表中是否存在后续 `QPushButton#iconbtn` 规则覆盖了 `min/max-width:26px`；运行 `.venv-win\Scripts\python.exe -m unittest tests.test_role_permissions.RolePermissionsTest.test_client_team_member_and_sidebar_controls_have_stable_widths -v`。
- 回滚：恢复 `backend/matrix_native_client.py` 和 `tests/test_role_permissions.py` 后重启客户端即可；本修复不涉及中心服或数据迁移。

## 2026-07-28 账号矩阵“今日发布”不更新
- 现象：账号矩阵顶部“今日发布”长期为 0，或发布成功后刷新账号矩阵仍没有变化。
- 根因：旧实现只累加账号对象自带的 `publishedToday/todayPublish` 字段，但中心服发布成功计数 `PUBLISH_RT` 没有回填到 `/api/accounts` 响应，也没有写入中心状态文件，重启后更容易丢失当天计数。
- 修复：`backend/central_server.py#L303-L394` 从 `STATE["publishRuntime"]` 恢复当天发布计数；`backend/central_server.py#L5847-L5879` 发布成功后持久化当天计数并给账号回填 `todayPublish/publishedToday`；`backend/central_server.py#L6821-L6849` 在 `/api/accounts` 返回前按角色过滤后统一补统计字段。
- 客户端兼容：`backend/matrix_native_client.py#L825-L848` 统一解析数字、`万`、`k` 等格式，账号矩阵汇总不再因非纯数字粉丝量失败。总粉丝量仍来自账号资料里的最近一次 `fans/followers` 字段；当前没有新增主动抓取平台粉丝数的定时任务。
- 排查：确认发布接口返回 `published=true`；检查 `backend/central_data/scheduler_state.json` 中是否存在 `publishRuntime.day` 和 `publishRuntime.counts`；如果跨天，计数会自动清零。运行 `.venv-win\Scripts\python.exe -m unittest tests.test_account_matrix_metrics -v` 可验证回填逻辑。
- 回滚：恢复 `backend/central_server.py` 和 `backend/matrix_native_client.py` 后重启中心服与本地客户端即可；已写入的 `publishRuntime` 字段是附加状态，旧代码会忽略。
## 2026-07-28 automation workflow file exists but "My workflows" is empty
- Symptom: admin has a saved workflow in `backend/datas/accounts/user-owner/workflows.json`, for example `丰田汽车宣传视频采集拆解并发送抖音`, but the current automation workflow page still shows no workflows.
- Root cause: startup loaded `backend/datas/workflows.json` before login/account scoping. After login, `apply_account_scope(acc)` switched `data_dir()` to `backend/datas/accounts/user-owner/`, but the in-memory `WORKFLOWS` list was not reloaded. `WorkflowPage.on_show()` only redrew the existing empty list.
- Fix: `backend/matrix_native_client.py#L10996-L11002` adds `reload_account_scoped_state()`; `backend/matrix_native_client.py#L22654-L22660` calls it immediately after account scope switching; `backend/matrix_native_client.py#L11708-L11716` makes the workflow page reload `workflows.json` before rendering and on refresh.
- Diagnostic check: confirm the workflow file exists at `backend/datas/accounts/user-owner/workflows.json`; then restart/re-login. The page should read the account-scoped file instead of the root `backend/datas/workflows.json`.
- Verification commands:
  - `py -3 -m unittest tests.test_workflow_account_scope -v`
  - `py -3 -m unittest tests.test_workflow_resilience -v`
  - `py -3 -m py_compile backend\matrix_native_client.py tests\test_workflow_account_scope.py tests\test_workflow_resilience.py`
- Rollback: revert `backend/matrix_native_client.py`, `tests/test_workflow_account_scope.py`, `tests/test_workflow_resilience.py`, and this document entry. No database migration or central API contract change is required.

## 2026-07-28 抖音私信全自动回复点击后没反应

- 现象：在“私信 / AI 销售”里填写客户主页链接后，点击“全自动回复”没有明显动作，状态栏提示“全自动收信暂不可用”“已检查，无新文本私信”，或后台浏览器反复弹出“登录后才可私信对方”。
- 根因：MVP 只支持指定客户主页链接的单客户私信会话轮询；旧版本没有接通 `douyin.dm.inbox` 本地浏览器任务，或者本地浏览器执行器未在线、应用内抖音登录态失效、客户主页没有可见“私信/发私信”入口、对方不可私信、消息为图片/语音/视频等非文本内容。注意：系统日常 Edge/Chrome 已登录不等于应用本地执行引擎的抖音登录态有效。
- 排查：先确认客户主页链接不是纯数字 uid，再确认本地执行器在线、抖音浏览器登录态有效；查看结构化日志 `douyin_dm_inbox_poll_started` / `douyin_dm_inbox_poll_finished`，用 `targetFingerprint` 关联客户会话；查看客户端日志 `douyin_dm_auto_reply_buffered`、`douyin_dm_auto_reply_manual_required`、`douyin_dm_auto_reply_failed`，用 `messageFingerprint` 和 `errorCode` 定位消息级问题。
- 处理：纯文本消息会先缓存，5 分钟窗口到达后合并成一次 AI 回复并直接发送；非文本消息固定进入人工查看，不自动发送。若出现 `not_authenticated`，客户端会自动关闭“全自动回复”，避免继续弹浏览器；请先在软件“账号中心 / 抖音登录”重新登录抖音，登录成功后再开启全自动。若出现 `dm_inbox_button_not_found`，客户端也会关闭全自动并提示人工查看，通常表示对方不可私信、主页链接不支持或页面结构变化。`dm_inbox_messages_not_found` 不会自动关闭，可继续轮询或改用半自动。
- 隐私边界：全自动收信由原生客户端直接调用本机 `127.0.0.1:9081/api/douyin/dm/inbox`，私信正文不通过中心服任务结果传递；中心服即使收到 `douyin.dm.inbox` 任务结果，也只持久化目标和正文指纹、消息数量、方向、类型和错误码。
- 回滚：回退 `backend/api_server.py`、`backend/local_browser_worker.py`、`backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_dm_auto_reply.py`、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可恢复旧的半自动私信行为；本次不涉及数据库迁移，`migration.sql` 为 no-op。
## 2026-07-28 小红书图文素材发布没有自动切图文、正文等于标题、标签为空
- 现象：素材发布里选择图文素材后点击“发布到小红书”，创作者中心提示“上传图文，请先切换到图片 tab”；手动切到上传图文后，正文被填成标题，标签没有填充。
- 根因：本地小红书发布器旧实现仍按视频发布流程执行，只打开创作者发布页并直接找上传控件，没有根据 `type=image_note` 先点击“上传图文/图片”入口；发布入口只把 `publishTitle` 传给发布器，没有把素材草稿里的 `body/tags` 用于页面填充；正文编辑器旧逻辑也复用了 `title`。
- 修复：`image_note` 发布会先切到小红书“上传图文”入口再上传图片；`run_publish()` 会把素材 `body/tags` 传给 `xhs_publish_material()`；发布器标题只填标题框，正文使用素材正文，标签优先填话题/标签输入框，找不到标签入口时把 `#标签` 追加到正文末尾兜底。
- 排查：重启本地客户端和本地执行引擎后重试。若仍提示需要切换 tab，说明运行中的执行节点仍是旧代码；若正文或标签仍不对，先检查素材发布列表中该素材是否为 `type=image_note`，且中心素材/本地素材里有 `body` 和 `tags` 字段。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v` 29/29 通过；`.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement -v` 51/51 通过；`py_compile` 通过，仅剩既有正则转义警告。
- 回滚：回滚 `backend/platform_adapters.py`、`backend/api_server.py`、`tests/test_native_publish.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。

## 2026-07-28 小红书图文同款正文模板味太重
- 现象：图文同款 AI 生成正文里反复出现“这组图文按真实体验整理”“这次把重点放在丰田汽车”“先收藏再对比”等句子，看起来像固定模板，不像自然小红书笔记。
- 根因：`copy_candidates()` 早期实现为了快速产出三套候选，使用了固定句式拼接业务名、地区、目标客户和卖点；这些句式会在不同素材之间重复，并可能产生“真实体验”这类不适合所有业务场景的表达。
- 修复：三套候选保留，但正文分别改为种草建议、避坑对比、本地咨询口吻；去掉上述固定话术，标签继续单独放在 `tags` 字段，正文不混入 `#标签`。
- 排查：如果界面仍显示旧句子，先确认是否在查看修改前已经生成的旧任务；旧任务 JSON 中的 `copyCandidates` 不会自动重写，需要重新点击“生成同款预览”。代码生效也需要重启本地客户端和本地执行引擎。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNotePreviewTests -v`，应通过 2 项；完整回归运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement -v`。
- 回滚：回滚 `backend/xhs_note_replacement.py`、`tests/test_xhs_note_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本条排障记录即可；不涉及数据库迁移、OpenAPI 或 `migration.sql`。
## 2026-07-28 workflow collected video enters publish queue by mistake
- Symptom: a workflow such as `collect -> vision -> library -> publish` downloads a platform video, then later steps either show `已入素材库 0/0` or try to treat collected material as publishable output. The expected product rule is that collected platform video is reference-only.
- Root cause: workflow execution only had one output bucket, `ctx["artifacts"]`, for generated assets. The collect step did not distinguish original platform downloads from newly generated workflow outputs, while library and publish logic only understood generated artifacts.
- Fix: `backend/matrix_native_client.py#L11755-L11774` splits downloaded platform files into video references and image thumbnails; `backend/matrix_native_client.py#L11816-L11858` writes only videos to `referenceArtifacts/collectedArtifacts` and cover images to `referenceThumbnails`; `backend/matrix_native_client.py#L12001-L12028` stores collected videos in the asset library under `category="采集参考视频"` with `thumbnail/preview` metadata; `backend/matrix_native_client.py#L12082-L12098` refuses to publish reference-only runs; `backend/matrix_native_client.py#L20202-L20293` adds an asset-library filter for `采集参考视频`.
- Expected behavior: if the workflow has no `video` step, publish should say `本次只有采集参考素材,未生成可发布视频,未入发布队列`. If the workflow should publish, add a `video` step to create a new generated video from the reference and script, then publish that generated video.
- Thumbnail behavior: if the platform download includes `cover.jpg` or similar image files, those images are stored only as the collected video asset's `thumbnail/preview` metadata. They should not appear as independent `采集参考视频` image assets.
- Verification commands:
  - `py -3 -m unittest tests.test_workflow_resilience -v`
  - `py -3 -m unittest tests.test_workflow_account_scope -v`
  - `py -3 -m unittest tests.test_asset_library_shared_button -v`
  - `py -3 -m py_compile backend\matrix_native_client.py tests\test_workflow_resilience.py`
- Rollback: revert `backend/matrix_native_client.py`, `tests/test_workflow_resilience.py`, and this documentation/changelog update. This change has no database migration, central API, OpenAPI, Docker, or `migration.sql` impact.

## 2026-07-28 workflow storyboard script not visible after run
- Symptom: a workflow run logs `视频理解失败,已兜底生成口播脚本(...)`, then the user cannot find the full detailed storyboard script in `wf_out` or the asset library.
- Root cause: `_exec_vision()` only kept the script in runtime `ctx["script"]`. If vision succeeded it appended `【分镜脚本】`; if vision failed it generated a fallback口播脚本. Neither path persisted the full text as a file, and `_exec_library()` intentionally only stores generated media and collected reference videos.
- Fix: `backend/matrix_native_client.py#L11656-L11691` adds `_workflow_save_script_artifact()` to save scripts as UTF-8 `.txt` files under `wf_out`; `backend/matrix_native_client.py#L11833-L11886` calls it from text/vision steps and logs the saved basename; `backend/matrix_native_client.py#L11907-L11912` also saves the video-step fallback script when the script was too short before generation.
- Expected behavior: if video understanding succeeds, the run log includes `已拆解详细分镜(...);已保存:<file>.txt`. If video understanding fails, the run log includes `已兜底生成口播脚本(...);已保存:<file>.txt`. The text file is in the account-scoped `wf_out` folder and is not added to the publish queue.
- Regression tests: `tests/test_workflow_resilience.py#L68-L118` covers saving fallback and successful storyboard scripts, and verifies text artifacts do not enter `ctx["artifacts"]`.
- Verification:
  - `py -3 -m unittest tests.test_workflow_resilience -v`
  - `py -3 -m py_compile backend\matrix_native_client.py tests\test_workflow_resilience.py`
- Rollback: revert `backend/matrix_native_client.py`, `tests/test_workflow_resilience.py`, `docs/IMPLEMENTATION.md`, `docs/TROUBLESHOOTING.md`, and `CHANGELOG.md`. No database migration, central API, OpenAPI, Docker, or `migration.sql` change is required.

## 2026-07-28 小红书图文同款保存草稿后资产库图文模板看不到
- Symptom: 图文同款页面点击“保存草稿”后，素材发布里能看到草稿，或本机保存接口返回成功，但 `资产库 -> 图文模板` 为空。
- Expected behavior: 保存成功后，本机应写入 `data_dir()/xhs_note_template_assets/note_template_<localMaterialId>.json`，并在本地资产库 `assets.json` 里新增 `kind="note_template"`、`source="图文同款"`、`category="图文模板"` 的记录。模板卡片使用第一张草稿图片作为缩略图。
- Root cause checklist: first confirm the draft material contains real saved image files under the account-scoped materials directory. If the image files are missing, local asset registration is skipped and the client structured log records `xhs_note_template_asset_register_failed` with `error="draft_files_not_found"`. If the JSON exists but asset library is empty, inspect `assets.json` for a `note_template` record and check for `error="asset_add_failed"`.
- Central sync boundary: central material upload failure records `xhs_note_draft_central_sync_failed`, but it does not by itself block local template asset registration as long as local draft image files exist. In that case the template JSON has an empty `centralMaterialId`.
- Recovery: restart the local client after code updates, save the draft again, then refresh `资产库 -> 图文模板`. Existing old drafts are not backfilled automatically; they need to be saved again or manually re-registered from their local material files.
- Verification commands:
  - `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_save_draft_registers_note_template_asset tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_save_draft_syncs_saved_material_to_central_library -v`
  - `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement -v`
  - `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_xhs_note_replacement.py`
- Rollback: revert `backend/matrix_native_client.py`, `tests/test_xhs_note_replacement.py`, `docs/IMPLEMENTATION.md`, `docs/TROUBLESHOOTING.md`, and `CHANGELOG.md`. This fix has no database migration, central API, OpenAPI, Docker, or `migration.sql` impact.

## 2026-07-28 小红书图文同款必填字段没有自动生成
- 现象：进入图文同款后，“标题（必填）”“所在地（必填）”“目标客户（必填）”为空；“卖点（可编辑）”可能直接取原文片段或原笔记标题，不符合“AI 生成后可编辑”的预期。
- 根因：旧页面只从原始正文按句子截取卖点，标题、所在地、目标客户不自动生成；原始正文为空时还会退回使用原笔记标题作为卖点。
- 修复：进入新笔记后异步调用 AI，根据原始标题、正文和标签生成四个业务字段；结果只填空字段，不覆盖用户已编辑内容。所在地判断不出来就保持空白，卖点会过滤原笔记标题和 `#标签`。
- 排查：如果字段没有自动出现，先确认本地客户端和本地执行引擎已重启、账号登录态和 AI 网关可用；查看客户端结构化日志 `xhs_note_business_prefill_failed`，其中只记录原文长度、标签数量和错误栈，不记录完整正文。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_collection_handoff_ai_prefills_editable_business_fields tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_collection_handoff_ai_leaves_unknown_region_blank -v`，应通过 2 项。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本条排障记录即可；不涉及数据库迁移、OpenAPI 或 `migration.sql`。

## 2026-07-29 小红书图文同款三套正文太短
- 现象：点击“生成同款预览”后，三套方案正文只有几十个字，信息量不够，发布到小红书像短说明而不是完整图文正文。
- 根因：`copy_candidates()` 早期正文模板只写一个短段，重点是快速表达卖点，没有展开使用场景、判断建议、到店沟通和对比逻辑。
- 修复：三套正文扩展为约 120-180 字的小红书段落，分别覆盖种草建议、避坑对比、本地咨询方向；正文继续不混入 `#标签`。
- 排查：旧任务 JSON 里的 `copyCandidates` 不会自动重写。如果界面仍是短正文，先重启本地客户端和本地执行引擎，再重新点击“生成同款预览”。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNotePreviewTests -v`，应通过 3 项；示例三套正文长度应大于 120 字。
- 回滚：回滚 `backend/xhs_note_replacement.py`、`tests/test_xhs_note_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和本条排障记录即可；不涉及数据库迁移、OpenAPI 或 `migration.sql`。

## 2026-07-28 抖音私信发送失败 `dm_input_not_found`
- 现象：在“私信 / AI 销售”里点击手动发送，或全自动回复触发发送后，页面显示 `发送失败:dm_input_not_found`。
- 根因：旧发送逻辑点击客户主页的私信按钮后固定等待 4 秒，只识别少数输入框类型。新版抖音私信编辑器可能更慢出现，也可能是 `role="textbox"`、`input` 或 `contenteditable="plaintext-only"`，导致页面已有输入框但程序判定为没找到。
- 修复：`browser_send_dm()` 改为最多等待 `DY_DM_EDITOR_WAIT_MS`，持续扫描更完整的编辑器候选；发送时先走 Playwright 填充，再用键盘和 DOM 兜底；找不到时记录结构化事件 `douyin_dm_send_editor_not_found`。
- 2026-07-29 追加修复：按真实页面形态处理客户主页右侧原页面私信浮层。点击“私信”后，程序会先点击底部“发送消息/输入消息”区域来激活聊天编辑器，再遍历当前页面所有 frame 查找输入框；填字、DOM 兜底和发送按钮点击都会在找到的 `editor_context` 内执行。
- 2026-07-29 追加修复：主页“私信”按钮优先使用用户实测 XPath，Edge 为 `//*[@id="user_detail_element"]/div/div[2]/div/div[1]/div[3]/div[2]/button[1]`，Chrome 为 `//*[@id="user_detail_element"]/div/div[2]/div/div[1]/div[3]/div[3]/div[1]/button[2]`；点击后必须确认右侧私信面板已打开，否则返回 `dm_panel_not_open`。
- 2026-07-29 登录态修复：私信发送前先从账号矩阵解析抖音账号 profile 和 `auth_cookie.json`，未找到有效登录 Cookie 时直接返回 `not_authenticated`，不会再弹出临时浏览器要求用户在里面登录。临时私信浏览器只从账号矩阵 profile 播种登录态；用户系统 Edge/Chrome 里登录过，不等于软件账号矩阵已经有可用 Cookie。
- 排查：如果仍失败，查看返回里的 `dmEditorDiagnostics.editorCandidateCount`。为 0 通常是私信面板没打开、应用内浏览器未登录、对方不能私信或抖音页面又变了；大于 0 且报 `dm_type_failed`，说明找到了输入框但页面拒绝填入。
- 新错误：`not_authenticated` 表示私信发送没有拿到账号矩阵里的抖音登录态。处理方式是在软件“账号矩阵”里重新登录抖音；不要在私信发送弹出的临时浏览器里登录，因为临时 profile 发送结束会被删除。
- 新错误：`dm_panel_not_open` 表示程序已经点击了私信按钮，但页面没有出现右侧私信面板。先看客户端提示里的“点击位置”，再检查浏览器是否弹出登录、验证码、私信限制、对方不可私信或页面拦截提示。
- 新诊断：如果状态栏显示“已点开私信，但没有识别到底部发送消息输入框”，继续看 `dmEditorDiagnostics.focusProbe.focusCandidateCount`、`frameIndex` 和 `frameUrl`。`focusCandidateCount=0` 通常说明底部输入区域没出现或不可点击；有候选但 `editorCandidateCount=0`，通常说明抖音只显示占位层，点击后仍没有生成真实编辑器。
- 隐私：诊断只包含候选输入框数量、页面标题、URL 和候选元素元信息，不写入要发送的私信正文。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v` 通过 42/42；`.\.venv-win\Scripts\python.exe -m py_compile backend\api_server.py backend\matrix_native_client.py tests\test_douyin_dm_auto_reply.py` 通过，仅剩既有正则转义警告。
- 回滚：回滚 `backend/api_server.py`、`tests/test_douyin_dm_auto_reply.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 小红书图文同款显示模板 ID 或方案编辑后未保存
- 现象：图文同款页面出现 `模板：tpl_* · 来源笔记：* · 图片槽位：N` 这类技术信息；或用户改了方案标题、正文、标签后点击“保存草稿”，素材发布里仍是 AI 原始方案。
- 根因：旧页面把模板 ID、来源笔记 ID 和图片槽位数量直接写入 `template_summary`；三套 `copyCandidates` 只在一个只读文本框中展示，保存时只传 `selectedCopyIndex`，本机保存接口仍按原始候选方案构建草稿。
- 修复：页面摘要改为业务提示，只显示需要替换的图片数量；三套方案改成可编辑标题、正文、标签，并在切换方案时缓存每套方案的编辑内容。保存草稿时客户端提交 `copyOverride`，本机接口写回当前选中的 `copyCandidates` 后再生成草稿素材。
- 排查：如果仍看到 `tpl_` 或来源笔记 ID，说明运行中的本地客户端没有加载新代码，先重启本地客户端。如果保存后仍是旧文案，检查本机请求体是否包含 `copyOverride`，并确认 `/api/xhs-note-replacement/save-draft` 处理时没有被旧执行引擎接管。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteSaveDraftApiTests.test_save_draft_applies_edited_copy_override tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_template_summary_hides_technical_ids tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_save_draft_sends_edited_selected_copy -v`，应通过 3 项；完整回归运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement -v`。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`tests/test_xhs_note_replacement.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。

## 2026-07-29 获客中心寻找线索按钮没有固定在表格中
- 现象：获客中心“寻找线索”结果表里的“打开主页 / 复制链接 / 去私信跟进 / 标记已跟进”按钮看起来被撑出单元格、跨列显示，或按钮只显示半截高度，文字被横线压住。
- 根因：旧实现只给按钮设置最小宽度，动作列使用 `ResizeToContents`。后续修补虽然改成了固定列和更高按钮，但仍没有处理全局 `QTableWidget::item { padding:8px; }`。该 padding 会把 cell widget 的实际区域从 44px 行高压到约 27px，高于该区域的按钮就会被底部裁掉；普通 `QPushButton/QToolButton` 还会带 Qt 原生按钮绘制边界，看起来更像偏右下。
- 修复：动作列 4-7 固定为 `112/112/140/140px`；按钮视觉宽度固定为 `92/92/118/118px`；结果行高固定为 54px，按钮高度固定为 32px；动作控件改用表格专用可点击 `QLabel#finderAction`，动作单元格内部二次留白改为 0，只保留表格自身 item padding。窄窗口下由表格横向滚动条处理，不再压缩按钮文字。
- 排查：如果仍看到旧布局，先重启本地客户端；确认运行代码里 `FinderPage` 包含 `FINDER_ACTION_COLUMN_WIDTHS = {4: 112, 5: 112, 6: 140, 7: 140}`、`FINDER_ACTION_BUTTON_HEIGHT = 32`、`FINDER_ROW_HEIGHT = 54`、`FINDER_ACTION_CELL_MARGIN_X = 0`，并且 `_action_button()` 使用 `QtWidgets.QLabel(text)`。如果窗口特别窄，出现横向滚动条是正常行为。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_finder_page_actions -v`，应通过 7 项；再运行 `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_finder_page_actions.py`。本地离屏截图几何应显示 cell widget 高约 37px、动作标签高约 34px，不再是 27px 容器裁 34px 控件。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_finder_page_actions.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。

## 2026-07-29 抖音私信发送内容被当成搜索词
- 现象：从获客中心点击“去私信跟进”后，在“私信 / AI 销售”里发送消息，浏览器打开目标用户页面，但输入的回复内容进入了抖音搜索框，最后显示 `dm_send_not_confirmed` 或搜索了该文本。
- 根因：“去私信跟进”只负责带入客户主页链接，真正发送由本机浏览器执行。旧发送逻辑的输入框识别过宽，可能把抖音顶部搜索框或已聚焦的导航输入框当成私信编辑器；随后按 Enter 就触发搜索，而不是发送私信。
- 修复：私信编辑器扫描现在会排除 `search/搜索` 输入框和顶部导航文本框，并优先选择聊天区域下半部分的编辑器；输入完成后优先点击编辑器附近的“发送”按钮。如果只命中 `INPUT` 但找不到私信发送按钮，会返回 `dm_send_button_not_found`，不再继续按 Enter 搜索。
- 排查：如果仍失败，查看返回中的 `dmEditorDiagnostics.searchBoxRejected` 和 `dmSendDiagnostics.buttonCandidates`。`searchBoxRejected > 0` 说明搜索框已被排除；`dm_send_button_not_found` 说明没有找到私信窗口内的发送按钮，通常是私信会话未打开、对方不可私信、账号权限/登录态异常或抖音页面结构变化。若状态显示 `dm_child_failed`，客户端会附带 `returncode`，后端结果还会带 `stderrTail/stdoutTail`；若返回 `dm_child_inner_exception`，客户端会显示后台浏览器异常摘要，后端结果可继续查看 `exceptionType/message/stackTail`，用于判断是后台浏览器启动失败、登录态/profile 失败还是页面脚本异常。
- 隐私：诊断只记录输入框/按钮候选元信息、页面标题和 URL，不记录要发送的私信正文。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v`，应通过 30 项；再运行 `.\.venv-win\Scripts\python.exe -m py_compile backend\api_server.py backend\matrix_native_client.py tests\test_douyin_dm_auto_reply.py`。
- 回滚：回滚 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_dm_auto_reply.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。
## 2026-07-29 小红书安全模式拦截后无法继续采集、评论或发布

- 现象：小红书搜索、下载、读取评论、发表评论或发布图文时返回 `xhs_safety_interval`、`xhs_safety_publish_limit`、`xhs_safety_comment_limit` 或 `xhs_safety_paused`；风控中心显示今日发布/评论已达上限、冷却未结束，或账号为高风险。
- 根因：安全模式会在执行前读取 `risk_config.json` 的每日发布上限、每日评论上限和最小间隔，并读取 `xhs_safety_state.json` 的当天账号状态。命中上限、冷却未结束或平台已触发验证码/IP 风险/安全验证时，系统会阻断后续自动操作。
- 排查：先到“风控中心”查看对应账号的“今日发布 / 今日评论 / 冷却 / 最近风险”；再查看本地账号数据目录下的 `xhs_safety_state.json`。如果 `paused=true` 或 `lastRisk` 有 300012、300031、验证码、安全验证、`xhs_creator_login_required` 等信息，应先人工登录小红书处理平台提示，不要继续自动化。
- 处理：正常命中上限时，降低当天操作量或等到次日再执行；命中冷却时等待冷却结束；命中平台风险时暂停该账号的采集、评论和发布，确认网络环境、登录状态、账号通知和平台违规提示。
- 可观测：接口拦截会返回 `safety` 快照，包含账号、日期、已用次数、上限、冷却剩余时间和暂停原因。风险命中后状态落盘到 `xhs_safety_state.json`，便于重启后追溯。
- 回滚：如果需要临时恢复旧行为，可设置 `XHS_SAFETY_MODE=0` 并重启本地客户端和本地执行引擎。代码级回滚恢复 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_xhs_safety_mode.py`、`tests/test_api_download_contract.py` 和本次文档；没有数据库迁移、OpenAPI 新接口或 Docker 变更。
## 2026-07-29 备用模型视频台词含混或变成模型原声

- 症状：分镜 TTS 文件本身清楚，但 Vidu 等备用模型生成的视频中台词含混，且旧的自动音频质检仍可能显示通过。
- 根因：Seedance 拒绝后，`_comic_video_fallback_params()` 会按设计删除备用模型不支持的音频和口型参数；备用模型完成后，旧链路直接把其视频 URL 写回分镜，因此成品保留了模型自带 AAC 音轨。原质检只检查是否存在音轨和平均音量，无法证明台词与口播稿一致。
- 修复：备用模型只提供画面。服务端在结果写回前从 `fallback_source_params` 恢复分镜 TTS，用 FFmpeg 明确映射 `0:v:0` 与 `1:a:0` 生成新文件，不映射 `0:a:0`。视频不足时冻结尾帧，TTS 不足时补静音，任何混音或校验失败都阻止任务成功；结果使用 `/data/uploads/` 账号隔离媒体路由。
- 观测：成功事件为 `comic_storyboard_fallback_tts_mix_completed`，失败事件为 `comic_storyboard_fallback_tts_mix_failed`；任务响应包含 `audioSource`、`audioMixStatus`、`providerResultUrl` 和时长字段。日志不包含音频 URL 或密钥。
- 验证：专项回归通过 13/13，`.venv-win` 相关漫剧/同款替换回归通过 57/57；真实 FFmpeg 冒烟输出时长 5.0 秒且存在音轨。项目 299 片段 2 的远程文件经 `ffprobe` 确认为 H.264 + AAC、17.584 秒，任务和分镜均指向新文件；未登录媒体请求返回 401，带真实页面会话的播放仍需由客户端会话验证。
- 回滚：恢复部署前 `server.py` 备份并重启 `ai-canvas.service`。回滚后会恢复备用模型原声行为；本地客户端不需要重启。

## 2026-07-29 远程视频完成但本地 401

- 现象：远程任务和结果地址已经完成，但片段显示“远程视频已生成，本地获取失败”，状态为 `download_failed`；旧版本可能同时把 `videoUrl` 显示为链接，并把下载失败误报成模型生成失败。
- 原始根因：`/data/uploads/comic-drama/` 等同源媒体受漫剧会话保护。旧客户端在写入 `videoUrl` 后调用不带 Authorization 的通用下载器，服务端因此返回 HTTP 401。远程模型、备用模型或 TTS 已成功，401 发生在本地取回阶段。
- 当前处理：同源受保护媒体统一通过 `ComicProjectAdapter.download_media()`，请求携带当前 Bearer Token；第一次 401 会清空本地漫剧凭证、重新登录一次并重试一次，第二次仍为 401 时停止，禁止无限刷新。外部 CDN 不携带该 Token。
- 诊断：先检查片段 `comicVideoResult.status` 是否为 `completed/success/done/succeeded`，以及是否存在 `pendingComicVideoRecovery.taskId/videoUrl`。若远程已完成而 `videoPath` 缺失，属于下载或校验故障，不要重新提交模型。结构化日志应能看到 `comic_media_download_retry` 或 `comic_media_download_failed`、HTTP 401、主机和文件名，但不应出现 Token、完整 Authorization、完整 URL 或敏感查询参数。
- 恢复：确认漫剧账号仍可登录后点击“重试失败片段”。对有效 `pendingComicVideoRecovery`，客户端只重新鉴权下载、校验并原子落盘，不更新分镜、不提交生成任务、不再次扣费；恢复成功后清除 pending 并进入 `done`。若缺少首帧或尾帧，该片段会被跳过并提示先单独重生成缺失帧，其他完整片段继续处理。
- 媒体校验：即使 HTTP 200，也必须确认下载结果具有有效视频流、音频流和时长并能完整解码；HTML/JSON 错误页、截断文件或无效媒体同样保持 `download_failed`。失败时删除 `.part`，保留上一版可用媒体和最新 `errorId`。
- 验证：专项回归覆盖鉴权下载、401 仅刷新一次、外部 CDN 不带 Bearer、`download_failed` 状态、pending 仅下载恢复且不重提/不扣费，以及最终合成拒绝 `video_stale` 或无效本地片段。
- 回滚：本地恢复上一稳定版客户端；远程恢复当次发布前 `server.py` 备份并重启 `ai-canvas.service`。保留任务 JSON、`retryHistory`、pending 恢复点和已生成媒体。本次无数据库 Schema 变化，不执行 `migration.sql`。
## 2026-07-29 同款替换女生参考图生成成长发男生
- 现象：原视频主角是男销售，用户上传女生角色参考图后，漫剧生成器的视频虽然参考了首尾帧，但人物融合成“长头发的男生”。
- 根因：本地客户端把原片分解出的“男销售、白衬衫、黑领带、眼镜、短发”等源视频人物外观词继续写入漫剧 `source_text/storyboards/video_prompt`。远程模型面对“女生参考图”和“男销售文字提示”冲突时会做融合。
- 修复：`backend/matrix_native_client.py#L9568-L9713` 在检测到上传人物参考图后，清洗原片人物性别、发型、脸、服装、体型和配饰词，只保留动作、站位、镜头关系和汽车销售职业语境，并在每个分镜画面提示里追加“人物完整外观以上传角色参考图为准；文字描述与角色参考图冲突时，以角色参考图为准”。
- 排查：新任务生成前可检查本地 `replacement_job.json` 或漫剧项目 `source_text`，确认画面提示词里不再出现原片人物外观词，也不再出现 `...(truncated)`。旧任务不会自动重写，需重新生成替换方案或重新执行同款替换。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_person_reference_overrides_source_person_appearance -v` 应通过；更完整的漫剧 payload 回归见 `docs/IMPLEMENTATION.md` 同日记录。
- 回滚：回退 `backend/matrix_native_client.py`、`tests/test_video_replacement.py` 和本条文档即可；不涉及中心服、数据库迁移、OpenAPI、Docker 或 `migration.sql`。
## 2026-07-29 抖音私信发送失败 `dm_child_failed returncode=0`
- 现象：在“私信 / AI 销售”手动发送或全自动回复发送时，客户端状态栏显示 `发送失败:后台浏览器进程失败:dm_child_failed returncode=0`。
- 根因：`returncode=0` 说明子进程正常退出；真正问题是父进程没有收到私信发送子进程应输出的 `__MATRIX_DM_JSON__` 结果标记。打包 Windows 客户端里 `sys.executable` 可能是 `MatrixShipAgent.exe`，不是 Python 解释器；用它执行 `-c` 脚本会正常退出但不产生 JSON 标记。
- 修复：本地客户端启动默认设置 `DY_DM_ISOLATED=0`，和搜索逻辑一样不再用冻结 exe 启动隔离 Python 子进程；后端也会先检查 `_python_c_child_cmd()`，只有确认为 Python 解释器时才走隔离子进程。无结果标记时返回 `dm_child_no_json_marker`，客户端会提示“后台浏览器未返回发送结果”。
- 处理：更新代码后必须重启本地客户端和本地执行器；旧进程仍保留旧环境变量，会继续报 `dm_child_failed returncode=0`。如果仍失败，再看新的错误码：`dm_button_not_found` 多半是主页没有私信入口，`dm_input_not_found` 是私信面板输入框未出现，`dm_send_button_not_found` 是找不到发送按钮。
- 验证：运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v` 应通过 32 项；再运行 `.\.venv-win\Scripts\python.exe -m py_compile backend\api_server.py backend\matrix_native_client.py tests\test_douyin_dm_auto_reply.py`。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`tests/test_douyin_dm_auto_reply.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。
## 2026-07-29 单帧重生失败后旧视频不可播放 / OpenAPI 成功响应不兼容

- 现象：单独重生首帧或尾帧失败后，片段仍保留有效 `videoPath`，但视频列优先显示失败；同时 `action_flow` 实际只返回 `data.task_id`，OpenAPI 却要求 `task_id` 和 `task_ids` 同时存在。
- 根因：播放器状态函数在本地媒体校验前提前返回失败；成功响应 Schema 把多任务列表误设为所有工作流必填。
- 修复：生成中和下载中仍显示实时状态；失败状态若存在校验通过的旧本地视频则继续播放，只有无可用本地视频时显示错误编号。OpenAPI 只强制 `data.task_id`，`task_ids` 保持为双帧/多帧可选字段。
- 验证：新增两项回归先分别因返回 `failure` 和响应 Schema 过严而失败；最小修复后两项通过，并纳入完整 375 项计划门禁。
- 回滚：恢复 `backend/matrix_native_client.py`、`docs/openapi.yaml`、`tests/test_video_replacement_v2.py`、`tests/test_openapi_contract.py` 及关联文档。无数据库迁移；远程服务部署失败时使用同批次 `server.py.bak.comic-inline-media-*` 备份回滚。

## 2026-07-30 账单领域 Phase 0 冒烟

- RED 证据：在创建 `backend/billing_analytics.py` 前执行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_billing_analytics -v`，测试模块导入失败并报告 `ModuleNotFoundError: No module named 'billing_analytics'`。这是预期的缺失领域模块失败，虚拟环境中的 `jsonschema` 可正常导入，不是依赖或测试路径错误。
- 非有限金额边界：`Decimal(str(value))` 会接受 `Infinity`、`NaN` 和浮点无穷，旧实现会把它们转换为 schema 可接受的非有限 number。`_amount()` 现在用 `Decimal.is_finite()` 拒绝这些值并抛出 `ValueError("invalid billing amount")`；只有 `build_billing_analytics()` 余额分支接收的精确字符串 `"inf"` 会保留为无限余额。拒绝发生在响应 schema 校验和 JSON 序列化之前。
- GREEN 证据：当前同一命令通过 12/12，包含精确 `"inf"` 接受以及 `"Infinity"`、`Decimal("Infinity")`、`float("inf")`、NaN 和负无穷拒绝回归；`.\.venv-win\Scripts\python.exe scripts\smoke_billing_dashboard.py` 输出唯一 JSON 行且顶层为 `{"ok": true}`，覆盖视频、图片、配音、充值和退款，并验证 analytics 与 ledger 运行时 schemas；`py_compile` 对领域模块、脚本和测试退出码为 0。
- 依赖确认：目标 `.venv-win` 中 `importlib.metadata.version('jsonschema')` 输出 `4.23.0`，`backend/requirements.txt` 和 `backend/requirements.deploy.txt` 使用相同精确锁定。
- 回滚：此任务是纯领域代码，未启动、停止或部署任何服务；按 IMPLEMENTATION 索引移除 Task 1 文件和两处依赖锁定即可。

## 2026-07-30 原生账户中心账单看板刷新或离屏截图异常

- 现象：快速切换日期、按日/按月、明细类型或分页后，旧请求可能晚于新请求返回；网络/格式错误时如果直接清空会丢失上次可用数据。Qt offscreen 首次截图还可能把全部中文和数字显示为方框。
- 请求排查：查看客户端 JSON 日志中的 `billing_analytics_request_started/completed/failed`、`billing_ledger_request_started/completed/failed` 和 `billing_*_stale_response_dropped`。同一请求类型只接受等于当前序列号的响应；错误提示必须包含可重试文案和 `errorId`，且指标、图表或表格仍保留上次成功内容。日志只记录日期、分组、页码、行数、错误码和错误编号，不记录 Token、请求头、手机号或完整媒体 URL。
- 显示排查：analytics 余额的精确字符串 `"inf"` 应显示 `∞ 运营方`；旧实时余额路径的浮点无穷保持同样显示；明细 `balanceAfter=null` 应显示 `—`。类型分布无数据时仍必须保留视频生成、图片生成、配音、其他四行。
- 离屏字体根因：当前 offscreen 插件可能返回空的 `QFontDatabase.families()`，即使 `C:\Windows\Fonts` 已安装中文字体。冒烟脚本显式加载 `C:\Windows\Fonts\Deng.ttf` 并设置 `DengXian` 为默认字体；这只用于可复现截图，不改变正式客户端字体策略。若字体文件缺失，脚本会明确失败而不是保存不可读证据。
- 验证：设置 `QT_QPA_PLATFORM=offscreen` 后运行 `scripts/smoke_account_billing_ui.py`，应输出 `ok` 并保存 1280x900、1024x768 两张非空 PNG；再运行 `python -m unittest tests.test_account_billing_dashboard tests.test_role_permissions tests.test_native_billing_rates -v`，应通过 26 项。两张图需人工确认四指标、筛选器、趋势标签、四条分布、七列表格和分页均无重叠或裁切。
- 回滚：回滚 `backend/matrix_native_client.py` 的 Task 5 hunks，移除专项测试、离屏冒烟、截图、Task 5 文档与报告即可。无需迁移或重启中心服/本地客户端；保留当前中心 API/OpenAPI。若后续客户端发布错误率超过 1%，按发布流程恢复上一稳定客户端包或镜像 Tag。
## 2026-07-30 任务中心为空但内容采集/获客/发布已执行
- 现象：在本地客户端执行内容采集、寻找线索、AI 触达、工作流采集/下载或素材发布后，任务中心没有任何记录；企业中心任务趋势也可能仍显示默认展示值。
- 根因：这些操作通过中心服的 `localBrowserTasks` 派发给本地客户端浏览器执行，但旧任务中心只读取中心节点任务 `STATE["tasks"]` 和发布队列，未合并 `localBrowserTasks`。
- 修复：任务中心、企业用量、企业概览和 `/api/central/tasks` 现在都会把本地客户端任务归一化后一起展示；离线导致无法创建执行任务时，也会写入一条 `local_browser_offline` 失败任务。
- 排查：进入任务中心点“刷新”。如果看到失败任务且原因为本地客户端离线，先确认本地客户端和本地执行引擎已启动、账号矩阵对应平台账号登录态有效；如果任务状态为失败但不是离线，按错误原因处理账号授权、平台风控或素材问题。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_enterprise_task_center_local_browser tests.test_role_permissions -v` 通过 17 项；`.\.venv-win\Scripts\python.exe -m py_compile backend\central_server.py backend\matrix_native_client.py tests\test_enterprise_task_center_local_browser.py` 通过。
- 回滚：回退 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_enterprise_task_center_local_browser.py`、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md`。无数据库迁移、Docker、OpenAPI 新接口或 `migration.sql` 变更。

## 2026-07-30 开启抖音全自动回复后浏览器反复要求登录
- 现象：账号矩阵已有在线抖音账号，手动私信也可以发送，但开启“全自动回复”后，每隔约 20 秒弹出的浏览器仍要求登录，随后全自动被关闭。
- 根因：手动发送和自动收件原本是两条浏览器链路。手动发送已按账号矩阵解析 profile 并注入 Cookie；自动收件请求没有传 `accountId`，本地执行引擎固定使用通用 `dy_dm_profile/current`，且只从默认 profile 播种文件、没有注入账号 Cookie，因此账号矩阵登录态没有进入轮询浏览器。
- 修复：从获客中心进入私信页时带入所选抖音账号；全自动收件与回复发送统一携带该账号。收件浏览器按账号矩阵解析 profile、播种稳定目录并在访问主页前注入 Cookie；直接进入私信页时由本地执行引擎选择最新可用抖音账号。
- 排查：查看 `/api/douyin/dm/inbox` 响应中的 `accountId` 和 `dmCookieInjection.attemptedCount/addedCount`。`not_authenticated` 或尝试数为 0 表示账号矩阵 Cookie 已失效，应在“账号矩阵”重新登录抖音；不要在自动回复弹出的浏览器里临时登录。日志不包含 Cookie 值或私信正文。
- 验证：私信专项 54/54、获客页面 9/9、OpenAPI 契约 5/5 通过，相关 Python 文件语法检查通过。真实浏览器冒烟应确认不再出现登录二维码/登录墙；若页面无消息，`dm_inbox_messages_not_found` 是合法的页面提取结果，不等同于登录失败。
- 回滚：恢复 `backend/matrix_native_client.py`、`backend/api_server.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`tests/test_douyin_dm_auto_reply.py`、`tests/test_openapi_contract.py`、`CHANGELOG.md` 和本条文档，重启本地客户端与执行引擎。无数据库、Docker 或 SQL 迁移，`migration.sql` 保持 no-op。
