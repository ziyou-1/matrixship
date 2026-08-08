"""Agent.模式「再次生成」必须原样带走条目上的全部生成参数。

旧实现用 12 个字段的白名单复制条目,视频的 duration 和 referenceVideo 每次重跑都被静默丢掉。
参数按模型动态化之后,每个模型的字段各不相同,白名单更不可能列全,所以改成只剔除运行态字段的黑名单。
"""
from pathlib import Path
import importlib.util
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_client_module(name="matrix_native_client_agent_regen_test"):
    spec = importlib.util.spec_from_file_location(name, CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _StubPage(object):
    """只提供 regen 用到的三个协作方法,避免为了测一个字典变换去构造整个 Qt 页面。"""

    def __init__(self):
        self.added = []
        self.started = []

    def _add_card(self, entry):
        self.added.append(entry)

    def _scroll_bottom(self):
        pass

    def _start(self, entry):
        self.started.append(entry)


class AgentRegenKeepsParamsTest(unittest.TestCase):
    def setUp(self):
        self.module = load_client_module()

    def _regen(self, entry):
        page = _StubPage()
        with mock.patch.object(self.module, "add_prodgen") as add:
            self.module.ProductGenPage.regen(page, entry)
        self.assertEqual(1, add.call_count)
        return add.call_args.args[0]

    def test_regen_keeps_video_duration_and_reference_video(self):
        new = self._regen({
            "id": "pg-old", "mode": "video", "model": "kling-v2-6",
            "prompt": "商品展示", "duration": 10, "referenceVideo": "C:/tmp/src.mp4",
            "aspect_ratio": "9:16", "refs": ["C:/tmp/a.png"],
            "status": "完成", "files": ["C:/tmp/out.mp4"], "error": "",
        })

        self.assertEqual(10, new["duration"])
        self.assertEqual("C:/tmp/src.mp4", new["referenceVideo"])
        self.assertEqual("9:16", new["aspect_ratio"])
        self.assertEqual(["C:/tmp/a.png"], new["refs"])

    def test_regen_keeps_unknown_forward_compatible_fields(self):
        """按模型动态化后条目上会出现任意参数键,regen 不能因为「不认识」就丢掉。"""
        new = self._regen({
            "id": "pg-old", "mode": "video", "model": "wan2.7-cankaosheng",
            "prompt": "x", "params": {"resolution": "720P", "ratio": "16:9"},
            "uploads": {"reference_urls": ["C:/tmp/a.png"]}, "schemaVersion": 2,
        })

        self.assertEqual({"resolution": "720P", "ratio": "16:9"}, new["params"])
        self.assertEqual({"reference_urls": ["C:/tmp/a.png"]}, new["uploads"])
        self.assertEqual(2, new["schemaVersion"])

    def test_regen_drops_runtime_fields_and_starts_fresh(self):
        new = self._regen({
            "id": "pg-old", "mode": "image", "model": "gpt-image-2", "prompt": "x",
            "status": "失败", "files": ["C:/tmp/out.png"], "error": "boom",
            "rawError": "status=Error", "saved": True, "ts": "2026-01-01 00:00:00",
            "expandedPrompt": "e", "modelPrompt": "m", "visiblePrompt": "v",
            "publishMaterialId": "mat-1", "pendingPublishId": "pen-1",
        })

        for key in self.module._PRODGEN_RUNTIME_KEYS:
            if key in ("id", "status", "files", "error", "ts"):
                continue  # 这五个由 regen 重新赋值
            self.assertNotIn(key, new, "运行态字段 %s 不该被带到新条目" % key)
        self.assertNotEqual("pg-old", new["id"])
        self.assertEqual("生成中", new["status"])
        self.assertEqual([], new["files"])
        self.assertEqual("", new["error"])

    def test_regen_deep_copies_so_editing_the_copy_cannot_touch_history(self):
        entry = {"id": "pg-old", "mode": "image", "model": "gpt-image-2", "prompt": "x",
                 "refs": ["C:/tmp/a.png"], "params": {"size": "auto"}}
        new = self._regen(entry)

        new["refs"].append("C:/tmp/b.png")
        new["params"]["size"] = "1024x1024"

        self.assertEqual(["C:/tmp/a.png"], entry["refs"])
        self.assertEqual({"size": "auto"}, entry["params"])


if __name__ == "__main__":
    unittest.main()
