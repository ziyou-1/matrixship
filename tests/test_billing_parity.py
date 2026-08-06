"""2026-08-06 回归:矩阵侧扣费必须与漫剧侧对齐。

背景(全部有生产数据佐证):
  * 汇率:漫剧 recharge_packages 实际是 50元档=50算力,即 1 元 ≈ 1 算力。矩阵侧却按
    MAINDB_YUAN_TO_POWER=10 扣,十倍超收。
  * 可见性:矩阵侧扣费只写中心服的 JSON 账本,不写 MySQL。生产库 model_usage_logs 共
    11415 行,description LIKE 'matrixship%' 的 0 行 —— 漫剧的消费账单界面完全看不到
    矩阵侧的消费,账号 44 的余额比最后一条 MySQL 记录少 77.23 却无从追溯。
  * 幂等:旧实现靠反向扫描 STATE["ledger"],而该账本截断到 8000 条,且查重与扣款不在
    同一把锁里,两个并发结算可以同时通过。
"""
import importlib.util
from decimal import Decimal
from pathlib import Path
import sys
import unittest
from unittest import mock


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


class ExchangeRateTest(unittest.TestCase):
    """1 元 = 1 算力,且充值与扣费必须共用同一个常量。"""

    def setUp(self):
        self.central = load("central_rate", "central_server.py")

    def test_one_yuan_is_one_power(self):
        self.assertEqual(self.central.MAINDB_YUAN_TO_POWER, 1.0)
        self.assertEqual(self.central.maindb_power_from_yundou(1), 1.0)
        self.assertEqual(self.central.maindb_power_from_yundou(0.0013), 0.0013)

    def test_charge_and_recharge_share_one_constant(self):
        """拆成两个常量就会变成 10 倍定价错误(方向取决于改了哪边),必须共用。"""
        src = (BACKEND / "central_server.py").read_text(encoding="utf-8")
        # 充值入账与扣费换算引用的是同一个名字
        self.assertIn("amount_fen / 100.0 * MAINDB_YUAN_TO_POWER", src)
        self.assertIn("float(yundou_amount or 0) * MAINDB_YUAN_TO_POWER", src)


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.lastrowid = 1001
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=None):
        self.conn.sql.append((sql.split()[0].upper() + " " + _target(sql), args))
        if self.conn.raise_duplicate and sql.strip().upper().startswith("INSERT INTO MODEL_USAGE_LOGS"):
            import pymysql
            raise pymysql.err.IntegrityError(1062, "Duplicate entry")
        if "FOR UPDATE" in sql.upper():
            self._row = None if self.conn.user_missing else {"computing_power": self.conn.balance}

    def fetchone(self):
        return self._row


def _target(sql):
    up = sql.strip().upper()
    for t in ("MODEL_USAGE_LOGS", "COMPUTING_POWER_RECORDS", "USERS"):
        if t in up:
            return t
    return "?"


