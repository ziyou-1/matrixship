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
        self.main_db_patch = mock.patch.object(self.server, "MAINDB_ENABLED", False)
        self.state_patch.start()
        self.persist_patch.start()
        self.main_db_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.addCleanup(self.persist_patch.stop)
        self.addCleanup(self.main_db_patch.stop)

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
        self.assertNotIn("inviteCode", payload["invite"])
        self.assertNotIn(code, repr(self.state))
        listed = self.server.list_enterprise_invites("org-a")
        self.assertNotIn(code, repr(listed))

    def test_new_user_accepts_invite_and_receives_session_context(self):
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
        self.assertEqual(payload["appRole"], self.server.PRODUCT_ROLE_NORMAL_USER)
        self.assertEqual(payload["roleScope"], "self")
        self.assertEqual(payload["memberships"][0]["orgId"], "org-a")

    def test_invite_acceptance_does_not_require_phone_or_email(self):
        code = self.create_invite(phone="", email="")["inviteCode"]

        payload, status = self.server.accept_enterprise_invite({
            "token": code,
            "name": "Invitee Without Phone",
            "password": "new-password-1",
        })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["orgId"], "org-a")
        self.assertEqual(payload["membership"]["role"], "member")
        self.assertEqual(payload["user"]["name"], "Invitee Without Phone")
        self.assertEqual(payload["user"].get("phone") or "", "")
        self.assertEqual(payload["user"].get("email") or "", "")
        membership = self.state["memberships"][0]
        self.assertEqual(membership["orgId"], "org-a")
        self.assertEqual(membership["userId"], payload["user"]["id"])

    def test_existing_user_requires_current_password_then_joins(self):
        user = {
            "id": "user-existing",
            "name": "Existing",
            "phone": "13900000000",
            "status": "active",
        }
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
        self.assertTrue(self.server.verify_user_password(user, "replacement-password"))

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

            def get_user_by_id(self, uid):
                return self.created if self.created and self.created["id"] == uid else None

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

    def test_upsert_enterprise_user_creates_main_db_user_when_main_db_enabled(self):
        class UpsertMainDb:
            def __init__(self):
                self.created = None
                self.passwords = []

            def configured(self):
                return True

            def ping(self):
                return True

            def get_user_by_phone(self, phone):
                return self.created if self.created and self.created["phone"] == phone else None

            def get_user_by_id(self, uid):
                return self.created if self.created and self.created["id"] == uid else None

            def create_phone_user(self, phone, password=None, signup_bonus=0):
                self.created = {
                    "id": 92,
                    "phone": phone,
                    "email": "",
                    "username": "member",
                    "password_hash": "hash",
                    "member_level": "FREE",
                    "member_plan_id": None,
                    "computing_power": signup_bonus,
                    "is_active": 1,
                    "is_admin": 0,
                    "is_staff": 0,
                }
                if password:
                    self.passwords.append((92, password))
                return self.created

            def set_password(self, uid, password):
                self.passwords.append((uid, password))

            def set_username(self, uid, name):
                self.created["username"] = name

        fake = UpsertMainDb()
        with mock.patch.object(self.server, "MAINDB_ENABLED", True), \
                mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "_MAINDB_OK", True):
            payload, status = self.server.upsert_enterprise_user({
                "orgId": "org-a",
                "name": "Main Db Member",
                "phone": "13800000092",
                "initialPassword": "new-password-2",
                "role": "member",
            })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["user"]["id"], 92)
        self.assertEqual(payload["credential"]["identifier"], "13800000092")
        self.assertIn((92, "new-password-2"), fake.passwords)
        self.assertEqual(self.state["memberships"][0]["userId"], 92)
        self.assertFalse(self.state["users"])

    def test_verify_is_post_only_and_audited_without_secret(self):
        source = SERVER.read_text(encoding="utf-8")
        get_block = source[source.index("    def do_GET(self):"):source.index("    def do_POST(self):")]
        post_block = source[source.index("    def do_POST(self):"):]

        self.assertNotIn('path == "/api/enterprise/invites/verify"', get_block)
        self.assertIn('path == "/api/enterprise/invites/verify"', post_block)
        self.assertIn('"enterprise.invite.verify"', post_block)
        audit_call = re.search(
            r'add_audit\(self, "enterprise\.invite\.verify"(?P<body>.*?)\)\n',
            post_block,
            re.S,
        )
        self.assertIsNotNone(audit_call)
        self.assertNotIn('body.get("token")', audit_call.group("body"))


if __name__ == "__main__":
    unittest.main()
