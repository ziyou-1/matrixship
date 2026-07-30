import importlib.util
import json
import tempfile
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SERVER = ROOT / "backend" / "central_server.py"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_maindb_module():
    pymysql = types.SimpleNamespace(cursors=types.SimpleNamespace(DictCursor=object))
    passlib = types.ModuleType("passlib")
    passlib_context = types.ModuleType("passlib.context")
    passlib_context.CryptContext = lambda *args, **kwargs: object()
    passlib.context = passlib_context
    spec = importlib.util.spec_from_file_location("maindb_billing_under_test", BACKEND / "maindb.py")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {
        "pymysql": pymysql,
        "passlib": passlib,
        "passlib.context": passlib_context,
    }):
        spec.loader.exec_module(module)
    return module


def load_server_module():
    sys.modules.setdefault(
        "loguru",
        types.SimpleNamespace(logger=types.SimpleNamespace(
            add=lambda *a, **k: None,
            bind=lambda *a, **k: types.SimpleNamespace(
                info=lambda *a, **k: None,
                warning=lambda *a, **k: None,
                error=lambda *a, **k: None,
                exception=lambda *a, **k: None,
            ),
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        )),
    )
    spec = importlib.util.spec_from_file_location("central_server_billing_under_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCursor:
    def __init__(self, calls, rowcount=1):
        self.calls = calls
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, params))


class FakeConn:
    def __init__(self, calls, rowcount=1):
        self.calls = calls
        self.rowcount = rowcount

    def cursor(self):
        return FakeCursor(self.calls, self.rowcount)


class FakeMainDb:
    def __init__(self, rowcount=1):
        self.calls = []
        self.rowcount = rowcount
        self.balance = 10.0
        self.topups = []
        self.topup_ok = True
        self.refunds = []
        self.refund_result = (False, 0.0)

    def _conn(self):
        return FakeConn(self.calls, self.rowcount)

    def get_balance(self, user_id):
        return self.balance

    def topup(self, user_id, amount, reason):
        self.topups.append((user_id, amount, reason))
        if not self.topup_ok:
            return False, self.balance
        self.balance = round(self.balance + float(amount), 6)
        return True, self.balance

    def refund_generation(self, ref, reason):
        self.refunds.append((ref, reason))
        ok, amount = self.refund_result
        if ok:
            self.balance = round(self.balance + float(amount), 6)
        return ok, amount


