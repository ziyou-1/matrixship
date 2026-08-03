from pathlib import Path
import ast
import json
import os
import tempfile
import unittest
import uuid


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


def load_history_helpers():
    source = _source()
    tree = ast.parse(source)
    wanted = {
        "_workflow_assistant_history_path",
        "_workflow_assistant_history_trim",
        "_load_workflow_assistant_history",
        "_save_workflow_assistant_history",
    }
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    found = {node.name for node in nodes}
    missing = wanted - found
    if missing:
        return None
    ns = {
        "os": os,
        "json": json,
        "tempfile": tempfile,
        "uuid": uuid,
        "data_dir": lambda: ns["DATA_DIR"],
        "_workflow_assistant_log": lambda *args, **kwargs: ns["LOGS"].append(
            (args, kwargs)
        ),
        "DATA_DIR": "",
        "LOGS": [],
    }
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(CLIENT), "exec"), ns)
    return ns


class WorkflowAssistantHistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helpers = load_history_helpers()

    def setUp(self):
        if (
            self.helpers is None
            and self._testMethodName != "test_agent_chat_page_declares_history_restore_and_save_flow"
        ):
            self.skipTest("history helpers are not implemented yet")

    def test_history_is_trimmed_to_latest_100_user_assistant_rounds(self):
        messages = []
        for index in range(101):
            messages.extend([
                {"role": "user", "content": f"user-{index}"},
                {
                    "role": "assistant",
                    "content": f"assistant-{index}",
                    "replacementPayloads": [
                        {"sourceVideoPath": f"video-{index}.mp4"}
                    ],
                },
            ])

        trimmed = self.helpers["_workflow_assistant_history_trim"](messages)

        self.assertEqual(200, len(trimmed))
        self.assertEqual("user-1", trimmed[0]["content"])
        self.assertEqual("assistant-100", trimmed[-1]["content"])
        self.assertEqual(
            "video-100.mp4",
            trimmed[-1]["replacementPayloads"][0]["sourceVideoPath"],
        )

    def test_history_path_uses_current_account_data_directory(self):
        with tempfile.TemporaryDirectory() as td:
            self.helpers["DATA_DIR"] = td
            self.assertEqual(
                os.path.join(td, "workflow_assistant_history.json"),
                self.helpers["_workflow_assistant_history_path"](),
            )

    def test_history_round_trip_preserves_replacement_payloads(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "workflow_assistant_history.json")
            messages = [
                {
                    "role": "user",
                    "content": "采集丰田汽车热门视频",
                    "createdAt": "2026-08-03T00:00:00Z",
                },
                {
                    "role": "assistant",
                    "content": "视频拆解结果",
                    "createdAt": "2026-08-03T00:00:01Z",
                    "replacementPayloads": [
                        {
                            "title": "参考视频",
                            "sourceVideoPath": "E:/assets/reference.mp4",
                        }
                    ],
                },
            ]

            self.assertTrue(
                self.helpers["_save_workflow_assistant_history"](messages, path)
            )
            loaded = self.helpers["_load_workflow_assistant_history"](path)

            self.assertEqual(messages, loaded)

    def test_history_save_uses_atomic_replace_without_leftover_temp_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "workflow_assistant_history.json")

            self.assertTrue(
                self.helpers["_save_workflow_assistant_history"](
                    [{"role": "user", "content": "hello"}],
                    path,
                )
            )

            self.assertTrue(os.path.isfile(path))
            self.assertEqual(["workflow_assistant_history.json"], os.listdir(td))
            self.assertEqual(
                1,
                json.loads(Path(path).read_text(encoding="utf-8"))["version"],
            )

    def test_malformed_history_returns_empty_and_logs_load_failure(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "workflow_assistant_history.json")
            Path(path).write_text("{broken", encoding="utf-8")

            self.assertEqual(
                [],
                self.helpers["_load_workflow_assistant_history"](path),
            )
            self.assertTrue(self.helpers["LOGS"])
            self.assertEqual(
                "history_load_failed",
                self.helpers["LOGS"][-1][0][0],
            )

    def test_history_loader_ignores_unsupported_roles_and_invalid_content(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "workflow_assistant_history.json")
            Path(path).write_text(
                json.dumps(
                    {
                        "version": 1,
                        "messages": [
                            {"role": "system", "content": "ignore"},
                            {"role": "user", "content": 123},
                            {"role": "user", "content": "keep"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                [{"role": "user", "content": "keep"}],
                self.helpers["_load_workflow_assistant_history"](path),
            )

    def test_agent_chat_page_declares_history_restore_and_save_flow(self):
        page = _class_source("AgentChatPage")

        self.assertIn("_load_workflow_assistant_history", page)
        self.assertIn("_save_workflow_assistant_history", page)
        self.assertIn("replacementPayloads", page)
        self.assertIn("def _restore_history", page)
        self.assertIn("def _persist_history", page)
        self.assertIn("def _history_account_key", page)
        self.assertIn("self._replacement_card(payload)", page)
        self.assertIn("def on_show", page)
        self.assertIn("workflow_assistant_history", _source())


if __name__ == "__main__":
    unittest.main()
