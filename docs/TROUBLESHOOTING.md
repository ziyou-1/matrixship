# Troubleshooting

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
- 修复：现在只按当前片段时间范围提取镜头拆解中的画面、人物、产品、动作、道具、场景和节奏，并前置发送；“字幕/信息”、OCR、原片字幕和原片口播转写会被过滤。AI 音色和上传完整配音模式下，人物台词和最终字幕都只以片段表的用户口播稿为准；原片声音模式才保留原音和原台词。
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
- 新规则：`source` 原片声音模式保持原链路，口播稿不应随意改台词；`tts` AI 音色配音模式会把每段口播稿放入 LK888 视频编辑 prompt 前部，远程生成后本地用所选音色 TTS 替换该片段音轨；`uploaded` 上传完整配音模式要求每段口播稿与上传音频一致，远程生成后按片段时间裁切上传配音并本地替换音轨。
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
- 根因：中心状态文件里当时只有 `org-default / 默认企业` 和 `org-9918a7f2bae2 / 用户8702的企业`，没有 `org-toyota / 丰田汽车`；同时 boss、user01、user02 的 membership 都绑定在 `org-default`，所以页面显示默认企业是按真实数据渲染，不是前端显示错误。
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
- 修复：`backend/matrix_native_client.py#L3032-L3451` 新增“企业中心 -> 团队成员”页，管理员可切换企业并添加/邀请成员，企业家固定当前企业，普通用户仍隐藏企业中心；`backend/matrix_native_client.py#L17579-L17585` 把原企业中心改为“总览 / 团队成员”标签页。
- 操作：管理员登录后进入“企业中心 -> 团队成员”，先选择企业，再点击“添加成员”或“邀请成员”；企业家登录后进入同一位置，只能管理自己企业；普通用户无需操作，也不应看到该入口。
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
- 排查：查看任务 JSON 的 `audioMode`、片段 `duration/script/ttsDurationSec/ttsTimingStatus/ttsTimingError`。如果 `audioMode=source`，使用的是原片声音，不走这套 TTS 校验；如果 `audioMode=uploaded`，整条音轨仍按最终成片时长校验。
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
- 排查：查看任务 JSON 的 `audioMode`、`voiceId`、`replacementAudioPath`、`replacementAudioUrl`、`finalAudioMode` 和片段 `ttsUrl/ttsPath`。`audioMode=source` 表示仍保留原片声音，`tts` 表示逐段 AI 音色配音，`uploaded` 表示最终整条音轨替换。
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
- 对照失败：只发送通用 `video_urls + image_urls` 时任务仍返回视频，但人物参考图被忽略，输出仍为原男性主角。根因是兼容层没有把通用 `image_urls` 映射为模型需要的 `images`，不是前端上传失败。
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
- 根因：主角整身替换的目标是把原片主角替换为上传人物，同时保留原片产品、场景、动作和音轨；产品图不是该模式的必需输入。低置信度时如果把第一张候选帧自动设为当前项，用户没有真正确认原片主角。
- 修复：`VIDEO_REPLACE_PRINCIPAL_REPLACEMENT=1` 的任务允许产品图为空；页面显示原片主角缩略图，低置信度首项为无数据占位，必须选择候选帧。没有产品参考图时仍会将待审核视频、原片片段和人物参考图送入主角视觉 QC，且不会虚构不存在的场景媒体。
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
## 2026-07-20 读取评论返回结果但前端显示 task_timeout

- 现象：网页版内容采集点击“看评论”后显示 `读取失败: task_timeout`；中心服 `/api/local-browser/status` 可看到 Windows 本地节点在线，且对应 `douyin.comments` 任务已有 `result.ok=true` 和评论结果，但任务状态仍停在 `running`。
- 根因：抖音评论接口返回的 `result.comments` 是对象结构，例如 `{status_code, comments:[...]}`。中心服 `local_browser_result()` 保存任务时把 `result.comments` 当列表执行 `[:500]`，触发 `KeyError: slice(...)`。异常发生前任务已被写成 `running` 并保存了部分结果，后续没有机会标记 `done`，前端轮询直到超时。
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
## LK888 访问不了本地上传图片/视频

