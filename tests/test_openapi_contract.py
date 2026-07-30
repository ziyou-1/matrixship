from pathlib import Path
import sys
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "docs" / "openapi.yaml"
BACKEND = ROOT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from billing_analytics import (
    ANALYTICS_RESPONSE_SCHEMA,
    LEDGER_RESPONSE_SCHEMA,
    validate_billing_payload,
)


class OpenApiContractTest(unittest.TestCase):
    def resolve_openapi_schema(self, document, schema):
        if isinstance(schema, list):
            return [self.resolve_openapi_schema(document, item) for item in schema]
        if not isinstance(schema, dict):
            return schema
        if "$ref" in schema:
            self.assertEqual(set(schema), {"$ref"})
            name = schema["$ref"].removeprefix("#/components/schemas/")
            self.assertIn(name, document["components"]["schemas"])
            return self.resolve_openapi_schema(
                document, document["components"]["schemas"][name]
            )
        resolved = {
            key: self.resolve_openapi_schema(document, value)
            for key, value in schema.items()
        }
        # OpenAPI 3.0 nullable is not a JSON Schema keyword. Translate only it
        # when a legacy component still uses that representation.
        if resolved.pop("nullable", False):
            if "type" in resolved:
                value_type = resolved["type"]
                resolved["type"] = (
                    [*value_type, "null"]
                    if isinstance(value_type, list)
                    else [value_type, "null"]
                )
            else:
                resolved = {"anyOf": [resolved, {"type": "null"}]}
        return resolved

    def assert_runtime_schema_surface_matches_openapi(self, runtime, openapi):
        for key in ("required", "additionalProperties"):
            self.assertEqual(openapi.get(key), runtime.get(key), key)
        self.assertEqual(set(openapi["properties"]), set(runtime["properties"]))
        for name, runtime_property in runtime["properties"].items():
            openapi_property = openapi["properties"][name]
            for key in ("type", "enum", "const", "oneOf", "minimum"):
                if key in runtime_property:
                    self.assertEqual(
                        openapi_property.get(key), runtime_property[key],
                        "%s.%s" % (name, key),
                    )

    def test_openapi_covers_production_observability_and_billing_paths(self):
        text = OPENAPI.read_text(encoding="utf-8")

        required_paths = (
            "/api/account/balance",
            "/api/billing/analytics",
            "/api/billing/ledger",
            "/api/billing/charge",
            "/api/billing/refund",
            "/api/local-browser/status",
            "/api/local-browser/task",
            "/api/douyin/dm/inbox",
            "/api/central/nodes",
            "/api/enterprise/task-center",
            "/api/enterprise/invites/create",
            "/api/enterprise/invites/verify",
            "/api/enterprise/invites/accept",
        )

        for path in required_paths:
            with self.subTest(path=path):
                self.assertIn(f"  {path}:", text)

        for schema_name in (
            "AccountBalance",
            "BillingAnalytics",
            "BillingMetricSet",
            "BillingTrendBucket",
            "BillingDistributionItem",
            "BillingLedgerRow",
            "BillingPagination",
            "LegacyBillingLedgerResponse",
            "BillingLedgerResponse",
            "BillingChargeRequest",
            "BillingChargeResponse",
            "BillingRefundRequest",
            "BillingRefundResponse",
            "LocalBrowserStatus",
            "LocalBrowserTask",
            "DouyinDmInboxRequest",
            "DouyinDmInboxMessage",
            "DouyinDmInboxResponse",
            "CentralNodes",
            "EnterpriseTaskCenter",
            "EnterpriseInviteCreateRequest",
            "EnterpriseInviteCreateResponse",
            "EnterpriseInviteVerifyRequest",
            "EnterpriseInviteVerifyResponse",
            "EnterpriseInviteAcceptRequest",
            "EnterpriseInviteAcceptResponse",
        ):
            with self.subTest(schema=schema_name):
                self.assertIn(f"    {schema_name}:", text)

    def test_douyin_dm_inbox_accepts_optional_account_id(self):
        text = OPENAPI.read_text(encoding="utf-8")
        start = text.index("    DouyinDmInboxRequest:")
        end = text.index("    DouyinDmInboxMessage:", start)
        block = text[start:end]
        self.assertIn("        accountId:", block)
        self.assertIn("Account matrix ID", block)
        self.assertNotIn("required: [target, accountId]", block)

    def test_billing_dashboard_openapi_matches_runtime_query_and_response_contracts(self):
        text = OPENAPI.read_text(encoding="utf-8")
        document = yaml.safe_load(text)
        self.assertEqual(document["openapi"], "3.1.0")

        analytics_contract = text[
            text.index("  /api/billing/analytics:"):text.index("  /api/billing/charge:")
        ]
        ledger_contract = text[
            text.index("  /api/billing/ledger:"):text.index("  /api/billing/charge:")
        ]
        self.assertIn("enum: [day, month]", analytics_contract)
        self.assertIn("maximum: 100", ledger_contract)
        self.assertIn("enum: [charged, refunded, recharged, failed]", ledger_contract)
        self.assertIn("enum: [video, image, voice, other, recharge, refund]", ledger_contract)

        analytics = document["paths"]["/api/billing/analytics"]["get"]
        ledger = document["paths"]["/api/billing/ledger"]["get"]
        self.assertEqual(analytics["security"], [{"bearerAuth": []}])
        self.assertEqual(ledger["security"], [{"bearerAuth": []}])
        self.assertEqual(set(analytics["responses"]), {"200", "400", "401", "500", "503"})
        self.assertEqual(set(ledger["responses"]), {"200", "400", "401", "500", "503"})
        for operation in (analytics, ledger):
            for status in ("400", "401", "500", "503"):
                with self.subTest(operation=operation["summary"], status=status):
                    self.assertEqual(
                        operation["responses"][status]["content"]["application/json"]["schema"],
                        {"$ref": "#/components/schemas/ErrorResponse"},
                    )

        analytics_parameters = {item["name"]: item["schema"] for item in analytics["parameters"]}
        self.assertEqual(set(analytics_parameters), {"startDate", "endDate", "groupBy"})
        self.assertEqual(analytics_parameters["startDate"], {"type": "string", "format": "date"})
        self.assertEqual(analytics_parameters["endDate"], {"type": "string", "format": "date"})
        self.assertEqual(analytics_parameters["groupBy"], {"type": "string", "enum": ["day", "month"], "default": "day"})

        ledger_parameters = {item["name"]: item["schema"] for item in ledger["parameters"]}
        self.assertEqual(set(ledger_parameters), {"startDate", "endDate", "type", "status", "page", "pageSize"})
        self.assertEqual(ledger_parameters["startDate"], {"type": "string", "format": "date"})
        self.assertEqual(ledger_parameters["endDate"], {"type": "string", "format": "date"})
        self.assertEqual(ledger_parameters["type"], {"type": "string", "enum": ["video", "image", "voice", "other", "recharge", "refund"]})
        self.assertEqual(ledger_parameters["status"], {"type": "string", "enum": ["charged", "refunded", "recharged", "failed"]})
        self.assertEqual(ledger_parameters["page"], {"type": "integer", "minimum": 1, "default": 1})
        self.assertEqual(ledger_parameters["pageSize"], {"type": "integer", "enum": [20, 50, 100], "maximum": 100, "default": 20})

        schemas = document["components"]["schemas"]
        self.assertEqual(schemas["BillingMetricSet"]["properties"]["balance"], {"oneOf": [{"type": "number"}, {"const": "inf"}]})
        self.assertEqual(schemas["BillingLedgerRow"]["properties"]["balanceAfter"], {"type": ["number", "null"]})
        ledger_response_schema = ledger["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(
            ledger_response_schema,
            {
                "oneOf": [
                    {"$ref": "#/components/schemas/LegacyBillingLedgerResponse"},
                    {"$ref": "#/components/schemas/BillingLedgerResponse"},
                ]
            },
        )
        self.assertIn("recognized dashboard parameter", ledger["description"])
        self.assertNotIn("any query parameter enables", ledger["description"])

        analytics_openapi_schema = self.resolve_openapi_schema(
            document,
            analytics["responses"]["200"]["content"]["application/json"]["schema"],
        )
        strict_ledger_openapi_schema = self.resolve_openapi_schema(
            document, {"$ref": "#/components/schemas/BillingLedgerResponse"}
        )
        legacy_ledger_openapi_schema = self.resolve_openapi_schema(
            document, {"$ref": "#/components/schemas/LegacyBillingLedgerResponse"}
        )
        self.assert_runtime_schema_surface_matches_openapi(
            ANALYTICS_RESPONSE_SCHEMA, analytics_openapi_schema
        )
        for name in ("period", "metrics"):
            self.assert_runtime_schema_surface_matches_openapi(
                ANALYTICS_RESPONSE_SCHEMA["properties"][name],
                analytics_openapi_schema["properties"][name],
            )
        for name in ("trend", "distribution"):
            self.assert_runtime_schema_surface_matches_openapi(
                ANALYTICS_RESPONSE_SCHEMA["properties"][name]["items"],
                analytics_openapi_schema["properties"][name]["items"],
            )
        self.assert_runtime_schema_surface_matches_openapi(
            LEDGER_RESPONSE_SCHEMA, strict_ledger_openapi_schema
        )
        self.assert_runtime_schema_surface_matches_openapi(
            LEDGER_RESPONSE_SCHEMA["properties"]["ledger"]["items"],
            strict_ledger_openapi_schema["properties"]["ledger"]["items"],
        )
        self.assert_runtime_schema_surface_matches_openapi(
            LEDGER_RESPONSE_SCHEMA["properties"]["pagination"],
            strict_ledger_openapi_schema["properties"]["pagination"],
        )
        self.assertTrue(legacy_ledger_openapi_schema["additionalProperties"])
        self.assertEqual(legacy_ledger_openapi_schema["required"], ["ok", "balance", "ledger"])
        self.assertEqual(legacy_ledger_openapi_schema["properties"]["ledger"]["items"], {})

        analytics_fixture = {
            "ok": True,
            "period": {"startDate": "2026-07-01", "endDate": "2026-07-30", "groupBy": "day", "timezone": "Asia/Shanghai"},
            "metrics": {"balance": "inf", "totalConsumption": 12.5, "activeConsumptionDays": 2, "dailyAverage": 6.25, "videoTaskCount": 1, "videoAverage": 8.0},
            "trend": [{"bucket": "2026-07-01", "amount": 8.0}],
            "distribution": [{"type": "video", "label": "video", "amount": 8.0, "ratio": 64.0}],
        }
        ledger_fixture = {
            "ok": True,
            "balance": 12.5,
            "ledger": [{"id": "legacy-1", "createdAt": "2026-07-30T12:00:00+08:00", "timestamp": 1785384000.0, "type": "refund", "typeLabel": "refund", "modelId": "", "taskId": "", "requestId": "", "detail": "historical record", "change": 2.0, "balanceAfter": None, "status": "refunded", "statusLabel": "refunded"}],
            "pagination": {"page": 1, "pageSize": 20, "total": 1, "totalPages": 1},
        }
        validate_billing_payload("analytics_response", analytics_fixture)
        validate_billing_payload("ledger_response", ledger_fixture)
        legacy_ledger_fixture = {
            "ok": True,
            "balance": 12.5,
            "ledger": [{"historicalColumn": {"unstructured": True}, "oldState": "done"}],
        }

        from jsonschema import Draft202012Validator

        Draft202012Validator(analytics_openapi_schema).validate(analytics_fixture)
        Draft202012Validator(strict_ledger_openapi_schema).validate(ledger_fixture)
        Draft202012Validator(legacy_ledger_openapi_schema).validate(legacy_ledger_fixture)
        Draft202012Validator(
            self.resolve_openapi_schema(document, ledger_response_schema)
        ).validate(ledger_fixture)
        Draft202012Validator(
            self.resolve_openapi_schema(document, ledger_response_schema)
        ).validate(legacy_ledger_fixture)

    def test_enterprise_invite_openapi_accepts_name_password_only(self):
        text = OPENAPI.read_text(encoding="utf-8")
        start = text.index("    EnterpriseInviteAcceptRequest:")
        end = text.index("    EnterpriseInviteAcceptResponse:", start)
        request_schema = text[start:end]

        self.assertIn("required: [token, name, password]", request_schema)
        self.assertNotIn("phone:", request_schema)
        self.assertNotIn("email:", request_schema)

    def test_comic_generate_image_openapi_limits_frame_index_to_start_or_end(self):
        text = OPENAPI.read_text(encoding="utf-8")
        path_start = text.index("  /api/v1/comic-drama/storyboards/{storyboard_id}/generate-image:")
        path_end = text.index("\n  /", path_start + 3)
        contract = text[path_start:path_end]
        request_start = text.index("    ComicStoryboardImageGenerateRequest:")
        request_end = text.index("    ComicStoryboardImageGenerateResponse:", request_start)
        request_schema = text[request_start:request_end]
        response_start = request_end
        response_end = text.index("    ComicStoryboardImageValidationError:", response_start)
        response_schema = text[response_start:response_end]
        error_start = text.index("    ComicStoryboardImageValidationError:")
        error_end = text.index("    AccountBalance:", error_start)
        error_schema = text[error_start:error_end]

        self.assertEqual(
            text.count("  /api/v1/comic-drama/storyboards/{storyboard_id}/generate-image:"),
            1,
        )
        for schema_name in (
                "ComicStoryboardImageGenerateRequest",
                "ComicStoryboardImageGenerateResponse",
                "ComicStoryboardImageValidationError",
        ):
            with self.subTest(schema=schema_name):
                self.assertEqual(text.count("    %s:" % schema_name), 1)
        self.assertIn('$ref: "#/components/schemas/ComicStoryboardImageGenerateRequest"', contract)
        self.assertIn("frameIndex:", request_schema)
        self.assertIn("frame_index:", request_schema)
        self.assertIn("enum: [1, 2]", request_schema)
        self.assertIn("enum: [action_flow, keyframes, multiframe]", request_schema)
        self.assertIn("required: [task_id]", response_schema)
        self.assertNotIn("required: [task_id, task_ids]", response_schema)
        self.assertIn("'400':", contract)
        self.assertIn('$ref: "#/components/schemas/ComicStoryboardImageValidationError"', contract)
        self.assertIn("detail: {type: string}", error_schema)
        self.assertNotIn("const:", error_schema)


if __name__ == "__main__":
    unittest.main()
