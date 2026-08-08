# 部署说明

## 2026-08-03 公开下载页 `/download`

- 中心服内置公开页面 `/download`，不依赖独立前端构建产物。部署中心服新版本并重启中心服后即可访问。
- 当前页面仅展示下载说明，下载按钮处于禁用状态，文案为“Windows 客户端即将开放下载”，不连接真实安装包。
- 正式开放下载前，不需要发布安装包文件；现有安装包直链 `/MatrixShipAgent-Setup.exe` 不随本页面变更。
- 数据库、Docker 镜像结构、环境变量和 `migration.sql` 均无影响。
- 回滚方式：回滚中心服代码到上一稳定版本，或删除 `/download` 路由与页面渲染函数。若页面异常率超过 1%，可先通过中心服代码回滚移除该页面，不影响客户端更新检查和安装包直链。

## 2026-08-03 MiniMax H3 Official Direct Release

- Scope: central server `backend/central_server.py` and remote AI Canvas `/root/AI-CanvasPro/server.py`.
- Center env: `MINIMAX_ENABLED=1`, `MINIMAX_CENTER_API_BASE=https://api.minimaxi.com`, `MINIMAX_CENTER_API_KEY=<center-only-key>`.
- Remote comic env: `MINIMAX_ENABLED=1`, `MINIMAX_COMIC_API_BASE=https://api.minimaxi.com`, `MINIMAX_COMIC_API_KEY=<comic-only-key>`.
- Shared runtime limits: `MINIMAX_MAX_ACTIVE_TASKS=2`, `MINIMAX_TASK_TIMEOUT_SEC=900`, `MINIMAX_POLL_INTERVAL_SEC=5`.
- Secrets stay in process env or uncommitted `.env` files. Do not reuse the center key for the remote comic generator.
- Packaging guard: do not copy or archive the whole workspace for release. Use Git-tracked source export or Docker build context only. `backend/.dockerignore` excludes `.env`, `.env.*`, runtime data, logs, uploads, caches, and backups; `.tmp-validation/` and local ignored env backups must never be included in manual release bundles.
- Rollback: set `MINIMAX_ENABLED=0` to block new H3 submissions. For remote AI Canvas code rollback, restore the deployment backup `/root/AI-CanvasPro/server.py.bak.<timestamp>`, restart `ai-canvas.service`, then verify service active, port `8777` listening, and `/login` returns 200.
- Database impact: none. `migration.sql` contains a no-op release note only.
- Remote deploy evidence: `/root/AI-CanvasPro/server.py` was updated at `20260803_122102`; backup `/root/AI-CanvasPro/server.py.bak.minimax-h3-poll-20260803_122102`; previous SHA `581f254102277914742d15e0384f8c8aa94341e04e2756dc97108f715ecdfa89`; deployed SHA `5bd0ee530bd5c3629d1ec91b5f733e04deb33e6ef09eafd717660f070537b295`; `ai-canvas.service` active; port `8777` listening; `/login` returned 200.

## 2026-08-03 抖音单平台运行开关

当前默认只开放抖音。`backend/.env.example`、`backend/.env.dev`、`backend/.env.prod` 和 `docker-compose.prod.yml` 均声明 `MATRIX_XHS_ENABLED=0`；本地客户端、本地执行器和中心服启动后会隐藏/拒绝小红书/XHS 入口、接口、平台适配器和任务类型。

恢复小红书时设置 `MATRIX_XHS_ENABLED=1`，并重启三个运行单元：本地客户端、`backend/api_server.py` 本地执行器、`backend/central_server.py` 中心服。上线前必须重新执行小红书账号登录态、搜索、下载、评论、发布和图文同款冒烟；失败时把开关改回 `0` 并重启即可回滚到抖音单平台。

历史小红书账号不需要保留。清理前先 dry-run：

```powershell
.\.venv-win\Scripts\python.exe scripts\disable_xhs_accounts.py --data-dir backend\datas --central-state backend\central_data\scheduler_state.json --dry-run
```

确认只命中小红书 profile/账号行后去掉 `--dry-run` 执行。该脚本不删除抖音账号目录、素材库或媒体文件；数据库结构无变化，`migration.sql` 仅记录 no-op 发布说明。

## 2026-08-03 临时原生界面功能开关

`dev`、`staging`、`prod` 均应由各自环境文件或编排系统显式注入以下非敏感开关。仓库模板和生产 Compose 默认值均为 `0`：

```text
MATRIX_VIDEO_REPLACEMENT_ENABLED=0
MATRIX_PENDING_PUBLISH_UI_ENABLED=0
MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED=0
```

| 开关 | `0` 的生产行为 | 恢复步骤 |
| --- | --- | --- |
| `MATRIX_VIDEO_REPLACEMENT_ENABLED` | 同款替换侧栏置灰并显示“功能完善中，敬请期待”；三个次级跳转隐藏 | 设为 `1`，重启本地客户端，验证侧栏和三个入口后再执行真实生成冒烟 |
| `MATRIX_PENDING_PUBLISH_UI_ENABLED` | 隐藏待发布队列标签页，保留现有队列文件和后台逻辑 | 设为 `1`，重启本地客户端，验证旧队列仍可读取 |
| `MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED` | 隐藏 TTS 上传和声音预览，自动 TTS 不变 | 设为 `1`，重启本地客户端，验证上传、预览和自动 TTS 两条路径 |

这三个开关只改变原生客户端可见性；Compose 中的同名变量用于保持统一配置契约，不改变中心服接口。`MATRIX_XHS_ENABLED` 仍是跨本地客户端、本地执行器和中心服的独立平台开关，切换它必须重启三个运行单元。

发布前登记上一稳定客户端包及 SHA-256；中心服镜像结构未变，仍保留上一稳定镜像 Tag。若启用任一隐藏功能后的观察窗口错误率超过 1%，立即把对应开关恢复为 `0` 并重启客户端；XHS 能力异常则把 `MATRIX_XHS_ENABLED` 恢复为 `0` 并重启三个运行单元。此次没有 API 路径/JSON Schema、OpenAPI、数据库表、Docker 镜像结构或 `migration.sql` 行为变更。

## 2026-07-30 账户中心账单看板发布与回滚门禁

### 环境与配置所有权

| 环境 | 配置来源 | 账单验证规则 |
| --- | --- | --- |
| `dev` | 未提交的 `backend/.env.dev` 或显式进程环境 | 隔离 JSON/假数据冒烟可显式设置 `MAINDB_ENABLED=0`；连接开发主库时保持为 `1`。 |
| `staging` | 未提交的 `backend/.env.staging` 或编排环境 | 代表性 MySQL 验收必须保持 `MAINDB_ENABLED=1`；纯 JSON 隔离冒烟才可临时设为 `0`。 |
| `prod` | 现有 `backend/.env.prod` 与 Compose/发布系统 | 发布系统负责主库变量，`MAINDB_ENABLED` 保持未设置或 `1`；禁止因故障改为 `0` 规避 503。 |

`CENTRAL_LOAD_DOTENV=0` 只允许隔离的 dev/staging 冒烟进程使用，并且必须同时使用隔离 `CENTRAL_DATA_DIR`、测试 Token 和非生产端口。生产保持该变量未设置，让既有 `.env` 加载行为不变。本功能不新增密钥或数据库连接串；`BILLING_SMOKE_TOKEN`、`BILLING_MONITOR_TOKEN` 只从环境读取，不能写入命令输出、日志或仓库。