- 现象：产品图、人物图、场景图或源视频片段上传后，本地客户端拿到的是中心服 `/api/library/file/...` 或本地/内网 URL，LK888 远程模型无法拉取，导致同款替换、数字人或参考图视频生成失败。
- 根因：原链路只依赖中心素材库 `publicUrls`；当中心服未配置公网素材代理时，远程模型拿不到本地上传内容。新部署的 `https://img.yunlingai.net/api/upload` 能提供稳定公网图片和视频 URL，但客户端此前只把图片接入该服务。
- 修复：`backend/matrix_native_client.py#L814-L956` 新增独立公网素材上传分支。配置 `UPLOAD_API_URL` 和 `UPLOAD_TOKEN` 后，`upload_asset_url(..., mtype="image"|"video")` 会优先带 `Authorization: Bearer <UPLOAD_TOKEN>` 上传图片或视频，并返回 `https://img.yunlingai.net/uploads/...` 给 LK888；音频等其他素材仍走中心素材库。
- 配置：本机环境变量或 `backend/.env` 中设置：
  - `UPLOAD_API_URL=https://img.yunlingai.net/api/upload`
  - `PUBLIC_UPLOAD_BASE_URL=https://img.yunlingai.net/uploads`
  - `PUBLIC_IMAGE_BASE_URL=https://img.yunlingai.net/uploads`
  - `UPLOAD_TOKEN=<server token>`
- 服务端限制：公网服务允许 `jpg/jpeg/png/webp/gif/mp4/mov/webm`，应用与 Nginx 单文件上限均为 500MB。`400 unsupported_file_type` 表示扩展名不在白名单；`413 file_too_large` 表示超过上限。
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
- 内容校准：运营主体为“云灵星图数字科技有限公司”，云豆规则为 `100 云豆 = 1 元`；协议 v1.0 生效日期为 2026-07-15。

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
## Web 版点击左侧栏后仍停在企业页

- 现象：访问 `http://127.0.0.1:8088/` 后点击左侧业务模块，看起来没有切换页面。
- 根因：这是前端的未登录门禁。`frontend/index.html#L2768-L2768` 会在没有会话 Token 时拦截业务模块；旧逻辑连 `accounts` 也拦截，导致用户到不了放置登录框的账号矩阵页。此前 Web 登录请求又没有提交中心服要求的 `legalConsent`，所以即使输入账号密码也会被 `/api/auth/login` 以 HTTP 428 拒绝，最终表现成左侧按钮一直“没反应”。
- 修复：`frontend/index.html#L2768-L2768` 和 `frontend/dist/index.html#L2768-L2768` 放行 `accounts` 作为 Web 登录入口，其余业务模块继续拦截；`frontend/index.html#L160-L167` 增加 Web 登录协议勾选；`frontend/index.html#L2854-L2862` 提交版本化 `legalConsent`；`frontend/index.html#L8-L22` 让 8088 静态 Web 本地开发页请求 9080 中心服，避免请求打到静态服务端口。
- 冒烟结果：未登录点击“账号矩阵”可看到手机号/用户名、登录密码、协议勾选和“登录企业账号”；点击“风控中心”等业务模块仍回到企业中心并提示先登录。当前本地管理员密码约定为 `admin/test123456`，由中心服启动环境 `CENTRAL_ADMIN_PASSWORD` 注入。
- 回滚：恢复 `frontend/index.html`、`frontend/dist/index.html`、`tests/test_web_login_navigation.py`、`tests/test_legal_agreements.py` 和本排障记录到上一稳定快照；不涉及数据库迁移或 `migration.sql`。
- 验证命令：
  - `.venv-win\Scripts\python.exe -m unittest tests.test_web_login_navigation tests.test_legal_agreements tests.test_auth_login_modes`
  - 浏览器刷新 `http://127.0.0.1:8088/`，确认登录区显示协议勾选框，页面 `MATRIX_API_BASE` 为 `http://127.0.0.1:9080`。

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
- `facefusion_requires_three_source_faces`：仅旧任务或高一致 FaceFusion 模式要求正脸、左约 45°、右约 45° 三张授权照片；新主角整身模式改为 1-3 张人物参考图，至少一张全身图。
- `principal_actor_extract_failed` / `principal_actor_extract_invalid_response`：原片主角视觉定位失败或返回非结构化 JSON。当前客户端会记录 `video_replace_principal_actor_extract_failed`，并把已抽取的候选帧带回页面；若 `principalActor.status=manual_required`，在“原片主角确认”下拉框选择正确主角帧后再开始生成。若页面仍直接显示“生成方案失败”，说明运行中的本地客户端未加载新代码，需要重启本地客户端。
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
- 回归测试：`tests/test_workflow_resilience.py#L30-L72` 覆盖多模态失败兜底和视频下单前脚本扩写，避免再次把空/短剧本传给 `vidu-jieshuoman`。
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
- 当前规则：`/api/billing/charge` 统一由中心服按 `capability` 定价；已知能力不信任客户端 `amount`。旧云豆钱包直接扣云豆，主库钱包按 `100 云豆 = 1 元` 与 `MAINDB_YUAN_TO_POWER` 换算为算力后原子扣减。
- 退款规则：失败退款必须携带原扣费 `ref`；中心服只退真实发生过且未退过的流水。重复退款返回成功但 `refunded=0`，不会凭空加款。
- 排查：查看 `/api/billing/ledger` 是否有对应 `ref` 的负数流水；主库通用扣费流水会标记 `wallet=maindb_generic`。余额不足应返回 HTTP 402 和 `insufficient_balance`。
- 验证命令：`python -m unittest tests.test_billing_unified tests.test_openapi_contract -v`。
- 回滚：回滚 `backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_billing_unified.py`、`tests/test_openapi_contract.py`、`docs/openapi.yaml`、`docs/API_REFERENCE.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md`；不涉及数据库结构或 `migration.sql`。
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
## 2026-07-25 数字人口播上传音频 video_replacesoundnot_public
- 现象：数字人口播使用上传配音生成时，LK888 返回 `video_replacesoundnot_public` / `video_replace_sound_not_public`，系统中间合成图已生成，但音频上传后无法继续生成视频。
- 根因：`upload_asset_url()` 只有图片和视频会优先走公网素材上传服务；音频 `mtype=audio` 落到中心素材库上传，返回地址可能不是 LK888 远程模型可直接抓取的公网音频。
- 修复：音频上传也纳入公网素材上传分支，数字人口播捕获 `video_replace_sound_not_public` 时显示中文可操作提示。
- 验证：`python -m py_compile backend/matrix_native_client.py`；目标检查确认上传分支包含 `audio`，并存在中文错误提示分支。
- 回滚：回滚 `backend/matrix_native_client.py` 和本文件；回滚后上传音频仍可能通过中心素材库返回非公网地址，导致 LK888 拒绝生成。


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

