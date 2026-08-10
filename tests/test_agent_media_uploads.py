# -*- coding: utf-8 -*-
"""Agent.模式 各模型上传框（图片/视频/音频）与真实 LK888 参数一一对应的测试。

分两层：
  1) 纯函数层——_agent_video_media_requirements / _agent_video_payload 的契约与字段路由；
  2) UI 层——ProductGenPage 在 offscreen Qt 下真实实例化，断言视频/音频上传按钮
     随所选模型显隐、pick/clear 生效、送生成的 entry 带上 referenceAudio。
真实字段来自 GET /v1/skills/models/{name} 的实测参数定义（image_url/video_url/audio_url 等）。
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_client_module(name="mnc_media_uploads_test"):
    spec = importlib.util.spec_from_file_location(name, CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentMediaContractTest(unittest.TestCase):
    """契约 + payload 字段（纯函数，无需 Qt）。"""

    @classmethod
    def setUpClass(cls):
        cls.m = load_client_module("mnc_media_contract_test")

    def test_omni_reference_models_declare_image_video_audio(self):
        for model in ("hailuo-h3-quannengcankao", "kwvideo-v2-quannengcankao",
                      "doubao-seedance-2-5-quannengcankao"):
            req = self.m._agent_video_media_requirements(model)
            self.assertEqual("image_url", req["image_field"], model)
            self.assertEqual("video_url", req["video_field"], model)
            self.assertEqual("audio_url", req["audio_field"], model)
            self.assertGreater(req["video_limit"], 0, model)
            self.assertGreater(req["audio_limit"], 0, model)
            self.assertTrue(req["image_as_array"], model)
            self.assertTrue(req["video_as_array"], model)
            self.assertTrue(req["audio_as_array"], model)

    def test_omni_payload_uses_url_array_fields_only(self):
        p = self.m._agent_video_payload(
            "hailuo-h3-quannengcankao", "prompt", 10, "16:9",
            ["https://x/a.jpg", "https://x/b.jpg"], "https://x/c.mp4", "https://x/d.mp3")
        self.assertEqual(["https://x/a.jpg", "https://x/b.jpg"], p["params"]["image_url"])
        self.assertEqual(["https://x/c.mp4"], p["params"]["video_url"])
        self.assertEqual(["https://x/d.mp3"], p["params"]["audio_url"])
        self.assertEqual("768P", p["params"]["resolution"])
        for stray in ("images", "image_urls", "reference_images", "video", "audio"):
            self.assertNotIn(stray, p["params"])

    def test_seedance25_allows_audio_only_generation(self):
        p = self.m._agent_video_payload(
            "doubao-seedance-2-5-quannengcankao", "prompt", 10, "16:9", [], "", "https://x/d.mp3")
        self.assertEqual(["https://x/d.mp3"], p["params"]["audio_url"])

    def test_h3_and_sd20_reject_audio_only(self):
        for model in ("hailuo-h3-quannengcankao", "kwvideo-v2-quannengcankao"):
            with self.assertRaisesRegex(RuntimeError, "至少上传"):
                self.m._agent_video_payload(model, "p", 10, "16:9", [], "", "https://x/d.mp3")

    def test_wan26_shouzheng_first_frame_and_audio_are_scalar(self):
        req = self.m._agent_video_media_requirements("wan2.6-shouzheng")
        self.assertEqual("img_url", req["image_field"])
        self.assertFalse(req["image_as_array"])  # 单首帧 -> 标量
        self.assertFalse(req["audio_as_array"])
        p = self.m._agent_video_payload(
            "wan2.6-shouzheng", "p", 6, "16:9", ["https://x/a.jpg"], "", "https://x/d.mp3")
        self.assertEqual("https://x/a.jpg", p["params"]["img_url"])
        self.assertEqual("https://x/d.mp3", p["params"]["audio_url"])

    def test_kling_motion_control_requires_image_and_video_as_scalars(self):
        m = self.m
        with self.assertRaisesRegex(RuntimeError, "参考图"):
            m._agent_video_payload("kling-motion-control", "p", 10, "16:9", [], "https://x/c.mp4", "")
        with self.assertRaisesRegex(RuntimeError, "参考视频"):
            m._agent_video_payload("kling-motion-control", "p", 10, "16:9", ["https://x/a.jpg"], "", "")
        p = m._agent_video_payload(
            "kling-motion-control", "p", 10, "16:9", ["https://x/a.jpg"], "https://x/c.mp4", "")
        self.assertEqual("https://x/a.jpg", p["params"]["image_url"])   # 单数字段 -> 标量
        self.assertEqual("https://x/c.mp4", p["params"]["video_url"])
        self.assertEqual("std", p["params"]["mode"])
        self.assertEqual("video", p["params"]["character_orientation"])

    def test_wan22_animate_mix_requires_image_and_video(self):
        m = self.m
        with self.assertRaisesRegex(RuntimeError, "参考视频"):
            m._agent_video_payload("wan2.2-animate-mix", "p", 10, "16:9", ["https://x/a.jpg"], "", "")
        p = m._agent_video_payload(
            "wan2.2-animate-mix", "p", 10, "16:9", ["https://x/a.jpg"], "https://x/c.mp4", "")
        self.assertEqual("https://x/a.jpg", p["params"]["image_url"])
        self.assertEqual("https://x/c.mp4", p["params"]["video_url"])
        self.assertEqual("wan-std", p["params"]["mode"])

    def test_omni_videoref_images_array_video_scalar(self):
        p = self.m._agent_video_payload(
            "kling-v3-omni-videoref", "p", 10, "16:9", ["https://x/a.jpg"], "https://x/c.mp4", "")
        self.assertEqual(["https://x/a.jpg"], p["params"]["images"])
        self.assertEqual("https://x/c.mp4", p["params"]["video"])
        self.assertEqual("feature", p["params"]["refer_type"])

    def test_wan27_xuxie_clips_is_array_and_required(self):
        with self.assertRaisesRegex(RuntimeError, "参考视频"):
            self.m._agent_video_payload("wan2.7-xuxie", "p", 6, "16:9", [], "", "")
        p = self.m._agent_video_payload("wan2.7-xuxie", "p", 6, "16:9", [], "https://x/c.mp4", "")
        self.assertEqual(["https://x/c.mp4"], p["params"]["clips"])

    def test_hailuo_h3_zaishengcheng_requires_source_video(self):
        with self.assertRaisesRegex(RuntimeError, "参考视频"):
            self.m._agent_video_payload("hailuo-h3-zaishengcheng", "p", 5, "16:9", [], "", "")
        p = self.m._agent_video_payload(
            "hailuo-h3-zaishengcheng", "p", 5, "16:9", ["https://x/a.jpg"], "https://x/c.mp4", "")
        self.assertEqual("https://x/c.mp4", p["params"]["video_url"])   # 单源视频 -> 标量
        self.assertEqual(["https://x/a.jpg"], p["params"]["image_url"])  # 可选原参考图（≤9）-> 数组

    def test_wan27_cankaosheng_reference_fields_corrected(self):
        # 回归：此前误写 images/video，模型（reference_urls/reference_video）收不到参考素材
        p = self.m._agent_video_payload(
            "wan2.7-cankaosheng", "p", 6, "16:9", ["https://x/a.jpg"], "https://x/c.mp4", "")
        self.assertEqual(["https://x/a.jpg"], p["params"]["reference_urls"])
        self.assertEqual("https://x/c.mp4", p["params"]["reference_video"])
        self.assertNotIn("images", p["params"])
        self.assertNotIn("video", p["params"])

    def test_legacy_video_model_payload_unchanged(self):
        p = self.m._agent_video_payload(
            "doubao-seedance-1-5-pro-251215", "p", 10, "16:9", ["https://x/a.jpg"], "", "")
        self.assertEqual(["https://x/a.jpg"], p["params"]["images"])
        self.assertIn("image_urls", p["params"])
        self.assertIn("reference_images", p["params"])

    def test_run_video_uploads_audio_and_routes_to_payload(self):
        m = self.m

        def fake_upload(path, title, mtype, metadata=None):
            return ("https://cdn.example.com/%s.bin" % mtype, {"ok": True})

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "a.mp3"; audio.write_bytes(b"aud")
            image = Path(tmp) / "i.jpg"; image.write_bytes(b"img")
            entry = {
                "id": "pg-audio-1", "mode": "video", "prompt": "p", "visiblePrompt": "p",
                "model": "hailuo-h3-quannengcankao", "duration": 10, "aspect_ratio": "16:9",
                "refs": [str(image)], "referenceAudio": str(audio),
            }
            with mock.patch.object(m, "data_dir", return_value=tmp), \
                    mock.patch.object(m, "_prodgen_refs_desc", return_value=""), \
                    mock.patch.object(m, "update_prodgen"), \
                    mock.patch.object(m, "upload_asset_url", side_effect=fake_upload) as up, \
                    mock.patch.object(m, "lk888_media_task", return_value="https://cdn.example.com/out.mp4") as media, \
                    mock.patch.object(m, "_wf_download"):
                m._prodgen_run_video(entry)

        payload = media.call_args.args[1]
        self.assertEqual(["https://cdn.example.com/audio.bin"], payload["params"]["audio_url"])
        self.assertEqual(["https://cdn.example.com/image.bin"], payload["params"]["image_url"])
        self.assertIn("audio", [call.args[2] for call in up.call_args_list])


class AgentMediaUploadUITest(unittest.TestCase):
    """真实实例化 ProductGenPage（offscreen），断言上传按钮随模型显隐与状态回填。"""

    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6 import QtWidgets  # noqa: F401
        cls.QtWidgets = QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.m = load_client_module("mnc_media_upload_ui_test")
        cls.m.BRIDGE = cls.m.Bridge()

    def _page(self):
        return self.m.ProductGenPage()

    def test_audio_and_video_buttons_follow_model_media_contract(self):
        p = self._page()
        p._mode = "video"

        p._video_model = "hailuo-h3-quannengcankao"; p._sync_model_ui()
        self.assertFalse(p.ref_audio_btn.isHidden())   # 全能参考：图+视频+音频
        self.assertFalse(p.ref_video_btn.isHidden())

        p._video_model = "wan2.6-shouzheng"; p._sync_model_ui()
        self.assertFalse(p.ref_audio_btn.isHidden())   # 有音频、无参考视频
        self.assertTrue(p.ref_video_btn.isHidden())

        p._video_model = "happyhorse-video-edit"; p._sync_model_ui()
        self.assertTrue(p.ref_audio_btn.isHidden())    # 有视频、无音频
        self.assertFalse(p.ref_video_btn.isHidden())

        p._video_model = "doubao-seedance-1-5-pro-251215"; p._sync_model_ui()
        self.assertTrue(p.ref_audio_btn.isHidden())    # 普通视频模型：都不显示
        self.assertTrue(p.ref_video_btn.isHidden())

        p._mode = "image"; p._sync_model_ui()
        self.assertTrue(p.ref_audio_btn.isHidden())    # 图片模式永不显示
        self.assertTrue(p.ref_video_btn.isHidden())

    def test_pick_and_clear_reference_audio(self):
        p = self._page()
        with mock.patch.object(self.m.QtWidgets.QFileDialog, "getOpenFileName",
                               return_value=("C:/x/a.mp3", "")):
            p.pick_reference_audio()
        self.assertEqual("C:/x/a.mp3", p._reference_audio)
        p.clear_reference_audio()
        self.assertEqual("", p._reference_audio)

    def test_send_carries_reference_audio_and_video_into_entry(self):
        p = self._page()
        p._mode = "video"
        p._video_model = "hailuo-h3-quannengcankao"
        p._reference_audio = "C:/x/a.mp3"
        p._reference_video = "C:/x/v.mp4"
        p.inp.setPlainText("生成一段视频")
        captured = {}
        with mock.patch.object(self.m, "add_prodgen", side_effect=lambda e: captured.update(e)), \
                mock.patch.object(p, "_start"), \
                mock.patch.object(p, "_add_card"):
            p.send()
        self.assertEqual("C:/x/a.mp3", captured.get("referenceAudio"))
        self.assertEqual("C:/x/v.mp4", captured.get("referenceVideo"))

    def test_reedit_restores_reference_audio(self):
        p = self._page()
        p.reedit({
            "mode": "video", "model": "hailuo-h3-quannengcankao",
            "referenceAudio": "C:/x/a.mp3", "referenceVideo": "C:/x/v.mp4", "refs": [],
        })
        self.assertEqual("C:/x/a.mp3", p._reference_audio)
        self.assertEqual("C:/x/v.mp4", p._reference_video)


if __name__ == "__main__":
    unittest.main()
