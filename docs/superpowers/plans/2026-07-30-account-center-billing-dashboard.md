# Account Center Billing Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an authoritative center-server billing dashboard and render it in the native Account Center with the confirmed metrics, charts, filters, pagination, permission rules, and traceable recharge/refund records.

**Architecture:** Add a pure `billing_analytics.py` domain module for validation, normalization, deduplication, aggregation, and pagination. `maindb.py` supplies bounded model-usage rows, `central_server.py` owns authorization/data collection/API responses, and `matrix_native_client.py` only renders server results with lightweight `QPainter` widgets. Existing no-parameter ledger behavior remains compatible.

**Tech Stack:** Python 3, standard-library `datetime`/`decimal`, `jsonschema==4.23.0`, existing `ThreadingHTTPServer`, MySQL through `pymysql`, PySide6, `QPainter`, `unittest`, OpenAPI YAML.

## Global Constraints

- Default period is the latest 30 calendar days in `Asia/Shanghai`; start and end dates are inclusive.
- Custom date ranges are limited to 366 days.
- Daily average is total consumption divided by calendar days that contain at least one valid consumption record; zero consumption returns zero.
- Top metrics are only balance, period consumption, daily average, and average cost per distinct billed video task.
- Preserve the existing `user-owner` unlimited balance: analytics returns `balance: "inf"` and the client displays “∞ 运营方”; every other account returns a numeric balance.
- Consumption categories are only `video`, `image`, `voice`, and `other`.
- Recharge and refund rows appear in details but never affect totals, averages, trends, or distribution.
- Refunds retain the original negative charge row and add a positive refund row linked by task/request ID.
- Detail statuses are `charged`, `refunded`, `recharged`, and `failed`.
- Detail page sizes are 20, 50, and 100; default 20 and server maximum 100.
- Platform administrators retain current recharge, redeem-code, phone-binding, and user-management controls; enterprise and normal users do not see those controls.
- No new database table or migration is allowed. `migration.sql` remains a documented no-op.
- Do not add QtCharts or a WebView. Use existing PySide6 and `QPainter` patterns.
- Runtime request and response validation must use pinned `jsonschema==4.23.0`; do not silently skip validation when the dependency is missing.
- Logs are structured JSON and must not include tokens, passwords, complete phone numbers, headers, or signed URLs.
- Preserve default `.env` loading in production, but support explicit `CENTRAL_LOAD_DOTENV=0` for isolated dev/staging tests so local `.env` values cannot override smoke-test ports or tokens.
- Do not restart the local client automatically. Center-server restart/deployment requires a separate confirmation after verification.
- Before every commit, recalculate all line references added to `docs/IMPLEMENTATION.md`; stage only task-owned hunks because the worktree already contains unrelated changes.

## File Map

- Create `backend/billing_analytics.py`: pure billing query parsing, record normalization, deduplication, analytics, and detail pagination.
- Modify `backend/requirements.txt` and `backend/requirements.deploy.txt`: pin `jsonschema==4.23.0` for local and deployed center-server runtimes.
- Create `tests/test_billing_analytics.py`: pure-domain and fake-data smoke coverage.
- Create `scripts/smoke_billing_dashboard.py`: deterministic Phase 0 fake-data end-to-end smoke.
- Modify `backend/maindb.py`: bounded `model_usage_logs` reader only; no schema changes.
- Modify `backend/central_server.py`: traceable future recharge/refund writes, data collection, analytics route, enhanced ledger route, structured logs.
- Create `tests/test_billing_dashboard_api.py`: center-service payload, validation, compatibility, and observability tests.
- Modify `tests/test_billing_unified.py`: recharge/refund persistence regression coverage.
- Modify `docs/openapi.yaml`: query and response JSON Schemas.
- Modify `tests/test_openapi_contract.py`: schema/path contract tests.
- Modify `docs/API_REFERENCE.md`: endpoint and statistical semantics.
- Modify `backend/matrix_native_client.py`: dashboard widgets, filters, async request sequencing, and seven-column details.
- Create `tests/test_account_billing_dashboard.py`: native-client source/Qt behavior tests.
- Create `scripts/smoke_account_billing_ui.py`: offscreen dashboard render for desktop viewport checks.
- Create `scripts/smoke_billing_performance.py`: authenticated local 20-concurrency/P95 check without logging credentials.
- Create `scripts/monitor_billing_rollout.py`: rollout error-rate monitor with a dry-run mode and previous-image rollback command.
- Create `tests/test_billing_rollout_guard.py`: rollback threshold, dry-run, subprocess safety, and log-redaction tests.
- Modify `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `docs/TROUBLESHOOTING.md`, `docs/IMPLEMENTATION.md`, `CHANGELOG.md`, and `migration.sql`: production traceability, verification, line references, and rollback.

---

### Task 1: Pure Billing Domain And Phase 0 Smoke

**Files:**
- Create: `backend/billing_analytics.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements.deploy.txt`
- Create: `tests/test_billing_analytics.py`
- Create: `scripts/smoke_billing_dashboard.py`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`

