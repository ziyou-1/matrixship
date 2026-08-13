"""声明了视频/音频上传的模型,界面上就得给得了入口。

手写的 `_AGENT_VIDEO_MEDIA_REQUIREMENT_OVERRIDES` 只覆盖了想起来加的 3 个模型,
其余 10 个在 schema 里声明了 video/audio 上传的模型,客户端里连按钮都不出现
(用户:「有的模型可以上传视频,为什么输入框里只能传图片」)。
"""
from pathlib import Path
import importlib.util
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"
FIXTURE = ROOT / "tests" / "fixtures" / "lk888_model_schemas.json"


def load_client_module(name="matrix_native_client_video_upload_contract_test"):
    spec = importlib.util.spec_from_file_location(name, CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentVideoUploadContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_client_module()
        cls.schemas = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_every_model_declaring_a_video_upload_gets_a_nonzero_limit(self):
        missing = []
        for name, schema in sorted(self.schemas.items()):
            if schema.get("type") != "video":
                continue
            form = self.module._agent_schema_form(name, "video", schema, "snapshot")
            declares = {u["media"] for u in form["uploads"]}
            req = self.module._agent_video_media_requirements(name)
            if "video" in declares and req["video_limit"] <= 0:
                missing.append("%s 声明了视频上传但 video_limit=0" % name)
            if "audio" in declares and req["audio_limit"] <= 0:
                missing.append("%s 声明了音频上传但 audio_limit=0" % name)
        self.assertEqual([], missing)

    def test_the_field_name_comes_from_the_schema(self):
        cases = {
            "kling-motion-control": "video_url",
            "wan2.2-animate-mix": "video_url",
            "kling-v3-omni-videoref": "video",
            "wan2.7-xuxie": "clips",
        }
        for model, field in cases.items():
            with self.subTest(model=model):
                self.assertEqual(field, self.module._agent_video_media_requirements(model)["video_field"])

    def test_hand_written_overrides_still_win_over_the_schema(self):
        """覆盖表(线上验证过的必传/字段)优先于 schema 推断。"""
        # wan2.7-cankaosheng:2026-08-10 起覆盖表已修正为真实字段 reference_video。
        # 旧断言写的是 video —— 那其实锁住了一个 bug(参考视频发到 video,模型收不到),
        # 实测 LK888 schema 的字段就是 reference_video,覆盖表现已与之一致。
        self.assertEqual(
            "reference_video",
            self.module._agent_video_media_requirements("wan2.7-cankaosheng")["video_field"])
        # 覆盖表仍然凌驾于 schema:必传视频由覆盖表声明,schema 推断不一定给 required。
        self.assertTrue(self.module._agent_video_media_requirements("kling-motion-control-v3")["video_required"])

    def test_a_model_without_any_video_upload_stays_at_zero(self):
        for model in ("kling-v2-6", "grok-video-3", "veo3.1", "sora-2"):
            with self.subTest(model=model):
                self.assertEqual(0, self.module._agent_video_media_requirements(model)["video_limit"])

    def test_a_plural_field_name_is_sent_as_an_array(self):
        """LK888 自己的 description 样板写死了:复数名参数一律传数组,哪怕只有一个文件。"""
        payload = self.module._agent_video_payload(
            "wan2.7-xuxie", "prompt", 5, "16:9", [], reference_video_url="https://x/a.mp4")

        self.assertEqual(["https://x/a.mp4"], payload["params"]["clips"])

    def test_a_singular_field_name_is_still_sent_as_a_string(self):
        payload = self.module._agent_video_payload(
            "kling-motion-control", "prompt", 5, "16:9", ["https://x/ref.png"],
            reference_video_url="https://x/a.mp4")

        self.assertEqual("https://x/a.mp4", payload["params"]["video_url"])

    def test_audio_reaches_the_payload_under_the_field_the_model_declares(self):
        cases = {
            "kling-avatar-image2video": "sound_file",
            "vidu-mv": "audio_url",
            "wan2.6-shouzheng": "audio_url",
        }
        for model, field in cases.items():
            with self.subTest(model=model):
                payload = self.module._agent_video_payload(
                    model, "prompt", 5, "16:9", ["https://x/ref.png"],
                    reference_audio_url="https://x/voice.mp3")
                self.assertEqual("https://x/voice.mp3", payload["params"][field])

    def test_several_videos_are_sent_when_the_model_takes_several(self):
        """hailuo-h3-quannengcankao:「参考视频最多 3 个」。"""
        videos = ["https://x/a.mp4", "https://x/b.mp4", "https://x/c.mp4"]

        payload = self.module._agent_video_payload(
            "hailuo-h3-quannengcankao", "prompt", 5, "16:9", [], reference_video_url=videos)

        self.assertEqual(videos, payload["params"]["video_url"])

    def test_a_singular_field_with_a_limit_above_one_is_still_an_array(self):
        """hailuo-h3-quannengcankao 的 video_url 是单数名却收 3 个 —— 3 个 URL 塞不进一个字符串。"""
        req = self.module._agent_video_media_requirements("hailuo-h3-quannengcankao")

        self.assertEqual(3, req["video_limit"])
        self.assertTrue(req["video_is_array"])

    def test_a_count_written_with_duan_is_parsed_too(self):
        """音频描述用的量词是「段」:「参考音频最多 3 段」「上传0~3段参考音频」。"""
        for model in ("hailuo-h3-quannengcankao", "kwvideo-v2-quannengcankao"):
            with self.subTest(model=model):
                self.assertEqual(3, self.module._agent_video_media_requirements(model)["audio_limit"])

    def test_a_video_field_with_no_stated_count_defaults_to_one(self):
        """wan2.7-xuxie 的 clips 描述是「上传首段视频」,没写数量。
        以前复数名没数字就取上限 10,界面上能选 10 个视频。"""
        req = self.module._agent_video_media_requirements("wan2.7-xuxie")

        self.assertEqual(1, req["video_limit"])
        self.assertTrue(req["video_is_array"], "clips 是复数名,仍然要传数组")

    def test_extra_files_beyond_the_declared_limit_are_dropped(self):
        """hailuo-h3-quannengcankao 的 video_url 上限是 3,多传的必须截掉而不是原样发出去。"""
        many = ["https://x/%d.mp4" % i for i in range(6)]

        payload = self.module._agent_video_payload(
            "hailuo-h3-quannengcankao", "prompt", 5, "16:9", [], reference_video_url=many)

        sent = payload["params"]["video_url"]
        self.assertEqual(3, len(sent) if isinstance(sent, list) else 1)

    def test_a_single_string_is_still_accepted(self):
        """历史条目的 referenceVideo 是单个字符串,不能因为改成列表就读不了。"""
        payload = self.module._agent_video_payload(
            "kling-motion-control", "prompt", 5, "16:9", ["https://x/ref.png"],
            reference_video_url="https://x/a.mp4")

        self.assertEqual("https://x/a.mp4", payload["params"]["video_url"])

    def test_a_missing_required_audio_stops_the_run(self):
        module = self.module
        entry = {"id": "pg-1", "mode": "video", "model": "vidu-mv",
                 "prompt": "x", "refs": [], "duration": 5}

        with self.assertRaises(RuntimeError) as caught:
            module._prodgen_run_video(entry)

        self.assertIn("音频", str(caught.exception))

    def test_the_audio_button_shows_up_for_models_that_take_audio(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QtWidgets = self.module.QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.module.BRIDGE = self.module.Bridge()
        self.module.ProductGenPage._request_model_schema = lambda self, model, mode: None

        page = self.module.ProductGenPage()
        page._video_models = [{"name": k, "display_name": v.get("display_name") or k, "type": "video"}
                              for k, v in self.schemas.items() if v.get("type") == "video"]
        page._models_loaded = True
        host = QtWidgets.QWidget()
        QtWidgets.QVBoxLayout(host).addWidget(page)
        host.resize(1200, 700)
        host.move(-4000, -4000)
        host.show()
        app.processEvents()

        for model, video, audio in (("vidu-mv", False, True),
                                    ("kling-avatar-image2video", False, True),
                                    ("hailuo-h3-quannengcankao", True, True),
                                    ("kling-motion-control", True, False),
                                    ("kling-v2-6", False, False)):
            with self.subTest(model=model):
                page._mode_set("video")
                page._set_current_model(model, "video")
                app.processEvents()
                self.assertEqual(model, page._current_model())
                self.assertEqual(video, page.ref_video_btn.isVisibleTo(page), "视频按钮")
                self.assertEqual(audio, page.ref_audio_btn.isVisibleTo(page), "音频按钮")
        host.close()

    def test_switching_to_a_model_that_takes_no_audio_drops_the_picked_file(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QtWidgets = self.module.QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.module.BRIDGE = self.module.Bridge()
        self.module.ProductGenPage._request_model_schema = lambda self, model, mode: None

        page = self.module.ProductGenPage()
        page._video_models = [{"name": k, "display_name": v.get("display_name") or k, "type": "video"}
                              for k, v in self.schemas.items() if v.get("type") == "video"]
        page._models_loaded = True
        page._mode_set("video")
        page._set_current_model("vidu-mv", "video")
        page._media_files["audio"] = ["C:/tmp/voice.mp3"]

        page._set_current_model("kling-v2-6", "video")

        self.assertEqual([], page._media_files["audio"], "换到不收音频的模型必须清掉,不能偷偷带着")

    def test_the_upload_button_shows_up_for_those_models(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QtWidgets = self.module.QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.module.BRIDGE = self.module.Bridge()
        self.module.ProductGenPage._request_model_schema = lambda self, model, mode: None

        page = self.module.ProductGenPage()
        page._video_models = [{"name": k, "display_name": v.get("display_name") or k, "type": "video"}
                              for k, v in self.schemas.items() if v.get("type") == "video"]
        page._models_loaded = True
        host = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(host)
        layout.addWidget(page)
        host.resize(1200, 700)
        host.move(-4000, -4000)
        host.show()
        app.processEvents()

        for model, expected in (("kling-motion-control", True), ("wan2.2-animate-mix", True),
                                ("wan2.7-xuxie", True), ("kling-v2-6", False)):
            with self.subTest(model=model):
                page._mode_set("video")
                page._set_current_model(model, "video")
                app.processEvents()
                self.assertEqual(model, page._current_model(), "目录没灌好,模型被换掉了")
                self.assertEqual(expected, page.ref_video_btn.isVisibleTo(page))
        host.close()

    def test_a_prominent_labeled_slot_appears_next_to_the_image_slot(self):
        """右下角小圆钮容易被挤出屏幕:视频/音频要在参考图旁边有显眼的带标签槽位。

        happyhorse-video-edit 视频必选,可图片可选。此前顶部只有「参考图」槽,
        用户「必选视频却找不到上传入口」。这里断言声明了视频/音频的模型会在
        顶部参考图行给出对应槽位,纯文生视频模型则不出现,免得添乱。
        """
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QtWidgets = self.module.QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.module.BRIDGE = self.module.Bridge()
        self.module.ProductGenPage._request_model_schema = lambda self, model, mode: None

        page = self.module.ProductGenPage()
        page._video_models = [{"name": k, "display_name": v.get("display_name") or k, "type": "video"}
                              for k, v in self.schemas.items() if v.get("type") == "video"]
        page._models_loaded = True
        host = QtWidgets.QWidget()
        QtWidgets.QVBoxLayout(host).addWidget(page)
        host.resize(1200, 700)
        host.move(-4000, -4000)
        host.show()
        app.processEvents()

        for model, expected in (("happyhorse-video-edit", {"video"}),
                                ("hailuo-h3-quannengcankao", {"video", "audio"}),
                                ("kling-v2-6", set())):
            with self.subTest(model=model):
                page._mode_set("video")
                page._set_current_model(model, "video")
                app.processEvents()
                self.assertEqual(model, page._current_model(), "目录没灌好,模型被换掉了")
                shown = {kind for kind, btn in page._media_slot_buttons.items()
                         if btn.isVisibleTo(page)}
                self.assertEqual(expected, shown)
        host.close()

    def test_the_prominent_slot_switches_to_the_chosen_state_after_a_pick(self):
        """选完视频后,顶部槽位得重建成已选态(而不是还显示空的必选槽)。"""
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QtWidgets = self.module.QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.module.BRIDGE = self.module.Bridge()
        self.module.ProductGenPage._request_model_schema = lambda self, model, mode: None

        page = self.module.ProductGenPage()
        page._video_models = [{"name": k, "display_name": v.get("display_name") or k, "type": "video"}
                              for k, v in self.schemas.items() if v.get("type") == "video"]
        page._models_loaded = True
        page._mode_set("video")
        page._set_current_model("happyhorse-video-edit", "video")

        page._media_files["video"] = ["C:/tmp/clip.mp4"]
        page._style_ref_slot()

        self.assertIn("video", page._media_slot_buttons, "选完仍要有视频槽")


if __name__ == "__main__":
    unittest.main()
