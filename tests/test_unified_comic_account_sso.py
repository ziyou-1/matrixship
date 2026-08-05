import importlib.util
import io
import json
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


class UnifiedAuthSourceGuardTest(unittest.TestCase):
    def setUp(self):
        self.central = load_module("central_server_unified_auth_guard", SERVER)

    def test_main_db_required_when_enabled_but_unavailable(self):
        class DeadMainDb(FakeMainDb):
            def ping(self):
                return False

        fake = DeadMainDb()
        with mock.patch.object(self.central, "MAINDB_ENABLED", True), \
                mock.patch.object(self.central, "maindb", fake), \
                mock.patch.object(self.central, "_MAINDB_OK", False), \
                mock.patch.object(self.central, "_MAINDB_LAST_PROBE", 0.0):
            ok, code = self.central.require_main_db_auth_source()

        self.assertFalse(ok)
        self.assertEqual(code, "maindb_unavailable")

    def test_fresh_process_probes_the_main_db_instead_of_failing_closed(self):
        """2026-08-05 回归:进程刚起时 `_MAINDB_OK` 还是 False。

        旧实现写成 `not _MAINDB_OK or not maindb_on()`,or 短路让 maindb_on()
        永远不执行,而它是唯一会探测主库并置位该标志的函数 —— 中心服每次重启后
        登录就永久返回 503 maindb_unavailable。
        """
        fake = FakeMainDb()  # configured() / ping() 都正常
        with mock.patch.object(self.central, "MAINDB_ENABLED", True), \
                mock.patch.object(self.central, "maindb", fake), \
                mock.patch.object(self.central, "_MAINDB_OK", False), \
                mock.patch.object(self.central, "_MAINDB_LAST_PROBE", 0.0):
            ok, code = self.central.require_main_db_auth_source()

        self.assertTrue(ok, "健康主库 + 冷进程必须探测成功,不能直接 fail-closed")
        self.assertEqual(code, "")

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

    def test_public_login_returns_503_without_falling_back_to_local_json_user(self):
        state = {
            "users": [{"id": "user-local", "name": "local", "status": "active", "passwordHash": "local"}],
            "sessions": [],
        }
        body = json.dumps({
            "identifier": "local",
            "password": "local",
            "legalConsent": {
                "accepted": True,
                "termsVersion": self.central.LEGAL_TERMS_VERSION,
                "privacyVersion": self.central.LEGAL_PRIVACY_VERSION,
                "acceptedAt": "2026-08-04T00:00:00Z",
            },
        }).encode("utf-8")
        handler = object.__new__(self.central.Handler)
        handler.path = "/api/auth/login"
        handler.headers = {"Content-Length": str(len(body)), "User-Agent": "test"}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.client_address = ("127.0.0.1", 1)
        handler.send_response = lambda status: setattr(handler, "status", status)
        handler.send_header = lambda *_args: None
        handler.end_headers = lambda: None
        with mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "MAINDB_ENABLED", True), \
                mock.patch.object(self.central, "maindb", None), \
                mock.patch.object(self.central, "add_audit"), \
                mock.patch.object(self.central, "json_log"):
            self.central.Handler.do_POST(handler)

        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(handler.status, 503)
        self.assertEqual(payload["error"], "maindb_unavailable")

    def test_healthy_main_db_authenticates_ordinary_user(self):
        fake = FakeMainDb()
        with mock.patch.object(self.central, "MAINDB_ENABLED", True), \
                mock.patch.object(self.central, "maindb", fake), \
                mock.patch.object(self.central, "_MAINDB_OK", True), \
                mock.patch.object(self.central, "maindb_on", return_value=True):
            user = self.central.find_login_user("comic-user")
            verified_user = self.central.shape_mdb_user(fake.row, "session")
            verified = self.central.verify_user_password(verified_user, "right-password")

        self.assertEqual(user["id"], 88)
        self.assertEqual(user["name"], "comic-user")
        self.assertTrue(user["_mdb"])
        self.assertTrue(verified)


class UnifiedPasswordWriteTest(unittest.TestCase):
    def setUp(self):
        self.central = load_module("central_server_unified_password_write", SERVER)
        self.state = {
            "organizations": [{"id": "org-a", "name": "Org A", "status": "active"}],
            "users": [],
            "memberships": [{"id": "m-org-a-88", "orgId": "org-a", "userId": 88, "role": "member", "status": "active"}],
            "sessions": [],
            "auditLogs": [],
        }

    def test_reset_enterprise_user_password_writes_main_db_member_password(self):
        class PasswordMainDb(FakeMainDb):
            def __init__(self):
                super().__init__()
                self.passwords = []

            def get_user_by_id(self, uid):
                return self.row if uid == self.row["id"] else None

            def set_password(self, uid, password):
                self.passwords.append((uid, password))

            def hash_password(self, password):
                return "new-hash"

        fake = PasswordMainDb()
        with mock.patch.object(self.central, "STATE", self.state), \
                mock.patch.object(self.central, "persist", return_value=None), \
                mock.patch.object(self.central, "MAINDB_ENABLED", True), \
                mock.patch.object(self.central, "maindb", fake), \
                mock.patch.object(self.central, "_MAINDB_OK", True):
            payload, status = self.central.reset_enterprise_user_password("org-a", {
                "userId": "88",
                "password": "new-password-3",
            })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["user"]["id"], 88)
        self.assertEqual(payload["credential"]["identifier"], "13800000000")
        self.assertEqual(fake.passwords, [(88, "new-password-3")])
