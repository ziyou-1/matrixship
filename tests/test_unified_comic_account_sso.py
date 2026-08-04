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
