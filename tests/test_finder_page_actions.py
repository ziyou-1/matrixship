from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


class FinderPageActionsTest(unittest.TestCase):
    def test_finder_page_has_explicit_lead_action_columns(self):
        source = CLIENT.read_text(encoding="utf-8")
        start = source.index("class FinderPage")
        end = source.index("class OutreachPage", start)
        block = source[start:end]

        self.assertIn("QtWidgets.QTableWidget(0, 8)", block)
        for label in ("打开主页", "复制链接", "去私信跟进", "标记已跟进"):
            with self.subTest(label=label):
                self.assertIn(label, block)
        self.assertIn("self.table.setCellWidget(r, 4", block)
        self.assertIn("self.table.setCellWidget(r, 5", block)
        self.assertIn("self.table.setCellWidget(r, 6", block)
        self.assertIn("self.table.setCellWidget(r, 7", block)
        self.assertIn("FINDER_ROW_HEIGHT = 54", block)
        self.assertIn("setDefaultSectionSize(self.FINDER_ROW_HEIGHT)", block)

    def test_finder_actions_copy_open_dm_followup_and_mark_followed(self):
        source = CLIENT.read_text(encoding="utf-8")
        start = source.index("class FinderPage")
        end = source.index("class OutreachPage", start)
        block = source[start:end]

        self.assertIn("def _profile_url_at_row", block)
        self.assertIn("def _copy_profile_link", block)
        self.assertIn("QtWidgets.QApplication.clipboard().setText", block)
        self.assertIn("def _go_dm_followup", block)
        self.assertIn('BRIDGE.payload.emit("dm_followup"', block)
        self.assertIn('BRIDGE.payload.emit("goto_nav", "💬 私信 / AI 销售")', block)
        self.assertIn("def _mark_followed", block)
        self.assertIn('btn.setText("已跟进")', block)

    def test_finder_open_profile_uses_local_executor_account_profile(self):
        source = CLIENT.read_text(encoding="utf-8")
        start = source.index("    def _open_profile", source.index("class FinderPage"))
        end = source.index("\n    def ", start + 10)
        block = source[start:end]

        self.assertIn("account_id = self._require_finder_account()", block)
        self.assertIn("platform = self._pf()", block)
        self.assertIn('local_api("POST", "/api/cloud-login/open-url"', block)
        self.assertIn('"accountId": account_id', block)
        self.assertIn('"url": u', block)
        self.assertIn('"platform": platform', block)
        self.assertNotIn('"platform": self._pf()', block)
        self.assertNotIn("QDesktopServices.openUrl", block)

    def test_finder_action_buttons_are_compact_for_table_cells(self):
        source = CLIENT.read_text(encoding="utf-8")
        start = source.index("class FinderPage")
        end = source.index("class OutreachPage", start)
        block = source[start:end]

        self.assertIn('btn.setObjectName("finderAction")', block)
        self.assertIn("btn.setFixedSize(width, self.FINDER_ACTION_BUTTON_HEIGHT)", block)
        self.assertIn("QtWidgets.QSizePolicy.Fixed", block)
        self.assertIn("QtWidgets.QLabel(text)", block)
        self.assertIn("QLabel#finderAction", block)
        self.assertIn("QtCore.Qt.AlignCenter", block)
        self.assertIn("mousePressEvent", block)
        self.assertNotIn("followed_btn.clicked.connect", block)
        self.assertIn("padding:0", block)
        self.assertIn("max-height:%dpx", block)
        self.assertIn("max-width:%dpx", block)

    def test_finder_action_columns_are_fixed_width_and_wrapped(self):
        source = CLIENT.read_text(encoding="utf-8")
        start = source.index("class FinderPage")
        end = source.index("class OutreachPage", start)
        block = source[start:end]

        self.assertIn("FINDER_ACTION_COLUMN_WIDTHS", block)
        self.assertIn("header.setStretchLastSection(False)", block)
        self.assertIn("QtWidgets.QHeaderView.Fixed", block)
        self.assertIn("self.table.setColumnWidth(c, width)", block)
        self.assertIn("def _action_cell", block)
        self.assertIn("layout.setContentsMargins(self.FINDER_ACTION_CELL_MARGIN_X, 0, self.FINDER_ACTION_CELL_MARGIN_X, 0)", block)
        self.assertIn("layout.setAlignment(QtCore.Qt.AlignCenter)", block)
        self.assertIn("self.table.setCellWidget(r, 4, self._action_cell", block)
        self.assertIn("self.table.setCellWidget(r, 7, self._action_cell", block)

    def test_finder_action_columns_fit_buttons_with_centering_padding(self):
        source = CLIENT.read_text(encoding="utf-8")
        start = source.index("class FinderPage")
        end = source.index("class OutreachPage", start)
        block = source[start:end]

        column_widths = {
            int(col): int(width)
            for col, width in re.findall(r"(\d+):\s*(\d+)", block[block.index("FINDER_ACTION_COLUMN_WIDTHS"):block.index("FINDER_ACTION_BUTTON_WIDTHS")])
        }
        self.assertIn("FINDER_ACTION_CELL_MARGIN_X", block)
        button_widths = {
            label: int(width)
            for label, width in re.findall(r'"([^"]+)":\s*(\d+)', block[block.index("FINDER_ACTION_BUTTON_WIDTHS"):block.index("def __init__")])
        }
        expected = {
            4: ("打开主页", 92),
            5: ("复制链接", 92),
            6: ("去私信跟进", 118),
            7: ("标记已跟进", 118),
        }
        for col, (label, min_button_width) in expected.items():
            with self.subTest(label=label):
                self.assertGreaterEqual(button_widths.get(label, 0), min_button_width)
                self.assertGreaterEqual(column_widths.get(col, 0), button_widths[label] + 12)
        self.assertIn("FINDER_ACTION_CELL_MARGIN_X = 0", block)
        self.assertIn("layout.setContentsMargins(self.FINDER_ACTION_CELL_MARGIN_X, 0, self.FINDER_ACTION_CELL_MARGIN_X, 0)", block)

    def test_finder_action_rows_are_tall_enough_for_rendered_buttons(self):
        source = CLIENT.read_text(encoding="utf-8")
        start = source.index("class FinderPage")
        end = source.index("class OutreachPage", start)
        block = source[start:end]

        row_match = re.search(r"FINDER_ROW_HEIGHT\s*=\s*(\d+)", block)
        button_match = re.search(r"FINDER_ACTION_BUTTON_HEIGHT\s*=\s*(\d+)", block)
        self.assertIsNotNone(row_match)
        self.assertIsNotNone(button_match)
        row_height = int(row_match.group(1))
        button_height = int(button_match.group(1))
        self.assertGreaterEqual(button_height, 32)
        self.assertGreaterEqual(row_height, button_height + 10)
        self.assertIn("self.table.verticalHeader().setDefaultSectionSize(self.FINDER_ROW_HEIGHT)", block)
        self.assertIn("self.table.setRowHeight(r, self.FINDER_ROW_HEIGHT)", block)

    def test_dm_page_accepts_finder_followup_target(self):
        source = CLIENT.read_text(encoding="utf-8")
        start = source.index("class DMPage")
        end = source.index("class CopywritingPage", start)
        block = source[start:end]

        self.assertIn('if tag == "dm_followup":', block)
        self.assertIn("self.target.setText", block)
        self.assertIn("已带入获客线索主页链接", block)

    def test_xhs_lead_does_not_enter_douyin_dm_followup(self):
        source = CLIENT.read_text(encoding="utf-8")
        start = source.index("def _go_dm_followup", source.index("class FinderPage"))
        end = source.index("\n    def ", start + 10)
        block = source[start:end]
        self.assertIn('if self._pf() != "douyin":', block)
        self.assertIn("目前仅支持抖音客户主页", block)
        self.assertIn("return", block)