**Interfaces:**
- Produces: `BillingQueryError`, `parse_period(params, now=None)`, `parse_ledger_filters(params, now=None)`, `normalize_billing_records(user_id, ledger_rows, model_usage_rows, recharge_orders, redeem_codes)`, `build_billing_analytics(records, balance, period)`, `build_billing_ledger(records, filters)`, and `validate_billing_payload(schema_name, payload)`.
- Produces JSON Schemas: `ANALYTICS_QUERY_SCHEMA`, `LEDGER_QUERY_SCHEMA`, `ANALYTICS_RESPONSE_SCHEMA`, and `LEDGER_RESPONSE_SCHEMA` using Draft 2020-12.
- Internal normalized rows always contain `id`, `createdAt`, `timestamp`, `type`, `typeLabel`, `modelId`, `taskId`, `requestId`, `detail`, `change`, `balanceAfter`, `status`, and `statusLabel`.

- [ ] **Step 1: Pin and install the approved schema dependency**

Append the exact same locked requirement to both requirement files:

```text
jsonschema==4.23.0
```

Confirm the project virtual environment is active/targeted, then install only the approved package:

```powershell
.\.venv-win\Scripts\python.exe -m pip install jsonschema==4.23.0
.\.venv-win\Scripts\python.exe -c "from importlib.metadata import version; print(version('jsonschema'))"
```

Expected: installation succeeds and prints `4.23.0`. If installation fails with `ModuleNotFoundError` or dependency conflict, stop, verify `.venv-win` and the requirement lock, and record the full context before continuing.

- [ ] **Step 2: Write failing domain and runtime-schema tests**

Create tests that lock the confirmed formulas and error rules:

```python
from datetime import datetime, timezone, timedelta
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
        f = parse_ledger_filters({"page": ["2"], "pageSize": ["50"], "status": ["refunded"]})
        self.assertEqual((f["page"], f["pageSize"], f["status"]), (2, 50, "refunded"))
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
```

- [ ] **Step 3: Run the tests and verify the intended failure**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_billing_analytics -v
```

Expected: FAIL because `backend/billing_analytics.py` does not exist.

- [ ] **Step 4: Implement the pure module and Draft 2020-12 schemas**

Use `Decimal` for every intermediate amount and convert only public response values to `float`. Implement fixed UTC+8 date boundaries without adding timezone packages:

```python
CN_TZ = timezone(timedelta(hours=8))
MAX_RANGE_DAYS = 366
PAGE_SIZES = (20, 50, 100)
TYPE_LABELS = {"video": "视频生成", "image": "图片生成", "voice": "配音", "other": "其他", "recharge": "充值", "refund": "退款"}
STATUS_LABELS = {"charged": "已扣费", "refunded": "已退款", "recharged": "已充值", "failed": "失败"}


class BillingQueryError(ValueError):
    def __init__(self, code, message):
        super().__init__(code)
        self.code = code
        self.message = message


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
    return {"startDate": start_day.isoformat(), "endDate": end_day.isoformat(), "startTs": _day_start(start_day), "endTs": _day_start(end_day + timedelta(days=1)), "groupBy": group_by, "timezone": "Asia/Shanghai"}
```

Define explicit schemas and a strict dispatcher:

```python
from jsonschema import Draft202012Validator, FormatChecker

SCHEMAS = {
    "analytics_query": ANALYTICS_QUERY_SCHEMA,
    "ledger_query": LEDGER_QUERY_SCHEMA,
    "analytics_response": ANALYTICS_RESPONSE_SCHEMA,
    "ledger_response": LEDGER_RESPONSE_SCHEMA,
}


def validate_billing_payload(schema_name, payload):
    schema = SCHEMAS[schema_name]
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    return payload
```

Query schemas must reject unknown keys, invalid dates, unsupported enums, page values below 1, and page sizes outside 20/50/100. Response schemas must require all confirmed metric, period, trend, distribution, row, and pagination fields; `balanceAfter` accepts number or null. Analytics `metrics.balance` accepts either a number or the exact string `"inf"`; no other string is valid.

Implement normalization with these precedence rules:

1. Explicit state-ledger rows take precedence because they contain the actual post-change balance.
2. A refunded `model_usage_logs` row expands into an original negative charge plus a positive refund; if a matching positive state-ledger refund exists, discard the synthetic refund.
3. Paid recharge orders and used redeem codes fill historical gaps only when no matching ledger `ref` exists.
4. `PAYERROR`, `CLOSED`, and `REVOKED` recharge orders become zero-change `failed` rows; unpaid pending orders are omitted.
5. Category matching checks explicit `model_type`, then model ID/capability/ref/reason keywords; unknown values become `other`.

Implement analytics and pagination as pure transformations. Trend buckets must be zero-filled across the full period. Video average uses distinct `taskId`, falling back to `requestId`, then row `id`.

- [ ] **Step 5: Add the deterministic Phase 0 smoke script**

The script must import only the pure module, feed one video charge, one image charge, one voice charge, one recharge, and one refund, then print one JSON object and exit nonzero on any mismatch:

```python
payload = build_billing_analytics(records, Decimal("120"), period)
page = build_billing_ledger(records, dict(filters, page=1, pageSize=20))
assert payload["metrics"]["activeConsumptionDays"] == 2
assert all(item["type"] in {"video", "image", "voice", "other"} for item in payload["distribution"])
assert {row["status"] for row in page["ledger"]} >= {"charged", "refunded", "recharged"}
validate_billing_payload("analytics_response", dict(payload, ok=True))
validate_billing_payload("ledger_response", dict(page, ok=True, balance=120.0))
print(json.dumps({"ok": True, "analytics": payload, "ledger": page}, ensure_ascii=False))
```

Run:

```powershell
.\.venv-win\Scripts\python.exe scripts\smoke_billing_dashboard.py
```

Expected: one JSON line with `"ok": true`.

- [ ] **Step 6: Run domain tests and record smoke evidence**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_billing_analytics -v
.\.venv-win\Scripts\python.exe -m py_compile backend\billing_analytics.py scripts\smoke_billing_dashboard.py tests\test_billing_analytics.py
```

