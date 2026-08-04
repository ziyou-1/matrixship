# Unified Comic Account SSO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI爆款复刻 and 漫剧 share `ai_education.users` as the single ordinary-user account source, with same-style replacement mapped to the current logged-in comic user instead of fixed account `003`.

**Architecture:** Keep MatrixShip center sessions as the product session layer, but authenticate ordinary users against the existing comic MySQL user table through `backend/maindb.py`. Keep emergency `user-owner` root-token/admin-password access isolated from ordinary account login. Issue Matrix SSO tickets with the current main-database `users.id`, and configure the remote comic server to exchange those tickets into the matching AI CanvasPro user session.

**Tech Stack:** Python `http.server` center service, `pymysql`/`passlib[bcrypt]` main-db adapter, HMAC Matrix SSO tickets, existing unittest suite, OpenAPI YAML docs, Docker Compose production deployment.

## Global Constraints

- Production ordinary users must authenticate only through comic main database `ai_education.users`.
- Do not hardcode passwords, database credentials, SSO secrets, API keys, cookies, bearer tokens, or signed URLs.
- `USER_TOKEN` / `user-owner` remains an emergency operations path, not a customer login source.
- `MATRIX_COMIC_FIXED_USER_ID`, `MATRIX_COMIC_FIXED_USERNAME`, and `MATRIX_COMIC_FIXED_DISPLAY_NAME` are deprecated for production and may only be used by rollback.
- `MATRIX_COMIC_SSO_SECRET` and `AICANVAS_MATRIX_SSO_SECRET` must be the same random server-only secret with at least 32 bytes.
- Main DB enabled but unavailable must fail closed with a 503, not fall back to local JSON ordinary users.
- Every changed API contract must update `docs/openapi.yaml` and `docs/API_REFERENCE.md`.
- Every code commit must update `docs/IMPLEMENTATION.md` line references after final line numbers are known.
- `migration.sql` must be updated before deployment even when the migration is a no-op.
- Verification must include focused unit tests, `py_compile`, public health smoke, and SSO smoke evidence.

---

## File Structure

- Modify `backend/central_server.py`: account-source policy, login guard, mapped comic SSO, enterprise user creation/reset-password/invite acceptance, structured logs and audit metadata.
- Modify `backend/maindb.py`: small user lookup helpers only if tests expose a missing operation; no schema change.
- Modify `backend/.env.example`: mapped SSO production defaults and fixed-account rollback comments.
- Modify `tests/test_comic_sso.py`: replace fixed-account SSO expectation with mapped-user expectation and fixed-account rollback-only coverage.
- Create `tests/test_unified_comic_account_sso.py`: focused auth/account-source tests with fake `maindb`.
- Modify `tests/test_enterprise_invites.py`: cover invite acceptance using main-db users instead of local JSON ordinary users.
- Modify `tests/test_openapi_contract.py`: lock updated auth/SSO error contracts.
- Modify `docs/ARCHITECTURE.md`, `docs/API_REFERENCE.md`, `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`, `docs/IMPLEMENTATION.md`, `docs/openapi.yaml`, `CHANGELOG.md`, and `migration.sql`.

---

### Task 1: Phase 0 Unified Auth Smoke Skeleton

**Files:**
- Create: `tests/test_unified_comic_account_sso.py`
- Modify: none

**Interfaces:**
- Consumes: `central_server.shape_mdb_user(row, auth_type="session", session_id=None)`, `central_server.verify_user_password(user, password)`, `central_server.issue_comic_sso_ticket_for_user(user, org_id, now_ts=None, nonce=None)`.
- Produces: a failing smoke test that proves the intended chain: fake main-db row -> Matrix-shaped user -> password verification -> mapped SSO ticket.

- [ ] **Step 1: Write the failing smoke test**

Add `tests/test_unified_comic_account_sso.py`:

```python
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SERVER = BACKEND / "central_server.py"
SSO = BACKEND / "matrix_sso.py"


def load_module(name, path):
    backend_text = str(BACKEND)
    if backend_text not in sys.path:
        sys.path.insert(0, backend_text)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeMainDb:
    def __init__(self):
        self.row = {
            "id": 88,
            "phone": "13800000000",
            "email": "user@example.com",
            "username": "comic-user",
            "password_hash": "$2b$12$fake",
            "member_level": "FREE",
            "member_plan_id": None,
            "computing_power": 123,
            "is_active": 1,
            "is_admin": 0,
            "is_staff": 0,
        }
        self.password_checked = False

    def configured(self):
        return True

    def ping(self):
        return True

    def find_login_user(self, identifier):
        return self.row if identifier in ("13800000000", "user@example.com", "comic-user", "88") else None

    def verify_password(self, user, password):
        self.password_checked = True
        return user.get("password_hash") == "$2b$12$fake" and password == "right-password"


class UnifiedComicAccountSmokeTest(unittest.TestCase):
    def setUp(self):
        self.central = load_module("central_server_unified_auth_smoke", SERVER)
        self.sso = load_module("matrix_sso_unified_auth_smoke", SSO)
        self.fake_maindb = FakeMainDb()

    def test_main_db_user_password_verifies_and_issues_mapped_comic_ticket(self):
        with mock.patch.object(self.central, "MAINDB_ENABLED", True), \
                mock.patch.object(self.central, "maindb", self.fake_maindb), \
                mock.patch.object(self.central, "_MAINDB_OK", True), \
                mock.patch.object(self.central, "COMIC_SSO_ENABLED", True), \
                mock.patch.object(self.central, "COMIC_SSO_SECRET", "s" * 48):
            row = self.fake_maindb.find_login_user("comic-user")
            user = self.central.shape_mdb_user(row, "session")
            self.assertTrue(self.central.verify_user_password(user, "right-password"))
            response = self.central.issue_comic_sso_ticket_for_user(
                user,
                "org-default",
                now_ts=1_000,
                nonce="mapped-user-88",
            )

        self.assertTrue(self.fake_maindb.password_checked)
        self.assertEqual(response["comicAccountMode"], "mapped")
        self.assertEqual(response["comicUserId"], 88)
        self.assertEqual(response["userId"], 88)
        self.assertEqual(response["comicUsername"], "comic-user")
        verified = self.sso.verify_ticket(
            response["ticket"],
            secret="s" * 48,
            issuer="matrix-central",
            audience="aicanvas",
            now=1_030,
            max_ttl_seconds=120,
        )
        self.assertEqual(verified["user_id"], 88)
        self.assertEqual(verified["sub"], "88")
```

- [ ] **Step 2: Run the smoke test to verify it fails on the current fixed-account behavior**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_unified_comic_account_sso -v
```

Expected: FAIL because `comicAccountMode` is currently `fixed` and `comicUserId` is currently `44`.

- [ ] **Step 3: Record the Phase 0 failure**

Add a short entry to `docs/TROUBLESHOOTING.md`:

```markdown
## 2026-08-04 Unified comic account SSO Phase 0
- RED: `tests.test_unified_comic_account_sso` proves the current center still signs comic SSO tickets to fixed account `003` (`comicUserId=44`) instead of the logged-in main-db user.
- Required fix: authenticate ordinary AI爆款复刻 users through `ai_education.users` and sign comic SSO tickets with the current `users.id`.
```

- [ ] **Step 4: Commit the smoke skeleton after documentation**

Run:

```powershell
git add tests/test_unified_comic_account_sso.py docs/TROUBLESHOOTING.md
git commit -m "test: capture unified comic account sso smoke"
```

Expected: commit succeeds with only the smoke test and troubleshooting entry staged.

---

### Task 2: Center Auth Source Guard

**Files:**
- Modify: `backend/central_server.py`
- Modify: `tests/test_unified_comic_account_sso.py`

**Interfaces:**
- Produces: `require_main_db_auth_source() -> tuple[bool, str]`.
- Produces: `find_login_user(identifier)` fails closed for ordinary users when main DB is required but unavailable.
- Consumes: existing `maindb_on()`, `MAINDB_ENABLED`, `maindb.configured()`, `maindb.ping()`.

- [ ] **Step 1: Add failing auth-source tests**

Append to `tests/test_unified_comic_account_sso.py`:

```python
class UnifiedAuthSourceGuardTest(unittest.TestCase):
    def setUp(self):
        self.central = load_module("central_server_unified_auth_guard", SERVER)

    def test_main_db_required_when_enabled_but_unavailable(self):
        fake = FakeMainDb()
        with mock.patch.object(self.central, "MAINDB_ENABLED", True), \
                mock.patch.object(self.central, "maindb", fake), \
                mock.patch.object(self.central, "_MAINDB_OK", False), \
                mock.patch.object(self.central, "_MAINDB_LAST_PROBE", 0.0):
            ok, code = self.central.require_main_db_auth_source()

        self.assertFalse(ok)
        self.assertEqual(code, "maindb_unavailable")

    def test_local_json_ordinary_user_is_not_used_when_main_db_auth_is_required(self):
        state = {
            "users": [{"id": "user-local", "name": "local", "status": "active"}],
            "sessions": [],
        }
        with mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "MAINDB_ENABLED", True), \
                mock.patch.object(self.central, "maindb", None):
            user = self.central.find_login_user("local")

        self.assertIsNone(user)
