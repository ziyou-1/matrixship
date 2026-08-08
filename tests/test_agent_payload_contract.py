"""按模型 schema 装配请求体的契约。

Agent.模式不再为每个模型写死参数,而是按 LK888 公开的 params 装配。既然装配是通用的,
守护也必须是通用的:下面第一组是对**全部 67 个模型**都成立的不变式,第二组是踩过坑的具体模型。
"""
from pathlib import Path
import importlib.util
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"
FIXTURE = ROOT / "tests" / "fixtures" / "lk888_model_schemas.json"


def load_client_module(name="matrix_native_client_agent_payload_contract_test"):
    spec = importlib.util.spec_from_file_location(name, CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentPayloadContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_client_module()
        with open(FIXTURE, "r", encoding="utf-8") as f:
            cls.schemas = json.load(f)

    def form(self, name, dynamic=True):
        schema = self.schemas[name]
        form = self.module._agent_schema_form(name, schema.get("type") or "", schema, "snapshot")
        form["dynamic"] = dynamic
        return form

    def payload(self, name, prompt="测试提示词", values=None, uploads=None, dynamic=True):
        return self.module._agent_dynamic_payload(
            self.form(name, dynamic), prompt, values or {}, uploads or {})

    # ---------- 对全部 67 个模型成立的不变式 ----------

    def test_every_model_assembles_without_violating_the_wire_contract(self):
        for name in sorted(self.schemas):
            with self.subTest(model=name):
                form = self.form(name)
                payload = self.payload(name)
                allowed = {f["name"] for f in form["fields"]}

                self.assertEqual({"prompt", "params"}, set(payload),
                                 "顶层只能有 prompt 和 params")
                for key, value in payload["params"].items():
                    self.assertIn(key, allowed, "%s 不是该模型声明过的参数" % key)
                    self.assertNotIsInstance(value, bool,
                                             "%s 发了 Python 布尔;上游要的是 options 里的字符串" % key)
                    self.assertIsNotNone(value)
                    self.assertIsInstance(value, (str, int, float, list))
                    field = self.module._agent_form_field(form, key)
                    if field and field["options"] and not isinstance(value, list):
                        self.assertIn(str(value), [o["value"] for o in field["options"]],
                                      "%s=%s 不在该字段的合法取值里" % (key, value))

    def test_required_params_are_always_sent_and_untouched_optionals_never_are(self):
        for name in sorted(self.schemas):
            with self.subTest(model=name):
                form = self.form(name)
                params = self.payload(name)["params"]
                for field in form["fields"]:
                    if field["kind"] in ("upload", "unknown") or field["placement"] == "prompt":
                        continue
                    if field["required"] and field["kind"] in ("choice", "toggle"):
                        self.assertIn(field["name"], params,
                                      "有 options 的必填参数一定能算出默认值,必须发出去")
                    elif not field["required"] and field["default"] == self.module.AGENT_PARAM_UNSET:
                        self.assertNotIn(field["name"], params,
                                         "用户没设过的可选参数不该发 —— 这是避开互斥字段 400 的机制")

    def test_required_free_text_has_no_inventable_default_so_validation_blocks_instead(self):
        """vidu-mv.duration(number)、vidu-jieshuoman.script_name(input)都是必填但没有 options。
        客户端不能凭空编一个值,只能在提交前拦住并让用户填。"""
        for name, param in (("vidu-mv", "duration"), ("vidu-jieshuoman", "script_name")):
            with self.subTest(model=name, param=param):
                form = self.form(name)
                field = self.module._agent_form_field(form, param)

                self.assertTrue(field["required"])
                self.assertEqual([], field["options"])
                self.assertNotIn(param, self.payload(name)["params"], "不能凭空发一个编造的值")

                errors = self.module._agent_validate_form(form, "x", {}, {})
                self.assertTrue(any(field["label"] in e for e in errors),
                                "必须在提交前拦住:%s" % errors)

                filled = self.payload(name, values={param: "8"})["params"]
                self.assertIn(param, filled, "用户填了就要发出去")

    def test_uploads_land_on_exactly_the_key_the_schema_names(self):
        urls = ["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"]
        for name in sorted(self.schemas):
            form = self.form(name)
            for field in form["uploads"]:
                with self.subTest(model=name, param=field["name"]):
                    params = self.payload(name, uploads={field["name"]: urls})["params"]
                    self.assertIn(field["name"], params)
                    value = params[field["name"]]
                    if field["is_array"]:
                        self.assertIsInstance(value, list, "复数名参数一律传数组")
                        self.assertLessEqual(len(value), field["limit"])
                    else:
                        self.assertIsInstance(value, str, "单文件参数传字符串")
                    aliases = [k for k in params if k in (
                        "image_urls", "images", "reference_images", "referenceImages",
                        "reference_image_urls")]
                    self.assertLessEqual(len(aliases), 1, "开闸模型只发一个规范键,不再散弹式兼容")

    def test_an_unopened_model_is_not_touched_by_the_gate(self):
        payload = self.payload("kling-v2-6", dynamic=False)

        self.assertEqual({"prompt", "params"}, set(payload))
        self.assertIn("duration", payload["params"])

    # ---------- 踩过坑的具体模型 ----------

    def test_kling_v2_6_sound_is_a_string_from_options_never_a_bool(self):
        """docs/TROUBLESHOOTING.md:LK888 拒绝 sound=false,只收 on/off。"""
        params = self.payload("kling-v2-6")["params"]

        self.assertIn(params["sound"], ("on", "off"))
        self.assertNotIsInstance(params["sound"], bool)

    def test_happyhorse_r2v_never_sends_ratio_and_aspect_ratio_together(self):
        """docs/TROUBLESHOOTING.md:HappyHorse 同时收到 ratio 与 aspect_ratio 会 400。
        角色绑定只认第一个匹配字段,第二个既不渲染也不发送。"""
        form = self.form("happyhorse-r2v")
        params = self.payload("happyhorse-r2v")["params"]

        self.assertEqual("aspect", self.module._agent_form_field(form, "ratio")["role"])
        self.assertEqual("other", self.module._agent_form_field(form, "aspect_ratio")["role"])
        self.assertNotIn("aspect_ratio", params)

    def test_veo31_keeps_the_two_switches_that_production_runs_with_on(self):
        params = self.payload("veo3.1")["params"]

        self.assertEqual("true", params["enhance_prompt"])
        self.assertEqual("true", params["enable_upsample"])

    def test_watermark_style_switches_default_off_so_nothing_costs_more_silently(self):
        for name in sorted(self.schemas):
            form = self.form(name)
            for field in form["fields"]:
                if field["kind"] != "toggle" or not field["required"]:
                    continue
                if field["name"] in (self.module._agent_model_overrides(name).get("switch_default_true") or []):
                    continue
                with self.subTest(model=name, param=field["name"]):
                    self.assertNotIn(field["default"], ("true", "on", "1", "yes"),
                                     "必填开关默认不该是开,否则静默涨价")

    def test_a_prompt_field_named_something_else_still_carries_the_prompt(self):
        """vidu-jieshuoman 的主文本字段叫 script_content,不叫 prompt。"""
        form = self.form("vidu-jieshuoman")
        params = self.payload("vidu-jieshuoman", prompt="一段解说词")["params"]

        self.assertEqual("script_content", form["prompt_field"])
        self.assertEqual("一段解说词", params["script_content"])

    def test_the_gate_drops_keys_the_model_never_declared(self):
        form = self.form("kling-v2-6")
        payload = {"prompt": "x", "params": {"duration": "5", "resolution": "720p"}, "images": ["u"]}

        gated = self.module._agent_payload_gate(form, payload)

        self.assertEqual({"prompt", "params"}, set(gated))
        self.assertNotIn("resolution", gated["params"], "kling-v2-6 的 schema 里没有 resolution")

    def test_validation_blocks_submission_before_any_charge_happens(self):
        form = self.form("vidu-mv")

        errors = self.module._agent_validate_form(form, "", {}, {})

        self.assertTrue(errors)
        self.assertTrue(any("上传" in e for e in errors), "必填上传缺失要拦住:%s" % errors)


if __name__ == "__main__":
    unittest.main()
