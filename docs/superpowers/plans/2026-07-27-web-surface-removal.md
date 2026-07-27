# Web 交付面移除与原生邀请迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除项目全部活跃 Web 页面与服务入口，将企业邀请完整迁移到 Windows 原生客户端，同时保持客户端 API、更新下载和浏览器自动化链路可用。

**Architecture:** 产品入口收敛为 `backend/matrix_native_client.py`。中心服继续提供 JSON API 和安装包下载，不再提供 HTML；企业邀请改为一次性 `inviteCode`，由客户端通过 POST 校验并完成注册或已有账号加入。删除前对所有待删除和待修改文件生成可验证离线归档，因为当前工作区大部分源文件尚未纳入 Git。

**Tech Stack:** Python 3.12 stdlib HTTP server、PySide6/Qt 原生客户端、PowerShell、unittest、OpenAPI 3.1 YAML、Inno Setup。

## Global Constraints

- 不创建独立 worktree：当前关键源文件大多未跟踪，新 worktree 无法带出完整项目状态。
- 首次改动前必须完成归档、解压复核和 SHA-256 校验；校验失败立即停止。
- 不删除 `backend/static/`、`backend/assets/`、`backend/legal/`、`backend/api_server.py` 或任何本地浏览器登录/采集/发布代码。
- 保留 `/api/version`、`/MatrixShipAgent-Setup.exe` 和 `MATRIXSHIP_AGENT_INSTALLER`。
- 邀请码不得出现在 URL、日志、审计元数据、邀请列表或持久化明文中。
- 不修改数据库 Schema；`migration.sql` 必须保持可执行 no-op。
- 使用 `.venv-win\Scripts\python.exe`；当前基线是 Python 3.12.13。
- 手工文本修改使用 `apply_patch`；目录删除前使用显式绝对路径校验，禁止通配递归删除。
- 不覆盖或回退用户已有改动；`tests/test_xhs_note_replacement.py` 当前工作区新增的 Web 测试属于本次明确删除范围，其余原生测试必须保留。
- 每次提交只暂存本任务文件；提交前运行 `git diff --cached --check` 并复核 `git diff --cached --name-status`。
- 修改 `backend/central_server.py` 或 `backend/matrix_native_client.py` 后，提交前必须同步 `docs/IMPLEMENTATION.md` 中受行偏移影响的引用。
- 任何测试失败先判断是否为基线问题，并把命令、错误和处置写入 `docs/TROUBLESHOOTING.md`。

---

## 文件映射

### 删除

- `frontend/`
- `backend/admin_console.html`
- `backend/tools/dev_proxy.py`
- `backend/LOCAL_AGENT_COMMERCIAL.md`
- `backend/SCHEME3_CLOUD_NODES.md`
- `tests/test_web_login_navigation.py`
- `docs/superpowers/specs/2026-07-18-web-interaction-usability-design.md`
- `frontend.restart.log`
- `frontend.restart.err.log`

### 创建

- `tests/test_enterprise_invites.py`：邀请码契约、泄密防护、新用户/已有用户接受邀请。
- `tests/test_native_enterprise_invite.py`：邀请码解析、错误映射和原生登录页入口。
- `tests/test_web_surface_removed.py`：Web 文件、HTML 路由、构建耦合删除门禁。

### 修改

- `backend/central_server.py`：邀请码契约、POST 校验、审计、删除 `/admin` 和前端安装包候选路径。
- `backend/matrix_native_client.py`：管理员复制邀请码、登录页“加入企业”模式和会话接入。
- `backend/build_matrix_agent.ps1`、`backend/installer/MatrixShipAgent.iss`：安装包只输出到 `backend/dist/installer`。
- `backend/agent_launcher.py`、`backend/agent_worker.py`、`backend/api_server.py`、`backend/local_browser_worker.py`、`backend/platform_adapters.py`、`backend/validate_douyin_flow.py`：把已退役项目 Web 前端表述改为原生客户端/调用方，不改变行为。
- `tests/test_digital_human_navigation.py`、`tests/test_library_video_playback.py`、`tests/test_legal_agreements.py`、`tests/test_xhs_note_replacement.py`：删除纯 Web 断言，保留后端和原生客户端覆盖。
- `tests/test_openapi_contract.py`：锁定三个邀请接口和对应 Schema。
- `docs/openapi.yaml`、`docs/API_REFERENCE.md`：邀请码请求/响应 JSON Schema。
- `docs/ARCHITECTURE.md`、`docs/DEPLOYMENT.md`、`docs/IMPLEMENTATION.md`、`docs/TROUBLESHOOTING.md`：原生入口、部署、行号、冒烟和回滚。
- `LOCAL_TEST.md`：删除前端安装包复制说明。
- `MIGRATION.md`、`backend/ENTERPRISE_DEVELOPMENT_PLAN.md`、`docs/superpowers/plans/2026-07-25-xhs-note-replacement-implementation.md`：增加 Web 假设已退役的历史说明。
- `CHANGELOG.md`、`migration.sql`：发布追踪和 no-op 迁移。

---

### Task 1: 生成回滚归档并完成 Phase 0 基线冒烟

**Files:**
- Create (ignored): `backups/web-removal-20260727/web-surface.zip`
- Create (ignored): `backups/web-removal-20260727/manifest.sha256`
- Create (ignored): `backups/web-removal-20260727/archive.sha256`
- Create (ignored): `backups/web-removal-20260727/pre-change-status.txt`
- Modify: `docs/TROUBLESHOOTING.md`

**Interfaces:**
- Consumes: 当前工作区所有将删除或修改的文件。
- Produces: 后续任务必须先验证的归档、逐文件哈希和基线测试记录。

- [ ] **Step 1: 验证工作区和归档目标都在允许范围内**

Run:

```powershell
$workspace = (Resolve-Path -LiteralPath '.').Path
$backupDir = Join-Path $workspace 'backups\web-removal-20260727'
if (-not $backupDir.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
  throw "Backup path escaped workspace: $backupDir"
}
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
git status --short | Set-Content -Encoding UTF8 (Join-Path $backupDir 'pre-change-status.txt')
```

Expected: `backups\web-removal-20260727` 创建成功，路径位于项目 `backups/` 内。

- [ ] **Step 2: 生成精确归档目标列表**

Run:

