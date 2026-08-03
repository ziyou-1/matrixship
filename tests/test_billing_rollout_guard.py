import json
import os
import subprocess
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from unittest import mock

from scripts import monitor_billing_rollout as rollout


class BillingRolloutGuardTest(unittest.TestCase):
    def test_redirect_is_counted_as_error_without_following_or_forwarding_authorization(self):
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
                self.end_headers()

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            statuses = rollout.sample_statuses(
                f"http://127.0.0.1:{server.server_port}",
                "redirect-regression-token",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(statuses, [302] * rollout.WINDOW_SIZE)
        self.assertEqual(observed["redirect"], rollout.WINDOW_SIZE)
        self.assertEqual(observed["target"], 0)
        self.assertIsNone(observed["targetAuthorization"])

    def test_more_than_one_percent_errors_requests_rollback(self):
        decision = rollout.evaluate_window([200] * 98 + [503] * 2, threshold=0.01)
        self.assertTrue(decision["rollback"])
        self.assertEqual(decision["errorRate"], 0.02)
        self.assertEqual(decision["sampleSize"], 100)

    def test_one_percent_does_not_cross_threshold(self):
        decision = rollout.evaluate_window([200] * 99 + [503], threshold=0.01)
        self.assertFalse(decision["rollback"])
        self.assertEqual(decision["errorRate"], 0.01)

    def test_rollback_command_requires_strict_image_tag(self):
        expected = [
            "docker",
            "compose",
            "-f",
            "docker-compose.prod.yml",
            "up",
            "-d",
            "--no-build",
            "matrix-central",
        ]
        self.assertEqual(rollout.rollback_command("stable-previous"), expected)
        for invalid in ("", "-leading", "tag with space", "stable/latest", "x" * 129):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "invalid previous image tag"):
                    rollout.rollback_command(invalid)

    def test_execute_rollback_uses_argument_list_copied_env_and_shell_false(self):
        original_env = dict(os.environ)
        with mock.patch("subprocess.run") as run:
            result = rollout.execute_rollback("stable-previous", dry_run=False)

        run.assert_called_once()
        _, kwargs = run.call_args
        self.assertEqual(kwargs["env"]["IMAGE_TAG"], "stable-previous")
        self.assertIsNot(kwargs["env"], os.environ)
        self.assertFalse(kwargs["shell"])
        self.assertTrue(kwargs["check"])
        self.assertEqual(dict(os.environ), original_env)
        self.assertTrue(result["executed"])

    def test_dry_run_never_invokes_subprocess_and_logs_no_token(self):
        with mock.patch("subprocess.run") as run:
            result = rollout.execute_rollback("stable-previous", dry_run=True)
        run.assert_not_called()
        rendered = json.dumps(result)
        self.assertNotIn("BILLING_MONITOR_TOKEN", rendered)
        self.assertNotIn("Authorization", rendered)
        self.assertFalse(result["executed"])

    def test_cli_fixture_dry_run_invokes_neither_network_nor_subprocess(self):
        output = StringIO()
        with mock.patch.dict(os.environ, {"PREVIOUS_IMAGE_TAG": "stable-previous"}, clear=False):
            with mock.patch.object(rollout, "sample_statuses") as sample_statuses:
                with mock.patch("urllib.request.OpenerDirector.open") as network_open:
                    with mock.patch("subprocess.run") as run:
                        with redirect_stdout(output):
                            exit_code = rollout.main(["--dry-run", "--fixture-error-rate", "0.02"])

        self.assertEqual(exit_code, 0)
        sample_statuses.assert_not_called()
        network_open.assert_not_called()
        run.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertTrue(result["rollback"])
        self.assertFalse(result["executed"])

    def test_evaluate_window_requires_exactly_one_hundred_statuses(self):
        for statuses in ([], [200] * 99, [200] * 101):
            with self.subTest(size=len(statuses)):
                with self.assertRaisesRegex(ValueError, "exactly 100"):
                    rollout.evaluate_window(statuses)


if __name__ == "__main__":
    unittest.main()
