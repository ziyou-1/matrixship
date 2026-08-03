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

    def test_native_client_login_screen_is_username_password_only(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("class LoginView", src)
        self.assertIn("def _sync_login_code_ui(self):", src)
        self.assertIn('self.phone_in.setPlaceholderText("用户名")', src)
        self.assertIn('self.phone_in.setPlaceholderText("手机号" if is_reg else "用户名")', src)
        self.assertIn("self.phone_in.setMaxLength(11 if is_reg else 64)", src)
        self.assertIn('need_code = self._mode == "register"', src)
        self.assertNotIn("手机号登录需验证码", src)
        self.assertNotIn("用户名登录只需密码", src)
        self.assertNotIn('self.phone_in.setPlaceholderText("手机号 / 用户名")', src)
        self.assertNotIn("用户名登录无需验证码", src)

        do_login = src[src.index("    def do_login(self):"):src.index("        def work():", src.index("    def do_login(self):"))]
        before_mode_branch = do_login.split('        if self._mode == "register":', 1)[0]
        login_branch = do_login.split('        else:  # login:', 1)[1]
        self.assertNotIn("acct.isdigit()", before_mode_branch)
        self.assertNotIn("login_needs_phone_code(acct)", do_login)
        self.assertNotIn('"code": code', login_branch)
        self.assertIn('if not acct:', do_login)
        self.assertIn('self._set_msg("请输入用户名", "err")', do_login)
    def test_account_matrix_exposes_self_service_password_change(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class AccountsPage(BasePage):")
        end = src.index("class TablePage(BasePage):", start)
        block = src[start:end]

        self.assertIn("self.change_password_btn", block)
        self.assertIn("self.change_password_btn.clicked.connect(self.change_password)", block)
        self.assertIn('api("POST", "/api/auth/change-password"', block)
        self.assertIn('"currentPassword": current_password', block)
        self.assertIn('"newPassword": new_password', block)
        self.assertIn('BRIDGE.payload.emit("acct_change_password"', block)
        self.assertIn('QtWidgets.QMessageBox.information(self, "修改密码", "密码修改成功")', block)
        self.assertNotIn('"/api/enterprise/users/reset-password"', block)

    def test_account_matrix_login_uses_local_executor_directly(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("def submit_account_login_direct(", src)
        self.assertIn('"/api/login/start"', src)
        self.assertIn('"/api/xhs/login"', src)
        self.assertIn('local_api("POST", start_path', src)
        self.assertIn('local_api("GET", "/api/login/status?sessionId=" + quote(str(sid), safe=""), timeout=15)', src)

        start = src.index("class AccountsPage(BasePage):")
        end = src.index("class TablePage(BasePage):", start)
        block = src[start:end]
        self.assertIn("submit_account_login_direct(platform, mode=mode, timeout_poll=300)", block)
        self.assertNotIn('submit_local_task(platform + ".login"', block)


if __name__ == "__main__":
    unittest.main()