```

- [ ] **Step 2: Run tests to verify they fail before implementation**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_unified_comic_account_sso.UnifiedAuthSourceGuardTest -v
```

Expected: FAIL because `require_main_db_auth_source` does not exist and local JSON fallback may still be reachable when main DB is missing.

- [ ] **Step 3: Implement the auth-source guard**

In `backend/central_server.py`, near `maindb_on()`, add:

```python
def require_main_db_auth_source():
    """Return whether ordinary users may authenticate against the comic main DB."""
    if not MAINDB_ENABLED:
        return False, "maindb_required"
    if maindb is None:
        return False, "maindb_unavailable"
    try:
        if not maindb.configured():
            return False, "maindb_unavailable"
    except Exception:
        return False, "maindb_unavailable"
    if not maindb_on():
        return False, "maindb_unavailable"
    return True, ""
```

Modify `find_login_user(identifier)`:

```python
def find_login_user(identifier):
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    low = identifier.lower()
    if low == "admin":
        with LOCK:
            return next((dict(u) for u in STATE.get("users") or [] if u.get("id") == "user-owner"), None)
    main_db_ready, _code = require_main_db_auth_source()
    if main_db_ready:
        try:
            row = maindb.find_login_user(identifier)
        except Exception:
            row = None
        if row:
            return shape_mdb_user(row, "session")
    return None
```

Modify `/api/auth/login` before calling `find_login_user(identifier)`:

```python
if identifier.lower() != "admin":
    main_db_ready, main_db_error = require_main_db_auth_source()
    if not main_db_ready:
        error_id = uuid.uuid4().hex[:12]
        json_log(
            logger,
            "auth_main_db_unavailable",
            level="warning",
            errorId=error_id,
            code=main_db_error,
            identifierHash=_short_hash(identifier),
        )
        add_audit(self, "auth.login", path, ok=False, meta={
            "identifierHash": _short_hash(identifier),
            "error": main_db_error,
            "errorId": error_id,
        })
        return json_response(self, {"ok": False, "error": main_db_error, "errorId": error_id}, 503)
```

- [ ] **Step 4: Run focused auth-source tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_unified_comic_account_sso.UnifiedAuthSourceGuardTest -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add backend/central_server.py tests/test_unified_comic_account_sso.py
git commit -m "fix: require comic main db for ordinary auth"
```

Expected: commit includes only the center auth guard and its tests.

---

### Task 3: Mapped Comic SSO

**Files:**
- Modify: `backend/central_server.py`
- Modify: `tests/test_comic_sso.py`
- Modify: `tests/test_unified_comic_account_sso.py`

**Interfaces:**
- Produces: `comic_sso_ticket_user_scope(user)` returns `mode="mapped"` for main-db users.
- Produces: optional rollback helper `comic_fixed_sso_enabled() -> bool`.
- Consumes: `COMIC_FIXED_USER_ID` only when explicit rollback env enables fixed mode.

- [ ] **Step 1: Replace the fixed-account SSO regression**

In `tests/test_comic_sso.py`, replace `test_central_issues_ticket_for_fixed_comic_account` with:

```python
    def test_central_issues_ticket_for_current_main_db_user(self):
        user = {
            "id": 88,
            "name": "comic-user",
            "username": "comic-user",
            "_mdb": True,
            "status": "active",
        }
        with mock.patch.object(self.central, "COMIC_SSO_ENABLED", True), \
                mock.patch.object(self.central, "COMIC_SSO_SECRET", "s" * 48), \
                mock.patch.object(self.central, "COMIC_FIXED_USER_ID", "44", create=True), \
                mock.patch.object(self.central, "COMIC_FIXED_USERNAME", "003", create=True), \
                mock.patch.object(self.central, "COMIC_FIXED_DISPLAY_NAME", "003", create=True), \
                mock.patch.object(self.central, "COMIC_FIXED_SSO_ENABLED", False, create=True):
            response = self.central.issue_comic_sso_ticket_for_user(
                user,
                "org-default",
                now_ts=1_000,
                nonce="nonce-88",
            )

        self.assertTrue(response["ok"])
        self.assertEqual(response["userId"], 88)
        self.assertEqual(response["comicUserId"], 88)
        self.assertEqual(response["matrixUserId"], "88")
        self.assertEqual(response["comicUsername"], "comic-user")
        self.assertEqual(response["comicAccountMode"], "mapped")

        verified = self.sso.verify_ticket(
            response["ticket"],
            secret="s" * 48,
            issuer="matrix-central",
            audience="aicanvas",
            now=1_030,
            max_ttl_seconds=120,
        )
        self.assertEqual(verified["user_id"], 88)
        self.assertEqual(verified["name"], "comic-user")