```powershell
$targets = @(
  'frontend',
  'backend/admin_console.html',
  'backend/tools/dev_proxy.py',
  'backend/LOCAL_AGENT_COMMERCIAL.md',
  'backend/SCHEME3_CLOUD_NODES.md',
  'backend/central_server.py',
  'backend/matrix_native_client.py',
  'backend/build_matrix_agent.ps1',
  'backend/installer/MatrixShipAgent.iss',
  'backend/agent_launcher.py',
  'backend/agent_worker.py',
  'backend/api_server.py',
  'backend/local_browser_worker.py',
  'backend/platform_adapters.py',
  'backend/validate_douyin_flow.py',
  'tests/test_web_login_navigation.py',
  'tests/test_auth_login_modes.py',
  'tests/test_role_permissions.py',
  'tests/test_digital_human_navigation.py',
  'tests/test_library_video_playback.py',
  'tests/test_legal_agreements.py',
  'tests/test_xhs_note_replacement.py',
  'tests/test_openapi_contract.py',
  'docs/openapi.yaml',
  'docs/API_REFERENCE.md',
  'docs/ARCHITECTURE.md',
  'docs/DEPLOYMENT.md',
  'docs/IMPLEMENTATION.md',
  'docs/TROUBLESHOOTING.md',
  'docs/superpowers/specs/2026-07-18-web-interaction-usability-design.md',
  'docs/superpowers/plans/2026-07-25-xhs-note-replacement-implementation.md',
  'frontend.restart.log',
  'frontend.restart.err.log',
  'LOCAL_TEST.md',
  'MIGRATION.md',
  'CHANGELOG.md',
  'migration.sql',
  'backend/ENTERPRISE_DEVELOPMENT_PLAN.md'
)
$missing = $targets | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing) { throw "Missing rollback targets: $($missing -join ', ')" }
# Windows PowerShell 5.1 writes a BOM for UTF8; bsdtar treats it as part of the first path.
$targets | Set-Content -Encoding ASCII (Join-Path $backupDir 'targets.txt')
```

Expected: 没有缺失目标；`targets.txt` 只包含上述相对路径。

- [ ] **Step 3: 创建归档和逐文件 SHA-256 清单**

Run:

```powershell
$ErrorActionPreference = 'Stop'
$files = foreach ($target in $targets) {
  $item = Get-Item -LiteralPath $target
  if ($item.PSIsContainer) {
    Get-ChildItem -LiteralPath $item.FullName -File -Recurse -Force
  } else {
    $item
  }
}
$files = $files | Sort-Object FullName -Unique
$workspacePrefix = $workspace + [IO.Path]::DirectorySeparatorChar
$manifest = foreach ($file in $files) {
  if (-not $file.FullName.StartsWith($workspacePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Archive target escaped workspace: $($file.FullName)"
  }
  $relative = $file.FullName.Substring($workspacePrefix.Length).Replace('\', '/')
  $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
  "$hash`t$($file.Length)`t$relative"
}
$manifest | Set-Content -Encoding UTF8 (Join-Path $backupDir 'manifest.sha256')
tar.exe -a -c -f (Join-Path $backupDir 'web-surface.zip') -T (Join-Path $backupDir 'targets.txt')
$archive = Get-Item -LiteralPath (Join-Path $backupDir 'web-surface.zip')
if ($LASTEXITCODE -ne 0 -or $archive.Length -le 0) { throw "Archive creation failed: tar exit $LASTEXITCODE" }
$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive.FullName).Hash.ToLowerInvariant()
"$archiveHash  web-surface.zip" | Set-Content -Encoding ASCII (Join-Path $backupDir 'archive.sha256')
```

Expected: archive 非空，清单至少包含当前 `frontend/` 的 36 个文件以及所有待修改文件。

- [ ] **Step 4: 解压并逐项验证归档**

Run:

```powershell
$restoreCheck = Join-Path $workspace '.tmp-validation\web-removal-restore-check'
if (Test-Path -LiteralPath $restoreCheck) {
  $resolvedCheck = (Resolve-Path -LiteralPath $restoreCheck).Path
  if (-not $resolvedCheck.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Restore check escaped workspace: $resolvedCheck"
  }
  Remove-Item -LiteralPath $resolvedCheck -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $restoreCheck | Out-Null
tar.exe -xf (Join-Path $backupDir 'web-surface.zip') -C $restoreCheck
$errors = foreach ($line in Get-Content -Encoding UTF8 (Join-Path $backupDir 'manifest.sha256')) {
  $parts = $line -split "`t", 3
  $restored = Join-Path $restoreCheck $parts[2]
  if (-not (Test-Path -LiteralPath $restored)) {
    "missing: $($parts[2])"
  } elseif ((Get-Item -LiteralPath $restored).Length -ne [long]$parts[1]) {
    "size: $($parts[2])"
  } elseif ((Get-FileHash -Algorithm SHA256 -LiteralPath $restored).Hash.ToLowerInvariant() -ne $parts[0]) {
    "hash: $($parts[2])"
  }
}
if ($errors) { throw ($errors -join [Environment]::NewLine) }
```

Expected: 无输出、无异常；归档可恢复且逐文件哈希一致。

- [ ] **Step 5: 运行基线编译和相关回归测试**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\central_server.py backend\matrix_native_client.py backend\api_server.py backend\agent_launcher.py backend\agent_worker.py backend\local_browser_worker.py
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv-win\Scripts\python.exe -m unittest tests.test_auth_login_modes tests.test_role_permissions tests.test_legal_agreements tests.test_digital_human_navigation tests.test_library_video_playback tests.test_xhs_note_replacement tests.test_api_download_contract tests.test_agent_mode_defaults tests.test_openapi_contract tests.test_structured_log -v
```

Expected: `py_compile` exit 0；测试以 `OK` 结束。若失败，先把完整失败命令、堆栈、是否为既有问题写入 `docs/TROUBLESHOOTING.md`，不得进入 Task 2。

- [ ] **Step 6: 记录 Phase 0 结果**

Add at the top of `docs/TROUBLESHOOTING.md`:

```markdown
## 2026-07-27 Web 交付面移除基线

- 环境：Windows，Python 3.12.13，Qt 使用 `offscreen`。
- 回滚：首次修改前已生成 `backups/web-removal-20260727/web-surface.zip`、逐文件 `manifest.sha256` 和归档 `archive.sha256`，并完成解压逐项复核。
- 基线：中心服、原生客户端和本地执行引擎编译检查通过；登录、权限、法律协议、企业成员、数字人、素材 Range、小红书图文同款、下载契约、客户端默认行为、OpenAPI 和结构化日志定向测试通过。
- 门禁：后续任一步出现回归，先停止改动并使用该归档对比；不得直接覆盖现有工作区数据。
```

- [ ] **Step 7: Commit**

```powershell
git add -- docs/TROUBLESHOOTING.md
git diff --cached --check
git diff --cached --name-status
git commit -m "docs: record web removal baseline"
```

Expected: 只提交 `docs/TROUBLESHOOTING.md`；`backups/` 和 `.tmp-validation/` 不进入 Git。

---

### Task 2: 用邀请码替换网页邀请契约

**Files:**
- Create: `tests/test_enterprise_invites.py`
- Modify: `backend/central_server.py:7245-7455`
- Modify: `backend/central_server.py:13640-13648`
- Modify: `backend/central_server.py:14390-14405`
- Modify: `backend/central_server.py:15298-15310`

