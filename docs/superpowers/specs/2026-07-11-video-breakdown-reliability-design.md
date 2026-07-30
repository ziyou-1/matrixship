# 视频深度分解可靠性增强设计

## 文档状态

- 日期：2026-07-11
- 状态：已实施，待最终真实素材端到端验证
- 适用范围：Mac 本地客户端、127.0.0.1:9081 本地执行引擎、127.0.0.1:9080 中心服
- Git 状态：当前项目目录不是 Git 仓库，无法提交设计文档；实施前使用时间戳备份和 SHA256 清单保证可回滚、可追溯

## 1. 背景与根因

当前「分解视频」报告无法识别画面、字幕和口播。现场证据如下：

- 下载得到的 `video.mp4` 只有 350 字节，实际内容是 OpenResty 返回的 `403 Forbidden` HTML。
- 裸请求抖音 CDN 返回 `403 text/html`；同一地址携带浏览器 `User-Agent`、`Referer` 和 `Range` 后返回 `206 video/mp4`。
- 下载器未检查 HTTP 状态、Content-Type 和媒体格式，直接将响应写成 `.mp4`。
- 本地和中心资产库只按扩展名接收文件，因此错误 HTML 被当成视频入库。
- 分解页只检查路径和扩展名；ffmpeg 探测失败后仍继续调用 AI，最终只能生成缺少输入的通用报告。
- 当前虚拟环境缺少 `pytesseract`、`Pillow` 和系统 Tesseract 中文语言包。
- `_transcribe_breakdown_audio()` 是明确返回 `disabled` 的占位实现。

## 2. 产品目标

实现稳定的一键深度分解链路：

1. 使用抖音登录态鉴权下载真实视频。
2. 在下载、入库、中心镜像和分析前进行媒体真实性校验。
3. 任何失败响应或无效媒体不得写入正式文件、资产库或中心库。
4. 重新下载成功后，原地修复历史坏素材并保留本地及中心素材 ID。
5. 使用 Tesseract 识别关键帧中的中英文字幕。
6. 将全视频音频按 60 秒分片，通过现有 LK888 中心反代调用 Gemini 原生音频理解接口转写。
7. 单视频最多分析 10 分钟，转写结果保留时间戳。
8. 远程转写失败时降级继续，并支持只重试失败分片。

## 3. 非目标

- 不分析超过前 10 分钟的内容；报告必须明确标注截断。
- 不增加批量视频分解。
- 不把报告自动写入知识库或资产库。
- 不新增数据库表或业务数据库迁移。
- 不新增面向前端的 HTTP API；继续使用中心服现有 `/lk888/*` 通用反代。
- 不在客户端或源码中保存 LK888 API Key、抖音 Cookie 或签名视频直链。

## 4. 功能需求

### 4.1 抖音鉴权下载

- `api_server.py` 从当前 `DouyinAuth` 获取登录 Cookie。
- 视频请求携带：
  - 当前登录 Cookie；
  - 项目现有 `HeaderBuilder.ua`；
  - `Referer: https://www.douyin.com/`；
  - `Accept: video/*,*/*;q=0.8`；
  - `Range: bytes=0-`。
- 响应只写入同目录的临时 `.part` 文件。
- 第一次收到 403 时，重新调用一次作品详情接口获取最新签名直链，再重试一次。
- 只有通过完整校验后才使用 `os.replace()` 原子替换正式 `video.mp4`。
- 失败时删除 `.part`，不得覆盖已有有效文件。

### 4.2 媒体真实性校验

新增共享模块 `backend/utils/media_validation.py`，提供可独立测试的校验接口。

校验顺序：

1. HTTP 状态必须是 200 或 206。
2. Content-Type 不得是 `text/html`、`application/json` 或其他明确文本错误类型。
3. 文件头不得包含 `<html`、`<!doctype html`、`403 forbidden` 等错误页特征。
4. 文件必须非空，且通过项目内置 imageio-ffmpeg 探测。
5. ffmpeg 输出必须包含视频流、正数时长、有效宽度和高度。

统一返回结构：

```json
{
  "ok": true,
  "code": "ok",
  "duration": 42.18,
  "width": 1080,
  "height": 1920,
  "hasVideo": true,
  "hasAudio": true
}
```

失败示例错误码：

