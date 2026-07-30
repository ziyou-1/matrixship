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
                self.assertFalse(view.phone_in.isVisibleTo(view))
                self.assertFalse(view.invite_email_in.isVisibleTo(view))
                self.assertFalse(view.code_row.isVisibleTo(view))
                self.assertEqual(view.btn.text(), "加入企业")
            finally:
                if view is not None:
                    view.deleteLater()
                self.client.BRIDGE = previous_bridge
                app.processEvents()

    def test_login_home_hides_register_tab_and_keeps_invite_tab(self):
        src = CLIENT.read_text(encoding="utf-8")
        build_card = src[src.index("    def _build_card(self):"):src.index("    def _show_legal_document")]

        self.assertIn('title = QtWidgets.QLabel("登录 / 加入企业")', build_card)
        self.assertIn('tabrow.addWidget(self.tab_login, 1)', build_card)
        self.assertIn('tabrow.addWidget(self.tab_invite, 1)', build_card)
        self.assertIn('self.tab_reg.setVisible(False)', build_card)
        self.assertNotIn('tabrow.addWidget(self.tab_reg, 1)', build_card)

    def test_entering_invite_mode_does_not_reuse_remembered_login_password(self):
        previous_bridge = self.client.BRIDGE
        view = None
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        self.client.BRIDGE = self.client.Bridge()
        view = self.client.LoginView(lambda _org: None)
        try:
            view.pw_in.setText("remembered-login-password")
            view.pw2_in.setText("remembered-login-password")
            view._set_mode("invite")
            self.assertEqual(view.pw_in.text(), "")
            self.assertEqual(view.pw2_in.text(), "")
        finally:
            if view is not None:
                view.deleteLater()
            self.client.BRIDGE = previous_bridge
            app.processEvents()

    def test_invite_mode_fits_900_by_700_without_overlap(self):
        previous_bridge = self.client.BRIDGE
        view = None
        with mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}, clear=False):
            app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
            self.client.BRIDGE = self.client.Bridge()
            view = self.client.LoginView(lambda _org: None)
            view.bg.start = lambda: None
            try:
                view._set_mode("invite")
                view.resize(900, 700)
                view.show()
                app.processEvents()
                self.assertEqual((view.width(), view.height()), (900, 700))
                card_pos = view._card.mapTo(view, self.client.QtCore.QPoint(0, 0))
                card_rect = self.client.QtCore.QRect(card_pos, view._card.size())
                self.assertTrue(view.rect().contains(card_rect))
                visible = []
                for name in (
                    "invite_code_row", "invite_org", "invite_name_in",
                    "pw_in", "pw2_in", "btn", "agree", "msg",
                ):
                    widget = getattr(view, name)
                    if widget.isVisibleTo(view):
                        pos = widget.mapTo(view, self.client.QtCore.QPoint(0, 0))
                        visible.append((name, self.client.QtCore.QRect(pos, widget.size())))
                for index, (name, rect) in enumerate(visible):
                    for other_name, other_rect in visible[index + 1:]:
                        self.assertFalse(rect.intersects(other_rect), (name, other_name))
            finally:
                if view is not None:
                    view.close()
                    view.deleteLater()
                self.client.BRIDGE = previous_bridge
                app.processEvents()

    def test_verify_posts_code_and_prefills_invited_identity(self):
        previous_bridge = self.client.BRIDGE
        view = None
        code = "c" * 64
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        self.client.BRIDGE = self.client.Bridge()
        view = self.client.LoginView(lambda _org: None)
        try:
            view._set_mode("invite")
            view.invite_code_in.setText(code)
            response = {
                "ok": True,
                "organization": {"id": "org-a", "name": "Org A"},
                "invite": {
                    "recipientName": "Invitee",
                    "recipientPhone": "13800000000",
                    "recipientEmail": "invitee@example.com",
                    "role": "member",
                    "expiresAt": 1893456000,
                },
            }
            with mock.patch.object(self.client, "api", return_value=(200, response)) as api_mock, \
                    mock.patch.object(self.client, "run_bg", side_effect=lambda work: work()):
                view.verify_enterprise_invite()

            api_mock.assert_called_once_with(
                "POST", "/api/enterprise/invites/verify", {"token": code}
            )
            self.assertEqual(view._invite_verified_code, code)
            self.assertEqual(view.invite_name_in.text(), "Invitee")
            self.assertEqual(view.phone_in.text(), "")
            self.assertEqual(view.invite_email_in.text(), "")
            self.assertIn("Org A", view.invite_org.text())
        finally:
            if view is not None:
                view.deleteLater()
            self.client.BRIDGE = previous_bridge
            app.processEvents()

    def test_verify_response_is_ignored_after_leaving_invite_mode(self):
        previous_bridge = self.client.BRIDGE
        view = None
        pending = []
        code = "e" * 64
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        self.client.BRIDGE = self.client.Bridge()
        view = self.client.LoginView(lambda _org: None)
        try:
            view._set_mode("invite")
            view.invite_code_in.setText(code)
            response = {
                "ok": True,
                "organization": {"id": "org-a", "name": "Org A"},
                "invite": {"recipientName": "Stale Invitee", "recipientPhone": "13800000000"},
            }
            with mock.patch.object(self.client, "api", return_value=(200, response)), \
                    mock.patch.object(self.client, "run_bg", side_effect=pending.append):
                view.verify_enterprise_invite()
                view._set_mode("login")
                view.phone_in.setText("active-login-user")
                pending.pop()()
                app.processEvents()
            self.assertEqual(view._mode, "login")
            self.assertEqual(view.phone_in.text(), "active-login-user")
            self.assertEqual(view._invite_verified_code, "")
        finally:
            if view is not None:
                view.deleteLater()
            self.client.BRIDGE = previous_bridge
            app.processEvents()

    def test_accept_response_is_ignored_after_leaving_invite_mode(self):
        previous_bridge = self.client.BRIDGE
        view = None
        pending = []
        code = "f" * 64
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        self.client.BRIDGE = self.client.Bridge()
        view = self.client.LoginView(lambda _org: None)
        try:
            view._set_mode("invite")
            view.invite_code_in.setText(code)
            view._invite_verified_code = code
            view.invite_name_in.setText("Invitee")
            view.pw_in.setText("replacement-password")
            view.pw2_in.setText("replacement-password")
            accepted = {
                "ok": True,
                "token": "stale-session-token",
                "orgId": "org-a",
                "user": {"id": "user-a"},
            }
            with mock.patch.object(self.client, "api", return_value=(200, accepted)), \
                    mock.patch.object(self.client, "run_bg", side_effect=pending.append), \
                    mock.patch.object(self.client, "set_session") as set_session_mock, \
                    mock.patch.object(self.client, "set_auth_context") as set_auth_context_mock:
                view.submit_enterprise_invite()
                view._set_mode("login")
                pending.pop()()
                app.processEvents()

            self.assertEqual(view._mode, "login")
            self.assertTrue(view.btn.isEnabled())
            set_session_mock.assert_not_called()
            set_auth_context_mock.assert_not_called()
        finally:
            if view is not None:
                view.deleteLater()
            self.client.BRIDGE = previous_bridge
            app.processEvents()

    def test_accept_locks_invite_identity_and_blocks_reverification(self):
        previous_bridge = self.client.BRIDGE
        view = None
        pending = []
        code = "1" * 64
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        self.client.BRIDGE = self.client.Bridge()
        view = self.client.LoginView(lambda _org: None)
        try:
            view._set_mode("invite")
            view.invite_code_in.setText(code)
            view._invite_verified_code = code
            view.invite_name_in.setText("Invitee")
            view.pw_in.setText("replacement-password")
            view.pw2_in.setText("replacement-password")
            with mock.patch.object(self.client, "run_bg", side_effect=pending.append):
                view.submit_enterprise_invite()
                generation = view._invite_request_generation
                self.assertFalse(view.invite_code_in.isEnabled())
                self.assertFalse(view.invite_verify_btn.isEnabled())
                self.assertFalse(view.tab_login.isEnabled())
                self.assertFalse(view.tab_reg.isEnabled())
                self.assertFalse(view.tab_invite.isEnabled())
                view.verify_enterprise_invite()

            self.assertEqual(len(pending), 1)
            self.assertEqual(view._invite_request_generation, generation)
        finally:
            if view is not None:
                view.deleteLater()
            self.client.BRIDGE = previous_bridge
            app.processEvents()

    def test_accept_response_rejects_same_mode_invite_code_change(self):
        previous_bridge = self.client.BRIDGE
        view = None
        pending = []
        code = "2" * 64
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        self.client.BRIDGE = self.client.Bridge()
        view = self.client.LoginView(lambda _org: None)
        try:
            view._set_mode("invite")
            view.invite_code_in.setText(code)
            view._invite_verified_code = code
            view.invite_name_in.setText("Invitee")
            view.pw_in.setText("replacement-password")
            view.pw2_in.setText("replacement-password")
            accepted = {
                "ok": True,
                "token": "same-mode-stale-token",
                "orgId": "org-a",
                "user": {"id": "user-a"},
            }
            with mock.patch.object(self.client, "api", return_value=(200, accepted)), \
                    mock.patch.object(self.client, "run_bg", side_effect=pending.append), \
                    mock.patch.object(self.client, "set_session") as set_session_mock, \
                    mock.patch.object(self.client, "set_auth_context") as set_auth_context_mock, \
                    mock.patch.object(self.client, "save_auth_pref") as save_auth_pref_mock:
                view.submit_enterprise_invite()
                view.invite_code_in.setText("3" * 64)
                pending.pop()()
                app.processEvents()

            set_session_mock.assert_not_called()
            set_auth_context_mock.assert_not_called()
            save_auth_pref_mock.assert_not_called()
            self.assertTrue(view.btn.isEnabled())
            self.assertEqual(view._invite_verified_code, "")
        finally:
            if view is not None:
                view.deleteLater()
            self.client.BRIDGE = previous_bridge
            app.processEvents()

    def test_accept_handles_existing_user_then_establishes_native_session(self):
        previous_bridge = self.client.BRIDGE
        view = None
        code = "d" * 64
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        self.client.BRIDGE = self.client.Bridge()
        view = self.client.LoginView(lambda _org: None)
        try:
            view._set_mode("invite")
            view.invite_code_in.setText(code)
            view._invite_verified_code = code
            view.invite_name_in.setText("Invitee")
            view.pw_in.setText("replacement-password")
            view.pw2_in.setText("replacement-password")
            with mock.patch.object(
                self.client, "api",
                return_value=(409, {"ok": False, "error": "existing_user_login_required"}),
            ), mock.patch.object(self.client, "run_bg", side_effect=lambda work: work()):
                view.submit_enterprise_invite()

            self.assertFalse(view.invite_current_pw_in.isHidden())
            self.assertIn("当前密码", view.msg.text())
            self.assertNotIn(code, view.msg.text())

            view.invite_current_pw_in.setText("current-password")
            accepted = {
                "ok": True,
                "token": "session-token",
                "orgId": "org-a",
                "user": {"id": "user-a", "phone": "13800000000"},
                "organizations": [{"id": "org-a", "name": "Org A"}],
                "memberships": [{"orgId": "org-a", "role": "member"}],
                "appRole": "normal_user",
                "roleScope": "self",
                "balance": 12,
            }
            with mock.patch.object(self.client, "api", return_value=(200, accepted)) as api_mock, \
                    mock.patch.object(self.client, "run_bg", side_effect=lambda work: work()), \
                    mock.patch.object(self.client, "set_session") as set_session_mock, \
                    mock.patch.object(self.client, "set_auth_context") as set_auth_context_mock, \
                    mock.patch.object(self.client, "save_auth_pref") as save_auth_pref_mock, \
                    mock.patch.object(view.bg, "release"):
                view.submit_enterprise_invite()

            body = api_mock.call_args.args[2]
            self.assertEqual(body["token"], code)
            self.assertEqual(body["currentPassword"], "current-password")
            self.assertNotIn("phone", body)
            self.assertNotIn("email", body)
            set_session_mock.assert_called_once_with("session-token", "org-a", account="user-a")
            set_auth_context_mock.assert_called_once_with(accepted)
            saved_pref = save_auth_pref_mock.call_args.args[0]
            self.assertEqual(saved_pref["account"], "user-a")
            self.assertFalse(saved_pref["remember"])
            self.assertFalse(saved_pref["autologin"])
            self.assertEqual(saved_pref["password"], "")
            self.assertEqual(saved_pref["token"], "")
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