**Interfaces:**
- Consumes: `enterprise_invite_token_hash()`, `enterprise_invite_verify()`, `accept_enterprise_invite()`。
- Produces: `POST /api/enterprise/invites/create -> inviteCode`、`POST /api/enterprise/invites/verify`、不泄密的邀请列表和接受响应。

- [ ] **Step 1: 写邀请码契约失败测试**

Create `tests/test_enterprise_invites.py` with these concrete cases:

```python
import importlib.util
from pathlib import Path
import re
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SERVER = BACKEND / "central_server.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_server_module():
    spec = importlib.util.spec_from_file_location("central_server_invites_under_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EnterpriseInviteContractTest(unittest.TestCase):
    def setUp(self):
        self.server = load_server_module()
        self.state = {
            "organizations": [{"id": "org-a", "name": "Org A", "status": "active"}],
            "users": [],
            "memberships": [],
            "enterpriseInvites": [],
            "sessions": [],
            "auditLogs": [],
        }
        self.state_patch = mock.patch.object(self.server, "STATE", self.state)
        self.persist_patch = mock.patch.object(self.server, "persist", return_value=None)
        self.state_patch.start()
        self.persist_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.addCleanup(self.persist_patch.stop)

    def create_invite(self, **overrides):
        body = {
            "recipientName": "Invitee",
            "phone": "13800000000",
            "role": "member",
            "ttlHours": 168,
        }
        body.update(overrides)
        payload, status = self.server.create_enterprise_invite(
            "org-a", body, actor={"id": "admin-1", "name": "Admin"}
        )
        self.assertEqual(status, 200)
        return payload

    def test_create_returns_secret_once_without_web_url_or_nested_token(self):
        payload = self.create_invite()
        code = payload["inviteCode"]
        self.assertRegex(code, r"^[0-9a-f]{64}$")
        self.assertNotIn("joinUrl", payload)
        self.assertNotIn("token", payload["invite"])
        self.assertNotIn("tokenHash", payload["invite"])
        self.assertNotIn(code, repr(self.state))
        listed = self.server.list_enterprise_invites("org-a")
        self.assertNotIn(code, repr(listed))

    def test_new_user_accepts_invite_and_receives_session(self):
        code = self.create_invite()["inviteCode"]
        payload, status = self.server.accept_enterprise_invite({
            "token": code,
            "name": "Invitee",
            "phone": "13800000000",
            "email": "",
            "password": "new-password-1",
            "currentPassword": "",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["token"])
        self.assertEqual(payload["orgId"], "org-a")
        self.assertEqual(payload["membership"]["role"], "member")

    def test_existing_user_requires_current_password_then_joins(self):
        user = {"id": "user-existing", "name": "Existing", "phone": "13900000000", "status": "active"}
        self.server.set_user_password(user, "current-password")
        self.state["users"].append(user)
        code = self.create_invite(phone="13900000000")["inviteCode"]
        denied, denied_status = self.server.accept_enterprise_invite({
            "token": code,
            "name": "Existing",
            "phone": "13900000000",
            "password": "replacement-password",
            "currentPassword": "wrong-password",
        })
        self.assertEqual(denied_status, 409)
        self.assertEqual(denied["error"], "existing_user_login_required")
        accepted, accepted_status = self.server.accept_enterprise_invite({
            "token": code,
            "name": "Existing",
            "phone": "13900000000",
            "password": "replacement-password",
            "currentPassword": "current-password",
        })
        self.assertEqual(accepted_status, 200)
        self.assertTrue(accepted["ok"])

    def test_verify_is_post_only_and_audited_without_secret(self):
        source = SERVER.read_text(encoding="utf-8")
        get_block = source[source.index("    def do_GET(self):"):source.index("    def do_POST(self):")]
        post_block = source[source.index("    def do_POST(self):"):]
        self.assertNotIn('path == "/api/enterprise/invites/verify"', get_block)
        self.assertIn('path == "/api/enterprise/invites/verify"', post_block)
        self.assertIn('"enterprise.invite.verify"', post_block)
        audit_call = re.search(r'add_audit\(self, "enterprise\.invite\.verify"(?P<body>.*?)\)\n', post_block, re.S)
        self.assertIsNotNone(audit_call)
        self.assertNotIn('body.get("token")', audit_call.group("body"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认旧契约失败**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_enterprise_invites -v
```

Expected: FAIL，至少出现 `KeyError: 'inviteCode'`，并指出 GET 校验路由仍存在。

- [ ] **Step 3: 删除 URL helper 并收紧公开邀请对象**

Replace the old URL helpers and token-aware serializer with:

```python
def public_enterprise_invite(invite):
    item = dict(invite or {})
    item.pop("token", None)
    item.pop("tokenHash", None)
    item.pop("inviteCode", None)
    item["status"] = enterprise_invite_status(invite)
    return item
```

Change `create_enterprise_invite` to omit `handler`, keep only the hash in `STATE`, and return:

```python
out = public_enterprise_invite(invite)
return {
    "ok": True,
    "orgId": org_id,
    "inviteCode": token,
    "invite": out,
    "message": "invite_created",
}, 200
```

Expected: `enterprise_invite_base_url()`、`enterprise_invite_join_url()`、`joinUrl` 和 nested `token` are absent from active server code.

- [ ] **Step 4: 把邀请校验从 GET 改为公开 POST**

Delete the GET branch. Immediately after `body = read_body(self)` in `do_POST`, add:

```python
if path == "/api/enterprise/invites/verify":
    payload, status = enterprise_invite_verify(body.get("token"))
    invite = payload.get("invite") if isinstance(payload.get("invite"), dict) else {}
    organization = payload.get("organization") if isinstance(payload.get("organization"), dict) else {}
    add_audit(self, "enterprise.invite.verify", path, ok=bool(payload.get("ok")), meta={
        "inviteId": invite.get("id"),
        "orgId": organization.get("id") or invite.get("orgId"),
        "status": status,
        "error": payload.get("error"),
    })
    return json_response(self, payload, status)
```

Do not include the request token in `meta` or error context.

- [ ] **Step 5: 让接受邀请响应携带完整客户端角色上下文**

At the end of `accept_enterprise_invite`, build the response with existing role helpers:

```python
ctx = auth_context_for_user(out_user)
return dict(ctx, **{
    "ok": True,
    "token": session.get("token"),
    "expiresAt": session.get("expiresAt"),
    "user": out_user,
    "membership": out_membership,
    "memberships": user_memberships(out_user.get("id")),
    "organizations": user_orgs(out_user.get("id")),
    "orgId": org_id,
    "message": "invite_accepted",
}), 200
```

Expected: native client can call `set_auth_context()` without guessing role or scope.

- [ ] **Step 6: 更新 create route 调用并运行后端测试**

Change the route call to:

```python
payload, status = create_enterprise_invite(org_id, body, actor=current_user(self))
```