- `download_http_403`
- `download_http_error`
- `download_unexpected_content_type`
- `download_html_body`
- `media_probe_failed`
- `media_missing_video_stream`
- `media_invalid_dimensions`

### 4.3 失败文件禁止入库

- `import_download_to_library()` 必须对候选视频重新校验，不能信任扩展名或上游返回值。
- 中心服 `mirror_download_material_to_library()` 在源文件对中心服本机可见时先校验；无论来源是本机路径还是远程节点下载，中心落盘后都必须再次校验。
- 任一校验失败时返回结构化失败结果，不创建素材记录，不发送“下载完成并入库”提示。
- 封面和元数据可以保留用于诊断，但错误视频和 `.part` 文件必须删除或隔离。

### 4.4 历史坏素材原 ID 修复

当相同 `sourceDownloadKey` 已存在时：

1. 校验现有素材文件。
2. 若现有文件有效，保持当前去重行为。
3. 若现有文件无效，将旧文件移入隔离目录。
4. 使用新下载的有效文件原子替换素材目录中的文件。
5. 保留 `id`、`createdAt`、`published`、引用 URL 和关联关系。
6. 更新文件名、类型、来源、尺寸、时长、修复时间和 `repaired=true`。

本地隔离目录：

```text
~/.matrix_ship_agent/data/quarantine/<material-id>/<timestamp>/
```

中心服隔离目录：

```text
backend/central_data/quarantine/<material-id>/<timestamp>/
```

隔离文件保留 7 天，清理操作只删除超过保留期的隔离数据。

### 4.5 Tesseract OCR

系统依赖：

```bash
brew install tesseract tesseract-lang
```

Python 依赖写入并锁定到 `backend/requirements.txt` 和 `backend/requirements.deploy.txt`：

- `Pillow`
- `pytesseract`

默认配置：

```dotenv
VIDEO_OCR_LANG=chi_sim+eng
VIDEO_OCR_CONFIG=--oem 3 --psm 11
```

OCR 对每张关键帧单独执行，输出 `[时间戳] 文本`。单帧失败不阻断其他帧；全部失败时状态为 `failed`，依赖不存在时状态为 `unavailable`。

### 4.6 Gemini 远程音频转写

LK888 的 `/v1/audio/transcriptions` 已验证返回 404，模型目录也没有 Whisper/ASR 模型。因此使用 LK888 已公开的 Gemini 原生透传格式：

```text
POST /lk888/v1beta/models/{model}:generateContent
```

客户端继续使用登录会话访问中心服；中心服注入真实 LK888 Key。客户端不得新增 API Key 配置。

音频处理：

- 使用 ffmpeg 导出 16 kHz、单声道、64 kbps MP3。
- 每 60 秒生成一个临时分片。
- 全视频顺序处理，最多 600 秒。
- 每次请求只包含一个分片，避免一次加载完整音频。
- Gemini 请求使用 `inline_data`，MIME 为 `audio/mpeg`。
- 提示模型输出严格 JSON：语言、分段起止秒数、文本。
- 客户端将分片内相对时间加上分片起点，合并为全局绝对时间戳。
- JSON 解析失败时保留模型原文，并以该 60 秒分片为粗粒度时间段，设置 `coarseTimestamps=true`。

