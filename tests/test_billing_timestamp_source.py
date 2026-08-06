"""2026-08-06 回归:主库记录的时间戳不能被当成北京时间。

现象:账户中心"扣费明细"第一行不是最新那笔,它的"扣后余额"因此对不上当前余额;
刷新也没用,因为数据其实已经刷新了,错的是排序。

根因:pymysql 返回不带时区的 datetime,而库里存的是 UTC。billing_analytics._timestamp()
对裸 datetime 按 CN_TZ(+8)解释,于是每条主库记录都早 8 小时。中心服 JSON 账本存的是
真实 epoch,两者混排时新扣费就沉到了旧记录下面。

修法:让数据库用 UNIX_TIMESTAMP() 直接给 epoch(created_ts / refunded_ts),不依赖任何
一侧对时区的假设 —— 容器时区将来若变更也不会再错。
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def load(name, filename):
    backend = str(BACKEND)
    if backend not in sys.path:
        sys.path.insert(0, backend)
    spec = importlib.util.spec_from_file_location(name, BACKEND / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class UsageLogTimestampTest(unittest.TestCase):
    def setUp(self):
        self.ba = load("billing_analytics_ts", "billing_analytics.py")

    def _records(self, ledger_rows, usage_rows):
        return self.ba.normalize_billing_records(44, ledger_rows, usage_rows, [], [])

    def test_db_epoch_column_is_preferred_over_the_naive_datetime(self):
        """created_ts 在场时必须用它,而不是把裸 datetime 当成北京时间。"""
        utc_naive = datetime(2026, 8, 6, 5, 10, 16)          # 库里存的 UTC
        true_epoch = utc_naive.replace(tzinfo=timezone.utc).timestamp()

        recs = self._records([], [{
            "id": 1, "user_id": 44, "request_id": "lk888:x", "model_id": "gemini",
            "amount": "0.02", "status": "charged",
            "created_at": utc_naive, "created_ts": true_epoch,
        }])

        self.assertEqual(len(recs), 1)
        self.assertAlmostEqual(recs[0]["timestamp"], true_epoch, places=3)

    def test_without_the_epoch_column_the_old_eight_hour_skew_is_visible(self):
        """留住证据:没有 created_ts 时确实会偏 8 小时,这正是当初的故障。"""
        utc_naive = datetime(2026, 8, 6, 5, 10, 16)
        true_epoch = utc_naive.replace(tzinfo=timezone.utc).timestamp()

        recs = self._records([], [{
            "id": 1, "user_id": 44, "request_id": "lk888:x", "model_id": "gemini",
            "amount": "0.02", "status": "charged", "created_at": utc_naive,
        }])

        self.assertAlmostEqual(recs[0]["timestamp"], true_epoch - 8 * 3600, places=3)

    def test_newest_db_charge_sorts_above_an_older_json_ledger_entry(self):
        """核心症状:同一天的主库新扣费必须排在 JSON 旧记录之前。"""
        utc_naive = datetime(2026, 8, 6, 5, 10, 16)           # 北京时间 13:10
        db_epoch = utc_naive.replace(tzinfo=timezone.utc).timestamp()
        json_epoch = db_epoch - 3 * 3600                       # 北京时间 10:10,更早

        recs = self._records(
            [{"id": "j1", "userId": 44, "delta": -72.86, "ref": "lk888:old",
              "reason": "LK888实际扣费", "ts": json_epoch, "balanceAfter": 4150.446}],
            [{"id": 1, "user_id": 44, "request_id": "lk888:new", "model_id": "gemini",
              "amount": "0.02", "status": "charged",
              "created_at": utc_naive, "created_ts": db_epoch}],
        )

        by_time = sorted(recs, key=lambda r: r["timestamp"], reverse=True)
        self.assertEqual(by_time[0]["requestId"], "lk888:new",
                         "最新的主库扣费必须排在最前,否则账户中心首行的扣后余额对不上当前余额")

    def test_refund_row_uses_its_own_db_epoch(self):
        created = datetime(2026, 8, 6, 5, 10, 16)
        refunded = datetime(2026, 8, 6, 6, 0, 0)
        created_ts = created.replace(tzinfo=timezone.utc).timestamp()
        refunded_ts = refunded.replace(tzinfo=timezone.utc).timestamp()

        recs = self._records([], [{
            "id": 1, "user_id": 44, "request_id": "lk888:r", "model_id": "gemini",
            "amount": "0.02", "status": "refunded",
            "created_at": created, "created_ts": created_ts,
            "refunded_at": refunded, "refunded_ts": refunded_ts,
        }])

        refund = [r for r in recs if r["type"] == "refund"]
        self.assertEqual(len(refund), 1)
        self.assertAlmostEqual(refund[0]["timestamp"], refunded_ts, places=3)


class MaindbQueryTest(unittest.TestCase):
    def test_usage_log_query_asks_the_database_for_epochs(self):
        src = (BACKEND / "maindb.py").read_text(encoding="utf-8")
        self.assertIn("UNIX_TIMESTAMP(created_at) AS created_ts", src)
        self.assertIn("UNIX_TIMESTAMP(refunded_at) AS refunded_ts", src)


if __name__ == "__main__":
    unittest.main()
