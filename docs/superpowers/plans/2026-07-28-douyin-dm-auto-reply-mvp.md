# Douyin DM Auto Reply MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the confirmed MVP for automatic replies to one specified Douyin customer DM conversation: poll every 20 seconds, merge text messages within 5 minutes, generate one AI reply, and send it through the existing local browser DM channel.

**Architecture:** Add a new local-browser task type `douyin.dm.inbox` that travels through central scheduling to the local engine. The local engine opens the specified customer profile/DM page with Playwright and returns recent messages. `DMPage` owns merge-window state, duplicate detection, non-text manual-review handling, AI generation, and reuse of the existing `douyin.dm` send path.

**Tech Stack:** Python `http.server`, Playwright sync API, PyQt, existing `unittest`, existing local-browser task dispatcher, existing `utils.structured_log.json_log`.

## Global Constraints

- Scope is MVP only: one specified Douyin customer profile URL, no full inbox scan, no multi-customer managed pool.
- Poll interval is 20 seconds.
- Same-customer auto replies are merged and sent at most once per 5 minutes.
- Only pure text customer messages are auto-replied to.
- Image, voice, video, emoji, card, share, and unknown messages require manual review and must not trigger auto-send.
- Logs and audit entries must not include Cookie, Authorization, complete profile URLs, or full DM text.
- No new external dependencies.
- Preserve production requirements: observable, rollbackable, traceable.
- Update documentation after implementation with final line numbers in `docs/IMPLEMENTATION.md`.

---

## File Structure

- Modify `backend/api_server.py`
  - Add DM inbox normalization helpers.
  - Add `browser_read_dm_inbox(target, limit=10, since_fingerprint="")`.
  - Add `run_douyin_dm_inbox(target, limit=10, since_fingerprint="")`.
  - Add POST route `/api/douyin/dm/inbox`.

- Modify `backend/local_browser_worker.py`
  - Add `douyin.dm.inbox` to `TASK_PATHS` and advertised `CAPABILITIES`.

- Modify `backend/central_server.py`
  - Add `douyin.dm.inbox` to `LOCAL_BROWSER_TASK_PATHS`.
  - Ensure audit metadata for local-browser tasks remains safe.

- Modify `backend/matrix_native_client.py`
  - Add DM auto-reply state helpers on `DMPage`.
  - Change `_auto_poll()` to send `sinceFingerprint`.
  - Change `_on("dm_inbox")` to buffer text, mark non-text manual review, and trigger a merge-window reply.
  - Change `_on("sales_reply")` and `_on("dm")` to mark auto-send success/failure correctly.

- Create or extend `tests/test_douyin_dm_auto_reply.py`
  - Covers task mapping, central whitelist, API route contract, DM message normalization, and client source contracts.

- Modify docs:
  - `docs/API_REFERENCE.md`
  - `docs/TROUBLESHOOTING.md`
  - `docs/IMPLEMENTATION.md`
  - `CHANGELOG.md`
  - `migration.sql` only if a DB schema change is introduced. MVP should keep it no-op.

---

### Task 1: Task Type Contracts

**Files:**
- Test: `tests/test_douyin_dm_auto_reply.py`
- Modify: `backend/local_browser_worker.py`
- Modify: `backend/central_server.py`

**Interfaces:**
- Consumes: Existing `TASK_PATHS`, `CAPABILITIES`, `LOCAL_BROWSER_TASK_PATHS`, `LOCAL_BROWSER_ALLOWED_TYPES`.
- Produces: Task type `douyin.dm.inbox` mapped to `/api/douyin/dm/inbox` in central and local worker.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_douyin_dm_auto_reply.py` with these initial tests:

```python
import importlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class DouyinDmAutoReplyContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.central = importlib.import_module("central_server")
        cls.worker = importlib.import_module("local_browser_worker")

    def test_central_allows_douyin_dm_inbox_task(self):
        self.assertEqual(
            self.central.LOCAL_BROWSER_TASK_PATHS.get("douyin.dm.inbox"),
            "/api/douyin/dm/inbox",
        )
        self.assertIn("douyin.dm.inbox", self.central.LOCAL_BROWSER_ALLOWED_TYPES)
        self.assertIn("douyin.dm.inbox", self.central.LOCAL_BROWSER_ALL_CAPS)

    def test_local_worker_advertises_douyin_dm_inbox_capability(self):
        self.assertEqual(
            self.worker.TASK_PATHS.get("douyin.dm.inbox"),
            "/api/douyin/dm/inbox",
        )
        self.assertIn("douyin.dm.inbox", self.worker.CAPABILITIES)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply.DouyinDmAutoReplyContractsTest -v
