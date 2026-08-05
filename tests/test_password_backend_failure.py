"""2026-08-05 回归:bcrypt 后端失效不得伪装成 invalid_credentials。

事故背景:中心服镜像重建把 bcrypt 拉到 5.0.0,和 passlib 1.7.4 不兼容,每次
校验都抛 ValueError;旧的 maindb.verify_password 把异常吞成 False,于是所有
漫剧账号在登录页看到的都是"密码错误",真实原因要进容器才能查出来。
"""
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
MAINDB = BACKEND / "maindb.py"

try:
    import bcrypt as _bcrypt  # noqa: F401
    import passlib  # noqa: F401

    _HAS_BCRYPT = True
except Exception:
    _HAS_BCRYPT = False


def load_module(name, path):
    backend_text = str(BACKEND)
    if backend_text not in sys.path:
        sys.path.insert(0, backend_text)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MainDbPasswordBackendTest(unittest.TestCase):
    """maindb 层:后端异常必须冒泡,不能退化成"密码不对"。"""

    def setUp(self):
        self.maindb = load_module("maindb_password_backend", MAINDB)

    def test_verify_password_raises_when_backend_fails(self):
        broken = mock.Mock()
        broken.verify.side_effect = ValueError(
            "password cannot be longer than 72 bytes, truncate manually if necessary"
        )
        with mock.patch.object(self.maindb, "_PWD", broken):
            with self.assertRaises(self.maindb.PasswordBackendError) as ctx:
                self.maindb.verify_password({"password_hash": "$2b$12$x"}, "right-password")

        # 只带异常类名,不回显 passlib 原始消息(可能含哈希片段)。
        self.assertEqual(str(ctx.exception), "ValueError")

    def test_hash_password_raises_when_backend_fails(self):
        broken = mock.Mock()
        broken.hash.side_effect = ValueError("boom")
        with mock.patch.object(self.maindb, "_PWD", broken):
            with self.assertRaises(self.maindb.PasswordBackendError):
                self.maindb.hash_password("whatever")

    def test_missing_hash_is_still_a_plain_mismatch(self):
        self.assertFalse(self.maindb.verify_password({"password_hash": ""}, "x"))

    def test_working_backend_still_returns_bool(self):
        working = mock.Mock()
        working.verify.return_value = True
        with mock.patch.object(self.maindb, "_PWD", working):
            self.assertTrue(self.maindb.verify_password({"password_hash": "$2b$12$x"}, "right"))
        working.verify.return_value = False
        with mock.patch.object(self.maindb, "_PWD", working):
            self.assertFalse(self.maindb.verify_password({"password_hash": "$2b$12$x"}, "wrong"))


class BrokenBackendMainDb:
    """漫剧主库可达、账号存在,但 bcrypt 后端坏了。"""

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

    class PasswordBackendError(RuntimeError):
        pass

    def configured(self):
        return True

    def ping(self):
        return True

    def find_login_user(self, identifier):
        return self.row if identifier in ("13800000000", "user@example.com", "comic-user", "88") else None

    def verify_password(self, user, password):
        raise self.PasswordBackendError("ValueError")

    def set_password(self, uid, password):
        raise self.PasswordBackendError("ValueError")

    def hash_password(self, password):
        raise self.PasswordBackendError("ValueError")

    def get_user_by_id(self, uid):
        return self.row if str(uid) == "88" else None


