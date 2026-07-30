# Download Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a public `/download` page for the 云灵星图 AI 爆款复刻平台 Windows 客户端 with a disabled download button and no real installer link.

**Architecture:** Add a lightweight public GET route in `backend/central_server.py` that returns an embedded HTML document. Keep the existing `/MatrixShipAgent-Setup.exe` installer endpoint unchanged and explicitly test that the new page does not link to it.

**Tech Stack:** Python standard library `http.server`, existing `central_server.Handler`, `unittest`, embedded HTML/CSS, no new frontend project and no new dependencies.

## Global Constraints

- Page type: public customer download page.
- Public path: `/download`.
- First-screen title: `云灵星图 AI 爆款复刻平台 Windows 客户端下载`.
- Company name: `云灵星图数字科技有限公司`.
- Visual direction: dark technology business style.
- Download button text: `Windows 客户端即将开放下载`.
- Download button state: disabled, not clickable, no real download URL.
- The `/download` HTML must not contain `/MatrixShipAgent-Setup.exe`.
- Existing `/MatrixShipAgent-Setup.exe` behavior must remain unchanged.
- Do not hardcode secrets, API keys, database connection strings, internal deployment paths, or account authorization data.
- Use structured logs only if new logging is added; this plan does not require new logging.
- Do not create an independent frontend project.
- Do not commit unless the user explicitly approves committing after implementation and verification.

---

## File Structure

- Modify `backend/central_server.py`
  - Add `download_page_html()` returning a Unicode HTML string.
  - Add `serve_download_page(self)` to return the HTML response.
  - Add a public `GET /download` branch before `require_user(self)`.
- Modify `tests/test_web_surface_removed.py`
  - Keep the guard that old product web files are absent.
  - Add tests that `/download` is served from the center server and does not link to the installer.
- Modify `docs/API_REFERENCE.md`
  - Document `GET /download` as a public HTML page, not an API contract.
- Modify `docs/DEPLOYMENT.md`
  - Document that `/download` is shipped by center server code and does not require a frontend build.
- Modify `docs/TROUBLESHOOTING.md`
  - Add smoke-test notes for `/download` and disabled download state.
- Modify `CHANGELOG.md`
  - Record the public download page addition.
- Modify `docs/IMPLEMENTATION.md`
  - Add exact line references after implementation is complete and line numbers are known.

## Task 1: Contract Tests For The Public Download Page

**Files:**
- Modify: `tests/test_web_surface_removed.py`
- Test: `tests/test_web_surface_removed.py`

**Interfaces:**
- Consumes: existing `backend.central_server.Handler`.
- Produces: failing tests requiring `Handler.download_page_html()` and `Handler.serve_download_page()`.

- [ ] **Step 1: Add failing tests**

Add these imports near the top of `tests/test_web_surface_removed.py`:

```python
import importlib
import io
import sys
```

Add this path setup after `ROOT = Path(__file__).resolve().parents[1]`:

```python
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
```

Add these tests inside `WebSurfaceRemovedTest`:

```python
    def test_center_serves_public_download_page_contract(self):
        central = importlib.import_module("central_server")
        html = central.Handler.download_page_html()

        self.assertIn("云灵星图 AI 爆款复刻平台 Windows 客户端下载", html)
        self.assertIn("云灵星图数字科技有限公司", html)
        self.assertIn("Windows 客户端即将开放下载", html)
        self.assertIn("disabled", html)
        self.assertNotIn("/MatrixShipAgent-Setup.exe", html)

    def test_download_page_response_is_public_html(self):
        central = importlib.import_module("central_server")
        handler = object.__new__(central.Handler)
        handler.wfile = io.BytesIO()
        handler.headers = {}
        sent = []

        def send_response(status):
            sent.append(("status", status))

        def send_header(name, value):
            sent.append(("header", name, value))

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = lambda: sent.append(("end",))

        central.Handler.serve_download_page(handler)

        body = handler.wfile.getvalue().decode("utf-8")
        self.assertIn(("status", 200), sent)
        self.assertIn(("header", "Content-Type", "text/html; charset=utf-8"), sent)
        self.assertIn("云灵星图 AI 爆款复刻平台 Windows 客户端下载", body)
        self.assertIn("Windows 客户端即将开放下载", body)
        self.assertNotIn("/MatrixShipAgent-Setup.exe", body)

    def test_download_route_is_public_before_auth_gate(self):
        source = (ROOT / "backend" / "central_server.py").read_text(encoding="utf-8")
        route_index = source.index('if path == "/download":')
        auth_index = source.index("if not require_user(self):", route_index)

        self.assertLess(route_index, auth_index)
        self.assertIn("return self.serve_download_page()", source[route_index:auth_index])
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_web_surface_removed.WebSurfaceRemovedTest -v
```