转写响应按照以下 JSON Schema 校验；不符合 Schema 时进入粗粒度时间戳降级，不直接信任模型字段：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["language", "segments"],
  "additionalProperties": false,
  "properties": {
    "language": {"type": "string", "minLength": 1, "maxLength": 32},
    "segments": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["startSec", "endSec", "text"],
        "additionalProperties": false,
        "properties": {
          "startSec": {"type": "number", "minimum": 0, "maximum": 60},
          "endSec": {"type": "number", "minimum": 0, "maximum": 60},
          "text": {"type": "string", "minLength": 1, "maxLength": 4000}
        }
      }
    }
  }
}
```

校验同时要求每个分段满足 `endSec >= startSec`。实现优先使用小型纯函数完成该固定 Schema 校验，不新增通用 Schema 运行时依赖。

默认环境变量：

```dotenv
VIDEO_TRANSCRIBE_MODEL=gemini-3.1-pro-preview
VIDEO_TRANSCRIBE_CHUNK_SEC=60
VIDEO_TRANSCRIBE_MAX_SEC=600
VIDEO_TRANSCRIBE_TIMEOUT_SEC=180
VIDEO_TRANSCRIBE_RETRIES=2
VIDEO_BREAKDOWN_MAX_CONCURRENCY=1
MEDIA_QUARANTINE_RETENTION_DAYS=7
DOUYIN_MEDIA_TIMEOUT_SEC=180
```

转写状态：

- `ok`：全部分片成功。
- `partial`：至少一个分片成功、至少一个分片失败。
- `failed`：所有分片失败。
- `no_audio`：视频没有可转写音轨。
- `truncated`：视频超过 10 分钟，仅处理前 10 分钟。

### 4.7 重试转写

- 分解页新增“重试转写”按钮。
- 首次转写失败后记录失败分片的起止时间和错误码，不记录音频 Base64。
- 重试时从原视频重新导出对应音频分片，只调用失败分片。
- 不重新下载视频、不重新抽帧、不重新执行已成功的 OCR。
- 重试完成后重新汇总报告，并在报告中记录重试次数和仍缺失的时间段。

## 5. 技术选型对比

### 5.1 下载方式

| 方案 | 登录态 | 成功率 | 复杂度 | 可测试性 | 结论 |
|---|---:|---:|---:|---:|---|
| 鉴权 HTTP + 严格校验 | Cookie + 浏览器请求头 | 高；当前链接已验证 | 低 | 高 | 采用 |
| Playwright 浏览器下载 | 完整浏览器上下文 | 高 | 高 | 中 | 不采用 |
| HTTP + Playwright 兜底 | 两者 | 最高 | 最高 | 低 | 暂不采用，缺少必要证据 |

### 5.2 OCR

| 方案 | 中文效果 | 依赖体积 | Mac/Python 3.12 风险 | 结论 |
|---|---:|---:|---:|---|
| Tesseract + pytesseract | 中等，适合大字幕 | 小 | 低 | 采用 |
| RapidOCR/ONNX | 较好 | 较大 | 中 | 作为 Tesseract 不可用时的自动回退 |
| 仅远程视觉模型 | 不稳定且增加费用 | 小 | 低 | 只作为视觉分析，不替代 OCR |

### 5.3 音频转写

| 方案 | 新密钥 | 接口可用性 | 维护成本 | 结论 |
|---|---:|---:|---:|---|
| LK888 Gemini 原生音频理解 | 无 | 模型目录支持 Gemini 原生端点 | 低 | 采用 |
| LK888 OpenAI transcription | 无 | 已验证 404 | 低 | 不可用 |
| 独立 OpenAI 兼容 ASR | 需要 | 取决于新供应商 | 中 | 暂不采用 |

## 6. 数据流

```text
内容采集点击分解
  -> 本地执行引擎获取最新作品详情和签名直链
  -> 携带 Cookie/浏览器头下载到 .part
  -> HTTP/内容/ffmpeg 校验
  -> 原子写入下载目录
  -> 本地资产库校验并创建或原 ID 修复
  -> 中心库校验并创建或原 ID 修复
  -> 分解页再次预检
  -> 抽取关键帧 + Tesseract OCR
  -> 导出 60 秒 MP3 分片
  -> LK888 Gemini 顺序转写并合并时间戳
  -> 视觉分析 + 报告汇总
  -> 页面展示临时报告，可下载 Markdown
