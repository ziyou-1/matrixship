# Video Replacement Identity Modes Design

## 背景

当前同款替换在上传三张授权人物图后会自动启用本地 FaceFusion。实际任务 `58e1e09bdbdb411abfb307c99b331d07` 中，远程同款视频已经生成成功，但三个非口播片段都在 FaceFusion 后处理阶段跑满 `FACEFUSION_TIMEOUT_SEC=420` 秒后超时，并回退到远程结果。用户看到的错误编号 `err-147651493a504bba` 对应第 2 段 `video_replace_non_talking_facefusion_failed`，不是远程生成失败。

问题根因是产品语义和实现不一致：前台曾提示默认关闭本地换脸，但代码中 `_replacement_enable_facefusion()` 对上传人物图场景直接返回 `True`。这会导致日常生产默认进入慢速本地换脸链路。

## 目标

- 将人物一致性能力拆成三种明确模式：快速、标准、高一致。
- 默认使用标准模式，避免每段默认卡在 FaceFusion。
- 保留高一致模式给需要本地换脸增强的用户显式启用。
- 让任务 JSON、前台文案、日志和文档都能追溯当前模式。
- 保持旧任务兼容和可回滚。

## 非目标

- 不更换远程视频生成模型供应商。
- 不引入新的数据库表。
- 不承诺远程同款生成能百分百锁定人物身份。
- 不把本地 FaceFusion 开发环境视为生产商业授权环境。

## 模式定义

### 快速模式

字段值：`identityMode=fast`

行为：
- 上传人物图只作为远程参考图。
- 不执行本地 FaceFusion。
- 人脸一致性 QC 可执行，但不作为强门禁。
- 适合快速出片和批量预览。

用户预期：
- 生成速度最快。
- 人物只能保证“尽量像上传人物”，不能保证逐帧身份一致。

### 标准模式

字段值：`identityMode=standard`

行为：
- 默认模式。
- 上传人物图作为远程参考图。
- 不执行本地 FaceFusion。
- 执行媒体、音频、人物、产品、Logo 和场景 QC。
- 媒体损坏、音频缺失、静音仍然阻断。
- 人脸、产品、场景不一致默认标记为 `review_warning`，进入人工审核。
- 若 `VIDEO_REPLACE_STRICT_VISUAL_QC=1`，视觉不一致仍可阻断。

用户预期：
- 日常生产首选。
- 不会因为本地 FaceFusion 超时而拖慢整单。
- 通过 QC 和人工审核管理人物一致性风险。

### 高一致模式

字段值：`identityMode=high`

行为：
- 远程同款生成成功后，非口播片段执行本地 FaceFusion。
- talking 数字人口播片段在下载数字人视频后可执行本地 FaceFusion。
- FaceFusion 失败或超时时不让片段硬失败，回退到远程或数字人原结果。
- 回退时写入 `facefusionStatus=fallback`、`facefusionError`、`facefusionErrorId` 和 `qcWarnings[].code=facefusion_failed`。
- 最终仍进入 QC 和人工审核。

用户预期：
- 人物一致性上限最高。
- 速度最慢，依赖本地 FaceFusion 环境、片段长度、机器性能和许可证状态。

## 数据模型

新增任务字段：

```json
{
  "identityMode": "standard"
}
```

允许值：
- `fast`
- `standard`
- `high`

旧字段兼容：
- 旧任务若存在 `identityMode`，优先使用它。
- 旧任务若没有 `identityMode` 但 `enableFaceFusion=true`，按 `high` 处理。
- 旧任务若没有 `identityMode` 且 `enableFaceFusion` 不为 true，按 `standard` 处理。

保留字段：
- `enableFaceFusion` 可继续写入，作为旧逻辑和文档兼容字段。
- 新任务中 `enableFaceFusion` 应由 `identityMode == "high"` 派生，不再由“是否上传人物图”自动打开。

## UI 设计

在同款替换页生成区增加“人物一致性模式”控件，默认选中“标准”。

建议文案：
- 快速：`快速：只远程生成`
- 标准：`标准：远程生成 + 一致性审核`
- 高一致：`高一致：远程生成 + 本地换脸增强`