Expected: fail with an error like `AttributeError: type object 'Handler' has no attribute 'download_page_html'`.

- [ ] **Step 3: Confirm the existing installer test still protects the direct installer route**

Check that `test_center_no_longer_serves_admin_or_frontend_installer_path` still includes:

```python
self.assertIn('path == "/MatrixShipAgent-Setup.exe"', source)
```

Expected: no change to that assertion.

## Task 2: Implement The Embedded Download Page

**Files:**
- Modify: `backend/central_server.py`
- Test: `tests/test_web_surface_removed.py`

**Interfaces:**
- Consumes: tests from Task 1.
- Produces:
  - `Handler.download_page_html() -> str`
  - `Handler.serve_download_page() -> None`
  - public `GET /download` response.

- [ ] **Step 1: Add the page HTML helper inside `Handler` before `serve_agent_installer`**

Insert this method in `backend/central_server.py` inside `class Handler`, immediately before `def serve_agent_installer(self):`:

```python
    @staticmethod
    def download_page_html():
        title = "云灵星图 AI 爆款复刻平台 Windows 客户端下载"
        company = "云灵星图数字科技有限公司"
        return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #080b12;
      --panel: rgba(18, 24, 38, 0.78);
      --panel-strong: rgba(22, 29, 48, 0.92);
      --line: rgba(148, 163, 184, 0.20);
      --line-strong: rgba(129, 140, 248, 0.42);
      --text: #f7f9ff;
      --sub: #aab6ca;
      --muted: #738096;
      --accent: #6366f1;
      --accent-2: #22d3ee;
      --warning: #f5c451;
    }}
    * {{ box-sizing: border-box; }}
    html {{ min-width: 320px; background: var(--bg); }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      color: var(--text);
      background:
        linear-gradient(90deg, rgba(148, 163, 184, 0.07) 1px, transparent 1px),
        linear-gradient(180deg, rgba(148, 163, 184, 0.06) 1px, transparent 1px),
        radial-gradient(circle at 70% 14%, rgba(99, 102, 241, 0.26), transparent 34%),
        radial-gradient(circle at 28% 4%, rgba(34, 211, 238, 0.13), transparent 28%),
        #080b12;
      background-size: 42px 42px, 42px 42px, auto, auto, auto;
    }}
    a {{ color: inherit; }}
    .page {{
      width: min(1160px, calc(100% - 40px));
      margin: 0 auto;
      padding: 34px 0 48px;
    }}
    .nav {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 54px;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }}
    .mark {{
      width: 38px;
      height: 38px;
      border-radius: 12px;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, rgba(99, 102, 241, 0.95), rgba(34, 211, 238, 0.85));
      color: #fff;
      font-weight: 900;
      box-shadow: 0 14px 38px rgba(34, 211, 238, 0.18);
      flex: 0 0 auto;
    }}
    .brand strong {{ display: block; font-size: 16px; line-height: 1.2; }}
    .brand span {{ display: block; margin-top: 3px; color: var(--muted); font-size: 12px; }}
    .nav-meta {{
      color: var(--sub);
      font-size: 13px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,0.03);
      white-space: nowrap;
    }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.02fr) minmax(360px, 0.98fr);
      gap: 38px;
      align-items: center;
      min-height: 560px;
    }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: #b9c3ff;
      font-size: 13px;
      font-weight: 700;
      padding: 7px 11px;
      border: 1px solid rgba(129, 140, 248, 0.35);
      border-radius: 999px;
      background: rgba(99, 102, 241, 0.10);
    }}
    h1 {{
      margin: 22px 0 18px;
      max-width: 760px;
      font-size: 52px;
      line-height: 1.08;
      font-weight: 860;
    }}
    .lead {{
      max-width: 680px;
      margin: 0 0 28px;
      color: var(--sub);
      font-size: 18px;
      line-height: 1.75;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      align-items: center;
      margin-bottom: 18px;
    }}
    .download-disabled {{
      min-height: 48px;
      padding: 0 22px;
      border: 1px solid rgba(148, 163, 184, 0.22);
      border-radius: 8px;
      background: linear-gradient(135deg, rgba(99, 102, 241, 0.42), rgba(34, 211, 238, 0.24));
      color: rgba(255,255,255,0.72);
      font-size: 15px;
      font-weight: 800;
      cursor: not-allowed;
    }}
    .status {{
      color: var(--sub);
      font-size: 13px;
      line-height: 1.6;
    }}
    .facts {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 24px;
      padding: 0;
      list-style: none;
    }}
    .facts li {{
      color: #d7def0;
      font-size: 13px;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,0.035);
    }}
    .product-panel {{
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      background: linear-gradient(180deg, var(--panel-strong), rgba(12, 17, 29, 0.92));
      box-shadow: 0 24px 80px rgba(0,0,0,0.36);
      overflow: hidden;
    }}
    .panel-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
    }}
    .dots {{ display: flex; gap: 7px; }}
    .dots span {{ width: 9px; height: 9px; border-radius: 50%; background: #44516a; }}
    .dots span:nth-child(2) {{ background: var(--accent); }}
    .dots span:nth-child(3) {{ background: var(--accent-2); }}
    .panel-status {{ color: #9fb0ca; font-size: 12px; }}
    .panel-body {{ padding: 20px; }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .metric, .flow {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,0.04);
      padding: 14px;
    }}
    .metric b {{ display: block; font-size: 23px; margin-bottom: 5px; }}
    .metric span, .flow span {{ color: var(--muted); font-size: 12px; }}
    .flow strong {{ display: block; margin: 6px 0 12px; font-size: 16px; }}
    .bar {{
      height: 8px;
      border-radius: 999px;
      background: rgba(148, 163, 184, 0.15);
      overflow: hidden;
    }}
    .bar i {{
      display: block;
      height: 100%;
      width: 72%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
    }}
    .section {{
      padding: 42px 0 0;
    }}
    .section h2 {{
      margin: 0 0 18px;
      font-size: 28px;
    }}
    .cards, .steps {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
    }}
    .card, .step, .support {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,0.035);
      padding: 18px;
    }}
    .card h3, .step h3 {{ margin: 0 0 9px; font-size: 16px; }}
    .card p, .step p, .support p {{
      margin: 0;
      color: var(--sub);
      font-size: 14px;
      line-height: 1.65;
    }}
    .step-num {{
      width: 28px;
      height: 28px;
      display: grid;
      place-items: center;
      margin-bottom: 12px;
      border-radius: 50%;
      background: rgba(99, 102, 241, 0.18);
      color: #cdd2ff;
      font-weight: 800;
      font-size: 13px;
    }}
    .support {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px 20px;
    }}
    .support p strong {{ display: block; color: var(--text); margin-bottom: 4px; }}
    @media (max-width: 900px) {{
      .page {{ width: min(100% - 28px, 680px); padding-top: 22px; }}
      .nav {{ margin-bottom: 34px; align-items: flex-start; }}
      .nav-meta {{ white-space: normal; text-align: right; }}
      .hero {{ grid-template-columns: 1fr; min-height: auto; gap: 28px; }}
      h1 {{ font-size: 38px; }}
      .lead {{ font-size: 16px; }}
      .cards, .steps {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .support {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 560px) {{
      .nav {{ flex-direction: column; }}
      .nav-meta {{ text-align: left; }}
      h1 {{ font-size: 31px; }}
      .download-disabled {{ width: 100%; }}
      .product-panel {{ margin-inline: -2px; }}
      .metric-grid, .cards, .steps {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header class="nav" aria-label="页面顶部">
      <div class="brand">
        <div class="mark" aria-hidden="true">星</div>
        <div>
          <strong>云灵星图</strong>
          <span>{company}</span>
        </div>
      </div>
      <div class="nav-meta">Windows 10/11 · 最新版即将发布</div>
    </header>

    <section class="hero">
      <div>
        <div class="eyebrow">AI 爆款复刻平台 · Windows 客户端</div>
        <h1>{title}</h1>
        <p class="lead">面向短视频内容团队的本地执行客户端，支持爆款采集、视频拆解、同款生成、素材管理与账号矩阵协作。</p>
        <div class="actions">
          <button class="download-disabled" type="button" disabled aria-disabled="true">Windows 客户端即将开放下载</button>
          <div class="status">正式安装包发布后，将由{company}提供下载。</div>
        </div>
        <ul class="facts" aria-label="下载页状态">
          <li>适用于 Windows 10/11</li>
          <li>企业账号登录</li>
          <li>{company}出品</li>
        </ul>
      </div>

      <aside class="product-panel" aria-label="产品能力概览">
        <div class="panel-head">
          <div class="dots" aria-hidden="true"><span></span><span></span><span></span></div>
          <div class="panel-status">Client Preview</div>
        </div>
        <div class="panel-body">
          <div class="metric-grid">
            <div class="metric"><b>采集</b><span>公开内容沉淀为参考素材</span></div>
            <div class="metric"><b>拆解</b><span>口播、节奏、关键帧结构化</span></div>
            <div class="metric"><b>复刻</b><span>生成可审核的新素材</span></div>
            <div class="metric"><b>协作</b><span>账号矩阵与任务中心联动</span></div>
          </div>
          <div class="flow">
            <span>内容生产链路</span>
            <strong>采集参考 → 视频拆解 → 同款生成 → 素材入库</strong>
            <div class="bar" aria-hidden="true"><i></i></div>
          </div>
        </div>
      </aside>
    </section>

    <section class="section" aria-labelledby="capabilities-title">
      <h2 id="capabilities-title">核心能力</h2>
      <div class="cards">
        <article class="card"><h3>爆款采集</h3><p>采集抖音、小红书公开内容，沉淀为参考素材。</p></article>
        <article class="card"><h3>视频拆解</h3><p>提取结构、口播、画面节奏和关键帧。</p></article>
        <article class="card"><h3>同款复刻</h3><p>基于产品、人物、场景生成可审核的新素材。</p></article>
        <article class="card"><h3>账号矩阵协作</h3><p>支持多账号、任务中心、素材与发布协同。</p></article>
      </div>
    </section>

    <section class="section" aria-labelledby="install-title">
      <h2 id="install-title">安装步骤</h2>
      <div class="steps">
        <article class="step"><div class="step-num">1</div><h3>等待开放</h3><p>正式安装包开放后，页面会更新交付状态。</p></article>
        <article class="step"><div class="step-num">2</div><h3>获取安装包</h3><p>按企业交付安排获取 Windows 客户端安装包。</p></article>
        <article class="step"><div class="step-num">3</div><h3>登录账号</h3><p>运行安装程序后，使用企业账号登录客户端。</p></article>
        <article class="step"><div class="step-num">4</div><h3>开始使用</h3><p>进入客户端完成采集、拆解、生成与素材管理。</p></article>
      </div>
    </section>

    <section class="section" aria-labelledby="support-title">
      <h2 id="support-title">安全与支持</h2>
      <div class="support">
        <p><strong>安装包来源</strong>{company}。</p>
        <p><strong>下载状态</strong>Windows 客户端即将开放下载。</p>
        <p><strong>更新机制</strong>客户端启动后会自动检查新版本。</p>
        <p><strong>数据说明</strong>平台账号授权、素材、日志按项目配置保存，下载页不展示敏感信息。</p>
      </div>
    </section>
  </main>
</body>
</html>""".format(title=title, company=company)
```

