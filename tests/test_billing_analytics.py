from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from billing_analytics import (
    BillingQueryError,
    build_billing_analytics,
    build_billing_ledger,
    normalize_billing_records,
    parse_ledger_filters,
    parse_period,
    validate_billing_payload,
)


CN_TZ = timezone(timedelta(hours=8))


class BillingAnalyticsTest(unittest.TestCase):
    def test_active_day_average_excludes_zero_days_recharges_and_refunds(self):
        period = parse_period({}, now=datetime(2026, 7, 30, 12, tzinfo=CN_TZ))
        rows = normalize_billing_records(
            user_id=44,
            ledger_rows=[
                {"id": "c1", "userId": 44, "delta": -12, "reason": "视频生成", "ref": "video:t1", "ts": datetime(2026, 7, 29, 10, tzinfo=CN_TZ).timestamp(), "balanceAfter": 88},
                {"id": "i1", "userId": 44, "delta": -6, "reason": "图片生成", "ref": "image:t2", "ts": datetime(2026, 7, 30, 10, tzinfo=CN_TZ).timestamp(), "balanceAfter": 82},
                {"id": "r1", "userId": 44, "delta": 6, "reason": "退款:图片生成", "ref": "image:t2", "ts": datetime(2026, 7, 30, 10, 5, tzinfo=CN_TZ).timestamp(), "balanceAfter": 88},
                {"id": "p1", "userId": 44, "delta": 100, "reason": "管理员充值", "ref": "topup:1", "ts": datetime(2026, 7, 30, 10, 10, tzinfo=CN_TZ).timestamp(), "balanceAfter": 188},
            ],
            model_usage_rows=[], recharge_orders=[], redeem_codes=[],
        )
        payload = build_billing_analytics(rows, Decimal("188"), period)
        self.assertEqual(payload["metrics"]["totalConsumption"], 18.0)
        self.assertEqual(payload["metrics"]["activeConsumptionDays"], 2)
        self.assertEqual(payload["metrics"]["dailyAverage"], 9.0)
        self.assertEqual([x["type"] for x in payload["distribution"]], ["video", "image", "voice", "other"])

    def test_refunded_model_log_expands_to_charge_and_refund(self):
        rows = normalize_billing_records(
            44, [], [{"id": 7, "request_id": "req-7", "task_id": "task-7", "model_id": "vidu", "model_type": "video", "amount": "10", "balance_after": "90", "status": "refunded", "created_at": "2026-07-29 10:00:00", "refunded_at": "2026-07-29 10:05:00"}], [], []
        )
        self.assertEqual({x["status"]: x["change"] for x in rows}, {"charged": -10.0, "refunded": 10.0})

    def test_authoritative_refund_keeps_matching_model_charge_without_synthetic_refund(self):
        rows = normalize_billing_records(
            44,
            [{"id": "ledger-refund", "userId": 44, "delta": "10", "reason": "refund", "ref": "req-7", "ts": datetime(2026, 7, 29, 10, tzinfo=CN_TZ).timestamp(), "balanceAfter": "100"}],
            [{"id": 7, "user_id": 44, "request_id": "req-7", "task_id": "task-7", "model_type": "video", "amount": "10", "status": "refunded", "created_at": "2026-07-29 10:00:00", "refunded_at": "2026-07-29 10:05:00"}],
            [],
            [],
        )
        self.assertEqual({row["id"]: (row["status"], row["change"]) for row in rows}, {
            "ledger-refund": ("refunded", Decimal("10")),
            "usage-7": ("charged", Decimal("-10")),
        })

    def test_normalized_amounts_remain_decimal_until_ledger_response_conversion(self):
        rows = normalize_billing_records(
            44,
            [{"id": "charge", "userId": 44, "delta": "-1.25", "ref": "video:1", "ts": datetime(2026, 7, 29, 10, tzinfo=CN_TZ).timestamp(), "balanceAfter": "98.75"}],
            [],
            [],
            [],
        )
        self.assertEqual(rows[0]["change"], Decimal("-1.25"))
        self.assertEqual(rows[0]["balanceAfter"], Decimal("98.75"))
        page = build_billing_ledger(rows, dict(parse_ledger_filters({"startDate": ["2026-01-01"], "endDate": ["2026-12-31"]}), page=1, pageSize=20))
        self.assertEqual(page["ledger"][0]["change"], -1.25)
        self.assertEqual(page["ledger"][0]["balanceAfter"], 98.75)
        self.assertIsInstance(rows[0]["change"], Decimal)
        self.assertIsInstance(rows[0]["balanceAfter"], Decimal)

    def test_video_average_counts_distinct_tasks_not_model_calls(self):
        rows = [
            {"id": "v1", "timestamp": datetime(2026, 7, 29, tzinfo=CN_TZ).timestamp(), "type": "video", "status": "charged", "change": -4.0, "taskId": "video-1", "requestId": "request-1"},
            {"id": "v2", "timestamp": datetime(2026, 7, 29, 1, tzinfo=CN_TZ).timestamp(), "type": "video", "status": "charged", "change": -6.0, "taskId": "video-1", "requestId": "request-2"},
        ]
        payload = build_billing_analytics(rows, Decimal("90"), parse_period({"startDate": ["2026-07-01"], "endDate": ["2026-07-30"]}))
        self.assertEqual(payload["metrics"]["videoTaskCount"], 1)
        self.assertEqual(payload["metrics"]["videoAverage"], 10.0)

    def test_month_grouping_zero_fills_range_and_unknown_type_becomes_other(self):
        period = parse_period({"startDate": ["2026-05-01"], "endDate": ["2026-07-30"], "groupBy": ["month"]})
        rows = normalize_billing_records(44, [{"id": "x", "userId": 44, "delta": -2, "reason": "未知能力", "ref": "unknown:1", "ts": datetime(2026, 6, 1, tzinfo=CN_TZ).timestamp(), "balanceAfter": 98}], [], [], [])
        payload = build_billing_analytics(rows, Decimal("98"), period)
        self.assertEqual([x["bucket"] for x in payload["trend"]], ["2026-05", "2026-06", "2026-07"])
        self.assertEqual(next(x["amount"] for x in payload["distribution"] if x["type"] == "other"), 2.0)

    def test_period_rejects_more_than_366_days(self):
        with self.assertRaisesRegex(BillingQueryError, "date_range_too_large"):
            parse_period({"startDate": ["2025-01-01"], "endDate": ["2026-07-30"]})

    def test_ledger_filters_limit_page_size_and_support_confirmed_statuses(self):
        filters = parse_ledger_filters({"page": ["2"], "pageSize": ["50"], "status": ["refunded"]})
        self.assertEqual((filters["page"], filters["pageSize"], filters["status"]), (2, 50, "refunded"))
        with self.assertRaisesRegex(BillingQueryError, "invalid_page_size"):
            parse_ledger_filters({"pageSize": ["101"]})

    def test_runtime_schemas_reject_invalid_query_and_response(self):
        with self.assertRaises(jsonschema.ValidationError):
            validate_billing_payload("analytics_query", {"groupBy": "week"})
        with self.assertRaises(jsonschema.ValidationError):
            validate_billing_payload("analytics_response", {"ok": True, "metrics": {}})

    def test_operator_unlimited_balance_is_schema_valid(self):
        payload = build_billing_analytics([], "inf", parse_period({}, now=datetime(2026, 7, 30, 12, tzinfo=CN_TZ)))
        validate_billing_payload("analytics_response", dict(payload, ok=True))
        self.assertEqual(payload["metrics"]["balance"], "inf")

    def test_only_exact_inf_string_represents_unlimited_balance(self):
        payload = build_billing_analytics([], "inf", parse_period({}, now=datetime(2026, 7, 30, 12, tzinfo=CN_TZ)))
        self.assertEqual(payload["metrics"]["balance"], "inf")
        validate_billing_payload("analytics_response", dict(payload, ok=True))

    def test_non_finite_balance_values_are_rejected_before_response_validation(self):
        period = parse_period({}, now=datetime(2026, 7, 30, 12, tzinfo=CN_TZ))
        for balance in ("Infinity", Decimal("Infinity"), float("inf"), Decimal("NaN"), float("nan"), float("-inf")):
            with self.subTest(balance=repr(balance)):
                with self.assertRaisesRegex(ValueError, "invalid billing amount"):
                    build_billing_analytics([], balance, period)