class UnifiedBillingTest(unittest.TestCase):
    def setUp(self):
        self.server = load_server_module()
        self.state = {
            "users": [{"id": "u1", "name": "User", "status": "active", "balance": 100.0}],
            "ledger": [],
            "auditLogs": [],
        }
        self.state_patch = mock.patch.object(self.server, "STATE", self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.persist_patch = mock.patch.object(self.server, "persist", lambda: None)
        self.persist_patch.start()
        self.addCleanup(self.persist_patch.stop)

    def test_capability_charge_uses_server_price_instead_of_client_amount(self):
        ok, balance, err = self.server.charge_capability_user(
            "u1", "copywriting", requested_amount=0.01, ref="copywriting:test"
        )

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(balance, 99.93)
        self.assertEqual(self.state["ledger"][0]["delta"], -0.07)
        self.assertEqual(self.state["ledger"][0]["ref"], "copywriting:test")

    def test_capability_prices_are_one_yundou_per_yuan(self):
        self.assertEqual(self.server.capability_price_yundou("copywriting")[0], 0.07)
        self.assertEqual(self.server.capability_price_yundou("comic_keyframe_image")[0], 0.14)
        self.assertEqual(self.server.capability_price_yundou("product_video")[0], 3.08)
        self.assertEqual(self.server.capability_price_yundou("digital_human")[0], 25.2)
        self.assertEqual(self.server.gen_price_yundou("doubao-seedance", {}), 3.08)
        self.assertEqual(self.server.gen_price_yundou("gpt-image-2", {}), 0.14)

    def test_capability_charge_blocks_insufficient_balance_before_ledger_write(self):
        self.state["users"][0]["balance"] = 0.01

        ok, balance, err = self.server.charge_capability_user(
            "u1", "copywriting", requested_amount=999, ref="copywriting:test"
        )

        self.assertFalse(ok)
        self.assertEqual(balance, 0.01)
        self.assertEqual(err, "insufficient_balance")
        self.assertEqual(self.state["ledger"], [])

    def test_maindb_capability_charge_converts_yundou_to_power(self):
        fake = FakeMainDb(rowcount=1)

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=True):
            ok, balance, err = self.server.charge_capability_user(
                42, "copywriting", requested_amount=999, ref="copywriting:test"
            )

        self.assertTrue(ok)
        self.assertEqual(balance, 10.0)
        self.assertIsNone(err)
        self.assertEqual(fake.calls[0][1], ("0.7", 42, "0.7"))
        self.assertEqual(self.state["ledger"][0]["delta"], -0.7)
        self.assertEqual(self.state["ledger"][0]["yundouAmount"], 0.07)
        self.assertEqual(self.state["ledger"][0]["wallet"], "maindb_generic")

    def test_maindb_topup_writes_traceable_positive_ledger(self):
        fake = FakeMainDb()

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=True):
            ok, balance, err = self.server.topup_user(42, 5, "管理员充值", "admin-topup:test")

        self.assertTrue(ok)
        self.assertEqual(balance, 15.0)
        self.assertIsNone(err)
        self.assertEqual(self.state["ledger"][-1]["delta"], 5.0)
        self.assertEqual(self.state["ledger"][-1]["balanceAfter"], 15.0)
        self.assertEqual(self.state["ledger"][-1]["ref"], "admin-topup:test")

    def test_maindb_topup_failure_does_not_write_positive_ledger(self):
        fake = FakeMainDb()
        fake.topup_ok = False

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=True):
            ok, balance, err = self.server.topup_user(42, 5, "管理员充值", "admin-topup:test")

        self.assertFalse(ok)
        self.assertEqual(balance, 10.0)
        self.assertEqual(err, "topup_failed")
        self.assertEqual(self.state["ledger"], [])

    def test_maindb_topup_zero_affected_rows_returns_false_and_writes_no_center_ledger(self):
        source = load_maindb_module()
        with mock.patch.object(source, "_exec", return_value=(0, 0)) as execute, \
                mock.patch.object(source, "get_balance", return_value=10.0):
            direct_ok, direct_balance = source.topup(42, 5, "管理员充值")
            with mock.patch.object(self.server, "maindb", source), \
                    mock.patch.object(self.server, "maindb_on", return_value=True):
                ok, balance, err = self.server.topup_user(42, 5, "管理员充值", "admin-topup:rowcount-zero")

        self.assertEqual(execute.call_count, 2)
        self.assertEqual(execute.call_args_list, [
            mock.call("UPDATE users SET computing_power = computing_power + %s, updated_at=NOW() WHERE id=%s",
                      ("5", 42)),
            mock.call("UPDATE users SET computing_power = computing_power + %s, updated_at=NOW() WHERE id=%s",
                      ("5.0", 42)),
        ])
        self.assertFalse(direct_ok)
        self.assertEqual(direct_balance, 10.0)
        self.assertFalse(ok)
        self.assertEqual(balance, 10.0)
        self.assertEqual(err, "topup_failed")
        self.assertEqual(self.state["ledger"], [])

    def test_maindb_model_refund_writes_one_positive_ledger(self):
        fake = FakeMainDb()
        fake.refund_result = (True, 3.0)

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=True):
            ok, balance, amount, err = self.server.refund_user_by_ref(42, "video:req-1")
            fake.refund_result = (False, 0.0)
            ok2, balance2, amount2, err2 = self.server.refund_user_by_ref(42, "video:req-1")

        self.assertTrue(ok)
        self.assertEqual(balance, 13.0)
        self.assertEqual((amount, self.state["ledger"][-1]["delta"]), (3.0, 3.0))
        self.assertEqual(self.state["ledger"][-1]["reason"], "退款:模型生成")
        self.assertEqual(self.state["ledger"][-1]["ref"], "video:req-1")
        self.assertTrue(ok2)
        self.assertEqual((balance2, amount2, err2), (13.0, 0.0, None))
        self.assertEqual(len(self.state["ledger"]), 1)

    def test_maindb_model_usage_logs_query_is_bounded_and_requests_overflow_row(self):
        source = load_maindb_module()
        rows = [{"id": 7, "request_id": "video:req-1"}]
        expected_sql = (
            "SELECT id, request_id, user_id, project_id, task_id, model_id, model_type, "
            "billing_method, amount, balance_before, balance_after, status, description, "
            "created_at, refunded_at FROM model_usage_logs "
            "WHERE user_id=%s AND created_at >= %s AND created_at < %s "
            "ORDER BY created_at DESC, id DESC LIMIT %s"
        )

        with mock.patch.object(source, "_q", return_value=rows) as query:
            result = source.list_model_usage_logs(42, "2026-07-01", "2026-08-01", limit=99999)

        self.assertEqual(result, rows)
        query.assert_called_once_with(expected_sql, (42, "2026-07-01", "2026-08-01", 50001))

    def test_maindb_refund_generation_database_exception_rolls_back_and_propagates(self):
        source = load_maindb_module()

        class FailingConn:
            def __init__(self):
                self.rollback_calls = 0

            def begin(self):
                raise RuntimeError("database unavailable")

            def rollback(self):
                self.rollback_calls += 1

        conn = FailingConn()
        with mock.patch.object(source, "_conn", return_value=conn):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                source.refund_generation("video:req-1")

        self.assertEqual(conn.rollback_calls, 1)

    def test_maindb_model_refund_database_exception_returns_failure_without_ledger(self):
        fake = FakeMainDb()
        fake.refund_generation = mock.Mock(side_effect=RuntimeError("database unavailable"))

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=True):
            ok, balance, amount, err = self.server.refund_user_by_ref(42, "video:req-1")

        self.assertFalse(ok)
        self.assertEqual((balance, amount), (10.0, 0.0))
        self.assertIn("database unavailable", err)
        self.assertEqual(self.state["ledger"], [])

    def test_recharge_packages_use_one_yundou_per_yuan(self):
        self.assertEqual(self.server.RECHARGE_PACKAGES[1], {"id": "p30", "yuan": 30, "yundou": 30})

    def test_create_recharge_order_credits_yuan_amount_as_yundou(self):
        fake_wx = types.SimpleNamespace(
            configured=True,
            native_prepay=lambda order_no, desc, amount_fen, attach=None: "weixin://pay/native-test",
        )

        with mock.patch.object(self.server, "wxpay", return_value=fake_wx), \
                mock.patch.object(self.server, "maindb_on", return_value=False):
            ok, order, err = self.server.create_recharge_order("u1", 3000)

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(order["amountFen"], 3000)
        self.assertEqual(order["yundou"], 30.0)
        self.assertEqual(order["credit"], 30.0)
        self.assertEqual(order["currency"], "yundou")

    def test_maindb_wechat_topup_failure_remains_uncredited_and_retryable(self):
        fake = FakeMainDb()
        fake.topup_ok = False
        self.state["recharge_orders"] = [{
            "orderNo": "wx-order-1", "userId": 42, "credit": 5.0, "yundou": 5.0,
            "credited": False, "status": "NOTPAY",
        }]
        fake_wx = types.SimpleNamespace(query=lambda order_no: {
            "trade_state": "SUCCESS", "transaction_id": "tx-1",
        })

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=True), \
                mock.patch.object(self.server, "wxpay", return_value=fake_wx):
            ok, result, err = self.server.poll_recharge_order(42, "wx-order-1")

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertFalse(result["credited"])
        self.assertFalse(self.state["recharge_orders"][0]["credited"])
        self.assertEqual(self.state["ledger"], [])

    def test_maindb_wechat_topup_writes_traceable_positive_ledger(self):
        fake = FakeMainDb()
        self.state["recharge_orders"] = [{
            "orderNo": "wx-order-2", "userId": 42, "credit": 5.0, "yundou": 5.0,
            "credited": False, "status": "NOTPAY",
        }]
        fake_wx = types.SimpleNamespace(query=lambda order_no: {
            "trade_state": "SUCCESS", "transaction_id": "tx-2",
        })

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=True), \
                mock.patch.object(self.server, "wxpay", return_value=fake_wx):
            ok, result, err = self.server.poll_recharge_order(42, "wx-order-2")

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertTrue(result["credited"])
        self.assertEqual((self.state["ledger"][-1]["delta"], self.state["ledger"][-1]["ref"]),
                         (5.0, "wxpay:wx-order-2"))

    def test_maindb_redeem_topup_failure_keeps_code_active(self):
        fake = FakeMainDb()
        fake.topup_ok = False
        self.state["redeem_codes"] = [{"code": "MXTEST", "amount": 5.0, "status": "active"}]

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=True):
            ok, balance, amount, err = self.server.redeem_code(42, "MXTEST")

        self.assertFalse(ok)
        self.assertEqual((balance, amount, err), (10.0, 0.0, "topup_failed"))
        self.assertEqual(self.state["redeem_codes"][0]["status"], "active")
        self.assertEqual(self.state["ledger"], [])

    def test_maindb_redeem_topup_writes_traceable_positive_ledger(self):
        fake = FakeMainDb()
        self.state["redeem_codes"] = [{"code": "MXTEST", "amount": 5.0, "status": "active"}]

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=True):
            ok, balance, amount, err = self.server.redeem_code(42, "MXTEST")

        self.assertTrue(ok)
        self.assertEqual((balance, amount, err), (15.0, 5.0, None))
        self.assertEqual(self.state["redeem_codes"][0]["status"], "used")
        self.assertEqual((self.state["ledger"][-1]["delta"], self.state["ledger"][-1]["ref"]),
                         (5.0, "redeem:MXTEST"))

    def test_yundou_legacy_balance_migration_scales_once(self):
        legacy = {
            "users": [{"id": "u1", "balance": 100.0}],
            "ledger": [
                {"id": "l1", "delta": -7.0, "balanceAfter": 93.0, "yundouAmount": 7.0},
                {"id": "l2", "delta": -0.7, "balanceAfter": 10.0, "wallet": "maindb_generic", "yundouAmount": 7.0},
            ],
            "recharge_orders": [{"orderNo": "o1", "amountFen": 3000, "yundou": 3000, "credit": 3000, "currency": "yundou"}],
            "redeem_codes": [{"code": "MX-OLD", "amount": 600, "status": "active"}],
        }

        summary = self.server.migrate_yundou_state_to_one_to_one(legacy, now_label="20260729120000")
        second = self.server.migrate_yundou_state_to_one_to_one(legacy, now_label="20260729120100")

        self.assertTrue(summary["migrated"])
        self.assertFalse(second["migrated"])
        self.assertEqual(legacy["users"][0]["balance"], 1.0)
        self.assertEqual(legacy["ledger"][0]["delta"], -0.07)
        self.assertEqual(legacy["ledger"][0]["balanceAfter"], 0.93)
        self.assertEqual(legacy["ledger"][0]["yundouAmount"], 0.07)
        self.assertEqual(legacy["ledger"][1]["delta"], -0.7)
        self.assertEqual(legacy["ledger"][1]["balanceAfter"], 10.0)
        self.assertEqual(legacy["ledger"][1]["yundouAmount"], 0.07)
        self.assertEqual(legacy["recharge_orders"][0]["yundou"], 30.0)
        self.assertEqual(legacy["recharge_orders"][0]["credit"], 30.0)
        self.assertEqual(legacy["redeem_codes"][0]["amount"], 6.0)

    def test_maindb_generic_refund_uses_ledger_once(self):
        fake = FakeMainDb(rowcount=1)
        self.state["ledger"].append({
            "id": "l1",
            "userId": 42,
            "delta": -0.7,
            "reason": "copywriting",
            "ref": "copywriting:test",
            "wallet": "maindb_generic",
            "refunded": False,
        })

        with mock.patch.object(self.server, "maindb", fake), \
                mock.patch.object(self.server, "maindb_on", return_value=True):
            ok, balance, amount, err = self.server.refund_user_by_ref(42, "copywriting:test")
            ok2, balance2, amount2, err2 = self.server.refund_user_by_ref(42, "copywriting:test")

        self.assertTrue(ok)
        self.assertEqual(balance, 10.7)
        self.assertEqual(amount, 0.7)
        self.assertIsNone(err)
        self.assertTrue(ok2)
        self.assertEqual(balance2, 10.7)
        self.assertEqual(amount2, 0.0)
        self.assertIsNone(err2)
        self.assertEqual(fake.topups, [(42, 0.7, "matrixship 通用扣费退款 copywriting:test")])


    def test_state_startup_backup_copies_existing_state_file(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "scheduler_state.json"
            state_path.write_text(json.dumps({"users": [{"id": "u1"}]}), encoding="utf-8")

            with mock.patch.object(self.server, "STORE_JSON", str(state_path)):
                backup_path = self.server.backup_state_file_on_startup(now_label="20260725143000")

            self.assertTrue(Path(backup_path).exists())
            self.assertEqual(json.loads(Path(backup_path).read_text(encoding="utf-8"))["users"][0]["id"], "u1")
    def test_state_loader_reads_utf8_sig_state_file(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "scheduler_state.json"
            state_path.write_text(json.dumps({"organizations": [{"id": "org-a"}]}), encoding="utf-8-sig")

            loaded = self.server._load_json(str(state_path), {})

        self.assertEqual(loaded["organizations"][0]["id"], "org-a")
        self.assertIsNone(self.server.STATE_LOAD_ERROR)

    def test_state_loader_refuses_corrupt_existing_state_file(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "scheduler_state.json"
            state_path.write_text("{bad json", encoding="utf-8")

            with mock.patch.object(self.server, "STORE_JSON", str(state_path)):
                with self.assertRaises(self.server.StateLoadError):
                    self.server.init_state()

            self.assertIsNotNone(self.server.STATE_LOAD_ERROR)
            self.assertIn("state_load_failed", self.server.STATE_LOAD_ERROR.get("error"))

    def test_state_save_guard_refuses_to_overwrite_rich_state_with_default_skeleton(self):
        self.server.STATE_LOAD_ERROR = None
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "scheduler_state.json"
            existing = {
                "organizations": [{"id": "org-default"}, {"id": "org-toyota"}],
                "users": [{"id": "user-owner"}, {"id": "boss"}],
                "memberships": [{"id": "m1"}, {"id": "m2"}],
            }
            state_path.write_text(json.dumps(existing), encoding="utf-8")
            skeleton = {
                "organizations": [{"id": "org-default"}],
                "users": [{"id": "user-owner", "phone": "admin"}],
                "memberships": [{"id": "m-default-owner", "orgId": "org-default", "userId": "user-owner"}],
            }

            with mock.patch.object(self.server, "STORE_JSON", str(state_path)):
                with self.assertRaises(self.server.StateWriteProtectionError):
                    self.server._save_json(str(state_path), skeleton)

            restored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(restored["organizations"]), 2)
            self.assertEqual(len(restored["users"]), 2)
    def test_lk888_proxy_task_flags_treat_chinese_error_status_as_failed(self):
        failed, done = self.server.lk888_proxy_task_flags({"data": {"status": "错误"}})

        self.assertTrue(failed)
        self.assertFalse(done)

if __name__ == "__main__":
    unittest.main()
