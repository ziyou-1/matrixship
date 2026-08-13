"""Agent.模式参数区随模型变化 —— 断言渲染结果,不是源码字符串。

写死的输入框在这里会立刻暴露:所有模型都长一样。
"""
from pathlib import Path
import importlib.util
import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_client_module(name="matrix_native_client_agent_page_test"):
    spec = importlib.util.spec_from_file_location(name, CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentPageParamBarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_client_module()
        cls.app = cls.module.QtWidgets.QApplication.instance() or cls.module.QtWidgets.QApplication([])
        cls.module.BRIDGE = cls.module.Bridge()
        # 参数区必须只读本地缓存/快照就能渲染出来。这里把取 schema 的后台任务换成断言,
        # 一旦有人让 UI 线程去发网络,测试立刻红。
        cls.module.ProductGenPage._request_model_schema = lambda self, model, mode: None
        cls.page = cls.module.ProductGenPage()
        # 必须真的把页面显示出来:未显示的控件 isVisible() 恒为 False,
        # 「胶囊消失了」的断言会因为整页不可见而假绿。
        cls.host = cls.module.QtWidgets.QWidget()
        layout = cls.module.QtWidgets.QVBoxLayout(cls.host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(cls.page)
        cls.host.resize(1280, 780)
        cls.host.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.host.close()

    def test_the_page_is_actually_visible_so_visibility_assertions_mean_something(self):
        self.select("video", "kling-v2-6")

        self.assertTrue(self.page.isVisible())
        self.assertTrue(self.page.b_model.isVisible())

    def select(self, mode, model):
        self.page._mode_set(mode)
        self.page._set_current_model(model, mode)
        self.app.processEvents()
        return self.page._current_form()

    def test_form_comes_from_the_bundled_snapshot_without_any_network(self):
        form = self.select("image", "gpt-image-2")

        self.assertEqual("snapshot", form["source"])
        self.assertEqual(["prompt", "images", "size", "quality"], [f["name"] for f in form["fields"]])

    def test_aspect_pill_options_come_from_the_model_not_a_fixed_list(self):
        gpt = self.select("image", "gpt-image-2")
        gpt_aspect = self.module._agent_form_role_field(gpt, "aspect")
        gemini = self.select("image", "gemini-3-pro-image-preview")
        gemini_aspect = self.module._agent_form_role_field(gemini, "aspect")

        self.assertEqual("size", gpt_aspect["name"])
        self.assertEqual(34, len(gpt_aspect["options"]))
        self.assertEqual("aspectRatio", gemini_aspect["name"])
        self.assertEqual(10, len(gemini_aspect["options"]))
        self.assertNotEqual(len(gpt_aspect["options"]), len(gemini_aspect["options"]),
                            "两个模型的比例选项数必须不同,否则就是写死的")

    def test_a_pill_disappears_when_the_model_has_no_such_parameter(self):
        self.select("video", "wan2.7-shouweizhen")
        self.assertFalse(self.page.b_aspect.isVisible(), "该模型没有比例参数,胶囊必须消失")
        self.assertTrue(self.page.b_duration.isVisible())

        self.select("video", "happyhorse-video-edit")
        self.assertFalse(self.page.b_aspect.isVisible())
        self.assertFalse(self.page.b_duration.isVisible(), "该模型没有时长参数,胶囊必须消失")

        self.select("video", "kling-v2-6")
        self.assertTrue(self.page.b_aspect.isVisible(), "换回有比例参数的模型要重新出现")
        self.assertTrue(self.page.b_duration.isVisible())

    def test_hint_uses_each_models_own_input_hint(self):
        self.select("image", "gpt-image-2")
        gpt_hint = self.page.hint.text()
        self.select("video", "happyhorse-video-edit")
        edit_hint = self.page.hint.text()

        self.assertIn("温馨提示", gpt_hint)
        self.assertIn("合计扣费", edit_hint, "该模型的计费提醒必须显示给用户")
        self.assertNotEqual(gpt_hint, edit_hint)
        self.assertNotIn(self.page.BASE_HINT, gpt_hint, "有 input_hint 时不该再用通用文案")

    def test_upload_slots_follow_the_models_declared_uploads(self):
        edit = self.select("video", "happyhorse-video-edit")
        kinds = [(u["media"], u["limit"]) for u in edit["uploads"]]

        self.assertIn(("video", 1), kinds, "这个模型要传待编辑视频")
        self.assertIn(("image", 5), kinds)

        frames = self.select("video", "wan2.7-shouweizhen")
        images = self.module._agent_form_field(frames, "images")
        self.assertEqual(2, images["limit"])
        self.assertEqual(["首帧", "尾帧"], images["slot_labels"], "首尾帧顺序语义要落到槽位标签上")

    def test_switching_model_keeps_a_compatible_choice_and_drops_an_incompatible_one(self):
        kling = self.select("video", "kling-v2-6")
        aspect = self.module._agent_form_role_field(kling, "aspect")
        self.page._set_field_value(aspect, "9:16")

        vidu = self.select("video", "vidu-jieshuoman")
        vidu_aspect = self.module._agent_form_role_field(vidu, "aspect")

        self.assertEqual("9:16", self.page._field_value(vidu_aspect), "两个模型都支持 9:16,换模型要沿用")

        gpt = self.select("image", "gpt-image-2")
        gpt_aspect = self.module._agent_form_role_field(gpt, "aspect")
        self.assertNotEqual("9:16", self.page._field_value(gpt_aspect),
                            "gpt-image-2 的 size 用像素档位,不该塞一个它不认识的值")

    def test_the_drawer_holds_every_parameter_that_is_not_already_a_pill(self):
        form = self.select("image", "mj_imagine")
        drawer = [f["label"] for f in self.module._agent_form_drawer_fields(form)]

        self.assertIn("混乱度", drawer)
        self.assertIn("风格化", drawer)
        self.assertTrue(self.page.b_more.isVisible())
        for field in self.module._agent_form_drawer_fields(form):
            self.assertNotIn(field["role"], ("aspect", "duration"), "已经有胶囊的参数不该在抽屉里重复")

    def test_a_duplicate_role_field_is_hidden_from_the_drawer_too(self):
        """happyhorse-r2v 的 aspect_ratio 是 ratio 的重复语义,两个都发会 400。
        它既不做胶囊,也绝不能从抽屉里溜进请求。"""
        form = self.select("video", "happyhorse-r2v")
        duplicate = self.module._agent_form_field(form, "aspect_ratio")

        self.assertEqual("aspect", duplicate["duplicate_role"])
        self.assertTrue(duplicate["hidden"])
        self.assertNotIn("aspect_ratio", [f["name"] for f in self.module._agent_form_drawer_fields(form)])

    def test_untouched_drawer_leaves_the_request_byte_for_byte_unchanged(self):
        self.select("image", "gpt-image-2")

        self.assertEqual({}, self.page._changed_extra_params())

        entry = {"model": "gpt-image-2", "mode": "image", "params": {}}
        payload = {"prompt": "x", "params": {"size": "1024x1024"}}
        self.assertEqual({"size": "1024x1024"},
                         self.module._agent_apply_entry_params(payload, entry)["params"])

    def test_a_value_picked_in_the_drawer_actually_reaches_the_request(self):
        form = self.select("image", "gpt-image-2")
        quality = self.module._agent_form_field(form, "quality")
        self.page._set_field_value(quality, "high")

        changed = self.page._changed_extra_params()
        self.assertEqual({"quality": "high"}, changed, "改过的参数必须被记下来")

        entry = {"model": "gpt-image-2", "mode": "image", "params": changed}
        payload = {"prompt": "x", "params": {"size": "1024x1024"}}
        merged = self.module._agent_apply_entry_params(payload, entry)["params"]

        self.assertEqual("high", merged["quality"], "抽屉里点的值必须真的发出去,不能是假控件")
        self.assertEqual("1024x1024", merged["size"], "没碰过的参数不受影响")
        self.page._set_field_value(quality, quality["default"])

    def test_a_value_the_model_never_declared_is_dropped_instead_of_sent(self):
        entry = {"model": "gpt-image-2", "mode": "image",
                 "params": {"quality": "ultra", "no_such_param": "1"}}
        payload = {"prompt": "x", "params": {"size": "1024x1024"}}

        merged = self.module._agent_apply_entry_params(payload, entry)["params"]

        self.assertNotIn("no_such_param", merged, "模型没声明过的字段不该发")
        self.assertNotIn("ultra", merged.values(), "不在 options 里的值不该发")

    def test_the_displayed_ratio_is_the_ratio_that_will_be_sent(self):
        """图片模式的请求只由 size 决定,所以界面显示什么比例,size 换算回来必须是同一个。"""
        self.select("image", "gemini-3-pro-image-preview")
        aspect = self.module._agent_form_role_field(self.page._current_form(), "aspect")
        for option in aspect["options"]:
            value = option["value"]
            if not self.module._agent_size_from_aspect(value):
                continue
            with self.subTest(ratio=value):
                self.page._set_field_value(aspect, value)
                _label, size, ratio = self.page._aspect_entry_fields()

                self.assertEqual(value, ratio)
                self.assertEqual(value, self.module._agent_aspect_from_size(size),
                                 "界面显示 %s 就必须发出 %s 的尺寸" % (value, value))

    def test_gpt_image_2_passes_its_own_size_value_straight_through(self):
        self.select("image", "gpt-image-2")
        aspect = self.module._agent_form_role_field(self.page._current_form(), "aspect")
        self.page._set_field_value(aspect, "2048x3072")

        _label, size, ratio = self.page._aspect_entry_fields()

        self.assertEqual("2048x3072", size, "字段本身就是像素档位,不该再翻译一次")
        self.assertEqual("2:3", ratio)

    def test_video_duration_entry_value_follows_the_models_own_options(self):
        self.select("video", "wan2.7-shouweizhen")
        duration = self.module._agent_form_role_field(self.page._current_form(), "duration")
        values = [o["value"] for o in duration["options"]]

        self.page._set_field_value(duration, values[-1])

        self.assertEqual(int(values[-1]), self.page._current_video_duration())


if __name__ == "__main__":
    unittest.main()