- [ ] **Step 2: Add the response method**

Insert this method immediately after `download_page_html()`:

```python
    def serve_download_page(self):
        html = self.download_page_html().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html)
```

- [ ] **Step 3: Add the public route**

In `do_GET`, add this branch before the existing installer branch:

```python
        if path == "/download":
            return self.serve_download_page()
```

The local route order should be:

```python
        if path == "/lk888" or path.startswith("/lk888/"):
            return lk888_proxy(self, "GET", parsed)
        if path.startswith("/manju-media/"):
            return manju_media_proxy(self, parsed)
        if path == "/download":
            return self.serve_download_page()
        if path == "/MatrixShipAgent-Setup.exe":
            return self.serve_agent_installer()
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_web_surface_removed.WebSurfaceRemovedTest -v
```

Expected: all tests in `WebSurfaceRemovedTest` pass.

- [ ] **Step 5: Run installer-related contract tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_api_download_contract.ApiDownloadContractTest.test_public_media_url_is_signed_https_and_verifiable -v
```

Expected: pass. This is a focused guard that central server import and public GET helpers still work.

## Task 3: Documentation, Line References, And Smoke Verification

**Files:**
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_web_surface_removed.py`

**Interfaces:**
- Consumes:
  - `Handler.download_page_html() -> str`
  - public `GET /download`