`MAINDB_ENABLED` 默认启用。只有 dev/staging 的隔离 JSON 冒烟可以显式关闭；默认启用时，`maindb` 导入、配置、健康检查、用量查询或严格余额查询任一失败，`/api/account/balance`、analytics 与参数化 ledger 都返回 503，不输出局部统计或虚假 0 余额。导入异常对象只保存在进程内用于状态判断，不写入日志。

`backend/Dockerfile` 继续安装 `backend/requirements.txt`，本地与主机部署文件 `backend/requirements.deploy.txt` 均精确锁定 `jsonschema==4.23.0`、`PyMySQL==1.1.1` 和 `passlib[bcrypt]==1.7.4`。Dockerfile 与 `docker-compose.prod.yml` 继续检查 `/api/health`，本次不修改容器拓扑。

### 发布验收

- 正常 30 天账户查询目标：20 QPS、P95 不超过 800 ms。验收脚本固定发送 200 个请求、使用 20 个 worker，并对每个响应执行运行时 analytics JSON Schema 校验。
- 性能脚本只接受 `http://127.0.0.1`、`http://localhost` 或 `http://[::1]`，禁止对生产环境运行。请求器在收到任何 3xx 时直接拒绝跳转并把原始状态记为无效，不会向跳转目标发起第二次请求或转发 Authorization。
- analytics/参数化 ledger 最大日期跨度为 366 天；主库读取使用 50,001 行硬门禁，达到上限即返回错误，不输出部分统计。
- 权威余额接口为 `GET /api/account/balance`，返回数字或运营方精确字符串 `inf`；参数化接口为 `GET /api/billing/analytics` 与 `GET /api/billing/ledger`。无参数 `GET /api/billing/ledger` 保持原响应路径，作为兼容与回滚后冒烟项。

### 可追溯基线

当前已提交源码基线 Git SHA：`347120c9308db2ae43482aba3f33df5ed2dd40ad`。Task 6 开始时工作区包含 Tasks 1-5 的未提交改动，因此该 SHA 只标识已提交源码基线，不包含本次账单实现。

以下均是本机预任务**源码快照**，可用于逐文件核对或源码级恢复；它们不是容器镜像、Windows/Mac 客户端安装包，也不能替代部署制品：

| 源码快照 | SHA-256 | 字节数 |
| --- | --- | ---: |
| `.tmp-validation/sdd/task-2-before/backend/central_server.py` | `301086C8902D9C5D20BC043FB178783E9BB2ED44A09330DF88F2C699B6505885` | 792096 |
| `.tmp-validation/sdd/task-2-before/backend/maindb.py` | `E421DA241263C12F93EE9C3A89670A1F1FA42D085D8811F6DC0A9D414F2B1B00` | 13370 |
| `.tmp-validation/sdd/task-5-before/backend/matrix_native_client.py` | `3C0DE2CCDF71CE5FB6FC42439548385DB30CA670C170041C496B022B36C11F30` | 1245363 |
| `.tmp-validation/sdd/task-4-before/docs/openapi.yaml` | `2BB3E0101E012E5FC3EF9AE2F12FF8DD56C6D91D3F8FD8D6C2F18E6783712E97` | 50520 |

最终阻断修复复核时的当前工作区源码哈希为：中心服 `09577E4A37FB94E5399E788AC13F785563AD25AF4207F311FD542339C0DB7CC1`，主库适配 `E2E1C47F149DB56265CB053BD1C029DBEF130F28CF78D0DF0718A58485761182`，原生客户端 `BF440E746CFB0C289AEF9B25AF90DE551788290A06315839D308079C8A9C0571`，账单领域模块 `2BDA3CEEF718212CFCF28C113EC73AB5899A4FE85357798699D05C1899CC08A7`，OpenAPI `921C02EBC61C541149782A81EDEBA0C26D86A2330B2DB6535FF260C9197C59C6`。这些同样只是当前候选源码证据，不是已部署版本；计算前已用两次长度、时间戳和 SHA-256 检查确认相关文件稳定。

生产发布前必须另外在发布单登记并校验两个**可部署制品**：上一稳定中心服镜像 Tag，以及上一稳定客户端包的版本、存放位置和 SHA-256。仓库当前没有足以证明这两个制品存在的记录；未登记时生产发布门禁不通过。演练值 `stable-previous` 只用于 dry-run，不得当作真实镜像证据。

### 回滚监控

监控窗口固定为 100 个账单 analytics 请求。只有新接口错误率严格大于 1% 时才选择回滚；正好 1% 不回滚。任何 3xx 都按原始状态计为错误，监控不会跟随跳转或把 Authorization 发送到跳转目标。`PREVIOUS_IMAGE_TAG` 必须完整匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`。

必需环境变量：

| 变量 | 用途 |
| --- | --- |
| `BILLING_MONITOR_BASE_URL` | 被监控中心服基础 URL。 |
| `BILLING_MONITOR_TOKEN` | 只用于 Authorization 请求头，不得输出。 |
| `PREVIOUS_IMAGE_TAG` | 已登记且已验证存在的上一稳定中心服镜像 Tag。 |

先使用受控 fixture 演练，演练不会访问服务或运行 Docker：

```powershell
$env:PREVIOUS_IMAGE_TAG='stable-previous'
.\.venv-win\Scripts\python.exe scripts\monitor_billing_rollout.py --dry-run --fixture-error-rate 0.02
```

真实监控由发布系统注入三个环境变量后运行：

```powershell
.\.venv-win\Scripts\python.exe scripts\monitor_billing_rollout.py
```

超过阈值时脚本使用参数列表、`shell=False` 和复制后的环境执行以下唯一命令，其中 `IMAGE_TAG` 被设为已校验的 `PREVIOUS_IMAGE_TAG`：

```text
docker compose -f docker-compose.prod.yml up -d --no-build matrix-central
```

回滚后检查 `/api/health`、无参数 `/api/billing/ledger` 和鉴权失败路径；再恢复并校验上一稳定客户端包。中心镜像和客户端包是两个独立回滚单位。任何真实回滚、部署、Docker 执行或进程重启都必须单独审批，本 Task 6 只执行 `--dry-run`。

### 数据库影响

本发布不新增或修改数据库结构与数据。`migration.sql` 仅追加 no-op 发布注释，不含本发布的 DDL/DML。

## 环境隔离

密钥和运行配置不得写入源码。建议分别维护未提交的 `backend/.env.dev`、`backend/.env.staging`、`backend/.env.prod`，启动前显式加载目标环境：

```bash
set -a
source backend/.env.dev
set +a
```

本机中心服还会加载项目根目录 `.env` 和 `backend/.env`。正式环境应只在受控主机保存 `.env.prod`，不要把真实 Key、Cookie 或 Token 写入示例文件。

## AI Canvas 视频模型降级发布

- 远程服务文件：`/root/AI-CanvasPro/server.py`，监听端口 `8777`。发布前先比较本地测试镜像与远程文件 SHA-256，再将远程文件备份为 `/root/AI-CanvasPro/server.py.bak.<timestamp>`。
- 上传后先在远程执行 Python 语法检查，成功后只重启 8777 对应 AI Canvas 服务；不要重启中心服或本地客户端。健康检查失败时立即恢复时间戳备份并再次启动 8777。
- 当前同款替换 Seedance 路径不再自动切备用模型；用户在本地客户端选中的视频模型就是唯一提交模型。`COMIC_REAL_PERSON_VIDEO_FALLBACK_MODELS` 仍保留给历史兼容和其他旧流程，但不再驱动这条同款替换链路的自动降级。
- Seedance 真人/版权/品牌/策略拒绝会直接返回中文失败提示；任务响应可保留诊断字段，但不应再提交 `vidu/viduq3-mix_reference2video`、`wan2.7-shouweizhen`、`kling-v3-omni-shouweizhen` 或 `pixverse-v6-shouweizhen` 作为自动后继模型。
- 查询超时、HTTP 502 和限流只继续查询既有远程任务，不会触发新模型提交；发现重复计费、部署后语法错误或健康检查失败时，立即恢复备份。
- 2026-08-01 发布记录：旧文件 SHA-256 为 `0cdbbd45b95817883ff0711faa6678b108f3f76a50b57f60c15fb3f54184f2fe`，备份为 `/root/AI-CanvasPro/server.py.bak.comic-inline-media-20260801_161136`；新文件 SHA-256 为 `e1b807eceac6527f9f30a86a78df09d3c798915bcfc8fa425939f6a973841e81`。`ai-canvas.service` 重启后为 active，8777 监听和 `/login` 200 均已验证。
- 2026-07-28 发布记录：旧文件 SHA-256 为 `27e49707684eeb1c3024afe305723f4576e52d8571f33c20560d27ed0acfc069`，备份为 `/root/AI-CanvasPro/server.py.bak.20260728_160337`；新文件 SHA-256 为 `bfbe4c1e310562d2b5a5dd9445d24fb1c134016ce834173f32a59b55b49b8e93`。`ai-canvas.service` 重启后为 active，8777 正常监听。
- 历史 2026-07-28 单模型冒烟只重提项目 294 分镜 294001，任务 `ai-86996340` 最终为 `completed`。该记录仅用于旧版本追溯，当前发布验收以五模型链和新三片段任务为准。

### 同款替换内嵌媒体与分项重生成发布

本节是 Documentation Task 7A 的受控发布作业单，不表示已经部署。实际发布由控制器完成，并在执行后把下表四项替换为真实值；在此之前不得把本节标记为已发布。

| 发布记录 | 值 |
|---|---|
| 部署时间 | `2026-07-29 19:48:04 +08:00` |
| 上一稳定版备份路径 | `/root/AI-CanvasPro/server.py.bak.comic-inline-media-20260729_194804` |
| 上一稳定版 SHA-256 | `8393970e0f9121ba7d9ba2b9bc68a278794464de629c6a464733f64309af52c5` |
| 新部署文件 SHA-256 | `f53d4d2ace67e12886557f28882fa61d40104083983ced96876b7efeaceb1f78` |

发布只替换远程 `/root/AI-CanvasPro/server.py` 并重启 `ai-canvas.service`；不重启中心服或本地客户端。本次任务 JSON 仅新增可选字段，不新增数据库表或列，`migration.sql` 无需执行和修改。

发布前先停止新漫剧生成入口，等待正在提交的请求结束。将待发布文件上传为同目录临时文件 `/root/AI-CanvasPro/server.py.incoming` 后，在远程主机执行以下预检、备份、哈希校验和同文件系统原子替换。真实值只能来自当次发布，不得沿用历史发布记录：

```bash
set -euo pipefail
DEPLOY_TS="20260729_194804"
BACKUP_PATH="/root/AI-CanvasPro/server.py.bak.comic-inline-media-20260729_194804"
EXPECTED_NEW_SHA256="f53d4d2ace67e12886557f28882fa61d40104083983ced96876b7efeaceb1f78"

