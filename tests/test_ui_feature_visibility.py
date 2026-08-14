import importlib
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CLIENT = BACKEND / "matrix_native_client.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class UiFeatureVisibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.features = importlib.import_module("platform_features")
        cls.client = importlib.import_module("matrix_native_client")
        cls.app = cls.client.QtWidgets.QApplication.instance()
        if cls.app is None:
            cls.app = cls.client.QtWidgets.QApplication([])

    def unset_flags(self, *names):
        """Run with the named flags absent so packaged defaults are exercised."""
        env = {key: value for key, value in os.environ.items() if key not in names}
        return mock.patch.dict(os.environ, env, clear=True)

    def test_same_style_replacement_is_default_on_and_explicitly_disablable(self):
        self.assertTrue(self.features.video_replacement_enabled({}))
        self.assertFalse(
            self.features.video_replacement_enabled(
                {"MATRIX_VIDEO_REPLACEMENT_ENABLED": "0"}
            )
        )
        self.assertTrue(
            self.features.video_replacement_enabled(
                {"MATRIX_VIDEO_REPLACEMENT_ENABLED": "1"}
            )
        )

    def test_remaining_temporary_ui_features_are_default_off_and_restorable(self):
        self.assertFalse(self.features.pending_publish_ui_enabled({}))
        self.assertFalse(self.features.digital_human_tts_upload_enabled({}))
        self.assertTrue(
            self.features.pending_publish_ui_enabled(
                {"MATRIX_PENDING_PUBLISH_UI_ENABLED": "true"}
            )
        )
        self.assertTrue(
            self.features.digital_human_tts_upload_enabled(
                {"MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED": "on"}
            )
        )

    def test_xhs_capability_filter_preserves_order_and_is_reversible(self):
        capabilities = [
            "douyin.search",
            "xhs.search",
            "douyin.publish",
            "xhs.login",
        ]
        self.assertEqual(
            self.features.filter_xhs_capabilities(
                capabilities,
                {"MATRIX_XHS_ENABLED": "0"},
            ),
            ["douyin.search", "douyin.publish"],
        )
        self.assertEqual(
            self.features.filter_xhs_capabilities(
                capabilities,
                {"MATRIX_XHS_ENABLED": "1"},
            ),
            capabilities,
        )

    def test_account_matrix_platforms_follow_the_xhs_gate(self):
        with self.unset_flags("MATRIX_XHS_ENABLED"):
            self.assertEqual(
                self.client.account_matrix_platform_keys(),
                ("douyin", "xhs"),
            )
        with mock.patch.dict(
            os.environ,
            {"MATRIX_XHS_ENABLED": "0"},
            clear=False,
        ):
            self.assertEqual(
                self.client.account_matrix_platform_keys(),
                ("douyin",),
            )
        with mock.patch.dict(
            os.environ,
            {"MATRIX_XHS_ENABLED": "1"},
            clear=False,
        ):
            self.assertEqual(
                self.client.account_matrix_platform_keys(),
                ("douyin", "xhs"),
            )

    def test_publish_workspace_hides_pending_queue_by_default(self):
        widget_factory = self.client.QtWidgets.QWidget
        with mock.patch.object(self.client, "PublishPage", widget_factory), \
                mock.patch.object(self.client, "PendingPublishPage", widget_factory), \
                mock.patch.dict(
                    os.environ,
                    {"MATRIX_PENDING_PUBLISH_UI_ENABLED": "0"},
                    clear=False,
                ):
            page = self.client.PublishWorkspacePage()
        try:
            self.assertEqual(
                [page.tabs.tabText(index) for index in range(page.tabs.count())],
                ["素材库与发布"],
            )
            self.assertNotIn("📤 待发布队列", page.nav_aliases)
        finally:
            page.deleteLater()

    def test_publish_workspace_restores_pending_queue_when_enabled(self):
        widget_factory = self.client.QtWidgets.QWidget
        with mock.patch.object(self.client, "PublishPage", widget_factory), \
                mock.patch.object(self.client, "PendingPublishPage", widget_factory), \
                mock.patch.dict(
                    os.environ,
                    {"MATRIX_PENDING_PUBLISH_UI_ENABLED": "1"},
                    clear=False,
                ):
            page = self.client.PublishWorkspacePage()
        try:
            self.assertEqual(
                [page.tabs.tabText(index) for index in range(page.tabs.count())],
                ["素材库与发布", "待发布队列"],
            )
            self.assertIn("📤 待发布队列", page.nav_aliases)
        finally:
            page.deleteLater()

    def test_same_style_replacement_navigation_is_enabled_by_default(self):
        name = "🧬 同款替换"
        with self.unset_flags("MATRIX_VIDEO_REPLACEMENT_ENABLED"):
            self.assertTrue(self.client.nav_feature_enabled(name))
        with mock.patch.dict(
            os.environ,
            {"MATRIX_VIDEO_REPLACEMENT_ENABLED": "0"},
            clear=False,
        ):
            self.assertFalse(self.client.nav_feature_enabled(name))
        with mock.patch.dict(
            os.environ,
            {"MATRIX_VIDEO_REPLACEMENT_ENABLED": "1"},
            clear=False,
        ):
            self.assertTrue(self.client.nav_feature_enabled(name))

    def test_same_style_replacement_sidebar_is_clickable_by_default(self):
        name = "🧬 同款替换"
        button = mock.Mock()
        shell = type(
            "Shell",
            (),
            {"nav_btns": [button], "_nav_names": [name]},
        )()
        with mock.patch.object(self.client, "nav_allowed", return_value=True), \
                self.unset_flags("MATRIX_VIDEO_REPLACEMENT_ENABLED"):
            self.client.MainWindow._apply_role_visibility(shell)

        button.setVisible.assert_called_once_with(True)
        button.setEnabled.assert_called_once_with(True)

    def test_same_style_replacement_sidebar_stays_visible_but_disabled(self):
        name = "🧬 同款替换"
        button = mock.Mock()
        shell = type(
            "Shell",
            (),
            {"nav_btns": [button], "_nav_names": [name]},
        )()
        with mock.patch.object(self.client, "nav_allowed", return_value=True), \
                mock.patch.dict(
                    os.environ,
                    {"MATRIX_VIDEO_REPLACEMENT_ENABLED": "0"},
                    clear=False,
                ):
            self.client.MainWindow._apply_role_visibility(shell)

        button.setVisible.assert_called_once_with(True)
        button.setEnabled.assert_called_once_with(False)

    def test_programmatic_same_style_replacement_navigation_is_blocked(self):
        name = "🧬 同款替换"
        shell = type(
            "Shell",
            (),
            {
                "_nav_labels": {name: 0},
                "_nav_names": [name],
                "_nav": mock.Mock(),
            },
        )()
        with mock.patch.dict(
            os.environ,
            {"MATRIX_VIDEO_REPLACEMENT_ENABLED": "0"},
            clear=False,
        ):
            self.client.MainWindow._goto_nav(shell, "goto_nav", name)

        shell._nav.assert_not_called()

    def test_secondary_replacement_entries_follow_the_replacement_gate(self):
        source = CLIENT.read_text(encoding="utf-8")
        self.assertIn("self.b_replace.setVisible(video_replacement_enabled())", source)
        self.assertIn("go.setVisible(video_replacement_enabled())", source)
        self.assertIn("use_btn.setVisible(video_replacement_enabled())", source)
        self.assertIn("SAME_STYLE_REPLACEMENT_TOOLTIP", source)

    def test_runtime_templates_match_the_shipped_flag_defaults(self):
        defaults = {
            "MATRIX_XHS_ENABLED": "1",
            "MATRIX_VIDEO_REPLACEMENT_ENABLED": "1",
            "MATRIX_PENDING_PUBLISH_UI_ENABLED": "0",
            "MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED": "0",
        }
        env_files = {
            BACKEND / ".env.example": "{name}={value}",
            BACKEND / ".env.dev": "export {name}={value}",
            BACKEND / ".env.prod": "{name}={value}",
        }
        checked = 0
        for path, expected_pattern in env_files.items():
            if not path.exists():
                # .env.dev/.env.prod are deployment-local and not tracked in git.
                continue
            checked += 1
            contents = path.read_text(encoding="utf-8-sig")
            for name, value in defaults.items():
                with self.subTest(path=path.name, flag=name):
                    self.assertIn(
                        expected_pattern.format(name=name, value=value),
                        contents,
                    )
        self.assertGreaterEqual(checked, 1, "no runtime env template was checked")

        compose = (ROOT / "docker-compose.prod.yml").read_text(
            encoding="utf-8-sig"
        )
        for name, value in defaults.items():
            with self.subTest(path="docker-compose.prod.yml", flag=name):
                self.assertIn(f"{name}: ${{{name}:-{value}}}", compose)


if __name__ == "__main__":
    unittest.main()