```

Expected: FAIL because `douyin.dm.inbox` is missing.

- [ ] **Step 3: Add local worker mapping**

In `backend/local_browser_worker.py`, add:

```python
"douyin.dm.inbox": "/api/douyin/dm/inbox",
```

near the existing `douyin.dm` mapping in `TASK_PATHS`.

- [ ] **Step 4: Add central mapping**

In `backend/central_server.py`, add:

```python
"douyin.dm.inbox": "/api/douyin/dm/inbox",
```

near the existing `douyin.dm` mapping in `LOCAL_BROWSER_TASK_PATHS`.

- [ ] **Step 5: Run test to verify it passes**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply.DouyinDmAutoReplyContractsTest -v
```

Expected: PASS.

- [ ] **Step 6: Commit task**

```powershell
git add backend/local_browser_worker.py backend/central_server.py tests/test_douyin_dm_auto_reply.py
git commit -m "feat: allow douyin dm inbox local tasks"
```

---

### Task 2: DM Inbox API Contract and Normalization

**Files:**
- Test: `tests/test_douyin_dm_auto_reply.py`
- Modify: `backend/api_server.py`

**Interfaces:**
- Consumes: Existing `Handler.do_POST`, `json_response`, and `run_douyin_dm()`.
- Produces:
  - `_dm_text_fingerprint(value: str) -> str`
  - `_normalize_dm_inbox_message(raw: dict, index: int) -> dict`
  - `run_douyin_dm_inbox(target: str, limit: int = 10, since_fingerprint: str = "") -> dict`
  - POST `/api/douyin/dm/inbox`

- [ ] **Step 1: Add failing tests for helpers and route**

Append to `tests/test_douyin_dm_auto_reply.py`:

```python
import io
import json
from unittest import mock


class DouyinDmInboxApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = importlib.import_module("api_server")

    def make_handler(self, payload):
        body = json.dumps(payload).encode("utf-8")
        handler = object.__new__(self.api.Handler)
        handler.path = "/api/douyin/dm/inbox"
        handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)
        return handler

    def test_normalize_dm_text_message_has_stable_fingerprint(self):
        msg = self.api._normalize_dm_inbox_message(
            {"direction": "customer", "kind": "text", "text": "想了解价格", "createdAtText": "14:20"},
            0,
        )
        self.assertEqual(msg["direction"], "customer")
        self.assertEqual(msg["kind"], "text")
        self.assertEqual(msg["text"], "想了解价格")
        self.assertTrue(msg["fingerprint"])
        self.assertLessEqual(len(msg["text"]), 1000)

    def test_normalize_dm_non_text_message_has_empty_text(self):
        msg = self.api._normalize_dm_inbox_message(
            {"direction": "customer", "kind": "image", "text": "ignored raw"},
            1,
        )
        self.assertEqual(msg["kind"], "image")
        self.assertEqual(msg["text"], "")

    def test_dm_inbox_route_requires_target(self):
        handler = self.make_handler({})
        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "missing_target")

    def test_dm_inbox_route_returns_browser_result(self):
        handler = self.make_handler({"target": "https://www.douyin.com/user/sec", "limit": 5})
        result = {
            "ok": True,
            "platform": "douyin",
            "target": "https://www.douyin.com/user/sec",
            "messages": [],
            "nonTextCount": 0,
        }
        with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "run_douyin_dm_inbox", return_value=result), \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply.DouyinDmInboxApiTest -v
```

Expected: FAIL because helpers and route do not exist.

- [ ] **Step 3: Implement normalization helpers**

In `backend/api_server.py`, near `browser_send_dm()`, add helpers:

```python
def _dm_text_fingerprint(value):
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]


def _normalize_dm_inbox_message(raw, index=0):
    raw = raw if isinstance(raw, dict) else {}
    kind = str(raw.get("kind") or raw.get("type") or "text").strip().lower()
    if kind not in ("text", "image", "voice", "video", "card", "emoji", "unknown"):
        kind = "unknown"
    direction = str(raw.get("direction") or raw.get("from") or "").strip().lower()
    direction = "me" if direction in ("me", "self", "mine") else "customer"
    text = str(raw.get("text") or raw.get("content") or "").strip()
    if kind != "text":
        text = ""
    text = text[:1000]
    basis = "|".join([
        direction,
        kind,
        text,
        str(raw.get("createdAtText") or raw.get("time") or ""),
        str(index),
    ])
    fingerprint = str(raw.get("fingerprint") or raw.get("id") or _dm_text_fingerprint(basis))
    return {
        "id": str(raw.get("id") or fingerprint),
        "fingerprint": fingerprint,
        "direction": direction,
        "kind": kind,
        "text": text,
        "createdAtText": str(raw.get("createdAtText") or raw.get("time") or ""),
    }
```

- [ ] **Step 4: Implement `run_douyin_dm_inbox()` wrapper**

Add:

```python
def run_douyin_dm_inbox(target, limit=10, since_fingerprint=""):
    target = (target or "").strip()
    if not target:
        return {"ok": False, "error": "missing_target"}
    try:
        limit = max(1, min(int(limit or 10), 20))
    except Exception:
        limit = 10
    return browser_read_dm_inbox(target, limit=limit, since_fingerprint=since_fingerprint)
```

- [ ] **Step 5: Add POST route**

In `Handler.do_POST`, before `/api/douyin/dm`, add:

```python
if path == '/api/douyin/dm/inbox':
    try:
        data = run_douyin_dm_inbox(
            body.get('target') or body.get('userUrl') or body.get('secUid') or '',
            body.get('limit') or 10,
            body.get('sinceFingerprint') or '',
        )
        status = 200 if data.get('ok') else (400 if data.get('error') == 'missing_target' else 500)
        return json_response(self, data, status)
    except Exception as e:
        need_login = is_douyin_auth_error(e)
        code = 401 if need_login else 500
        return json_response(self, {'ok': False, 'needLogin': need_login, 'error': str(e), 'trace': traceback.format_exc()}, code)
```

- [ ] **Step 6: Add temporary placeholder `browser_read_dm_inbox()`**

Add a minimal implementation that validates the shape and returns an explicit unsupported error. This turns the route contract green before Playwright scraping is added:

```python
def browser_read_dm_inbox(target, limit=10, since_fingerprint=""):
    target = (target or "").strip()
    if not target:
        return {"ok": False, "error": "missing_target"}
    return {
        "ok": False,
        "platform": "douyin",
        "target": target,
        "messages": [],
        "nonTextCount": 0,
        "error": "dm_inbox_not_implemented",
    }
```

- [ ] **Step 7: Run test to verify route contract passes**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply.DouyinDmInboxApiTest -v
```

Expected: PASS.

- [ ] **Step 8: Commit task**

```powershell
git add backend/api_server.py tests/test_douyin_dm_auto_reply.py
git commit -m "feat: add douyin dm inbox api contract"
```

---

### Task 3: Playwright DM Inbox Reader

**Files:**
- Test: `tests/test_douyin_dm_auto_reply.py`
- Modify: `backend/api_server.py`

**Interfaces:**
- Consumes: `_normalize_dm_inbox_message()`.
- Produces: `browser_read_dm_inbox(target, limit=10, since_fingerprint="")` returning a real inbox result.

- [ ] **Step 1: Add source contract tests**

Append:

```python
class DouyinDmInboxBrowserSourceTest(unittest.TestCase):
    def test_browser_read_dm_inbox_uses_isolated_child_process(self):
        source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        self.assertIn("DY_DM_INBOX_CHILD", source)
        self.assertIn("__MATRIX_DM_INBOX_JSON__", source)

    def test_browser_read_dm_inbox_reports_expected_error_codes(self):
        source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        for code in (
            "dm_inbox_button_not_found",
            "dm_inbox_messages_not_found",
            "not_authenticated",
        ):
            with self.subTest(code=code):
                self.assertIn(code, source)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply.DouyinDmInboxBrowserSourceTest -v
