# 实现索引
## 2026-07-27 企业邀请码契约原生化
- `backend/central_server.py#L7245-L7373`：邀请对象只持久化令牌哈希；创建成功只在顶层返回一次 `inviteCode`，公开邀请对象、列表和校验响应剔除 `token`、`tokenHash`、`inviteCode`，不再生成网页加入链接。
- `backend/central_server.py#L7397-L7481`：接受邀请保留新用户创建账号和已有用户当前密码校验，成功响应补齐 `appRole`、`roleScope`、`memberships`、`organizations` 和会话信息，供原生客户端直接接入现有登录态。
- `backend/central_server.py#L14160-L14171`、`backend/central_server.py#L14394-L14397`、`backend/central_server.py#L15300-L15306`：邀请校验改为公开 POST JSON 请求；审计只记录邀请 ID、企业 ID、状态和错误码，接受与创建路由沿用脱敏审计元数据。
- `tests/test_enterprise_invites.py#L23-L136`：TDD 覆盖邀请码只返回一次且不进入状态/列表、未注册用户与已有用户接受、完整角色上下文，以及 GET 校验退役和 POST 审计不含邀请码。
- 回滚：先校验 `backups/web-removal-20260727/archive.sha256` 和 `manifest.sha256`，再从归档恢复本阶段文件；不得把明文邀请码写入日志、审计或持久化状态。本阶段不修改数据库 Schema。