```

Add rollback-only coverage:

```python
    def test_fixed_comic_account_requires_explicit_rollback_flag(self):
        with mock.patch.object(self.central, "COMIC_FIXED_SSO_ENABLED", True, create=True), \
                mock.patch.object(self.central, "COMIC_FIXED_USER_ID", "44", create=True), \
                mock.patch.object(self.central, "COMIC_FIXED_USERNAME", "003", create=True), \
                mock.patch.object(self.central, "COMIC_FIXED_DISPLAY_NAME", "003", create=True):
            scope = self.central.comic_sso_ticket_user_scope({"id": "user-owner", "name": "ops"})

        self.assertEqual(scope["mode"], "fixed")
        self.assertEqual(scope["userId"], 44)
        self.assertEqual(scope["username"], "003")
```

- [ ] **Step 2: Run the SSO tests to verify they fail**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_comic_sso -v
```

Expected: FAIL because current code still uses `MATRIX_COMIC_FIXED_USER_ID` whenever it is non-empty.

- [ ] **Step 3: Implement explicit rollback flag and mapped default**

In `backend/central_server.py`, near existing comic SSO config, add:

```python
COMIC_FIXED_SSO_ENABLED = os.getenv("MATRIX_COMIC_FIXED_SSO_ENABLED", "0").strip().lower() in (
    "1", "true", "yes", "on",
)
```

Modify `comic_sso_ticket_user_scope(user)`:

```python
def comic_sso_ticket_user_scope(user):
    """Return the AI CanvasPro user claims used for Matrix same-style replacement."""
    matrix_user_id = str((user or {}).get("id") or "").strip()
    if COMIC_FIXED_SSO_ENABLED:
        fixed_user_id = str(COMIC_FIXED_USER_ID or "").strip()
        try:
            user_id = int(fixed_user_id)
        except (TypeError, ValueError) as exc:
            raise ComicSsoIssueError("comic_fixed_user_invalid") from exc
        if user_id <= 0:
            raise ComicSsoIssueError("comic_fixed_user_invalid")
        return {
            "mode": "fixed",
            "userId": user_id,
            "username": COMIC_FIXED_USERNAME,
            "displayName": COMIC_FIXED_DISPLAY_NAME or COMIC_FIXED_USERNAME,
            "matrixUserId": matrix_user_id,
        }
    if not is_maindb_user(user):
        raise ComicSsoIssueError("comic_sso_user_not_mapped")
    user_id = int((user or {}).get("id"))
    if user_id <= 0:
        raise ComicSsoIssueError("comic_sso_user_not_mapped")
    display_name = first_nonempty(
        (user or {}).get("name"),
        (user or {}).get("nickname"),
        (user or {}).get("username"),
        str(user_id),
    )
    return {
        "mode": "mapped",
        "userId": user_id,
        "username": str((user or {}).get("username") or (user or {}).get("name") or ""),
        "displayName": display_name,
        "matrixUserId": matrix_user_id,
    }
```

- [ ] **Step 4: Update SSO error HTTP status mapping**

In the `/api/comic/auth/ticket` handler, keep `comic_sso_user_not_mapped` as 403 and config failures as 503:

```python
status = 503 if exc.code in (
    "comic_sso_disabled",
    "comic_sso_secret_missing",
    "comic_fixed_user_invalid",
) else 403
```