Expected: all tests PASS and compilation exits 0. Add the initial missing-module failure and passing smoke result to `docs/TROUBLESHOOTING.md`. Add exact new-file line references and rollback scope to `docs/IMPLEMENTATION.md`.

- [ ] **Step 7: Review checkpoint and optional commit**

Verify `git diff --check`, recalculate the new `IMPLEMENTATION.md` references, and stage only Task 1 hunks. Commit only after confirming no unrelated existing documentation changes would be included:

```powershell
git commit -m "feat: add billing analytics domain"
```

### Task 2: Bounded Data Sources And Traceable Balance Changes

**Files:**
- Modify: `backend/maindb.py:204-283`
- Modify: `backend/central_server.py:3039-3225`
- Modify: `backend/central_server.py:3414-3500`
- Modify: `tests/test_billing_unified.py`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`

**Interfaces:**
- Produces: `maindb.list_model_usage_logs(uid, start_at, end_at, limit=50001) -> list[dict]`.
- Preserves: existing `charge_generation`, `refund_generation`, `topup`, `topup_user`, `poll_recharge_order`, and `redeem_code` return signatures.
- Adds: exact positive ledger rows for successful main-database refunds and all future main-database recharge paths.

- [ ] **Step 1: Add failing main-database query and ledger-write tests**

Extend `FakeMainDb` with `refund_generation` and update tests to assert:

```python
def test_maindb_topup_writes_traceable_positive_ledger(self):
    fake = FakeMainDb()
    with mock.patch.object(self.server, "maindb", fake), mock.patch.object(self.server, "maindb_on", return_value=True):
        ok, balance, err = self.server.topup_user(42, 5, "管理员充值", "admin-topup:test")
    self.assertTrue(ok)
    self.assertEqual(self.state["ledger"][-1]["delta"], 5.0)
    self.assertEqual(self.state["ledger"][-1]["balanceAfter"], 15.0)
    self.assertEqual(self.state["ledger"][-1]["ref"], "admin-topup:test")

def test_maindb_model_refund_writes_separate_positive_ledger(self):
    fake = FakeMainDb()
    fake.refund_generation = lambda ref, reason: (True, 3.0)
    with mock.patch.object(self.server, "maindb", fake), mock.patch.object(self.server, "maindb_on", return_value=True):
        ok, balance, amount, err = self.server.refund_user_by_ref(42, "video:req-1")
    self.assertTrue(ok)
    self.assertEqual((amount, self.state["ledger"][-1]["delta"]), (3.0, 3.0))
    self.assertEqual(self.state["ledger"][-1]["reason"], "退款:模型生成")
```

Add a direct `maindb` source test that patches `_q` and verifies the SQL is user-scoped, bounded by `[start_at, end_at)`, ordered, and requests one overflow row.

- [ ] **Step 2: Run the focused tests and observe failure**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_billing_unified -v
```

Expected: new tests FAIL because main-database topups/refunds do not append ledger rows and the list function does not exist.

- [ ] **Step 3: Implement the bounded model-usage query**

Add this query shape to `maindb.py`:

```python
def list_model_usage_logs(uid, start_at, end_at, limit=50001):
    safe_limit = max(1, min(int(limit), 50001))
    sql = (
        "SELECT id, request_id, user_id, project_id, task_id, model_id, model_type, "
        "billing_method, amount, balance_before, balance_after, status, description, "
        "created_at, refunded_at FROM model_usage_logs "
        "WHERE user_id=%s AND created_at >= %s AND created_at < %s "
        "ORDER BY created_at DESC, id DESC LIMIT %s"
    )
    return _q(sql, (int(uid), start_at, end_at, safe_limit))
```

Do not catch database errors here; the center server must distinguish a configured data-source failure from an empty result.

- [ ] **Step 4: Persist future main-database recharge/refund rows**

After successful `maindb.topup`, call `_add_ledger(user_id, amount, reason, ref, balance_after)` under `LOCK` and call `persist()`. Use stable refs:

- Admin topup: caller ref, else `"admin-topup:" + uuid.uuid4().hex`.
- WeChat: `"wxpay:" + order_no`.
- Redeem code: `"redeem:" + norm`.
- Model refund: original request ref and reason `退款:模型生成`.

Never append on failed database updates. Existing non-main-database paths remain unchanged. Repeated refund calls must not append a second row when `amount == 0`.

For WeChat and redeem-code main-database paths, check the concrete `ok, balance = maindb.topup(user_id, amount, reason)` return value before setting `credited=True` or marking a code `used`. A failed balance update must remain retryable and must not create a positive ledger row.

- [ ] **Step 5: Verify focused regressions**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_billing_unified -v
.\.venv-win\Scripts\python.exe -m py_compile backend\maindb.py backend\central_server.py tests\test_billing_unified.py
```

Expected: all billing-unified tests PASS and compilation exits 0. Update troubleshooting and exact implementation line references before any commit.

- [ ] **Step 6: Review checkpoint and optional commit**

Run `git diff --check`, inspect only Task 2 hunks, and commit after line-reference verification:

```powershell
git commit -m "feat: make billing balance changes traceable"
```

### Task 3: Authoritative Center-Server Analytics And Filtered Ledger APIs

**Files:**
- Modify: `backend/central_server.py:20-55`
- Modify: `backend/central_server.py:3039-3225`
- Modify: `backend/central_server.py:13880-13940`
- Create: `tests/test_billing_dashboard_api.py`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`

**Interfaces:**
- Produces: `collect_billing_records(user_id, period) -> tuple[list[dict], dict]` and `billing_dashboard_payload(user_id, params, analytics=False) -> dict`; metadata contains `sourceRows` and `deduplicatedRows`.
- Adds: `GET /api/billing/analytics`.
- Enhances: parameterized `GET /api/billing/ledger` while preserving the exact no-parameter response path.
- Enforces: runtime Draft 2020-12 validation for normalized query objects and successful API responses.

- [ ] **Step 1: Write failing service tests**

Cover these cases with patched `STATE`, `maindb`, `get_balance`, and `json_log`:

```python
def test_analytics_payload_uses_active_consumption_days(self):
    payload = server.billing_dashboard_payload(44, {"startDate": ["2026-07-01"], "endDate": ["2026-07-30"], "groupBy": ["day"]}, analytics=True)
    self.assertEqual(payload["metrics"]["activeConsumptionDays"], 2)
    self.assertEqual(payload["metrics"]["dailyAverage"], payload["metrics"]["totalConsumption"] / 2)

def test_parameterized_ledger_filters_and_paginates(self):
    payload = server.billing_dashboard_payload(44, {"status": ["refunded"], "page": ["1"], "pageSize": ["20"]}, analytics=False)
    self.assertTrue(all(row["status"] == "refunded" for row in payload["ledger"]))
    self.assertEqual(payload["pagination"]["pageSize"], 20)

def test_configured_maindb_failure_returns_error_not_partial_totals(self):
    with self.assertRaisesRegex(RuntimeError, "billing_data_source_failed"):
        server.collect_billing_records(44, period)

def test_central_load_dotenv_flag_can_disable_local_env_override(self):
    source = SERVER.read_text(encoding="utf-8")
    self.assertIn('CENTRAL_LOAD_DOTENV', source)
    self.assertIn('if load_dotenv and CENTRAL_LOAD_DOTENV:', source)
```

Add a source-contract test proving the old branch still executes when none of `startDate`, `endDate`, `type`, `status`, `page`, or `pageSize` is present.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_billing_dashboard_api -v
```

Expected: FAIL because service helpers and the analytics route are absent.

- [ ] **Step 3: Implement bounded collection and API payload helpers**

Before the existing dotenv calls, add an opt-out that defaults to current production behavior:

```python
CENTRAL_LOAD_DOTENV = os.getenv("CENTRAL_LOAD_DOTENV", "1").strip().lower() not in ("0", "false", "no", "off")
if load_dotenv and CENTRAL_LOAD_DOTENV:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(os.path.dirname(_HERE), ".env"), override=False)
    load_dotenv(os.path.join(_HERE, ".env"), override=True)
```

Remove the old unconditional `if load_dotenv:` block. With the variable unset, behavior is unchanged.

Snapshot state under `LOCK`, filtering by current user before copying. Query `maindb.list_model_usage_logs` only when main DB is enabled and the user ID is numeric. If 50,001 rows return, raise `billing_record_limit_exceeded` instead of calculating partial totals.

The parameterized helper must:

```python
period = parse_period(params)
records, meta = collect_billing_records(user_id, period)
if analytics:
    payload = dict(build_billing_analytics(records, get_balance(user_id), period), ok=True)
    return validate_billing_payload("analytics_response", payload)