## 2026-07-25 Agent.模式视频时长可选
- `backend/matrix_native_client.py#L1483`、`backend/matrix_native_client.py#L10894`：视频时长白名单固定为 5 秒和 10 秒；历史记录的非法或缺失时长自动回落到 5 秒，提交 LK888 时使用该值，不再写死 5 秒。
- `backend/matrix_native_client.py#L16928`：Agent.模式视频控制区新增时长按钮；图片模式置灰，视频模式可在 5 秒与 10 秒之间切换。生成记录与重新编辑会保存/恢复时长。
- `tests/test_agent_video_duration.py#L1`：回归测试覆盖可选时长控件、记录写入和 LK888 请求参数链路。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_agent_video_duration.py`、`CHANGELOG.md` 和本条实现索引即可；不涉及数据库、中心服或接口契约变更。
## 2026-07-25 同款替换口播音频时间表约束
- `backend/matrix_native_client.py#L12246-L12351`：新增口播稿按标点/长度切分、按最终音频时长分配到 0.01 秒精度的 `dialogueTiming`，并生成“口播时间表”prompt 块；时间表只来自片段 `script`，不读取原视频字幕/OCR/转写。
- `backend/matrix_native_client.py#L12354-L12535`：主角整身替换和 hybrid 视频编辑 prompt 在最前面注入口播时间表，继续保留产品、场景、原片动作和字幕安全规则；`source` 原片声音模式不注入新台词时间表。
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
- `backend/matrix_native_client.py`：`_run_hybrid_lipsynced_replacement_segment()` 在生成口型同步底片时继续用 `audioMode=source` 保留原片音频，但新增 `promptAudioMode` 保存用户选择的 `tts/uploaded` 台词来源，避免底片 prompt 被误判为原片声音模式。
- `_build_principal_replacement_prompt()` 优先读取 `promptAudioMode/dialogueAudioMode`，并把口播稿台词规则放在已保存的长 `segment.prompt` 前面，确保提交给 LK888 的 1800 字 prompt 内包含用户修改后的口播稿。
- `tests/test_video_replacement_v2.py`：新增回归测试覆盖底片 source 音频时仍写入口播稿，以及长拆解 prompt 不会截断新台词。
- 验证：新增两条测试先失败后通过；同款替换 prompt/口型同步定向测试和 `py_compile` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md` 和 `docs/IMPLEMENTATION.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。按用户要求本次修改后不自动重启本地客户端。
## 2026-07-25 同款替换口播稿进入主角替换提示词
- `backend/matrix_native_client.py`：`_build_principal_replacement_prompt()` 改为按 `audioMode` 生成台词规则。`source` 原片声音模式继续保留原片原音和台词；`tts` AI 音色配音模式把片段 `script` 写入 LK888 prompt，要求台词以用户修改后的口播稿为准；`uploaded` 上传完整配音模式把片段 `script` 写入 prompt，要求台词与上传配音和口播稿一致。
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
- `backend/platform_adapters.py#L719-L815`：新增小红书下载媒体过滤与结果契约 helper，过滤 `data:`、`blob:`、`fe-platform.xhscdn.com`、`picasso-static.xiaohongshu.com`、头像/图标/雪碧图等页面静态资源，并在没有有效正文媒体时返回 `ok=false/error=xhs_no_note_media/stage=download`。
- `backend/platform_adapters.py#L818-L903`：`xhs_download_note()` 改为只从笔记详情主体候选容器收集图片和视频，带上 DOM 尺寸后再进入过滤器，避免把搜索图标、导航资源、广告位和 base64 内嵌图保存成素材文件。
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
- `backend/central_server.py#L2602-L2637`：中心服新增能力价格表和云豆到主库算力的换算 helper，已知能力以中心服价格为准，不再信任客户端传入的金额。
- `backend/central_server.py#L2702-L2744`：新增 `charge_capability_user()`，通用能力扣费统一走中心服；旧云豆钱包直接扣云豆，主库钱包按 `100 云豆 = 1 元` 和 `MAINDB_YUAN_TO_POWER` 换算为算力后原子扣减。
- `backend/central_server.py#L2756-L2816`、`backend/central_server.py#L14549-L14568`：`/api/billing/charge` 调用统一扣费，`/api/billing/refund` 对主库通用扣费按 `ref` 幂等退款；找不到可退流水时返回退款 0，避免凭空加款。
- `backend/matrix_native_client.py#L704-L708`：客户端扣费请求新增 `capability` 字段，继续保留 `amount/reason/ref` 兼容旧中心服。
- `tests/test_billing_unified.py#L98-L154`、`tests/test_openapi_contract.py#L13-L36`：覆盖中心服价格优先、余额不足不写流水、主库算力换算、主库通用退款幂等，以及 OpenAPI 契约包含 `charge/refund`。
- `docs/openapi.yaml#L394-L447`、`docs/openapi.yaml#L690-L719`、`docs/API_REFERENCE.md#L412-L415`：补充扣费和退款接口契约。
- 验证：运行 `python -m unittest tests.test_billing_unified -v` 通过；运行 `python -m unittest tests.test_billing_unified tests.test_openapi_contract -v` 通过；运行 `python -m py_compile backend/central_server.py backend/matrix_native_client.py tests/test_billing_unified.py tests/test_openapi_contract.py` 通过。
- 回滚：回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_billing_unified.py`、`tests/test_openapi_contract.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及数据库结构，`migration.sql` 仍为 no-op。回滚后主库模式下文案、混剪等通用扣费会恢复为放行不扣。
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
- `backend/central_server.py#L6849-L6920`、`backend/central_server.py#L15278-L15283`：新增平台管理员专用 `/api/enterprise/memberships/replace`，用于在运行中的中心服内把指定用户独占移动到指定企业并持久化，避免只改磁盘文件后被旧内存状态覆盖。
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
- `backend/matrix_native_client.py#L3042-L3461`：新增 `EnterpriseMembersPage`，在企业中心内展示成员表；管理员可切换企业，企业家固定当前企业；支持添加成员、创建邀请、重置密码、停用/恢复成员，并调用中心服已有 `/api/enterprise/summary`、`/api/enterprise/invites`、`/api/enterprise/users/upsert`、`/api/enterprise/invites/create`、`/api/enterprise/users/reset-password`、`/api/enterprise/users/status` 接口。
- `backend/matrix_native_client.py#L17608-L17614`：新增 `EnterpriseCenterPage`，把原“企业中心”入口改成“总览 / 团队成员”两个标签页，左侧菜单仍只保留一个企业中心入口。
- `tests/test_role_permissions.py#L124-L136`：新增客户端源码契约测试，锁定企业中心团队成员入口、普通用户隐藏规则和成员管理接口路径。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_role_permissions` 通过；运行 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py backend\central_server.py` 通过。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_role_permissions.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及数据库结构、账号矩阵授权账号迁移、充值/兑换码逻辑或 `migration.sql`。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 2026-07-24 企业中心按钮重叠修复
- `backend/matrix_native_client.py#L3081-L3082`：团队成员表格“操作”列改为固定宽度 174px，避免 `style_table()` 的全列拉伸在窄窗口下把两个操作按钮压到一起。
- `backend/matrix_native_client.py#L3183-L3187`：行内“重置密码”和“停用/恢复”按钮使用固定宽度，保证每一行的点击区域稳定，不随文字和表格宽度抖动。
- `backend/matrix_native_client.py#L18773-L18816`：侧边栏底部由单行布局改为上下两行；上行显示头像、账号名和连接状态，下行显示余额、主题切换和退出按钮，避免用户信息、余额和图标按钮在 220px 侧边栏内重叠。
- `tests/test_role_permissions.py#L137-L147`：新增布局契约测试，锁定操作列固定宽度、按钮固定宽度和侧边栏底部上下两行结构。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_role_permissions` 通过；运行 `.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py` 通过；使用 Qt 离屏渲染生成 `.tmp-validation/team-members-layout.png`，操作列按钮不再重叠。
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
- `backend/matrix_native_client.py#L10519-L10570`：`_extract_replacement_principal_actor()` 保持视觉模型响应解析严格，但当返回内容触发 `principal_actor_extract_invalid_response` 时，不再继续抛出到方案生成层；改为记录 `video_replace_principal_actor_extract_failed`，返回 `status=manual_required`、`candidatePaths`、首张候选帧预览和错误号，页面沿用现有“请选择并确认原片主角”下拉流程继续生成方案。
- `backend/matrix_native_client.py#L6605-L6629`、`backend/matrix_native_client.py#L6992-L7002`：方案就绪事件会把候选帧显示到原片主角下拉框；开始生成时要求用户选择候选帧并把 `principalActor.status` 改为 `manual` 后继续主角整身替换链路。
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
- `backend/central_server.py#L3202-L3274`：新增产品角色中枢，统一把平台管理员映射为 `platform_admin`、企业 `owner/admin` 映射为 `enterprise_admin`、企业 `member` 映射为 `normal_user`，并提供自有数据过滤 helper。
- `backend/central_server.py#L3302-L3317`：平台管理员判定收紧为 root token、`user-owner` 或显式 `isPlatformAdmin`，不再把默认企业的 admin 自动当作平台管理员。
- `backend/central_server.py#L6630-L6659`、`backend/central_server.py#L9498-L9580`：账号矩阵和企业总览按角色返回 `all/org/self` 范围；普通用户只统计归属到自己的账号、素材、知识库、队列和任务。
- `backend/central_server.py#L13649-L13673`、`backend/central_server.py#L14569-L14618`：充值套餐、充值下单/状态、兑换码使用和管理员加款统一要求平台管理员，企业家和普通用户接口层返回 403。
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
- `backend/matrix_native_client.py#L6210-L6252`：同款替换页新增“声音来源”“AI 音色”和“上传配音音频”，默认保留原片声音；AI 音色按每段口播稿配音；上传完整配音会在最终成片阶段替换整条音轨，不做音色克隆。
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
- `backend/matrix_native_client.py#L6681-L6690`：开始生成时把产品图处理进度转发为 `video_replace_progress`，阶段标记为 `product_refs`，前端状态栏和进度详情会显示具体产品图编号，而不是只停留在“上传参考图”。
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