test -n "$DEPLOY_TS"
test -n "$BACKUP_PATH"
test -n "$EXPECTED_NEW_SHA256"
test -f /root/AI-CanvasPro/server.py
test -f /root/AI-CanvasPro/server.py.incoming

install -m 0644 /root/AI-CanvasPro/server.py "$BACKUP_PATH"
BACKUP_SHA256="$(sha256sum "$BACKUP_PATH" | awk '{print $1}')"
CURRENT_SHA256="$(sha256sum /root/AI-CanvasPro/server.py | awk '{print $1}')"
test "$BACKUP_SHA256" = "$CURRENT_SHA256"

NEW_SHA256="$(sha256sum /root/AI-CanvasPro/server.py.incoming | awk '{print $1}')"
test "$NEW_SHA256" = "$EXPECTED_NEW_SHA256"
python3 -m py_compile /root/AI-CanvasPro/server.py.incoming
install -m 0644 /root/AI-CanvasPro/server.py.incoming /root/AI-CanvasPro/server.py.next
mv -f /root/AI-CanvasPro/server.py.next /root/AI-CanvasPro/server.py
test "$(sha256sum /root/AI-CanvasPro/server.py | awk '{print $1}')" = "$EXPECTED_NEW_SHA256"
```

替换后只重启目标服务，并依次检查 systemd active、8777 监听、登录页和真实受控冒烟账号登录。账号密码由主机环境变量注入，脚本不打印密码或返回 Token：

```bash
set -euo pipefail
systemctl restart ai-canvas.service
systemctl is-active --quiet ai-canvas.service
ss -ltn '( sport = :8777 )' | grep -q LISTEN
curl -fsS -o /dev/null http://127.0.0.1:8777/login

test -n "${AIC_SMOKE_USERNAME:-}"
test -n "${AIC_SMOKE_PASSWORD:-}"
python3 - <<'PY'
import json
import os
import urllib.request

body = json.dumps({
    "username": os.environ["AIC_SMOKE_USERNAME"],
    "password": os.environ["AIC_SMOKE_PASSWORD"],
}).encode("utf-8")
request = urllib.request.Request(
    "http://127.0.0.1:8777/api/v1/auth/login/password",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=20) as response:
    payload = json.load(response)
assert response.status == 200
assert payload.get("access_token") or payload.get("token")
PY
```

发布后观察窗口至少覆盖首轮真实漫剧任务。任一硬门禁失败，或新版本错误率严格大于 1%，控制器必须自动停止新任务并运行回滚；重复计费、无参数双帧行为改变、401 凭证刷新超过一次、播放器持续卡死或崩溃也视为立即回滚条件。监控器把当前错误率百分值写入 `AIC_ERROR_RATE_PERCENT` 后执行：

```bash
set -euo pipefail
BACKUP_PATH="/root/AI-CanvasPro/server.py.bak.comic-inline-media-20260729_194804"
EXPECTED_BACKUP_SHA256="8393970e0f9121ba7d9ba2b9bc68a278794464de629c6a464733f64309af52c5"
ERROR_RATE_PERCENT="${AIC_ERROR_RATE_PERCENT:?AIC_ERROR_RATE_PERCENT is required}"

if python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) > 1.0 else 1)' "$ERROR_RATE_PERCENT"; then
  test -n "$BACKUP_PATH"
  test -n "$EXPECTED_BACKUP_SHA256"
  test "$(sha256sum "$BACKUP_PATH" | awk '{print $1}')" = "$EXPECTED_BACKUP_SHA256"
  install -m 0644 "$BACKUP_PATH" /root/AI-CanvasPro/server.py.rollback
  mv -f /root/AI-CanvasPro/server.py.rollback /root/AI-CanvasPro/server.py
  systemctl restart ai-canvas.service
  systemctl is-active --quiet ai-canvas.service
  ss -ltn '( sport = :8777 )' | grep -q LISTEN
  curl -fsS -o /dev/null http://127.0.0.1:8777/login
