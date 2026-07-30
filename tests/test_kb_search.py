from pathlib import Path
import importlib.util
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "backend" / "central_server.py"
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("central_server_under_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KnowledgeBaseSearchTest(unittest.TestCase):
    def test_notice_question_returns_snippet_centered_on_notice_section(self):
        server = load_server_module()
        original_state = server.STATE
        try:
            filler = "产品介绍内容。" * 45
            notice = (
                "八、注意事项\n"
                "1. 上妆前做好保湿，避免卡粉浮粉\n"
                "2. 开封后尽快使用，避免成分氧化失效\n"
                "3. 皮肤破损、过敏时暂停使用\n"
                "4. 避光阴凉保存，避免高温暴晒"
            )
            server.STATE = {
                "kb": [
                    {
                        "id": "doc-notice",
                        "orgId": "org-default",
                        "title": "粉底液",
                        "chunkTexts": [filler + "\n" + notice],
                    },
                    {
                        "id": "doc-generic",
                        "orgId": "org-default",
                        "title": "通用资料",
                        "chunkTexts": ["有什么产品信息吗？这里是常规说明，没有注意事项正文。"],
                    },
                ]
            }

            hits = server.search_kb("有什么注意事项吗？", "org-default", limit=2)

            self.assertGreaterEqual(len(hits), 1)
            self.assertEqual(hits[0]["docId"], "doc-notice")
            self.assertIn("注意事项", hits[0]["text"])
            self.assertIn("皮肤破损、过敏时暂停使用", hits[0]["text"])
            self.assertLess(hits[0]["text"].find("注意事项"), 180)
        finally:
            server.STATE = original_state

    def test_native_client_keeps_full_kb_source_context_for_answering(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn('(s.get("text") or "").strip().replace("\\n", " ")[:900]', src)


if __name__ == "__main__":
    unittest.main()
