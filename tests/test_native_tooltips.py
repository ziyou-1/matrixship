import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


class NativeTooltipPolicyTest(unittest.TestCase):
    def test_native_client_does_not_define_non_empty_tooltips(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "setToolTip":
                continue
            if not node.args:
                offenders.append(node.lineno)
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and arg.value == "":
                continue
            offenders.append(node.lineno)

        self.assertEqual(
            offenders,
            [],
            "Qt tooltip 会在鼠标悬停时弹出黑框，请改用页面内可见文案或状态栏提示。",
        )