fi
```

硬门禁检查失败时不等待错误率窗口，直接使用同一回滚块恢复备份。回滚后保留结构化脱敏日志、任务 JSON、已生成媒体和 `pendingComicVideoRecovery`，便于追溯和继续仅下载恢复；不要删除用户项目。远程与本地可分别回滚，任务新增字段为可选读取，因此无需数据降级脚本。

## Mac 依赖

```bash
cd "/Users/mac/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252"
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
brew install tesseract tesseract-lang
```

若当前 Mac 无法安装 Homebrew，程序会自动使用已列入 Python 依赖的 RapidOCR。确认运行时：

```bash
tesseract --list-langs
.venv/bin/python -c "from rapidocr_onnxruntime import RapidOCR; print('rapidocr ok')"
```

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `CENTRAL_HOST` | `0.0.0.0` | 中心服监听地址；本地建议 `127.0.0.1` |
| `CENTRAL_PORT` | `9080` | 中心服端口 |
| `CENTRAL_DATA_DIR` | `backend/central_data` | 中心服数据目录 |
| `CENTRAL_LOCAL_BROWSER_LONG_TASK_TIMEOUT_SEC` | `900` | 本地浏览器长任务在中心服被重新排队前允许运行的秒数；覆盖 AI触达、寻找线索、发布和下载类任务 |
| `LK888_BASE_URL` | `https://api.lk888.ai` | LK888 上游地址；本地网络无法直连 LK888 TLS 时可设为 `https://img.yunlingai.net/lk888-upstream` |
| `LK888_API_KEY` | 无 | 仅中心服保存的密钥 |
| `PUBLIC_MEDIA_BASE_URL` | 无 | 公网 HTTPS 素材代理地址；临时测试可用 Cloudflare Tunnel 的 `https://*.trycloudflare.com` |
| `PUBLIC_MEDIA_TOKEN_SECRET` | 无 | 素材公网链接 HMAC 签名密钥；不配置时不生成 `publicUrls` |
| `PUBLIC_MEDIA_TTL_SEC` | `3600` | 素材公网链接有效期，最低 60 秒 |
| `MATRIX_CENTRAL` | `http://127.0.0.1:9080` | 客户端连接的中心服 |
| `API_HOST` | `127.0.0.1` | 本地执行引擎监听地址 |
| `API_PORT` | 客户端内置 `9081` | 本地执行引擎端口 |
| `MATRIX_AGENT_DATA_DIR` | `backend/datas` | 本地素材、生成任务、日志、账号注册表和每账号抖音 profile 根目录；Windows 源码部署默认不再使用 `%APPDATA%\MatrixShipAgent\data` |
| `DY_PROFILE_DIR` | `MATRIX_AGENT_DATA_DIR/dy_profile` | 旧默认抖音账号 profile；新增账号自动使用 `douyin_accounts/<id>/dy_profile` |
| `MATRIX_AGENT_USE_APPDATA` | 空 | 紧急回滚开关；设为 `1` 时 Windows 本地客户端临时恢复旧 `%APPDATA%\MatrixShipAgent\data` 默认目录 |
| `MATRIX_AGENT_SKIP_APPDATA_MIGRATION` | 空 | 设为 `1` 时跳过从旧 AppData 数据目录向新目录的非破坏性复制 |
| `VIDEO_OCR_LANG` | `chi_sim+eng` | Tesseract 语言 |
| `VIDEO_OCR_CONFIG` | `--oem 3 --psm 11` | Tesseract 参数 |
| `TESSERACT_CMD` | 自动查找 | 自定义 Tesseract 路径 |
| `VIDEO_TRANSCRIBE_MODEL` | `gemini-3.1-pro-preview` | 音频理解模型 |
| `VIDEO_TRANSCRIBE_CHUNK_SEC` | `60` | 分片秒数 |
| `VIDEO_TRANSCRIBE_MAX_SEC` | 空 | 默认转写整条视频；设置正数后才限制单视频转写范围 |
| `VIDEO_TRANSCRIBE_TIMEOUT_SEC` | `180` | 单分片远程超时 |
| `VIDEO_TRANSCRIBE_RETRIES` | `2` | 单分片重试次数 |
| `VIDEO_BREAKDOWN_MAX_CONCURRENCY` | `1` | 产品约束；当前页面固定串行 |
| `VIDEO_BREAKDOWN_TEMP_RETENTION_SEC` | `3600` | 崩溃遗留分解临时目录的保留秒数 |
| `MEDIA_QUARANTINE_RETENTION_DAYS` | `7` | 坏素材隔离保留期 |
| `MEDIA_DECODE_TIMEOUT_SEC` | 动态 `60-600` | 全量解码超时；设置正数时覆盖动态预算 |
| `DOUYIN_MEDIA_TIMEOUT_SEC` | `180` | 抖音媒体读取超时 |
| `LEGAL_TERMS_VERSION` | `1.0` | 用户协议版本；提升后要求用户重新同意 |
| `LEGAL_PRIVACY_VERSION` | `1.0` | 隐私政策版本；提升后要求用户重新同意 |
| `LEGAL_EFFECTIVE_DATE` | `2026-07-15` | 登录弹窗和 428 响应显示的生效日期 |
| `VIDEO_REPLACE_PIPELINE` | `hybrid_v2` | 同款替换功能开关；回滚时切回稳定入口 |
| `VIDEO_REPLACE_DEFAULT_MODE` | `comic_project` | 同款替换新任务默认模式；设为 `legacy` 可让新任务回到旧 LK888 链路 |
| `VIDEO_REPLACE_PRINCIPAL_REPLACEMENT` | `1` | 单主角源视频编辑总开关；设为 `0` 回滚新任务到旧参考图视频候选链 |
| `VIDEO_REPLACE_PRINCIPAL_MODEL` | `happyhorse-video-edit` | 同款替换任务未手动选择模型时的主角源视频编辑默认模型；页面模型下拉框会把任务级 `model` 写入任务 JSON，所选模型必须支持源视频 + 参考图片输入 |
| `VIDEO_REPLACE_PRINCIPAL_MIN_CONFIDENCE` | `0.65` | 原片主角视觉定位最低置信度；低于阈值必须人工确认 |
| `VIDEO_REPLACE_PRODUCT_PARALLEL` | `2` | 产品图原图上传并发度；运行时限制为 `1..3`，设为 `1` 可回退串行上传 |
| `VIDEO_REPLACE_TTS_CHARS_PER_SEC` | `5.5` | 同款替换 AI 音色配音的生成前口播时长估算语速；数值越大越宽松，建议保持 `2.5..8.0` 范围。旧默认为 `4.2`，偏慢约 25%，会把 11 秒的口播估成 15 秒 |
| `VIDEO_REPLACE_COMIC_DURATION_SLOTS` | 无（`4..15` 每个整数秒） | 漫剧项目模式每段可申请的视频秒数档位；留空表示按整秒申请。若漫剧服务端拒绝任意整秒，设为 `4,8,12,15` 回到旧的粗档位 |
| `VIDEO_REPLACE_COMIC_DURATION_HEADROOM_SEC` | `0.5` | 漫剧项目模式在口播时长之上预留的视频余量秒数；运行时限制为 `0..3` |
| `VIDEO_REPLACE_COMIC_MEASURE_TTS` | `1` | 漫剧项目模式排期时是否先生成一遍 TTS 并探测真实音频时长来定视频秒数；设为 `0` 回退到纯字数估算 |
| `VIDEO_REPLACE_COMIC_MEASURE_TTS_PARALLELISM` | `4` | 上述时长探测的并发度；运行时限制为 `1..8`，设为 `1` 可回退串行 |
| `VIDEO_REPLACE_LIPSYNC_MODEL` / `LK888_VIDEO_LIPSYNC_MODEL` | 无 | 历史兼容变量；当前同款替换 `tts/uploaded` 不再依赖已有视频口型同步模型，而是把口播稿写入 LK888 视频编辑 prompt 后本地替换音轨 |
| `VIDEO_REPLACE_SUBTITLE_SAFE_SOURCE` | `1` | 同款替换上传给远程视频模型前是否生成字幕安全源片段；默认遮罩顶部/底部常见字幕区，最终中文字幕仍由本地后期字幕层烧录 |
| `VIDEO_REPLACE_SUBTITLE_FONT_FILE` | 自动查找 `C:\Windows\Fonts\msyh.ttc` 等中文字体 | 同款替换最终中文字幕烧录时传给 ffmpeg/libass 的固定字体文件目录；可指定受控中文字体文件，避免系统字体回退导致中文显示异常 |
| `VIDEO_REPLACE_ACTION_CONTROL` | `0` | 历史兼容变量；当前同款替换新任务页面已移除原片动作控制入口，并固定写入 `actionControlEnabled=false` |
| `VIDEO_REPLACE_ENABLE_AVATAR_SEGMENTS` | `0` | 历史兼容变量；当前同款替换不使用数字人模型重生成片段，`tts/uploaded` 通过视频编辑 prompt 传入口播稿并在本地替换音轨 |
| `VIDEO_REPLACE_ENABLE_FACEFUSION` | `0` | 旧任务兼容开关；当前同款替换新任务页面已移除人物一致性入口，并固定写入 `enableFaceFusion=false` |
| `VIDEO_REPLACE_FACE_RETENTION_SEC` | `86400` | 本地人脸/任务临时文件保留秒数 |
| `VIDEO_REPLACE_VISUAL_QC` | `1` | 启用人物、产品/Logo 和场景自动视觉 QC |
| `VIDEO_REPLACE_DRIFT_GUARD` | `1` | 同款替换漂移防护总开关；设为 `0` 时强制关闭预检、严重漂移阻断和自动重试 |
| `VIDEO_REPLACE_REFERENCE_PREFLIGHT` | `1` | 生成前参考图预检；人物图上下文、产品类别差异和场景差异只提醒，产品/场景是否替换由上传素材和后置 QC 判定 |
| `VIDEO_REPLACE_BLOCK_SEVERE_DRIFT` | `1` | 严重主题/角色/结构漂移是否阻断所有人物一致性模式 |
| `VIDEO_REPLACE_DRIFT_AUTO_RETRY` | `1` | 严重漂移是否自动强化源视频锁定后重试 |
| `VIDEO_REPLACE_DRIFT_MAX_RETRIES` | `1` | 每片段严重漂移自动重试次数，运行时钳制为 0-3 |
| `VIDEO_REPLACE_PREFLIGHT_BLOCK_SCENE` | `0` | 场景参考强阻断开关；默认不因场景图或人物图背景冲突提前阻断 |
| `VIDEO_REPLACE_REFERENCE_MAX_BYTES` | `20971520` | 旧任务中心素材转临时 data URL 的单图上限 |
| `VIDEO_REPLACE_KEYFRAME_RETRY_SIZE` | `1024x1024` | 同款替换关键帧同步图片 502/504 后的轻量重试尺寸 |
| `VIDEO_REPLACE_KEYFRAME_RETRY_REFS` | `2` | 同款替换关键帧轻量重试保留的参考图数量 |
| `VIDEO_REPLACE_KEYFRAME_FALLBACK` | `1` | 历史兼容变量；当前同款替换 talking 片段不再通过关键帧兜底到数字人口播 |
| `VIDEO_REPLACE_STRICT_VISUAL_QC` | `0` | 同款替换视觉不一致默认只提醒人工审核；设为 `1` 时 `face/product/scene_mismatch` 阻断片段 |
| `VIDEO_REPLACE_DIGITAL_HUMAN_FACEFUSION` | `0` | 历史兼容变量；当前同款替换新任务不通过页面启用本地 FaceFusion |
| `MATRIX_COMIC_BASE_URL` | `http://120.26.194.174` | 漫剧生成器基址；也可用 `COMIC_TOOL_URL` 覆盖 |
| `MATRIX_COMIC_FIXED_USER_ID` | `44` | 同款替换漫剧项目固定写入的 AI CanvasPro 用户 ID；当前对应账号 `003` |
| `MATRIX_COMIC_FIXED_USERNAME` | `003` | 固定漫剧账号用户名，仅用于 ticket 响应和日志追踪，不是密码 |
| `COMIC_REAL_PERSON_VIDEO_FALLBACK_MODELS` | `vidu/viduq3-mix_reference2video,wan2.7-shouweizhen,kling-v3-omni-shouweizhen,pixverse-v6-shouweizhen` | 远程 AI Canvas 视频降级顺序；显式空值禁用，修改后只重启 8777 |
| `COMIC_REAL_PERSON_VIDEO_FALLBACK_MODEL` | 无 | 旧单模型配置兼容项；仅在未配置复数变量时读取 |
| `MATRIX_COMIC_FIXED_DISPLAY_NAME` | `003` | 固定漫剧账号显示名，写入 Matrix SSO ticket 的 `name` claim |
| `LK888_IMAGE_TIMEOUT_SEC` | `540` | 客户端同步图片生成超时 |
| `LK888_SYNC_IMAGE_TIMEOUT_SEC` | `480` | 中心服同步图片上游超时，应小于客户端超时 |
| `FACEFUSION_BIN` | 无 | 独立 FaceFusion 商用环境可执行文件绝对路径 |
| `FACEFUSION_MODEL_DIR` | 无 | 已取得商业许可的模型目录；不得提交到源码仓库 |
| `FACEFUSION_LICENSE_REF` | 无 | 内部许可证记录编号或受控文档引用，不是密钥 |
| `FACEFUSION_EXECUTION_PROVIDER` | `coreml,cpu` | M2 优先 CoreML、失败时 CPU；逗号分隔 |