- Produces:
  - operator-facing docs for `/download`
  - rollback notes
  - exact implementation line references.

- [ ] **Step 1: Update API reference**

Add this section to `docs/API_REFERENCE.md` near the version and download-related public endpoints:

```markdown
## GET /download

公开客户下载页，返回 `text/html; charset=utf-8`。页面用于展示“云灵星图 AI 爆款复刻平台 Windows 客户端下载”的产品说明、适用系统、核心能力、安装步骤和安全支持信息。

当前下载按钮为禁用状态，文案为“Windows 客户端即将开放下载”，页面不链接真实安装包，不暴露 `/MatrixShipAgent-Setup.exe`。

回滚：删除中心服 `/download` 路由和页面渲染函数即可；现有 `/MatrixShipAgent-Setup.exe` 安装包直链不受影响。
```

- [ ] **Step 2: Update deployment documentation**

Add this section to `docs/DEPLOYMENT.md`:

```markdown
## 公开下载页

中心服内置公开页面 `/download`，不依赖独立前端构建产物。部署中心服新版本后即可访问。

当前页面仅展示下载说明，下载按钮处于禁用状态，不连接真实安装包。正式开放下载前，不需要发布安装包文件。

回滚方式：回滚中心服代码到上一稳定版本，或删除 `/download` 路由与页面渲染函数。安装包直链 `/MatrixShipAgent-Setup.exe` 不随本页面变更。
```