class LoginPasswordBackendFailureTest(unittest.TestCase):
    def setUp(self):
        self.central = load_module("central_server_password_backend", SERVER)
        self.fake = BrokenBackendMainDb()

    def _login(self, state):
        body = json.dumps({
            "identifier": "comic-user",
            "password": "right-password",
            "legalConsent": {
                "accepted": True,
                "termsVersion": self.central.LEGAL_TERMS_VERSION,
                "privacyVersion": self.central.LEGAL_PRIVACY_VERSION,
                "acceptedAt": "2026-08-05T00:00:00Z",
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
                mock.patch.object(self.central, "maindb", self.fake), \
                mock.patch.object(self.central, "PasswordBackendError", self.fake.PasswordBackendError), \
                mock.patch.object(self.central, "_MAINDB_OK", True), \
                mock.patch.object(self.central, "maindb_on", return_value=True), \
                mock.patch.object(self.central, "add_audit"), \
                mock.patch.object(self.central, "json_log") as logged:
            self.central.Handler.do_POST(handler)
        return handler, json.loads(handler.wfile.getvalue().decode("utf-8")), logged

    def test_login_returns_503_not_invalid_credentials(self):
        handler, payload, _logged = self._login({"users": [], "sessions": []})

        self.assertEqual(handler.status, 503)
        self.assertEqual(payload["error"], "password_backend_unavailable")
        self.assertNotEqual(payload.get("error"), "invalid_credentials")
        self.assertTrue(payload.get("errorId"))

    def test_failure_is_logged_without_leaking_the_identifier(self):
        _handler, _payload, logged = self._login({"users": [], "sessions": []})

        self.assertTrue(logged.called)
        _args, kwargs = logged.call_args
        self.assertEqual(_args[1], "auth_password_backend_failed")
        self.assertEqual(kwargs["code"], "ValueError")
        self.assertNotIn("comic-user", json.dumps(kwargs))
        self.assertNotIn("right-password", json.dumps(kwargs))


class PasswordWriteBackendFailureTest(unittest.TestCase):
    """写密码失败必须报错,旧实现 except Exception: pass 会静默成空操作。"""

    def setUp(self):
        self.central = load_module("central_server_password_write_failure", SERVER)
        self.fake = BrokenBackendMainDb()
        self.state = {
            "organizations": [{"id": "org-a", "name": "Org A", "status": "active"}],
            "users": [],
            "memberships": [{"id": "m-org-a-88", "orgId": "org-a", "userId": 88, "role": "member", "status": "active"}],
            "sessions": [],
            "auditLogs": [],
        }

    def test_set_user_password_propagates_backend_failure(self):
        with mock.patch.object(self.central, "MAINDB_ENABLED", True), \
                mock.patch.object(self.central, "maindb", self.fake), \
                mock.patch.object(self.central, "_MAINDB_OK", True), \
                mock.patch.object(self.central, "maindb_on", return_value=True):
            with self.assertRaises(self.fake.PasswordBackendError):
                self.central.set_user_password({"id": 88, "_mdb": True}, "new-password-3")

    def test_reset_enterprise_password_returns_503(self):
        with mock.patch.object(self.central, "STATE", self.state), \
                mock.patch.object(self.central, "persist", return_value=None), \
                mock.patch.object(self.central, "MAINDB_ENABLED", True), \
                mock.patch.object(self.central, "maindb", self.fake), \
                mock.patch.object(self.central, "PasswordBackendError", self.fake.PasswordBackendError), \
                mock.patch.object(self.central, "_MAINDB_OK", True), \
                mock.patch.object(self.central, "maindb_on", return_value=True), \
                mock.patch.object(self.central, "json_log"):
            payload, status = self.central.reset_enterprise_user_password("org-a", {
                "userId": "88",
                "password": "new-password-3",
            })

        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "password_backend_unavailable")


class BcryptPinTest(unittest.TestCase):
    """依赖必须锁版本,否则下次重建镜像会再踩一次。"""

    def test_requirements_pin_bcrypt_below_4_1(self):
        for name in ("requirements.txt", "requirements.deploy.txt"):
            text = (BACKEND / name).read_text(encoding="utf-8")
            self.assertIn("bcrypt==4.0.1", text, "%s 必须显式锁定 bcrypt" % name)

    @unittest.skipUnless(_HAS_BCRYPT, "bcrypt/passlib 未安装(开发机不装,容器里必须过)")
    def test_installed_bcrypt_is_compatible_with_passlib(self):
        """当前环境真的能用 passlib 校验 bcrypt 哈希。

        这条要在中心服容器里跑才有意义:开发机没装 bcrypt 会跳过,部署冒烟时
        必须在容器内执行一次。
        """
        import bcrypt
        from passlib.context import CryptContext

        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        hashed = bcrypt.hashpw(b"probe-Password-123", bcrypt.gensalt()).decode()
        self.assertTrue(ctx.verify("probe-Password-123", hashed))
        self.assertFalse(ctx.verify("wrong-password", hashed))


if __name__ == "__main__":
    unittest.main()
