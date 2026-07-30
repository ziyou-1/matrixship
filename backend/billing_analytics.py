"""Pure billing analytics transformations shared by future API handlers."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from math import ceil

from jsonschema import Draft202012Validator, FormatChecker


CN_TZ = timezone(timedelta(hours=8))
MAX_RANGE_DAYS = 366
PAGE_SIZES = (20, 50, 100)
TYPE_LABELS = {
    "video": "视频生成", "image": "图片生成", "voice": "配音", "other": "其他",
    "recharge": "充值", "refund": "退款",
}
STATUS_LABELS = {
    "charged": "已扣费", "refunded": "已退款", "recharged": "已充值", "failed": "失败",
}
_TYPES = tuple(TYPE_LABELS)
_STATUSES = tuple(STATUS_LABELS)


class BillingQueryError(ValueError):
    def __init__(self, code, message):
        super().__init__(code)
        self.code = code
        self.message = message


def _query_value(params, key):
    value = (params or {}).get(key)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return value if value not in (None, "") else None


def _date_value(params, key):
    value = _query_value(params, key)
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise BillingQueryError("invalid_date", "日期必须为 YYYY-MM-DD") from exc


def _day_start(day):
    return datetime.combine(day, datetime.min.time(), tzinfo=CN_TZ).timestamp()


def parse_period(params, now=None):
    current = (now or datetime.now(CN_TZ)).astimezone(CN_TZ)
    end_day = _date_value(params, "endDate") or current.date()
    start_day = _date_value(params, "startDate") or (end_day - timedelta(days=29))
    if start_day > end_day:
        raise BillingQueryError("invalid_date_range", "开始日期不能晚于结束日期")
    if (end_day - start_day).days + 1 > MAX_RANGE_DAYS:
        raise BillingQueryError("date_range_too_large", "查询范围最多 366 天")
    group_by = _query_value(params, "groupBy") or "day"
    if group_by not in ("day", "month"):
        raise BillingQueryError("invalid_group_by", "分组方式只能是 day 或 month")
    return {
        "startDate": start_day.isoformat(), "endDate": end_day.isoformat(),
        "startTs": _day_start(start_day), "endTs": _day_start(end_day + timedelta(days=1)),
        "groupBy": group_by, "timezone": "Asia/Shanghai",
    }


def parse_ledger_filters(params, now=None):
    period = parse_period(params, now=now)
    def integer(key, default):
        value = _query_value(params, key)
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError) as exc:
            raise BillingQueryError("invalid_" + key.lower(), key + " 必须为整数") from exc
    page, page_size = integer("page", 1), integer("pageSize", 20)
    if page < 1:
        raise BillingQueryError("invalid_page", "页码必须大于 0")
    if page_size not in PAGE_SIZES:
        raise BillingQueryError("invalid_page_size", "每页数量只能是 20、50 或 100")
    row_type, status = _query_value(params, "type"), _query_value(params, "status")
    if row_type and row_type not in _TYPES:
        raise BillingQueryError("invalid_type", "类型不受支持")
    if status and status not in _STATUSES:
        raise BillingQueryError("invalid_status", "状态不受支持")
    return dict(period, page=page, pageSize=page_size, type=row_type, status=status)


def _amount(value, default="0"):
    try:
        amount = Decimal(str(value if value is not None else default))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid billing amount") from exc
    if not amount.is_finite():
        raise ValueError("invalid billing amount")
    return amount


def _timestamp(value):
    if isinstance(value, datetime):
        return value.astimezone(CN_TZ).timestamp() if value.tzinfo else value.replace(tzinfo=CN_TZ).timestamp()
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if value:
        text = str(value).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=CN_TZ)).astimezone(CN_TZ).timestamp()
    return 0.0


def _type_for(row):
    explicit = str(row.get("model_type") or row.get("modelType") or "").lower()
    haystack = " ".join(str(row.get(key) or "") for key in ("model_id", "modelId", "capability", "ref", "reason", "detail")).lower()
    if explicit in ("video", "image", "voice"):
        return explicit
    if any(word in haystack for word in ("video", "vidu", "seedance", "视频")):
        return "video"
    if any(word in haystack for word in ("image", "图片", "keyframe", "gpt-image")):
        return "image"
    if any(word in haystack for word in ("voice", "tts", "配音", "声音")):
        return "voice"
    return "other"


def _record(record_id, timestamp, row_type, change, status, **values):
    created = datetime.fromtimestamp(timestamp, CN_TZ).isoformat()
    return {
        "id": str(record_id), "createdAt": created, "timestamp": float(timestamp),
        "type": row_type, "typeLabel": TYPE_LABELS[row_type],
        "modelId": str(values.get("model_id") or ""), "taskId": str(values.get("task_id") or ""),
        "requestId": str(values.get("request_id") or ""), "detail": str(values.get("detail") or ""),
        "change": change, "balanceAfter": values.get("balance_after"),
        "status": status, "statusLabel": STATUS_LABELS[status],
    }


def _is_refund_ledger(row, delta):
    reason = str(row.get("reason") or "").lower()
    return delta > 0 and ("退款" in reason or "refund" in reason or "refund" in str(row.get("ref") or "").lower())


def _same_ref(left, right):
    return bool(left and right and str(left) == str(right))


def normalize_billing_records(user_id, ledger_rows, model_usage_rows, recharge_orders, redeem_codes):
    """Return deterministic, deduplicated records without querying infrastructure."""
    ledger_rows = [row for row in (ledger_rows or []) if str(row.get("userId", row.get("user_id", user_id))) == str(user_id)]
    records, ledger_refs, charge_ledger_refs, refund_refs = [], set(), set(), set()
    for row in ledger_rows:
        delta = _amount(row.get("delta"))
        ref = row.get("ref")
        is_refund = _is_refund_ledger(row, delta)
        if ref:
            ledger_refs.add(str(ref))
            if delta < 0:
                charge_ledger_refs.add(str(ref))
        if is_refund and ref:
            refund_refs.add(str(ref))
        row_type = "refund" if is_refund else ("recharge" if delta > 0 else _type_for(row))
        status = "refunded" if is_refund else ("recharged" if delta > 0 else "charged")
        records.append(_record(row.get("id", ref or len(records)), _timestamp(row.get("ts", row.get("createdAt"))), row_type, delta, status,
            model_id=row.get("modelId"), task_id=row.get("taskId"), request_id=row.get("requestId"),
            detail=row.get("reason") or row.get("detail") or TYPE_LABELS[row_type], balance_after=(_amount(row["balanceAfter"]) if row.get("balanceAfter") is not None else None)))
    for row in model_usage_rows or []:
        if str(row.get("user_id", user_id)) != str(user_id):
            continue
        ref = row.get("ref") or row.get("request_id") or row.get("requestId")
        if ref and str(ref) in charge_ledger_refs:
            continue
        amount = abs(_amount(row.get("amount")))
        base = dict(model_id=row.get("model_id") or row.get("modelId"), task_id=row.get("task_id") or row.get("taskId"), request_id=row.get("request_id") or row.get("requestId"), detail=row.get("detail") or row.get("reason") or "模型调用", balance_after=(_amount(row["balance_after"]) if row.get("balance_after") is not None else None))
        row_type = _type_for(row)
        records.append(_record("usage-" + str(row.get("id", ref)), _timestamp(row.get("created_at") or row.get("createdAt")), row_type, -amount, "charged", **base))
        if str(row.get("status", "")).lower() == "refunded" and not (ref and str(ref) in refund_refs):
            records.append(_record("usage-refund-" + str(row.get("id", ref)), _timestamp(row.get("refunded_at") or row.get("created_at")), "refund", amount, "refunded", **base))
    for source, used_status in ((recharge_orders or [], ("paid", "success", "completed")), (redeem_codes or [], ("used",))):
        for row in source:
            if str(row.get("userId", row.get("user_id", user_id))) != str(user_id):
                continue
            ref = row.get("ref") or row.get("orderNo") or row.get("order_no") or row.get("code")
            if ref and str(ref) in ledger_refs:
                continue
            status_value = str(row.get("status", "")).lower()
            failed = source is recharge_orders and status_value in ("payerror", "closed", "revoked")
            if not failed and status_value not in used_status:
                continue
            timestamp = _timestamp(row.get("paid_at") or row.get("used_at") or row.get("created_at") or row.get("createdAt"))
            change = Decimal("0") if failed else abs(_amount(row.get("credit", row.get("yundou", row.get("amount")))))
            records.append(_record(("failed-" if failed else "recharge-") + str(ref or row.get("id", len(records))), timestamp, "recharge", change, "failed" if failed else "recharged", detail="充值失败" if failed else "充值", balance_after=None))
    return sorted(records, key=lambda item: (item["timestamp"], item["id"]), reverse=True)


def _in_period(row, period):
    return period["startTs"] <= row.get("timestamp", 0) < period["endTs"]


def _consumption(rows, period):
    return [row for row in rows if _in_period(row, period) and row.get("status") == "charged" and row.get("change", 0) < 0 and row.get("type") in ("video", "image", "voice", "other")]


def _buckets(period):
    start, end = date.fromisoformat(period["startDate"]), date.fromisoformat(period["endDate"])
    if period["groupBy"] == "day":
        while start <= end:
            yield start.isoformat()
            start += timedelta(days=1)
    else:
        start = start.replace(day=1)
        end = end.replace(day=1)
        while start <= end:
            yield start.strftime("%Y-%m")
            start = (start.replace(day=28) + timedelta(days=4)).replace(day=1)


def _bucket(row, group_by):
    value = datetime.fromtimestamp(row["timestamp"], CN_TZ)
    return value.strftime("%Y-%m") if group_by == "month" else value.date().isoformat()


def build_billing_analytics(records, balance, period):
    consumption = _consumption(records or [], period)
    amounts = [abs(_amount(row["change"])) for row in consumption]
    total = sum(amounts, Decimal("0"))
    active_days = {datetime.fromtimestamp(row["timestamp"], CN_TZ).date() for row in consumption}
    video = [row for row in consumption if row.get("type") == "video"]
    video_total = sum((abs(_amount(row["change"])) for row in video), Decimal("0"))
    video_ids = {row.get("taskId") or row.get("requestId") or row.get("id") for row in video}
    trend = {bucket: Decimal("0") for bucket in _buckets(period)}
    distribution = {kind: Decimal("0") for kind in ("video", "image", "voice", "other")}
    for row in consumption:
        amount = abs(_amount(row["change"]))
        trend[_bucket(row, period["groupBy"])] += amount
        distribution[row["type"]] += amount
    balance_value = "inf" if balance == "inf" else float(_amount(balance))
    return {
        "period": {key: period[key] for key in ("startDate", "endDate", "groupBy", "timezone")},
        "metrics": {"balance": balance_value, "totalConsumption": float(total), "activeConsumptionDays": len(active_days), "dailyAverage": float(total / len(active_days)) if active_days else 0.0, "videoTaskCount": len(video_ids), "videoAverage": float(video_total / len(video_ids)) if video_ids else 0.0},
        "trend": [{"bucket": bucket, "amount": float(amount)} for bucket, amount in trend.items()],
        "distribution": [{"type": kind, "label": TYPE_LABELS[kind], "amount": float(amount), "ratio": float(amount / total * 100) if total else 0.0} for kind, amount in distribution.items()],
    }


def build_billing_ledger(records, filters):
    selected = [row for row in records or [] if _in_period(row, filters)]
    for key in ("type", "status"):
        if filters.get(key):
            selected = [row for row in selected if row.get(key) == filters[key]]
    selected.sort(key=lambda item: (item.get("timestamp", 0), item.get("id", "")), reverse=True)
    total, page_size, page = len(selected), filters["pageSize"], filters["page"]
    start = (page - 1) * page_size
    ledger = [
        dict(
            row,
            change=float(_amount(row["change"])),
            balanceAfter=(float(_amount(row["balanceAfter"])) if row.get("balanceAfter") is not None else None),
        )
        for row in selected[start:start + page_size]
    ]
    return {"ledger": ledger, "pagination": {"page": page, "pageSize": page_size, "total": total, "totalPages": ceil(total / page_size) if total else 0}}


_QUERY_DATE = {"type": "string", "format": "date"}
ANALYTICS_QUERY_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False, "properties": {"startDate": _QUERY_DATE, "endDate": _QUERY_DATE, "groupBy": {"enum": ["day", "month"]}}}
LEDGER_QUERY_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False, "properties": {"startDate": _QUERY_DATE, "endDate": _QUERY_DATE, "type": {"enum": list(_TYPES)}, "status": {"enum": list(_STATUSES)}, "page": {"type": "integer", "minimum": 1}, "pageSize": {"enum": list(PAGE_SIZES)}}}
_PERIOD_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["startDate", "endDate", "groupBy", "timezone"], "properties": {"startDate": _QUERY_DATE, "endDate": _QUERY_DATE, "groupBy": {"enum": ["day", "month"]}, "timezone": {"const": "Asia/Shanghai"}}}
_METRICS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["balance", "totalConsumption", "activeConsumptionDays", "dailyAverage", "videoTaskCount", "videoAverage"], "properties": {"balance": {"oneOf": [{"type": "number"}, {"const": "inf"}]}, "totalConsumption": {"type": "number"}, "activeConsumptionDays": {"type": "integer", "minimum": 0}, "dailyAverage": {"type": "number"}, "videoTaskCount": {"type": "integer", "minimum": 0}, "videoAverage": {"type": "number"}}}
_ROW_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["id", "createdAt", "timestamp", "type", "typeLabel", "modelId", "taskId", "requestId", "detail", "change", "balanceAfter", "status", "statusLabel"], "properties": {"id": {"type": "string"}, "createdAt": {"type": "string", "format": "date-time"}, "timestamp": {"type": "number"}, "type": {"enum": list(_TYPES)}, "typeLabel": {"type": "string"}, "modelId": {"type": "string"}, "taskId": {"type": "string"}, "requestId": {"type": "string"}, "detail": {"type": "string"}, "change": {"type": "number"}, "balanceAfter": {"type": ["number", "null"]}, "status": {"enum": list(_STATUSES)}, "statusLabel": {"type": "string"}}}
ANALYTICS_RESPONSE_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False, "required": ["ok", "period", "metrics", "trend", "distribution"], "properties": {"ok": {"const": True}, "period": _PERIOD_SCHEMA, "metrics": _METRICS_SCHEMA, "trend": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["bucket", "amount"], "properties": {"bucket": {"type": "string"}, "amount": {"type": "number"}}}}, "distribution": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["type", "label", "amount", "ratio"], "properties": {"type": {"enum": ["video", "image", "voice", "other"]}, "label": {"type": "string"}, "amount": {"type": "number"}, "ratio": {"type": "number"}}}}}}
LEDGER_RESPONSE_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False, "required": ["ok", "balance", "ledger", "pagination"], "properties": {"ok": {"const": True}, "balance": {"oneOf": [{"type": "number"}, {"const": "inf"}]}, "ledger": {"type": "array", "items": _ROW_SCHEMA}, "pagination": {"type": "object", "additionalProperties": False, "required": ["page", "pageSize", "total", "totalPages"], "properties": {"page": {"type": "integer", "minimum": 1}, "pageSize": {"enum": list(PAGE_SIZES)}, "total": {"type": "integer", "minimum": 0}, "totalPages": {"type": "integer", "minimum": 0}}}}}

SCHEMAS = {"analytics_query": ANALYTICS_QUERY_SCHEMA, "ledger_query": LEDGER_QUERY_SCHEMA, "analytics_response": ANALYTICS_RESPONSE_SCHEMA, "ledger_response": LEDGER_RESPONSE_SCHEMA}


def validate_billing_payload(schema_name, payload):
    schema = SCHEMAS[schema_name]
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    return payload