LK888 模型结算固定为后付费实际成本：部署配置中不存在预扣开关，历史 `LK888_LEGACY_PRECHARGE_ENABLED` 即使残留在 `.env` 中也不会被读取。发布或回滚计费代码时必须把中心服和本地客户端作为同一版本单元重启；禁止新客户端连接旧预扣中心服，也禁止旧客户端连接新中心服。上线后检查新流水只包含稳定任务 `ref`、`billingSource=lk888_actual`、`actualAmount`、实际 `modelId` 和 `taskId`。

## LK888 出口代理

- 服务器：`120.26.194.174` 的 `ai_education_nginx` 容器。
- 公网入口：`https://img.yunlingai.net/lk888-upstream/...`，固定转发到 `https://api.lk888.ai/...`。
- 安全约束：Nginx 要求请求带 `Authorization`，仅转发该请求头，不在 Nginx 注入 LK888 密钥，也不改写上传服务 `/api/upload`、`/uploads/`、`/health`。
- Multipart 约束：`Content-Type` 必须用 `$http_content_type` 原样透传，保留 `boundary`；否则仍使用 multipart 的媒体接口可能被上游误判为非 UTF-8 请求体。`kling-avatar-image2video` 当前走 JSON，头像优先使用公网 URL。
- 本地配置：`backend/.env` 的 `LK888_BASE_URL=https://img.yunlingai.net/lk888-upstream`，`LK888_API_KEY` 仍只保存在本地中心服环境。
- 回滚：将 `backend/.env` 的 `LK888_BASE_URL` 恢复为 `https://api.lk888.ai`，并在服务器恢复 `/root/ai-education-platform/nginx/nginx.conf.bak.lk888-upstream-*` 后 reload `ai_education_nginx`。

## 协议发布流程

