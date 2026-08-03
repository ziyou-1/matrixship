import json
import re
import traceback
import uuid
from urllib.parse import parse_qsl, urlsplit, urlunsplit


_SENSITIVE_KEYS = (
    "api_key",
    "apikey",
    "authorization",
    "base64",
    "cookie",
    "password",
    "secret",
    "token",
)
_URL_TEXT_DELIMITERS = "。．，、；：！？…（）［］【】〔〕｛｝《》〈〉「」『』“”‘’＂＇"
_HTTP_URL_RE = re.compile(
    r'https?://[^\s<>"\x00-\x1f' + re.escape(_URL_TEXT_DELIMITERS) + r"]+",
    re.IGNORECASE,
)
_BEARER_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])Bearer[ \t]+[A-Za-z0-9_~+/=-]+(?:\.[A-Za-z0-9_~+/=-]+)*",
    re.IGNORECASE,
)
_TRAILING_URL_PUNCTUATION = ".,;:!?。．，、；：！？…”’＂＇"
_URL_CLOSING_PAIRS = {
    ")": "(",
    "]": "[",
    "}": "{",
    "）": "（",
    "］": "［",
    "】": "【",
    "〕": "〔",
    "｝": "｛",
    "》": "《",
    "〉": "〈",
    "」": "「",
    "』": "『",
}


def _hostname_with_port(parsed):
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL hostname is missing")
    if ":" in hostname:
        hostname = "[" + hostname + "]"
    port = parsed.port
    if port is not None:
        return hostname + ":" + str(port)
    return hostname


def redact_url(url):
    value = str(url or "")
    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.netloc:
            return "<redacted-url>"
        netloc = _hostname_with_port(parsed)
        keys = [key for key, _value in parse_qsl(parsed.query, keep_blank_values=True)]
        query = "&".join(dict.fromkeys(keys))
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))
    except Exception:
        return "<redacted-url>"


def _split_url_suffix(value, has_opening_quote=False):
    candidate = value
    suffix = ""
    while candidate:
        last = candidate[-1]
        if last in _TRAILING_URL_PUNCTUATION:
            candidate = candidate[:-1]
            suffix = last + suffix
            continue
        opening = _URL_CLOSING_PAIRS.get(last)
        if opening and candidate.count(last) > candidate.count(opening):
            candidate = candidate[:-1]
            suffix = last + suffix
            continue
        break
    if has_opening_quote and candidate.endswith("'"):
        candidate = candidate[:-1]
        suffix = "'" + suffix
    return candidate, suffix


def _has_unclosed_single_quote(value):
    has_opening_quote = False
    escaped = False
    for index, character in enumerate(value):
        if character == "\\":
            escaped = not escaped
            continue
        if character == "'" and not escaped:
            previous = value[index - 1] if index else ""
            following = value[index + 1] if index + 1 < len(value) else ""
            if not (previous.isalnum() and following.isalnum()):
                has_opening_quote = not has_opening_quote
        escaped = False
    return has_opening_quote


def _redact_url_match(match):
    has_opening_quote = _has_unclosed_single_quote(match.string[:match.start()])
    candidate, suffix = _split_url_suffix(match.group(0), has_opening_quote)
    return redact_url(candidate) + suffix


def _is_standalone_url(value):
    text = str(value or "")
    if not text or any(character.isspace() for character in text):
        return False
    try:
        parsed = urlsplit(text)
        return bool(parsed.scheme and parsed.netloc)
    except Exception:
        return False


def _redact_text(value):
    text = str(value or "")
    text = _HTTP_URL_RE.sub(_redact_url_match, text)
    text = _BEARER_TOKEN_RE.sub("Bearer <redacted>", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-<redacted>", text)
    return text


def _sanitize(value, key_hint=""):
    key_lower = str(key_hint or "").lower()
    if any(part in key_lower for part in _SENSITIVE_KEYS):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(key): _sanitize(child, str(key)) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(child, key_hint) for child in value]
    if isinstance(value, str):
        if _is_standalone_url(value):
            return redact_url(value)
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(value)


def json_log(logger, event, level="error", exc=None, **context):
    explicit_error_id = str(context.pop("errorId", "") or "")
    level_name = str(level or "error").lower()
    payload = {
        "event": str(event or "unknown_event"),
    }
    if explicit_error_id:
        payload["errorId"] = explicit_error_id
    elif exc is not None or level_name in ("error", "warning", "critical", "exception"):
        payload["errorId"] = "err-" + uuid.uuid4().hex[:16]
    payload.update(_sanitize(context))
    if exc is not None:
        payload["exceptionType"] = type(exc).__name__
        payload["stack"] = _redact_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    writer = getattr(logger, level_name, None) or getattr(logger, "error")
    writer(raw)
    return raw