filters = parse_ledger_filters(params)
payload = dict(build_billing_ledger(records, filters), ok=True, balance=get_balance(user_id))
return validate_billing_payload("ledger_response", payload)
```

Before parsing, collapse `parse_qs` list values into a scalar query object and validate it against `ANALYTICS_QUERY_SCHEMA` or `LEDGER_QUERY_SCHEMA`. Translate `jsonschema.ValidationError` to the same HTTP 400 shape as `BillingQueryError` without exposing the full schema object.

Only configured data-source failures are fatal; disabled main DB is a supported deployment mode.

- [ ] **Step 4: Add routes, validation errors, and structured logs**

For `/api/billing/analytics`, authenticate with `current_user(self)` and never accept a user ID parameter. Map `BillingQueryError` to HTTP 400 with `error`, `message`, and `errorId`. Map collection exceptions to HTTP 503 with `billing_data_source_failed`.

Emit `json_log` events containing only:

```python
json_log(logger, "billing_analytics_completed", level="info", matrixUserId=user_id, startDate=period["startDate"], endDate=period["endDate"], groupBy=period["groupBy"], sourceRows=meta["sourceRows"], deduplicatedRows=meta["deduplicatedRows"], elapsedMs=elapsed_ms)
```

Emit this completion event inside `billing_dashboard_payload`, where `user_id`, `period`, `meta`, and elapsed time are all in scope. Route handlers only map the returned payload to HTTP.

For the ledger route, retain the existing raw latest-100 response when no new query parameter is present. Use the normalized/paginated path otherwise.

- [ ] **Step 5: Verify API behavior and compatibility**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_billing_dashboard_api tests.test_billing_unified tests.test_structured_log -v
.\.venv-win\Scripts\python.exe -m py_compile backend\billing_analytics.py backend\maindb.py backend\central_server.py
```

Expected: all tests PASS. Confirm logged test payloads contain an error ID and no fixture secret values.

- [ ] **Step 6: Review checkpoint and optional commit**

Recalculate `central_server.py` references in `docs/IMPLEMENTATION.md`, run `git diff --check`, and commit only owned hunks:

```powershell
git commit -m "feat: expose authoritative billing dashboard APIs"
```

### Task 4: OpenAPI And API Documentation

**Files:**
- Modify: `docs/openapi.yaml:439-455`
- Modify: `docs/openapi.yaml:885-896`
- Modify: `docs/API_REFERENCE.md:604-617`
- Modify: `tests/test_openapi_contract.py:8-45`
- Modify: `docs/IMPLEMENTATION.md`

**Interfaces:**
- Adds schemas: `BillingAnalytics`, `BillingMetricSet`, `BillingTrendBucket`, `BillingDistributionItem`, `BillingLedgerRow`, and `BillingPagination`.
- Extends `BillingLedger` without removing `ok`, `ledger`, or `balance`.
- Keeps OpenAPI property names, required fields, enums, limits, and nullability aligned with the runtime schemas in `billing_analytics.py`.

- [ ] **Step 1: Write failing OpenAPI contract tests**

Add `/api/billing/analytics` and all schema names to existing required lists. Assert the analytics path declares `startDate`, `endDate`, and `groupBy`, and ledger declares all six query parameters. Assert enums and limits exactly, then validate representative success payloads with the runtime Draft 2020-12 schemas:

```python
self.assertIn("enum: [day, month]", analytics_contract)
self.assertIn("maximum: 100", ledger_contract)
self.assertIn("enum: [charged, refunded, recharged, failed]", ledger_contract)
self.assertIn("enum: [video, image, voice, other, recharge, refund]", ledger_contract)
validate_billing_payload("analytics_response", analytics_fixture)
validate_billing_payload("ledger_response", ledger_fixture)
```

- [ ] **Step 2: Run the contract test and verify failure**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v
```

Expected: FAIL because the new path and schemas are absent.

- [ ] **Step 3: Add strict OpenAPI schemas**

Document date parameters with `type: string`, `format: date`; page with `minimum: 1`; page size with `enum: [20, 50, 100]`. `BillingLedgerRow.balanceAfter` must be nullable for historical records that cannot be reconstructed accurately. `BillingMetricSet.balance` uses `oneOf` with numeric balance or exact `"inf"`. Declare 400, 401, and 503 error responses through `ErrorResponse`.

Do not remove `additionalProperties: true` from the top-level legacy ledger response; make the new nested row and analytics schemas explicit enough for contract validation.

- [ ] **Step 4: Update the API reference**

Document active-day averaging, refund expansion, recharge exclusions, 366-day limit, page-size choices, role scoping, data-source failure behavior, and legacy no-parameter compatibility.

- [ ] **Step 5: Verify documentation contract**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v
git diff --check -- docs/openapi.yaml docs/API_REFERENCE.md tests/test_openapi_contract.py
```

Expected: OpenAPI tests PASS and diff check exits 0.

- [ ] **Step 6: Review checkpoint and optional commit**

Recalculate new documentation references and commit only Task 4 hunks:

```powershell
git commit -m "docs: define billing dashboard API contract"
```

### Task 5: Native Account Center Dashboard