1. 法务审核 `backend/legal/user_agreement.md` 和 `backend/legal/privacy_policy.md`，确认运营主体、联系方式、计费和信息处理描述与生产实际一致。
2. 任一正文发生实质变更时，提升对应的 `LEGAL_*_VERSION`，同步修改 Markdown 内版本和更新日期。
3. 先部署中心服，再发布携带同版本正文的客户端。版本不匹配期间，中心服返回 HTTP 428，不创建会话。
4. PyInstaller 必须包含 `legal/` 数据目录。打包后在无网络环境点击两个协议链接，确认可离线滚动阅读。
5. 发布后检查 `legal.consent.accept` 审计记录和 `legalConsents`最新版本，不记录密码、Token 或短信验证码。

回滚时同时恢复上一稳定客户端、中心服和对应协议版本环境变量。已保存的同意与审计数据保留，不执行数据迁移或删除。

## FaceFusion 商用环境预检

V2 不安装或捆绑许可证不明的人脸模型。运维人员应在独立虚拟环境安装已完成商业许可审查的 FaceFusion 版本和模型，然后在 `.env.dev` / `.env.staging` / `.env.prod` 中配置路径。上线前执行：

```bash
test -x "$FACEFUSION_BIN"
test -d "$FACEFUSION_MODEL_DIR"
test -n "$FACEFUSION_LICENSE_REF"
"$FACEFUSION_BIN" --help >/dev/null
```

客户端在上传三张人脸或触发远程计费前执行同样的文件、模型和许可证检查。预检失败会显示具体错误码并停止任务。

本地参考图和本地源视频片段不会将 `127.0.0.1` URL 提交给远程模型。配置 `PUBLIC_MEDIA_BASE_URL` 后，中心服会为上传素材返回带签名和过期时间的 `publicUrls`，客户端优先把这些 HTTPS URL 传给 LK888。也可以配置独立公网素材上传服务：`UPLOAD_API_URL=https://img.yunlingai.net/api/upload`、`PUBLIC_UPLOAD_BASE_URL=https://img.yunlingai.net/uploads`、`PUBLIC_IMAGE_BASE_URL=https://img.yunlingai.net/uploads`、`UPLOAD_TOKEN=<secret>`；客户端图片和视频类 `upload_asset_url()` 会优先把人物图、产品图、场景图和已替换视频片段上传到该服务，并把返回的公网 HTTPS URL 传给 LK888。音频类 `upload_asset_url()` 继续走中心服 `/api/library/upload` 并使用 `PUBLIC_MEDIA_BASE_URL` 生成的 `publicUrls`，避免独立公网图片/视频服务拒收 `mp3/wav/m4a/ogg/aac` 后返回 400。当前独立服务端允许 `jpg/jpeg/png/webp/gif/mp4/mov/webm`，应用和 `img.yunlingai.net` Nginx 均按 500MB 单文件上限配置；超过上限会返回 413。未配置公网代理或独立公网素材服务时，关键帧生成在请求内存中临时转为 data URL，不写入任务 JSON 或日志；同款替换 `tts/uploaded` 当前不再上传已替换视频做二次口型同步，音轨替换在本地完成。

同款替换产品图当前直接上传用户原图，不再执行白底归一化或归一化后一致性校验。历史环境变量 `VIDEO_REPLACE_PRODUCT_NORMALIZE`、`VIDEO_REPLACE_PRODUCT_NORMALIZE_VALIDATE` 不再改变新任务的产品图处理链路；如需控制速度，只调整 `VIDEO_REPLACE_PRODUCT_PARALLEL` 并重启本地客户端。

旧 LK888 主角模式仍默认调用 `happyhorse-video-edit` 源视频编辑；页面“同款替换模型”下拉框可把任务级 `model` 切换为其他适合的 LK888 视频参考模型。客户端只展示白名单和 LK888 目录中识别到的“SD 2.0 全能参考”等适合模型，不展示纯文生视频或图片模型。原片段和 1-3 张人物参考图必须先变成公网 HTTPS URL，请求同时保留 `video`、`images`、`video_url`、`video_urls`、`reference_video` 和 `params` 内源视频字段；失败记录实际 `model`、`remoteErrorId` 和 `principal_video_edit_failed`。设置 `VIDEO_REPLACE_PRINCIPAL_REPLACEMENT=0` 后，新任务回到参考图视频候选链。源片段公网 URL 仍会写入任务 JSON 供追踪和音频回填；如无公网素材基址，会在远程下单前返回 `video_replace_remote_media_required`。`tts/uploaded` 声音模式会把口播稿写入主角替换视频 prompt；远程生成完成后，本地用 AI 音色 TTS 或上传完整配音裁切片段替换音轨，不再要求配置 `VIDEO_REPLACE_LIPSYNC_MODEL`。

新任务默认走漫剧项目模式。`MATRIX_COMIC_BASE_URL` / `COMIC_TOOL_URL` 指向漫剧生成器根地址，默认 `http://120.26.194.174`。本地客户端会先用中心服换 ticket，再与漫剧生成器交换 token；中心服默认把 ticket 固定签给漫剧账号 `MATRIX_COMIC_FIXED_USER_ID=44` / `MATRIX_COMIC_FIXED_USERNAME=003`，不再按当前 Matrix 用户做一对一映射。之后按角色/场景/道具写入项目库并生成分镜、首尾帧和视频。`audioMode` 当前允许 `auto` 和 `tts`：`auto` 使用生成视频自带声音，`tts` 使用 AI 音色按口播稿生成声音；上传完整配音的稳定片段接口还没有接通，`uploaded` 仍会被前置阻断。如果暂时不想让新任务进入漫剧模式，把 `VIDEO_REPLACE_DEFAULT_MODE` 改成 `legacy` 并手动重启本地客户端即可。临时开发测试可使用 Cloudflare Tunnel：

`SD 2.0 全能参考` 的 LK888 生成模型标识是 `kwvideo-v2-quannengcankao`，云灵页面卡片 ID `76` 只用于上游页面展示/选择。客户端已把该标识作为同款替换内置备选；如果上游实际接口不支持源视频 + 参考图输入，应从任务级模型切回 `happyhorse-video-edit` 后重生失败片段。

```bash
cloudflared tunnel --url http://127.0.0.1:9080
```

复制输出的 `https://*.trycloudflare.com`，重启中心服时设置：

```bash
PUBLIC_MEDIA_BASE_URL=https://xxxx.trycloudflare.com \
PUBLIC_MEDIA_TOKEN_SECRET="$(openssl rand -hex 32)" \
PUBLIC_MEDIA_TTL_SEC=3600 \
CENTRAL_HOST=127.0.0.1 CENTRAL_PORT=9080 \
python backend/central_server.py
```

`cloudflared` 进程必须保持运行；重启 tunnel 后 URL 会变化，需要同步更新 `PUBLIC_MEDIA_BASE_URL` 并重启中心服。

## FaceFusion 标准版本地开发

当前 Mac 安装 FaceFusion `3.7.1` 于 `/Users/mac/facefusion-standard`，独立虚拟环境为 `/Users/mac/.venvs/facefusion-standard`。项目通过 `/Users/mac/facefusion-standard/run-facefusion` 兼容官方 CLI，并使用 `ghost_2_256` 开发模型。

该环境仅用于本地开发测试：FaceFusion 项目为 `OpenRAIL-AS`，但完整链路仍包含非商用/研究限制模型。`FACEFUSION_LICENSE_REF=DEV-ONLY-...` 不是商业许可证，不得用于 staging/prod 或正式收费服务。

启动前加载开发配置：

```bash
cd "/Users/mac/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252"
source backend/.env.dev
```

预检：

