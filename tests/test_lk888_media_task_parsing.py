import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_helper(name):
    src = CLIENT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            ns = {}
            exec(compile(module, str(CLIENT), "exec"), ns)
            return ns[name]
    raise AssertionError("%s helper missing" % name)


class Lk888MediaTaskParsingTest(unittest.TestCase):
    def test_extracts_video_url_without_file_extension_from_task_status(self):
        extract = load_helper("_extract_lk888_media_url")
        status = {
            "data": {
                "status": "succeeded",
                "result": {
                    "video_url": "https://cdn.example.com/download?id=task-123&token=abc"
                },
            }
        }

        self.assertEqual(
            extract(status, ["mp4", "mov"]),
            "https://cdn.example.com/download?id=task-123&token=abc",
        )

    def test_recognizes_chinese_error_task_status(self):
        failed = load_helper("_lk888_task_failed")

        self.assertTrue(failed({"data": {"status": "错误", "message": "参数无效"}}))


if __name__ == "__main__":
    unittest.main()
