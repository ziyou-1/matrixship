import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SSO_MODULE = BACKEND / "matrix_sso.py"
CENTRAL_SERVER = BACKEND / "central_server.py"


def load_module(name, path):
    backend_text = str(BACKEND)
    if backend_text not in sys.path:
        sys.path.insert(0, backend_text)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ComicSsoContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sso = load_module("matrix_sso_under_test", SSO_MODULE)

    def test_ticket_round_trip_preserves_shared_user_scope(self):
        ticket, issued = self.sso.issue_ticket(
            secret="s" * 48,
            issuer="matrix-central",
            audience="aicanvas",
            user_id=44,
            org_id="org-default",
            display_name="测试用户",
            ttl_seconds=60,
            now=1_000,
            nonce="nonce-44",
        )

        verified = self.sso.verify_ticket(
            ticket,
            secret="s" * 48,
            issuer="matrix-central",
            audience="aicanvas",
            now=1_030,
            max_ttl_seconds=120,
        )

        self.assertEqual(verified, issued)
        self.assertEqual(verified["user_id"], 44)
        self.assertEqual(verified["sub"], "44")
        self.assertEqual(verified["org_id"], "org-default")
        self.assertEqual(verified["jti"], "nonce-44")

    def test_ticket_rejects_tampering_wrong_audience_and_expiry(self):
        ticket, _payload = self.sso.issue_ticket(
            secret="s" * 48,
            issuer="matrix-central",
            audience="aicanvas",
            user_id=44,
            ttl_seconds=60,
            now=1_000,
            nonce="nonce-44",
        )
        payload_part, signature_part = ticket.split(".", 1)
        tampered = payload_part[:-1] + ("A" if payload_part[-1] != "A" else "B") + "." + signature_part

        cases = (
            (tampered, "aicanvas", 1_030, "invalid_signature"),
            (ticket, "another-service", 1_030, "invalid_audience"),
            (ticket, "aicanvas", 1_060, "expired_ticket"),
        )
        for candidate, audience, now_value, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(self.sso.MatrixSsoError) as raised:
                    self.sso.verify_ticket(
                        candidate,
                        secret="s" * 48,
                        issuer="matrix-central",
                        audience=audience,
                        now=now_value,
                        max_ttl_seconds=120,
                    )
                self.assertEqual(raised.exception.code, expected_code)

    def test_ticket_rejects_short_secret_and_unbounded_ttl(self):
        with self.assertRaises(self.sso.MatrixSsoError) as raised:
            self.sso.issue_ticket(secret="short", user_id=44)
        self.assertEqual(raised.exception.code, "sso_secret_not_configured")

        ticket, _payload = self.sso.issue_ticket(
            secret="s" * 48,
            user_id=44,
            ttl_seconds=180,
            now=1_000,
        )
        with self.assertRaises(self.sso.MatrixSsoError) as raised:
            self.sso.verify_ticket(
                ticket,
                secret="s" * 48,
                now=1_010,
                max_ttl_seconds=120,
            )
        self.assertEqual(raised.exception.code, "ticket_ttl_exceeded")


class CentralComicSsoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.central = load_module("central_server_comic_sso_under_test", CENTRAL_SERVER)
        cls.sso = load_module("matrix_sso_for_central_fixed_test", SSO_MODULE)

    def test_central_issues_ticket_for_fixed_comic_account(self):
        with mock.patch.object(self.central, "COMIC_SSO_ENABLED", True), \
                mock.patch.object(self.central, "COMIC_SSO_SECRET", "s" * 48), \
                mock.patch.object(self.central, "COMIC_FIXED_USER_ID", "44", create=True), \
                mock.patch.object(self.central, "COMIC_FIXED_USERNAME", "003", create=True), \
                mock.patch.object(self.central, "COMIC_FIXED_DISPLAY_NAME", "003", create=True):
            response = self.central.issue_comic_sso_ticket_for_user(
                {"id": "user-owner", "name": "local user"},
                "org-default",
                now_ts=1_000,
                nonce="nonce-44",
            )

        self.assertTrue(response["ok"])
        self.assertEqual(response["expiresAt"], 1_060)
        self.assertEqual(response["exchangePath"], "/api/v2/auth/exchange-matrix-ticket")
        self.assertEqual(response["userId"], 44)
        self.assertEqual(response["matrixUserId"], "user-owner")
        self.assertEqual(response["comicUsername"], "003")
        self.assertEqual(response["comicAccountMode"], "fixed")
        self.assertNotIn("secret", response)

        verified = self.sso.verify_ticket(
            response["ticket"],
            secret="s" * 48,
            issuer="matrix-central",
            audience="aicanvas",
            now=1_030,
            max_ttl_seconds=120,
        )
        self.assertEqual(verified["user_id"], 44)
        self.assertEqual(verified["name"], "003")

    def test_central_fails_closed_when_sso_is_disabled_or_secret_missing(self):
        user = {"id": 44, "name": "测试用户", "_mdb": True}
        cases = (
            (False, "s" * 48, "comic_sso_disabled"),
            (True, "", "comic_sso_secret_missing"),
        )
        for enabled, secret, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with mock.patch.object(self.central, "COMIC_SSO_ENABLED", enabled), \
                        mock.patch.object(self.central, "COMIC_SSO_SECRET", secret):
                    with self.assertRaises(self.central.ComicSsoIssueError) as raised:
                        self.central.issue_comic_sso_ticket_for_user(user, "org-default")
                self.assertEqual(raised.exception.code, expected_code)


if __name__ == "__main__":
    unittest.main()
