"""小红书账号登录后必须显示在线。

Seam: 本地执行器 `/api/accounts` -> 客户端 `merge_account_sources()` -> 账号矩阵徽标。
只测其中一端会漏掉这个 bug:本地行少写 `online/status` 时,单测 merge 用手写行仍然通过。
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


STATUS_LABELS = {"online": "在线", "offline": "离线", "idle": "空闲", "ready": "就绪"}


def account_matrix_badge(account):
    """Mirror the account matrix pill in matrix_native_client.py."""
    status = account.get("status") or ("online" if account.get("online") else "offline")
    return STATUS_LABELS.get(str(status), str(status))


class XhsAccountOnlineStatusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = importlib.import_module("api_server")
        cls.client = importlib.import_module("matrix_native_client")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.old_env = os.environ.copy()

        def restore_env():
            os.environ.clear()
            os.environ.update(self.old_env)

        self.addCleanup(restore_env)
        os.environ["MATRIX_XHS_ENABLED"] = "1"
        os.environ.pop("XHS_ACCOUNT_ENABLED", None)
        old_data_dir = self.api.DATA_DIR
        self.addCleanup(setattr, self.api, "DATA_DIR", old_data_dir)
        self.api.DATA_DIR = str(self.data_dir)
        # 账号矩阵刚登录成功:本机 xhs profile 有效。
        (self.data_dir / "xhs_auth_state.json").write_text(
            json.dumps({"loggedIn": True, "cookieCount": 12}), encoding="utf-8")

    def local_xhs_accounts(self):
        return [a for a in self.api.current_accounts() if a.get("platform") == "xhs"]

    def test_local_executor_reports_online_status_for_logged_in_xhs_account(self):
        rows = self.local_xhs_accounts()

        self.assertTrue(rows, "本机 xhs profile 有效时应返回 xhs-self")
        self.assertTrue(rows[0]["online"])
        self.assertEqual(rows[0]["status"], "online")
        self.assertFalse(rows[0]["needLogin"])

    def test_account_matrix_shows_online_without_central_record(self):
        # 账号矩阵登录走 submit_account_login_direct(),直连本地引擎,
        # 不会把结果回报中心服,所以中心服没有这个号的记录。
        merged = self.client.merge_account_sources([], self.local_xhs_accounts())

        self.assertEqual(len(merged), 1)
        self.assertEqual(account_matrix_badge(merged[0]), "在线")

    def test_publish_and_collect_pickers_keep_logged_in_xhs_account(self):
        merged = self.client.merge_account_sources([], self.local_xhs_accounts())

        ready = self.client.clean_accounts(merged, platform="xhs", ready_only=True)

        self.assertEqual(len(ready), 1, "发布/采集账号下拉不应过滤掉已登录的小红书账号")
        self.assertIn("可用", self.client.account_option_label(ready[0]))

    def test_account_matrix_marks_offline_when_local_login_state_is_gone(self):
        (self.data_dir / "xhs_auth_state.json").unlink()

        merged = self.client.merge_account_sources([], self.local_xhs_accounts())

        self.assertEqual(merged, [], "本机登录态消失后不应再显示小红书账号")

    def test_run_xhs_login_marks_profile_ready_on_success(self):
        """账号矩阵登录成功后账号卡片必须出现。

        账号矩阵登录走 /api/xhs/login -> run_xhs_login() -> platform_adapters.xhs_login()。
        旧实现登录成功只组 job、不写 xhs_auth_state.json;而账号列表就绪判定
        xhs_profile_ready() 无 marker 时只认强 cookie(id_token/customerClientId/
        galaxy_creator_session_id/access-token-creator)。主站/DOM 判定登录成功但
        profile 缺这些强 cookie 时,登录成功却显示 0 个授权账号。
        """
        # 登录前:没有 marker,profile 也没有强 cookie(模拟主站登录)。
        (self.data_dir / "xhs_auth_state.json").unlink()
        self.assertEqual(self.local_xhs_accounts(), [])

        adapters = importlib.import_module("platform_adapters")

        def fake_xhs_login(data_dir="", login_timeout=None):
            prof = Path(data_dir) / "xhs_profile" / "Default" / "Network"
            prof.mkdir(parents=True, exist_ok=True)
            (prof / "Cookies").write_bytes(b"")
            return {"logged_in": True, "cookieCount": 7, "platform": "xhs"}

        with mock.patch.object(adapters, "xhs_login", side_effect=fake_xhs_login):
            self.api.run_xhs_login("job-xhs-login-test")

        job = self.api.STATE["cookie_jobs"].get("job-xhs-login-test") or {}
        self.assertTrue(job.get("loggedIn"), "前置:登录应成功")
        self.assertTrue(
            adapters.xhs_profile_ready(str(self.data_dir)),
            "登录成功后 xhs_profile_ready 必须为真",
        )
        rows = self.local_xhs_accounts()
        self.assertEqual(len(rows), 1, "登录成功后账号卡片应显示 1 个授权账号")
        self.assertTrue(rows[0]["online"])


if __name__ == "__main__":
    unittest.main()
