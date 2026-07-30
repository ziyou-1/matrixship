# coding: utf-8
"""Short-lived HMAC tickets shared by MatrixShip and AI CanvasPro."""

import base64
import hashlib
import hmac
import json
import re
import time
import uuid


_MIN_SECRET_BYTES = 32
_MAX_TICKET_CHARS = 4096
_JTI_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class MatrixSsoError(ValueError):
    def __init__(self, code, message=""):
        self.code = str(code or "invalid_ticket")
        super().__init__(message or self.code)


def _secret_bytes(secret):
    raw = secret if isinstance(secret, bytes) else str(secret or "").encode("utf-8")
    if len(raw) < _MIN_SECRET_BYTES:
        raise MatrixSsoError("sso_secret_not_configured")
    return raw


def _b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value):
    text = str(value or "")
    try:
        return base64.urlsafe_b64decode(text + ("=" * (-len(text) % 4)))
    except Exception as exc:
        raise MatrixSsoError("malformed_ticket") from exc


def _bounded_text(value, limit):
    return str(value or "").strip()[: int(limit)]


def _positive_user_id(value):
    try:
        user_id = int(value)
    except (TypeError, ValueError) as exc:
        raise MatrixSsoError("invalid_user_id") from exc
    if user_id <= 0:
        raise MatrixSsoError("invalid_user_id")
    return user_id


def issue_ticket(
    secret,
    user_id,
    issuer="matrix-central",
    audience="aicanvas",
    org_id="",
    display_name="",
    ttl_seconds=60,
    now=None,
    nonce=None,
):
    key = _secret_bytes(secret)
    issued_at = int(time.time() if now is None else now)
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError) as exc:
        raise MatrixSsoError("invalid_ticket_ttl") from exc
    if ttl <= 0 or ttl > 300:
        raise MatrixSsoError("invalid_ticket_ttl")
    uid = _positive_user_id(user_id)
    ticket_id = _bounded_text(nonce or uuid.uuid4().hex, 128)
    if not _JTI_RE.fullmatch(ticket_id):
        raise MatrixSsoError("invalid_ticket_id")
    payload = {
        "v": 1,
        "iss": _bounded_text(issuer, 80),
        "aud": _bounded_text(audience, 80),
        "sub": str(uid),
        "user_id": uid,
        "org_id": _bounded_text(org_id, 128),
        "name": _bounded_text(display_name, 120),
        "iat": issued_at,
        "exp": issued_at + ttl,
        "jti": ticket_id,
    }
    if not payload["iss"] or not payload["aud"]:
        raise MatrixSsoError("invalid_ticket_contract")
    encoded_payload = _b64url_encode(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = hmac.new(key, encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return encoded_payload + "." + _b64url_encode(signature), payload


def verify_ticket(
    ticket,
    secret,
    issuer="matrix-central",
    audience="aicanvas",
    now=None,
    max_ttl_seconds=120,
    clock_skew_seconds=15,
):
    key = _secret_bytes(secret)
    raw_ticket = str(ticket or "").strip()
    if not raw_ticket or len(raw_ticket) > _MAX_TICKET_CHARS or raw_ticket.count(".") != 1:
        raise MatrixSsoError("malformed_ticket")
    encoded_payload, encoded_signature = raw_ticket.split(".", 1)
    expected = hmac.new(key, encoded_payload.encode("ascii"), hashlib.sha256).digest()
    actual = _b64url_decode(encoded_signature)
    if not hmac.compare_digest(expected, actual):
        raise MatrixSsoError("invalid_signature")
    try:
        payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
    except MatrixSsoError:
        raise
    except Exception as exc:
        raise MatrixSsoError("malformed_ticket") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise MatrixSsoError("invalid_ticket_version")
    if str(payload.get("iss") or "") != str(issuer or ""):
        raise MatrixSsoError("invalid_issuer")
    if str(payload.get("aud") or "") != str(audience or ""):
        raise MatrixSsoError("invalid_audience")
    uid = _positive_user_id(payload.get("user_id"))
    if str(payload.get("sub") or "") != str(uid):
        raise MatrixSsoError("invalid_subject")
    try:
        issued_at = int(payload.get("iat"))
        expires_at = int(payload.get("exp"))
        maximum_ttl = int(max_ttl_seconds)
        clock_skew = max(0, int(clock_skew_seconds))
    except (TypeError, ValueError) as exc:
        raise MatrixSsoError("invalid_ticket_time") from exc
    if expires_at <= issued_at:
        raise MatrixSsoError("invalid_ticket_time")
    if maximum_ttl <= 0 or expires_at - issued_at > maximum_ttl:
        raise MatrixSsoError("ticket_ttl_exceeded")
    current = int(time.time() if now is None else now)
    if issued_at > current + clock_skew:
        raise MatrixSsoError("ticket_not_yet_valid")
    if current >= expires_at:
        raise MatrixSsoError("expired_ticket")
    ticket_id = str(payload.get("jti") or "")
    if not _JTI_RE.fullmatch(ticket_id):
        raise MatrixSsoError("invalid_ticket_id")
    payload["user_id"] = uid
    payload["org_id"] = _bounded_text(payload.get("org_id"), 128)
    payload["name"] = _bounded_text(payload.get("name"), 120)
    return payload
