# MiniMax H3 Task 2/3 返工报告

日期：2026-08-03
状态：GREEN（价格与结算保持阻塞，不进入生产扣费）

## 返工范围

本次按已核对的 MiniMax H3 官方契约返工，未继续 Hailuo 或 deprecated 模板 Agent 实现：

- 提交：`POST https://api.minimaxi.com/v2/video_generation`
- 请求字段：固定 `model: MiniMax-H3`、`prompt`、`duration`（4-15）、`resolution`（`768P`/`2K`），可选 `content` 多模态数组
- 查询：`GET /v2/query/video_generation/{task_id}`
- 成功结果：从 `task.content.url` 取得视频 URL
- 密钥：只通过 `Authorization: Bearer ...` 发送
- URL：base URL、content 内 URL、检索 URL 和下载 URL 均要求 HTTPS；拒绝本地路径和 `data:` URL
- 生命周期：submit、poll、retrieve、download；provider 失败按阶段报错；超时不自动重提

## 先 RED 后实现

先运行：

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_direct tests.test_minimax_pricing -v
```

结果：RED，`Ran 11 tests`，`FAILED (failures=2, errors=5)`。失败原因与旧实现一致：仍要求旧 `mode`，使用 Hailuo 模型和 `/v1` 路径，且只支持 `file_id`/旧文件检索形状；不是测试装置或网络问题。

随后实现最小 H3 适配器并重新运行，结果：

```text
Ran 12 tests in 0.004s
OK
```

## 修改文件

- `backend/utils/minimax_direct.py`
  - 重写为 H3 固定模型适配器
  - 支持请求规范化、content 递归 HTTPS 校验、注入 `request_fn`
  - 实现 H3 submit/poll/retrieve/download 路径和阶段错误
  - 保留超时状态，不自动 resubmit
- `backend/utils/minimax_pricing.py`
  - 删除旧 Hailuo 价格表及 `0.28` 等未经确认金额
  - `published_unit_price(...)` 固定返回 `None`
- `backend/central_server.py`
  - 中心服提交骨架固定 `actualModel=MiniMax-H3`
  - 保留认证、JSON 校验、开关、中心密钥、并发限制、pending/failed/awaiting_actual_cost 状态
  - 不加入价格扣费、结算或幂等 billing
- `tests/test_minimax_direct.py`
  - 改为 H3 请求和 provider lifecycle 测试
  - 覆盖模型固定、duration/resolution、content、HTTPS、异常阶段、timeout
- `tests/test_minimax_pricing.py`
  - 明确 H3 价格未确认时返回 `None`
- `tests/test_minimax_central_server.py`
  - 删除旧 Hailuo mode/image 断言，改为 H3 content 请求和固定 actual model
  - 修复测试间 pending 状态隔离
- `docs/openapi.yaml`
  - 同步 H3 请求字段、范围、固定模型和 `video_generation` 内部 mode
- `docs/API_REFERENCE.md`
  - 删除旧 Hailuo 语义，记录 H3 API、状态和未扣费约束

未修改 `tools/aicanvas_remote/server_current.py`，未实现远程生成器、价格结算或 live provider 调用。

## 验证结果

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_direct tests.test_minimax_pricing -v
```

通过：12 tests。

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_central_server tests.test_openapi_contract -v
```

通过：18 tests。

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\utils\minimax_direct.py backend\utils\minimax_pricing.py backend\central_server.py tests\test_minimax_direct.py tests\test_minimax_pricing.py tests\test_minimax_central_server.py
```

通过，无编译错误。

```powershell
git diff --check
```

通过，无 whitespace error。Git 对当前工作树已有文件输出的 LF/CRLF 转换提示不属于 diff 检查错误。

## 未决项与风险

- H3 官方价格和币种尚未确认，生产代码不返回金额，不使用 `Decimal("0.28")`，成功任务只能保持 `awaiting_actual_cost`。
- 本次仅使用 fake provider 验证适配器生命周期，未调用真实 MiniMax 服务，真实账号、权限、响应细节和下载链路仍需单独 live smoke。
- 当前中心服 GET 继续提供任务状态骨架，不做 provider 轮询、下载验证或结算，这些属于后续任务范围。
- 工作树存在大量与本任务无关的既有 dirty changes，均未回滚；未创建 commit。