Run:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\central_server.py tests\test_enterprise_invites.py
.\.venv-win\Scripts\python.exe -m unittest tests.test_enterprise_invites tests.test_role_permissions tests.test_auth_login_modes -v
```

Expected: all tests PASS; no raw invite code appears in `STATE`, list output or audit source.

- [ ] **Step 7: Commit**

Before commit, update any `docs/IMPLEMENTATION.md` references shifted by this task using the backup/current zero-context diff described in Task 5.

```powershell
git add -- backend/central_server.py tests/test_enterprise_invites.py docs/IMPLEMENTATION.md
git diff --cached --check
git diff --cached --name-status
git commit -m "feat: move enterprise invites to code contract"
```

---

### Task 3: 在原生客户端完成邀请加入流程

**Files:**
- Create: `tests/test_native_enterprise_invite.py`
- Modify: `backend/matrix_native_client.py:20-35`
- Modify: `backend/matrix_native_client.py:3238-3428`
- Modify: `backend/matrix_native_client.py:19491-20130`

**Interfaces:**
- Consumes: `POST /api/enterprise/invites/verify`、`POST /api/enterprise/invites/accept`。
- Produces: `normalize_enterprise_invite_code(value) -> str`、`enterprise_invite_error_message(code) -> str`、登录页 `invite` 模式。

- [ ] **Step 1: 写原生邀请失败测试**

Create `tests/test_native_enterprise_invite.py`:

```python
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CLIENT = BACKEND / "matrix_native_client.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_client_module():
    spec = importlib.util.spec_from_file_location("matrix_native_client_invites_under_test", CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeEnterpriseInviteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client_module()

    def test_normalize_accepts_raw_code_and_legacy_url_only(self):
        code = "a" * 64
        normalize = self.client.normalize_enterprise_invite_code
        self.assertEqual(normalize(code), code)
        self.assertEqual(normalize("https://old.example/join-enterprise.html?token=" + code), code)
        self.assertEqual(normalize("https://old.example/join-enterprise.html?token=short"), "")
        self.assertEqual(normalize("not-an-invite"), "")

    def test_error_mapping_is_actionable_and_does_not_echo_secret(self):
        code = "b" * 64
        message = self.client.enterprise_invite_error_message("invite_expired")
        self.assertIn("已过期", message)
        self.assertNotIn(code, message)

    def test_login_view_exposes_native_invite_mode(self):
        previous_bridge = self.client.BRIDGE
        view = None
        with mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}, clear=False):
            app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
            self.client.BRIDGE = self.client.Bridge()
            view = self.client.LoginView(lambda _org: None)
            try:
                view._set_mode("invite")
                self.assertTrue(view.tab_invite.isEnabled())
                self.assertTrue(view.invite_code_row.isVisibleTo(view))
                self.assertTrue(view.invite_name_in.isVisibleTo(view))
                self.assertTrue(view.invite_email_in.isVisibleTo(view))
                self.assertFalse(view.code_row.isVisibleTo(view))
                self.assertEqual(view.btn.text(), "加入企业")
            finally:
                if view is not None:
                    view.deleteLater()
                self.client.BRIDGE = previous_bridge
                app.processEvents()

    def test_client_uses_post_for_verify_and_accept(self):
        source = CLIENT.read_text(encoding="utf-8")
        self.assertIn('api("POST", "/api/enterprise/invites/verify"', source)
        self.assertIn('api("POST", "/api/enterprise/invites/accept"', source)
        self.assertIn('response.get("inviteCode")', source)
        self.assertNotIn('response.get("joinUrl")', source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认原生邀请入口尚不存在**

Run:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv-win\Scripts\python.exe -m unittest tests.test_native_enterprise_invite -v
```

Expected: FAIL with missing `normalize_enterprise_invite_code` or `tab_invite`.

- [ ] **Step 3: 新增纯邀请码解析和错误映射 helper**

Change the urllib import to include `parse_qs`, then add near the login helpers:

```python
_ENTERPRISE_INVITE_CODE_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def normalize_enterprise_invite_code(value):
    raw = str(value or "").strip()
    if "://" in raw:
        parsed = urlparse(raw)
        raw = str((parse_qs(parsed.query).get("token") or [""])[0]).strip()
    return raw.lower() if _ENTERPRISE_INVITE_CODE_RE.fullmatch(raw) else ""


def enterprise_invite_error_message(error):
    return {
        "missing_token": "请输入有效邀请码",
        "invalid_invite": "邀请码无效，请检查后重试",
        "invite_expired": "邀请码已过期，请联系管理员重新创建",
        "invite_revoked": "邀请已撤销，请联系管理员",
        "invite_accepted": "邀请已使用，请直接登录或联系管理员",
        "organization_inactive": "企业当前不可加入，请联系管理员",
        "existing_user_login_required": "该账号已存在，请输入当前密码",
        "password_too_short": "密码至少 8 位",
    }.get(str(error or ""), "加入企业失败，请稍后重试")
```

- [ ] **Step 4: 管理员端改为复制邀请码**

Keep the existing dialog structure and line count as stable as practical. Replace link copy with:

```python
elif action == "invite":
    self._show_copy_dialog(
        "邀请已创建",
        "邀请码：\n%s\n\n请通过可信渠道发送给对方，对方在本地客户端登录页选择“加入企业”。"
        % (response.get("inviteCode") or "-"),
    )
```

Change labels to `邀请码有效期` and `创建后复制邀请码发送给对方`.

- [ ] **Step 5: 在登录卡增加第三个模式和邀请字段**

Add `self.tab_invite = QtWidgets.QPushButton("加入企业")` to the existing segmented row. Add these widgets using the same `_LOGIN_INPUT_QSS` and fixed input height as current login fields:

```python
self.invite_code_row = QtWidgets.QWidget()
invite_code_layout = QtWidgets.QHBoxLayout(self.invite_code_row)
invite_code_layout.setContentsMargins(0, 0, 0, 0)
invite_code_layout.setSpacing(9)
self.invite_code_in = QtWidgets.QLineEdit()
self.invite_code_in.setPlaceholderText("邀请码")
self.invite_code_in.setStyleSheet(_LOGIN_INPUT_QSS)
self.invite_code_in.setMinimumHeight(46)
self.invite_verify_btn = QtWidgets.QPushButton("校验")
self.invite_verify_btn.setFixedSize(82, 46)
self.invite_verify_btn.clicked.connect(self.verify_enterprise_invite)
invite_code_layout.addWidget(self.invite_code_in, 1)
invite_code_layout.addWidget(self.invite_verify_btn)

self.invite_org = QtWidgets.QLabel("")
self.invite_org.setWordWrap(True)
self.invite_name_in = QtWidgets.QLineEdit()
self.invite_name_in.setPlaceholderText("姓名")
self.invite_name_in.setStyleSheet(_LOGIN_INPUT_QSS)
self.invite_name_in.setMinimumHeight(46)
self.invite_email_in = QtWidgets.QLineEdit()
self.invite_email_in.setPlaceholderText("邮箱（手机号和邮箱至少填写一项）")
self.invite_email_in.setStyleSheet(_LOGIN_INPUT_QSS)
self.invite_email_in.setMinimumHeight(46)
self.invite_current_pw_in = QtWidgets.QLineEdit()
self.invite_current_pw_in.setPlaceholderText("已有账号的当前密码")
self.invite_current_pw_in.setEchoMode(QtWidgets.QLineEdit.Password)
self.invite_current_pw_in.setStyleSheet(_LOGIN_INPUT_QSS)
self.invite_current_pw_in.setMinimumHeight(46)
self.invite_current_pw_in.hide()
self._invite_verified_code = ""
```

Wire `tab_invite` to `_set_mode("invite")`. In `_set_mode`, style all three tabs, show invitation fields only for invite mode, hide SMS/remember rows, require 8-character new password, and set button/subtitle to `加入企业` / `校验邀请码后填写账号信息`.

- [ ] **Step 6: 实现异步校验和接受邀请**

Add methods that use existing `run_bg()` and `BRIDGE.payload`:

```python
def verify_enterprise_invite(self):
    code = normalize_enterprise_invite_code(self.invite_code_in.text())
    if not code:
        self._set_msg("邀请码无效，请检查后重试", "err")
        return
    self.invite_verify_btn.setEnabled(False)
    self._set_msg("正在校验邀请码…", "info")

    def work():
        status, response = api("POST", "/api/enterprise/invites/verify", {"token": code})
        BRIDGE.payload.emit("login_invite_verify", {
            "httpStatus": status,
            "response": response if isinstance(response, dict) else {},
            "code": code,
        })

    run_bg(work)


def submit_enterprise_invite(self):
    code = self._invite_verified_code
    name = self.invite_name_in.text().strip()
    phone = self.phone_in.text().strip()
    email = self.invite_email_in.text().strip()
    password = self.pw_in.text()
    if not code:
        self._set_msg("请先校验邀请码", "err")
        return
    if not name or not (phone or email):
        self._set_msg("请填写姓名及手机号或邮箱", "err")
        return
    if len(password) < 8:
        self._set_msg("密码至少 8 位", "err")
        return
    if self.pw2_in.text() != password:
        self._set_msg("两次输入的密码不一致", "err")
        return
    self.btn.setEnabled(False)
    self._set_msg("正在加入企业…", "info")
    body = {
        "token": code,
        "name": name,
        "phone": phone,
        "email": email,
        "password": password,
        "currentPassword": self.invite_current_pw_in.text(),
    }

    def work():
        status, response = api("POST", "/api/enterprise/invites/accept", body)
        BRIDGE.payload.emit("login_invite_accept", {
            "httpStatus": status,
            "response": response if isinstance(response, dict) else {},
        })

    run_bg(work)
```

Handle `login_invite_verify` in `_on_payload`: enable the verify button; on success set `_invite_verified_code`, prefill `recipientName/recipientPhone/recipientEmail`, and show organization name/role/expiry; on failure clear verified state and call `enterprise_invite_error_message`.

Handle `login_invite_accept`: on `existing_user_login_required`, show and focus `invite_current_pw_in` without clearing fields; on success call `set_session`, `set_auth_context`, update `_SHARED["balance"]`, then emit `BRIDGE.logged_in.emit(True, org_id)`; all other errors use the sanitized error map.

At the start of `do_login`, route invite mode to `submit_enterprise_invite()` after the existing legal agreement checkbox gate.

- [ ] **Step 7: 验证原生 UI、会话和布局**

Run:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_native_enterprise_invite.py
.\.venv-win\Scripts\python.exe -m unittest tests.test_native_enterprise_invite tests.test_auth_login_modes tests.test_role_permissions tests.test_legal_agreements tests.test_login_centered_layout tests.test_login_success_transition -v
```

Expected: all PASS. Render the invite mode at 1240x780 and 900x700 to `.tmp-validation/login-invite-1240x780.png` and `.tmp-validation/login-invite-900x700.png`; verify the card is inside the viewport, all fields are readable, and no controls overlap.

- [ ] **Step 8: Commit**

Update affected `docs/IMPLEMENTATION.md` line references first.

```powershell
git add -- backend/matrix_native_client.py tests/test_native_enterprise_invite.py docs/IMPLEMENTATION.md
git diff --cached --check
git diff --cached --name-status
git commit -m "feat: accept enterprise invites in native client"
```

---

### Task 4: 删除 Web 文件、路由、构建耦合和页面测试

**Files:**
- Create: `tests/test_web_surface_removed.py`
- Delete: all paths listed under “文件映射 / 删除”
- Modify: `backend/central_server.py:13473-13605`
- Modify: `backend/build_matrix_agent.ps1:100-130`
- Modify: `backend/installer/MatrixShipAgent.iss:1-6`
- Modify: mixed tests and source comments listed in the file map

**Interfaces:**
- Consumes: verified rollback archive from Task 1.
- Produces: no active HTML/Web runtime while retaining installer download and native automation.

- [ ] **Step 1: 写 Web 删除失败测试**

Create `tests/test_web_surface_removed.py`:

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebSurfaceRemovedTest(unittest.TestCase):
    def test_product_web_files_are_absent(self):
        for relative in (
            "frontend",
            "backend/admin_console.html",
            "backend/tools/dev_proxy.py",
            "backend/LOCAL_AGENT_COMMERCIAL.md",
            "backend/SCHEME3_CLOUD_NODES.md",
            "tests/test_web_login_navigation.py",
            "docs/superpowers/specs/2026-07-18-web-interaction-usability-design.md",
        ):
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())

    def test_no_active_product_html_remains(self):
        excluded = {"backups", "node_modules", ".git", ".playwright-cli", ".tmp-validation"}
        html = [
            path for path in ROOT.rglob("*.html")
            if not excluded.intersection(path.relative_to(ROOT).parts)
        ]
        self.assertEqual(html, [])

    def test_center_no_longer_serves_admin_or_frontend_installer_path(self):
        source = (ROOT / "backend" / "central_server.py").read_text(encoding="utf-8")
        self.assertNotIn("admin_console.html", source)
        self.assertNotIn('path == "/admin"', source)
        self.assertNotIn('"frontend", "downloads"', source)
        self.assertIn("def serve_agent_installer", source)
        self.assertIn("MATRIXSHIP_AGENT_INSTALLER", source)
        self.assertIn('path == "/MatrixShipAgent-Setup.exe"', source)

    def test_build_stays_native_only(self):
        build = (ROOT / "backend" / "build_matrix_agent.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "backend" / "installer" / "MatrixShipAgent.iss").read_text(encoding="utf-8")
        self.assertNotIn("frontend\\downloads", build)
        self.assertNotIn("frontend\\downloads", installer)
        self.assertIn("dist\\installer\\MatrixShipAgent-Setup.exe", build)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认删除前失败**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_web_surface_removed -v
```

Expected: FAIL for existing `frontend/`, `admin_console.html`, `dev_proxy.py` and Web build references.

- [ ] **Step 3: 解除中心服和安装包构建的 Web 路径耦合**

In `serve_agent_installer`, keep these candidates only:

```python
candidates = [
    os.path.abspath(os.path.expandvars(os.getenv("MATRIXSHIP_AGENT_INSTALLER", ""))),
    "/root/juzhen-xingjian/MatrixShipAgent-Setup.exe",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "MatrixShipAgent-Setup.exe")),
]
```

Delete the `/admin` HTML branch. In `build_matrix_agent.ps1`, keep the generated installer and print only:

```powershell
if (Test-Path $setup) {
  Write-Host "Installer -> $setup"
}
```

Change the final first-run text to native login, not a Web pairing code. Update the Inno Setup comment to `Output: ..\dist\installer\MatrixShipAgent-Setup.exe`.

- [ ] **Step 4: 删除混合测试中的纯 Web 覆盖**

Apply these exact removals:

- `tests/test_digital_human_navigation.py`: remove `FRONTEND`, `FRONTEND_DIST`, and `test_web_content_production_menu_exposes_digital_human`.
- `tests/test_library_video_playback.py`: remove `FRONTEND` and `test_library_video_cards_render_playable_video_element`; retain HTTP Range parsing.
- `tests/test_legal_agreements.py`: remove `FRONTEND`, `FRONTEND_DIST`, `test_web_login_submits_versioned_legal_consent`, and `test_web_local_static_frontend_points_api_to_central_port`.
- `tests/test_xhs_note_replacement.py`: remove `json`/`subprocess` imports if unused and remove the entire `XhsNoteWebUiTests`; retain `XhsNoteNativeUiTests` and all backend tests.

Run the four remaining modules immediately; expected result is `OK`.

- [ ] **Step 5: 清理活跃源码中的已退役 Web 描述**

Make comment/docstring-only wording changes:

- `backend/central_server.py`: `Native client -> central_server -> execution nodes`.
- `backend/api_server.py`: replace project frontend references with `native client` or `API caller`; keep CORS behavior.
- `backend/agent_launcher.py`: describe native client and local engine.
- `backend/agent_worker.py`: describe native client uploads through central server.
- `backend/local_browser_worker.py`: change `pairing code from the web app` to `legacy pairing code from the operator`.
- `backend/platform_adapters.py`: replace `frontend flows` with `client flows`.
- `backend/validate_douyin_flow.py`: replace `hosted frontend` with `native client`.
- `backend/matrix_native_client.py`: replace `与网页版导航一致` with `原生客户端模块映射`.

No function signatures or runtime branches change in this step.

- [ ] **Step 6: 验证归档仍有效后执行显式删除**

Run archive hash verification first, then delete only resolved targets:

```powershell
$expectedArchiveHash = ((Get-Content -Encoding ASCII backups\web-removal-20260727\archive.sha256) -split '\s+')[0]
$actualArchiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath backups\web-removal-20260727\web-surface.zip).Hash.ToLowerInvariant()
if ($actualArchiveHash -ne $expectedArchiveHash) { throw 'Rollback archive hash mismatch' }
$workspace = (Resolve-Path -LiteralPath '.').Path
$deleteTargets = @(
  'frontend',
  'backend/admin_console.html',
  'backend/tools/dev_proxy.py',
  'backend/LOCAL_AGENT_COMMERCIAL.md',
  'backend/SCHEME3_CLOUD_NODES.md',
  'tests/test_web_login_navigation.py',
  'docs/superpowers/specs/2026-07-18-web-interaction-usability-design.md',
  'frontend.restart.log',
  'frontend.restart.err.log'
)
foreach ($target in $deleteTargets) {
  if (-not (Test-Path -LiteralPath $target)) { continue }
  $resolved = (Resolve-Path -LiteralPath $target).Path
  if (-not $resolved.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Delete target escaped workspace: $resolved"
  }
  Remove-Item -LiteralPath $resolved -Recurse -Force
}
```

Expected: only listed targets disappear; `backend/static/`, `backend/assets/`, `backend/legal/` and installer output remain.

- [ ] **Step 7: 运行 Web 删除和本地客户端回归**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\central_server.py backend\matrix_native_client.py backend\api_server.py backend\agent_launcher.py backend\agent_worker.py backend\local_browser_worker.py
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv-win\Scripts\python.exe -m unittest tests.test_web_surface_removed tests.test_enterprise_invites tests.test_native_enterprise_invite tests.test_auth_login_modes tests.test_role_permissions tests.test_legal_agreements tests.test_digital_human_navigation tests.test_library_video_playback tests.test_xhs_note_replacement tests.test_api_download_contract -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

Update affected implementation line references before staging.

```powershell
git add -- backend/central_server.py backend/matrix_native_client.py backend/build_matrix_agent.ps1 backend/installer/MatrixShipAgent.iss backend/agent_launcher.py backend/agent_worker.py backend/api_server.py backend/local_browser_worker.py backend/platform_adapters.py backend/validate_douyin_flow.py tests/test_web_surface_removed.py tests/test_digital_human_navigation.py tests/test_library_video_playback.py tests/test_legal_agreements.py tests/test_xhs_note_replacement.py docs/IMPLEMENTATION.md
git diff --cached --check
git diff --cached --name-status
git commit -m "refactor: remove web delivery surface"
```

Deleted untracked Web files are traced by the verified archive, `tests/test_web_surface_removed.py`, CHANGELOG and final status report.

---

### Task 5: 同步 OpenAPI、四级文档和行号索引

**Files:**
- Modify: `docs/openapi.yaml`
- Modify: `tests/test_openapi_contract.py`
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `LOCAL_TEST.md`
- Modify: `MIGRATION.md`
- Modify: `backend/ENTERPRISE_DEVELOPMENT_PLAN.md`
- Modify: `docs/superpowers/plans/2026-07-25-xhs-note-replacement-implementation.md`

**Interfaces:**
- Consumes: final Task 2-4 function locations and test results.
- Produces: OpenAPI 3.1 contract and current native-only operational documentation.

- [ ] **Step 1: 扩展 OpenAPI 失败测试**

Add these required paths and schemas to `tests/test_openapi_contract.py`:

```python
for path in (
    "/api/enterprise/invites/create",
    "/api/enterprise/invites/verify",
    "/api/enterprise/invites/accept",
):
    with self.subTest(path=path):
        self.assertIn(f"  {path}:", text)

