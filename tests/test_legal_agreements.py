import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CLIENT = BACKEND / "matrix_native_client.py"
SERVER = BACKEND / "central_server.py"


def load_module(name, path):
    backend_text = str(BACKEND)
    if backend_text not in sys.path:
        sys.path.insert(0, backend_text)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LegalAgreementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_module("matrix_native_client_for_legal", CLIENT)
        cls.server = load_module("central_server_for_legal", SERVER)

    def test_bundled_documents_match_confirmed_operator_and_billing(self):
        terms = self.client._load_legal_document("terms")
        privacy = self.client._load_legal_document("privacy")

        for text in (terms, privacy):
            self.assertIn("云灵星图数字科技有限公司", text)
            self.assertIn("15962658751", text)
            self.assertIn("597399219@qq.com", text)
            self.assertIn("昆山开发区春旭路188号帝宝国际大厦2202室", text)
        self.assertIn("1 云豆 = 1 元", terms)
        self.assertIn("人脸", privacy)
        self.assertIn("第三方 AI", privacy)

    def test_client_builds_versioned_consent_payload(self):
        payload = self.client._legal_consent_payload()

        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["termsVersion"], "1.0")
        self.assertEqual(payload["privacyVersion"], "1.0")
        self.assertEqual(payload["clientVersion"], self.client.APP_VERSION)
        self.assertRegex(payload["acceptedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_center_rejects_missing_or_outdated_consent(self):
        consent, error = self.server.validate_legal_consent({})
        self.assertIsNone(consent)
        self.assertEqual(error, "legal_consent_required")

        consent, error = self.server.validate_legal_consent({"legalConsent": {
            "accepted": True,
            "termsVersion": "0.9",
            "privacyVersion": "1.0",
            "acceptedAt": "2026-07-15T00:00:00Z",
            "clientVersion": "1.1.16",
        }})
        self.assertIsNone(consent)
        self.assertEqual(error, "legal_consent_outdated")

        current = self.client._legal_consent_payload()
        consent, error = self.server.validate_legal_consent({"legalConsent": current})
        self.assertEqual(error, "")
        self.assertEqual(consent["termsVersion"], self.server.LEGAL_TERMS_VERSION)

    def test_center_records_latest_consent_and_audit(self):
        user = {"id": "user-legal", "name": "Test", "meta": {}}
        consent = self.client._legal_consent_payload()
        old_state = self.server.STATE
        self.server.STATE = {"users": [user], "legalConsents": {}, "auditLogs": []}
        handler = mock.Mock()
        handler.headers = {"User-Agent": "MatrixShip-test"}
        handler.client_address = ("127.0.0.1", 12345)
        try:
            with mock.patch.object(self.server, "persist"), mock.patch.object(self.server, "add_audit") as audit:
                record = self.server.record_legal_consent(handler, user, consent)
        finally:
            self.server.STATE = old_state

        self.assertEqual(record["termsVersion"], "1.0")
        self.assertGreater(record["acceptedAtServer"], 0)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[1], "legal.consent.accept")

    def test_login_page_wires_both_links_to_local_dialog(self):
        source = CLIENT.read_text(encoding="utf-8")
        self.assertIn("class LegalAgreementDialog", source)
        self.assertIn('href="terms"', source)
        self.assertIn('href="privacy"', source)
        self.assertIn("alab.linkActivated.connect(self._show_legal_document)", source)
        self.assertIn('"legalConsent": _legal_consent_payload()', source)
        self.assertIn("_auth_pref_has_current_legal_consent", source)


if __name__ == "__main__":
    unittest.main()
