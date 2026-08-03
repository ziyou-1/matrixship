from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


class OutreachPageCopyTest(unittest.TestCase):
    def _client_source(self):
        return CLIENT.read_text(encoding="utf-8")

    def _outreach_block(self):
        source = self._client_source()
        start = source.index("class OutreachPage")
        end = source.index("class GrowthPage", start)
        return source[start:end]

    def test_ai_outreach_page_explains_comment_outreach_flow(self):
        block = self._outreach_block()

        self.assertIn("AI 触达是做什么的", block)
        self.assertIn("不是私信群发", block)
        self.assertIn("搜索相关视频/笔记", block)
        self.assertIn("筛选出有咨询、比价、想了解意向的潜在客户", block)
        self.assertIn("生成一条短评论话术", block)
        self.assertIn("通过本机浏览器在评论区回复/评论", block)
        self.assertIn("默认限量、间隔发送", block)
        self.assertIn("status.setWordWrap(True)", block)

    def test_ai_outreach_uses_long_browser_task_timeout(self):
        block = self._outreach_block()

        self.assertIn('submit_local_task("outreach.run", payload, 900)', block)

    def test_ai_outreach_status_uses_local_task_error_message(self):
        block = self._outreach_block()

        self.assertIn('_local_task_error_message(d)', block)
        self.assertNotIn('"未完成:" + str(d.get("error") or "")', block)

    def test_local_task_timeout_preserves_last_status_for_diagnostics(self):
        source = self._client_source()
        start = source.index("def submit_local_task")
        end = source.index("XHS_LOGIN_EXPIRED_HINT", start)
        block = source[start:end]

        self.assertIn("last_task = None", block)
        self.assertIn("lastStatus", block)
        self.assertIn("lastTask", block)

    def test_local_task_error_message_explains_task_timeout(self):
        source = self._client_source()
        start = source.index("def _local_task_error_message")
        end = source.index("def _is_xhs_guest_collection_block", start)
        block = source[start:end]

        self.assertIn('error == "task_timeout"', block)
        self.assertIn("本机浏览器任务超过等待时间", block)
        self.assertIn("任务ID", block)


if __name__ == "__main__":
    unittest.main()