for schema_name in (
    "EnterpriseInviteCreateRequest",
    "EnterpriseInviteCreateResponse",
    "EnterpriseInviteVerifyRequest",
    "EnterpriseInviteVerifyResponse",
    "EnterpriseInviteAcceptRequest",
    "EnterpriseInviteAcceptResponse",
):
    with self.subTest(schema=schema_name):
        self.assertIn(f"    {schema_name}:", text)
```

Run the test; expected FAIL because invite paths are not yet documented.

- [ ] **Step 2: 定义三个邀请接口的 OpenAPI 3.1 Schema**

Add three POST paths. Requirements:

- create requires authenticated admin, request has `orgId`, recipient fields, role and `ttlHours`; response requires top-level `inviteCode` matching `^[0-9a-f]{64}$` and forbids `joinUrl`.
- verify request is `{token}` with the same 64-hex pattern; response includes sanitized `invite` and `organization`.
- accept request includes token, name, phone/email, password and optional currentPassword; response includes token, user, membership, memberships, organizations, appRole and roleScope.
- all error responses reference `ErrorResponse`; 409 includes `existing_user_login_required`; 410 covers expired/revoked/accepted/inactive.
- every object sets `additionalProperties` deliberately; secret-bearing request objects use `additionalProperties: false`.

Run:

```powershell
.\.venv-win\Scripts\python.exe -c "import pathlib,yaml; p=pathlib.Path('docs/openapi.yaml'); d=yaml.safe_load(p.read_text(encoding='utf-8')); assert d['openapi']=='3.1.0'; assert '/api/enterprise/invites/verify' in d['paths']; print('OPENAPI_OK')"
.\.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v
```

Expected: `OPENAPI_OK` and test PASS.

- [ ] **Step 3: 更新 API 和架构文档**

Document in `docs/API_REFERENCE.md`:

- invite code is returned once at create time;
- verify is POST-only to avoid URL logging;
- list, verify response and audit never expose code/hash;
- existing-user retry semantics and stable error codes.

Update `docs/ARCHITECTURE.md` so the product entry is the native client. Replace `前端隐藏` with `客户端 UI 隐藏`; remove the Web XHS entry and add the native invite data flow.

- [ ] **Step 4: 更新部署、测试和历史说明**

- `docs/DEPLOYMENT.md`: remove `frontend/index.html` rollback references; document installer env path and native-only topology.
- `LOCAL_TEST.md`: installer output ends at `backend\dist\installer\MatrixShipAgent-Setup.exe`.
- `MIGRATION.md`: add a top banner stating all SPA/Web assumptions below are historical and retired on 2026-07-27; replace the current architecture block with native client -> central -> local engine/worker.
- `backend/ENTERPRISE_DEVELOPMENT_PLAN.md`: add a top historical notice linking to current architecture; do not present frontend steps as active delivery instructions.
- `docs/superpowers/plans/2026-07-25-xhs-note-replacement-implementation.md`: add a top note that its Web tasks are retired and only native/backend history remains relevant.
- `docs/TROUBLESHOOTING.md`: remove obsolete active Web login and Web XHS page troubleshooting blocks; add invite code errors and `/admin` retirement behavior.

- [ ] **Step 5: 原子更新 IMPLEMENTATION 行号**

First inspect line-changing hunks against the verified baseline:

```powershell
git diff --no-index --unified=0 -- .tmp-validation\web-removal-restore-check\backend\central_server.py backend\central_server.py
git diff --no-index --unified=0 -- .tmp-validation\web-removal-restore-check\backend\matrix_native_client.py backend\matrix_native_client.py
rg -n 'backend/central_server\.py#L|backend/matrix_native_client\.py#L|frontend/' docs\IMPLEMENTATION.md
```

Apply each hunk's line delta to pre-existing references located after that hunk. Manually recalculate references that overlap changed logic using:

```powershell
rg -n 'def public_enterprise_invite|def create_enterprise_invite|def accept_enterprise_invite|def serve_agent_installer|/api/enterprise/invites/verify|/api/enterprise/invites/create|/api/enterprise/invites/accept' backend\central_server.py
rg -n 'def normalize_enterprise_invite_code|def enterprise_invite_error_message|def invite_member|class LoginView|def verify_enterprise_invite|def submit_enterprise_invite|def _on_payload|def do_login' backend\matrix_native_client.py
```

Remove all active `frontend/...#L...` entries. Add a new top section with exact final ranges for backend invite serialization/routes, native admin copy, native join mode, three new tests, build output, and rollback archive. Verify every referenced line is within the target file and visibly contains the described logic.

