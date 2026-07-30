import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "backend" / "utils" / "structured_log.py"


def load_module():
    if not MODULE_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("structured_log_under_test", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeLogger:
    def __init__(self):
        self.rows = []

    def error(self, value):
        self.rows.append(("error", value))

    def info(self, value):
        self.rows.append(("info", value))


class StructuredLogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logs = load_module()

    def require_module(self):
        self.assertIsNotNone(self.logs, "backend/utils/structured_log.py is missing")

    def test_signed_url_keeps_query_names_but_not_values(self):
        self.require_module()
        redacted = self.logs.redact_url(
            "https://video.example/path/file.mp4?token=secret-value&expires=12345"
        )

        self.assertIn("video.example/path/file.mp4", redacted)
        self.assertIn("token", redacted)
        self.assertIn("expires", redacted)
        self.assertNotIn("secret-value", redacted)
        self.assertNotIn("12345", redacted)

    def test_redact_url_removes_userinfo_and_preserves_explicit_port(self):
        self.require_module()

        redacted = self.logs.redact_url(
            "https://fake-user:fake-pass@api.example:8443/v1/items?signature=fake-signature&attempt=2"
        )

        self.assertEqual(
            redacted,
            "https://api.example:8443/v1/items?signature&attempt",
        )
        self.assertNotIn("fake-user", redacted)
        self.assertNotIn("fake-pass", redacted)

    def test_redact_url_removes_userinfo_from_ipv6_and_preserves_port(self):
        self.require_module()

        redacted = self.logs.redact_url(
            "https://fake-user:fake-pass@[2001:db8::1]:9443/v1/items?signature=fake-signature"
        )

        self.assertEqual(
            redacted,
            "https://[2001:db8::1]:9443/v1/items?signature",
        )
        self.assertNotIn("fake-user", redacted)
        self.assertNotIn("fake-pass", redacted)

    def test_redact_url_fails_closed_for_malformed_urls(self):
        self.require_module()
        malformed_urls = (
            "",
            "//api.example/v1/items?signature=fake-signature",
            "https:///v1/items?signature=fake-signature",
            "https://[2001:db8::1",
        )

        for url in malformed_urls:
            with self.subTest(url=url):
                self.assertEqual("<redacted-url>", self.logs.redact_url(url))

    def test_url_named_field_with_pure_url_keeps_url_structure(self):
        self.require_module()
        logger = FakeLogger()

        raw = self.logs.json_log(
            logger,
            "callback_registered",
            callback_url="https://hooks.example/v1/callback?signature=fake-signature&attempt=2",
        )
        payload = json.loads(raw)

        self.assertEqual(
            payload["callback_url"],
            "https://hooks.example/v1/callback?signature&attempt",
        )

    def test_url_named_field_with_mixed_text_uses_full_text_redaction(self):
        self.require_module()
        logger = FakeLogger()

        raw = self.logs.json_log(
            logger,
            "callback_failed",
            callback_url=(
                "failed https://hooks.example/v1/callback?signature=fake-signature&attempt=2 "
                "using Bearer fake-bearer-token and sk-examplevalue123"
            ),
        )

        self.assertIn(
            "https://hooks.example/v1/callback?signature&attempt",
            raw,
        )
        self.assertNotIn("fake-signature", raw)
        self.assertNotIn("=2", raw)
        self.assertNotIn("fake-bearer-token", raw)
        self.assertNotIn("sk-examplevalue123", raw)
        self.assertIn("Bearer <redacted>", raw)
        self.assertIn("sk-<redacted>", raw)

    def test_json_log_redacts_secrets_and_includes_stack(self):
        self.require_module()
        logger = FakeLogger()
        exc = RuntimeError("remote request failed")

        raw = self.logs.json_log(
            logger,
            "video_download_failed",
            exc=exc,
            cookie="session-secret",
            authorization="Bearer private-token",
            api_key="sk-private",
            signed_url="https://video.example/v.mp4?token=url-secret",
            material_id="m1",
        )
        payload = json.loads(raw)

        self.assertEqual(payload["event"], "video_download_failed")
        self.assertTrue(payload["errorId"].startswith("err-"))
        self.assertIn("RuntimeError", payload["stack"])
        self.assertEqual(payload["material_id"], "m1")
        self.assertNotIn("session-secret", raw)
        self.assertNotIn("private-token", raw)
        self.assertNotIn("sk-private", raw)
        self.assertNotIn("url-secret", raw)
        self.assertEqual(len(logger.rows), 1)

    def test_json_log_redacts_embedded_url_query_values_in_plain_text(self):
        self.require_module()
        logger = FakeLogger()

        raw = self.logs.json_log(
            logger,
            "upstream_request_failed",
            message=(
                "GET https://api.example/v1/items?cursor=fake-cursor-value&limit=25 "
                "with Bearer fake-bearer-token and sk-examplevalue123"
            ),
        )

        self.assertIn("https://api.example/v1/items?cursor&limit", raw)
        self.assertNotIn("fake-cursor-value", raw)
        self.assertNotIn("=25", raw)
        self.assertNotIn("fake-bearer-token", raw)
        self.assertNotIn("sk-examplevalue123", raw)
        self.assertIn("Bearer <redacted>", raw)
        self.assertIn("sk-<redacted>", raw)

    def test_plain_text_preserves_token_and_fullwidth_url_punctuation(self):
        self.require_module()
        logger = FakeLogger()

        raw = self.logs.json_log(
            logger,
            "request_failed",
            message=(
                "错误中sk-examplevalue123；授权 Bearer fake-token.segment_value.last-part'). "
                "请求（https://fake-user:fake-pass@api.example:8443/v1/items?signature=fake-signature&attempt=2）；继续处理。"
                "畸形 https:///private?signature=malformed-secret。"
            ),
        )

        self.assertIn("错误中sk-<redacted>；", raw)
        self.assertIn("Bearer <redacted>').", raw)
        self.assertIn(
            "请求（https://api.example:8443/v1/items?signature&attempt）；继续处理。",
            raw,
        )
        self.assertIn("畸形 <redacted-url>。", raw)
        self.assertNotIn("sk-examplevalue123", raw)
        self.assertNotIn("fake-token", raw)
        self.assertNotIn("segment_value", raw)
        self.assertNotIn("last-part", raw)
        self.assertNotIn("fake-user", raw)
        self.assertNotIn("fake-pass", raw)
        self.assertNotIn("fake-signature", raw)
        self.assertNotIn("malformed-secret", raw)
        self.assertNotIn("=2", raw)

    def test_plain_text_preserves_each_fullwidth_url_delimiter(self):
        self.require_module()
        delimiter_pairs = (
            ("（", "）"),
            ("", "。"),
            ("", "，"),
            ("", "；"),
            ("", "："),
            ("“", "”"),
        )

        for opening, closing in delimiter_pairs:
            with self.subTest(closing=closing):
                raw = self.logs.json_log(
                    FakeLogger(),
                    "request_failed",
                    message=(
                        f"前文{opening}https://api.example/v1/items?signature=fake-signature"
                        f"{closing}后文"
                    ),
                )
                self.assertIn(
                    f"前文{opening}https://api.example/v1/items?signature{closing}后文",
                    raw,
                )
                self.assertNotIn("fake-signature", raw)

    def test_plain_text_url_with_legal_apostrophe_redacts_entire_query(self):
        self.require_module()
        logger = FakeLogger()

        raw = self.logs.json_log(
            logger,
            "upstream_request_failed",
            message=(
                "request ('GET https://api.example/v1/items?signature=alpha'beta-private&expires=1700000000')."
            ),
        )

        self.assertIn(
            "request ('GET https://api.example/v1/items?signature&expires').",
            raw,
        )
        self.assertNotIn("alpha", raw)
        self.assertNotIn("beta-private", raw)
        self.assertNotIn("1700000000", raw)

    def test_real_traceback_redacts_url_query_with_legal_apostrophe(self):
        self.require_module()
        logger = FakeLogger()

        try:
            raise RuntimeError(
                "错误中sk-examplevalue123；request failed with Bearer fake-token.segment_value.last-part'). "
                "请求（https://fake-user:fake-pass@files.example:9443/download/archive.zip?signature=query-prefix'value-private&expires=1700000000）；继续处理。"
                "畸形 https:///private?signature=malformed-secret。"
            )
        except RuntimeError as exc:
            raw = self.logs.json_log(logger, "download_failed", exc=exc)
        payload = json.loads(raw)

        self.assertIn("Traceback (most recent call last)", payload["stack"])
        self.assertIn("raise RuntimeError", payload["stack"])
        self.assertIn(
            "请求（https://files.example:9443/download/archive.zip?signature&expires）；继续处理。",
            payload["stack"],
        )
        self.assertIn("畸形 <redacted-url>。", payload["stack"])
        self.assertIn("错误中sk-<redacted>；", payload["stack"])
        self.assertIn("Bearer <redacted>", payload["stack"])
        self.assertIn("Bearer <redacted>').", payload["stack"])
        self.assertIn("sk-<redacted>", payload["stack"])
        self.assertNotIn("fake-token", raw)
        self.assertNotIn("segment_value", raw)
        self.assertNotIn("last-part", raw)
        self.assertNotIn("sk-examplevalue123", raw)
        self.assertNotIn("fake-user", raw)
        self.assertNotIn("fake-pass", raw)
        self.assertNotIn("query-prefix", raw)
        self.assertNotIn("value-private", raw)
        self.assertNotIn("malformed-secret", raw)
        self.assertNotIn("1700000000", raw)


if __name__ == "__main__":
    unittest.main()
