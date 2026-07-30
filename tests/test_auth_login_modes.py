from pathlib import Path
import importlib.util
import os
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "backend" / "central_server.py"
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("central_server_under_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuthLoginModesTest(unittest.TestCase):
    def test_only_phone_identifier_requires_login_sms_code(self):
        server = load_server_module()
        requires = getattr(server, "login_requires_phone_code", None)
        self.assertIsNotNone(requires)

        user = {"id": "user-1", "phone": "19711057505"}
        self.assertTrue(requires("19711057505", user))
        self.assertFalse(requires("admin", user))
        self.assertFalse(requires("user-1", user))
        self.assertFalse(requires("企业管理员", user))

    def test_documented_local_admin_password_comes_from_environment(self):
        server = load_server_module()
        with mock.patch.dict(os.environ, {"CENTRAL_ADMIN_PASSWORD": "test123456"}, clear=False):
            self.assertTrue(server.verify_user_password({"id": "user-owner"}, "test123456"))
            self.assertFalse(server.verify_user_password({"id": "user-owner"}, "test1234567"))

    def test_native_client_does_not_require_code_for_username_login(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("def login_needs_phone_code(", src)
        self.assertIn("def _sync_login_code_ui(self):", src)
        self.assertIn("self.phone_in.textChanged.connect(self._sync_login_code_ui)", src)
        self.assertIn("self.code_row.setVisible(need_code)", src)
        self.assertIn("if login_needs_phone_code(acct) and not code:", src)
        self.assertIn('self.phone_in.setPlaceholderText("手机号" if is_reg else "手机号 / 用户名")', src)
        self.assertIn("self.phone_in.setMaxLength(11 if is_reg else 64)", src)
        self.assertNotIn('if not code:\n                self._set_msg("请输入短信验证码(账号密码需二次验证)", "err")', src)
        do_login = src[src.index("    def do_login(self):"):src.index("        def work():", src.index("    def do_login(self):"))]
        before_mode_branch = do_login.split('        if self._mode == "register":', 1)[0]
        self.assertNotIn("acct.isdigit()", before_mode_branch)
        self.assertIn('if not acct:', do_login)


if __name__ == "__main__":
    unittest.main()