- [ ] **Step 6: 文档引用扫描**

Run:

```powershell
rg -n -S 'frontend|join-enterprise\.html|admin_console\.html|dev_proxy|Web 端|Web端|网页版|Web 登录|网页前端|hosted frontend' docs\ARCHITECTURE.md docs\API_REFERENCE.md docs\DEPLOYMENT.md docs\TROUBLESHOOTING.md docs\IMPLEMENTATION.md LOCAL_TEST.md backend\*.py backend\installer\MatrixShipAgent.iss
```

Expected: no active deployment/runtime reference. Allowed mentions are limited to the current removal design/plan, CHANGELOG, explicitly marked historical documents, and rollback archive paths.

- [ ] **Step 7: Commit**

```powershell
git add -- docs/openapi.yaml tests/test_openapi_contract.py docs/API_REFERENCE.md docs/ARCHITECTURE.md docs/DEPLOYMENT.md docs/IMPLEMENTATION.md docs/TROUBLESHOOTING.md LOCAL_TEST.md MIGRATION.md backend/ENTERPRISE_DEVELOPMENT_PLAN.md docs/superpowers/plans/2026-07-25-xhs-note-replacement-implementation.md
git diff --cached --check
git diff --cached --name-status
git commit -m "docs: document native-only delivery"
```

