"""Deterministic Phase 0 smoke for the isolated billing domain."""

import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from billing_analytics import (  # noqa: E402
    build_billing_analytics, build_billing_ledger, normalize_billing_records,
    parse_ledger_filters, parse_period, validate_billing_payload,
)


CN_TZ = timezone(timedelta(hours=8))
period = parse_period({"startDate": ["2026-07-29"], "endDate": ["2026-07-30"]})
filters = parse_ledger_filters({"startDate": ["2026-07-29"], "endDate": ["2026-07-30"]})
records = normalize_billing_records(44, [
    {"id": "video", "userId": 44, "delta": -10, "reason": "视频生成", "ref": "video:t1", "ts": datetime(2026, 7, 29, 10, tzinfo=CN_TZ).timestamp(), "balanceAfter": 90},
    {"id": "image", "userId": 44, "delta": -5, "reason": "图片生成", "ref": "image:t2", "ts": datetime(2026, 7, 30, 9, tzinfo=CN_TZ).timestamp(), "balanceAfter": 85},
    {"id": "voice", "userId": 44, "delta": -3, "reason": "配音", "ref": "voice:t3", "ts": datetime(2026, 7, 30, 10, tzinfo=CN_TZ).timestamp(), "balanceAfter": 82},
    {"id": "refund", "userId": 44, "delta": 5, "reason": "退款:图片生成", "ref": "image:t2", "ts": datetime(2026, 7, 30, 10, 5, tzinfo=CN_TZ).timestamp(), "balanceAfter": 87},
    {"id": "topup", "userId": 44, "delta": 33, "reason": "管理员充值", "ref": "topup:1", "ts": datetime(2026, 7, 30, 10, 10, tzinfo=CN_TZ).timestamp(), "balanceAfter": 120},
], [], [], [])
payload = build_billing_analytics(records, Decimal("120"), period)
page = build_billing_ledger(records, dict(filters, page=1, pageSize=20))
assert payload["metrics"]["activeConsumptionDays"] == 2
assert all(item["type"] in {"video", "image", "voice", "other"} for item in payload["distribution"])
assert {row["status"] for row in page["ledger"]} >= {"charged", "refunded", "recharged"}
validate_billing_payload("analytics_response", dict(payload, ok=True))
validate_billing_payload("ledger_response", dict(page, ok=True, balance=120.0))
print(json.dumps({"ok": True, "analytics": payload, "ledger": page}, ensure_ascii=False))
