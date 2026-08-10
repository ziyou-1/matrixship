# coding: utf-8
"""平台管理员『用户管理』列表必须列出漫剧主库 ai_education.users 的真实用户,
而不是只回中心服本地 JSON(那里只有运维兜底账号 user-owner)。

复现的线上 bug:管理员 billing_admin 登录公网客户端后,账号中心「用户管理(管理员)」
只显示一个 admin(user-owner),42 个真实用户一个都看不到。根因是 /api/admin/users
只读 STATE["users"],从不查 maindb,且 maindb 当时连列出用户的函数都没有。
"""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SERVER = BACKEND / "central_server.py"


def load_module(name, path):
    backend_text = str(BACKEND)
    if backend_text not in sys.path:
        sys.path.insert(0, backend_text)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeMainDb:
    def __init__(self, rows):
        self._rows = rows

    def list_users(self, limit=1000, offset=0, q=""):
        rows = self._rows
        if q:
            rows = [r for r in rows
                    if q in str(r.get("username") or "") or q in str(r.get("phone") or "")]
        return rows[offset:offset + limit]


def _row(uid, username, is_admin=0, is_staff=0, power=0):
    return {
        "id": uid, "phone": "138%08d" % uid, "email": "", "username": username,
        "member_level": "FREE", "member_plan_id": None, "computing_power": power,
        "is_active": 1, "is_admin": is_admin, "is_staff": is_staff,
    }


class AdminListUsersTest(unittest.TestCase):
    def setUp(self):
        self.central = load_module("central_server_admin_users_under_test", SERVER)

    def _state(self):
        return {
            "users": [{"id": "user-owner", "name": "企业管理员", "balance": 10000.0, "status": "active"}],
            "sessions": [],
        }

    def test_lists_maindb_users_when_maindb_on(self):
        rows = [
            _row(18, "billing_admin", is_admin=1, is_staff=1, power=500),
            _row(44, "003", is_admin=0, is_staff=0, power=12),
        ]
        with mock.patch.object(self.central, "maindb", FakeMainDb(rows)), \
                mock.patch.object(self.central, "STATE", self._state()), \
                mock.patch.object(self.central, "maindb_on", lambda: True), \
                mock.patch.object(self.central, "get_balance", lambda uid: 10000.0 if uid == "user-owner" else 0.0):
            users = self.central.admin_list_users()
        ids = [u.get("id") for u in users]
        # 真实主库用户都在列表里(修复前只会有 user-owner)
        self.assertIn(18, ids)
        self.assertIn(44, ids)
        # 本地运维账号仍保留
        self.assertIn("user-owner", ids)
        # 主库用户不泄露密码哈希
        for u in users:
            self.assertNotIn("passwordHash", u)
            self.assertNotIn("password_hash", u)
        admin = next(u for u in users if u.get("id") == 18)
        self.assertTrue(admin.get("isPlatformAdmin"))       # is_admin/is_staff -> 平台管理员
        self.assertEqual(admin.get("balance"), 500.0)       # balance 来自 computing_power
        normal = next(u for u in users if u.get("id") == 44)
        self.assertFalse(normal.get("isPlatformAdmin"))

    def test_search_q_filters_maindb_users(self):
        rows = [
            _row(18, "billing_admin", is_admin=1, is_staff=1, power=500),
            _row(44, "003", is_admin=0, is_staff=0, power=12),
        ]
        with mock.patch.object(self.central, "maindb", FakeMainDb(rows)), \
                mock.patch.object(self.central, "STATE", self._state()), \
                mock.patch.object(self.central, "maindb_on", lambda: True), \
                mock.patch.object(self.central, "get_balance", lambda uid: 0.0):
            users = self.central.admin_list_users(q="003")
        maindb_ids = [u.get("id") for u in users if isinstance(u.get("id"), int)]
        self.assertEqual(maindb_ids, [44])

    def test_falls_back_to_local_json_when_maindb_off(self):
        with mock.patch.object(self.central, "STATE", self._state()), \
                mock.patch.object(self.central, "maindb_on", lambda: False), \
                mock.patch.object(self.central, "get_balance", lambda uid: 10000.0):
            users = self.central.admin_list_users()
        self.assertEqual([u.get("id") for u in users], ["user-owner"])


if __name__ == "__main__":
    unittest.main()