- [ ] **Step 5: Run focused SSO tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_comic_sso tests.test_unified_comic_account_sso -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add backend/central_server.py tests/test_comic_sso.py tests/test_unified_comic_account_sso.py
git commit -m "fix: map comic sso to current main db user"
```

Expected: commit contains SSO mapping code and tests only.

---

### Task 4: Enterprise Users, Invites, And Password Writes

**Files:**
- Modify: `backend/central_server.py`
- Modify: `tests/test_enterprise_invites.py`
- Modify: `tests/test_unified_comic_account_sso.py`

**Interfaces:**
- Produces: `create_or_claim_main_db_user(identifier, password, name="") -> dict`.
- Produces: enterprise upsert/invite/reset-password paths write passwords through `maindb.set_password()` for main-db users.
- Consumes: `maindb.get_user_by_phone()`, `maindb.create_phone_user()`, `maindb.set_password()`, `maindb.set_username()`.

- [ ] **Step 1: Add tests for invite acceptance using main-db users**

In `tests/test_enterprise_invites.py`, add:

```python
    def test_invite_acceptance_uses_main_db_user_when_main_db_enabled(self):
        class InviteMainDb:
            def __init__(self):
                self.created = None
                self.passwords = []

            def configured(self):
                return True

            def ping(self):
                return True

            def get_user_by_phone(self, phone):
                return self.created if self.created and self.created["phone"] == phone else None

            def create_phone_user(self, phone, password=None, signup_bonus=0):
                self.created = {
                    "id": 91,
                    "phone": phone,
                    "email": "",
                    "username": "invitee",
                    "password_hash": "hash",
                    "member_level": "FREE",
                    "member_plan_id": None,
                    "computing_power": signup_bonus,
                    "is_active": 1,
                    "is_admin": 0,
                    "is_staff": 0,
                }
                if password:
                    self.passwords.append((91, password))
                return self.created

            def set_password(self, uid, password):
                self.passwords.append((uid, password))

            def set_username(self, uid, name):
                self.created["username"] = name

        fake = InviteMainDb()
        code = self.create_invite(phone="13800000091")["inviteCode"]
        with mock.patch.object(self.server, "MAINDB_ENABLED", True), \
                mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "_MAINDB_OK", True):
            payload, status = self.server.accept_enterprise_invite({
                "token": code,
                "name": "Invitee",
                "phone": "13800000091",
                "password": "new-password-1",
            })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["user"]["id"], 91)
        self.assertEqual(payload["membership"]["userId"], 91)
        self.assertIn((91, "new-password-1"), fake.passwords)
        self.assertFalse(any(u.get("id") == 91 for u in self.state["users"]))
```

- [ ] **Step 2: Add reset-password main-db test**

Append to `tests/test_unified_comic_account_sso.py`:

```python
class UnifiedPasswordWriteTest(unittest.TestCase):
    def setUp(self):
        self.central = load_module("central_server_unified_password_write", SERVER)

    def test_set_user_password_writes_only_main_db_for_main_db_user(self):
        fake = FakeMainDb()
        calls = []
        fake.set_password = lambda uid, password: calls.append((uid, password))
        fake.hash_password = lambda password: "new-hash"
        user = {"id": 88, "_mdb": True, "passwordHash": "old"}

        with mock.patch.object(self.central, "MAINDB_ENABLED", True), \
                mock.patch.object(self.central, "maindb", fake), \
                mock.patch.object(self.central, "_MAINDB_OK", True):
            self.central.set_user_password(user, "new-password-1")

        self.assertEqual(calls, [(88, "new-password-1")])
        self.assertEqual(user["passwordHash"], "new-hash")
```

- [ ] **Step 3: Run tests to verify failures**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_enterprise_invites tests.test_unified_comic_account_sso.UnifiedPasswordWriteTest -v
```

Expected: invite test may fail because current invite acceptance can still create local JSON users or does not consistently shape main-db membership.

- [ ] **Step 4: Implement main-db claim helper**

In `backend/central_server.py`, near `create_phone_user`, add:

```python
def create_or_claim_main_db_user(phone="", password="", name=""):
    main_db_ready, main_db_error = require_main_db_auth_source()
    if not main_db_ready:
        raise RuntimeError(main_db_error)
    p = str(phone or "").strip()
    if not p:
        raise ValueError("main_db_phone_required")
    existing = maindb.get_user_by_phone(p)
    if existing:
        uid = existing.get("id")
        if password:
            maindb.set_password(uid, password)
        if name:
            maindb.set_username(uid, name[:40])
        row = maindb.get_user_by_id(uid)
    else:
        row = maindb.create_phone_user(p, password=password, signup_bonus=MAINDB_SIGNUP_BONUS)
        uid = (row or {}).get("id")
        if name and uid:
            maindb.set_username(uid, name[:40])
            row = maindb.get_user_by_id(uid)
    user = shape_mdb_user(row, "session") if row else None
    if not user:
        raise RuntimeError("main_db_user_create_failed")
    return user
```

- [ ] **Step 5: Route invite and upsert creation through the helper**

Modify `accept_enterprise_invite(body, handler=None)`:

```python
if MAINDB_ENABLED:
    try:
        user = create_or_claim_main_db_user(phone=phone, password=password, name=name)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:80]}, 503
    membership = ensure_membership(org_id, user.get("id"), invite.get("role") or "member")
    session = create_user_session(user, {
        "ip": handler.client_address[0] if handler and getattr(handler, "client_address", None) else "",
        "userAgent": handler.headers.get("User-Agent") if handler else "",
    })
    ctx = auth_context_for_user(user, org_id=org_id)
    return dict(ctx, ok=True, token=session["token"], expiresAt=session["expiresAt"],
                orgId=org_id, user=public_user(user), membership=membership,
                organizations=user_orgs(user.get("id"), user=user)), 200
```

