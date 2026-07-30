# MatrixShip 迁移:服务端浏览器自动化 → 用户本地客户端

目标:把浏览器自动化从中心服务器搬到**每个用户自己的 Windows 电脑**上跑,用用户真实浏览器 + 住宅 IP,
这样平台封的是用户各自的 IP(几乎不可能整体封),中心服务器 IP 不再直接碰抖音/小红书,永不被整站拉黑。
中心服务器(central_server.py)保留为**控制面**:多租户账号/RBAC/审计、任务队列调度、账号资产登记、素材库、寻客线索。

## 目标架构(控制面 / 数据面分离)

```
用户浏览器打开 SPA(中心服务器 39.105.120.104 提供)
  → 用户登录 SaaS(user session)
  → 本机客户端 MatrixShipAgent(常驻)按 orgId+user token 轮询中心 /api/local-browser/poll
  → 用户在 SPA 点任意操作(搜索/看视频/发视频/评论/登录)
  → SPA POST 任务到中心 /api/local-browser/task(orgId 隔离 + 审计)
  → 本机客户端领取 → 用**用户自己的 Edge + cookie + IP** 执行(本地引擎 api_server :9081)
  → 结果 POST 回中心 /api/local-browser/result → 中心跑同样的后处理(素材入库/发布记账/线索归并)
  → SPA 轮询拿结果
Cookie / 浏览器 profile 永不离开用户电脑;只有账号状态 + 抓取结果回中心。
```

## 端口约定(单一事实来源)
- **中心服务器(远程 39.105.120.104)**:`central_server.py` = **9080**(nginx :80 反代 /api/ → 9080)
- **本机客户端引擎**:`api_server.py` = **9081**(仅监听 127.0.0.1)
- **本机 worker**:`agent_worker.py` 轮询中心 :9080 的 `/api/local-browser/*`,转发到本地 127.0.0.1:9081
- 旧的"商业版直连"模型(前端直连 127.0.0.1:9080)**不采用**,统一走中心协调。

## 浏览器控制方式(已定)
- 默认:Playwright `executable_path` 挂**用户已装 Edge** + 每账号一个持久化 profile
  (`%APPDATA%\MatrixShipAgent\data\profiles\<accountId>`);`remote-debugging-port` 默认关。
- 不用需要"开发者模式加载解压扩展"的显眼方式;旧 MV3 扩展仅留只读 XHS 兜底(待定/可删)。

## 登录(已定,替换旧云登录)
点登录 → 本机 Edge 打开抖音登录页 → 用户正常登(扫码/密码/短信)→ 客户端探测 `sessionid/sid_guard` 等标记 →
抓完整 `storageState`(留本机 profile)→ 只回传账号身份+cookie 状态到中心。底层复用 `local_login.py` / `cookie_util`。
**删除**:`/api/cloud-login/*`、`login-douyin.html`、`login-xhs.html`、noVNC 截图中继、`CloudLoginSession`。

## 打包(已定)
- PyInstaller 打 `MatrixShipAgent.exe`(build_matrix_agent.ps1),**必须**打进:`static/*.js` 签名器 +
  `node_modules`(jsrsasign)+ `vendor/node/node.exe`(用户机器可能没 Node)。`runtime_paths.ensure_node_on_path()` 开机把 node 放上 PATH。
- 无代码签名:安装器做成双击 → 向导 → 桌面图标直接用(Inno Setup,Phase 3);SmartScreen 那步在向导第一页给图示。

## 阶段进度
- [x] **Phase 0 — 使可构建 & 一致性**
  - git 基线已建(服务器只有 .bak 无版本控制)
  - 签名器 dev + **冻结** 均已验证出 a_bogus(SignSelfTest.exe → `FROZEN_SIGNER_OK`,用捆绑 node,无需系统 Node)
  - 新增 `runtime_paths.py`(node PATH shim)并接入 `agent_launcher.py`
  - 新增 `static/__init__.py`(让 `static.*_pb2` 冻结后可导入)
  - 重写 `build_matrix_agent.ps1`(完整 add-data/hidden-import 配方)+ `sign_selftest.py`
  - 修 `local_login.py` 默认中心地址(旧 118.178.32.71 → 39.105.120.104)、`LOCAL_AGENT_COMMERCIAL.md` 旧路径
  - 已知遗留:扩展 `manifest/background.js` 里硬编码 39.105.120.104(扩展将弃用,暂不动)