```

Expected: FAIL because Playwright reader is still placeholder.

- [ ] **Step 3: Replace placeholder with isolated child wrapper**

Pattern after `browser_send_dm()`:

```python
def browser_read_dm_inbox(target, limit=10, since_fingerprint=""):
    from playwright.sync_api import sync_playwright
    target = (target or "").strip()
    if not target:
        return {"ok": False, "error": "missing_target"}
    try:
        limit = max(1, min(int(limit or 10), 20))
    except Exception:
        limit = 10
    if target.startswith("http"):
        profile_url = target
    elif not target.isdigit():
        profile_url = "https://www.douyin.com/user/" + target
    else:
        return {"ok": False, "error": "numeric_uid_unsupported_in_browser_dm"}

    if os.getenv("DY_DM_INBOX_CHILD", "").strip() != "1" and os.getenv("DY_DM_ISOLATED", "1").strip().lower() not in ("0", "false", "no", "off"):
        child_env = os.environ.copy()
        child_env["DY_DM_INBOX_CHILD"] = "1"
        child_env.setdefault("MATRIX_AGENT_DATA_DIR", DATA_DIR)
        child_env.setdefault("DY_DATA_DIR", DATA_DIR)
        child_env["DY_DM_INBOX_TARGET_B64"] = base64.b64encode(profile_url.encode("utf-8")).decode("ascii")
        child_env["DY_DM_INBOX_LIMIT"] = str(limit)
        child_env["DY_DM_INBOX_SINCE"] = str(since_fingerprint or "")
        child_code = r"""
import base64, json, os, sys
os.chdir(r'__BACKEND_DIR__')
sys.path.insert(0, r'__BACKEND_DIR__')
import api_server
t = base64.b64decode(os.environ.get('DY_DM_INBOX_TARGET_B64', '')).decode('utf-8')
limit = int(os.environ.get('DY_DM_INBOX_LIMIT', '10') or '10')
since = os.environ.get('DY_DM_INBOX_SINCE', '')
res = api_server.browser_read_dm_inbox(t, limit, since)
print('__MATRIX_DM_INBOX_JSON__' + json.dumps(res, ensure_ascii=False))
""".replace("__BACKEND_DIR__", os.path.dirname(os.path.abspath(__file__)).replace("\\", "\\\\"))
        try:
            proc = subprocess.run(
                [sys.executable, "-c", child_code],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=child_env,
                capture_output=True,
                text=True,
                timeout=int(os.getenv("DY_DM_INBOX_CHILD_TIMEOUT", "120") or "120"),
            )
            marker = "__MATRIX_DM_INBOX_JSON__"
            if marker in (proc.stdout or ""):
                payload = (proc.stdout or "").rsplit(marker, 1)[1].strip().splitlines()[0]
                return json.loads(payload)
            return {"ok": False, "error": "dm_inbox_child_failed", "stderr": (proc.stderr or "")[-800:], "stdout": (proc.stdout or "")[-400:]}
        except Exception as exc:
            return {"ok": False, "error": "dm_inbox_child_exception:" + str(exc)}