If `ensure_membership` does not exist, add a small helper that updates `STATE["memberships"]` idempotently:

```python
def ensure_membership(org_id, user_id, role="member"):
    org_id = normalize_org_id(org_id)
    user_id_value = user_id
    with LOCK:
        existing = next((m for m in STATE.setdefault("memberships", [])
                         if m.get("orgId") == org_id and same_user_id(m.get("userId"), user_id_value)), None)
        if existing:
            existing["role"] = role or existing.get("role") or "member"
            existing["status"] = "active"
            existing["updatedAt"] = now()
            persist()
            return dict(existing)
        membership = {
            "id": "m-%s-%s" % (org_id, user_id_value),
            "orgId": org_id,
            "userId": user_id_value,
            "role": role or "member",
            "status": "active",
            "createdAt": now(),
        }
        STATE.setdefault("memberships", []).append(membership)
        persist()
        return dict(membership)
```

- [ ] **Step 6: Run focused enterprise/auth tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_enterprise_invites tests.test_unified_comic_account_sso -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```powershell
git add backend/central_server.py tests/test_enterprise_invites.py tests/test_unified_comic_account_sso.py
git commit -m "fix: write enterprise users to comic main db"
```

Expected: commit contains enterprise account-source changes and tests.

---

### Task 5: API, Config, And Production Docs

**Files:**
- Modify: `backend/.env.example`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/openapi.yaml`
- Modify: `CHANGELOG.md`
- Modify: `migration.sql`
- Modify: `tests/test_openapi_contract.py`

**Interfaces:**
- Produces: documented auth errors `maindb_required`, `maindb_unavailable`, `comic_sso_user_not_mapped`.
- Produces: env contract for mapped SSO and rollback-only fixed SSO.

- [ ] **Step 1: Add OpenAPI contract test**

In `tests/test_openapi_contract.py`, add:

```python
def test_auth_login_documents_main_db_unavailable_error(self):
    document = load_openapi()
    schema_ref = document["paths"]["/api/auth/login"]["post"]["responses"]["503"]["content"]["application/json"]["schema"]
    self.assertTrue(schema_ref)
    text = yaml.safe_dump(document, allow_unicode=True)
    self.assertIn("maindb_required", text)
    self.assertIn("maindb_unavailable", text)


def test_comic_sso_documents_mapped_account_mode(self):
    document = load_openapi()
    text = yaml.safe_dump(document, allow_unicode=True)
    self.assertIn("comicAccountMode", text)
    self.assertIn("mapped", text)
    self.assertIn("comic_sso_user_not_mapped", text)
```

- [ ] **Step 2: Run OpenAPI contract test to verify failure**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v
```

Expected: FAIL until docs and OpenAPI are updated.

- [ ] **Step 3: Update `.env.example`**

Change the comic SSO block in `backend/.env.example` to:

```dotenv
MATRIX_COMIC_SSO_ENABLED=1
MATRIX_COMIC_SSO_SECRET=
MATRIX_COMIC_SSO_ISSUER=matrix-central
MATRIX_COMIC_SSO_AUDIENCE=aicanvas
MATRIX_COMIC_SSO_TTL_SEC=60
# Production maps same-style replacement to the current ai_education.users.id.
# Fixed account SSO is rollback-only; leave disabled for normal production.
MATRIX_COMIC_FIXED_SSO_ENABLED=0
MATRIX_COMIC_FIXED_USER_ID=
MATRIX_COMIC_FIXED_USERNAME=
MATRIX_COMIC_FIXED_DISPLAY_NAME=
```

- [ ] **Step 4: Update OpenAPI**

In `docs/openapi.yaml`, ensure `/api/auth/login` has a `503` response:

```yaml
        '503':
          description: Comic main database is required for ordinary user login but is unavailable.
          content:
            application/json:
              schema:
                type: object
                required: [ok, error]
                properties:
                  ok:
                    type: boolean
                    enum: [false]
                  error:
                    type: string
                    enum: [maindb_required, maindb_unavailable]
                  errorId:
                    type: string
```

Ensure the comic SSO ticket response schema includes:

```yaml
        comicAccountMode:
          type: string
          enum: [mapped, fixed]
          description: mapped is the production mode; fixed is rollback-only.
```

- [ ] **Step 5: Update production docs**

Add these exact facts:

```markdown
- Production ordinary auth source is `ai_education.users`; local JSON users are not a fallback when `MAINDB_ENABLED=1`.
- Same-style replacement comic SSO defaults to mapped-user mode, where `comicUserId` equals the current main-db `users.id`.
- Fixed account `003` is rollback-only through `MATRIX_COMIC_FIXED_SSO_ENABLED=1`.
- Main-db auth failures return 503 with `maindb_required` or `maindb_unavailable`.
```

