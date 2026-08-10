import importlib
import importlib.util
import sys
import unittest
import warnings
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CLIENT = BACKEND / "matrix_native_client.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_client(name="matrix_native_client_douyin_riskkey_test"):
    spec = importlib.util.spec_from_file_location(name, CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DouyinRiskCenterAccountKeyTest(unittest.TestCase):
    """Regression coverage for the flaky 抖音 safety-state key in 风控中心.

    _douyin_comment_account_key selected the key by iterating _account_risk_refs
    (a Python set), so on some PYTHONHASHSEED values it returned the account NAME
    instead of the id. The executor (api_server._douyin_comment_account_id) writes
    comment-risk usage/cooldown/paused state under the account id, so when the
    reader returned the name the risk center silently read an empty record:
    今日评论 0/30, 冷却 -, and a paused/风控 account shown as 低风险 instead of 高风险 —
    non-deterministically, roughly per app launch.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = load_client()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cls.api = importlib.import_module("api_server")

    def test_key_matches_executor_write_key(self):
        # Reader key must equal the key the executor writes state under.
        acct = {"id": "douyin-self", "localAccountId": "douyin-self",
                "platform": "douyin", "name": "带货小达人"}
        self.assertEqual(
            self.client._douyin_comment_account_key(acct),
            self.api._douyin_comment_account_id(acct["id"]),
        )

    def test_key_prefers_id_over_name(self):
        acct = {"id": "douyin-7788", "localAccountId": "douyin-7788",
                "platform": "douyin", "name": "某抖音昵称"}
        self.assertEqual(self.client._douyin_comment_account_key(acct), "douyin-7788")

    def test_key_falls_back_to_douyin_self(self):
        self.assertEqual(
            self.client._douyin_comment_account_key({"platform": "douyin"}),
            "douyin-self",
        )

    def test_key_is_independent_of_ref_ordering(self):
        # The defining property: the chosen key must NOT depend on the order in
        # which _account_risk_refs happens to yield elements. Simulate both
        # orderings deterministically; a set-iteration implementation returns the
        # name for the name-first ordering and fails this test.
        acct = {"id": "douyin-self", "localAccountId": "douyin-self",
                "platform": "douyin", "name": "带货小达人"}
        with mock.patch.object(self.client, "_account_risk_refs",
                               return_value=["带货小达人", "douyin-self"]):
            name_first = self.client._douyin_comment_account_key(acct)
        with mock.patch.object(self.client, "_account_risk_refs",
                               return_value=["douyin-self", "带货小达人"]):
            id_first = self.client._douyin_comment_account_key(acct)
        self.assertEqual(name_first, "douyin-self")
        self.assertEqual(id_first, "douyin-self")
        self.assertEqual(name_first, id_first)

    def test_usage_and_cooldown_resolve_recorded_state(self):
        # End-to-end at the helper level: state written under the id must be read
        # back for the risk-center 今日评论 / 冷却 columns.
        client = self.client
        client.RISK.update({"dailyComment": 30, "minInterval": 45})
        acct = {"id": "douyin-self", "localAccountId": "douyin-self",
                "platform": "douyin", "name": "带货小达人"}
        import time
        state = {"accounts": {"douyin-self": {
            "day": time.strftime("%Y-%m-%d"),
            "commentCount": 12,
            "lastCommentAt": time.time() - 10,
            "paused": True,
            "pausedUntil": time.time() + 600,
        }}}
        self.assertEqual(client._douyin_comment_usage_text(acct, state), "12/30")
        self.assertTrue(client._douyin_comment_cooldown_text(acct, state).endswith("s"))
        self.assertTrue(client._douyin_comment_account_usage(acct, state).get("paused"))


if __name__ == "__main__":
    unittest.main()