- 在「内容采集」中选中单条小红书链接，点击「图文同款」后，Web 端和原生客户端都会先下载该笔记的用户图片；Web 端会按图片扩展二次过滤，再自动进入图文同款页面并读取图文结构；即使运行环境没有 `AbortController`，30 秒超时仍会给出明确提示。
- 如果提示「未找到图片素材，请先下载笔记」，说明当前下载结果没有用户发布图片；请确认这条笔记确实是图文笔记，必要时先点击「下载」检查素材。页面静态图、搜索图标和横幅不会被当作笔记素材。
- 如果提示「读取图文结构超时」，请确认本机执行引擎在线，并确认笔记已经下载完成后重试。单次读取最多等待 30 秒，超时后可再次点击「读取图文结构」。
- 回滚：回滚 `frontend/index.html`、`backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和 `CHANGELOG.md` 即可；不涉及中心服、数据库或 `migration.sql`。

## 原生图文同款跳转后不显示已下载内容（2026-07-27）

- 现象：在桌面客户端“内容采集”选中小红书链接并点击“图文同款”，页面已跳转，但来源素材、已下载图片和图片槽位为空。
- 根因：原生 `XhsNoteReplacementPage` 之前没有连接全局 `BRIDGE.payload`，因此没有接收 `xhs_note_replace_start`；页面也缺少原图缩略图区域，且槽位表只读取生成预览后的 `slotMappings`。
- 修复：页面接收采集事件后立即清理上一条任务，带入素材信息，显示全部下载图片及数量，自动读取结构；模板返回后直接按 `template.imageSlots` 显示槽位，点击缩略图可查看大图。
- 远程图片：本机文件优先直接读取；中心服 `/api/library/file/` 图片使用当前登录态后台加载，单图上限 20 MB。外部签名 CDN 地址不会携带 `X-Matrix-User-Token` 或企业标识，中心认证请求不自动跨域重定向。
- 观测：远程图片加载失败会记录 JSON 结构化事件 `xhs_note_source_image_load_failed`，包含脱敏后的 `materialId`、`imageIndex`、`fileName` 和异常堆栈，不记录签名 URL 或凭据。
- 排查：先确认页面“原笔记图片”数量；若为 0，检查下载结果 `material.files` 是否包含 JPG/PNG/WebP 等图片。若数量正确但缩略图加载失败，按上述事件名查询客户端日志，并确认中心素材文件仍可访问。
- 生效：Python 桌面客户端不会热加载源码。修改后必须关闭当前客户端并重新启动，再从“内容采集”点击“图文同款”验证。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteNativeDisplayTests -v`，再运行 `.venv-win\Scripts\python.exe -m unittest tests.test_api_download_contract tests.test_material_repair tests.test_native_publish tests.test_xhs_note_replacement -v` 和 Python 编译检查。
- 回滚：恢复 `backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 与 Task 8 计划记录并重启客户端；不涉及数据迁移，已下载素材和现有图文任务无需删除。
