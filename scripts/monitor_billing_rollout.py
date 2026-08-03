"""Billing endpoint rollout monitor with a strict rollback gate."""

import argparse
import json
import os
import re
import subprocess
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request


WINDOW_SIZE = 100
DEFAULT_THRESHOLD = 0.01
IMAGE_TAG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ROLLBACK_COMMAND = [
    "docker",
    "compose",
    "-f",
    "docker-compose.prod.yml",
    "up",
    "-d",
    "--no-build",
    "matrix-central",
]


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_RejectRedirectHandler())


def _required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def evaluate_window(status_codes, threshold=DEFAULT_THRESHOLD):
    statuses = list(status_codes)
    if len(statuses) != WINDOW_SIZE:
        raise ValueError("rollout evaluation requires exactly 100 status codes")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between zero and one")
    errors = sum(not 200 <= int(status) < 300 for status in statuses)
    error_rate = errors / WINDOW_SIZE
    return {
        "sampleSize": WINDOW_SIZE,
        "errorCount": errors,
        "errorRate": error_rate,
        "threshold": threshold,
        "rollback": error_rate > threshold,
    }


def rollback_command(previous_tag):
    if not IMAGE_TAG_PATTERN.fullmatch(previous_tag or ""):
        raise ValueError("invalid previous image tag")
    return list(ROLLBACK_COMMAND)


def execute_rollback(previous_tag, dry_run=False):
    command = rollback_command(previous_tag)
    result = {"command": command, "imageTag": previous_tag, "executed": False}
    if dry_run:
        return result
    environment = os.environ.copy()
    environment["IMAGE_TAG"] = previous_tag
    completed = subprocess.run(command, env=environment, shell=False, check=True)
    result.update({"executed": True, "returnCode": completed.returncode})
    return result


def sample_statuses(base_url, token):
    parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid billing monitor base URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("billing monitor base URL must not contain credentials, query, or fragment")
    url = f"{base_url.rstrip('/')}/api/billing/analytics"
    statuses = []
    for _ in range(WINDOW_SIZE):
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with _NO_REDIRECT_OPENER.open(request, timeout=10) as response:
                statuses.append(response.status)
        except urllib.error.HTTPError as exc:
            statuses.append(exc.code)
        except (OSError, TimeoutError):
            statuses.append(0)
    return statuses


def _fixture_statuses(error_rate):
    if not 0 <= error_rate <= 1:
        raise ValueError("fixture error rate must be between zero and one")
    error_count = round(error_rate * WINDOW_SIZE)
    if abs(error_rate - error_count / WINDOW_SIZE) > 1e-12:
        raise ValueError("fixture error rate must use one-percent increments")
    return [200] * (WINDOW_SIZE - error_count) + [503] * error_count


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Monitor billing rollout and gate rollback")
    parser.add_argument("--dry-run", action="store_true", help="report the rollback selection without invoking Docker")
    parser.add_argument("--fixture-error-rate", type=float, help="controlled dry-run fixture; does not access a service")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    try:
        previous_tag = _required_env("PREVIOUS_IMAGE_TAG")
        rollback_command(previous_tag)
        if args.fixture_error_rate is not None:
            if not args.dry_run:
                raise ValueError("fixture error rate is allowed only with --dry-run")
            statuses = _fixture_statuses(args.fixture_error_rate)
        else:
            statuses = sample_statuses(
                _required_env("BILLING_MONITOR_BASE_URL"),
                _required_env("BILLING_MONITOR_TOKEN"),
            )

        decision = evaluate_window(statuses)
        action = {
            "command": rollback_command(previous_tag),
            "imageTag": previous_tag,
            "executed": False,
        }
        if decision["rollback"]:
            action = execute_rollback(previous_tag, dry_run=args.dry_run)
        result = {"ok": True, "event": "billing_rollout_evaluated", **decision, **action}
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "event": "billing_rollout_failed",
                    "errorType": type(exc).__name__,
                    "error": str(exc),
                    "stack": traceback.format_exc(),
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
