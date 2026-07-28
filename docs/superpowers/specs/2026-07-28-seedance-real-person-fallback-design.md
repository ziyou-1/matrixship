# Seedance 真人参考图自动回退设计

## 背景

同款替换的漫剧项目模式已能生成首尾帧和台词音频，但火山官方 Seedance 2.0 在参考图被识别为真人时会返回 `InputImageSensitiveContentDetected.PrivacyInformation`。当前实现把该同步提交错误直接登记为失败任务，导致没有片段视频，也无法进入最终拼接。

## 目标

- 仅对明确的火山真人参考图隐私拒绝执行一次自动回退。
- 回退到 `kling-avatar-image2video`，使用当前分镜首帧和已生成的完整台词音频，优先保证声音与口型同步。
- 保存请求模型、实际模型和回退原因，并在本地同款替换页面显示清楚。
- Seedance 提交失败后退回对应计费；备用模型按自身模型重新计费。
- 任一异常都保留结构化、脱敏、可追踪的错误信息。

## 非目标

- 不绕过或弱化任何平台内容审核。
- 不对其他 Ark 400、网络错误、余额错误或普通模型失败自动切换。
- 不保证 Kling Avatar 与 Seedance 相同的动作幅度或多图控制能力。
- 不改变旧任务 JSON 的打开和查看行为。

## 方案对比

| 方案 | 真人参考 | 配音与口型 | 多图与动作 | 结论 |
|---|---:|---:|---:|---|
| Kling Avatar 自动回退 | 支持授权真人链路 | 强，直接使用完整配音 | 中，主要依赖当前分镜首帧 | 采用 |
| Vidu Q3 自动回退 | 较适合多参考图 | 弱，不能保证现有配音驱动口型 | 强 | 不采用 |
| 仅提示用户手动换模型 | 取决于用户选择 | 取决于模型 | 取决于模型 | 不满足自动恢复目标 |

## 远程漫剧服务

### 触发条件

在 Ark Seedance 视频任务同步提交异常中同时满足以下条件才回退：

1. 当前任务是分镜视频任务。
2. 当前模型属于官方 Ark Seedance 模型集合。
3. 错误文本包含精确错误码 `InputImageSensitiveContentDetected.PrivacyInformation`。
4. 当前调用尚未执行过真人参考图回退。
5. `COMIC_REAL_PERSON_VIDEO_FALLBACK_MODEL` 配置为非空且不是当前 Ark 模型，默认值为 `kling-avatar-image2video`。

### 数据流

1. Seedance 提交失败。
2. 退回 Seedance 本次预扣费用。
3. 复用已经准备好的分镜参数，其中包含首帧、尾帧、角色/场景/道具参考和完整台词音频。
4. 使用 Kling Avatar 重新进入现有视频网关提交链路；模型适配层选取当前分镜首帧作为主体图，并把完整台词音频写入数字人音频字段。
5. 对备用模型重新计费并登记远程任务。
6. 给任务补充 `requested_model`、`actual_model`、`fallback_model`、`fallback_reason` 和 `fallback_applied`。

回退最多一次，防止递归或重复扣费。备用模型失败时保留 Seedance 拒绝原因和备用模型失败原因。

## 本地客户端

- 轮询远程任务时读取回退元数据。
- 片段保存请求模型、实际模型和回退原因。
- 进度提示显示“Seedance 拒绝真人参考图，已切换 Kling Avatar，正在生成视频”。
- 备用模型也失败时，显示“Seedance 真人参考图被拒绝；Kling Avatar 生成失败”的组合错误，不再只显示通用错误编号。
- 成功后片段状态显示实际使用的模型，最终拼接流程保持不变。

## 可观测与错误处理

远程服务输出结构化 JSON 日志，至少包含事件名、项目 ID、分镜 ID、请求模型、备用模型、脱敏错误码和任务 ID，不记录 API Key、登录令牌或完整素材签名参数。

新增事件：

- `comic_storyboard_video_privacy_fallback_started`
- `comic_storyboard_video_privacy_fallback_submitted`
- `comic_storyboard_video_privacy_fallback_failed`

## 测试

1. 单元测试先复现 Ark 真人隐私错误，确认当前实现返回失败任务。
2. 验证只有精确隐私错误会切换到 Kling Avatar。
3. 验证备用提交收到首帧和完整台词音频，并且只执行一次。
4. 验证 Seedance 计费退款、Kling Avatar 独立计费。
5. 验证任务元数据和本地前端提示。
6. 验证其他 Ark 400 不自动回退。
7. 部署后用项目 294 的一个失败片段做真实冒烟测试，再验证视频可下载；不自动执行完整任务的全部片段。

## 部署与回滚

- 部署前备份远程 `/root/AI-CanvasPro/server.py`，文件名包含时间戳。
- 语法检查和定向测试通过后，仅重启远程 8777 漫剧服务并检查健康状态。
- 不重启本地客户端；本地修改由用户后续手动重启生效。
- 回滚时恢复本次备份，重启远程 8777 服务，并把 `COMIC_REAL_PERSON_VIDEO_FALLBACK_MODEL` 设为空可立即关闭自动回退。

## 风险

- Kling Avatar 更重视口型同步，动作和多素材控制可能弱于 Seedance。
- 当前分镜首帧质量直接影响备用视频；若首帧本身人物、产品或场景不正确，备用模型不会自动修复构图。
- 上游仍可能因其他审核、计费或参数原因失败，这些错误不会被本方案掩盖。
