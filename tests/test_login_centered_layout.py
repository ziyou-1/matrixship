from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


class LoginCenteredLayoutTest(unittest.TestCase):
    def test_login_view_centers_full_marketing_and_card_layout(self):
        src = CLIENT.read_text(encoding="utf-8")
        build_ui = src[src.index("    def _build_ui(self):"):src.index("    def _build_hero(self):")]

        self.assertIn("root = QtWidgets.QVBoxLayout(self)", build_ui)
        self.assertIn("content = QtWidgets.QWidget()", build_ui)
        self.assertIn("row = QtWidgets.QHBoxLayout(content)", build_ui)
        self.assertIn("root.addStretch(1)", build_ui)
        self.assertIn("root.addWidget(content, 0, QtCore.Qt.AlignCenter)", build_ui)
        self.assertIn("self._hero = self._build_hero()", build_ui)
        self.assertIn("row.addWidget(self._hero)", build_ui)
        self.assertIn("row.addWidget(self._card)", build_ui)

        self.assertNotIn("self._hero = None", build_ui)
        self.assertNotIn("root.addWidget(self._card, 0, QtCore.Qt.AlignCenter)", build_ui)

    def test_marketing_copy_is_restored_outside_login_card(self):
        src = CLIENT.read_text(encoding="utf-8")
        hero = src[src.index("    def _build_hero(self):"):src.index("    def _build_card(self):")]
        build_card = src[src.index("    def _build_card(self):"):src.index("    def _show_legal_document")]

        self.assertIn('QtWidgets.QLabel("从选题到成片")', hero)
        self.assertIn('GradientLabel("一个人就是一支运营团队"', hero)
        self.assertIn("多平台矩阵", hero)
        self.assertIn("Agent.模式", hero)
        self.assertIn("混剪短视频", hero)
        self.assertIn("工作流助手", hero)
        self.assertIn('title = QtWidgets.QLabel("登录 / 加入企业")', build_card)
        self.assertNotIn('brand_title = QtWidgets.QLabel("云灵星图")', build_card)

    def test_success_evil_eye_transition_is_not_restored_by_layout_changes(self):
        src = CLIENT.read_text(encoding="utf-8")
        login_view = src[src.index("class LoginView"):src.index("\n\nclass MainWindow")]

        self.assertNotIn("LOGIN_SUCCESS_TRANSITION_MS", login_view)
        self.assertNotIn("LOGIN_SUCCESS_FULL_SCREEN_SCALE", login_view)
        self.assertNotIn("_play_success_transition", login_view)
        self.assertNotIn("QParallelAnimationGroup", login_view)


if __name__ == "__main__":
    unittest.main()
