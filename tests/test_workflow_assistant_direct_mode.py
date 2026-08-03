from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def _source():
    return CLIENT.read_text(encoding="utf-8-sig")


def _class_source(class_name):
    source = _source()
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError(f"{class_name} not found")


def _method_source(class_name, method_name):
    source = _source()
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return "\n".join(lines[item.lineno - 1:item.end_lineno])
    raise AssertionError(f"{class_name}.{method_name} not found")


class WorkflowAssistantDirectModeTest(unittest.TestCase):
    def test_sidebar_no_longer_exposes_automation_workflow_page(self):
        src = _source()
        nav = src[src.index("NAV = ["):src.index("# ---------- 登录页")]

        self.assertIn("🤖 工作流助手", nav)
        self.assertNotIn("🔀 自动化工作流", nav)
        self.assertNotIn("WorkflowPage()", nav)

    def test_agent_chat_no_longer_generates_or_saves_workflows(self):
        page = _class_source("AgentChatPage")

        self.assertNotIn("WF_ORCH_SYSTEM", page)
        self.assertNotIn("extract_workflow", page)
        self.assertNotIn("WORKFLOWS.insert", page)
        self.assertNotIn("save_workflows", page)
        self.assertNotIn("wf_created", page)
        self.assertNotIn("自动化工作流", page)
        self.assertIn("热点视频拆解助手", page)
        self.assertIn("直接采集并拆解", page)

    def test_agent_chat_exposes_video_replacement_action_for_breakdown_payloads(self):
        page = _class_source("AgentChatPage")

        self.assertIn("_replacement_card", page)
        self.assertIn('BRIDGE.payload.emit("goto_nav", "🧬 同款替换")', page)
        self.assertIn('BRIDGE.payload.emit("video_replace_start"', page)
        self.assertNotIn('BRIDGE.payload.emit("goto_nav", "🛍️ Agent.模式")', page)

    def test_login_does_not_start_legacy_workflow_scheduler(self):
        on_login = _method_source("MainWindow", "on_login")

        self.assertNotIn("_start_scheduler", on_login)

    def test_account_scope_reload_no_longer_loads_legacy_workflow_file(self):
        src = _source()
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "reload_account_scoped_state":
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        fn = child.func
                        if isinstance(fn, ast.Name):
                            calls.append(fn.id)
                        elif isinstance(fn, ast.Attribute):
                            calls.append(fn.attr)
                self.assertNotIn("load_workflows", calls)
                self.assertEqual(calls[:4], ["load_pending", "load_assets", "load_brand", "load_risk"])
                return
        raise AssertionError("reload_account_scoped_state not found")


if __name__ == "__main__":
    unittest.main()
