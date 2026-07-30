import importlib.util
import copy
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SERVER = ROOT / "backend" / "central_server.py"
CLIENT = ROOT / "backend" / "matrix_native_client.py"
TOYOTA_SEED = ROOT / "scripts" / "seed_toyota_enterprise.py"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_server_module():
    spec = importlib.util.spec_from_file_location("central_server_roles_under_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_toyota_seed_module():
    spec = importlib.util.spec_from_file_location("toyota_seed_under_test", TOYOTA_SEED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RolePermissionsTest(unittest.TestCase):
    def setUp(self):
        self.server = load_server_module()
        self.state = {
            "organizations": [{"id": "org-a", "name": "Org A", "status": "active"}],
            "users": [
                {"id": "user-owner", "name": "Platform", "status": "active"},
                {"id": "u-admin", "name": "Entrepreneur", "status": "active"},
                {"id": "u-member", "name": "Member", "status": "active"},
                {"id": "u-other", "name": "Other", "status": "active"},
            ],
            "memberships": [
                {"id": "m-admin", "orgId": "org-a", "userId": "u-admin", "role": "admin", "status": "active"},
                {"id": "m-member", "orgId": "org-a", "userId": "u-member", "role": "member", "status": "active"},
                {"id": "m-other", "orgId": "org-a", "userId": "u-other", "role": "member", "status": "active"},
                {"id": "m-default-admin", "orgId": "org-default", "userId": "u-default-admin", "role": "admin", "status": "active"},
            ],
            "tasks": {
                "t-member": {"id": "t-member", "orgId": "org-a", "createdBy": "u-member", "status": "done"},
                "t-other": {"id": "t-other", "orgId": "org-a", "createdBy": "u-other", "status": "done"},
            },
            "accountsRegistry": [
                {"id": "a-member", "orgId": "org-a", "ownerUserId": "u-member", "online": True, "cookieReady": True},
                {"id": "a-other", "orgId": "org-a", "ownerUserId": "u-other", "online": True, "cookieReady": True},
            ],
            "library": [
                {"id": "lib-member", "orgId": "org-a", "createdBy": "u-member"},
                {"id": "lib-other", "orgId": "org-a", "createdBy": "u-other"},
            ],
            "kb": [
                {"id": "kb-member", "orgId": "org-a", "createdBy": "u-member"},
                {"id": "kb-other", "orgId": "org-a", "createdBy": "u-other"},
            ],
            "queue": [
                {"id": "q-member", "orgId": "org-a", "createdBy": "u-member", "status": "pending"},
                {"id": "q-other", "orgId": "org-a", "createdBy": "u-other", "status": "pending"},
            ],
            "auditLogs": [],
            "nodes": {},
            "sessions": [],
        }
        self.state_patch = mock.patch.object(self.server, "STATE", self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.persist_patch = mock.patch.object(self.server, "persist", lambda: None)
        self.persist_patch.start()
        self.addCleanup(self.persist_patch.stop)

    def test_product_role_maps_platform_entrepreneur_and_normal_user(self):
        self.assertEqual(
            self.server.product_role_for_user({"id": "user-owner"}, "org-a"),
            "platform_admin",
        )
        self.assertEqual(
            self.server.product_role_for_user({"id": "u-admin"}, "org-a"),
            "enterprise_admin",
        )
        self.assertEqual(
            self.server.product_role_for_user({"id": "u-member"}, "org-a"),
            "normal_user",
        )

    def test_default_org_admin_is_not_implicitly_platform_admin(self):
        with mock.patch.object(self.server, "USER_TOKEN", "enabled"), \
                mock.patch.object(self.server, "current_user", return_value={"id": "u-default-admin"}):
            self.assertFalse(self.server.is_platform_admin(object()))

    def test_phone_registration_creates_normal_member_not_enterprise_owner(self):
        user = self.server.create_phone_user("19300008702")

        membership = next(m for m in self.state["memberships"] if m["userId"] == user["id"])
        self.assertEqual(membership["role"], "member")

    def test_enterprise_summary_is_org_wide_for_entrepreneur_and_self_only_for_member(self):
        entrepreneur = {"id": "u-admin", "name": "Entrepreneur"}
        member = {"id": "u-member", "name": "Member"}

        entrepreneur_summary = self.server.enterprise_summary(entrepreneur)
        member_summary = self.server.enterprise_summary(member)

        self.assertEqual(entrepreneur_summary["counts"]["users"], 3)
        self.assertEqual(entrepreneur_summary["counts"]["accounts"], 2)
        self.assertEqual(entrepreneur_summary["scope"], "org")
        self.assertEqual(member_summary["counts"]["users"], 1)
        self.assertEqual(member_summary["counts"]["accounts"], 1)
        self.assertEqual(member_summary["counts"]["tasks"], 1)
        self.assertEqual(member_summary["counts"]["kbDocs"], 1)
        self.assertEqual(member_summary["scope"], "self")
        self.assertEqual([u["id"] for u in member_summary["users"]], ["u-member"])

    def test_client_contains_role_menu_and_billing_visibility_guards(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("def product_role():", src)
        self.assertIn("ROLE_NAV_DENY", src)
        self.assertIn("def nav_allowed(name):", src)
        self.assertIn('user.get("id") == "user-owner"', src)
        self.assertIn('role = "platform_admin"', src)
        self.assertIn("self.billing_box.setVisible(product_role() == \"platform_admin\")", src)
        self.assertIn("self.phone_bind_panel.setVisible(product_role() == \"platform_admin\")", src)
        self.assertIn("if not nav_allowed(name):", src)

    def test_client_exposes_enterprise_team_member_management(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("class EnterpriseMembersPage(BasePage):", src)
        self.assertIn("class EnterpriseCenterPage(TabbedWorkspacePage):", src)
        self.assertIn('("团队成员", lambda: EnterpriseMembersPage())', src)
        self.assertIn('"normal_user": {"🏢 企业中心", "👥 团队成员"}', src)
        self.assertIn('api("GET", "/api/enterprise/summary")', src)
        self.assertIn('api("GET", "/api/enterprise/invites"', src)
        self.assertIn('"/api/enterprise/users/upsert"', src)
        self.assertIn('"/api/enterprise/invites/create"', src)
        self.assertIn('"/api/enterprise/users/reset-password"', src)
        self.assertIn('"/api/enterprise/users/status"', src)

    def test_client_exposes_platform_admin_enterprise_creation(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("self.create_org_btn", src)
        self.assertIn("self.create_org_btn.setVisible(product_role() == \"platform_admin\")", src)
        self.assertIn("def create_enterprise(self):", src)
        self.assertIn('"/api/enterprise/orgs/upsert"', src)
        self.assertIn('"create_org"', src)

    def test_enterprise_admin_team_members_header_hides_direct_add_buttons(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class EnterpriseMembersPage(BasePage):")
        end = src.index("    def on_show(self):", start)
        block = src[start:end]

        self.assertIn("self.create_org_btn.setVisible(product_role() == \"platform_admin\")", block)
        self.assertIn("self.add_btn.setVisible(product_role() == \"platform_admin\")", block)
        self.assertNotIn("self.refresh_btn.setVisible(product_role() == \"platform_admin\")", block)
        self.assertNotIn("self.invite_btn.setVisible(product_role() == \"platform_admin\")", block)
        self.assertIn("企业家请通过“邀请成员”添加本企业成员。", src)

    def test_enterprise_members_page_reapplies_role_visibility_after_login(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class EnterpriseMembersPage(BasePage):")
        end = src.index("class EnterpriseProfilePage(BasePage):", start)
        block = src[start:end]

        self.assertIn("def _apply_role_visibility(self):", block)
        self.assertIn("is_platform_admin = product_role() == \"platform_admin\"", block)
        self.assertIn("self.create_org_btn.setVisible(is_platform_admin)", block)
        self.assertIn("self.add_btn.setVisible(is_platform_admin)", block)
        self.assertIn("self.org_combo.setVisible(is_platform_admin)", block)
        self.assertIn("self._org_label.setVisible(is_platform_admin)", block)
        self.assertIn("self._apply_role_visibility()", block[block.index("    def on_show(self):"):])
        self.assertIn("self._apply_role_visibility()", block[block.index("    def _on(self, tag, data):"):])

    def test_toyota_seed_moves_named_users_without_touching_phone_owner(self):
        seed = load_toyota_seed_module()
        state = {
            "organizations": [{"id": "org-default", "name": "默认企业", "status": "active"}],
            "users": [
                {"id": "boss", "name": "企业家"},
                {"id": "user01", "name": "普通用户01"},
                {"id": "user02", "name": "普通用户02"},
                {"id": "user-owner", "phone": "19711057505", "name": "企业管理员"},
            ],
            "memberships": [
                {"id": "m-org-default-boss", "orgId": "org-default", "userId": "boss", "role": "admin", "status": "active"},
                {"id": "m-org-default-user01", "orgId": "org-default", "userId": "user01", "role": "member", "status": "active"},
                {"id": "m-org-default-user02", "orgId": "org-default", "userId": "user02", "role": "member", "status": "active"},
                {"id": "m-default-owner", "orgId": "org-default", "userId": "user-owner", "role": "owner", "status": "active"},
            ],
        }

        changed = seed.apply_toyota_seed(state)

        self.assertTrue(changed)
        toyota = next(org for org in state["organizations"] if org["id"] == "org-toyota")
        self.assertEqual(toyota["name"], "丰田汽车")
        self.assertEqual(toyota["status"], "active")
        self.assertEqual(toyota["plan"], "standard")
        by_user = {m["userId"]: m for m in state["memberships"]}
        self.assertEqual(by_user["boss"]["orgId"], "org-toyota")
        self.assertEqual(by_user["boss"]["role"], "admin")
        self.assertEqual(by_user["user01"]["orgId"], "org-toyota")
        self.assertEqual(by_user["user01"]["role"], "member")
        self.assertEqual(by_user["user02"]["orgId"], "org-toyota")
        self.assertEqual(by_user["user02"]["role"], "member")
        self.assertEqual(by_user["user-owner"]["orgId"], "org-default")

        after_first_run = copy.deepcopy(state)
        self.assertFalse(seed.apply_toyota_seed(state))
        self.assertEqual(state, after_first_run)

    def test_server_can_replace_enterprise_memberships_for_running_state(self):
        payload, status = self.server.replace_enterprise_memberships({
            "orgId": "org-toyota",
            "name": "丰田汽车",
            "members": [
                {"userId": "u-admin", "role": "admin"},
                {"userId": "u-member", "role": "member"},
            ],
            "exclusive": True,
        })

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["organization"]["id"], "org-toyota")
        self.assertEqual(payload["organization"]["name"], "丰田汽车")
        memberships = {
            item["userId"]: item
            for item in self.state["memberships"]
            if item["userId"] in {"u-admin", "u-member", "u-other"}
        }
        self.assertEqual(memberships["u-admin"]["orgId"], "org-toyota")
        self.assertEqual(memberships["u-admin"]["role"], "admin")
        self.assertEqual(memberships["u-member"]["orgId"], "org-toyota")
        self.assertEqual(memberships["u-member"]["role"], "member")
        self.assertEqual(memberships["u-other"]["orgId"], "org-a")

    def test_client_team_member_and_sidebar_controls_have_stable_widths(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("self.table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.Fixed)", src)
        self.assertIn("self.table.setColumnWidth(5, 174)", src)
        self.assertIn("reset_btn.setFixedWidth(82)", src)
        self.assertIn("status_btn.setFixedWidth(58)", src)
        self.assertIn("foot = QtWidgets.QVBoxLayout()", src)
        self.assertIn("user_row = QtWidgets.QHBoxLayout()", src)
        self.assertIn("control_row = QtWidgets.QHBoxLayout()", src)
        self.assertIn("QPushButton#iconbtn", src)
        self.assertIn("min-width:26px", src)
        self.assertIn("max-width:26px", src)
        self.assertIn("self.balance_lab.setMaximumWidth(92)", src)
        self.assertIn("control_row.addWidget(self.balance_lab, 1)", src)
        self.assertIn("self._theme_btn.setFixedSize(26, 26)", src)
        self.assertIn("self._logout_btn.setFixedSize(26, 26)", src)
        self.assertIn("control_row.addWidget(self._logout_btn)", src)


    def test_client_refreshes_sidebar_balance_periodically_after_login(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn("self._balance_timer = QtCore.QTimer(self)", src)
        self.assertIn("self._balance_timer.setInterval(30000)", src)
        self.assertIn("self._balance_timer.timeout.connect(self.refresh_balance)", src)
        self.assertIn("self._balance_timer.start()", src)
        self.assertIn("self._balance_timer.stop()", src)

if __name__ == "__main__":
    unittest.main()
