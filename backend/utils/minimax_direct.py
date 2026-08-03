from pathlib import Path
import ipaddress
import json
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen


H3_MODEL = "MiniMax-H3"
SUPPORTED_DURATIONS = range(4, 16)
SUPPORTED_RESOLUTIONS = {"768P", "2K"}


class MiniMaxDirectError(RuntimeError):
    pass


class _UrlResponse:
    def __init__(self, body, headers):
        self.content = body
        self.headers = dict(headers.items())

    def json(self):
        return json.loads(self.content.decode("utf-8"))


def _urllib_request(method, url, headers=None, json=None, timeout=None):
    request_headers = dict(headers or {})
    body = None
    if json is not None:
        body = __import__("json").dumps(json).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = Request(url, data=body, headers=request_headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        return _UrlResponse(response.read(), response.headers)


def _response_json(response, stage):
    if isinstance(response, dict):
        return response
    try:
        return response.json()
    except (AttributeError, TypeError, ValueError) as exc:
        raise MiniMaxDirectError(f"{stage}: provider returned invalid JSON") from exc


def _provider_error(payload):
    base_resp = payload.get("base_resp") if isinstance(payload, dict) else None
    if isinstance(base_resp, dict):
        code = base_resp.get("status_code")
        if code not in (None, 0, "0"):
            return base_resp.get("status_msg") or "provider rejected request"
    return None


def _https_url(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a public HTTPS URL")
    parsed = urlparse(value)
    host = (parsed.hostname or "").strip().lower()
    if parsed.scheme.lower() != "https" or not host:
        raise ValueError(f"{label} must be a public HTTPS URL")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError(f"{label} must be a public HTTPS URL")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise ValueError(f"{label} must be a public HTTPS URL")
    return value


def _validate_content(value):
    if isinstance(value, list):
        return [_validate_content(item) for item in value]
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            if key == "url":
                normalized[key] = _https_url(item, "content URL")
            else:
                normalized[key] = _validate_content(item)
        return normalized
    return value


def actual_model_for_mode(_mode=None):
    return H3_MODEL


def normalize_video_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("video request must be an object")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt is required")

    if "mode" in payload and payload.get("mode") not in (
        None,
        "",
        "video_generation",
    ):
        raise ValueError("H3 requests do not support provider modes")

    try:
        duration = int(payload.get("duration"))
    except (TypeError, ValueError) as exc:
        raise ValueError("duration must be an integer") from exc
    if duration not in SUPPORTED_DURATIONS:
        raise ValueError("duration must be between 4 and 15 seconds")

    resolution = str(payload.get("resolution") or "").upper()
    if resolution not in SUPPORTED_RESOLUTIONS:
        raise ValueError("resolution must be 768P or 2K")

    normalized = {
        "model": H3_MODEL,
        "mode": "video_generation",
        "prompt": prompt.strip(),
        "duration": duration,
        "resolution": resolution,
    }
    if "content" in payload:
        if not isinstance(payload["content"], list):
            raise ValueError("content must be an array")
        normalized["content"] = _validate_content(payload["content"])
    return normalized


class MiniMaxDirectClient:
    def __init__(
        self,
        base_url,
        api_key,
        timeout_sec=900,
        poll_interval_sec=10,
        request_fn=None,
    ):
        self.base_url = str(base_url).rstrip("/")
        if urlparse(self.base_url).scheme.lower() != "https":
            raise ValueError("MiniMax base_url must use HTTPS")
        self.api_key = str(api_key or "")
        self.timeout_sec = timeout_sec
        self.poll_interval_sec = poll_interval_sec
        self.request_fn = request_fn or _urllib_request
        self._poll_started_at = {}

    @property
    def _api_headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def _request(self, method, path, payload=None, headers=None):
        url = f"{self.base_url}{path}"
        return self.request_fn(
            method,
            url,
            headers={**self._api_headers, **(headers or {})},
            json=payload,
            timeout=self.timeout_sec,
        )

    def submit_video(self, request):
        normalized = normalize_video_request(request)
        provider_payload = {
            "model": H3_MODEL,
            "prompt": normalized["prompt"],
            "duration": normalized["duration"],
            "resolution": normalized["resolution"],
        }
        if "content" in normalized:
            provider_payload["content"] = normalized["content"]
        try:
            payload = _response_json(
                self._request("POST", "/v2/video_generation", provider_payload),
                "submit",
            )
        except MiniMaxDirectError:
            raise
        except Exception as exc:
            raise MiniMaxDirectError(f"submit: {type(exc).__name__}") from exc
        error = _provider_error(payload)
        if error:
            raise MiniMaxDirectError(f"submit: {error}")
        task_id = payload.get("task_id") or payload.get("taskId")
        if not task_id:
            raise MiniMaxDirectError("submit: provider task ID missing")
        return str(task_id)

    def poll_video(self, provider_task_id):
        task_id = str(provider_task_id or "").strip()
        if not task_id:
            raise ValueError("provider task ID is required")
        started_at = self._poll_started_at.setdefault(task_id, time.monotonic())
        if (
            self.timeout_sec is not None
            and time.monotonic() - started_at >= self.timeout_sec
        ):
            raise TimeoutError("poll: timeout reached")
        try:
            payload = _response_json(
                self._request(
                    "GET",
                    f"/v2/query/video_generation/{task_id}",
                ),
                "poll",
            )
        except MiniMaxDirectError:
            raise
        except Exception as exc:
            raise MiniMaxDirectError(f"poll: {type(exc).__name__}") from exc
        error = _provider_error(payload)
        if error:
            raise MiniMaxDirectError(f"poll: {error}")
        raw_status = payload.get("status") or payload.get("state")
        status = str(raw_status or "").lower()
        if status in {"success", "succeeded", "complete", "completed"}:
            payload["status"] = "success"
            self._poll_started_at.pop(task_id, None)
            return payload
        if status in {"pending", "processing", "queued", "running"}:
            payload["status"] = "pending"
            if self.poll_interval_sec:
                time.sleep(self.poll_interval_sec)
            return payload
        if status in {"fail", "failed", "failure", "cancelled", "canceled"}:
            self._poll_started_at.pop(task_id, None)
            raise MiniMaxDirectError(f"poll: provider task {status}")
        raise MiniMaxDirectError("poll: malformed provider status")

    def retrieve_video(self, provider_result):
        if not isinstance(provider_result, dict):
            raise MiniMaxDirectError("retrieve: provider result must be an object")
        task = provider_result.get("task")
        if not isinstance(task, dict):
            task = provider_result
        content = task.get("content")
        if not isinstance(content, dict) or not content.get("url"):
            raise MiniMaxDirectError("retrieve: provider task content URL missing")
        return _https_url(content["url"], "provider file")

    def download_video(self, url, destination):
        url = _https_url(url, "provider file")
        try:
            response = self.request_fn(
                "GET",
                url,
                headers={},
                json=None,
                timeout=self.timeout_sec,
            )
        except Exception as exc:
            raise MiniMaxDirectError(f"download: {type(exc).__name__}") from exc
        content = getattr(response, "content", None)
        if content is None:
            raise MiniMaxDirectError("download: provider returned no bytes")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        headers = getattr(response, "headers", {}) or {}
        return {
            "path": destination,
            "bytes": len(content),
            "content_type": headers.get("Content-Type") or headers.get("content-type"),
        }
