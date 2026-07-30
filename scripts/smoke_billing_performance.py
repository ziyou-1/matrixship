"""Local-only authenticated performance smoke for billing analytics."""

import json
import math
import os
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from billing_analytics import validate_billing_payload  # noqa: E402


REQUEST_COUNT = 200
WORKERS = 20
P95_LIMIT_MS = 800.0
REQUEST_TIMEOUT_SECONDS = 10


def _required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _local_base_url(value):
    parsed = urllib.parse.urlsplit(value.rstrip("/"))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("billing performance smoke accepts only a local HTTP base URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("billing performance smoke base URL must not contain credentials, query, or fragment")
    return value.rstrip("/")


def _percentile_nearest_rank(values, percentile):
    if not values:
        raise ValueError("cannot calculate percentile for an empty sample")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _analytics_url(base_url):
    end_date = date.today()
    start_date = end_date - timedelta(days=29)
    query = urllib.parse.urlencode(
        {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "groupBy": "day",
        }
    )
    return f"{base_url}/api/billing/analytics?{query}"


def _request_once(index, url, token):
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = response.status
            payload = json.loads(response.read().decode("utf-8"))
        validate_billing_payload("analytics_response", payload)
        return {"index": index, "status": status, "valid": status == 200, "elapsedMs": (time.perf_counter() - started) * 1000.0}
    except urllib.error.HTTPError as exc:
        return {"index": index, "status": exc.code, "valid": False, "elapsedMs": (time.perf_counter() - started) * 1000.0, "errorType": type(exc).__name__}
    except Exception as exc:
        return {"index": index, "status": 0, "valid": False, "elapsedMs": (time.perf_counter() - started) * 1000.0, "errorType": type(exc).__name__}


def run_smoke(base_url, token):
    url = _analytics_url(_local_base_url(base_url))
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(_request_once, index, url, token) for index in range(REQUEST_COUNT)]
        results = [future.result() for future in as_completed(futures)]

    elapsed = [item["elapsedMs"] for item in results]
    invalid = [
        {"index": item["index"], "status": item["status"], "errorType": item.get("errorType", "schema_or_status")}
        for item in results
        if not item["valid"]
    ]
    p95_ms = _percentile_nearest_rank(elapsed, 0.95)
    summary = {
        "ok": not invalid and p95_ms <= P95_LIMIT_MS,
        "event": "billing_performance_smoke_completed",
        "requests": REQUEST_COUNT,
        "workers": WORKERS,
        "validResponses": REQUEST_COUNT - len(invalid),
        "invalidResponses": len(invalid),
        "p95Ms": round(p95_ms, 3),
        "p95LimitMs": P95_LIMIT_MS,
    }
    if invalid:
        summary["failures"] = sorted(invalid, key=lambda item: item["index"])
    return summary


def main():
    try:
        result = run_smoke(
            _required_env("BILLING_SMOKE_BASE_URL"),
            _required_env("BILLING_SMOKE_TOKEN"),
        )
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0 if result["ok"] else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "event": "billing_performance_smoke_failed",
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
