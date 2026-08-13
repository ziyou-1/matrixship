"""单模型表单 schema 的取用与降级。

Agent.模式按每个模型自己的 params 渲染参数控件,所以「拿不到 schema」必须有确定的兜底行为,
而不是让参数区空白或者退回「所有模型一个样」。降级链:内存 → 网络 → 内存(过期 stale) → 磁盘 → 随包快照 → 空。
"""
from pathlib import Path
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"

GPT_SCHEMA = {
    "name": "gpt-image-2",
    "display_name": "GPT Image 2",
    "input_hint": "描述画面中的物体、风格及文字排版。",
    "type": "image",
    "params": [
        {"name": "prompt", "label": "提示词", "type": "textarea", "required": True, "description": "d"},
        {"name": "size", "label": "图片比例", "type": "select", "required": True, "description": "d",
         "options": [{"value": "auto", "label": "自适应"}, {"value": "1024x1024", "label": "正方形 (1:1)"}]},
    ],
}


def load_client_module(name="matrix_native_client_agent_schema_fetch_test"):
    spec = importlib.util.spec_from_file_location(name, CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentSchemaFetchTest(unittest.TestCase):
    def setUp(self):
        self.module = load_client_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(self.module, "data_dir", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.module._LK888_SCHEMA_MEM.clear()

    def _disk(self):
        path = os.path.join(self.tmp.name, "lk888_model_schemas.json")
        if not os.path.isfile(path):
            return {}
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)

    def test_success_normalizes_caches_in_memory_and_writes_disk(self):
        with mock.patch.object(self.module, "api", return_value=(200, GPT_SCHEMA)) as api:
            schema, source = self.module._lk888_model_schema("gpt-image-2")

        self.assertEqual("net", source)
        self.assertEqual(["prompt", "size"], [p["name"] for p in schema["params"]])
        self.assertEqual("/lk888/v1/skills/models/gpt-image-2", api.call_args.args[1])
        self.assertIn("gpt-image-2", self._disk()["models"])

        with mock.patch.object(self.module, "api", side_effect=AssertionError("不该再发网络")):
            again, source2 = self.module._lk888_model_schema("gpt-image-2")
        self.assertEqual("memory", source2)
        self.assertEqual(schema, again)

    def test_failures_never_raise_and_fall_back_to_bundled_snapshot(self):
        for code, body in ((401, {"error": "unauthorized"}), (502, {}), (0, {"ok": False}), (200, {"params": "x"})):
            self.module._LK888_SCHEMA_MEM.clear()
            with mock.patch.object(self.module, "api", return_value=(code, body)), \
                    mock.patch.object(self.module, "log") as logged:
                schema, source = self.module._lk888_model_schema("gpt-image-2")

            self.assertEqual("snapshot", source, "http %s 应落到随包快照" % code)
            self.assertTrue(schema["params"], "快照必须给出该模型的真实参数")
            self.assertTrue(logged.called, "每次失败都要留痕")
            self.assertEqual({}, self._disk(), "失败绝不写盘")

    def test_failure_is_negatively_cached_on_a_short_ttl(self):
        with mock.patch.object(self.module, "api", return_value=(502, {})):
            self.module._lk888_model_schema("gpt-image-2")
        with mock.patch.object(self.module, "api", side_effect=AssertionError("负缓存期内不该重试")):
            self.module._lk888_model_schema("gpt-image-2")

        self.assertLess(self.module._LK888_SCHEMA_TTL_FAIL, self.module._LK888_SCHEMA_TTL_OK,
                        "失败的缓存时间必须远短于成功,否则一次 502 会把模型冻住")

    def test_failure_after_success_keeps_serving_the_last_good_schema(self):
        with mock.patch.object(self.module, "api", return_value=(200, GPT_SCHEMA)):
            self.module._lk888_model_schema("gpt-image-2")
        with mock.patch.object(self.module, "api", return_value=(502, {})):
            schema, source = self.module._lk888_model_schema("gpt-image-2", force=True)

        self.assertIn(source, ("stale", "disk"))
        self.assertEqual(["prompt", "size"], [p["name"] for p in schema["params"]])

    def test_disk_cache_survives_a_restart_without_network(self):
        with mock.patch.object(self.module, "api", return_value=(200, GPT_SCHEMA)):
            self.module._lk888_model_schema("gpt-image-2")

        fresh = load_client_module("matrix_native_client_agent_schema_restart_test")
        with mock.patch.object(fresh, "data_dir", return_value=self.tmp.name):
            schema, source = fresh._lk888_model_schema_cached("gpt-image-2")

        self.assertEqual("disk", source)
        self.assertEqual("GPT Image 2", schema["display_name"])

    def test_corrupt_disk_cache_is_ignored_instead_of_breaking_the_form(self):
        with open(os.path.join(self.tmp.name, "lk888_model_schemas.json"), "w", encoding="utf-8") as f:
            f.write("{ this is not json")

        schema, source = self.module._lk888_model_schema_cached("gpt-image-2")

        self.assertEqual("snapshot", source)
        self.assertTrue(schema["params"])

    def test_cached_lookup_never_touches_the_network(self):
        with mock.patch.object(self.module, "api", side_effect=AssertionError("UI 线程不许发网络")):
            schema, source = self.module._lk888_model_schema_cached("kling-v2-6")

        self.assertEqual("snapshot", source)
        self.assertIn("sound", [p["name"] for p in schema["params"]])

    def test_normalize_tolerates_a_hostile_payload(self):
        schema = self.module._lk888_schema_normalize("x", {
            "params": [
                None,
                {"name": "", "type": "select"},
                {"name": "ok", "options": "not-a-list"},
                {"name": "opt", "type": "SELECT", "required": 1,
                 "options": [{"value": 5, "label": None}, {"nolabel": 1}, "bare"]},
            ],
        })

        self.assertEqual(["ok", "opt"], [p["name"] for p in schema["params"]])
        self.assertEqual([], schema["params"][0]["options"])
        self.assertEqual("select", schema["params"][1]["type"])
        self.assertIs(True, schema["params"][1]["required"])
        self.assertEqual([{"value": "5", "label": "5"}, {"value": "bare", "label": "bare"}],
                         schema["params"][1]["options"])

    def test_bundled_snapshot_covers_the_models_the_agent_offers(self):
        import lk888_schema_snapshot

        rows = lk888_schema_snapshot.all_schemas()

        self.assertGreaterEqual(len(rows), 60)
        for name in (self.module._LK888_IMAGE_DEFAULT, self.module._LK888_VIDEO_DEFAULT):
            self.assertIn(name, rows)
            self.assertTrue(rows[name]["params"])
            self.assertTrue(rows[name]["input_hint"], "input_hint 是模型自己的填写提示,必须随包")


if __name__ == "__main__":
    unittest.main()