- `backend/central_server.py#L12857-L12874`：本地浏览器任务结果列表归一化，避免对象型 `comments` 被当作列表切片。
- `backend/central_server.py#L13266-L13293`：`local_browser_result()` 保存 `items/comments/leads` 时只切片列表，评论对象回退到规范化后的 `items` 或嵌套评论列表，确保成功结果能继续标记为 `done`。
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
- `backend/api_server.py#L446-L463`、`backend/api_server.py#L2943-L2954`：抖音登录态完整性校验，拒绝只有 `msToken` 或缺少浏览器指纹的缓存，返回 `douyin_auth_incomplete` 供前端提示重新登录。
- `backend/matrix_native_client.py#L3640-L3646`、`backend/matrix_native_client.py#L8645-L8653`：原生客户端分解下载失败文案映射，将 `douyin_auth_incomplete` 和历史 `'s_v_web_id'` 显示为重新登录抖音提示。
- `backend/api_server.py#L1443-L1678`：本地素材入库校验、原 ID 修复和事务回滚。
- `backend/central_server.py#L1397-L1651`：中心素材镜像校验、隔离和原 ID 修复。
- `backend/api_server.py#L4881-L4998`：抖音/XHS 下载入库错误契约与中心素材删除入口。
- `backend/central_server.py#L13184-L13235`：local-browser 下载完成前的中心镜像最终化。
- `backend/central_server.py#L15047-L15088`：中心云节点下载镜像错误契约。

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
- `backend/utils/video_transcription.py#L24-L141`：服务 URL 策略、60 秒分片、600 秒上限和定向重试导出。
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
- `backend/matrix_native_client.py#L5510-L5632`：产品、可选场景、三张授权人脸、纯产品无人物模式、人物一致性模式选择、目标人物、方案/执行/审核/取消控件、进度详情标签、片段操作列和内部事件；`backend/matrix_native_client.py#L5712-L5716` 将场景图标记为可选增强，文案明确不得覆盖源视频主题和镜头结构。
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