**Files:**
- Modify: `backend/matrix_native_client.py:15-35`
- Modify: `backend/matrix_native_client.py:3730-3775`
- Modify: `backend/matrix_native_client.py:24896-25276`
- Create: `tests/test_account_billing_dashboard.py`
- Create: `scripts/smoke_account_billing_ui.py`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`

**Interfaces:**
- Adds: `BillingTrendChart.set_series(items)`, `BillingDistributionBars.set_distribution(items)`, `_billing_amount(value)`, and `_billing_query(params)`.
- Changes: `AccountPage.load_analytics()`, parameterized `AccountPage.load_ledger(reset_page=False)`, and request-sequence-aware `_on` handlers.
- Preserves: `billing_box`, `phone_bind_panel`, and `admin_box` permission checks.

- [ ] **Step 1: Write failing source and Qt behavior tests**

The source-contract portion must assert the four exact metric labels, seven exact detail columns, date/group controls, page-size choices, and permission visibility calls. The Qt portion should instantiate widgets with `QT_QPA_PLATFORM=offscreen` and verify stable dimensions and data updates:

```python
def test_distribution_keeps_four_rows_at_zero(self):
    widget = client.BillingDistributionBars()
    widget.set_distribution([])
    self.assertEqual(widget.row_count(), 4)
    self.assertEqual(widget.values(), [0.0, 0.0, 0.0, 0.0])

def test_account_page_keeps_admin_controls_role_gated(self):
    source = CLIENT.read_text(encoding="utf-8")
    self.assertIn('self.billing_box.setVisible(product_role() == "platform_admin")', source)
    self.assertIn('self.phone_bind_panel.setVisible(product_role() == "platform_admin")', source)
    self.assertIn('self.admin_box.setVisible(False)', source)
```

Add a stale-response test by emitting analytics payload sequence 1 after sequence 2 and asserting sequence 1 does not overwrite labels.

- [ ] **Step 2: Run tests and observe failure**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv-win\Scripts\python.exe -m unittest tests.test_account_billing_dashboard -v
```

Expected: FAIL because widgets and controls do not exist.

- [ ] **Step 3: Implement lightweight chart widgets**

Add `urlencode` to the existing `urllib.parse` import. Implement:

```python
class BillingTrendChart(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self.setMinimumHeight(190)

    def set_series(self, items):
        self._items = [x for x in (items or []) if isinstance(x, dict)]
        self.update()


class BillingDistributionBars(QtWidgets.QWidget):
    ORDER = (("video", "视频生成", "#6366f1"), ("image", "图片生成", "#22c55e"), ("voice", "配音", "#f59e0b"), ("other", "其他", "#64748b"))
```

`paintEvent` must reserve fixed label, bar, amount, and percentage columns. Trend labels thin deterministically when there are more than 12 buckets; changing data must never change widget height.

- [ ] **Step 4: Rebuild AccountPage layout without changing permissions**

Place four compact metric panels first. Add global `QDateEdit` controls initialized to latest 30 days and a day/month `QButtonGroup`. Add the bar chart and four distribution rows. Add independent detail type/status/date filters, page-size combo, previous/next icon buttons, and seven columns; changing detail filters must not change the global metric period:

```python
["时间", "类型", "模型ID", "任务详情", "实扣/变动", "扣后余额", "状态"]
```

The Account Center source test must also assert that “折扣共节省” is absent and no fifth metric card is created.

Move existing administrator widgets below billing details under the existing permission-controlled containers. Do not expose them to enterprise or normal users.

- [ ] **Step 5: Implement async loading, stale-response protection, and errors**

Use independent monotonically increasing request IDs:

```python
self._analytics_seq += 1
seq = self._analytics_seq
query = _billing_query({
    "startDate": self.analytics_start.date().toString("yyyy-MM-dd"),
    "endDate": self.analytics_end.date().toString("yyyy-MM-dd"),
    "groupBy": self._group_by,
})
_c, payload = api("GET", "/api/billing/analytics?" + query)
BRIDGE.payload.emit("acct_analytics", {"seq": seq, "payload": payload or {}})
```

Ignore payloads whose sequence is not current. Preserve the last successful chart/table on error and display a retry message with `errorId`. Render analytics balance `"inf"` as “∞ 运营方”; render all other balance values numerically. Table rendering uses normalized fields, `—` for unknown historical `balanceAfter`, red for negative change, green for positive change, and tooltip text for truncated details.

- [ ] **Step 6: Add and run the offscreen UI smoke**

`scripts/smoke_account_billing_ui.py` must create a `QApplication`, instantiate only the dashboard widgets with fake payloads, render at 1280x900 and 1024x768, save PNGs under `.tmp-validation/account-billing/`, and assert:

- Both images are nonblank.
- Metric labels and table remain inside widget bounds.
- Four distribution rows remain visible.
- Administrator controls are hidden for enterprise and normal roles.

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv-win\Scripts\python.exe scripts\smoke_account_billing_ui.py
.\.venv-win\Scripts\python.exe -m unittest tests.test_account_billing_dashboard tests.test_role_permissions tests.test_native_billing_rates -v
.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py scripts\smoke_account_billing_ui.py
```

Expected: smoke prints `ok`, screenshots exist and are nonblank, all tests PASS, and compilation exits 0.

- [ ] **Step 7: Review checkpoint and optional commit**

Inspect both rendered images, recalculate all new client line references, run `git diff --check`, and commit only owned hunks:

```powershell
git commit -m "feat: redesign native account billing center"
```

### Task 6: Full Verification, Production Documentation, And Rollback Gate

**Files:**
- Create: `scripts/smoke_billing_performance.py`
- Create: `scripts/monitor_billing_rollout.py`
- Create: `tests/test_billing_rollout_guard.py`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`
- Modify: `migration.sql`