- [x] **Phase 1 — 执行统一到 local-browser 通道**
  - central 放开任务类型到全量(LOCAL_BROWSER_TASK_PATHS)+ 结果后处理复用(local_browser_apply_side_effects:下载入库/发布记账/线索归并)
  - 新增 local_browser_worker.py(注册/轮询 /api/local-browser/*,type→本地 :9081 路径转发,发布素材镜像);agent_launcher 后台起 worker;引擎改 9081
  - 前端:新增 dispatchViaLocal 归一助手;抖音/小红书 搜索·评论·下载·寻客discover 改走本地通道(support.js 实测渲染无报错)
  - 遗留:写操作 outreach.run / publish.run / 评论发布 仍走旧中央路径,待联调时切换(前端已有 pathToLocalType 映射,改一行即可)
- [x] **Phase 2 — 登录重写到本地浏览器(删云登录/noVNC)**
  - 后端:platform_adapters.xhs_login()、api_server /api/xhs/login+run_xhs_login、central local_browser_upsert_account()+登录结果入库、/api/cloud-login/* 全部 410 下线
  - worker:douyin.login/xhs.login 驱动本地引擎登录并回传账号身份(cookie 只留本机)
  - 前端:doLogin/maintainAccount→startLocalLogin(投递 *.login 任务并轮询);删除 login-douyin.html/login-xhs.html;云登录相关入口全部改走本地;pollCloudLoginProgress 停用。support.js 实测渲染无报错
- [~] **Phase 3 — 真·原生桌面客户端(PySide6/Qt)+ 打包**(核心已通,模块补齐中)
  - **最终形态**:`matrix_native_client.py` —— PySide6/Qt **原生控件**客户端(非网页),原生窗口「矩阵星舰 本地客户端」+ 任务栏图标,打包 `MatrixShipAgent.exe`(--windowed,含 PySide6+引擎,~474MB 目录)。内嵌本地引擎(9081)+worker;登录/账号/寻客走 central 的 local-browser 任务通道,由本机 Edge 执行。实测冻结 exe:原生窗口起、引擎 /api/health ok。
  - 已含模块:登录、账号矩阵(含"登录抖音/小红书"→开本机Edge)、寻客中心、运行日志。**待补**:素材发布/软文/爆款/混剪/数字人/风控/工作流/AI拓客/AI销售/企业中心 等其余模块(按同骨架逐个加 QWidget 页)。
  - (弃用)Edge app-webview 版 matrix_client.py 已删;配对通道 pair/{create,redeem}+connect.html 仅留作纯浏览器兜底,原生客户端不用(登录即连)。
  - 安装器 installer/MatrixShipAgent.iss(双击装+桌面图标+可选自启);build_matrix_agent.ps1 出 exe+签名自测,装 Inno Setup 后出安装包。
  - 历史安装向导页 `frontend/connect.html` 已随 Web 交付面退役；当前通过原生客户端安装包分发。
  - 安装器 backend/installer/MatrixShipAgent.iss(Inno Setup:双击→向导→桌面图标+开始菜单+可选开机自启;免管理员装到 LocalAppData);build_matrix_agent.ps1 [7/7] 自动调 ISCC 并输出到 backend/dist/installer/
  - 浏览器控制沿用 Phase 0/2:Playwright 挂系统 Edge + 持久化 profile,remote-debugging 默认关;不需要浏览器扩展
- [~] **Phase 4 — 下线云节点/扩展,加固,补文档**
  - [x] 云登录 410 下线;旧 MV3 扩展标注弃用(仅只读 XHS 兜底,见其 README)
  - [x] 文档:本 MIGRATION.md + connect.html 引导 + 构建说明
  - [ ] 待联调后:彻底删除 /api/node/* 与 cloud_login_* 死代码(现为安全保留)
  - [ ] 端到端联调(central 本地起 + 已配对客户端 + 真账号):跑通 登录→搜索→评论→下载→寻客→发布 全链路
- [ ] **Phase 2 — 登录重写到本地浏览器**(删云登录/noVNC)
- [ ] **Phase 3 — 隐身打包 + 引导配对**(挂系统 Edge;/api/local-browser/pair 配对码;Inno Setup 向导;托盘+自启)
- [ ] **Phase 4 — 下线云节点/扩展,加固,补文档**

## 构建 & 验证
```powershell
cd C:\Users\72992\matrixship\backend
powershell -ExecutionPolicy Bypass -File .\build_matrix_agent.ps1
.\dist\SignSelfTest\SignSelfTest.exe   # 期望输出 FROZEN_SIGNER_OK
```
本机开发/连服务器约定见记忆:用 PowerShell + Posh-SSH 连 39.105.120.104(root/Zql@2022)。