class FinderAccountLoadingTest(unittest.TestCase):
    def test_growth_page_refreshes_current_inner_tab_accounts(self):
        source = CLIENT.read_text(encoding="utf-8")
        start = source.index("class GrowthPage")
        end = source.index("class TaskCenterPage", start)
        block = source[start:end]

        self.assertIn("self.finder_page = FinderPage()", block)
        self.assertIn("self.outreach_page = OutreachPage()", block)
        self.assertIn("self.tabs.currentChanged.connect(lambda _i: self._show_current())", block)
        self.assertIn("def on_show(self):", block)
        self.assertIn("self._show_current()", block)
        self.assertIn("page = self.tabs.currentWidget()", block)
        self.assertIn("page.on_show()", block)

    def test_finder_and_outreach_account_boxes_show_loading_placeholder(self):
        source = CLIENT.read_text(encoding="utf-8")
        finder_start = source.index("class FinderPage")
        finder_block = source[finder_start:source.index("class OutreachPage", finder_start)]
        outreach_start = source.index("class OutreachPage")
        outreach_block = source[outreach_start:source.index("class GrowthPage", outreach_start)]

        for block in (finder_block, outreach_block):
            self.assertIn('self.account.addItem("正在读取账号...", "")', block)


if __name__ == "__main__":
    unittest.main()
