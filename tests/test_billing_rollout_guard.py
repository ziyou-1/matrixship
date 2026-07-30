import json
import os
import subprocess
import unittest
from unittest import mock

from scripts import monitor_billing_rollout as rollout


class BillingRolloutGuardTest(unittest.TestCase):
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

    def test_evaluate_window_requires_exactly_one_hundred_statuses(self):
        for statuses in ([], [200] * 99, [200] * 101):
            with self.subTest(size=len(statuses)):
                with self.assertRaisesRegex(ValueError, "exactly 100"):
                    rollout.evaluate_window(statuses)


if __name__ == "__main__":
    unittest.main()
