import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CLIENT = BACKEND / "matrix_native_client.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_client(name="matrix_native_client_xhs_health_test"):
    spec = importlib.util.spec_from_file_location(name, CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Exact shape of a logged-in 小红书 account as emitted by
# api_server.current_accounts(): it sets cookieReady/usable but NOT online/status,
# and carries no localAccountId (only id). Douyin, by contrast, sets online/status.
def _local_xhs_account():
    return {
        "id": "xhs-self",
        "platform": "xhs",
        "name": "小红书账号",
        "handle": "",
        "cookieReady": True,
        "cookieCount": 1,
        "usable": True,
    }


def _local_douyin_account():
    return {
        "id": "dy-1",
        "platform": "douyin",
        "name": "抖音测试号",
        "online": True,
        "cookieReady": True,
        "usable": True,
        "status": "online",
    }


class XhsAccountHealthRiskCenterTest(unittest.TestCase):
    """Regression coverage for: 风控中心 must display 小红书 account health.

    Three defects fixed together:
      1. RiskControlPage fetched central-only /api/accounts, so local-only XHS
         accounts never appeared. It must use the merged (local+central) source.
      2. merge_account_sources marked accounts that report usable/cookieReady but
         omit `online` (i.e. XHS) as offline -> the row read 中风险/离线 while logged in.
      3. _xhs_safety_account_key picked an arbitrary element from a set, so it could
         return the account NAME instead of the id and miss the executor's
         safety-state entry (paused/usage), non-deterministically per process.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = load_client()

    # ---- Defect 1: risk page wiring uses the merged account source ----
    def test_risk_center_source_uses_merged_account_matrix_rows(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class RiskControlPage")
        end = src.index("class AssetMultiPicker", start)
        risk_src = src[start:end]
        # Must pull accounts from the merged local+central source, not central-only.
        self.assertIn("load_account_matrix_rows", risk_src)
        # Must classify platform with the canonical helper (handles xhs/xiaohongshu/rednote).
        self.assertIn("_account_platform_label", risk_src)

    def test_load_account_matrix_rows_includes_logged_in_xhs_online(self):
        client = self.client
        central = []  # 小红书没有独立的中心服矩阵来源
        local = [_local_douyin_account(), _local_xhs_account()]
        with mock.patch.object(client, "api", lambda *a, **k: (200, central)), \
                mock.patch.object(client, "local_api", lambda *a, **k: (200, local)):
            rows = client.load_account_matrix_rows()
        xhs = [r for r in rows if client._account_platform_label(r) == "小红书"]
        self.assertEqual(len(xhs), 1, "logged-in 小红书 account must appear in the merged rows")
        self.assertTrue(xhs[0].get("online"), "usable 小红书 account must be online, not offline")
        self.assertEqual(xhs[0].get("status"), "online")

    # ---- Defect 2: merge derives online from usable/cookieReady when absent ----
    def test_merge_marks_usable_xhs_online(self):
        client = self.client
        merged = client.merge_account_sources([], [_local_xhs_account()])
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["online"])
        self.assertEqual(merged[0]["status"], "online")

    def test_merge_keeps_explicitly_offline_account_offline(self):
        # Regression guard: the online-derivation must NOT flip a genuinely offline
        # account (explicit online=False) to online.
        client = self.client
        offline = {
            "id": "dy-off", "platform": "douyin", "name": "掉线抖音",
            "online": False, "cookieReady": False, "usable": False, "status": "offline",
        }
        merged = client.merge_account_sources([], [offline])
        self.assertEqual(len(merged), 1)
        self.assertFalse(merged[0]["online"])
        self.assertEqual(merged[0]["status"], "offline")

    def test_account_risk_summary_healthy_for_logged_in_xhs(self):
        client = self.client
        merged = client.merge_account_sources([], [_local_xhs_account()])[0]
        summary = client._account_risk_summary(merged, [])
        self.assertEqual(summary["risk"], "低风险")
        self.assertNotIn("不在线", summary["reason"])

    # ---- Defect 3: safety-state key is deterministic and id-based ----
    def test_xhs_safety_account_key_is_deterministic_id(self):
        client = self.client
        merged = client.merge_account_sources([], [_local_xhs_account()])[0]
        # The account carries both an id ("xhs-self") and a name ("小红书账号").
        # The key must be the id (matching api_server._xhs_safety_account_id),
        # never the name, and must be stable regardless of hash ordering.
        self.assertEqual(client._xhs_safety_account_key(merged), "xhs-self")

    def test_xhs_safety_account_key_prefers_local_account_id(self):
        client = self.client
        acct = {"id": "xhs-brand", "localAccountId": "xhs-brand",
                "platform": "xhs", "name": "品牌号"}
        self.assertEqual(client._xhs_safety_account_key(acct), "xhs-brand")

    def test_xhs_safety_usage_and_paused_lookup_hits_written_key(self):
        client = self.client
        merged = client.merge_account_sources([], [_local_xhs_account()])[0]
        # Executor writes safety state under the account id ("xhs-self").
        state = {"accounts": {"xhs-self": {
            "day": "1970-01-01", "publishCount": 2, "commentCount": 5,
            "paused": True, "pausedReason": "账号违规提示",
        }}}
        key = client._xhs_safety_account_key(merged)
        self.assertIn(key, state["accounts"], "reader key must match the executor's written key")
        # And the usage text helper resolves the same account.
        self.assertTrue(client._xhs_safety_usage_text(merged, "publish", state).endswith("/3"))


if __name__ == "__main__":
    unittest.main()