```bash
/Users/mac/facefusion-standard/run-facefusion --version
.venv/bin/python -c "import os,sys; sys.path.insert(0, os.path.abspath('backend')); import matrix_native_client as m; print(m._facefusion_preflight())"
```

标准版 `3.7.1` 不接受项目原有的 `--reference-face-path` / `--model-dir` 参数。兼容启动器会移除这两个参数，并降级为 `--face-selector-mode one --face-selector-order large-small`，因此本地测试只支持画面中有一个主要人物的视频。多人精确锁定仍需生产级商业引擎或后续实现官方 reference frame/position 适配。

不要执行 `force-download --download-scope lite` 来准备单一换脸链路：FaceFusion `3.7.1` 会遍历多个处理器并下载大量无关模型，可额外占用数 GB 磁盘。

## 启动中心服

```bash
cd "/Users/mac/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend"
CENTRAL_HOST=127.0.0.1 \
CENTRAL_PORT=9080 \
python central_server.py
```

看到 `Listening: http://127.0.0.1:9080` 表示已启动。根路径返回 `not_found` 是正常行为，健康检查使用：

```bash
curl -sS http://127.0.0.1:9080/api/health
```

## 启动原生客户端

```bash
open -n -a "/Library/Frameworks/Python.framework/Versions/3.12/Resources/Python.app" \
  --env PYTHONPATH="/Users/mac/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/.venv/lib/python3.12/site-packages" \
  --env MATRIX_CENTRAL="http://127.0.0.1:9080" \
  --args "/Users/mac/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/matrix_native_client.py"
```

登录后客户端会启动 `127.0.0.1:9081` 本地执行引擎。健康检查：

```bash
curl -sS http://127.0.0.1:9081/api/health
```

## 验证

```bash
.venv/bin/python -m unittest discover tests -v
.venv/bin/python -m py_compile \
  backend/utils/media_validation.py \
  backend/utils/structured_log.py \
  backend/utils/video_transcription.py \
  backend/utils/data_util.py \
  backend/api_server.py \
  backend/central_server.py \
  backend/matrix_native_client.py
```

## Windows 验证环境

本项目在 Windows 本地验证时应使用 Python 3.12。系统 Python 3.14 与 `rapidocr-onnxruntime==1.4.4` 不兼容，会导致依赖安装失败。当前已验证的解释器为 Codex 工作区内置 Python：

```powershell
C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
```

推荐一次性创建项目本地虚拟环境，目录保留在 `.venv-win/`，该目录已加入 `.gitignore`：

```powershell
C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m venv .venv-win
.venv-win\Scripts\python.exe -m pip install -r backend\requirements.txt
```

运行验证时建议把临时目录指向项目内 `.tmp-validation/`，避免系统临时目录权限或跨盘路径影响测试。`.tmp-validation/` 已加入 `.gitignore`，不得提交。

## Docker 生产部署

生产中心服务提供 `backend/Dockerfile` 和根目录 `docker-compose.prod.yml`。镜像默认监听 `CENTRAL_HOST=0.0.0.0`、`CENTRAL_PORT=9080`，健康检查使用 `/api/health`。

部署前准备受控的 `backend/.env.prod`，不要提交真实密钥、Cookie 或 Token。建议使用显式镜像 Tag 便于回滚：

```bash
IMAGE_TAG=20260720-ops docker compose -f docker-compose.prod.yml --env-file backend/.env.prod up -d --build
curl -fsS http://127.0.0.1:9080/api/health
```

回滚时把 `IMAGE_TAG` 切回上一稳定版本并重启服务。若新版本错误率超过 1%，先停止新任务入口，再回滚镜像；`matrix-central-data` 卷保留业务数据，不随容器删除。

### Windows 10 本地生产冒烟

当前 Windows 验证机为 Windows 10 Pro 21H2 build `19044.1766`。该版本对 Store WSL 的 `wsl.exe --status` 支持不足，Docker Desktop 可切换到 Hyper-V 后端完成本地生产冒烟。Docker Desktop 配置文件必须保持 UTF-8 无 BOM；Windows PowerShell 的 `Set-Content -Encoding UTF8` 可能写入 BOM，导致 Docker 报 `invalid character 'ï'`。

本机 Docker 客户端普通权限可能无法访问 `//./pipe/docker_engine`，验证 compose 状态时需要管理员权限；HTTP 健康检查可直接访问本地端口。为了避免读取用户 Docker 凭据，验证时使用项目内临时 Docker 配置目录：

```powershell
$env:DOCKER_CONFIG = (Join-Path (Get-Location) '.tmp-validation\docker-config')
$env:IMAGE_TAG = 'prod-smoke-20260720'
docker compose -f docker-compose.prod.yml --env-file backend\.env.prod up -d --build
curl.exe -fsS http://127.0.0.1:9080/api/health
docker compose -f docker-compose.prod.yml --env-file backend\.env.prod ps
```

若直连 Docker Hub 拉取 `python:3.12-slim` 超时，可先从受控镜像源拉取并打本地等价 tag，再重新构建：

```powershell
docker pull docker.1ms.run/library/python:3.12-slim
docker tag docker.1ms.run/library/python:3.12-slim python:3.12-slim
```

该镜像源只作为网络受限环境的构建兜底；正式 CI/CD 应优先使用企业镜像仓库缓存固定 digest 的基础镜像。

## 回滚

本项目目录不是 Git 仓库。本次初始稳定快照位于：

```text
backups/video-breakdown-reliability-20260711_190142/
```

本次七栏报告、用户名登录和无图标缩略图修复的最终已验证快照位于：

```text
backups/video-breakdown-final-20260713_132558/
```

本次“分解视频 -> 同款替换生成”功能快照位于：

```text
backups/video-replacement-20260713_180954/
```

先停止中心服和客户端，再按 `SHA256SUMS.txt` 核对并恢复目标文件。示例：

```bash
cp backups/video-breakdown-reliability-20260711_190142/backend/matrix_native_client.py backend/matrix_native_client.py
cp backups/video-breakdown-reliability-20260711_190142/backend/api_server.py backend/api_server.py
cp backups/video-breakdown-reliability-20260711_190142/backend/central_server.py backend/central_server.py
```

不要回滚已经修复成功的素材目录。历史坏文件仍保存在 `quarantine/<material-id>/<timestamp>/`，需要恢复素材时先验证目标文件，再做原子替换。

同款替换生成不新增数据库表。本次参考图视频模型适配的回滚单位是 `backend/matrix_native_client.py`、`tests/test_video_replacement.py`、`tests/test_lk888_media_task_parsing.py` 和相关 `docs/`；停止客户端后恢复到 2026-07-13 的已验证快照即可。已经生成并进入资产库的视频素材可以保留，也可以按资产库记录人工删除。

V2 发布由 `VIDEO_REPLACE_PIPELINE=hybrid_v2` 控制。出现错误率超过 1%、视觉 QC 大面积误判或主角模型契约异常时，先停止新任务并将 `VIDEO_REPLACE_PRINCIPAL_REPLACEMENT=0`，再重启客户端；已完成片段和 `replacement_job.json` 保持不变，可在修复后继续。当前新任务已移除页面上的原片动作控制、产品镜头锚定和人物一致性入口，回滚这些入口需要恢复本地客户端代码并重启。回滚前先让运行中的远程片段结束或在页面请求取消，确认中心人物副本清理结果后再停进程。

公网素材代理回滚：停止新同款替换任务，取消 `PUBLIC_MEDIA_BASE_URL` 或 `PUBLIC_MEDIA_TOKEN_SECRET` 后重启中心服。上传接口将不再返回 `publicUrls`，客户端会退回旧的本地/中心素材处理逻辑；已生成的旧签名链接会在 `PUBLIC_MEDIA_TTL_SEC` 后自然失效。

