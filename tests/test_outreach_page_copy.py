from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


class OutreachPageCopyTest(unittest.TestCase):
    def test_ai_outreach_page_explains_comment_outreach_flow(self):
        source = CLIENT.read_text(encoding="utf-8")
        start = source.index("class OutreachPage")
        end = source.index("class GrowthPage", start)
        block = source[start:end]

        self.assertIn("AI 触达是做什么的", block)
        self.assertIn("不是私信群发", block)
        self.assertIn("搜索相关视频/笔记", block)
        self.assertIn("筛选出有咨询、比价、想了解意向的潜在客户", block)
        self.assertIn("生成一条短评论话术", block)
        self.assertIn("通过本机浏览器在评论区回复/评论", block)
        self.assertIn("默认限量、间隔发送", block)
        self.assertIn("status.setWordWrap(True)", block)


if __name__ == "__main__":
    unittest.main()
