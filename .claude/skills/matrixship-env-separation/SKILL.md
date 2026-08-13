---
name: matrixship-env-separation
description: 区分「本地测试」与「公网正式」两套环境，并约束发布动作。当涉及 MatrixShip / 矩阵星舰 / 云灵星图 的客户端、中心服、安装包、部署、排查线上问题、"为什么公网下载的软件…"、"本地能跑线上不行"、改配置或上传安装包时，必须先读本文件。
---

# MatrixShip 环境区分与发布纪律

本项目有**两套完全独立的运行环境**，长得几乎一样。把它们搞混会导致：在 A 上排查 B 的故障、把只在 A 验证过的改动发到 B、或者把 B 的修复覆盖掉。这些都真实发生过（2026-08-06）。

## 第一步:先确定你在说哪一套

**任何排查、任何改动之前，先回答"这是本地还是公网"。答不上来就去问，别猜。**

| | 本地测试 | 公网正式 |
|---|---|---|
| 客户端 | 源码跑 `backend/matrix_native_client.py`（`start-visible-client.bat`） | 安装版 exe，默认装在 `%LOCALAPPDATA%\MatrixShipAgent\app`（本机实例在 `D:\数字人\app`） |
| 中心服 | 本机 `http://127.0.0.1:9080` | `https://central.yunlingai.net`（阿里云容器 `matrixship-central-prod-matrix-central-1`） |
| 数据目录 | `backend/datas` | `<安装目录>\_internal\datas` |
| 客户端日志 | `backend/datas/logs/client-YYYYMMDD.log` | `<安装目录>\_internal\datas\logs\client-YYYYMMDD.log` |
| 主库 | 通常连不到，`maindb_on()` 为 False | 漫剧 MySQL，真实用户余额 |
| 扣费 | 不产生真实消耗 | **动真钱**，写 `model_usage_logs` / `computing_power_records` |

### 一眼判定

客户端日志第一行就写着连的是谁：

```
MatrixShipAgent 启动 v1.1.16 · 中心服 https://central.yunlingai.net
```

看到 `127.0.0.1:9080` 就是本地，看到 `central.yunlingai.net` 就是公网。**排查任何"公网软件有问题"，第一件事是确认用户看的日志来自安装目录，不是 `backend/datas`。**

## 第二步:代码在哪个分支，就往哪个分支的产物里发

两条分支长期并行，**同名文件内容不同**：

| 分支 | 承载 | 产物 |
|---|---|---|
| `codex/xhs-note-replacement` | 客户端主线 | Windows 安装包 |
| `codex/unified-comic-account-sso` | 线上中心服 | `/opt/matrixship-central-prod/releases/<commit>` |

**规则**：改中心服 → 在 SSO 分支（或其 worktree）改、测、发。改客户端 → 在客户端分支改、测、打包。

**曾经踩过的坑**：在客户端分支编辑 `backend/central_server.py`，却把它上传进从 SSO 分支复制出来的 release 目录，一次性把 SSO 分支的四处线上修复（登录 fail-closed、主库探测顺序、密码后端 503、下载入库）**静默覆盖**。部署后健康检查全绿，问题几小时后才被发现。

发布前必查：

```bash
# 线上正在跑的代码里，本该存在的关键标记还在不在
docker exec matrixship-central-prod-matrix-central-1 \
  grep -c 'require_main_db_auth_source\|password_backend_failure\|libraryErrorId' /app/central_server.py
```

跨分支需要同一个修复时，用 `git cherry-pick -x`，不要手工复制文件。

## 第三步:发布是有门槛的动作

> **本地改动默认不上公网。** 公网发布必须是显式决定，且逐条过完下面的清单。

### 中心服发布

1. 工作区干净：`git status --short` 只有你自己的文件。有别人未提交的改动就停下——一起发出去就是把半成品推给用户
2. 从**当前 release** 复制新目录（保住 `.env.prod` 等只在服务器上的文件），别从旧的复制
3. 只覆盖你确实改了的文件
4. 上传后逐个比对 SHA-256，与本地一致才继续
5. 构建镜像 → 切 `current` 软链 → `up -d` → 等 healthy
6. **在运行中的容器里验证行为**，不是只看 `/api/health` 200

回滚：把 `current` 指回上个 release，用旧 `IMAGE_TAG` 重启。旧 release 目录和镜像都保留着。

### 客户端安装包发布

线上路径：`/root/AI-CanvasPro/MatrixShipAgent-Setup.exe`

1. 干净工作区打包（别人的未提交改动会被一起打进去）
2. 签名自检必须过：`dist/SignSelfTest/SignSelfTest.exe` → `FROZEN_SIGNER_OK`
3. **验证冻结产物里的关键常量**，不是只看源码：

```bash
python - <<'PY'
from PyInstaller.archive.readers import CArchiveReader
import marshal
car = CArchiveReader('dist/MatrixShipAgent/MatrixShipAgent.exe')
for name in car.toc:
    if name != 'matrix_native_client': continue
    b = car.extract(name); b = b[1] if isinstance(b, tuple) else b
    print([c for c in marshal.loads(b).co_consts if isinstance(c, str) and 'yunlingai' in c])
PY
```

4. 备份线上包并记录 SHA-256 → 上传成 `.incoming-*` → 比对哈希 → `mv -T` 原子替换
5. **从公网真下载一次并比对哈希**——用户拿到的字节才算数

回滚：把 `.bak-*` 移回原路径即可，无需重启任何服务。

## 排查纪律

### 先确认测量环境本身是干净的

**排查网络问题前，先看有没有本地代理。**

```bash
env | grep -iE '^(http_proxy|https_proxy|all_proxy|no_proxy)='
curl --noproxy '*' ...   # 对比走代理与不走代理
```

曾经因为开发机上有 `HTTP_PROXY=http://127.0.0.1:10808`，测出"443 被针对性限速 22 倍、握手 40% 失败"，据此推导出"TLS 被干扰、要换非标准端口"的完整错误结论，还动了生产 nginx。绕过代理后：3.59 MB/s、20/20 全通，服务器一直是好的。

判据：到远程服务器的 `time_connect` 只有零点几毫秒 → 你连的是本机代理，不是服务器。

注意 `requests` **默认读这两个环境变量**，所以客户端也会走代理。

### 在真正会跑的东西上验证

- 改了中心服 → 在**运行中的容器**里验证，不是只跑本地单测
- 改了客户端 → 验证**冻结后的 exe**，源码测试通过不等于打包后一致（依赖可能没被 PyInstaller 打进去，而降级分支往往是静默的）
- 改了扣费 → 造一笔**真实且保持终态**的记录去看界面。曾经自检"通过"只是因为随后退了款把状态改写了，真正的扣费状态值其实是错的

### 症状归属

看到问题先分层，别急着改代码：

| 症状 | 大概率在哪 |
|---|---|
| 登录不上 | 中心服（主库/密码后端/鉴权） |
| 下载"失败"但文件其实在本地 | 中心服的入库/结果改写 |
| 分解的转写或视觉失败 | 中心服的 `/lk888` 代理，或客户端网络 |
| 只有大请求超时、小请求正常 | 上行带宽（先查代理） |
| 两个界面数字对不上 | 统计口径，不一定是数据错 |

## 硬性停止

遇到下列情况，先说明情况再动手，不要自行推进：

- 分不清当前是本地还是公网
- 工作区有别人未提交的改动，而你要打包或发布
- 改动会动到真实用户余额
- 要动共享 nginx（同一容器还在服务漫剧等站点）
- 线上现象与本地复现不一致，且尚未确认测量环境干净
