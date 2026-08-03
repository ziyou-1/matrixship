from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


class AssetLibrarySharedButtonTest(unittest.TestCase):
    def test_asset_library_hides_shared_library_switch(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("class AssetLibraryPage")
        end = source.index("class ", start + 1)
        block = source[start:end]

        self.assertNotIn('("shared", "漫剧共享库", "platform")', block)
        self.assertNotIn("本地收藏 + 漫剧共享库", block)

    def test_asset_library_imports_assets_and_opens_card_folder(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("class AssetLibraryPage")
        end = source.index("class ", start + 1)
        block = source[start:end]

        self.assertNotIn('QtWidgets.QPushButton("打开文件夹")', block)
        self.assertNotIn('("local", "本地资产", "grid")', block)
        self.assertIn('QtWidgets.QPushButton("导入资产")', block)
        self.assertIn("def import_assets(self):", block)
        self.assertIn("QtWidgets.QFileDialog.getOpenFileNames", block)
        self.assertIn('add_asset(path, kind=kind, prompt="", source="手动导入")', block)
        self.assertIn("def open_asset_folder(self, a):", block)
        self.assertIn("_open_path(os.path.dirname(path))", block)
        self.assertIn('"文件夹"', block)

    def test_asset_card_actions_use_icon_buttons_in_one_row_to_avoid_overlap(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("class AssetLibraryPage")
        end = source.index("class ", start + 1)
        block = source[start:end]

        self.assertIn("def _asset_action_btn(self,", block)
        action_block = block[block.index("def _asset_action_btn(self,"):block.index("def _asset_card(self, a):")]
        self.assertIn('return _round_icon_btn(icon_kind, 30, accent, cb=cb, tip=text)', action_block)
        self.assertNotIn("setText(text)", action_block)
        self.assertNotIn("setFixedWidth(", action_block)
        card_block = block[block.index("def _asset_card(self, a):"):block.index("def use_ref(self, a):")]
        self.assertIn("v.setContentsMargins(8, 10, 8, 10)", card_block)
        self.assertIn("actions = QtWidgets.QHBoxLayout()", card_block)
        self.assertIn("actions.setSpacing(0)", card_block)
        self.assertNotIn("actions = QtWidgets.QGridLayout()", card_block)
        self.assertIn("self._add_asset_action_buttons(actions, buttons)", card_block)
        self.assertNotIn("actions.addWidget(_round_icon_btn", card_block)

    def test_asset_card_actions_are_evenly_distributed_across_row(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("class AssetLibraryPage")
        end = source.index("class ", start + 1)
        block = source[start:end]

        self.assertIn("def _add_asset_action_buttons(self, actions, buttons):", block)
        helper = block[
            block.index("def _add_asset_action_buttons(self, actions, buttons):"):
            block.index("def _asset_card(self, a):")
        ]
        self.assertIn("actions.addStretch(1)", helper)
        self.assertIn("for button in buttons:", helper)
        self.assertIn("actions.addWidget(button)", helper)

        card_block = block[block.index("def _asset_card(self, a):"):block.index("def use_ref(self, a):")]
        self.assertIn("actions.setSpacing(0)", card_block)
        self.assertIn("buttons = [", card_block)
        self.assertIn("self._add_asset_action_buttons(actions, buttons)", card_block)
        self.assertNotIn("actions.addStretch()", card_block)

    def test_note_template_asset_cards_do_not_open_json_directly(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("class AssetLibraryPage")
        end = source.index("class ", start + 1)
        block = source[start:end]
        card_block = block[block.index("def _asset_card(self, a):"):block.index("def use_ref(self, a):")]
        buttons_start = card_block.index('if kind == "image":')
        note_start = card_block.index('elif kind == "note_template":', buttons_start)
        note_block = card_block[note_start:card_block.index("        else:", note_start)]

        self.assertNotIn("open_asset(a)", note_block)
        self.assertIn("open_asset_folder(a)", note_block)
        self.assertIn("delete_btn", note_block)

    def test_asset_library_hides_note_template_filter_button(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("class AssetLibraryPage")
        end = source.index("class ", start + 1)
        block = source[start:end]
        filter_start = block.index("# 本地过滤")
        filter_end = block.index("self.scroll = QtWidgets.QScrollArea()", filter_start)
        filter_block = block[filter_start:filter_end]

        self.assertNotIn('"note_template"', filter_block)
        self.assertNotIn("图文模板", filter_block)
        self.assertIn('elif kind == "note_template":', block)

    def test_asset_library_groups_local_assets_by_date(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("class AssetLibraryPage")
        end = source.index("class ", start + 1)
        block = source[start:end]
        build = block[block.index("def _build_local(self):"):block.index("def _asset_action_btn(self,")]

        self.assertIn("def _asset_timestamp(self, a):", block)
        self.assertIn("def _asset_day_label(self, ts):", block)
        self.assertIn("def _asset_time_label(self, a):", block)
        self.assertIn("def _asset_date_header(self, label, count):", block)
        self.assertIn("items.sort(key=self._asset_timestamp, reverse=True)", build)
        self.assertIn("for label, group in self._group_assets_by_day(items):", build)
        self.assertIn("self.grid.addWidget(self._asset_date_header(label, len(group)), row, 0, 1, cols)", build)

    def test_asset_cards_show_created_time(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("class AssetLibraryPage")
        end = source.index("class ", start + 1)
        block = source[start:end]
        card_block = block[block.index("def _asset_card(self, a):"):block.index("def use_ref(self, a):")]

        self.assertIn("time_lab = QtWidgets.QLabel(self._asset_time_label(a))", card_block)
        self.assertIn("v.addWidget(time_lab)", card_block)

    def test_add_asset_records_created_at_for_time_grouping(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("def add_asset(")
        end = source.index("def remove_asset(", start)
        block = source[start:end]

        self.assertIn("now = time.time()", block)
        self.assertIn('"createdAt": now', block)

    def test_text_assets_are_removed_from_asset_library(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        load_start = source.index("def load_assets():")
        load_end = source.index("def save_assets():", load_start)
        load_block = source[load_start:load_end]
        start = source.index("class AssetLibraryPage")
        end = source.index("class ", start + 1)
        block = source[start:end]
        import_block = block[block.index("def import_assets(self):"):block.index("def _asset_timestamp(self, a):")]
        card_block = block[block.index("def _asset_card(self, a):"):block.index("def use_ref(self, a):")]

        self.assertIn('x.get("kind") != "text"', load_block)
        self.assertIn("save_assets()", load_block)
        self.assertNotIn('("text", "文本", "publish")', block)
        self.assertNotIn("text_exts", import_block)
        self.assertNotIn('kind = "text"', import_block)
        self.assertNotIn('elif kind == "text":', card_block)
        self.assertNotIn('thumb.setText("文本")', card_block)
        self.assertNotIn('(a.get("path") if a.get("kind") == "text" else "")', block)

    def test_agent_reference_thumbnail_shows_inline_usage_hint(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("class ProductGenPage")
        end = source.index("class AssetPickerDialog", start)
        block = source[start:end]
        method = block[
            block.index("def _make_ref_cell(self, path, i):"):
            block.index("def _make_ref_add_cell(self):")
        ]

        self.assertIn('btn.setToolTip("")', method)
        self.assertIn('"点击替换 / 右键删除"', method)
        self.assertIn('"%s\\n%s" % (self._ref_label(i), "点击替换 / 右键删除")', method)
        self.assertNotIn("os.path.basename(path)", method)

    def test_round_icon_buttons_lock_their_own_width(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("def _round_icon_btn(")
        end = source.index("def _fmt_ratio", start)
        block = source[start:end]

        self.assertIn("b.setFixedSize(size, size)", block)
        self.assertIn("b.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)", block)
        self.assertIn('"padding:0;min-width:%dpx;max-width:%dpx;min-height:%dpx;max-height:%dpx;', block)
        self.assertIn("% (size, size, size, size, size // 2)", block)

    def test_video_asset_card_prefers_saved_thumbnail_metadata(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("class AssetLibraryPage")
        end = source.index("class ", start + 1)
        block = source[start:end]
        card_block = block[block.index("def _asset_card(self, a):"):block.index("def use_ref(self, a):")]

        self.assertIn('poster = a.get("thumbnail") or a.get("preview") or ""', card_block)
        self.assertIn('_thumb_pixmap(poster, 212, 158, 10)', card_block)
        self.assertIn("_video_thumb_pixmap(path, 212, 158, 10)", card_block)

    def test_collected_reference_video_card_exposes_breakdown_text_action(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("class AssetLibraryPage")
        end = source.index("class ", start + 1)
        block = source[start:end]
        card_block = block[block.index("def _asset_card(self, a):"):block.index("def use_ref(self, a):")]

        self.assertIn("is_collected_reference", card_block)
        self.assertIn("breakdown_path", card_block)
        self.assertIn('"文本"', card_block)
        self.assertIn("open_asset_text(a)", card_block)

    def test_text_viewer_can_send_breakdown_to_video_replacement(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        start = source.index("class AssetLibraryPage")
        end = source.index("class ", start + 1)
        block = source[start:end]

        self.assertIn("def open_asset_text(self, a):", block)
        method = block[block.index("def open_asset_text(self, a):"):block.index("def open_asset_folder(self, a):")]
        self.assertIn('"按此视频改造"', method)
        self.assertIn("_reference_breakdown_to_replacement_payload", method)
        self.assertIn('BRIDGE.payload.emit("video_replace_start"', method)
        self.assertIn('BRIDGE.payload.emit("goto_nav", "🧬 同款替换")', method)
        self.assertNotIn('BRIDGE.payload.emit("breakdown_to_product_video"', method)
        self.assertNotIn('BRIDGE.payload.emit("goto_nav", "🛍️ Agent.模式")', method)


if __name__ == "__main__":
    unittest.main()
