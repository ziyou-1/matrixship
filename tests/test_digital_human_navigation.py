from pathlib import Path
import importlib.util
import os
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_client_module():
    spec = importlib.util.spec_from_file_location("matrix_native_client_under_test", CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DigitalHumanNavigationTest(unittest.TestCase):
    def test_native_content_production_menu_exposes_digital_human_page(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn('("🧑 数字人口播", lambda: DigitalHumanPage())', src)
        self.assertNotIn("🧑‍💼 数字人口播", src)

    def test_breakdown_seed_prefers_transcript_and_builds_editable_avatar_description(self):
        client = load_client_module()
        seed = client._digital_human_seed_from_breakdown({
            "sourceUrl": "https://example.test/video/1",
            "visual": "画面里是年轻女主播，白色衬衫，明亮厨房，手持护肤品讲解。",
            "transcript": {
                "text": "[00:00.000-00:03.000] 今天给大家看这个护肤品的真实使用感。\n"
                        "[00:03.000-00:06.000] 质地清爽，适合通勤前快速护理。"
            },
        }, "## 字幕与口播\n备用报告")

        self.assertIn("真实使用感", seed["script"])
        self.assertIn("年轻女主播", seed["avatarDescription"])
        self.assertIn("明亮厨房", seed["avatarDescription"])
        self.assertEqual(seed["sourceUrl"], "https://example.test/video/1")

    def test_digital_human_page_accepts_breakdown_seed_without_generating_media(self):
        client = load_client_module()
        previous_bridge = client.BRIDGE
        page = None
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(
                os.environ, {"QT_QPA_PLATFORM": "offscreen"}, clear=False):
            app = client.QtWidgets.QApplication.instance()
            if app is None:
                app = client.QtWidgets.QApplication([])
            client.BRIDGE = client.Bridge()
            page = client.DigitalHumanPage()
            try:
                client.BRIDGE.payload.emit("digital_human_seed", {
                    "topic": "https://example.test/video/1",
                    "script": "这是从分解结果带来的口播稿。",
                    "avatarDescription": "亲和力强的年轻女主播，棚拍白底，正脸清晰。",
                    "sourceUrl": "https://example.test/video/1",
                })
                app.processEvents()

                self.assertEqual(page.topic.text(), "https://example.test/video/1")
                self.assertEqual(page.avatar_desc.text(), "亲和力强的年轻女主播，棚拍白底，正脸清晰。")
                self.assertIn("分解结果带来的口播稿", page.text.toPlainText())
                self.assertIn("可修改", page.status.text())
                self.assertIsNone(page._avatar_url)
            finally:
                if page is not None:
                    page.deleteLater()
                client.BRIDGE = previous_bridge
                del app

    def test_tts_upload_ui_is_hidden_by_default_and_restorable(self):
        client = load_client_module()
        previous_bridge = client.BRIDGE
        disabled_page = None
        enabled_page = None
        with mock.patch.dict(
            os.environ,
            {"QT_QPA_PLATFORM": "offscreen"},
            clear=False,
        ):
            app = client.QtWidgets.QApplication.instance()
            if app is None:
                app = client.QtWidgets.QApplication([])
            client.BRIDGE = client.Bridge()
            try:
                with mock.patch.dict(
                    os.environ,
                    {"MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED": "0"},
                    clear=False,
                ):
                    disabled_page = client.DigitalHumanPage()
                self.assertTrue(disabled_page.b_upload_sound.isHidden())
                self.assertTrue(disabled_page.sound_frame.isHidden())
                self.assertIn("自动合成", disabled_page.asset_status.text())
                self.assertNotIn("TTS 声音可选", disabled_page.asset_status.text())

                with mock.patch.dict(
                    os.environ,
                    {"MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED": "1"},
                    clear=False,
                ):
                    enabled_page = client.DigitalHumanPage()
                self.assertFalse(enabled_page.b_upload_sound.isHidden())
                self.assertFalse(enabled_page.sound_frame.isHidden())
                self.assertIn("TTS 声音可选", enabled_page.asset_status.text())
            finally:
                if disabled_page is not None:
                    disabled_page.deleteLater()
                if enabled_page is not None:
                    enabled_page.deleteLater()
                client.BRIDGE = previous_bridge
                del app

    def test_digital_human_generation_prefers_public_avatar_url(self):
        client = load_client_module()
        previous_bridge = client.BRIDGE
        page = None
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(
                os.environ, {"QT_QPA_PLATFORM": "offscreen"}, clear=False):
            avatar = Path(td) / "avatar.png"
            avatar.write_bytes(b"fake-image")
            app = client.QtWidgets.QApplication.instance()
            if app is None:
                app = client.QtWidgets.QApplication([])
            client.BRIDGE = client.Bridge()
            page = client.DigitalHumanPage()
            try:
                client.BRIDGE.payload.emit("dh_asset", {
                    "ok": True,
                    "kind": "avatar",
                    "url": "https://cdn.example.com/avatar.png",
                    "path": str(avatar),
                })
                app.processEvents()
                page.text.setPlainText("这是一段测试口播稿。")

                with mock.patch.object(client, "generate_digital_human") as generate:
                    page.gen()

                generate.assert_called_once()
                self.assertEqual(generate.call_args.args[0], "https://cdn.example.com/avatar.png")
                self.assertEqual(generate.call_args.args[1], "这是一段测试口播稿。")
            finally:
                if page is not None:
                    page.deleteLater()
                client.BRIDGE = previous_bridge
                del app

    def test_digital_human_generation_falls_back_to_local_avatar_path(self):
        client = load_client_module()
        previous_bridge = client.BRIDGE
        page = None
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(
                os.environ, {"QT_QPA_PLATFORM": "offscreen"}, clear=False):
            avatar = Path(td) / "avatar.png"
            avatar.write_bytes(b"fake-image")
            app = client.QtWidgets.QApplication.instance()
            if app is None:
                app = client.QtWidgets.QApplication([])
            client.BRIDGE = client.Bridge()
            page = client.DigitalHumanPage()
            try:
                client.BRIDGE.payload.emit("dh_asset", {
                    "ok": True,
                    "kind": "avatar",
                    "url": "http://127.0.0.1:9080/avatar.png",
                    "path": str(avatar),
                })
                app.processEvents()
                page.text.setPlainText("这是一段测试口播稿。")

                with mock.patch.object(client, "generate_digital_human") as generate:
                    page.gen()

                generate.assert_called_once()
                self.assertEqual(generate.call_args.args[0], str(avatar))
            finally:
                if page is not None:
                    page.deleteLater()
                client.BRIDGE = previous_bridge
                del app

    def test_tts_voice_falls_back_to_doubao_when_gemini_tts_fails(self):
        client = load_client_module()
        with mock.patch.object(client, "lk888_media_task",
                               side_effect=RuntimeError("gemini-2.5-pro-preview-tts 未拿到任务ID")), \
                mock.patch.object(client, "lk888_tts", return_value="https://cdn.example.com/fallback.mp3") as fallback, \
                mock.patch.object(client, "json_log") as write_log:
            url = client.lk888_tts_voice("测试口播", voice_id="Zephyr")

        self.assertEqual(url, "https://cdn.example.com/fallback.mp3")
        fallback.assert_called_once_with("测试口播", progress=None)
        write_log.assert_called_once()
        self.assertEqual(write_log.call_args.args[1], "digital_human_tts_voice_fallback")


if __name__ == "__main__":
    unittest.main()