当选择高一致模式时：
- 若未选择原片目标人物，阻止开始并提示选择人物候选。
- 执行 FaceFusion preflight；不通过时在上传素材和扣费前阻止。

当选择快速或标准模式时：
- 不要求选择原片目标人物。
- 不执行 FaceFusion preflight。
- 仍要求上传三张授权人物图，除非用户勾选“纯产品视频（无人物）”。

## 执行流

### 开始生成

1. 读取 UI 的 `identityMode`。
2. 构建 job 时写入 `identityMode`。
3. 派生 `enableFaceFusion = identityMode == "high"`。
4. 只有高一致模式需要 `targetFaceReferencePath` 和 FaceFusion preflight。

### 非口播片段

1. 裁切源片段并上传公网 URL。
2. 调用远程参考图视频候选链。
3. 下载远程编辑结果。
4. 若 `identityMode != high`，直接回填音频并进入 QC。
5. 若 `identityMode == high`，执行 FaceFusion，失败后回退远程结果。
6. 执行音频和视觉 QC。
7. 进入人工审核。

### talking 片段

1. 生成关键帧。
2. 执行 TTS 和数字人口播。
3. 下载数字人视频。
4. 若 `identityMode == high` 且上传人物图，执行 FaceFusion，失败后回退数字人原视频。
5. 执行 QC。
6. 进入人工审核。

## 错误处理与文案

替换现有 `facefusion_timeout` 展示文案。

建议文案：

```text
本地换脸增强超时：已回退远程同款结果，可继续审核；如需提高一致性，请缩短片段、调低换脸配置，或切换高性能换脸环境。
```

在快速/标准模式中不应出现“执行人脸替换”阶段。

当用户问“为什么人物不完全像”时，产品解释应为：
- 快速和标准模式依赖远程模型参考图，只能尽量保持人物特征。
- 标准模式通过一致性 QC 标出风险。
- 高一致模式才会执行本地身份替换增强。

## 可观测性

结构化日志和任务 JSON 应包含：
- `identityMode`
- `enableFaceFusion`
- `facefusionStatus`
- `facefusionErrorId`
- `qcWarnings`

进度事件中应显示当前模式，至少在任务状态摘要或片段状态文本中可见。

## 回滚

本变更不涉及数据库迁移。

回滚方式：
- 代码回滚到上一稳定快照。
- 或通过配置/默认值临时等价回滚：
  - 若要恢复旧自动 FaceFusion 行为，将默认模式改为 `high`。
  - 若要完全规避 FaceFusion，将默认模式保持 `standard`。

旧任务可继续读取：
- `identityMode=high` 或旧 `enableFaceFusion=true` 的任务仍会尝试 FaceFusion。
- `identityMode=standard/fast` 的任务不再默认进入 FaceFusion。

## 测试策略

新增或更新 `tests/test_video_replacement_v2.py`：

- 默认 job 为 `identityMode=standard`。
- 上传三张人物图不会自动启用 FaceFusion。
- `identityMode=fast` 不调用 FaceFusion，并进入 QC/审核链路。
- `identityMode=standard` 不调用 FaceFusion，但保留视觉 QC。
- `identityMode=high` 调用 FaceFusion，并在超时时回退远程结果。
- 旧任务 `enableFaceFusion=true` 兼容为高一致模式。
- `facefusion_timeout` 文案改为“本地换脸增强超时，已回退远程同款结果”。

运行验证：

```bash
.venv/bin/python -m unittest tests.test_video_replacement_v2 -v
.venv/bin/python -m unittest tests.test_video_replacement -v
.venv/bin/python -m py_compile backend/matrix_native_client.py
```

## 文档更新范围

实施时同步更新：
- `docs/ARCHITECTURE.md`
- `docs/API_REFERENCE.md`
- `docs/DEPLOYMENT.md`
- `docs/TROUBLESHOOTING.md`
- `docs/IMPLEMENTATION.md`
- `CHANGELOG.md`

`docs/IMPLEMENTATION.md` 中所有涉及 `backend/matrix_native_client.py#L...` 和 `tests/test_video_replacement_v2.py#L...` 的行号必须在改动后重新计算。
