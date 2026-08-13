"""2026-08-06 回归:"期间总消耗"必须剔除已退款,与漫剧账单口径一致。

现象:同一账号、同一区间,矩阵账户中心显示 1319.41 / 1740 条,漫剧消费账单显示
936.41 / 1180 次。两边读的是同一张 model_usage_logs,差在口径——矩阵侧把已退款的
扣费也算进了消费。

根因:normalize_billing_records() 给每条主库记录硬编码 status="charged",不看它在
库里的真实状态。_consumption() 按 status=="charged" 过滤,于是退掉的钱照样计入总消耗。
"""
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def load():
    backend = str(BACKEND)
    if backend not in sys.path:
        sys.path.insert(0, backend)
    spec = importlib.util.spec_from_file_location("billing_analytics_parity", BACKEND / "billing_analytics.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def usage_row(rid, amount, status, ts):
    return {
        "id": rid, "user_id": 44, "request_id": "lk888:%s" % rid,
        "model_id": "gemini-3.1-pro-preview", "model_type": "other",
        "amount": amount, "status": status, "balance_after": "100",
        "created_ts": ts, "refunded_ts": ts + 60 if status == "refunded" else None,
    }


# 用模块自己的 parse_period 构造,它还会补 startTs/endTs 这两个内部字段
_BA = load()
PERIOD = _BA.parse_period({"startDate": "2026-08-01", "endDate": "2026-08-31", "groupBy": "day"})
TS = PERIOD["startTs"] + 5 * 86400 + 3600  # 落在区间内


class ConsumptionExcludesRefundsTest(unittest.TestCase):
    def setUp(self):
        self.ba = load()

    def _analytics(self, rows):
        recs = self.ba.normalize_billing_records(44, [], rows, [], [])
        return self.ba.build_billing_analytics(recs, 100, PERIOD)

    def test_refunded_charge_is_not_counted_as_consumption(self):
        a = self._analytics([usage_row(1, "10", "charged", TS),
                             usage_row(2, "90", "refunded", TS)])

        self.assertAlmostEqual(a["metrics"]["totalConsumption"], 10.0,
                               msg="退掉的 90 不该计入总消耗")

    def test_refunded_charge_still_appears_in_the_detail_list(self):
        """只是不计入合计;明细里仍要看得到,带"已退款"标记。"""
        recs = self.ba.normalize_billing_records(44, [], [usage_row(2, "90", "refunded", TS)], [], [])

        charge_rows = [r for r in recs if r["id"].startswith("usage-") and not r["id"].startswith("usage-refund-")]
        self.assertEqual(len(charge_rows), 1)
        self.assertEqual(charge_rows[0]["status"], "refunded")
        self.assertEqual(charge_rows[0]["statusLabel"], "已退款")

    def test_plain_charge_is_still_counted(self):
        a = self._analytics([usage_row(1, "10", "charged", TS)])

        self.assertAlmostEqual(a["metrics"]["totalConsumption"], 10.0)

    def test_distribution_and_trend_also_exclude_refunds(self):
        a = self._analytics([usage_row(1, "10", "charged", TS),
                             usage_row(2, "90", "refunded", TS)])

        self.assertAlmostEqual(sum(d["amount"] for d in a["distribution"]), 10.0)
        self.assertAlmostEqual(sum(t["amount"] for t in a["trend"]), 10.0)

    def test_matches_the_comic_side_arithmetic(self):
        """用真实比例复现:含退款 100 vs 剔除后 10,漫剧口径取后者。"""
        rows = [usage_row(i, "10", "charged", TS) for i in range(1, 2)]
        rows += [usage_row(i, "10", "refunded", TS) for i in range(2, 11)]

        a = self._analytics(rows)

        self.assertAlmostEqual(a["metrics"]["totalConsumption"], 10.0)


if __name__ == "__main__":
    unittest.main()
