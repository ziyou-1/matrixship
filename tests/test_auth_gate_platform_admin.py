"""2026-08-06 回归:开启 CENTRAL_USER_TOKEN 后,鉴权必须按预期生效。

此前生产未设 CENTRAL_USER_TOKEN,has_role() 第一行 `if not USER_TOKEN: return True`
让所有权限检查对任何人(包括匿名的公网访客)一律放行。开启前做了一次全量梳理,
只确认一处会真正坏掉:平台管理员对 org-default 以外的企业会被拒。

根因:has_role() 只认 root-token 和成员关系,不认 isPlatformAdmin;而运营方的隐式
成员身份只覆盖 org-default,"添加企业"又不会给创建者建成员关系。于是服务端一边
通过 product_role_for_user() 告诉客户端"你是 platform_admin"、把所有企业列进下拉框,
一边拒掉除 org-default 外的每一次操作。
"""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def load():
    backend = str(BACKEND)
    if backend not in sys.path:
        sys.path.insert(0, backend)
    spec = importlib.util.spec_from_file_location("central_auth_gate", BACKEND / "central_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PLATFORM_ADMIN = {"id": 44, "name": "003", "isPlatformAdmin": True, "_mdb": True, "_authType": "session"}
MEMBER = {"id": 55, "name": "普通用户", "isPlatformAdmin": False, "_mdb": True, "_authType": "session"}


class AuthEnabledTest(unittest.TestCase):
    def setUp(self):
        self.central = load()

    def _has_role(self, user, org_id, level, token="root-secret"):
        with mock.patch.object(self.central, "USER_TOKEN", token), \
                mock.patch.object(self.central, "current_user", return_value=user), \
                mock.patch.object(self.central, "maindb_on", return_value=True), \
                mock.patch.object(self.central, "STATE", {"memberships": [], "organizations": []}):
            return self.central.has_role(None, org_id, level)

    def test_authorization_is_off_while_the_token_is_unset(self):
        """记录现状:没设 token 时任何人都放行 —— 这正是要关掉的口子。"""
        self.assertTrue(self._has_role(None, "org-x", "admin", token=""))

    def test_platform_admin_can_administer_any_org(self):
        """运营方对所有企业有权,否则"新建企业→新增成员"当场断裂。"""
        self.assertTrue(self._has_role(PLATFORM_ADMIN, "org-other", "admin"))
        self.assertTrue(self._has_role(PLATFORM_ADMIN, "org-default", "owner"))

    def test_ordinary_member_keeps_member_level_access_in_their_own_org(self):
        """普通用户的日常流程不能被这次开启影响。"""
        self.assertTrue(self._has_role(MEMBER, self.central.DEFAULT_ORG_ID, "member"))

    def test_ordinary_member_is_refused_admin_actions(self):
        """这不是回归,是修复:此前能做只因为锁没上。"""
        self.assertFalse(self._has_role(MEMBER, self.central.DEFAULT_ORG_ID, "admin"))

    def test_anonymous_is_refused_once_the_token_is_set(self):
        self.assertFalse(self._has_role(None, "org-default", "member"))

    def test_root_token_still_works(self):
        root = {"id": "user-owner", "_authType": "root-token"}
        self.assertTrue(self._has_role(root, "any-org", "owner"))


if __name__ == "__main__":
    unittest.main()