```

## 7. 错误处理与可观测性

新增链路日志必须是单行 JSON，至少包含：

```json
{
  "event": "video_transcription_chunk_failed",
  "errorId": "err-...",
  "stage": "transcription",
  "code": "remote_timeout",
  "materialId": "...",
  "chunkStartSec": 120,
  "chunkEndSec": 180,
  "durationMs": 180002
}
```

日志规则：

- 记录异常类型、脱敏上下文和完整堆栈。
- 不记录 Cookie、Authorization、API Key、音频 Base64。
- 签名 URL 只记录 scheme、host、path 和查询参数名称，不记录参数值。
- UI 只展示错误码、简短说明和 `errorId`，不展示内部堆栈。

重试规则：

- 下载 403：刷新直链后重试 1 次。
- Gemini 分片：最多重试 2 次，采用短退避，不并发发送。
- OCR 单帧：不自动重试；继续其他帧。
- 媒体校验失败：不重试 ffmpeg，回到下载阶段处理。

## 8. 非功能性需求

- 并发：每个本地客户端同时最多 1 个深度分解任务。
- 上游 QPS：Gemini 转写请求最高 1 QPS，实际为顺序等待响应。
- 延迟目标：1 分钟视频 3 分钟内完成；10 分钟视频 15 分钟内完成。
- 单分片超时：180 秒。
- 内存增量上限：目标不超过 300 MB。
- 临时磁盘上限：目标不超过 200 MB。
- 音频上限：600 秒；超过部分不上传。
- 安全：密钥仅保存在中心服环境变量中；客户端只持有登录会话。
- 隐私：音频只发送到已配置的 LK888 Gemini 上游；任务完成后清理临时音频。
- 可用性：转写失败不得阻断关键帧、OCR、视觉分析和报告下载。

## 9. 测试与冒烟

### 9.1 Phase 0 最小冒烟

在完整实现前验证：

1. 真实抖音链接使用 Cookie 和浏览器头返回 `video/mp4`，ffmpeg 可读取。
2. Tesseract 可使用 `chi_sim+eng` 识别一张合成中文字幕图片。
3. 1 秒合成音频可通过 LK888 Gemini 原生接口返回转写文本。

失败点和修复结果写入 `docs/TROUBLESHOOTING.md`。

### 9.2 TDD 覆盖

- 403 HTML 使用 `.mp4` 扩展名时必须被拒绝。
- 下载请求携带 Cookie、User-Agent、Referer 和 Range。
- 下载失败时 `.part` 被删除，正式文件不被覆盖。
- 有效 MP4 通过 ffmpeg 校验。
- 无视频流或无有效尺寸时禁止入库。
- 本地坏素材修复后 ID 不变。
- 中心坏素材修复后 ID 不变。
- OCR 依赖缺失、单帧失败和正常中文识别状态正确。
- 音频按 60 秒切片，最多 600 秒。
- Gemini 请求不包含 API Key 明文和完整视频。
- 相对时间戳正确合并为绝对时间戳。
- 部分分片失败时状态为 `partial`。
- “重试转写”只处理失败分片。
- JSON 日志不包含 Cookie、Authorization、签名参数值或 Base64。

### 9.3 完成验证

- 运行完整单元测试。
- 运行 Python 语法检查。
- 运行本地 ffmpeg、OCR 和 Gemini 转写冒烟。
- 使用问题抖音链接完成下载、入库修复、抽帧、OCR、转写和报告生成。
- 验证本地素材 ID 和中心素材 ID 均未变化。
- 验证失败路径不会出现新的伪视频素材。

## 10. 文档更新

实施时同步更新：

- `docs/ARCHITECTURE.md`
- `docs/DEPLOYMENT.md`
- `docs/TROUBLESHOOTING.md`
- `docs/IMPLEMENTATION.md`
- `docs/API_REFERENCE.md`：注明没有新增业务接口，仅复用 LK888 通用反代
- `CHANGELOG.md`
- `docs/superpowers/plans/2026-07-11-video-breakdown-reliability.md`

`IMPLEMENTATION.md` 必须在最终修改后重算实际行号，并使用 `path/to/file.py#Lx-Ly` 格式。

## 11. 回滚方案

由于当前目录没有 Git：

1. 修改生产代码前，将所有待修改文件复制到时间戳备份目录。
2. 生成 SHA256 清单，记录原文件和备份文件摘要。
3. 回滚时恢复代码、requirements 和文档，再重启中心服及本地客户端。
4. 新依赖可以保留；如需完全回滚，按部署文档卸载 Python 包，Tesseract 系统包无需强制删除。
5. 被修复的旧坏文件保存在隔离目录 7 天，可按素材 ID 恢复。
6. 不涉及数据库结构变更，因此无 migration 回滚。

## 12. 验收标准

- 问题链接下载后的文件必须是可播放视频，不再是 HTML。
- 报告必须显示真实时长、分辨率、关键帧信息、OCR 状态和转写状态。
- 有音轨时，报告包含带绝对时间戳的口播文本。
- 历史坏素材在本地库和中心库中保持原 ID，文件被有效视频替换。
- 任意 403、HTML、空文件或 ffmpeg 无效文件不得进入资产库。
- 转写部分失败时仍生成报告，并可只重试失败分片。
- 日志可根据 `errorId` 追踪完整链路，且不泄露密钥、Cookie、签名 URL 或音频内容。