Update `migration.sql`:

```sql
-- 2026-08-04 unified comic account SSO
-- No schema migration required.
-- AI爆款复刻 ordinary user auth now uses existing ai_education.users.
```

Update `CHANGELOG.md`:

```markdown
## 2026-08-04 Unified comic account SSO
- AI爆款复刻普通用户登录收敛到漫剧主库 `ai_education.users`。
- 同款替换漫剧 SSO 默认按当前用户映射，不再固定使用账号 `003`。
- 主库不可用时普通登录返回脱敏 503，不降级为本地 JSON 用户。
```

- [ ] **Step 6: Recalculate implementation line references**

After all code changes are final, run:

```powershell
Select-String -Path backend\central_server.py -Pattern 'def require_main_db_auth_source','def comic_sso_ticket_user_scope','def create_or_claim_main_db_user','if path == "/api/auth/login"','if path == "/api/comic/auth/ticket"'
Select-String -Path tests\test_comic_sso.py -Pattern 'test_central_issues_ticket_for_current_main_db_user'
Select-String -Path tests\test_unified_comic_account_sso.py -Pattern 'UnifiedComicAccountSmokeTest','UnifiedAuthSourceGuardTest','UnifiedPasswordWriteTest'
```

Update `docs/IMPLEMENTATION.md` with final `file#Lx-Ly` references and the verification/rollback summary.

- [ ] **Step 7: Run docs/API tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```powershell
git add backend/.env.example docs/ARCHITECTURE.md docs/API_REFERENCE.md docs/DEPLOYMENT.md docs/TROUBLESHOOTING.md docs/IMPLEMENTATION.md docs/openapi.yaml CHANGELOG.md migration.sql tests/test_openapi_contract.py
git commit -m "docs: document unified comic account sso"
```

Expected: commit contains docs, OpenAPI, env example, migration no-op, and contract test.

---

### Task 6: Verification Gate

**Files:**
- No source edits unless a verification failure exposes a bug.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: local verification evidence suitable for `docs/TROUBLESHOOTING.md` and release notes.

- [ ] **Step 1: Run focused auth and SSO tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_unified_comic_account_sso tests.test_comic_sso tests.test_enterprise_invites tests.test_auth_login_modes tests.test_openapi_contract -v
```

Expected: PASS.

- [ ] **Step 2: Run billing and role smoke tests that share main-db/user assumptions**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_billing_unified tests.test_billing_dashboard_api tests.test_role_permissions -v
```

Expected: PASS or document unrelated pre-existing failures with exact test names.

