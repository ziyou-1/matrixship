import os
import sys
from pathlib import Path
import unittest
from unittest import mock


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CLIENT = BACKEND / "matrix_native_client.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import matrix_native_client as client
from PySide6 import QtCore, QtGui, QtWidgets


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
        self.assertEqual(client._billing_amount(12.3456), "12.3456")
        self.assertEqual(client._billing_query({"type": "video", "status": "", "page": 2}), "type=video&page=2")

    def test_lk888_actual_charges_keep_four_decimal_places(self):
        self.assertEqual(client._billing_amount("-0.0016"), "-0.0016")
        self.assertEqual(client._billing_amount("-0.0222"), "-0.0222")
        self.assertEqual(client._billing_amount("-0.0340"), "-0.034")
        self.assertEqual(client._billing_amount("-0.0000"), "0")

    def test_ledger_display_helpers_clean_model_and_business_detail(self):
        row = {
            "type": "video",
            "typeLabel": "视频生成",
            "modelId": "",
            "model": "viduq3",
            "detail": "LK888实际扣费 viduq3",
            "ref": "lk888:90109143",
        }

        self.assertEqual(client._billing_ledger_model_text(row), "viduq3")
        self.assertEqual(client._billing_ledger_detail_text(row), "agent.模式视频生成")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "image",
            "detail": "comic_keyframe_image",
            "ref": "comic_keyframe:job-a:seg:4:abc:frame:1",
        }), "同款替换首帧图")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "image",
            "detail": "comic_keyframe_image",
            "ref": "comic_keyframe:job-a:seg:4:abc:frame:2",
        }), "同款替换尾帧图")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "video",
            "detail": "漫剧视频生成，项目310 · 片段6 · abc",
            "ref": "comic_video:job-a:project:310:seg:6:abc",
        }), "同款替换视频 · 片段6")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "refund",
            "detail": "退款:漫剧视频生成，项目310 · 片段5 · abc",
            "ref": "refund:comic_video:job-a:project:310:seg:5:abc",
        }), "同款替换视频退款 · 片段5")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "voice",
            "detail": "tts voice clone",
        }), "数字人口播配音")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "other",
            "detail": "chat completion",
            "modelId": "gemini-3.1-pro-preview",
        }), "工作流助手聊天")

    def test_ledger_display_helpers_describe_agent_prompt_stages(self):
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "other",
            "billingScenario": "agent_mode",
            "billingStage": "prompt_optimization",
            "modelId": "gpt-5.4-xhigh",
            "source": "chat_usage_reconcile",
        }), "Agent.模式 - 提示词优化")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "other",
            "billingScenario": "agent_mode",
            "billingStage": "reference_analysis",
            "modelId": "gemini-3.1-pro-preview",
            "source": "chat_usage_reconcile",
        }), "Agent.模式 - 参考图理解")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "other",
            "billingScenario": "agent_mode",
            "billingStage": "prompt_translation",
            "modelId": "gpt-5.4-xhigh",
            "source": "chat_usage_reconcile",
        }), "Agent.模式 - 模型兼容提示词转换")


    def test_ledger_display_helpers_describe_video_breakdown_model_stages(self):
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "other",
            "billingScenario": "video_breakdown",
            "billingStage": "audio_transcription",
            "modelId": "gemini-3.1-pro-preview",
            "source": "chat_usage_reconcile",
        }), "分解视频调用")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "other",
            "billingScenario": "video_breakdown",
            "billingStage": "visual_analysis",
            "modelId": "gemini-3.1-pro-preview",
            "source": "chat_usage_reconcile",
        }), "分解视频调用")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "other",
            "billingScenario": "video_breakdown",
            "billingStage": "report_generation",
            "modelId": "gpt-5.4-xhigh",
            "source": "chat_usage_reconcile",
        }), "分解视频调用")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "other",
            "ref": "lk888-chat:abc",
            "detail": "video_breakdown ocr_text",
            "modelId": "gemini-3.1-pro-preview",
        }), "分解视频调用")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "refund",
            "billingScenario": "video_breakdown",
            "billingStage": "visual_analysis",
            "modelId": "gemini-3.1-pro-preview",
            "source": "chat_usage_reconcile",
        }), "分解视频调用退款")
        self.assertEqual(client._billing_ledger_detail_text({
            "type": "other",
            "detail": "chat completion",
            "modelId": "gemini-3.1-pro-preview",
        }), "工作流助手聊天")


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

    def test_billing_date_picker_calendar_year_is_readable(self):
        for edit in (
            self.page.analytics_start,
            self.page.analytics_end,
            self.page.detail_start,
            self.page.detail_end,
        ):
            self.assertTrue(edit.calendarPopup())
            self.assertEqual(edit.objectName(), "billingDateEdit")
            self.assertIn("QDateEdit#billingDateEdit", edit.styleSheet())

            calendar = edit.calendarWidget()
            self.assertIsNotNone(calendar)
            self.assertEqual(calendar.objectName(), "billingDateCalendar")
            calendar_style = calendar.styleSheet()
            self.assertIn("QCalendarWidget#billingDateCalendar QSpinBox", calendar_style)
            self.assertIn("color:#ffffff", calendar_style)
            self.assertIn("background:%s" % client.TK["inputFocusBg"], calendar_style)
            self.assertIn("QWidget#qt_calendar_navigationbar", calendar_style)

    def test_account_page_auto_refreshes_visible_billing_data(self):
        self.page.on_show()

        self.assertTrue(self.page._billing_refresh_timer.isActive())
        self.assertGreaterEqual(self.page._billing_refresh_timer.interval(), 10000)

    def test_account_page_shows_loading_placeholders_before_billing_responses(self):
        with mock.patch.object(client, "run_bg"):
            self.page.on_show()

        self.assertEqual(self.page.metric_values["云豆余额"].text(), "加载中")
        self.assertIn("正在加载", self.page.analytics_error.text())
        self.assertIn("正在加载", self.page.ledger_error.text())
        self.assertEqual(self.page.ltable.rowCount(), 1)
        self.assertIn("正在读取扣费明细", self.page.ltable.item(0, 0).text())

    def test_header_has_compact_refresh_button_with_icon(self):
        header = self.page.v.itemAt(0).widget()

        self.assertEqual(self.page.refresh_btn.text(), "刷新")
        self.assertFalse(self.page.refresh_btn.icon().isNull())
        self.assertLessEqual(self.page.refresh_btn.width(), 100)
        self.assertTrue(header.isAncestorOf(self.page.refresh_btn))

    def test_manual_refresh_requests_all_billing_data_without_resetting_view_state(self):
        self.page._ledger_page = 4
        self.page._ledger_total_pages = 9
        self.page._group_by = "month"
        analytics_start = self.page.analytics_start.date()
        analytics_end = self.page.analytics_end.date()
        detail_start = self.page.detail_start.date()
        detail_end = self.page.detail_end.date()
        detail_type = self.page.detail_type.currentData()
        detail_status = self.page.detail_status.currentData()
        page_size = self.page.page_size.currentText()

        with mock.patch.object(client, "run_bg") as run_bg, mock.patch.object(self.page, "load_users") as load_users:
            self.page.refresh_btn.click()

        self.assertEqual(run_bg.call_count, 3)
        load_users.assert_not_called()
        self.assertEqual(self.page._ledger_page, 4)
        self.assertEqual(self.page._group_by, "month")
        self.assertEqual(self.page.analytics_start.date(), analytics_start)
        self.assertEqual(self.page.analytics_end.date(), analytics_end)
        self.assertEqual(self.page.detail_start.date(), detail_start)
        self.assertEqual(self.page.detail_end.date(), detail_end)
        self.assertEqual(self.page.detail_type.currentData(), detail_type)
        self.assertEqual(self.page.detail_status.currentData(), detail_status)
        self.assertEqual(self.page.page_size.currentText(), page_size)
        self.assertFalse(self.page.refresh_btn.isEnabled())
        self.assertEqual(self.page.refresh_btn.text(), "刷新中...")
        self.assertLessEqual(self.page.refresh_btn.sizeHint().width(), self.page.refresh_btn.width())

    def test_manual_refresh_finishes_after_current_success_and_error_responses(self):
        with mock.patch.object(client, "run_bg"):
            self.page.refresh_all()

        balance_seq = self.page._balance_seq
        analytics_seq = self.page._analytics_seq
        ledger_seq = self.page._ledger_seq
        self.page._on("acct_bal", {"seq": balance_seq, "balance": 88})
        self.assertFalse(self.page.refresh_btn.isEnabled())
        self.page._on(
            "acct_analytics",
            {"seq": analytics_seq, "payload": {"ok": False, "message": "统计失败", "errorId": "err-refresh-a"}},
        )
        self.assertFalse(self.page.refresh_btn.isEnabled())
        self.page._on(
            "acct_ledger",
            {"seq": ledger_seq, "payload": {"ok": False, "message": "明细失败", "errorId": "err-refresh-l"}},
        )

        self.assertTrue(self.page.refresh_btn.isEnabled())
        self.assertEqual(self.page.refresh_btn.text(), "刷新")
        self.assertIn("err-refresh-a", self.page.analytics_error.text())
        self.assertIn("err-refresh-l", self.page.ledger_error.text())

    def test_stale_response_cannot_finish_current_manual_refresh(self):
        with mock.patch.object(client, "run_bg"):
            self.page.refresh_all()

        balance_seq = self.page._balance_seq
        analytics_seq = self.page._analytics_seq
        ledger_seq = self.page._ledger_seq
        self.page._on("acct_bal", {"seq": balance_seq, "balance": 88})
        self.page._on(
            "acct_ledger",
            {"seq": ledger_seq, "payload": {"ok": True, "ledger": [], "pagination": {"page": 1, "pageSize": 20, "total": 0, "totalPages": 0}}},
        )
        self.page._on("acct_analytics", {"seq": analytics_seq - 1, "payload": ANALYTICS_PAYLOAD})

        self.assertFalse(self.page.refresh_btn.isEnabled())
        self.page._on("acct_analytics", {"seq": analytics_seq, "payload": ANALYTICS_PAYLOAD})
        self.assertTrue(self.page.refresh_btn.isEnabled())

    def test_new_request_during_manual_refresh_replaces_pending_sequence(self):
        with mock.patch.object(client, "run_bg"):
            self.page.refresh_all()
            first_analytics_seq = self.page._analytics_seq
            self.page.load_analytics()

        latest_analytics_seq = self.page._analytics_seq
        self.assertGreater(latest_analytics_seq, first_analytics_seq)
        self.page._on("acct_bal", {"seq": self.page._balance_seq, "balance": 88})
        self.page._on(
            "acct_ledger",
            {"seq": self.page._ledger_seq, "payload": {"ok": True, "ledger": [], "pagination": {"page": 1, "pageSize": 20, "total": 0, "totalPages": 0}}},
        )
        self.page._on("acct_analytics", {"seq": first_analytics_seq, "payload": ANALYTICS_PAYLOAD})

        self.assertFalse(self.page.refresh_btn.isEnabled())
        self.page._on("acct_analytics", {"seq": latest_analytics_seq, "payload": ANALYTICS_PAYLOAD})
        self.assertTrue(self.page.refresh_btn.isEnabled())

    def test_invalid_date_request_counts_as_finished_manual_refresh_part(self):
        self.page.analytics_start.blockSignals(True)
        self.page.analytics_end.blockSignals(True)
        self.page.analytics_start.setDate(self.page.analytics_end.date().addDays(1))
        self.page.analytics_end.blockSignals(False)
        self.page.analytics_start.blockSignals(False)

        with mock.patch.object(client, "run_bg") as run_bg:
            self.page.refresh_all()

        self.assertEqual(run_bg.call_count, 2)
        self.assertFalse(self.page.refresh_btn.isEnabled())
        self.page._on("acct_bal", {"seq": self.page._balance_seq, "balance": 88})
        self.assertFalse(self.page.refresh_btn.isEnabled())
        self.page._on(
            "acct_ledger",
            {"seq": self.page._ledger_seq, "payload": {"ok": True, "ledger": [], "pagination": {"page": 1, "pageSize": 20, "total": 0, "totalPages": 0}}},
        )

        self.assertTrue(self.page.refresh_btn.isEnabled())
        self.assertIn("开始日期不能晚于结束日期", self.page.analytics_error.text())
        self.assertIn("错误编号", self.page.analytics_error.text())

    def test_hiding_page_cancels_manual_refresh_busy_state(self):
        with mock.patch.object(client, "run_bg"):
            self.page.refresh_all()

        self.page.hideEvent(QtGui.QHideEvent())

        self.assertTrue(self.page.refresh_btn.isEnabled())
        self.assertEqual(self.page.refresh_btn.text(), "刷新")

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

    def test_ledger_range_error_shows_actionable_message_without_error_id(self):
        self.page._ledger_seq = 1
        self.page._on(
            "acct_ledger",
            {
                "seq": 1,
                "payload": {
                    "ok": False,
                    "error": "date_range_too_large",
                    "message": "查询范围最多 366 天",
                    "errorId": "err-range",
                },
            },
        )

        self.assertEqual(self.page.ledger_error.text(), "查询范围最多366天，请重试")
        self.assertNotIn("错误编号", self.page.ledger_error.text())
        self.assertNotIn("err-range", self.page.ledger_error.text())

    def test_ledger_renders_normalized_rows_unknown_balance_without_detail_tooltip(self):
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
        self.assertEqual(self.page.ltable.item(0, 2).text(), "seedance-2.0")
        self.assertEqual(self.page.ltable.item(0, 3).toolTip(), "")
        self.assertEqual(self.page.ltable.item(0, 4).foreground().color().name(), "#ef5555")

    def test_ledger_table_centers_header_loading_and_row_items(self):
        header_alignment = self.page.ltable.horizontalHeader().defaultAlignment()
        self.assertEqual(header_alignment & QtCore.Qt.AlignHCenter, QtCore.Qt.AlignHCenter)

        self.page._set_ledger_loading_row()
        for column in range(self.page.ltable.columnCount()):
            item = self.page.ltable.item(0, column)
            self.assertIsNotNone(item)
            self.assertEqual(item.textAlignment() & QtCore.Qt.AlignHCenter, QtCore.Qt.AlignHCenter)

        self.page._ledger_seq = 4
        self.page._on(
            "acct_ledger",
            {
                "seq": 4,
                "payload": {
                    "ok": True,
                    "ledger": [{
                        "createdAt": "2026-07-31T12:05:00+08:00",
                        "typeLabel": "模型调用",
                        "modelId": "gemini-3.1-pro-preview",
                        "detail": "chat completion",
                        "change": -0.0016,
                        "balanceAfter": 9.9984,
                        "statusLabel": "已扣费",
                    }],
                    "pagination": {"page": 1, "pageSize": 20, "total": 1, "totalPages": 1},
                },
            },
        )

        for column in range(self.page.ltable.columnCount()):
            item = self.page.ltable.item(0, column)
            self.assertIsNotNone(item)
            self.assertEqual(item.textAlignment() & QtCore.Qt.AlignHCenter, QtCore.Qt.AlignHCenter)

    def test_ledger_table_renders_lk888_four_decimal_actual_charge(self):
        self.page._ledger_seq = 4
        self.page._on(
            "acct_ledger",
            {
                "seq": 4,
                "payload": {
                    "ok": True,
                    "ledger": [{
                        "createdAt": "2026-07-31T12:05:00+08:00",
                        "typeLabel": "other",
                        "modelId": "gemini-3.1-pro-preview",
                        "detail": "LK888 actual charge",
                        "change": -0.0016,
                        "balanceAfter": 9.9984,
                        "statusLabel": "charged",
                    }],
                    "pagination": {"page": 1, "pageSize": 20, "total": 1, "totalPages": 1},
                },
            },
        )

        self.assertEqual(self.page.ltable.item(0, 4).text(), "-0.0016")
        self.assertEqual(self.page.ltable.item(0, 5).text(), "9.9984")
        self.assertEqual(self.page.ltable.item(0, 3).text(), "工作流助手聊天")

    def test_ledger_table_stretches_detail_column_to_fill_available_width(self):
        header = self.page.ltable.horizontalHeader()

        self.assertEqual(header.sectionResizeMode(3), QtWidgets.QHeaderView.Stretch)
        for column in (0, 1, 2, 4, 5, 6):
            self.assertEqual(header.sectionResizeMode(column), QtWidgets.QHeaderView.ResizeToContents)

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

    def test_successful_analytics_balance_wins_over_late_legacy_balance(self):
        owner_payload = dict(ANALYTICS_PAYLOAD)
        owner_payload["metrics"] = dict(ANALYTICS_PAYLOAD["metrics"], balance="inf")
        self.page._analytics_seq = 1

        self.page._on("acct_bal", {"balance": 0})
        self.assertEqual(self.page.bal_lab.text(), "0")
        self.page._on("acct_analytics", {"seq": 1, "payload": owner_payload})
        self.assertEqual(self.page.bal_lab.text(), "∞ 运营方")

        self.page._on("acct_bal", {"balance": 0})
        self.assertEqual(self.page.bal_lab.text(), "∞ 运营方")


if __name__ == "__main__":
    unittest.main()