```

- [ ] **Step 4: Implement browser interaction in child branch**

Continue in the same function after child wrapper:

```python
edge_exe = os.getenv("DY_EDGE_PATH", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
profile_base = os.path.abspath(os.getenv("DY_DM_PROFILE_DIR", os.path.join(DATA_DIR, "dy_dm_profile")))
os.makedirs(profile_base, exist_ok=True)
profile_dir = tempfile.mkdtemp(prefix="dm_inbox_", dir=profile_base)
_seed_login_state_into_profile(profile_dir)
args = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--lang=zh-CN",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]
result = {"ok": False, "platform": "douyin", "target": profile_url, "messages": [], "nonTextCount": 0}
with sync_playwright() as p:
    kw = dict(
        headless=os.getenv("DY_DM_HEADLESS", "").strip().lower() in ("1", "true", "yes", "on"),
        args=args,
        ignore_default_args=["--enable-automation"],
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        viewport={"width": 1280, "height": 900},
    )
    if edge_exe and os.path.exists(edge_exe):
        kw["executable_path"] = edge_exe
    ctx = p.chromium.launch_persistent_context(profile_dir, **kw)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(profile_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(5000)
        if page.locator("text=登录").count() and not page.locator('text=私信, text=发私信, text=发消息').count():
            result.update({"needLogin": True, "error": "not_authenticated"})
            return result
        btn = None
        for sel in ['text=私信', 'text=发私信', 'text=发消息', 'button:has-text("私信")']:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    btn = loc
                    break
            except Exception:
                continue
        if btn is None:
            result["error"] = "dm_inbox_button_not_found"
            return result
        btn.click()
        page.wait_for_timeout(4000)
        raw_messages = page.evaluate("""(limit) => {
            const nodes = Array.from(document.querySelectorAll('[class*="message"], [class*="Message"], [data-e2e*="message"], div[role="listitem"]')).slice(-Math.max(limit * 4, 20));
            return nodes.map((node, index) => {
                const text = (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
                const html = (node.innerHTML || '').toLowerCase();
                let kind = 'text';
                if (!text) kind = 'unknown';
                if (html.includes('img') || html.includes('image')) kind = 'image';
                if (html.includes('voice') || text.includes('[语音]')) kind = 'voice';
                if (html.includes('video') || text.includes('[视频]')) kind = 'video';
                if (html.includes('emoji') || text === '[表情]') kind = 'emoji';
                if (html.includes('card') || text.includes('分享')) kind = 'card';
                const cls = (node.className || '').toString().toLowerCase();
                const direction = cls.includes('self') || cls.includes('right') || cls.includes('mine') ? 'me' : 'customer';
                return { direction, kind, text, createdAtText: '', index };
            }).filter(x => x.text || x.kind !== 'text').slice(-limit);
        }""", limit)
        messages = [_normalize_dm_inbox_message(x, i) for i, x in enumerate(raw_messages or [])]
        if since_fingerprint:
            seen = False
            filtered = []
            for item in messages:
                if item.get("fingerprint") == since_fingerprint:
                    seen = True
                    filtered = []
                    continue
                if seen:
                    filtered.append(item)
            if seen:
                messages = filtered
        result["messages"] = messages[-limit:]
        result["nonTextCount"] = len([x for x in result["messages"] if x.get("kind") != "text"])
        result["ok"] = True
        if not result["messages"]:
            result["empty"] = True
        return result
    finally:
        try:
            ctx.close()
        finally:
            shutil.rmtree(profile_dir, ignore_errors=True)
```

This DOM reader is deliberately conservative and may need selector tuning after a real-page smoke test.

- [ ] **Step 5: Run tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v
```

Expected: PASS.

- [ ] **Step 6: Commit task**

```powershell
git add backend/api_server.py tests/test_douyin_dm_auto_reply.py
git commit -m "feat: read specified douyin dm conversation"
```

---

### Task 4: Client Merge Window and Auto-Send State

**Files:**
- Test: `tests/test_douyin_dm_auto_reply.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Consumes: `submit_local_task("douyin.dm.inbox", payload, 120)`, existing `gen_reply()`, existing `send_reply()`.
- Produces:
  - `DMPage._auto_buffer_text(message: dict) -> bool`
  - `DMPage._auto_ready_to_reply(now=None) -> bool`
  - `DMPage._auto_flush_buffer() -> bool`
  - `DMPage._auto_handle_inbox_messages(messages: list) -> dict`

- [ ] **Step 1: Add source contract tests**

Append:

```python
class DouyinDmClientAutoReplySourceTest(unittest.TestCase):
    def test_client_contains_merge_window_state_and_since_fingerprint(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        self.assertIn("_auto_pending_texts", source)
        self.assertIn("_auto_last_reply_at", source)
        self.assertIn("sinceFingerprint", source)
        self.assertIn("DM_AUTO_REPLY_MERGE_WINDOW_SEC", source)

    def test_client_manual_required_does_not_auto_send_non_text(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        self.assertIn("manual_required", source)
        self.assertIn("收到非文本私信，请人工查看该客户会话。", source)

    def test_client_auto_reply_uses_existing_send_path(self):
        source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        self.assertIn("self.send_reply(reply)", source)
        self.assertIn("douyin.dm.inbox", source)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply.DouyinDmClientAutoReplySourceTest -v
```

Expected: FAIL for new state/helper strings.

- [ ] **Step 3: Add constants near `DMPage`**

In `backend/matrix_native_client.py`, near `DMPage`, add:

```python
DM_AUTO_REPLY_POLL_MS = 20000
DM_AUTO_REPLY_MERGE_WINDOW_SEC = 300
DM_AUTO_REPLY_MAX_SEEN = 100
```

- [ ] **Step 4: Initialize auto state in `DMPage.__init__`**

Add:

```python
self._auto_seen_fingerprints = []
self._auto_pending_texts = []
self._auto_last_reply_at = 0.0
self._auto_last_fingerprint = ""
self._auto_manual_required = False
```

- [ ] **Step 5: Add helper methods**

Add methods:

```python
def _auto_mark_seen(self, fingerprint):
    fp = str(fingerprint or "").strip()
    if not fp:
        return False
    if fp in self._seen:
        return False
    self._seen.add(fp)
    self._auto_seen_fingerprints.append(fp)
    self._auto_seen_fingerprints = self._auto_seen_fingerprints[-DM_AUTO_REPLY_MAX_SEEN:]
    self._auto_last_fingerprint = fp
    return True

def _auto_buffer_text(self, message):
    message = message if isinstance(message, dict) else {}
    fp = message.get("fingerprint") or message.get("id")
    if not self._auto_mark_seen(fp):
        return False
    text = str(message.get("text") or "").strip()
    if not text:
        return False
    self._auto_pending_texts.append({
        "text": text,
        "fingerprint": fp,
        "createdAtText": message.get("createdAtText") or "",
        "receivedAt": time.time(),
    })
    return True

def _auto_ready_to_reply(self, now=None):
    if not self._auto_pending_texts:
        return False
    now = float(now if now is not None else time.time())
    if self._auto_last_reply_at <= 0:
        return True
    return (now - float(self._auto_last_reply_at or 0)) >= DM_AUTO_REPLY_MERGE_WINDOW_SEC

def _auto_flush_buffer(self):
    if not self._auto_pending_texts:
        return False
    merged = "\n".join(x.get("text") or "" for x in self._auto_pending_texts if x.get("text")).strip()
    if not merged:
        self._auto_pending_texts = []
        return False
    self._auto_pending_texts = []
    self.gen_reply(merged, auto=True)
    return True

def _auto_handle_inbox_messages(self, messages):
    buffered = 0
    manual = 0
    for m in list(messages or []):
        if not isinstance(m, dict):
            continue
        if m.get("direction") == "me":
            self._auto_mark_seen(m.get("fingerprint") or m.get("id"))
            continue
        if (m.get("kind") or "text") != "text":
            if self._auto_mark_seen(m.get("fingerprint") or m.get("id")):
                manual += 1
                self._hist().append({"role": "customer", "text": "[非文本私信，请人工查看]", "status": "manual_required"})
            continue
        if self._auto_buffer_text(m):
            buffered += 1
    save_dm_conv(self._conv)
    return {"buffered": buffered, "manual": manual, "pending": len(self._auto_pending_texts)}
```

- [ ] **Step 6: Change timer interval and inbox payload**

In `toggle_auto()`, replace hard-coded `20000` with `DM_AUTO_REPLY_POLL_MS`.

In `_auto_poll()`, send:

```python
payload = {"target": t, "limit": 10, "sinceFingerprint": self._auto_last_fingerprint}
res = submit_local_task("douyin.dm.inbox", payload, 120)
```

- [ ] **Step 7: Change `dm_inbox` handling**

Replace the immediate per-message `self.gen_reply(text, auto=True)` loop with:

```python
msgs = res.get("messages") or res.get("unread") or []
summary = self._auto_handle_inbox_messages(msgs)
if summary.get("manual"):
    self.status.setText("收到非文本私信，请人工查看该客户会话。")
if self._auto_ready_to_reply():
    self._auto_flush_buffer()
elif summary.get("buffered"):
    self.status.setText(
        "全自动：已缓存 %d 条新文本，5 分钟内合并回复一次。" % summary.get("pending")
    )
else:
    self.status.setText("全自动：已检查，无新文本私信。")
```

- [ ] **Step 8: Mark auto reply success time**

In `_on("dm")`, when `ok` and an auto send is in progress, set:

```python
self._auto_last_reply_at = time.time()
```

If needed, add `self._auto_sending = True` before `self.send_reply(reply)` in the auto branch of `_on("sales_reply")`, and reset it in `_on("dm")`.

- [ ] **Step 9: Run tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply.DouyinDmClientAutoReplySourceTest -v
```

Expected: PASS.

- [ ] **Step 10: Commit task**

```powershell
git add backend/matrix_native_client.py tests/test_douyin_dm_auto_reply.py
git commit -m "feat: merge and send specified dm auto replies"
```

---

### Task 5: Observability and Safer Error Messages

**Files:**
- Test: `tests/test_douyin_dm_auto_reply.py`
- Modify: `backend/api_server.py`
- Modify: `backend/matrix_native_client.py`
- Modify: `backend/central_server.py`

**Interfaces:**
- Consumes: Existing `json_log` and `add_audit`.
- Produces: redacted structured logs for inbox polling and auto-reply decisions.

- [ ] **Step 1: Add source tests for redaction and event names**

Append:

```python
class DouyinDmAutoReplyObservabilityTest(unittest.TestCase):
    def test_observability_events_are_present(self):
        api_source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        client_source = (ROOT / "backend" / "matrix_native_client.py").read_text(encoding="utf-8")
        combined = api_source + "\n" + client_source
        for event in (
            "douyin_dm_inbox_poll_started",
            "douyin_dm_inbox_poll_finished",
            "douyin_dm_auto_reply_buffered",
            "douyin_dm_auto_reply_sent",
            "douyin_dm_auto_reply_manual_required",
            "douyin_dm_auto_reply_failed",
        ):
            with self.subTest(event=event):
                self.assertIn(event, combined)

    def test_dm_logs_use_fingerprints_not_raw_messages(self):
        source = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        self.assertIn("_dm_text_fingerprint", source)
        self.assertIn("targetFingerprint", source)
        self.assertIn("messageFingerprint", source)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply.DouyinDmAutoReplyObservabilityTest -v
```

Expected: FAIL until logging is added.

- [ ] **Step 3: Add inbox poll logs in `api_server.py`**

At start of `browser_read_dm_inbox()` after validation:

```python
json_log("info", "douyin_dm_inbox_poll_started", {
    "targetFingerprint": _dm_text_fingerprint(profile_url),
    "limit": limit,
})
```

Before each return:

```python
json_log("info", "douyin_dm_inbox_poll_finished", {
    "targetFingerprint": _dm_text_fingerprint(profile_url),
    "ok": bool(result.get("ok")),
    "messageCount": len(result.get("messages") or []),
    "nonTextCount": result.get("nonTextCount") or 0,
    "error": result.get("error") or "",
})
```

If wrapping this with `try/finally` is cleaner, use a single final log and keep error fields stable.

- [ ] **Step 4: Add client decision logs**

In `DMPage` helpers, use existing `json_log` if already imported in `matrix_native_client.py`; otherwise import it with the existing utility import pattern. Emit:

```python
json_log("info", "douyin_dm_auto_reply_buffered", {"messageFingerprint": fp, "pending": len(self._auto_pending_texts)})
json_log("info", "douyin_dm_auto_reply_manual_required", {"messageFingerprint": fp, "kind": m.get("kind") or "unknown"})
json_log("info", "douyin_dm_auto_reply_sent", {"targetFingerprint": _dm_text_fingerprint(self.target.text().strip())})
json_log("error", "douyin_dm_auto_reply_failed", {"stage": "ai" or "send", "error": error_code})
```

If `_dm_text_fingerprint` is not available client-side, add a local `_safe_text_fingerprint()` helper using SHA-256 truncated to 16 chars.

- [ ] **Step 5: Ensure central audit stays redacted**

Review `local_browser_create_task()` audit payload. If `audit_safe_body()` already redacts URLs and content adequately, keep it. If not, special-case `task_type == "douyin.dm.inbox"` to log only:

```python
{"targetFingerprint": _short_hash(payload.get("target") or ""), "limit": payload.get("limit")}
```

- [ ] **Step 6: Run tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v
```

Expected: PASS.

- [ ] **Step 7: Commit task**

```powershell
git add backend/api_server.py backend/matrix_native_client.py backend/central_server.py tests/test_douyin_dm_auto_reply.py
git commit -m "feat: add dm auto reply observability"
```

---

### Task 6: Documentation, Changelog, and Verification

**Files:**
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`
- Optionally confirm no-op: `migration.sql`

**Interfaces:**
- Consumes: final line numbers after implementation.
- Produces: production docs that match the code.

- [ ] **Step 1: Update API reference**

Add a small section for local browser task type `douyin.dm.inbox`:

```markdown
| `douyin.dm.inbox` | POST `/api/douyin/dm/inbox` | 指定客户主页私信会话读取；只返回最近消息和脱敏指纹，真实执行在用户本机浏览器。 |
```

Include request fields `target`, `limit`, `sinceFingerprint` and response fields `ok`, `messages`, `nonTextCount`, `needLogin`, `error`.

- [ ] **Step 2: Update troubleshooting**

Add an entry:

```markdown
## 全自动回复点击后没有反应或自动关闭

- 现象：勾选「全自动回复」后未开始自动回复，或提示全自动收信不可用。
- 根因：旧版本没有接通 `douyin.dm.inbox` 本地浏览器任务；未填写客户主页链接时也会立即取消开关。
- 修复：新增指定客户主页私信轮询任务、5 分钟合并回复、非文本转人工提示和脱敏结构化日志。
- 排查：先确认客户主页链接、抖音登录态、本地执行器在线，再查看 `douyin_dm_inbox_poll_finished` 和 `douyin_dm_auto_reply_failed` 日志。
- 回滚：回滚 `backend/api_server.py`、`backend/local_browser_worker.py`、`backend/central_server.py`、`backend/matrix_native_client.py`、测试和本文档即可。
```

- [ ] **Step 3: Update implementation doc with final line numbers**

After all code is in place, run line-number queries and add:

```markdown
## 2026-07-28 抖音指定客户私信全自动回复 MVP

- `backend/api_server.py#Lx-Ly`：新增 `/api/douyin/dm/inbox`、私信读取、消息归一化和脱敏日志。
- `backend/local_browser_worker.py#Lx-Ly`：新增 `douyin.dm.inbox` 本地执行器映射。
- `backend/central_server.py#Lx-Ly`：新增中心服本地浏览器任务白名单和安全审计。
- `backend/matrix_native_client.py#Lx-Ly`：`DMPage` 新增 20 秒轮询、5 分钟合并、非文本转人工和自动发送状态。
- `tests/test_douyin_dm_auto_reply.py#Lx-Ly`：覆盖任务契约、API 契约、客户端合并窗口和可观测性。
- 验证：列出实际运行命令和结果。
- 回滚：回滚上述文件；不涉及数据库迁移，`migration.sql` 保持 no-op。
```

- [ ] **Step 4: Update changelog**

Add:

```markdown
- 新增抖音指定客户私信全自动回复 MVP：每 20 秒检查指定客户会话，纯文本消息 5 分钟合并一次自动回复，非文本消息提示人工查看，并补齐本地浏览器任务、日志和测试。
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_dm_auto_reply -v
```

Expected: PASS.

- [ ] **Step 6: Run related regression tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_douyin_multi_account tests.test_api_download_contract tests.test_openapi_contract -v
```

Expected: PASS.

- [ ] **Step 7: Run compile check**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\\api_server.py backend\\local_browser_worker.py backend\\central_server.py backend\\matrix_native_client.py tests\\test_douyin_dm_auto_reply.py
```

Expected: exit code 0.

- [ ] **Step 8: Run Phase 0 smoke with fake data**

Use the test suite as the smoke harness: fake inbox returns two customer text messages and one non-text message, client buffers text, manual-review skips non-text, merged auto reply uses existing send path.

Expected: one send operation, zero sends for non-text, no duplicate send for repeated fingerprints.

- [ ] **Step 9: Optional real-page smoke**

Only if a safe test Douyin account and a test customer profile are available:

1. Start central server and local browser worker.
2. Log into Douyin through the account matrix.
3. Open「私信 / AI 销售」and fill the test customer profile URL.
4. Enable auto reply.
5. Send one pure text message from the test customer.
6. Wait for polling and the merge window behavior.
7. Confirm one generated reply is sent.
8. Send a non-text message and confirm it is not auto-sent.

If this cannot be run, final report must state that real-page smoke was not executed and why.

- [ ] **Step 10: Commit docs and verification**

```powershell
git add docs/API_REFERENCE.md docs/TROUBLESHOOTING.md docs/IMPLEMENTATION.md CHANGELOG.md migration.sql
git commit -m "docs: document douyin dm auto reply mvp"
```

---

## Self-Review Checklist

- Spec coverage: task type, local API, local worker, central whitelist, client merge window, manual-review handling, logging, tests, docs, rollback are covered.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation steps should remain.
- Type consistency: task type is consistently `douyin.dm.inbox`; local path is consistently `/api/douyin/dm/inbox`; message fields are consistently `fingerprint`, `direction`, `kind`, `text`, `createdAtText`.
- Scope check: plan does not implement full inbox scan or multi-customer automation.