**Interfaces:**
- No new runtime interfaces.
- Produces final verification evidence, deployment steps, and an executable rollout rollback guard.

- [ ] **Step 1: Write failing performance/rollback guard tests**

Test `monitor_billing_rollout.evaluate_window(status_codes, threshold=0.01)` and `rollback_command(previous_tag)`:

```python
def test_more_than_one_percent_errors_requests_rollback(self):
    decision = rollout.evaluate_window([200] * 98 + [503] * 2, threshold=0.01)
    self.assertTrue(decision["rollback"])
    self.assertEqual(decision["errorRate"], 0.02)

def test_one_percent_does_not_cross_threshold(self):
    self.assertFalse(rollout.evaluate_window([200] * 99 + [503], threshold=0.01)["rollback"])

def test_dry_run_never_invokes_subprocess_and_logs_no_token(self):
    with mock.patch("subprocess.run") as run:
        result = rollout.execute_rollback("stable-previous", dry_run=True)
    run.assert_not_called()
    self.assertNotIn("BILLING_MONITOR_TOKEN", json.dumps(result))
```

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_billing_rollout_guard -v
```

Expected: FAIL because the rollout monitor does not exist.

- [ ] **Step 2: Implement local performance and rollout scripts**

`smoke_billing_performance.py` reads `BILLING_SMOKE_BASE_URL` and `BILLING_SMOKE_TOKEN`, sends 200 analytics requests through 20 workers, computes P95 from monotonic timings, and exits nonzero when P95 exceeds 800 ms or any response violates the runtime response schema. It must never print the token.

`monitor_billing_rollout.py` reads `BILLING_MONITOR_BASE_URL`, `BILLING_MONITOR_TOKEN`, and required `PREVIOUS_IMAGE_TAG`, samples a fixed 100-request window, and triggers only when `errorRate > 0.01`. The rollback subprocess must use an argument list, `shell=False`, and a copied environment where `IMAGE_TAG` equals the validated `PREVIOUS_IMAGE_TAG`, with this exact command:

```python
["docker", "compose", "-f", "docker-compose.prod.yml", "up", "-d", "--no-build", "matrix-central"]
```

Accept image tags only when they match `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`. `--dry-run` returns the decision and command as redacted JSON without running it.

- [ ] **Step 3: Update production documentation**

Document the flow `AccountPage -> /api/billing/analytics + parameterized /api/billing/ledger -> billing_analytics -> STATE + model_usage_logs + recharge sources`. Include:

- Environment mode distinctions (`dev`, `staging`, `prod`) and existing center-server configuration ownership.
- `CENTRAL_LOAD_DOTENV=0` is allowed only for isolated dev/staging smoke processes; production leaves it unset so existing `.env` loading remains unchanged.
- No new secrets or connection strings.
- Health check remains `/api/health`.
- P95 target 800 ms at 20 QPS for a normal 30-day account query.
- Runtime JSON Schema validation uses `jsonschema==4.23.0`; both local and deployment requirement files carry the same lock.
- 50,001-row hard guard and 366-day range guard.
- Previous stable center-server/client artifacts as rollback targets.
- Automatic rollback threshold: new billing endpoint error rate greater than 1%.
- Rollout monitor invocation, required environment variables, `--dry-run` rehearsal, and previous-image tag validation.
- `migration.sql` append-only no-op release note; no DDL/DML.

- [ ] **Step 4: Recalculate implementation line references**

Use current post-change line numbers for every new reference in `docs/IMPLEMENTATION.md`, in the required format such as:

```text
backend/billing_analytics.py#L1-L420
backend/maindb.py#L204-L310
backend/central_server.py#L3039-L3300
backend/matrix_native_client.py#L3730-L3850
```

Do not reuse these illustrative numbers. Recalculate actual ranges after formatting and before each commit.

- [ ] **Step 5: Run focused and broad tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_billing_analytics tests.test_billing_unified tests.test_billing_dashboard_api tests.test_openapi_contract tests.test_account_billing_dashboard tests.test_billing_rollout_guard tests.test_role_permissions tests.test_native_billing_rates tests.test_structured_log -v
.\.venv-win\Scripts\python.exe scripts\smoke_billing_dashboard.py
$env:QT_QPA_PLATFORM='offscreen'
.\.venv-win\Scripts\python.exe scripts\smoke_account_billing_ui.py
.\.venv-win\Scripts\python.exe -m py_compile backend\billing_analytics.py backend\maindb.py backend\central_server.py backend\matrix_native_client.py
.\.venv-win\Scripts\python.exe -c "from importlib.metadata import version; assert version('jsonschema') == '4.23.0'"
git diff --check
```