抖音多账号不新增数据库表。回滚到单账号行为时，先停止客户端和本地执行引擎，恢复 `backend/api_server.py` 到上一稳定快照；如需隐藏多账号记录，可将用户数据目录中的 `douyin_accounts.json` 重命名为 `douyin_accounts.json.bak`。每个账号的 `douyin_accounts/<id>/dy_profile` 默认保留，不会被回滚脚本删除。

本次没有数据库 Schema 变更；根目录 `migration.sql` 是可追溯的 no-op 发布声明，不修改任何表。当前同时支持 Mac 原生 Qt 客户端、本地 Python 服务和中心服 Docker 部署。源码回滚单位是带 SHA256 的源码快照；容器回滚单位是上一稳定镜像 Tag，并以 `/api/health` 和错误率超过 1% 的发布门禁作为回滚触发条件。
## 2026-07-20 Windows 本地数据目录

Windows 源码部署默认把本地客户端运行数据写入项目内 `backend/datas`，中心服素材库继续写入 `backend/central_data`。同款替换、视频分解、浏览器 profile、账号注册表、日志和工作流产物都应优先跟随 `MATRIX_AGENT_DATA_DIR`，避免落到 `%APPDATA%\MatrixShipAgent\data`。

启动脚本 `start-local-test.ps1` 和 `backend/start-matrix-agent.bat` 会显式设置：

```powershell
MATRIX_AGENT_DATA_DIR=backend\datas
DY_DATA_DIR=backend\datas
DY_PROFILE_DIR=backend\datas\dy_profile
```

首次启动会从旧 `%APPDATA%\MatrixShipAgent\data` 做一次非破坏性复制：只复制新目录不存在的文件或文件夹，不删除旧 C 盘数据。回滚时可设置 `MATRIX_AGENT_USE_APPDATA=1` 临时恢复旧目录；如需禁止复制旧数据，可设置 `MATRIX_AGENT_SKIP_APPDATA_MIGRATION=1`。

## 2026-07-25 中心状态文件保护与恢复

中心服启动时会在读取 `backend/central_data/scheduler_state.json` 前自动生成 `scheduler_state.json.bak-startup-*`。如果状态文件存在但无法解析，中心服会阻断启动，避免把默认企业/默认用户写回覆盖正式数据。

不要在中心服运行时直接编辑 `scheduler_state.json`。需要恢复或规范化状态时，按以下流程执行：

```powershell
# 1. 停止中心服进程
# 2. 校验当前状态，只读不写
.venv-win\Scripts\python.exe tools\repair_scheduler_state.py

# 3. 从备份恢复，工具会先备份当前文件，并用无 BOM UTF-8 写回
.venv-win\Scripts\python.exe tools\repair_scheduler_state.py --restore backend\central_data\scheduler_state.json.bak-startup-YYYYMMDDHHMMSS

# 4. 重启中心服并检查健康状态
.venv-win\Scripts\python.exe backend\central_server.py
```

如确需初始化全新空状态，必须显式设置 `CENTRAL_ALLOW_STATE_REINIT=1`。该开关只用于临时开发或空环境初始化，不应在正式数据环境长期启用。

## 小红书图文同款部署说明

环境变量：

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `XHS_NOTE_REPLACEMENT_ENABLED` | `1` | 控制本地 `/api/xhs-note-replacement/*` 接口。设置为 `0/false/no/off` 可即时停用图文同款入口的后端能力。 |

本次不新增端口、数据库表、外部密钥或 GPU 服务。接口运行在本地执行引擎 `127.0.0.1:9081`，仍使用现有账号数据目录和素材库。生产发布前不需要执行数据库迁移；`migration.sql` 保持 no-op 以保留发布追溯记录。

回滚预案：优先设置 `XHS_NOTE_REPLACEMENT_ENABLED=0` 并重启本地客户端；若需要代码回滚，恢复 `backend/xhs_note_replacement.py`、`backend/api_server.py`、`backend/central_server.py`、`backend/matrix_native_client.py`、`tests/test_xhs_note_replacement.py` 和本次文档即可。历史 Web 入口已退役，不再作为常规回滚目标；由于 V1 默认只生成草稿且发布预检阻断 `image_note`，回滚不会影响既有视频发布链路。

## 小红书获客采集过滤

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `XHS_STRICT_LEAD_FILTER_ENABLED` | `1` | 开启主页校验、评论尾部清洗、用户名校验和主页级去重。仅在确认误过滤时临时设置为 `0/false/no/off`，修改后重启本地执行引擎。 |

该过滤运行在本地执行引擎，不新增端口、数据库、外部密钥、网络请求或 GPU 服务。紧急降级只关闭严格校验和主页级去重，不修改历史数据；完整回滚前先校验 `backups/xhs-lead-filtering-20260727/manifest.sha256`，再恢复归档中的 `backend/platform_adapters.py` 和相关文档。
## 小红书安全模式与抖音评论风控

环境变量：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `XHS_GUEST_COLLECTION_DEFAULT` | `1` | 小红书搜索、下载、读取评论、图文同款下载和获客中心寻客默认使用游客采集。设置为 `0/false/no/off` 并重启本地客户端和本地执行引擎后，可临时恢复旧的账号采集默认模式；该开关不关闭安全模式。 |
| `XHS_SAFETY_MODE` | `1` | 开启小红书执行前安全拦截。设置为 `0/false/no/off` 并重启本地客户端和本地执行引擎后，可临时恢复旧行为。 |

抖音评论风控不新增环境变量，默认读取风控中心保存到 `risk_config.json` 的 `dailyComment` 和 `minInterval`。每日评论上限、最小间隔冷却和评论风险暂停是硬门禁，命中后 `force=true`、`safeMode=false`、普通 API 通道、自动 UI 回退和强制 `edge-ui` 通道都会在打开浏览器或调用平台前停止；`force` 只跳过浏览器 DOM 预检，`safeMode=false` 只关闭评论文案清洗与 DOM 预检。

运行态文件：

| 文件 | 说明 |
| --- | --- |
| `backend/datas/risk_config.json` | 风控中心保存的每日发布上限、每日评论上限、最小间隔和并发配置。 |
| `backend/datas/xhs_safety_state.json` | 小红书安全模式写入的账号当天计数、最后动作时间、冷却和平台风险暂停状态。 |
| `backend/datas/comment_risk_state.json` | 抖音评论写入 `accounts.<accountId>.day/commentCount/lastCommentAt`、账号级冷却状态、平台评论风险暂停和脱敏后的风险响应摘要；风控中心抖音“今日评论 / 冷却”列读取该文件。 |

发布与回滚：本功能不新增数据库表，不需要 `migration.sql`；不新增接口路径，因此不需要 OpenAPI 路径变更。上线后如果游客模式误判，可先设置 `XHS_GUEST_COLLECTION_DEFAULT=0` 临时恢复账号采集默认值；如果小红书安全模式误拦截，优先在风控中心调整上限/间隔，或临时设置 `XHS_SAFETY_MODE=0` 后重启本地客户端和本地执行引擎；如果抖音评论误拦截，优先在风控中心调高每日评论上限或缩短最小间隔，确认 `comment_risk_state.json` 没有残留风险暂停，再重启本地执行器和本地客户端。代码级回滚恢复 `backend/api_server.py`、`backend/matrix_native_client.py`、`tests/test_douyin_comment_cooldown.py` 和本次文档即可。