- `backend/matrix_native_client.py#L838-L1017`：上传素材优先使用中心服返回的 `publicUrls`；配置 `UPLOAD_API_URL` / `UPLOAD_TOKEN` 时，图片和视频素材先上传到独立公网素材服务并返回 LK888 可访问 URL，音频等其他素材回退中心素材 URL。
- `backend/matrix_native_client.py#L1147-L1195`：同步图片生成返回图片字节和上游公网 URL，客户端超时默认 540 秒。
- `backend/matrix_native_client.py#L4615-L4639`：可灵数字人公网 URL / 本地关键帧分流；本地文件转 `data:image/...;base64,...` 后通过 JSON `params.image` 提交，音频必须为公网 URL。
- `backend/matrix_native_client.py#L7587-L7689`：公网 URL 检查、参考图大小上限、私网拒绝、关键帧轻量重试参数和旧中心素材限定路径内存转 data URL。
- `backend/matrix_native_client.py#L8649-L8717`：非口播公网素材门禁和口播片段在 TTS 前的头像可读性预检。
- `backend/matrix_native_client.py#L9391-L9500`：关键帧参考图临时构建、旧任务迁移、502/504 轻量重试、公网关键帧 URL 保留和本地库 URL 分离。
- `backend/central_server.py#L1254-L1330`：`PUBLIC_MEDIA_BASE_URL`、HMAC 签名、过期校验和素材 `publicUrls` 生成。
- `backend/central_server.py#L13399-L13461`：`/api/public-media/<material>/<file>` 签名访问、Range 支持和素材归属校验。
- `backend/central_server.py#L755-L790`：不复制文件体的 multipart 非文件字段解析，保留 `model` / `mode` 计费契约。
- `backend/central_server.py#L793-L930`：LK888 反代计费、multipart 适配和同步图片 480 秒上游超时。

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
- `backend/matrix_native_client.py#L12497-L12729`：登录页背景视频固定四项轮播、单次播放切换和背景绘制。
- `backend/matrix_native_client.py#L12779-L13092`、`backend/matrix_native_client.py#L13103-L13343`：登录页左侧品牌/卖点文案与右侧玻璃登录卡作为完整内容组居中排放，保留手机号/用户名登录、验证码、用户名免验证码和法律同意提交流程。
- `backend/matrix_native_client.py#L13351-L13398`、`backend/matrix_native_client.py#L13740-L13758`：登录成功后播放本地 `evil_eye_login.png` 星核过场，900ms 内完成遮罩淡入与图像全屏矩形缩放，结束后释放背景视频并进入主界面。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 登录协议与同意审计

- `backend/matrix_native_client.py#L63-L89`：内置协议读取、版本化同意 payload 和自动登录版本门禁。
- `backend/matrix_native_client.py#L12731-L12777`：可滚动《用户协议》/《隐私政策》双标签弹窗。
- `frontend/index.html#L8-L22`、`frontend/dist/index.html#L8-L22`：Web 静态页本地开发访问 `127.0.0.1:8088` 时，将 API 基址指向中心服 `127.0.0.1:9080`；生产 Web 仍保持同源 `/api`。
- `frontend/index.html#L160-L167`、`frontend/dist/index.html#L160-L167`：Web 登录表单要求勾选用户协议和隐私政策。
- `frontend/index.html#L2099-L2105`、`frontend/dist/index.html#L2099-L2105`：Web 登录使用当前客户端版本和法律版本常量。
- `frontend/index.html#L2768-L2768`、`frontend/dist/index.html#L2768-L2768`：未登录用户点击左侧业务模块时回到企业登录页并提示先登录；`accounts` 例外，作为 Web 登录入口放行。
- `frontend/index.html#L2854-L2862`、`frontend/dist/index.html#L2854-L2862`：Web 登录请求提交版本化 `legalConsent`，避免中心服返回 `legal_consent_required`。
- `backend/legal/user_agreement.md#L1-L85`：用户协议 v1.0，包含 `100 云豆 = 1 元`、AI/换脸/平台授权和争议解决条款。
- `backend/legal/privacy_policy.md#L1-L103`：隐私政策 v1.0，包含人脸、声音、Cookie、第三方 AI、保留期和用户权利。
- `backend/central_server.py#L2469-L2534`：同意 Schema 校验、HTTP 428 契约、服务端时间和 `legal.consent.accept` 审计。
- `backend/central_server.py#L14175-L14375`：登录、手机验证码登录、注册和会话刷新的法律版本强制门禁。