- [ ] **Step 3: Update troubleshooting**

Add this entry to `docs/TROUBLESHOOTING.md`:

```markdown
## 公开下载页 `/download`

- 现象：访问 `/download` 返回 404。
- 排查：确认运行中的中心服代码包含 `Handler.serve_download_page()` 和 `path == "/download"` 路由；如果代码已更新但仍为 404，重启中心服后再访问。
- 现象：页面出现真实安装包链接。
- 排查：当前阶段下载按钮必须为禁用状态，页面源码不应包含 `/MatrixShipAgent-Setup.exe`。运行 `.\.venv-win\Scripts\python.exe -m unittest tests.test_web_surface_removed.WebSurfaceRemovedTest -v` 验证。
- 回滚：删除 `/download` 路由和页面渲染函数；不需要改动安装包直链接口。
```

- [ ] **Step 4: Update changelog**

Add this entry near the top of `CHANGELOG.md`:

```markdown
## 2026-07-30

- 新增中心服内置公开下载页设计与实现入口 `/download`，用于展示“云灵星图 AI 爆款复刻平台 Windows 客户端下载”。当前下载按钮为禁用状态，不链接真实安装包。
```

- [ ] **Step 5: Update implementation line references**

After code changes are complete, calculate line numbers:

```powershell
rg -n "download_page_html|serve_download_page|path == \"/download\"" backend\central_server.py
```

Add a concise entry to `docs/IMPLEMENTATION.md` using exact line references in this format:

```markdown
## 公开下载页

- `backend/central_server.py#L13780-L14060` 内置 `/download` 页面 HTML 和响应头。
- `backend/central_server.py#L13892-L13893` 将 `/download` 注册为公开 GET 页面，位于登录鉴权前。
- `tests/test_web_surface_removed.py#L24-L62` 覆盖页面标题、公司背书、禁用按钮、无安装包链接和公开路由位置。
```

The line numbers above are an example of the required format. During implementation, replace them with the actual line numbers printed by `rg -n` and verify the final document with the command in Step 6.

- [ ] **Step 6: Run documentation and contract checks**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_web_surface_removed.WebSurfaceRemovedTest -v
```

Expected: pass.

Run:

```powershell
rg -n "TODO|TBD|L13780-L14060|L13892-L13893|L24-L62" docs\API_REFERENCE.md docs\DEPLOYMENT.md docs\TROUBLESHOOTING.md docs\IMPLEMENTATION.md
```

Expected: no matches.

- [ ] **Step 7: Smoke-check the route locally**

Start the center server in a controlled terminal:

```powershell
.\.venv-win\Scripts\python.exe backend\central_server.py
```

In a second terminal, request the page:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:9080/download | Select-Object -ExpandProperty Content
```

Expected: returned HTML contains `云灵星图 AI 爆款复刻平台 Windows 客户端下载` and `Windows 客户端即将开放下载`, and does not contain `/MatrixShipAgent-Setup.exe`.

Stop the local center server after the smoke check.

## Self-Review

- Spec coverage: The plan covers `/download`, the confirmed title, company name, disabled button, dark business visual direction, no installer link, documentation, smoke verification, and rollback.
- Placeholder scan: Implementation tasks define concrete files, route names, method names, commands, and expected results. Example line numbers are marked as examples and the final documentation verification prevents them from being left in `docs/IMPLEMENTATION.md`.
- Type consistency: `Handler.download_page_html() -> str` is used by `Handler.serve_download_page()`, and tests call those exact methods.
