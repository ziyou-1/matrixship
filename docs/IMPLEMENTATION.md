## 2026-08-10 修复 wan2.7-cankaosheng 参考图/参考视频字段名
- `backend/matrix_native_client.py#L2712-L2716`：`_AGENT_VIDEO_MEDIA_REQUIREMENT_OVERRIDES["wan2.7-cankaosheng"]` 的 `video_field` 由 `video` 改为真实字段 `reference_video`。
- `backend/matrix_native_client.py#L3039-L3047`：`_agent_video_payload()` 为 `wan2.7-cankaosheng` 增加精确分支——参考图写 `reference_urls`、参考视频写 `reference_video`，直接 return，不再走通用别名块（此前误写 `images/image_urls/reference_images` 和 `video`，模型收不到参考素材、退化为纯文生视频）。
- `tests/test_agent_video_duration.py#L553-L558`、`#L753-L756`、`#L874-L878`：修正三处与实现同源、把该模型字段锁成 `images`/`video` 的旧断言，改按实测 `reference_urls`/`reference_video`。
- 验证与影响：`tests.test_agent_video_duration`、`tests.test_agent_regen_keeps_params` 全绿、`py_compile` 通过；仅影响该模型 payload，不改中心服 API、OpenAPI、数据库、Docker、密钥或 `migration.sql`。退出后 `start-visible-client.bat` 重启生效。来源:并行分支 `claude/agent-model-params-ui-e46b0b`（已 -s ours 记录合并）中唯一目标分支尚缺的修复。

## 2026-08-08 内容采集页恢复图文同款按钮
- `backend/matrix_native_client.py` `ContentPage.__init__`：在"下载"和"分解"之间重新创建 `self.b_note_replace = QtWidgets.QPushButton("图文同款")` 并 `addWidget`；恢复 `note_replace()` 方法（校验小红书链接→下载→emit `c_note_replace`）。
- `_set_xhs_retry_busy` 和 `c_note_replace` 结果处理器改为对 `b_note_replace` 做 `setEnabled`（此前删按钮后只操作 `b_dl`）。孤儿处理器 `c_note_replace`（解析图片素材→跳转"🧩 图文同款"页）本来就在，现在重新接上按钮。
- 背景：`5e3c052`（2026-08-03）有意删除该按钮，但小红书大部分是图文笔记，"分解"只处理视频，图文笔记因此在内容采集页无出口，点分解报"未找到可分析的视频文件"。按用户要求恢复。
- `tests/test_xhs_note_replacement.py`：`test_content_page_hides_note_replacement_button`→`test_content_page_shows_note_replacement_button`；`test_native_collection_hides_note_replace_button_but_keeps_handoff_handler`→`test_native_collection_has_note_replace_button_and_handoff_handler`。
- 验证与影响：`tests.test_xhs_note_replacement` 62/62，相邻套件 177/177，`py_compile` 通过。仅本地客户端 UI，不涉及中心服 API、OpenAPI、数据库、Docker 镜像结构或 `migration.sql`。

## 2026-08-08 小红书安全间隔按动作类型分别计冷却
- `backend/api_server.py` `_xhs_safety_usage()` 新增 `lastActionAtBy` dict；`xhs_safety_record()` 除了写全局 `lastActionAt`（保留给展示/兼容），额外写 `lastActionAtBy[action]=ts`。
- `_xhs_safety_snapshot()` 新增 `action` 形参：传入时用 `lastActionAtBy[action]` 算 `cooldownLeft`，为空时回退全局 `lastActionAt`（兼容旧调用）。`xhs_safety_preflight()` 和 `xhs_safety_record()` 的 snapshot 调用都带上 `action`。
- 根因：旧实现全账号共享一个 `lastActionAt`，`search` 的 `xhs_safety_record("search")` 写的时间戳会让 `download` 的 `xhs_collection_account_gate("download")→xhs_safety_preflight("download")` 在 `minInterval` 默认 45s 内命中 `cooldownLeft>0` → `xhs_safety_interval`。
- `tests/test_xhs_safety_mode.py`：新增 `test_search_does_not_block_immediate_download`、`test_min_interval_still_throttles_repeated_download`，替换固化错误行为的 `test_min_interval_blocks_xhs_download_endpoint`。
- 边界：平台风险暂停 `xhs_safety_paused` 仍为全局；douyin 评论冷却是独立函数（`minIntervalCooldownLeft`），不受影响。旧状态文件无 `lastActionAtBy` 时读取补空 dict。
- 验证与影响：`tests.test_xhs_safety_mode` 7/7，相邻套件除 1 条环境性 `playwright` 缺失外全过，`py_compile` 通过。不涉及中心服 API、OpenAPI、数据库、Docker 镜像结构或 `migration.sql`。

## 2026-08-08 小红书登录成功写入就绪 marker
- `backend/api_server.py` `run_xhs_login()` 登录成功分支新增 `_save_json(DATA_DIR/xhs_auth_state.json, {loggedIn, cookieCount, profileDir, savedAt})`，与云登录路径 `_read_login_state()` 写 marker 的行为对齐。
- 根因：`platform_adapters.xhs_login()` 的登录判定接受强 cookie `XHS_STRONG_LOGIN_COOKIES` 或 DOM 登录态；而就绪判定 `xhs_profile_ready()` 无 marker 时只调 `_xhs_profile_has_login_cookie()` 找强 cookie。DOM/主站 `web_session` 登录成功但缺强 cookie 时两者分歧，`current_accounts()` 不返回 xhs 行，卡片显示 0 个授权账号。
- `tests/test_xhs_account_online_status.py`：mock `xhs_login` 返回 `logged_in=True` 但 profile 无强 cookie、无 marker，先断言就绪为假/账号 0（复现），修复后断言就绪为真/账号 1。测点选在 `run_xhs_login` 接缝，不需要 playwright。
- 运行现场：排查时 9080/9081 由 codex-runtime 老客户端占用，其 agent token 与 `backend/datas/agent_token.txt` 不一致，无法直接读其账号列表；故用代码级接缝复现，与具体运行实例解耦。
- 验证与影响：`tests.test_xhs_account_online_status` 5/5，相邻套件合计 193/193，`py_compile` 通过。不涉及中心服 API、OpenAPI、数据库、Docker 镜像结构或 `migration.sql`。

## 2026-08-08 中心服小红书恢复开关接线
- `backend/central_server.py#L161-L172`：新增 `_xhs_route_blocked()`，`xhs_enabled()` 为真时返回 `None`，否则复用 `_xhs_disabled()` 生成脱敏的 `platform_disabled` 结果。原 `_xhs_disabled()` 里的 `_ = XHS_ENABLED_ENV` 只是空引用，不构成任何判断。
- `backend/central_server.py` 三个闸门改为先取 `_xhs_route_blocked()` 再决定是否 404：`create_task()`（`/api/xhs*` 与 `payload_uses_xhs()`）、`local_browser_create_task()`（`xhs.*` 任务类型）、POST 分发器（路径与 payload 双重判断）。
- 同文件 `sync_node_accounts_locked()`、账号资产过滤和 `local_browser_upsert_account()` 早已正确调用 `xhs_enabled()`，此次只补齐漏掉的三处路由闸门。
- `LOCAL_BROWSER_ALLOWED_TYPES` 仍由 `filter_xhs_capabilities()` 在 import 期计算，开关需在中心服启动前设置，符合既有「重启三个运行单元」的操作契约。
- `tests/test_xhs_platform_disable.py`：新增 `test_central_restores_xhs_task_routing_when_flag_is_set`、`test_central_local_browser_channel_accepts_xhs_task_when_flag_is_set` 覆盖「打开后放行」方向；`test_local_browser_xhs_task_type_is_disabled` 由源码字符串 grep 改为真正调用 `local_browser_create_task()` 断言 404。旧测试只覆盖关闭方向，是本 bug 长期未被发现的直接原因。
- 验证与影响：`tests.test_xhs_platform_disable` 13/13，相邻套件合计 162/162，`py_compile` 通过；未设开关时中心服仍返回 404 `platform_disabled`，已单独验证。不涉及 OpenAPI 路径、JSON Schema、数据库、Docker 镜像结构或 `migration.sql`。

## 2026-08-08 小红书账号在线状态补齐
- `backend/api_server.py#L1218-L1235`：`current_accounts()` 的小红书行补写 `online: True` / `status: 'online'` / `needLogin: False`。该分支入口条件是 `xhs_enabled() and xhs_profile_ready(DATA_DIR)`，本机登录态失效时整行不返回，因此置为在线不会误报。
- 回归来源 `backend/matrix_native_client.py` 的 `submit_account_login_direct()`（2026-08-03 引入）：账号矩阵登录直连本机执行器，不再经中心服本地浏览器任务通道，`backend/central_server.py` 的 `local_browser_upsert_account()` 因此不再被触发。
- 受影响的消费点：`merge_account_sources()` 合并时 `online` 回落到中心服记录；账号矩阵徽标渲染；`clean_accounts(ready_only=True)` 过滤发布/采集账号下拉；`account_option_label()` 标注“登录态失效”。
- `tests/test_xhs_account_online_status.py`：跨 `api_server` 与 `matrix_native_client` 的回归，覆盖本地执行器字段、账号矩阵徽标为“在线”、发布/采集下拉保留该账号，以及本机登录态消失后不再显示账号的对照项。只测其中一端会漏掉本 bug。
- 验证与影响：`tests.test_xhs_account_online_status` 4/4，相邻套件通过，`py_compile` 通过。只改本地执行器账号列表和新增测试，不涉及中心服 API、OpenAPI、数据库、Docker、密钥配置或 `migration.sql`。重启本地客户端和本地执行器生效；回滚 `backend/api_server.py`、`tests/test_xhs_account_online_status.py`、`CHANGELOG.md`、本条记录和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-08-08 同款替换 / 图文同款换位台账布局
- 定位方式说明：`docs/IMPLEMENTATION.md` 存在广播式重复（同一 `#L` 引用最多重复 67 次，`matrix_native_client.py#L4733-L4804` 等），行号引用整体不可信，故本条只用符号名定位，不写行号。
- `backend/matrix_native_client.py` `THEMES`：dark / light 各新增换位台账状态色 `stKeep`/`stSwap`/`stOwe`/`stDone`/`stFail`，以及禁用态与勾选框 token `disBg`/`disBorder`/`checkBg`/`checkBorder`/`checkDisBg`/`checkDisBorder`。亮色下状态色统一压深以保证白卡上的对比度。
- `backend/matrix_native_client.py` `build_qss()`：新增统一字阶与分区样式（`#eyebrow` 10.5/800、`#zoneTitle` 13.5/750、`#fieldValue` 12.5/600、`#meta` 11/500、`#slotIndex` 等宽数字），新增 `#zone`/`#readyBar`/`#hline`/`#quiet` 与 `QProgressBar` 样式；`QPushButton:disabled`、`QLineEdit:disabled` 系列与 `QCheckBox::indicator` 改为读取上述 token；补充 `QScrollBar:horizontal`。
- `backend/matrix_native_client.py` 新增共用构件：`_state_color()`/`_style_state_pill()`/`state_pill()`、`zone_card()`、`field_label()`/`field_grid()`/`button_cell()`、`SwapRail`（横向连接线，QPainter）、`SwapSlotRow`（竖向状态脊线）、`ReadyBar`（行动条 + 还差什么）。
- `backend/matrix_native_client.py` `XhsNoteReplacementPage.__init__`：重排为 原片 / 你的信息 / 换位台账 / 行动条 / 生成结果 五个分区；两条缩略图带共用列距并通过 `_on_swap_scrolled()` 联动滚动，中间插入 `SwapRail`；新增 `_sync_swap_state()` 汇总缺图与必填项，并在 `_render_replacement_slots()`、`_fill_replacement_paths()`、`_start_from_collection()` 调用。
- `backend/matrix_native_client.py` `VideoReplacementPage.__init__`：重排为 原片 / 替换素材 / 声音与模型 / 行动条 / 生成 / 审核 / 核对 七个分区；人物、产品、场景各为一条 `SwapSlotRow`；新增 `_sync_swap_ledger()`，并在 `pick_products()`/`pick_face()`/`pick_scene()`/`pick_replacement_audio()`/`_sync_person_controls()`/`load_source()`、方案就绪与虚拟模特就绪分支调用。
- 未改动任何构件的构造语句文本（`self.b_face`、`self.face_authorized`、`self.person_full_body`、`self.b_virtual`、`self.b_retry_failed`、`self.no_person_mode` 等），仅改变其所属布局，以满足既有的源码子串断言。未新增任何非空 tooltip，说明文字一律改为页面内可见的 hint / meta 行。
- 遗留问题（本次未处理，需单独决定）：本次改动使 `matrix_native_client.py` 净增约 504 行，`docs/IMPLEMENTATION.md` 中指向该文件的 `#L` 引用共 1017 处（去重后 808 处），其中 533 处因本次改动整体下移，另有 144 处在本次改动前即已失准。考虑到该文档存在 67 倍广播式重复、且主目录同一文件另有大量未提交改动，未对这些行号做批量重写。
- 验证与影响：全量 `unittest` 1367 项无新增失败（2 项 error 为环境缺失 `playwright` 与 `backend/.env.dev`，已在干净树复现）；`py_compile` 通过；暗色 / 亮色双主题离屏截图核对。纯本地客户端展示层，不改中心服 API、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧界面。

## 2026-08-07 下载失败的成品可恢复
- `backend/matrix_native_client.py`(`_PRODGEN_RUNTIME_KEYS`):新增 `pendingDownloadRecovery`。`regen` 是黑名单复制,不加会把上一条的结果 URL 带进新条目。
- `backend/matrix_native_client.py`(`_prodgen_entry_by_id` / `_prodgen_download_recovery` / `_prodgen_download_error_text`):按 id 取条目、判定是否可恢复(必须有 `resultUrl`)、把网络错误翻成不含 host 与 SSL 栈的中文文案(403 引导「重新生成」而非「恢复下载」)。
- `backend/matrix_native_client.py`(`_prodgen_remember_result`):下载前写入 `pendingDownloadRecovery = {status, createdAt, taskId, resultUrl, model, mode, targets, downloadAttempts, lastError}`。字段名与漫剧的 `pendingComicVideoRecovery` 同构,便于日后合并。
- `backend/matrix_native_client.py`(`lk888_media_task`):新增 `on_result(url, task_id)`,在 `return url` **之前**回调,回调异常只记日志不外抛(落盘失败不能反过来把已生成的结果弄丢)。`_prodgen_run_image` 传 `files + [p]`,保住部分成功的那几张。
- `backend/matrix_native_client.py`(`_wf_download` / `_wf_download_should_retry` / `_WF_DOWNLOAD_RETRY_STATUS`):退避重试仅限连接层瞬时故障与 408/429/5xx。`HTTPError` 是 `RequestException` 的子类,所以必须先按异常类分流再看状态码,否则会把 403 也重试掉,正好踩爆 `raise_for_status` 那条注释守的不变量。流式下载 + `.part` + `os.replace`,避免半截文件骗过调用方「已存在就跳过」的判断。`trust_env=False` 绕开系统代理。
- `backend/matrix_native_client.py`(`ProductGenPage._start`):异常分支先查 `pendingDownloadRecovery`,命中则写 `status="下载失败"` 并累计 `downloadAttempts`,否则维持原「失败」路径。
- `backend/matrix_native_client.py`(`ProductGenPage.recover_download` + `GenCard` 的 `下载失败` 分支与「恢复下载」按钮):只调 `_wf_download`,不调 `_prodgen_generate` / `try_charge` / `_start` / `lk888_media_task`。成功后清空 `pendingDownloadRecovery`。
- `tests/test_agent_download_recovery.py`:12 条。`test_recovering_a_download_never_starts_a_new_paid_generation` 用 AST 取实际被调用的函数名(不看注释),避免文档措辞误伤。
- 运行说明与回滚见 `CHANGELOG.md` 同日条目。

## 2026-08-07 Agent.模式「更多参数」抽屉
- `backend/matrix_native_client.py`(`_agent_schema_field`):新增 `duplicate_role` 字段。同一模型内同角色的第二个字段除了不当胶囊,还会被置 `hidden=True`,因此 `_agent_form_drawer_fields` 也拿不到它。`happyhorse-r2v` 的 `aspect_ratio` 由此彻底进不了请求 —— 它和 `ratio` 同时出现会 400。
- `backend/matrix_native_client.py`(`_agent_form_visible_fields` / `_agent_form_drawer_fields`):前者收敛为「会渲染且一定会被发出去的字段」,后者是它里面 role 不属于 aspect/duration 的部分,即抽屉内容。
- `backend/matrix_native_client.py`(`_agent_entry_extra_params` / `_agent_apply_entry_params`):把条目里用户显式改过的参数合并进已组装好的 payload。合并前逐个过该模型 schema:字段不存在、是上传/未知类型、值不在 `options` 里,一律丢弃并 `log`。`_prodgen_run_image` 与 `_prodgen_run_video` 在 `lk888_media_task` 之前各调一次。
- `backend/matrix_native_client.py`(`class AgentMoreParamsDialog`):抽屉对话框。choice/toggle → `QComboBox`(可选项在最前面插「默认(不指定)」)、textarea → `QPlainTextEdit`、input/number → `QLineEdit`;必填标 `*必填`;单选项字段渲染但禁用。`description` 一律落成控件下方的灰色可见文案 —— `tests/test_native_tooltips.py` 用 AST 扫全文件禁止任何非空 `setToolTip`。`values()` 只返回与默认值不同的项。
- `backend/matrix_native_client.py`(`ProductGenPage._changed_extra_params` / `_open_more_params`、`b_more` 胶囊):抽屉是这批参数的唯一来源,确认时先清掉旧值再写入,避免残留。改动条数反映在胶囊文案与配色上,并在 `param_note` 列出「已改动的模型参数：…」。
- `backend/matrix_native_client.py`(`_send_confirmed`):条目新增 `params`(只含改过的项)与 `paramsMeta`(给生成卡显示的快照)。`regen` 已是黑名单复制,这两个字段会自动跟着重跑。
- 设计取舍:让抽屉「真生效」而不必逐模型开闸,靠的是**只发用户显式改过的键**。没开过抽屉 → `params` 为空 → 请求与上一版逐字节相同;开过 → 增量就是用户自己点的那几个键,且值必来自模型自己的 options。这样既不留假控件,也没有把 67 个模型的装配权一次性交给 schema。
- `tests/test_agent_page_offscreen.py`:新增 `test_the_drawer_holds_every_parameter_that_is_not_already_a_pill`、`test_a_duplicate_role_field_is_hidden_from_the_drawer_too`、`test_untouched_drawer_leaves_the_request_byte_for_byte_unchanged`、`test_a_value_picked_in_the_drawer_actually_reaches_the_request`、`test_a_value_the_model_never_declared_is_dropped_instead_of_sent`。
- 运行说明与回滚见 `CHANGELOG.md` 同日条目。

## 2026-08-07 Agent.模式输入框按模型 schema 渲染(UI 接线)
- `backend/matrix_native_client.py#L2796-L2820`:`_agent_aspect_from_size` 里的局部 mapping 提为模块级 `_AGENT_SIZE_TO_ASPECT`,并由它推出反向表 `_AGENT_ASPECT_TO_SIZE`(每个比例取 1K 档)与新函数 `_agent_size_from_aspect()`。图片模式的请求只由 `size` 决定(`_prodgen_run_image` 只把 size 传下去),两个方向必须同源,否则界面说 16:9、上游收到 3:2。
- `backend/matrix_native_client.py#L27352-L27470`:`ProductGenPage` 新增 `_current_form/_request_model_schema/_model_values/_field_value/_set_field_value/_field_label_for/_pick_field/_bind_role_pill/_sync_param_bar`。`_bind_role_pill` 把 `b_aspect`/`b_duration` 绑到当前模型的 aspect/duration 角色字段上,字段不存在就 `setVisible(False)`。`_pick_field` 对可选字段在菜单顶部插一项「默认(不指定)」,选中即 `AGENT_PARAM_UNSET`。
- `backend/matrix_native_client.py#L27556-L27600`:`_pick_aspect`/`_pick_video_duration` 改为读表单字段弹菜单;`_select_aspect`/`_select_duration` 保留下标入口(没有 schema 时 `ASPECTS`/`duration_slots` 仍是兜底档位),但会把对应的 schema 取值一并写进 `_param_values`。`_current_video_duration` 优先读表单值。
- `backend/matrix_native_client.py#L27380-L27400`:`_set_current_model` 换模型时清掉该 (model, mode) 的表单缓存并起后台取 schema;`_sync_model_ui` 末尾改调 `_sync_param_bar`;`_sync_duration_ui` 降为它的薄封装(名字保留,`tests/test_agent_video_duration.py` 以它为锚点)。
- `backend/matrix_native_client.py#L27700-L27712`:新增 `_current_input_hint()`,提示语优先用模型自己的 `input_hint`(多行压成一行),`_apply_ref_hint` 以它为基准而不是 `BASE_HINT`。
- `backend/matrix_native_client.py#L27810-L27832`:新增 `_aspect_entry_fields()` 适配器,把比例胶囊的取值折回条目既有的 `(aspectLabel, size, aspect_ratio)` 三个字段。字段名本身就是 `size`(gpt-image-2)或值形如 `1920x1088` 时原样透传,否则用 `_agent_size_from_aspect` 换算。**请求的形状一点没变**,`_send_confirmed` 里 `self.ASPECTS[self.aspect_i]` 换成这个方法的返回值。
- `backend/matrix_native_client.py#L26560-L26566`、`#L26760-L26770`:`__init__` 新增 `_forms/_param_values/_role_values/_schema_pending` 四个状态与只读的 `param_note` 标签;`_on` 新增 `prodgen_model_schema` 分支;`on_show` 预取当前模型的 schema。
- 假控件的处理口径:`_agent_form_visible_fields` 对未开闸模型只返回 role ∈ {aspect,duration} 的字段,其余参数由 `param_note` 列成一行只读文字(「该模型另有参数：… —— 尚未接入请求」)。**渲染出来的控件一定是会被发出去的**,不画点了不影响请求的控件。description 一律落成页面内可见文案 —— `tests/test_native_tooltips.py` 用 AST 扫全文件禁止任何非空 `setToolTip`。
- `tests/test_agent_page_offscreen.py`(新增 11 条):断言渲染结果而非源码字符串。关键一点是 `setUpClass` 里必须把页面真正 `show()` 出来 —— 未显示的控件 `isVisible()` 恒为 False,「胶囊消失了」这类断言会假绿(第一版就踩了这个,`test_the_page_is_actually_visible_so_visibility_assertions_mean_something` 专门守住)。
- 离屏实测(不发网络,全部走随包快照):`gpt-image-2` 比例 34 项无时长胶囊 / `gemini-3-pro-image-preview` 比例 10 项 / `mj_imagine` 另有 5 个未接入参数 / `kling-v2-6` 比例 3 项时长 2 项 / `wan2.7-shouweizhen` 无比例胶囊、上传槽「首帧 尾帧」上限 2 / `happyhorse-video-edit` 两条胶囊全无、多出视频上传口 / `vidu-jieshuoman` 比例 6 项时长 3 项。
- 运行说明、已知副作用(16:9 由 `1536x1024` 改为 `1920x1088`)与回滚见 `CHANGELOG.md` 同日条目。

## 2026-08-07 Agent.模式参数按模型 schema 动态化(引擎部分)
- `backend/matrix_native_client.py#L2556-L2572`:新增单模型 schema 的缓存常量。与 `_LK888_MODEL_CACHE` 分开的原因是后者是裸 dict、且失败按成功 TTL 缓存 300 秒;schema 这边成功 24 小时、失败 120 秒负缓存,并且复合读改写全程持 `_LK888_SCHEMA_LOCK`(UI 线程读、后台线程写)。
- `backend/matrix_native_client.py#L3243-L3290`:`_lk888_schema_disk_path/_load/_save` 磁盘缓存(`data_dir()/lk888_model_schemas.json`,`_atomic_write_json`,按 ts 淘汰到 200 条)。坏文件、版本不符一律当空,不让一份损坏缓存拖垮参数区。
- `backend/matrix_native_client.py#L3292-L3345`:`_lk888_schema_snapshot()` 读随包快照;`_lk888_schema_normalize()` 把上游返回收敛成固定形状(params 恒 list、option 恒 `{value:str,label:str}`),对 `params` 非 list、option 缺 value、裸字符串 option 等敌意输入全部容错。
- `backend/matrix_native_client.py#L3347-L3410`:`_lk888_model_schema_cached()`(只读,UI 线程用)与 `_lk888_model_schema()`(发网络,只在后台线程调)。后者失败时**保留上一次成功的结果**再落降级链,否则一次 502 会把 stale 兜底一起抹掉。
- `backend/matrix_native_client.py#L3050-L3120`:`AGENT_PARAM_UNSET`、`_AGENT_SCHEMA_MODELS`(逐模型开闸集合,当前空集)、`AGENT_DYNAMIC_PARAMS` 总开关、角色字段名表、`_AGENT_UPLOAD_PLURAL`(直接抄 LK888 写在 77/78 条上传描述样板里的契约,不靠猜)、`_AGENT_MODEL_OVERRIDES` 与其闭合键集 `_AGENT_OVERRIDE_KEYS`。
- `backend/matrix_native_client.py#L3122-L3260`:`_agent_param_kind/_agent_param_role/_agent_clean_description/_agent_desc_count_limit/_agent_upload_media/_agent_upload_is_array/_agent_upload_limit/_agent_param_default`。其中 `_agent_param_role` 对同一模型内同角色只认第一个字段 —— `happyhorse-r2v` 的 params 顺序是 `resolution, duration, ratio, aspect_ratio`,绑到 `ratio` 后 `aspect_ratio` 既不渲染也不发送,机械避开 `docs/TROUBLESHOOTING.md` 记录的那条互斥 400。
- `backend/matrix_native_client.py#L3196-L3232`:`_agent_param_default` 的八级阶梯。关键取舍是规则 4:**可选 choice/toggle 一律返回 `AGENT_PARAM_UNSET`,不预填也不发送**。schema 里 356 个参数一个 `default` 都没有,若照抄 `options[0]` 会造成静默改档(实测 pixverse 全系 `options[0]` 是 `360P` 而今天发 `720p`,kwvideo 是 `480p`,`kling-v3.resolution` 是 `2k` 而今天发 `1k`)。
- `backend/matrix_native_client.py#L3262-L3400`:`_agent_schema_field/_agent_schema_form/_agent_legacy_form/_agent_schema_form_for_ui/_agent_form_field/_agent_form_role_field/_agent_form_visible_fields`。`_agent_schema_form` 整体 try/except 退回 `_agent_legacy_form`,参数区绝不空白。`_agent_form_visible_fields` 对未开闸模型只返回 role ∈ {aspect,duration} 的字段 —— **渲染出来的一定是会被发出去的**,不画点了不影响请求的假控件。
- `backend/matrix_native_client.py#L3402-L3520`:`_agent_serialize_value`(值恒取自 options 且恒为字符串,消灭 `sound=false` 与 `watermark=False` 两类)、`_agent_dynamic_payload`(R1 必填必发 / R2 可选未设不发 / R4 值域收敛)、`_agent_payload_gate`(params 键必属该模型 schema,被丢的只记键名不记值)、`_agent_validate_form`(扣费前拦截,choice/toggle 说「请选择」、自由文本说「请填写」)、`_agent_params_meta`。
- `backend/matrix_native_client.py#L19800-L19806`、`#L27470-L27480`:`_PRODGEN_RUNTIME_KEYS` + `regen()` 白名单改黑名单。旧实现只抄 12 个字段,视频重跑丢 `duration`/`referenceVideo`;参数动态化后每个模型字段各不相同,白名单更不可能列全。
- `tools/gen_lk888_schema_snapshot.py`(新增):抓全量 schema → 生成 `backend/lk888_schema_snapshot.py`(gzip+base64 单常量,PyInstaller 靠 import 自动收集,不用改打包配方)与 `tests/fixtures/lk888_model_schemas.json`。少于 20 个模型时拒绝覆盖快照。
- 契约测试口径:`tests/test_agent_payload_contract.py` 对全部 67 个模型跑通用不变式,而不是逐模型钉死 payload —— 装配是通用的,守护也必须是通用的。踩过坑的模型(`kling-v2-6` sound、`happyhorse-r2v` 互斥、`veo3.1` 双开关、`vidu-jieshuoman` 主文本字段叫 `script_content`)另有具名用例。
- 一个真实发现:`vidu-mv.duration`(number)与 `vidu-jieshuoman.script_name`(input)都是 required 但没有 options,客户端不能凭空编默认值,只能由 `_agent_validate_form` 在提交前拦住让用户填。这是契约测试跑出来的,不是设计时想到的。
- 运行说明与回滚见 `CHANGELOG.md` 同日条目。`_AGENT_SCHEMA_MODELS` 为空集时线上行为逐字节未变。

## 2026-08-07 Agent.模式输入框改成 lk888 版式
- `backend/matrix_native_client.py#L4816`：`_draw_icon()` 新增 `bolt`（计费徽章闪电）、`info`（圆圈 i）、`close`（清空叉）、`chevron` 四种手绘图标。
- `backend/matrix_native_client.py#L25971`、`#L25989`、`#L25997`、`#L26002`：新增 `_PROD_MENU_PILL_TPL` / `_prod_menu_pill_style(accent)`（按参数着色的下拉胶囊）、`_PROD_COST_CHIP`、`_PROD_SEND_BTN`（青绿圆形发送键）、`_menu_pill_label()`（文案尾部补 `▾`）、`_prod_menu(parent)`（统一深色菜单，`_pick_model` 也改用它）。
- `backend/matrix_native_client.py#L25984`：`REF_SLOT_W/H` 由 112×56 改为 84×84，`REF_SLOT_RADIUS` 13→14。84 是让槽下「点击替换 / 右键删除」在 8.5px 字号下单行放得下的宽度。
- `backend/matrix_native_client.py#L26575`：composer 重排为「工具条 → body（左参考图 / 右提示语+输入）→ 分隔线 → 胶囊行 → 模型元信息」。工具条含清空输入、清空参考图、计费徽章、计费说明；底部胶囊行去掉原来的清空输入垃圾桶。
- `backend/matrix_native_client.py#L26806`、`#L26819`、`#L26827`：`_sync_cost_chip()` 读 `_SHARED["balance"]` 渲染云豆余额，`_refresh_cost_chip()` 在 `on_show` 起后台 `fetch_balance()` 并经 `BRIDGE` 的 `prodgen_balance` 回主线程刷新，`_show_billing_note()` 弹计费说明。徽章不显示单价：`product_image`/`product_video` 在 `_SERVER_CHARGED_CAPS` 里，由中心服按 LK888 实际用量后付费，提交前无确定单价。
- `backend/matrix_native_client.py#L26859`：`_autosize_input()` 按文档高度把输入框钉在 78~138px，接 `textChanged`。此前 `QPlainTextEdit` 直接撑到 `maximumHeight`，composer 白占一截高度。
- `backend/matrix_native_client.py#L26865`：`_menu_choice(button, options, current_index, on_pick)` 在胶囊正下方弹选项菜单；`_cycle_aspect/_cycle_count/_cycle_style/_cycle_video_duration` 全部替换为 `_pick_*` + `_select_*`。新增类常量 `COUNTS = (1, 2)`，发送时的 `count` 改读 `self.COUNTS[self.count_i]`。
- `backend/matrix_native_client.py#L26524`、`#L27026`、`#L27038`：`BASE_HINT` 只留通用提示语；参考图用法由 `_ref_hint_text()` 按模式产出、`_apply_ref_hint()` 追加到 `self.hint`（`__init__` 里先建槽后建提示语，故做空值保护），不再作为一个 QLabel 塞进 `ref_strip`。
- `tests/test_agent_mode_defaults.py`、`tests/test_agent_video_duration.py`：源码契约断言跟随更新（`body.addLayout(ref_strip)` / `prompt_col.addWidget(self.inp)` / `REF_SLOT_W = 84` / `def _pick_video_duration`），`_mode_set` 块的切分锚点由 `def _cycle_aspect(self):` 改为 `def _menu_choice(`。
- 验证：`py_compile` 通过，`tests` 全量 1520/1520 通过；offscreen 与真字体各渲染一次 composer 核对版式（1232×268，参考图槽 84×109，胶囊 `▾` 正常）。需重启本地客户端生效，未打包、未上线。

## 2026-08-07 视觉分析失败不再污染同款替换提示词
- `backend/replacement_analysis.py#L35-L91`：新增 `_visual_status_ok/_visual_status_failed/_visual_status_empty/_visual_status_skipped` 和 `breakdown_visual_failure()`。失败记录只带 `status/errorId/code` 和一句固定中文，异常原文留在结构化日志，避免上游主机名和端点随分析结果进入任务负载；缺少 `visualStatus` 的历史分析按 ok 处理。
- `backend/replacement_analysis.py#L242-L268`、`backend/replacement_analysis.py#L300-L307`、`backend/matrix_native_client.py#L8146-L8172`、`backend/matrix_native_client.py#L8199-L8206`：视觉模型失败、无可用关键帧和分解整体失败时 `visual` 一律置空，失败信息写进 `visualStatus`，不再拼 `视觉模型分析失败（errorId: ...）: <异常> + frameNotes`。
- `backend/matrix_native_client.py#L21292-L21318`：新增 `_REPLACEMENT_DIAGNOSTIC_NOISE_RE` 和 `_replacement_strip_diagnostic_noise()`，按行丢弃报错文本、URL、域名、`host=/port=/timeout=`、`/v1/` 类接口路径和 `.jpg/.png/.mp4/.log` 文件名；`_replacement_current_shot_constraints()`（时间轴取材与 `visual` 兜底两处）和 `_replacement_safe_breakdown_evidence()` 都在拼提示词前调用它，历史任务里已被污染的分析结果同样被过滤。
- `backend/matrix_native_client.py#L12916-L12931`：`_comic_visual_prompt_text()` 增加 `describable_visual_line()` 白名单校验，标注块和普通行两条路径都要求文本含中文描述且不含技术噪声，才允许进入 storyboard `description`。原有 `drop_markers` 黑名单保留，只作为第一层过滤。
- `backend/matrix_native_client.py#L20894-L20907`、`backend/matrix_native_client.py#L20927`：新增 `_breakdown_visual_status_label()`，分解报告“来源”区输出 `- 视觉分析: ok` 或 `- 视觉分析: 失败（错误编号 err-xxxx）`。
- `backend/matrix_native_client.py#L16675-L16696`、`backend/matrix_native_client.py#L15344`：`VideoReplacementPage._confirm_visual_analysis_failure()` 在 `start_generation()` 收集完片段编辑后拦截，视觉分析未成功时弹确认框并默认取消。
- `backend/replacement_pipeline.py#L100-L111`：`build_plan()` 把 `breakdown_visual_failure()` 结果写进 `job["visualAnalysisFailure"]`，失败时输出 `video_replace_visual_analysis_unavailable` 结构化日志（只带 jobId、状态和错误编号）。
- `tests/test_replacement_service.py#L160-L168`、`#L410-L462`：`_replacement_analysis()` 支持注入 `vision_runner`；新增视觉失败/成功两条契约用例，断言 `visual` 为空、`visualStatus` 完整，且序列化后的分析结果不含上游主机名和端点。
- `tests/test_video_replacement.py#L2101-L2150`、`tests/test_video_replacement_v2.py#L1212-L1256`、`tests/test_video_breakdown.py#L244-L267`：回归覆盖被污染分析不进视频/关键帧/漫剧三类提示词、漫剧画面描述只保留中文描述行、`build_plan()` 记录视觉失败，以及报告显示视觉分析状态。
- 验证与影响：上述用例先在旧实现下 RED；修复后引用这三个文件的 38 个测试模块共 974 条用例通过，仅剩两条与本次无关的既有失败（`tests.test_douyin_comment_cooldown` 的评论前检查、`tests.test_ui_feature_visibility` 缺少 `backend/.env.dev`）。本次只影响本地客户端与本地服务层，不改变中心服 API、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。漫剧端 `tools/aicanvas_remote/server_current.py#L14554-L14566` 在首尾帧路径上仍拼“七帧中的每一帧”前缀，属于远端文案问题，本次未改。

## 2026-08-05 网页替换按 job 模式选管线（漫剧/hybrid）+ 网页启动器
- `backend/matrix_native_client.py#L11690`、`#L11727`：新增 `_ReplacementServicePipeline` / `_replacement_service_pipeline()`，为 `/replacement` 网页与 Qt 共享服务按 job 的 `replacementMode` 路由 hybrid 或 comic_project 管线（镜像 `_replacement_pipeline_for_job`）；缺模式的网页 job 在 `build_plan` 时补产品默认 `VIDEO_REPLACE_DEFAULT_MODE`（默认 `comic_project`）并持久化到 job.json，使后续 execute/retry/concat 路由一致；已有模式的 Qt 共享 job 不被覆盖。修复此前网页服务 `_build_pipeline` 写死 hybrid、忽略默认漫剧模式的 gap。
- `backend/replacement_web.py` 的 `_build_pipeline()`：`build_video_service` 改用 `_replacement_service_pipeline()` 路由管线，取代只用 `_replacement_hybrid_pipeline()`。
- `tests/test_video_replacement_v2.py`：新增 4 个路由测试（缺模式默认 comic、legacy 默认 hybrid、显式模式优先并路由 execute、`build_video_service` 使用路由管线）；并修复 `test_keyframe_references_migrate_existing_central_library_urls_in_memory` —— 该迁移仅对回环中心库 URL 适用，测试显式钉 `CENTRAL=http://127.0.0.1:9080`，不再依赖出厂默认（现为公网 `120.26.194.174`，见 d349f9c）。
- `start-visible-client-web.bat`：出厂 `start-visible-client.bat` 的瘦包装，额外设 `MATRIX_REPLACEMENT_WEB_ENABLED=1` 与 `VIDEO_REPLACEMENT_SERVICE_MODE=shared`，便于本机跑网页版同款替换真实链路（原脚本保持默认关的安全默认）。

## 2026-08-04 本地视频替换共享服务（Web 生命周期、Qt 适配器与熔断回滚）
- `backend/replacement_service.py#L109`：模块级 `public_job()` 抽出集中脱敏（去除 `outDir/sourceVideoPath/videoPath/outputPath`、凭据、签名 URL），Web 与 Qt 复用同一份公开视图。
- `backend/replacement_service.py#L458`：`ReplacementService.retry()` 仅在 `partial`/`awaiting_review` 状态转发 `pipeline.retry`，原子持久化并返回脱敏 job；缺失 job 抛 `replacement_job_not_found`。
- `backend/replacement_service.py#L190`、`#L224`、`#L246`：`record_terminal_result()` 维护有界终态窗口（≤500，按 agent 数据目录持久化、只存 job id 哈希，cancelled 不计失败）；`circuit_breaker_state()` / `shared_mode_allowed()` 需至少 100 个终态样本，仅当 `failed/total > 0.01` 才回落 legacy（1% 严格不触发），且从不打断进行中的 job。
- `backend/replacement_service.py#L285`、`#L329`：`build_replacement_event()` / `emit_replacement_event()` 产出脱敏事件（provider task id 走 sha256 前缀哈希、签名 URL 只保留 scheme+host），覆盖 `prepare_started/analysis_completed/provider_submitted/provider_recovered/billing_settled/video_completed/video_failed/shared_mode_circuit_opened/rollback_requested`。
- `backend/replacement_web.py#L1083`、`#L1136`、`#L1166`、`#L1179`、`#L1194`、`#L1207`：`build_video_service()` 用真实 `SourceResolver`+`HybridReplacementPipeline` 构建服务并注入 `metrics_dir`；`prepare/execute/retry/concat/cancel_video_job()` 只编排服务，绝不直连 provider、不预扣费。
- `backend/replacement_web.py#L1238`、`#L1268`：`video_job_response()` 字段白名单 + 复用 `public_job` 脱敏（download 只给 basename 与 available，绝不含内部路径/凭据）；`final_media_path()` 校验 job id、文件名 basename 与 data-dir sandbox 根，拒绝穿越。
- `backend/api_server.py#L7186`、`#L7337`、`#L7367`、`#L7518`：新增 `POST /api/replacement/video/{prepare,execute,retry,concat,cancel}`（202）、`GET .../job`（200，走 `video_job_response`）、`GET .../download`（校验 task id/文件名/根后串流最终媒体）；`POST .../video/start` 保留为不能触发生成的 Phase 0 兼容别名；均保留 `MATRIX_REPLACEMENT_WEB_ENABLED` 开关与 agent token 鉴权，非法状态转移返回 HTTP 409。
- `backend/matrix_native_client.py#L11691`、`#L11739`、`#L11743`：`replacement_mode_for_new_job()` 仅在 `VIDEO_REPLACEMENT_SERVICE_MODE=shared` 且 `shared_mode_allowed()` 同时成立时返回 shared，熔断开启时发 `shared_mode_circuit_opened`/`rollback_requested` 并回落 legacy；`video_replacement_service_shared()` 与 `ReplacementServiceAdapter`（prepare/execute/retry/concat/cancel）把 Qt 控件映射为服务请求、从 job.json 读回脱敏状态并发既有 BRIDGE 事件，绝不改动 provider task id 或计费 ref；legacy 默认路径逐字保留。
- `backend/matrix_native_client.py#L17514`：`_replacement_web_download_source()` 复用既有分解下载/校验路径（`_wf_download` + `_breakdown_source_validation`），使生产直链替换的源下载可用（闭合 Task 5 遗留），非 2xx 或非法媒体拒绝并删除半成品文件。
- `tests/test_replacement_web_mvp.py`、`tests/test_replacement_service.py`、`tests/test_video_replacement.py`、`tests/test_video_replacement_v2.py`：覆盖 handoff/直链 prepare、鉴权 execute/retry/concat/cancel、轮询、非法状态 409、下载与响应脱敏、页面视频 tab 控件、Qt legacy/shared 门控与 BRIDGE 事件形状、熔断边界（100/2→legacy、100/1→shared、cancelled 不计、active 不打断）与事件脱敏。
- 功能开关与回滚：`MATRIX_REPLACEMENT_WEB_ENABLED`（默认关，关闭时 `/replacement` 与 `/api/replacement/*` 返回 404）、`VIDEO_REPLACEMENT_SERVICE_MODE=legacy|shared`（默认 legacy）。回滚只需将 `VIDEO_REPLACEMENT_SERVICE_MODE` 保持/切回 `legacy` 即恢复旧 Qt 生成路径；无远程部署、无数据库迁移、`migration.sql` 为无迁移说明。中心服默认 `CENTRAL` 恢复为 `http://127.0.0.1:9080`（与出厂 `start-visible-client.bat` 一致），远程中心服由 `MATRIX_CENTRAL` 显式覆盖。
- 验证：`tests.test_replacement_service`、`tests.test_replacement_web_mvp`、`tests.test_openapi_contract`、`tests.test_video_replacement(_v2)`、`tests.test_video_breakdown`、`tests.test_web_surface_removed` 全绿（合并 526）；`py_compile` 所有改动模块通过。注意：本 `IMPLEMENTATION.md` 存量约 1399 处行号引用（其中约 1024 处指向 `matrix_native_client.py`）在本次及既往 `44bac87` 大重构后可能整体漂移，本次仅保证以上新增条目行号为当前值，未逐条重算历史引用。

## 2026-08-04 Comic tool Windows client download card
- `tools/aicanvas_remote/server_current.py#L359-L374`: `_agent_installer_candidates()` and `_resolve_agent_installer_path()` resolve the public Windows installer from `AICANVAS_AGENT_INSTALLER`, `MATRIXSHIP_AGENT_INSTALLER`, the remote AI Canvas root, or the local project installer output.
- `tools/aicanvas_remote/server_current.py#L376-L450`: `_comic_tool_download_card_script()` and `_inject_comic_tool_download_card_html()` inject an idempotent `yunling-download-card-injector` script into `/comic-tool`; the script appends a standalone Windows client card that links to `/MatrixShipAgent-Setup.exe`.
- `tools/aicanvas_remote/server_current.py#L392-L416`: append-fix removes cloning/reordering of existing cards. The script now finds the common tool container for `漫剧Agent` and `漫剧画布`, then appends a standalone Windows card; it no longer uses `cloneNode` or inserts immediately after Agent.
- `tools/aicanvas_remote/server_current.py#L422-L422`: Windows card copy positions the product as `云灵星图 AI爆款复刻平台 Windows 桌面客户端` for the local executor, account matrix, and material tasks; it explicitly says the download is the client installer and does not include comic project files.
- `tools/aicanvas_remote/server_current.py#L25793-L25798`: `Handler.send_head()` injects the download-card script into `platform-index.html` only for `/comic-tool` and `/comic-tool/agent` shell responses.
- `tools/aicanvas_remote/server_current.py#L25867-L25883`: `Handler.serve_agent_installer()` serves the installer with attachment headers and supports HEAD without streaming the body.
- `tools/aicanvas_remote/server_current.py#L25970-L25971` and `tools/aicanvas_remote/server_current.py#L25988-L25989`: `do_HEAD()` and `do_GET()` expose `/MatrixShipAgent-Setup.exe` before other routing.
- `tests/test_minimax_aicanvas_remote.py#L292-L372`: `AiCanvasComicToolDownloadEntryTest` covers 4th-card script content, idempotent HTML injection, environment path resolution, unauthenticated route ordering, GET serving, and attachment headers.
- `tests/test_minimax_aicanvas_remote.py#L306-L311`: regression coverage prevents the download-card script from cloning or reordering existing tool cards.
- `tests/test_minimax_aicanvas_remote.py#L297-L305`: card-copy coverage requires `AI爆款复刻平台`, `下载的是客户端安装包`, and `不包含漫剧项目文件`.
- Verification and rollback: focused RED/GREEN was run for `tests.test_minimax_aicanvas_remote.AiCanvasComicToolDownloadEntryTest`; final verification passed the focused test, full `tests.test_minimax_aicanvas_remote`, and `py_compile` for the touched remote mirror/test. Remote runtime was deployed to `/root/AI-CanvasPro/server.py`, installer copied to `/root/AI-CanvasPro/MatrixShipAgent-Setup.exe`, and `ai-canvas.service` restarted active; no OpenAPI, database, Docker, secret, or `migration.sql` impact. Roll back `tools/aicanvas_remote/server_current.py`, `tests/test_minimax_aicanvas_remote.py`, `CHANGELOG.md`, `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`, and this entry, plus restore `/root/AI-CanvasPro/server.py.bak.download-card-test-20260804_094216` to remote `server.py` and restart `ai-canvas.service`.


## 2026-08-03 账号矩阵新增账号 agent token 同步
- `backend/local_browser_worker.py#L85-L95`：`read_local_token()` 继续优先读取 `MATRIX_AGENT_TOKEN` / `LOCAL_AGENT_TOKEN`，没有环境变量时读取当前数据目录下的 `agent_token.txt`；文件读取改为 `with open(...)`，避免长期 worker 泄漏文件句柄。
- `backend/local_browser_worker.py#L202-L207`：`local_headers` 每次转发本机执行器请求前动态刷新本地 agent token，并更新 `self.local_token` 缓存，避免新用户登录、账号隔离目录切换或 token 文件刷新后仍使用旧 token。
- `backend/matrix_native_client.py#L1629-L1699`：新增账号矩阵专用 `submit_account_login_direct()`，由原生客户端直接请求本机执行器 `/api/login/start` 或 `/api/xhs/login`，再轮询 `/api/login/status` 并读取 `/api/accounts` 回填账号摘要，避免登录新增账号时再绕中心服本地浏览器任务队列。
- `backend/matrix_native_client.py#L6356-L6362`：账号矩阵登录按钮改为调用 `submit_account_login_direct(platform, mode=mode, timeout_poll=300)`，`acct_login` 返回结构保持原页面消费格式。
- `start-visible-client.bat#L11-L12`、`start-visible-client.bat#L53-L80`：双击启动脚本显式设置 `LOCAL_API_PORT/API_PORT=9081`，并在启动客户端前用 `netstat` + `taskkill` 清理旧本地执行器监听，防止新用户会话打到上一轮 token 的残留 `9081`。
- `tests/test_douyin_dm_auto_reply.py#L42-L112`：新增两条 RED/GREEN 回归，分别覆盖环境变量 token 从旧值切换到新值、`agent_token.txt` 从旧值刷新到新值后，`douyin.login` 转发 `/api/login/start` 必须携带最新 `X-Matrix-Agent-Token`。
- `tests/test_auth_login_modes.py#L74-L86`、`tests/test_start_visible_client_script.py#L21-L30`：回归覆盖账号矩阵登录直连本机执行器，以及启动脚本在客户端启动前清理旧 `9081`。
- 验证与影响：定向 token、账号矩阵登录链路、启动脚本回归和 `py_compile` 通过；本次影响本地浏览器 worker、本地客户端账号矩阵和本地启动脚本，不放宽 token 鉴权，不改变中心服 API、OpenAPI、数据库、Docker、密钥配置或 `migration.sql`。退出后用 `start-visible-client.bat` 重启生效；回滚 `backend/local_browser_worker.py`、`backend/matrix_native_client.py`、`start-visible-client.bat`、相关测试、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-08-03 Asset Library note-template filter visibility
- `backend/matrix_native_client.py#L27428-L27436`: `AssetLibraryPage` local filter tuple now exposes only All, Image, Video, and Collected Reference Video; `note_template` is intentionally omitted so the note-template button is hidden from the Asset Library filter row.
- `backend/matrix_native_client.py#L27659-L27698`: note-template card handling remains in `_asset_card()`, preserving historical note-template assets with folder and delete actions while avoiding direct JSON opening.
- `tests/test_asset_library_shared_button.py#L89-L100` and `tests/test_xhs_note_replacement.py#L551-L569`: regression coverage asserts the filter row hides `note_template` while the compatibility card branch remains.
- Verification and operations: focused native-client tests passed; restart the local client before checking the UI. No OpenAPI, database schema, Docker, environment variable, remote service, or `migration.sql` impact. Roll back the files listed in `CHANGELOG.md` to restore the old button.
## 2026-08-03 账户中心分解视频扣费文案与明细居中
- `backend/matrix_native_client.py#L1074-L1091`：`_billing_video_breakdown_detail_text()` 命中 `billingScenario=video_breakdown`、`video_breakdown` 引用或原始详情里的“分解视频”后直接返回“分解视频调用”，退款流水返回“分解视频调用退款”，让分解视频页产生的模型扣费先于通用 chat/workflow 兜底被识别。
- `backend/matrix_native_client.py#L28734-L28743`：账户中心扣费明细表头设置 `QtCore.Qt.AlignCenter`，保持现有列宽、详情列拉伸、横向滚动和 tooltip 清空策略。
- `backend/matrix_native_client.py#L29008-L29023`：新增 `_ledger_table_item()`，加载占位行和空白占位列统一居中，并继续用 muted 颜色显示“正在读取扣费明细…”。
- `backend/matrix_native_client.py#L29476-L29500`：真实账单流水渲染改用 `_ledger_table_item()`，时间、类型、模型、任务详情、实扣/变动、扣后余额、状态全部居中；负数红色、正数绿色和任务详情无原生 tooltip 行为保持不变。
- `tests/test_account_billing_dashboard.py#L148-L187`、`tests/test_account_billing_dashboard.py#L472-L506`：RED/GREEN 覆盖分解视频文案、退款文案、工作流助手边界，以及表头、加载行、真实流水单元格居中。
- 验证与影响：`tests.test_account_billing_dashboard` 30/30 通过，`py_compile` 通过。本次只影响本地客户端展示层、测试和文档；不改中心服 API、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。重启本地客户端后生效，回滚 `backend/matrix_native_client.py`、`tests/test_account_billing_dashboard.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧展示。

## 2026-08-03 素材发布浏览器关闭错误中文化
- `backend/matrix_native_client.py#L18296-L18327`：新增 `_publish_error_text()`，在 `_publish_result_message()` 最终展示前识别 `set_input_files` 与 `Target page, context or browser has been closed` 组合错误，改为中文提示“发布页面或浏览器已关闭，请重新点击发布，并在上传完成前不要关闭抖音发布窗口。”
- `tests/test_native_publish.py#L640-L656`：新增回归测试，先验证旧实现会裸露 Playwright 英文异常，再锁定中文提示和英文隐藏。
- 影响与回滚：仅本地客户端错误展示层变更，不改变抖音发布、浏览器保留、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本条记录即可。

## 2026-08-03 临时 UI 开关与 XHS 能力元数据过滤
- `backend/platform_features.py#L11-L51`：统一解析 `1/true/yes/on`，新增同款替换、待发布队列、数字人 TTS 上传三个默认关闭开关，并提供可逆、保序的 `xhs.*` 能力过滤。
- `backend/local_browser_worker.py#L36-L70`、`backend/local_browser_worker.py#L204-L221`：本地浏览器执行器注册与轮询动态上报当前允许能力；关闭 XHS 时不再传出 `xhs.*`，开启并重启后使用保留的原任务映射恢复。
- `backend/central_server.py#L79-L87`、`backend/central_server.py#L14376-L14390`、`backend/central_server.py#L14425-L14443`、`backend/central_server.py#L14658-L14688`、`backend/central_server.py#L14778-L14810`：中心服过滤允许任务、新上报、内存存储、轮询匹配和公开响应中的 XHS 能力；历史记录读取时过滤，不做数据迁移。
- `backend/matrix_native_client.py#L44-L88`、`backend/matrix_native_client.py#L6368-L6406`：账号矩阵默认只保留抖音账号、KPI 和平台卡片；`MATRIX_XHS_ENABLED=1` 后恢复 XHS 分组。
- `backend/matrix_native_client.py#L7850-L7853`、`backend/matrix_native_client.py#L18638-L18648`、`backend/matrix_native_client.py#L27761-L27763`：分解视频、工作流助手和资产库的同款替换跳转按钮由 `MATRIX_VIDEO_REPLACEMENT_ENABLED` 控制可见性。
- `backend/matrix_native_client.py#L10018-L10114`：数字人口播在 TTS 上传开关关闭时隐藏上传按钮和声音预览，调整可见说明；自动 TTS、已有上传处理器和持久化字段不变。
- `backend/matrix_native_client.py#L29651-L29659`、`backend/matrix_native_client.py#L31132-L31139`、`backend/matrix_native_client.py#L31215-L31224`、`backend/matrix_native_client.py#L31226-L31231`：待发布队列标签和导航别名按开关构建；同款替换侧栏保持可见但禁用，挂载“功能完善中，敬请期待”悬浮说明，并在事件跳转和直接导航两层阻断绕过。
- `tests/test_ui_feature_visibility.py#L1-L213`、`tests/test_xhs_platform_disable.py#L119-L152`、`tests/test_digital_human_navigation.py#L73-L119`、`tests/test_video_breakdown.py#L1086-L1112`：RED/GREEN 覆盖默认关闭、显式恢复、账号矩阵、队列标签、侧栏状态、程序化跳转、TTS 控件、执行器/中心服能力过滤和 XHS 链接识别恢复。
- 配置：`backend/.env.example#L90-L96`、`backend/.env.dev#L11-L14`、`backend/.env.prod#L10-L13`、`docker-compose.prod.yml#L13-L16` 均显式默认关闭四个开关；不包含密钥。
- 文档：`docs/ARCHITECTURE.md#L19-L37`、`docs/ARCHITECTURE.md#L100-L106`、`docs/DEPLOYMENT.md#L15-L47`、`docs/TROUBLESHOOTING.md#L30-L50`、`CHANGELOG.md#L134-L155` 同步架构边界、风控实际覆盖、部署回滚和旧进程排障。
- 验证：定向回归 170/170 通过；四个生产模块 `py_compile` 和 `git diff --check` 退出 0。Qt 离屏属性、像素和人工截图检查通过。重启后 9080/9081 均为 200，中心服 1 个在线客户端公开 `xhs.*=0`，本地抖音账号能力 3/4，评论写入因 `comment_login_required` 未就绪；本地和中心 XHS 搜索均为 404 `platform_disabled`；清理前中心状态备份 SHA-256 为 `ca1b0d85a7101048857c2de159318e13de78ae70101876239e92ee1e26a650ae`，实际移除 1 条 XHS 账号记录，重启后 dry-run 复查为 0。
- 影响与回滚：不改 API 路径或 JSON Schema、OpenAPI、数据库、Docker 镜像结构和 `migration.sql`。UI 回滚把对应开关恢复为 `0` 并重启客户端；恢复 XHS 设置 `MATRIX_XHS_ENABLED=1` 并重启本地客户端、本地执行器和中心服。

## 2026-08-03 小红书平台默认禁用，仅保留抖音
- `backend/platform_features.py#L11-L111`：新增统一平台开关，`MATRIX_XHS_ENABLED` 默认关闭；`payload_uses_xhs()` 递归识别路由 payload、嵌套 `payload`、素材平台、账号和任务类型中的 XHS 标记；`platform_disabled_result()` 与 `log_platform_disabled()` 输出稳定且脱敏的 `platform_disabled` 契约。
- `backend/platform_adapters.py#L60-L63`、`backend/platform_adapters.py#L243-L2000`：小红书登录、搜索、评论、获客、下载、评论发布和素材发布入口在浏览器导入/自动化前统一返回 `platform_disabled`。
- `backend/api_server.py#L58-L72`、`backend/api_server.py#L1058-L1140`、`backend/api_server.py#L3852-L5558`、`backend/api_server.py#L7146-L7292`：本地执行器隐藏 XHS 账号，阻断 `/api/xhs/*`、`/api/xhs-note-replacement/*`、XHS publish/finder/outreach/login 服务入口和携带 XHS payload 的 POST 请求。
- `backend/central_server.py#L79-L87`、`backend/central_server.py#L161-L166`、`backend/central_server.py#L5178-L5501`、`backend/central_server.py#L7243-L7279`、`backend/central_server.py#L14696-L14702`、`backend/central_server.py#L15270-L15873`：中心服过滤 XHS 账号汇总，阻断 XHS 路由、`xhs.*` 本地浏览器任务和嵌套 XHS payload，且在节点选择前返回 404。
- `backend/matrix_native_client.py#L44-L91`、`backend/matrix_native_client.py#L6368-L6406`、`backend/matrix_native_client.py#L8267-L8282`、`backend/matrix_native_client.py#L18965-L18971`、`backend/matrix_native_client.py#L20603-L20607`、`backend/matrix_native_client.py#L29682-L29699`：本地客户端平台下拉默认只展示抖音；发布页标题、工作流发布平台、视频链接平台识别和图文同款导航均由 `xhs_enabled()` 控制恢复。
- `scripts/disable_xhs_accounts.py#L55-L106`：新增小红书账号状态清理脚本，支持 `--dry-run`，只删除 XHS profile/auth/safety state 和 JSON 账号行，保留抖音账号与素材。
- `tests/test_xhs_platform_disable.py#L44-L176`、`tests/test_openapi_contract.py#L159-L176`：回归覆盖默认禁用/开关恢复、脱敏错误契约、本地/中心/适配器阻断、客户端入口隐藏、嵌套 payload 检测、清理脚本和 OpenAPI 文档门禁。
- 配置与文档：`backend/.env.example#L90-L90`、`backend/.env.dev#L11-L11`、`backend/.env.prod#L10-L10`、`docker-compose.prod.yml#L13-L13` 默认 `MATRIX_XHS_ENABLED=0`；`docs/API_REFERENCE.md#L12-L17`、`docs/ARCHITECTURE.md#L21-L23`、`docs/DEPLOYMENT.md#L15-L27`、`docs/TROUBLESHOOTING.md#L30-L35`、`docs/openapi.yaml#L399-L2096`、`CHANGELOG.md#L134-L143` 同步发布与回滚说明；`migration.sql#L18-L20` 为 no-op 迁移记录。
- 验证：新增测试先在旧实现下失败；当前聚焦验证见最终交付记录。未执行真实小红书浏览器登录/采集/发布，因为默认禁用路径应在浏览器前被阻断。
- 回滚：配置级设置 `MATRIX_XHS_ENABLED=1` 并重启本地客户端、本地执行器和中心服；代码级回滚恢复上述源文件、测试、配置和文档。数据库无结构变更，历史 XHS 清理若已执行，需要从清理前备份或账号重新登录恢复。

## 2026-08-03 抖音私信转人工后继续收件并恢复全自动
- `backend/matrix_native_client.py#L8764-L8804`：新增人工接管消息记录辅助逻辑；转人工时保留收件定时器，只清空自动发送状态并关闭复选框。结构化日志仅记录客户消息指纹、消息类型和接管原因类别。
- `backend/matrix_native_client.py#L8868-L8912`：人工接管状态下继续处理收件结果，将后续客户消息写入当前客户会话并标记 `manual_required`，不进入 `_auto_pending_texts`，不调用 `gen_reply`。
- `backend/matrix_native_client.py#L9082-L9110`、`#L9163-L9284`：再次勾选全自动时清除 `_auto_manual_required` 和一次性提醒状态，保留已处理指纹并从后续新消息恢复自动回复。
- `tests/test_douyin_dm_auto_reply.py#L652-L779`：覆盖转人工关闭自动发送但保持轮询、后续消息显示且不调用 AI，以及人工处理后重新开启全自动继续回复。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v` 通过 84/84；本次未执行真实抖音私信发送。
- 运行与回滚：需重启本地客户端后生效；不涉及 OpenAPI、数据库、Docker、环境变量、远程服务或 `migration.sql`。回滚本次涉及的本地客户端、专项测试和文档即可恢复旧行为。

## 2026-08-03 工作流助手聊天与分析结果按账号恢复
- `backend/matrix_native_client.py#L17238-L17344`：新增工作流助手账号级历史文件 `workflow_assistant_history.json`，保留最近 100 轮用户/助手消息，使用临时文件加 `os.replace` 原子写入；JSON 损坏、版本不支持或写入失败时只记录脱敏结构化日志，不阻断当前页面。
- `backend/matrix_native_client.py#L18268-L18480`：`AgentChatPage` 创建时恢复历史，用户消息和助手最终回复实时保存；切换账号后按新的 `data_dir()` 清理并重载，助手回复中的 `replacementPayloads` 会恢复“按这条改造生成”卡片。采集/转写进度消息保持临时显示，不在重开页面后伪造“运行中”状态。
- `tests/test_workflow_assistant_history.py#L1-L207`：覆盖账号路径、100 轮裁剪、原子写入、payload 保留、损坏 JSON 降级和页面恢复契约。
- 验证：工作流助手历史与既有直接模式/拆解 helper 专项通过；需要重启本地客户端后生效。本次不涉及 OpenAPI、数据库、Docker、环境变量、远程服务或 `migration.sql`。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_workflow_assistant_history.py` 及本条文档变更；删除 `workflow_assistant_history.json` 不影响资产库视频、拆解文本和结构化分析 sidecar。

## 2026-08-01 Agent LK888 online-only video menu rows
- `backend/matrix_native_client.py#L3001-L3009`: `_lk888_grouped_models()` now accepts an optional already-loaded row list. This keeps family grouping on the same LK888 catalog snapshot that the page is currently validating.
- `backend/matrix_native_client.py#L26306-L26335`: `ProductGenPage._pick_model()` passes `self._model_rows()` into `_lk888_grouped_models()`, so online-only LK888 video models under `Omni` or `Other` are selected from the same row set that `_sync_model_ui()` uses to decide whether the current model is still valid.
- `tests/test_agent_video_duration.py#L751-L773`: regression coverage locks the menu source contract and verifies loaded online-only rows can still be grouped into `Omni` and `Other`.
- Verification: focused RED/GREEN tests passed. Full `tests.test_agent_video_duration` is still blocked by existing HappyHorse canonical-rule failures unrelated to this menu data-source fix.
- Operations and rollback: native-client-only change; restart the local client to refresh the Agent model selector. No OpenAPI, database, Docker, environment variable, remote service, or `migration.sql` impact. Revert `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous grouping path.
## 2026-08-03 账户中心范围错误文案与 INFO 成功日志
- `backend/matrix_native_client.py#L28788-L28803`: `AccountPage._request_error()` 对 `date_range_too_large` 单独显示“查询范围最多366天，请重试”，不把 `错误编号 err-*` 渲染到扣费明细前台；内部 `json_log()` 仍记录 `errorId` 和 `code`，保留追踪能力。
- `backend/utils/structured_log.py#L149-L162`: `json_log()` 改为只有调用方显式传入 `errorId`、日志级别为 warning/error/critical/exception，或传入异常 `exc` 时才写入 `errorId`；普通 `level="info"` 成功事件不再自动生成错误编号。
- `tests/test_account_billing_dashboard.py#L392-L410`: 新增扣费明细范围错误展示回归，锁定 `date_range_too_large` 前台文案不含“错误编号”和具体 `err-*`。
- `tests/test_structured_log.py#L159-L169`: 新增 INFO 成功日志回归，锁定 `billing_analytics_completed` 这类成功事件不再自动带 `errorId`。
- 验证与回滚：新增用例先在旧实现下失败，修复后 `tests.test_account_billing_dashboard` 28/28、`tests.test_structured_log` 13/13 通过。本次不改变中心服 API 形状、OpenAPI、数据库、Docker、环境变量或 `migration.sql`；本地客户端和使用 `json_log()` 的长驻服务重启后生效。回滚上述代码、测试、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-08-01 SD2.0 全能参考隐藏彩铅预处理
- `backend/matrix_native_client.py#L12668-L12681`: `_comic_model_is_seedance()` 除 `seedance` 字符串外，也把 `kwvideo-v2-quannengcankao` 和 SD2.0 全能参考类模型识别为隐藏彩铅链路，修复 `SD 2.0 全能参考` 不触发 `gpt-image-2` 的根因。
- `backend/matrix_native_client.py#L12690-L12752`: `_comic_storyboard_video_payload()` 优先读取 `coloredPencilStartFrameUrl`、`coloredPencilEndFrameUrl`、`coloredPencilReferenceImageUrls`，并在存在隐藏彩铅参考时清空普通 typed reference arrays，确保最终视频只拿到隐藏彩铅 URL，同时 prompt 仍追加“真人写实风格”。
- `backend/matrix_native_client.py#L12818-L12924`: `_prepare_comic_colored_pencil_references()` 在首尾帧生成后、视频提交前调用 `gpt-image-2` 转换首帧、尾帧、人物、场景和产品参考图；前端可见的 `startFrameUrl/endFrameUrl` 不被覆盖。缺少隐藏彩铅首帧或尾帧时记录 `video_replace_colored_pencil_keyframes_missing` 结构化日志并抛中文错误，阻断视频提交。
- `backend/matrix_native_client.py#L15322-L15325`: `_run_comic_project_segments()` 在 `comic_colored_pencil_refs` 阶段完成隐藏彩铅预处理后，才进入 `submit_storyboard_video()`。
- `tests/test_video_replacement.py#L773-L901`: 回归覆盖 SD2.0 全能参考触发彩铅链路、视频 payload 优先隐藏彩铅 URL、`gpt-image-2` 被调用且不替换可见首尾帧，以及隐藏彩铅首尾帧缺失时阻断视频。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_prepare_colored_pencil_references_blocks_video_when_keyframes_missing tests.test_video_replacement.VideoReplacementHelpersTest.test_sd20_all_reference_comic_payload_uses_colored_pencil_chain tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_video_payload_prefers_hidden_colored_pencil_references tests.test_video_replacement.VideoReplacementHelpersTest.test_prepare_colored_pencil_references_calls_gpt_image_without_replacing_visible_frames -v` 通过；完整聚焦验证见本次最终交付记录。
- 运行与回滚：本地客户端变更，需重启客户端；已打包 EXE 需要重新构建后用户才能生效。不涉及中心服、远程 AI Canvas、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py` 和本条文档/Changelog 即可恢复。

## 2026-08-01 工作流助手完整视频分析与口播时间轴
- `backend/matrix_native_client.py#L17074-L17239`：工作流助手复用视频分解链路，校验视频后从整条视频抽取关键帧、识别 OCR、按 60 秒分片转写完整音频、调用视觉模型并生成七栏深度报告；关键帧覆盖整条视频时长，音频默认不截断。
- `backend/utils/video_transcription.py#L44-L145`：`VIDEO_TRANSCRIBE_MAX_SEC` 为空时按源视频完整时长构建分片；只有显式设置正数时才截断，并返回实际转写覆盖秒数。
- `backend/matrix_native_client.py#L19878-L19936`：报告保存完整口播时间轴；显式上限时显示真实分析范围，不再固定写“前 10 分钟”。
- `backend/matrix_native_client.py#L16527-L16724`、`backend/matrix_native_client.py#L20141-L20182`：资产库拆解文本与结构化 `transcript.segments` 一起进入同款替换 payload，按时间段生成可编辑 `script`，避免同款替换口播稿为空。
- `backend/matrix_native_client.py#L17242-L17330`、`backend/matrix_native_client.py#L19274-L19355`：每条采集参考视频同时保存可读拆解文本和结构化 JSON sidecar；封面只作为视频 thumbnail/preview 元数据，不单独登记资产。
- `tests/test_workflow_assistant_deep_breakdown.py#L27-L305`、`tests/test_workflow_assistant_helpers.py#L103-L130`：回归覆盖完整时长默认值、完整口播时间轴、显式上限范围、结构化口播到同款替换脚本和资产 sidecar。
- 验证：工作流助手/韧性回归 34/34、音频转写回归 22/22、同款替换口播链路专项 3/3 通过；未执行真实 LK888 视频分析调用。
- 运行与回滚：仅本地客户端、转写工具、测试和文档变更；需重启本地客户端后生效。不涉及 OpenAPI、数据库、Docker、`migration.sql` 或远程服务部署。回滚上述两个源码文件、相关测试和四级文档/变更记录即可恢复旧行为。

## 2026-08-01 同款替换 Seedance 首尾帧彩铅与视频写实风格
- `backend/matrix_native_client.py#L12548-L12572`: 新增 Seedance 风格常量和 `_comic_video_model()` / `_comic_model_is_seedance()` / `_append_prompt_rule()`，只按当前 `comicVideoModel/model` 是否包含 `seedance` 触发。
- `backend/matrix_native_client.py#L12575-L12634`: `_comic_storyboard_video_payload()` 在 Seedance 视频模型下给最终视频 prompt 追加“真人写实风格”规则，并保持 `keyframes_video_prompt/video_prompt/prompt` 三个字段一致。
- `backend/matrix_native_client.py#L12637-L12664`: `_comic_storyboard_image_payload()` 在 Seedance 视频模型下显式设置 `image_model/imageModel=gpt-image-2`，并把首尾帧图片 prompt 覆盖为彩铅手绘风格；图片 payload 不包含“真人写实”，避免首尾帧风格和最终视频风格互相污染。
- `tests/test_video_replacement.py#L722-L767`: 新增两条回归，锁定 Seedance 图片 payload 的 `gpt-image-2 + 彩铅/手绘`，Seedance 视频 payload 的“真人写实”，以及非 Seedance 视频模型不追加该规则。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_seedance_comic_image_payload_uses_gpt_image_colored_pencil_style tests.test_video_replacement.VideoReplacementHelpersTest.test_seedance_comic_video_payload_requests_realistic_style_after_colored_pencil_frames -v` 通过；邻近 prompt 回归 3/3 通过；`.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement.py` 通过。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；无中心服、远程漫剧服务、OpenAPI、数据库、Docker、环境变量或 `migration.sql` 影响。重启本地客户端后生效。

## 2026-08-01 同款替换 LK888 视频提示词动作来源修正
- `backend/matrix_native_client.py#L12024-L12028`: `_comic_person_reference_priority_rule()` 将人物动作来源改为“参考分镜拆解文本和关键帧近似生成”，不再写“只沿用原片人物动作、站位、镜头关系”。
- `backend/matrix_native_client.py#L12078-L12091`: `_comic_asset_binding_prompt()` 保持项目库人物、场景、道具最高优先级；场景文案改为“不得使用原视频场景”，动作/站位/镜头节奏改为参考拆解文本和关键帧，不再暗示 LK888 收到了原片视频。
- `backend/matrix_native_client.py#L12258-L12289`: `_comic_reference_safe_visual_text()` 会把拆解文本中的“沿用原片/保留原片动作/原片站位”改写为分镜文本来源，避免上传女角色但原拆解写男销售时继续污染最终视频 prompt。
- `backend/matrix_native_client.py#L20125-L20279`: 旧同款替换链路的实体替换和手动瑕疵重生提示同步降误导，动作、站位和镜头节奏只参考源视频拆解文本与抽帧结果近似生成。
- `tests/test_video_replacement.py#L698-L721`: 新增 payload 回归，锁定 `_comic_storyboard_video_payload()` 传给 LK888 的 prompt 不含“沿用原片”“原视频只提供”“保留原片动作”“原片站位”，且 payload 仍不传 `sourceVideoUrl/source_video_url`。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_video_prompt_does_not_claim_lk888_receives_source_video_motion tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_storyboard_payload_uses_script_and_keyframes tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_storyboard_payload_keeps_dialogue_out_of_visual_prompt -v` 通过；`.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement.py` 通过。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；无中心服、远程漫剧服务、OpenAPI、数据库、Docker、环境变量或 `migration.sql` 影响。重启本地客户端后生效。

## 2026-08-01 Agent.模式生成提示词中文直传与扣费标签
- `backend/matrix_native_client.py#L1037-L1081`: 新增 Agent.模式账单阶段映射和 `_billing_agent_mode_detail_text()`，账户中心按 `billingScenario=agent_mode` 与 `billingStage` 显示“提示词优化 / 参考图理解 / 模型兼容提示词转换”。
- `backend/matrix_native_client.py#L18566-L18634`: 参考图理解调用 `lk888_vision()` 时携带 `agent_mode/reference_analysis`；`_prodgen_expand_prompt()` 保留为显式模型兼容转换入口，并携带 `agent_mode/prompt_translation`，但默认生成链路不再调用它。
- `backend/matrix_native_client.py#L18636-L18680`: 显式“提示词优化”调用 `lk888_chat()` 时携带 `agent_mode/prompt_optimization`，便于账户中心和 LK888 对账流水区分这类用户主动触发的模型调用。
- `backend/matrix_native_client.py#L18685-L18816`: 新增 `_prodgen_direct_model_prompt()`；图片和视频生成阶段用用户确认的中文 `visiblePrompt/prompt` 加参考图规则、参考图描述和风格方向组装模型 prompt，不再隐藏调用 `_prodgen_expand_prompt()`。
- `tests/test_agent_video_duration.py#L30-L111`: 回归覆盖图片/视频生成中文直传、隐藏扩写不被调用、提示词优化/兼容转换/参考图理解的业务扣费标签。
- `tests/test_account_billing_dashboard.py#L124-L147`: 回归覆盖账户中心三类 Agent.模式提示词阶段的扣费详情文案。
- 验证与回滚：`tests.test_account_billing_dashboard` 26/26 通过，Agent.模式提示词阶段专项 4/4 通过，`py_compile` 通过；当前完整 `tests.test_agent_video_duration` 受同文件内另一路图片模型端点/参数规则未收口改动阻塞。无中心服接口、OpenAPI、数据库、Docker、环境变量或 `migration.sql` 影响；重启本地客户端后生效。回滚 `backend/matrix_native_client.py`、`tests/test_agent_video_duration.py`、`tests/test_account_billing_dashboard.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧生成提示词链路。

## 2026-08-01 Agent.模式图片模型端点路由修复
- `backend/matrix_native_client.py#L2339-L2342`: Agent 图片模型规则新增 `endpoint`，`gemini-3-pro-image-preview` 与 `gemini-3.1-flash-image-preview` 标记为 `media`，避免继续调用不支持它们的 `/v1/images/generations`。
- `backend/matrix_native_client.py#L2397-L2405`: 新增 `_agent_image_endpoint()`，本地已知规则优先；未显式配置但名称匹配 `gemini-*image-preview` 时也走 `media` 兜底，其它图片模型默认走 `images`。
- `backend/matrix_native_client.py#L18704-L18724`: `_prodgen_run_image()` 按 endpoint 路由；`media` 图片模型使用 `lk888_media_task(model, payload, ["png", "jpg", "jpeg", "webp"], tries=150)`，拿到结果 URL 后下载成本地图片；`images` 图片模型保留 `lk888_image()` 同步链路。
- `tests/test_agent_video_duration.py#L136-L165`、`tests/test_agent_video_duration.py#L202-L207`: 回归覆盖 Gemini 图片预览模型必须走 LK888 媒体端点，以及图片规则表中 GPT 与 Gemini 的 endpoint 差异。
- 验证与回滚：新增用例先在旧实现下失败，错误为 Gemini 图片预览模型仍调用 `lk888_image()`；修复后聚焦测试通过。当前未执行真实 LK888 调用；回滚 `backend/matrix_native_client.py`、`tests/test_agent_video_duration.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧端点路由。

## 2026-08-01 账户中心一键刷新
- `backend/matrix_native_client.py#L26912-L26944`: `AccountPage` 标题栏新增固定 100×34 的图标刷新按钮，并初始化余额请求序号与手动刷新状态；忙碌时临时隐藏图标，确保“刷新中...”完整显示且按钮不位移。
- `backend/matrix_native_client.py#L27293-L27374`: 新增三类账单请求的手动刷新协调、完成/取消结构化日志和页面隐藏处理；手动刷新保留日期、筛选、分组和流水页码，自动刷新不触发按钮忙碌态。
- `backend/matrix_native_client.py#L27376-L27465`: 余额请求增加序号；统计、流水的日期校验失败也会完成本轮对应请求，避免按钮永久禁用。
- `backend/matrix_native_client.py#L27590-L27673`: 余额、统计、流水响应接入序号过滤与手动刷新完成态；陈旧响应不覆盖新数据，单项错误继续走现有错误编号和旧数据保留逻辑。
- `tests/test_account_billing_dashboard.py#L206-L335`: 新增刷新按钮、状态保留、成功/错误完成、陈旧响应、最新请求接管、日期校验、忙碌文案宽度和隐藏取消回归。
- 验证：新增行为测试先在旧实现下失败；修复后账户中心 25/25、相关计费/OpenAPI/API/分析测试共 77/77 通过，`py_compile`、`git diff --check` 和 Qt offscreen 几何检查通过。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_account_billing_dashboard.py`、`CHANGELOG.md`、本条记录即可；不涉及 OpenAPI schema、数据库、Docker、环境变量或 `migration.sql`。需要重启本地客户端后生效，未自动重启。

## 2026-08-01 账户中心首屏加载占位
- `backend/matrix_native_client.py#L28361-L28375`: `AccountPage` 新增 `_set_initial_metric_loading()` 和 `_set_ledger_loading_row()`，只在当前值为空、`—` 或 `-` 时写入加载态，避免覆盖已有成功数据。
- `backend/matrix_native_client.py#L28490-L28499`: `load_balance()` 在 analytics 余额尚未成为权威数据前把“云豆余额”设置为“加载中”，防止首屏余额卡片显示成空白/横线。
- `backend/matrix_native_client.py#L28501-L28539`: `load_analytics()` 发起请求前把四个统计卡片写为“加载中”，并通过现有 `_set_request_state()` 显示“正在加载...”，请求结构化日志仍保留 `billing_analytics_request_started`。
- `backend/matrix_native_client.py#L28541-L28570`: `load_ledger()` 发起请求前插入“正在读取扣费明细...”占位行，并显示“正在加载...”；真实响应、错误响应和旧数据保留仍走原有 `_on()` 分支。
- `tests/test_account_billing_dashboard.py#L229-L237`: 新增首屏 loading 回归，mock 掉后台请求返回，锁定 `on_show()` 后余额、统计提示和扣费明细占位立即可见。
- 验证与回滚：新增用例先在旧实现下失败，修复后 `tests.test_account_billing_dashboard` 27/27 与 `py_compile` 通过。本次只影响本地客户端 UI、测试和文档；无中心服接口、OpenAPI、数据库、Docker、环境变量或 `migration.sql` 影响。重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`tests/test_account_billing_dashboard.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-08-01 Agent.模式图片参考图传给 LK888
- `backend/matrix_native_client.py#L18479-L18510`: 新增 `_prodgen_upload_reference_urls()` 与 `_prodgen_image_reference_urls()`，图片模式提交前会把本地上传图逐张通过 `upload_asset_url(..., mtype="image")` 上传为 LK888 可抓取的 HTTP(S) 图片 URL；上传异常或 URL 不可远程抓取时抛出“参考图上传失败”。
- `backend/matrix_native_client.py#L18635-L18679`: `_prodgen_run_image()` 保持“第 1 张为待修改图、第 2 张起为参考图”的顺序规则，但不再把本地文件转成 `data:image/...`，而是把上传后的公网 URL 作为 `image_urls` 传给 `lk888_image()`。
- `backend/matrix_native_client.py#L18687-L18730`: `_prodgen_run_video()` 注释同步为当前行为：视频模式既保留视觉描述作为 prompt 辅助，也上传公网参考图 URL 给 LK888 视频模型。
- `tests/test_agent_video_duration.py#L102-L158`: 新增图片参考图 payload 回归和上传失败阻断回归，覆盖本地图片必须先上传、传给 LK888 图片模型，以及上传失败时不得继续提交生成任务。
- `tests/test_agent_mode_defaults.py#L363-L369`: 更新 Agent 图片模式源码契约，锁定 `_prodgen_image_reference_urls(refs, display_prompt)` 和“第 1 张/第 2 张起”规则。
- 验证与回滚：新增用例先在旧实现下失败，修复后相关测试通过。当前只完成 mock 上传与 payload 回归，未执行真实 LK888 联调；本次无中心服接口、OpenAPI、数据库、Docker、环境变量或 `migration.sql` 影响。重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`tests/test_agent_video_duration.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

## 2026-07-31 分解视频 LK888 实扣对账与任务详情
- `backend/matrix_native_client.py#L945-L999`: 新增分解视频账单阶段映射，优先按 `billingScenario=video_breakdown` 和 `billingStage` 生成“分解视频文本生成 - OCR转写 / 音频提取/口播转写 / 画面理解 / 拆解报告”的任务详情，避免通用 chat 流水误显示为“工作流助手聊天”。
- `backend/matrix_native_client.py#L1874-L1904`、`backend/matrix_native_client.py#L2199-L2228`: `lk888_chat()` 和 `lk888_vision()` 支持发送 `X-Matrix-Billing-Scenario/Stage/Detail` 脱敏业务标签；普通调用不传标签时保持旧行为。
- `backend/matrix_native_client.py#L7449-L7454`、`backend/matrix_native_client.py#L19304-L19319`、`backend/matrix_native_client.py#L24088-L24146`: 分解视频关键帧画面理解标记为 `visual_analysis`，拆解报告生成标记为 `report_generation`，音频分片转写标记为 `audio_transcription`。OCR 仍为本地识别，不调用 LK888、不新增扣费。
- `backend/utils/video_transcription.py#L312-L366`: `transcribe_audio_chunks()` 新增 `billing_context`，向中心服代理请求附加业务场景、阶段和简短说明；不记录或发送 Cookie、Token、Authorization 以外的敏感内容。
- `backend/central_server.py#L1011-L1042`、`backend/central_server.py#L1277-L1305`、`backend/central_server.py#L1428-L1451`: 中心服读取本地业务标签，识别 `/v1beta/models/<model>:generateContent` 的模型名，并把这类音频转写请求登记为 `chat_usage_reconcile` 待对账。
- `backend/central_server.py#L1519-L1520`、`backend/central_server.py#L3800-L3801`、`backend/central_server.py#L3870-L3880`: 异步任务状态结算和 LK888 usage 明细对账时，把 pending 里的 `billingScenario/billingStage/billingDetail` 透传到账单流水；金额仍完全来自 LK888 实际 `cost`，不恢复本地 token 估算。
- `tests/test_account_billing_dashboard.py#L124-L152`、`tests/test_video_transcription.py#L342-L383`、`tests/test_api_download_contract.py#L957-L1030`、`tests/test_api_download_contract.py#L1104-L1143`: 新增回归覆盖分解视频账单文案、音频转写请求标签、`generateContent` 待对账登记和对账后 meta 保留。
- 验证与回滚：新增测试先在旧实现下失败，修复后 `tests.test_account_billing_dashboard` 18/18、`tests.test_video_transcription tests.test_video_breakdown` 64/64、`tests.test_api_download_contract` 42/42 通过，`py_compile` 通过。本次不新增 OpenAPI 路径、数据库字段、Docker 配置、环境变量或 `migration.sql`；重启中心服和本地客户端后生效。回滚上述代码、测试和文档即可恢复旧行为。

## 2026-07-31 抖音评论今日计数与硬门禁
- `backend/api_server.py#L3953-L3979`: 新增抖音评论风控错误码到中文 `message/userMessage` 的映射，后端 `error` 机器码继续保留，覆盖每日上限、评论冷却、风险暂停和浏览器预检安全验证。
- `backend/api_server.py#L4022-L4182`: 抖音评论状态按 `comment_risk_state.json.accounts.<accountId>` 维护，包含当天 `day/commentCount`、最近评论时间、最小间隔冷却、每日评论上限、账号级风险暂停快照，以及命中硬门禁时的 `lastBlocked*` 记录；旧全局 `cooldownUntil` 只在 `lastRiskAccountId` 匹配当前账号时生效。
- `backend/api_server.py#L4185-L4269`: 评论成功后递增账号级 `commentCount` 并写入 `lastCommentAt/lastAction`；平台预检或评论响应命中风险时，把 `paused/pausedUntil/pausedReason/lastRiskReason` 写入同一账号状态，并把 `lastResponse` 脱敏为安全字段和 URL/正文指纹。
- `backend/api_server.py#L4495-L4564`: `publish_comment_to_douyin()` 在 API、自动 UI 回退、强制 `edge-ui` 和 `safeMode=false` 调用前统一执行日上限/冷却/风险暂停硬门禁；`force=true` 只跳过 DOM 预检，不绕过硬门禁。
- `backend/api_server.py#L4626-L4700`: `run_ai_outreach()` 将当前 `accountId` 传入抖音评论链路，遇到 `daily_limit/comment_cooldown/risk_cooldown/risk_paused/preflight_blocked` 立即停止本轮，并把摘要标记为 `ok=false`、中文 `message/userMessage`。
- `backend/api_server.py#L7504-L7521`: `/api/douyin/comment/publish` 复用同一门禁，命中上限、冷却或风险暂停时返回 HTTP 429，同时保留机器 `error` 和中文提示。
- `backend/matrix_native_client.py#L1596-L1659`: 本地客户端任务错误展示优先使用中文 `userMessage/message`，若后端只返回机器码，则把抖音评论相关错误本地化，不再把错误码直接显示给用户。
- `backend/matrix_native_client.py#L18960-L19024`: 风控中心读取 `comment_risk_state.json`，抖音账号“今日评论”显示当天真实 `commentCount/dailyComment`，“冷却”合并最小间隔和当前账号风险暂停剩余秒数，不展示其他抖音账号的风险冷却。
- `backend/matrix_native_client.py#L26332-L26455`: `RiskControlPage` 抖音分支接入账号级评论状态，风险暂停时显示高风险、最近风险原因和等待/人工处理建议。
- `tests/test_douyin_comment_cooldown.py#L64-L497`: 回归覆盖成功计数、每日上限硬拦截、`safeMode=false` 仍拦截、硬门禁写入状态文件、HTTP 429 中文响应、风险暂停写入、平台风险响应暂停、账号级风险隔离、风险响应脱敏、AI 触达停止、风控中心今日评论接入和客户端中文提示。
- 验证与回滚：新增用例先在旧实现下失败，修复后 `tests.test_douyin_comment_cooldown` 18/18 通过；完整回归见最终交付记录。本次不新增数据库迁移、Docker、环境变量或 OpenAPI 路径；重启本地客户端和本地执行器后生效。回滚上述代码、测试和文档即可恢复旧行为。

## 2026-07-31 新用户账号矩阵隐藏无效默认抖音占位
- `backend/api_server.py#L1073-L1088`: 本地执行器 `current_accounts()` 只有在默认抖音 Cookie 真实可用时才返回 `douyin-self`，空数据目录或只有无效默认 Cookie 时不再生成离线占位账号。
- `backend/matrix_native_client.py#L1117-L1124`: 新增 `_is_offline_default_douyin_placeholder()`，识别无在线状态、无 Cookie、无可用性的本地默认抖音占位账号。
- `backend/matrix_native_client.py#L1149-L1150`: `merge_account_sources()` 在无中心账号匹配时过滤上述占位，防止旧本地执行器仍返回 `douyin-self` 时污染账号矩阵。
- `tests/test_douyin_multi_account.py#L67-L70`、`tests/test_native_publish.py#L170-L197`: 回归覆盖新用户空账号目录不返回默认抖音账号，以及客户端合并时只过滤默认占位、不误删真实离线多账号。
- 验证与回滚：新增测试先在旧实现下失败，修复后账号矩阵/抖音多账号相关 70/70 通过，`py_compile` 通过。本次无 OpenAPI、数据库、Docker、环境变量或 `migration.sql` 变更；重启本地客户端和本地执行器后生效。回滚 `backend/api_server.py`、`backend/matrix_native_client.py`、两组测试和本条文档即可恢复旧行为。

## 2026-07-31 账户中心扣费明细业务化展示
- `backend/matrix_native_client.py#L926-L942`: 新增 `_billing_ledger_model_text()`，从账单行的 `model/modelId/model_id/modelName/model_name/capability` 等字段提取模型 ID，避免账户中心模型列频繁显示 `—`。
- `backend/matrix_native_client.py#L944-L999`: 新增 `_billing_ledger_detail_text()`，按 `ref/detail/billingSource/model` 将内部账单流水转换为用户可读任务详情；覆盖数字人、同款替换首帧图/尾帧图/视频/退款、Agent.模式视频生成和工作流助手聊天等场景，并剥离“LK888实际扣费”“漫剧视频生成，项目…”类内部描述。
- `backend/matrix_native_client.py#L26660-L26679`: 账户中心扣费明细表格清空表格和 viewport 的原生 tooltip，关闭末列强制拉伸，改为第 3 列“任务详情”拉伸，其余列按内容自适应，使表格填满右侧可用区域。
- `backend/matrix_native_client.py#L27250-L27270`: 渲染账单行时统一使用 `_billing_ledger_model_text()` 和 `_billing_ledger_detail_text()`，并清空任务详情单元格 `ToolTipRole`，避免鼠标悬停继续显示黑色 Qt tooltip。
- `tests/test_account_billing_dashboard.py#L81-L113`: 新增 helper 回归，锁定模型 ID 提取和任务详情业务化映射。
- `tests/test_account_billing_dashboard.py#L252-L263`: 新增表格列宽策略回归，锁定任务详情列 `Stretch`、其余列 `ResizeToContents`。
- 验证与回滚：新用例先在旧实现下失败，修复后账户中心扣费明细回归和原生 tooltip 策略测试通过；本次只影响本地客户端 UI、测试和文档。重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`tests/test_account_billing_dashboard.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧展示。无 OpenAPI、数据库、Docker、环境变量或 `migration.sql` 影响。

## 2026-07-31 企业中心 KPI 悬浮文案与两行三列布局
- `backend/matrix_native_client.py#L3632-L3639`: 企业中心总览继续固定 6 个 KPI：客户企业、企业用户、授权账号、可用账号、在线节点、调度任务。
- `backend/matrix_native_client.py#L3642-L3680`: 新增 `_enterprise_org_names()` 和 `enterprise_kpi_info()`，让“客户企业”悬浮显示企业名称，“企业用户”显示已加入人数，“在线节点”说明启动、心跳、退出、断网、休眠、切换企业和 45 秒心跳过期等变化时机，“调度任务”显示任务总数。
- `backend/matrix_native_client.py#L4778-L4781`: KPI 网格改为 `i // 3, i % 3`，6 张卡片稳定展示为两行三列，并将动态悬浮说明传给 `kpi_card()`。
- `tests/test_agent_mode_defaults.py#L246-L264`: 新增回归测试锁定企业名称、企业用户数量、在线节点变化说明、调度任务总数文案，以及 3 列布局源码契约。
- 验证与回滚：新用例先在旧实现下因缺少 `enterprise_kpi_info()` 失败，修复后企业中心相关 54/54 通过，`py_compile` 通过。本次只影响本地客户端 UI、测试和文档；无 OpenAPI、数据库、Docker、环境变量或 `migration.sql` 变更。重启本地客户端后生效；回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py` 和本条文档即可恢复旧行为。

# 2026-07-31 Agent.模式视频参考图传给 LK888
- `backend/matrix_native_client.py#L17925-L17945`: 新增 `_prodgen_video_reference_urls()`，把 Agent 视频模式上传的本地图片逐张通过 `upload_asset_url(..., mtype="image")` 上传成远程模型可读取的 HTTP(S) 图片 URL；上传失败或返回不可抓取 URL 时抛出“参考图上传失败”，不继续提交视频任务。
- `backend/matrix_native_client.py#L18113-L18166`: `_prodgen_run_video()` 保留原有多图视觉描述作为 prompt 辅助，但在调用 `lk888_media_task()` 前会把上传后的参考图 URL 写入 `image_urls/images/reference_images/referenceImages/reference_image_urls`，并同步写入 `params.images/params.image_urls/params.reference_images`，让 LK888 视频模型直接收到用户上传图片。
- `tests/test_agent_video_duration.py#L130-L194`: 回归覆盖 1-4 张 Agent 视频参考图进入 LK888 视频 payload 的兼容字段，以及参考图上传失败时不提交 LK888 视频任务。
- TDD 与验证：新增测试先在旧实现下失败，分别暴露视频 payload 缺少 `image_urls` 和上传失败不会阻断提交；修复后 `tests.test_agent_video_duration` 8/8、`tests.test_agent_mode_defaults` 31/31 通过。
- 运行与回滚：本次只影响本地客户端 Agent.模式视频参考图提交链路，需重启本地客户端后生效；不改变中心服接口形状、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_agent_video_duration.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧的纯文字视频提交行为。

# 2026-07-31 企业中心数据悬浮说明
- `backend/matrix_native_client.py#L3372-L3466`: 新增 `HoverInfoPopup`、`_HoverInfoFilter` 和 `attach_hover_info()`，用自绘悬浮信息卡替代 Qt 原生 tooltip，悬浮位置会按当前屏幕可用区域做边界收敛。
- `backend/matrix_native_client.py#L3520-L3540`: 新增 `ENTERPRISE_METRIC_HELP`，集中维护企业中心 KPI 和面板统计口径说明。
- `backend/matrix_native_client.py#L3833-L3908`: `kpi_card()` 与 `Panel` 支持 `info` 参数，角落增加轻量 `i` 标记并绑定自定义悬浮说明。
- `backend/matrix_native_client.py#L4633-L4657`: 企业中心 KPI 网格和“任务趋势 / 运行健康 / 账号分布”面板传入对应说明文案。
- `backend/matrix_native_client.py#L26562-L26935`: 账号中心遗留非空 `setToolTip(...)` 清理；图标按钮改接自定义悬浮说明，状态标签和账单明细单元格清空原生 tooltip。
- `tests/test_agent_mode_defaults.py#L210-L226`: 新增源码回归测试，锁定企业中心说明文案表、自定义悬浮组件和实际接入点。
- `tests/test_native_tooltips.py#L10-L33`: 全局策略测试继续禁止本地客户端新增任何非空 `setToolTip(...)`。
- 验证与回滚：新测试先在旧实现下失败，修复后定向 2/2 通过；本次仅本地客户端 UI、测试和文档变化，重启本地客户端后生效。回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为；无 OpenAPI、数据库、Docker、环境变量或 `migration.sql` 影响。

# 2026-07-31 分解视频口播稿去除相邻重叠
- `backend/utils/video_transcription.py#L196-L229`: 新增 `remove_adjacent_text_overlap()`，用压缩空白后的相邻文本做最长后缀/前缀匹配；`merge_transcription_segments()` 在生成全局时间轴前删除后一段重复前缀，保留时间戳和非重复正文。
- `backend/matrix_native_client.py#L39`、`backend/matrix_native_client.py#L19294-L19315`: 本地客户端复用同一去重函数；同款替换从 `breakdownAnalysis.transcript.segments` 聚合每个片段口播稿时，会按上一片段最终口播稿清理下一片段开头重复内容。
- `tests/test_video_transcription.py#L246-L274`: 回归复现转写块之间重复“就这个法汀妮的粉底液...”时，合并结果只保留一次重复句。
- `tests/test_video_replacement.py#L1415-L1453`: 回归复现同款替换 3 个片段口播稿相邻重叠，断言第二、第三段不再带上一段尾部重复句。
- 验证：新增两项回归先在旧实现下失败，修复后通过；`tests.test_video_transcription` 21/21、`tests.test_video_replacement` 95/95、`tests.test_video_breakdown` 42/42 通过；`py_compile` 通过。
- 运行与回滚：本次仅本地客户端和转写工具变化，不涉及中心服、远程漫剧服务、OpenAPI、数据库、Docker、环境变量或 `migration.sql`；按用户要求不自动重启，用户手动重启本地客户端后生效。回滚上述文件即可恢复旧行为。

## 2026-08-01 同款替换 Seedance 彩铅首尾帧与单模型执行
- `backend/matrix_native_client.py#L12594-L12681`: 新增 `_COMIC_SEEDANCE_FRAME_IMAGE_MODEL`、`_COMIC_SEEDANCE_COLORED_PENCIL_IMAGE_STYLE` 与 `_COMIC_SEEDANCE_REALISTIC_VIDEO_STYLE`；Seedance 视频模型下，首尾帧图走 `gpt-image-2` 彩铅风格，视频 prompt 追加“真人写实风格”。
- `backend/matrix_native_client.py#L12683-L12735`: `_comic_storyboard_image_payload()` 给 Seedance 首尾帧写入 `image_model/imageModel/frame_style_mode/frameStyleMode`，并保留彩铅提示；`_comic_storyboard_video_payload()` 只在 Seedance 视频模型下追加写实要求。
- `backend/matrix_native_client.py#L12804-L12849`: `_comic_project_video_model_candidates()` 现在只返回用户当前选择的模型；`_comic_task_progress_message()` 和 `_comic_task_failure_message()` 不再暗示“已切备用模型”，Seedance 拒绝会直接转成中文失败原因。
- `backend/matrix_native_client.py#L14959-L15177`: `_run_comic_project_segments()` 记录 `comicVideoFallbacks` 只作诊断，不再继续提交其他模型；用户选 Seedance 就只跑 Seedance，失败直接结束片段。
- `tests/test_video_replacement.py#L726-L1404`: 回归覆盖 Seedance 首尾帧彩铅 payload、Seedance 视频写实 prompt、单模型执行和 PolicyViolation 中文失败提示。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement tests.test_aicanvas_frame_billing tests.test_aicanvas_real_person_fallback -v` 通过 160/160；`py_compile` 通过。
- 运行与回滚：本次只改本地客户端与远程漫剧镜像的同款替换链路及测试/文档，不涉及中心服、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。本地客户端需重启后生效；远程 AI Canvas 还需要单独部署 `server_current.py`/`server.py` 并重启服务后才会真正取消 fallback。回滚上述文件即可恢复旧行为。

# 2026-07-31 同款替换前端隐藏错误编号
- `backend/matrix_native_client.py#L9292-L9336`: 新增 `_replacement_display_text_without_error_id()` 并调整 `_localize_replacement_display_text()`，展示层会剥离 `错误编号 err-*`，已知错误码翻译成中文，未知上游错误保留实际 `message/detail/status` 内容，不再替换成“生成失败，请根据错误编号查看日志”。
- `backend/matrix_native_client.py#L9338-L9363`: `_replacement_segment_display_error()` 优先返回 `error/remoteError/facefusionError` 的可读内容；只有任务只有编号没有正文时才显示“生成失败，请重试或查看日志。”，编号继续留在任务 JSON 和结构化日志里。
- `backend/matrix_native_client.py#L2510-L2585`、`backend/matrix_native_client.py#L2851-L2875`、`backend/matrix_native_client.py#L10245-L10273`、`backend/matrix_native_client.py#L15044-L15066`：视频预览、片段状态栏、视频格子和最终弹窗同步改为可读错误，不再把错误编号直接渲染到前端。
- `tests/test_video_replacement_v2.py#L743-L754`、`tests/test_video_replacement_v2.py#L889-L907`、`tests/test_video_replacement_v2.py#L1079-L1105`、`tests/test_video_replacement_v2.py#L5272-L5364`、`tests/test_video_replacement_v2.py#L5755-L5779`: 回归覆盖本地视频无效、远程错误、已知错误码翻译和真实上游 `message` 透出，同时断言前端不包含 `错误编号` 或 `err-*`。
- 验证：先运行新增/调整用例观察旧实现 6 failures，修复后聚焦 10/10 通过；`py_compile` 与 diff 检查见最终交付结果。
- 运行与回滚：本次只影响本地客户端展示层和测试，不改中心服、远程漫剧服务、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。按用户要求不自动重启本地客户端；回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py` 和本条文档即可恢复旧展示。

# 2026-07-31 工作流助手采集视频基础信息展示
- `backend/matrix_native_client.py#L16096-L16162`: 新增 `_assistant_reference_info_lines()`，从采集结果对象读取平台、作者、点赞数、评论数、收藏数、分享数、时长、作品链接和本地参考视频文件名，统一格式化为聊天页可读信息。
- `backend/matrix_native_client.py#L16168-L16196`: `_assistant_build_direct_breakdown_reply()` 在每条“视频 N”标题后插入基础信息块，再显示拆解文本和“如何拍出同等价值的视频”，不改变采集、下载、视频理解或同款替换 payload 契约。
- `tests/test_workflow_assistant_helpers.py#L19-L161`: 回归测试覆盖工作流助手回复必须展示作者、点赞/评论/收藏/分享、时长、链接和本地文件名；旧实现下缺少 helper 和基础信息块，测试先失败，修复后通过。
- 运行与回滚：仅本地客户端展示层变更，需重启本地客户端后生效；不涉及本地执行器接口、中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_workflow_assistant_helpers.py` 和本次文档记录即可。

# 2026-07-31 分解视频支持直接粘贴链接
- `backend/matrix_native_client.py#L18189-L18194`: 新增 `_video_breakdown_platform_from_url()`，按链接域名识别小红书 `xiaohongshu.com/xhslink.com`，其它链接默认走抖音下载链路。
- `backend/matrix_native_client.py#L6789-L6925`: `VideoBreakdownPage` 顶部新增链接输入框和“下载并分解”按钮；点击后后台调用 `submit_local_task(<platform>.download)`，下载完成后通过 `video_breakdown_start` 复用现有视频校验、抽帧、OCR、口播转写和报告生成流程。
- `backend/matrix_native_client.py#L6856-L6882`: 新增 `video_breakdown_link_download` 事件处理，下载失败、本地执行器失败、账号失效或未找到视频文件时直接在分解视频页显示错误；下载成功时携带 `platform/sourceUrl/videoPath/download` 进入现有分解入口。
- `tests/test_video_breakdown.py#L1010-L1031`: 新增回归覆盖页面直链入口、下载任务调用、分解事件复用，以及抖音/小红书链接平台识别。
- TDD 与验证：新增测试先在旧实现下失败，暴露缺少链接入口和 `_video_breakdown_platform_from_url()`；实现后 `tests.test_video_breakdown` 42/42 通过。
- 运行与回滚：仅本地客户端分解视频入口变更，需用户手动重启本地客户端后生效；不涉及中心服、远程服务、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_video_breakdown.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧页面。

# 2026-07-31 Agent.模式 LK888 模型对应关系规则完善
- `backend/matrix_native_client.py#L2086-L2121`: `_LK888_FALLBACK_MODELS` 不再只是兜底显示列表，而是 Agent.模式本地权威模型规则表；已知模型绑定真实 LK888 模型标识、用户可读显示名、`image/video` 类型和视频 `duration_slots`。前端仍不展示真实模型 ID。
- `backend/matrix_native_client.py#L2124-L2169`: 新增 `_agent_model_rule()`、`_agent_model_for_type()` 和 `_agent_video_duration_slots()`；图片任务遇到已知视频模型会退回默认图片模型，视频任务遇到已知图片模型会退回默认 Seedance 视频模型，Vidu Q3 系列提交时长固定规范化为 8 秒。
- `backend/matrix_native_client.py#L2361-L2368`: `_lk888_canonical_model_row()` 命中本地已知模型时合并完整本地规则，LK888 在线目录不能把 Seedance 改名成 GPT/Seedream，也不能把视频模型错分到图片列表。
- `backend/matrix_native_client.py#L17760-L17846`: `_prodgen_run_image()` 和 `_prodgen_run_video()` 在调用 LK888 前都会先做模型类型规范化，并把规范化后的模型和显示名写回生成记录。
- `backend/matrix_native_client.py#L24227-L24239`: Agent 视频时长按钮改为按当前视频模型规则同步；Vidu Q3 / Vidu Q3 Turbo 显示固定 8 秒，Seedance 1.5 Pro 保留 5/10 秒切换。
- `tests/test_agent_video_duration.py#L31-L131`: 回归覆盖 Vidu Q3 8 秒、视频任务拒绝图片模型状态、图片任务拒绝视频模型状态、本地规则表存在，以及 LK888 目录错配不能覆盖本地权威规则。
- TDD 与验证：新增测试先在旧实现下失败，分别暴露 `gpt-image-2` 被提交到视频任务、Seedance 被提交到图片任务、缺少 `_agent_model_rule()` 和已知模型缺少 `duration_slots`；修复后 `tests.test_agent_video_duration` 6/6、`tests.test_agent_mode_defaults` 29/29 通过。
- 运行与回滚：本次只影响本地客户端 Agent.模式模型映射、参数规范化和 UI 时长显示，需重启本地客户端后生效；不涉及中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_agent_video_duration.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为。

# 2026-07-31 本地客户端 LK888 扣费四位小数显示
- `backend/matrix_native_client.py#L3845-L3855`: `_billing_amount()` 从 `float + %.2f` 改为 `Decimal` 四位量化后去尾零，非有限值继续显示 `—`，精确字符串 `"inf"` 继续显示运营方无限余额；`-0.0000` 和四位量化后的负零统一显示为 `0`。
- `backend/matrix_native_client.py#L26543-L26558`: 账户中心账单表格的实扣/变动金额继续复用 `_billing_amount()`，因此 LK888 返回的 `0.0016`、`0.0222`、`0.0340` 等实际扣费不会在本地表格中被压成两位或 `-0`。
- `tests/test_account_billing_dashboard.py#L75-L79`、`tests/test_account_billing_dashboard.py#L177-L199`: 回归覆盖 helper 四位小数、负零处理，以及账单表格中 `change=-0.0016` 和 `balanceAfter=9.9984` 的真实渲染。
- TDD 与验证：新增测试先在旧实现下失败，错误为 `-0.0016` 显示成 `-0`、`12.3456` 显示成 `12.35`；修复后账户中心账单回归 14/14 通过，并通过 LK888 实际扣费中心服聚焦用例确认结算路径没有两位取整。
- 运行与回滚：本次只影响本地客户端显示层，需重启本地客户端后生效；不涉及 OpenAPI、数据库、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_account_billing_dashboard.py` 和本条文档/Changelog 即可恢复旧两位显示。

# 2026-07-31 Agent.模式 Vidu Q3 视频时长参数修复
- `backend/matrix_native_client.py#L2121-L2134`: 保留 Agent 视频界面通用 `5/10` 秒时长选择，同时新增 `_agent_video_request_duration(model, value)`；当模型 ID 以 `viduq3` 或 `vidug3` 开头时，提交前统一规范化为 LK888 当前可接受的 8 秒。
- `backend/matrix_native_client.py#L17770-L17804`: `_prodgen_run_video()` 先确定视频模型，再用 `_agent_video_request_duration()` 计算实际提交时长，并把规范化后的时长写回生成记录和 LK888 `params.duration`。
- `tests/test_agent_video_duration.py#L1-L58`: 回归覆盖 `viduq3` 在界面时长为 5 秒时，实际提交 payload 使用 `duration=8`，且 Seedance 等其他模型仍保留通用选择链路。
- TDD 与验证：新增 Vidu Q3 时长测试先在旧实现下失败，证明旧代码会提交 `duration=5`；修复后该测试通过。完整验证见最终交付结果。
- 运行与回滚：仅本地客户端 Agent 视频参数层变更，需重启本地客户端后生效。回滚 `backend/matrix_native_client.py`、`tests/test_agent_video_duration.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为；无中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql` 影响。

# 2026-07-31 Windows start-visible-client central restart
- `start-visible-client.bat#L31`: startup now calls `:restart_central` before the first `:check_central`, so an already-healthy old 9080 process is not reused.
- `start-visible-client.bat#L59-L67`: `:restart_central` scans `netstat -ano` for `:%CENTRAL_PORT% ... LISTENING`, force-stops matching PIDs with `taskkill /F /PID`, waits one second, then lets the existing central startup and health-check flow launch the current `backend/central_server.py`.
- `tests/test_start_visible_client_script.py#L11-L19`: regression coverage locks the restart call order and the netstat/taskkill/port contract.
- Verification: the new script test first failed against the old script because `call :restart_central` was missing, then passed after the script update. Focused LK888 postpaid tests also passed, confirming the startup change does not alter billing logic.
- Runtime and rollback: double-clicking `start-visible-client.bat` now restarts the center server and then opens the local client. Rollback restores the previous script and removes `tests/test_start_visible_client_script.py`; no OpenAPI, database, Docker, environment-variable, or `migration.sql` change is involved.

# 2026-07-31 工作流助手对话式热点视频拆解
- `backend/matrix_native_client.py#L15366-L15370`: 账号切换后的本地状态重载不再读取旧 `workflows.json`，避免历史自动化工作流在新模式下继续影响页面状态。
- `backend/matrix_native_client.py#L15448-L15664`: 新增 `WF_ASSISTANT_SYSTEM`、`_assistant_guess_collect_request()`、`_reference_breakdown_to_replacement_payload()`、`_assistant_reference_replacement_payloads()`、`_assistant_build_direct_breakdown_reply()` 和 `run_workflow_assistant_request()`；助手只追问或直接执行采集/拆解，不输出工作流 JSON，不把采集原视频作为可发布素材。拆解结果会被包装成 `video_replace_start` 兼容 payload。
- `backend/matrix_native_client.py#L16328-L16459`: `AgentChatPage` 改为“热点视频拆解助手”，发送消息后直接调用 `run_workflow_assistant_request(..., include_payloads=True)`，通过 `workflow_assistant_status/workflow_assistant_reply` 在当前聊天页显示状态和最终拆解文本，并为每条参考视频展示“按这条改造生成”按钮；按钮发送 `goto_nav=🧬 同款替换` 和 `video_replace_start`。
- `backend/matrix_native_client.py#L24904-L24952`: 资产库采集参考视频的文本弹窗按钮从“用此文本生成视频”改为“按此视频改造”，读取绑定拆解文本后调用 `_reference_breakdown_to_replacement_payload()` 并进入 `同款替换`，不再发送 `breakdown_to_product_video` 或跳转 `Agent.模式`。
- `backend/matrix_native_client.py#L26518-L26543`、`backend/matrix_native_client.py#L28149-L28182`: 侧边栏移除“自动化工作流”页面入口；登录完成后不再启动旧 `_start_scheduler()` 定时工作流调度。
- `tests/test_workflow_assistant_direct_mode.py#L57-L64`、`tests/test_workflow_assistant_helpers.py#L48-L101`、`tests/test_asset_library_shared_button.py#L192-L205`: 回归覆盖助手动作卡进入同款替换、拆解包符合 `video_replace_start` 契约、资产库文本入口不再进入 `Agent.模式`。
- `tests/test_workflow_assistant_direct_mode.py#L36-L75`、`tests/test_workflow_account_scope.py#L70-L73`、`tests/test_workflow_resilience.py#L468-L472`、`tests/test_login_centered_layout.py#L31-L37`: 回归覆盖旧入口消失、助手不再生成/保存工作流、旧调度不启动、直接助手提示规则和登录页文案。
- 验证：先补测试并确认旧实现失败；实现后聚焦助手/资产库/同款替换相关回归与 `python -m py_compile backend\matrix_native_client.py` 通过。
- 运行与回滚：仅本地客户端层变更，需重启本地客户端后生效；不涉及中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、相关测试和三份文档即可恢复旧自动化工作流入口与编排链路。

# 2026-07-31 同款替换漫剧素材优先提示词
- `backend/matrix_native_client.py#L11135-L11203`：`_comic_person_reference_priority_rule()` 与 `_comic_asset_binding_prompt()` 改为“上传素材最高优先级、原视频只提供动作/站位/镜头/节奏”，并追加不要生成字幕、对白文字、促销文字或复刻原片实体的约束。
- `backend/matrix_native_client.py#L11205-L11287`：新增 `_comic_motion_entity_terms()` 和 `_comic_clean_motion_action()`，从原片拆解字段中只保留动作表达；上传道具存在时，把动作里指向原片产品、原片道具或通用商品部位的词替换为“上传道具”。
- `backend/matrix_native_client.py#L11244-L11331`：`_comic_uploaded_asset_motion_prompt()` 在上传人物/场景/道具时只输出 `项目库角色“主角”`、`项目库场景“场景1”`、`项目库道具“道具1”` 以及清洗后的动作、节奏、景别，不再把原片人物、产品、道具、场景字段原文传给漫剧生成器。
- `backend/matrix_native_client.py#L11440-L11461`：`_comic_segment_script_line()` 不再向项目 `source_text` 写入 `对白：<口播稿>`；口播稿继续只通过 TTS/audio 字段进入配音链路，避免画面剧本和远程模型 prompt 被台词污染。
- `backend/matrix_native_client.py#L11579-L11627`：`_comic_storyboard_video_payload()` 除首尾帧外，同步携带 typed reference fields，并新增负向提示，确保视频生成阶段也能看到上传人物、场景和道具的分类参考，不再只依赖文字描述。
- `tests/test_video_replacement.py#L1568-L1718`：更新并新增回归，覆盖项目剧本不带台词、远程模型 prompt 只使用上传素材和动作、视频 payload 带 typed refs，且不包含原片男销售、服装、凯美瑞、汽车展厅、OCR 或原片拆解证据。
- TDD 与验证：新素材优先测试在旧实现下失败，证明 `source_text` 仍含 `对白` 且画面提示词混入台词；实现后 `tests.test_video_replacement` 93/93 通过。未调用真实远程模型。
- 运行与回滚：仅本地客户端提示词拼装逻辑变更，需用户手动重启本地客户端后生效。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为；无中心服、远程漫剧服务、数据库、OpenAPI、Docker、环境变量或 `migration.sql` 影响。

# 2026-07-31 本地客户端任务中心表格样式与时间显示
- `backend/matrix_native_client.py#L4063-L4086`：新增 `_task_center_time_text()`，优先显示中心服已有的 `updatedAtText/createdAtText/timeText`；当接口只返回 `updatedAt/createdAt/finishedAt/startedAt` 数值时间戳时，兜底格式化为 `MM-DD HH:MM`，并兼容毫秒时间戳。
- `backend/matrix_native_client.py#L5777-L5820`：任务中心表格改用统一 `style_table(self.table)`，关闭默认单元格网格线，保持整行选择和其他本地客户端表格视觉一致；时间列改为 `_task_center_time_text(t)`，避免最近任务有时间戳但页面为空。
- `tests/test_agent_mode_defaults.py#L158-L188`：新增回归测试，覆盖任务中心表格必须复用统一样式、文本时间优先、数值时间戳可格式化显示。
- TDD 与验证：生产代码修改前，表格样式测试因缺少 `style_table(self.table)` 失败，时间测试因缺少 `_task_center_time_text()` 失败；实现后定向 3/3 通过。完整相关回归与编译检查见最终回复。
- 运行与回滚：仅本地客户端显示层变更，需重启本地客户端后生效。回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py` 和本次三份文档记录即可恢复旧显示；无 Web、中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql` 影响。

# 2026-07-31 同款替换取消声音验证
- `backend/matrix_native_client.py#L14104-L14140`：当前漫剧自动声音任务的最终合成只使用片段状态、人工确认、视频有效性和保留的视觉质量门禁；完成任务清理历史 `audioCheck` 并记录 `audioValidation=disabled`，页面进度不再宣称正在执行声音检查。
- `backend/matrix_native_client.py#L20122-L20150`：FaceFusion 输出无音轨且前序视频也无音轨时直接保留无声视频；只有前序视频确有音轨时才执行兼容性音轨回填，FFmpeg 回填失败仍按功能失败处理。
- `backend/matrix_native_client.py#L20603-L20633`：AI 配音或上传配音混音只校验输入存在、视频时长、FFmpeg 返回值和输出视频有效性，不再比较配音覆盖时长，也不再检查输出音轨、静音或音量。
- `backend/matrix_native_client.py#L21229-L21335`：片段质检保留视频有效性、审核帧和视觉质检，声音检查固定记录为 `status=skipped/code=disabled`、`checks.audio=skipped`。
- `backend/matrix_native_client.py#L21794-L21826`：漫剧自动声音任务的最终门禁不再读取 `hasAudio`、`audioStatus` 或历史 `qcStatus`，但仍要求片段完成、人工确认且本地视频有效；其他模式继续保留非声音质量门禁。
- `backend/matrix_native_client.py#L22667-L22701`：片段合成及上传完整配音后的最终输出不再调用声音质量检查；片段缺失、视频损坏、混音命令失败仍会停止合成。
- `tests/test_video_replacement.py#L2927-L2969`、`tests/test_video_replacement_v2.py#L2536-L2553`、`tests/test_video_replacement_v2.py#L3203-L3216`、`tests/test_video_replacement_v2.py#L4412-L4421`：覆盖历史声音状态不阻断、无音轨可合成但损坏视频仍阻断、片段质检跳过声音、合成不复查声音及人工确认/失败状态门禁。
- TDD 与验证：上述 5 项在生产代码修改前为 5 failures，修改后 5/5 通过；`tests.test_video_replacement` 92/92 通过。V2 完整套件保留改动前已存在的 5 failures + 2 errors 基线；未调用真实远程模型。
- 运行与回滚：仅本地客户端需要用户手动重启后生效。回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`tests/test_video_replacement_v2.py` 和本次三份文档记录即可恢复旧门禁；无中心服、远程服务、数据库、OpenAPI、Docker、环境变量或 `migration.sql` 影响。

# 2026-07-31 抖音详情接口连接重试与脱敏失败契约
- `backend/dy_apis/douyin_api.py#L20-L30` 定义固定连接/读取超时、退避间隔和稳定异常类型；`backend/dy_apis/douyin_api.py#L121-L185` 在作品详情请求中仅重试连接及超时异常，最多执行 4 次请求，不改变 HTTP 业务响应和 JSON 解析行为。
- `backend/api_server.py#L3569-L3597` 生成作品编号指纹、固定主机、尝试次数、异常类型和超时参数组成的脱敏 JSON 日志；`backend/api_server.py#L7399-L7438` 将最终详情网络失败归一化为 HTTP 502、`douyin_detail_network_failed`、`stage=detail` 和安全 `errorId`，响应不返回原始异常或堆栈。
- `backend/matrix_native_client.py#L6671-L6681` 使用统一分解下载失败文案；`backend/matrix_native_client.py#L17685-L17706` 将稳定错误码精确映射为“抖音连接暂时失败，请重试”，其他历史错误继续使用原提示。
- `tests/test_douyin_detail_retry.py#L31-L97` 覆盖临时失败恢复、固定 `(8, 15)` 超时、`1/2/4` 秒退避、4 次失败和 HTTP 业务响应不重试；`tests/test_api_download_contract.py#L85-L132` 覆盖 502 契约及作品编号、签名、Token、Cookie 脱敏；`tests/test_video_breakdown.py#L78-L82` 锁定页面完整中文文案。
- Phase 0/TDD：生产代码修改前运行上述 5 项测试，结果为 1 failure、3 errors，分别证明缺少重试异常、接口契约和中文映射；实现后同一组测试 5/5 通过。
- 回滚：恢复上述三个生产文件、三组测试及本次 API/排障/变更文档即可。无数据库、中心服、Docker、环境变量或 `migration.sql` 变更；按用户要求未自动重启任何进程。

# 2026-07-30 抖音全自动回复会话、账号与隐私边界加固
- `backend/matrix_native_client.py#L5480-L5493`：小红书线索禁止进入当前仅支持抖音主页的私信 MVP；抖音线索继续携带获客中心选中的 `accountId`。
- `backend/matrix_native_client.py#L7488-L7629`：`DMPage` 引入会话代次；编辑客户主页时立即关闭全自动、清空旧客户待回复/发送中/去重状态和输入内容，迟到的收件、AI 和发送事件按代次、目标及账号丢弃。
- `backend/matrix_native_client.py#L7869-L7937`、`backend/matrix_native_client.py#L7954-L8009`：手动发送、自动发送和收件轮询都直连本机 `9081`；成功事件不再误带 `http_200`。首次成功收件会锁定实际账号，后续收发账号不一致时停止自动处理。
- `backend/api_server.py#L406-L416`、`backend/api_server.py#L1504-L1556`：中心复合账号 ID 归一化成本机账号 ID；收件浏览器按账号加锁，并使用 `dy_dm_profile/accounts/<localAccountId>/current` 稳定隔离，默认账号保留 `dy_dm_profile/current` 兼容路径。
- `backend/api_server.py#L1809-L1821`、`backend/api_server.py#L2908-L3181`：浏览器异常生成脱敏 `errorId` 和安全堆栈，不返回子进程标准输出/错误或客户链接；空会话返回 `ok=true/messages=[]/empty=true`。
- `backend/api_server.py#L4360-L4387`、`backend/api_server.py#L7199-L7250`：私信发送/收件统一状态码为成功 200、无效目标 400、登录失效 401、内部浏览器异常 500，异常响应不再暴露原始堆栈。
- `backend/central_server.py#L763-L818`、`backend/central_server.py#L850-L878`、`backend/central_server.py#L13517-L13549`、`backend/central_server.py#L13770-L13803`：中心兼容任务的发送目标、正文和发送结果只持久化/公开其指纹；只有领取排队任务的本地执行器可在内存中读取原始参数。
- `docs/openapi.yaml#L339-L374`、`docs/openapi.yaml#L1586-L1675` 与 `docs/API_REFERENCE.md#L670-L754`：记录目标别名、账号 profile 隔离、空会话成功、HTTP 状态和脱敏边界，删除 `dm_inbox_messages_not_found` 错误枚举。
- `tests/test_douyin_dm_auto_reply.py#L157-L242`、`tests/test_douyin_dm_auto_reply.py#L385-L488`、`tests/test_douyin_dm_auto_reply.py#L816-L844`、`tests/test_finder_page_actions.py#L132-L140`、`tests/test_openapi_contract.py#L123-L151`：覆盖状态码、脱敏日志、账号目录、客户切换、迟到事件、本机直连、账号锁定、中心持久化、XHS 门禁和 OpenAPI 契约。
- 验证：新增成功事件和空会话契约断言均先失败后通过；完整私信模块 72/72、获客页面 10/10、OpenAPI 契约 6/6 通过，三层源码与相关测试 `py_compile` 退出 0。既有 `utils/dy_util.py` 未关闭文件 `ResourceWarning` 和 `api_server.py` 两条无效转义 `SyntaxWarning` 仍存在，未由本次改动引入。
- 运行与回滚：本地客户端/执行器必须重启后加载新代码；中心隐私加固需中心服后续按发布流程部署。回滚本节列出的三层源码、三组测试、OpenAPI/API 文档及本次变更记录即可；不涉及数据库、Docker、环境变量或 `migration.sql`。

# 2026-07-30 小红书真实浏览器冒烟与账号默认口径统一
- 真实冒烟：使用 `backend/datas/accounts/boss/xhs_profile` 跑小红书搜索、下载、评论、获客寻客和图文发布 dry-run。`xhs_profile_ready=true`，但搜索页面实际停在 `https://www.xiaohongshu.com/explore?source=tourist_search`，页面仍显示登录入口，搜索返回 0；下载和评论因无笔记无法继续；获客寻客返回 0；发布 dry-run 返回 `xhs_creator_login_required`，未点击真实发布。
- `backend/platform_adapters.py#L484-L505`：新增 `_xhs_apply_search_login_state()`，账号模式搜索未验证且落到游客推荐流或登录提示页时返回 `xhs_login_required/needLogin=true`，不再伪装为成功 0 条。
- `backend/platform_adapters.py#L855-L855`：`xhs_search_notes()` 在写入调试快照和风险判断后调用账号登录态校验，保留 `debug.screenshot/html` 用于追溯。
- `backend/api_server.py#L7164-L7179`、`backend/api_server.py#L7314-L7329`：`/api/xhs/search` 和 `/api/xhs/download` 默认改为 `guestMode=false`，与客户端“账号矩阵登录态优先”口径一致；未传 `accountCollectionConfirmed=true` 时由账号采集门禁拒绝。
- `tests/test_api_download_contract.py#L110-L154`、`tests/test_xhs_lead_filtering.py#L65-L97`：新增/更新回归，覆盖搜索默认账号确认门禁、确认后账号模式调用、账号搜索落游客推荐流时要求重新登录，以及显式游客模式仍保持游客受限契约。
- `docs/API_REFERENCE.md#L245-L256`、`docs/openapi.yaml#L1207-L1219`、`docs/openapi.yaml#L1676-L1686`：小红书采集通用字段改为全部默认账号模式，OpenAPI 同步允许 `guestMode/accountCollectionConfirmed/accountId`。
- 验证与回滚：新增/修改测试先失败后通过；完整回归见本次交付验证。回滚可恢复 `backend/api_server.py`、`backend/platform_adapters.py`、`tests/test_api_download_contract.py`、`tests/test_xhs_lead_filtering.py`、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/TROUBLESHOOTING.md`、`CHANGELOG.md` 和本节文档；不涉及数据库迁移、Docker 或 `migration.sql`。

# 2026-07-30 同款替换口播识别失败提示与重试入口
- `backend/matrix_native_client.py#L12475-L12480`: 同款替换源视频栏新增“重试口播”短按钮，默认禁用，载入分解结果后仅在 `transcript.failedRanges` 非空时启用。
- `backend/matrix_native_client.py#L12791-L12825`: `VideoReplacementPage._on()` 新增口播重试进度和完成事件处理；成功或失败都会回写 `_source["breakdownAnalysis"]`，已有任务会同步保存到 `replacement_job.json`。
- `backend/matrix_native_client.py#L12947-L13050`: `load_source()` 在口播转写失败时直接显示“口播识别失败”提醒；`retry_source_transcription()` 复用 `_transcribe_breakdown_audio()` 和 `_merge_transcription_retry()`，只重试失败时间段，不重新下载、抽帧或 OCR。
- `backend/matrix_native_client.py#L17962-L17985`: 新增 `_replacement_transcription_retry_ranges()` 和 `_replacement_transcription_issue_text()`，统一把 `remote_timeout` 等失败码转为用户可读提示。
- `tests/test_video_replacement_v2.py#L5160-L5241`: TDD 覆盖失败提醒文案和重试成功后源分析/任务 JSON 回写。
- 验证：新增两项测试先在旧实现下失败，修复后通过；`py_compile` 通过。完整 `tests.test_video_replacement_v2` 的 5 failures + 2 errors 为既有 XHS 测试夹具和旧原片声音断言，不属于本次改动。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。本次不涉及中心服、远程漫剧服务、OpenAPI、数据库、Docker、环境变量或 `migration.sql`；本地客户端需重启生效。

# 2026-07-30 Douyin DM inbox account scope
- `backend/api_server.py#L2851-L3094`: `browser_read_dm_inbox()` accepts optional `account_id`, resolves the account-matrix login source before Playwright starts, forwards `DY_DM_INBOX_ACCOUNT_ID` into the isolated child, seeds the selected profile, and injects selected-account cookies before visiting the customer page without logging cookie values.
- `backend/api_server.py#L4271-L4286` and `backend/api_server.py#L7109-L7118`: local wrapper and `/api/douyin/dm/inbox` route pass `accountId/account`; omitted account keeps latest usable Douyin account behavior.
- `backend/matrix_native_client.py#L5462-L5472` and `backend/matrix_native_client.py#L7466-L7844`: Finder follow-up carries the selected account, DMPage stores `_dm_account_id`, and manual send plus auto inbox polling use the same account until the user edits the target.
- `docs/openapi.yaml#L1513-L1538` documents the optional inbox `accountId`; `docs/openapi.yaml#L1559-L1599` documents response `accountId` and count-only `dmCookieInjection` diagnostics. `docs/API_REFERENCE.md#L670-L732` keeps the same request, response, and privacy contract.
- `tests/test_douyin_dm_auto_reply.py#L132-L279`, `tests/test_openapi_contract.py#L120-L128`, and `tests/test_openapi_contract.py#L129-L138`: regression coverage locks route, wrapper, browser reader, cookie injection, client account carryover, the optional OpenAPI request field, and the safe response diagnostics schema.
- Verification: the new tests first failed on missing route/wrapper/browser/client/OpenAPI account propagation. After implementation, focused DM tests passed 54/54, the full DM module passed 58/58, Finder tests passed 9/9, OpenAPI tests passed 6/6, and related `py_compile` checks exited 0. Real read-only browser smoke and the restarted `9081` endpoint both matched the selected account, injected 60/60 cookies, returned `needLogin=false`, and did not send a message; an empty page returned the existing `dm_inbox_messages_not_found` code.
- Runtime: the old local client was stopped and `start-visible-client.bat` started the updated client. The `9081` listener changed from PID `29684` to `7012`; the existing `9080` central service was not restarted.
- Rollback: revert `backend/api_server.py`, `backend/matrix_native_client.py`, `docs/openapi.yaml`, `docs/API_REFERENCE.md`, `docs/IMPLEMENTATION.md`, `docs/TROUBLESHOOTING.md`, `tests/test_douyin_dm_auto_reply.py`, and `tests/test_openapi_contract.py`. No database or `migration.sql` change is involved; local client and local executor must restart for runtime effect.

# 2026-07-30 账户中心账单看板完整验证与回滚门禁
- `backend/billing_analytics.py#L1-L300`：账单查询边界、来源归一化、analytics/ledger 计算与 Draft 2020-12 运行时响应 Schema；`backend/billing_analytics.py#L151-L213` 规范化 `wxpay:<orderNo>` / `redeem:<code>`、兼容 `paidAt/usedAt`，并把没有其他关联字段的账本 `ref` 保留到 `requestId`。
- `backend/maindb.py#L162-L171`：`get_balance_strict()` 不吞查询异常；`backend/maindb.py#L417-L426`：`model_usage_logs` 按用户、时间范围和稳定降序键查询，`limit` 限制在 50,001 行。
- `backend/central_server.py#L54-L65`、`backend/central_server.py#L2661-L2680`：`MAINDB_ENABLED` 默认启用，显式 `0` 才跳过导入；导入异常只记录进程内状态且不写日志，其他既有主库调用仍沿用健康探测。
- `backend/central_server.py#L3105-L3172`：余额与参数化账单在主库默认启用时对导入、配置、健康、用量和严格余额读取失败统一失败关闭；`user-owner` 固定返回 `"inf"`，达到 50,001 行拒绝部分统计。
- `backend/central_server.py#L3175-L3273`：查询/响应校验、结构化耗时日志和脱敏 400/500/503 错误响应；异常消息、凭据和连接细节不进入日志。
- `backend/central_server.py#L3359-L3473`、`backend/central_server.py#L3664-L3757`：主库充值与退款同步写入可追溯正向 `STATE` 流水，保留既有返回签名和稳定 `wxpay/redeem` 引用。
- `backend/central_server.py#L14332-L14368`：`/api/account/balance`、analytics 与参数化 ledger 共用运营方 `"inf"` 和主库失败关闭语义；鉴权失败返回 401，查询错误返回 400，来源错误返回 503，无参数 ledger 继续走原兼容响应。
- `backend/matrix_native_client.py#L3837-L4083`：金额/查询格式、固定高度趋势图和固定四行类型分布控件。
- `backend/matrix_native_client.py#L25479-L26276`：账户中心四指标、独立筛选/分页、analytics/ledger 请求序列、迟到响应丢弃、成功 analytics 余额优先级、充值后刷新、错误保留与角色权限复核。
- `docs/openapi.yaml#L457-L589` 与 `docs/openapi.yaml#L1009-L1134`：account balance/ledger/analytics 查询参数、数字或 `inf` 余额、成功/错误响应及账单 Schema，与运行时字段、枚举、范围和 nullability 一致。
- `scripts/smoke_billing_performance.py#L1-L148`：仅允许本机 HTTP 回环地址，固定 200 请求/20 workers，拒绝所有跳转且不转发 Authorization，使用单调计时计算 nearest-rank P95，并逐响应调用运行时 analytics Schema；P95 超过 800 ms 或任一响应无效即非零退出。
- `scripts/monitor_billing_rollout.py#L1-L165`：固定 100 请求窗口、3xx 原样计错且禁止跳转、严格 `>1%` 门槛、镜像 Tag 全字符串校验、固定 Docker 参数列表、复制环境和 `shell=False`；fixture 只能与 `--dry-run` 同时使用。
- `tests/test_billing_rollout_guard.py#L1-L128` 与 `tests/test_billing_performance_smoke.py#L1-L92`：TDD 覆盖跳转前拒绝及 Authorization 隔离、任一无效响应即失败、nearest-rank P95 的 800 ms 精确边界、CLI dry-run 无网络/子进程、1%/2% 回滚边界和既有命令安全约束。
- `tests/test_billing_analytics.py#L67-L153`、`tests/test_billing_dashboard_api.py#L248-L580`、`tests/test_account_billing_dashboard.py#L190-L207`、`tests/test_billing_unified.py#L246-L289`：最终评审 RED/GREEN 覆盖权威充值去重、驼峰时间、共享引用、主库失败关闭、三条真实运营方余额路径、迟到旧余额覆盖和精确依赖锁。
- `backend/requirements.txt#L20-L22`、`backend/requirements.deploy.txt#L21-L23`：两种运行方式统一锁定 `jsonschema==4.23.0`、`PyMySQL==1.1.1`、`passlib[bcrypt]==1.7.4`。
- 可追溯性：已提交源码基线为 `347120c9308db2ae43482aba3f33df5ed2dd40ad`；源码快照和当前源码 SHA-256 见 `docs/DEPLOYMENT.md`。这些不是可部署制品，生产发布前仍须登记上一稳定中心镜像 Tag 和客户端包 SHA-256。
- 数据库/部署：`migration.sql` 只追加 no-op 注释，无 DDL/DML；Dockerfile、Compose 拓扑与 `/api/health` 不变。本任务不运行 Docker、不部署、不重启生产或客户端、不提交。

# 2026-07-30 抖音私信真实按钮标签与登录 Cookie 恢复修复
- `backend/api_server.py#L1772-L1786`: 新增纯函数 `_is_douyin_dm_button_label()` 和 `_douyin_dm_context_cookies()`；前者接受“私信 私信 / 发消息发消息”等同一文案重复结果，但拒绝“回关 私信 / 关注”，后者从当前账号缓存构建 `.douyin.com` Cookie 注入列表并排除易失效的 `msToken`。
- `backend/api_server.py#L1955-L1975`: 私信临时浏览器启动后、访问客户主页前，从已解析的账号矩阵账号加载 Cookie 并调用 `ctx.add_cookies()`；`dmCookieInjection` 只返回 `attemptedCount/addedCount/error type`，结构化日志不记录 Cookie 名值或私信正文。
- `backend/api_server.py#L2004-L2174`: 客户主页按钮候选继续执行严格标签校验，但改用重复文案兼容函数；真实页面返回 `私信 私信` 时不再进入 `rejectedButtons`，相邻“回关/关注”仍不会被点击。
- `backend/matrix_native_client.py#L7716-L7731`: `dm_button_not_found` 提示改用 `saveLoginPrompt.finalPromptVisible` 判断弹窗最终状态；弹窗已关闭或未出现时不再提示“仍可见”，并给出对应排查文案。
- `tests/test_douyin_dm_auto_reply.py#L90-L106`、`tests/test_douyin_dm_auto_reply.py#L221-L232`、`tests/test_douyin_dm_auto_reply.py#L326-L335`: 回归覆盖重复按钮标签、相邻操作拒绝、Cookie 注入排除 `msToken`、注入时序和最终弹窗状态提示。RED 阶段分别因缺少两个 helper、缺少注入调用和仍读取 `promptVisible` 失败。
- 冒烟：先复现到 `rejectedButtons.label="私信 私信"`；修复标签后复现到临时浏览器未恢复登录导致 `dm_panel_not_open`；对比试验证实补充注入 60 个账号 Cookie 后页面稳定出现私信按钮。最终真实浏览器自动关闭弹窗、点击 Edge 私信按钮、打开会话并发送“你好”，`/v1/message/send` 返回 HTTP 200。
- 验证：不依赖中心服务导入的私信发送、收信、客户端提示和脱敏日志测试通过 47/47；`backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_dm_auto_reply.py` 通过 `py_compile`，相关文件通过 `git diff --check`。完整测试文件另有 2 项被工作区既有 `backend/central_server.py#L10031` 缩进错误阻断，本次未修改该无关文件。
- 回滚：回滚 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_dm_auto_reply.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 中本条变更即可。无中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql` 影响；本地客户端和本地执行引擎需重启后生效。

# 2026-07-30 同款替换 Seedance 素材安全降级与视频参考图收敛
- `backend/matrix_native_client.py#L11152-L11207`: 漫剧视频生成请求只提交当前片段首帧/尾帧；若首尾帧缺失才回退使用 `flowchartUrl/keyframeUrl`。视频阶段不再叠加人物、场景、产品或历史 `referenceImageUrls`，减少真人、水印、品牌 Logo、屏幕文字等参考图在 Ark/Seedance 视频阶段触发安全策略。
- `backend/matrix_native_client.py#L11300-L11340`: 本地客户端把 `InputImageSensitiveContentDetected.PolicyViolation`、`copyright restriction` 和 `policy violation` 识别为可降级原因；轮询提示区分“真人参考图”和“素材版权/品牌风险”，失败消息保留 Seedance 原因和备用模型上游错误。
- `backend/matrix_native_client.py#L20364-L20425`: 同款替换参考图预检提示词新增水印、百度百科/平台来源标记、抖音/小红书截图边框、电子屏幕大段文字、促销海报、代言人照片、第三方品牌和 Logo 过密检查；自有门店 Logo 可 warning 通过，但会给出重新拍摄建议。
- `tools/aicanvas_remote/server_current.py#L12973-L12994`: 漫剧服务快照把 `PolicyViolation/copyright restriction` 纳入 Seedance 视频备用模型链，按 Vidu Q3、万相、Kling、PixVerse 顺序继续尝试。
- `tools/aicanvas_remote/server_legacy.py#L25225-L25241`: 旧服务快照的 Ark proxy 错误提示补充素材版权/品牌风险分支，避免以后切回旧文件时仍只显示通用 502。
- `tests/test_video_replacement.py#L189-L243`、`tests/test_video_replacement.py#L244-L285`、`tests/test_video_replacement.py#L1217-L1295`、`tests/test_video_replacement.py#L1696-L1754`: 覆盖视频阶段只传首尾帧、PolicyViolation 本地识别、降级进度/失败文案和上传人物参考图优先清洗原片男销售外观。
- `tests/test_video_replacement_v2.py#L2799-L2825`、`tests/test_aicanvas_real_person_fallback.py#L29-L34`、`tests/test_aicanvas_real_person_fallback.py#L329-L338`: 覆盖参考图预检风险词和 Seedance PolicyViolation 自动进入 Vidu 备用模型。
- 验证：新增失败用例先覆盖旧行为；实现后 `tests.test_video_replacement` 92/92 通过，`tests.test_aicanvas_real_person_fallback` 14/14 通过，预检专项 2/2 通过，相关 Python 文件 `py_compile` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tools/aicanvas_remote/server_current.py`、`tools/aicanvas_remote/server_legacy.py`、`tests/test_video_replacement.py`、`tests/test_video_replacement_v2.py`、`tests/test_aicanvas_real_person_fallback.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可恢复旧行为。本次不改数据库、OpenAPI、Docker、环境变量或 `migration.sql`；本地客户端需重启后生效，远程服务器需单独部署/重启对应漫剧服务文件后才会影响线上任务。

# 2026-07-30 抖音私信保存登录信息弹窗关闭增强
- `backend/api_server.py#L1876-L1914`: `browser_send_dm()` 新增 `disable_chromium_password_prompts()`，在私信临时浏览器 profile 写入 `credentials_enable_service=false` 和 `profile.password_manager_enabled=false`，并在启动参数中追加 `--disable-save-password-bubble`，减少浏览器保存密码气泡遮挡主页。
- `backend/api_server.py#L1985-L2126`: `dismiss_douyin_save_login_prompt()` 扩展识别“保存登录信息/保存登录状态/记住登录”等弹窗，并优先点击“以后再说 / 暂不保存 / 不保存 / 暂不 / 取消 / 关闭 / 跳过 / 稍后 / 稍后再说 / 下次再说”等关闭类按钮；页面事件点击后若弹窗仍在，会用 `page.mouse.click()` 对候选按钮坐标再做真实点击，诊断写入 `realMouseClick/finalPromptVisible`。
- `backend/api_server.py#L2112-L2152`: 如果弹窗仍挡住主页导致 `dm_button_not_found`，`maybe_keep_browser_for_blocked_save_prompt()` 会让可见浏览器默认短暂停留 `DY_DM_KEEP_BROWSER_ON_BLOCKED_PROMPT_MS=20000`，并把 `browserKeptOpenMs` 返回给客户端，方便用户手动处理弹窗后重试。
- `backend/matrix_native_client.py#L7695-L7730`: `_dm_send_error_text()` 在 `dm_button_not_found` 时读取 `browserKeptOpenMs`，提示“浏览器已短暂停留，请手动点掉弹窗后重试”。
- `tests/test_douyin_dm_auto_reply.py#L204-L214`、`tests/test_douyin_dm_auto_reply.py#L349-L359`: 回归测试覆盖客户端弹窗提示、关闭类文案、真实鼠标点击、浏览器保存密码禁用和失败停留参数。
- 验证：新增弹窗关闭增强测试先在旧实现下失败；实现后完整私信回归 `tests.test_douyin_dm_auto_reply` 通过 47/47，相关 Python 文件 `py_compile` 通过。
- 回滚：回滚 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_dm_auto_reply.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服接口、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。代码生效需要重启本地客户端和本地执行引擎。

# 2026-07-30 抖音私信主页按钮误判修复
- `backend/api_server.py#L1954-L2015`: `browser_send_dm()` 在遍历客户主页“私信”按钮候选时新增 `is_dm_button_label()` 和 `locator_label()`，固定 XPath 命中后必须确认按钮文本/标签包含“私信 / 发私信 / 发消息”才会点击；误命中的“回关”等按钮会进入 `rejectedButtons` 诊断，避免未打开私信面板就继续发送。
- `backend/api_server.py#L1985-L2126`: 新增 `dismiss_douyin_save_login_prompt()`，识别保存登录类弹窗并等待弹窗消失；诊断写入 `saveLoginPrompt`，避免弹窗遮挡主页导致 `dm_button_not_found`。
- `backend/api_server.py#L2156-L2203`: 私信面板探测新增 `strongMarkers`，只有“收起会话 / 发送消息 / 输入消息 / 确认聊天”或真实可编辑输入区这类强信号出现时才返回 `panelOpened=true`；普通“私信/消息”文字只保留为诊断分数，不再作为打开成功条件。
- `backend/api_server.py#L2210-L2315`: 新增 `click_profile_dm_button()`，点击前滚动到按钮，先执行普通 Playwright 点击，再用 `page.mouse.click()` 做真实坐标点击兜底，最后才尝试 DOM 事件点击；每次尝试都会记录 `clickAttempts`、按钮坐标和 `clickedPanelOpened`。
- `backend/matrix_native_client.py#L7695-L7730`: 客户端新增 `dm_button_not_found` 中文提示，带出保存登录信息弹窗状态，避免用户只看到英文错误码。
- `tests/test_douyin_dm_auto_reply.py#L315-L359`: 回归测试锁定固定 XPath 点击前的按钮文字校验、保存登录信息弹窗处理、面板探测必须使用强信号，以及私信按钮点击必须有真实坐标兜底。
- Verification: 新增测试先在旧实现下失败；实现后完整私信回归 `tests.test_douyin_dm_auto_reply` 通过 46/46。完整相关验证见本次交付结果。
- Rollback: 回滚 `backend/api_server.py`、`tests/test_douyin_dm_auto_reply.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服接口、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端和本地执行引擎。

# 2026-07-30 Task 3: authoritative billing analytics and filtered ledger APIs

- `backend/central_server.py#L40-L52`: `_load_central_dotenv()` defaults to enabled and performs the two pre-existing dotenv loads in exact parent/backend order with `override=False` then `override=True`; `CENTRAL_LOAD_DOTENV=0` skips both.
- `backend/central_server.py#L54-L65`、`backend/central_server.py#L3105-L3172`: `MAINDB_ENABLED=0` is the only intentional local-source mode. With the default enabled mode, import/configuration/readiness/usage/strict-balance failures are fatal; `user-owner` returns exact `"inf"`; the 50,001-row sentinel still raises `billing_record_limit_exceeded`.
- `backend/central_server.py#L3175-L3234`: `_normalized_billing_query()` starts the query/payload helper range. Request schemas validate before parsing; `_validated_billing_response()` wraps only successful-response schema failures; `billing_dashboard_payload()` emits approved completion fields after successful validation.
- `backend/central_server.py#L3237-L3273`: `_billing_api_error()` maps query `ValidationError` to redacted 400, response validation failures to redacted 500, and source failures to 503. Response and JSON log share one `errorId`; import exception text is never logged.
- `backend/central_server.py#L14338-L14363`: authenticated analytics handling continues through the legacy/parameterized ledger route. Requests without `startDate/endDate/type/status/page/pageSize` retain the raw reverse latest-100 response.
- `tests/test_billing_dashboard_api.py#L1-L758`: 29 tests cover explicit main-DB disable versus default fail-closed behavior, import tracking, strict balance, owner infinity through real routes, dependency locks, query/response validation, correlated redacted 400/500/503 errors, dotenv control, completion logs, and exact legacy compatibility.
- Verification: remaining-findings RED ran 4 focused tests with `FAILED (failures=3)`; focused GREEN is 4/4. Final Task 3, unified/structured, compile, and diff-check evidence is recorded in `.tmp-validation/sdd/task-3-implementer-report.md`.
- Rollback: revert only the Task 3 hunks in `backend/central_server.py`, remove `tests/test_billing_dashboard_api.py`, and remove these Task 3 documentation/report entries. No OpenAPI, database schema, migration, deployment, remote service, production request, process restart, or image tag changed; a later release must retain the previous stable image tag and roll back if the new endpoint error rate exceeds 1%.

# 2026-07-30 Task 4: billing OpenAPI and API reference contract

- `backend/billing_analytics.py#L52-L94`: `parse_period()` and `parse_ledger_filters()` are the authoritative optional date, `groupBy`, type, status, minimum-page, and `20/50/100` page-size contract.
- `backend/billing_analytics.py#L286-L292`: Draft 2020-12 query and response schemas define the strict parameterized contract: exact dates, numeric-or-exact-`"inf"` balance, nullable historical `balanceAfter`, required pagination, and closed response objects.
- `backend/central_server.py#L14338-L14363`: analytics is always validated; ledger selects strict pagination only when one of the six recognized dashboard parameters is present, leaving unrelated-query requests on the legacy raw latest-100 path.
- `docs/openapi.yaml#L475-L583`: authenticated ledger and analytics routes document 400/401/500/503 `ErrorResponse` responses. Ledger 200 explicitly uses the legacy/strict response union and says unrelated parameters preserve legacy behavior.
- `docs/openapi.yaml#L1012-L1125`: `LegacyBillingLedgerResponse` preserves arbitrary historical rows without pagination, while `BillingLedgerResponse` exactly represents the closed parameterized response; analytics, metrics, buckets, distribution, rows, and pagination remain explicit.
- `tests/test_openapi_contract.py#L1-L335`: YAML parsing, component-reference resolution, strict runtime-surface/enums comparison, and representative analytics, strict-ledger, and legacy-ledger validation prevent contract drift.
- `docs/API_REFERENCE.md#L618-L622`: operator-facing analytics semantics, recognized-parameter mode selection, current-user scope, validation/data-source failures, strict pagination, and legacy compatibility.
- Verification: review-fix RED was the focused billing OpenAPI contract test and failed on the prior missing 500 contract. Focused GREEN passed; final Task 4 evidence is in `.tmp-validation/sdd/task-4-implementer-report.md`.
- Rollback: revert only the Task 4 hunks in `docs/openapi.yaml`, `docs/API_REFERENCE.md`, `docs/IMPLEMENTATION.md`, `docs/TROUBLESHOOTING.md`, `tests/test_openapi_contract.py`, and its report. No production source, schema migration, deployment manifest, image tag, service process, or database state changed. A later release must retain the previous stable image tag and roll back if endpoint error rate exceeds 1%.

# 2026-07-30 Task 2: bounded data sources and traceable balance changes

# 2026-07-30 获客中心使用账号为空修复
- `backend/matrix_native_client.py#L1126-L1139`: 新增 `emit_account_matrix_rows()`，账号矩阵加载异常时返回明确失败 payload，并用脱敏 JSON 结构化日志记录 `account_matrix_load_failed`、`errorId` 和来源 tag。
- `backend/matrix_native_client.py#L5175-L5225`: `FinderPage` 的“使用账号”下拉框在初始化和刷新前显示“正在读取账号...”，并通过 `emit_account_matrix_rows("finder_accounts")` 读取账号，避免初始空框。
- `backend/matrix_native_client.py#L5438-L5471`: `OutreachPage` 同步增加账号读取占位和统一加载入口，账号接口异常时显示“账号加载失败，请刷新账号矩阵”。
- `backend/matrix_native_client.py#L5532-L5553`: `GrowthPage` 保存 `FinderPage/OutreachPage` 子页实例，进入获客中心或切换 Tab 时调用当前子页 `on_show()`，修复外层页面未转发显示事件导致账号不加载的问题。
- `backend/api_server.py#L276-L281`、`backend/api_server.py#L322-L381`: 本地引擎读取抖音账号清单时保留 JSON 解析错误；清单损坏且 profile 目录存在时，从 `douyin_accounts/<账号ID>/auth_cookie.json` 和 `dy_profile` 重建最小账号索引，备份坏文件为 `.invalid` 并记录 `douyin_accounts_registry_recovered`。
- `tests/test_finder_page_actions.py#L133-L158`、`tests/test_douyin_multi_account.py#L67-L82`、`tests/test_native_publish.py#L214-L218`: 回归测试覆盖获客中心子 Tab 刷新、账号框非空占位、损坏抖音账号清单的 profile 目录恢复，以及 Finder/Outreach 账号加载入口契约。
- Verification: 新增测试先在旧实现下失败；实现后 `.\.venv-win\Scripts\python.exe -m unittest tests.test_finder_page_actions.FinderAccountLoadingTest -v` 通过 2/2，`.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_multi_account.DouyinMultiAccountTest.test_load_douyin_accounts_recovers_from_profile_dirs_when_registry_json_is_corrupt -v` 通过 1/1。当前 `backend/datas/accounts/boss/douyin_accounts.json` 经 Python JSON 解析确认可读，本地账号接口返回 2 个在线抖音账号。
- Rollback: 回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`tests/test_finder_page_actions.py`、`tests/test_douyin_multi_account.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服接口、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。生效需要重启本地客户端。
- `backend/maindb.py#L254-L289`: `refund_generation()` retains `(False, 0.0)` for no eligible or already-refunded rows, but rolls back and re-raises transactional/database exceptions so callers can distinguish a failed data source from idempotency.
- `backend/maindb.py#L292-L402`: `topup()` requires `_exec()` to report exactly one affected user row before returning success; a zero-row update returns `ok=False` and cannot authorize a center-ledger entry.
- `backend/maindb.py#L417-L426`: `list_model_usage_logs()` selects the exact usage fields for one user, applies `[start_at, end_at)`, orders by `created_at DESC, id DESC`, clamps `limit` to `1..50001`, and intentionally lets database errors propagate.
- `backend/central_server.py#L3359-L3384`: successful main-DB `topup_user()` writes a positive ledger entry under `LOCK`, persists it, and uses the caller ref or an `admin-topup:<uuid>` fallback. Failed main-DB updates keep the existing return signature and write nothing.
- `backend/central_server.py#L3387-L3473`: a successful non-zero model refund writes `退款:模型生成` with the original request ref. A false/zero result preserves the documented idempotent success tuple and cannot append another positive row.
- `backend/central_server.py#L3664-L3713`: WeChat only marks an order credited and persists `wxpay:<order_no>` after concrete `maindb.topup()` success; failed balance writes remain eligible for later polling retry.
- `backend/central_server.py#L3716-L3757`: redeem-code use is deferred until concrete main-DB topup success, then persists `redeem:<normalized-code>`; failures leave the code active.
- `tests/test_billing_unified.py#L177-L289`、`tests/test_billing_unified.py#L338-L407`: focused regressions cover strict-balance propagation plus main-DB admin/refund/WeChat/redeem ledger rows, zero-row topups, repeated zero refunds, and the bounded query contract.
- Verification: the review-fix RED run was 24 tests with 2 expected failures; GREEN was `24/24` with the specified unittest command. No schema, migration, deployment, remote service, or process restart was changed.

# 实现索引

## 2026-07-30 Agent.模式视频上传图片全部作为参考图
- `backend/matrix_native_client.py#L16745-L16770`: `_prodgen_refs_desc(refs, is_video=False)` 增加模式参数；图片模式仍说明第 1 张是待修改图、第 2 张起是参考图，视频模式改为说明所有图片都是视频视觉参考，且没有待修改图。
- `backend/matrix_native_client.py#L16909-L16923`: `_prodgen_run_video()` 调用 `_prodgen_refs_desc(refs, is_video=True)`，确保视频生成链路不会把第 1 张上传图描述成编辑目标。
- `backend/matrix_native_client.py#L22759-L22813`: `GenCard` 结果卡片按生成记录的 `mode` 显示上传图片标签；视频记录显示 `参考图1/参考图2/...`，图片记录继续显示 `待修改图/参考图1/...`。
- `backend/matrix_native_client.py#L23088-L23580`: `ProductGenPage` 的上传区提示、模式切换、图片标签和提示词优化链路按当前 `image/video` 模式同步刷新；`_ref_label()` 在视频模式返回 `参考图1/参考图2/...`，`_rebuild_ref_slots()` 在视频模式显示“上传图片全部作为参考图”。
- `tests/test_agent_mode_defaults.py#L193-L259`: 回归测试锁定图片模式旧规则、视频模式全参考图规则、视频生成按上传顺序使用全部图片，以及模式切换时标签/提示词刷新。
- 验证：新增视频模式测试先在旧规则下失败；实现后专项 3/3 通过。完整验证见本次交付结果。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。

## 2026-07-30 资产库删除文本资产分类
- `backend/matrix_native_client.py#L16959-L17036`: `load_assets()` 读取资产索引时移除历史 `kind=text` 记录并保存清理后的索引；`add_asset()` 拒绝新增 `kind=text`，且文件扩展名自动识别只允许图片和视频进入资产库。
- `backend/matrix_native_client.py#L15146-L15153`、`backend/matrix_native_client.py#L15349-L15445`: 工作流 `.txt/.md/.csv/.json/.log` 产物不再映射为独立资产类型，`library` 步骤不会把 `textArtifacts/scriptArtifacts` 写入资产库；采集参考视频仍通过 `text_path/breakdown_path` 绑定拆解文本，并在总结里显示“绑定文本 x/y”。
- `backend/matrix_native_client.py#L23865-L23899`: 资产库导入对话框删除文本文件类型，只保留图片和视频导入。
- `backend/matrix_native_client.py#L24010-L24144`: 独立文本资产卡片分支和 `kind=text` 打开入口删除；采集参考视频卡片的“文本”按钮和 `open_asset_text()` 保留，只读取视频资产绑定的 `breakdownPath/textPath`。
- `tests/test_asset_library_shared_button.py#L123-L140`、`tests/test_workflow_resilience.py#L299-L427`: 回归测试覆盖文本分类消失、历史文本资产清理、独立文本产物不入库，以及采集参考视频仍绑定文本。
- 验证：新增/调整测试先在旧实现下失败；实现后专项 4/4 通过，完整相关验证见本次交付结果。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`tests/test_workflow_resilience.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧文本资产分类；本次不涉及中心服、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。

## 2026-07-30 自动化工作流参考视频拆解文本可读性优化
- `backend/matrix_native_client.py#L14963-L15019`: 新增 `_workflow_clean_breakdown_cell()` 和 `_workflow_normalize_reference_breakdown_text()`，保存前识别 Markdown 表格拆解结果，去掉粗体标记、表头、分隔行、`台词/字幕` 前缀和卖点分类前缀，并转换为“镜头 N｜主题｜时长 / 画面 / 台词 / 节奏 / 可借鉴点”的卡片式文本。
- `backend/matrix_native_client.py#L15021-L15044`: 参考视频理解提示词改为明确禁止 Markdown 表格和竖线表格，要求模型直接输出镜头卡片式文本；模型仍返回表格时由规范化函数兜底。
- `tests/test_workflow_resilience.py#L349-L368`: 新增回归测试，使用真实表格样例验证输出不再包含表头和 `**`，并保留镜头、画面、台词、节奏、时长和可借鉴点。
- 验证：先运行新增测试观察旧实现因缺少规范化函数失败；实现后 `.\.venv-win\Scripts\python.exe -m unittest tests.test_workflow_resilience tests.test_asset_library_shared_button -v` 通过 30/30；`.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_workflow_resilience.py tests\test_asset_library_shared_button.py` 通过；`git diff --check -- ...` 退出码 0，仅提示现有 LF/CRLF 换行转换。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_workflow_resilience.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库、OpenAPI、Docker、环境变量或 `migration.sql`。

## 2026-07-30 资产库按时间分组
- `backend/matrix_native_client.py#L16984-L17036`: `add_asset()` 为新资产写入 `createdAt` 数值时间，同时保留原 `ts` 字符串，便于排序、分组和兼容历史资产。
- `backend/matrix_native_client.py#L23901-L23969`: `AssetLibraryPage` 新增资产时间解析、日期标签、卡片时间文本、日期分组和日期标题构造；优先读取 `createdAt/updatedAt/mtime`，再兼容旧 `ts` 字符串，最后回退到文件修改时间。
- `backend/matrix_native_client.py#L23971-L23999`: `_build_local()` 在筛选后按时间倒序排序，并按日期标题分组渲染，同一日期内继续使用 4 列素材卡片布局。
- `backend/matrix_native_client.py#L24010-L24088`: `_asset_card()` 在素材说明下方显示 `HH:mm` 或“时间未知”，按钮行保持原来的短图标均匀分散布局。
- `tests/test_asset_library_shared_button.py#L89-L122`: 回归测试锁定日期分组渲染、卡片时间显示，以及新资产写入 `createdAt`。
- 验证：新增三条测试先在旧实现下失败，改动后通过；完整相关验证见本次交付结果。
- 回滚：回退 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧的平铺资产库；本次不涉及中心服、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。

## 2026-07-30 同款替换视频预览、漫剧视频扣费与自动声音合成门禁
- `backend/matrix_native_client.py#L735-L925`: `try_charge()` / `refund_cap()` 支持按本次模型报价传入动态金额；`_comic_video_billing_quote()` 从漫剧 `/api/model-prices` 读取视频模型价格，兼容 Vidu 模型别名，按远程 `per_second` 或 `per_call` 规则计算；`_charge_comic_video_attempt()` 使用项目、片段、模型和时长生成唯一扣费引用并输出脱敏 JSON 日志，失败由 `_refund_comic_video_attempt()` 按同一引用幂等退款。
- `backend/matrix_native_client.py#L11697-L11700`、`backend/matrix_native_client.py#L12902-L13150`、`backend/matrix_native_client.py#L13496-L13680`: 初次生成和单段视频重生成均在提交模型任务前读取价格并扣费；提交或远程等待失败时退款。远程任务已经成功但本地下载失败时保留扣费，后续 `pendingComicVideoRecovery` 仅恢复下载，不重新提交模型也不重复扣费；报价快照保存在片段 `comicVideoBilling`。
- `backend/matrix_native_client.py#L24373-L24520`: 账户中心消费流水改为“时间、项目/模型、任务详情、变动、余额后”五列；漫剧视频扣费引用转换为可读的项目和片段信息，不显示内部尝试后缀。
- `backend/matrix_native_client.py#L2327-L2800`: `VideoPlayerBox` 新增 `contain` 模式；漫剧视频预览按源视频宽高比计算窗口，最大占可用屏幕 82%，竖屏保持竖屏、横屏保持横屏。预览挂在稳定页面窗口上，不依赖可刷新的表格单元格；播放结束不关闭弹窗，只有用户手动关闭时才释放播放器。
- `backend/matrix_native_client.py#L13209-L13240`、`backend/matrix_native_client.py#L20758-L20794`: 漫剧项目 `audioMode=auto` 的最终合成只要求每段 `status=done`、人工确认、本地视频可解码且包含音轨；历史 `audioStatus/qcStatus` 不再造成误拦截。片段未完成、未确认、视频缺失/损坏或无声音仍逐段给出阻断原因；其他声音模式维持原门禁。
- `tests/test_video_replacement.py#L2693-L2905`、`tests/test_video_replacement_v2.py#L5781-L5812`: 回归覆盖按秒/按次报价、扣费描述、失败退款、恢复下载不重扣、账户流水可读引用、自动声音合成门禁以及横竖屏预览尺寸和稳定父窗口。
- 远程价格接口当前未返回 `billing_method` 与 `price_tiers`。客户端优先使用未来返回的明确 `billing_method`；当前按价格描述、provider 和模型标识推断按秒/按次。若远程启用非 1 的档位系数，或内部从首选模型降级到不同价格的备用模型，必须先扩展公开价格/结算契约再宣称完全等价计费，不能在远程任务完成后用不可靠的本地差额扣费改变任务状态。
- 验证：`tests.test_video_replacement` 89/89 通过；视频预览专项 8/8 通过；客户端和两份测试语法检查通过；目标文件 `git diff --check` 通过。完整 `tests.test_video_replacement_v2` 为 245/252 通过，剩余 5 failures + 2 errors 与修改前基线一致：4 项断言旧原片音轨回填，3 项属于内容采集/XHS 旧夹具或旧文案。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`tests/test_video_replacement_v2.py` 和本次文档条目即可。无中心服、远程漫剧服务、数据库、OpenAPI、Docker、环境变量或 `migration.sql` 变更；按用户要求不自动重启本地客户端。

## 2026-07-30 小红书登录态失效提示改为明确原因
- `backend/matrix_native_client.py#L1131-L1143`: 新增 `XHS_LOGIN_EXPIRED_HINT`，通用本地任务错误 `_local_task_error_message()` 遇到 `xhs_login_required` 时返回“账号已存在，但登录态已失效。请到账号矩阵重新登录该平台账号后再采集。”
- `backend/matrix_native_client.py#L5204-L5222`: 内容采集搜索失败文案在 `needLogin=true/error=xhs_login_required` 时显示同一句提示，不再显示泛化的“需先登录小红书账号”。
- `backend/matrix_native_client.py#L16481-L16489`: 下载、图文同款和视频分解使用的 `_localize_download_task_error()` 同步识别 `xhs_login_required` 并显示同一句提示。
- `tests/test_native_publish.py#L203-L211`: 回归测试锁定提示文案和两个关键错误分支，避免后续又退回笼统登录提示。
- 验证：新增测试先在旧文案下失败，改动后通过；完整相关验证见本次交付结果。
- 回滚：回退 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧提示；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-30 自动化工作流采集参考视频全量入库与文本拆解
- `backend/matrix_native_client.py#L14434-L14514`: `_workflow_ensure_reference_text_artifacts()` 会在入库前为每个 `referenceArtifacts` 视频生成一份拆解文本，优先调用视频理解模型，失败时用文本脚本兜底；文本保存到账号级 `wf_out`，并通过 `ctx["referenceTextArtifacts"]` 绑定到对应视频。
- `backend/matrix_native_client.py#L14557-L14635`: `_exec_collect()` 从“只下载 Top1”改为按本次 `topN` 逐条下载，采集视频只进入 `referenceArtifacts/collectedArtifacts`，不进入可发布 `artifacts`；运行日志改为 `已下载 x/y 到采集参考素材`。
- `backend/matrix_native_client.py#L15349-L15445`: `_exec_library()` 入库前确保参考视频已有拆解文本，并将 `text_path/breakdown_path` 传给视频资产；运行日志里的“绑定文本 x/y”只统计参考视频已绑定的拆解文本，普通文本文件不再作为资产库资产。
- `backend/matrix_native_client.py#L16283-L16330`: `add_asset()` 兼容新增 `text_path/breakdown_path`，把拆解文本复制到资产目录并保存为视频资产的 `textPath/breakdownPath` 元数据；封面仍只作为 `thumbnail/preview` 元数据，不单独显示资产。
- `backend/matrix_native_client.py#L22897-L22908` and `backend/matrix_native_client.py#L23198-L23336`: `ProductGenPage` 接收 `breakdown_to_product_video` 事件并预填视频生成提示词；`AssetLibraryPage` 为带拆解文本的“采集参考视频”卡片显示“文本”按钮，弹窗中提供“用此文本生成视频”入口。
- `tests/test_workflow_resilience.py#L193-L347` and `tests/test_asset_library_shared_button.py#L143-L164`: 回归测试覆盖 TopN 全量下载、每个参考视频生成并绑定拆解文本、资产卡片文本入口和跳转到 Agent 视频生成页。
- 验证：先运行同一组测试观察旧行为失败 4 项；实现后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_workflow_resilience tests.test_asset_library_shared_button tests.test_workflow_account_scope -v`，32/32 通过；`.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_workflow_resilience.py tests\test_asset_library_shared_button.py` 通过；`git diff --check -- ...` 退出码 0，仅提示现有 LF/CRLF 换行转换。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_workflow_resilience.py`、`tests/test_asset_library_shared_button.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库、OpenAPI、Docker、环境变量或 `migration.sql`。

## 2026-07-30 同款替换重生、时长、预览与素材约束
- `backend/matrix_native_client.py#L8789-L8880`：新增口播时长槽位、按标点无损拆分和连续片段规划；单段口播最多 15 秒，拆分后重新压紧序号与时间轴，并保存 `speechDurationSec`、`videoDurationSec` 和连续片段元数据。
- `backend/matrix_native_client.py#L12323-L12415`：新建漫剧项目任务时，在最终口播稿和画面提示词确定后执行时长规划，避免继续沿用固定 5 秒分镜。
- `backend/matrix_native_client.py#L10467-L10677`：项目、图片和视频请求透传分镜时长及人物、场景、道具分类参考图；`audioMode=auto` 不发送 TTS 提示，保留生成视频自带声音。
- `backend/matrix_native_client.py#L10173-L10464`：上传素材存在时，画面描述明确以项目库人物、场景、道具为最高优先级，只保留原片动作、镜头、站位和节奏，移除冲突的原人物、产品、场景、OCR、全局总结和表格文本。
- `backend/matrix_native_client.py#L13147-L13613`：首帧、尾帧和视频重生点击不再静默返回；忙碌时给出可见状态，接受、完成和失败均写脱敏结构化事件，不记录 Token 或完整素材 URL。
- `backend/matrix_native_client.py#L13876-L14070`：行内三个重生按钮在任务忙碌时仍可点击，由处理函数统一反馈“当前任务正在处理”；删除按钮继续受任务状态限制。
- `backend/matrix_native_client.py#L2398-L2636`：视频列新增独立的普通模态预览播放器，窗口不超过可用屏幕 82%，支持播放、进度、音量和关闭；点击视频画面或预览图标均打开该窗口，关闭时释放播放器，不再移动表格播放器或进入全屏。
- `tests/test_video_replacement.py#L461-L525`、`tests/test_video_replacement.py#L1434-L1587`、`tests/test_video_replacement_v2.py#L655-L876`：覆盖忙碌反馈、真实按钮点击、15 秒边界、递归无损拆分、请求时长、分类素材约束、非全屏视频预览和资源释放。
- 验证：`tests.test_video_replacement` 81/81 通过；本次新增的视频预览与按钮离屏测试通过；`backend/matrix_native_client.py` 语法检查通过。`tests.test_video_replacement_v2` 全量仍有 7 条与本次无关的既有失败，详见 `docs/TROUBLESHOOTING.md`。
- 回滚：恢复上述本地客户端函数、对应测试和本节文档即可；不涉及中心服、远程漫剧服务、数据库、OpenAPI、Docker、环境变量或 `migration.sql`。按用户要求本次不自动重启本地客户端。

## 2026-07-30 自动化工作流删除入口
- `backend/matrix_native_client.py#L14895-L14899`: 自动化工作流页头部新增垃圾桶图标按钮，接入 `_delete_current_workflow()`；按钮清空 Qt tooltip，避免系统悬停黑框，只保留无障碍名称。
- `backend/matrix_native_client.py#L14948-L14969`: `_delete_current_workflow()` 读取当前选中的工作流，弹出确认框后从账号级 `WORKFLOWS/workflows.json` 删除配置并调用 `save_workflows()`、`_build_list()` 刷新列表；确认文案明确不会删除已生成素材、脚本、发布队列或 `wf_out` 文件。
- `backend/matrix_native_client.py#L21811-L21820`: `_round_icon_btn()` 统一不再生成非空 Qt tooltip，传入的 `tip` 只写入无障碍名称，避免后续图标按钮重新引入悬停黑框。
- `tests/test_workflow_account_scope.py#L74-L94`: 新增回归测试，锁定删除入口、无 tooltip、确认弹窗、持久化保存和列表刷新。
- 验证：`py -3 -m unittest tests.test_workflow_account_scope.WorkflowAccountScopeTest.test_workflow_page_exposes_delete_current_workflow_action tests.test_workflow_account_scope.WorkflowAccountScopeTest.test_delete_current_workflow_confirms_saves_and_rebuilds -v` 通过。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_workflow_account_scope.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及中心服接口、数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 自动化工作流强制文本产物
- `backend/matrix_native_client.py#L13699-L13709`：工作流助手提示改为强制文本型，只允许 `collect/vision/text/library`，禁止编排 `image/video/tts/publish`，即使用户提到发布也只生成脚本/分镜文本。
- `backend/matrix_native_client.py#L15146-L15153`、`backend/matrix_native_client.py#L15349-L15445`：`.txt/.md/.csv/.json/.log` 保留为工作流文件产物，但不再作为独立文本资产写入资产库；图像、视频、语音步骤继续直接跳过，不调用模型、不扣费。
- `backend/matrix_native_client.py#L15446-L15464`：发布步骤遇到文本产物直接返回“不进入发布队列”。
- `backend/matrix_native_client.py#L14587-L14613`、`backend/matrix_native_client.py#L25713-L25726`：工作流页面隐藏自动发布语义，定时运行只生成文本并按文本产物计数。
- `tests/test_workflow_resilience.py`、`tests/test_asset_library_shared_button.py`：覆盖文本产物不入资产库、媒体步骤跳过、编排提示禁止媒体/发布、资产库文本分类删除，以及采集参考视频绑定文本入口。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_workflow_resilience tests.test_asset_library_shared_button -v` 通过 22 项；`.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_workflow_resilience.py tests\test_asset_library_shared_button.py` 通过。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_workflow_resilience.py`、`tests/test_asset_library_shared_button.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及中心服接口、数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 抖音私信原页面浮层输入框识别
- `backend/api_server.py#L1239-L1277`: `_seed_login_state_into_profile()` 支持显式传入账号矩阵的登录 profile，避免只复制进程环境变量 `DY_PROFILE_DIR` 指向的旧目录。
- `backend/api_server.py#L1283-L1324`: 新增 `_resolve_douyin_dm_login_source()`，优先使用传入的 `accountId`，否则使用最近可用抖音账号；只有 profile 存在且 `auth_cookie.json` 有登录 Cookie 时才允许继续。
- `backend/api_server.py#L1582-L1665`: `browser_send_dm()` 在打开 Playwright 前完成账号矩阵登录态预检；不可用时返回 `not_authenticated/dm_login_profile_not_ready`，播种失败时返回 `not_authenticated/dm_login_profile_seed_failed`，不再弹临时未登录浏览器。
- `backend/api_server.py#L1694-L1719`: `browser_send_dm()` 优先使用客户主页操作区精确 XPath 点击私信按钮：Edge `//*[@id="user_detail_element"]/div/div[2]/div/div[1]/div[3]/div[2]/button[1]` 和 Chrome `//*[@id="user_detail_element"]/div/div[2]/div/div[1]/div[3]/div[3]/div[1]/button[2]`；命中结果记录到 `dmButtonSelector`。
- `backend/api_server.py#L1722-L1776`: 点击私信后新增 `dm_panel_probe_js`，必须确认右侧私信面板出现“收起会话 / 发送消息 / 输入消息”等标志；如果面板未打开，返回 `dm_panel_not_open` 和 `dmButtonDiagnostics.clickedSelector`，不再误报为 `dm_input_not_found`。
- `backend/api_server.py#L1780-L1853`: `browser_send_dm()` 点击客户主页“私信”后新增 `dm_editor_focus_js`，优先点击原页面私信浮层底部的“发送消息/输入消息”区域，排除搜索框和大面积容器，促使抖音激活真正聊天编辑器。
- `backend/api_server.py#L1975-L1994` 和 `backend/api_server.py#L2029-L2040`: 发送链路新增 `scan_dm_editor_contexts()`，遍历 `page.frames` 查找被激活的编辑器，并把后续填字、DOM 兜底、发送按钮点击都切到找到的 `editor_context` 中执行。
- `backend/api_server.py#L1996-L2018`: `dmEditorDiagnostics` 新增 `frameIndex/frameUrl/focusProbe`，只记录页面/元素候选元信息，不记录私信正文。
- `backend/api_server.py#L3605-L3613` 和 `backend/api_server.py#L6423-L6430`: `run_douyin_dm()` 和 `/api/douyin/dm` 支持 `accountId/account`，并传入 `browser_send_dm()`。
- `backend/matrix_native_client.py#L6537-L6554`: `_dm_send_error_text()` 将 `not_authenticated` 翻译为“没有拿到账号矩阵里的抖音登录态，请到账号矩阵重新登录抖音”；`dm_panel_not_open` 和 `dm_input_not_found` 继续显示可定位诊断。
- `tests/test_douyin_dm_auto_reply.py#L204-L212`、`tests/test_douyin_dm_auto_reply.py#L281-L364`: 回归测试锁定登录态预检、账号 profile 播种、接口账号透传、精确 XPath 优先级、面板打开确认、底部输入区激活、frame 扫描和客户端可读错误提示。新增测试先在旧实现下失败，修复后通过。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v` 通过 42/42；`.\.venv-win\Scripts\python.exe -m py_compile backend\api_server.py backend\matrix_native_client.py tests\test_douyin_dm_auto_reply.py` 退出码 0，仅保留既有 invalid-escape 警告。
- 回滚：回退 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_dm_auto_reply.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。

## 2026-07-29 小红书采集默认复用账号矩阵本地登录态
- `backend/matrix_native_client.py#L5260-L5265`: `ContentPage._xhs_account_payload()` 统一为小红书采集请求补齐 `guestMode=false/accountCollectionConfirmed=true`，表示使用账号矩阵里本机已登录的小红书账号。
- `backend/matrix_native_client.py#L5318-L5387`: 内容采集页的小红书搜索、下载、图文同款下载和视频分解下载默认走账号模式，并清理旧的一次性游客重试上下文。
- `backend/matrix_native_client.py#L5391-L5414`: 小红书评论读取和评论发布同样携带账号模式字段，和账号矩阵本地登录态保持一致。
- `backend/api_server.py#L3519-L3536`: `xhs_collection_account_gate()` 在账号模式下先检查本机 `xhs_profile` 是否可用；不可用时返回 `xhs_login_required` 和 `needLogin=true`，不再继续进入风控或采集。
- `tests/test_native_publish.py#L189-L213` 和 `tests/test_xhs_safety_mode.py#L86-L114`: 回归覆盖客户端默认账号模式、评论账号模式、缺失本地小红书 profile 时的后端登录门禁，以及已有登录态时的风控间隔门禁。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_xhs_safety_mode tests.test_douyin_multi_account -v` 通过 49/49；`.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py backend\api_server.py tests\test_native_publish.py tests\test_xhs_safety_mode.py` 退出码 0，仅保留既有 invalid-escape 警告。
- 回滚：回退 `backend/matrix_native_client.py`、`backend/api_server.py`、`tests/test_native_publish.py`、`tests/test_xhs_safety_mode.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧行为；本次不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。

## 2026-07-29 抖音私信 dm_child_failed returncode=0
- `backend/matrix_native_client.py#L382-L387`: `setup_env()` now sets `DY_DM_ISOLATED=0` alongside `DY_SEARCH_ISOLATED=0`, because the packaged Windows client executable cannot reliably run Python `-c` child scripts.
- `backend/api_server.py#L1504-L1514`: `_python_c_child_cmd()` returns a child command only when an explicit `MATRIX_PYTHON_EXE/PYTHON_EXE` or `sys.executable` is actually a Python launcher.
- `backend/api_server.py#L1542-L1584`: `browser_send_dm()` only uses the isolated child path when `_python_c_child_cmd()` is available; a child that exits without `__MATRIX_DM_JSON__` now returns `dm_child_no_json_marker` with safe stdout/stderr tails instead of the generic `dm_child_failed`.
- `backend/matrix_native_client.py#L6515-L6532`: `_dm_send_error_text()` displays `dm_child_no_json_marker` as a local browser result-marker problem and asks the user to restart the local client, while preserving existing `dm_child_inner_exception` and `dm_child_failed` diagnostics.
- `tests/test_douyin_dm_auto_reply.py#L178-L191` and `tests/test_douyin_dm_auto_reply.py#L274-L280`: regression coverage locks the packaged-client environment default and the backend child-command guard.
- Verification: the two new focused tests first failed against the old implementation, then passed after the fix. `.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v` passed 32/32; `.\.venv-win\Scripts\python.exe -m py_compile backend\api_server.py backend\matrix_native_client.py tests\test_douyin_dm_auto_reply.py` exited 0 with only existing invalid-escape warnings.
- Rollback: revert `backend/matrix_native_client.py`, `backend/api_server.py`, `tests/test_douyin_dm_auto_reply.py`, this implementation note, `docs/TROUBLESHOOTING.md`, and `CHANGELOG.md`. No database migration, OpenAPI, Docker, central-server API, or `migration.sql` change is involved.

## 2026-07-29 本地客户端全局移除鼠标悬停黑框
- `backend/matrix_native_client.py#L4193-L4568`：账号矩阵删除按钮和获客中心主页链接表格项清空 tooltip，避免鼠标经过按钮或表格项时弹出系统黑框。
- `backend/matrix_native_client.py#L6721-L7647`：AI 文案页知识库开关、数字人状态链接和头像链接清空 tooltip，状态文本仍保留在页面可见区域。
- `backend/matrix_native_client.py#L10858-L12592`：同款替换设置项和首尾帧按钮清空 tooltip，模式选择、按钮文案和生成流程不变。
- `backend/matrix_native_client.py#L20606-L21620`：资产库、Agent.模式上传图、提示词、模型选择和示例按钮清空 tooltip，图片替换、提示词确认和模型选择功能不变。
- `backend/matrix_native_client.py#L23871-L24740`：登录页记住密码/自动登录、主题、退出和连接状态清空 tooltip，避免顶部/底部控件继续弹出黑框。
- `tests/test_native_tooltips.py#L1-L33`：新增全局源码回归测试，禁止 `backend/matrix_native_client.py` 出现任何非空 `setToolTip(...)`，后续说明必须使用页面内可见文字或状态栏。
- 验证：新增测试先在旧实现下失败并列出 28 个非空 tooltip，修复后通过；完整相关回归、编译和 diff 检查见本次交付验证。
- 回滚：回退 `backend/matrix_native_client.py`、`tests/test_native_tooltips.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。

## 2026-07-29 小红书评论读取改为必须登录
- `backend/api_server.py#L3487-L3490`：`xhs_collection_guest_mode()` 支持按动作传入默认值；小红书搜索/下载继续使用全局游客默认，评论读取可单独设为账号默认。
- `backend/api_server.py#L5644-L5669`、`backend/api_server.py#L6047-L6074`、`backend/api_server.py#L6262-L6278`：GET/POST `/api/xhs/comments` 和 `/api/finder/discover` 的小红书分支默认 `guestMode=false`，未传 `accountCollectionConfirmed=true` 时由 `xhs_collection_account_gate()` 拒绝；确认后执行 `xhs_safety_preflight()`、底层账号采集和 `xhs_safety_record()`。
- `backend/matrix_native_client.py#L4373-L4547`：获客中心选择小红书时直接发送 `guestMode=false/accountCollectionConfirmed=true`，状态提示改为“账号寻客中：使用已登录小红书账号读取评论”，不再注册游客失败后的二次确认重试。
- `backend/matrix_native_client.py#L5387-L5404`：内容采集页“小红书 -> 看评论”直接发送账号模式请求，状态提示改为“账号读取评论中：使用已登录小红书账号”；搜索、下载、图文同款下载仍使用游客优先。
- `docs/API_REFERENCE.md#L223-L234`：小红书采集请求字段说明按动作拆分默认值，明确搜索/下载默认游客，评论/寻客默认账号且必须确认账号采集。
- `tests/test_native_publish.py#L189-L234`、`tests/test_api_download_contract.py#L159-L232`：回归覆盖客户端评论/寻客账号模式、接口默认账号确认门禁，以及确认后底层调用 `guest_mode=False`。
- 验证与回滚：新增测试先在旧实现下失败，修复后通过；完整回归见本次交付验证。回滚可恢复 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_native_publish.py`、`tests/test_api_download_contract.py`、`CHANGELOG.md` 和本节文档；不涉及数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 小红书图文同款图片悬停黑框移除
- `backend/matrix_native_client.py#L8917-L8925`：图文同款原图缩略图按钮保留缩略图、序号和点击查看原图能力，但清空 Qt tooltip，避免鼠标悬停时出现黑色提示框。
- `backend/matrix_native_client.py#L8985-L8994`：远程原图加载失败或格式不可用时不再把失败信息写入缩略图 tooltip，错误仍通过状态栏/结构化日志链路排查，避免失败缩略图悬停继续弹黑框。
- `backend/matrix_native_client.py#L9101-L9115`：替换图片槽位在未选择和已选择状态都清空 tooltip，保留按钮文字“点击选择/已选择”和缩略图显示。
- `tests/test_xhs_note_replacement.py#L836-L841`、`tests/test_xhs_note_replacement.py#L1138-L1144`：新增回归断言，锁定原图缩略图和替换图槽位的 `toolTip()` 均为空。
- 验证：新增断言先在旧实现下失败，修复后相关两条测试通过；完整图文同款回归、编译和 diff 检查见本次交付验证。
- 回滚：回退 `backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可恢复旧行为；不涉及数据库迁移、OpenAPI、Docker、中心服接口或 `migration.sql`。

## 2026-07-29 小红书游客搜索推荐流误采集修复
- `backend/platform_adapters.py#L605-L622`：新增 `_xhs_search_page_matches_keyword()`，只接受 `search_result` 页面且查询参数与用户输入关键词一致的搜索页。
- `backend/platform_adapters.py#L624-L834`：`xhs_search_notes()` 增加 `search_api_state` 与 `search_verified`；只有捕获到 `/search/notes` 响应或 URL 校验通过时才保留页面笔记。游客模式停留在发现页/推荐流时清空结果，返回 `blocked=true` 和 `message=xhs_search_result_unverified`，再由既有游客受限流程提示用户确认账号采集。
- `tests/test_xhs_lead_filtering.py#L42-L63`：新增回归测试，覆盖关键词 URL 匹配、发现页不匹配、搜索词不一致，以及搜索函数必须包含未验证结果拦截。
- 验证与回滚：新增测试先在旧实现下失败，修复后通过；完整回归见本次交付验证。回滚可恢复 `backend/platform_adapters.py`、`tests/test_xhs_lead_filtering.py`、`CHANGELOG.md` 和本节文档；不涉及数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 小红书游客采集登录弹窗自动处理
- `backend/platform_adapters.py#L166-L220`：新增 `_XHS_CLOSE_GUEST_LOGIN_MODAL_JS` 和 `_xhs_close_guest_login_modal()`，识别“手机号登录 / 扫码登录 / 登录后推荐更懂你的笔记”等游客登录弹窗，并点击可见关闭按钮；关闭失败时返回 `loginWall=true`。
- `backend/platform_adapters.py#L380-L388`：`xhs_guest_collection_block_error()` 将 `loginWall=true` 统一归类为 `xhs_guest_login_required`，继续触发客户端已有“公开访问受限”确认流程。
- `backend/platform_adapters.py#L624-L834`、`backend/platform_adapters.py#L1277-L1387`、`backend/platform_adapters.py#L1626-L1748`：小红书搜索、读取评论、笔记下载在浏览器加载页面后先尝试关闭登录弹窗；其中搜索和下载仍由客户端游客优先发起，评论读取当前由客户端和接口默认改为账号模式。若弹窗无法关闭，结果明确返回需要登录，不继续伪装成空结果。
- `tests/test_xhs_lead_filtering.py#L23-L40`：新增回归测试，锁定三个采集入口都必须调用登录弹窗关闭逻辑，并确认 `loginWall=true` 会要求用户确认账号采集。
- 验证与回滚：新增测试先在旧实现下失败，修复后通过；相关回归和编译见本次交付验证。回滚可恢复 `backend/platform_adapters.py`、`tests/test_xhs_lead_filtering.py`、`CHANGELOG.md` 和本节文档；不涉及数据库迁移、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 企业家团队成员按钮刷新修复
- `backend/matrix_native_client.py#L3560-L3574`：团队成员页说明文案改为角色中性表达，并把“当前企业”标签保存为 `self._org_label`，便于后续按角色统一隐藏。
- `backend/matrix_native_client.py#L3589-L3594`：新增 `_apply_role_visibility()`，按 `product_role()=="platform_admin"` 统一控制“添加企业 / 添加成员 / 企业下拉 / 当前企业标签”可见性。
- `backend/matrix_native_client.py#L3597-L3598`、`backend/matrix_native_client.py#L3705-L3706`：进入页面和收到成员加载回调时重新应用角色可见性，修复企业家登录后页面残留管理员按钮的问题。
- `tests/test_role_permissions.py#L167-L180`：新增回归测试，锁定团队成员页必须在登录后重新应用角色按钮权限。
- 验证：新增测试先在旧实现下失败，修复后通过；`tests.test_role_permissions` 全部通过。回滚：回退 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 同款替换首尾帧接入云豆扣费
- `backend/matrix_native_client.py#L685-L692`：客户端能力价格增加 `comic_keyframe_image=0.14`，保持 `1 云豆 = 1 元` 口径，并与 LK888 图片生成价格一致。
- `backend/matrix_native_client.py#L780-L799`：新增同款替换首尾帧扣费和退款辅助函数，扣费 `ref` 包含 job、片段、尝试时间戳和 `frame:1/2`，便于流水追溯。
- `backend/matrix_native_client.py#L11819-L11901`、`backend/matrix_native_client.py#L11959-L11961`：漫剧项目模式生成首尾帧前逐帧扣云豆；提交、等待、下载或结果缺失失败时退回已扣首尾帧费用，首尾帧保存成功后不再因后续视频失败退款。
- `backend/central_server.py#L2936-L2947`：中心服能力价格表登记 `comic_keyframe_image=0.14`，避免客户端自报金额覆盖平台价格。
- `tests/test_video_replacement.py#L994-L1120`、`tests/test_billing_unified.py#L111-L117`：覆盖首尾帧提交前两笔扣费、图片阶段失败退款，以及中心服能力价格。
- 验证：新增测试先在旧实现下失败，修复后通过；完整回归见本次交付验证。回滚：回退 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_video_replacement.py`、`tests/test_billing_unified.py`、`docs/API_REFERENCE.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库结构、Docker、OpenAPI 路由或 `migration.sql`。

## 2026-07-29 同款替换删除原片主角预览与确认区
- `backend/matrix_native_client.py#L10436-L10494`：同款替换素材区域删除主角预览框、漫剧项目模式提示文字和“原片主角确认”下拉行；场景、模型、声音来源、AI 音色、上传配音和虚拟模特行整体上移。
- `backend/matrix_native_client.py#L10717-L10731`：新增 `_auto_confirm_principal_actor_candidate()`，当后端返回 `principalActor.status=manual_required` 且存在候选帧时，自动使用第一张候选帧写入 `manualFramePath`，不再依赖可见下拉框。
- `backend/matrix_native_client.py#L10760-L10777`、`backend/matrix_native_client.py#L10826-L10873`、`backend/matrix_native_client.py#L11178-L11189`：方案就绪、载入源视频和开始生成逻辑移除对 `principal_actor_lab/principal_actor_preview/target_person` 的强依赖；生成前若仍没有可用候选帧，则提示重新生成替换方案。
- `tests/test_video_replacement_v2.py#L5116-L5186`：回归锁定 UI 不再创建或添加上述控件，并验证低置信度主角候选会自动确认第一张候选帧。
- 验证：新增/修改测试先在旧实现下失败；实现后相关 2 条测试通过，随后执行同款替换相关回归和 `py_compile`。回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 同款替换声音来源改为自动
- `backend/matrix_native_client.py#L10466-L10480`：同款替换页“声音来源”下拉框移除“原片声音”，默认项改为 `自动/auto`，提示文案改为“自动使用生成视频自带声音”；AI 音色和上传完整配音入口保留。
- `backend/matrix_native_client.py#L10613-L10644`、`backend/matrix_native_client.py#L17068-L17081`：客户端选择值和任务字段默认改为 `auto`；历史 `source/origin/original/source_audio` 兼容映射为 `auto`，合法值收敛为 `auto/tts/uploaded`。
- `backend/matrix_native_client.py#L8255-L8260`、`backend/matrix_native_client.py#L9555-L9561`、`backend/matrix_native_client.py#L16229-L16252`：`auto` 不把口播稿片段标记为 talking，漫剧项目模式允许 `auto`，`tts/uploaded` 生成口播底片时也使用 `auto` 生成视频自带音轨作为底片声音。
- `backend/matrix_native_client.py#L18323-L18551`：非口播片段在 `auto` 模式下下载远程生成视频后直接保留自带声音，不调用 `_replace_segment_audio_from_source()`，也不从原片 `source_segment` 回填音频；FaceFusion 输出丢音轨时只从本次 `edited_path` 回填。
- `tests/test_video_replacement_v2.py#L515-L523`、`tests/test_video_replacement_v2.py#L3026-L3059`、`tests/test_video_replacement_v2.py#L3914-L3940`：回归覆盖 UI 不再出现“原片声音”、默认主角片段不回填原片音频、`auto` 不触发 talking、漫剧模式允许 `auto`。
- 验证：先运行新增/修改测试观察旧实现失败；实现后运行声音来源相关 7 条回归测试通过，并执行 `py_compile`。回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/API_REFERENCE.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 同款替换操作列按钮紧凑化
- `backend/matrix_native_client.py#L12232-L12251`：漫剧项目模式操作列使用居中 `QHBoxLayout`，边距收紧为 `4,6,4,6`，间距固定 4px；“重生”和“删除”均改为 30px `_round_icon_btn()`，避免两个文本按钮在窄列内重叠。
- `backend/matrix_native_client.py#L12265-L12277`：普通同款替换模式的删除按钮也改为 30px 垃圾桶图标按钮，悬停提示保留“删除”，不再使用 92px 文本按钮。
- `tests/test_video_replacement_v2.py#L491-L512`：回归锁定操作列使用 `refresh/trash` 图标按钮、30px 尺寸、4px 间距，并禁止旧 `72x30` / `92x30` 文本按钮回归。
- 验证：新增测试先在旧实现下失败；修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_replacement_segment_table_uses_readable_script_editor_and_fixed_actions tests.test_video_replacement_v2.VideoReplacementV2Test.test_replacement_segment_actions_use_compact_icon_buttons tests.test_video_replacement_v2.VideoReplacementV2Test.test_comic_segment_table_uses_two_frame_columns_without_editor_overflow -v` 通过，`py_compile` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 小红书默认游客采集与账号采集确认
- `backend/platform_adapters.py#L624-L834`、`backend/platform_adapters.py#L1277-L1387`、`backend/platform_adapters.py#L1390-L1471`、`backend/platform_adapters.py#L1626-L1748`：小红书搜索、读取评论、获客发现和笔记下载均支持 `guest_mode` 参数；搜索、下载和图文同款下载保持游客优先，评论读取和获客中心小红书寻客按 2026-07-29 后续规则改为账号默认。
- `backend/api_server.py#L3487-L3547`：新增 `xhs_collection_guest_mode()`、`xhs_account_collection_confirmed()`、`xhs_collection_account_gate()` 和 `xhs_log_guest_collection_block()`，统一处理默认游客、未确认账号采集拦截、确认后风控预检和脱敏结构化日志。
- `backend/api_server.py#L5574-L5594`、`backend/api_server.py#L6005-L6026`、`backend/api_server.py#L6204-L6218`、`backend/api_server.py#L6265-L6278`、`backend/api_server.py#L6353-L6366`：GET/POST 评论读取、获客发现、搜索和下载入口接入 `guestMode` / `accountCollectionConfirmed`；游客采集不写入安全计数，确认账号采集仍走 `xhs_safety_preflight()` 和 `xhs_safety_record()`。
- `backend/matrix_native_client.py#L1118-L1152`、`backend/matrix_native_client.py#L4339-L4510`、`backend/matrix_native_client.py#L5127-L5328`：客户端新增游客受限识别和“公开访问受限”确认框；内容搜索、下载、图文同款下载默认发送 `guestMode=true`，用户确认后只对当前动作重试一次 `guestMode=false/accountCollectionConfirmed=true`。评论读取和获客中心小红书寻客已改为直接账号模式。
- `tests/test_xhs_lead_filtering.py#L12-L22`、`tests/test_api_download_contract.py#L106-L157`、`tests/test_xhs_safety_mode.py#L86-L101`、`tests/test_native_publish.py#L189-L220`：回归覆盖适配器参数、接口默认游客、账号采集确认门禁、风控预检和客户端一次性确认重试。
- 验证与回滚：先观察新增测试失败，再实现通过。回滚可设置 `XHS_GUEST_COLLECTION_DEFAULT=0` 后重启本地客户端和本地执行引擎，或回退上述代码和测试文件；无数据库迁移、无新公共路由、无 Docker 结构变更，`migration.sql` 不需要修改。

## 2026-07-29 Seedance 音频时长超限进入备用模型链
- `tools/aicanvas_remote/server_current.py#L12936-L12952`：新增严格错误分类，仅识别 Seedance R2V `InvalidParameter` 中明确包含音频时长必须小于等于模型上限的错误，归一为 `InvalidParameter.AudioDurationExceeded`。
- `tools/aicanvas_remote/server_current.py#L13255-L13310`：该错误与真人隐私拒绝共用既有有序降级状态机；失败的 Seedance 调用先退款，Vidu/首尾帧备用参数移除音频字段，分辨率等其他参数错误仍直接失败。
- `tests/test_aicanvas_real_person_fallback.py#L288-L304`：回归覆盖超过 15.2 秒的真实 Seedance 错误会切换 Vidu、移除音频并保留退款；本次专项回归 52/52 通过。包含旧版 V2 的扩展套件 270/273 通过，剩余 3 条均为小红书内容采集既有改动导致，与本链路无关。
- 真实任务 `be79cc777af2497bbc95601b12b65eab` / 项目 299：3 个片段均已由 Vidu 成功生成；片段 2 验证了 `InvalidParameter.AudioDurationExceeded` 自动退款并切换 Vidu，片段 1、3 未被重复生成。
- 回滚：恢复本次远程部署前 `server.py` 时间戳备份并只重启 `ai-canvas.service`。无数据库迁移，不重启本地客户端。

## 2026-07-29 同款替换精确分镜项目初始化
- `backend/matrix_native_client.py#L9654-L9700`：同款替换创建漫剧项目时写入 `source_mode=matrix_video_replacement`、`manualAssetsOnly=true`、精确 `storyboardCount`，并把每个本地片段的纯画面描述和最终口播稿分别写入对应分镜。
- `tools/aicanvas_remote/server_current.py#L14146-L14202`：远程漫剧服务仅对 `matrix_video_replacement` 接受外部分镜种子，按项目 ID 生成稳定分镜 ID；项目初始角色、场景、道具保持为空，等待本地客户端上传真实素材。普通漫剧项目忽略外部分镜种子，继续原有分析流程。
- `tests/test_video_replacement.py#L260-L286`、`tests/test_aicanvas_matrix_project_seed.py#L35-L67`：覆盖客户端精确分镜载荷、同款替换项目不自动创建占位资产、普通漫剧项目不接受外部分镜种子。
- 验证：本次专项回归 52/52 通过；包含旧版 V2 的扩展套件 270/273 通过，3 条未通过项均属于小红书内容采集既有改动；`backend/matrix_native_client.py` 和 `tools/aicanvas_remote/server_current.py` 编译通过。
- 回滚：本地回滚上述客户端和测试文件；远程恢复部署前 `server.py` 时间戳备份并只重启 `ai-canvas.service`。项目 298 保留为故障证据，不继续生成；本次无数据库迁移，不重启本地客户端。

## 2026-07-29 小红书标题 20 字限制
- `backend/xhs_note_replacement.py#L8-L110`：新增 `XHS_TITLE_LIMIT=20` 和 `_xhs_title()`，图文同款三套候选标题生成时统一去掉空白并截断到 20 字以内。
- `backend/matrix_native_client.py#L4633-L4635` 与 `backend/matrix_native_client.py#L8969-L8969`：AI 预填“标题（必填）”时同样使用 20 字限制，防止输入框自动出现超长小红书标题。
- `backend/matrix_native_client.py#L5649-L5649`：素材发布列表标题列文案改为“标题（可编辑，抖音最多30字，小红书最多20字）”。
- `backend/matrix_native_client.py#L5721-L5722` 与 `backend/matrix_native_client.py#L5878-L5882`：实际发布标题按当前平台截断，抖音 30 字，小红书 20 字；编辑弹窗计数提示也跟随当前发布平台。
- `tests/test_xhs_note_replacement.py#L170-L186`、`tests/test_xhs_note_replacement.py#L1038-L1051`、`tests/test_native_publish.py#L65-L82`：新增回归测试，覆盖三套方案标题、AI 预填标题、素材发布表头和按平台截断。
- 验证：新增测试先在旧实现下失败；修复后运行标题限制相关测试均通过，完整相关回归见本次交付验证。
- 回滚：回滚 `backend/xhs_note_replacement.py`、`backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 Agent.模式上传图操作提示改为可见小字
- `backend/matrix_native_client.py#L20488-L20494`：Agent.模式 `_make_ref_cell()` 清空已上传图片按钮 tooltip，并把操作说明直接写入缩略图下方小字，显示为“待修改图/参考图”加“点击替换 / 右键删除”两行。
- `tests/test_asset_library_shared_button.py#L89-L101`：新增回归测试，锁定已上传图片缩略图不再使用 tooltip 展示操作说明，且该方法内不再使用 `os.path.basename(path)` 拼接长提示。
- 验证：先运行新增单项测试确认旧实现失败；修复后单项通过。完整相关验证见本次回复。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 数字人口播 TTS 不进入素材发布
- `backend/matrix_native_client.py#L1300-L1308`：`upload_asset_url()` 支持向通用素材上传透传 `metadata`，保持原有图片、视频、音频上传调用兼容。
- `backend/matrix_native_client.py#L5731-L5746`：素材发布列表过滤 `hideFromPublish/internalOnly`、`source=digital_human_tts`，并隐藏历史标题以“数字人TTS声音-”开头的音频素材。
- `backend/matrix_native_client.py#L7235-L7253`：数字人口播“上传TTS声音”继续上传音频供生成使用，但写入 `hideFromPublish=True` 和 `source=digital_human_tts`，不再作为可发布素材展示。
- `tests/test_native_publish.py#L308-L335`：回归覆盖历史数字人 TTS 音频和新标记音频均不显示在素材发布，并锁定数字人口播上传声音时必须传隐藏标记。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_digital_human_navigation -v` 通过 38 项；未修改接口契约、数据库结构、OpenAPI 或 `migration.sql`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md` 和本条实现索引即可恢复旧行为；历史音频文件未被删除。

## 2026-07-29 资产库图文同款不再打开 JSON
- `backend/matrix_native_client.py#L21033-L21037`：资产库 `note_template` 卡片动作按钮移除“打开”入口，只保留“文件夹”和“删除”，避免用户直接打开本地图文模板 JSON。
- `tests/test_asset_library_shared_button.py#L75-L87`：新增回归测试，锁定图文模板卡片不能包含 `open_asset(a)` 的“打开”按钮，且仍保留文件夹定位和删除。
- 验证：先运行新增测试确认旧实现失败；修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_asset_library_shared_button -v` 通过 7 项，`py_compile` 通过。`git diff --check` 仍被同文件中同款替换区域既有行尾空白阻断，非本次资产库按钮改动引入。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 小红书内容采集默认显示浏览器
- `backend/platform_adapters.py#L99-L107`：`_xhs_open_context()` 新增 `default_headless` 参数，并继续把 `XHS_*_HEADLESS` 环境变量作为最终覆盖开关。
- `backend/platform_adapters.py#L522-L535`：`xhs_search_notes()` 调用小红书搜索浏览器上下文时传入 `default_headless=False`，因此默认弹出浏览器；设置 `XHS_SEARCH_HEADLESS=1` 可回滚为后台搜索。
- `backend/platform_adapters.py#L1500-L1513`：`xhs_download_note()` 下载笔记时同样传入 `default_headless=False`；设置 `XHS_DOWNLOAD_HEADLESS=1` 可回滚为后台下载。
- `backend/matrix_native_client.py#L5117-L5159`：内容采集页在小红书搜索、下载和“图文同款”下载时显示“正在打开浏览器，请登录/不要关闭窗口”，抖音流程保持原提示。
- `tests/test_native_publish.py#L157-L168` 与 `tests/test_video_replacement_v2.py#L320-L331`：新增回归测试，分别锁定小红书采集浏览器默认可见和客户端提示文案。
- 验证：新增测试先在旧实现下失败；修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish.NativePublishTest.test_xhs_collection_browser_is_visible_by_default -v` 和 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_xhs_collection_actions_explain_visible_browser -v` 均通过。
- 回滚：回滚 `backend/platform_adapters.py`、`backend/matrix_native_client.py`、`tests/test_native_publish.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；或临时设置 `XHS_SEARCH_HEADLESS=1`、`XHS_DOWNLOAD_HEADLESS=1` 并重启本地执行引擎恢复后台采集。本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 Agent.模式上传图片槽位铺满
- `backend/matrix_native_client.py#L19437-L19439`：新增 `REF_SLOT_W/REF_SLOT_H/REF_SLOT_RADIUS`，统一 Agent.模式上传图片槽位尺寸与圆角。
- `backend/matrix_native_client.py#L20266-L20282`：已上传图片按钮改为 `112px × 56px`，图片按槽位尺寸 `KeepAspectRatioByExpanding` 放大后居中裁切，再用同尺寸 icon 铺满按钮内容区。
- `backend/matrix_native_client.py#L20298-L20307`：“添加图片”空槽位也使用同一横向尺寸，并去掉按钮内边距，避免左右两侧视觉留白。
- `tests/test_agent_mode_defaults.py#L211-L227`：新增源码契约测试，锁定上传槽位尺寸、居中裁切策略和不再使用旧 `52px × 52px` 缩略图。
- 验证：先运行新增测试确认旧实现失败；修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_reference_slots_fill_horizontal_content_area tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_supports_ordered_multi_image_references -v` 通过，`py_compile` 通过，`git diff --check` 仅剩文档 LF/CRLF 提示。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 小红书图文同款三套正文加长
- `backend/xhs_note_replacement.py#L107-L132`：`copy_candidates()` 的三套正文候选扩展为约 120-180 字的小红书段落，分别覆盖种草建议、避坑对比、本地咨询方向；正文继续不混入 `#标签`，并保留去模板话术规则。
- `tests/test_xhs_note_replacement.py#L151-L169`：新增长度回归测试，要求三套正文均不少于 120 字、不超过 220 字，并确认正文不带标签。
- 验证：先运行新增测试确认旧正文 73 字会失败；修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNotePreviewTests -v` 通过，三套示例正文长度为 124、124、123。
- 回滚：回滚 `backend/xhs_note_replacement.py`、`tests/test_xhs_note_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-28 分解视频打开视频按钮无反馈修复
- `backend/matrix_native_client.py#L5573-L5587`：`VideoBreakdownPage.open_video()` 先校验 `_video_path` 是否为空和本地文件是否存在；打开成功、文件缺失、直接播放失败都会写状态栏提示。
- `backend/matrix_native_client.py#L12026-L12065`：保留 `_open_path()` 调用系统默认播放器，新增 `_reveal_path()` 作为兜底；Windows 下用 Explorer 选中文件，macOS 下用 Finder 定位文件，Linux 下打开所在目录。
- `tests/test_video_breakdown.py#L121-L170`：回归覆盖打开失败、打开成功、播放器失败后打开文件夹、源视频文件缺失四种情况。
- 验证：先运行新增用例确认旧实现缺少 `_reveal_path`、成功无状态反馈、文件缺失仍尝试打开；修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_breakdown -v` 通过 39 项，`.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_breakdown.py` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_breakdown.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-28 小红书图文同款必填字段 AI 预填
- `backend/matrix_native_client.py#L8864-L8972`：图文同款页面新增来源快照、AI JSON 解析、AI 字段生成和异步预填逻辑。输入为原始标题、正文和标签；输出为 `title/region/audience/sellingPoints`。所在地判断不出来保留空字符串，卖点过滤原笔记标题和 `#标签`。
- `backend/matrix_native_client.py#L9114-L9191`：`_on()` 新增 `xhs_note_business_prefill` 事件分支；`_on_business_prefill()` 只填空字段，不覆盖用户已编辑内容，并在 AI 失败时提示“AI 生成字段失败，请手动填写”。
- `backend/matrix_native_client.py#L9019-L9056`：切换新笔记时让旧 AI 预填结果失效，清空旧业务字段后再启动新笔记的 AI 预填。
- `tests/test_xhs_note_replacement.py#L907-L974`：回归覆盖 AI 自动填标题、所在地、目标客户和卖点；卖点不能用原笔记标题；所在地判断不出时保持空白。
- 验证：新增两条测试先在旧实现下失败；修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_collection_handoff_ai_prefills_editable_business_fields tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_collection_handoff_ai_leaves_unknown_region_blank tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_new_collection_handoff_clears_previous_note_and_replacement_state -v` 通过；`py_compile` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-28 资产库卡片按钮一行紧凑布局
- `backend/matrix_native_client.py#L19553-L19565`：`_round_icon_btn()` 自身固定 `QSizePolicy.Fixed`，并在局部样式中写死 `padding:0` 与 `min/max-width/height`，避免继承全局 `QPushButton min-width:76px` 后被撑成长条。
- `backend/matrix_native_client.py#L20730-L20731`：`_asset_action_btn()` 改为直接返回 `_round_icon_btn(..., 30, ..., tip=text)`，参考退出登录按钮的纯图标形态，按钮名称保留在 tooltip 中。
- `backend/matrix_native_client.py#L20733-L20737`：新增 `_add_asset_action_buttons()`，在按钮前、按钮之间、按钮后都加入等权重弹性空白，让动作按钮在整行内均匀分散。
- `backend/matrix_native_client.py#L20777-L20800`：资产卡片动作区保持单行 `QHBoxLayout`，固定间距改为 0；图片卡片一行放下“参考 / 打开 / 文件夹 / 删除”四个 30px 图标按钮，视频卡片一行放下“播放 / 文件夹 / 删除”，图文模板卡片只保留“文件夹 / 删除”。
- `tests/test_asset_library_shared_button.py#L35-L86`：布局契约测试锁定一行图标按钮结构、圆形按钮宽度锁定和整行动作按钮均匀分布，确认局部样式不会再被全局按钮最小宽度撑开，也不会靠左聚集。
- 验证：先运行新增回归测试确认旧实现会被全局按钮最小宽度撑长或靠左聚集；修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_asset_library_shared_button -v`、`.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_asset_library_shared_button.py` 和 `git diff --check -- backend/matrix_native_client.py tests/test_asset_library_shared_button.py CHANGELOG.md docs/IMPLEMENTATION.md docs/TROUBLESHOOTING.md`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-28 寻找线索操作列
- `backend/matrix_native_client.py#L4324-L4333`：获客中心 `FinderPage` 线索表从 4 列扩展为 8 列，新增“打开主页 / 复制链接 / 去私信跟进 / 标记已跟进”四个显式操作列，保留用户、主页链接、意向和评论基础信息；线索表默认行高固定为 34px，避免按钮撑破表格行。
- `backend/matrix_native_client.py#L4349-L4381`：新增行级主页链接读取、系统默认浏览器打开、复制链接、带入私信跟进和本页跟进标记方法；“打开主页”当前仍调用系统默认浏览器，“去私信跟进”通过 `dm_followup` 与 `goto_nav` 事件把主页链接带入“私信 / AI 销售”页面。
- `backend/matrix_native_client.py#L4388-L4398`：新增 `finderAction` 专用紧凑按钮样式，按钮高度固定为 24px，内边距降到 `1px 6px`，避免继承全局 `ghost` 按钮的大内边距和最小宽度。
- `backend/matrix_native_client.py#L4434-L4445`：每条线索渲染四个操作按钮；“标记已跟进”点击后按钮变为“已跟进”并禁用，作为本页轻量状态提示，不写数据库。
- `backend/matrix_native_client.py#L6334-L6340`：`DMPage` 接收 `dm_followup` 事件后自动填入客户主页链接、刷新该客户历史，并提示可继续生成回复或开启全自动跟进。
- `tests/test_finder_page_actions.py#L9-L53`：新增源码契约测试，锁定四个操作列、复制/打开/私信跟进/标记跟进方法、紧凑按钮尺寸，以及 DMPage 接收获客线索主页链接。
- 验证：先运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_finder_page_actions -v` 确认旧页面缺失操作列和紧凑按钮时失败；修改后运行同命令通过，并运行 `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_finder_page_actions.py`、`.\.venv-win\Scripts\python.exe -m unittest tests.test_finder_page_actions tests.test_outreach_page_copy tests.test_native_publish tests.test_client_logout -v` 通过 36/36。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_finder_page_actions.py`、`CHANGELOG.md` 和本条实现索引即可；不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-28 AI 触达页面说明增强
- `backend/matrix_native_client.py#L4392-L4403`：获客中心 `OutreachPage` 在关键词输入区上方新增说明文案，说明 AI 触达会搜索相关视频/笔记、读取评论区、筛选咨询/比价/想了解意向客户、生成短评论话术，并通过本机浏览器在评论区回复/评论；同时明确不是私信群发，并提示默认限量、间隔发送和风控停止。
- `backend/matrix_native_client.py#L4413-L4415`：AI 触达状态提示开启自动换行，避免长风险提示在窄窗口中截断。
- `tests/test_outreach_page_copy.py#L9-L21`：新增源码契约测试，锁定页面必须解释触达流程、非私信群发、评论区执行和限频风控。
- 验证：先运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_outreach_page_copy -v` 确认旧页面说明不足时失败；修改后运行同命令通过，并运行 `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_outreach_page_copy.py`、`.\.venv-win\Scripts\python.exe -m unittest tests.test_outreach_page_copy tests.test_native_publish tests.test_client_logout -v` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_outreach_page_copy.py`、`CHANGELOG.md` 和本条实现索引即可；不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-29 同款替换双帧表格与五模型降级
- `backend/matrix_native_client.py#L9660-L9692`、`backend/matrix_native_client.py#L9846-L9895`：解析首尾两个任务 ID、补全 `/uploads/...` 相对媒体地址，并从远程分镜恢复首尾帧 URL；旧单任务 helper 和 `flowchart*` 字段继续兼容。
- `backend/matrix_native_client.py#L9937-L9962`、`backend/matrix_native_client.py#L11279-L11538`：已有远程视频 URL 时直接规范化并下载，不重复提交；首尾帧分别等待并原子保存任务 ID、URL 和视频状态。
- `backend/matrix_native_client.py#L11807-L11900`、`backend/matrix_native_client.py#L11965-L12020`：异步加载首尾帧缩略图，片段表固定为六列，口播稿编辑器受单元格尺寸约束。
- `tools/aicanvas_remote/server_current.py#L11201-L11297`：任务响应同时返回请求模型、实际模型、降级原因、候选链、当前索引和历史记录的 snake_case/camelCase 字段。
- `tools/aicanvas_remote/server_current.py#L12647-L12780`：轮询明确失败时保留原本地任务 ID 并进入下一模型；查询异常继续原任务重试，不会因 502、超时或限流创建新任务。
- `tools/aicanvas_remote/server_current.py#L12936-L13314`：默认降级顺序为 Vidu Q3、万相 2.7、Kling V3 Omni、PixVerse V6；每个失败调用单独退款，首尾帧模型删除不支持的音频字段，结构化日志不包含密钥和素材签名参数。
- `tests/test_video_replacement.py#L24-L37`、`tests/test_video_replacement.py#L706-L823`、`tests/test_video_replacement_v2.py#L474-L513`、`tests/test_aicanvas_real_person_fallback.py#L222-L402`：覆盖双任务、相对 URL、已生成视频复用、六列表格、模型顺序、字段适配、远程失败续切和空配置禁用。
- 验证：相关三组测试共 269/269 通过，`backend/matrix_native_client.py` 与 `tools/aicanvas_remote/server_current.py` 编译通过。
- 回滚：恢复远程时间戳备份并只重启 8777；本地回滚客户端和测试文件。无需数据库迁移、OpenAPI 或中心服重启；按用户要求不自动重启本地客户端。

## 2026-07-28 同款替换统一单图与漫剧远程自动时长
- `backend/matrix_native_client.py#L9082-L9133`：`_comic_project_manual_assets()` 对新旧任务的人物 URL 去重后只保留第一张，项目库只创建一个“主角”；场景和道具仍按上传内容完整创建，角色音色继续写入人物设计字段。
- `backend/matrix_native_client.py#L9136-L9165`：视频生成 payload 保留完整 `audio_prompt.dialogue.text/voice` 和 `auto_match_audio_duration=true`，由漫剧生成器按最终口播稿自动匹配或延长视频时长。
- `backend/matrix_native_client.py#L9640-L9646`、`backend/matrix_native_client.py#L10106-L10120`：同款替换统一显示“上传主角正脸全身照”并使用单文件选择器，不再按任务模式提供多图入口。
- `backend/matrix_native_client.py#L10279-L10300`、`backend/matrix_native_client.py#L10303-L10394`、`backend/matrix_native_client.py#L10396-L10452`、`backend/matrix_native_client.py#L10492-L10492`：所有模式只上传和保存第一张人物图，生成前统一校验一张清晰正脸全身照；删除旧链路三张授权照片拦截。
- `backend/matrix_native_client.py#L10698-L10763`：漫剧片段生成不再调用本地配音准备接口，不再根据临时音频改写片段时长；写入远程分镜前清理旧任务残留的 `audioUrl/audioDurationSeconds/audioPrepareStatus/audioWarning`，随后直接生成首尾帧和视频。
- `tests/test_video_replacement.py#L447-L463`、`tests/test_video_replacement.py#L632-L690`：回归覆盖旧多图任务只创建一个主角，以及漫剧片段不得调用本地音频准备接口。
- `tests/test_video_replacement.py#L912-L926`：回归锁定所有模式必须使用单文件人物选择器、只上传第一张，并禁止三图切片和三图提示回归。
- `tests/test_video_replacement_v2.py#L5014-L5049`：界面源码契约同步锁定所有模式只保存第一张人物图。
- 远程项目 293：通过漫剧后端现有的账号作用域接口删除角色 1、2；角色 4、5 在清理前已不存在。最终 API 与持久化文件均确认只剩角色 3、场景 1、道具 1，分镜 293001-293006 全部绑定上述资产。修改前备份为 `/root/AI-CanvasPro/backups/20260728-project-293-single-character/comic_projects_local.before-20260728-143933.json`，SHA-256 为 `499e302f1f65162e62173637a093e3913cd74ab2395f31ac40d88ae97c0edaca`。
- 验证：单图回归测试先在旧实现上因多文件选择器失败，修改后通过；完整同款替换回归、语法和差异检查见本次交付结果。
- 回滚：本地行为可回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`；远程项目 293 可从上述备份恢复。恢复远程备份时需同步运行中服务状态，不能只覆盖文件后继续运行。不涉及中心服、远程漫剧服务代码、数据库、OpenAPI、Docker 或 `migration.sql`。按用户要求不自动重启本地客户端。

## 2026-07-28 资产库导入与素材文件夹入口
- `backend/matrix_native_client.py#L20176-L20184`、`backend/matrix_native_client.py#L20185-L20193`：资产库页头部按钮从“打开文件夹”改为“导入资产”，刷新按钮保留；单一来源的“本地资产”切换按钮移除，只保留右侧资产数量。
- `backend/matrix_native_client.py#L20253-L20287`：新增 `import_assets()`，通过 `QFileDialog.getOpenFileNames()` 多选图片/视频，按扩展名识别 `image/video`，调用 `add_asset(path, kind=kind, prompt="", source="手动导入")` 复制并登记到本地资产库，导入后刷新列表。
- `backend/matrix_native_client.py#L20346-L20354`、`backend/matrix_native_client.py#L20371-L20377`：每个素材卡片在“播放/打开”旁新增“文件夹”按钮，`open_asset_folder()` 打开素材文件所在目录；文件缺失时复用资产库缺失提示。
- `tests/test_asset_library_shared_button.py#L19-L31`：回归测试锁定顶部不再出现“打开文件夹”和“本地资产”按钮，且导入资产、卡片级文件夹入口存在。
- 验证：先运行新增测试确认旧实现失败；修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_asset_library_shared_button -v`，再运行 `py_compile` 和 `git diff --check`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_asset_library_shared_button.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-28 小红书图文同款正文去模板化
- `backend/xhs_note_replacement.py#L107-L132`：`copy_candidates()` 保留三套标题/正文/标签候选，但正文改为“种草建议 / 避坑对比 / 本地咨询”三种自然口吻，去掉“这组图文按真实体验整理”“这次把重点放在…”“先收藏再对比”等固定模板句，并继续让标签只存在于 `tags` 字段。
- `tests/test_xhs_note_replacement.py#L126-L150`：新增回归测试，锁定固定模板话术不能再出现在三套正文里，同时正文仍包含业务名和卖点，正文中不混入 `#` 标签。
- 验证：先运行新增定向测试确认旧实现失败；修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNotePreviewTests -v` 通过。完整回归和编译检查见本次最终回复。
- 回滚：回滚 `backend/xhs_note_replacement.py`、`tests/test_xhs_note_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-07-28 登录成功移除 evil-eye 覆盖过场
- `backend/matrix_native_client.py#L22546-L22557`：登录成功路径删除 `evil_eye_login.png` 遮罩、900ms 全屏缩放和 Qt 动画组，改为先释放登录页背景媒体管线与缓存，再立即进入主界面；登录失败路径仍停留在登录页并显示错误。
- `tests/test_login_success_transition.py#L9-L41`：新增回归测试，锁定登录成功不再引用 evil-eye 素材、成功过场常量、遮罩构建和 `_play_success_transition()`，并确认 `self.bg.release()` 先于 `self.on_success(info)` 执行。
- `tests/test_login_centered_layout.py#L40-L47`：布局回归测试同时锁定后续居中布局调整不能恢复 evil-eye 成功过场。
- 验证：先运行新增/更新测试确认旧实现失败；实现后运行 `python -m py_compile backend\matrix_native_client.py tests\test_login_success_transition.py tests\test_login_centered_layout.py tests\test_native_enterprise_invite.py`、`python -m unittest tests.test_login_success_transition -v`、`python -m unittest tests.test_login_centered_layout -v` 通过。当前 Windows Python 环境缺少 `requests`/`loguru`，涉及这些依赖的扩展用例无法完整执行。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_login_success_transition.py`、`tests/test_login_centered_layout.py`、`tests/test_native_enterprise_invite.py` 和本条实现索引即可恢复登录成功 evil-eye 过场；本次不涉及中心服、OpenAPI、数据库迁移、Docker 或 `migration.sql`。

## 2026-07-28 Agent.模式 LK888 模型权威映射
- `backend/matrix_native_client.py#L1723-L1753`：Agent.模式的本地 LK888 兜底模型表保留真实模型 ID 与中文显示名，其中 `doubao-seedance-1-5-pro-251215` 对应 `Seedance 1.5 Pro`，作为默认视频模型的权威映射。
- `backend/matrix_native_client.py#L1757-L1758`：新增本地权威模型字典和顺序表，后续标签解析与模型列表排序都以该表优先。
- `backend/matrix_native_client.py#L1954-L1973`：`_lk888_canonical_model_row()` 和 `_lk888_model_label()` 在命中已确认模型 ID 时，忽略 LK888 目录返回的错配 `display_name`，避免把 Seedance 显示成 Seedream 等其它模型。
- `backend/matrix_native_client.py#L2015-L2042`：`_lk888_models_by_type()` 先放入本地权威模型，再追加 LK888 目录补充项，并按权威顺序置顶，目录缺失默认模型时也不会把默认视频模型移除。
- `tests/test_agent_mode_defaults.py#L222-L252`：回归测试覆盖 LK888 目录错标显示名、目录缺失默认视频模型时仍保留并优先展示 Seedance。
- 验证：先运行新增两条回归用例确认旧实现失败；修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_canonical_model_label_overrides_lk888_catalog_mismatch tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_mode_video_models_keep_canonical_defaults_before_catalog_additions -v`，再运行完整 `tests.test_agent_mode_defaults` 和 `py_compile`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、Web 端、OpenAPI、数据库、Docker 或 `migration.sql`。代码生效需要手动重启本地客户端。

## 2026-07-28 同款替换漫剧生成提交恢复
- `backend/matrix_native_client.py#L8466-L8510`：`_comic_visual_prompt_text()` 进一步解析嵌入式原片拆解标签，只保留 `画面/人物/产品/动作/道具/场景/节奏`，跳过 `字幕/口播/OCR/转写`，并丢弃单独的 `当前片段原片镜头约束` 标题行，减少漫剧项目创建 payload 噪声。
- `backend/matrix_native_client.py#L9039-L9114`：新增漫剧生成提交恢复 helper。`_comic_generation_submit_can_recover()` 识别 `计费请求重复`、`Read timed out` 和本机代理 `127.0.0.1` 读超时；`_comic_request_no_proxy()` 使用 `requests.Session(trust_env=False)` 禁用环境代理；`_comic_recover_storyboard_media()` 从项目详情分镜里回收首尾帧/视频任务 ID 或结果 URL。
- `backend/matrix_native_client.py#L9117-L9224`：`ComicProjectAdapter` 默认请求函数切到 `_comic_request_no_proxy`，避免漫剧接口误走系统代理；`create_project()` 创建远程漫剧项目的超时从 60 秒放宽到 240 秒；单元测试注入的 `request_fn` 仍保持兼容。
- `backend/matrix_native_client.py#L10516-L10580`：首尾帧和视频提交阶段遇到可恢复异常时先调用项目详情回查；如果远程已经生成 `flowchartTaskId` / `videoTaskId` 或结果 URL，则继续等待或直接使用结果，并在片段上记录 `comicRecoveryStatus=recovered` 与 `comicRecoveryReason`。
- `tests/test_video_replacement.py#L249-L271`、`tests/test_video_replacement.py#L285-L326`、`tests/test_video_replacement.py#L393-L421`、`tests/test_video_replacement.py#L620-L691`：回归覆盖嵌入式拆解清洗、漫剧请求禁用环境代理、创建项目长超时、`计费请求重复` 后从分镜任务恢复、以及本机代理读超时被识别为可恢复错误。
- 验证：先运行新增三项测试观察旧实现失败；修复后新增三项通过。最终完整同款替换回归、编译和 diff 检查见本次回复。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、远程漫剧 `server.py`、OpenAPI、数据库或 `migration.sql`。按用户要求不自动重启本地客户端。

## 2026-07-28 本地客户端风控中心接入小红书违规风险
- `backend/matrix_native_client.py#L828-L947`：新增本地账号风险事件文件 `account_risk_events.json` 的读写与去重；`_account_risk_event_from_task()` 会从小红书任务返回里识别 `账号违规提示/账号违规预警`、第三方工具/脚本/自动浏览/自动发布、`xhs_ip_risk`、`300012`、`300031` 等平台风险，并写入结构化日志 `account_platform_risk_recorded`。
- `backend/matrix_native_client.py#L986-L1041`：新增 `_account_risk_summary()`，风控中心不再只按在线状态和 Cookie 判断；账号自身 `riskEvents/platformRisks/lastRisk` 或本地持久化的小红书风险事件命中时，在线账号也会显示为“高风险”，并给出最近风险与建议动作。
- `backend/matrix_native_client.py#L1069-L1085`：`submit_local_task()` 在任务提交失败、轮询完成失败或超时时都会尝试记录平台风险，避免小红书任务已经返回风险码但风控中心仍显示低风险。
- `backend/matrix_native_client.py#L19922-L20024`：风控中心账号表扩展为 `账号/平台/状态/风险/最近风险/建议动作` 六列，进入页面时同时加载账号列表和本地风险事件。
- `tests/test_agent_mode_defaults.py#L99-L132`：新增回归测试，覆盖账号直接携带小红书违规提示、以及任务持久化 `xhs_ip_risk/300012` 后同平台账号显示高风险。
- 验证：先运行新增定向用例确认旧实现失败；修复后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_risk_summary_marks_xhs_account_violation_as_high_risk tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_risk_summary_applies_persisted_xhs_task_risk_to_same_platform -v`，2/2 通过。完整回归与编译检查见本次最终回复。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md`、`CHANGELOG.md` 即可恢复旧逻辑；如需清理本地风险缓存，可删除运行数据目录下的 `account_risk_events.json`。本次只涉及本地客户端，不涉及 Web 端、中心服、OpenAPI、数据库迁移或 `migration.sql`。

## 2026-08-04 客户端默认连接公网中心服
- `backend/matrix_native_client.py#L56-L66`：`CENTRAL` 保持优先读取 `MATRIX_CENTRAL` / `CENTRAL_URL`，无环境变量时默认使用 `http://127.0.0.1:9080`（与出厂 `start-visible-client.bat` 自启的本地中心服一致）；中心服地址使用独立校验 `validate_central_service_url`，允许 HTTP 中心服，但不放宽远程素材 URL 的 HTTPS 校验。
- `backend/.env.example#L2-L2`、`docs/DEPLOYMENT.md#L310-L310`：示例配置和部署环境变量表将中心服默认对齐本地 `http://127.0.0.1:9080`；连接远程中心服时显式覆盖。
- `tests/test_video_breakdown.py#L42-L58`：RED/GREEN 覆盖默认公网中心服和本地开发覆盖能力。
- 验证与影响：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_breakdown.VideoBreakdownHelpersTest.test_central_defaults_to_public_production_server tests.test_video_breakdown.VideoBreakdownHelpersTest.test_central_env_override_still_supports_local_development`。本次只影响本地客户端默认配置、测试和文档；不改变中心服 API、OpenAPI、数据库、Docker、密钥或 `migration.sql`。生效需要重新打包并替换服务器安装包；回滚恢复默认值和上一版安装包。

## 2026-08-04 登录页只保留漫剧账号登录
- `backend/matrix_native_client.py#L30324-L30343`：登录卡标题改为“账号登录”，副文案改为“使用漫剧账号密码登录 AI爆款复刻”；`self.tab_login/self.tab_reg/self.tab_invite` 保留为隐藏兼容对象，但不再创建 `tabrow` 或加入登录页布局。
- `backend/matrix_native_client.py#L5831-L5831`、`backend/matrix_native_client.py#L6004-L6004`：企业中心“邀请成员”的复制弹窗和提示文案不再引导用户到登录页选择“加入企业”，改为建议管理员用“添加成员”或“重置密码”交付成员账号。
- `tests/test_native_enterprise_invite.py#L42-L84`、`tests/test_login_centered_layout.py#L26-L38`：覆盖登录页隐藏加入企业入口、企业邀请文案不再指向登录页，以及登录卡营销布局仍在卡片外。
- 验证与影响：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_enterprise_invite tests.test_login_centered_layout tests.test_auth_login_modes` 和 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py`。本次只影响本地客户端 UI 和测试文档，不改变中心服 API、OpenAPI、数据库、Docker、环境变量或 `migration.sql`；重启本地客户端或重新打包安装包后生效。回滚 `backend/matrix_native_client.py`、相关测试、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可恢复旧入口。

## 2026-07-28 同款替换漫剧画面描述与口播分离
- `backend/matrix_native_client.py#L8466-L8496`：`_comic_visual_prompt_text()` 从旧 LK888 长提示词中剔除 `源视频锁定`、`原片拆解证据`、`字幕安全`、`人物参考图只用于`、`上传产品必须`、`口播对应`、`OCR/转写` 等控制语，去掉 `画面/镜头/动作/产品/场景` 前缀后只保留短视觉描述。
- `backend/matrix_native_client.py#L8499-L8517`：`_comic_segment_script_line()` 创建漫剧项目 `source_text` 时改写为 `分镜 / 画面 / 对白 / 景别 / 角度 / 音效 / 运镜 / 最终提示词` 的短结构；对白来自用户最终口播稿，但画面字段和最终提示词不含对白原文。
- `backend/matrix_native_client.py#L8553-L8604`：`_comic_project_manual_assets()` 写入人物、场景、道具时补齐 `reference_image/reference_images/referenceImages`；人物资产同步写入 `voiceName/ttsVoice/voiceStatus/voiceType/voiceProvider/voiceModel/voiceDescription`，用于漫剧项目库角色的人物设计音色追踪。
- `backend/matrix_native_client.py#L8607-L8645`：`_comic_storyboard_video_payload()` 的 `keyframes_video_prompt/video_prompt/prompt` 统一使用清洗后的视觉提示，台词只进入 `audio_prompt.dialogue.text`；存在 `comicProjectId` 时同步传 `project_id/projectId`，避免远程接口按错误作用域查项目。
- `backend/matrix_native_client.py#L8785-L8787`、`backend/matrix_native_client.py#L10185-L10191`：`prepare-dialogue-audio` 或 `comic_api_http_404` 只降级为 `audioPrepareStatus=skipped` 和 `audioWarning`，后续继续走首尾帧和视频生成；其它音频准备错误仍按片段失败处理。
- `tests/test_video_replacement.py#L186-L246`、`tests/test_video_replacement.py#L329-L382`、`tests/test_video_replacement.py#L523-L579`：回归覆盖干净剧本、上传资产字段、`project_id/projectId` 传递，以及音频准备 404 不再导致片段失败。
- 验证：先运行新增目标用例观察旧实现失败 5 项；修复后 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement -v` 26/26 通过。最终 `py_compile` 和 diff 检查见本次回复。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、远程漫剧 `server.py`、数据库、OpenAPI 或 `migration.sql`。按用户要求本次修改后不自动重启本地客户端，生效需要手动重启本地客户端；已在漫剧端创建过的污染分镜需要重建任务或重新分析/重建项目。

## 2026-07-28 小红书创作者登录页等待登录
- `backend/platform_adapters.py#L231-L253`：新增 `_wait_for_xhs_creator_login()`，遇到登录页后在当前可见浏览器里轮询 cookie、URL 和上传控件，默认等待 180 秒，登录后自动回到发布页继续。
- `backend/platform_adapters.py#L1772-L1778`：`xhs_publish_material()` 不再在登录页出现时立刻返回，而是调用等待函数；只有超时未登录时才回落到 `xhs_creator_login_required`。
- `tests/test_native_publish.py#L154-L168`：回归覆盖等待登录逻辑和等待超时配置，防止以后再次恢复成“打开即关闭”。
- 验证：先运行新增测试观察旧实现失败 2 项；修复后 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v` 25/25 通过。`py_compile` 通过，只有既有的正则转义警告。
- 回滚：回滚 `backend/platform_adapters.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 即可；本次不涉及中心服、数据库、OpenAPI 或 `migration.sql`。

## 2026-07-28 同款替换漫剧分镜异步分析等待
- `backend/matrix_native_client.py#L8640-L8681`：新增漫剧分镜 ID、序号解析和 `_comic_assign_storyboard_ids()`，支持 `id/storyboard_id/storyboardId` 以及按 `sequence/index` 或片段顺序回填 `comicStoryboardId`。
- `backend/matrix_native_client.py#L8799-L8800`、`backend/matrix_native_client.py#L8870-L8889`：`ComicProjectAdapter` 新增项目详情读取和非媒体任务等待；分析任务只返回 `task_id` 时会轮询到 `completed/success/done/succeeded`，失败状态保留原始任务摘要。
- `backend/matrix_native_client.py#L10027-L10073`：同款替换漫剧主流程在片段生成前先读取项目分镜；仍缺失时提交 `/projects/{projectId}/analyze`，等待分析任务完成后再次拉取项目详情并回填分镜 ID；旧任务重试时也会恢复已有项目分镜，不再直接报 `comic_storyboard_id_missing:segment_1`。
- `tests/test_video_replacement.py#L400-L458`、`tests/test_video_replacement.py#L460-L536`：回归覆盖已有项目恢复缺失分镜 ID、新项目异步分析任务完成后再使用分镜 ID。
- 验证：先运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_existing_project_recovers_missing_storyboard_ids -v` 观察旧实现失败；修复后该测试通过，并补充异步分析测试。最终 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement -v` 24/24 通过、`.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement.py` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、远程漫剧 `server.py`、数据库、OpenAPI 或 `migration.sql`。按用户要求本次修改后不自动重启本地客户端，生效需要手动重启本地客户端。

## 2026-07-28 小红书发布可见浏览器与登录态提示
- `backend/platform_adapters.py#L67-L80`：`_browser_kwargs()` 新增 `default_headless` 参数，保留其它小红书任务的默认后台模式，同时允许发布流程单独默认显示浏览器。
- `backend/platform_adapters.py#L226-L229`：新增 `_is_xhs_creator_login_url()`，识别 `creator.xiaohongshu.com/login` 和 `redirectReason=401`，用于区分“未登录创作者中心”和“上传控件不存在”。
- `backend/platform_adapters.py#L1726-L1745`：`xhs_publish_material()` 调用发布浏览器时使用 `default_headless=False`；打开创作者发布页后先检测登录跳转，命中时返回 `xhs_creator_login_required` 和 `final_url`，再进入上传控件检查。
- `backend/matrix_native_client.py#L10956-L10974`：`_publish_result_message()` 把 `xhs_creator_login_required` 映射成“小红书创作者中心未登录，请在打开的浏览器中登录后重试。”，避免继续展示内部错误码。
- `tests/test_native_publish.py#L128-L152`：回归覆盖小红书创作者中心登录提示、发布浏览器默认可见、登录跳转必须早于上传控件检查。
- 验证：先运行新增测试观察旧实现失败 3 项；修复后 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v` 23/23 通过。最终编译验证见本次回复。
- 回滚：回滚 `backend/platform_adapters.py`、`backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可；本次不涉及 OpenAPI、中心服、数据库迁移或 `migration.sql`。
## 2026-07-28 同款替换漫剧项目库资产创建
- `backend/matrix_native_client.py#L8802-L8828`：`ComicProjectAdapter.upsert_manual_assets()` 改为对 `/api/v1/comic-drama/projects/{projectId}/{characters|scenes|props}` 执行 `POST` 创建项目库资产，补齐 `reference_image` 和 `reference_images` 字段，并保存漫剧后端返回的真实 `id/asset_id`。旧实现直接 `PUT /.../{matrix-character-1}`，漫剧端会把该 ID 当作已存在资产更新，导致 `comic_api_http_404: 本地资产不存在`。
- `tests/test_video_replacement.py#L250-L292`：回归测试锁定人物、场景、道具均通过集合 `POST` 创建，且返回 ID 会写回 `comicAssets`，避免后续分镜绑定继续引用本地临时 ID。
- 验证：先运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_adapter_upserts_manual_assets -v` 观察旧实现失败；修复后该测试通过，并补跑 `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement -v` 24/24 通过、`.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement.py` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、远程漫剧 `server.py`、数据库、OpenAPI 或 `migration.sql`。按用户要求本次修改后不自动重启本地客户端，生效需要手动重启本地客户端。

## 2026-07-27 企业中心横幅视频稳定显示
- `backend/matrix_native_client.py#L2830-L2846`：新增企业中心横幅资源解析，候选路径按 `data_dir()/hero.mp4`、`backend/datas/hero.mp4`、内置 `assets/login_bg/car-shouye.mp4` 顺序查找，并固定 `HERO_POSTER` 为 `assets/login_bg/car-shouye.png`，避免不同启动方式或数据目录切换时只看到紫色渐变底。
- `backend/matrix_native_client.py#L2849-L3035`：`VideoHero` 初始化时先加载固定海报图，视频可用时再覆盖播放；视频缺失、组件不可用、播放错误和媒体状态变化均写入结构化日志事件 `enterprise_hero_video_*`，页面不再因为 Qt 多媒体失败而空白。
- `tests/test_agent_mode_defaults.py#L198-L230`：新增并更新回归测试，锁定企业中心横幅不再依赖单一路径，同时保留“无重新生成按钮”的固定视频行为。
- 验证：先运行新增目标测试确认旧实现失败，再实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults -v`，19/19 通过；运行 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_agent_mode_defaults.py` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md`、`CHANGELOG.md` 即可恢复旧行为；本次不涉及中心服、OpenAPI、数据库迁移或 `migration.sql`。
## 2026-07-27 素材发布小红书按钮与失败诊断

- `backend/matrix_native_client.py#L4253-L4254`、`backend/matrix_native_client.py#L5168-L5197`、`backend/matrix_native_client.py#L5373-L5374`：素材发布页抽出 `_publish_platform_label()`，平台下拉切换时同步更新按钮文案；选择小红书时按钮显示“发布到小红书”，未选账号提示也使用当前平台名称。
- `backend/matrix_native_client.py#L10933-L10949`：发布结果文案优先显示本地发布器返回的真实错误；当中心任务外层只有兜底 `task_failed`、内层有明确错误时，不再把 `task_failed` 展示给用户。
- `backend/platform_adapters.py#L1765-L1768`、`backend/platform_adapters.py#L1790-L1804`：小红书发布器把“发布笔记”纳入精确按钮候选，不再排除该文案；未找到按钮后的坐标兜底改为按当前视口计算，并在未确认成功时返回 `publish_unconfirmed`。
- `backend/api_server.py#L5603-L5604`：本地 `/api/publish/run` 响应透传 `platform` 和小红书按钮诊断 `button`，方便排查是否没找到按钮、坐标兜底失败或点击后未确认。
- `tests/test_native_publish.py#L107-L144`、`tests/test_native_publish.py#L269-L276`：TDD 覆盖按钮文案随平台切换、优先显示内层平台错误、小红书发布器识别“发布笔记”、未确认发布返回 `publish_unconfirmed`、本地接口透传按钮诊断。
- 验证：先运行新增用例复现旧实现失败；修复后 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v` 20/20 通过。完整相关回归和编译检查见本次回复。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/platform_adapters.py`、`backend/api_server.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可；不涉及数据库迁移。代码生效需要重启本地客户端和本地执行引擎。

## 2026-07-27 企业邀请免手机号邮箱与账户中心手机号隐藏

- `backend/central_server.py#L7476-L7547`、`backend/central_server.py#L7550-L7630`、`backend/central_server.py#L14297-L14584`、`backend/central_server.py#L15490-L15498`：企业邀请创建继续兼容历史 `recipientPhone/recipientEmail` 字段，但接受邀请码时移除“手机号或邮箱必填”校验；新用户可仅凭邀请码、姓名和 8 位以上密码加入邀请码绑定的企业，成员关系仍写入 `orgId/userId/role`。
- `backend/matrix_native_client.py#L3402-L3457`：团队成员页“邀请成员”弹窗改为先选择企业、再选择角色和有效期；手机号、邮箱字段和旧校验删除，平台管理员可切换目标企业，企业管理员固定当前企业。
- `backend/matrix_native_client.py#L19935-L20021`：账户中心手机号绑定面板抽为 `phone_bind_panel`，初始化和 `on_show()` 均只在 `product_role()=="platform_admin"` 时显示；企业管理员和普通用户仍可看余额/流水，但不再看到手机号绑定入口。
- `backend/matrix_native_client.py#L21216-L21428`：登录页“加入企业”模式隐藏并清空手机号和邮箱输入；校验邀请码后只显示企业、角色、有效期和姓名；接受请求体只提交 `token/name/password/currentPassword`，不再提交 `phone/email`。
- `tests/test_enterprise_invites.py#L68-L107`、`tests/test_native_enterprise_invite.py#L42-L148`、`tests/test_native_enterprise_invite.py#L350-L352`、`tests/test_role_permissions.py#L123-L132`：TDD 覆盖无手机号邮箱接受邀请码、本地邀请码 UI 隐藏手机号邮箱、提交体不带 `phone/email`、账户中心手机号面板仅平台管理员可见。
- 文档契约：`docs/API_REFERENCE.md#L79-L116` 增加企业邀请三接口说明；`docs/openapi.yaml#L627-L688` 增加 `/api/enterprise/invites/create|verify|accept` 路径，`docs/openapi.yaml#L960-L1035` 增加 `EnterpriseInvite*` schema，明确接受邀请码只必填 `token/name/password` 并返回 `EnterpriseInviteAcceptResponse`；`tests/test_openapi_contract.py#L10-L57` 锁定该契约。
- 验证：先运行目标测试观察旧实现失败 5 项，再实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_enterprise_invites tests.test_native_enterprise_invite tests.test_role_permissions -v`，28/28 通过；本次补跑 `.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v`，2/2 通过。最终 `py_compile` 和 OpenAPI 合法性验证见本次回复。
- 回滚：回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_enterprise_invites.py`、`tests/test_native_enterprise_invite.py`、`tests/test_role_permissions.py`、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 即可恢复旧的手机号/邮箱邀请和账户中心手机号显示行为；本次不涉及数据库迁移，`migration.sql` 保持 no-op。

## 2026-07-27 内容采集收藏数与图文同款草稿入库

- `backend/platform_adapters.py#L404-L481`、`backend/platform_adapters.py#L518-L660`：新增小红书搜索响应元数据解析，把 `/search/notes` 返回里的作者、点赞数和收藏数按 `note_id` 回填到采集结果；兼容 `collect/favorite/bookmark/saved` 等别名。
- `backend/matrix_native_client.py#L4117-L4166`、`backend/matrix_native_client.py#L4494-L4494`：内容采集表格统一展示“作者 / 点赞数 / 收藏数”，原“转发数”列改为“收藏数”；小红书和抖音结果都会优先读取收藏字段，缺失时显示 `-`。
- `backend/matrix_native_client.py#L8069-L8080`：图文同款的“标题（必填）”不再自动使用原始标题，进入页面后保持空白，要求用户手动输入；“卖点（可编辑）”仍可从原笔记正文辅助生成。
- `backend/matrix_native_client.py#L980-L1016`、`backend/matrix_native_client.py#L4388-L4469`、`backend/matrix_native_client.py#L8187-L8225`：本地保存图文同款草稿成功后，把保存后的图片文件和 `sourceTitle/sourceBody/sourceTags/replacementJobId` 等追溯字段同步上传到中心素材库；同步失败时保留本机草稿并提示“同步到『素材发布』失败”，同时写结构化日志 `xhs_note_draft_central_sync_failed`。
- `backend/api_server.py#L739-L768`、`backend/api_server.py#L903-L941`、`backend/api_server.py#L4751-L4751`：本地素材上传和中心素材下发保留图文草稿元数据，避免从中心素材库进入发布流程后标题、正文、标签、来源任务丢失。
- `backend/central_server.py#L1361-L1390`、`backend/central_server.py#L1529-L1569`、`backend/central_server.py#L13665-L13665`：中心素材上传白名单接收图文同款元数据，素材发布 payload 继续携带 `platform/body/tags/sourceTitle/sourceBody/sourceTags/importedFromXhsNoteReplacement`。
- `backend/local_browser_worker.py#L221-L267`：本地执行引擎从中心素材同步到本地时继续转发图文草稿元数据，保证“素材发布”真实发布前还能追溯来源。
- `tests/test_video_replacement_v2.py#L310-L317`、`tests/test_xhs_lead_filtering.py#L83-L101`、`tests/test_xhs_note_replacement.py#L277-L318`、`tests/test_xhs_note_replacement.py#L1003-L1063`：回归覆盖表头“收藏数”、小红书搜索元数据回填、素材库元数据白名单和保存草稿后同步中心素材库。
- 验证：本阶段目标用例与相关回归使用 `.venv-win\Scripts\python.exe -m unittest ... -v` 通过，最终完整命令见本次回复；`py_compile` 覆盖客户端、中心服、本地 API、执行引擎、平台适配器和相关测试文件。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/platform_adapters.py`、`backend/api_server.py`、`backend/central_server.py`、`backend/local_browser_worker.py`、相关测试和本条文档即可恢复旧行为；不涉及数据库迁移，`migration.sql` 仍为 no-op。若需临时规避图文草稿能力，可设置 `XHS_NOTE_REPLACEMENT_ENABLED=0` 并重启本地服务。

## 2026-07-27 素材发布来源过滤

- `backend/matrix_native_client.py#L5147-L5160`：新增素材发布列表来源过滤，隐藏 `importedFromDownload`、`sourceDownloadPath/sourceDownloadKey` 等内容采集下载素材，以及 `source=混剪短视频/mix` 或 `prompt` 以“混剪 ”开头的混剪素材；不删除历史文件。
- `backend/matrix_native_client.py#L5318-L5322`：素材发布页加载 `/api/library` 后先应用来源过滤，再渲染“素材库与发布”表格；用户手动上传、商品图/视频生成成品、图文同款 `image_note` 草稿和待发布队列不受影响。
- `tests/test_native_publish.py#L150-L180`：回归覆盖手动上传与图文同款草稿继续显示，内容采集下载与混剪来源隐藏，并锁定加载列表时必须调用过滤函数。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_xhs_note_replacement -v` 通过 64 项；未修改接口契约、数据库结构、OpenAPI 或 `migration.sql`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md` 和本条实现索引即可恢复旧列表展示；历史素材文件未被删除。

## 2026-07-27 同款替换漫剧项目模式

- `backend/central_server.py#L94-L98`、`backend/central_server.py#L2414-L2488`、`backend/central_server.py#L14312-L14362`：中心服漫剧 SSO 增加固定账号策略，默认把所有同款替换漫剧项目 ticket 签给 AI CanvasPro 账号 `003` / `user_id=44`，不再要求当前 Matrix 用户映射到漫剧主库用户；ticket 响应、结构化日志和审计记录保留 `matrixUserId`、`comicUserId`、`comicUsername` 和 `comicAccountMode`。
- `tests/test_comic_sso.py#L109-L150`：回归覆盖普通本地 Matrix 用户也能签出固定漫剧账号 ticket，并验证 ticket claim 中的 `user_id=44`、`name=003`。
- `backend/matrix_native_client.py#L8299-L8650`：`VIDEO_REPLACE_DEFAULT_MODE` 默认值切到 `comic_project`，补齐漫剧项目模式的 base URL、口播台词来源、项目创建 payload、手动资产映射和 `ComicProjectAdapter`。
- `backend/matrix_native_client.py#L8980-L9121`：新任务面板在漫剧项目模式下改写状态文案，明确提示使用上传人物/场景/道具作为角色参考。
- `backend/matrix_native_client.py#L9286-L9848`：生成入口按 `replacementMode` 分流，漫剧项目模式会创建项目、分析分镜、写入人物/场景/道具、逐片更新分镜、准备配音、生成首尾帧、生成视频、下载结果，并在失败时写入 `partial` 和 `errorId`。
- `backend/matrix_native_client.py#L10136-L10324`：历史实现曾使用“流程图生成”单列；2026-07-29 起由上方双帧表格实现取代，旧记录仅用于追溯。
- `tests/test_video_replacement.py#L186-L390`：覆盖漫剧项目 payload、票据交换、手动资产写入、道具映射、首尾帧视频 payload、默认模式和 `partial` 失败回归。
- `tests/test_video_replacement_v2.py#L3735-L3838`：覆盖漫剧模式下 `tts/uploaded` 音频准备、上传完整配音裁切和历史已有视频口型同步兼容逻辑。
- 验证：沿用既有同款替换回归，`tests.test_video_replacement` 和 `tests.test_video_replacement_v2` 已覆盖漫剧项目链路、音频门禁和单片失败状态；`uploaded` 音频在漫剧项目模式下仍被前置阻断，属于当前设计限制，不是回归。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`tests/test_video_replacement_v2.py`、`docs/ARCHITECTURE.md`、`docs/API_REFERENCE.md`、`docs/DEPLOYMENT.md`、`docs/TROUBLESHOOTING.md`、`CHANGELOG.md` 和本条实现索引即可；不涉及数据库迁移。

## 2026-07-27 小红书获客采集数据过滤

- `backend/platform_adapters.py#L688-L847`：严格过滤开关、评论尾部清洗、主页规范化、浏览器 `rawText` 文本/点赞解析、校验和采集异常脱敏 helper。浏览器正文同行尾部元数据与完整组合元数据行（如 `赞 8 回复`）会清洗，点赞解析在进入嵌套回复前停止。稳定过滤原因码为 `missing_profile_url`、`invalid_profile_url`、`empty_user`、`user_equals_comment`；有有效主页时 `.` 和纯 emoji 用户名保留。
- `backend/platform_adapters.py#L848-L1124`：意向/点赞优先级、SHA-256 截断指纹、逐条脱敏 JSON 日志、搜索失败日志、主页级归并、结果上限和采样重复汇总。事件为 `xhs_collected_record_filtered`、`xhs_collected_record_deduplicated`、`xhs_collected_record_parse_failed`、`xhs_collection_filter_summary`、`xhs_collection_search_failed`；汇总包含 `scope`、`candidateLimit`、`candidateLimitReached`、`candidateDuplicateCount`。异常使用固定脱敏消息的新堆栈，日志不含用户名、评论、完整主页、query token 或异常原文。
- `backend/platform_adapters.py#L1127-L1235`：`xhs_get_comments()` 移除普通容器 `div` 候选，原始候选固定上限为 900，在单笔记内按主页归并并由过滤器执行 `result_limit`；页面导航失败记录 `xhs_collection_page_navigation_failed`。`backend/platform_adapters.py#L1237-L1320`：`discover_xhs_leads_by_keyword()` 在跨笔记汇总后再次按主页归并，单笔记失败记录 `xhs_note_collection_failed`；搜索阶段命中小红书安全限制时返回 `ok=false`、`xhs_ip_risk`、`riskCode=300012` 和关联 `errorId`，不再显示为正常 0 条。
- `backend/matrix_native_client.py#L839-L851`、`backend/matrix_native_client.py#L4008-L4081`：原生获客页把 `xhs_ip_risk` 展示为“小红书安全限制：当前网络/IP存在风险，请切换可靠网络环境后重试(300012)”，避免用户误判为没有抓取。
- `tests/test_xhs_lead_filtering.py#L11-L183`、`tests/test_xhs_lead_filtering.py#L184-L583`、`tests/test_xhs_lead_filtering.py#L584-L704`、`tests/test_agent_mode_defaults.py#L87-L98`：覆盖清洗边界、组合元数据、浏览器同行元数据、嵌套回复点赞隔离、过滤规则、日志/响应脱敏、回滚开关、300 条上限、900 条候选状态、采样重复计数、搜索风控失败传播、前端风控提示、50ms 硬门禁、5MB 内存门禁、DOM 契约及跨笔记去重。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_xhs_lead_filtering tests.test_agent_mode_defaults tests.test_structured_log tests.test_openapi_contract tests.test_douyin_multi_account -v` 实际 79/79 通过；`py_compile` 和 `git diff --check` 退出成功。抖音依赖读取仍输出 3 条既有 `ResourceWarning`，Python 编译仍保留 1 条既有小红书发布 evaluator `SyntaxWarning`。假数据冒烟准确返回 2 条有效主页记录；`xhs_profile_ready('backend/datas')` 输出 `ready=false`，因此未请求真实小红书页面。
- 回滚：设置 `XHS_STRICT_LEAD_FILTER_ENABLED=0` 并重启本地执行引擎可紧急降级过滤规则；若要回滚本次风控错误提示，恢复 `backend/platform_adapters.py`、`backend/matrix_native_client.py`、`tests/test_xhs_lead_filtering.py`、`tests/test_agent_mode_defaults.py`、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/TROUBLESHOOTING.md`、`CHANGELOG.md` 和本条实现索引即可。本次不涉及数据库或 `migration.sql`。

## 2026-07-27 小红书图文同款采集元数据与图片框流程
- `backend/platform_adapters.py#L1273-L1349`：小红书下载媒体过滤新增 `/comment/`、`/comments/` 评论区图片排除，继续过滤页面静态资源、小图标和过小图片，只保留用户发布的正文媒体候选。
- `backend/platform_adapters.py#L1350-L1421`：新增标题/正文/标签规范化；正文中的话题标签会从正文移出并并入 `tags`，`meta.json` 同步写入 `note`、`title`、`body`、`tags` 和 `savePath`。
- `backend/platform_adapters.py#L1422-L1544`：`xhs_download_note()` 浏览器脚本同时采集正文图片、原始标题、正文和标签；下载完成后用规范化元数据生成返回 payload 和 `meta.json`。
- `backend/api_server.py#L1683-L1912`：下载入库保存 `body`、`tags`、`noteId`、`sourceDownloadPath`，并在命中已有有效素材时补齐缺失元数据，避免标题继续回退为链接或下载目录名。
- `backend/api_server.py#L739-L764`、`backend/api_server.py#L4941-L5000`：`/api/xhs-note-replacement/save-draft` 保存前校验所有槽位都有真实可读图片；缺图返回 HTTP 400、`xhs_note_replacement_missing_images`。保存时按槽位生成唯一文件名，使用模块级 `shutil`，`copy2` 元数据复制失败时降级为普通文件复制，不再因局部导入触发 `xhs_note_save_failed`。
- `backend/api_server.py#L5438-L5454`：`/api/xhs/download` 将下载返回里的 `note.title/body/tags` 或顶层 `title/body/tags` 合并后传给素材入库。
- `backend/xhs_note_replacement.py#L54-L88`：模板保留 `sourceDownloadPath`，供图文同款页展示“来源素材”的本地目录。
- `backend/xhs_note_replacement.py#L99-L163`：预览匹配替换图时优先按 `slotIndex`，再按 `slotRole/role`；一张原图对应一张替换图，避免多个同角色槽位复用同一图片。
- `backend/xhs_note_replacement.py#L168-L176`、`backend/xhs_note_replacement.py#L213-L238`：新增草稿保存前槽位检查，并在草稿素材里保留 `sourceTitle`、`sourceBody`、`sourceTags`。
- `backend/matrix_native_client.py#L4131-L4183`：内容采集下载结果转图文同款素材时保留本地下载目录、原始标题、正文、标签和签名图片 URL。
- `backend/matrix_native_client.py#L7504-L7645`：原生“图文同款”页改为单页表单；“来源素材”显示本地路径，字段改为“标题（必填）/所在地（必填）/目标客户（必填）/卖点（可编辑）”，删除可见的“读取图文结构”按钮、路径文本框、槽位调试表和“AI生成缺图”入口。
- `backend/matrix_native_client.py#L7846-L7927`：替换图改为图片框数组，支持点击单框选择、多选顺序填充、根据原正文预填卖点；缺图必须手动选择替换图片。
- `backend/matrix_native_client.py#L7971-L8059`：采集跳转会清空旧状态、自动读取结构；生成预览前检查必填字段和全部替换图；保存草稿带上用户选择的方案编号；文案区只展示当前选中的 3 方案之一。
- `tests/test_api_download_contract.py#L139-L212`：覆盖评论图过滤、正文/标签拆分和下载入库元数据传递。
- `tests/test_xhs_note_replacement.py#L84-L284`、`tests/test_xhs_note_replacement.py#L373-L927`：覆盖来源目录进入模板、空图保存阻断、复制元数据失败降级、下载交接保留原文、图片框样式、多选填充、移除 AI 缺图入口、预览校验和保存选中方案。
- 验证：新增回归测试先复现 `UnboundLocalError` 导致 HTTP 500、`xhs_note_save_failed`；修复后 `.venv-win\Scripts\python.exe -m unittest tests.test_api_download_contract tests.test_xhs_note_replacement -v` 通过 71 项；扩展回归 `.venv-win\Scripts\python.exe -m unittest tests.test_material_repair tests.test_native_publish tests.test_api_download_contract tests.test_xhs_note_replacement -v` 通过 106 项；`.venv-win\Scripts\python.exe -m py_compile backend\platform_adapters.py backend\xhs_note_replacement.py backend\api_server.py backend\matrix_native_client.py tests\test_api_download_contract.py tests\test_xhs_note_replacement.py` 退出码 0。
- 回滚：回滚 `backend/platform_adapters.py`、`backend/api_server.py`、`backend/xhs_note_replacement.py`、`backend/matrix_native_client.py`、`tests/test_api_download_contract.py`、`tests/test_xhs_note_replacement.py`、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/ARCHITECTURE.md`、`docs/TROUBLESHOOTING.md`、`CHANGELOG.md` 和本条实现索引；不涉及数据库迁移，`migration.sql` 保持 no-op。

## 2026-07-27 Web 交付面移除
- `tests/test_web_surface_removed.py#L8-L48`：锁定产品 Web 文件缺席、活动 HTML 缺席（扫描排除 `.worktrees`、`build`、`dist` 等构建/嵌套 worktree 产物）、中心服不再服务 `/admin` 或 `frontend/downloads` 安装包路径，同时保留 `/MatrixShipAgent-Setup.exe` 和 `MATRIXSHIP_AGENT_INSTALLER`。
- `backend/central_server.py#L13481-L13587`：安装包下载只保留环境变量、服务器固定路径和后端目录候选；`/admin` HTML 路由已移除，中心服继续提供 JSON API 与安装包下载。
- `backend/build_matrix_agent.ps1#L105-L120`、`backend/installer/MatrixShipAgent.iss#L21-L22`：Windows 原生客户端安装包输出到 `backend\dist\installer\MatrixShipAgent-Setup.exe`，不再复制到 Web 下载目录；打包脚本同时查找 Program Files 和 `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`，支持用户级 Inno Setup 安装。
- `backend/agent_launcher.py#L45-L79`、`backend/matrix_native_client.py#L8-L8`、`backend/matrix_native_client.py#L5459-L5459`：运行时提示和模块注释改为原生客户端/中心服/本地执行引擎表述，不再把产品入口描述成网页前端。
- 回滚：校验 `backups/web-removal-20260727/archive.sha256` 中的 `fbf0989fef5727f461d6424fa24eacea4385d73e078528266997af403b794097` 后，从 `web-surface.zip` 恢复被删除的 Web 文件；若新版本错误率超过 1%，回滚本阶段提交并恢复上一稳定安装包。

## 2026-07-27 原生客户端企业邀请码加入
- `backend/matrix_native_client.py#L3248-L3253`、`backend/matrix_native_client.py#L3386-L3430`：企业管理员创建邀请后只展示并复制一次性邀请码，文案引导受邀人在本地客户端选择“加入企业”，不再生成或展示 Web 链接。
- `backend/matrix_native_client.py#L19857-L19877`：新增 64 位十六进制邀请码标准化和脱敏错误映射；兼容粘贴历史邀请 URL，但只在本机解析查询参数，不向日志或审计输出邀请码。
- `backend/matrix_native_client.py#L19880-L20409`：登录卡新增“加入企业”第三模式、邀请码校验、受邀资料、8 位新密码和已有账号当前密码控件；900 像素宽度下隐藏宣传区，且进入邀请模式会清空记住的登录密码。接受请求期间会锁定邀请码、校验按钮、模式切换和账号字段。
- `backend/matrix_native_client.py#L22307-L22436`：邀请码校验与接受均使用 POST JSON，并以请求代次和提交邀请码双重拒绝陈旧响应；成功后复用 `set_session()`、`set_auth_context()` 和登录成功回调，把持久化认证偏好切换为新账号且不保存密码/Token，已有用户可在 `existing_user_login_required` 后原位补填当前密码。
- `tests/test_native_enterprise_invite.py#L23-L378`：覆盖邀请码/历史 URL 解析、脱敏错误、第三模式、900×700 布局、记忆密码隔离、跨模式及同模式陈旧响应、接受期间控件锁定、校验预填、已有用户重试、成功会话和认证偏好建立，以及 Web 邀请链接读取退役。
- 验证：`py_compile` 通过；原生邀请 12/12、邀请 API 4/4、登录/权限/协议/布局/成功过场 28/28 通过。Windows Qt 屏幕外渲染 `.tmp-validation/login-invite-1240x780.png` 与 `.tmp-validation/login-invite-900x700.png`，卡片均在视口内、无控件重叠、密码为空。
- 回滚：优先回滚本阶段提交；或校验 `backups/web-removal-20260727/archive.sha256` 后从隔离恢复目录取回修改前客户端文件。回滚会恢复网页邀请入口依赖，因此必须与后续 Web 删除提交一并回滚；本阶段不修改数据库 Schema。

## 2026-07-27 企业邀请码契约原生化
- `backend/central_server.py#L7282-L7389`：邀请对象只持久化令牌哈希；创建成功只在顶层返回一次 `inviteCode`，公开邀请对象、列表和校验响应剔除 `token`、`tokenHash`、`inviteCode`，不再生成网页加入链接。
- `backend/central_server.py#L7416-L7498`：接受邀请保留新用户创建账号和已有用户当前密码校验，成功响应补齐 `appRole`、`roleScope`、`memberships`、`organizations` 和会话信息，供原生客户端直接接入现有登录态。
- `backend/central_server.py#L14164-L14174`、`backend/central_server.py#L14398-L14401`、`backend/central_server.py#L15304-L15310`：邀请校验改为公开 POST JSON 请求；审计只记录邀请 ID、企业 ID、状态和错误码，接受与创建路由沿用脱敏审计元数据。
- `tests/test_enterprise_invites.py#L23-L136`：TDD 覆盖邀请码只返回一次且不进入状态/列表、未注册用户与已有用户接受、完整角色上下文，以及 GET 校验退役和 POST 审计不含邀请码。
- 回滚：先校验 `backups/web-removal-20260727/archive.sha256` 和 `manifest.sha256`，再从归档恢复本阶段文件；不得把明文邀请码写入日志、审计或持久化状态。本阶段不修改数据库 Schema。

## 2026-07-25 Agent.模式视频时长可选
- `backend/matrix_native_client.py#L1483`、`backend/matrix_native_client.py#L10894`：视频时长白名单固定为 5 秒和 10 秒；历史记录的非法或缺失时长自动回落到 5 秒，提交 LK888 时使用该值，不再写死 5 秒。
- `backend/matrix_native_client.py#L16928`：Agent.模式视频控制区新增时长按钮；图片模式置灰，视频模式可在 5 秒与 10 秒之间切换。生成记录与重新编辑会保存/恢复时长。
- `tests/test_agent_video_duration.py#L1`：回归测试覆盖可选时长控件、记录写入和 LK888 请求参数链路。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_video_duration.py`、`CHANGELOG.md` 和本条实现索引即可；不涉及数据库、中心服或接口契约变更。
## 2026-07-25 同款替换口播音频时间表约束
- `backend/matrix_native_client.py#L12246-L12351`：新增口播稿按标点/长度切分、按最终音频时长分配到 0.01 秒精度的 `dialogueTiming`，并生成“口播时间表”prompt 块；时间表只来自片段 `script`，不读取原视频字幕/OCR/转写。
- `backend/matrix_native_client.py#L12354-L12535`：主角整身替换和 hybrid 视频编辑 prompt 在最前面注入口播时间表，继续保留产品、场景、原片动作和字幕安全规则；`auto` 自动模式不注入新台词时间表，也不回填原片声音。
- `backend/matrix_native_client.py#L12609-L12651`、`backend/matrix_native_client.py#L13526-L13650`：`tts/uploaded` talking 片段改为先生成或裁切最终口播音频，探测真实时长后写入 `dialogueAudioDurationSec/dialogueTiming/dialogueTimingPrompt`，再提交 LK888 视频编辑；TTS 仍沿用 `VIDEO_REPLACE_TTS_MAX_SPEED` 的自动提速上限。
- `backend/matrix_native_client.py#L13883-L14020`：最终换音轨阶段优先复用前置准备好的 `ttsPath` 或 `uploadedAudioSegmentPath`，避免二次生成/二次裁切导致提示词时间表和最终音频不一致。
- `tests/test_video_replacement_v2.py#L1447-L1503`、`tests/test_video_replacement_v2.py#L3733-L3831`：新增/更新回归测试，覆盖 0.01 秒时间表、prompt 前置、TTS 和上传完整配音都先准备音频时间表再生成视频。
- 验证：新增测试先观察到旧实现缺少 `_replacement_build_dialogue_timing`、prompt 无时间表、链路未先准备音频；实现后新增 4 条测试通过，并补跑同款替换 prompt/音频/场景降级相关 15 条定向回归测试和 `py_compile`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。按用户要求本次修改后不自动重启本地客户端。
## 2026-07-25 同款替换片段镜头约束与用户口播稿字幕
- `backend/matrix_native_client.py#L11239-L11427`：新增原片字幕/口播清洗和当前片段镜头拆解 helper。按片段 `start/end` 解析“时间轴镜头拆解”表格，只保留画面、人物、产品、动作、道具、场景和节奏，过滤“字幕/信息”列、OCR、原片字幕和原片口播转写。
- `backend/matrix_native_client.py#L11644-L11728`：生成方案和关键帧 prompt 将“当前片段原片镜头约束”前置；不再把整段 report、OCR、原片 transcript 原样写入 LK888 prompt。历史保存的片段 prompt 也会在发送前清洗。
- `backend/matrix_native_client.py#L11960-L12140`：主角整身替换和 hybrid 视频编辑 prompt 继续把用户当前 `segment.script` 作为 `tts/uploaded` 的唯一台词来源；通用源视频实体/瑕疵重生文案不再要求保留原片台词，改为按声音来源处理。
- `tests/test_video_replacement_v2.py#L1996-L2050`：新增回归测试覆盖当前片段镜头约束前置、原视频字幕/OCR/转写过滤，以及主角 prompt 只保留用户口播稿作为台词来源。
- 验证：新增两条测试先失败后通过；同款替换 prompt、源实体、声音来源和场景降级共 11 条定向回归测试通过，`py_compile` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。按用户要求本次修改后不自动重启本地客户端。
## 2026-07-25 同款替换场景冲突 AI 降级
- `backend/matrix_native_client.py#L6678-L6732`：新增片段级 AI 场景降级状态 helper。只有上传了场景图、当前片段还未降级、QC 错误为 `scene_mismatch` 或 `principal_motion_mismatch`，且产品、Logo、主角替换检查没有失败时，才允许自动重试一次。
- `backend/matrix_native_client.py#L11780-L11879`、`backend/matrix_native_client.py#L11881-L11964`：主角整身替换和混合视频编辑请求在降级片段中不再把上传场景图放入参考图列表；prompt 写入“AI 生成场景”说明，同时继续保留上传产品图和产品外观、Logo、包装文字强约束。
- `backend/matrix_native_client.py#L13554-L13735`：视觉 QC 在降级片段中跳过上传场景参考图一致性检查，但产品、Logo、人物和主题漂移检查仍按原规则执行。
- `backend/matrix_native_client.py#L14118-L14127`、`backend/matrix_native_client.py#L14205-L14214`：非口播片段 QC 失败时优先判断是否可做 AI 场景降级，保存任务状态并回到同一片段远程生成链路重试。
- `tests/test_video_replacement_v2.py#L2216-L2274`：新增回归测试覆盖降级后不传场景图但保留产品图、视觉 QC 跳过场景检查，以及动作/场景冲突可触发一次降级重试。
- 验证：先运行新增 3 条测试观察旧实现失败；实现后新增测试和 4 条同款替换回归测试通过，并运行 `py_compile` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。按用户要求本次修改后不自动重启本地客户端。
## 2026-07-25 同款替换取消已有视频口型同步模型依赖
- `backend/matrix_native_client.py`：`_run_hybrid_lipsynced_replacement_segment()` 保留函数名兼容旧调用，但执行链路改为“LK888 视频编辑 prompt 含口播稿 -> 本地替换音轨 -> QC”。`tts` 调用 `_replace_replacement_segment_audio_with_tts()`，`uploaded` 调用新增 `_replace_replacement_segment_audio_with_uploaded()` 按片段时间裁切上传完整配音并替换音轨。
- `VIDEO_REPLACE_LIPSYNC_MODEL` / `LK888_VIDEO_LIPSYNC_MODEL` 不再是同款替换 `tts/uploaded` 的必需配置；口型正确性由 LK888 视频编辑 prompt 中的口播稿约束承担，最终声音由本地音轨替换保证。
- `backend/matrix_native_client.py`：主角视频编辑 prompt 截断上限从 1800 放宽到 3200 字，以便保留更多原片镜头拆解和当前片段上下文。
- `tests/test_video_replacement_v2.py`：新增回归测试覆盖 `tts/uploaded` 不调用 `_run_replacement_video_lipsync()`，分别调用本地 TTS/上传配音片段音轨替换；保留上传配音裁切 URL helper 的兼容测试。
- 验证：新增两条测试先失败后通过；同款替换 prompt 和音频链路 8 条定向测试通过；`py_compile` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。按用户要求本次修改后不自动重启本地客户端。## 2026-07-25 同款替换口播稿提示词前置
- `backend/matrix_native_client.py`：`_run_hybrid_lipsynced_replacement_segment()` 在生成口型同步底片时使用 `audioMode=auto` 保留生成视频自带声音，并继续用 `promptAudioMode` 保存用户选择的 `tts/uploaded` 台词来源，避免底片 prompt 被误判为自动声音模式。
- `_build_principal_replacement_prompt()` 优先读取 `promptAudioMode/dialogueAudioMode`，并把口播稿台词规则放在已保存的长 `segment.prompt` 前面，确保提交给 LK888 的 1800 字 prompt 内包含用户修改后的口播稿。
- `tests/test_video_replacement_v2.py`：新增回归测试覆盖底片 source 音频时仍写入口播稿，以及长拆解 prompt 不会截断新台词。
- 验证：新增两条测试先失败后通过；同款替换 prompt/口型同步定向测试和 `py_compile` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md` 和 `docs/IMPLEMENTATION.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。按用户要求本次修改后不自动重启本地客户端。
## 2026-07-25 同款替换口播稿进入主角替换提示词
- `backend/matrix_native_client.py`：`_build_principal_replacement_prompt()` 改为按 `audioMode` 生成台词规则。`auto` 自动模式保留生成视频自带声音，不再回填原片原音；`tts` AI 音色配音模式把片段 `script` 写入 LK888 prompt，要求台词以用户修改后的口播稿为准；`uploaded` 上传完整配音模式把片段 `script` 写入 prompt，要求台词与上传配音和口播稿一致。
- 口型同步链路不变：`tts/uploaded` 仍先生成同款替换画面，再用“已有视频 + 音频”的口型同步模型处理口型，字幕继续由本地后期字幕层按口播稿烧录；本次只是让远程画面生成阶段也收到明确台词约束。
- `tests/test_video_replacement_v2.py`：新增回归测试，覆盖 `tts/uploaded` prompt 包含片段口播稿且不再写死“原音和台词”，以及 `source` 模式不会把用户改稿误传成新台词。
- 验证：先运行新增 3 条测试观察旧实现中 `tts/uploaded` 失败；实现后运行同款替换 prompt/口型同步 6 条定向测试通过，并运行 `py_compile`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md` 和 `docs/IMPLEMENTATION.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。按用户要求本次修改后不自动重启本地客户端。
## 2026-07-25 内容采集小红书离线提示平台误写
- `backend/matrix_native_client.py#L4100-L4123`：新增内容采集平台名称和搜索失败文案 helper，按任务类型、响应平台或当前下拉平台判断“抖音 / 小红书”，不再把所有 `local_browser_offline` 都写成“需先登录抖音账号”。
- `backend/matrix_native_client.py#L4271-L4272`：内容采集搜索失败状态统一调用 `_content_search_failure_text()`；小红书搜索离线时提示“本地客户端未在线或未绑定当前账号/企业，并确认小红书账号已登录”。
- `tests/test_video_replacement_v2.py#L310-L325`：新增小红书内容采集离线回归测试，先观察旧实现把小红书误提示为抖音，再验证修复后状态栏包含“小红书”且不包含“抖音账号”。
- 验证：`.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_xhs_content_search_offline_error_names_xhs_not_douyin -v` 通过；`.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement_v2.py` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-25 小红书下载过滤页面静态图
- `backend/platform_adapters.py#L1273-L1421`：新增小红书下载媒体过滤与结果契约 helper，过滤 `data:`、`blob:`、`fe-platform.xhscdn.com`、`picasso-static.xiaohongshu.com`、头像/图标/雪碧图等页面静态资源，并在没有有效正文媒体时返回 `ok=false/error=xhs_no_note_media/stage=download`。
- `backend/platform_adapters.py#L1422-L1544`：`xhs_download_note()` 改为只从笔记详情主体候选容器收集图片和视频，带上 DOM 尺寸后再进入过滤器，避免把搜索图标、导航资源、广告位和 base64 内嵌图保存成素材文件。
- `tests/test_api_download_contract.py#L95-L168`：新增小红书下载过滤契约测试，覆盖页面静态资源被过滤、过滤后没有作品媒体时不再假成功。
- 验证：先运行新增两条测试观察旧实现因缺少 `_xhs_filter_note_media` 和 `_xhs_download_meta` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_api_download_contract -v` 通过 20 条用例。
- 回滚：回滚 `backend/platform_adapters.py`、`tests/test_api_download_contract.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-25 数字人口播本地中文字幕后处理
- `backend/matrix_native_client.py#L5671-L5695`：`lk888_digital_human()` 在提交给 LK888/可灵数字人模型的 prompt 中追加“不要在画面中生成任何字幕、文字、标题、贴纸文字或水印；字幕由后期单独添加”，降低上游模型把中文画进画面导致乱码假字的概率。
- `backend/matrix_native_client.py#L5698-L5752`：`generate_digital_human()` 下载远程数字人视频后新增本地中文字幕后处理，完成事件返回最终 `path`、`subtitleStatus` 和 `subtitlePath`；字幕烧录失败时 helper 返回原视频路径，不触发扣费退款或整单失败。
- `backend/matrix_native_client.py#L14821-L14950`：新增数字人口播字幕 helper，默认由 `DIGITAL_HUMAN_BURN_SUBTITLES=1` 开启，按口播文案切分 ASS 事件，优先使用真实视频时长铺排字幕，并复用 ffmpeg `subtitles` 滤镜、微软雅黑字体目录和结构化日志 `digital_human_subtitle_burn_failed`。
- `tests/test_video_replacement_v2.py#L841-L909`：新增回归测试，覆盖数字人口播 prompt 禁止模型画字幕、生成完成后调用本地字幕后处理并回传字幕版视频路径，以及 ASS 字幕文件按文案和视频时长生成。
- 验证：先运行新增测试观察旧实现失败；实现后运行 6 条数字人口播定向测试通过，并运行 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement_v2.py` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。临时规避可设置 `DIGITAL_HUMAN_BURN_SUBTITLES=0` 并重启本地客户端。
## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 同款替换主角职业装质检误判降级
- `backend/matrix_native_client.py#L6478-L6487`：新增 `_replacement_principal_visual_qc_blocks()`，只把 `principal_replacement_mismatch`、`principal_other_subjects_changed`、`principal_motion_mismatch` 继续作为主角模式硬阻断；`principal_appearance_mismatch` 在标准/快速模式下降级为人工审核提醒，高一致模式或严格视觉质检仍阻断。
- `backend/matrix_native_client.py#L13452-L13452`：主角视觉 QC 提示词补充职业装判定规则，明确白衬衫搭配深色职业马甲、西装外套、西装裤或职业半裙属于职业套装，不应误判为吊带裙。
- `backend/matrix_native_client.py#L13654-L13656`：主角视觉 QC 失败分支改用上述 helper 判断是否阻断；标准模式下仍记录 `qcWarnings`、审核帧和原因，页面可继续走人工审核。
- `tests/test_video_replacement_v2.py#L1616-L1650`、`tests/test_video_replacement_v2.py#L1724-L1775`：覆盖 QC 提示词包含职业马甲规则、标准模式外观误判降级为 `visual_qc_warning`、高一致模式仍阻断。
- 验证：先运行新增标准模式测试观察旧实现失败；实现后运行 3 条定向测试通过。随后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2 -v` 和 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement_v2.py`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。代码改动需要手动重启本地客户端后生效。
## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 云豆统一扣费收口
- `backend/central_server.py#L2936-L2971`：中心服能力价格表按 `1 云豆 = 1 元` 口径保存，云豆到主库算力不再除以 100，而是直接乘 `MAINDB_YUAN_TO_POWER`。
- `backend/central_server.py#L3097-L3126`：`charge_capability_user()` 通用能力扣费统一走中心服；旧云豆钱包直接扣云豆，主库钱包按 `1 云豆 = 1 元` 和 `MAINDB_YUAN_TO_POWER` 换算为算力后原子扣减。
- `backend/central_server.py#L14904-L14929`：`/api/billing/charge` 调用统一扣费，`/api/billing/refund` 对主库通用扣费按 `ref` 幂等退款；找不到可退流水时返回退款 0，避免凭空加款。
- `backend/matrix_native_client.py#L708-L711`：客户端扣费请求新增 `capability` 字段，继续保留 `amount/reason/ref` 兼容旧中心服。
- `tests/test_billing_unified.py#L98-L165`、`tests/test_openapi_contract.py#L13-L36`：覆盖中心服价格优先、余额不足不写流水、主库算力换算、主库通用退款幂等，以及 OpenAPI 契约包含 `charge/refund`。
- `docs/openapi.yaml#L430-L459`、`docs/API_REFERENCE.md#L534-L536`：补充扣费和退款接口契约。
- 验证：运行 `python -m unittest tests.test_billing_unified -v` 通过；运行 `python -m unittest tests.test_billing_unified tests.test_openapi_contract -v` 通过；运行 `python -m py_compile backend/central_server.py backend/matrix_native_client.py tests/test_billing_unified.py tests/test_openapi_contract.py` 通过。
- 回滚：回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_billing_unified.py`、`tests/test_openapi_contract.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及数据库结构，`migration.sql` 仍为 no-op。回滚后主库模式下文案、混剪等通用扣费会恢复为放行不扣。
## 2026-07-29 云豆 1:1 人民币口径
- `backend/central_server.py#L74-L77`：新增 `YUNDOU_PER_YUAN=1.0` 和 `LEGACY_YUNDOU_PER_YUAN=100.0`，新用户默认赠豆从旧口径 100 调整为新口径 1。
- `backend/central_server.py#L955-L976`、`backend/central_server.py#L2936-L2971`：LK888 反代媒体生成和通用业务能力价格全部按旧云豆价 `/100` 保存，保持人民币价格不变。
- `backend/central_server.py#L2981-L3033`、`scripts/migrate_yundou_one_to_one.py#L1-L59`：新增一次性历史余额折算能力；脚本默认 dry-run，`--apply` 时先备份 `scheduler_state.json` 再写回。
- `backend/central_server.py#L3283-L3412`、`backend/central_server.py#L13951-L13964`：充值档位和下单到账改为 `1 元 = 1 云豆`；主库算力充值仍按 `MAINDB_YUAN_TO_POWER` 单独返回算力。
- `backend/matrix_native_client.py#L685-L689`、`backend/matrix_native_client.py#L21686-L21710`：本地客户端价格表、充值档位和充值弹窗说明同步新口径。
- `backend/legal/user_agreement.md#L24-L29`：用户协议计费条款改为 `1 云豆 = 1 元人民币`。
- 验证：先运行新增扣费/客户端规则测试观察旧规则失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_billing_unified tests.test_native_billing_rates tests.test_legal_agreements tests.test_openapi_contract -v`，并运行 `.venv-win\Scripts\python.exe -m py_compile backend\central_server.py backend\matrix_native_client.py scripts\migrate_yundou_one_to_one.py tests\test_billing_unified.py tests\test_native_billing_rates.py tests\test_legal_agreements.py`。
- 回滚：回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、`backend/legal/user_agreement.md`、`scripts/migrate_yundou_one_to_one.py`、`tests/test_billing_unified.py`、`tests/test_native_billing_rates.py`、`tests/test_legal_agreements.py`、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`；如已执行余额迁移，用脚本生成的 `.bak-yundou-1to1-*` 备份恢复状态文件。
## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 同款替换口型同步规则
- `backend/matrix_native_client.py#L6657-L6663`：`_replacement_segment_should_talk()` 改为按声音来源判定；`source` 原片声音不重建口型，`tts` 和 `uploaded` 只有在片段存在 `script` 口播稿时才标记为 `talking`。
- `backend/matrix_native_client.py#L7786-L7802`、`backend/matrix_native_client.py#L8454-L8464`：任务构建和片段表编辑同步时，按当前声音来源重新计算 `segmentType`，避免用户修改口播稿后仍被旧逻辑固定为 `non_talking`。
- `backend/matrix_native_client.py#L11873-L11911`：talking 片段不再调用 `lk888_digital_human()` 重生成整段视频；2026-07-25 起改为先把口播稿放入视频编辑 prompt 生成同款替换画面，再本地替换 TTS/上传配音音轨。
- `backend/matrix_native_client.py#L12866-L12886`：新增口型同步音频 URL helper。`tts` 模式按口播稿生成公网 TTS 音频，`uploaded` 模式复用上传完整配音的片段级裁切和上传结果。
- `backend/matrix_native_client.py#L12888-L12974`：保留历史已有视频口型同步 helper 供兼容；当前同款替换主链路不再依赖 `VIDEO_REPLACE_LIPSYNC_MODEL` 或 `LK888_VIDEO_LIPSYNC_MODEL`。
- `backend/matrix_native_client.py#L14040-L14058`：同款替换执行入口把 `tts/uploaded + script` 片段导向“同款视频编辑 prompt 含口播稿 -> 本地替换 TTS/上传配音音轨 -> QC”，`source` 原片声音仍走原同款替换链路。
- `tests/test_video_replacement_v2.py#L3337-L3427`：覆盖 TTS/uploaded talking 片段先生成同款替换画面再本地替换音轨且不调用数字人/已有视频口型同步模型，并覆盖声音来源对 talking 判定的影响和上传完整配音按片段裁切。
- 验证：先运行上述目标测试观察旧实现失败，再实现后运行同样测试通过；运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2 -v` 通过 199 个用例；运行 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement_v2.py` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。回滚后 `tts/uploaded` 可能恢复“换完视频后只换声音导致口型不一致”或误走数字人口播的旧风险。
## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 同款替换 AI 配音自动提速
- `backend/matrix_native_client.py#L6681-L6715`：新增 `VIDEO_REPLACE_TTS_MAX_SPEED` 上限读取，默认 `1.45x` 且限制在 `1.0-2.0`；开始生成前的口播时长预检改为只阻断“预计时长超过片段时长 * 最大提速 + 0.25 秒”的文案，允许 8 秒片段内通过约 1.4 倍语速读完的口播继续生成。
- `backend/matrix_native_client.py#L12651-L12692`：新增 `_audio_atempo_filter()` 和 `_speed_up_audio()`，用 ffmpeg `atempo` 对真实 TTS 音频做加速处理，输出 `replacement_tts_XX.fit.mp3` 后再进入音轨回填。
- `backend/matrix_native_client.py#L12739-L12799`：`_replace_replacement_segment_audio_with_tts()` 在下载 TTS 后探测真实音频时长；如果音频长于片段且所需语速不超过上限，则记录 `ttsOriginalDurationSec/ttsRequiredSpeed/ttsMaxSpeed/ttsSpeed/ttsTimingStatus=sped_up` 并用加速音频合成；如果超过上限，则记录 `ttsTimingStatus=too_long` 和可读错误后抛出 `replacement_tts_audio_too_long`。
- `tests/test_video_replacement_v2.py#L361-L417`、`tests/test_video_replacement_v2.py#L4278-L4295`：覆盖预计超长阻断、真实音频自动提速、超过提速上限时不进入合成，以及页面开始生成前的阻断路径。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_tts_duration_preflight_flags_segment_script_that_will_be_cut tests.test_video_replacement_v2.VideoReplacementV2Test.test_tts_audio_mode_speeds_up_real_audio_to_fit_segment_before_mux tests.test_video_replacement_v2.VideoReplacementV2Test.test_tts_audio_mode_rejects_real_audio_beyond_speed_limit_before_mux tests.test_video_replacement_v2.VideoReplacementV2Test.test_start_generation_blocks_tts_script_that_exceeds_segment_duration -v` 通过；运行 `.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2 -v` 通过；运行 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement_v2.py` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。临时调低或关闭自动提速可把 `VIDEO_REPLACE_TTS_MAX_SPEED` 设为 `1.0` 后重启本地客户端。
## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 丰田汽车企业创建入口与成员归属修正
- `backend/matrix_native_client.py#L3042-L3332`：团队成员页新增管理员专用“添加企业”按钮；按钮只在 `platform_admin` 下显示，提交后调用中心服已有 `/api/enterprise/orgs/upsert`，创建成功后刷新并选中新企业。企业家和普通用户不显示该入口，后端仍负责最终权限校验。
- `backend/central_server.py#L6868-L6939`、`backend/central_server.py#L15297-L15302`：新增平台管理员专用 `/api/enterprise/memberships/replace`，用于在运行中的中心服内把指定用户独占移动到指定企业并持久化，避免只改磁盘文件后被旧内存状态覆盖。
- `scripts/seed_toyota_enterprise.py#L1-L158`：新增一次性丰田汽车企业初始化脚本，写入 `org-toyota / 丰田汽车`，把 `boss` 设为该企业 `admin`，把 `user01`、`user02` 设为该企业 `member`，并保留 `19711057505 / user-owner` 在默认企业。脚本正式写入前会备份 `backend/central_data/scheduler_state.json`，且重复执行为幂等。
- `backend/central_data/scheduler_state.json`：已执行运行态数据修正；生成备份 `backend/central_data/scheduler_state.json.bak-20260724150901`。本次不迁移账号矩阵中已授权登录的抖音/小红书账号。
- `tests/test_role_permissions.py#L146-L216`：新增客户端创建企业入口契约测试、丰田汽车归属脚本测试和中心服运行态成员替换测试，覆盖 boss/user01/user02 迁入丰田汽车、19711057505 保留默认企业、脚本重复执行不再改数据。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_role_permissions` 通过；运行 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py backend\central_server.py scripts\seed_toyota_enterprise.py` 通过；运行 `.venv-win\Scripts\python.exe scripts\seed_toyota_enterprise.py --dry-run` 返回 `changed=false`；运行态接口返回 `replaceOk=true`，抽查中心数据确认 `丰田汽车` 已存在且三名目标用户归属正确。
- 回滚：如需回滚数据，停止中心服和本地客户端后，用 `backend/central_data/scheduler_state.json.bak-20260724150901` 覆盖 `backend/central_data/scheduler_state.json`；代码回滚范围为 `backend/matrix_native_client.py`、`backend/central_server.py`、`scripts/seed_toyota_enterprise.py`、`tests/test_role_permissions.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`。不涉及数据库结构、OpenAPI、充值/兑换码或 `migration.sql`。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 本地客户端普通按钮点击位移修复
- `backend/matrix_native_client.py#L2245-L2248`：全局点击动画 `_scale()` 对所有 `QPushButton` 直接返回，不再用 `QPropertyAnimation(..., b"geometry")` 修改按钮位置和尺寸。根因是普通按钮由 Qt layout 管理，点击后改文字或启停状态会触发布局重排，和手动 geometry 动画叠加后表现为按钮上移。
- `backend/matrix_native_client.py#L7117-L7144`：同款替换页底部操作按钮属于普通 `QPushButton`，包括“生成替换方案 / 执行替换生成 / 确认片段并合成 / 重试失败片段 / 重生选中片段 / 加入待发布队列”，现在统一受全局跳过规则保护。
- `tests/test_agent_mode_defaults.py#L187-L196`：新增源码契约测试，确认 `QPushButton` 的跳过判断发生在任何 `obj.geometry()` 读取之前，防止后续改动重新引入点击位移。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。回滚后普通布局按钮可能再次点击上移。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 企业中心团队成员管理
- `backend/matrix_native_client.py#L636-L640`：普通用户继续隐藏“企业中心”，并把“团队成员”作为企业中心内部别名纳入普通用户禁用列表，避免通过导航别名进入管理页。
- `backend/matrix_native_client.py#L663-L665`：新增 `current_org()`，团队成员页在管理员未切换企业或企业家固定企业时复用当前登录企业 ID。
- `backend/matrix_native_client.py#L3474-L3904`：`EnterpriseMembersPage` 在企业中心内展示成员表；管理员可切换企业，并可添加企业、添加成员、创建邀请、重置密码、停用/恢复成员；企业家固定当前企业，页头只保留“刷新”和“邀请成员”，不显示“添加企业”和“添加成员”。
- `backend/matrix_native_client.py#L3494-L3494`、`backend/matrix_native_client.py#L3767-L3770`：直接添加成员入口只允许平台管理员可见和执行；企业家需要通过“邀请成员”把用户加入自己企业。
- `backend/matrix_native_client.py#L22447-L22453`：`EnterpriseCenterPage` 把原“企业中心”入口组织成“总览 / 团队成员”两个标签页，左侧菜单仍只保留一个企业中心入口。
- `tests/test_role_permissions.py#L134-L165`：客户端源码契约测试锁定企业中心团队成员入口、普通用户隐藏规则、成员管理接口路径，以及企业家隐藏“添加企业/添加成员”但保留“刷新/邀请成员”的页头权限。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_role_permissions` 通过；运行 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py backend\central_server.py` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及数据库结构、账号矩阵授权账号迁移、充值/兑换码逻辑或 `migration.sql`。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 企业中心按钮重叠修复
- `backend/matrix_native_client.py#L5524-L5525`：团队成员表格“操作”列保持固定宽度，并收窄到 146px，避免 `style_table()` 的全列拉伸在窄窗口下挤压操作按钮。
- `backend/matrix_native_client.py#L5631-L5648`：行内“重置密码”和“停用/恢复”按钮改用专属 `teamAction` 紧凑样式，宽度分别为 72px 和 48px，覆盖全局 `ghost` 按钮最小宽度，保证每一行点击区域稳定且不重叠。
- `backend/matrix_native_client.py#L31086-L31123`：侧边栏底部保持上下两行；上行显示头像和账号名，下行显示余额、主题切换和退出按钮，避免用户信息、余额和图标按钮在 220px 侧边栏内重叠。
- `tests/test_role_permissions.py#L259-L277`：布局契约测试锁定操作列固定宽度、`teamAction` 紧凑按钮宽度和侧边栏底部上下两行结构。
- 验证：先运行 `.venv-win\Scripts\python.exe -m unittest tests.test_role_permissions.RolePermissionsTest.test_client_team_member_and_sidebar_controls_have_stable_widths -v` 观察旧实现因仍是 174px 操作列和 `ghost` 按钮而失败；修复后同命令通过，`.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_role_permissions.py` 通过；Qt 离屏几何检查生成 `.tmp-validation/team-members-actions.png`，按钮外框为 74px/50px，最右到 131px，小于 146px 操作列且不重叠。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI、充值/兑换码或 `migration.sql`。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 素材发布平台账号切换
- `backend/matrix_native_client.py#L4221-L4224`：素材发布页新增“发布平台”下拉框，支持在“抖音”和“小红书”之间切换。
- `backend/matrix_native_client.py#L4268-L4294`：点击发布时读取当前发布平台，并把 `platform` 与素材、账号、标题一起提交给本地任务。
- `backend/matrix_native_client.py#L4296-L4311`：账号下拉框统一由 `_refresh_publish_accounts()` 按当前平台和登录状态过滤，加载账号后不再重复清空和重填，避免平台切换结果被旧逻辑覆盖。
- `backend/api_server.py#L2735-L2746`、`backend/api_server.py#L5350-L5363`：`/api/publish/run` 接收并规范化 `platform`，`run_publish()` 按平台进入抖音或小红书发布链路。
- `tests/test_native_publish.py#L72-L102`：覆盖本地发布接口接受平台覆盖、发布页存在平台切换、加载账号后不再重复填充账号下拉框。
- 数据归属：当前已授权账号保持在 `org-default / user-owner`，不迁移到“丰田汽车”企业；企业数据归属仍由账号矩阵/中心服的 `orgId` 控制。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`tests/test_native_publish.py`、`CHANGELOG.md` 和本文档即可；不涉及数据库结构、账号迁移或 `migration.sql`。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 Agent.模式多图参考上传
- `backend/matrix_native_client.py#L9369-L9407`：新增 `_prodgen_entry_refs()` 和 `_prodgen_refs_desc()`，统一读取新 `refs` 列表并兼容旧 `ref` 字段；多图视觉描述按顺序说明“第1张为待修改图，第2张起为参考图”。
- `backend/matrix_native_client.py#L9489-L9555`：图片生成从单个 `ref` 改为有序 `refs`，调用 LK888 图片接口时把全部本地图转为 `image_urls`；视频模式和提示词优化复用多图视觉描述，保证“第一张改成第二张风格、人物换成第三张人物”这类中文指令有对应图片顺序。
- `backend/matrix_native_client.py#L14383-L14411`：生成记录卡片按顺序展示多张缩略图，标签为“待修改图 / 参考图1 / 参考图2...”，旧单图记录仍能显示。
- `backend/matrix_native_client.py#L14697-L15059`、`backend/matrix_native_client.py#L15094-L15286`：Agent.模式输入区新增最多 4 张图片状态，支持一次多选、分批追加、点击缩略图替换、右键删除；新任务写入 `refs` 并保留 `ref=第一张`，重新编辑、再次生成、资产库选图和共享库选图都走追加/恢复多图逻辑。
- `tests/test_agent_mode_defaults.py#L147-L174`：新增源码契约测试，覆盖多图 UI、一次多选、有序标签、新旧字段兼容和生成层按顺序传入所有图片。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。回滚后 Agent.模式将恢复只上传一张参考图。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 Agent.模式多行输入布局
- `backend/matrix_native_client.py#L14744-L14759`：Agent.模式 composer 内部改为上下结构，`ref_strip` 单独承载上传参考图槽，下面使用 `QPlainTextEdit` 多行提示词输入框，固定 78-138px 高度并按控件宽度自动换行，避免参考图和文本框同排挤压。
- `backend/matrix_native_client.py#L15061-L15194`：重新编辑改用 `setPlainText()` 回填提示词，发送、提示词优化和优化确认 fallback 均改为 `toPlainText().strip()`，确保多行中文提示词会按最新输入生成。
- `tests/test_agent_mode_defaults.py#L132-L145`：新增源码契约测试，锁定参考图条在输入框上方、多行控件、自动换行、读写多行文本和不再使用旧同排 `midrow.addWidget(self.ref_slot...)`。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。回滚后 Agent.模式会恢复参考图和单行输入框同排，长提示词仍可能被横向压缩。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 账号隔离根目录固定
- `backend/matrix_native_client.py#L405-L456`：新增 `_account_scope_root_dir()`，首次进入账号隔离时记录 `MATRIX_AGENT_ROOT_DATA_DIR`，后续 `apply_account_scope()` 始终基于该根目录写入 `accounts/<用户>`，避免切换用户后生成 `accounts/<用户>/accounts/<用户>` 嵌套路径，导致内容采集读不到账号矩阵 Cookie。
- `tests/test_agent_mode_defaults.py#L62-L88`：覆盖先切到 `user-owner` 再切到 `boss` 时，第二个账号目录必须仍在同一个根目录下，而不是落到前一个账号目录里面。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。回滚后多次切换用户仍可能再次产生账号目录嵌套。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 同款替换主角提取异常降级
- `backend/matrix_native_client.py#L10519-L10570`：`_extract_replacement_principal_actor()` 保持视觉模型响应解析严格，但当返回内容触发 `principal_actor_extract_invalid_response` 时，不再继续抛出到方案生成层；改为记录 `video_replace_principal_actor_extract_failed`，返回 `status=manual_required`、`candidatePaths`、首张候选帧预览和错误号。
- `backend/matrix_native_client.py#L10717-L10731`：方案就绪事件会在低置信度时自动使用第一张候选帧，把 `principalActor.status` 改为 `manual` 后继续主角整身替换链路，不再要求页面下拉确认。
- `tests/test_video_replacement_v2.py#L1405-L1427`：覆盖视觉模型返回非 JSON 时，主角提取降级为人工确认并保留候选帧、错误码和错误号。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。回滚后 `principal_actor_extract_invalid_response` 会再次导致“生成方案失败”。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 企业中心横幅视频固定
- `backend/matrix_native_client.py#L2690-L2814`：`VideoHero` 保留现有 `backend/datas/hero.mp4` 循环播放，移除横幅内“生成宣传片/重新生成”按钮、生成进度监听和重新加载生成结果逻辑，避免企业中心管理页出现可误触的生成入口。
- `tests/test_agent_mode_defaults.py#L143-L153`：覆盖企业中心横幅仍加载 `HERO_VIDEO` 播放，但类内部不再创建 `genbtn`、不再调用 `generate_hero_video()`、不再监听 `hero_video` 生成事件，源码中也不再保留横幅重新生成函数。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md` 和本文档即可；不涉及中心服、数据库、现有 `backend/datas/hero.mp4` 或 `migration.sql`。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 抖音内容采集默认账号选择
- `backend/api_server.py#L4994-L5015`：`/api/finder/discover` 在抖音平台下先按 `accountId/account` 选择账号；未显式传账号时复用账号矩阵最新可用抖音账号，并在该账号 Cookie/profile 作用域内执行内容采集。找不到可用账号时保留旧的默认 `require_auth()` 行为。
- `tests/test_douyin_multi_account.py#L125-L179`：覆盖默认 `auth_cookie.json` 只有 `msToken`、但账号矩阵里有完整抖音 Cookie 时，内容采集接口会使用矩阵账号而不是返回 `douyin_auth_incomplete`。
- 回滚：回滚 `backend/api_server.py`、`tests/test_douyin_multi_account.py`、`docs/TROUBLESHOOTING.md`、`CHANGELOG.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 同款替换字幕安全源片段
- `backend/matrix_native_client.py#L10373-L10427`：关键帧和旧图生视频提示词统一加入“字幕安全”规则，禁止模型复刻、保留或新增顶部/底部字幕、营销大字、弹幕式文字和屏幕贴纸文字。
- `backend/matrix_native_client.py#L10638-L10663`、`backend/matrix_native_client.py#L10718-L10782`：主角整身替换和普通远程编辑提示词不再要求“文字必须保持原视频一致”，只允许保留真实物体上的 Logo、招牌和产品包装文字；中文字幕只由后期字幕层合成。
- `backend/matrix_native_client.py#L12360-L12414`：新增 `_prepare_subtitle_safe_source_segment()`，默认用 ffmpeg 遮罩源片段顶部 16% 和底部 26% 区域，生成只供远程模型参考的字幕安全版视频；可通过 `VIDEO_REPLACE_SUBTITLE_SAFE_SOURCE=0` 关闭。
- `backend/matrix_native_client.py#L12433-L12441`：远程上传改用字幕安全源片段，任务 JSON 记录 `sourceSegmentUploadPath/sourceSegmentSubtitleSafeStatus`；音频回填仍使用原始 `sourceSegmentPath`。
- `tests/test_video_replacement_v2.py#L1191-L1218`、`tests/test_video_replacement_v2.py#L2120-L2168`：覆盖主角/普通远程编辑提示词的后期字幕层规则、远程上传安全源片段但音频回填保留原片段，以及 ffmpeg 生成有效字幕安全源片段。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/DEPLOYMENT.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。临时规避可设置 `VIDEO_REPLACE_SUBTITLE_SAFE_SOURCE=0` 并重启本地客户端。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 同款替换 AI 配音防截断
- `backend/matrix_native_client.py#L6041-L6089`：新增同款替换 TTS 口播时长估算和阻断提示格式化 helper，默认按约 `VIDEO_REPLACE_TTS_CHARS_PER_SEC=4.2` 字/秒估算，并计入标点停顿。
- `backend/matrix_native_client.py#L7082-L7085`：开始生成时只在 `audioMode=tts` 下检查每个片段口播稿，预计长于片段时长时直接提示“会被截断”并阻断后台生成。
- `backend/matrix_native_client.py#L11661-L11688`：TTS 音频下载后探测真实音频时长，若长于当前片段视频时长则写入 `ttsDurationSec/ttsTimingStatus/ttsTimingError` 并抛出 `replacement_tts_audio_too_long`，不再进入按片段时长截断的音轨合成。
- `tests/test_video_replacement_v2.py#L317-L348`、`tests/test_video_replacement_v2.py#L3876-L3930`：覆盖预计超长提示、真实 TTS 超长不进入合成、页面开始生成前阻断。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/DEPLOYMENT.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。回滚后 AI 配音超长会重新存在尾部被片段时长截断的风险。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 本地客户端三角色权限体系
- `backend/central_server.py#L3210-L3282`：新增产品角色中枢，统一把平台管理员映射为 `platform_admin`、企业 `owner/admin` 映射为 `enterprise_admin`、企业 `member` 映射为 `normal_user`，并提供自有数据过滤 helper。
- `backend/central_server.py#L3310-L3325`：平台管理员判定收紧为 root token、`user-owner` 或显式 `isPlatformAdmin`，不再把默认企业的 admin 自动当作平台管理员。
- `backend/central_server.py#L6649-L6678`、`backend/central_server.py#L9517-L9599`：账号矩阵和企业总览按角色返回 `all/org/self` 范围；普通用户只统计归属到自己的账号、素材、知识库、队列和任务。
- `backend/central_server.py#L13668-L13692`、`backend/central_server.py#L14588-L14637`：充值套餐、充值下单/状态、兑换码使用和管理员加款统一要求平台管理员，企业家和普通用户接口层返回 403。
- `backend/matrix_native_client.py#L596-L632`、`backend/matrix_native_client.py#L15913-L16000`、`backend/matrix_native_client.py#L17688-L17695`：本地客户端保存登录角色，左侧菜单按角色隐藏企业中心，账户中心资金容器和管理员用户管理只对平台管理员显示；兼容旧中心服未返回 `appRole/productRole/roleScope` 的登录响应，`user-owner` 推断为平台管理员，企业 `owner/admin` 推断为企业家。
- `tests/test_role_permissions.py#L1-L125`、`tests/test_auth_login_modes.py#L32-L36`：覆盖三角色映射、默认企业 admin 不再隐式成为平台管理员、手机号自注册默认普通用户、企业总览企业/个人范围差异、旧登录响应下管理员菜单兼容，以及本地管理员密码统一来自 `CENTRAL_ADMIN_PASSWORD=test123456`。
- 回滚：回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/ARCHITECTURE.md`、`docs/TROUBLESHOOTING.md`、`CHANGELOG.md` 和本文档即可；本次不改数据库结构，`migration.sql` 仍为 no-op。回滚后企业 admin 可能重新获得平台资金入口风险。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 同款替换无效控件移除
- `backend/matrix_native_client.py#L6276-L6321`：同款替换页移除“产品镜头锚定”“原片动作控制”“人物一致性”入口，声音来源控件上移；页面不再展示不会影响当前主角整身替换链路的选项。
- `backend/matrix_native_client.py#L6821-L6841`、`backend/matrix_native_client.py#L6917-L6930`：新任务固定写入 `identityMode=standard`、`enableFaceFusion=false`、`actionControlEnabled=false`、`productAnchorEnabled=false` 和空 `targetFaceReferencePath`，避免隐藏触发产品锚定、动作帧或本地 FaceFusion。
- `tests/test_video_replacement_v2.py#L3921-L3957`、`tests/test_video_replacement_v2.py#L4008-L4021`：覆盖页面不再创建三个控件，并锁定开始生成时固定关闭对应任务字段。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/ARCHITECTURE.md`、`docs/DEPLOYMENT.md`、`docs/TROUBLESHOOTING.md` 和本文档；不涉及中心服、数据库或 `migration.sql`。回滚后页面会恢复这些历史入口。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 同款替换产品图归一化移除与取消任务即时反馈
- `backend/matrix_native_client.py#L1289-L1337`：`lk888_media_task()` 新增 `cancel_check`，每轮轮询前、睡眠后和进度回调后检查本地取消标记，命中后抛出 `lk888_task_cancelled`，用于尽快退出本地等待。
- `backend/matrix_native_client.py#L6139-L6163`：新增同款替换取消状态 helper 和 `_mark_replacement_job_canceled()`，统一保存取消终态、清理敏感/临时素材并发送 `video_replace_done`。
- `backend/matrix_native_client.py#L7257-L7295`：`cancel_generation()` 在生成中立即写入 `status=cancel_requested`、`cancelRequested=true`，按钮改为“取消中”并禁用，同时发送 `video_replace_progress` 提示“当前远程片段结束后停止”。
- `backend/matrix_native_client.py#L10804-L10866`：产品图归一化函数保留兼容入口但不再调用图像模型；`_process_replacement_product_refs()` 直接并行上传用户原图，`productPreprocess` 记录 `normalized=false`、`product_normalize_removed`、`selectedPath`、`uploadUrl` 和耗时。
- `backend/matrix_native_client.py#L10712-L10726`、`backend/matrix_native_client.py#L12281-L12287`、`backend/matrix_native_client.py#L13107-L13124`：同款替换口播 TTS/数字人、主角整身替换和旧替换链路均接入取消检查；取消异常不会被记为片段生成失败。
- `tests/test_video_replacement_v2.py#L516-L538`、`tests/test_video_replacement_v2.py#L2402-L2544`、`tests/test_video_replacement_v2.py#L3645-L3679`：覆盖远程轮询取消、产品图直接原图上传且不调用归一化、取消按钮即时落盘和页面反馈。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `docs/DEPLOYMENT.md`；不涉及中心服、数据库或 `migration.sql`。回滚后产品图可能再次被图像模型重绘归一化，取消仍只能在片段边界体现。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 Agent.模式胶囊按钮点击位移修复
- `backend/matrix_native_client.py#L2127-L2129`：全局点击动画 `_scale()` 识别 `_no_press_scale` 标记，跳过直接修改 `geometry` 的缩放动画，避免和 Qt 布局管理器争抢按钮位置。
- `backend/matrix_native_client.py#L13863-L13865`：所有 `_icon_text_btn()` 生成的图标文字按钮统一打 `_no_press_scale=True`；覆盖 Agent.模式的风格、数量、比例、模型、提示词优化按钮，也覆盖资产库筛选、混剪添加等复用同一工厂的同类按钮。圆形固定图标按钮保留原动画。
- `tests/test_agent_mode_defaults.py#L88-L99`：新增契约测试，确认图标文字按钮退出全局 geometry 点击动画，避免点击后因文字变化或布局重算产生上移/跳动。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 Agent.模式提示词优化确认
- `backend/matrix_native_client.py#L9092-L9131`：新增 `_prodgen_optimize_prompt()`，使用 LK888 文本模型把用户原始需求优化为中文提示词；异常只记录本地日志并返回空结果，页面允许用户直接生成原输入。
- `backend/matrix_native_client.py#L9134-L9217`：商品图/视频生成链路拆分 `visiblePrompt` 与 `modelPrompt`；生成记录、生成中面板和资产库保存继续使用中文确认提示词，隐藏模型入参仍可按现有链路转换为模型更适配的提示词。
- `backend/matrix_native_client.py#L14116-L14165`：新增 `PromptConfirmDialog`，展示可编辑中文优化结果，用户点击“确认生成”后才进入扣费和生成流程。
- `backend/matrix_native_client.py#L14272-L14274`、`backend/matrix_native_client.py#L14526-L14559`、`backend/matrix_native_client.py#L14588-L14602`：Agent.模式输入区新增“提示词优化”按钮；优化过程禁用按钮并显示状态；返回后弹出确认窗口，失败时提示“可直接生成或稍后重试”。
- `tests/test_agent_mode_defaults.py#L75-L86`：新增契约测试，确认优化入口、确认弹窗、中文展示字段和隐藏模型提示词字段存在，且不再显示“英文提示词”说明。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_mode_defaults.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。回滚后 Agent.模式恢复输入后直接生成，生成中面板可能再次展示英文模型提示词。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 同款替换源视频槽位动态提取
- `backend/matrix_native_client.py#L9874-L9936`：`_replacement_source_context_from_analysis()` 现在合并分解报告、视觉说明、关键帧说明、OCR 和转写作为证据，从“视频类型/主推产品/核心卖点/场景/人物”等字段动态提取源视频类别、产品、场景和角色；兜底值改为通用“原视频类别/原视频可见产品/原视频场景/原视频人物”，不再把展厅或门店默认解释成汽车销售。
- `backend/matrix_native_client.py#L9939-L9985`：`_replacement_source_entities_from_analysis()` 使用动态 `sourceProductCategory` 和 `sourceScene` 生成 `sourceReplacementEntities`，产品和场景槽位跟随原视频真实内容，例如卫浴花洒视频会生成花洒/卫浴展厅槽位，而不是汽车/汽车展厅槽位。
- `backend/matrix_native_client.py#L6801-L6801`：开始生成或重试构建任务时，按当前 `breakdownAnalysis` 重新计算 `sourceReplacementEntities`，不复用旧任务 JSON 里可能已经写错的产品/场景槽位。
- `backend/matrix_native_client.py#L10498-L10523`：远程视频编辑 prompt 继续注入源视频锁定和实体槽位规则；上传产品/场景时强制替换，未上传时保留原片对应槽位。
- `tests/test_video_replacement_v2.py#L1384-L1410`：新增花洒/卫浴视频回归测试，确认源视频类别、产品和场景不再包含“汽车”，产品槽位必须包含“花洒”，场景槽位必须包含“卫浴”。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md`、`docs/API_REFERENCE.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。回滚后旧任务可能再次因错误源视频槽位触发视觉 QC 误判。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 同款替换声音来源可选
- `backend/matrix_native_client.py#L10466-L10480`：同款替换页“声音来源”默认改为自动使用生成视频自带声音；AI 音色按每段口播稿配音；上传完整配音会在最终成片阶段替换整条音轨，不做音色克隆。
- `backend/matrix_native_client.py#L6347-L6376`、`backend/matrix_native_client.py#L6566-L6585`：页面同步音频模式控件状态，上传完整配音音频后保存本地路径和素材 URL，并提示最终成片会替换整条音轨。
- `backend/matrix_native_client.py#L6654-L6657`、`backend/matrix_native_client.py#L6792-L6795`、`backend/matrix_native_client.py#L6878-L6901`：替换任务 JSON 写入 `audioMode`、`voiceId`、`replacementAudioPath` 和 `replacementAudioUrl`；上传完整配音缺失时生成前阻断，AI 音色配音缺口播稿时生成前阻断。
- `backend/matrix_native_client.py#L11250-L11365`、`backend/matrix_native_client.py#L12111-L12196`、`backend/matrix_native_client.py#L13062-L13064`：新增音频模式归一化、TTS 片段音轨替换和最终完整配音替换；默认 `source` 仍回填原片音轨，`tts` 逐段替换为所选音色，`uploaded` 在字幕烧录后替换最终成片音轨并要求上传音频不短于成片。
- `tests/test_video_replacement_v2.py#L267-L304`、`tests/test_video_replacement_v2.py#L1783-L1814`：覆盖 AI 音色模式不再调用原声回填、上传完整配音在字幕后替换最终音轨。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。回滚后同款替换将恢复固定使用原片声音。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 抖音安全验证窗口保留修复
- `backend/utils/publish_util.py#L142-L142`：新增 `MANUAL_VERIFY_REASONS`，把需要用户在浏览器里处理的安全验证/申诉状态归为人工处理类错误。
- `backend/utils/publish_util.py#L538-L540`：发布结果检测不再用泛泛的“验证”二字命中失败，改为只识别“安全验证 / 身份验证 / 验证身份”，避免页面出现“发送验证码”时被误杀。
- `backend/utils/publish_util.py#L619-L621`：真实发布遇到 `security_verify_required` 或 `security_appeal_required` 时保留浏览器窗口，不再进入 `ctx.close()` 清理，便于用户点击发送验证码并完成抖音安全验证。
- `backend/matrix_native_client.py#L7662-L7665`：本地客户端对 `security_verify_required` 和 `security_appeal_required` 展示中文可操作提示，要求用户在打开的浏览器里处理后重试。
- `tests/test_publish_util_safety.py#L36-L41`、`tests/test_native_publish.py#L57-L72`：覆盖安全验证不应泛匹配“验证”、必须保留浏览器，以及客户端提示不能再只显示“真实发布未完成”。
- 回滚：回滚 `backend/utils/publish_util.py`、`backend/matrix_native_client.py`、`tests/test_publish_util_safety.py`、`tests/test_native_publish.py` 和本文档即可；不涉及数据库迁移。回滚后抖音安全验证页可能再次在用户点击“发送验证码”前被关闭。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 素材发布标题弹窗编辑并作为真实发布标题
- `backend/matrix_native_client.py#L4605-L4616`：素材发布页发布账号栏新增“打开素材”按钮，用户选中表格素材后可直接用系统默认程序打开本机素材文件。
- `backend/matrix_native_client.py#L4678-L4734`：新增素材文件查找与打开逻辑；优先按素材记录的 `files/urls` 文件名，在下载源目录、本机素材目录和中心服本机素材目录中查找，命中顺序为视频文件优先、图片文件其次；找不到文件或系统无法打开时在状态栏提示。
- `backend/matrix_native_client.py#L4056-L4061`：素材发布表格标题列显示“标题（可编辑，正式发布时字数限制在30字以内）”，表格本身禁用内嵌编辑器，双击标题列打开编辑标题弹窗，类型和文件数仍保持只读。
- `backend/matrix_native_client.py#L4104-L4129`：点击“发布到抖音”时读取当前选中行第 0 列标题栏文本，保存完整标题，并将前 30 个字符作为 `publishTitle` 提交。
- `backend/matrix_native_client.py#L4131-L4178`：标题弹窗使用大文本框编辑完整标题，显示当前字数和正式发布 30 字提示；保存后写回表格并调用 `/api/library/update-title`，刷新后不丢失。
- `backend/api_server.py#L5293-L5308`：`/api/library/update-title` 只更新指定素材的 `title` 字段。
- `backend/api_server.py#L2727-L2736`、`backend/api_server.py#L5342-L5354`：`run_publish()` 支持 `title_override`，`/api/publish/run` 优先使用 `publishTitle`，无覆盖值时回退素材原 `title`。
- `backend/utils/publish_util.py#L444-L445`：发布器填写抖音标题前按正式发布规则限制为前 30 个字符；素材库保存的标题不受该限制。
- `tests/test_native_publish.py#L40-L132`、`tests/test_publish_util_safety.py#L44-L51`：覆盖标题列改走弹窗编辑、表格内嵌编辑器禁用、素材打开按钮和文件优先级、发布 payload 使用前 30 个字符、本机 API 接收标题覆盖值、标题更新接口存在，以及发布器的 30 字限制。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`backend/utils/publish_util.py`、相关测试、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及数据库迁移。回滚后真实发布标题将重新取素材入库 `title`，标题编辑也可能恢复为表格内嵌输入框，“打开素材”按钮会消失。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 主角整身替换提示词和 QC 收紧
- `backend/matrix_native_client.py#L6120-L6182`：同款替换页前置提示改为“上传人物/产品/场景则强制替换，未上传则保留原片对应槽位”，避免用户误以为产品或场景只是弱参考。
- `backend/matrix_native_client.py#L9750-L9879`：源视频实体替换规则和源视频锁定文案统一为槽位开关逻辑：人物图强制替换主角完整外观；产品图未上传保留原产品、上传强制替换；场景图未上传保留原场景、上传强制替换。
- `backend/matrix_native_client.py#L10197-L10272`：`happyhorse-video-edit` 主角请求把人物图、产品图、场景图一起写入 `images/image_urls/params.images`；提示词明确不得保留原片主角外观，并按上传状态控制产品/场景槽位。
- `backend/matrix_native_client.py#L11227-L11575`：参考图预检把产品/场景类别差异降级为 warning；主角视觉 QC 新增 `fullBodyAppearanceMatch` 和 `principal_appearance_mismatch`，生成结果若仍保留原片主角发型、服装、体型或配饰会硬阻断；上传场景图后 `scene_mismatch` 不再以源场景优先放行。
- `tests/test_video_replacement_v2.py#L914-L955`、`tests/test_video_replacement_v2.py#L1398-L1422`、`tests/test_video_replacement_v2.py#L1467-L1498`、`tests/test_video_replacement_v2.py#L3115-L3137`：覆盖主角请求携带产品/场景参考图、产品类别冲突降级 warning、实体槽位 prompt 和上传场景不匹配时失败。
- 回滚：设置 `VIDEO_REPLACE_PRINCIPAL_REPLACEMENT=0` 并重启本地客户端可回到旧参考图候选链；不涉及中心服、数据库或 `migration.sql`。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 素材发布上传中窗口保留修复
- `backend/utils/publish_util.py#L151-L159`：新增 `DY_PUBLISH_PENDING_TIMEOUT`，真实发布点击后若抖音显示“作品上传中/上传完成后将自动发布”，会使用独立的长等待窗口，默认 1800 秒。
- `backend/utils/publish_util.py#L543-L598`：发布成功确认循环在检测到上传中状态时延长等待，而不是按普通 `DY_PUBLISH_TIMEOUT` 过早结束。
- `backend/utils/publish_util.py#L614-L660`：如果等待结束时仍是 `publish_upload_pending`，发布器不再主动关闭浏览器上下文或删除临时 profile，保留窗口让抖音继续完成上传/自动发布。
- `tests/test_publish_util_safety.py#L28-L34`：覆盖上传中真实发布必须有延长等待和保留窗口保护。
- 回滚：回滚 `backend/utils/publish_util.py` 与 `tests/test_publish_util_safety.py` 对应改动即可；不涉及数据库迁移。回滚后大文件或慢网发布仍可能在抖音完成前被本地窗口关闭。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-22 素材发布真实发布未完成提示修复
- `backend/matrix_native_client.py#L4135-L4137`：本地客户端“发布到抖音”结果展示改为统一调用 `_publish_result_message()`，不再在真实发布失败时直接显示“试发完成，未真实发布”。
- `backend/matrix_native_client.py#L7495-L7505`：新增 `_publish_result_message()`；只有结果里明确 `dryRun=true` 且 `filled=true/published=false` 时才显示“试发完成”，真实发布未完成会显示“真实发布未完成:<error>”。
- `backend/api_server.py#L5328-L5331`：本机 `/api/publish/run` 响应新增 `dryRun` 字段，保证客户端能区分试发和真实发布。
- `tests/test_native_publish.py#L40-L63`：覆盖真实发布 `filled=true/published=false/dryRun=false` 不能再被标记为试发，以及本机发布接口必须回传 `dryRun`。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/api_server.py` 和 `tests/test_native_publish.py` 对应改动即可；不涉及数据库迁移。回滚后真实发布未完成仍可能被界面误写成“试发完成”。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-22 同款替换源视频实体槽位替换
- `backend/matrix_native_client.py`：同款替换页标题和生成中反馈改为“先提取原片人物/产品/场景槽位”，让用户知道不是只把上传参考图直接丢给模型。
- `backend/matrix_native_client.py`：新增 `_replacement_source_entities_from_analysis()` 与 `_replacement_source_entity_lock_text()`，从原视频分解结果归纳人物槽位、产品槽位、场景槽位和替换规则，并写入任务 JSON `sourceReplacementEntities`。
- `backend/matrix_native_client.py`：替换方案 prompt 与远程编辑 prompt 注入“源视频实体替换”规则：原片人物槽位替换为上传授权人物/虚拟模特完整外观；原片产品和场景槽位均为“未上传保留原片，上传强制替换为上传素材”。
- `tests/test_video_replacement_v2.py`：新增源视频实体提取、远程编辑实体替换 prompt 和页面提示契约测试。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md` 和本文件即可；不涉及数据库迁移。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-22 素材发布到抖音真实发布误报修复
- `backend/utils/publish_util.py#L400-L405`：登录墙/风控墙命中 `CTF_LOCAL_SAFE_PUBLISH` 绕过时，真实发布不再返回 `ok=true` 或 `published=true`；仅 dry-run 可标记为表单填充完成。
- `backend/utils/publish_util.py#L604-L609`：点击发布后的失败、风控或上传未完成结果即使在本地安全绕过模式下也保留失败错误码，并强制 `published=false`。
- `tests/test_publish_util_safety.py#L11-L26`：覆盖安全绕过代码块不得再把正式发布伪装为 `published=true`，防止“发布到抖音”按钮显示成功但作品未进入抖音。
- 回滚：回滚 `backend/utils/publish_util.py` 和 `tests/test_publish_util_safety.py` 即可；不涉及数据库迁移。回滚后若环境中存在 `CTF_LOCAL_SAFE_PUBLISH=1`，真实发布遇到登录墙、风控或上传未完成仍可能被误报为发布成功。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-22 同款替换口播稿链路回正
- `backend/matrix_native_client.py#L5830-L5831`：同款替换片段判定函数固定返回非数字人口播，避免环境变量或旧任务字段把同款替换片段转为 `talking`。
- `backend/matrix_native_client.py#L6237-L6259`：同款替换片段表格从 10 列改为 9 列，移除“类型”列，口播稿列固定为可编辑多行文本框。
- `backend/matrix_native_client.py#L6808-L6813`：生成前收集用户编辑内容时直接读取口播稿文本框，并把片段类型统一写回 `non_talking`。
- `backend/matrix_native_client.py#L7011-L7035`：口播稿读取列改为当前第 2 列，刷新表格时不再创建口播/非口播下拉框。
- `backend/matrix_native_client.py#L9496-L9528`：生成同款替换方案时保留转写/文本框口播稿到 `script`，但 `segmentType` 固定为 `non_talking`。
- `backend/matrix_native_client.py#L11242-L11249`：执行单片段时兼容旧 job，把历史 `talking` 片段也归一为同款替换远程参考/动作控制链路。
- `tests/test_video_replacement_v2.py#L221-L235`、`tests/test_video_replacement_v2.py#L258-L294`、`tests/test_video_replacement_v2.py#L2282-L2312`、`tests/test_video_replacement_v2.py#L3083-L3131`：覆盖表格列变化、环境变量无效化、严格口播不再进数字人口播、mock 混合链路全段走同款替换。
- 回滚：恢复上述文件到上一稳定版本即可。回滚后 `VIDEO_REPLACE_STRICT_SCRIPT_AUDIO` 或旧 `talking` 任务可能再次导致同款替换进入数字人口播。本次不涉及数据库结构或数据迁移，`migration.sql` 不变。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-22 同款替换产品图归一化一致性校验

- 注：该历史链路已在 2026-07-23 被废弃；当前新任务直接上传用户产品原图，不再执行白底归一化或归一化后一致性校验。
- `backend/matrix_native_client.py#L9878-L9947`：新增 `VIDEO_REPLACE_PRODUCT_NORMALIZE_VALIDATE` 开关和 `_validate_replacement_product_normalization()`，用视觉模型比较用户原始产品图与白底归一化结果，要求仍为同一产品主体；品类变化、主体变化或引入其他品牌产品时返回 `product_normalize_mismatch`。
- `backend/matrix_native_client.py#L9949-L10008`：`_normalize_replacement_product_image()` 在采信白底图前执行一致性校验；校验失败、校验异常或缺少可访问 URL 时自动回退用户原图，并在 `productPreprocess` 写入 `normalizedPath`、`selectedPath`、`fallbackReason`、`validation` 和结构化日志 `errorId`。
- `backend/matrix_native_client.py#L10010-L10039`：`_process_replacement_product_refs()` 上传最终选中的图片；当归一化异常回退时向页面发送“产品图 N/M 归一化异常，已回退原图继续生成”，避免用户误以为系统仍采信错图。
- `tests/test_video_replacement_v2.py#L1739-L1887`：覆盖归一化成功必须通过校验、上游生成失败回退、验真拒绝时回退原图、环境开关关闭归一化、受限并行顺序稳定和回退进度提示。
- 回滚：设置 `VIDEO_REPLACE_PRODUCT_NORMALIZE_VALIDATE=0` 可临时恢复旧的“生成成功即采信”逻辑；更稳妥的紧急规避是设置 `VIDEO_REPLACE_PRODUCT_NORMALIZE=0` 直接使用用户原图。本次不涉及数据库迁移，`migration.sql` 无需变更。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-22 同款替换产品图并行处理与页面提示

- 注：2026-07-23 起并行处理只负责上传用户产品原图，不再包含白底归一化步骤。
- `backend/matrix_native_client.py#L6489-L6496`：同款替换上传参考图入口改为调用 `_process_replacement_product_refs()`，产品图预处理报告继续写入任务 JSON，后续人脸图和场景图上传链路保持原有顺序。
- `backend/matrix_native_client.py#L6681-L6690`：开始生成时把产品图处理进度转发为 `video_replace_progress`，阶段标记为 `product_refs`，客户端状态栏和进度详情会显示具体产品图编号，而不是只停留在“上传参考图”。
- `backend/matrix_native_client.py#L9908-L9974`：新增 `VIDEO_REPLACE_PRODUCT_PARALLEL` 并发控制和 `_process_replacement_product_refs()`；默认并行度为 `2`，范围限制在 `1..3`，并保留输出顺序、单图耗时 `elapsedSec`、上传 URL 和归一化报告。
- `tests/test_video_replacement_v2.py#L1779-L1831`：覆盖产品图受限并行、结果顺序稳定、进度回调触达页面事件的契约。
- 回滚：设置 `VIDEO_REPLACE_PRODUCT_PARALLEL=1` 可恢复串行处理；若上游图像归一化服务异常或成本需要临时规避，可设置 `VIDEO_REPLACE_PRODUCT_NORMALIZE=0` 跳过白底归一化。本次不涉及数据库迁移，`migration.sql` 无需变更。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-21 数字人口播场景背景强制重试
- `backend/matrix_native_client.py#L4719-L4730`：新增脱敏追踪 URL，只保留协议、主机和路径，避免签名查询参数进入结构化日志或客户端诊断信息。
- `backend/matrix_native_client.py#L4733-L4806`：场景合成支持 `strict_scene=True`；重试提示明确要求上传场景是唯一背景来源，禁止生成户外公园、绿地、湖景或其他新场景。
- `backend/matrix_native_client.py#L4808-L4890`：新增场景合成与质检编排，首次背景质检失败时自动强约束重试一次；二次质检仍失败才进入退款和错误链路，并记录 `digital_human_scene_background_retry`。
- `backend/matrix_native_client.py#L4892-L4909`：数字人口播在 TTS 前使用上述编排结果，只有通过背景质检的合成图才会进入数字人视频生成。
- `backend/matrix_native_client.py#L4922-L4966`、`#L5269-L5280`：错误提示区分用户上传场景图与系统合成数字人图，并把中间合成图的脱敏 URL 放入错误事件和客户端状态栏。
- `tests/test_video_replacement_v2.py#L603-L681`、`#L725-L799`：覆盖背景跑偏后的严格重试、签名 URL 脱敏、可追溯状态字段和原有场景图回归路径。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-21 本地客户端真实发布修复

- `backend/matrix_native_client.py#L4103-L4111`：本地客户端“素材与发布”页发布 payload 显式加入 `dryRun=false`，确保按钮执行真实发布而不是后端默认试发。
- `backend/matrix_native_client.py#L4133-L4144`：发布结果状态栏只在 `_publish_result_ok()` 通过时显示“发布成功”，试发完成但未发布时显示“试发完成，未真实发布”。
- `backend/matrix_native_client.py#L7490-L7497`：`_publish_result_ok(..., dry=False)` 改为只认 `published=true`；`dry=True` 仍允许 `filled/ok` 表示试发完成。
- `tests/test_native_publish.py#L22-L37`：覆盖真实发布不能由 `ok=true/filled=true` 误判成功，以及本地发布按钮必须提交 `dryRun=false`。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-21 同款替换 fallback、连续性和字幕稳定性修复

- `backend/matrix_native_client.py#L3990-L3995`：分解视频页打开视频失败时显示状态提示，避免点击无反应。
- `backend/matrix_native_client.py#L9657-L9664`、`backend/matrix_native_client.py#L10579-L10584`：按候选模型构建远程 payload，`happyhorse-*` fallback 下单前将 `resolution=720p` 规范为 `720P`。
- `backend/matrix_native_client.py#L9586-L9618`：非口播远程编辑请求支持上一段生成结果连续性参考帧，并在提示词中约束同一新人设、脸部观感、发型和服装连续。
- `backend/matrix_native_client.py#L10565-L10571`、`backend/matrix_native_client.py#L10988-L11034`：上传上一段最后一张审核帧作为 `continuityFrameUrl`；失败只记录 `continuityFrameWarning`，不阻断当前片段。
- `backend/matrix_native_client.py#L11298-L11324`：字幕事件优先按每个片段实际 `videoPath` 探测时长排布，减少生成片段时长波动造成的字幕漂移。
- `tests/test_video_breakdown.py#L121-L130`：覆盖打开视频失败时必须给出状态提示。
- `tests/test_video_replacement_v2.py#L755-L785`：覆盖上一段连续性参考和 `happyhorse-*` fallback 分辨率规范化。
- `tests/test_video_replacement_v2.py#L1129-L1148`：覆盖字幕事件按实际片段视频时长对齐。
- `tests/test_video_replacement_v2.py#L1313-L1329`：覆盖连续性参考帧上传和临时素材 ID 记录。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-21 同款替换原片动作控制

- `backend/matrix_native_client.py#L5540-L5546`：新增 `_replacement_action_control_enabled()`，支持任务字段和 `VIDEO_REPLACE_ACTION_CONTROL` 环境变量，默认关闭。
- `backend/matrix_native_client.py#L5884-L5909`：同款替换页新增“原片动作控制”开关，文案明确动作帧只用于动作、站位、构图和镜头参考。
- `backend/matrix_native_client.py#L6241-L6294`、`backend/matrix_native_client.py#L6319-L6352`：生成任务持久化 `actionControlEnabled`，用于执行、重试和审计。
- `backend/matrix_native_client.py#L9224-L9254`：同款替换方案取消固定总时长硬上限，仍按约 8 秒分段并保留口播/非口播识别。
- `backend/matrix_native_client.py#L9470-L9527`：非口播远程视频请求把 `actionFrameUrls` 追加到参考图列表，并在提示词中声明动作帧不是身份参考。
- `backend/matrix_native_client.py#L10439-L10445`：源片段上传后准备动作帧引用，失败时只记录 warning 并继续原远程链路。
- `backend/matrix_native_client.py#L10767-L10860`：新增按约 2 秒抽取动作帧、单段最多 4 张、上传公网 URL 和 fallback 记录 helper。
- `tests/test_video_replacement_v2.py#L272-L281`：覆盖 180 秒视频不再因旧 60 秒配置失败，并按 8 秒切为 23 段。
- `tests/test_video_replacement_v2.py#L570-L594`：覆盖动作帧加入远程参考图和 motion-only/非身份参考提示词。
- `tests/test_video_replacement_v2.py#L1021-L1100`：覆盖动作帧抽取上传进入远程请求，以及上传失败时回退标准远程链路。
- `tests/test_video_replacement_v2.py#L2409-L2420`：覆盖页面新增开关和任务 JSON 字段契约。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-21 同款替换片段表格可读性修复

- `backend/matrix_native_client.py#L5948-L5974`：同款替换片段表格开启逐像素滚动、行选择、固定列宽和 122px 行高；口播稿列固定 520px，操作列固定 120px，避免信息列继续挤压口播稿编辑区。
- `backend/matrix_native_client.py#L6505-L6517`：生成前从 `_segment_script_value()` 读取多行口播稿编辑器内容，继续保留口播片段缺稿阻断。
- `backend/matrix_native_client.py#L6691-L6719`：新增 `_make_segment_script_editor()` 和 `_segment_script_value()`，口播稿使用 `QPlainTextEdit` 多行显示/编辑，最小宽度 500px、最小高度 104px，固定深色背景、白色文字、选中态和 focus 边框。
- `backend/matrix_native_client.py#L6722-L6755`：刷新片段表格时使用多行口播稿编辑器，删除按钮放入带内边距的 cell 容器并固定为 92x30。
- `tests/test_video_replacement_v2.py#L221-L235`：覆盖片段表格口播稿编辑器、滚动/列宽、行高和删除按钮固定尺寸契约。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-20 同款替换清晰中文字幕后期烧录

- `backend/matrix_native_client.py#L6501-L6534`：人工确认合成时改走 `_prepare_replacement_final_video()`，先合并片段，再按口播稿烧录字幕，最后保存资产库并执行最终音频检查。
- `backend/matrix_native_client.py#L9281-L9444`：同款替换片段、关键帧、图生视频和远程编辑 prompt 增加“不要新增模型生成字幕/屏幕文字”的约束，避免模型先生成糊字。
- `backend/matrix_native_client.py#L10903-L11054`：新增字幕开关、ASS 时间戳/文本转义/换行、片段口播稿事件生成、ASS 文件输出、ffmpeg 字幕烧录和最终成片准备 helper；`VIDEO_REPLACE_BURN_SUBTITLES=0` 可回滚关闭。
- `tests/test_video_replacement_v2.py#L870-L912`：覆盖 ASS 字幕样式、片段时间轴和最终合成前先烧录字幕的契约。
- `tests/test_video_replacement_v2.py#L2213-L2256`：混合口播/非口播 mock 管线继续验证最终拼接视频可用且音频非静音。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-20 原生客户端可读性与中文片段提示词

- `backend/matrix_native_client.py#L1754-L1794`：全局 Qt 深色主题补齐 `QCheckBox::indicator`、按钮、文本框 focus/selection/disabled 和表格选中态样式，确保勾选框、下载报告按钮、口播稿文本框在深色界面可读。
- `backend/matrix_native_client.py#L9842-L9879`：同款替换源视频锁定文案中文化，明确人物参考图只用于新主角完整外观一致性，产品图只控制目标产品，冲突时以源视频类别和上传产品为准。
- `backend/matrix_native_client.py#L9268-L9444`：跑偏重试、片段 prompt、关键帧 prompt、图生视频 prompt 和混合远程编辑 prompt 统一输出中文，保留源片节奏、产品锁定、人物身份锁定和场景参考可选约束。
- `backend/matrix_native_client.py#L10835-L10854`：非口播替换片段生成前用 `源视频锁定：` 检测是否已注入锁定规则，避免中文化后重复拼接或漏拼接。
- `tests/test_video_replacement.py#L40-L164`：覆盖同款替换片段 prompt、中文显示 prompt 和关键帧首帧锚定约束。
- `tests/test_video_replacement_v2.py#L210-L225`、`tests/test_video_replacement_v2.py#L696-L735`、`tests/test_video_replacement_v2.py#L2252-L2268`：覆盖深色主题控件可读性、源视频锁定中文契约和场景参考可选约束。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-20 本地浏览器评论任务结果归一化

- `backend/central_server.py#L12876-L12893`：本地浏览器任务结果列表归一化，避免对象型 `comments` 被当作列表切片。
- `backend/central_server.py#L13285-L13312`：`local_browser_result()` 保存 `items/comments/leads` 时只切片列表，评论对象回退到规范化后的 `items` 或嵌套评论列表，确保成功结果能继续标记为 `done`。
- `tests/test_api_download_contract.py#L295-L336`：覆盖 `douyin.comments` 返回 `{status_code, comments:[...]}` 时中心任务状态必须结束为 `done`。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-20 抖音读取评论默认账号选择

- `backend/api_server.py#L344-L366`：`default_douyin_comment_account_id()` 在未显式传入 `accountId` 时，从账号矩阵中按 `lastLoginAt/updatedAt` 选择最新且 Cookie 缓存含登录标记的可用抖音账号。
- `backend/api_server.py#L4745-L4765`：GET `/api/douyin/comments` 读取评论前优先进入选中账号的 Cookie/profile 作用域，找不到可用账号时保留旧默认鉴权。
- `backend/api_server.py#L5113-L5151`：POST `/api/douyin/comments` 同步使用默认账号选择，覆盖本地客户端 `douyin.comments` 任务未传账号的场景。
- `tests/test_douyin_multi_account.py#L103-L121`：覆盖默认缓存无效但账号矩阵账号可用时，读取评论默认选中最新可用账号。

以下行号基于 2026-07-20 当前工作区。任何后续源文件改动导致行号变化时，发布前必须重新计算。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 下载、校验与素材修复

- `backend/utils/media_validation.py#L119-L246`：视频全量解码、图片完整解码和媒体真实性校验。
- `backend/utils/media_validation.py#L254-L306`：坏文件隔离和保留期清理。
- `backend/utils/structured_log.py#L56-L162`：URL、认证信息和密钥脱敏，输出带堆栈及 `errorId` 的 JSON 日志。
- `backend/utils/data_util.py#L186-L335`：抖音鉴权下载到独立 `.part`，校验后原子替换。
- `backend/api_server.py#L446-L463`、`backend/api_server.py#L2943-L2954`：抖音登录态完整性校验，拒绝只有 `msToken` 或缺少浏览器指纹的缓存，返回 `douyin_auth_incomplete` 供客户端提示重新登录。
- `backend/matrix_native_client.py#L3640-L3646`、`backend/matrix_native_client.py#L8645-L8653`：原生客户端分解下载失败文案映射，将 `douyin_auth_incomplete` 和历史 `'s_v_web_id'` 显示为重新登录抖音提示。
- `backend/api_server.py#L1443-L1678`：本地素材入库校验、原 ID 修复和事务回滚。
- `backend/central_server.py#L1405-L1659`：中心素材镜像校验、隔离和原 ID 修复。
- `backend/api_server.py#L4881-L4998`：抖音/XHS 下载入库错误契约与中心素材删除入口。
- `backend/central_server.py#L13203-L13254`：local-browser 下载完成前的中心镜像最终化。
- `backend/central_server.py#L15066-L15107`：中心云节点下载镜像错误契约。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 抖音多账号

- `backend/api_server.py#L138-L149`：本地账号注册表和每账号 profile 根目录路径。
- `backend/api_server.py#L285-L437`：抖音账号 ID 派生、注册表读写、profile/auth 路径、账号注册/移除和运行时账号作用域。
- `backend/api_server.py#L606-L665`：账号级能力计算和 Cookie 缓存读写。
- `backend/api_server.py#L727-L792`：`/api/accounts` 返回多个抖音账号并保留旧 `douyin-self` 兼容。
- `backend/api_server.py#L2694-L2733`：发布时按 `accountId` 切换对应账号 Cookie 与 `DY_PROFILE_DIR`。
- `backend/api_server.py#L2855-L2910`：账号级 `set_auth_from_cookie()`、`ensure_auth_from_cache()` 和 profile 同步。
- `backend/api_server.py#L3028-L3075`：`fresh=true` 登录使用临时 profile，成功后迁入独立账号目录，不再删除旧账号 profile。
- `backend/api_server.py#L4947-L4951`：本地 `/api/accounts/remove` 删除注册表记录，默认保留 profile 文件便于回滚。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 分解、OCR 与转写

- `backend/matrix_native_client.py#L231-L310`：客户端启动时清理崩溃遗留的分解临时目录。
- `backend/matrix_native_client.py#L3553-L3968`：分解页预检、串行任务、重试、进入同款替换事件和带入数字人口播事件。
- `backend/matrix_native_client.py#L8033-L8057`：分解结果转数字人口播 seed，优先使用口播转写并生成可编辑数字人形象描述。
- `backend/matrix_native_client.py#L8060-L8429`：七栏报告契约、缺失栏目补全和报告生成。
- `backend/matrix_native_client.py#L9679-L9799`：Tesseract 优先、RapidOCR 回退和逐帧错误记录。
- `backend/matrix_native_client.py#L9801-L9888`：客户端音频分片转写封装与降级状态。
- `backend/utils/video_transcription.py#L24-L145`：服务 URL 策略、60 秒分片、默认完整时长导出、显式上限和定向重试导出。
- `backend/utils/video_transcription.py#L144-L243`：严格转写 Schema、拒绝识别和绝对时间戳合并。
- `backend/utils/video_transcription.py#L274-L356`：Gemini 音频请求、顺序重试和结构化失败。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 数字人口播
- `backend/matrix_native_client.py#L4698-L4744`：场景版人物图合成新增同步图片网关异常识别与轻量重试；首次 `1024x1536` 遇到 `502/504/timeout/lk888_proxy_error` 时记录 `digital_human_scene_avatar_retry` 结构化日志，并用 `1024x1024` 重试一次。连续失败时抛出 `digital_human_scene_avatar_image_timeout`，不继续进入 TTS 或最终数字人视频生成。
- `backend/matrix_native_client.py#L4842-L4843`：数字人口播页面把连续图片代理超时映射为中文可操作提示，建议稍后重试、不上传场景图或更换更清晰简单的场景图。
- `tests/test_video_replacement_v2.py#L602-L680`：覆盖场景合成图超时中文提示、502 后降尺寸重试、场景图本地 data URL、场景一致性质检和失败阻断。

- `backend/matrix_native_client.py#L4650-L4692`：新增 `_digital_human_scene_reference()` 与 `_verify_digital_human_scene_background()`，优先把本地上传场景图转 data URL 送视觉模型，对比上传场景和合成后人物图背景；场景不一致时返回失败并记录结构化日志。
- `backend/matrix_native_client.py#L4695-L4725`：`_compose_digital_human_scene_avatar_url()` 上传场景图时把人物图和场景图送入 `lk888_image_result(..., image_urls=[avatar, scene])`，生成场景版人物形象图公网 URL；若场景图不是公网可读 URL 或合成图无法转成公网 URL，则抛错并停止生成。
- `backend/matrix_native_client.py#L4754-L4814`：数字人口播生成在 TTS 前执行强制换背景和场景一致性质检；未上传场景图时保持原链路，上传场景图时只有合成图背景通过质检才继续 TTS 与 `kling-avatar-image2video`，失败进入现有退款路径并显示中文原因。
- `backend/matrix_native_client.py#L4827-L5092`：数字人口播页面保存本地场景图路径，生成时随公网场景 URL 一起传入后端；页面文案明确“上传场景图（强制换背景）”。
- `tests/test_video_replacement_v2.py#L531-L676`：覆盖上传场景图时必须“合成 -> 质检 -> TTS”、场景不一致时停止、合成优先使用本地场景 data URL、质检 JSON 解析、无场景图跳过、私网场景图在 TTS 前阻断，以及页面文案契约。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 同款替换 V2 页面

- `backend/matrix_native_client.py#L5069-L5274`：同款替换前台错误展示中文化映射、上游预检结果归一化和任务内诊断摘要 helper；任务 JSON 和结构化日志仍保留原始错误码、`errorId`、`upstreamPreflight` 与 `diagnostics`。
- `backend/matrix_native_client.py#L5373-L5534`：人物一致性模式 helper、FaceFusion 启用门禁、视觉 QC 严格/宽松开关、漂移防护环境变量配置、硬漂移判定、自动重试计数和重试耗尽标记；`role_mismatch` / `structure_mismatch` 默认降级为 `review_warning`，仅 `visual_drift_blocked`、`topic_mismatch` 和 `visual_drift_retry_exhausted` 属于硬漂移。
- `backend/matrix_native_client.py#L5576-L5617`：片段状态文本显示片段序号、阶段、人物一致性模式、模型、耗时、质检提醒、错误编号、漂移重试次数和阻断原因。
- 历史实现 `backend/matrix_native_client.py#L5510-L5632` 曾包含产品、可选场景、三张授权人脸、纯产品无人物模式和人物一致性控件；当前人物入口已由本页顶部“同款替换统一单图”规则取代。场景图仍为可选增强，不得覆盖源视频主题和镜头结构。
- `backend/matrix_native_client.py#L5629-L5747`：源视频加载、输入选择、60 秒分段方案、人物候选、虚拟模特生成和原子任务 JSON。
- `backend/matrix_native_client.py#L6218-L6353`：开始生成读取 `identityMode`，默认标准模式不跑 FaceFusion，高一致模式才执行 FaceFusion 预检，纯产品模式强制关闭 FaceFusion；真人模式不再要求场景图必填；任务在上传参考图前先执行 `_replacement_upstream_preflight()`，失败时写入 `upstreamPreflight`、`diagnostics` 和 `errorId` 并发送 `video_replace_done`，成功后再上传素材、持久化 `driftGuardConfig` 与 `referencePreflight`。
- `backend/matrix_native_client.py#L6356-L6431`：单并发混合分流、片段开始/结束时间、阶段进度 payload、失败片段保留、`diagnostics` 摘要和 `awaiting_review` 门禁。
- `backend/matrix_native_client.py#L6004-L6058`：人工确认后合成、资产库复制、最终音频检查和中心素材清理。
- `backend/matrix_native_client.py#L6507-L6533`：单段重试前调用 `_prepare_replacement_segment_for_retry()`，把旧误阻断快照写入 `retryHistory`，记录 `lastRetryPreparation`，再重跑失败片段。
- `backend/matrix_native_client.py#L6535-L6604`：取消、待生成片段删除、进度反馈、耗时/预计列、模型/质检提醒/错误编号状态摘要、可编辑片段/QC 表格和失败弹窗诊断建议。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 同款替换 V2 核心

- `backend/matrix_native_client.py#L5519-L5533`、`backend/matrix_native_client.py#L5859-L5862`、`backend/matrix_native_client.py#L9128-L9162`、`backend/matrix_native_client.py#L10510-L10516`：同款替换支持严格口播模式；`VIDEO_REPLACE_STRICT_SCRIPT_AUDIO=1` 或页面“严格按口播稿生成语音”开启时，有 `script` 的片段强制标注为 `talking` 并进入 TTS/数字人口播链路；默认/回滚状态仍可保留旧的非口播回填源音频策略。
- `backend/matrix_native_client.py#L1465-L1477`、`backend/matrix_native_client.py#L9151-L9206`：同款替换默认使用 `viduq3-turbo-cankaosheng` 参考图视频模型，失败后按 `wan2.7-cankaosheng`、Vidu 其他参考模型和 happyhorse r2v 顺序回退；发送远端前剥离本地追踪字段，任务 JSON 保留 `sourceSegmentUrl`、`model`、`remoteModelFallbacks`、`remoteErrorId`。
- `backend/matrix_native_client.py#L8950-L9012`：从分解报告抽取源视频行业、人物角色和产品类别，并构造 Source lock 文案；人物参考图只贡献身份，不能覆盖原片行业、商品、背景或道具。
- `backend/matrix_native_client.py#L9003-L9204`：漂移重试提示、替换 prompt、关键帧 prompt 和非口播远程编辑 prompt 注入 Source lock；严重跑偏重试时强化原视频锁定；场景参考只在兼容源视频场景类型、镜头节奏和营销结构时作为可选环境提示。
- `backend/matrix_native_client.py#L9792-L9865`：参考图预检调用视觉服务，写入 `referencePreflight`；服务异常降级为后置质检，人物参考图上下文阻断降级为 warning，产品图强冲突才默认返回 `reference_mismatch` 阻断，场景图不能覆盖源视频主题、源片段场景类型或镜头结构。
- `backend/matrix_native_client.py#L11396-L11575`：视觉 QC 输出 `topicMatch`、`roleMatch`、`structureMatch`、`severeDrift` 和 `visualDriftQc`；Prompt 明确要求无人物产品段、车身/车内/细节角度变化不要判为严重跑题；硬漂移按 `blocking` 处理并覆盖所有人物一致性模式，角色/结构变化默认进入人工审核提醒；上传场景图时 `sceneMatch=false` 返回 `scene_mismatch`。
- `backend/matrix_native_client.py#L9839-L10043`：非口播“源片段上传并记录公网 URL -> 参考图视频模型顺序重试 -> 下载 -> 按高一致模式可选 FaceFusion -> 音频回填 -> QC”；硬漂移自动重试一次，第二次写入 `visual_drift_retry_exhausted` 并阻断合成。
- `backend/matrix_native_client.py#L10029-L10397`：talking 片段关键帧、TTS、数字人口播、高一致模式 FaceFusion 兜底和 QC。
- `backend/matrix_native_client.py#L9257-L9335`：FaceFusion 商用配置预检和参数数组 `shell=False` 调用。
- `backend/matrix_native_client.py#L9338-L9428`：中心敏感/临时素材清理、任务原子持久化和 24 小时目录清理。
- `backend/matrix_native_client.py#L9448-L9586`：同款替换旧任务恢复与重试准备 helper；启动时把残留活跃任务恢复为 `partial` / `failed`，重试前清理旧 `role_mismatch`、`structure_mismatch`、人物背景类 `reference_mismatch` 阻断并保留可追溯历史。
- `backend/matrix_native_client.py#L9431-L9547`：非静音音频 QC、FaceFusion 音轨回填、源片段裁切和首中尾帧抽取。
- `backend/matrix_native_client.py#L9209-L9242`：talking 片段头像可读性预检、TTS、数字人口播和场景 URL 分流。
- `backend/matrix_native_client.py#L10399-L10429`：全部片段媒体校验、保留音频合成、最终非静音检查和成片入资产库。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 同款替换远程素材边界

- `backend/matrix_native_client.py#L1180-L1305`：上传素材优先使用中心服返回的 `publicUrls`；配置 `UPLOAD_API_URL` / `UPLOAD_TOKEN` 时，图片、视频和音频素材先上传到独立公网素材服务并返回 LK888 可访问 URL。`img.yunlingai.net` 公网素材服务已支持 `mp3/wav/m4a/ogg/aac` 和对应音频 MIME。
- `backend/matrix_native_client.py#L1147-L1195`：同步图片生成返回图片字节和上游公网 URL，客户端超时默认 540 秒。
- `backend/matrix_native_client.py#L4615-L4639`：可灵数字人公网 URL / 本地关键帧分流；本地文件转 `data:image/...;base64,...` 后通过 JSON `params.image` 提交，音频必须为公网 URL。
- `backend/matrix_native_client.py#L7587-L7689`：公网 URL 检查、参考图大小上限、私网拒绝、关键帧轻量重试参数和旧中心素材限定路径内存转 data URL。
- `backend/matrix_native_client.py#L8649-L8717`：非口播公网素材门禁和口播片段在 TTS 前的头像可读性预检。
- `backend/matrix_native_client.py#L9391-L9500`：关键帧参考图临时构建、旧任务迁移、502/504 轻量重试、公网关键帧 URL 保留和本地库 URL 分离。
- `backend/central_server.py#L1544-L1570`、`backend/central_server.py#L13652-L13693`：`PUBLIC_MEDIA_BASE_URL`、HMAC 签名、过期校验、素材 `publicUrls` 生成和签名公网素材文件读取；音频文件按后缀返回对应 `Content-Type`。
- `backend/central_server.py#L13418-L13480`：`/api/public-media/<material>/<file>` 签名访问、Range 支持和素材归属校验。
- `backend/central_server.py#L763-L798`：不复制文件体的 multipart 非文件字段解析，保留 `model` / `mode` 计费契约。
- `backend/central_server.py#L801-L938`：LK888 反代计费、multipart 适配和同步图片 480 秒上游超时。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## FaceFusion 本地开发环境

- `/Users/mac/facefusion-standard/run-facefusion#L1-L84`：官方 FaceFusion `3.7.1` 兼容启动器；使用参数数组、结构化警告和 dry-run，将开发测试限定为单人最大脸选择。
- `backend/.env.dev#L1-L15`：`hybrid_v2` 开发开关、法律版本、参考图/超时上限、FaceFusion 独立虚拟环境路径、CoreML/CPU Provider 和 `DEV-ONLY` 许可标识。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 其他历史回归

- `backend/matrix_native_client.py#L135-L174`：退出登录的 Qt 独立进程启动、成功/失败结构化日志和 `errorId`。
- `backend/matrix_native_client.py#L368-L373`：客户端启动环境初始化在清理临时目录后调用 `recover_stale_video_replacement_jobs()`，恢复重启遗留的同款替换 `running` 任务状态。
- `backend/matrix_native_client.py#L13792-L13819`：清理会话后重启，仅在新客户端启动成功时退出旧窗口，失败时保留窗口并显示错误编号。
- `backend/matrix_native_client.py#L10060-L10158`：视频首帧缩略图和无居中播放图标的播放器海报。
- `backend/matrix_native_client.py#L10940-L11260`：资产库视频卡片和播放入口。
- `backend/matrix_native_client.py#L12317-L12332`：内容生产导航中的分解视频、同款替换、Agent.模式和资产库。
- `backend/matrix_native_client.py#L21462-L21642`：登录页背景视频固定四项轮播、单次播放切换和背景绘制。
- `backend/matrix_native_client.py#L21788-L22071`、`backend/matrix_native_client.py#L22095-L22545`：登录页左侧品牌/卖点文案与右侧玻璃登录卡作为完整内容组居中排放，保留手机号/用户名登录、验证码、用户名免验证码和法律同意提交流程。
- `backend/matrix_native_client.py#L22546-L22557`：登录成功后不再播放 `evil_eye_login.png` 全屏放大过场，改为释放背景视频管线与图像缓存后直接进入主界面。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 登录协议与同意审计

- `backend/matrix_native_client.py#L63-L89`：内置协议读取、版本化同意 payload 和自动登录版本门禁。
- `backend/matrix_native_client.py#L12731-L12777`：可滚动《用户协议》/《隐私政策》双标签弹窗。
- 历史 Web 登录实现已在 `2026-07-27 Web 交付面移除` 中退役；当前登录协议和同意审计只保留原生客户端与中心服契约。
- `backend/legal/user_agreement.md#L1-L85`：用户协议 v1.0，包含 `1 云豆 = 1 元`、AI/换脸/平台授权和争议解决条款。
- `backend/legal/privacy_policy.md#L1-L103`：隐私政策 v1.0，包含人脸、声音、Cookie、第三方 AI、保留期和用户权利。
- `backend/central_server.py#L2477-L2542`：同意 Schema 校验、HTTP 428 契约、服务端时间和 `legal.consent.accept` 审计。
- `backend/central_server.py#L14194-L14394`：登录、手机验证码登录、注册和会话刷新的法律版本强制门禁。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 测试

- `tests/test_client_logout.py#L18-L52`：Qt 独立重启成功契约和失败 `errorId` 回归。
- `tests/test_douyin_multi_account.py#L15-L90`：多个抖音账号并存、profile 不覆盖、发布按账号切换 Cookie/profile。
- `tests/test_legal_agreements.py#L1-L102`：主体/计费正文、同意 payload、过期拒绝、中心审计、登录链接、Web 法律同意和本地静态页 API 基址契约。
- `tests/test_login_background_playlist.py#L10-L29`：登录页背景视频清单、首条顺序和单次播放轮播契约。
- `tests/test_login_centered_layout.py#L9-L47`：登录页完整内容组居中、左侧营销文案恢复，并防止布局调整恢复成功 evil-eye 过场。
- `tests/test_login_success_transition.py#L9-L41`：登录成功移除 evil-eye 过场素材、常量、遮罩和 Qt 动画组，成功路径直接释放背景资源后进入主界面，失败路径保持不变。
- `tests/test_video_replacement_v2.py#L197-L223`：关键帧同步图片 504 后使用 `1024x1024` 和更少参考图轻量重试。
- `tests/test_video_replacement_v2.py#L722-L790`：独立公网素材上传服务覆盖图片、视频和音频，确认配置 `UPLOAD_API_URL` / `UPLOAD_TOKEN` 时三类素材都不再回退中心素材库。
- `tests/test_video_replacement_v2.py#L301-L324`：本地数字人头像文件转 JSON `data:image/...;base64,...` 兜底提交，不再走 multipart。
- `tests/test_video_replacement_v2.py#L401-L440`：漂移防护默认生产安全、`VIDEO_REPLACE_DRIFT_GUARD=0` 可强制关闭，源视频上下文抽取汽车销售角色和产品类别。
- `tests/test_video_replacement_v2.py#L442-L525`：参考图预检对人物上下文 blocking 降级为 warning，对产品类别冲突返回 `reference_mismatch` 阻断；视觉服务失败时降级为后置质检并保留 `errorId`。
- `tests/test_video_replacement_v2.py#L503-L541`：替换 prompt 和非口播编辑 prompt 包含 Source lock、identity-only 规则和参考冲突时源视频优先规则。
- `tests/test_video_replacement_v2.py#L512-L560`：未上传人物图时不调用 FaceFusion，使用远程编辑结果直接音频回填并执行产品 QC。
- `tests/test_video_replacement_v2.py#L629-L696`：非口播高一致模式才执行 FaceFusion；标准模式即使上传人物图也跳过 FaceFusion。
- `tests/test_video_replacement_v2.py#L698-L735`：非口播高一致模式 FaceFusion 失败或超时会回退到远程视频，记录 `facefusion_failed` 和 `review_warning`。
- `tests/test_video_replacement_v2.py#L771-L898`：非口播严重漂移自动重试一次；高一致 FaceFusion 分支会用正确片段参数发送重试进度事件；第二次仍失败时写入 `visual_drift_retry_exhausted`、`blockedReason` 和失败状态。
- `tests/test_video_replacement_v2.py#L616-L654`：talking 片段关键帧 502/504 后记录 `keyframeErrorId` 并使用已有人物头像继续生成。
- `tests/test_video_replacement_v2.py#L895-L921`：纯产品模式视觉 QC 跳过人脸检查；未上传场景图时跳过场景 QC；原片源片段无产品时产品/Logo 标记为 `skipped_source_absent`。
- `tests/test_video_replacement_v2.py#L3115-L3137`：上传场景参考后如果生成结果没有采用上传场景，视觉 QC 返回 `scene_mismatch`，不再以源视频场景优先放行。
- `tests/test_video_replacement_v2.py#L797-L805`：源片段公网素材缺失错误在前台展示为中文，不暴露 `video_replace_remote_media_required`。
- `tests/test_video_replacement_v2.py#L210-L263`、`tests/test_video_replacement_v2.py#L1307-L1350`：同款替换默认不因转写台词触发数字人口播；显式开启 `VIDEO_REPLACE_ENABLE_AVATAR_SEGMENTS=1` 或任务级严格口播时才生成/兜底转为 talking 片段，严格口播片段不得走非口播回填原音频分支。
- `tests/test_video_replacement_v2.py#L1214-L1264`：严重主题漂移在快速、标准、高一致模式下都返回 `visual_drift_blocked`；普通人脸不一致保持 `review_warning`。
- `tests/test_video_replacement_v2.py#L1309-L1448`：视觉 QC 超时降级为人工审核，普通视觉不一致带 `review_warning` 分级；角色/结构不一致但主题保留时不触发硬漂移；显式严格 QC 环境变量可恢复阻断。
- `tests/test_video_replacement_v2.py#L806-L831`：同款替换进度文本包含已用时/预计剩余，并基于任务和片段时间估算剩余时长。
- `tests/test_video_replacement_v2.py#L1117-L1132`：FaceFusion 超时展示为“本地换脸增强超时，已回退远程同款结果”，不暴露原始 `facefusion_timeout`。
- `tests/test_video_replacement_v2.py#L1453-L1473`：片段状态文本展示漂移重试次数、阻断合成原因和 drift QC 原因；错误文案本地化 `reference_mismatch` 与视觉漂移错误码。
- `tests/test_video_replacement_v2.py#L1192-L1229`：标准 talking 片段跳过数字人口播 FaceFusion，高一致 talking 片段保留 FaceFusion 失败回退。
- `tests/test_video_replacement_v2.py#L1250-L1257`：片段状态文本包含人物一致性模式。
- `tests/test_video_replacement_v2.py#L1333-L1366`：同款替换页面包含快速/标准/高一致模式选择，开始生成前先派生 `identityMode` 和 `enableFaceFusion`，纯产品模式强制关闭 FaceFusion。
- `tests/test_video_replacement_v2.py#L1831-L1947`：覆盖上游余额不足预检阻断、账单/配置类错误中文化、任务诊断摘要统计失败片段、`start_generation()` 上传前预检的执行路径，以及历史异常 `diagnostics` 的弹窗兼容。
- `tests/test_video_replacement_v2.py#L2151-L2201`：同款替换页面场景图为可选，真人模式不再有场景图硬门禁；非口播编辑 prompt 保留场景图为参考素材，但只在不冲突时使用。
- `tests/test_video_replacement_v2.py#L78-L108`：Windows 测试环境下 PySide6 不可用时安装轻量 Qt stub，使同款替换 helper 测试不依赖真实 Qt runtime。
- `tests/test_video_replacement_v2.py#L1358-L1465`：覆盖残留 `running` 任务启动恢复、无成功片段任务失败归档、旧误阻断重试清理和硬漂移历史保留。
- `tests/test_video_replacement_v2.py#L891-L909`：同款替换页面展示进度详情标签、耗时/预计列和进度文本 helper。
- `tests/test_api_download_contract.py#L608-L642`：公网素材签名 URL、HTTPS 基址、TTL 和过期拒绝契约。
- `tests/test_video_replacement.py#L24-L244`：稳定 V1 分段、参考图模型、公网关键帧 URL 保留、失败重试、合成校验和资产入库回归。
- `tests/test_video_breakdown.py#L30-L964`：报告、预检、OCR、转写、重试、临时清理和串行约束。
- `tests/test_digital_human_navigation.py#L81-L140`：分解结果生成数字人口播 seed、数字人口播页接收 seed 后只填表、不自动生成媒体、上传人物图后生成时优先传公网头像 URL，以及 Gemini TTS 失败降级 doubao 的回归。
- `tests/test_video_transcription.py#L67-L509`：分片、Schema、远程重试、拒绝识别和失败区间定向重试。
- `tests/test_authenticated_download.py#L68-L395`：浏览器请求头、Cookie、403、并发 `.part` 和原文件保护。
- `tests/test_douyin_multi_account.py#L94-L101`：只有 `msToken` 的抖音缓存必须被 `require_auth()` 拒绝，防止下载/分解链路暴露底层 `'s_v_web_id'` KeyError。
- `tests/test_video_breakdown.py#L68-L76`：客户端分解下载鉴权错误本地化，确保状态栏提示重新登录抖音。
- `tests/test_media_validation.py#L44-L309`：错误页、截断视频、全量解码、隔离和过期清理。
- `tests/test_material_repair.py#L75-L1104`：本地/中心素材保留 ID 修复、图片拒绝和事务回滚。
- `tests/test_structured_log.py#L39-L296`：签名 URL、Bearer、API Key、Token 和堆栈脱敏。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-20 生产验证与契约补强

- `backend/matrix_native_client.py#L6567-L6604`：同款替换进度反馈兼容轻量测试 UI，缺少按钮、进度条或详情标签时不再抛异常。
- `backend/matrix_native_client.py#L9818-L9865`：同款替换音频 QC 调用 ffmpeg 时显式使用 UTF-8 replacement 解码，避免 Windows GBK 环境误失败。
- `backend/matrix_native_client.py#L10273-L10397`：非口播片段输出路径按任务 `outDir` 风格生成，保留 POSIX 风格路径以兼容既有任务 JSON 和测试。
- `backend/matrix_native_client.py#L10892-L10900`：视频探测调用 ffprobe 时显式使用 UTF-8 replacement 解码。
- `backend/utils/media_validation.py#L47-L73`：媒体探测调用 ffprobe 时显式使用 UTF-8 replacement 解码。
- `tests/test_video_replacement_v2.py#L173-L181`：音量检测测试辅助函数同步 Windows 解码策略。
- `tests/test_deployment_security.py#L21-L129`：覆盖 `.gitignore` 敏感目录忽略、生产 Dockerfile healthcheck 和 `docker-compose.prod.yml` 中心服务契约。
- `tests/test_openapi_contract.py#L9-L31`：锁定余额、账务流水、本地浏览器、中心节点和企业任务中心的 OpenAPI 覆盖。
- `docs/openapi.yaml#L275-L471`：新增 6 个生产观测/运营接口契约。
- `docs/openapi.yaml#L526-L633`：新增 `AccountBalance`、`BillingLedger`、`LocalBrowserStatus`、`LocalBrowserTaskCreateRequest`、`LocalBrowserTask`、`CentralNodes`、`EnterpriseTaskCenter` Schema。
- `backend/Dockerfile#L1-L28`：中心服务生产镜像、默认监听配置和 `/api/health` healthcheck。
- `docker-compose.prod.yml#L1-L24`：生产中心服务 compose、命名数据卷、`.env.prod` 加载和健康检查。
- `start-local-test.ps1#L1-L27`：Windows 本地启动脚本固定使用项目 `.venv-win\Scripts\python.exe`，并校验 Python 3.12 后再启动中心服。
- `backend/.env.prod#L1-L32`：Docker compose 本地生产冒烟占位配置；真实密钥必须由受控环境注入，不提交到仓库。
- `docs/DEPLOYMENT.md#L226-L260`：Windows 10 Hyper-V 后端 Docker 冒烟流程、Docker Hub 镜像源兜底和回滚边界。
- `docs/TROUBLESHOOTING.md#L35-L41`：Windows Docker/WSL 生产冒烟故障、根因、修复、验证和回滚记录。
## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-20 Windows 本地数据目录迁移

- `backend/runtime_paths.py#L46-L97`：统一解析本地客户端数据目录；Windows 源码部署默认 `backend/datas`，支持 `MATRIX_AGENT_DATA_DIR` / `DY_DATA_DIR` 覆盖、`MATRIX_AGENT_USE_APPDATA=1` 回滚和旧 AppData 非破坏性复制。
- `backend/matrix_native_client.py#L92-L99`：客户端 `data_dir()` / `logs_dir()` 改为统一路径助手，日志进入 `backend/datas/logs`。
- `backend/matrix_native_client.py#L1015-L1023`、`backend/matrix_native_client.py#L1833-L1835`、`backend/matrix_native_client.py#L2616-L2616`、`backend/matrix_native_client.py#L4126-L4128`、`backend/matrix_native_client.py#L6705-L6848`、`backend/matrix_native_client.py#L8149-L8568`、`backend/matrix_native_client.py#L13702-L13705`：LK888 本地配置、主题、Hero 视频、私信会话、工作流、商品生成、资产库、品牌/风控配置和登录偏好均跟随 `data_dir()`。
- `backend/api_server.py#L58-L64`、`backend/api_server.py#L127-L149`：本地 API 引擎数据根目录跟随统一路径，素材、账号 profile、队列和 cookie cache 默认进入 `backend/datas`。
- `backend/agent_launcher.py#L20-L30`、`backend/local_browser_worker.py#L75-L76`、`backend/utils/common_util.py#L57-L67`、`backend/utils/cookie_util.py#L40-L46`：启动器、worker、下载目录和抖音 profile 默认路径统一。
- `backend/start-matrix-agent.bat#L3-L7`、`start-local-test.ps1#L9-L35`：Windows 启动脚本显式设置 `MATRIX_AGENT_DATA_DIR`、`DY_DATA_DIR` 和 `DY_PROFILE_DIR` 到项目数据目录。
- `tests/test_agent_mode_defaults.py#L22-L67`：覆盖 Windows 默认路径、环境变量覆盖和启动脚本契约，防止回退到 `%APPDATA%\MatrixShipAgent\data`。
## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-22 单主角整身替换收尾修复
- `backend/matrix_native_client.py#L1467-L1514`：主角模式尊重纯产品模式；回滚总开关关闭时清除残留的主角自定义模型，恢复旧参考图候选链。
- `backend/matrix_native_client.py#L10436-L10494`：同款替换页删除固定 `144x180` 主角缩略图和原片主角确认下拉框；低置信度候选由客户端自动使用第一张候选帧；产品图文案明确主角整身替换可选。
- `backend/matrix_native_client.py#L6704-L6716`、`#L11534-L11564`：主角模式不强制产品参考图；没有产品图时仍运行主角视觉 QC，并按实际提供的源片段/人物/场景媒体动态描述媒体顺序。
- `backend/matrix_native_client.py#L11038-L11080`、`#L11812-L11818`：HappyHorse 结果统一用源片段音轨原子回填，保留原音频并在回填后执行媒体校验。
- `tests/test_video_replacement_v2.py#L252-L266`、`#L1025-L1042`、`#L1193-L1241`、`#L1955-L1985`、`#L3440-L3489`、`#L3677-L3745`：覆盖真实 ffmpeg 音轨回填、纯产品/回滚边界、无产品 QC、媒体索引、主角无产品启动、预览控件和低置信度人工确认。
- 回滚：设置 `VIDEO_REPLACE_PRINCIPAL_REPLACEMENT=0` 并只重启本地客户端；本次不改 `central_server.py`、`api_server.py`、中心服接口或数据库迁移。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 同款替换短尾片段合并
- `backend/matrix_native_client.py#L9791-L9833`：`_build_replacement_segments()` 在按约 8 秒切段后，若最后一段短于 3 秒，会并入上一段，避免 `happyhorse-video-edit` 拒绝过短参考视频。
- `backend/matrix_native_client.py#L7184-L7210`：点击“重试失败片段”前先执行短尾段规范化，旧任务中已保存的最后失败短段会合并到上一段后再重跑。
- `backend/matrix_native_client.py#L11007-L11078`：新增 `_replacement_segment_duration()` 与 `_normalize_replacement_retry_segments()`，合并时清空上一段旧成片路径，把短尾段失败快照写入 `retryHistory`，并在 `lastRetryPreparation.normalization` 保留可追溯记录。
- `tests/test_video_replacement_v2.py#L376-L384`、`tests/test_video_replacement_v2.py#L3105-L3134`：覆盖新建方案短尾合并和旧任务短尾重试合并。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。回滚后 3 秒以下最后片段会再次直接提交给上游并失败。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 数字人口播参考图字段兼容
- `backend/matrix_native_client.py#L1183-L1237`：`lk888_image_result()` 在存在参考图时不再只发送 `image_urls`；当全部参考图都是公网直链时，同步写入 `images`、`reference_images`、`referenceImages` 和 `params.images/params.image_urls/params.reference_images`。若包含本地 `data:image`，只保留 `image_urls`，避免 LK888 的 `images` 字段校验 400。
- `backend/matrix_native_client.py#L4887-L4940`：数字人口播场景版人物图合成继续把人物图和场景图作为两张参考图传入图片生成；场景参考改用已上传的公网 URL，底层兼容字段保证 LK888 图片接口不会退化成纯文生图，也不会把 data URL 放入公网直链字段。
- `tests/test_video_replacement_v2.py#L647-L674`：新增回归测试，模拟 LK888 图片接口并断言数字人口播合成请求同时携带人物图和场景图的多个兼容参考字段。
- `tests/test_video_replacement_v2.py#L676-L704`、`#L927-L948`：覆盖 `images/reference_images/params.images` 不接收 data URL，以及数字人口播场景合成使用公网场景 URL。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。回滚后若 LK888 不识别单一 `image_urls` 字段，人物和场景可能再次完全跑偏。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-23 数字人口播安全策略低风险重试
- `backend/matrix_native_client.py#L4842-L4884`：新增 `_is_digital_human_scene_image_policy_error()` 和 `_digital_human_scene_avatar_prompt()`，将内容安全、策略阻止、policy/safety/moderation 等错误从超时类错误中分离，并提供更中性的合成提示词。
- `backend/matrix_native_client.py#L4903-L4940`：场景版人物图合成首次被内容安全策略拦截时，记录 `digital_human_scene_avatar_policy_retry`，使用低风险提示词和 `1024x1024` 重试一次；二次仍拦截时抛出 `digital_human_scene_avatar_policy_blocked`。
- `backend/matrix_native_client.py#L5128-L5135`：页面错误提示区分安全策略拦截和图片生成超时，连续拦截时提示用户更换更中性的参考图或简化场景。
- `tests/test_video_replacement_v2.py#L848-L896`：覆盖安全策略拦截会低风险重试，且最终失败时不会误显示为超时。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。回滚后 LK888 安全拦截会继续直接失败或被误判为其他图片生成错误。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 内容采集指标列
- `backend/matrix_native_client.py#L3481-L3532`：新增内容采集搜索结果行格式化 helper，兼容 `digg_count/diggCount/like_count`、`share_count/shareCount/repost_count` 和 `duration/videoDuration` 等字段；视频时长统一显示为中文时长，缺失时显示 `-`。
- `backend/matrix_native_client.py#L3561-L3562`、`backend/matrix_native_client.py#L3678-L3679`：内容采集表格由 3 列扩为 6 列，在“链接”后新增“点赞数 / 转发数 / 视频时长”，搜索结果逐列填充。
- `backend/api_server.py#L1134-L1152`、`backend/utils/data_util.py#L118-L162`：抖音搜索结果标准化补充 `duration` 字段，兼容秒和毫秒来源。
- `tests/test_video_replacement_v2.py#L282-L308`：覆盖内容采集搜索结果表在链接后展示点赞数、转发数和格式化视频时长。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/api_server.py`、`backend/utils/data_util.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。本次按用户要求不自动重启本地客户端。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 同款替换单段瑕疵重生与字幕预检
- `backend/matrix_native_client.py#L6112-L6162`：新增字幕文本预检 helper，识别 OCR/转写乱码、可疑词和未人工确认口播稿，并生成确认提示。
- `backend/matrix_native_client.py#L6573-L6589`、`backend/matrix_native_client.py#L7463-L7508`、`backend/matrix_native_client.py#L7686-L7687`：同款替换页面新增“重生选中片段”入口，选中片段后填写上一版瑕疵，只重生该段并同步按钮状态。
- `backend/matrix_native_client.py#L7162-L7173`：开始生成前执行字幕预检；用户确认后为片段写入 `scriptReviewed=true`，否则返回片段表修改口播稿。
- `backend/matrix_native_client.py#L10465-L10477`、`backend/matrix_native_client.py#L10813-L10813`、`backend/matrix_native_client.py#L10923-L10923`、`backend/matrix_native_client.py#L11378-L11416`：手动瑕疵说明进入下一次主角/普通远程编辑提示词；重生前保留 `retryHistory` 快照并清空旧视频路径、旧错误和旧 QC 状态。
- `backend/matrix_native_client.py#L13658-L13700`：最终 ASS 字幕烧录优先查找 `VIDEO_REPLACE_SUBTITLE_FONT_FILE` 或 Windows 中文字体目录，并在 ffmpeg subtitles filter 中传入 `fontsdir`。
- `tests/test_video_replacement_v2.py#L3428-L3498`：覆盖手动瑕疵重生提示词、字幕预检和固定字体目录烧录。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/DEPLOYMENT.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。代码改动需要重启本地客户端后进入运行进程。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 同款替换任务级模型切换
- `backend/matrix_native_client.py#L1478-L1599`：新增同款替换模型筛选 helper，白名单保留 `happyhorse-video-edit`、`kwvideo-v2-quannengcankao` 和参考视频模型；`kwvideo-v2-quannengcankao` 是 LK888 页面“SD 2.0 全能参考”的实际模型标识，页面卡片 ID 76 仅用于云灵页面内部选择，并只作为内置可选模型，不抢占未选择时的 Vidu/Wan 自动兜底顺序。
- `backend/matrix_native_client.py#L1626-L1642`、`backend/matrix_native_client.py#L10844-L10852`、`backend/matrix_native_client.py#L11078-L11105`、`backend/matrix_native_client.py#L12864-L12926`：主角源视频编辑候选读取任务级 `model`，所选模型会进入远程请求和片段实际模型记录；分辨率按模型适配，`happyhorse-*` 使用 `720P/1080P`，`kwvideo-v2-quannengcankao` 等非 happyhorse 模型保持 `720p/1080p`，避免 LK888 对 `resolution=720P` 返回 400。
- `backend/matrix_native_client.py#L6651-L6673`、`backend/matrix_native_client.py#L6813-L6894`、`backend/matrix_native_client.py#L7125-L7183`、`backend/matrix_native_client.py#L7251-L7308`：同款替换页新增“同款替换模型”下拉框，先显示内置适配模型，后台刷新 LK888 目录后补充 SD 2.0 全能参考等备选模型。
- `backend/matrix_native_client.py#L7113-L7183`、`backend/matrix_native_client.py#L7251-L7308`、`backend/matrix_native_client.py#L7685-L7685`：生成方案和正式生成都把页面选择写入任务 JSON 的 `model`，后续单段重生继续沿用同一任务模型。
- `tests/test_video_replacement_v2.py#L1186-L1256`、`tests/test_video_replacement_v2.py#L1328-L1328`、`tests/test_video_replacement_v2.py#L1351-L1416`、`tests/test_video_replacement_v2.py#L4167-L4192`：覆盖 SD 2.0 全能参考动态识别、真实模型标识内置、主角链路使用任务模型、按模型适配分辨率大小写和 `_build_job()` 保存所选模型。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/ARCHITECTURE.md`、`docs/API_REFERENCE.md`、`docs/DEPLOYMENT.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。代码改动需要重启本地客户端后进入运行进程。
## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 Web 左侧栏登录入口放行
- 历史记录：该 Web 左侧栏登录入口已随 `2026-07-27 Web 交付面移除` 退役；当前登录入口位于原生客户端，`tests/test_web_login_navigation.py` 已删除。
- 回滚：如需恢复历史 Web 入口，必须先校验 `backups/web-removal-20260727/archive.sha256`，再整体回滚 Web 移除提交；不要只恢复单个 `frontend` 文件。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 同款替换片段删除与滚轮滚动修复
- `backend/matrix_native_client.py#L6739-L6740`：片段表垂直滚动条显式设置 `singleStep=24`、`pageStep=122`，配合像素滚动模式，避免滚轮滑动表现得像整页跳转。
- `backend/matrix_native_client.py#L7784-L7785`：删除片段前先调用 `_sync_segment_scripts_from_table()`，把当前表格里尚未刷新到任务 JSON 的口播稿写回内存任务。
- `backend/matrix_native_client.py#L7851-L7912`：口播稿多行编辑器实时同步 `segment.script`，并在变更时把 `scriptReviewed` 置为 `false`，避免刷新表格后恢复旧文案。
- `tests/test_video_replacement_v2.py#L409-L426`：锁定片段表像素滚动、小步滚动、口播稿编辑器和删除前同步契约。
- `tests/test_video_replacement_v2.py#L3900-L3922`：覆盖删除第 2 段后，第 1 段和第 3 段已编辑口播稿仍保留。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。代码改动只需重启本地客户端后生效。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 同款替换删除后压紧时间轴与成功后清理远程错误
- `backend/matrix_native_client.py#L6902-L6929`：删除待生成片段后，按剩余片段的 `duration` 重新计算 `start/end`，保证时间轴从 0 秒起连续压紧。
- `backend/matrix_native_client.py#L13459-L13471`、`backend/matrix_native_client.py#L6888-L6913`：远程候选模型先失败、后续候选成功时，成功片段清空当前 `remoteError/remoteErrorId`；状态栏只在当前片段仍有错误时展示远程 fallback 失败，避免“视频已生成但还显示错误”。
- `tests/test_video_replacement_v2.py#L2419-L2455`、`tests/test_video_replacement_v2.py#L2460-L2477`、`tests/test_video_replacement_v2.py#L3885-L3899`：覆盖远程候选 fallback 记录、成功后隐藏旧远程错误、以及删除片段后时间轴压紧。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本文档即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。代码改动需要重启本地客户端后生效。




## 2026-07-25 余额实时刷新与 LK888 中文失败状态退款
- `backend/matrix_native_client.py#L21159-L21171`：登录成功后启动 `_start_balance_timer()`，每 30 秒调用 `refresh_balance()` 从中心服重新读取余额；`backend/matrix_native_client.py#L21203-L21206` 在退出登录时停止该定时器，避免登出后继续刷新旧会话。
- `backend/central_server.py#L739-L763`：新增 `lk888_proxy_task_flags()`，统一解析 LK888 task-status 的失败/完成状态，补充中文状态 `错误`、`失败`、`超时`、`已取消`、`取消`，并继续用真实媒体 URL 判断完成。
- `backend/central_server.py#L1002-L1016`：LK888 反代轮询到任务状态后调用 `lk888_proxy_task_flags()`；失败时按原 `ref` 调用 `refund_user_by_ref()` 幂等退款，退款成功后移除 `STATE['gen_charges'][task_id]`。
- `tests/test_role_permissions.py#L231-L238`、`tests/test_billing_unified.py#L165-L169`：新增余额刷新定时器源码契约测试和 LK888 中文失败状态退款判断回归测试。先运行新增测试观察旧实现失败，再实现后转绿。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及 OpenAPI、数据库结构或 `migration.sql`。运行中中心服需要重启后加载代码变更。

## 2026-07-25 中心状态文件防默认骨架覆盖保护
- `backend/central_server.py#L177-L193`：新增 `StateLoadError`、`StateWriteProtectionError` 和 `CENTRAL_ALLOW_STATE_REINIT` 显式重置开关。默认情况下，已有状态文件读失败不允许回落到默认企业/默认用户。
- `backend/central_server.py#L231-L247`：`_load_json()` 改为 `utf-8-sig` 读取，可兼容 UTF-8 BOM；若 `scheduler_state.json` 存在但解析失败，会记录 `STATE_LOAD_ERROR` 并抛出 `StateLoadError` 阻断启动。
- `backend/central_server.py#L250-L272`：`_state_write_guard()` 在写入前检查现有状态；当现有企业/用户/成员关系明显多于 1 条时，拒绝把 `org-default/user-owner` 的默认骨架写回覆盖。
- `backend/central_server.py#L284-L357`：新增 `backup_state_file_on_startup()`，中心服初始化 `STATE` 前先复制 `scheduler_state.json.bak-startup-*`，保证启动级可回滚。
- `tools/repair_scheduler_state.py#L1-L85`：新增状态修复工具，支持只读校验、`--normalize` 无 BOM 重写、`--restore <backup>` 验证后恢复，并在写入前自动备份当前文件。
- `tests/test_billing_unified.py#L167-L218`：覆盖启动前备份、UTF-8 BOM 读取、坏 JSON 阻断启动、完整状态禁止被默认骨架覆盖。
- 回滚：回滚 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `docs/DEPLOYMENT.md` 即可；不涉及 OpenAPI、数据库结构或 `migration.sql`。回滚后坏状态文件可能再次被默认骨架覆盖。

## 2026-07-25 小红书图文同款

- `backend/xhs_note_replacement.py#L9-L20`：功能开关、任务 ID 与本地任务目录。
- `backend/xhs_note_replacement.py#L53-L87`：从小红书素材或 `sourceNote` 构建图文结构模板。
- `backend/xhs_note_replacement.py#L134-L154`：按用户替换图生成槽位映射，缺图槽位仅标记为待补齐占位（内部字段仍为 `source=ai_placeholder`），不触发图片生成。
- `backend/xhs_note_replacement.py#L167-L188`：本地 JSON 任务原子保存与读取。
- `backend/xhs_note_replacement.py#L192-L223`：生成 `image_note` 草稿素材 payload 和 AI 图片审核元数据。
- `backend/xhs_note_replacement.py#L225-L231`：小红书图文 V1 发布阻断错误码。
- `backend/xhs_note_replacement.py#L234-L286`：4 图图文同款无副作用冒烟 helper。
- `backend/api_server.py#L4789-L4927`：本地 `/api/xhs-note-replacement/*` 模板、预览、确认和保存草稿接口。
- `backend/central_server.py#L5747-L5750`：中心服发布预检复用 `image_note` blocker。
- `backend/matrix_native_client.py#L4129-L4176`：从小红书下载任务结果中提取素材文件；字典或纯 URL 结果统一拆为不含查询凭据的 `files` 与按索引对齐的 `urls`，避免签名 token 进入模板任务，同时保留可加载地址。
- `backend/matrix_native_client.py#L4179-L4322`：解析本机图片、中心素材 URL 和仅带签名 URL 的图片；过滤视频等非图片文件，中心素材请求才携带登录头，外部 CDN 不外发登录凭据；模板阶段即可生成槽位行。
- `backend/matrix_native_client.py#L4203-L4230`：远程响应按 64 KB 分块读取并在累计超过 20 MB 时立即终止；图片请求最多 4 路并发。
- `backend/matrix_native_client.py#L4365-L4524`：内容采集页“图文同款”按钮校验单条小红书链接，复用下载任务，下载完成后提取图片素材、切换页面并发送 `xhs_note_replace_start`；无图片时提示先下载笔记。
- `backend/matrix_native_client.py#L7479-L8019`：原生“图文同款”独立页面接收采集事件，立即显示全部原图缩略图和图片数量，支持点击查看大图，并自动读取结构；新任务清理旧笔记、替换图、槽位和文案状态。
- `backend/matrix_native_client.py#L7654-L7715`：远程原图在后台流式加载；失败记录脱敏结构化日志 `xhs_note_source_image_load_failed`，旧任务图片响应由 generation 标识丢弃。
- `backend/matrix_native_client.py#L7927-L8059`：读取结构、生成预览和保存草稿均固定捕获发起时的任务 ID 与 generation；切换笔记后旧响应不再覆盖新任务，读取结构仍包含 30 秒超时和明确缺图提示，生成预览前会要求手动补齐全部替换图。
- `backend/matrix_native_client.py#L11365-L11365`：资产库允许 `note_template` 类型。
- `backend/matrix_native_client.py#L18016-L18038`：资产库保留 `note_template` 类型兼容；当前筛选入口不展示“图文模板”。
- `backend/matrix_native_client.py#L19406-L19406`：原生导航新增“🧩 图文同款”。
- 历史 Web 图文同款入口已随 `2026-07-27 Web 交付面移除` 退役；当前入口只保留原生客户端“内容生产 -> 图文同款”和后端接口。
- `tests/test_xhs_note_replacement.py#L385-L397`：4 图图文同款冒烟测试。
- 历史 Web 图文同款测试已移除；现有覆盖集中在后端契约和原生客户端跳转。
- `tests/test_xhs_note_replacement.py#L399-L413`：覆盖原生采集页一键图文同款、读取结构超时、下载完成跳转和“未找到图片素材，请先下载笔记”提示。
- `tests/test_xhs_note_replacement.py#L415-L927`：覆盖真实内容采集导航交接、下载字典与签名 URL 规范化、流式大小限制、本机/中心缩略图、外部凭据隔离、点击大图、模板槽位即时显示、AI 缺图入口移除、旧动作响应失效和保存任务 ID 固定捕获。

验证：`.venv-win\Scripts\python.exe -m unittest tests.test_api_download_contract tests.test_material_repair tests.test_native_publish tests.test_xhs_note_replacement -v` 通过 99 项；`.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_xhs_note_replacement.py` 退出码 0。

回滚：恢复 `backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和实施计划中的 Task 8 记录并重启桌面客户端；不涉及数据库、中心服接口、OpenAPI 或 `migration.sql`。
## 2026-07-28 小红书创作服务平台刷新循环
- `backend/platform_adapters.py#L231-L252`：`_wait_for_xhs_creator_login()` 等待登录时只轮询上传入口和当前 URL，不再读取 `XHS_STRONG_LOGIN_COOKIES` 后在循环内反复 `page.goto(creator_url)`，避免残留 cookie 触发“发布页/登录页”来回刷新。
- `backend/platform_adapters.py#L1766-L1777`：`xhs_publish_material()` 在登录等待成功后，如果当前页还没有上传入口，最多再进入一次创作者发布页；若仍回到登录页，返回 `xhs_creator_login_required` 和 `final_url`。
- `tests/test_native_publish.py#L154-L178`：新增回归测试锁定等待登录函数不能从 cookie 触发页面刷新，同时保留可见登录等待、超时和发布错误提示覆盖。
- 验证：先运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v` 观察旧实现 1 项失败；修复后同命令 26/26 通过。后续编译验证见最终回复。
- 回滚：回滚 `backend/platform_adapters.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本条实现索引即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-28 侧边栏底部余额与图标按钮防重叠
- `backend/matrix_native_client.py#L2259-L2292`：为 `QPushButton#iconbtn` 单独覆盖全局按钮样式，固定 `26px × 26px`、`padding:0`、`min/max-width:26px`，避免继承普通按钮 `min-width:76px` 后在左下角变成长按钮。
- `backend/matrix_native_client.py#L23136-L23152`：余额标签限制最大宽度为 `92px` 并以伸缩项加入底部控制行；主题按钮和退出按钮改为 `26px × 26px`，退出图标同步缩到 `14px`。
- `tests/test_role_permissions.py#L219-L235`：扩展侧边栏控件宽度契约测试，锁定 `iconbtn` 短按钮样式、余额宽度上限和两个底部图标按钮固定尺寸。
- 验证：先运行 `.venv-win\Scripts\python.exe -m unittest tests.test_role_permissions.RolePermissionsTest.test_client_team_member_and_sidebar_controls_have_stable_widths -v` 观察旧实现因缺少 `iconbtn` 宽度覆盖失败；修复后同命令通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及后端接口、数据库结构、OpenAPI 或 `migration.sql`。回滚后长余额文本仍可能挤压底部按钮。

## 2026-07-28 账号矩阵发布统计监控
- `backend/central_server.py#L311-L402`：新增 `publishRuntime` 运行态归档结构，中心服启动时从 `scheduler_state.json` 恢复当天发布计数；跨天时自动清空当天计数，避免昨日数据混入今日发布。
- `backend/central_server.py#L5852-L5898`：发布成功调用 `record_publish_success()` 后同步写入 `STATE["publishRuntime"]` 并持久化；账号列表通过 `account_asset_with_metrics()` 回填 `todayPublish`、`publishedToday`、`todayPublishDay` 和 `todayPublishUpdatedAt`。
- `backend/central_server.py#L6840-L6868`：`/api/accounts` 按角色过滤后统一返回带统计字段的账号；管理员/企业家仍看范围内账号，普通用户仍只看自己的账号。
- `backend/matrix_native_client.py#L825-L848`、`backend/matrix_native_client.py#L3970-L3971`：账号矩阵汇总总粉丝量和今日发布时使用 `_account_metric_number()`，兼容空值、纯数字、`1.2万`、`3k` 等格式，避免非纯数字导致页面刷新异常。
- `tests/test_account_matrix_metrics.py#L31-L105`：新增账号矩阵统计回归测试，覆盖今日发布从发布运行态回填、重启后恢复计数、客户端数字单位解析。
- 验证：先运行 `.venv-win\Scripts\python.exe -m unittest tests.test_account_matrix_metrics -v` 观察旧实现因缺少 `todayPublish` 和 `_account_metric_number()` 失败；实现后同命令 3/3 通过。
- 回滚：回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_account_matrix_metrics.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库结构、OpenAPI 新接口或 `migration.sql`。回滚后账号矩阵“今日发布”会恢复为仅展示账号对象自带字段。
## 2026-07-28 workflow account-scope reload
- `backend/matrix_native_client.py#L10972-L10994`: `load_workflows()` now reads `workflows.json` from the current `data_dir()` and clears in-memory `WORKFLOWS` when the file is missing or malformed, so one account cannot inherit another account's workflow list.
- `backend/matrix_native_client.py#L10996-L11002`: added `reload_account_scoped_state()` to reload workflows, pending queue, assets, brand profile, and risk config through one account-scoped entry point.
- `backend/matrix_native_client.py#L11708-L11716`: the automation workflow page reloads `workflows.json` before rendering the list on initial build, page show, and manual refresh.
- `backend/matrix_native_client.py#L22654-L22660`: after login, `apply_account_scope(acc)` runs before `reload_account_scoped_state()`, so admin mapped to `backend/datas/accounts/user-owner/` can see that directory's `workflows.json`.
- `backend/matrix_native_client.py#L22897-L22897`: startup uses the same `reload_account_scoped_state()` loader to avoid duplicated state-loading paths.
- `tests/test_workflow_account_scope.py#L42-L65`: regression tests lock login reload ordering, workflow page reload-before-render behavior, refresh routing, and the state loader contents.
- `tests/test_workflow_resilience.py#L14-L14`: source-reading test helper uses `utf-8-sig` so BOM in `matrix_native_client.py` does not block workflow regression tests.
- Verification: old implementation failed `py -3 -m unittest tests.test_workflow_account_scope -v`; after the fix, `tests.test_workflow_account_scope` passed 4/4, `tests.test_workflow_resilience` passed 2/2, and `py -3 -m py_compile backend\matrix_native_client.py tests\test_workflow_account_scope.py tests\test_workflow_resilience.py` exited 0.
- Rollback: revert `backend/matrix_native_client.py`, `tests/test_workflow_account_scope.py`, `tests/test_workflow_resilience.py`, and this troubleshooting/implementation note. No OpenAPI, database migration, Docker, or central-server change is involved.

## 2026-07-28 抖音私信全自动回复 MVP

- `backend/local_browser_worker.py#L48-L48`：本地浏览器执行器新增 `douyin.dm.inbox -> /api/douyin/dm/inbox` 映射，并通过现有 `CAPABILITIES` 对中心服声明能力。
- `backend/central_server.py#L740-L747`：中心服审计对 `douyin.dm.inbox` payload 做专门脱敏，只记录 `targetFingerprint`、`limit` 和 `sinceFingerprint`；`backend/central_server.py#L751-L781` 对中心任务结果做持久化脱敏，不保存 `target` 原文和 `messages[].text` 原文；`backend/central_server.py#L13043-L13043` 将任务类型映射到本地收件箱接口；`backend/central_server.py#L13541-L13559` 在任务结果写入时使用脱敏结果。
- `backend/api_server.py#L1644-L1672`：新增私信消息归一化，固定输出 `fingerprint/direction/kind/text/createdAtText`，非文本消息不返回正文；未知方向输出 `unknown`，客户端不自动处理；浏览器抽取会给同文本重复消息附加 `ordinal`，避免连续相同文本共用同一指纹；`backend/api_server.py#L1675-L1867` 使用隔离子进程和本机 Playwright 浏览器打开指定客户私信会话并读取最近消息；`backend/api_server.py#L1759-L1760` 将私信读取浏览器固定到 `dy_dm_profile/current` 资料目录，避免每 20 秒创建全新临时 profile；`backend/api_server.py#L3032-L3040` 提供 `run_douyin_dm_inbox()` 包装；`backend/api_server.py#L5548-L5560` 接通 POST `/api/douyin/dm/inbox`。
- 该历史实现已由本文件 2026-08-01 的 “Douyin automatic reply serial queue and manual handoff” 记录替代：当前轮询间隔仍为 20 秒，但纯文本按顺序逐条回复；非文本或明确转人工请求会关闭自动回复并提示人工接管。
- `tests/test_douyin_dm_auto_reply.py#L22-L727`：覆盖中心服/本地执行器任务映射、本地接口契约、消息指纹稳定性、重复文本指纹、未知方向跳过、隔离子进程、本机直连轮询、20 秒轮询、首次尾部未回复消息处理、单轮即时合并、非文本/混合批次人工处理、发送失败停用、未登录/不可私信时停止全自动、固定私信 profile、中心结果脱敏和结构化日志字段；`tests/test_openapi_contract.py#L14-L44` 将 `/api/douyin/dm/inbox` 和 schema 纳入 OpenAPI 契约覆盖。
- `docs/openapi.yaml#L276-L325`、`docs/openapi.yaml#L1259-L1332`：新增本地收件箱接口和请求/响应/消息 schema，并标注正文只在本机响应中存在、中心持久化会脱敏；`docs/API_REFERENCE.md#L586-L646`：同步接口手册和隐私边界；`docs/TROUBLESHOOTING.md#L1761-L1768`：记录“全自动回复点击后没反应”的排查、隐私边界和回滚；`CHANGELOG.md#L702-L708` 与 `migration.sql#L7-L10`：记录发布和 no-op 迁移。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply tests.test_openapi_contract -v` 通过 19/19；后续完整回归见最终回复。真实抖音页面冒烟依赖可用登录账号和目标客户会话，本次未自动执行。
- 回滚：回退上述后端、客户端、测试和文档文件即可恢复到半自动私信能力；不涉及数据库结构或数据迁移。代码生效需要重启本地客户端、本地执行引擎和中心服。
## 2026-07-28 小红书图文素材发布自动切图文与文案标签填充
- `backend/platform_adapters.py#L1749-L1799`：新增 `_xhs_normalize_publish_tags()` 和 `_xhs_select_image_note_tab()`，规范化 `#标签` 并在 `image_note` 发布前点击小红书“上传图文/图片”入口。
- `backend/platform_adapters.py#L1801-L1885`：`xhs_publish_material()` 新增 `body/tags` 参数；标题只填标题框，正文编辑器改为填素材正文；标签优先填话题/标签控件，找不到标签入口时把 `#标签` 追加到正文末尾兜底。
- `backend/api_server.py#L3075-L3080`：`run_publish()` 从素材读取 `body/tags` 并传给小红书发布器，避免图文同款草稿发布时只剩标题。
- `tests/test_native_publish.py#L83-L91`、`tests/test_native_publish.py#L205-L224`：回归覆盖正文/标签传递、图文素材上传前切 tab、正文不再使用标题填充。
- 验证：先运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_native_publish -v` 观察旧实现 3 项失败；修复后 `tests.test_native_publish` 29/29 通过，`tests.test_xhs_note_replacement` 51/51 通过，`py_compile` 退出码 0。
- 回滚：回滚 `backend/platform_adapters.py`、`backend/api_server.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-28 漫剧本地项目计费外键与错误保留
- `/root/ai-education-platform/backend/api/routes/aicanvas.py#L84-L99`、`/root/ai-education-platform/backend/api/routes/aicanvas.py#L300-L329`：计费前查询平台项目；本地项目改为空外键并在描述及 JSON 日志中保留 `local_project_id`，已存在的平台项目继续使用原外键。
- `/root/ai-education-platform/backend/services/billing_service.py#L231-L263`、`/root/ai-education-platform/backend/services/billing_service.py#L298-L304`、`/root/ai-education-platform/backend/services/billing_service.py#L681-L687`：完整性冲突回滚后查询真实幂等记录；无同请求记录时输出脱敏 SHA-256 指纹及项目/任务上下文，不再误报“计费请求重复”。
- `backend/matrix_native_client.py#L9723-L9734`、`backend/matrix_native_client.py#L11116-L11118`、`backend/matrix_native_client.py#L11153-L11155`：首尾帧/视频提交后恢复查询仍无任务时，失败文本保留原始提交错误并追加 `recovery_missing`。
- `tests/test_video_replacement.py#L815-L859`、`/root/ai-education-platform/backend/tests/test_aicanvas_billing_guard.py#L41-L74`：回归覆盖本地项目转换、平台项目保留、非重复完整性错误和客户端首错保留。
- 验证：远程 6/6 计费回归通过；真实计费冒烟中本地项目 `296` 落库外键为 `NULL`，平台项目 `295` 仍落库为 `295`；本地客户端完整回归 37/37 通过。无数据库迁移、OpenAPI 或配置变更。
- 回滚：远程使用 `*.bak.local-project-billing-20260728-1700` 备份恢复两个服务文件；本地回滚客户端、测试和本次文档。本地客户端未自动重启。

## 2026-07-28 workflow collected video reference category
- `backend/matrix_native_client.py#L11618-L11624`: workflow orchestration prompt now states that collected platform videos can only enter the asset library as `采集参考视频`; publishing requires a prior `video` generation step and cannot use the original collected video.
- `backend/matrix_native_client.py#L11699-L11752`: added `_workflow_downloaded_paths()` to extract local media files from local-browser download task results, including `files`, `savePath`, material payloads, and saved directories.
- `backend/matrix_native_client.py#L11755-L11774`: `_workflow_split_reference_downloads()` splits downloaded platform files into video references and image thumbnails, so downloaded `cover.jpg` files become preview metadata instead of separate asset-library cards.
- `backend/matrix_native_client.py#L11816-L11858`: `_exec_collect()` stores only downloaded video files in `ctx["referenceArtifacts"]` and `ctx["collectedArtifacts"]`, writes cover images to `ctx["referenceThumbnails"]`, and keeps reference media out of publishable `ctx["artifacts"]`.
- `backend/matrix_native_client.py#L11656-L11691`: `_workflow_save_script_artifact()` writes workflow script text to `wf_out` as UTF-8 `.txt`, records `ctx["scriptPath"]`, and stores text paths in `scriptArtifacts/textArtifacts` so scripts are traceable but never treated as publishable video/image artifacts.
- `backend/matrix_native_client.py#L11833-L11886`: text and vision steps now persist generated口播脚本,兜底口播脚本, or detailed storyboard scripts and include the saved basename in the run log.
- `backend/matrix_native_client.py#L12001-L12028`: `_exec_library()` splits generated assets and collected reference assets. Generated assets keep `source="自动化工作流"`; collected videos are saved with `source="采集参考视频"` and `category="采集参考视频"`, with `thumbnail/preview` metadata when a downloaded cover image exists.
- `backend/matrix_native_client.py#L12047-L12063`: `_exec_publish()` still only publishes generated videos from `ctx["artifacts"]`; if only reference assets exist, it returns `本次只有采集参考素材,未生成可发布视频,未入发布队列`.
- `backend/matrix_native_client.py#L13555-L13584`: `add_asset()` now accepts backward-compatible `category`, `thumbnail`, and `preview` fields. Thumbnail files are copied into the asset directory and stored on the video asset record, not inserted as independent image assets.
- `backend/matrix_native_client.py#L20360-L20377`: local video asset cards prefer saved `thumbnail/preview` images and fall back to video frame extraction when no thumbnail metadata is available.
- `backend/matrix_native_client.py#L20202-L20293`: the local asset library adds a `采集参考视频` filter button that shows assets whose `category` or `source` is `采集参考视频`.
- `tests/test_workflow_resilience.py#L68-L118`: regression tests cover both vision fallback and successful detailed storyboard script persistence. The tests assert saved script files are visible through `scriptPath/scriptArtifacts` and are not added to publishable `artifacts`.
- `tests/test_workflow_resilience.py#L176-L239`: regression coverage locks cover-image-as-thumbnail handling and verifies the asset library receives only the reference video asset.
- `tests/test_asset_library_shared_button.py#L50-L60`: regression coverage locks local video asset cards to prefer saved thumbnail metadata before extracting a video frame.
- Verification: `py -3 -m unittest tests.test_workflow_resilience -v` passed 6/6; `py -3 -m unittest tests.test_workflow_account_scope -v` passed 4/4; `py -3 -m unittest tests.test_asset_library_shared_button -v` passed 2/2; `py -3 -m py_compile backend\matrix_native_client.py tests\test_workflow_resilience.py` exited 0; `git diff --check -- ...` exited 0 with only existing LF-to-CRLF warnings for docs.
- Rollback: revert `backend/matrix_native_client.py`, `tests/test_workflow_resilience.py`, this implementation note, troubleshooting note, and changelog entry. No OpenAPI, central-server, database migration, Docker, or `migration.sql` change is involved.

## 2026-07-28 小红书图文同款保存草稿进入资产库图文模板
- `backend/matrix_native_client.py#L4871-L4904`: `_sync_xhs_note_draft_to_central()` keeps the existing saved-draft upload path and records `xhs_note_draft_central_sync_failed` structured warnings when draft files are missing or central upload fails.
- `backend/matrix_native_client.py#L4907-L4977`: `_register_xhs_note_template_asset()` writes a traceable `note_template` JSON under `data_dir()/xhs_note_template_assets/`, carrying draft title/body/tags/files/status, source title/body/tags/url/noteId, template id/imageSlots/copyStructure, replacement job id, and the first saved draft image as thumbnail/preview metadata. Missing files or asset registration failures emit `xhs_note_template_asset_register_failed`.
- `backend/matrix_native_client.py#L9090-L9112`: `XhsNoteReplacementPage.save_draft()` now registers the local asset template after a successful local draft save and central sync attempt, returning the result as `assetSync`.
- `backend/matrix_native_client.py#L13767-L13798`: `add_asset()` accepts `kind="note_template"` plus compatible `category`, `thumbnail`, and `preview` fields, copying thumbnails into the asset directory for stable local display.
- `backend/matrix_native_client.py#L20461-L20555` and `backend/matrix_native_client.py#L20570-L20621`: the local asset library retains note-template card rendering with thumbnail fallback plus `文件夹` and `删除` actions, while the current filter row no longer exposes the `图文模板` entry and still does not expose a direct JSON `打开` action.
- `tests/test_xhs_note_replacement.py#L1094-L1144` and `tests/test_xhs_note_replacement.py#L1147-L1225`: regression coverage verifies saved drafts still sync to the central material library and now register a `note_template` asset with source/template metadata.
- Verification: first ran the new focused regression and observed the old implementation fail with no asset registration; after implementation, `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_save_draft_registers_note_template_asset tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_save_draft_syncs_saved_material_to_central_library -v` passed 2/2, `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement -v` passed 55/55, and `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_xhs_note_replacement.py` exited 0.
- Rollback: revert `backend/matrix_native_client.py`, `tests/test_xhs_note_replacement.py`, this implementation note, the troubleshooting note, and `CHANGELOG.md`. No central-server API, OpenAPI, Docker, database schema, or `migration.sql` change is required.

## 2026-07-28 Douyin manual DM editor detection
- `backend/api_server.py#L1501-L1810`: `browser_send_dm()` now waits up to `DY_DM_EDITOR_WAIT_MS` after clicking the profile DM button, scans richer editor candidates (`role=textbox`, `textarea`, `input`, and multiple `contenteditable` variants), fills the selected editor through Playwright with keyboard/DOM fallbacks, and emits `douyin_dm_send_editor_not_found` structured logs with safe diagnostics when the editor is still missing.
- `backend/api_server.py#L1726-L1736` and `backend/api_server.py#L1791-L1794`: `dm_input_not_found` and `dm_type_failed` responses now include `dmEditorDiagnostics` with `editorCandidateCount`, selected candidate metadata, page title, and URL. The diagnostics do not include the outgoing private-message text.
- `tests/test_douyin_dm_auto_reply.py#L209-L235`: regression coverage locks the wider editor selector set, condition polling, and safe diagnostics contract for manual and auto-reply send paths that reuse `douyin.dm`.
- Verification: the focused regression first failed against the old implementation, then passed after the fix. `.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v` passed 26/26. `.\.venv-win\Scripts\python.exe -m py_compile backend\api_server.py tests\test_douyin_dm_auto_reply.py` exits 0, with only existing invalid-escape warnings in unrelated lines.
- Rollback: revert `backend/api_server.py`, `tests/test_douyin_dm_auto_reply.py`, this implementation note, the troubleshooting entry, and `CHANGELOG.md`. No OpenAPI, central-server API, Docker, database schema, or `migration.sql` change is involved.

## 2026-07-29 小红书图文同款隐藏技术摘要与可编辑方案
- `backend/matrix_native_client.py#L8629-L8644`: 图文同款候选方案区域拆成可编辑标题、正文和标签控件，用户不再只能看只读预览文本。
- `backend/matrix_native_client.py#L9267-L9284`: 新增候选方案编辑缓存和标签规范化；切换 `方案1/2/3` 时保留各自已经编辑过的标题、正文和标签。
- `backend/matrix_native_client.py#L9147-L9151` and `backend/matrix_native_client.py#L9287-L9326`: 保存草稿时提交 `copyOverride`，页面摘要只显示业务提示 `已读取图文结构：N 张图片需要替换`，不再展示 `模板：tpl_*`、来源笔记 ID 或内部槽位调试串。
- `backend/api_server.py#L5403-L5430`: 本机 `/api/xhs-note-replacement/save-draft` 接收 `copyOverride` 后写回当前选中的 `copyCandidates[selectedCopyIndex]`，标签自动补 `#` 并去重，后续草稿素材继续复用既有 `build_draft_material_payload()`。
- `tests/test_xhs_note_replacement.py#L312-L375`: 保存草稿接口回归覆盖编辑后的标题、正文和标签落地到素材库与保存后的 job。
- `tests/test_xhs_note_replacement.py#L1171-L1235`: 客户端回归覆盖技术 ID 不显示、编辑后的当前方案随保存提交、切换方案后编辑内容保留。
- Verification: new focused tests first failed against the old implementation, then passed after the fix. `.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement -v` passed 59/59. Follow-up compile and diff checks are recorded in the final response.
- Rollback: revert `backend/matrix_native_client.py`, `backend/api_server.py`, `tests/test_xhs_note_replacement.py`, this implementation note, the troubleshooting entry, and `CHANGELOG.md`. No database migration, OpenAPI, Docker, central-server API, or `migration.sql` change is involved.

## 2026-07-29 获客中心寻找线索动作列固定
- `backend/matrix_native_client.py#L4340-L4349`: `FinderPage` defines action column widths `112/112/140/140`, button widths `92/92/118/118`, `FINDER_ACTION_BUTTON_HEIGHT=32`, `FINDER_ACTION_CELL_MARGIN_X=0`, and `FINDER_ROW_HEIGHT=54` so each action button has enough room after the global table item padding is applied.
- `backend/matrix_native_client.py#L4375-L4387`: the finder table header disables stretch-last-section, keeps data columns flexible, pins columns 4-7 with `QHeaderView.Fixed` plus explicit `setColumnWidth()`, and applies the fixed 54px row height.
- `backend/matrix_native_client.py#L4439-L4469`: finder action controls now use centered clickable `QLabel` widgets with fixed size and independent `QLabel#finderAction` QSS, avoiding Qt native button painting offsets from `QPushButton/QToolButton`.
- `backend/matrix_native_client.py#L4471-L4479` and `backend/matrix_native_client.py#L4530-L4543`: `_action_cell()` wraps each action label in a transparent centered cell widget with no extra side margin; row rendering applies `FINDER_ROW_HEIGHT` and inserts wrapped action widgets for "打开主页", "复制链接", "去私信跟进", and "标记已跟进".
- `tests/test_finder_page_actions.py#L43-L118`: regression coverage locks the dedicated label-style action control, fixed action columns, centered action-cell wrapping, row/button height relationship, and minimum width rules that keep labels fully visible.
- Verification: runtime geometry showed the previous 44px row still produced only a 27px-high cell widget because global `QTableWidget::item { padding:8px; }` shrank the cell widget rect. After changing to 54px rows and removing the action cell's second margin, `.\.venv-win\Scripts\python.exe -m unittest tests.test_finder_page_actions -v` passed 7/7. Offscreen UI inspection confirmed runtime action columns are `112/112/140/140`, rows are 54px, cell widgets are 37px high, and 34px-high action labels render without bottom clipping.
- Rollback: revert `backend/matrix_native_client.py`, `tests/test_finder_page_actions.py`, this implementation note, the troubleshooting entry, and `CHANGELOG.md`. No database migration, OpenAPI, Docker, central-server API, or `migration.sql` change is involved.

## 2026-07-29 抖音私信发送误触搜索框
- `backend/api_server.py#L1534-L1569`: the isolated `browser_send_dm()` child process now wraps inner exceptions and always prints the `__MATRIX_DM_JSON__` marker; failures return `dm_child_inner_exception`, `exceptionType`, a truncated message, `stackTail`, and outer `dm_child_failed` diagnostics include `returncode/stderrTail/stdoutTail`.
- `backend/matrix_native_client.py#L6318-L6334` and `backend/matrix_native_client.py#L6500-L6500`: DM send failure status text now uses `_dm_send_error_text()` so `dm_child_inner_exception` and `dm_child_failed returncode` are visible in the client instead of being hidden behind the outer `error`.
- `backend/api_server.py#L1658-L1686`: `browser_send_dm()` editor scanning now rejects Douyin search-like inputs before typing, including `search`/`搜索` attributes and top navigation textboxes (`r.top < 120`). Diagnostics include `searchBoxRejected`.
- `backend/api_server.py#L1698-L1699`: scoring now prefers lower-half conversation editors and penalizes top-page inputs, reducing the chance that focused navigation/search fields outrank the DM editor.
- `backend/api_server.py#L1834-L1893`: after filling the DM editor, `dm_send_button_click_js` finds a send button near the selected editor and clicks it. Search buttons and top navigation controls are excluded, and `buttonCandidates` are returned for safe diagnosis.
- `backend/api_server.py#L1903-L1918`: if no send button is found, the sender only falls back to Enter for non-`INPUT` editors; if the selected editor is an `INPUT`, it returns `dm_send_button_not_found` instead of pressing Enter into a likely search box.
- `tests/test_douyin_dm_auto_reply.py#L176-L182` and `tests/test_douyin_dm_auto_reply.py#L244-L265`: regression coverage locks client child-diagnostic status text, search-box rejection, conversation send-button click behavior, and child-process failure diagnostics.
- Verification: new focused tests first failed against the old broad editor detection/status display, then passed after the fix. `.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v` passed 30/30; `.\.venv-win\Scripts\python.exe -m py_compile backend\api_server.py backend\matrix_native_client.py tests\test_douyin_dm_auto_reply.py` exited 0 with only existing invalid-escape warnings in unrelated lines.
- Rollback: revert `backend/api_server.py`, `backend/matrix_native_client.py`, `tests/test_douyin_dm_auto_reply.py`, this implementation note, the troubleshooting entry, and `CHANGELOG.md`. No database migration, OpenAPI, Docker, central-server API, or `migration.sql` change is involved.
## 2026-07-29 小红书安全模式执行前拦截

- `backend/api_server.py#L144-L145`: 新增 `RISK_CONFIG_JSON` 和 `XHS_SAFETY_STATE_JSON`，风控配置继续使用 `risk_config.json`，小红书执行态独立写入 `xhs_safety_state.json`，便于回溯当天计数和暂停原因。
- `backend/api_server.py#L3366-L3515`: 新增 `load_risk_config()`、`load_xhs_safety_state()`、`save_xhs_safety_state()`、`xhs_safety_preflight()` 和 `xhs_safety_record()`。执行前会检查每日发布上限、每日评论上限、最小间隔和账号暂停状态；执行后只在成功结果上累计次数，并在发现小红书风险码、验证码、安全验证或创作者登录失效时自动暂停账号。
- `backend/api_server.py#L3196-L3205`、`backend/api_server.py#L3517-L3538`、`backend/api_server.py#L5574-L5585`、`backend/api_server.py#L6010-L6021`、`backend/api_server.py#L6108-L6116`、`backend/api_server.py#L6169-L6177`、`backend/api_server.py#L6248-L6257`: 小红书获客评论、素材发布、读取评论、发表评论、搜索、评论列表和下载入口都接入同一套预检/记录链路，拦截时返回 `xhs_safety_*` 错误码和 `safety` 快照。
- `backend/matrix_native_client.py#L14340-L14384`: 客户端读取本地 `xhs_safety_state.json`，按账号生成“已用/上限”和冷却剩余时间文本。
- `backend/matrix_native_client.py#L21438-L21538`: 风控中心账号表新增“今日发布 / 今日评论 / 冷却”，并在小红书账号被安全模式暂停时显示高风险与处理建议。
- `tests/test_xhs_safety_mode.py#L20-L123`: 回归覆盖发布/评论上限、最小间隔、风险暂停、风控中心列展示和读取状态文件逻辑。`tests/test_api_download_contract.py#L39-L44` 隔离下载契约测试的安全状态文件，避免测试污染默认数据目录。
- 回滚：设置 `XHS_SAFETY_MODE=0` 后重启本地客户端和本地执行引擎，可临时关闭执行前拦截；代码级回滚恢复 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_xhs_safety_mode.py`、`tests/test_api_download_contract.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `docs/DEPLOYMENT.md` 即可。无数据库结构、OpenAPI 新接口、Docker 或 `migration.sql` 变更。
## 2026-07-29 漫剧备用视频模型强制合入分镜 TTS

- `tools/aicanvas_remote/server_current.py#L12688-L12688`、`tools/aicanvas_remote/server_current.py#L12770-L12770`：既有完成任务和刚轮询完成的备用模型任务，在写回项目分镜前都必须先经过 TTS 音轨终结；终结失败直接把任务标记为失败，不允许继续使用模型原声。
- `tools/aicanvas_remote/server_current.py#L13000-L13029`：从未被备用模型参数裁剪破坏的 `fallback_source_params` 中优先恢复该分镜的 TTS URL，并兼容现有音频字段别名。
- `tools/aicanvas_remote/server_current.py#L13031-L13109`：FFmpeg 只映射备用视频的画面流和分镜 TTS 音频流。TTS 比视频长时通过 `tpad=stop_mode=clone` 冻结尾帧；视频比 TTS 长时通过 `apad` 补静音；输出经临时文件校验后原子落盘并返回 `/data/uploads/` 账号隔离地址，模型原音轨不会进入新文件。
- `tools/aicanvas_remote/server_current.py#L13112-L13184`：成功任务记录 `audioSource=storyboard_tts`、`audioMixStatus=completed` 和三类时长；原模型视频 URL 保留为 `providerResultUrl` 供审计和回滚。失败日志为脱敏 JSON 事件，不记录 TTS URL。
- `tests/test_aicanvas_real_person_fallback.py#L447-L599`：覆盖 TTS 来源恢复、短视频冻结尾帧、长视频补静音、模型音轨不映射、账号隔离媒体路由、成功元数据和混音失败阻止项目回写。
- 验证：新增测试先因三个目标函数缺失得到 5 个预期错误，媒体路由测试又先捕获旧 `/uploads/` 前缀；实现后 `.venv-win` 相关回归 57/57 通过，`py_compile` 和 `git diff --check` 退出 0。真实 FFmpeg 冒烟将 3 秒带模型音轨的视频与 5 秒 TTS 合成为 5 秒且含音轨的新视频。
- 生产部署：远程 `server.py` SHA-256 为 `8393970e0f9121ba7d9ba2b9bc68a278794464de629c6a464733f64309af52c5`，服务处于 `active`。项目 299 片段 2 已用现有 16.042 秒 Vidu 视频和 17.571 秒 TTS 重混为 17.584 秒 H.264/AAC 文件，任务记录 `audioSource=storyboard_tts`，未重新调用模型或计费。
- 回滚：代码备份为 `/root/AI-CanvasPro/server.py.bak.tts-mix-route-20260729_123511`；项目状态备份为 `/root/AI-CanvasPro/user/comic_projects_local.json.bak.tts-route-20260729_123619`。恢复对应备份并重启 `ai-canvas.service` 即可；不涉及数据库迁移、中心服或本地客户端重启。
## 2026-07-29 同款替换漫剧提示词角色参考优先
- `backend/matrix_native_client.py#L9568-L9713`: 新增漫剧同款替换人物参考检测、角色参考图优先规则和原片人物外观清洗。上传人物参考图后，画面提示词会删除原片人物性别、发型、脸、服装、体型和配饰描述，只保留销售动作、站位、镜头关系和职业语境，并明确“人物完整外观以上传角色参考图为准”。
- `backend/matrix_native_client.py#L9716-L9859` and `backend/matrix_native_client.py#L10086-L10103`: 创建漫剧项目、生成 `source_text/storyboards`、更新分镜、提交首尾帧/视频时都把 `job` 传入视觉提示词清洗函数，确保同一规则覆盖创建项目和实际生成请求。
- `tests/test_video_replacement.py#L499-L546`: 新增回归测试，覆盖“女生角色参考图 + 原片男销售描述”场景，验证传给漫剧生成器的 `source_text/description/prompt` 不再包含男销售、白衬衫、黑领带、眼镜、短发等原片外观词，不再出现 `truncated`，且画面描述不再被 240 字硬截断。
- Verification: focused regression first failed on the old implementation, then passed after the fix. `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_person_reference_overrides_source_person_appearance tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_payload_uses_keyframes_and_manual_assets tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_source_text_strips_lk888_prompt_boilerplate tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_storyboard_payload_keeps_dialogue_out_of_visual_prompt tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_storyboard_payload_uses_script_and_keyframes tests.test_video_replacement.VideoReplacementHelpersTest.test_comic_project_visual_prompt_extracts_embedded_breakdown_without_subtitles -v` passed 6/6.
- Rollback: revert `backend/matrix_native_client.py`, `tests/test_video_replacement.py`, this implementation note, troubleshooting note, and changelog entry. No central-server API, OpenAPI, database migration, Docker, or `migration.sql` change is involved.

## 2026-07-29 漫剧内联媒体重生成 Task 7B 发布门禁（已完成）

- 状态边界：Task 1-6/5A 的最终本地代码、远端部署源码和关键测试已重新索引；Task 7 已按批准范围完成。远程服务已部署，本地客户端按用户要求未重启；未执行 Git 暂存或提交。
- Task 1-2，受保护媒体鉴权与下载：`backend/matrix_native_client.py#L10728-L10829` 负责脱敏媒体日志、同源保护判断、视频/首尾帧下载及失败状态；`backend/matrix_native_client.py#L11020-L11075` 对同源媒体附加 Bearer、401 时只刷新一次凭证、外部 CDN 不带凭证，并以 `.part` 原子落盘；`backend/matrix_native_client.py#L11099-L11135` 负责 Matrix ticket 交换、漫剧 Token 缓存和鉴权头。恢复语义见 `docs/TROUBLESHOOTING.md#L2128-L2137`。
- Task 3，`frameIndex` 校验、推断和 direct/batch/proxy 路由：`tools/aicanvas_remote/server_current.py#L13644-L13665` 严格校验 `frameIndex/frame_index` 并在批量载荷展开前移除帧选择器；`tools/aicanvas_remote/server_current.py#L14069-L14112` 只展开被选中的关键帧；`tools/aicanvas_remote/server_current.py#L17974-L18218` 是 direct 单分镜图片/视频入口，`tools/aicanvas_remote/server_current.py#L18220-L18457` 是 batch 入口；`tools/aicanvas_remote/server_current.py#L19568-L19586` 按显式 workflow、`quantity=2`、`count=7`、pending/project 顺序推断工作流；`tools/aicanvas_remote/server_current.py#L20232-L20385` 执行 proxy 单帧/双帧提交和独立计费 ID，`tools/aicanvas_remote/server_current.py#L22511-L22532` 在通用平台代理中优先分流该请求；`tools/aicanvas_remote/server_current.py#L19944-L19987` 只把所选帧任务结果覆盖回对应位置。契约见 `docs/openapi.yaml#L113-L139`、`docs/openapi.yaml#L843-L875` 和 `docs/API_REFERENCE.md#L380-L410`。
- Task 4，图片载荷与纯视觉资产绑定：`backend/matrix_native_client.py#L10295-L10326` 构造不含音频/声音/TTS/时长字段的图片生成载荷，同时保留人物、场景、道具及视觉参考；`backend/matrix_native_client.py#L10547-L10570` 支持分镜更新时显式 `include_audio=False`；`backend/matrix_native_client.py#L11205-L11215` 为单帧提交写入一致的 `frameIndex/frame_index`；`backend/matrix_native_client.py#L12856-L12898` 的单帧 runner 仅更新分镜视觉字段、提交所选帧并保留另一帧。
- Task 4-5，单帧/视频重生成与 pending 恢复：`backend/matrix_native_client.py#L10843-L10907` 定义完成态 pending 恢复点及候选状态提升，`backend/matrix_native_client.py#L10910-L10988` 归档脱敏的视频尝试并在单帧成功后标记 `video_stale`，`backend/matrix_native_client.py#L10935-L10962` 对批量重试执行缺帧跳过和仅下载恢复筛选；`backend/matrix_native_client.py#L12791-L12854` 是单帧 UI 入口，`backend/matrix_native_client.py#L12856-L12898` 是单帧执行器，`backend/matrix_native_client.py#L12900-L13140` 是视频强制重生成、下载失败持久化和无重提/无重复计费的 pending 恢复执行器。
- Task 5A，远端声音模式、重复任务和 fallback：`tools/aicanvas_remote/server_current.py#L9802-L9866` 规范化 `auto/tts/legacy` 并决定跳过或准备分镜 TTS；`tools/aicanvas_remote/server_current.py#L12920-L12954` 按声音语义隔离重复视频任务；`tools/aicanvas_remote/server_current.py#L13039-L13067` 恢复 fallback TTS 来源，`tools/aicanvas_remote/server_current.py#L13151-L13247` 对 direct 与 batch 共用终结逻辑，`auto` 保留 provider 音轨而 `tts/legacy` 强制重混；`tools/aicanvas_remote/server_current.py#L13250-L13393` 保存 fallback 原始参数并推进候选模型；`tools/aicanvas_remote/server_current.py#L13396-L13632` 统一 direct/batch 提交、重复复用和声音元数据，`tools/aicanvas_remote/server_current.py#L13919-L13938` 防止复用任务的声音模式被不匹配请求覆盖。direct/batch 调用点分别位于 `tools/aicanvas_remote/server_current.py#L17974-L18218` 和 `tools/aicanvas_remote/server_current.py#L18220-L18457`。
- Task 6，本地预览、播放器、状态和释放：`backend/matrix_native_client.py#L2144-L2177` 校验并缓存本地视频结果；`backend/matrix_native_client.py#L2180-L2345` 提供默认不自动播放且可显式释放后端资源的播放器，`backend/matrix_native_client.py#L2348-L2395` 只读取本地图片进行缩放预览；`backend/matrix_native_client.py#L2398-L2544` 定义视频单元格状态、固定尺寸控件、播放/暂停、进度、音量、全屏和释放；`backend/matrix_native_client.py#L13380-L13439` 在缺失本地帧时后台鉴权下载后再打开预览，`backend/matrix_native_client.py#L13441-L13497` 提供首尾帧独立刷新控件，`backend/matrix_native_client.py#L13563-L13588` 在刷新和销毁时释放旧播放器。
- 关键本地回归：`tests/test_video_replacement.py#L42-L173` 覆盖单帧别名和纯视觉图片载荷；`tests/test_video_replacement.py#L267-L918` 覆盖单帧状态、帧/视频 runner、声音载荷、批量跳过和 pending 仅下载恢复；`tests/test_video_replacement.py#L935-L1083` 覆盖受保护媒体 Bearer、单次 401 刷新、外部 CDN 隔离、下载失败和已完成远程视频恢复；`tests/test_video_replacement_v2.py#L638-L997` 覆盖本地预览、独立刷新、播放器状态/控件/校验/释放、帧失败后旧视频保留及脱敏失败日志。
- 关键远端与契约回归：`tests/test_aicanvas_frame_billing.py#L217-L667` 覆盖 `auto/tts/legacy`、direct/batch 重复任务隔离和共用 fallback 终结；`tests/test_aicanvas_frame_billing.py#L669-L1145` 覆盖独立计费 ID、direct/proxy workflow 推断、严格帧选择校验、batch 字段隔离和单帧 overlay；`tests/test_openapi_contract.py#L66-L102` 锁定 OpenAPI 的整数枚举、成功响应兼容和 400 Schema。
- 独立审查修复：`docs/openapi.yaml#L855-L869` 只强制成功响应包含 `data.task_id`，兼容只返回单任务 ID 的 `action_flow` 与同时返回 `task_ids` 的双帧/多帧工作流；`backend/matrix_native_client.py#L2398-L2424` 在失败状态下优先校验并继续播放已保留的有效本地视频。对应回归为 `tests/test_openapi_contract.py#L66-L102` 和 `tests/test_video_replacement_v2.py#L810-L829`，均先在旧实现下失败再转绿。
- 当前新鲜证据：`py_compile` 已通过，115 项核心测试已通过。完整计划门禁已重跑 375 项，其中 368 项通过；剩余 7 项与记录基线逐项一致，为 4 项旧原片声音预期和 3 项小红书旧夹具/文案问题，未发现新的本功能失败。
- 远程发布与恢复：`2026-07-29 19:48:04 +08:00` 将 SHA-256 `f53d4d2ace67e12886557f28882fa61d40104083983ced96876b7efeaceb1f78` 原子部署到 `/root/AI-CanvasPro/server.py`，上一版本备份为 `/root/AI-CanvasPro/server.py.bak.comic-inline-media-20260729_194804`。部署后 38 项 mock 上游冒烟通过，服务、8777 端口和登录页正常。任务 `5a8c84d4aa1f40239b49435abae6fd08` 的 3 个远程完成视频通过鉴权仅下载恢复，生成提交数为 0，并合成 31.67 秒、720x1280、含音轨的有效成片。
- 回滚与发布边界：本地发布工作集包括 `backend/matrix_native_client.py`、`tools/aicanvas_remote/server_current.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、相关四级文档与变更记录、`tests/test_video_replacement.py` 的确认框 fixture 修正、`tests/test_video_replacement_v2.py`、`tests/test_aicanvas_frame_billing.py` 和 `tests/test_openapi_contract.py`。远程部署前服务进程仍未改变；本次无数据库迁移。

## 2026-07-30 账单领域模块与 Phase 0 冒烟

- `backend/billing_analytics.py#L1-L300`：新增无基础设施依赖的账单领域模块，包含 UTC+8 日期范围和流水筛选、账本/模型用量/充值订单/兑换码的归一化与去重、退款双记录、四类消费聚合、零填充趋势、分页，以及 Draft 2020-12 运行时 JSON Schema 校验；金额转换边界拒绝 Infinity、NaN 和其他非有限 Decimal，只有余额输入的精确字符串 `"inf"` 表示无限。
- `tests/test_billing_analytics.py#L1-L216`：测试锁定活跃消费日均值、权威充值去重和驼峰时间、共享扣费/退款引用、退款展开、Decimal 边界、视频任务去重均值、月趋势、范围/分页、运行时 schema 和仅精确 `"inf"` 合法的语义。
- `scripts/smoke_billing_dashboard.py#L1-L36`：确定性 Phase 0 假数据链路覆盖视频、图片、配音、充值和退款；执行归一化、统计、分页及两个响应 schema 校验。
- `backend/requirements.txt#L20-L22`、`backend/requirements.deploy.txt#L21-L23`：锁定 `jsonschema==4.23.0`、`PyMySQL==1.1.1` 和 `passlib[bcrypt]==1.7.4`，供本地和部署运行时使用。
- 验证：先运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_billing_analytics -v`，因缺少 `billing_analytics` 按预期 RED；当前完整套件 12/12 通过，包含非有限余额回归。Phase 0 冒烟输出单个 `{"ok": true}` JSON 对象，且 `py_compile` 退出码为 0。
- 回滚：移除 `backend/billing_analytics.py`、`tests/test_billing_analytics.py`、`scripts/smoke_billing_dashboard.py` 及两份 requirements 中的 `jsonschema` 锁定，并删除本条和对应排障记录即可；本任务未改动中心服、客户端、数据库、OpenAPI、Docker、环境变量或运行中进程。

## 2026-07-30 Task 5 原生账户中心账单看板

- `backend/matrix_native_client.py#L3830-L4000`：新增 `_billing_amount()`、`_billing_query()`、固定 190px 高的 `BillingTrendChart` 和固定四行的 `BillingDistributionBars`。趋势标签超过 12 个桶时确定性抽稀；分布图固定预留类型、横条、金额和百分比列，不引入 QtCharts、WebView 或新依赖。
- `backend/matrix_native_client.py#L25479-L25853`：`AccountPage` 构建四个紧凑指标、独立的统计/明细日期、按日/按月分组、四类消费分布、六项明细筛选、20/50/100 分页和七列固定宽度表格；管理控件仍由平台管理员权限容器控制。
- `backend/matrix_native_client.py#L25854-L25931`：`load_analytics()` 与 `load_ledger()` 使用独立序列号、脱敏结构化事件、分页/筛选查询和带 `errorId` 的异常 payload。
- `backend/matrix_native_client.py#L26055-L26268`：`_on()` 丢弃迟到 analytics/ledger 响应，错误时保留上次成功内容；`"inf"` 显示为 `∞ 运营方`，未知 `balanceAfter` 显示 `—`，并在晚到管理员响应后复核当前角色。
- `tests/test_account_billing_dashboard.py#L1-L197`：TDD 覆盖四指标/七列表头源码契约、30 天默认区间、明细筛选独立性、固定图表高度、零数据四行分布、金额/查询格式、analytics/ledger 过期响应、错误保留、未知历史余额、详情 tooltip、角色隐藏及旧浮点无穷余额兼容。
- `scripts/smoke_account_billing_ui.py#L1-L205`：使用假 analytics/ledger 响应分别以企业角色渲染 1280x900、普通角色渲染 1024x768，输出 `.tmp-validation/account-billing/account-billing-1280x900.png` 和 `account-billing-1024x768.png`；脚本检查非空像素、每个命名账单指标标签的页面/文本边界、表头和可见单元格的 viewport/字体几何、右侧省略的长详情完整 tooltip、固定四行分布及晚到管理员 payload 后的管理员控件隐藏，并为 Qt offscreen 显式加载 Windows 中文字体以保证视觉证据可读。
- 验证：`tests/test_account_billing_dashboard.py#L1-L197` 的专项测试先有 9 项因控件/字段缺失按预期 RED；实现后专项 11/11 与既有权限/计费回归 15/15 通过。review-fix RED 确认旧 205 行离屏脚本缺少标签/表格几何断言助手；补充助手后，离屏冒烟覆盖命名指标文字、表头、可见单元格与长详情 tooltip。2026-07-30 最终复跑 `tests.test_account_billing_dashboard tests.test_role_permissions tests.test_native_billing_rates` 为 26/26（3.659s），`py_compile` 覆盖客户端、205 行冒烟脚本和 197 行专项测试，`git diff --check` 全量与 Task 5 定向检查均通过。离屏冒烟首次因 PySide6 `QWidget.render` 签名不兼容失败，修正为显式 `QPoint` 后通过；首次图片检查发现 offscreen 字体库为空导致方框字，显式加载 `Deng.ttf` 后重渲染并人工确认两种尺寸无重叠、裁切或不可读文本。
- 回滚：只回滚 `backend/matrix_native_client.py` 的 Task 5 hunks并移除 `tests/test_account_billing_dashboard.py`、`scripts/smoke_account_billing_ui.py`、两张离屏截图、本条实现记录、对应排障记录和 Task 5 报告，即可恢复旧五列账户页。中心 API/OpenAPI、数据库、Docker、环境变量和运行中进程未改动；本任务未启动、重启、部署或提交任何服务。
# 2026-07-30 任务中心纳入本地客户端任务
- `backend/central_server.py#L9550-L9569`: 企业每日任务配额统计会把本地客户端浏览器任务按真实接口路径归一化后纳入计数，账号登录类任务仍不作为可计费任务。
- `backend/central_server.py#L9610-L9620`: 企业用量 `tasks24h/tasks7d` 现在包含本地客户端执行的采集、下载、获客、发布等任务，企业中心“任务趋势”不再只看中心节点任务。
- `backend/central_server.py#L10019-L10026`: 企业概览 `counts.tasks` 纳入 `localBrowserTasks`，管理员/企业家/普通用户仍按现有角色范围过滤。
- `backend/central_server.py#L11208-L11222`、`backend/central_server.py#L11299-L11332`: 小红书搜索/下载/评论归类为搜索、下载、评论任务；新增 `local_browser_task_as_task()` 把本地浏览器任务转换为任务中心统一行。
- `backend/central_server.py#L11630-L11657`: `/api/enterprise/task-center` 合并中心任务、发布队列任务和本地客户端任务；传入当前用户后，企业家看本企业，普通用户只看自己创建的任务。
- `backend/central_server.py#L11830-L11840`、`backend/central_server.py#L14326-L14355`: `/api/central/tasks` 和批量候选列表同步纳入本地客户端任务，避免任务中心摘要和详情列表口径不一致。
- `backend/central_server.py#L13604-L13660`: 本地客户端任务创建时，如果执行端离线，仍写入一条 `failed/local_browser_offline` 任务，任务中心可直接看到失败原因。
- `backend/matrix_native_client.py#L5728-L5769`: 本地任务中心列表优先显示中文类型、中文状态、账号名或节点名，减少 `search/done` 等技术字段暴露。
- `tests/test_enterprise_task_center_local_browser.py#L86-L134`: 回归覆盖企业家看到本企业本地任务、普通用户只看到自己的本地任务、企业用量/概览计数包含本地任务，以及离线本地执行尝试会留下失败任务。
- 验证：先运行新增专项测试观察旧实现失败；实现后 `.\.venv-win\Scripts\python.exe -m unittest tests.test_enterprise_task_center_local_browser tests.test_role_permissions -v` 通过 17 项，`.\.venv-win\Scripts\python.exe -m py_compile backend\central_server.py backend\matrix_native_client.py tests\test_enterprise_task_center_local_browser.py` 通过。
- 回滚：回退 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_enterprise_task_center_local_browser.py`、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库迁移、Docker、环境变量或 `migration.sql`。中心服和本地客户端需重启后生效。
# 2026-07-30 小红书账号矩阵改名同步修复
- `backend/matrix_native_client.py#L1108-L1117`: 账号矩阵合并中心服和本地执行引擎账号时，小红书只在本地执行引擎返回 `xhs-self` 时展示；本地登录态消失后，中心旧记录不再单独出现在账号矩阵里。
- `backend/matrix_native_client.py#L5111-L5111`、`backend/matrix_native_client.py#L5214-L5237`: “改名”按钮把中心账号 ID 一并传入；保存昵称时先写本地 `/api/accounts/rename`，再同步调用中心服 `/api/accounts/rename`。只要本地或中心任一侧保存成功，界面刷新后即可看到新昵称；两侧都失败才提示失败。
- `backend/central_server.py#L4302-L4332`、`backend/central_server.py#L13794-L13825`: 节点账号同步和本地浏览器账号上报时保留 `displayNameOverride`，避免下一次心跳把人工昵称刷回平台默认名。
- `backend/central_server.py#L4464-L4469`、`backend/central_server.py#L4502-L4539`、`backend/central_server.py#L15389-L15398`: 中心账号列表优先返回人工昵称；新增中心服账号改名函数与 `/api/accounts/rename` 路由，按企业范围和当前用户可见范围拦截越权请求，并写入 `account.rename` 审计。
- `docs/openapi.yaml#L184-L214`、`docs/openapi.yaml#L1524-L1556`、`docs/API_REFERENCE.md#L161-L180`: 补齐账号改名 OpenAPI 和接口说明，明确不返回 Cookie、不修改平台昵称，中心服记录写入 `displayNameOverride`。
- `tests/test_native_publish.py#L170-L191`、`tests/test_native_publish.py#L257-L268`、`tests/test_account_matrix_metrics.py#L87-L119`、`tests/test_openapi_contract.py#L78-L110`: TDD 回归覆盖小红书中心旧记录登录态失效、客户端本地/中心双写、中心人工昵称不被节点同步覆盖，以及 OpenAPI 路径/Schema 追踪。
- Verification: 新增失败测试已先在旧实现下失败，修复后相关聚焦测试、OpenAPI 合同测试和 `py_compile` 通过。完整验证见本次最终交付记录。
- Rollback: 回退 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_native_publish.py`、`tests/test_account_matrix_metrics.py`、`tests/test_openapi_contract.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库迁移、Docker、环境变量或 `migration.sql`。
# 2026-07-31 LK888 strict postpaid actual-cost settlement
- `backend/matrix_native_client.py#L802-L991`: `_comic_actual_cost()` reads only final remote cost fields; `_settle_comic_actual_billing()` writes an idempotent task-based ref, actual model ID and exact amount with `allowArrears=true`. Missing cost or task ID becomes `awaiting_actual_cost` with a redacted structured log. The former video/keyframe estimate, precharge and refund helpers are deleted.
- `backend/matrix_native_client.py#L14688-L14906`: initial comic replacement submits and waits for start/end-frame and video tasks before billing. Each successful remote task is settled from its own `cost/actual_model`; failed or cancelled tasks create no local precharge or refund.
- `backend/matrix_native_client.py#L15256-L15418`: single-frame and video regeneration use the same actual-cost settlement. Video download failure keeps the old completed media and stores the new task as pending recovery; settlement reads the new task ID from the final payload without overwriting the old media state.
- `backend/central_server.py#L1065-L1157`: `lk888_actual_charge_amount()` extracts final cost and `lk888_actual_model_id()` prefers `actual_model/fallback_model` over the requested model. Known Vidu Q3 remote aliases normalize to `viduq3-cankaosheng`.
- `backend/central_server.py#L1199-L1462`: `/lk888/*` has no estimate/precharge branch or runtime switch. Synchronous final costs settle immediately. `/v1/media/generate` submit responses always remain pending even when they contain amount-like fields; task status settles only from final cost and actual model. Historical `STATE.gen_charges` is read only to refund or close old precharge records.
- `backend/central_server.py#L3485-L3539` and `backend/central_server.py#L3743-L3852`: actual-cost charging is idempotent by `ref`, may create arrears and uses the supplied LK888 amount even for `comic_keyframe_image`; normal non-model capability charging still uses center-owned prices and blocks insufficient balance.
- `backend/central_server.py#L15917-L15936`, `docs/openapi.yaml#L594-L622` and `docs/openapi.yaml#L1168-L1192`: `/api/billing/charge` accepts documented `allowArrears` plus actual-cost metadata (`modelId/taskId/actualAmount/billingScenario/billingStage/billingDetail`). No new path or response field is introduced.
- `tests/test_video_replacement.py#L2419-L2577` and `tests/test_video_replacement.py#L3009-L3120`: regression coverage proves submit-before-charge ordering, exact frame/video costs, actual model IDs, no charge/refund on submit failure, and preservation of existing media during download recovery.
- `tests/test_api_download_contract.py#L1362-L1504` and `tests/test_billing_unified.py#L184-L205`: setting the removed legacy environment variable cannot restore precharge; async status uses the actual model; keyframe actual cost is not replaced by a local fixed capability price.
- Observability: successful and pending comic settlements emit `video_replace_comic_actual_billing_settled` or `video_replace_comic_billing_awaiting_actual_cost`. Logs include amount/model and hashed task ID only; no Cookie, Token, Authorization, API key or private media URL is recorded.
- Contract and storage impact: OpenAPI descriptions/schema are updated; no database DDL/DML, Docker topology, required environment variable or `migration.sql` change. Historical ledger rows are not mutated automatically.
- Rollback: restore the matching previous client, center, tests and docs together, then restart both processes. There is no environment switch for precharge; running old and new billing processes together is prohibited because it can create duplicate or mismatched ledger rows.

# 2026-07-31 素材发布抖音多文件素材拦截
- `backend/api_server.py#L4666-L4678`: `run_publish()` 在抖音平台进入发布锁、账号恢复和浏览器上传前检查素材文件数量；多于 1 个文件时返回 `douyin_single_video_required`、`platform=douyin` 和 `fileCount`，不再把多个路径交给抖音单文件上传框。
- `backend/api_server.py#L7605-L7626`: `/api/publish/run` 响应透传 `fileCount`，便于本地客户端显示“当前选中几个文件”的可读提示。
- `backend/matrix_native_client.py#L16852-L16869`: `_publish_result_message()` 将 `douyin_single_video_required` 翻译为“抖音视频发布只支持单个视频文件”，提示用户选择单独的 `.mp4/.mov` 视频素材后重试。
- `tests/test_douyin_multi_account.py#L112-L134` 和 `tests/test_native_publish.py#L596-L613`: 回归覆盖抖音多文件素材不会调用 `publish_to_douyin()`，以及客户端展示中文单视频限制提示。
- 契约影响：`/api/publish/run` 成功/失败 JSON 新增可选 `fileCount` 字段，已同步 `docs/openapi.yaml` 和 `docs/API_REFERENCE.md`。无数据库、Docker、环境变量或 `migration.sql` 变更。
- 验证与回滚：新增测试先在旧实现下失败，修复后通过；完整验证见最终交付记录。回滚 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_multi_account.py`、`tests/test_native_publish.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可恢复旧行为。生效需要重启本地客户端和本地执行器。
# 2026-07-31 抖音全自动回复每轮即时合并
- 上述 2026-07-31 合并回复实现已被 2026-08-01 逐条队列替代。当前行为和测试位置见本文件的 “Douyin automatic reply serial queue and manual handoff” 记录。
- 验证与回滚：新增行为测试先在旧实现下失败，修复后 `tests.test_douyin_dm_auto_reply` 79/79 通过；完整验证见最终交付记录。回滚 `backend/matrix_native_client.py`、`tests/test_douyin_dm_auto_reply.py`、`docs/API_REFERENCE.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可恢复旧 5 分钟窗口行为；本次不涉及中心服接口、数据库、OpenAPI schema、Docker、环境变量或 `migration.sql`，代码生效需要重启本地客户端。
# 2026-07-31 资产库按此视频改造口播稿传递修复
- `backend/matrix_native_client.py#L15513-L15632`: 新增 `_reference_breakdown_text_to_transcript_segments()`，把资产库采集参考视频的可读拆解文本解析为 `breakdownAnalysis.transcript.segments`；`_reference_breakdown_to_replacement_payload()` 在发送 `video_replace_start` 前补齐分段口播时间轴，避免同款替换生成方案只看到 `transcript.text` 而每段 `script` 为空。
- `backend/matrix_native_client.py#L18598-L18616`: 同款替换方案构建仍按现有规则从 `transcript.segments` 与分镜时间重叠关系提取口播稿，本次只补齐资产库入口的数据契约，不改变用户上传人物/场景/道具后的替换方案生成流程。
- `tests/test_workflow_assistant_helpers.py#L20-L130`: 回归测试覆盖资产库拆解文本中的 `镜头/台词/时长` 被转换成同款替换可读取的口播片段；旧实现因缺少转换函数和 `segments=[]` 先失败，修复后通过。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_workflow_assistant_helpers.WorkflowAssistantHelpersTest.test_reference_breakdown_payload_builds_transcript_segments_for_replacement_scripts -v` 已从失败转为通过；完整相关回归和编译检查见最终交付结果。
- 运行与回滚：仅本地客户端层变更，需重启本地客户端后生效；不涉及中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。回滚 `backend/matrix_native_client.py`、`tests/test_workflow_assistant_helpers.py` 和本次文档记录即可恢复旧行为。
# 2026-07-31 本地客户端主题切换保留 UI 状态
- `backend/matrix_native_client.py#L28477-L28526`: `toggle_theme()` 不再调用 `_rebuild_pages()`，改为调用 `_refresh_theme_ui()` 轻量刷新 QApplication 样式、现有控件和 `AuroraBg` 背景绘制，避免销毁工作流助手、输入框、任务页等本地 UI 状态。
- `backend/matrix_native_client.py#L28528-L28559`: `_rebuild_pages()` 保留给确需完整页面重建的场景，主题/背景切换不再使用它。
- `tests/test_video_breakdown.py#L873-L924`: 回归测试锁定视频分解忙碌时仍阻止主题切换，空闲后主题切换只调用 `_refresh_theme_ui()`，不得调用 `_rebuild_pages()`。
- 验证：新增断言先在旧实现下失败；修复后运行主题切换聚焦测试、工作流助手直接模式测试、`py_compile` 和 `git diff --check`。
- 回滚：回退 `backend/matrix_native_client.py`、`tests/test_video_breakdown.py`、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本条记录即可；不涉及中心服、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。
# 2026-07-31 企业中心任务趋势真实柱状图
- `backend/central_server.py#L10055-L10135`: 新增 `enterprise_task_trend_7d()`，`enterprise_usage()` 返回 `taskTrend7d`，按最近 7 个自然日和任务 `createdAt` 聚合中心服任务 `STATE["tasks"]` 与本地客户端任务 `STATE["localBrowserTasks"]`。
- `backend/matrix_native_client.py#L4415-L4522`: 新增 `_enterprise_task_trend_series()`，企业中心“任务趋势”改为读取 `usage.taskTrend7d`，展示真实日期标签和每日任务数；删除 `or 280` 与固定比例模拟柱状图。
- `docs/openapi.yaml#L827-L856`、`docs/openapi.yaml#L1332-L1379`、`docs/API_REFERENCE.md#L629-L644`: 补齐 `/api/enterprise/usage`、`EnterpriseUsage` 和 `EnterpriseTaskTrendBucket` 契约，并说明 `调度任务` KPI 是当前权限范围内任务总数，趋势图是近 7 天每日任务量。
- `tests/test_enterprise_task_center_local_browser.py#L113-L142`、`tests/test_agent_mode_defaults.py#L189-L208`、`tests/test_openapi_contract.py#L80-L114`: 回归覆盖真实日桶聚合、前端不再使用模拟数据和 OpenAPI 必备路径/schema。
- 验证：新增测试先在旧实现下失败；修复后运行企业任务中心、本地客户端趋势解析、OpenAPI 覆盖测试和相关 `py_compile` 均通过。
- 回滚：回退 `backend/central_server.py`、`backend/matrix_native_client.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、相关测试、`CHANGELOG.md`、`docs/TROUBLESHOOTING.md` 和本条记录即可；不涉及数据库、Docker、环境变量或 `migration.sql`。
# 2026-07-31 数字人口播上传素材悬浮删除
- `backend/matrix_native_client.py#L3279-L3348`: 新增 `HoverDeleteMediaFrame`，把预览 QLabel 和左上角 `×` 删除按钮封装到同一个固定尺寸预览框；按钮默认隐藏，只在鼠标悬停且已有素材时显示。
- `backend/matrix_native_client.py#L9110-L9119`: `DigitalHumanPage` 的人物、场景和声音上传位改用 `HoverDeleteMediaFrame`，三类素材都绑定到同一个 `_clear_uploaded_asset()` 清空入口。
- `backend/matrix_native_client.py#L9244-L9279`: `_set_image_preview()` 支持新预览框；新增 `_sync_asset_status()` 和 `_clear_uploaded_asset()`，点击 `×` 只清空当前页面状态与预览，不删除磁盘文件或资产库记录。
- `backend/matrix_native_client.py#L9281-L9327`: 上传流程改为上传成功后才替换预览；声音上传成功后显示短文本预览并可悬浮移除。
- `tests/test_video_replacement_v2.py#L1895-L1906`: 新增源码回归测试，锁定数字人口播三类上传素材都有悬浮删除控件和清空逻辑。
- 验证与回滚：本次只影响本地客户端数字人口播 UI；需要重启本地客户端后生效。无 OpenAPI、数据库、Docker、环境变量或 `migration.sql` 影响；回滚上述代码、测试和文档即可恢复旧行为。
# 2026-07-31 企业中心 KPI 固定口径与在线节点统计
- `backend/matrix_native_client.py#L3618-L3625`: 新增 `ENTERPRISE_OVERVIEW_KPI_LABELS`，企业中心总览固定展示“客户企业 / 企业用户 / 授权账号 / 可用账号 / 在线节点 / 调度任务”六个业务指标，不再按接口返回顺序展示“团队成员”等重复卡片。
- `backend/matrix_native_client.py#L4717-L4719`: KPI 网格按固定列表取数，缺失字段显示 0；“授权账号”仍表示账号矩阵平台账号数量，“企业用户”表示企业内平台登录用户数量。
- `backend/central_server.py#L10284-L10358`: `/api/enterprise/usage` 的 `nodes/onlineNodes/nodeOnlineRate` 改为使用统一执行端口径，包含本地浏览器客户端和兼容期旧执行节点。
- `backend/central_server.py#L10694-L10782`: `/api/enterprise/summary` 的 `counts.nodesOnline` 按角色过滤；平台管理员/企业管理员按可见企业统计，普通用户直接调用接口返回 0，避免泄露企业执行端状态。
- `backend/central_server.py#L14104-L14154`: 新增 `enterprise_execution_nodes()` 和 `enterprise_execution_nodes_for_orgs()`，统一本地浏览器客户端 `localBrowserClients` 与旧 `nodes`，并按 `lb-` 前缀去重同一台本地客户端。
- `tests/test_enterprise_task_center_local_browser.py#L113-L124`、`tests/test_role_permissions.py#L124-L134`、`tests/test_agent_mode_defaults.py#L234-L244`: 回归覆盖在线本地浏览器客户端计入企业管理员在线节点、普通用户不能看到该数量，以及客户端 KPI 固定列表。
- 验证与回滚：新增测试先暴露旧实现未统计 `localBrowserClients`、普通用户可看到企业在线节点和客户端 KPI 未固定的问题；修复后 `tests.test_enterprise_task_center_local_browser`、`tests.test_role_permissions`、`tests.test_agent_mode_defaults` 共 52/52 通过，`py_compile` 通过。回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、三组测试、`docs/API_REFERENCE.md`、`docs/openapi.yaml`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及数据库结构、Docker、环境变量或 `migration.sql`。中心服和本地客户端需重启后生效。
# 2026-07-31 AI触达 task_timeout 可观测性与长任务超时修复
- `backend/matrix_native_client.py#L1394-L1416`: `submit_local_task()` 超时返回时保留最后一次 `/api/local-browser/task` 轮询结果，写入 `lastStatus`、`lastError` 和 `lastTask`，便于前端和日志判断任务是 queued、running 还是其他状态。
- `backend/matrix_native_client.py#L1433-L1440`: `_local_task_error_message()` 新增 `task_timeout` 中文说明，提示检查本地执行引擎、登录/验证码/风控和页面加载状态，并附带任务ID与最后状态。
- `backend/matrix_native_client.py#L6022-L6040`: `OutreachPage` 提交 `outreach.run` 时等待 900 秒，状态栏失败文案改用 `_local_task_error_message(d)`，不再直接显示 `未完成:task_timeout`。
- `backend/central_server.py#L14024-L14093`: 中心服新增 `LOCAL_BROWSER_LONG_TASK_TIMEOUT_SEC`、`LOCAL_BROWSER_LONG_TASK_PATHS` 和 `local_browser_task_timeout_sec()`；AI触达、寻找线索、发布、下载类长任务默认 900 秒后才 requeue，普通任务保持 300 秒。
- `docs/DEPLOYMENT.md#L221-L221`: 环境变量清单补充可选 `CENTRAL_LOCAL_BROWSER_LONG_TASK_TIMEOUT_SEC`，便于 staging/prod 按需调整本地浏览器长任务 requeue 阈值。
- `tests/test_outreach_page_copy.py#L31-L61`: 回归覆盖 AI触达 900 秒等待、中文错误翻译和超时诊断字段。
- `tests/test_enterprise_task_center_local_browser.py#L180-L220`: 回归覆盖 `outreach.run` 运行超过普通 300 秒不会被中心服重新排队，同时普通搜索任务仍会按原 300 秒 requeue。
- 验证：新增测试先在旧实现下失败；修复后运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_outreach_page_copy tests.test_enterprise_task_center_local_browser tests.test_finder_page_actions tests.test_native_publish -v` 通过 68/68。完整编译和 diff 检查见最终交付记录。
- 回滚：恢复 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_outreach_page_copy.py`、`tests/test_enterprise_task_center_local_browser.py`、`CHANGELOG.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及 OpenAPI、数据库、Docker 或 `migration.sql`。本次新增可选环境变量 `CENTRAL_LOCAL_BROWSER_LONG_TASK_TIMEOUT_SEC`，默认 900 秒；中心服与本地客户端均需重启后生效。
## 2026-07-31 Comic Replacement Motion-Only Prompt Cleanup
- `backend/matrix_native_client.py#L11962-L12010`: `_comic_clean_motion_action()` now strips quoted spoken text, replaces source product/object words with uploaded prop actions, collapses repeated uploaded-prop replacements, and normalizes speech/promo verbs into visual actions.
- `backend/matrix_native_client.py#L12001-L12009`: `_comic_clean_visual_continuation_prompt()` sanitizes continuation text before it is appended to visual prompts, removing `口播/讲解/说话` wording from LK888-facing prompt text.
- `backend/matrix_native_client.py#L12012-L12111`: `_comic_uploaded_asset_motion_prompt()` now parses Markdown shot blocks such as `### ... **画面：** ... **动作：** ...`, keeps only motion/shot/rhythm structure, omits original person/product/scene/subtitle fields, and emits uploaded asset slots.
- `backend/matrix_native_client.py#L12757-L12775`: `_comic_storyboard_update_payload()` sends `camera_movement="静态镜头"` instead of the full visual prompt, so the comic generator no longer parses the prompt body as camera movement.
- `tests/test_video_replacement.py#L155-L170` and `tests/test_video_replacement.py#L1630-L1695`: regression coverage locks the camera-movement field and the Markdown motion-only prompt cleanup.
- Verification and rollback: `tests.test_video_replacement` 97/97 passed; `py_compile` passed for `backend/matrix_native_client.py` and `tests/test_video_replacement.py`; latest job prompt reconstruction showed no original product/scene/person-clothing/subtitle-table/original quote/koubo/promo-detail residue. No OpenAPI, database, Docker, environment variable, remote comic service, or `migration.sql` impact. Roll back the two code/test files and docs entries to restore old behavior. Runtime effect requires manually restarting the local client; no restart was performed.
## 2026-08-01 同款替换远程网络错误中文提示
- `backend/matrix_native_client.py#L9870-L9905`: `_localize_replacement_display_text()` 新增远程请求超时与连接失败识别；`HTTPConnectionPool`、`Read timed out`、`ConnectionError`、`NewConnectionError` 等 requests 内部文本只保留在原始错误和结构化日志中，用户界面显示固定中文提示。
- `tests/test_video_replacement_v2.py#L5340-L5376`: 新增两条展示层回归，分别锁定远程服务响应超时和远程服务连接失败，不展示英文异常、错误编号或 requests 内部文本。
- 运行与回滚：本次仅本地客户端展示层、同款替换测试和文档变化；不涉及中心服、远程漫剧服务、OpenAPI、数据库、Docker、环境变量或 `migration.sql`。重启本地客户端后生效，回滚上述文件和文档条目即可恢复旧展示。
## 2026-08-01 Matrix comic storyboard TTS audio boundary
- `tools/aicanvas_remote/server_current.py#L9807-L9820`: added `_is_matrix_video_replacement_project()` to detect Matrix video replacement projects from `source_mode/sourceMode/project_source_mode/projectSourceMode` on the project, task, or project config.
- `tools/aicanvas_remote/server_current.py#L9822-L9838`: `_comic_storyboard_video_params_with_dialogue_audio()` now upgrades Matrix storyboard `audio_mode=auto` with dialogue to the TTS preparation path. Ordinary comic `auto` still logs `comic_storyboard_dialogue_audio_skipped` and submits no storyboard TTS.
- `tools/aicanvas_remote/server_current.py#L13176-L13211`: `_finalize_ai_comic_fallback_video_audio()` now allows Matrix primary storyboard video results to enter the TTS remux path even when `fallback_applied` is false; non-Matrix primary results still return unchanged. The task-level `project_source_mode` fallback covers project-cache misses after service restart.
- `tools/aicanvas_remote/server_current.py#L13432-L13478`: storyboard video submission now persists `project_source_mode/projectSourceMode` on remote tasks alongside `audio_mode/audioMode`.
- `tests/test_aicanvas_frame_billing.py#L254-L274`, `tests/test_aicanvas_frame_billing.py#L446-L454`, and `tests/test_aicanvas_frame_billing.py#L609-L681`: regression coverage for Matrix `auto+dialogue` TTS preparation, source-mode metadata persistence, primary video TTS remux, and project-cache-miss remux. `tests/test_aicanvas_real_person_fallback.py#L58-L60` keeps the AST fixture aligned with the new helper.
- Verification: RED was `tests.test_aicanvas_frame_billing` with 2 initial failures, then 2 metadata/cache-miss failures. GREEN verification passed `tests.test_aicanvas_frame_billing tests.test_aicanvas_real_person_fallback` 56/56, `.venv/bin/python -m unittest tests.test_video_replacement`, and `py_compile` for the remote mirror, local client, and touched tests. `server_current.py` still emits a pre-existing `return in finally` SyntaxWarning at line 2621.
- Operations and rollback: no remote deploy, restart, OpenAPI, database, Docker, environment variable, or `migration.sql` change was performed. Runtime production effect requires separately deploying the remote AI Canvas `server.py` with backup hash, service health check, port check, and rollback plan. Revert `tools/aicanvas_remote/server_current.py`, `tests/test_aicanvas_frame_billing.py`, `tests/test_aicanvas_real_person_fallback.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous behavior.
## 2026-08-01 Agent LK888 model endpoint audit
- `backend/matrix_native_client.py#L2357-L2409`: Agent local canonical LK888 model rows keep UI-facing display names, model type, endpoint and duration rules. `_LK888_AGENT_EXCLUDED_MODEL_IDS` and `_lk888_fallback_models_by_type()` keep non-generic video rows such as `kling-avatar-image2video`, `vidu-jieshuoman`, and `vidu-mv` out of generic Agent selectors.
- `backend/matrix_native_client.py#L2462-L2538`: `_agent_image_payload()` and `_agent_video_payload()` build LK888 media payloads with model-specific required params for Gemini/Nano Banana, Seedream, MJ, Vidu, Kling, Seedance, Sora, Grok, HappyHorse, Hailuo and Wanxiang rows.
- `backend/matrix_native_client.py#L2845-L2868`: `_lk888_models_by_type()` merges LK888 online catalog rows with local canonical rows, then filters Agent-selectable models before the frontend receives the catalog. This prevents LK888 raw model IDs or mismatched catalog metadata from changing local Agent behavior.
- `backend/matrix_native_client.py#L18832-L18915`: `_prodgen_run_image()` and `_prodgen_run_video()` submit Agent generation through `lk888_media_task()` with uploaded HTTP(S) reference images and the normalized model payload.
- `tests/test_agent_video_duration.py#L301-L654`: regression coverage locks media endpoint routing, required LK888 params, valid duration normalization and exclusion of `kling-avatar-image2video` / `vidu-jieshuoman` / `vidu-mv` from Agent video choices.
- `tests/test_video_replacement_v2.py#L1440-L1490`: focused digital-human tests keep `kling-avatar-image2video` available on the avatar/audio path and ensure local avatar images are sent in the dedicated digital-human payload.
- Verification and rollback: no live LK888 generation was executed, so no real model fee was produced. No OpenAPI, DB, Docker, environment variable, or `migration.sql` impact. Restart the local client for runtime effect. Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, `tests/test_agent_mode_defaults.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the old mapping.
## 2026-08-01 Agent LK888 reference limits and special video params
- `backend/matrix_native_client.py#L2357-L2380`: canonical Agent LK888 rows now include `viduq3-turbo-cankaosheng` and `grok-imagine-video-1.5-preview`; Vidu Q3 family duration slots are `(4, 8, 12, 16)`, Wanxiang 2.7 reference/first-last-frame rows use `(3, 6, 9, 12, 15)`, `sora-2` uses LK888's valid `(4, 8, 12)` slots, `veo3.1` uses LK888's single valid `(8,)` slot, and Grok Imagine 1.5 uses `(1..15)` slots.
- `backend/matrix_native_client.py#L2389-L2422`: `_AGENT_IMAGE_REFERENCE_LIMITS` and `_AGENT_VIDEO_REFERENCE_LIMITS` define per-model LK888 reference limits. Locked image limits include `qwen-image=4`, `kling-v3=4`, `kling-v3-omni=4`, `wan2.7-image=4`, and `kling-image-o1=10`; locked video limits include `viduq3=7`, `viduq3-turbo=2`, `viduq3-turbo-cankaosheng=7`, `wan2.7-cankaosheng=4`, `wan2.7-shouweizhen=2`, `sora-2=2`, `veo3.1=3`, `grok-video-3=0`, `grok-imagine-video-1.5-preview=1`, `pixverse-v6-shouweizhen=2`, `happyhorse-i2v=1`, and `hailuo-2.3=2`.
- `backend/matrix_native_client.py#L2462-L2495`: `_agent_image_reference_limit()`, `_agent_video_reference_limit()`, `_agent_video_is_first_last_frame_model()`, and `_prodgen_ref_label_for()` centralize reference truncation and UI labels. First/last-frame video models are detected by local row or `*-shouweizhen` style IDs and always show `首帧/尾帧` with a 2-image limit.
- `backend/matrix_native_client.py#L2545-L2625`: `_agent_video_payload()` sends the model-specific LK888 fields: Vidu reference models use supported duration slots and `off_peak=false`; `wan2.7-cankaosheng` uses `ratio/resolution/images`; `wan2.7-shouweizhen` uses `first_frame_image/last_frame_image`; `sora-2` uses `input_reference`; `veo3.1` uses fixed `duration=8`, `generation_mode=fast/components`, `generation_type=TEXT/REFERENCE`, `quality=1080p`, and up to 3 `images`; `grok-video-3` uses `size=vertical_hd/horizontal_hd` without generic `resolution/aspect_ratio`; `grok-imagine-video-1.5-preview` requires one first-frame image and uses `aspect_ratio/resolution/images`; `happyhorse-i2v` uses `resolution=720P` without generic `aspect_ratio`; `hailuo-2.3` uses `resolution=768P`.
- `backend/matrix_native_client.py#L19334-L19357`: `_prodgen_entry_ref_limit()` and `_prodgen_entry_refs()` apply the same model-specific limit to saved generation cards, so historical Agent records for first/last-frame models no longer render a third thumbnail as if it participated in generation.
- `backend/matrix_native_client.py#L25722-L25722` and `backend/matrix_native_client.py#L26417-L26417`: generation cards and input slots use the centralized first/last-frame label and hint text instead of generic `参考图1/2/3`.
- `tests/test_agent_video_duration.py#L419-L640`: regression coverage locks image/video reference limits, first/last-frame visible slots, Vidu/Wanxiang/Sora-2/Veo 3.1/Grok duration normalization, and LK888-specific payload fields for Sora, Veo, Grok, PixVerse, HappyHorse, Hailuo, Vidu and Wanxiang rows.
- Verification: focused RED/GREEN was run for the new tests; final local verification is `.\.venv-win\Scripts\python.exe -m unittest tests.test_agent_video_duration -v`, `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_agent_video_duration.py`, and `git diff --check -- backend/matrix_native_client.py tests/test_agent_video_duration.py CHANGELOG.md docs/IMPLEMENTATION.md docs/TROUBLESHOOTING.md`.
- Operations and rollback: native-client-only change. No OpenAPI, database, Docker, environment variable, remote deploy, or `migration.sql` impact. Restart the local client before UI retest. Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous mapping.
## 2026-08-01 Local browser account profile routing
- `backend/matrix_native_client.py#L6192-L6254`: `FinderPage` 继续从账号下拉读取当前 `accountId`，但“打开主页”不再调用 `QDesktopServices.openUrl`；点击时捕获 `platform/accountId/url`，异步调用本地执行器 `/api/cloud-login/open-url`。
- `backend/matrix_native_client.py#L6370-L6376`: `FinderPage._on()` 接收 `finder_open_profile` 结果并在状态栏显示“已用所选账号浏览器打开主页”或本地浏览器失败原因。
- `backend/api_server.py#L4282-L4564`: 抖音评论预检、云浏览器 UI fallback、旧 Edge fallback 和 `publish_comment_to_douyin()` 全部携带选中的 `account_id`，避免 AI 触达评论回退误用 `douyin-self`。
- `backend/api_server.py#L6163-L6182`: `CloudLoginSession.open_url()` 在已有账号浏览器 session 中导航到指定 HTTP(S) URL，并保留登录态诊断。
- `backend/api_server.py#L6913-L6927`: `cleanup_cloud_sessions()` 对缺少 `last_seen/closed` 的旧 session 容错，避免残留 session 让本地浏览器接口 500。
- `backend/api_server.py#L7385-L7428`: 新增 `/api/cloud-login/open-url`，按传入 `accountId` 查找或创建本地执行器管理的可视浏览器 session，并返回 `sessionId/accountId/requestedUrl/createdSession` 等诊断字段。
- `tests/test_finder_page_actions.py#L43-L57`: 源码契约锁定获客中心“打开主页”必须调用本地执行器并传入选中账号，不得再调用系统默认浏览器。
- `tests/test_douyin_comment_cooldown.py#L497-L611`: 回归覆盖评论预检、强制 UI fallback、云浏览器 session 创建和 `/api/cloud-login/open-url` 路由都使用选中 `accountId`。
- `tests/test_openapi_contract.py#L77-L109`、`docs/openapi.yaml#L220-L253`、`docs/openapi.yaml#L1702-L1747`、`docs/API_REFERENCE.md#L182-L226`: 新接口写入 OpenAPI 和 API 参考，保持本地执行器契约可追溯。
- 验证与回滚：已执行定向 RED/GREEN；最终验证见交付记录。生效需要重启本地客户端和本地执行器；无数据库、Docker、环境变量或 `migration.sql` 影响。回滚上述代码、测试和文档即可恢复旧行为。
## 2026-08-01 AI Canvas remote file descriptor exhaustion handling
- `tools/aicanvas_remote/server_current.py#L5878-L5928`: `_is_file_descriptor_exhaustion_error()` detects `OSError(24)`, `errno 24`, and `Too many open files`; `_platform_json_request()` sends `Connection: close`, emits `platform_json_request_fd_exhausted`, and returns `503 {"code":"platform_fd_exhausted"}` without exposing raw Python exception text.
- `backend/matrix_native_client.py#L10059-L10103`: `_localize_replacement_display_text()` maps remote `Too many open files`, `OSError(24)`, `errno 24`, and `platform_fd_exhausted` failures to a Chinese operational message for same-style replacement users.
- `tests/test_aicanvas_frame_billing.py#L214-L238`: regression covers remote platform request handling for `URLError(OSError(24, "Too many open files"))`, asserting the 503 code, sanitized detail, and structured log event.
- `tests/test_video_replacement_v2.py#L5377-L5395`: regression covers native-client display localization so Python internals are not shown in the UI.
- Verification: focused RED/GREEN was run for both new tests, then `tests.test_aicanvas_frame_billing tests.test_aicanvas_real_person_fallback` passed 57/57, the three focused display tests passed 3/3, and `py_compile` passed for `backend/matrix_native_client.py` and `tools/aicanvas_remote/server_current.py`.
- Operations and rollback: no OpenAPI, database, Docker, environment variable, or `migration.sql` impact. Remote AI Canvas was deployed to `/root/AI-CanvasPro/server.py` at `20260801_113520`; backup is `/root/AI-CanvasPro/server.py.bak.comic-inline-media-20260801_113520`, previous SHA `f53d4d2ace67e12886557f28882fa61d40104083983ced96876b7efeaceb1f78`, deployed SHA `0cdbbd45b95817883ff0711faa6678b108f3f76a50b57f60c15fb3f54184f2fe`, service `active`, port listeners `1`, `/login` health `200`, remote smoke `tests.test_aicanvas_frame_billing` 43/43 OK. Roll back remote runtime by restoring that backup to `server.py` and restarting `ai-canvas.service`; roll back the two source files, two tests, `CHANGELOG.md`, `docs/TROUBLESHOOTING.md`, and this entry to restore prior source behavior.
## 2026-08-01 Douyin DM inbox diagnostics and safe message classification

## 2026-08-01 Douyin automatic reply serial queue and manual handoff

- `backend/matrix_native_client.py#L8392-L8395`: the explicit-handoff pattern recognizes clear transfer requests such as `转人工`, `人工客服`, and `找人工`; ordinary mentions of `人工` alone do not trigger it.
- `backend/matrix_native_client.py#L8654-L8691`: system notices are stored in the current conversation for traceability; manual handoff stops the timer, clears pending automatic messages, closes the checkbox, raises the app taskbar entry, and opens one non-blocking notification.
- `backend/matrix_native_client.py#L8741-L8749`: the automatic queue pops one customer message at a time, keeps its single fingerprint as the active send, and never combines customer text.
- `backend/matrix_native_client.py#L8752-L8811`, `backend/matrix_native_client.py#L9066-L9135`: non-text media or an explicit handoff request routes the batch to human review; the redacted log records `non_text` or `explicit_handoff`, and after each successful automatic send the next queued text begins immediately.
- `tests/test_douyin_dm_auto_reply.py#L520-L673`: regressions cover local display, ordered one-by-one generation after each send, image handoff, and explicit customer request for human service.
- Verification and operations: `\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v` passed 82/82. No API/OpenAPI, database, Docker, environment-variable, remote-service, or `migration.sql` change. Restart the local client to apply. Rollback restores `backend/matrix_native_client.py`, `tests/test_douyin_dm_auto_reply.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md`.

- `backend/api_server.py#L2952-L2964`: inbox completion logs include redacted panel state and text-direction counts, without cookies or message bodies.
- `backend/api_server.py#L3131-L3263`: DM inbox reading finds a bottom rich-text editor, scopes candidate bubbles to its conversation column, keeps non-empty bubbles as text even if avatar markup is present, strips trailing hover-menu actions, and uses bubble-center versus panel-center geometry only when CSS direction markers are absent.
- `backend/matrix_native_client.py#L8594-L8643`: unknown-direction messages are retained for manual review instead of being marked seen.
- `backend/matrix_native_client.py#L8896-L8932`: auto-reply status distinguishes unknown-direction text from a true empty inbox.
- `tests/test_douyin_dm_auto_reply.py#L243-L356`: source-contract regression coverage protects panel diagnostics, rich-text editor candidates, action-menu exclusion, geometry fallback, and the client manual-review status.
- Runtime note: restart the local client and local executor after applying. No API contract, OpenAPI, database, Docker, environment variable, or `migration.sql` change is required. Rollback is file-level restoration of the files listed in `docs/TROUBLESHOOTING.md`.
## 2026-08-01 Same-style replacement image URL recovered as video
- `backend/matrix_native_client.py#L10011-L10013`: `_REPLACEMENT_ERROR_DISPLAY` now maps `comic_segment_invalid:media_invalid_duration`, generic comic segment invalid media, and missing comic video recovery to Chinese user-facing messages.
- `backend/matrix_native_client.py#L13046-L13057`: added small URL suffix helpers so recovery can distinguish obvious image URLs from video URLs without logging signed query strings.
- `backend/matrix_native_client.py#L13059-L13070`: `_comic_storyboard_media_url(..., "video")` now accepts strong video fields only when they are not image URLs and accepts generic `resultUrl/result_url/url` only when the suffix is video-like. This prevents a storyboard end-frame `.png` from becoming the segment `videoUrl` after a submit timeout.
- `tests/test_video_replacement.py#L1163-L1186`: regression reproduces project `314` / storyboard `314001` style recovery where only start/end frame image URLs exist and asserts `comic_video_recovery_missing` instead of returning a `.png`.
- `tests/test_video_replacement_v2.py#L5394-L5403`: regression locks the Chinese display text for `comic_segment_invalid:media_invalid_duration`.
- Verification: the two new tests failed before implementation and passed after the fix. Focused recovery/download tests passed 4/4, focused display tests passed 4/4. Broader verification is listed in the final handoff.
- Operations and rollback: local client source and tests only. No remote AI Canvas deploy/restart, OpenAPI, database, Docker, environment variable, or `migration.sql` impact. Restart the local client for runtime effect. Roll back `backend/matrix_native_client.py`, `tests/test_video_replacement.py`, `tests/test_video_replacement_v2.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore prior behavior.
## 2026-08-01 Agent Kling 2.6 Pro LK888 sound param
- `backend/matrix_native_client.py#L2501-L2536`: `_agent_video_payload()` now leaves `kling-v2-6` on the generic video parameter set and no longer sends `params.sound=false`, which LK888 rejects during task creation.
- `tests/test_agent_video_duration.py#L332-L350`: regression coverage asserts the `Kling 2.6 Pro` payload has no `sound` field while preserving the other Agent video model parameter rules.
- Verification and rollback: RED first failed with `sound` present, then GREEN passed after the payload change. `tests.test_agent_video_duration tests.test_agent_mode_defaults` passed 58/58 and `py_compile` passed for `backend/matrix_native_client.py`. No OpenAPI, DB, Docker, environment variable, remote service, live LK888 generation, or `migration.sql` impact. Restart the local client for runtime effect. Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the old mapping.
## 2026-08-01 Agent LK888 upstream saturation display text
- `backend/matrix_native_client.py#L18896-L18965`: `_prodgen_user_error_text()` now normalizes mixed Chinese/English quotes first, extracts `详情/detail/message/msg/error/reason`, strips `未拿到任务ID` / `status` / `message` / `code`-style wrappers, removes raw error-number prefixes, and normalizes malformed punctuation such as `（image_url)` to `（image_url）`.
- `backend/matrix_native_client.py#L25348-L25348`: Agent result cards render `生成失败：` plus `_prodgen_user_error_text(...)`, so historical saved failures are also cleaned when cards refresh.
- `backend/matrix_native_client.py#L26135-L26140`: Agent generation failure handling stores the cleaned `error` for UI, keeps the original summary in `rawError`, logs the raw diagnostic locally, and refunds the local pre-generation capability charge as before.
- `tests/test_agent_video_duration.py#L451-L569`: regression coverage now also locks two task-creation payload shapes that previously leaked raw LK888 fields: unquoted `code/msg` JSON-like text and mixed-quote Chinese-colon payloads.
- Verification and rollback: `.\.venv-win\Scripts\python.exe -m unittest tests.test_agent_video_duration -v` passed 27/27 and `.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_agent_video_duration.py` passed. No OpenAPI, DB, Docker, environment variable, remote deploy, live LK888 generation, or `migration.sql` impact. Restart the local client for runtime effect. Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the old raw-error display.
- Verification and rollback: `tests.test_agent_video_duration tests.test_agent_mode_defaults` passed 54/54; `py_compile` passed for `backend/matrix_native_client.py`. No OpenAPI, DB, Docker, environment variable, or `migration.sql` impact. Restart the local client for runtime effect. Roll back `backend/matrix_native_client.py`, `tests/test_agent_video_duration.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore old display behavior.
## 2026-08-01 Agent Motion Control 与图片提交契约
- `backend/matrix_native_client.py#L2053-L2140`：旧图片入口统一提交 LK888 `/v1/media/generate`，返回原始 JSON；需要本地图片字节的内部流程改用 `_lk888_image_result_download()`，避免旧入口隐式轮询下载。
- `backend/matrix_native_client.py#L2409-L2558`：Agent 模型规则区增加图像/视频参考图数量上限、`kling-motion-control-v3` 专属图片+视频字段和 `kling-v2-6` 的 `sound=on`。
- `backend/matrix_native_client.py#L19161-L19191`、`#L19367-L19419`：参考视频先上传为公网 HTTPS URL，再进入动作控制任务 payload；普通视频模型仍上传全部允许的参考图片。
- `backend/matrix_native_client.py#L25734-L26230`：Agent UI 增加动作控制参考视频选择按钮，模型非动作控制时隐藏；生成记录保存 `referenceVideo` 路径，重新编辑时恢复。
- `tests/test_agent_video_duration.py#L342-L430`：覆盖动作控制字段、参考视频上传、多图上限、Kling 2.6 有声和旧图片入口原始 JSON 契约。
## 2026-08-01 小红书移除账号不再残留 JSON
- `backend/api_server.py#L589-L610`: `remove_xhs_account()` 现在会优先删除 `xhs_auth_state.json`，失败时才回退为最小 tombstone；同时只清理 `xhs_profile` 下的 `Cookies*` 文件，不会触碰 `materials/`、`media_datas/` 或其他素材目录。
- `tests/test_douyin_multi_account.py#L186-L210`: 回归测试覆盖了小红书移除后 `xhs_auth_state.json` 消失、cookie 文件清理、profile marker 保留以及素材文件保留。
- 运行与回滚：仅影响本地账号状态文件与测试；重启本地客户端后生效。回滚 `backend/api_server.py`、`tests/test_douyin_multi_account.py` 和本条文档即可恢复旧行为。
## 2026-08-03 Agent LK888 video media contract alignment
- `backend/matrix_native_client.py#L2408-L2490`: define per-model Agent video image/video/audio capability defaults and required-media rules. The same helper controls reference limits and UI capability checks.
- `backend/matrix_native_client.py#L2628-L2776`: build LK888-specific video payloads. Hailuo, Vidu Q3, Kling V3 video, HappyHorse, Wanxiang, first/last-frame, Motion Control, and Grok Imagine rules are normalized before submission; local reference videos are passed as public URLs.
- `backend/matrix_native_client.py#L19775-L19794`: reference-video upload metadata is generic for Agent video models, not limited to Motion Control.
- `backend/matrix_native_client.py#L19971-L20035`: `_prodgen_run_video()` uploads images and supported reference videos according to the shared media contract before calling LK888.
- `backend/matrix_native_client.py#L26562-L26577`: Agent reference-video button visibility follows the selected model capability.
- `tests/test_agent_video_duration.py#L431-L858`: regression coverage for image limits, duration slots, model-specific payload fields, required media, generic reference-video upload, and HappyHorse/Wanxiang contracts.
- Native-client-only change. No OpenAPI, database, Docker, environment-variable, remote-service, or `migration.sql` change. Restart the local client before testing the Agent UI.
## 2026-08-03 Agent videos to publish queue
- `backend/matrix_native_client.py#L19511-L19557`: `prodgen_video_pending_entry()` and `add_prodgen_video_to_pending()` convert only completed Agent video records into `PENDING` publish rows, default the platform to Douyin, copy the Agent prompt into `caption`, and preserve `sourceProdgenId` for traceability. The helper checks for an existing pending row before insertion so repeated clicks do not duplicate the publish queue.
- `backend/matrix_native_client.py#L26206-L26213`: `GenCard` shows `加入发布` beside `播放` only for completed video results; once a matching pending row exists, it switches to disabled `已加入`.
- `backend/matrix_native_client.py#L26564-L26566`: `ProductGenPage.on_show()` loads both Agent results and the pending publish queue so restarted clients can still show `已加入` for videos already queued.
- `backend/matrix_native_client.py#L26882-L26891`: `ProductGenPage.add_to_publish()` handles the click, refreshes the current card, and tells the user to continue in 素材发布 for account selection and Douyin publishing.
- `tests/test_agent_mode_defaults.py#L375-L410`: regression coverage verifies Douyin defaulting, duplicate protection, source trace fields, and completed-video button visibility.
- Verification and rollback: run `.\.venv-win\Scripts\python.exe -m unittest tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_completed_video_can_be_added_to_douyin_pending_publish_once tests.test_agent_mode_defaults.AgentModeDefaultsTest.test_agent_video_publish_button_is_only_available_after_generation -v`, then the broader Agent/native publish checks. This is native-client-only; no OpenAPI, database, Docker, environment variable, remote deployment, LK888 generation, or `migration.sql` change. Restart the local client after source update. Roll back `backend/matrix_native_client.py`, `tests/test_agent_mode_defaults.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md`.
## 2026-08-03 MiniMax H3 official direct integration
- `backend/utils/minimax_direct.py#L1-L272`: adds the dependency-light MiniMax official direct adapter. `_https_url()` rejects non-public HTTPS media including local paths, `data:` URLs, localhost, loopback, private, link-local, reserved, multicast, and unspecified IPs before provider submission. `normalize_video_request()` fixes provider model to `MiniMax-H3`, validates duration `4..15` and resolution `768P|2K`. `MiniMaxDirectClient.submit_video()` calls `/v2/video_generation`; `poll_video()` calls `/v2/query/video_generation/{task_id}`; `retrieve_video()` extracts final `task.content.url` shapes.
- `backend/utils/minimax_pricing.py#L1-L6`: intentionally returns no published unit price with version `minimax-h3-price-unresolved`, so H3 cannot be charged from an unsupported local estimate.
- `backend/central_server.py#L980-L1287`: adds the authenticated center endpoints `/api/v1/minimax/video/generate` and `/api/v1/minimax/video/tasks/{task_id}`, including enabled/configured/concurrency checks, redacted structured MiniMax logs, pending-task storage, official provider polling for active tasks, `resultUrl/providerResultUrl` extraction, and `awaiting_actual_cost` status when provider generation succeeds without a confirmed price.
- `backend/central_server.py#L14315-L14340`: reads `MINIMAX_ENABLED`, `MINIMAX_CENTER_API_BASE`, `MINIMAX_CENTER_API_KEY`, `MINIMAX_MAX_ACTIVE_TASKS`, `MINIMAX_TASK_TIMEOUT_SEC`, and `MINIMAX_POLL_INTERVAL_SEC` from the environment. `backend/central_server.py#L15253-L15254` and `backend/central_server.py#L15865-L15865` wire the GET/POST routes.
- `tools/aicanvas_remote/server_current.py#L437-L446`: adds remote-only MiniMax H3 constants and environment variables. `tools/aicanvas_remote/server_current.py#L1220-L1225` adds the `minimax-h3` catalog row with provider `minimax-direct`, actual model `MiniMax-H3`, duration `4..15`, and resolutions `768P/2K`.
- `tools/aicanvas_remote/server_current.py#L11242-L11256`: maps H3 video selections to the `minimax-h3-video` direct adapter. `tools/aicanvas_remote/server_current.py#L12844-L12847` routes active `provider=minimax-direct` task refreshes to MiniMax official status query. `tools/aicanvas_remote/server_current.py#L13514-L13772`: submits H3 comic video tasks through the direct branch, bypassing local precharge and LK888/APIMart gateway submission, and records `billing_status=awaiting_actual_cost`.
- `tools/aicanvas_remote/server_current.py#L14127-L14442`: implements remote H3 HTTPS media validation, duration/resolution normalization, content assembly, official `/v2/video_generation` submit, official `/v2/query/video_generation/{task_id}` status envelope, provider result URL extraction, provider `task_id` extraction, and redacted H3 task metadata.
- `docs/openapi.yaml#L113-L161` and `docs/openapi.yaml#L2097-L2157`: document the center H3 submit/status contract, result URL fields, and `awaiting_actual_cost`. `docs/API_REFERENCE.md#L18-L71`, `docs/ARCHITECTURE.md#L3-L8`, `docs/DEPLOYMENT.md#L3-L13`, `docs/TROUBLESHOOTING.md#L1-L8`, `backend/.env.example#L24-L27`, `CHANGELOG.md#L3-L13`, and `migration.sql#L21-L25` document the two dedicated keys, official direct boundary, rollout, no-op migration, and rollback expectations.
- `tests/test_minimax_direct.py#L1-L244`, `tests/test_minimax_pricing.py#L1-L29`, `tests/test_minimax_central_server.py#L1-L480`, `tests/test_minimax_aicanvas_remote.py#L1-L291`, and `tests/test_openapi_contract.py#L1-L372`: focused coverage for the adapter contract, unresolved pricing, center auth/config/error/status polling, remote H3 no-gateway/no-precharge branch, official remote polling, local/private-reference rejection, and OpenAPI schema exposure.
- Operations and rollback: center/runtime use only environment secrets and require process restart after deploy. Remote AI Canvas requires backing up `/root/AI-CanvasPro/server.py`, verifying incoming SHA, atomic replacement, restarting `ai-canvas.service`, checking port `8777`, and confirming `/login` returns 200. Database migration is no-op. Roll back by restoring the previous remote `server.py` backup and reverting the listed local source, tests, docs, `CHANGELOG.md`, and `migration.sql`.
## 2026-08-03 Native Client Username-Only Login Screen
- `backend/matrix_native_client.py#L30111-L30119`: login account input is labeled as username-only while retaining the same widget for register-mode phone input.
- `backend/matrix_native_client.py#L30282-L30331`: login mode sets the placeholder to `用户名`, shows the new username/password copy, and restricts the SMS verification row to register mode.
- `backend/matrix_native_client.py#L30484-L30499`: `send_code()` returns immediately outside register mode so the login screen cannot request a login SMS code.
- `backend/matrix_native_client.py#L30662-L30673`: login submission no longer checks `login_needs_phone_code(acct)` and sends only `identifier`, `password`, and `legalConsent`.
- `tests/test_auth_login_modes.py#L38-L58`: regression coverage locks the username-only login screen, removed phone/SMS copy, no login SMS branch, and no login `code` field.
- Verification and rollback: focused RED/GREEN was run for `tests.test_auth_login_modes.AuthLoginModesTest.test_native_client_login_screen_is_username_password_only`, then `tests.test_auth_login_modes` passed 3/3 with `PYTHONPATH=backend`. Native-client restart is required for the UI change. No OpenAPI shape, database, Docker, environment variable, remote service, or `migration.sql` change. Roll back `backend/matrix_native_client.py`, `tests/test_auth_login_modes.py`, `CHANGELOG.md`, `docs/API_REFERENCE.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous phone/SMS login entry.
## 2026-08-03 Account Center Date Picker Year Contrast
- `backend/matrix_native_client.py#L28774-L28820`: `AccountPage._date_edit()` now assigns `billingDateEdit`/`billingDateCalendar` object names and local QSS for the date input, calendar navigation bar, month/year buttons, popup menu, year `QSpinBox`, and date grid.
- `tests/test_account_billing_dashboard.py#L223-L242`: regression coverage verifies all four account-center date fields use the calendar popup and include explicit readable year-spinbox styling.
- Verification and rollback: focused RED/GREEN was run for `test_billing_date_picker_calendar_year_is_readable`; `tests.test_account_billing_dashboard` passed 29/29 and `py_compile` passed for the touched client/test files. A small offscreen render saved nonblank account/date-calendar PNGs under `.tmp-validation/account-billing/`. The broader `scripts/smoke_account_billing_ui.py` is still blocked by its existing fake-ledger long-text-elision assertion, so it was not used as a passing gate. Native-client restart is required. No OpenAPI, database, Docker, environment variable, remote service, or `migration.sql` change. Roll back `backend/matrix_native_client.py`, `tests/test_account_billing_dashboard.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore prior styling.
## 2026-08-03 Agent videos appear in material publish list
- `backend/matrix_native_client.py#L19583-L19628`: `prodgen_video_publish_material_id()` and `add_prodgen_video_to_publish_library()` upload completed Agent videos to the central material library through existing `upload_materials(..., mtype="video")`, store `publishMaterialId` on the Agent entry, and avoid duplicate uploads when the same card is clicked again.
- `backend/matrix_native_client.py#L19630-L19660`: `add_prodgen_video_to_pending()` still creates the compatible pending-publish row and now copies `materialId/centralMaterialId` when available.
- `backend/matrix_native_client.py#L26315-L26322`: `GenCard.refresh()` marks a video as `已加入` only after a material-library id exists, so older pending-only rows can be clicked again to sync into 素材发布.
- `backend/matrix_native_client.py#L26990-L27022` and `backend/matrix_native_client.py#L27196-L27212`: `ProductGenPage.add_to_publish()` runs the material upload in a background task, updates the pending row after upload, and refreshes the card/status from `prodgen_publish_add`.
- `tests/test_agent_mode_defaults.py#L407-L456`: regression coverage verifies material-library upload, idempotency, old pending-row gating, pending compatibility, and completed-video button visibility.
- Verification: focused RED/GREEN Agent publish tests and `py_compile` passed. Native-client-only change using existing `/api/library/upload`; no LK888 payload, OpenAPI shape, database schema, Docker, environment variable, remote service, or `migration.sql` impact. Restart the local client to load the new button behavior.

## 2026-08-03 Agent video editor placeholder copy
- `backend/matrix_native_client.py#L26768-L26769`: `ProductGenPage.sync_mode()` keeps the image-mode reference hint, but the video-mode placeholder now renders only `描述你想要的视频素材…` and no longer mentions LK888 output-model behavior.
- `tests/test_agent_mode_defaults.py#L294-L299`: regression coverage locks the video placeholder copy and rejects both spaced and unspaced variants of `按所选 LK888 视频模型出片`.
- Verification: focused RED/GREEN unittest passed; `py_compile` passed. Native-client-only change; no LK888 payload, OpenAPI, database, Docker, environment variable, remote service, or `migration.sql` impact. Restart the local client to refresh the placeholder. Roll back the files listed in `CHANGELOG.md` for this entry to restore old copy.
## 2026-08-03 Agent video selector removes Kling Motion Control V3
- `backend/matrix_native_client.py#L2421-L2426`: `_LK888_AGENT_EXCLUDED_MODEL_IDS` now includes `kling-motion-control-v3`, so Agent.模式 does not show `Kling Motion Control V3` from local fallback rows or LK888 catalog rows.
- `backend/matrix_native_client.py#L3137-L3149`: `_lk888_grouped_models()` canonicalizes and filters caller-provided rows before building the menu groups, preventing raw online rows for excluded Agent models from appearing in the selector.
- `tests/test_agent_video_duration.py#L973-L993`: regression coverage locks the fallback, online catalog, and grouped-menu paths so `kling-motion-control-v3` remains hidden from Agent video selection.
- Operations: native-client-only change. Restart the local client to refresh the video model selector. No OpenAPI, database, Docker, environment variable, remote service, or `migration.sql` impact. Roll back this change set to restore the previous selectable model.
## 2026-08-03 Agent grok-video-3 uses 10s only
- `backend/matrix_native_client.py#L2405-L2405`: local canonical Agent LK888 row for `grok-video-3` now uses `duration_slots=(10,)`, so the UI exposes only 10 seconds.
- `tests/test_agent_video_duration.py#L616-L629`: regression coverage locks the 10-second-only slot and verifies a saved/stale 5-second request is normalized to `params.duration=10` before LK888 submission.
- Operations: native-client-only LK888 payload mapping change. Restart the local client to refresh the Agent duration button. No OpenAPI, database, Docker, environment variable, remote service, or `migration.sql` impact.
## 2026-08-03 Sidebar Connection Status Copy Removal
- `backend/matrix_native_client.py#L31071-L31085`: the sidebar footer now adds only the account display name beside the avatar; the previous `self.conn` status label is no longer created.
- `backend/matrix_native_client.py#L31178-L31191`: warmup payload handling keeps toast notifications but no longer writes warmup or connection status into the sidebar.
- `backend/matrix_native_client.py#L31217-L31248`: successful login still sets the account name, avatar, balance refresh and session context, but no longer renders `已连接 · 数据隔离`.
- `tests/test_role_permissions.py#L277-L290`: regression coverage locks the absence of the sidebar status label and the old connection/isolation copy.
- Verification and rollback: focused RED/GREEN was run for `test_client_sidebar_does_not_show_connection_isolation_status`. Native-client restart is required. No OpenAPI, database, Docker, environment variable, remote service, or `migration.sql` change. Roll back `backend/matrix_native_client.py`, `tests/test_role_permissions.py`, `CHANGELOG.md`, `docs/IMPLEMENTATION.md`, and `docs/TROUBLESHOOTING.md` to restore the previous status row.
## 2026-08-03 内容采集隐藏图文同款按钮
- `backend/matrix_native_client.py#L7413-L7425`: `ContentPage` 底部操作区只保留“下载 / 分解 / 看评论”等按钮，不再创建或加入“图文同款”按钮，隐藏内容采集页的一键图文同款入口。
- `backend/matrix_native_client.py#L7686-L7707`: 保留历史 `c_note_replace` 结果处理，旧异步结果如果到达仍可完成素材解析与图文同款页面交接，不因按钮移除产生属性错误。
- `tests/test_xhs_note_replacement.py#L577-L612`: RED/GREEN 覆盖内容采集页按钮文本中不再出现“图文同款”，并确认历史交接处理仍存在。
- 验证：`.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_content_page_hides_note_replacement_button tests.test_xhs_note_replacement.XhsNoteNativeFlowTests.test_native_collection_hides_note_replace_button_but_keeps_handoff_handler tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests.test_content_download_result_navigates_and_reaches_prebuilt_note_page -v` 通过。该变更仅影响本地客户端 UI；无 OpenAPI、数据库、Docker、环境变量、远程服务或 `migration.sql` 影响，重启本地客户端后生效。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md`，重新启动本地客户端即可恢复旧按钮。
## 2026-08-03 Account Matrix Self-Service Password Change
- `backend/matrix_native_client.py#L6185-L6192`: `AccountsPage` header now adds a right-side `修改密码` ghost button before `刷新`, visible to every user who can open 账号矩阵, including enterprise admins and normal users.
- `backend/matrix_native_client.py#L6211-L6266`: `change_password()` opens a local password dialog, validates current password presence, new password length and confirmation match, then posts only `currentPassword` and `newPassword` to `/api/auth/change-password` through the authenticated central API helper.
- `backend/matrix_native_client.py#L6268-L6276` and `backend/matrix_native_client.py#L6359-L6366`: password-change errors are localized without logging password text; success clears the hint and shows only `密码修改成功`.
- `docs/openapi.yaml#L93-L123` and `docs/openapi.yaml#L1652-L1668`: OpenAPI documents the authenticated self-service password-change path, request schema, success schema and 400/401/403 error surfaces.
- `docs/API_REFERENCE.md#L112-L139`: API reference documents that the endpoint changes only the current user's password, keeps the current session, revokes other sessions server-side, and audits without plaintext passwords.
- `tests/test_auth_login_modes.py#L59-L74` and `tests/test_openapi_contract.py#L317-L340`: RED/GREEN coverage locks the native account-matrix button, central request body, success message and OpenAPI contract.
- Verification and rollback: `tests.test_auth_login_modes` 4/4, `tests.test_openapi_contract` 9/9, `py_compile`, and an offscreen `AccountsPage` smoke check pass. Restart the native client to show the button; update/restart the central server only if the running deployment does not already include `/api/auth/change-password`. No database schema, Docker, environment variable, or `migration.sql` change. Roll back the files listed in `CHANGELOG.md` to remove the entry.
## 2026-08-03 Enterprise Add Member Without Contact Fields
- `backend/matrix_native_client.py#L5696-L5704`: the add-member success handler now opens the copy dialog with `成员已加入当前企业`, the generated login identifier, and either the provided initial password or a reset-password reminder.
- `backend/matrix_native_client.py#L5787-L5828`: `EnterpriseMembersPage.add_member()` no longer creates phone/email inputs, no longer requires a contact field, and posts only `orgId`, `name`, optional `password`, and `role` to `/api/enterprise/users/upsert`.
- `backend/central_server.py#L8636-L8672`: `upsert_enterprise_user()` accepts name-only member creation, generates `user-<12 hex>` ids when no user id is provided, writes optional initial passwords, creates the membership, and returns `credential.identifier`.
- `backend/central_server.py#L17151-L17157`: the HTTP handler for `/api/enterprise/users/upsert` delegates to `upsert_enterprise_user()` and audits only user id, name, org id, status, and error code, not plaintext passwords.
- `docs/openapi.yaml#L1080-L1118` and `docs/openapi.yaml#L1732-L1765`: OpenAPI documents the add/update member request with only `orgId/name` required and a credential-bearing response.
- `docs/API_REFERENCE.md#L187-L226`: API reference documents that phone/email are legacy optional fields and new native add-member flow uses generated user ids.
- `tests/test_role_permissions.py#L195-L236` and `tests/test_openapi_contract.py#L342-L364`: RED/GREEN coverage locks UI removal of contact fields, backend generated login identifiers, and OpenAPI contract.
- Verification and rollback: `tests.test_openapi_contract` 10/10, focused team-member role tests 3/3, `py_compile`, and an offscreen `EnterpriseMembersPage` smoke check pass. Restart native client and central server to apply. No database schema, Docker, environment variable, or `migration.sql` change. Roll back the files listed in `CHANGELOG.md` to restore the previous contact-required form.
## 2026-08-03 公开下载页 `/download`
- `backend/central_server.py#L15211-L15566`：内置“云灵星图 AI 爆款复刻平台 Windows 客户端下载”页面 HTML 和 `text/html; charset=utf-8` 响应头，下载按钮为禁用状态，不链接安装包。
- `backend/central_server.py#L15677-L15678`：将 `/download` 注册为公开 GET 页面，位于登录鉴权前；现有 `/MatrixShipAgent-Setup.exe` 直链保持不变。
- `tests/test_web_surface_removed.py#L50-L92`：覆盖页面标题、公司背书、禁用按钮、无安装包链接、HTML 响应头和公开路由位置。
- 验证与影响：`tests.test_web_surface_removed.WebSurfaceRemovedTest` 先红后绿；本次无 OpenAPI JSON Schema、数据库、Docker、环境变量或 `migration.sql` 影响。中心服重启后生效，回滚上述文件和文档即可移除页面。
## 2026-08-07 客户端移除全部网页版替换入口
- `backend/matrix_native_client.py#L14677-L14683`：`VideoReplacementPage.__init__()` 删除标题横幅下方的 `web_row` 与「打开网页版替换」按钮，页面在 `prereq_banner()` 之后直接进入 `self._source` 初始化。同款替换只在客户端内完成。
- `backend/matrix_native_client.py#L15208`：删除 `VideoReplacementPage.open_replacement_web()`(原位于 `retry_source_transcription()` 之前),连同它的「请先从『分解视频』载入分解结果」「当前分解结果缺少可用的本地视频文件」「创建网页交接失败」三个提示框。
- `backend/matrix_native_client.py#L11997-L12018`：`XhsNoteReplacementPage.__init__()` 同样删除 `web_row` 与「打开网页版替换」按钮，图文同款页在 `prereq_banner()` 之后直接构造 `source` 卡片。该页现在只剩 2 个按钮。
- `backend/matrix_native_client.py#L746`：删除 `open_replacement_web_page()`。两个按钮移除后它没有任何调用方,也没有测试覆盖。`_open_url()` 本身保留,漫剧工具入口仍在用。
- 保留项：`replacement_web_user_context()#L701`、`create_replacement_web_handoff()#L720`、`replacement_web_launch_url()#L731` 不动,它们由 `tests/test_replacement_web_mvp.py#L267-L321` 覆盖交接与脱敏契约。副作用是三者目前都没有 UI 调用方,视频交接 `rwh_...` 没有 UI 触发路径。
- 未改动：`backend/replacement_web.py`、`backend/api_server.py` 的 `/replacement` 与 `/api/replacement/*` 路由、`MATRIX_REPLACEMENT_WEB_ENABLED` 开关。网页版本身仍然存在,但只能靠手工 `/replacement#token=...` 这条本地排查兜底路径进入。
- 验证与回滚：`py_compile` 通过；`tests.test_replacement_web_mvp`、`tests.test_video_replacement`、`tests.test_video_replacement_v2`、`tests.test_replacement_service`、`tests.test_xhs_note_replacement` 合计 561/561 通过(两次移除后各跑一次)；offscreen 构造两页得到 `VideoReplacementPage` 14 个按钮、`XhsNoteReplacementPage` 2 个按钮,均无「网页」字样,`b_open_replacement_web` 属性都不存在,模块级 `open_replacement_web_page` 已消失而 `replacement_web_launch_url`/`create_replacement_web_handoff` 仍在；`nav_feature_enabled("同款替换")` 在 `MATRIX_VIDEO_REPLACEMENT_ENABLED=1` 下为 `True`。改动只在客户端进程内,需重启本地客户端；已发布安装包不受影响,除非重新打包。无中心服 API、OpenAPI、数据库、Docker、密钥、环境变量或 `migration.sql` 影响。回滚恢复 `backend/matrix_native_client.py`、`docs/API_REFERENCE.md`、`docs/TROUBLESHOOTING.md`、`CHANGELOG.md` 和本条目。

## 2026-08-07 漫剧项目模式片段时长按真实口播排期
- `backend/matrix_native_client.py#L11156-L11175`：`_estimate_replacement_tts_duration_sec()` 默认语速常量 `_REPLACEMENT_TTS_DEFAULT_CHARS_PER_SEC` 由 `4.2` 改为 `5.5` 字/秒，`VIDEO_REPLACE_TTS_CHARS_PER_SEC` 覆盖行为和 `2.5..8.0` 夹取不变。
- `backend/matrix_native_client.py#L11178-L11241`：新增 `_comic_duration_headroom_sec()`、`_comic_duration_slots()` 和 `_comic_segment_video_duration()`；漫剧档位默认为 `4..15` 每个整数秒，`_comic_video_duration_slot()` 增加 `headroom_sec` 参数，已排期的 `videoDurationSec` 走 `headroom_sec=0.0` 保证重复调用幂等。
- `backend/matrix_native_client.py#L11289-L11356`：新增 `_comic_measure_script_duration()` 和 `_comic_apply_measured_speech_durations()`，排期阶段用 `lk888_tts_voice()` + `_probe_media_duration()` 探测真实口播秒数，默认 4 路并发，失败或被禁用时回落估算并写入 `speechDurationSource`。
- `backend/matrix_native_client.py#L11359-L11403`：`_comic_plan_script_segments()` 新增 `job` 参数，先按估算切分口播稿，再用测得时长重算 `videoDurationSec` 和时间轴，并保留 `speechEstimatedSec`、`speechOverflowSec` 供排查。
- `backend/matrix_native_client.py#L13129`、`#L13295`：`_comic_project_create_payload()` 和 `_comic_storyboard_video_payload()` 改用 `_comic_segment_video_duration()`，不再对已排期时长重复叠加余量。
- `backend/replacement_pipeline.py#L98-L99`：`HybridReplacementPipeline.build_plan()` 把 `job` 透传给 `_comic_plan_script_segments()`，使真实时长探测能拿到 `voiceId` 和取消检查。
- `tests/test_video_replacement.py#L1965-L2052`：覆盖整秒档位与余量、环境变量回退粗档位、已排期时长幂等、真实 TTS 时长排期、TTS 失败回落估算、无 job 时不触发探测、默认语速 `5.5` 字/秒。
- 验证：`tests.test_video_replacement`、`tests.test_video_replacement_v2`、`tests.test_replacement_service` 共 395 条通过；全量 1374 条中仅 `tests.test_ui_feature_visibility`（缺 `backend/.env.dev`）和 playwright 相关用例失败，改动前即存在。
- 回滚：三个环境变量 `VIDEO_REPLACE_COMIC_DURATION_SLOTS=4,8,12,15`、`VIDEO_REPLACE_TTS_CHARS_PER_SEC=4.2`、`VIDEO_REPLACE_COMIC_MEASURE_TTS=0` 可分别关闭三项改动；或回滚 `backend/matrix_native_client.py`、`backend/replacement_pipeline.py`、`tests/test_video_replacement.py`、`CHANGELOG.md`、`docs/DEPLOYMENT.md`、`docs/TROUBLESHOOTING.md` 和本文档。不涉及中心服、数据库、OpenAPI、Docker 或 `migration.sql`。

## 2026-08-04 Local replacement web MVP
- `backend/platform_features.py#L15-L44`: adds the reversible `MATRIX_REPLACEMENT_WEB_ENABLED` feature gate, defaulting off unless the environment value is truthy.
- `backend/matrix_native_client.py#L683-L710`: writes short-lived native-to-web video handoffs through `create_replacement_web_handoff()`, then builds `/replacement#token=...&user=...&handoffId=...` from the local executor token plus redacted `userId/displayName/orgId/account/appRole/roleScope`, never from the center user session, phone, Cookie, platform auth, or local video path.
- `backend/matrix_native_client.py#L11719-L11745` and `backend/matrix_native_client.py#L14406-L14416`: add "打开网页版替换" buttons to the native image-note replacement and same-style video replacement pages. The image-note page opens the plain local page; the video page uses the handoff-aware method. **Superseded 2026-08-07**: both buttons were removed and `open_replacement_web_page()` was deleted with them; no native page opens the web replacement page any more.
- `backend/matrix_native_client.py#L14947-L14959`: `VideoReplacementPage.open_replacement_web()` requires an already-loaded breakdown source and readable local source video before writing the `rwh_...` handoff and opening the web page. **Removed 2026-08-07**; `create_replacement_web_handoff()` is retained for the handoff contract and its tests but no longer has a UI caller.
- `backend/replacement_web.py#L40-L392`: renders the local `/replacement` HTML page with video and image-note tabs, hash/input token handling, `handoffId` session storage, handoff loading from `/api/replacement/video/handoff`, redacted user context display, customer-facing 401/validation/network/non-JSON error text, Phase 0 video success copy, visual note preview slots, authenticated blob thumbnail loading, copy-candidate radio selection, editable title/body/tags fields, and a note save-draft button that submits `selectedCopyIndex` plus `copyOverride` to `/api/replacement/note/save-draft`.
- `backend/replacement_web.py#L396-L565`: builds safe preview URLs, validates source URLs, rejects userinfo credentials, stores only host/pathHash, records file metadata, resolves uploaded note thumbnails only inside `replacement_web_uploads/note/<jobId>/`, and redacts Cookie/Token/Authorization/Bearer/data URL/signed URL/base64-like fragments from note inputs and filenames.
- `backend/replacement_web.py#L567-L719`: creates, loads, expires, and redacts `rwh_...` video handoff JSON. `handoff_response()` returns source host/pathHash, `sourceVideo.available/pathHash`, analysis duration/transcript counts, and user context without exposing `sourceVideoPath` or source URL query strings.
- `backend/replacement_web.py#L721-L809`: returns redacted job responses and creates video `rvw_...` jobs, optionally binding them to a valid handoff through `sourceContext`; neither path calls LK888, remote AI Canvas, publishing, center sync, or billing.
- `backend/replacement_web.py#L811-L875`: creates `xnr_...` note preview state by reusing the existing image-note template/preview logic and compatible `xhs_note_replacements/<jobId>/replacement_job.json`.
- `backend/api_server.py#L1038-L1123`: extracts `save_xhs_note_draft_payload()` so the old XHS note draft endpoint and new `/replacement` endpoint share copy override, image validation, local material copy, library insert, and compatible job persistence.
- `backend/api_server.py#L5343-L5350`: adds `html_response()` for the local HTML page while preserving CORS and no-store headers.
- `backend/api_server.py#L7185-L7207`: routes multipart `/api/replacement/video/start` and `/api/replacement/note/start` to local job factories, checks the feature gate before reading multipart bodies, and records structured info logs.
- `backend/api_server.py#L7286-L7334`: routes `GET /replacement`, authenticated video/note job status reads, authenticated `/api/replacement/video/handoff` handoff reads, and authenticated `/api/replacement/file` thumbnail reads with disabled, missing-job, bad-path, and read-failure JSON errors.
- `backend/api_server.py#L7466-L7496`: routes `/api/replacement/note/save-draft`, reuses the shared XHS draft save payload helper, replaces the internal XHS job in the HTTP response with the redacted web job response, marks the web job as `draft`, and records redacted `replacement_note_draft_saved` structured logs.
- `backend/api_server.py#L7558-L7566`: keeps `/api/xhs-note-replacement/save-draft` compatible while delegating to the shared draft save helper.
- `docs/openapi.yaml#L145-L357`: documents `/replacement` and the seven local `/api/replacement/*` routes, including video handoff, disabled, validation, thumbnail, and save-draft responses.
- `docs/openapi.yaml#L2320-L2470`: documents replacement start, video handoff, save-draft, and job response schemas without secrets or full private URLs, including optional `handoffId`, `sourceContext`, object-array `copyCandidates`, `files[].previewUrl`, and note `slotMappings[].hasFile`.
- `docs/API_REFERENCE.md#L829-L918`: documents runtime unit, feature flag, video handoff, request examples, authenticated thumbnail loading, visual preview editing, preview/save-draft boundary, token handling, observability, and rollback.
- `tests/test_replacement_web_mvp.py#L49-L730`: covers feature gate behavior, page HTML, customer auth/Phase 0 status copy, native launch URL and handoff redaction, handoff response/job binding, note preview editing controls, job validation, upload persistence, safe thumbnail URLs/file serving, compatible XHS preview job creation, local draft saving without local path exposure, secret redaction, route wiring, disabled/missing responses, token-auth boundaries, disabled multipart reads, and docs contracts.
- Verification and rollback: focused replacement tests, OpenAPI contract tests, adjacent XHS note tests, HTTP smoke, `py_compile`, and `git diff --check` are the release gate. Rollback first sets `MATRIX_REPLACEMENT_WEB_ENABLED=0` and restarts the local executor; code rollback restores the files named in CHANGELOG. No database schema/data migration, Docker image change, LK888 call, remote AI Canvas deploy, publish action, center sync, or billing side effect is introduced.

## 2026-08-04 Installer directory selection
- `backend/installer/MatrixShipAgent.iss#L18-L25`: the installer keeps the default user-writable `{localappdata}\MatrixShipAgent\app` location and `PrivilegesRequired=lowest`, while `DisableDirPage=no` shows the Inno Setup directory page so users can choose another install path.
- `tests/test_web_surface_removed.py#L102-L108`: regression coverage locks the default directory, visible directory page, and non-admin install permission.
- Verification and rollback: RED/GREEN was run for `tests.test_web_surface_removed.WebSurfaceRemovedTest.test_installer_allows_user_to_choose_install_directory` and `test_build_stays_native_only`; full relevant verification should include `tests.test_web_surface_removed` and `py_compile` for the touched test. The change requires rebuilding `backend\dist\installer\MatrixShipAgent-Setup.exe` before release. Roll back `backend/installer/MatrixShipAgent.iss`, `backend/build_matrix_agent.ps1`, `tests/test_web_surface_removed.py`, `CHANGELOG.md`, `docs/TROUBLESHOOTING.md`, and this entry; no center API, OpenAPI, database, Docker, secrets, environment variables, or `migration.sql` impact.

