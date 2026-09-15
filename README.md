# MatrixShip（矩阵星舰）

Windows 原生桌面客户端 + 本机执行器 + 中心服。登录、搜索、下载、评论、发布都在**用户自己的 Edge 和本机网络**上执行；中心服只做账号、任务协调、素材镜像和计费。Cookie 和浏览器 profile 不离开本机。

仓库描述见 GitHub：`local client, local executor, and central server source`。

## 三个运行单元

```text
PySide6 原生客户端                 本机执行器                 中心服
matrix_native_client.py      →    api_server.py :9081   ←→  central_server.py :9080
账号矩阵 / 采集 / 发布 / 计费        本机 Edge + profile        会话 / 任务 / 素材镜像 / 账单
                                  local_browser_worker.py
```

- 客户端默认连 `MATRIX_CENTRAL`（本地一般是 `http://127.0.0.1:9080`）。
- 本机执行器只听 `127.0.0.1:9081`。
- 健康检查：`GET /api/health`。
- 旧云登录 `/api/cloud-login/*` 已下线（410）。账号矩阵登录直连本机执行器 `/api/login/start`。

## 它做什么

- **账号矩阵**：本机 Edge 扫码/短信登录抖音、小红书；多账号 profile 隔离。
- **内容采集**：拉作品、下载、看评论。
- **分解视频 / 同款替换**：采集后拆镜头，再按参考生成同款（默认开）。
- **图文同款**：小红书链路（默认开，由 `MATRIX_XHS_ENABLED` 控制）。
- **素材发布 / 寻客 / 工作流助手 / 数字人**：发布和获客走本机浏览器；部分界面由开关隐藏。
- **账户中心**：余额、扣费明细、角色权限（平台管理员 / 企业家 / 普通用户）。

Cookie、Token、平台私有 URL 不要写进日志或仓库。

## 仓库结构

```text
backend/                 客户端、中心服、本机执行器、打包脚本
backend/matrix_native_client.py
backend/api_server.py
backend/central_server.py
backend/local_browser_worker.py
backend/build_matrix_agent.ps1
docs/                    架构、部署、API、排障
tests/
docker-compose.prod.yml  中心服
start-visible-client.bat 本机一键起中心服 + 客户端（:9080 / :9081）
start-local-test.ps1     本机测试中心服改到 :9099
LOCAL_TEST.md
MIGRATION.md
CHANGELOG.md
```

## 本机怎么跑

需要 Python 3.12（仓库用 `.venv-win`）、`backend/requirements.txt`、Node（`cd backend && npm install`，签名依赖 `jsrsasign`）、本机已装 Microsoft Edge。

```powershell
# 源码窗口：起中心服 :9080，再开原生客户端
.\start-visible-client.bat
```

或：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-local-test.ps1
```

`start-local-test.ps1` 把中心服放在 `127.0.0.1:9099`，并用脚本里的 `CENTRAL_ADMIN_PASSWORD` 建本地管理员。登录账号见 `LOCAL_TEST.md`。这是本地测试口令，不要用在公网。

已打好的客户端：`backend\dist\MatrixShipAgent\MatrixShipAgent.exe`。连本地中心服时先设 `$env:MATRIX_CENTRAL="http://127.0.0.1:9080"`（或脚本用的 9099）。

## 打安装包

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File .\build_matrix_agent.ps1
```

产出 `dist\MatrixShipAgent\` 和 `dist\installer\MatrixShipAgent-Setup.exe`。打包细节见 `LOCAL_TEST.md`。

## 中心服（Docker）

```powershell
# 先准备未提交的 backend/.env.prod（密钥、主库、模型服务）
docker compose -f docker-compose.prod.yml up -d --build
```

容器探活：`/api/health`。数据卷：`matrix-central-data` → `/app/central_data`。完整发布步骤见 `docs/DEPLOYMENT.md`。

## 功能开关

公网安装包不读 `.env`，行为跟 `backend/platform_features.py` 的代码默认值走。模板和生产 Compose 与下面一致。

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `MATRIX_XHS_ENABLED` | `1` | 小红书入口、图文同款。改它必须同时重启客户端、本机执行器、中心服 |
| `MATRIX_VIDEO_REPLACEMENT_ENABLED` | `1` | 同款替换侧栏和跳转 |
| `MATRIX_PENDING_PUBLISH_UI_ENABLED` | `0` | 待发布队列页 |
| `MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED` | `0` | 数字人 TTS 上传 / 预览 |

改开关后重启对应进程。设 `=0` 是配置级回滚，不需要改库。

## 文档

- `docs/ARCHITECTURE.md` — 运行单元、权限、采集/替换数据流
- `docs/DEPLOYMENT.md` — 发布与回滚
- `docs/API_REFERENCE.md` / `docs/openapi.yaml` — HTTP 契约
- `docs/TROUBLESHOOTING.md` — 常见故障
- `LOCAL_TEST.md` — 本机冒烟
- `MIGRATION.md` — 从服务器浏览器迁到本机客户端
- `CHANGELOG.md` — 按日期的行为变更

## 不要提交

`.env` / `.env.*`（保留 `.env.example`）、`backend/central_data/`、`backend/datas/`、Cookie、`storageState`、浏览器 profile、真实 Token、安装包 `dist/`。
