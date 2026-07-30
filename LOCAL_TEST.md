# 本地测试指南(原生桌面客户端)

形态:**真·原生 Windows 客户端**(PySide6/Qt 原生控件,不是网页)。双击 `MatrixShipAgent.exe` 打开一个原生应用窗口(自带标题栏「矩阵星舰 本地客户端」、任务栏图标),左侧原生导航,右侧原生表单/表格。所有平台动作(登录/搜索/看视频/评论)在**你本机的 Edge + 你的 IP** 上执行(客户端内嵌本地引擎 127.0.0.1:9081 + worker)。中心服务器只做数据/协调,不直接访问平台。

已含模块:登录、账号矩阵(含「登录抖音/小红书」→ 开本机 Edge)、寻客中心、运行日志。其余模块(素材发布/软文/爆款/风控/工作流/AI 拓客等)按同一骨架逐步补齐。

## 前置(本机已具备)
- Python 3.12 + 依赖(PySide6 / playwright / PyExecJS / protobuf / pillow …)
- Node v20 + `backend/node_modules`(jsrsasign)
- Microsoft Edge(平台登录用它)

## 一键启动(源码或 exe)
```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\72992\matrixship\start-local-test.ps1
```
它会启动中心(9099)并打开客户端窗口(有 exe 用 exe,否则用源码 `matrix_native_client.py`)。然后:
1. 在客户端窗口用 **admin / test123456** 登录。
2. 进 **账号矩阵** → 点 **登录抖音** → 本机 Edge 自动打开抖音登录页 → 正常扫码/短信登录 → 账号出现在表格里。
3. 进 **寻客中心** → 输关键词 → **开始寻客** → 结果表格显示意向客户(在你本机浏览器执行)。
4. **运行日志** 页可看引擎/worker 实时日志。

> 直接用 exe:`backend\dist\MatrixShipAgent\MatrixShipAgent.exe`;本地测试连本地中心先设
> `$env:MATRIX_CENTRAL="http://127.0.0.1:9099"`。正式环境默认连 `http://39.105.120.104`。

## 已验证(本机自动化实测)
- 原生窗口:进程标题 = 「矩阵星舰 本地客户端」,内嵌引擎 `/api/health ok`(不是浏览器,不是网页弹窗)
- 登录/寻客/账号登录都走 central 的 local-browser 任务通道,由本机 worker 执行
- 登录 `admin/test123456` → ok;旧云登录 `/api/cloud-login/*` → 410 已下线

## 常见问题
- **点“登录抖音”没反应/报离线**:客户端登录后 worker 需要几秒连上中心,稍等再点;日志页会显示「已连接中心，客户端上线」。
- **Edge 没弹**:关掉所有 Edge 窗口再试(持久化 profile 被占用会失败);或设 `DY_EDGE_PATH`。
- **签名报错**:确认 `backend\node_modules\jsrsasign` 在(没有就 `cd backend; npm install`)。

## 出正式安装包(给最终用户双击装,含桌面图标)
```powershell
winget install JRSoftware.InnoSetup          # 首次装一次
cd C:\Users\72992\matrixship\backend
powershell -ExecutionPolicy Bypass -File .\build_matrix_agent.ps1
# 产出 dist\MatrixShipAgent\ + 安装包 dist\installer\MatrixShipAgent-Setup.exe
```
