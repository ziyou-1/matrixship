import os
import sys
from pathlib import Path
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CLIENT = BACKEND / "matrix_native_client.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import matrix_native_client as client
from PySide6 import QtCore, QtWidgets


ANALYTICS_PAYLOAD = {
    "ok": True,
    "period": {
        "startDate": "2026-07-01",
        "endDate": "2026-07-30",
        "groupBy": "day",
        "timezone": "Asia/Shanghai",
    },
    "metrics": {
        "balance": 188,
        "totalConsumption": 42.5,
        "activeConsumptionDays": 5,
        "dailyAverage": 8.5,
        "videoTaskCount": 2,
        "videoAverage": 12.25,
    },
    "trend": [
        {"bucket": "2026-07-29", "amount": 18.5},
        {"bucket": "2026-07-30", "amount": 24},
    ],
    "distribution": [
        {"type": "video", "label": "视频生成", "amount": 24, "ratio": 56.47},
        {"type": "image", "label": "图片生成", "amount": 10, "ratio": 23.53},
        {"type": "voice", "label": "配音", "amount": 5, "ratio": 11.76},
        {"type": "other", "label": "其他", "amount": 3.5, "ratio": 8.24},
    ],
}


class BillingWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_distribution_keeps_four_rows_at_zero(self):
        widget = client.BillingDistributionBars()
        widget.set_distribution([])

        self.assertEqual(widget.row_count(), 4)
        self.assertEqual(widget.values(), [0.0, 0.0, 0.0, 0.0])

    def test_trend_height_is_stable_when_series_changes(self):
        widget = client.BillingTrendChart()
        initial = (widget.minimumHeight(), widget.maximumHeight())

        widget.set_series([{"bucket": "2026-07-%02d" % day, "amount": day} for day in range(1, 31)])

        self.assertEqual((widget.minimumHeight(), widget.maximumHeight()), initial)
        self.assertEqual(initial[0], 190)

    def test_amount_and_query_helpers_follow_display_contract(self):
        self.assertEqual(client._billing_amount("inf"), "∞ 运营方")
        self.assertEqual(client._billing_amount(12.0), "12")
        self.assertEqual(client._billing_amount(12.3456), "12.35")
        self.assertEqual(client._billing_query({"type": "video", "status": "", "page": 2}), "type=video&page=2")


class AccountPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        client.BRIDGE = client.Bridge()
        with client._SLOCK:
            client._SHARED["appRole"] = "normal_user"
        self.page = client.AccountPage()
        self.addCleanup(self.page.deleteLater)

    def test_source_contract_has_exact_dashboard_controls_and_role_guards(self):
        source = CLIENT.read_text(encoding="utf-8")
        start = source.index("class AccountPage(BasePage):")
        end = source.index("\n\nCOMIC_TOOL_URL", start)
        block = source[start:end]

        for label in ("云豆余额", "期间总消耗", "日均消耗", "单条视频平均消耗"):
            self.assertIn('"%s"' % label, block)
        self.assertEqual(block.count("self._make_billing_metric("), 4)
        self.assertNotIn("折扣共节省", block)
        self.assertIn(
            '["时间", "类型", "模型ID", "任务详情", "实扣/变动", "扣后余额", "状态"]',
            block,
        )
        self.assertIn("self.analytics_start = self._date_edit", block)
        self.assertIn("self.analytics_end = self._date_edit", block)
        self.assertIn("edit = QtWidgets.QDateEdit(value)", block)
        self.assertIn("self.analytics_group = QtWidgets.QButtonGroup", block)
        self.assertIn('self.page_size.addItems(["20", "50", "100"])', block)
        self.assertIn('self.billing_box.setVisible(product_role() == "platform_admin")', block)
        self.assertIn('self.phone_bind_panel.setVisible(product_role() == "platform_admin")', block)
        self.assertIn("self.admin_box.setVisible(False)", block)

    def test_default_period_is_latest_thirty_days_and_detail_dates_are_independent(self):
        self.assertEqual(self.page.analytics_start.date().daysTo(self.page.analytics_end.date()), 29)
        self.assertEqual(self.page.detail_start.date(), self.page.analytics_start.date())
        self.assertEqual(self.page.detail_end.date(), self.page.analytics_end.date())

        analytics_start = self.page.analytics_start.date()
        self.page.detail_start.setDate(self.page.detail_start.date().addDays(3))

        self.assertEqual(self.page.analytics_start.date(), analytics_start)

    def test_newer_analytics_payload_is_not_overwritten_by_stale_response(self):
        self.page._analytics_seq = 2
        newest = dict(ANALYTICS_PAYLOAD)
        newest["metrics"] = dict(ANALYTICS_PAYLOAD["metrics"], totalConsumption=99)
        self.page._on("acct_analytics", {"seq": 2, "payload": newest})
        self.page._on("acct_analytics", {"seq": 1, "payload": ANALYTICS_PAYLOAD})

        self.assertEqual(self.page.metric_values["期间总消耗"].text(), "99")

    def test_analytics_error_preserves_last_success_and_shows_retry_error_id(self):
        self.page._analytics_seq = 1
        self.page._on("acct_analytics", {"seq": 1, "payload": ANALYTICS_PAYLOAD})
        self.page._analytics_seq = 2
        self.page._on(
            "acct_analytics",
            {"seq": 2, "payload": {"ok": False, "message": "暂时不可用", "errorId": "err-analytics"}},
        )

        self.assertEqual(self.page.metric_values["期间总消耗"].text(), "42.5")
        self.assertIn("重试", self.page.analytics_error.text())
        self.assertIn("err-analytics", self.page.analytics_error.text())

    def test_ledger_renders_normalized_rows_unknown_balance_and_detail_tooltip(self):
        self.page._ledger_seq = 3
        detail = "这是一个需要在表格中截断但可通过悬停查看的完整任务详情" * 2
        self.page._on(
            "acct_ledger",
            {
                "seq": 3,
                "payload": {
                    "ok": True,
                    "ledger": [{
                        "createdAt": "2026-07-30T12:05:00+08:00",
                        "typeLabel": "视频生成",
                        "modelId": "seedance-2.0",
                        "detail": detail,
                        "change": -12.5,
                        "balanceAfter": None,
                        "statusLabel": "已扣费",
                    }],
                    "pagination": {"page": 1, "pageSize": 20, "total": 1, "totalPages": 1},
                },
            },
        )

        self.assertEqual(self.page.ltable.columnCount(), 7)
        self.assertEqual(self.page.ltable.item(0, 5).text(), "—")
        self.assertEqual(self.page.ltable.item(0, 3).toolTip(), detail)
        self.assertEqual(self.page.ltable.item(0, 4).foreground().color().name(), "#ef5555")

    def test_stale_ledger_error_does_not_replace_newer_success(self):
        self.page._ledger_seq = 2
        self.page._on(
            "acct_ledger",
            {"seq": 2, "payload": {"ok": True, "ledger": [], "pagination": {"page": 2, "pageSize": 20, "total": 21, "totalPages": 2}}},
        )
        self.page._on(
            "acct_ledger",
            {"seq": 1, "payload": {"ok": False, "message": "旧错误", "errorId": "err-stale"}},
        )

        self.assertEqual(self.page.page_status.text(), "第 2 / 2 页 · 共 21 条")
        self.assertNotIn("err-stale", self.page.ledger_error.text())

    def test_account_page_keeps_admin_controls_role_gated(self):
        self.assertTrue(self.page.billing_box.isHidden())
        self.assertTrue(self.page.phone_bind_panel.isHidden())
        self.assertTrue(self.page.admin_box.isHidden())

    def test_legacy_balance_refresh_keeps_operator_infinity_display(self):
        self.page._on("acct_bal", {"balance": float("inf")})

        self.assertEqual(self.page.bal_lab.text(), "∞ 运营方")


if __name__ == "__main__":
    unittest.main()
