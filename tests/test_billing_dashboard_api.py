import importlib.util
import io
import json
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from jsonschema import ValidationError


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SERVER = BACKEND / "central_server.py"
NEW_LEDGER_PARAMS = ("startDate", "endDate", "type", "status", "page", "pageSize")

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_server_module():
    sys.modules.setdefault(
        "loguru",
        types.SimpleNamespace(logger=types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
            exception=lambda *args, **kwargs: None,
        )),
    )
    spec = importlib.util.spec_from_file_location("central_server_dashboard_under_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, {"CENTRAL_LOAD_DOTENV": "0"}):
        spec.loader.exec_module(module)
    return module


def cn_timestamp(day, hour=12):
    return datetime.fromisoformat(day).replace(
        hour=hour, tzinfo=timezone(timedelta(hours=8))
    ).timestamp()


class FakeMainDb:
    def __init__(self, rows=None, error=None, configured=True, configured_error=None):
        self.rows = list(rows or [])
        self.error = error
        self.configured_value = configured
        self.configured_error = configured_error
        self.calls = []

    def configured(self):
        if self.configured_error:
            raise self.configured_error
        return self.configured_value

    def list_model_usage_logs(self, user_id, start_at, end_at, limit=50001):
        self.calls.append((user_id, start_at, end_at, limit))
        if self.error:
            raise self.error
        return self.rows


class FakeLogger:
    def __init__(self):
        self.rows = []

    def info(self, value):
        self.rows.append(value)

    def error(self, value):
        self.rows.append(value)


class FakeHttpHandler:
    def __init__(self, path):
        self.path = path
        self.headers = {}
        self.wfile = io.BytesIO()
        self.status = None
        self.response_headers = []
        self.headers_ended = False

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.response_headers.append((name, value))

    def end_headers(self):
        self.headers_ended = True


class BillingDashboardApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = load_server_module()

    def setUp(self):
        self.state = {
            "ledger": [
                {
                    "id": "charge-video",
                    "userId": 44,
                    "delta": -12,
                    "balanceAfter": 88,
                    "reason": "video generation",
                    "ref": "video:req-1",
                    "ts": cn_timestamp("2026-07-02"),
                },
                {
                    "id": "charge-image",
                    "userId": 44,
                    "delta": -8,
                    "balanceAfter": 80,
                    "reason": "image generation",
                    "ref": "image:req-2",
                    "ts": cn_timestamp("2026-07-03"),
                },
                {
                    "id": "refund-video",
                    "userId": 44,
                    "delta": 12,
                    "balanceAfter": 92,
                    "reason": "refund: video generation",
                    "ref": "video:req-1",
                    "ts": cn_timestamp("2026-07-04"),
                },
                {
                    "id": "other-user",
                    "userId": 99,
                    "delta": -999,
                    "balanceAfter": 0,
                    "reason": "video generation",
                    "ref": "video:secret-fixture",
                    "ts": cn_timestamp("2026-07-02"),
                },
            ],
            "recharge_orders": [],
            "redeem_codes": [],
        }
        self.state_patch = mock.patch.object(self.server, "STATE", self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def dashboard_patches(self, *, maindb=None, enabled=False):
        return (
            mock.patch.object(self.server, "maindb", maindb),
            mock.patch.object(self.server, "maindb_on", return_value=enabled),
            mock.patch.object(self.server, "get_balance", return_value=92.0),
            mock.patch.object(self.server, "json_log", return_value='{"errorId":"err-complete"}'),
        )

    def test_analytics_payload_uses_active_consumption_days(self):
        patches = self.dashboard_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            payload = self.server.billing_dashboard_payload(
                44,
                {
                    "startDate": ["2026-07-01"],
                    "endDate": ["2026-07-30"],
                    "groupBy": ["day"],
                },
                analytics=True,
            )

        self.assertEqual(payload["metrics"]["activeConsumptionDays"], 2)
        self.assertEqual(
            payload["metrics"]["dailyAverage"],
            payload["metrics"]["totalConsumption"] / 2,
        )

    def test_parameterized_ledger_filters_and_paginates(self):
        patches = self.dashboard_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            payload = self.server.billing_dashboard_payload(
                44,
                {"status": ["refunded"], "page": ["1"], "pageSize": ["20"]},
                analytics=False,
            )

        self.assertTrue(payload["ledger"])
        self.assertTrue(all(row["status"] == "refunded" for row in payload["ledger"]))
        self.assertEqual(payload["pagination"]["pageSize"], 20)

    def test_collection_filters_state_by_current_user_and_reports_counts(self):
        patches = self.dashboard_patches()
        period = self.server.parse_period({"startDate": "2026-07-01", "endDate": "2026-07-30"})
        with patches[0], patches[1], patches[2], patches[3]:
            records, meta = self.server.collect_billing_records(44, period)

        self.assertEqual(meta, {"sourceRows": 3, "deduplicatedRows": 3})
        self.assertNotIn("secret-fixture", json.dumps(records, default=str))

    def test_configured_maindb_failure_returns_error_not_partial_totals(self):
        fake = FakeMainDb(error=RuntimeError("database secret-fixture unavailable"))
        period = self.server.parse_period({"startDate": "2026-07-01", "endDate": "2026-07-30"})

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "billing_data_source_failed"):
                self.server.collect_billing_records(44, period)

    def test_absent_or_unconfigured_maindb_is_supported_without_querying_it(self):
        period = self.server.parse_period({"startDate": "2026-07-01", "endDate": "2026-07-30"})
        unconfigured = FakeMainDb(
            error=AssertionError("unconfigured source must not be queried"), configured=False
        )

        with self.subTest("absent"):
            with mock.patch.object(self.server, "maindb", None), \
                    mock.patch.object(self.server, "maindb_on", return_value=False):
                records, meta = self.server.collect_billing_records(44, period)

            self.assertEqual((len(records), meta["sourceRows"]), (3, 3))

        with self.subTest("unconfigured"):
            with mock.patch.object(self.server, "maindb", unconfigured), \
                    mock.patch.object(self.server, "maindb_on", return_value=False):
                records, meta = self.server.collect_billing_records(44, period)

            self.assertEqual(unconfigured.calls, [])
            self.assertEqual((len(records), meta["sourceRows"]), (3, 3))

    def test_configured_but_unavailable_maindb_is_fatal_before_local_totals(self):
        fake = FakeMainDb(error=AssertionError("disabled source must not be queried"))
        period = self.server.parse_period({"startDate": "2026-07-01", "endDate": "2026-07-30"})

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "billing_data_source_failed"):
                self.server.collect_billing_records(44, period)

        self.assertEqual(fake.calls, [])

    def test_configured_maindb_check_failure_is_fatal(self):
        fake = FakeMainDb(configured_error=RuntimeError("configuration unavailable"))
        period = self.server.parse_period({"startDate": "2026-07-01", "endDate": "2026-07-30"})

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "billing_data_source_failed"):
                self.server.collect_billing_records(44, period)

        self.assertEqual(fake.calls, [])

    def test_50001_maindb_rows_are_an_error_not_partial_totals(self):
        fake = FakeMainDb(rows=[{}] * 50001)
        period = self.server.parse_period({"startDate": "2026-07-01", "endDate": "2026-07-30"})

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "billing_record_limit_exceeded"):
                self.server.collect_billing_records(44, period)

        self.assertEqual(fake.calls[0][-1], 50001)

    def test_normalized_query_is_strictly_validated(self):
        patches = self.dashboard_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            with self.assertRaises(ValidationError):
                self.server.billing_dashboard_payload(
                    44, {"page": ["1"], "pageSize": ["25"]}, analytics=False
                )
            with self.assertRaises(ValidationError):
                self.server.billing_dashboard_payload(
                    44, {"startDate": ["2026-07-01"], "userId": ["99"]}, analytics=True
                )

    def test_successful_response_is_runtime_schema_validated(self):
        patches = self.dashboard_patches()
        with patches[0], patches[1], patches[2], patches[3], \
                mock.patch.object(
                    self.server,
                    "validate_billing_payload",
                    wraps=self.server.validate_billing_payload,
                ) as validate:
            self.server.billing_dashboard_payload(
                44,
                {"startDate": ["2026-07-01"], "endDate": ["2026-07-30"]},
                analytics=True,
            )

        self.assertEqual(validate.call_args_list[0].args[0], "analytics_query")
        self.assertEqual(validate.call_args_list[-1].args[0], "analytics_response")

    def test_completion_log_has_only_the_allowed_non_secret_context(self):
        fake_log = mock.Mock(return_value='{"errorId":"err-complete"}')
        with mock.patch.object(self.server, "maindb", None), \
                mock.patch.object(self.server, "maindb_on", return_value=False), \
                mock.patch.object(self.server, "get_balance", return_value=92.0), \
                mock.patch.object(self.server, "json_log", fake_log):
            self.server.billing_dashboard_payload(
                44,
                {
                    "startDate": ["2026-07-01"],
                    "endDate": ["2026-07-30"],
                    "groupBy": ["day"],
                },
                analytics=True,
            )

        args, kwargs = fake_log.call_args
        self.assertIs(args[0], self.server.logger)
        self.assertEqual(args[1], "billing_analytics_completed")
        self.assertEqual(
            set(kwargs),
            {
                "level", "matrixUserId", "startDate", "endDate", "groupBy",
                "sourceRows", "deduplicatedRows", "elapsedMs",
            },
        )
        self.assertEqual(kwargs["matrixUserId"], 44)
        self.assertNotIn("secret-fixture", json.dumps(kwargs))

    def invoke_get(self, path, *, user=None, payload=None, error=None):
        handler = types.SimpleNamespace(path=path)
        responses = []
        helper = mock.Mock(side_effect=error) if error else mock.Mock(return_value=payload or {"ok": True})
        with mock.patch.object(self.server, "require_user", return_value=True), \
                mock.patch.object(self.server, "current_user", return_value=user or {"id": 44}), \
                mock.patch.object(self.server, "billing_dashboard_payload", helper), \
                mock.patch.object(
                    self.server,
                    "json_response",
                    side_effect=lambda _handler, body, status=200: responses.append((body, status)),
                ), \
                mock.patch.object(
                    self.server,
                    "json_log",
                    return_value=json.dumps({"ok": True}),
                ) as logged:
            self.server.Handler.do_GET(handler)
        return responses, helper, logged

    def test_analytics_route_authenticates_from_current_user_only(self):
        payload = {"ok": True, "metrics": {}}
        responses, helper, _logged = self.invoke_get(
            "/api/billing/analytics?startDate=2026-07-01", payload=payload
        )

        self.assertEqual(responses, [(payload, 200)])
        self.assertEqual(helper.call_args.args[0], 44)
        self.assertEqual(helper.call_args.args[1], {"startDate": ["2026-07-01"]})
        self.assertTrue(helper.call_args.kwargs["analytics"])

    def test_query_and_schema_errors_map_to_redacted_400_response(self):
        error = self.server.BillingQueryError("invalid_date", "invalid date")
        responses, _helper, logged = self.invoke_get(
            "/api/billing/analytics?startDate=bad&userId=secret-fixture",
            error=error,
        )

        self.assertEqual(responses[0][1], 400)
        self.assertEqual(responses[0][0]["error"], "invalid_date")
        self.assertEqual(responses[0][0]["message"], "invalid date")
        self.assertTrue(responses[0][0]["errorId"].startswith("err-"))
        logged_kwargs = logged.call_args.kwargs
        self.assertEqual(logged_kwargs["errorId"], responses[0][0]["errorId"])
        self.assertNotIn("secret-fixture", json.dumps(logged_kwargs, default=str))

    def test_schema_error_response_does_not_expose_schema(self):
        try:
            self.server.validate_billing_payload(
                "analytics_query", {"userId": "secret-fixture"}
            )
        except ValidationError as error:
            schema_error = error
        responses, _helper, _logged = self.invoke_get(
            "/api/billing/analytics?userId=secret-fixture", error=schema_error
        )

        self.assertEqual(responses[0][1], 400)
        self.assertEqual(responses[0][0]["error"], "invalid_billing_query")
        self.assertEqual(
            responses[0][0]["errorId"], _logged.call_args.kwargs["errorId"]
        )
        self.assertNotIn("schema", json.dumps(responses[0][0]).lower())
        self.assertNotIn("secret-fixture", json.dumps(responses[0][0]))
        self.assertNotIn(
            "secret-fixture", json.dumps(_logged.call_args.kwargs, default=str)
        )

    def test_server_generated_response_schema_failure_maps_to_internal_500(self):
        handler = types.SimpleNamespace(
            path="/api/billing/analytics?startDate=2026-07-01&endDate=2026-07-30"
        )
        responses = []
        fake_logger = FakeLogger()
        invalid_server_payload = {"internalValue": "secret-fixture"}

        with mock.patch.object(self.server, "require_user", return_value=True), \
                mock.patch.object(self.server, "current_user", return_value={"id": 44}), \
                mock.patch.object(self.server, "maindb_on", return_value=False), \
                mock.patch.object(self.server, "get_balance", return_value=92.0), \
                mock.patch.object(
                    self.server,
                    "build_billing_analytics",
                    return_value=invalid_server_payload,
                ), \
                mock.patch.object(self.server, "logger", fake_logger), \
                mock.patch.object(
                    self.server,
                    "json_response",
                    side_effect=lambda _handler, body, status=200: responses.append((body, status)),
                ):
            self.server.Handler.do_GET(handler)

        payload, status = responses[0]
        logged = json.loads(fake_logger.rows[0])
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], "internal_billing_response_error")
        self.assertNotEqual(payload["error"], "invalid_billing_query")
        self.assertEqual(logged["event"], "billing_response_invalid")
        self.assertEqual(logged["errorId"], payload["errorId"])
        self.assertIn("stack", logged)
        self.assertNotIn("secret-fixture", json.dumps(payload))
        self.assertNotIn("secret-fixture", fake_logger.rows[0])

    def test_collection_failure_maps_to_503_without_partial_payload(self):
        error = RuntimeError("billing_data_source_failed: secret-fixture")
        responses, _helper, logged = self.invoke_get(
            "/api/billing/ledger?page=1", error=error
        )

        self.assertEqual(responses[0][1], 503)
        self.assertEqual(responses[0][0]["error"], "billing_data_source_failed")
        self.assertTrue(responses[0][0]["errorId"].startswith("err-"))
        self.assertEqual(
            responses[0][0]["errorId"], logged.call_args.kwargs["errorId"]
        )
        self.assertNotIn("secret-fixture", json.dumps(responses[0][0]))
        self.assertNotIn("secret-fixture", json.dumps(logged.call_args.kwargs, default=str))

    def test_configured_unavailable_maindb_route_returns_503_without_local_payload(self):
        handler = types.SimpleNamespace(
            path="/api/billing/analytics?startDate=2026-07-01&endDate=2026-07-30"
        )
        fake = FakeMainDb(error=AssertionError("unavailable source must not be queried"))
        responses = []

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=False), \
                mock.patch.object(self.server, "require_user", return_value=True), \
                mock.patch.object(self.server, "current_user", return_value={"id": 44}), \
                mock.patch.object(
                    self.server,
                    "json_response",
                    side_effect=lambda _handler, body, status=200: responses.append((body, status)),
                ):
            self.server.Handler.do_GET(handler)

        self.assertEqual(responses, [(
            mock.ANY,
            503,
        )])
        self.assertEqual(responses[0][0]["error"], "billing_data_source_failed")
        self.assertNotIn("metrics", responses[0][0])
        self.assertEqual(fake.calls, [])

    def test_error_log_is_json_with_matching_error_id_and_no_fixture_secret(self):
        fake_logger = FakeLogger()
        with mock.patch.object(self.server, "logger", fake_logger):
            payload, status = self.server._billing_api_error(
                44, RuntimeError("Bearer secret-fixture-token")
            )

        logged = json.loads(fake_logger.rows[0])
        self.assertEqual(status, 503)
        self.assertEqual(logged["errorId"], payload["errorId"])
        self.assertIn("stack", logged)
        self.assertNotIn("secret-fixture", fake_logger.rows[0])

    def test_default_dotenv_loading_preserves_paths_order_and_overrides(self):
        loader = mock.Mock()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CENTRAL_LOAD_DOTENV", None)
            self.server._load_central_dotenv(loader)

        self.assertEqual(
            loader.call_args_list,
            [
                mock.call(str(ROOT / ".env"), override=False),
                mock.call(str(BACKEND / ".env"), override=True),
            ],
        )

    def test_central_load_dotenv_zero_skips_both_files(self):
        loader = mock.Mock()
        with mock.patch.dict(os.environ, {"CENTRAL_LOAD_DOTENV": "0"}):
            self.server._load_central_dotenv(loader)

        loader.assert_not_called()

    def test_legacy_ledger_branch_remains_for_requests_without_new_params(self):
        source = SERVER.read_text(encoding="utf-8")
        route_start = source.index('if path == "/api/billing/ledger":')
        route_end = source.index('if path == "/api/billing/recharge/packages":', route_start)
        route = source[route_start:route_end]

        self.assertTrue(all(name in route for name in NEW_LEDGER_PARAMS))
        self.assertIn('STATE.get("ledger")', route)
        self.assertIn("list(reversed(rows))[:100]", route)
        self.assertIn('{"ok": True, "ledger": rows, "balance": get_balance(u.get("id"))}', route)

    def test_legacy_ledger_route_emits_compatible_bytes_status_and_latest_100(self):
        legacy_rows = [
            {
                "id": f"legacy-{index}",
                "userId": 44,
                "delta": -index,
                "reason": "视频生成",
            }
            for index in range(105)
        ]
        route_state = dict(
            self.state,
            ledger=legacy_rows + [{"id": "other-user", "userId": 99}],
        )
        handler = FakeHttpHandler("/api/billing/ledger?unrelated=value")
        helper = mock.Mock(side_effect=AssertionError("legacy route must bypass helper"))

        with mock.patch.object(self.server, "STATE", route_state), \
                mock.patch.object(self.server, "require_user", return_value=True), \
                mock.patch.object(self.server, "current_user", return_value={"id": 44}), \
                mock.patch.object(self.server, "get_balance", return_value=92.0), \
                mock.patch.object(self.server, "billing_dashboard_payload", helper):
            self.server.Handler.do_GET(handler)

        expected = {
            "ok": True,
            "ledger": list(reversed(legacy_rows))[:100],
            "balance": 92.0,
        }
        expected_bytes = json.dumps(expected, ensure_ascii=False).encode("utf-8")
        actual_payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual((handler.wfile.getvalue(), handler.status), (expected_bytes, 200))
        self.assertEqual(list(actual_payload), ["ok", "ledger", "balance"])
        self.assertEqual(len(actual_payload["ledger"]), 100)
        self.assertEqual(
            [row["id"] for row in actual_payload["ledger"]],
            [f"legacy-{index}" for index in range(104, 4, -1)],
        )
        self.assertTrue(handler.headers_ended)
        helper.assert_not_called()


if __name__ == "__main__":
    unittest.main()