Expected: all focused tests PASS, both functional smoke tests print `ok`, rollout guard tests pass, compilation exits 0, and diff check reports no whitespace errors.

Also inspect `backend/Dockerfile` and `docker-compose.prod.yml`. The existing Dockerfile installs `backend/requirements.txt`, so verify that file contains `jsonschema==4.23.0`; verify `backend/requirements.deploy.txt` carries the same lock for host deployments. Confirm both Dockerfile and Compose retain the existing `/api/health` healthcheck. No container-topology change is required.

- [ ] **Step 6: Run a local authenticated API and performance smoke without production restart**

Start a separate center-server process on port 19080 with an isolated test state and test-only token. Keep the process handle and always stop it in `finally`:

```powershell
$env:CENTRAL_PORT='19080'
$env:CENTRAL_USER_TOKEN='billing-smoke-local-only'
$env:CENTRAL_DATA_DIR=(Join-Path (Get-Location) '.tmp-validation\billing-center-data')
$env:CENTRAL_LOAD_DOTENV='0'
New-Item -ItemType Directory -Force -Path $env:CENTRAL_DATA_DIR | Out-Null
$server = Start-Process -FilePath '.\.venv-win\Scripts\python.exe' -ArgumentList 'backend\central_server.py' -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2
$headers = @{Authorization='Bearer billing-smoke-local-only'}
try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:19080/api/health'
    Invoke-RestMethod -Headers $headers -Uri 'http://127.0.0.1:19080/api/billing/analytics?startDate=2026-07-01&endDate=2026-07-30&groupBy=day'
    Invoke-RestMethod -Headers $headers -Uri 'http://127.0.0.1:19080/api/billing/ledger?startDate=2026-07-01&endDate=2026-07-30&type=video&status=charged&page=1&pageSize=20'
    try {
        Invoke-WebRequest -Uri 'http://127.0.0.1:19080/api/billing/analytics' -ErrorAction Stop | Out-Null
        throw 'unauthenticated billing request unexpectedly succeeded'
    } catch {
        if ([int]$_.Exception.Response.StatusCode -ne 401) { throw }
    }
    try {
        Invoke-WebRequest -Headers $headers -Uri 'http://127.0.0.1:19080/api/billing/analytics?startDate=2025-07-29&endDate=2026-07-30' -ErrorAction Stop | Out-Null
        throw '367-day billing request unexpectedly succeeded'
    } catch {
        if ([int]$_.Exception.Response.StatusCode -ne 400) { throw }
    }
    $env:BILLING_SMOKE_BASE_URL='http://127.0.0.1:19080'
    $env:BILLING_SMOKE_TOKEN='billing-smoke-local-only'
    .\.venv-win\Scripts\python.exe scripts\smoke_billing_performance.py
} finally {
    Stop-Process -Id $server.Id -ErrorAction SilentlyContinue
}
```

The smoke validates these requests:

```text
GET /api/health
GET /api/billing/analytics?startDate=2026-07-01&endDate=2026-07-30&groupBy=day
GET /api/billing/ledger?startDate=2026-07-01&endDate=2026-07-30&type=video&status=charged&page=1&pageSize=20
```

Expected: health is 200; authenticated billing responses are 200 and match OpenAPI; unauthenticated requests are 401; 367-day requests are 400; no production service is stopped or restarted.

Expected: 200/200 valid responses, 20 workers, and P95 at or below 800 ms. Do not run this load check against production.

- [ ] **Step 7: Verify rollback readiness**

Record the current stable Git SHA or packaged client version and center-server artifact hash in `docs/DEPLOYMENT.md`. Verify rollback restores the prior center-server artifact and client package while the no-parameter ledger endpoint remains available. Do not deploy or restart either process in this task.

Run the guard in dry-run mode against a controlled failure fixture and confirm it selects the previous image without invoking Docker:

```powershell
$env:PREVIOUS_IMAGE_TAG='stable-previous'
.\.venv-win\Scripts\python.exe scripts\monitor_billing_rollout.py --dry-run --fixture-error-rate 0.02
```

Expected: redacted JSON contains `"rollback": true` and `"executed": false`.

- [ ] **Step 8: Final review and release commit**

Confirm staged files are only billing-dashboard implementation/test/documentation files, confirm `docs/IMPLEMENTATION.md` line references against current files, and commit only after owner approval:

```powershell
git commit -m "feat: add account center billing dashboard"
```

## Completion Criteria

- Fake-data Phase 0 smoke, unit tests, API tests, OpenAPI tests, native UI tests, offscreen screenshots, and compilation all pass.
- The center server is the only authority for billing calculations.
- Active-day daily average, refund/recharge exclusions, four categories, and distinct-video average match the approved design.
- Detail records support the confirmed filters, statuses, page sizes, and two-row refund trace.
- Existing administrator-only controls remain hidden from enterprise and normal users.
- OpenAPI, API reference, architecture, deployment, troubleshooting, implementation line references, changelog, and no-op migration note are current.
- No local-client restart, center-server restart, production deployment, or remote comic-service modification has occurred.