- [ ] **Step 3: Compile changed Python files**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\central_server.py backend\maindb.py backend\matrix_sso.py tests\test_unified_comic_account_sso.py tests\test_comic_sso.py tests\test_enterprise_invites.py
```

Expected: exit code 0.

- [ ] **Step 4: Check no secrets entered tracked files**

Run:

```powershell
rg -n "Xhw_|MATRIX_COMIC_SSO_SECRET=.{8,}|AICANVAS_MATRIX_SSO_SECRET=.{8,}|MAINDB_PASS=.{4,}|Authorization: Bearer [A-Za-z0-9]" backend docs tests CHANGELOG.md migration.sql
```

Expected: no real secret values. Empty example variables are allowed.

- [ ] **Step 5: Commit verification docs if updated**

Run:

```powershell
git add docs/TROUBLESHOOTING.md docs/IMPLEMENTATION.md CHANGELOG.md
git commit -m "docs: record unified auth verification"
```

Expected: commit only if verification evidence changed docs after Task 5.

---

### Task 7: Production Deploy And Remote Smoke

**Files:**
- Modify only remote deployment environment files after backup.
- Do not modify unrelated projects under `/root/AI-CanvasPro` except the intended environment for SSO if required.
- Do not mix this project with other server projects.

**Interfaces:**
- Consumes: local committed code and production deployment at `/opt/matrixship-central-prod/current`.
- Produces: deployed center service with mapped SSO and remote comic service configured with the same SSO secret.

- [ ] **Step 1: Prepare deploy metadata**

Record:

```bash
git rev-parse --short HEAD
git status --short
```

Expected: only intended release files are committed; unrelated local working-tree changes are not deployed.

- [ ] **Step 2: Back up current production release**

On server:

```bash
readlink -f /opt/matrixship-central-prod/current
docker compose -p matrixship-central-prod -f /opt/matrixship-central-prod/current/docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:9080/api/health
```

Expected: current release path, container status, and health response recorded.

- [ ] **Step 3: Configure center env**

Set center environment without printing secret values:

```bash
MAINDB_ENABLED=1
MATRIX_COMIC_SSO_ENABLED=1
MATRIX_COMIC_FIXED_SSO_ENABLED=0
MATRIX_COMIC_FIXED_USER_ID=
MATRIX_COMIC_FIXED_USERNAME=
MATRIX_COMIC_FIXED_DISPLAY_NAME=
```

Generate one secret on the server:

```bash
openssl rand -base64 48
```

Put the generated value into both `MATRIX_COMIC_SSO_SECRET` and `AICANVAS_MATRIX_SSO_SECRET` through the server's private env mechanism. Do not echo it in terminal output or commit it.

- [ ] **Step 4: Configure remote comic env**

Set remote AI CanvasPro environment:

```bash
AICANVAS_MATRIX_SSO_ENABLED=1
AICANVAS_MATRIX_SSO_ISSUER=matrix-central
AICANVAS_MATRIX_SSO_AUDIENCE=aicanvas
```

Set `AICANVAS_MATRIX_SSO_SECRET` to the same server-only secret through the service env file or systemd drop-in.

- [ ] **Step 5: Deploy center**

Use the existing isolated deployment directory:

```bash
cd /opt/matrixship-central-prod/current
RELEASE_SHA="$(git rev-parse --short HEAD)"
IMAGE_TAG="$RELEASE_SHA" CENTRAL_PORT=9080 docker compose -p matrixship-central-prod -f docker-compose.prod.yml up -d --build
```

Expected: container starts and reports healthy.

- [ ] **Step 6: Restart remote comic service if env changed**

On server:

```bash
systemctl restart ai-canvas.service
systemctl is-active ai-canvas.service
ss -ltnp | grep 8777
```

Expected: `active` and port `8777` listening.

- [ ] **Step 7: Public smoke**

From local machine:

```powershell
Invoke-WebRequest -Uri 'http://120.26.194.174:9080/api/health' -UseBasicParsing -TimeoutSec 15
Invoke-WebRequest -Uri 'http://120.26.194.174:9080/download' -UseBasicParsing -TimeoutSec 15
```

Expected: both return HTTP 200.

- [ ] **Step 8: Auth and SSO smoke**

Use a real existing comic test account through the client or API without exposing its password in logs:

```text
1. Login to AI爆款复刻 with an existing 漫剧 account.
2. Confirm `/api/auth/me` returns the expected numeric user id and role.
3. Request comic SSO ticket.
4. Confirm ticket response has `comicAccountMode=mapped` and `comicUserId` equal to the current numeric `users.id`.
5. Exchange ticket with the remote comic endpoint.
6. Confirm the comic session belongs to the same `users.id`.
```

Expected: no login prompt after SSO exchange, no `003` project ownership unless the logged-in account actually is `003`.

- [ ] **Step 9: Rollback command**

If mapped SSO blocks production users, use one of these rollback paths:

```bash
cd /opt/matrixship-central-prod/current
MATRIX_COMIC_FIXED_SSO_ENABLED=1 MATRIX_COMIC_FIXED_USER_ID=44 MATRIX_COMIC_FIXED_USERNAME=003 MATRIX_COMIC_FIXED_DISPLAY_NAME=003 docker compose -p matrixship-central-prod -f docker-compose.prod.yml up -d
```

or roll back the release symlink to the previous release and restart:

```bash
PREVIOUS_RELEASE="$(ls -1dt /opt/matrixship-central-prod/releases/* | sed -n '2p')"
PREVIOUS_SHA="$(basename "$PREVIOUS_RELEASE")"
ln -sfn "$PREVIOUS_RELEASE" /opt/matrixship-central-prod/current
cd /opt/matrixship-central-prod/current
IMAGE_TAG="$PREVIOUS_SHA" CENTRAL_PORT=9080 docker compose -p matrixship-central-prod -f docker-compose.prod.yml up -d
```

Expected: `/api/health` returns 200 after rollback.

---

## Self-Review

- Spec coverage: The plan covers ordinary login, mapped comic SSO, enterprise invite/user password writes, OpenAPI, docs, migration no-op, verification, deployment, and rollback.
- Marker scan: The plan contains no unresolved marker tokens; deploy commands derive release values from Git and the release directory.
- Type consistency: New helpers consistently use `require_main_db_auth_source()`, `create_or_claim_main_db_user(...)`, `comic_sso_ticket_user_scope(user)`, and existing `shape_mdb_user(...)`.
- Scope check: This plan does not implement full OAuth/OIDC SSO, mobile login business, recharge business, or old local JSON user migration.
