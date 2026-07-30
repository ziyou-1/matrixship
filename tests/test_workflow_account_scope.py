from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def _source_tree():
    return ast.parse(CLIENT.read_text(encoding="utf-8-sig"))


def _call_name(node):
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Name):
            return fn.id
        if isinstance(fn, ast.Attribute):
            return fn.attr
    return ""


def _method_calls(class_name, method_name):
    tree = _source_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return [_call_name(n) for n in ast.walk(item) if isinstance(n, ast.Call)]
    raise AssertionError(f"{class_name}.{method_name} not found")


def _function_calls(function_name):
    tree = _source_tree()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return [_call_name(n) for n in ast.walk(node) if isinstance(n, ast.Call)]
    raise AssertionError(f"{function_name} not found")


def _class_source(class_name):
    source = CLIENT.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError(f"{class_name} not found")


class WorkflowAccountScopeTest(unittest.TestCase):
    def test_login_reloads_account_scoped_workflows_after_scope_switch(self):
        calls = _method_calls("MainWindow", "on_login")
        self.assertIn("apply_account_scope", calls)
        self.assertIn("reload_account_scoped_state", calls)
        self.assertLess(calls.index("apply_account_scope"), calls.index("reload_account_scoped_state"))
        self.assertLess(calls.index("reload_account_scoped_state"), calls.index("start_engine"))

    def test_workflow_page_reloads_file_before_rendering_list(self):
        calls = _method_calls("WorkflowPage", "on_show")
        self.assertIn("load_workflows", calls)
        self.assertIn("_build_list", calls)
        self.assertLess(calls.index("load_workflows"), calls.index("_build_list"))

    def test_refresh_button_uses_reload_list(self):
        calls = _method_calls("WorkflowPage", "__init__")
        self.assertIn("_reload_list", calls)

    def test_account_scoped_state_loader_includes_workflows(self):
        calls = _function_calls("reload_account_scoped_state")
        self.assertEqual(calls[:5], ["load_workflows", "load_pending", "load_assets", "load_brand", "load_risk"])

    def test_workflow_page_exposes_delete_current_workflow_action(self):
        block = _class_source("WorkflowPage")

        self.assertIn('self.b_del = _round_icon_btn("trash"', block)
        self.assertIn('self.b_del.setAccessibleName("删除当前工作流")', block)
        self.assertIn('self.b_del.setToolTip("")', block)
        self.assertIn("self.b_del.clicked.connect(self._delete_current_workflow)", block)
        self.assertIn("[self.b_open, self.b_ref, self.b_del]", block)

    def test_delete_current_workflow_confirms_saves_and_rebuilds(self):
        calls = _method_calls("WorkflowPage", "_delete_current_workflow")
        block = _class_source("WorkflowPage")
        method = block[block.index("def _delete_current_workflow(self):"):block.index("def _run(self):")]

        self.assertIn("QMessageBox", calls)
        self.assertIn("addButton", calls)
        self.assertIn("exec", calls)
        self.assertIn("save_workflows", calls)
        self.assertIn("_build_list", calls)
        self.assertIn("WORKFLOWS.pop(row)", method)
        self.assertIn("不会删除已生成素材", method)

    def test_workflow_collect_and_ui_use_selected_account_id(self):
        source = CLIENT.read_text(encoding="utf-8-sig")
        collect_start = source.index("def _exec_collect(")
        collect = source[collect_start:source.index("def _exec_text(", collect_start)]
        page = _class_source("WorkflowPage")

        self.assertIn('account_id = p.get("accountId")', collect)
        self.assertIn('search_payload["accountId"] = account_id', collect)
        self.assertIn('download_payload["accountId"] = account_id', collect)
        self.assertIn('BRIDGE.payload.emit("workflow_accounts", load_account_matrix_rows())', page)
        self.assertIn("account_option_label(a)", page)
        self.assertIn('sc2["publishAccountId"] = apacc.currentData() or ""', page)


if __name__ == "__main__":
    unittest.main()
