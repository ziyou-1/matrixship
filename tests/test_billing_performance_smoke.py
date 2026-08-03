import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from scripts import smoke_billing_performance as performance


class BillingPerformanceSmokeTest(unittest.TestCase):
    def test_redirect_is_invalid_without_following_or_forwarding_authorization(self):
        observed = {"redirect": 0, "target": 0, "targetAuthorization": None}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/api/billing/analytics":
                    observed["redirect"] += 1
                    self.send_response(302)
                    self.send_header("Location", "/redirect-target")
                    self.end_headers()
                    return
                observed["target"] += 1
                observed["targetAuthorization"] = self.headers.get("Authorization")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = performance._request_once(
                0,
                f"http://127.0.0.1:{server.server_port}/api/billing/analytics",
                "redirect-regression-token",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result["status"], 302)
        self.assertFalse(result["valid"])
        self.assertEqual(observed["redirect"], 1)
        self.assertEqual(observed["target"], 0)
        self.assertIsNone(observed["targetAuthorization"])

    def test_any_invalid_response_fails_the_full_smoke(self):
        def request_once(index, _url, _token):
            return {
                "index": index,
                "status": 200 if index == 0 else 503,
                "valid": index == 0,
                "elapsedMs": 1.0,
            }

        with mock.patch.object(performance, "REQUEST_COUNT", 2):
            with mock.patch.object(performance, "WORKERS", 2):
                with mock.patch.object(performance, "_request_once", side_effect=request_once):
                    result = performance.run_smoke("http://127.0.0.1:19080", "test-token")

        self.assertFalse(result["ok"])
        self.assertEqual(result["validResponses"], 1)
        self.assertEqual(result["invalidResponses"], 1)

    def test_nearest_rank_p95_accepts_exactly_800_ms_and_rejects_above(self):
        def run_with_p95(boundary):
            def request_once(index, _url, _token):
                return {
                    "index": index,
                    "status": 200,
                    "valid": True,
                    "elapsedMs": 1.0 if index < 189 else boundary,
                }

            with mock.patch.object(performance, "_request_once", side_effect=request_once):
                return performance.run_smoke("http://127.0.0.1:19080", "test-token")

        at_limit = run_with_p95(800.0)
        above_limit = run_with_p95(800.001)

        self.assertEqual(at_limit["p95Ms"], 800.0)
        self.assertTrue(at_limit["ok"])
        self.assertEqual(above_limit["p95Ms"], 800.001)
        self.assertFalse(above_limit["ok"])


if __name__ == "__main__":
    unittest.main()