## 2026-07-25 素材发布多文件打开目录
- `backend/matrix_native_client.py#L4733-L4804`：素材发布页把本机素材路径查找拆成文件名解析、候选目录解析、已存在文件列表和打开目标选择；仍按视频优先、图片其次查找单个素材文件。
- `backend/matrix_native_client.py#L4793-L4804`、`backend/matrix_native_client.py#L4806-L4817`：点击“打开素材”时，若选中素材只有一个本机文件则打开该文件；若命中多个本机文件则打开共同目录，多个目录时优先打开素材候选根目录，否则打开第一个命中文件所在目录。
- `tests/test_native_publish.py#L122-L149`：新增多文件素材打开目录的回归测试，并更新文件查找源码契约测试。
- 验证：先运行新增测试观察旧实现因缺少 `_selected_material_open_target` 失败；实现后运行 `.venv-win\Scripts\python.exe -m unittest tests.test_native_publish tests.test_publish_util_safety -v` 通过 17 条用例。
- 回滚：回滚 `backend/matrix_native_client.py`、`tests/test_native_publish.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及中心服、数据库、OpenAPI 或 `migration.sql`。
## 测试

- `tests/test_client_logout.py#L18-L52`：Qt 独立重启成功契约和失败 `errorId` 回归。
- `tests/test_douyin_multi_account.py#L15-L90`：多个抖音账号并存、profile 不覆盖、发布按账号切换 Cookie/profile。
- `tests/test_legal_agreements.py#L1-L121`：主体/计费正文、同意 payload、过期拒绝、中心审计、登录链接、Web 法律同意和本地静态页 API 基址契约。
- `tests/test_login_background_playlist.py#L10-L29`：登录页背景视频清单、首条顺序和单次播放轮播契约。
- `tests/test_login_centered_layout.py#L9-L47`：登录页完整内容组居中、左侧营销文案恢复和成功动画契约保留。
- `tests/test_login_success_transition.py#L11-L49`：登录成功过场动画素材、成功/失败路径分流、900ms 时长、全屏缩放和 Qt opacity/scale 动画契约。
- `tests/test_video_replacement_v2.py#L197-L223`：关键帧同步图片 504 后使用 `1024x1024` 和更少参考图轻量重试。
- `tests/test_video_replacement_v2.py#L239-L299`：独立公网素材上传服务覆盖图片、视频，并确认音频继续走中心素材库。
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
- `backend/matrix_native_client.py#L6115-L6377`：同款替换页接入固定 `144x180` 主角缩略图；低置信度候选首项为“请选择并确认原片主角”且不带数据，必须人工选择后才能生成；产品图文案明确主角整身替换可选。
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
- `backend/matrix_native_client.py#L1478-L1599`：新增同款替换模型筛选 helper，白名单保留 `happyhorse-video-edit`、`kwvideo-v2-quannengcankao` 和参考视频模型；`kwvideo-v2-quannengcankao` 是 LK888 页面“SD 2.0 全能参考”的实际模型标识，页面卡片 ID 76 仅用于云灵前端内部选择，并只作为内置可选模型，不抢占未选择时的 Vidu/Wan 自动兜底顺序。
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
- `frontend/index.html#L2768-L2768`、`frontend/dist/index.html#L2768-L2768`：未登录时左侧栏继续拦截业务模块，但放行 `accounts` 作为登录入口，点击“账号矩阵”可直接进入账号矩阵页的登录表单。
- `tests/test_web_login_navigation.py#L10-L20`：新增源码契约测试，锁定未登录门禁必须允许 `accounts`，同时保留 `enterprise` 提示和业务模块拦截。
- 回滚：恢复 `frontend/index.html`、`frontend/dist/index.html`、`tests/test_web_login_navigation.py`、`CHANGELOG.md` 和本文档即可；不涉及中心服、数据库或 `migration.sql`。回滚后未登录用户会再次被挡在企业页外，无法直接从 Web 侧栏进入登录框。

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
- `backend/matrix_native_client.py#L19507-L19516`：登录成功后启动 `_start_balance_timer()`，每 30 秒调用 `refresh_balance()` 从中心服重新读取余额；`backend/matrix_native_client.py#L19555-L19557` 在退出登录时停止该定时器，避免登出后继续刷新旧会话。
- `backend/central_server.py#L731-L755`：新增 `lk888_proxy_task_flags()`，统一解析 LK888 task-status 的失败/完成状态，补充中文状态 `错误`、`失败`、`超时`、`已取消`、`取消`，并继续用真实媒体 URL 判断完成。
- `backend/central_server.py#L994-L1008`：LK888 反代轮询到任务状态后调用 `lk888_proxy_task_flags()`；失败时按原 `ref` 调用 `refund_user_by_ref()` 幂等退款，退款成功后移除 `STATE['gen_charges'][task_id]`。
- `tests/test_role_permissions.py#L231-L238`、`tests/test_billing_unified.py#L165-L169`：新增余额刷新定时器源码契约测试和 LK888 中文失败状态退款判断回归测试。先运行新增测试观察旧实现失败，再实现后转绿。
- 回滚：回滚 `backend/matrix_native_client.py`、`backend/central_server.py`、`tests/test_role_permissions.py`、`tests/test_billing_unified.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 即可；不涉及 OpenAPI、数据库结构或 `migration.sql`。运行中中心服需要重启后加载代码变更。

## 2026-07-25 中心状态文件防默认骨架覆盖保护
- `backend/central_server.py#L169-L185`：新增 `StateLoadError`、`StateWriteProtectionError` 和 `CENTRAL_ALLOW_STATE_REINIT` 显式重置开关。默认情况下，已有状态文件读失败不允许回落到默认企业/默认用户。
- `backend/central_server.py#L223-L239`：`_load_json()` 改为 `utf-8-sig` 读取，可兼容 UTF-8 BOM；若 `scheduler_state.json` 存在但解析失败，会记录 `STATE_LOAD_ERROR` 并抛出 `StateLoadError` 阻断启动。
- `backend/central_server.py#L242-L264`：`_state_write_guard()` 在写入前检查现有状态；当现有企业/用户/成员关系明显多于 1 条时，拒绝把 `org-default/user-owner` 的默认骨架写回覆盖。
- `backend/central_server.py#L276-L349`：新增 `backup_state_file_on_startup()`，中心服初始化 `STATE` 前先复制 `scheduler_state.json.bak-startup-*`，保证启动级可回滚。
- `tools/repair_scheduler_state.py#L1-L89`：新增状态修复工具，支持只读校验、`--normalize` 无 BOM 重写、`--restore <backup>` 验证后恢复，并在写入前自动备份当前文件。
- `tests/test_billing_unified.py#L167-L218`：覆盖启动前备份、UTF-8 BOM 读取、坏 JSON 阻断启动、完整状态禁止被默认骨架覆盖。
- 回滚：回滚 `backend/central_server.py`、`tools/repair_scheduler_state.py`、`tests/test_billing_unified.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `docs/DEPLOYMENT.md` 即可；不涉及 OpenAPI、数据库结构或 `migration.sql`。回滚后坏状态文件可能再次被默认骨架覆盖。

## 2026-07-25 小红书图文同款

- `backend/xhs_note_replacement.py#L9-L20`：功能开关、任务 ID 与本地任务目录。
- `backend/xhs_note_replacement.py#L53-L87`：从小红书素材或 `sourceNote` 构建图文结构模板。
- `backend/xhs_note_replacement.py#L124-L155`：按用户替换图生成槽位映射，缺图槽位标记为 AI 占位。
- `backend/xhs_note_replacement.py#L167-L188`：本地 JSON 任务原子保存与读取。
- `backend/xhs_note_replacement.py#L192-L223`：生成 `image_note` 草稿素材 payload 和 AI 图片审核元数据。
- `backend/xhs_note_replacement.py#L225-L231`：小红书图文 V1 发布阻断错误码。
- `backend/xhs_note_replacement.py#L234-L286`：4 图图文同款无副作用冒烟 helper。
- `backend/api_server.py#L4789-L4927`：本地 `/api/xhs-note-replacement/*` 模板、预览、确认和保存草稿接口。
- `backend/central_server.py#L5728-L5731`：中心服发布预检复用 `image_note` blocker。
- `backend/matrix_native_client.py#L4129-L4162`：从小红书下载任务结果中提取素材文件，过滤掉没有用户图片的任务结果。
- `backend/matrix_native_client.py#L4165-L4276`：解析本机图片、中心素材 URL 和仅带签名 URL 的图片；过滤视频等非图片文件，中心素材请求才携带登录头，外部 CDN 不外发登录凭据；模板阶段即可生成槽位行。
- `backend/matrix_native_client.py#L4319-L4478`：内容采集页“图文同款”按钮校验单条小红书链接，复用下载任务，下载完成后提取图片素材、切换页面并发送 `xhs_note_replace_start`；无图片时提示先下载笔记。
- `backend/matrix_native_client.py#L7433-L7943`：原生“图文同款”独立页面接收采集事件，立即显示全部原图缩略图和图片数量，支持点击查看大图，并自动读取结构；新任务清理旧笔记、替换图、槽位和文案状态。
- `backend/matrix_native_client.py#L7607-L7664`：远程原图在后台加载，限制单图 20 MB；失败记录脱敏结构化日志 `xhs_note_source_image_load_failed`，旧任务图片响应由 generation 标识丢弃。
- `backend/matrix_native_client.py#L7753-L7824`：读取图文结构包含 30 秒超时、明确缺图提示和旧模板请求失效处理；模板读取成功后无需先生成预览即可显示图片槽位。
- `backend/matrix_native_client.py#L11288-L11288`：资产库允许 `note_template` 类型。
- `backend/matrix_native_client.py#L17939-L17961`：资产库仅展示本地收藏，过滤项新增“图文模板”。
- `backend/matrix_native_client.py#L19329-L19329`：原生导航新增“🧩 图文同款”。
- `frontend/index.html#L466-L621`：Web 端采集结果、素材卡和独立页面入口。
- `frontend/index.html#L2343-L2386`：Web 端采集结果“图文同款”先通过本地浏览器下载 `/api/xhs/download`，并按图片扩展二次过滤，只在下载素材含图片文件时进入图文同款；缺图提示“未找到图片素材，请先下载笔记”。
- `frontend/index.html#L2392-L2426`：Web 端读取图文结构统一走 `loadXhsNoteTemplateFromMaterial()`，读取前二次过滤图片文件，带 30 秒 `Promise.race` 超时；有 `AbortController` 时同时中断请求，空 `imageSlots` 显示缺图提示。
- `frontend/index.html#L2430-L2465`：Web 端预览、AI 确认和保存草稿动作。
- `tests/test_xhs_note_replacement.py#L346-L357`：4 图图文同款冒烟测试。
- `tests/test_xhs_note_replacement.py#L230-L323`：覆盖 Web 端采集结果“图文同款”先下载、过滤图片文件再读取结构；执行真实前端方法验证非图片不进入模板；覆盖无 `AbortController` 时仍能触发超时提示。
- `tests/test_xhs_note_replacement.py#L360-L373`：覆盖原生采集页一键图文同款、读取结构超时、下载完成跳转和“未找到图片素材，请先下载笔记”提示。
- `tests/test_xhs_note_replacement.py#L376-L644`：覆盖图片过滤与 URL 解析、页面事件接收、本机/中心缩略图、外部签名 URL 凭据隔离、点击大图、模板槽位即时显示和新任务状态清理。

验证：`.venv-win\Scripts\python.exe -m unittest tests.test_api_download_contract tests.test_material_repair tests.test_native_publish tests.test_xhs_note_replacement -v` 通过 94 项；`.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_xhs_note_replacement.py` 退出码 0。

回滚：恢复 `backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和实施计划中的 Task 8 记录并重启桌面客户端；不涉及数据库、中心服接口、OpenAPI 或 `migration.sql`。
