# Digital Human Forced Scene Background Design

## Goal

数字人口播中，场景图从“弱参考”改为明确的可选强制换背景能力：不上传场景图时保持原数字人口播链路；上传场景图时必须先合成人物站在该场景中的新形象图，再生成口播视频。

## Requirements

- 上传场景图后，系统必须执行场景版人物图合成，不能只把场景图作为提示词或弱参考传给数字人模型。
- 场景版人物图合成后，必须用视觉模型比对上传场景和合成图背景；背景不一致时，先按上传场景唯一背景约束重试一次，二次仍不一致才停止并退费，不继续生成原背景视频。
- 合成和质检都优先使用本地上传场景图的 data URL 作为视觉参考，公网 URL 作为可访问性和后续链路依据。
- 未上传场景图时，不做场景合成，继续使用原人物形象图生成数字人口播。
- 场景图必须是远程模型可读取的公网 URL；本地或私网 URL 不得继续进入强制换背景链路。
- 页面文案必须明确“上传场景图（强制换背景）”。
- 生成状态必须显示“正在合成场景版人物图”。

## Architecture

新增后端 helper，接收人物图和场景图，调用现有 `lk888_image_result(..., image_urls=[avatar, scene])` 生成场景版人物图，并要求返回公网 URL。随后调用视觉质检 helper，对上传场景和合成图背景做一致性判断。`generate_digital_human()` 在 TTS 前执行合成和质检，成功后把合成图作为新的数字人人物图传入 `lk888_digital_human()`。

## Data Flow

1. 用户上传人物形象。
2. 用户可选上传场景图。
3. 点击生成。
4. 如果没有场景图：人物形象图 + 音频进入原数字人链路。
5. 如果有场景图：人物形象图 + 场景图先生成场景版人物图。
6. 用视觉模型比对上传场景和场景版人物图；通过后再合成或使用音频。
7. 场景版人物图公网 URL + 音频进入数字人链路。
8. 任何场景版人物图生成失败都会停止本次任务并退款；场景一致性质检失败先自动严格重试一次，二次失败后才停止并退款。

## Error Handling

- 场景图不是公网可读 URL：抛出 `digital_human_scene_not_public`。
- 场景图合成结果没有公网 URL：抛出 `digital_human_scene_avatar_not_public`。
- 合成图背景未采用上传场景：抛出 `digital_human_scene_background_mismatch`，前台显示中文原因。
- 图片生成上游失败：保留原始异常信息进入现有错误处理和退款链路。

## Testing

- 单元测试覆盖上传公网场景图时必须先调用场景合成 helper，并把合成后的公网图传给数字人生成。
- 单元测试覆盖合成图背景不一致时先严格重试一次，并在二次失败时停止在 TTS 前。
- 单元测试覆盖合成优先使用本地上传场景图 data URL。
- 单元测试覆盖未上传场景图时不调用场景合成 helper。
- 单元测试覆盖场景图不是公网 URL 时阻断并不调用 TTS。

## Rollback

回滚范围为 `backend/matrix_native_client.py`、`tests/test_video_replacement_v2.py`、`CHANGELOG.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md` 和本设计文档。紧急回滚可恢复这些文件到上一稳定版本。