---

### Task 6: 发布记录、完整验证和最终审计

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `migration.sql`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md` only if final formatting shifts line references

**Interfaces:**
- Consumes: all previous task outputs.
- Produces: verified release record, no-op migration and final smoke evidence.

- [ ] **Step 1: 更新发布与 no-op 迁移记录**

Add a 2026-07-27 CHANGELOG entry covering:

- removed `frontend/`, admin HTML, dev proxy and Web tests;
- native invite code flow for new and existing users;
- retained version/installer download and browser automation;
- rollback archive path and error-rate rollback threshold of 1%;
- no database changes.

Replace `migration.sql` with this release-specific no-op:

```sql
-- Release: 2026-07-27 native-only delivery and enterprise invite-code migration.
-- Database schema/data changes: none.
-- Existing users, organizations, memberships, invites, and sessions remain unchanged.
-- This no-op migration is intentionally retained for release traceability.
BEGIN;
COMMIT;
```

- [ ] **Step 2: 运行编译、OpenAPI 和定向测试门禁**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\central_server.py backend\matrix_native_client.py backend\api_server.py backend\agent_launcher.py backend\agent_worker.py backend\local_browser_worker.py tests\test_enterprise_invites.py tests\test_native_enterprise_invite.py tests\test_web_surface_removed.py
.\.venv-win\Scripts\python.exe -c "import pathlib,yaml; yaml.safe_load(pathlib.Path('docs/openapi.yaml').read_text(encoding='utf-8')); print('OPENAPI_OK')"
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv-win\Scripts\python.exe -m unittest tests.test_enterprise_invites tests.test_native_enterprise_invite tests.test_web_surface_removed tests.test_auth_login_modes tests.test_role_permissions tests.test_legal_agreements tests.test_digital_human_navigation tests.test_library_video_playback tests.test_xhs_note_replacement tests.test_openapi_contract tests.test_api_download_contract tests.test_agent_mode_defaults tests.test_native_publish tests.test_structured_log tests.test_deployment_security -v
```

