from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUBLISH_UTIL = ROOT / "backend" / "utils" / "publish_util.py"


class PublishUtilSafetyTest(unittest.TestCase):
    def test_ctf_local_safe_bypass_never_reports_live_publish_success(self):
        src = PUBLISH_UTIL.read_text(encoding="utf-8")
        bypass_blocks = re.findall(
            r"if _env_bool\('CTF_LOCAL_SAFE_PUBLISH', False\):(?P<body>.*?)(?:\n\s{16}(?:return|else:|elif )|\n\s{12}(?:return|else:|elif ))",
            src,
            flags=re.S,
        )

        self.assertEqual(2, len(bypass_blocks))
        for block in bypass_blocks:
            published_assignments = re.findall(
                r"result\[['\"]published['\"]\]\s*=\s*(.+)", block
            )
            self.assertEqual(["False"], [x.strip() for x in published_assignments])
            self.assertNotIn("result['ok'] = True", block)
            self.assertNotIn("result['error'] = None", block)

    def test_upload_pending_live_publish_keeps_browser_open(self):
        src = PUBLISH_UTIL.read_text(encoding="utf-8")

        self.assertIn("pending_deadline = None", src)
        self.assertIn("pending_deadline = time.monotonic() + _publish_pending_timeout(publish_timeout)", src)
        self.assertIn("keep_browser_open = True", src)
        self.assertIn("if not keep_browser_open:", src)

    def test_security_verify_keeps_browser_open_for_manual_action(self):
        src = PUBLISH_UTIL.read_text(encoding="utf-8")

        self.assertNotIn("('验证', 'security_verify_required')", src)
        self.assertIn("MANUAL_VERIFY_REASONS = {'security_verify_required', 'security_appeal_required'}", src)
        self.assertIn("if fail_reason in MANUAL_VERIFY_REASONS:", src)


    def test_publish_title_is_limited_to_30_chars_before_filling_douyin(self):
        src = PUBLISH_UTIL.read_text(encoding="utf-8")
        start = src.index("# 3) 填标题")
        end = src.index("if t:", start)
        title_src = src[start:end]

        self.assertIn("t = (title or '').strip()[:30]", title_src)


if __name__ == "__main__":
    unittest.main()