class FakeConn:
    def __init__(self, balance="100", raise_duplicate=False, user_missing=False):
        self.balance = Decimal(balance)
        self.raise_duplicate = raise_duplicate
        self.user_missing = user_missing
        self.sql = []
        self.committed = False
        self.rolled_back = False

    def begin(self):
        self.sql.append(("BEGIN", None))

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class ChargeActualCostTest(unittest.TestCase):
    def setUp(self):
        self.maindb = load("maindb_parity", "maindb.py")
        self.maindb._POWER_RECORDS_OK = True  # 跳过探针,不碰真实数据库

    def _charge(self, conn, **kw):
        with mock.patch.object(self.maindb, "_conn", return_value=conn), \
                mock.patch.object(self.maindb, "get_balance", return_value=float(conn.balance)):
            return self.maindb.charge_actual_cost(
                44, kw.pop("amount", "1.5"), request_id=kw.pop("ref", "lk888:123"),
                model_id="gemini-3.1-pro-preview", description="LK888实际扣费", **kw)

    def test_charge_writes_balance_and_both_audit_tables_in_one_transaction(self):
        conn = FakeConn(balance="100")

        status, amt, bal, err = self._charge(conn)

        self.assertEqual(status, "charged")
        self.assertIsNone(err)
        self.assertAlmostEqual(amt, 1.5)
        self.assertAlmostEqual(bal, 98.5)
        self.assertTrue(conn.committed)
        self.assertFalse(conn.rolled_back)
        touched = [t for t, _ in conn.sql]
        self.assertIn("INSERT MODEL_USAGE_LOGS", touched)
        self.assertIn("UPDATE USERS", touched)
        self.assertIn("INSERT COMPUTING_POWER_RECORDS", touched)

    def test_lock_order_matches_refund_generation(self):
        """必须先动 model_usage_logs 再动 users;反序会与并发退款形成死锁环。"""
        conn = FakeConn(balance="100")

        self._charge(conn)

        touched = [t for t, _ in conn.sql]
        self.assertLess(touched.index("INSERT MODEL_USAGE_LOGS"), touched.index("UPDATE USERS"))

    def test_foreign_key_violation_is_an_error_not_a_silent_duplicate(self):
        """1452 等完整性错误绝不能当成"已扣过"。

        task_id / project_id 是外键。若把任意 IntegrityError 都判成 duplicate,
        调用方会以为扣过了而放行,用户白嫖且无任何记录 —— 与本次改造的目标相反。
        """
        import pymysql

        class FKConn(FakeConn):
            def cursor(self):
                cur = FakeCursor(self)
                orig = cur.execute

                def execute(sql, args=None):
                    if sql.strip().upper().startswith("INSERT INTO MODEL_USAGE_LOGS"):
                        self.sql.append(("INSERT MODEL_USAGE_LOGS", args))
                        raise pymysql.err.IntegrityError(1452, "Cannot add or update a child row")
                    return orig(sql, args)

                cur.execute = execute
                return cur

        conn = FKConn(balance="100")

        status, _amt, _bal, err = self._charge(conn)

        self.assertEqual(status, "error")
        self.assertIn("1452", err or "")
        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.committed)

    def test_duplicate_request_id_is_rejected_by_the_database(self):
        """幂等由唯一索引保证,不依赖任何进程内状态。"""
        conn = FakeConn(balance="100", raise_duplicate=True)

        status, amt, bal, err = self._charge(conn)

        self.assertEqual(status, "duplicate")
        self.assertEqual(amt, 0.0)
        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.committed)
        self.assertNotIn("UPDATE USERS", [t for t, _ in conn.sql])

    def test_insufficient_balance_is_refused_not_allowed_to_go_negative(self):
        conn = FakeConn(balance="0.5")

        status, amt, bal, err = self._charge(conn, amount="1.5")

        self.assertEqual(status, "insufficient")
        self.assertEqual(err, "insufficient_balance")
        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.committed)
        self.assertNotIn("UPDATE USERS", [t for t, _ in conn.sql])

    def test_arrears_can_still_be_opted_into_explicitly(self):
        conn = FakeConn(balance="0.5")

        status, amt, bal, err = self._charge(conn, amount="1.5", allow_arrears=True)

        self.assertEqual(status, "charged")
        self.assertAlmostEqual(bal, -1.0)

    def test_missing_request_id_never_charges(self):
        conn = FakeConn(balance="100")

        status, _amt, _bal, err = self._charge(conn, ref="")

        self.assertEqual(status, "error")
        self.assertEqual(err, "missing_request_id")
        self.assertEqual(conn.sql, [])


class CentralChargePathTest(unittest.TestCase):
    """中心服侧:漫剧账号必须走 MySQL,且不再往 JSON 账本写模型扣费。"""

    def setUp(self):
        self.central = load("central_charge_path", "central_server.py")

    def test_maindb_user_charge_goes_to_mysql_and_not_the_json_ledger(self):
        state = {"ledger": [], "users": []}
        fake = mock.Mock(charge_actual_cost=mock.Mock(return_value=("charged", 0.013, 4148.7, None)))
        with mock.patch.object(self.central, "STATE", state), \
                mock.patch.object(self.central, "maindb", fake), \
                mock.patch.object(self.central, "maindb_on", return_value=True), \
                mock.patch.object(self.central, "get_balance", return_value=4148.7):
            ok, bal, err = self.central.charge_user_actual_cost(
                44, 0.013, reason="LK888实际扣费 gemini", ref="lk888:95592854",
                meta={"modelId": "gemini-3.1-pro-preview", "taskId": "95592854"})

        self.assertTrue(ok)
        self.assertIsNone(err)
        fake.charge_actual_cost.assert_called_once()
        self.assertEqual(fake.charge_actual_cost.call_args.kwargs["request_id"], "lk888:95592854")
        self.assertIs(fake.charge_actual_cost.call_args.kwargs["allow_arrears"], False)
        self.assertEqual(state["ledger"], [], "漫剧账号不得再写 JSON 账本,否则账户中心会重复计数")

    def test_insufficient_balance_surfaces_as_a_failure(self):
        fake = mock.Mock(charge_actual_cost=mock.Mock(
            return_value=("insufficient", 1.5, 0.5, "insufficient_balance")))
        with mock.patch.object(self.central, "STATE", {"ledger": [], "users": []}), \
                mock.patch.object(self.central, "maindb", fake), \
                mock.patch.object(self.central, "maindb_on", return_value=True), \
                mock.patch.object(self.central, "get_balance", return_value=0.5):
            ok, bal, err = self.central.charge_user_actual_cost(44, 1.5, ref="lk888:1")

        self.assertFalse(ok)
        self.assertEqual(err, "insufficient_balance")

    def test_duplicate_settlement_is_treated_as_success_without_recharging(self):
        fake = mock.Mock(charge_actual_cost=mock.Mock(return_value=("duplicate", 0.0, 4148.7, None)))
        with mock.patch.object(self.central, "STATE", {"ledger": [], "users": []}), \
                mock.patch.object(self.central, "maindb", fake), \
                mock.patch.object(self.central, "maindb_on", return_value=True), \
                mock.patch.object(self.central, "get_balance", return_value=4148.7):
            ok, bal, err = self.central.charge_user_actual_cost(44, 0.013, ref="lk888:95592854")

        self.assertTrue(ok, "重复结算应视为已完成,不能报错让上层重试")
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