Expected: compile exit 0, `OPENAPI_OK`, all tests `OK`.

- [ ] **Step 3: 运行完整 unittest 回归**

Run:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv-win\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: `OK`. If an unrelated external-media or environment test fails, record exact test, stack, baseline comparison and why it does not invalidate this release; all invite/Web/native focused tests must pass without exception.

- [ ] **Step 4: 启动隔离中心服并做 HTTP 冒烟**

Use a non-production port and temporary data directory:

```powershell
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path '.').Path
$smokeData = Join-Path $workspace '.tmp-validation\web-removal-central'
if (Test-Path -LiteralPath $smokeData) {
  $resolvedSmokeData = (Resolve-Path -LiteralPath $smokeData).Path
  if (-not $resolvedSmokeData.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Smoke data path escaped workspace: $resolvedSmokeData"
  }
  Remove-Item -LiteralPath $resolvedSmokeData -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $smokeData | Out-Null
$oldHost = $env:CENTRAL_HOST
$oldPort = $env:CENTRAL_PORT
$oldData = $env:CENTRAL_DATA_DIR
$oldPythonPath = $env:PYTHONPATH
$env:CENTRAL_HOST = '127.0.0.1'
$env:CENTRAL_PORT = '19080'
$env:CENTRAL_DATA_DIR = $smokeData
$env:PYTHONPATH = (Resolve-Path '.\.venv-win\Lib\site-packages').Path + ';' + (Resolve-Path '.\backend').Path
$basePython = (& .\.venv-win\Scripts\python.exe -c 'import sys; print(sys._base_executable)').Trim()
$process = $null
try {
  # Use one base-Python process so cleanup does not leave the Windows venv launcher's child behind.
  $code = "import runpy, sys, types; dotenv = types.ModuleType('dotenv'); dotenv.load_dotenv = lambda *args, **kwargs: False; sys.modules['dotenv'] = dotenv; runpy.run_path('backend/central_server.py', run_name='__main__')"
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $basePython
  $psi.Arguments = '-c "' + $code + '"'
  $psi.WorkingDirectory = $workspace
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $psi
  if (-not $process.Start()) { throw 'Central smoke process did not start' }
  $ready = $false
  for ($i = 0; $i -lt 20; $i++) {
    if ($process.HasExited) { throw "Central smoke server exited early: $($process.ExitCode)" }
    try {
      $health = Invoke-RestMethod -Uri 'http://127.0.0.1:19080/api/health' -TimeoutSec 2
      if ($health.ok) { $ready = $true; break }
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  if (-not $ready) { throw 'Central smoke server did not become healthy' }
  try {
    Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:19080/admin' -TimeoutSec 3 | Out-Null
    throw '/admin unexpectedly returned success'
  } catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
  }
  try {
    Invoke-RestMethod -Method Post -ContentType 'application/json' -Body '{"token":"invalid"}' -Uri 'http://127.0.0.1:19080/api/enterprise/invites/verify' | Out-Null
    throw 'Invalid invite unexpectedly returned success'
  } catch [System.Net.WebException] {
    $response = $_.Exception.Response
    if (-not $response -or $response.StatusCode.value__ -ne 404) { throw }
    $stream = $response.GetResponseStream()
    $reader = New-Object System.IO.StreamReader($stream)
    try {
      $verify = $reader.ReadToEnd() | ConvertFrom-Json
    } finally {
      $reader.Dispose()
      $stream.Dispose()
    }
  }
  if ($verify.error -ne 'invalid_invite') { throw 'Invite verify smoke returned unexpected payload' }
} finally {
  if ($process) {
    if (-not $process.HasExited) { $process.Kill() }
    $process.WaitForExit()
    $process.Dispose()
  }
  $env:CENTRAL_HOST = $oldHost
  $env:CENTRAL_PORT = $oldPort
  $env:CENTRAL_DATA_DIR = $oldData
  $env:PYTHONPATH = $oldPythonPath
}
Start-Sleep -Milliseconds 500
try {
  Invoke-RestMethod -Uri 'http://127.0.0.1:19080/api/health' -TimeoutSec 1 | Out-Null
  throw 'Central smoke port is still live after cleanup'
} catch [System.Net.WebException] {
  # Expected: the isolated process is gone and the test port refuses connections.
}
```

Expected: health `ok=true`, `/admin` returns 404, POST verify returns structured `invalid_invite`, and port 19080 is closed after cleanup.

- [ ] **Step 5: 最终静态和回滚审计**

Run:

```powershell
if (Test-Path -LiteralPath frontend) { throw 'frontend directory still exists' }
$activeHtml = Get-ChildItem -File -Recurse -Filter '*.html' | Where-Object {
  $_.FullName -notmatch '\\(backups|node_modules|\.git|\.playwright-cli|\.tmp-validation)\\'
}
if ($activeHtml) { throw "Active HTML remains: $($activeHtml.FullName -join ', ')" }
$expectedArchiveHash = ((Get-Content -Encoding ASCII backups\web-removal-20260727\archive.sha256) -split '\s+')[0]
$actualArchiveHash = (Get-FileHash -Algorithm SHA256 backups\web-removal-20260727\web-surface.zip).Hash.ToLowerInvariant()
if ($actualArchiveHash -ne $expectedArchiveHash) { throw 'Rollback archive changed' }
git status --short
git diff --check
```

Expected: no active HTML, archive hash unchanged, no whitespace errors; unrelated user changes remain visible and untouched.

- [ ] **Step 6: 把最终结果写入排障文档并复核行号**

Append the exact commands and observed pass/fail counts to the 2026-07-27 section of `docs/TROUBLESHOOTING.md`. Re-run all `rg -n` symbol queries from Task 5 and verify `docs/IMPLEMENTATION.md` line references after final documentation edits.

- [ ] **Step 7: Final commit**

```powershell
git add -- CHANGELOG.md migration.sql docs/TROUBLESHOOTING.md docs/IMPLEMENTATION.md
git diff --cached --check
git diff --cached --name-status
git commit -m "chore: finalize native-only release records"
```

- [ ] **Step 8: Final review checkpoint**

Report:

- exact removed paths and file count/bytes;
- native invite behavior for new and existing users;
- focused and full test results;
- HTTP smoke results;
- rollback archive path and verified SHA file;
- any remaining unrelated dirty-worktree files or residual risk.
