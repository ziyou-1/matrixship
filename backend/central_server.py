# coding: utf-8
"""MatrixShip central scheduler.

Commercial scheme #3:

    Native client -> central_server -> many execution nodes -> Douyin

Users do not install a local helper.  Each execution node is operated by you and
has its own IP, browser profile, cookies and cooldown state.  If one node is
risk-blocked, only tasks routed to that node are affected.
"""

import json
import mimetypes
import os
import platform
import re
import shutil
import sqlite3
import hashlib
import hmac
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse, urlencode
import urllib.error
import urllib.request

from loguru import logger

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(os.path.dirname(_HERE), ".env"), override=False)
    load_dotenv(os.path.join(_HERE, ".env"), override=True)

try:
    import maindb  # 漫剧(ai-education)共享主库访问层:用户/余额/价格/资产
except Exception:
    maindb = None

from utils.media_validation import cleanup_quarantine, validate_image_file, validate_video_file
from utils.structured_log import json_log


CENTRAL_VERSION = "1.1.16-agent-mode"
HOST = os.getenv("CENTRAL_HOST", os.getenv("API_HOST", "0.0.0.0"))
PORT = int(os.getenv("CENTRAL_PORT", os.getenv("API_PORT", "9080")))
DATA_DIR = os.path.abspath(os.path.expandvars(os.getenv("CENTRAL_DATA_DIR", os.path.join(os.path.dirname(__file__), "central_data"))))
STORE_JSON = os.path.join(DATA_DIR, "scheduler_state.json")
SQLITE_MIRROR_ENABLED = os.getenv("CENTRAL_SQLITE_MIRROR_ENABLED", "1").lower() not in ("0", "false", "no", "off")
SQLITE_MIRROR_DB = os.path.abspath(os.path.expandvars(os.getenv("CENTRAL_SQLITE_MIRROR_DB", os.path.join(DATA_DIR, "matrixship_mirror.db"))))
SQLITE_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "migrations", "001_enterprise_core_schema.sql")
SQLITE_MIRROR_MIN_INTERVAL_SEC = float(os.getenv("CENTRAL_SQLITE_MIRROR_MIN_INTERVAL_SEC", "10") or 10)
MATERIALS_DIR = os.path.join(DATA_DIR, "materials")
MATERIAL_QUARANTINE_DIR = os.path.join(DATA_DIR, "quarantine")
NODE_SECRET = os.getenv("CENTRAL_NODE_SECRET", "matrix-node-secret-change-me")
USER_TOKEN = os.getenv("CENTRAL_USER_TOKEN", "").strip()
TASK_WAIT_DEFAULT = float(os.getenv("CENTRAL_TASK_WAIT_SEC", "240") or 240)
TASK_WAIT_LONG = float(os.getenv("CENTRAL_TASK_WAIT_LONG_SEC", "900") or 900)
NODE_TIMEOUT_SEC = float(os.getenv("CENTRAL_NODE_TIMEOUT_SEC", "75") or 75)
SESSION_TTL_SEC = float(os.getenv("CENTRAL_SESSION_TTL_SEC", str(7 * 24 * 3600)) or (7 * 24 * 3600))
TASK_RECOVERY_GRACE_SEC = float(os.getenv("CENTRAL_TASK_RECOVERY_GRACE_SEC", "90") or 90)
TASK_QUEUED_MAX_SEC = float(os.getenv("CENTRAL_TASK_QUEUED_MAX_SEC", "900") or 900)
DEFAULT_ORG_ID = "org-default"
# 新用户注册赠豆(云豆,1 云豆=¥0.01)。每个手机号首次建号赠一次;=0 关闭。
SIGNUP_BONUS_YUNDOU = float(os.getenv("CENTRAL_SIGNUP_BONUS", "100") or 0)
# 漫剧模式下新用户注册赠送的**算力**(与云豆不同量纲;算力≈真金,默认 0 不赠,运营方按需 env 配)
MAINDB_SIGNUP_BONUS = float(os.getenv("MAINDB_SIGNUP_BONUS", "0") or 0)
# matrixship 生成在漫剧成本价(model_prices)基础上的加价倍率(只影响 matrixship,漫剧画布不受影响)。
# 一个 env 就能调整全站加价;默认 ×3(留出零售利润)。
MAINDB_PRICE_MULTIPLIER = float(os.getenv("MAINDB_PRICE_MULTIPLIER", "3") or 3)
# 漫剧算力充值汇率:1 元 = N 算力(与漫剧 recharge_packages 一致:50元=500算力 → 10)
MAINDB_YUAN_TO_POWER = float(os.getenv("MAINDB_YUAN_TO_POWER", "10") or 10)
LEGAL_TERMS_VERSION = os.getenv("LEGAL_TERMS_VERSION", "1.0") or "1.0"
LEGAL_PRIVACY_VERSION = os.getenv("LEGAL_PRIVACY_VERSION", "1.0") or "1.0"
LEGAL_EFFECTIVE_DATE = os.getenv("LEGAL_EFFECTIVE_DATE", "2026-07-15") or "2026-07-15"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(MATERIALS_DIR, exist_ok=True)
os.makedirs(MATERIAL_QUARANTINE_DIR, exist_ok=True)
LOCK = threading.RLock()


TASK_POST_PATHS = {
    "/api/cloud-login/start",
    "/api/cloud-login/current",
    "/api/cloud-login/screenshot",
    "/api/cloud-login/qr",
    "/api/cloud-login/status",
    "/api/cloud-login/click",
    "/api/cloud-login/type",
    "/api/cloud-login/code",
    "/api/cloud-login/key",
    "/api/cloud-login/sms",
    "/api/cloud-login/refresh",
    "/api/cloud-login/close",
    "/api/finder/discover",
    "/api/outreach/run",
    "/api/douyin/comment/publish",
    "/api/xhs/comment/publish",
    "/api/douyin/search",
    "/api/xhs/search",
    "/api/douyin/work",
    "/api/douyin/comments",
    "/api/xhs/comments",
    "/api/douyin/download",
    "/api/xhs/download",
    "/api/publish/run",
}

INTERACTIVE_TASK_PATHS = {
    "/api/cloud-login/sms",
    "/api/cloud-login/click",
    "/api/cloud-login/type",
    "/api/cloud-login/code",
    "/api/cloud-login/key",
    "/api/cloud-login/refresh",
    "/api/cloud-login/close",
    "/api/cloud-login/status",
    "/api/cloud-login/current",
    "/api/cloud-login/qr",
}

LONG_TASK_PATHS = {
    "/api/cloud-login/start",
    "/api/outreach/run",
    "/api/finder/discover",
    "/api/publish/run",
    "/api/douyin/download",
    "/api/xhs/download",
}

RETRYABLE_TASK_PATHS = {
    "/api/cloud-login/current",
    "/api/cloud-login/screenshot",
    "/api/cloud-login/qr",
    "/api/cloud-login/status",
    "/api/cloud-login/refresh",
    "/api/douyin/search",
    "/api/xhs/search",
    "/api/douyin/work",
    "/api/douyin/comments",
    "/api/xhs/comments",
    "/api/douyin/download",
    "/api/xhs/download",
    "/api/finder/discover",
    "/api/publish/queue",
}


def now():
    return time.time()


def today_key():
    return time.strftime("%Y-%m-%d", time.localtime())


STATE_LOAD_ERROR = None


class StateLoadError(RuntimeError):
    pass


class StateWriteProtectionError(RuntimeError):
    pass


def _is_store_json_path(path):
    try:
        return os.path.abspath(path) == os.path.abspath(STORE_JSON)
    except Exception:
        return False


def _allow_state_reinit():
    return os.getenv("CENTRAL_ALLOW_STATE_REINIT", "").lower() in ("1", "true", "yes", "on")


def _state_counts(value):
    value = value if isinstance(value, dict) else {}
    return {
        "organizations": len(value.get("organizations") or []),
        "users": len(value.get("users") or []),
        "memberships": len(value.get("memberships") or []),
    }


def _state_is_default_skeleton(value):
    counts = _state_counts(value)
    if counts != {"organizations": 1, "users": 1, "memberships": 1}:
        return False
    org = ((value or {}).get("organizations") or [{}])[0]
    user = ((value or {}).get("users") or [{}])[0]
    membership = ((value or {}).get("memberships") or [{}])[0]
    return (
        org.get("id") == DEFAULT_ORG_ID
        and user.get("id") == "user-owner"
        and membership.get("orgId") == DEFAULT_ORG_ID
        and membership.get("userId") == "user-owner"
    )


def _state_error(kind, path, exc=None, **context):
    err = {
        "error": kind,
        "path": os.path.abspath(path or STORE_JSON),
        "errorType": type(exc).__name__ if exc else "",
        "message": str(exc)[:300] if exc else "",
    }
    err.update(context)
    return err


def _load_json(path, default):
    global STATE_LOAD_ERROR
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            value = json.load(f)
        if _is_store_json_path(path):
            STATE_LOAD_ERROR = None
        return value
    except FileNotFoundError:
        if _is_store_json_path(path):
            STATE_LOAD_ERROR = None
        return default
    except Exception as exc:
        if _is_store_json_path(path) and os.path.exists(path) and not _allow_state_reinit():
            STATE_LOAD_ERROR = _state_error("state_load_failed", path, exc)
            raise StateLoadError("state_load_failed: %s" % STATE_LOAD_ERROR["message"]) from exc
        return default


def _state_write_guard(path, data):
    if not _is_store_json_path(path) or _allow_state_reinit():
        return
    if STATE_LOAD_ERROR:
        raise StateWriteProtectionError("refuse_state_write_after_load_error")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            existing = json.load(f)
    except Exception as exc:
        raise StateWriteProtectionError("refuse_state_write_over_unreadable_state") from exc
    old_counts = _state_counts(existing)
    new_counts = _state_counts(data)
    old_rich = any(old_counts.get(k, 0) > 1 for k in ("organizations", "users", "memberships"))
    if old_rich and _state_is_default_skeleton(data):
        raise StateWriteProtectionError(
            "refuse_state_write_default_skeleton_over_existing_state old=%s new=%s" % (old_counts, new_counts)
        )


def _save_json(path, data):
    _state_write_guard(path, data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        # This state file is hot-path data, not a human-edited config file.
        # Compact JSON keeps cloud-login responses from blocking on large writes.
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def backup_state_file_on_startup(now_label=None):
    if not os.path.exists(STORE_JSON):
        return ""
    label = now_label or time.strftime("%Y%m%d%H%M%S")
    backup_path = STORE_JSON + ".bak-startup-" + label
    if os.path.exists(backup_path):
        backup_path = backup_path + "-" + uuid.uuid4().hex[:8]
    shutil.copy2(STORE_JSON, backup_path)
    return backup_path


def init_state():
    global STATE_LOAD_ERROR
    st = _load_json(STORE_JSON, {})
    if not isinstance(st, dict):
        if os.path.exists(STORE_JSON) and not _allow_state_reinit():
            STATE_LOAD_ERROR = _state_error("state_load_failed_not_object", STORE_JSON)
            raise StateLoadError("state_load_failed_not_object")
        st = {}
    st.setdefault("nodes", {})
    st.setdefault("tasks", {})
    st.setdefault("events", [])
    st.setdefault("auditLogs", [])
    st.setdefault("organizations", [])
    st.setdefault("users", [])
    st.setdefault("memberships", [])
    st.setdefault("sessions", [])
    st.setdefault("accountsRegistry", [])
    st.setdefault("library", [])
    st.setdefault("kb", [])
    st.setdefault("queue", [])
    st.setdefault("actionSnoozes", {})
    st.setdefault("notificationReads", {})
    st.setdefault("notificationSettings", {})
    st.setdefault("webhookDeliveries", {})
    st.setdefault("nodeSettings", {})
    st.setdefault("supportLinks", [])
    st.setdefault("healthSnapshots", {})
    st.setdefault("cloudLoginProgress", [])
    st.setdefault("enterpriseInvites", [])
    st.setdefault("legalConsents", {})
    st.setdefault("settings", {"perAccountPerDay": 1, "intervalMin": 60, "enabled": False})
    st.setdefault("orgSettings", {})
    st.setdefault("orgQuotas", {})
    st.setdefault("orgOnboarding", {})
    if DEFAULT_ORG_ID not in st["orgSettings"]:
        st["orgSettings"][DEFAULT_ORG_ID] = dict(st.get("settings") or {"perAccountPerDay": 1, "intervalMin": 60, "enabled": False})
    if not st["organizations"]:
        st["organizations"].append({
            "id": "org-default",
            "name": "默认企业",
            "status": "active",
            "createdAt": time.time(),
        })
    if not st["users"]:
        st["users"].append({
            "id": "user-owner",
            "name": "企业管理员",
            "phone": "admin",
            "status": "active",
            "createdAt": time.time(),
        })
    if not st["memberships"]:
        st["memberships"].append({
            "id": "m-default-owner",
            "orgId": "org-default",
            "userId": "user-owner",
            "role": "owner",
            "createdAt": time.time(),
        })
    return st


STATE_STARTUP_BACKUP = backup_state_file_on_startup()
STATE = init_state()
PUBLISH_RT = {"day": "", "last_ts": 0.0, "counts": {}}


def normalize_org_id(value=None):
    value = (value or "").strip()
    return value or DEFAULT_ORG_ID


def item_org_id(item):
    return normalize_org_id((item or {}).get("orgId"))


def request_org_id(handler=None, body=None, qs=None):
    if body and isinstance(body, dict):
        for k in ("orgId", "tenantId", "organizationId"):
            if body.get(k):
                return normalize_org_id(body.get(k))
    if qs is None and handler is not None:
        try:
            qs = parse_qs(urlparse(handler.path).query)
        except Exception:
            qs = {}
    if qs:
        for k in ("orgId", "tenantId", "organizationId"):
            v = (qs.get(k) or [""])[0]
            if v:
                return normalize_org_id(v)
    if handler is not None:
        try:
            v = handler.headers.get("X-Matrix-Org-Id") or ""
            if v:
                return normalize_org_id(v)
        except Exception:
            pass
        try:
            u = current_user(handler)
            if u:
                orgs = user_orgs(u.get("id"), u)
                if orgs:
                    return normalize_org_id(orgs[0].get("id"))
        except Exception:
            pass
    return DEFAULT_ORG_ID


def with_org_defaults():
    changed = False
    with LOCK:
        for m in STATE.get("library") or []:
            if not m.get("orgId"):
                m["orgId"] = DEFAULT_ORG_ID
                changed = True
        for q in STATE.get("queue") or []:
            if not q.get("orgId"):
                q["orgId"] = DEFAULT_ORG_ID
                changed = True
        for d in STATE.get("kb") or []:
            if not d.get("orgId"):
                d["orgId"] = DEFAULT_ORG_ID
                changed = True
        for n in (STATE.get("nodes") or {}).values():
            if not n.get("orgId"):
                n["orgId"] = DEFAULT_ORG_ID
                changed = True
            accs = n.get("accounts") or []
            for a in accs:
                if isinstance(a, dict) and not a.get("orgId"):
                    a["orgId"] = item_org_id(n)
                    changed = True
            if accs:
                before = len(STATE.get("accountsRegistry") or [])
                sync_node_accounts_locked(n)
                if len(STATE.get("accountsRegistry") or []) != before:
                    changed = True
        org_settings = STATE.setdefault("orgSettings", {})
        if DEFAULT_ORG_ID not in org_settings:
            org_settings[DEFAULT_ORG_ID] = dict(STATE.get("settings") or {"perAccountPerDay": 1, "intervalMin": 60, "enabled": False})
            changed = True
        STATE.setdefault("sessions", [])
        STATE.setdefault("healthSnapshots", {})
        STATE.setdefault("cloudLoginProgress", [])
        for u in STATE.get("users") or []:
            if u.get("id") == "user-owner" and not u.get("phone"):
                u["phone"] = "admin"
                changed = True
    return changed



PERSISTENCE_MIRROR_STATE = {"lastOk": False, "lastAt": 0, "lastError": "", "lastCounts": {}, "lastDurationMs": 0}


def _mirror_json(value, default=None):
    try:
        return json.dumps(value if value is not None else (default if default is not None else {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return json.dumps(default if default is not None else {}, ensure_ascii=False, sort_keys=True)


def _mirror_ts(item, *keys):
    item = item if isinstance(item, dict) else {}
    for k in keys:
        try:
            v = item.get(k)
            if v is not None and v != "":
                return float(v)
        except Exception:
            pass
    return None


def _mirror_upsert(conn, table, row):
    keys = list(row.keys())
    placeholders = ",".join(["?"] * len(keys))
    cols = ",".join(keys)
    updates = ",".join([k + "=excluded." + k for k in keys if k != "id"])
    sql = "INSERT INTO " + table + " (" + cols + ") VALUES (" + placeholders + ") ON CONFLICT(id) DO UPDATE SET " + updates
    conn.execute(sql, [row.get(k) for k in keys])


def _mirror_schema(conn):
    if os.path.exists(SQLITE_SCHEMA_PATH):
        with open(SQLITE_SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
    conn.execute("CREATE TABLE IF NOT EXISTS persistence_meta (key TEXT PRIMARY KEY, value TEXT, updated_at REAL)")


def _mirror_account_rows_locked():
    rows = []
    seen = set()
    for a in STATE.get("accountsRegistry") or []:
        if not isinstance(a, dict):
            continue
        aid = a.get("id") or a.get("accountId") or a.get("localAccountId") or ""
        if not aid or aid in seen:
            continue
        seen.add(aid)
        rows.append(dict(a))
    for n in (STATE.get("nodes") or {}).values():
        if not isinstance(n, dict):
            continue
        for a in n.get("accounts") or []:
            if not isinstance(a, dict):
                continue
            aid = a.get("id") or a.get("accountId") or a.get("localAccountId") or ""
            if not aid or aid in seen:
                continue
            seen.add(aid)
            row = dict(a)
            row.setdefault("nodeId", n.get("id"))
            row.setdefault("orgId", item_org_id(n))
            rows.append(row)
    return rows


def sqlite_mirror_state(reason="persist"):
    if not SQLITE_MIRROR_ENABLED:
        PERSISTENCE_MIRROR_STATE.update({"lastOk": False, "lastAt": now(), "lastError": "disabled", "lastDurationMs": 0})
        return {"ok": False, "disabled": True}
    started = now()
    counts = {}
    try:
        os.makedirs(os.path.dirname(SQLITE_MIRROR_DB), exist_ok=True)
        conn = sqlite3.connect(SQLITE_MIRROR_DB, timeout=5)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            _mirror_schema(conn)
            ts_now = now()
            with LOCK:
                orgs = [dict(x) for x in (STATE.get("organizations") or []) if isinstance(x, dict)]
                users = [dict(x) for x in (STATE.get("users") or []) if isinstance(x, dict)]
                memberships = [dict(x) for x in (STATE.get("memberships") or []) if isinstance(x, dict)]
                nodes = [dict(x) for x in (STATE.get("nodes") or {}).values() if isinstance(x, dict)]
                accounts = _mirror_account_rows_locked()
                materials = [dict(x) for x in (STATE.get("library") or []) if isinstance(x, dict)]
                queue = [dict(x) for x in (STATE.get("queue") or []) if isinstance(x, dict)]
                tasks = [dict(x) for x in (STATE.get("tasks") or {}).values() if isinstance(x, dict)]
                audits = [dict(x) for x in (STATE.get("auditLogs") or []) if isinstance(x, dict)]
                support = [dict(x) for x in (STATE.get("supportLinks") or []) if isinstance(x, dict)]
                kb_docs = [dict(x) for x in (STATE.get("kb") or []) if isinstance(x, dict)]
                progress = [dict(x) for x in (STATE.get("cloudLoginProgress") or []) if isinstance(x, dict)]
                finder = []
                for oid, arr in (STATE.get("finderLeads") or {}).items():
                    for x in arr or []:
                        if isinstance(x, dict):
                            row = dict(x); row.setdefault("orgId", oid); finder.append(row)
            if not orgs:
                orgs = [{"id": DEFAULT_ORG_ID, "name": "Default Workspace", "plan": "standard", "status": "active", "createdAt": ts_now}]
            for o in orgs:
                oid = normalize_org_id(o.get("id"))
                _mirror_upsert(conn, "organizations", {"id": oid, "name": o.get("name") or oid, "plan_code": o.get("plan") or o.get("planCode") or "standard", "status": o.get("status") or "active", "created_at": _mirror_ts(o, "createdAt") or ts_now, "updated_at": _mirror_ts(o, "updatedAt") or ts_now, "meta_json": _mirror_json(o.get("meta") or {})})
            for u in users:
                uid = str(u.get("id") or u.get("phone") or uuid.uuid4().hex)
                _mirror_upsert(conn, "users", {"id": uid, "name": u.get("name") or uid, "phone": u.get("phone") or "", "email": u.get("email") or "", "password_hash": u.get("passwordHash") or u.get("password_hash") or "", "status": u.get("status") or "active", "created_at": _mirror_ts(u, "createdAt") or ts_now, "updated_at": _mirror_ts(u, "updatedAt") or ts_now, "meta_json": _mirror_json(u.get("meta") or {})})
            for m in memberships:
                mid = str(m.get("id") or (normalize_org_id(m.get("orgId")) + ":" + str(m.get("userId") or "user")))
                _mirror_upsert(conn, "memberships", {"id": mid, "org_id": normalize_org_id(m.get("orgId")), "user_id": str(m.get("userId") or ""), "role": m.get("role") or "member", "status": m.get("status") or "active", "created_at": _mirror_ts(m, "createdAt") or ts_now, "updated_at": _mirror_ts(m, "updatedAt") or ts_now})
            for n in nodes:
                nid = str(n.get("id") or n.get("nodeId") or uuid.uuid4().hex)
                _mirror_upsert(conn, "nodes", {"id": nid, "org_id": item_org_id(n), "name": n.get("name") or nid, "host": n.get("host") or n.get("ip") or "", "online": 0 if n.get("online") is False else 1, "capacity_json": _mirror_json(n.get("capacity") or {}), "last_seen": _mirror_ts(n, "lastSeen", "updatedAt"), "created_at": _mirror_ts(n, "createdAt") or ts_now, "updated_at": _mirror_ts(n, "updatedAt") or ts_now, "meta_json": _mirror_json(n.get("meta") or {})})
            for a in accounts:
                aid = str(a.get("id") or a.get("accountId") or a.get("localAccountId") or uuid.uuid4().hex)
                _mirror_upsert(conn, "accounts", {"id": aid, "org_id": item_org_id(a), "platform": a.get("platform") or "douyin", "node_id": a.get("nodeId") or "", "name": a.get("name") or a.get("nickname") or aid, "handle": a.get("handle") or "", "cookie_ready": 1 if a.get("cookieReady") else 0, "usable": 1 if a.get("usable") else 0, "online": 0 if a.get("online") is False else 1, "authorized_at": _mirror_ts(a, "authorizedAt"), "cookie_updated_at": _mirror_ts(a, "cookieUpdatedAt"), "last_seen": _mirror_ts(a, "lastSeen", "updatedAt"), "created_at": _mirror_ts(a, "createdAt") or ts_now, "updated_at": _mirror_ts(a, "updatedAt") or ts_now, "meta_json": _mirror_json(a.get("meta") or {})})
            for m in materials:
                mid = str(m.get("id") or uuid.uuid4().hex)
                files = m.get("files") or []
                _mirror_upsert(conn, "materials", {"id": mid, "org_id": item_org_id(m), "title": m.get("title") or mid, "type": m.get("type") or "video", "file_count": len(files), "files_json": _mirror_json(files, []), "urls_json": _mirror_json(m.get("urls") or [], []), "created_at": _mirror_ts(m, "createdAt") or ts_now, "updated_at": _mirror_ts(m, "updatedAt") or ts_now, "meta_json": _mirror_json(m.get("meta") or {})})
            for q in queue:
                qid = str(q.get("id") or q.get("queueId") or uuid.uuid4().hex)
                _mirror_upsert(conn, "publish_queue_items", {"id": qid, "org_id": item_org_id(q), "account_id": q.get("accountId") or "", "material_id": q.get("materialId") or "", "status": q.get("status") or "pending", "receipt_id": q.get("receiptId") or "", "task_id": q.get("centralTaskId") or q.get("taskId") or "", "last_error": q.get("lastError") or "", "preflight_json": _mirror_json(q.get("preflight") or {}), "events_json": _mirror_json(q.get("events") or [], []), "created_at": _mirror_ts(q, "createdAt") or ts_now, "updated_at": _mirror_ts(q, "updatedAt") or ts_now, "meta_json": _mirror_json(q.get("meta") or {})})
            for t in tasks:
                tid = str(t.get("id") or uuid.uuid4().hex)
                result = t.get("result") if isinstance(t.get("result"), dict) else {}
                _mirror_upsert(conn, "central_tasks", {"id": tid, "org_id": item_org_id(t), "type": t.get("type") or "", "path": t.get("path") or "", "status": t.get("status") or "queued", "queue_id": t.get("queueId") or "", "account_id": t.get("accountId") or "", "node_id": t.get("nodeId") or "", "payload_json": _mirror_json(audit_safe_body(t.get("body") or {})), "result_json": _mirror_json(audit_safe_body(result)), "error": public_error_text(t.get("error") or t.get("lastError") or ""), "created_at": _mirror_ts(t, "createdAt") or ts_now, "started_at": _mirror_ts(t, "startedAt"), "finished_at": _mirror_ts(t, "finishedAt"), "updated_at": _mirror_ts(t, "updatedAt") or ts_now})
            for a in audits:
                aid = str(a.get("id") or uuid.uuid4().hex)
                meta = a.get("meta") if isinstance(a.get("meta"), dict) else {}
                _mirror_upsert(conn, "audit_logs", {"id": aid, "org_id": audit_log_org_id(a) or item_org_id(a), "actor_id": a.get("actorUserId") or a.get("userId") or "", "action": a.get("action") or "unknown", "resource_type": a.get("resourceType") or "", "resource_id": a.get("resourceId") or "", "summary": a.get("summary") or a.get("target") or "", "meta_json": _mirror_json(audit_safe_body(meta)), "created_at": _mirror_ts(a, "ts", "createdAt") or ts_now})
            for s in support:
                sid = str(s.get("id") or uuid.uuid4().hex)
                _mirror_upsert(conn, "support_links", {"id": sid, "org_id": item_org_id(s), "kind": s.get("kind") or "", "severity": s.get("severity") or "", "title": s.get("title") or "", "description": s.get("description") or "", "resource_json": _mirror_json(s.get("resource") or {}), "archived": 1 if s.get("archived") else 0, "created_at": _mirror_ts(s, "createdAt") or ts_now, "updated_at": _mirror_ts(s, "updatedAt") or ts_now})
            for f in finder:
                fid = str(f.get("id") or uuid.uuid4().hex)
                _mirror_upsert(conn, "finder_leads", {"id": fid, "org_id": item_org_id(f), "keyword": f.get("keyword") or "", "source_url": f.get("sourceUrl") or f.get("url") or "", "author": f.get("author") or f.get("name") or "", "comment": f.get("comment") or f.get("text") or "", "intent": f.get("intent") or "", "score": float(f.get("score") or 0), "status": f.get("status") or "new", "created_at": _mirror_ts(f, "createdAt") or ts_now, "updated_at": _mirror_ts(f, "updatedAt") or ts_now, "meta_json": _mirror_json(f.get("meta") or {})})
            for k in kb_docs:
                kid = str(k.get("id") or uuid.uuid4().hex)
                _mirror_upsert(conn, "kb_docs", {"id": kid, "org_id": item_org_id(k), "title": k.get("title") or "", "type": k.get("type") or "", "chunks": len(k.get("chunkTexts") or []), "text_hash": _short_hash(k.get("text") or k.get("preview") or ""), "created_at": _mirror_ts(k, "createdAt") or ts_now, "updated_at": _mirror_ts(k, "updatedAt") or ts_now, "meta_json": _mirror_json({"source": k.get("source") or "", "chars": k.get("chars") or 0})})
            for c in progress:
                cid = str(c.get("id") or c.get("sessionId") or (str(c.get("ts") or "") + _short_hash(c)))
                _mirror_upsert(conn, "cloud_login_sessions", {"id": cid, "org_id": item_org_id(c), "account_id": c.get("accountId") or "", "node_id": c.get("nodeId") or "", "status": c.get("status") or "", "phase": c.get("phase") or c.get("label") or "", "progress_json": _mirror_json(audit_safe_body(c)), "created_at": _mirror_ts(c, "createdAt", "ts") or ts_now, "updated_at": _mirror_ts(c, "updatedAt", "ts") or ts_now, "closed_at": _mirror_ts(c, "closedAt"), "meta_json": _mirror_json({})})
            for table in ["organizations", "users", "memberships", "nodes", "accounts", "materials", "publish_queue_items", "central_tasks", "audit_logs", "support_links", "finder_leads", "kb_docs", "cloud_login_sessions"]:
                counts[table] = int(conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0])
            duration_ms = int((now() - started) * 1000)
            conn.execute("INSERT INTO persistence_meta(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", ("last_mirror", _mirror_json({"reason": reason, "counts": counts, "durationMs": duration_ms}), ts_now))
            conn.commit()
        finally:
            conn.close()
        PERSISTENCE_MIRROR_STATE.update({"lastOk": True, "lastAt": now(), "lastError": "", "lastCounts": counts, "lastDurationMs": int((now() - started) * 1000)})
        return {"ok": True, "counts": counts, "dbPath": SQLITE_MIRROR_DB, "durationMs": PERSISTENCE_MIRROR_STATE.get("lastDurationMs")}
    except Exception as exc:
        PERSISTENCE_MIRROR_STATE.update({"lastOk": False, "lastAt": now(), "lastError": public_error_text(str(exc)), "lastCounts": counts, "lastDurationMs": int((now() - started) * 1000)})
        return {"ok": False, "error": public_error_text(str(exc)), "counts": counts, "dbPath": SQLITE_MIRROR_DB}


def persistence_health(org_id=None, refresh=False):
    org_id = normalize_org_id(org_id)
    if refresh:
        sqlite_mirror_state("health_refresh")
    exists = os.path.exists(SQLITE_MIRROR_DB)
    size = os.path.getsize(SQLITE_MIRROR_DB) if exists else 0
    tables = {}
    meta = {}
    error = ""
    if exists:
        try:
            conn = sqlite3.connect(SQLITE_MIRROR_DB, timeout=3)
            try:
                for table in ["organizations", "users", "memberships", "nodes", "accounts", "materials", "publish_queue_items", "central_tasks", "audit_logs", "support_links", "finder_leads", "kb_docs", "cloud_login_sessions"]:
                    try:
                        tables[table] = int(conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0])
                    except Exception:
                        tables[table] = None
                try:
                    rows = conn.execute("SELECT key,value,updated_at FROM persistence_meta").fetchall()
                    for k, v, u in rows:
                        meta[k] = {"value": v, "updatedAt": u}
                except Exception:
                    pass
            finally:
                conn.close()
        except Exception as exc:
            error = public_error_text(str(exc))
    status = "ready" if (SQLITE_MIRROR_ENABLED and exists and PERSISTENCE_MIRROR_STATE.get("lastOk")) else ("disabled" if not SQLITE_MIRROR_ENABLED else "needs_attention")
    return {"ok": True, "orgId": org_id, "enabled": SQLITE_MIRROR_ENABLED, "status": status, "dbPath": SQLITE_MIRROR_DB, "dbExists": exists, "dbSize": size, "lastOk": bool(PERSISTENCE_MIRROR_STATE.get("lastOk")), "lastAt": PERSISTENCE_MIRROR_STATE.get("lastAt") or 0, "lastError": PERSISTENCE_MIRROR_STATE.get("lastError") or error, "lastDurationMs": PERSISTENCE_MIRROR_STATE.get("lastDurationMs") or 0, "lastCounts": PERSISTENCE_MIRROR_STATE.get("lastCounts") or {}, "tables": tables, "meta": meta, "generatedAt": now()}

def persist():
    with LOCK:
        with_org_defaults()
        # Keep the state file bounded.
        tasks = STATE.get("tasks") or {}
        if len(tasks) > 2000:
            keep = sorted(tasks.values(), key=lambda x: x.get("createdAt", 0), reverse=True)[:1600]
            STATE["tasks"] = {x["id"]: x for x in keep}
        events = STATE.get("events") or []
        STATE["events"] = events[-500:]
        progress = STATE.get("cloudLoginProgress") or []
        STATE["cloudLoginProgress"] = progress[-800:]
        audits = STATE.get("auditLogs") or []
        STATE["auditLogs"] = audits[-5000:]
        _save_json(STORE_JSON, compact_state_for_persist(STATE))
    try:
        mirror_due = (not PERSISTENCE_MIRROR_STATE.get("lastOk")) or (now() - float(PERSISTENCE_MIRROR_STATE.get("lastAt") or 0) >= SQLITE_MIRROR_MIN_INTERVAL_SEC)
        if mirror_due:
            sqlite_mirror_state("persist")
    except Exception:
        pass


def add_event(kind, data=None):
    with LOCK:
        STATE.setdefault("events", []).append({"ts": now(), "kind": kind, "data": data or {}})
        STATE["events"] = STATE["events"][-500:]


SENSITIVE_AUDIT_KEYS = {
    "cookie", "cookies", "authorization", "token", "password", "passwd",
    "secret", "text", "code", "sms", "captcha", "verify", "verification",
    "image", "screenshot", "base64", "dataurl", "data_url",
}


def _short_hash(value):
    value = str(value or "")
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8", "ignore")).hexdigest()[:12]


def audit_safe_body(body):
    safe = {}
    for k, v in (body or {}).items():
        lk = str(k).lower()
        if any(x in lk for x in SENSITIVE_AUDIT_KEYS):
            safe[k] = "<redacted>"
        elif lk in ("sessionid", "session_id"):
            safe[k] = (str(v)[:8] + "..." + str(v)[-4:]) if v else ""
        elif isinstance(v, (str, int, float, bool)) or v is None:
            safe[k] = v
        elif isinstance(v, list):
            safe[k] = {"type": "list", "len": len(v)}
        elif isinstance(v, dict):
            safe[k] = {"type": "dict", "keys": sorted(list(v.keys()))[:20]}
        else:
            safe[k] = str(type(v).__name__)
    return safe


def strip_large_payloads(value, max_inline=4096):
    """Return a copy suitable for persistence/audit without embedded images."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            lk = str(k).lower().replace("-", "_")
            if isinstance(v, str):
                if (
                    lk in LARGE_PAYLOAD_KEYS
                    or "image" in lk
                    or "screenshot" in lk
                    or v.startswith("data:image/")
                    or len(v) > 120000
                ):
                    out[k] = "<omitted:%d chars>" % len(v)
                else:
                    out[k] = v
            elif isinstance(v, (dict, list)):
                out[k] = strip_large_payloads(v, max_inline=max_inline)
            else:
                out[k] = v
        return out
    if isinstance(value, list):
        return [strip_large_payloads(x, max_inline=max_inline) for x in value[:200]]
    if isinstance(value, str) and len(value) > max_inline:
        return "<omitted:%d chars>" % len(value)
    return value


def compact_state_for_persist(state):
    """Keep runtime STATE intact, but persist only compact task payloads."""
    src = state if isinstance(state, dict) else {}
    out = dict(src)
    tasks_out = {}
    for tid, task in (src.get("tasks") or {}).items():
        if not isinstance(task, dict):
            tasks_out[tid] = task
            continue
        t = dict(task)
        if isinstance(t.get("result"), (dict, list)):
            t["result"] = strip_large_payloads(t.get("result"))
        if isinstance(t.get("body"), (dict, list)):
            t["body"] = strip_large_payloads(t.get("body"), max_inline=20000)
        tasks_out[tid] = t
    out["tasks"] = tasks_out
    return out


def add_audit(handler, action, target, ok=True, meta=None):
    should_persist = False
    try:
        token = handler.headers.get("X-Matrix-User-Token") or handler.headers.get("Authorization") or ""
        actor = current_user(handler)
        item = {
            "id": uuid.uuid4().hex,
            "ts": now(),
            "action": action,
            "target": target,
            "ok": bool(ok),
            "ip": handler.client_address[0] if getattr(handler, "client_address", None) else "",
            "origin": handler.headers.get("Origin") or "",
            "userAgent": handler.headers.get("User-Agent") or "",
            "actorUserId": actor.get("id") if actor else "",
            "actorName": actor.get("name") if actor else "",
            "actorTokenHash": _short_hash(token),
            "meta": meta or {},
        }
        with LOCK:
            STATE.setdefault("auditLogs", []).append(item)
            STATE["auditLogs"] = STATE["auditLogs"][-5000:]
            should_persist = True
    except Exception:
        should_persist = False
    if should_persist:
        try:
            persist()
        except Exception:
            pass


def audit_log_org_id(log):
    meta = (log or {}).get("meta") or {}
    if isinstance(meta, dict):
        if meta.get("orgId"):
            return normalize_org_id(meta.get("orgId"))
        body = meta.get("body")
        if isinstance(body, dict) and body.get("orgId"):
            return normalize_org_id(body.get("orgId"))
    return ""


def json_response(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", handler.headers.get("Origin") or "*")
    handler.send_header("Vary", "Origin")
    handler.send_header("Access-Control-Allow-Headers", "content-type, authorization, x-matrix-user-token, x-matrix-org-id, x-node-secret")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def read_body(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


_LK_SSLCTX = None


class _LK888NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _LK888UpstreamPolicyError(RuntimeError):
    pass


def _lk888_https_origin(value):
    try:
        parsed = urlparse(value)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return None
        return parsed.hostname.lower(), parsed.port or 443
    except Exception:
        return None


def _lk888_open(request, context, timeout):
    if _lk888_https_origin(request.full_url) is None:
        raise _LK888UpstreamPolicyError("https_required")
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        _LK888NoRedirectHandler(),
    )
    return opener.open(request, timeout=timeout)


def lk888_proxy_task_flags(obj):
    """Return (failed, done) for LK888 task-status payloads used by refund logic."""
    payload = obj if isinstance(obj, dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    body = data or payload
    status = str((body or {}).get("status") or payload.get("status") or "").lower().strip()
    has_url = bool(re.search(
        r'https?://[^"\s\\]+\.(?:mp4|mov|png|jpe?g|webp|mp3|wav)',
        json.dumps(payload, ensure_ascii=False),
        re.IGNORECASE,
    ))
    failed = status in {
        "failed", "fail", "error", "timeout", "cancelled", "canceled",
        "错误", "失败", "超时", "已取消", "取消",
    }
    done = status in {
        "success", "succeed", "succeeded", "completed", "done", "finished",
        "成功", "完成", "已完成",
    } or has_url
    return failed, done


def gen_price_yundou(model, params):
    """服务端权威计费:按 lk888 模型(+关键 params)定云豆价。反代对每次 /v1/media/generate 强制
    扣费,客户端改不了、也绕不过(分发客户端没有 lk888 直连 key,只能走反代)。与客户端展示价对齐。
    mix(本地 ffmpeg,无 lk888 调用、无算力成本)与 copywriting/chat(便宜、且内部也用)不经此路径。
    未知媒体模型给保底价,避免用没定价的模型白嫖;非生成类(状态查询/模型列表)不进这里。"""
    m = (model or "").lower()
    p = params or {}
    if "kling-avatar" in m:  # 数字人
        return 5040 if str(p.get("mode") or "").lower() == "pro" else 2520
    if "vidu" in m:          # 工作流视频(vidu-jieshuoman)
        return 2520
    if "seedance" in m:      # 商品视频(doubao-seedance)
        return 308
    if "gpt-image" in m or "image-2" in m or "image2" in m:  # 出图(商品/爆款/工作流/封面)
        return 14
    if "tts" in m or "speech" in m:  # 语音
        return 21
    if any(k in m for k in ("suno", "music", "audio", "sound")):  # 音乐/音频
        return 21
    if any(k in m for k in ("veo", "sora", "runway", "pika", "hailuo", "wan", "cog", "video", "avatar", "image", "flux", "midjourney", "sd")):
        return 308           # 其它视频/图像类媒体模型:保底(不白嫖)
    return 308               # 兜底:未知模型按视频价保底(客户端只用已定价模型;未知=改过的客户端,按高价扣防白嫖)


def _lk888_multipart_fields(body, content_type):
    """Extract non-file multipart fields without copying uploaded file bodies."""
    raw = body if isinstance(body, bytes) else bytes(body or b"")
    match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;\s]+))", str(content_type or ""), re.I)
    boundary = (match.group(1) or match.group(2)) if match else ""
    if not raw or not boundary:
        return {}
    marker = b"--" + boundary.encode("utf-8", "ignore")
    fields = {}
    cursor = 0
    while True:
        part_start = raw.find(marker, cursor)
        if part_start < 0:
            break
        header_start = part_start + len(marker)
        if raw[header_start:header_start + 2] == b"--":
            break
        if raw[header_start:header_start + 2] == b"\r\n":
            header_start += 2
        header_end = raw.find(b"\r\n\r\n", header_start)
        if header_end < 0:
            break
        next_part = raw.find(marker, header_end + 4)
        if next_part < 0:
            break
        headers = raw[header_start:header_end].decode("latin-1", "replace")
        cursor = next_part
        name_match = re.search(r'name="([^"\r\n]+)"', headers, re.I)
        if not name_match or re.search(r'filename="', headers, re.I):
            continue
        value = raw[header_end + 4:next_part]
        if value.endswith(b"\r\n"):
            value = value[:-2]
        if len(value) <= 16384:
            fields[name_match.group(1)] = value.decode("utf-8", "replace")
    return fields


def lk888_proxy(handler, method, parsed):
    """lk888 反代中转:客户端 /lk888/<子路径> → https://api.lk888.ai/<子路径>,服务端注入真 key。
    这样分发的客户端既不用内置 lk888 key、也不用翻墙代理(服务器直连 lk888)。
    鉴权:必须是有效登录会话(客户端把 session token 放 Authorization: Bearer)。
    **计费**:对 POST /v1/media/generate 服务端权威扣云豆(见 gen_price_yundou),余额不足直接 402
    不转发;下单失败/任务失败自动退款(见 STATE['gen_charges'] 按 task_id 记账,轮询到失败即退)。"""
    import ssl
    import urllib.request
    import urllib.error
    global _LK_SSLCTX
    u = current_user(handler)
    if not u:
        return json_response(handler, {"ok": False, "error": "not_authenticated"}, 401)
    key = os.getenv("LK888_API_KEY", "")
    base = (os.getenv("LK888_BASE_URL", "https://api.lk888.ai")).rstrip("/")
    if not key:
        return json_response(handler, {"ok": False, "error": "lk888_not_configured"}, 503)
    if urlparse(base).scheme.lower() != "https":
        try:
            add_event("lk888_proxy_config_error", {"error": "tls_required"})
        except Exception:
            pass
        return json_response(handler, {"ok": False, "error": "lk888_tls_required"}, 503)
    if _LK_SSLCTX is None:
        _LK_SSLCTX = ssl.create_default_context()
    sub = parsed.path[len("/lk888"):] or "/"
    url = base + sub + (("?" + parsed.query) if parsed.query else "")
    initial_origin = _lk888_https_origin(url)
    if initial_origin is None:
        return json_response(handler, {"ok": False, "error": "lk888_tls_required"}, 503)
    data = None
    if method == "POST":
        length = int(handler.headers.get("Content-Length", "0") or "0")
        data = handler.rfile.read(length) if length else b""
    # ===== 服务端权威计费:媒体生成先扣云豆,余额不足直接拒绝转发 =====
    # 异步任务生成走 /v1/media/generate(视频/数字人/TTS/部分图);同步图片走 /v1/images/generations。
    _sub_path = sub.split("?", 1)[0].rstrip("/")
    _is_sync_img = (_sub_path == "/v1/images/generations")
    _is_gen = (_sub_path == "/v1/media/generate") or _is_sync_img
    charge_ctx = None
    if method == "POST" and _is_gen and u.get("id") != "user-owner":
        content_type = handler.headers.get("Content-Type") or ""
        if "multipart/form-data" in content_type.lower():
            _fields = _lk888_multipart_fields(data, content_type)
            _bo = {
                "model": _fields.get("model"),
                "params": {"mode": _fields.get("mode")} if _fields.get("mode") else {},
            }
        else:
            try:
                _bo = json.loads(data or b"{}")
            except Exception:
                _bo = {}
        if maindb_on() and isinstance(u.get("id"), int):
            # ===== 漫剧模式:按共享 model_prices 扣**算力**(与漫剧画布同一钱包/同一价) =====
            _model = _bo.get("model")
            _params = _bo.get("params") or {}
            _rid = "msgen-" + uuid.uuid4().hex
            _ok, _amt, _bal, _err = maindb.charge_generation(u.get("id"), _model, _params, request_id=_rid,
                                                             multiplier=MAINDB_PRICE_MULTIPLIER)
            if not _ok:
                if _err == "insufficient_balance":
                    return json_response(handler, {"ok": False, "error": "insufficient_balance",
                                                   "need": _amt, "balance": _bal,
                                                   "message": "算力余额不足(本次约需 %s,当前 %s),请充值后再生成。" % (_amt, _bal)}, 402)
                # 模型未在 model_prices 配价:拒绝(避免白嫖 + 提示运营方补价)
                return json_response(handler, {"ok": False, "error": "model_not_priced",
                                               "model": _model,
                                               "message": "该模型「%s」暂未接入计费,请联系管理员在 model_prices 配置价格。" % str(_model)[:40]}, 402)
            if _amt > 0:
                charge_ctx = {"ref": _rid, "userId": u.get("id"), "amount": _amt, "sync": _is_sync_img, "ts": now(), "mdb": True}
        else:
            # ===== 旧云豆模式(未接漫剧主库时的回退) =====
            _amt = gen_price_yundou(_bo.get("model"), _bo.get("params") or {})
            if _amt > 0:
                _gref = "gen:" + uuid.uuid4().hex[:16]
                _ok, _bal, _err = charge_user(u.get("id"), _amt, reason="AI生成·" + str(_bo.get("model") or "")[:24], ref=_gref)
                if not _ok:
                    return json_response(handler, {"ok": False, "error": "insufficient_balance",
                                                   "need": _amt, "balance": _bal,
                                                   "message": "云豆余额不足(需 %d,当前 %s),请充值后再生成。" % (_amt, _bal)}, 402)
                charge_ctx = {"ref": _gref, "userId": u.get("id"), "amount": _amt, "sync": _is_sync_img, "ts": now()}
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + key)
    ct = handler.headers.get("Content-Type")
    if ct:
        req.add_header("Content-Type", ct)
    req.add_header("Accept", handler.headers.get("Accept") or "application/json")
    try:
        try:
            sync_image_timeout = max(60, int(os.getenv("LK888_SYNC_IMAGE_TIMEOUT_SEC", "480") or 480))
        except Exception:
            sync_image_timeout = 480
        upstream_timeout = sync_image_timeout if _is_sync_img else 240
        with _lk888_open(req, _LK_SSLCTX, upstream_timeout) as r:
            final_url = r.geturl() if hasattr(r, "geturl") else url
            if _lk888_https_origin(final_url) != initial_origin:
                raise _LK888UpstreamPolicyError("redirect_or_origin_change_blocked")
            payload = r.read()
            status = r.status
            resp_ct = r.headers.get("Content-Type") or "application/json"
    except urllib.error.HTTPError as e:
        if 300 <= int(e.code or 0) < 400:
            if charge_ctx:
                try:
                    refund_user_by_ref(charge_ctx["userId"], charge_ctx["ref"])
                except Exception:
                    pass
            try:
                add_event("lk888_upstream_redirect_blocked", {"status": int(e.code or 0)})
            except Exception:
                pass
            return json_response(handler, {"ok": False, "error": "lk888_upstream_error"}, 502)
        payload = e.read()
        status = e.code
        resp_ct = e.headers.get("Content-Type") or "application/json"
    except _LK888UpstreamPolicyError:
        if charge_ctx:
            try:
                refund_user_by_ref(charge_ctx["userId"], charge_ctx["ref"])
            except Exception:
                pass
        try:
            add_event("lk888_upstream_policy_blocked", {"error": "https_origin_required"})
        except Exception:
            pass
        return json_response(handler, {"ok": False, "error": "lk888_upstream_error"}, 502)
    except Exception as ex:
        if charge_ctx:
            try:
                refund_user_by_ref(charge_ctx["userId"], charge_ctx["ref"])
            except Exception:
                pass
        try:
            add_event("lk888_proxy_error", {"errorType": type(ex).__name__})
        except Exception:
            pass
        return json_response(handler, {"ok": False, "error": "lk888_proxy_error"}, 502)
    key_bytes = key.encode("utf-8")
    if key_bytes and key_bytes in payload:
        payload = payload.replace(key_bytes, b"[REDACTED]")
    # ===== 计费善后 =====
    if charge_ctx and charge_ctx.get("sync"):
        # 同步图片(/v1/images/generations):非 200 = 上游没出图 → 退款;200 成功不退。
        if status != 200:
            try:
                refund_user_by_ref(charge_ctx["userId"], charge_ctx["ref"])
            except Exception:
                pass
    elif charge_ctx:
        # 异步 media/generate:成功下单(200 + task_id)→ 记账等轮询退;非 200 → 退款。
        # 200 但解析不到 task_id:保守**不退**(生成已受理,退款=白嫖),仅无法后续按 task 退。
        _tid = None
        try:
            _rj = json.loads(payload)
            _d = _rj.get("data") if isinstance(_rj.get("data"), dict) else {}
            _tid = _d.get("task_id") or (_d.get("task_ids") or [None])[0] or _rj.get("task_id")
        except Exception:
            _tid = None
        if status == 200:
            if _tid:
                with LOCK:
                    _gc = STATE.setdefault("gen_charges", {})
                    _gc[str(_tid)] = charge_ctx
                    _cut = now() - 6 * 3600   # 只清 >6h 陈旧记录(任务早该终态),不删活跃的
                    for _k in [k for k, v in list(_gc.items()) if float((v or {}).get("ts") or 0) < _cut]:
                        _gc.pop(_k, None)
                    persist()
        else:
            try:
                refund_user_by_ref(charge_ctx["userId"], charge_ctx["ref"])
            except Exception:
                pass
    elif method == "GET" and _sub_path == "/v1/skills/task-status":
        _tid = (parse_qs(parsed.query).get("task_id") or [""])[0]
        if _tid:
            with LOCK:
                _ch = (STATE.get("gen_charges") or {}).get(str(_tid))
            # 只有该扣费所属用户轮询才处理(防跨用户触发他人退款)
            if _ch and _ch.get("userId") == u.get("id"):
                _fail = _done = False
                try:
                    _rj = json.loads(payload)
                    _fail, _done = lk888_proxy_task_flags(_rj)
                except Exception:
                    pass
                if _fail:
                    _refunded = False
                    try:
                        refund_user_by_ref(_ch["userId"], _ch["ref"])
                        _refunded = True
                    except Exception:
                        _refunded = False
                    if _refunded:  # 退成功才 pop;退失败保留记录,下次轮询重试(避免退款丢失)
                        with LOCK:
                            (STATE.get("gen_charges") or {}).pop(str(_tid), None)
                            persist()
                elif _done:
                    with LOCK:
                        (STATE.get("gen_charges") or {}).pop(str(_tid), None)
                        persist()
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", resp_ct)
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Access-Control-Allow-Origin", handler.headers.get("Origin") or "*")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(payload)
    except Exception:
        pass


# ============ 漫剧资产库互通(Phase B):读漫剧资产 + 反代其上传目录 + 写回共享库 ============
MANJU_INTERNAL_BASE = os.getenv("MANJU_INTERNAL_BASE", "http://127.0.0.1:8000").rstrip("/")


def _central_base(handler):
    """当前 matrixship 中心服对外基址(优先请求 Host,回退 PUBLIC_HOST:PORT)。"""
    host = ""
    proto = "http"
    try:
        host = (handler.headers.get("Host") or "").strip() if handler else ""
        proto = (handler.headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip() if handler else "http"
    except Exception:
        host = ""
    if not host:
        host = os.getenv("PUBLIC_HOST", "118.178.32.71") + ":" + str(PORT)
    if proto not in ("http", "https"):
        proto = "http"
    return (proto + "://" + host).rstrip("/")


def _resolve_asset_url(u, base):
    """漫剧相对 /uploads/... → 经 matrixship 反代的绝对 URL;已是绝对(http/https/data)的原样返回。"""
    if not u:
        return u
    s = str(u)
    if s.startswith(("http://", "https://", "data:")):
        return s
    if s.startswith("/uploads/"):
        return base + "/manju-media" + s
    if s.startswith("uploads/"):
        return base + "/manju-media/" + s
    return s


def _coerce_ref_list(refs):
    """referenceImages 可能是 list、JSON 串、或 Python-repr 串(漫剧历史数据)。统一成 list[str]。"""
    if refs is None:
        return []
    if isinstance(refs, list):
        return [str(x) for x in refs if x]
    s = str(refs).strip()
    if not s:
        return []
    for loader in (json.loads,):
        try:
            v = loader(s)
            if isinstance(v, list):
                return [str(x) for x in v if x]
        except Exception:
            pass
    # Python repr 串 "['a','b']" → 用 ast 兜底
    try:
        import ast
        v = ast.literal_eval(s)
        if isinstance(v, list):
            return [str(x) for x in v if x]
        if isinstance(v, str):
            return [v]
    except Exception:
        pass
    return [s]


def manju_media_proxy(handler, parsed):
    """反代漫剧上传目录:/manju-media/uploads/... → 漫剧后端 /uploads/...(只放行 /uploads/ 前缀,防开放代理)。"""
    import urllib.request
    import urllib.error
    sub = parsed.path[len("/manju-media"):] or "/"
    if not sub.startswith("/uploads/"):
        return json_response(handler, {"ok": False, "error": "forbidden_path"}, 403)
    url = MANJU_INTERNAL_BASE + sub + (("?" + parsed.query) if parsed.query else "")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=30) as r:
            payload = r.read()
            ct = r.headers.get("Content-Type") or "application/octet-stream"
        handler.send_response(200)
        handler.send_header("Content-Type", ct)
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Cache-Control", "public, max-age=86400")
        handler.end_headers()
        handler.wfile.write(payload)
    except urllib.error.HTTPError as e:
        handler.send_response(e.code)
        handler.end_headers()
    except Exception:
        handler.send_response(502)
        handler.end_headers()


def _shape_shared_asset(r, base):
    ad = r.get("asset_data")
    if isinstance(ad, str):
        try:
            ad = json.loads(ad)
        except Exception:
            ad = {}
    ad = ad or {}
    refs = [_resolve_asset_url(x, base) for x in _coerce_ref_list(ad.get("referenceImages"))]
    thumb = _resolve_asset_url(r.get("thumbnail_url") or (refs[0] if refs else ""), base)
    return {
        "id": r.get("id"),
        "type": r.get("asset_type"),
        "name": r.get("name"),
        "description": r.get("description") or "",
        "prompt": ad.get("basePrompt") or ad.get("prompt") or "",
        "thumbnail": thumb,
        "referenceImages": refs,
        "source": r.get("source_type"),
    }


def shared_assets_list(handler, parsed):
    """GET /api/shared-assets:返回当前用户在漫剧共享资产库的资产(角色/主体/场景/道具/风格),
    URL 已改写成可直接加载的绝对地址。"""
    u = current_user(handler)
    if not u:
        return json_response(handler, {"ok": False, "error": "not_authenticated"}, 401)
    if not (maindb_on() and isinstance(u.get("id"), int)):
        return json_response(handler, {"ok": True, "shared": False, "assets": []})
    qs = parse_qs(parsed.query)
    atype = (qs.get("type") or [None])[0]
    base = _central_base(handler)
    try:
        rows = maindb.list_assets(u.get("id"), limit=300, asset_type=atype)
    except Exception:
        rows = []
    assets = [_shape_shared_asset(r, base) for r in rows]
    return json_response(handler, {"ok": True, "shared": True, "count": len(assets), "assets": assets})


def shared_assets_add(handler, body):
    """POST /api/shared-assets/add:把 matrixship 生成的资产存进漫剧共享资产库(漫剧画布也能看见)。
    body: {type, name, description?, prompt?, thumbnail?, referenceImages|images|image_url}。"""
    u = current_user(handler)
    if not u:
        return json_response(handler, {"ok": False, "error": "not_authenticated"}, 401)
    if not (maindb_on() and isinstance(u.get("id"), int)):
        return json_response(handler, {"ok": False, "error": "shared_library_unavailable"}, 400)
    atype = str(body.get("type") or body.get("asset_type") or "prop").strip() or "prop"
    name = str(body.get("name") or "matrixship素材").strip()[:180]
    desc = body.get("description") or ""
    prompt = body.get("prompt") or desc or ""
    imgs = body.get("referenceImages") or body.get("images")
    if not imgs and body.get("image_url"):
        imgs = [body.get("image_url")]
    imgs = [str(x) for x in (imgs or []) if x]
    thumb = body.get("thumbnail") or body.get("thumbnail_url") or (imgs[0] if imgs else None)
    asset_data = {"basePrompt": prompt, "referenceImages": imgs}
    try:
        aid = maindb.add_asset(u.get("id"), atype, name, asset_data=asset_data,
                               thumbnail_url=thumb, description=desc, source_type="matrixship")
    except Exception as e:
        return json_response(handler, {"ok": False, "error": str(e)[:120]}, 500)
    return json_response(handler, {"ok": bool(aid), "id": aid})


def parse_multipart(handler):
    """Binary-safe multipart/form-data parser.

    Returns (fields, files), where fields is {name: str} and files is
    [(field_name, filename, bytes)].
    """
    ctype = handler.headers.get("Content-Type", "") or ""
    boundary = None
    for part in ctype.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[len("boundary="):].strip('"')
    if not boundary:
        return {}, []
    length = int(handler.headers.get("Content-Length", "0") or "0")
    body = handler.rfile.read(length) if length else b""
    delim = b"--" + boundary.encode("utf-8")
    fields = {}
    files = []
    for raw in body.split(delim):
        if raw[:2] == b"\r\n":
            raw = raw[2:]
        if not raw or raw[:2] == b"--":
            continue
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        if b"\r\n\r\n" not in raw:
            continue
        head, data = raw.split(b"\r\n\r\n", 1)
        disp = ""
        for line in head.decode("utf-8", "ignore").split("\r\n"):
            if line.lower().startswith("content-disposition"):
                disp = line
        name = None
        filename = None
        for seg in disp.split(";"):
            seg = seg.strip()
            if seg.startswith("name="):
                name = seg[len("name="):].strip('"')
            elif seg.startswith("filename="):
                filename = seg[len("filename="):].strip('"')
        if filename is not None:
            files.append((name or "files", filename, data))
        elif name is not None:
            fields[name] = data.decode("utf-8", "ignore")
    return fields, files


def safe_filename(name, fallback="file"):
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    return base or fallback


def load_library(org_id=None):
    org_id = normalize_org_id(org_id) if org_id else None
    with LOCK:
        items = list(STATE.get("library") or [])
    if org_id:
        items = [m for m in items if item_org_id(m) == org_id]
    return items


def save_library(lib):
    with LOCK:
        STATE["library"] = list(lib or [])
        persist()


def find_material(mid, org_id=None):
    mid = (mid or "").strip()
    for m in load_library(org_id):
        if m.get("id") == mid:
            return m
    return None


def material_dir(mid):
    mid = safe_filename(mid, "material")
    path = os.path.normpath(os.path.join(MATERIALS_DIR, mid))
    if path != MATERIALS_DIR and path.startswith(MATERIALS_DIR + os.sep):
        return path
    raise ValueError("bad_material_id")


def public_media_base_url():
    base = (os.getenv("PUBLIC_MEDIA_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return ""
    parsed = urlparse(base)
    if parsed.scheme != "https" or not parsed.netloc:
        return ""
    return base


def public_media_secret():
    return (os.getenv("PUBLIC_MEDIA_TOKEN_SECRET") or "").strip()


def public_media_ttl_sec():
    try:
        return max(60, int(os.getenv("PUBLIC_MEDIA_TTL_SEC", "3600") or 3600))
    except Exception:
        return 3600


def public_media_signature(mid, name, org_id, expires):
    secret = public_media_secret()
    if not secret:
        return ""
    msg = "%s\n%s\n%s\n%s" % (
        normalize_org_id(org_id),
        safe_filename(mid, "material"),
        safe_filename(name, "file"),
        str(expires),
    )
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_public_media_token(mid, name, org_id, expires, token, now=None):
    if not public_media_secret():
        return False, "not_configured"
    try:
        exp = int(str(expires or "0"))
    except Exception:
        return False, "bad_expires"
    if exp < int(now if now is not None else time.time()):
        return False, "expired"
    expected = public_media_signature(mid, name, org_id, exp)
    if not expected or not hmac.compare_digest(expected, str(token or "")):
        return False, "bad_token"
    return True, ""


def public_media_url(mid, name, org_id=None, now=None):
    base = public_media_base_url()
    if not base or not public_media_secret():
        return ""
    exp = int(now if now is not None else time.time()) + public_media_ttl_sec()
    org_id = normalize_org_id(org_id)
    token = public_media_signature(mid, name, org_id, exp)
    if not token:
        return ""
    query = urlencode({"orgId": org_id, "expires": str(exp), "token": token})
    return "%s/api/public-media/%s/%s?%s" % (
        base,
        quote(safe_filename(mid, "material")),
        quote(safe_filename(name, "file")),
        query,
    )


def public_material(m):
    item = dict(m or {})
    mid = item.get("id") or ""
    files = item.get("files") or []
    item["urls"] = ["/api/library/file/%s/%s" % (quote(mid), quote(fn)) for fn in files]
    public_urls = [public_media_url(mid, fn, item_org_id(item)) for fn in files]
    public_urls = [u for u in public_urls if u]
    if public_urls:
        item["publicUrls"] = public_urls
    return item


def parse_http_range(header, size):
    header = str(header or "").strip()
    try:
        size = int(size)
    except Exception:
        return None
    if size <= 0 or not header.startswith("bytes="):
        return None
    spec = header[len("bytes="):].split(",", 1)[0].strip()
    if "-" not in spec:
        return None
    start_s, end_s = spec.split("-", 1)
    try:
        if start_s == "":
            suffix = int(end_s)
            if suffix <= 0:
                return None
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
            if end >= size:
                end = size - 1
        if start < 0 or end < start or start >= size:
            return None
        return start, end
    except Exception:
        return None


def material_payload(mid, org_id=None):
    m = find_material(mid, org_id)
    if not m:
        return None
    return {
        "id": m.get("id"),
        "title": m.get("title") or "",
        "type": m.get("type") or "video",
        "files": [{"name": fn, "url": "/api/library/file/%s/%s" % (quote(m.get("id") or ""), quote(fn))} for fn in (m.get("files") or [])],
    }


def safe_material_file_name(name, idx=0):
    base = safe_filename(name, "file_%d" % idx)
    for ch in '<>:"/\\|?*\r\n\t':
        base = base.replace(ch, "_")
    return base[:160] or ("file_%d" % idx)


def copy_or_link_file(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        if os.path.exists(dst):
            os.remove(dst)
        os.link(src, dst)
    except Exception:
        shutil.copy2(src, dst)


def _write_material_quarantine_metadata(path, metadata):
    temp_path = path + ".tmp-" + uuid.uuid4().hex[:10]
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise


def _prepare_material_quarantine(path, quarantine_root, material_id, reason):
    if not (path and os.path.isfile(path)):
        return None
    safe_mid = re.sub(r"[^A-Za-z0-9._-]+", "_", str(material_id or "").strip())[:120] or "unknown-material"
    stamp = time.strftime("%Y%m%d_%H%M%S") + ("_%03d_" % int((time.time() % 1) * 1000)) + uuid.uuid4().hex[:8]
    target_dir = os.path.join(quarantine_root, safe_mid, stamp)
    backup_path = os.path.join(target_dir, os.path.basename(path))
    metadata_path = os.path.join(target_dir, "metadata.json")
    os.makedirs(target_dir, exist_ok=False)
    try:
        shutil.copy2(path, backup_path)
        if not os.path.isfile(backup_path) or os.path.getsize(backup_path) != os.path.getsize(path):
            raise OSError("quarantine_copy_incomplete")
        _write_material_quarantine_metadata(metadata_path, {
            "materialId": str(material_id or ""),
            "reason": str(reason or "media_invalid"),
            "originalPath": os.path.abspath(path),
            "quarantinedAt": time.time(),
        })
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    return {
        "backupPath": backup_path,
        "metadataPath": metadata_path,
        "originalPath": path,
    }


def _restore_material_files_from_quarantine(backups, installed_paths):
    by_original = {item["originalPath"]: item for item in backups if item}
    first_error = None
    for path in reversed(installed_paths):
        restore_temp = path + ".restore-" + uuid.uuid4().hex[:10]
        try:
            backup = by_original.get(path)
            if backup and os.path.isfile(backup.get("backupPath") or ""):
                shutil.copy2(backup["backupPath"], restore_temp)
                os.replace(restore_temp, path)
            elif os.path.isfile(path):
                os.remove(path)
        except Exception as exc:
            first_error = first_error or exc
        finally:
            try:
                if os.path.exists(restore_temp):
                    os.remove(restore_temp)
            except OSError:
                pass
    if first_error:
        raise first_error


def node_info(node_id):
    with LOCK:
        return dict((STATE.get("nodes") or {}).get(node_id or "") or {})


def mirror_download_material_to_library(result, org_id, node_id=""):
    """Mirror a node-local downloaded material into central enterprise library.
    The user-facing frontend reads central /api/library, while downloads execute on nodes.
    This function creates a central material backed by copied/proxied node media so it can be queued/published later.
    """
    if not isinstance(result, dict) or not result.get("ok"):
        return None
    mat = result.get("material") if isinstance(result.get("material"), dict) else {}
    if not mat:
        return None
    org_id = normalize_org_id(org_id)
    node_id = node_id or result.get("nodeId") or result.get("dispatchNodeId") or ""
    remote_mid = str(mat.get("id") or result.get("materialId") or "")
    source_key = str(mat.get("sourceDownloadKey") or mat.get("sourceUrl") or result.get("savePath") or remote_mid)
    files = [str(x or "") for x in (mat.get("files") or []) if str(x or "").strip()]
    if not files:
        return None

    cleanup_quarantine(MATERIAL_QUARANTINE_DIR, int(os.getenv("MEDIA_QUARANTINE_RETENTION_DAYS", "7") or 7))
    ninfo = node_info(node_id)
    local_api = str(ninfo.get("localApi") or "").strip().rstrip("/")
    source_dir = str(mat.get("sourceDownloadPath") or result.get("savePath") or "")
    media_type = mat.get("type") or "video"
    video_exts = (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")
    image_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    candidate_id = uuid.uuid4().hex
    os.makedirs(MATERIALS_DIR, exist_ok=True)
    staging_dir = os.path.join(MATERIALS_DIR, ".incoming-" + candidate_id)
    os.makedirs(staging_dir, exist_ok=False)

    def copy_incoming(name, dst):
        copied = False
        if source_dir:
            src = os.path.normpath(os.path.join(source_dir, os.path.basename(name)))
            if os.path.isfile(src):
                copy_or_link_file(src, dst)
                copied = True
        if not copied and local_api and remote_mid:
            url = local_api + "/api/library/file/%s/%s" % (quote(remote_mid), quote(os.path.basename(name)))
            req = urllib.request.Request(url, headers=local_agent_headers(), method="GET")
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = resp.read()
            with open(dst, "wb") as f:
                f.write(data)
            copied = True
        return copied and os.path.isfile(dst)

    def find_existing(rows):
        for index, old in enumerate(rows):
            if item_org_id(old) != org_id:
                continue
            if old.get("sourceDownloadKey") == source_key or (remote_mid and old.get("remoteMaterialId") == remote_mid and old.get("remoteNodeId") == node_id):
                return index, old
        return None, None

    def record_token(record):
        return json.dumps(record or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    def record_is_valid(record):
        mid = str((record or {}).get("id") or "")
        if not mid:
            return False
        mdir = material_dir(mid)
        names = list((record or {}).get("files") or [])
        video_names = [name for name in names if os.path.splitext(name)[1].lower() in video_exts]
        if video_names:
            return any(validate_video_file(os.path.join(mdir, name)).get("ok") for name in video_names)
        if (record or {}).get("type") == "video":
            return False
        image_names = [name for name in names if os.path.splitext(name)[1].lower() in image_exts]
        return any(validate_image_file(os.path.join(mdir, name)).get("ok") for name in image_names)

    saved = []
    validations = []
    try:
        for idx, name in enumerate(files):
            clean = safe_material_file_name(name, idx)
            if clean in saved:
                stem, ext = os.path.splitext(clean)
                clean = "%s_%d%s" % (stem, idx, ext)
            staged_path = os.path.join(staging_dir, clean)
            if not copy_incoming(name, staged_path):
                continue
            validation = validate_video_file(staged_path) if media_type == "video" else validate_image_file(staged_path)
            if not validation.get("ok"):
                return None
            saved.append(clean)
            validations.append(validation)
        if not saved:
            return None

        first_validation = validations[0] if validations else {}
        while True:
            event_kind = None
            event_data = None
            with LOCK:
                library = list(STATE.get("library") or [])
                existing_index, existing = find_existing(library)
                if existing is None:
                    mid = candidate_id
                    mdir = material_dir(mid)
                    item = {
                        "id": mid,
                        "orgId": org_id,
                        "title": (mat.get("title") or (result.get("work") or {}).get("desc") or (result.get("work") or {}).get("title") or saved[0])[:120],
                        "type": media_type,
                        "files": list(saved),
                        "urls": ["/api/library/file/%s/%s" % (quote(mid), quote(fn)) for fn in saved],
                        "published": 0,
                        "createdAt": now(),
                        "platform": mat.get("platform") or ("xhs" if "/xhs/" in str(result.get("dispatchPath") or "") else "douyin"),
                        "sourceUrl": mat.get("sourceUrl") or "",
                        "sourceDownloadKey": source_key,
                        "sourceDownloadPath": source_dir,
                        "sourceAuthor": mat.get("sourceAuthor") or "",
                        "remoteNodeId": node_id,
                        "remoteMaterialId": remote_mid,
                        "importedFromDownload": True,
                        "mirroredFromNode": True,
                        "duration": first_validation.get("duration"),
                        "width": first_validation.get("width"),
                        "height": first_validation.get("height"),
                    }
                    previous_library = STATE.get("library") or []
                    moved = False
                    try:
                        os.replace(staging_dir, mdir)
                        moved = True
                        library.insert(0, item)
                        STATE["library"] = library
                        persist()
                    except Exception:
                        STATE["library"] = previous_library
                        if moved:
                            try:
                                os.replace(mdir, staging_dir)
                            except OSError:
                                shutil.rmtree(mdir, ignore_errors=True)
                        raise
                    event_kind = "download_material_mirrored"
                    event_data = {"orgId": org_id, "nodeId": node_id, "remoteMaterialId": remote_mid, "materialId": mid}
                    committed = item
                else:
                    snapshot = dict(existing)
                    snapshot_token = record_token(existing)
                    committed = None

            if committed is not None:
                add_event(event_kind, event_data)
                return committed

            existing_valid = record_is_valid(snapshot)

            prepared_mid = None
            prepared_dir = None
            prepared_backups = []
            if not existing_valid:
                prepared_mid = str(snapshot.get("id") or uuid.uuid4().hex)
                prepared_dir = material_dir(prepared_mid)
                for old_name in snapshot.get("files") or []:
                    old_path = os.path.join(prepared_dir, old_name)
                    if os.path.isfile(old_path):
                        backup = _prepare_material_quarantine(
                            old_path, MATERIAL_QUARANTINE_DIR, prepared_mid, "invalid_historical_media"
                        )
                        if backup:
                            prepared_backups.append(backup)
                backed_up_paths = {item["originalPath"] for item in prepared_backups}
                for name in saved:
                    final_path = os.path.join(prepared_dir, name)
                    if os.path.isfile(final_path) and final_path not in backed_up_paths:
                        backup = _prepare_material_quarantine(
                            final_path, MATERIAL_QUARANTINE_DIR, prepared_mid, "overwritten_historical_media"
                        )
                        if backup:
                            prepared_backups.append(backup)
                            backed_up_paths.add(final_path)

            with LOCK:
                library = list(STATE.get("library") or [])
                existing_index, current = find_existing(library)
                if current is None or record_token(current) != snapshot_token:
                    continue
                if existing_valid:
                    return current

                mid = prepared_mid
                mdir = prepared_dir
                os.makedirs(mdir, exist_ok=True)
                previous_library = STATE.get("library") or []
                backups = prepared_backups
                installed_paths = []
                try:
                    for name in saved:
                        staged_path = os.path.join(staging_dir, name)
                        final_path = os.path.join(mdir, name)
                        os.replace(staged_path, final_path)
                        installed_paths.append(final_path)

                    repaired = dict(current)
                    repair_updates = {
                        "id": mid,
                        "title": (mat.get("title") or (result.get("work") or {}).get("desc") or current.get("title") or saved[0])[:120],
                        "type": media_type,
                        "files": list(saved),
                        "urls": ["/api/library/file/%s/%s" % (quote(mid), quote(fn)) for fn in saved],
                        "platform": mat.get("platform") or current.get("platform") or "douyin",
                        "sourceUrl": mat.get("sourceUrl") or current.get("sourceUrl") or "",
                        "sourceDownloadKey": source_key,
                        "sourceDownloadPath": source_dir,
                        "sourceAuthor": mat.get("sourceAuthor") or current.get("sourceAuthor") or "",
                        "remoteNodeId": node_id,
                        "remoteMaterialId": remote_mid,
                        "repaired": True,
                        "repairedAt": now(),
                    }
                    if media_type == "video":
                        for key in ("duration", "width", "height"):
                            value = first_validation.get(key)
                            if isinstance(value, (int, float)) and value > 0:
                                repair_updates[key] = value
                    repaired.update(repair_updates)
                    library[existing_index] = repaired
                    STATE["library"] = library
                    persist()
                except Exception:
                    restore_error = None
                    try:
                        _restore_material_files_from_quarantine(backups, installed_paths)
                    except Exception as exc:
                        restore_error = exc
                    STATE["library"] = previous_library
                    if restore_error:
                        raise restore_error
                    raise
                final_paths = {os.path.join(mdir, name) for name in saved}
                for backup in backups:
                    old_path = backup.get("originalPath") or ""
                    if old_path and old_path not in final_paths:
                        try:
                            if os.path.isfile(old_path):
                                os.remove(old_path)
                        except OSError:
                            pass
                event_kind = "download_material_repaired"
                event_data = {"orgId": org_id, "nodeId": node_id, "remoteMaterialId": remote_mid, "materialId": mid}
                committed = repaired

            add_event(event_kind, event_data)
            return committed
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def default_publish_settings():
    return {"perAccountPerDay": 1, "intervalMin": 60, "enabled": False}


def load_settings(org_id=None):
    org_id = normalize_org_id(org_id)
    with LOCK:
        org_settings = STATE.setdefault("orgSettings", {})
        if org_id not in org_settings:
            org_settings[org_id] = dict(STATE.get("settings") or default_publish_settings())
        s = dict(org_settings.get(org_id) or {})
    s.setdefault("perAccountPerDay", 1)
    s.setdefault("intervalMin", 60)
    s.setdefault("enabled", False)
    s["orgId"] = org_id
    return s


def save_settings(s, org_id=None):
    org_id = normalize_org_id(org_id)
    merged = load_settings(org_id)
    merged.update(s or {})
    merged["orgId"] = org_id
    with LOCK:
        STATE.setdefault("orgSettings", {})[org_id] = merged
        if org_id == DEFAULT_ORG_ID:
            STATE["settings"] = {k: v for k, v in merged.items() if k != "orgId"}
        persist()
    return merged


def load_queue(org_id=None):
    org_id = normalize_org_id(org_id) if org_id else None
    with LOCK:
        items = list(STATE.get("queue") or [])
    if org_id:
        items = [q for q in items if item_org_id(q) == org_id]
    return items


def save_queue(q):
    with LOCK:
        STATE["queue"] = list(q or [])
        persist()


def queue_receipt_id(qid):
    qid = (qid or "").strip()
    return "queue:" + qid if qid else "queue:"


def append_queue_event(item, action="status", status="", meta=None, ts=None):
    item = item if isinstance(item, dict) else {}
    qid = item.get("id") or ""
    item["receiptId"] = item.get("receiptId") or queue_receipt_id(qid)
    events = list(item.get("events") or [])
    ts = float(ts or now())
    idx = len(events) + 1
    safe_meta = audit_safe_body(meta if isinstance(meta, dict) else {})
    evt = {
        "id": "%s:evt:%03d" % (queue_receipt_id(qid), idx),
        "queueId": qid,
        "action": action or "status",
        "status": status or item.get("status") or "",
        "ts": ts,
        "meta": safe_meta,
    }
    events.append(evt)
    item["events"] = events[-30:]
    item["latestEventId"] = evt["id"]
    return evt


def public_queue_item(item):
    q = dict(item or {})
    qid = q.get("id") or ""
    q["receiptId"] = q.get("receiptId") or queue_receipt_id(qid)
    events = list(q.get("events") or [])
    q["events"] = events[-30:]
    q["latestEventId"] = (events[-1] or {}).get("id") if events else q.get("latestEventId") or q["receiptId"]
    q["health"] = queue_item_health(q)
    return q


def queue_item_health(item):
    q = dict(item or {})
    st = queue_task_status(q.get("status") or "pending") if "queue_task_status" in globals() else (q.get("status") or "pending")
    ts = now()
    created = float(q.get("createdAt") or q.get("updatedAt") or ts)
    updated = float(q.get("updatedAt") or created)
    age = max(0, ts - created)
    idle = max(0, ts - updated)
    health = {
        "status": st,
        "severity": "info",
        "label": "\u6392\u961f\u4e2d" if st == "queued" else ("\u53d1\u5e03\u4e2d" if st == "running" else ("\u5df2\u5b8c\u6210" if st == "done" else ("\u5df2\u53d6\u6d88" if st == "canceled" else "\u5f85\u786e\u8ba4"))),
        "message": "\u7b49\u5f85\u8c03\u5ea6\u8282\u70b9\u6267\u884c\u3002",
        "nextAction": "wait",
        "actionLabel": "\u67e5\u770b\u8be6\u60c5",
        "ageSec": round(age, 1),
        "idleSec": round(idle, 1),
        "blockedBy": "",
        "accountId": q.get("accountId") or "",
        "nodeId": "",
        "supportRef": "",
    }
    if st == "running":
        health.update({"severity": "info", "label": "\u53d1\u5e03\u4e2d", "message": "\u6267\u884c\u8282\u70b9\u6b63\u5728\u5904\u7406\u8be5\u53d1\u5e03\u4efb\u52a1\u3002", "nextAction": "observe"})
        return health
    if st == "done":
        health.update({"severity": "info", "label": "\u5df2\u5b8c\u6210", "message": "\u961f\u5217\u4efb\u52a1\u5df2\u5b8c\u6210\u3002", "nextAction": "done"})
        return health
    if st == "canceled":
        health.update({"severity": "info", "label": "\u5df2\u53d6\u6d88", "message": "\u961f\u5217\u4efb\u52a1\u5df2\u53d6\u6d88\uff0c\u53ef\u6309\u9700\u91cd\u65b0\u52a0\u5165\u8ba1\u5212\u3002", "nextAction": "requeue"})
        return health
    pf = q.get("preflight") if isinstance(q.get("preflight"), dict) else None
    if st in ("queued", "failed") and not pf:
        try:
            pf = publish_preflight(item_org_id(q), q.get("accountId") or "douyin-self", q.get("materialId") or "", mode="queue_view", dry_run=False)
        except Exception as e:
            pf = {"ok": False, "error": "preflight_unavailable", "message": str(e)}
    if pf and not pf.get("ok"):
        aa = pf.get("accountAuthorization") if isinstance(pf.get("accountAuthorization"), dict) else {}
        reason = pf.get("error") or (pf.get("errors") or ["preflight_failed"])[0]
        next_action = aa.get("nextAction") or ("authorize_account" if str(reason).startswith("account_") else "repair_queue")
        label = aa.get("summary") or public_error_text(reason) or "\u524d\u7f6e\u6821\u9a8c\u672a\u901a\u8fc7"
        action_label = "\u4fee\u590d\u8d26\u53f7" if next_action in ("authorize_account", "resume_auth") else ("\u67e5\u770b\u8282\u70b9" if next_action == "repair_node" else "\u67e5\u770b\u8be6\u60c5")
        health.update({
            "severity": aa.get("severity") or "warning",
            "label": "\u9700\u5904\u7406",
            "message": label,
            "nextAction": next_action,
            "actionLabel": action_label,
            "blockedBy": reason,
            "supportRef": aa.get("supportRef") or "",
            "accountAuth": {k: aa.get(k) for k in ("ready", "code", "severity", "summary", "supportRef", "nextAction", "handoffNote")},
            "nodeId": ((pf.get("account") or {}).get("nodeId") if isinstance(pf.get("account"), dict) else "") or "",
        })
        return health
    if st == "failed":
        health.update({"severity": "warning", "label": "\u5931\u8d25", "message": public_error_text(q.get("lastError") or "queue_failed"), "nextAction": "retry", "actionLabel": "\u91cd\u8bd5"})
    elif st == "queued" and age > 3600:
        health.update({"severity": "warning", "label": "\u6392\u961f\u8f83\u4e45", "message": "\u961f\u5217\u5df2\u7b49\u5f85\u8d85\u8fc7 1 \u5c0f\u65f6\uff0c\u53ef\u5230\u4efb\u52a1\u4e2d\u5fc3\u67e5\u770b\u8282\u70b9\u5bb9\u91cf\u3002", "nextAction": "inspect_capacity"})
    return health


def add_queue_event_for_task(task_id, action, meta=None):
    task_id = (task_id or "").strip()
    if not task_id:
        return 0
    changed = 0
    with LOCK:
        q = list(STATE.get("queue") or [])
        for item in q:
            if item.get("centralTaskId") == task_id:
                append_queue_event(item, action=action, status=item.get("status") or "", meta=meta or {})
                changed += 1
        if changed:
            STATE["queue"] = q
            persist()
    return changed


def load_kb(org_id=None):
    org_id = normalize_org_id(org_id) if org_id else None
    with LOCK:
        docs = list(STATE.get("kb") or [])
    if org_id:
        docs = [d for d in docs if item_org_id(d) == org_id]
    return docs


def split_text_chunks(text, size=700, overlap=80):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    chunks = []
    i = 0
    n = len(text)
    size = max(200, int(size or 700))
    overlap = max(0, min(int(overlap or 0), size // 2))
    while i < n:
        part = text[i:i + size].strip()
        if part:
            chunks.append(part)
        if i + size >= n:
            break
        i += size - overlap
    return chunks


def public_kb_doc(doc):
    chunks = doc.get("chunkTexts") or []
    preview = (doc.get("preview") or doc.get("text") or (chunks[0] if chunks else ""))[:160]
    return {
        "id": doc.get("id"),
        "orgId": item_org_id(doc),
        "title": doc.get("title") or "未命名资料",
        "type": doc.get("type") or "company",
        "chunks": len(chunks),
        "chars": int(doc.get("chars") or len(doc.get("text") or "")),
        "preview": preview,
        "createdBy": doc.get("createdBy") or doc.get("createdByUserId") or "",
        "createdByUserId": doc.get("createdByUserId") or doc.get("createdBy") or "",
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
    }


def add_kb_doc(title, ktype, text, org_id=None, source=None, created_by=None):
    org_id = normalize_org_id(org_id)
    text = (text or "").strip()
    chunks = split_text_chunks(text)
    item = {
        "id": uuid.uuid4().hex,
        "orgId": org_id,
        "title": (title or source or "未命名资料").strip(),
        "type": (ktype or "company").strip() or "company",
        "text": text,
        "chunkTexts": chunks,
        "chars": len(text),
        "preview": text[:160],
        "source": source or "",
        "createdBy": created_by or "",
        "createdByUserId": created_by or "",
        "createdAt": now(),
        "updatedAt": now(),
    }
    with LOCK:
        STATE.setdefault("kb", []).insert(0, item)
        persist()
    return item


def delete_kb_doc(doc_id, org_id=None):
    org_id = normalize_org_id(org_id)
    found = False
    with LOCK:
        kept = []
        for d in STATE.get("kb") or []:
            if d.get("id") == doc_id and item_org_id(d) == org_id:
                found = True
                continue
            kept.append(d)
        STATE["kb"] = kept
        if found:
            persist()
    return found


KB_INTENT_PHRASES = (
    "注意事项",
    "使用方法",
    "适用肤质",
    "适用场景",
    "产品规格",
    "产品卖点",
    "核心卖点",
    "售后规则",
    "价格政策",
    "常见问题",
    "禁忌",
    "过敏",
    "保存",
)


def _compact_kb_text(text):
    return re.sub(r"\s+", "", (text or "").lower())


def kb_terms(text):
    text = (text or "").lower()
    parts = set([x for x in re.split(r"\s+", text) if x])
    cjk = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    for ch in cjk:
        parts.add(ch)
    for width in (2, 3, 4):
        for i in range(0, max(0, len(cjk) - width + 1)):
            parts.add(cjk[i:i + width])
    return parts


def kb_query_phrases(query):
    compact = _compact_kb_text(query)
    phrases = [p for p in KB_INTENT_PHRASES if p in compact]
    cjk = "".join(ch for ch in compact if "\u4e00" <= ch <= "\u9fff")
    for width in (4, 3, 2):
        for i in range(0, max(0, len(cjk) - width + 1)):
            part = cjk[i:i + width]
            if part not in phrases:
                phrases.append(part)
    return phrases


def kb_match_score(query, chunk):
    q_terms = kb_terms(query)
    if not q_terms:
        return 0, ""
    c_terms = kb_terms(chunk)
    score = len(q_terms & c_terms)
    best_phrase = ""
    compact_chunk = _compact_kb_text(chunk)
    for phrase in kb_query_phrases(query):
        if phrase and phrase in compact_chunk:
            score += max(8, len(phrase) * 4)
            if not best_phrase or len(phrase) > len(best_phrase):
                best_phrase = phrase
            if re.search(r"(^|\n)\s*[一二三四五六七八九十0-9]+[、.．]\s*" + re.escape(phrase), chunk):
                score += 12
    return score, best_phrase


def kb_snippet(chunk, phrase="", limit=700):
    chunk = (chunk or "").strip()
    limit = max(180, int(limit or 700))
    idx = chunk.find(phrase) if phrase else -1
    if idx < 0:
        if len(chunk) <= limit:
            return chunk
        return chunk[:limit]
    start = max(0, idx - 120)
    end = min(len(chunk), start + limit)
    snippet = chunk[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(chunk):
        snippet = snippet + "..."
    return snippet


def search_kb(query, org_id=None, limit=5):
    if not kb_terms(query):
        return []
    hits = []
    for doc in load_kb(org_id):
        for idx, chunk in enumerate(doc.get("chunkTexts") or []):
            score, phrase = kb_match_score(query, chunk)
            if score:
                hits.append({
                    "title": doc.get("title") or "资料",
                    "text": kb_snippet(chunk, phrase, limit=700),
                    "score": score,
                    "docId": doc.get("id"),
                    "chunk": idx,
                })
    hits.sort(key=lambda x: x.get("score", 0), reverse=True)
    return hits[:max(1, int(limit or 5))]


def decode_uploaded_text(filename, data):
    name = (filename or "").lower()
    if name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".avi", ".zip", ".rar", ".7z")):
        return ""
    for enc in ("utf-8", "gb18030", "gbk", "latin-1"):
        try:
            return data.decode(enc, "ignore")
        except Exception:
            pass
    return data.decode("utf-8", "ignore")


def bump_published(mid):
    with LOCK:
        lib = list(STATE.get("library") or [])
        for m in lib:
            if m.get("id") == mid:
                m["published"] = int(m.get("published") or 0) + 1
                break
        STATE["library"] = lib
        persist()


def task_result_ok(result):
    if not isinstance(result, dict):
        return False
    if result.get("ok") is False:
        return False
    # publish/run exposes either filled=True (dry-run) or published=True (real run).
    return bool(result.get("ok") or result.get("published") or result.get("filled"))


def node_authorized(handler):
    return (handler.headers.get("X-Node-Secret") or "") == NODE_SECRET


def extract_user_token(handler):
    tok = handler.headers.get("X-Matrix-User-Token") or ""
    auth = handler.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
    return tok.strip()


def public_user(user):
    if not user:
        return None
    item = dict(user)
    for k in ("password", "passwordHash", "passwordSalt"):
        item.pop(k, None)
    # 去掉内部标记(_authType/_sessionId/_mdb 等),不外泄给客户端
    for k in [k for k in item if isinstance(k, str) and k.startswith("_")]:
        item.pop(k, None)
    return item


def is_maindb_user(user):
    return bool(user and (user.get("_mdb") or (maindb_on() and isinstance(user.get("id"), int))))


def implicit_memberships_for_user(user):
    if not is_maindb_user(user):
        return []
    uid = user.get("id")
    role = "admin" if user.get("isPlatformAdmin") else "member"
    return [{
        "id": "m-%s-%s" % (DEFAULT_ORG_ID, uid),
        "orgId": DEFAULT_ORG_ID,
        "userId": uid,
        "role": role,
        "status": "active",
        "implicit": True,
        "source": "maindb",
    }]


def user_memberships(user):
    if not user:
        return []
    user_id = user.get("id")
    with LOCK:
        memberships = [dict(m) for m in (STATE.get("memberships") or []) if m.get("userId") == user_id]
    seen_orgs = {normalize_org_id(m.get("orgId")) for m in memberships}
    for m in implicit_memberships_for_user(user):
        oid = normalize_org_id(m.get("orgId"))
        if oid not in seen_orgs:
            memberships.append(m)
            seen_orgs.add(oid)
    return memberships


def same_user_id(a, b):
    return str(a if a is not None else "").strip() == str(b if b is not None else "").strip()


def user_orgs(user_id, user=None):
    if user is None and maindb_on() and isinstance(user_id, int):
        user = {"id": user_id, "_mdb": True}
    memberships = user_memberships(user) if user else []
    if not memberships:
        with LOCK:
            memberships = [dict(m) for m in (STATE.get("memberships") or []) if m.get("userId") == user_id]
    orgs = []
    with LOCK:
        orgs = []
        for m in memberships:
            org = next((dict(o) for o in (STATE.get("organizations") or []) if o.get("id") == m.get("orgId")), None)
            if not org and normalize_org_id(m.get("orgId")) == DEFAULT_ORG_ID:
                org = {"id": DEFAULT_ORG_ID, "name": "Default Workspace", "status": "active"}
            if org:
                org["role"] = m.get("role") or "member"
                orgs.append(org)
    return orgs


def current_user(handler):
    tok = extract_user_token(handler)
    if USER_TOKEN and tok == USER_TOKEN:
        with LOCK:
            u = next((dict(x) for x in (STATE.get("users") or []) if x.get("id") == "user-owner"), None)
        if u:
            u["_authType"] = "root-token"
        return u
    if not tok:
        return None
    with LOCK:
        sessions = STATE.setdefault("sessions", [])
        changed = False
        found = None
        kept = []
        for s in sessions:
            if float(s.get("expiresAt") or 0) <= now():
                changed = True
                continue
            kept.append(s)
            if s.get("token") == tok:
                found = dict(s)
        if changed:
            STATE["sessions"] = kept
            persist()
    if not found:
        return None
    if maindb_on():
        try:
            row = maindb.get_user_by_id(found.get("userId"))
        except Exception:
            row = None
        u = shape_mdb_user(row, "session", found.get("id"))
        return u if (u and u.get("status") == "active") else None
    with LOCK:
        u = next((dict(x) for x in (STATE.get("users") or []) if x.get("id") == found.get("userId") and x.get("status", "active") == "active"), None)
    if u:
        u["_authType"] = "session"
        u["_sessionId"] = found.get("id")
    return u


def hash_password(password, salt=None):
    salt = salt or uuid.uuid4().hex
    h = hashlib.sha256((salt + ":" + (password or "")).encode("utf-8")).hexdigest()
    return salt, h


def set_user_password(user, password):
    # 漫剧用户:直接把 bcrypt 写回主库 users.password_hash
    if maindb_on() and user and (user.get("_mdb") or isinstance(user.get("id"), int)):
        try:
            maindb.set_password(user.get("id"), password)
            user["passwordHash"] = maindb.hash_password(password)
        except Exception:
            pass
        return
    salt, h = hash_password(password)
    user["passwordSalt"] = salt
    user["passwordHash"] = h


def verify_user_password(user, password):
    password = password or ""
    # 漫剧用户走 bcrypt(passlib)校验
    if maindb_on() and user and user.get("_mdb"):
        return maindb.verify_password({"password_hash": user.get("passwordHash")}, password)
    if user and user.get("passwordHash"):
        _, h = hash_password(password, user.get("passwordSalt") or "")
        return h == user.get("passwordHash")
    # Bootstrap path: before commercial accounts have passwords, the owner can
    # log in with the existing deployment token. This preserves compatibility.
    if user and user.get("id") == "user-owner" and USER_TOKEN and password == USER_TOKEN:
        return True
    admin_pw = os.getenv("CENTRAL_ADMIN_PASSWORD", "")
    if user and user.get("id") == "user-owner" and admin_pw and password == admin_pw:
        return True
    return False


_MAINDB_OK = False
_MAINDB_LAST_PROBE = 0.0


def maindb_on():
    """漫剧主库是否接管账号/余额。True 后永久缓存;未就绪时每 30s 重探一次
    (避免启动瞬间 MySQL 未起就把整机永久降级到本地 JSON)。"""
    global _MAINDB_OK, _MAINDB_LAST_PROBE
    if _MAINDB_OK:
        return True
    if not maindb:
        return False
    t = now()
    if t - _MAINDB_LAST_PROBE < 30:
        return False
    _MAINDB_LAST_PROBE = t
    try:
        _MAINDB_OK = bool(maindb.configured() and maindb.ping())
    except Exception:
        _MAINDB_OK = False
    return _MAINDB_OK


def shape_mdb_user(row, auth_type="session", session_id=None):
    """漫剧 users 行 → matrixship 代码期望的用户 dict 形状。id=漫剧 int id;balance=算力;
    passwordHash=bcrypt;isPlatformAdmin 由 is_admin/is_staff 决定。"""
    if not row:
        return None
    active = row.get("is_active")
    return {
        "id": row.get("id"),
        "phone": row.get("phone"),
        "email": row.get("email"),
        "name": row.get("username") or ("用户" + str(row.get("phone") or "0000")[-4:]),
        "balance": float(row.get("computing_power") or 0),
        "passwordHash": row.get("password_hash"),
        "status": "active" if (active in (1, True, None)) else "disabled",
        "is_admin": bool(row.get("is_admin")),
        "isPlatformAdmin": bool(row.get("is_admin")) or bool(row.get("is_staff")),
        "member_level": row.get("member_level"),
        "_authType": auth_type,
        "_sessionId": session_id,
        "_mdb": True,
    }


def find_login_user(identifier):
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    low = identifier.lower()
    if maindb_on():
        # 运营方后台账号("admin")仍用本地 user-owner;其余走漫剧主库
        if low != "admin":
            try:
                row = maindb.find_login_user(identifier)
            except Exception:
                row = None
            if row:
                return shape_mdb_user(row, "session")
            return None
        with LOCK:
            return next((dict(u) for u in STATE.get("users") or [] if u.get("id") == "user-owner"), None)
    with LOCK:
        for u in STATE.get("users") or []:
            vals = [u.get("id"), u.get("phone"), u.get("email"), u.get("name")]
            if low == "admin" and u.get("id") == "user-owner":
                return dict(u)
            if any(str(v or "").strip().lower() == low for v in vals):
                return dict(u)
    return None


def is_phone_login_identifier(identifier):
    identifier = str(identifier or "").strip()
    return identifier.isdigit() and len(identifier) == 11


def login_requires_phone_code(identifier, user):
    return bool(user and user.get("phone") and is_phone_login_identifier(identifier))


def validate_legal_consent(body):
    value = (body or {}).get("legalConsent")
    if not isinstance(value, dict) or value.get("accepted") is not True:
        return None, "legal_consent_required"
    terms_version = str(value.get("termsVersion") or "").strip()
    privacy_version = str(value.get("privacyVersion") or "").strip()
    if terms_version != LEGAL_TERMS_VERSION or privacy_version != LEGAL_PRIVACY_VERSION:
        return None, "legal_consent_outdated"
    accepted_at = str(value.get("acceptedAt") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", accepted_at):
        return None, "legal_consent_required"
    return {
        "accepted": True,
        "termsVersion": terms_version,
        "privacyVersion": privacy_version,
        "acceptedAtClient": accepted_at,
        "clientVersion": str(value.get("clientVersion") or "")[:40],
    }, ""


def legal_consent_error_response(error):
    return {
        "ok": False,
        "error": error or "legal_consent_required",
        "requiredTermsVersion": LEGAL_TERMS_VERSION,
        "requiredPrivacyVersion": LEGAL_PRIVACY_VERSION,
        "effectiveDate": LEGAL_EFFECTIVE_DATE,
    }


def record_legal_consent(handler, user, consent):
    accepted_at_server = now()
    user_id = str((user or {}).get("id") or "")
    record = dict(consent or {})
    record.update({
        "userId": user_id,
        "acceptedAtServer": accepted_at_server,
        "ip": handler.client_address[0] if getattr(handler, "client_address", None) else "",
        "userAgent": (handler.headers.get("User-Agent") or "")[:300],
    })
    with LOCK:
        STATE.setdefault("legalConsents", {})[user_id] = record
        for stored in STATE.get("users") or []:
            if str(stored.get("id") or "") != user_id:
                continue
            meta = stored.get("meta") if isinstance(stored.get("meta"), dict) else {}
            meta["legalConsent"] = {
                "termsVersion": record.get("termsVersion"),
                "privacyVersion": record.get("privacyVersion"),
                "acceptedAtServer": accepted_at_server,
            }
            stored["meta"] = meta
            stored["updatedAt"] = accepted_at_server
            break
        persist()
    add_audit(handler, "legal.consent.accept", "/api/auth", ok=True, meta={
        "userId": user_id,
        "termsVersion": record.get("termsVersion"),
        "privacyVersion": record.get("privacyVersion"),
        "acceptedAtClient": record.get("acceptedAtClient"),
        "acceptedAtServer": accepted_at_server,
        "clientVersion": record.get("clientVersion"),
    })
    return record


def user_has_current_legal_consent(user):
    user_id = str((user or {}).get("id") or "")
    with LOCK:
        record = dict((STATE.get("legalConsents") or {}).get(user_id) or {})
    return bool(
        record.get("termsVersion") == LEGAL_TERMS_VERSION
        and record.get("privacyVersion") == LEGAL_PRIVACY_VERSION
    )


def create_user_session(user, request_meta=None):
    token = uuid.uuid4().hex + uuid.uuid4().hex
    item = {
        "id": uuid.uuid4().hex,
        "token": token,
        "userId": user.get("id"),
        "createdAt": now(),
        "expiresAt": now() + SESSION_TTL_SEC,
        "meta": request_meta or {},
    }
    with LOCK:
        sessions = [s for s in STATE.setdefault("sessions", []) if float(s.get("expiresAt") or 0) > now()]
        sessions.append(item)
        STATE["sessions"] = sessions[-500:]
        persist()
    return item


# ============ 手机验证码登录 + 阿里云短信(移植自漫剧/AIedu) ============
SMS_CFG = {
    "access_key_id": os.getenv("ALIYUN_SMS_KEY_ID", ""),        # 密钥不写死进源码,走 env(生产 systemd 已配)
    "access_key_secret": os.getenv("ALIYUN_SMS_KEY_SECRET", ""),  # ⚠️旧 AK 已进 git 历史,需去阿里云控制台轮换
    "sign_name": os.getenv("ALIYUN_SMS_SIGN", "南京恒知云枢智能科技"),
    "tmpl_login": os.getenv("ALIYUN_SMS_TMPL_LOGIN", "SMS_505715313"),
    "tmpl_register": os.getenv("ALIYUN_SMS_TMPL_REGISTER", "SMS_505940287"),
}
# 开发模式:不真发短信,验证码直接回给前端,便于本地测试(生产务必关掉)
SMS_DEV_MODE = os.getenv("SMS_DEV_MODE", "").strip().lower() in ("1", "true", "yes", "on")

_PHONE_CODES = {}        # {phone: {"code","expiresAt","sentAt","scene"}}
_SEND_IP_LOG = {}        # {ip: [ts,...]}  单 IP 每小时发送上限
_PHONE_CODE_TTL = 300
_PHONE_CODE_COOLDOWN = 60
_PHONE_CODE_MAX_ATTEMPTS = 5   # 单个验证码最多校验尝试次数,超过即作废(防 6 位码被暴力枚举)
_SEND_IP_MAX = 30
_SEND_IP_WINDOW = 3600


def _sms_pe(s):
    return quote(str(s), safe="~").replace("+", "%20").replace("*", "%2A").replace("%7E", "~")


def aliyun_send_sms(phone, template_code, template_param):
    """阿里云短信 POP RPC v1 签名(HMAC-SHA1),不依赖 SDK。返回 (ok, message)。"""
    import base64 as _b64
    ak = SMS_CFG.get("access_key_id") or ""
    sk = SMS_CFG.get("access_key_secret") or ""
    sign = SMS_CFG.get("sign_name") or ""
    if not (ak and sk and sign):
        return False, "短信服务未配置"
    params = {
        "AccessKeyId": ak, "Action": "SendSms", "Format": "JSON", "RegionId": "cn-hangzhou",
        "SignatureMethod": "HMAC-SHA1", "SignatureNonce": uuid.uuid4().hex, "SignatureVersion": "1.0",
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "Version": "2017-05-25",
        "PhoneNumbers": phone, "SignName": sign, "TemplateCode": template_code,
        "TemplateParam": json.dumps(template_param, ensure_ascii=False),
    }
    q = "&".join("%s=%s" % (_sms_pe(k), _sms_pe(params[k])) for k in sorted(params))
    sts = "GET&" + _sms_pe("/") + "&" + _sms_pe(q)
    sig = _b64.b64encode(hmac.new((sk + "&").encode(), sts.encode(), hashlib.sha1).digest()).decode()
    url = "https://dysmsapi.aliyuncs.com/?" + q + "&Signature=" + _sms_pe(sig)
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("Code") == "OK":
            return True, "发送成功"
        return False, data.get("Message") or "短信发送失败"
    except Exception as e:
        return False, "短信请求异常: %s" % str(e)[:100]


def _send_ip_allowed(ip):
    t = now()
    lst = [x for x in _SEND_IP_LOG.get(ip or "", []) if t - x < _SEND_IP_WINDOW]
    if len(lst) >= _SEND_IP_MAX:
        _SEND_IP_LOG[ip or ""] = lst
        return False
    lst.append(t)
    _SEND_IP_LOG[ip or ""] = lst
    return True


def gen_phone_code(phone, scene="login"):
    """生成并暂存验证码;冷却期内返回 (None, 提示)。"""
    import random
    t = now()
    prev = _PHONE_CODES.get(phone)
    if prev and t - float(prev.get("sentAt") or 0) < _PHONE_CODE_COOLDOWN:
        return None, "请 %d 秒后重试" % int(_PHONE_CODE_COOLDOWN - (t - prev["sentAt"]))
    code = "".join(str(random.randint(0, 9)) for _ in range(6))
    _PHONE_CODES[phone] = {"code": code, "expiresAt": t + _PHONE_CODE_TTL, "sentAt": t, "scene": scene}
    return code, None


def verify_phone_code(phone, code, expected_scene=None):
    rec = _PHONE_CODES.get(phone)
    if not rec or now() > float(rec.get("expiresAt") or 0):
        _PHONE_CODES.pop(phone, None)  # 顺手清过期,避免字典膨胀
        return False
    # 限制单码校验尝试次数:任何失败(码错/场景错)都计数,超上限即作废该码,
    # 使 6 位码无法在 5 分钟 TTL 内被暴力枚举(枚举需重发,受 60s 冷却 + 单 IP 发送上限约束)。
    rec["attempts"] = int(rec.get("attempts") or 0) + 1
    if rec["attempts"] > _PHONE_CODE_MAX_ATTEMPTS:
        _PHONE_CODES.pop(phone, None)
        return False
    if str(code or "").strip() != str(rec.get("code")):
        return False
    # 场景绑定:登录码只能用于登录、注册码只能用于注册(防"场景混淆"接管);
    # 不匹配时不消费该码,合法用途仍可核销。expected_scene=None 表示不校验(兼容旧调用如绑定手机)。
    if expected_scene is not None and str(rec.get("scene") or "login") != expected_scene:
        return False
    _PHONE_CODES.pop(phone, None)  # 一次性
    return True


def find_user_by_phone(phone):
    p = str(phone or "").strip()
    if not p:
        return None
    if maindb_on():
        try:
            row = maindb.get_user_by_phone(p)
        except Exception:
            row = None
        return shape_mdb_user(row, "session") if row else None
    with LOCK:
        for u in STATE.get("users") or []:
            if str(u.get("phone") or "").strip() == p:
                return dict(u)
    return None


def create_phone_user(phone):
    """按手机号自动注册:漫剧模式=在主库建 users 行;否则=本地建独立企业+owner+成员关系。"""
    p = str(phone).strip()
    if maindb_on():
        try:
            row = maindb.create_phone_user(p, password=None, signup_bonus=MAINDB_SIGNUP_BONUS)
        except Exception:
            row = None
        return shape_mdb_user(row, "session")
    uid = "user-" + uuid.uuid4().hex[:12]
    oid = "org-" + uuid.uuid4().hex[:12]
    with LOCK:
        STATE.setdefault("organizations", []).append(
            {"id": oid, "name": "用户" + p[-4:] + "的企业", "status": "active", "createdAt": now()})
        bonus = round(float(SIGNUP_BONUS_YUNDOU or 0), 6)
        user = {"id": uid, "name": "用户" + p[-4:], "phone": p, "email": "",
                "status": "active", "balance": bonus if bonus > 0 else 0.0, "phoneVerified": True,
                "createdAt": now(), "updatedAt": now()}
        STATE.setdefault("users", []).append(user)
        STATE.setdefault("memberships", []).append(
            {"id": "m-%s-%s" % (oid, uid), "orgId": oid, "userId": uid,
             "role": "member", "status": "active", "createdAt": now()})
        if bonus > 0:
            _add_ledger(uid, bonus, "注册赠豆", "signup-bonus", user["balance"])
        persist()
    return dict(user)


def get_or_create_phone_user(phone):
    """原子 find-or-create:并发同号请求不会建重复用户/企业(RLock 可重入)。"""
    p = str(phone or "").strip()
    if maindb_on():
        try:
            row = maindb.get_user_by_phone(p) or maindb.create_phone_user(p, password=None, signup_bonus=MAINDB_SIGNUP_BONUS)
        except Exception:
            row = None
        return shape_mdb_user(row, "session")
    with LOCK:
        for u in STATE.get("users") or []:
            if str(u.get("phone") or "").strip() == p:
                return dict(u)
        return create_phone_user(p)


# ============ 余额 / 计费框架(单价规则留空,等业务方定) ============
BILLING_CAPABILITY_PRICES_YUNDOU = {
    "product_image": 14,
    "product_video": 308,
    "copywriting": 7,
    "viral_image": 21,
    "digital_human": 2520,
    "digital_human_pro": 5040,
    "mix": 14,
    "workflow_image": 14,
    "workflow_video": 2520,
    "workflow_tts": 21,
}

LK888_PROXY_CHARGED_CAPABILITIES = {
    "product_image", "product_video", "viral_image", "digital_human", "digital_human_pro",
    "workflow_image", "workflow_video", "workflow_tts",
}


def _capability_key(value):
    return str(value or "").strip().lower().replace("-", "_")


def capability_price_yundou(capability, requested_amount=None):
    cap = _capability_key(capability)
    if cap in BILLING_CAPABILITY_PRICES_YUNDOU:
        return float(BILLING_CAPABILITY_PRICES_YUNDOU[cap]), cap
    try:
        amount = round(float(requested_amount or 0), 6)
    except Exception:
        return None, cap
    return amount, cap


def maindb_power_from_yundou(yundou_amount):
    return round(float(yundou_amount or 0) / 100.0 * MAINDB_YUAN_TO_POWER, 6)


def get_balance(user_id):
    if maindb_on() and isinstance(user_id, int):
        try:
            return round(float(maindb.get_balance(user_id)), 6)
        except Exception:
            return 0.0
    with LOCK:
        u = next((x for x in STATE.get("users") or [] if x.get("id") == user_id), None)
    return round(float((u or {}).get("balance") or 0.0), 6)


def _add_ledger(user_id, delta, reason, ref, balance_after):
    item = {"id": uuid.uuid4().hex, "userId": user_id, "delta": round(float(delta), 6),
            "balanceAfter": round(float(balance_after), 6), "reason": reason or "", "ref": ref or "", "ts": now()}
    STATE.setdefault("ledger", []).append(item)
    STATE["ledger"] = STATE["ledger"][-8000:]
    return item


def charge_user(user_id, amount, reason="生成", ref=""):
    """扣费。owner(运营方)免扣不限量;普通用户余额不足返回 ok=False。返回 (ok, balance_after, error)。"""
    try:
        amount = round(float(amount or 0), 6)
    except Exception:
        return False, 0.0, "amount_invalid"
    if user_id == "user-owner":
        return True, float("inf"), None  # 运营方账号不计费
    if maindb_on() and isinstance(user_id, int):
        # 漫剧算力:原子条件扣费(余额足才扣)
        if amount <= 0:
            return True, get_balance(user_id), None
        try:
            conn = maindb._conn()
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET computing_power = computing_power - %s, updated_at=NOW() "
                            "WHERE id=%s AND computing_power >= %s", (str(amount), int(user_id), str(amount)))
                if cur.rowcount != 1:
                    return False, get_balance(user_id), "insufficient_balance"
            return True, get_balance(user_id), None
        except Exception as e:
            return False, get_balance(user_id), str(e)[:80]
    with LOCK:
        u = next((x for x in STATE.get("users") or [] if x.get("id") == user_id), None)
        if not u:
            return False, 0.0, "user_not_found"
        bal = float(u.get("balance") or 0.0)
        if amount > 0 and bal < amount:
            return False, bal, "insufficient_balance"
        u["balance"] = round(bal - amount, 6)
        u["updatedAt"] = now()
        _add_ledger(user_id, -amount, reason, ref, u["balance"])
        persist()
        return True, u["balance"], None


def _add_maindb_generic_ledger(user_id, amount, yundou_amount, reason, ref, balance_after):
    item = _add_ledger(user_id, -amount, reason, ref, balance_after)
    item["wallet"] = "maindb_generic"
    item["yundouAmount"] = round(float(yundou_amount or 0), 6)
    return item


def charge_capability_user(user_id, capability="", requested_amount=None, ref=""):
    """Charge a business capability with server-owned pricing."""
    amount_yundou, cap = capability_price_yundou(capability, requested_amount)
    if amount_yundou is None:
        return False, get_balance(user_id), "amount_invalid"
    reason = cap or "生成"
    if cap in LK888_PROXY_CHARGED_CAPABILITIES:
        return True, get_balance(user_id), None
    if user_id == "user-owner":
        return True, float("inf"), None
    if maindb_on() and isinstance(user_id, int):
        amount_power = maindb_power_from_yundou(amount_yundou)
        if amount_power <= 0:
            return True, get_balance(user_id), None
        try:
            conn = maindb._conn()
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET computing_power = computing_power - %s, updated_at=NOW() "
                            "WHERE id=%s AND computing_power >= %s",
                            (str(amount_power), int(user_id), str(amount_power)))
                if cur.rowcount != 1:
                    return False, get_balance(user_id), "insufficient_balance"
            bal = get_balance(user_id)
            with LOCK:
                _add_maindb_generic_ledger(user_id, amount_power, amount_yundou, reason, ref, bal)
                persist()
            return True, bal, None
        except Exception as e:
            return False, get_balance(user_id), str(e)[:80]
    return charge_user(user_id, amount_yundou, reason=reason, ref=ref)


def topup_user(user_id, amount, reason="充值", ref=""):
    try:
        amount = round(float(amount or 0), 6)
    except Exception:
        return False, 0.0, "amount_invalid"
    if maindb_on() and isinstance(user_id, int):
        try:
            ok, bal = maindb.topup(user_id, amount, reason)
            return (True, round(float(bal), 6), None) if ok else (False, round(float(bal), 6), "topup_failed")
        except Exception as e:
            return False, get_balance(user_id), str(e)[:80]
    with LOCK:
        u = next((x for x in STATE.get("users") or [] if x.get("id") == user_id), None)
        if not u:
            return False, 0.0, "user_not_found"
        u["balance"] = round(float(u.get("balance") or 0.0) + amount, 6)
        u["updatedAt"] = now()
        _add_ledger(user_id, amount, reason, ref, u["balance"])
        persist()
        return True, u["balance"], None


def refund_user_by_ref(user_id, ref):
    """按扣费 ref 退款:只退该用户名下、该 ref、真实扣过费(delta<0)且未退过的最近一笔,
    退回精确金额并把原扣费标记 refunded=True(幂等,防重复退)。找不到可退的扣费即视为成功退 0
    (例如单价=0 时压根没扣费)。返回 (ok, balance_after, refunded_amount, error)。
    —— 关键:客户端只能触发『退回一笔真实发生过的扣费』,无法凭空充值,杜绝白嫖余额。"""
    if not ref:
        return True, None, 0.0, None
    if user_id == "user-owner":
        return True, float("inf"), 0.0, None  # 运营方本就免扣
    if maindb_on() and isinstance(user_id, int):
        entry = None
        with LOCK:
            for it in reversed(STATE.get("ledger") or []):
                if (it.get("userId") == user_id and it.get("ref") == ref
                        and it.get("wallet") == "maindb_generic"
                        and float(it.get("delta") or 0) < 0
                        and not it.get("refunded") and not it.get("refundPending")):
                    entry = it
                    entry["refundPending"] = True
                    break
        if entry is not None:
            amt = round(-float(entry.get("delta") or 0), 6)
            try:
                ok, bal = maindb.topup(user_id, amt, "matrixship 通用扣费退款 " + str(ref))
                if not ok:
                    with LOCK:
                        entry.pop("refundPending", None)
                    return False, get_balance(user_id), 0.0, "topup_failed"
                bal = round(float(bal), 6)
            except Exception as e:
                with LOCK:
                    entry.pop("refundPending", None)
                return False, get_balance(user_id), 0.0, str(e)[:80]
            with LOCK:
                entry["refunded"] = True
                entry.pop("refundPending", None)
                item = _add_ledger(user_id, amt, "退款:" + (entry.get("reason") or ""), ref, bal)
                item["wallet"] = "maindb_generic"
                persist()
            return True, bal, amt, None
        with LOCK:
            refunded = any(
                it.get("userId") == user_id and it.get("ref") == ref
                and it.get("wallet") == "maindb_generic"
                and float(it.get("delta") or 0) < 0 and it.get("refunded")
                for it in reversed(STATE.get("ledger") or [])
            )
        if refunded:
            return True, get_balance(user_id), 0.0, None
    if maindb_on() and isinstance(user_id, int):
        # 漫剧模式:按 request_id 退 model_usage_logs(幂等)
        try:
            ok, amt = maindb.refund_generation(ref, "matrixship 退款")
            return True, get_balance(user_id), round(float(amt or 0), 6), None
        except Exception as e:
            return False, get_balance(user_id), 0.0, str(e)[:80]
    with LOCK:
        u = next((x for x in STATE.get("users") or [] if x.get("id") == user_id), None)
        if not u:
            return False, 0.0, 0.0, "user_not_found"
        entry = None
        for it in reversed(STATE.get("ledger") or []):
            if (it.get("userId") == user_id and it.get("ref") == ref
                    and float(it.get("delta") or 0) < 0 and not it.get("refunded")):
                entry = it
                break
        if entry is None:
            return True, round(float(u.get("balance") or 0.0), 6), 0.0, None
        amt = round(-float(entry.get("delta") or 0), 6)
        u["balance"] = round(float(u.get("balance") or 0.0) + amt, 6)
        u["updatedAt"] = now()
        entry["refunded"] = True
        _add_ledger(user_id, amt, "退款:" + (entry.get("reason") or ""), ref, u["balance"])
        persist()
        return True, u["balance"], amt, None


# ============ 兑换码充值(自助充值通道:管理员批量生成 → 用户兑换入账) ============
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 去掉易混字符 0/O/1/I/L


def _normalize_code(code):
    """规整兑换码:大写、只留字母数字(容忍用户输入的空格/连字符)。"""
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def _format_code(code):
    """显示用:每 4 位一组用连字符分隔,如 MXA3-F9K2-M7P8-QRST。"""
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def _new_code():
    import secrets
    return "MX" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(14))  # 16 位 → 4 组


def gen_redeem_codes(count, amount, note="", created_by=""):
    """批量生成兑换码(管理员)。每张面值 amount 云豆,状态 active。返回 (ok, [显示码...], error)。"""
    try:
        count = int(count)
        amount = round(float(amount), 6)
    except Exception:
        return False, [], "invalid_params"
    if count < 1 or count > 2000:
        return False, [], "count_out_of_range"  # 单批 1..2000
    if amount <= 0:
        return False, [], "amount_must_be_positive"
    with LOCK:
        existing = {c.get("code") for c in STATE.get("redeem_codes") or []}
        batch = "rb_" + uuid.uuid4().hex[:10]
        made = []
        for _ in range(count):
            code = _new_code()
            while code in existing:
                code = _new_code()
            existing.add(code)
            item = {"code": code, "display": _format_code(code), "amount": amount,
                    "batchId": batch, "status": "active", "note": note or "",
                    "createdBy": created_by or "", "createdAt": now(),
                    "usedBy": None, "usedAt": None}
            STATE.setdefault("redeem_codes", []).append(item)
            made.append(item["display"])
        STATE["redeem_codes"] = STATE["redeem_codes"][-50000:]
        persist()
    return True, made, None


# ===================== 微信支付 v3(Native 扫码充值云豆) =====================
# 移植自 ai-education-platform 的 wechatpay_v3(直连商户 / Native)。用 urllib + cryptography;
# 到账确认走「轮询订单状态」query_by_out_trade_no(中心服是 HTTP,无需公网 HTTPS 回调)。
# 复用漫剧同一微信商户(商户号见 env);1 元 = 100 云豆(= 支付分数)。配置全走 env(systemd drop-in)。
WXPAY_API_BASE = "https://api.mch.weixin.qq.com"
RECHARGE_PACKAGES = [
    {"id": "p6", "yuan": 6, "yundou": 600}, {"id": "p30", "yuan": 30, "yundou": 3000},
    {"id": "p68", "yuan": 68, "yundou": 6800}, {"id": "p128", "yuan": 128, "yundou": 12800},
    {"id": "p298", "yuan": 298, "yundou": 29800}, {"id": "p648", "yuan": 648, "yundou": 64800},
]
RECHARGE_MIN_FEN = 100        # 1 元
RECHARGE_MAX_FEN = 500000     # 5000 元


class WechatPayV3:
    def __init__(self):
        self.appid = (os.getenv("WECHAT_PAY_APPID") or "").strip()
        self.mchid = (os.getenv("WECHAT_PAY_MCHID") or "").strip()
        self.apiv3_key = (os.getenv("WECHAT_PAY_API_V3_KEY") or "").strip()
        self.cert_serial = (os.getenv("WECHAT_PAY_CERT_SERIAL") or "").strip()
        self.private_key_path = (os.getenv("WECHAT_PAY_PRIVATE_KEY_PATH") or "").strip()
        self.notify_url = (os.getenv("WECHAT_PAY_NOTIFY_URL") or "").strip()
        self._pk = None

    @property
    def configured(self):
        return bool(self.appid and self.mchid and self.apiv3_key and self.cert_serial
                    and self.private_key_path and self.notify_url)

    def _load_key(self):
        if self._pk is None:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            with open(self.private_key_path, "rb") as f:
                self._pk = load_pem_private_key(f.read(), password=None)
        return self._pk

    def _sign(self, message):
        import base64
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        sig = self._load_key().sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        return base64.b64encode(sig).decode("utf-8")

    def _auth(self, method, url_path, body):
        nonce = uuid.uuid4().hex.upper()
        ts = str(int(time.time()))
        msg = "%s\n%s\n%s\n%s\n%s\n" % (method, url_path, ts, nonce, body)
        return ('WECHATPAY2-SHA256-RSA2048 mchid="%s",nonce_str="%s",signature="%s",timestamp="%s",serial_no="%s"'
                % (self.mchid, nonce, self._sign(msg), ts, self.cert_serial))

    def _request(self, method, url_path, body_obj=None):
        body = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":")) if body_obj is not None else ""
        headers = {"Authorization": self._auth(method, url_path, body),
                   "Accept": "application/json", "User-Agent": "matrixship-wxpay/1.0"}
        data = None
        if body:
            headers["Content-Type"] = "application/json"
            data = body.encode("utf-8")
        req = urllib.request.Request(WXPAY_API_BASE + url_path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read().decode("utf-8")
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "ignore")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"_raw": raw}

    def native_prepay(self, out_trade_no, description, amount_fen, attach=None):
        """返回 code_url(前端渲染二维码)。"""
        body = {"appid": self.appid, "mchid": self.mchid, "description": description,
                "out_trade_no": out_trade_no, "notify_url": self.notify_url,
                "amount": {"total": int(amount_fen), "currency": "CNY"}}
        if attach:
            body["attach"] = attach
        code, data = self._request("POST", "/v3/pay/transactions/native", body)
        if code == 200 and data.get("code_url"):
            return data["code_url"]
        raise RuntimeError((data or {}).get("message") or ("微信下单失败 http_%s" % code))

    def query(self, out_trade_no):
        url_path = "/v3/pay/transactions/out-trade-no/%s?mchid=%s" % (out_trade_no, self.mchid)
        code, data = self._request("GET", url_path, None)
        if code == 200:
            return data
        raise RuntimeError((data or {}).get("message") or ("查询失败 http_%s" % code))


_WXPAY = None


def wxpay():
    global _WXPAY
    if _WXPAY is None:
        _WXPAY = WechatPayV3()
    return _WXPAY


def create_recharge_order(user_id, amount_fen):
    """创建云豆充值订单并向微信 Native 下单。amount_fen=支付分数;云豆=分数(1元=100分=100云豆)。
    返回 (ok, order_dict, error)。"""
    try:
        amount_fen = int(amount_fen)
    except Exception:
        return False, None, "金额无效"
    if amount_fen < RECHARGE_MIN_FEN or amount_fen > RECHARGE_MAX_FEN:
        return False, None, "金额需在 1~5000 元之间"
    if user_id == "user-owner":
        return False, None, "运营方账号无需充值"
    wx = wxpay()
    if not wx.configured:
        return False, None, "微信支付未配置(缺 " + ",".join(
            k for k, v in [("APPID", wx.appid), ("MCHID", wx.mchid), ("APIv3KEY", wx.apiv3_key),
                           ("CERT_SERIAL", wx.cert_serial), ("PRIVATE_KEY", wx.private_key_path),
                           ("NOTIFY_URL", wx.notify_url)] if not v) + ")"
    # 漫剧模式:入账**算力**(1元=MAINDB_YUAN_TO_POWER 算力,默认 10);否则旧云豆(1元=100)
    _mdb_mode = maindb_on() and isinstance(user_id, int)
    if _mdb_mode:
        credit = round(amount_fen / 100.0 * MAINDB_YUAN_TO_POWER, 6)  # 算力
        unit = "算力"
    else:
        credit = amount_fen  # 1 分 = 1 云豆
        unit = "云豆"
    yundou = credit  # 兼容旧字段(前端读 yundou 展示到账数)
    order_no = "MSHIP" + time.strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:8].upper()
    desc = "矩阵星舰%s充值 %.2f元" % (unit, amount_fen / 100.0)
    try:
        code_url = wx.native_prepay(order_no, desc, amount_fen, attach="matrixship:%s" % user_id)
    except Exception as e:
        return False, None, str(e)
    item = {"orderNo": order_no, "userId": user_id, "amountFen": amount_fen, "yundou": yundou,
            "credit": credit, "currency": ("power" if _mdb_mode else "yundou"), "unit": unit,
            "status": "NOTPAY", "codeUrl": code_url, "createdAt": now(), "paidAt": None,
            "credited": False, "transactionId": None}
    with LOCK:
        STATE.setdefault("recharge_orders", []).append(item)
        STATE["recharge_orders"] = STATE["recharge_orders"][-20000:]
        persist()
    return True, item, None


def poll_recharge_order(user_id, order_no):
    """查询订单并在支付成功时给用户入账云豆(credited 标志 + LOCK 幂等,重复轮询只入一次)。
    返回 (ok, {status, credited, balance?, yundou?}, error)。"""
    with LOCK:
        o = next((x for x in STATE.get("recharge_orders") or [] if x.get("orderNo") == order_no), None)
        if not o:
            return False, None, "order_not_found"
        if o.get("userId") != user_id:
            return False, None, "forbidden"
        if o.get("credited"):
            return True, {"status": "SUCCESS", "credited": True,
                          "balance": get_balance(user_id), "yundou": o.get("yundou")}, None
    try:
        data = wxpay().query(order_no)
    except Exception as e:
        return False, None, str(e)
    state = data.get("trade_state") or "NOTPAY"
    if state == "SUCCESS":
        with LOCK:
            o = next((x for x in STATE.get("recharge_orders") or [] if x.get("orderNo") == order_no), None)
            if o and not o.get("credited"):
                _credit = float(o.get("credit") if o.get("credit") is not None else o.get("yundou") or 0)
                if maindb_on() and isinstance(user_id, int):
                    # 入账到漫剧算力(computing_power);STATE 只留订单+credited 标志做幂等
                    try:
                        maindb.topup(user_id, _credit, "微信充值 " + order_no)
                    except Exception:
                        pass
                    o["status"] = "SUCCESS"; o["credited"] = True; o["paidAt"] = now()
                    o["transactionId"] = data.get("transaction_id")
                    persist()
                else:
                    u = next((x for x in STATE.get("users") or [] if x.get("id") == user_id), None)
                    if u:
                        u["balance"] = round(float(u.get("balance") or 0.0) + _credit, 6)
                        u["updatedAt"] = now()
                        o["status"] = "SUCCESS"; o["credited"] = True; o["paidAt"] = now()
                        o["transactionId"] = data.get("transaction_id")
                        _add_ledger(user_id, _credit, "微信充值", "wxpay:" + order_no, u["balance"])
                        persist()
        return True, {"status": "SUCCESS", "credited": True,
                      "balance": get_balance(user_id), "yundou": (o or {}).get("yundou")}, None
    with LOCK:
        o = next((x for x in STATE.get("recharge_orders") or [] if x.get("orderNo") == order_no), None)
        if o:
            o["status"] = state
    return True, {"status": state, "credited": False}, None


def redeem_code(user_id, code):
    """用户兑换:原子核销一张 active 兑换码并给该用户入账(全程持锁,防并发双兑;不调用 topup_user
    以避免非重入 LOCK 死锁,入账逻辑内联)。返回 (ok, balance_after, amount, error)。"""
    norm = _normalize_code(code)
    if not norm:
        return False, None, 0.0, "code_empty"
    with LOCK:
        rc = next((c for c in STATE.get("redeem_codes") or [] if c.get("code") == norm), None)
        if rc is None:
            return False, None, 0.0, "code_not_found"
        if rc.get("status") == "used":
            return False, None, 0.0, "code_used"
        if rc.get("status") == "void":
            return False, None, 0.0, "code_void"
        amount = round(float(rc.get("amount") or 0), 6)
        # 漫剧模式:核销后把额度加到漫剧算力
        if maindb_on() and isinstance(user_id, int):
            rc["status"] = "used"
            rc["usedBy"] = user_id
            rc["usedAt"] = now()
            persist()
            try:
                _ok, _bal = maindb.topup(user_id, amount, "兑换码充值 " + norm)
                return True, round(float(_bal), 6), amount, None
            except Exception:
                return True, get_balance(user_id), amount, None
        u = next((x for x in STATE.get("users") or [] if x.get("id") == user_id), None)
        if not u:
            return False, None, 0.0, "user_not_found"
        rc["status"] = "used"
        rc["usedBy"] = user_id
        rc["usedAt"] = now()
        u["balance"] = round(float(u.get("balance") or 0.0) + amount, 6)
        u["updatedAt"] = now()
        _add_ledger(user_id, amount, "兑换码充值", "redeem:" + norm, u["balance"])
        persist()
        return True, u["balance"], amount, None


def void_redeem_code(code):
    """作废一张未使用的兑换码(管理员)。已使用的不可作废。返回 (ok, error)。"""
    norm = _normalize_code(code)
    with LOCK:
        rc = next((c for c in STATE.get("redeem_codes") or [] if c.get("code") == norm), None)
        if rc is None:
            return False, "code_not_found"
        if rc.get("status") == "used":
            return False, "code_used"
        rc["status"] = "void"
        rc["updatedAt"] = now()
        persist()
    return True, None


def list_redeem_codes(limit=200):
    """列出最近的兑换码及汇总(管理员)。"""
    with LOCK:
        codes = list(STATE.get("redeem_codes") or [])
    total = len(codes)
    active = sum(1 for c in codes if c.get("status") == "active")
    used = sum(1 for c in codes if c.get("status") == "used")
    void = sum(1 for c in codes if c.get("status") == "void")
    recent = [{"display": c.get("display"), "amount": c.get("amount"), "status": c.get("status"),
               "note": c.get("note"), "batchId": c.get("batchId"), "createdAt": c.get("createdAt"),
               "usedBy": c.get("usedBy"), "usedAt": c.get("usedAt")}
              for c in codes[-int(limit):][::-1]]
    return {"total": total, "active": active, "used": used, "void": void, "codes": recent}


def revoke_user_session(token):
    if not token:
        return False
    with LOCK:
        before = len(STATE.setdefault("sessions", []))
        STATE["sessions"] = [s for s in STATE.get("sessions") or [] if s.get("token") != token]
        changed = len(STATE["sessions"]) != before
        if changed:
            persist()
    return changed


def refresh_user_session(token):
    token = (token or "").strip()
    if not token:
        return None
    ts = now()
    found = None
    with LOCK:
        sessions = []
        changed = False
        for s in STATE.setdefault("sessions", []):
            if float(s.get("expiresAt") or 0) <= ts:
                changed = True
                continue
            if s.get("token") == token:
                s = dict(s)
                s["expiresAt"] = ts + SESSION_TTL_SEC
                s["refreshedAt"] = ts
                found = dict(s)
                changed = True
            sessions.append(s)
        if changed:
            STATE["sessions"] = sessions[-500:]
            persist()
    return found


def user_session_by_token(token):
    token = (token or "").strip()
    if not token:
        return None
    ts = now()
    with LOCK:
        for s in STATE.setdefault("sessions", []):
            if s.get("token") == token and float(s.get("expiresAt") or 0) > ts:
                return dict(s)
    return None


def public_auth_session(session, current_session_id=""):
    session = dict(session or {})
    meta = session.get("meta") if isinstance(session.get("meta"), dict) else {}
    ua = str(meta.get("userAgent") or "")
    exp = float(session.get("expiresAt") or 0)
    return {
        "id": session.get("id") or "",
        "current": bool(current_session_id and session.get("id") == current_session_id),
        "createdAt": session.get("createdAt"),
        "refreshedAt": session.get("refreshedAt"),
        "expiresAt": session.get("expiresAt"),
        "expiresInSec": max(0, int(exp - now())) if exp else 0,
        "sessionTtlSec": int(SESSION_TTL_SEC),
        "ip": meta.get("ip") or "",
        "userAgent": ua[:160],
    }


def list_authenticated_user_sessions(user):
    if not user:
        return {"ok": False, "error": "not_authenticated"}, 401
    if user.get("_authType") != "session":
        return {"ok": False, "error": "session_login_required"}, 403
    user_id = user.get("id")
    if isinstance(user_id, str):
        user_id = user_id.strip()
    current_session_id = user.get("_sessionId") or ""
    ts = now()
    with LOCK:
        rows = [dict(s) for s in (STATE.get("sessions") or []) if s.get("userId") == user_id and float(s.get("expiresAt") or 0) > ts]
    items = [public_auth_session(s, current_session_id) for s in sorted(rows, key=lambda x: float(x.get("refreshedAt") or x.get("createdAt") or 0), reverse=True)]
    return {"ok": True, "items": items, "total": len(items), "currentSessionId": current_session_id}, 200


def revoke_authenticated_user_other_sessions(user):
    if not user:
        return {"ok": False, "error": "not_authenticated"}, 401
    if user.get("_authType") != "session":
        return {"ok": False, "error": "session_login_required"}, 403
    user_id = user.get("id")
    if isinstance(user_id, str):
        user_id = user_id.strip()
    current_session_id = user.get("_sessionId") or ""
    revoked = 0
    with LOCK:
        kept = []
        for s in STATE.setdefault("sessions", []):
            if s.get("userId") == user_id and s.get("id") != current_session_id:
                revoked += 1
                continue
            kept.append(s)
        STATE["sessions"] = kept[-500:]
        if revoked:
            persist()
    payload, _ = list_authenticated_user_sessions(user)
    if not payload.get("ok"):
        payload = {"items": [], "total": 0}
    return {"ok": True, "revokedSessions": revoked, "items": payload.get("items") or [], "total": payload.get("total") or 0}, 200


def change_authenticated_user_password(user, current_password, new_password, keep_session_id=""):
    if not user:
        return {"ok": False, "error": "not_authenticated"}, 401
    if user.get("_authType") != "session":
        return {"ok": False, "error": "session_login_required"}, 403
    user_id = user.get("id")
    if isinstance(user_id, str):
        user_id = user_id.strip()
    current_password = current_password or ""
    new_password = (new_password or "").strip()
    if user_id in (None, ""):
        return {"ok": False, "error": "user_not_found"}, 404
    if not current_password:
        return {"ok": False, "error": "missing_current_password"}, 400
    if len(new_password) < 8:
        return {"ok": False, "error": "new_password_too_short", "minLength": 8}, 400
    ts = now()
    revoked = 0
    if is_maindb_user(user):
        try:
            actual = shape_mdb_user(maindb.get_user_by_id(user_id), "session", keep_session_id)
        except Exception:
            actual = None
        if not actual or actual.get("status") != "active":
            return {"ok": False, "error": "user_not_found"}, 404
        if not verify_user_password(actual, current_password):
            return {"ok": False, "error": "current_password_invalid"}, 403
        set_user_password(actual, new_password)
        try:
            actual = shape_mdb_user(maindb.get_user_by_id(user_id), "session", keep_session_id) or actual
        except Exception:
            pass
        with LOCK:
            kept = []
            for s in STATE.setdefault("sessions", []):
                if s.get("userId") == user_id and s.get("id") != keep_session_id:
                    revoked += 1
                    continue
                kept.append(s)
            STATE["sessions"] = kept[-500:]
            persist()
        return {"ok": True, "user": public_user(actual), "revokedSessions": revoked, "changedAt": ts}, 200
    with LOCK:
        actual = next((u for u in (STATE.get("users") or []) if u.get("id") == user_id and u.get("status", "active") == "active"), None)
        if not actual:
            return {"ok": False, "error": "user_not_found"}, 404
        if not verify_user_password(actual, current_password):
            return {"ok": False, "error": "current_password_invalid"}, 403
        set_user_password(actual, new_password)
        actual["passwordChangeRequired"] = False
        actual["passwordChangedAt"] = ts
        actual["updatedAt"] = ts
        kept = []
        for s in STATE.setdefault("sessions", []):
            if s.get("userId") == user_id and s.get("id") != keep_session_id:
                revoked += 1
                continue
            kept.append(s)
        STATE["sessions"] = kept[-500:]
        persist()
        out_user = public_user(actual)
    return {"ok": True, "user": out_user, "revokedSessions": revoked, "changedAt": ts}, 200


ROLE_RANK = {"auditor": 1, "member": 2, "admin": 3, "owner": 4}
PRODUCT_ROLE_PLATFORM_ADMIN = "platform_admin"
PRODUCT_ROLE_ENTERPRISE_ADMIN = "enterprise_admin"
PRODUCT_ROLE_NORMAL_USER = "normal_user"


def product_role_for_user(user, org_id=None):
    if not user:
        return PRODUCT_ROLE_NORMAL_USER
    if user.get("_authType") == "root-token" or user.get("id") == "user-owner" or user.get("isPlatformAdmin"):
        return PRODUCT_ROLE_PLATFORM_ADMIN
    memberships = [m for m in user_memberships(user) if m.get("status", "active") == "active"]
    org_id = normalize_org_id(org_id) if org_id and org_id != "*" else org_id
    for m in memberships:
        if org_id not in (None, "*") and normalize_org_id(m.get("orgId")) != org_id:
            continue
        if (m.get("role") or "member") in ("owner", "admin"):
            return PRODUCT_ROLE_ENTERPRISE_ADMIN
    return PRODUCT_ROLE_NORMAL_USER


def product_role_for_handler(handler, org_id=None):
    return product_role_for_user(current_user(handler), org_id)


def auth_context_for_user(user, auth_type=None):
    orgs = user_orgs(user.get("id"), user) if user else []
    primary_org = normalize_org_id((orgs[0] or {}).get("id")) if orgs else DEFAULT_ORG_ID
    app_role = product_role_for_user(user, primary_org)
    return {
        "organizations": orgs,
        "memberships": user_memberships(user) if user else [],
        "appRole": app_role,
        "productRole": app_role,
        "roleScope": "all" if app_role == PRODUCT_ROLE_PLATFORM_ADMIN else ("org" if app_role == PRODUCT_ROLE_ENTERPRISE_ADMIN else "self"),
        "authType": auth_type if auth_type is not None else (user or {}).get("_authType"),
    }


def item_owner_user_id(item):
    item = item if isinstance(item, dict) else {}
    for key in ("ownerUserId", "createdByUserId", "createdBy", "userId", "actorUserId"):
        value = item.get(key)
        if value not in (None, ""):
            return value
    body = item.get("body") if isinstance(item.get("body"), dict) else {}
    for key in ("ownerUserId", "createdByUserId", "createdBy", "userId", "actorUserId"):
        value = body.get(key)
        if value not in (None, ""):
            return value
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    for key in ("ownerUserId", "createdByUserId", "createdBy", "userId", "actorUserId", "ownerId"):
        value = meta.get(key)
        if value not in (None, ""):
            return value
    return ""


def item_visible_to_user(item, user, org_id=None):
    role = product_role_for_user(user, org_id)
    if role in (PRODUCT_ROLE_PLATFORM_ADMIN, PRODUCT_ROLE_ENTERPRISE_ADMIN):
        return True
    if not user:
        return False
    owner_id = item_owner_user_id(item)
    return bool(owner_id not in (None, "") and same_user_id(owner_id, user.get("id")))


def filter_items_for_product_role(items, user, org_id=None):
    role = product_role_for_user(user, org_id)
    if role in (PRODUCT_ROLE_PLATFORM_ADMIN, PRODUCT_ROLE_ENTERPRISE_ADMIN):
        return list(items or [])
    return [x for x in (items or []) if item_visible_to_user(x, user, org_id)]


def has_role(handler, org_id=None, min_role="member"):
    if not USER_TOKEN:
        return True
    user = current_user(handler)
    if not user:
        return False
    if user.get("_authType") == "root-token":
        return True
    need = ROLE_RANK.get(min_role, ROLE_RANK["member"])
    org_id = normalize_org_id(org_id) if org_id and org_id != "*" else org_id
    memberships = [m for m in user_memberships(user) if m.get("status", "active") == "active"]
    for m in memberships:
        if org_id not in (None, "*") and normalize_org_id(m.get("orgId")) != org_id:
            continue
        if ROLE_RANK.get(m.get("role") or "member", 0) >= need:
            return True
    return False


def require_role(handler, org_id=None, min_role="member"):
    if has_role(handler, org_id, min_role):
        return True
    json_response(handler, {"ok": False, "error": "permission_denied", "requiredRole": min_role, "orgId": normalize_org_id(org_id) if org_id and org_id != "*" else org_id}, 403)
    return False


def is_platform_admin(handler):
    """平台级管理员判定(运营方)。修复历史漏洞:此前平台管理端点用 require_role(*,'admin'),
    而『*』= 在任意组织里是 admin+;但每个手机用户都是自己隔离 org 的 owner,于是普通用户
    也能命中,从而可越权(如给自己充值/列全部用户)。平台管理必须限定为:root-token /
    运营方 owner 账号(user-owner)/ 显式 isPlatformAdmin。企业 owner/admin 只管本企业。"""
    if not USER_TOKEN:
        return True  # 未设 USER_TOKEN 的纯本地 dev 模式不限制(与 has_role 一致)
    u = current_user(handler)
    if not u:
        return False
    if u.get("_authType") == "root-token" or u.get("id") == "user-owner":
        return True
    if u.get("isPlatformAdmin"):  # 被显式授予平台管理员的普通账号(不改其所属 org/数据隔离)
        return True
    return False


def require_platform_admin(handler):
    if is_platform_admin(handler):
        return True
    json_response(handler, {"ok": False, "error": "permission_denied", "requiredRole": "platform_admin"}, 403)
    return False


def user_authorized(handler):
    if not USER_TOKEN:
        return True
    return current_user(handler) is not None


def require_user(handler):
    if not user_authorized(handler):
        json_response(handler, {"ok": False, "error": "user_token_required"}, 401)
        return False
    return True


def node_settings(node_id):
    node_id = (node_id or "").strip()
    defaults = {"maxConcurrency": 1, "cooldownSec": 0, "paused": False, "note": ""}
    if not node_id:
        return defaults
    with LOCK:
        saved = dict((STATE.setdefault("nodeSettings", {}) or {}).get(node_id) or {})
    try:
        defaults["maxConcurrency"] = max(1, min(10, int(saved.get("maxConcurrency", defaults["maxConcurrency"]) or 1)))
    except Exception:
        defaults["maxConcurrency"] = 1
    try:
        defaults["cooldownSec"] = max(0, min(86400, int(saved.get("cooldownSec", defaults["cooldownSec"]) or 0)))
    except Exception:
        defaults["cooldownSec"] = 0
    defaults["paused"] = bool(saved.get("paused", defaults["paused"]))
    defaults["note"] = str(saved.get("note") or "")[:200]
    return defaults


def node_task_counts(node_id):
    node_id = (node_id or "").strip()
    running = queued = 0
    last_finished = 0.0
    with LOCK:
        for t in (STATE.get("tasks") or {}).values():
            if t.get("nodeId") != node_id:
                continue
            if t.get("status") == "running":
                running += 1
            elif t.get("status") == "queued":
                queued += 1
            last_finished = max(last_finished, float(t.get("finishedAt") or 0), float(t.get("updatedAt") or 0) if t.get("status") in ("done", "failed") else 0)
        raw_node = (STATE.get("nodes") or {}).get(node_id) or {}
        last_finished = max(last_finished, float(raw_node.get("lastFinishedAt") or 0))
    return running, queued, last_finished


def node_capacity_snapshot(node_id):
    cfg = node_settings(node_id)
    running, queued, last_finished = node_task_counts(node_id)
    cooldown_until = (last_finished + cfg["cooldownSec"]) if cfg.get("cooldownSec") else 0
    ts = now()
    if cfg.get("paused"):
        status = "paused"
        reason = "node_paused"
    elif running >= cfg["maxConcurrency"]:
        status = "at_capacity"
        reason = "node_at_capacity"
    elif cooldown_until and cooldown_until > ts:
        status = "cooldown"
        reason = "node_cooling_down"
    else:
        status = "available"
        reason = ""
    return {
        "settings": cfg,
        "maxConcurrency": cfg["maxConcurrency"],
        "cooldownSec": cfg["cooldownSec"],
        "paused": bool(cfg.get("paused")),
        "note": cfg.get("note") or "",
        "running": running,
        "queued": queued,
        "availableSlots": max(0, cfg["maxConcurrency"] - running),
        "lastFinishedAt": last_finished,
        "cooldownUntil": cooldown_until,
        "cooldownRemainingSec": max(0, int(cooldown_until - ts)) if cooldown_until else 0,
        "status": status,
        "reason": reason,
    }


def update_node_capacity(org_id, node_id, body):
    org_id = normalize_org_id(org_id)
    node_id = (node_id or "").strip()
    if not node_id:
        return {"ok": False, "error": "missing_node_id"}, 400
    with LOCK:
        node = (STATE.get("nodes") or {}).get(node_id)
    if not node:
        return {"ok": False, "error": "node_not_found"}, 404
    if item_org_id(node) != org_id:
        return {"ok": False, "error": "node_org_mismatch"}, 403
    cfg = node_settings(node_id)
    if "maxConcurrency" in body:
        try:
            cfg["maxConcurrency"] = max(1, min(10, int(body.get("maxConcurrency") or 1)))
        except Exception:
            return {"ok": False, "error": "invalid_max_concurrency"}, 400
    if "cooldownSec" in body:
        try:
            cfg["cooldownSec"] = max(0, min(86400, int(body.get("cooldownSec") or 0)))
        except Exception:
            return {"ok": False, "error": "invalid_cooldown"}, 400
    if "paused" in body:
        cfg["paused"] = bool(body.get("paused"))
    if "note" in body:
        cfg["note"] = str(body.get("note") or "")[:200]
    with LOCK:
        STATE.setdefault("nodeSettings", {})[node_id] = cfg
        persist()
    return {"ok": True, "orgId": org_id, "nodeId": node_id, "capacity": node_capacity_snapshot(node_id)}, 200


def org_node_capacity(org_id=None):
    org_id = normalize_org_id(org_id)
    with LOCK:
        nodes = [dict(n) for n in (STATE.get("nodes") or {}).values() if item_org_id(n) == org_id]
    rows = []
    for n in nodes:
        cap = node_capacity_snapshot(n.get("id"))
        rows.append({"nodeId": n.get("id"), "name": n.get("name") or n.get("id"), "online": now() - float(n.get("lastSeen") or 0) <= NODE_TIMEOUT_SEC, "capacity": cap})
    counts = {}
    for r in rows:
        st = (r.get("capacity") or {}).get("status") or "unknown"
        counts[st] = counts.get(st, 0) + 1
    return {"ok": True, "orgId": org_id, "nodes": rows, "counts": counts}


def public_node(n):
    last = float(n.get("lastSeen") or 0)
    online = now() - last <= NODE_TIMEOUT_SEC
    return {
        "id": n.get("id"),
        "name": n.get("name") or n.get("id"),
        "orgId": item_org_id(n),
        "region": n.get("region") or "",
        "tags": n.get("tags") or [],
        "online": online,
        "busy": bool(n.get("busy")),
        "lastSeen": last,
        "cookieReady": bool(n.get("cookieReady")),
        "cookieCount": n.get("cookieCount", 0),
        "accountCount": len(n.get("accounts") or []),
        "accounts": n.get("accounts") or [],
        "risk": n.get("risk") or {},
        "stats": n.get("stats") or {},
        "version": n.get("version") or "",
        "localApi": n.get("localApi") or "",
        "capacity": node_capacity_snapshot(n.get("id")),
    }



def _account_capability(key, label, ready, domain='', reason=''):
    return {
        "key": key,
        "label": label,
        "ready": bool(ready),
        "status": "ready" if ready else "needs_auth",
        "domain": domain,
        "reason": reason or ("" if ready else "login_required"),
    }


def infer_account_platform(account_id="", asset=None, platform=""):
    # Infer content platform for customer-facing authorization UX.
    raw = str(platform or "").strip().lower()
    aliases = {
        "xhs": "xhs", "xiaohongshu": "xhs", "rednote": "xhs", "小红书": "xhs",
        "douyin": "douyin", "dy": "douyin", "抖音": "douyin",
    }
    if raw in aliases:
        return aliases[raw]
    asset = asset or {}
    parts = [account_id, asset.get("id"), asset.get("localAccountId"), asset.get("platform"), asset.get("name"), asset.get("handle")]
    hay = " ".join(str(x or "") for x in parts).lower()
    if any(k in hay for k in ("xhs", "xiaohongshu", "rednote", "hongshu", "小红书")):
        return "xhs"
    return "douyin"


def default_account_capabilities(platform="douyin", cookie_ready=False, cookie_count=0):
    platform = infer_account_platform(platform=platform)
    ready = bool(cookie_ready)
    if platform == "xhs":
        items = {
            "search": _account_capability("search", "\u641c\u7d22\u7b14\u8bb0", ready, "xiaohongshu.com"),
            "commentRead": _account_capability("commentRead", "\u67e5\u770b\u8bc4\u8bba", ready, "xiaohongshu.com"),
            "commentWrite": _account_capability("commentWrite", "\u53d1\u9001\u8bc4\u8bba", ready, "xiaohongshu.com"),
            "publish": _account_capability("publish", "\u53d1\u5e03\u7b14\u8bb0", ready, "creator.xiaohongshu.com"),
        }
    else:
        items = {
            "search": _account_capability("search", "\u641c\u7d22\u89c6\u9891", ready, "www.douyin.com"),
            "commentRead": _account_capability("commentRead", "\u67e5\u770b\u8bc4\u8bba", ready, "www.douyin.com"),
            "commentWrite": _account_capability("commentWrite", "\u53d1\u9001\u8bc4\u8bba", ready, "www.douyin.com"),
            "publish": _account_capability("publish", "\u53d1\u5e03\u89c6\u9891", ready, "creator.douyin.com"),
        }
    ready_count = len([x for x in items.values() if x.get("ready")])
    return {
        "profileUnified": True,
        "cookieReady": ready,
        "cookieCount": cookie_count or 0,
        "ready": ready_count == len(items),
        "readyCount": ready_count,
        "total": len(items),
        "items": items,
    }


def normalize_account_capabilities(value, platform="douyin", cookie_ready=False, cookie_count=0):
    if isinstance(value, dict) and isinstance(value.get("items"), dict):
        out = dict(value)
        fallback = default_account_capabilities(platform, cookie_ready, cookie_count).get("items") or {}
        items = {}
        for key in ("search", "commentRead", "commentWrite", "publish"):
            src = out.get("items", {}).get(key) or fallback.get(key) or {}
            items[key] = dict(src)
            fb = fallback.get(key) or {}
            items[key].setdefault("key", key)
            if fb.get("label"):
                items[key]["label"] = fb.get("label")
            if fb.get("domain"):
                items[key]["domain"] = fb.get("domain")
            items[key].setdefault("ready", bool(cookie_ready))
            items[key].setdefault("status", "ready" if items[key].get("ready") else "needs_auth")
        ready_count = len([x for x in items.values() if x.get("ready")])
        out["items"] = items
        out["profileUnified"] = True
        out["cookieReady"] = bool(out.get("cookieReady", cookie_ready))
        out["cookieCount"] = out.get("cookieCount", cookie_count or 0)
        out["readyCount"] = ready_count
        out["total"] = len(items)
        out["ready"] = ready_count == len(items)
        return out
    return default_account_capabilities(platform, cookie_ready, cookie_count)

def sync_node_accounts_locked(node):
    node = node or {}
    node_id = node.get("id") or ""
    if not node_id:
        return
    org_id = item_org_id(node)
    node_online = now() - float(node.get("lastSeen") or 0) <= NODE_TIMEOUT_SEC
    current_ids = set()
    registry = list(STATE.setdefault("accountsRegistry", []))
    by_id = {a.get("id"): dict(a) for a in registry if a.get("id")}
    for raw in node.get("accounts") or []:
        if not isinstance(raw, dict):
            continue
        local_id = str(raw.get("id") or raw.get("name") or "account")
        asset_id = node_id + ":" + local_id
        current_ids.add(asset_id)
        old = by_id.get(asset_id) or {"id": asset_id, "createdAt": now()}
        prev_cookie_ready = bool(old.get("cookieReady"))
        prev_online = bool(old.get("online"))
        raw_cookie_ready = bool(raw.get("cookieReady", node.get("cookieReady")))
        raw_cookie_count = raw.get("cookieCount", node.get("cookieCount", 0))
        raw_platform = raw.get("platform") or "douyin"
        raw_capabilities = normalize_account_capabilities(raw.get("capabilities") or old.get("capabilities"), raw_platform, raw_cookie_ready, raw_cookie_count)
        old.update({
            "id": asset_id,
            "orgId": normalize_org_id(raw.get("orgId") or org_id),
            "platform": raw_platform,
            "localAccountId": local_id,
            "nodeId": node_id,
            "nodeName": node.get("name") or node_id,
            "name": raw.get("name") or raw.get("n") or raw.get("handle") or ("小红书账号" if (raw.get("platform") or "") == "xhs" else "抖音账号"),
            "handle": raw.get("handle") or raw.get("h") or "",
            "fans": raw.get("fans") or "",
            "avatar": raw.get("avatar") or "",
            "cookieReady": raw_cookie_ready,
            "cookieCount": raw_cookie_count,
            "capabilities": raw_capabilities,
            "online": bool(node_online),
            "status": "online" if node_online and raw_cookie_ready else "offline",
            "lastSeen": node.get("lastSeen") or now(),
            "updatedAt": now(),
        })
        if raw_cookie_ready:
            old.setdefault("authorizedAt", old.get("createdAt") or now())
            old["cookieUpdatedAt"] = node.get("lastSeen") or now()
            old.pop("cookieLostAt", None)
        elif prev_cookie_ready or not old.get("cookieLostAt"):
            old["cookieLostAt"] = now()
        if node_online:
            old.pop("offlineSince", None)
        elif prev_online or not old.get("offlineSince"):
            old["offlineSince"] = old.get("lastSeen") or now()
        by_id[asset_id] = old
    for aid, old in list(by_id.items()):
        if old.get("nodeId") == node_id and aid not in current_ids:
            if old.get("online") or not old.get("offlineSince"):
                old["offlineSince"] = old.get("lastSeen") or now()
            old["online"] = False
            old["cookieReady"] = bool(old.get("cookieReady") and node_online)
            if not old.get("cookieReady") and not old.get("cookieLostAt"):
                old["cookieLostAt"] = old.get("updatedAt") or now()
            old["status"] = "offline"
            old["lastSeen"] = node.get("lastSeen") or old.get("lastSeen") or now()
            old["updatedAt"] = now()
            by_id[aid] = old
    STATE["accountsRegistry"] = sorted(by_id.values(), key=lambda x: x.get("updatedAt", 0), reverse=True)



ACCOUNT_REPAIR_SLA_SEC = 4 * 3600
ACCOUNT_REPAIR_WARN_SEC = 60 * 60


def _safe_ts(value, default=0):
    try:
        return float(value or default or 0)
    except Exception:
        return float(default or 0)


def account_repair_sla(asset, ts_now=None):
    ts_now = float(ts_now or now())
    a = dict(asset or {})
    if not a:
        return {
            "state": "unknown",
            "severity": "info",
            "label": "SLA \u5f85\u786e\u8ba4",
            "targetSec": ACCOUNT_REPAIR_SLA_SEC,
            "ageSec": 0,
            "remainingSec": ACCOUNT_REPAIR_SLA_SEC,
            "overdueSec": 0,
            "handoffNote": "\u5148\u5b8c\u6210\u8d26\u53f7\u6388\u6743\uff0c\u518d\u4ea4\u4ed8\u5ba2\u6237\u4f7f\u7528\u3002",
            "ownerRole": "operator",
        }
    online = bool(a.get("online"))
    cookie_ready = bool(a.get("cookieReady"))
    if online and cookie_ready:
        ref = _safe_ts(a.get("cookieUpdatedAt") or a.get("authorizedAt") or a.get("updatedAt") or a.get("createdAt"), ts_now)
        return {
            "state": "healthy",
            "severity": "info",
            "label": "SLA \u6b63\u5e38",
            "targetSec": ACCOUNT_REPAIR_SLA_SEC,
            "ageSec": 0,
            "remainingSec": ACCOUNT_REPAIR_SLA_SEC,
            "overdueSec": 0,
            "since": ref,
            "dueAt": 0,
            "handoffNote": "\u8d26\u53f7\u53ef\u7528\uff0c\u65e0\u9700\u5ba2\u6237\u91cd\u65b0\u6388\u6743\u3002",
            "ownerRole": "operator",
        }
    if not online:
        state = "node_offline"
        since = _safe_ts(a.get("offlineSince") or a.get("lastSeen") or a.get("updatedAt") or a.get("createdAt"), ts_now)
        handoff = "\u6267\u884c\u8282\u70b9\u79bb\u7ebf\uff0c\u5148\u4ea4\u63a5\u7ba1\u7406\u5458\u6062\u590d\u8282\u70b9\u670d\u52a1\uff0c\u518d\u7531\u8fd0\u8425\u786e\u8ba4\u6388\u6743\u3002"
        owner = "admin"
    else:
        state = "cookie_unavailable"
        since = _safe_ts(a.get("cookieLostAt") or a.get("cookieUpdatedAt") or a.get("authorizedAt") or a.get("updatedAt") or a.get("createdAt"), ts_now)
        handoff = "\u767b\u5f55\u6001\u4e0d\u53ef\u7528\uff0c\u4ea4\u63a5\u8fd0\u8425\u901a\u8fc7\u524d\u7aef\u5b8c\u6210\u626b\u7801/\u77ed\u4fe1\u9a8c\u8bc1\u3002"
        owner = "operator"
    age = max(0, ts_now - since)
    due_at = since + ACCOUNT_REPAIR_SLA_SEC
    remaining = max(0, due_at - ts_now)
    overdue = max(0, ts_now - due_at)
    if overdue > 0:
        severity = "critical"
        label = "SLA \u8d85\u65f6"
    elif age >= ACCOUNT_REPAIR_WARN_SEC:
        severity = "warning"
        label = "SLA \u5f85\u4fee\u590d"
    else:
        severity = "info"
        label = "SLA \u89c2\u5bdf"
    return {
        "state": state,
        "severity": severity,
        "label": label,
        "targetSec": ACCOUNT_REPAIR_SLA_SEC,
        "warnSec": ACCOUNT_REPAIR_WARN_SEC,
        "ageSec": round(age, 1),
        "remainingSec": round(remaining, 1),
        "overdueSec": round(overdue, 1),
        "since": since,
        "dueAt": due_at,
        "handoffNote": handoff,
        "ownerRole": owner,
    }


def cloud_login_handoff(status, latest_path="", latest_error="", idle_sec=0):
    status = status or "unknown"
    latest_error = public_error_text(latest_error or "")
    if status == "stale":
        return {"handoffSeverity": "warning", "slaLabel": "\u4f1a\u8bdd\u7591\u4f3c\u5361\u4f4f", "handoffNote": "\u4f1a\u8bdd\u8d85\u8fc7 30 \u5206\u949f\u65e0\u66f4\u65b0\uff0c\u4ea4\u63a5\u7ba1\u7406\u5458\u5f3a\u5236\u5173\u95ed\u540e\u91cd\u65b0\u6388\u6743\u3002"}
    if status == "failed":
        note = "\u6388\u6743\u4efb\u52a1\u5931\u8d25\uff0c\u6838\u5bf9\u9875\u9762\u72b6\u6001\u540e\u91cd\u65b0\u5f00\u59cb\u3002"
        if latest_error:
            note += " \u6700\u8fd1\u9519\u8bef\uff1a" + latest_error
        return {"handoffSeverity": "warning", "slaLabel": "\u9700\u91cd\u8bd5", "handoffNote": note}
    if status in ("running", "active"):
        return {"handoffSeverity": "info", "slaLabel": "\u5ba2\u6237\u64cd\u4f5c\u4e2d", "handoffNote": "\u4fdd\u6301\u5f53\u524d\u6388\u6743\u9875\u9762\uff0c\u5ba2\u6237\u5b8c\u6210\u626b\u7801\u6216\u77ed\u4fe1\u9a8c\u8bc1\u540e\u518d\u70b9\u51fb\u5b8c\u6210\u5e76\u4fdd\u5b58\u3002"}
    if status == "logged_in":
        return {"handoffSeverity": "info", "slaLabel": "\u5df2\u767b\u5f55", "handoffNote": "\u767b\u5f55\u5df2\u68c0\u6d4b\u6210\u529f\uff0c\u5ba2\u670d\u53ef\u901a\u77e5\u5ba2\u6237\u8fd4\u56de\u7cfb\u7edf\u4f7f\u7528\u3002"}
    if status in ("closed", "no_session"):
        return {"handoffSeverity": "info", "slaLabel": "\u53ef\u91cd\u5efa\u4f1a\u8bdd", "handoffNote": "\u5f53\u524d\u65e0\u6709\u6548\u4e91\u7aef\u4f1a\u8bdd\uff0c\u9700\u8981\u65f6\u53ef\u91cd\u65b0\u53d1\u8d77\u6388\u6743\u3002"}
    return {"handoffSeverity": "info", "slaLabel": "\u5f85\u786e\u8ba4", "handoffNote": "\u8bf7\u5237\u65b0\u4f1a\u8bdd\u72b6\u6001\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u91cd\u5efa\u6388\u6743\u3002"}

def public_account_asset(a):
    item = dict(a or {})
    item.setdefault("platform", "douyin")
    item.setdefault("localAccountId", (item.get("id") or "").split(":", 1)[-1])
    item.setdefault("name", "小红书账号" if item.get("platform") == "xhs" else "抖音账号")
    item.setdefault("status", "online" if item.get("online") else "offline")
    item["orgId"] = item_org_id(item)
    item["capabilities"] = normalize_account_capabilities(item.get("capabilities"), item.get("platform") or "douyin", bool(item.get("cookieReady")), item.get("cookieCount", 0))
    item["usable"] = bool(item.get("online") and item.get("cookieReady") and item["capabilities"].get("ready"))
    item["repairSla"] = account_repair_sla(item)
    return item

def delete_account(org_id, account_id):
    """Remove one account row from the matrix (accountsRegistry). Only the central
    record is dropped — the user's local browser login state is untouched. Returns
    (payload, status). Matches by exact asset id (nodeId:localAccountId)."""
    account_id = (account_id or "").strip()
    if not account_id:
        return {"ok": False, "error": "missing_account_id"}, 400
    org_id = normalize_org_id(org_id) if org_id else None
    removed = 0
    with LOCK:
        registry = STATE.setdefault("accountsRegistry", [])
        kept = []
        for a in registry:
            if a.get("id") == account_id and (not org_id or item_org_id(a) == org_id):
                removed += 1
                continue
            kept.append(a)
        if removed:
            STATE["accountsRegistry"] = kept
    if removed:
        persist()
        return {"ok": True, "deleted": account_id, "removed": removed}, 200
    return {"ok": False, "error": "account_not_found", "deleted": account_id}, 404

def find_account_asset(account_id, org_id=None):
    account_id = (account_id or "").strip()
    org_id = normalize_org_id(org_id) if org_id else None
    if not account_id:
        return None
    for a in aggregate_accounts(org_id):
        if a.get("id") == account_id or a.get("localAccountId") == account_id:
            return public_account_asset(a)
    return None


def account_unusable_reason(asset):
    if not asset:
        return "account_not_found"
    if item_org_id(asset) and not asset.get("orgId"):
        return "account_org_invalid"
    if not asset.get("online"):
        return "account_offline"
    if not asset.get("cookieReady"):
        return "account_cookie_unavailable"
    return ""


def account_detail(account_id, org_id=None):
    org_id = normalize_org_id(org_id)
    asset = find_account_asset(account_id, org_id)
    if not asset:
        return None
    node = None
    with LOCK:
        raw_node = (STATE.get("nodes") or {}).get(asset.get("nodeId") or "")
        if raw_node:
            node = public_node(raw_node)
        tasks = [
            dict(t)
            for t in (STATE.get("tasks") or {}).values()
            if item_org_id(t) == org_id and (
                ((t.get("body") or {}).get("centralAccountId") == asset.get("id")) or
                ((t.get("body") or {}).get("accountId") in (asset.get("id"), asset.get("localAccountId")))
            )
        ]
        q = [
            dict(x)
            for x in (STATE.get("queue") or [])
            if item_org_id(x) == org_id and x.get("accountId") == asset.get("id")
        ]
    tasks = sorted(tasks, key=lambda x: x.get("createdAt", 0), reverse=True)[:20]
    q = sorted(q, key=lambda x: x.get("createdAt", 0), reverse=True)[:20]
    diag = auth_diagnosis(org_id, account_id=asset.get("id") or account_id, node_id=asset.get("nodeId") or "")
    support_ref = "authdiag-" + _short_hash(json.dumps({"orgId": org_id, "accountId": asset.get("id"), "nodeId": asset.get("nodeId"), "code": diag.get("code")}, ensure_ascii=False, sort_keys=True))
    next_action = "use_account" if asset.get("usable") else ("repair_node" if diag.get("code") in ("no_online_node", "target_node_offline") else "authorize_account")
    return {
        "ok": True,
        "account": asset,
        "node": node,
        "usable": bool(asset.get("usable")),
        "unusableReason": account_unusable_reason(asset),
        "repairSla": asset.get("repairSla") or account_repair_sla(asset),
        "authorizationStatus": {
            "ready": bool(asset.get("usable")),
            "code": diag.get("code"),
            "severity": diag.get("severity"),
            "summary": diag.get("summary"),
            "suggestions": diag.get("suggestions") or [],
            "handoffNote": diag.get("handoffNote") or "",
            "supportRef": support_ref,
            "nextAction": next_action,
        },
        "authDiagnosis": diag,
        "recentTasks": tasks,
        "queue": q,
    }



def account_authorization_summary(org_id=None):
    org_id = normalize_org_id(org_id)
    accounts = [public_account_asset(a) for a in aggregate_accounts(org_id)]
    counts = {
        "total": len(accounts),
        "ready": 0,
        "needAuth": 0,
        "nodeIssue": 0,
        "inProgress": 0,
        "warning": 0,
        "critical": 0,
    }
    severity_rank = {"critical": 4, "warning": 3, "info": 2, "": 1}
    items = []
    for asset in accounts[:200]:
        diag = auth_diagnosis(org_id, account_id=asset.get("id") or asset.get("localAccountId") or "", node_id=asset.get("nodeId") or "")
        diag = diag if isinstance(diag, dict) else {"ok": False, "code": "diagnosis_unavailable", "severity": "warning", "summary": "Diagnosis unavailable", "suggestions": []}
        code = diag.get("code") or "unknown"
        severity = diag.get("severity") or "info"
        ready = bool(asset.get("usable"))
        if ready:
            counts["ready"] += 1
            next_action = "use_account"
        elif code in ("no_online_node", "target_node_offline") or not asset.get("online"):
            counts["nodeIssue"] += 1
            next_action = "repair_node"
        elif code == "auth_session_in_progress":
            counts["inProgress"] += 1
            next_action = "resume_auth"
        else:
            counts["needAuth"] += 1
            next_action = "authorize_account"
        if severity == "critical":
            counts["critical"] += 1
        elif severity == "warning":
            counts["warning"] += 1
        items.append({
            "accountId": asset.get("id") or "",
            "localAccountId": asset.get("localAccountId") or "",
            "name": asset.get("name") or "Douyin account",
            "handle": asset.get("handle") or "",
            "platform": asset.get("platform") or "douyin",
            "nodeId": asset.get("nodeId") or "",
            "nodeName": asset.get("nodeName") or "",
            "online": bool(asset.get("online")),
            "cookieReady": bool(asset.get("cookieReady")),
            "usable": ready,
            "code": code,
            "severity": severity,
            "summary": diag.get("summary") or "",
            "suggestions": (diag.get("suggestions") or [])[:3],
            "handoffNote": diag.get("handoffNote") or "",
            "nextAction": next_action,
            "repairSla": diag.get("repairSla") or asset.get("repairSla") or account_repair_sla(asset),
            "updatedAt": asset.get("updatedAt") or asset.get("lastSeen") or 0,
            "supportRef": "authsum-" + _short_hash(json.dumps({"orgId": org_id, "accountId": asset.get("id"), "code": code}, ensure_ascii=False, sort_keys=True)),
        })
    items = sorted(items, key=lambda x: (0 if not x.get("usable") else 1, -severity_rank.get(x.get("severity") or "", 0), -(float(x.get("updatedAt") or 0))))
    with LOCK:
        nodes = [public_node(n) for n in (STATE.get("nodes") or {}).values() if item_org_id(n) == org_id]
    online_nodes = len([n for n in nodes if n.get("online")])
    top = items[0] if items else None
    if counts["total"] <= 0:
        status = "empty"
        headline = "No authorized accounts yet"
    elif counts["ready"] > 0 and counts["critical"] == 0 and counts["warning"] == 0:
        status = "healthy"
        headline = "Accounts ready"
    elif counts["critical"] > 0:
        status = "critical"
        headline = "Authorization needs attention"
    elif counts["warning"] > 0 or counts["needAuth"] > 0:
        status = "warning"
        headline = "Some accounts need authorization"
    else:
        status = "info"
        headline = "Authorization status available"
    return {
        "ok": True,
        "orgId": org_id,
        "generatedAt": now(),
        "status": status,
        "headline": headline,
        "counts": counts,
        "onlineNodes": online_nodes,
        "nodeCount": len(nodes),
        "topIssue": top,
        "items": items,
    }


def account_authorization_handoff(org_id=None, limit=30):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(100, max(1, int(limit or 30)))
    except Exception:
        limit = 30
    summary = account_authorization_summary(org_id)
    sessions = cloud_login_sessions(org_id, limit=100)
    items = []
    seen_accounts = set()
    now_ts = now()
    counts = {
        "ready": 0,
        "needAuth": 0,
        "inProgress": 0,
        "nodeIssue": 0,
        "stale": 0,
        "failed": 0,
        "total": 0,
    }

    def _severity_rank(v):
        return {"critical": 0, "warning": 1, "info": 2}.get(str(v or "info"), 2)

    def _add(item):
        if not isinstance(item, dict):
            return
        item.setdefault("id", "handoff-" + _short_hash(json.dumps(item, ensure_ascii=False, sort_keys=True)))
        item.setdefault("updatedAt", now_ts)
        items.append(item)

    def _session_action(status, idle_sec=0):
        if status == "logged_in":
            return "complete_save"
        if status in ("running", "active"):
            return "continue_auth"
        if status == "stale":
            try:
                idle_sec = float(idle_sec or 0)
            except Exception:
                idle_sec = 0
            return "cleanup_and_restart" if idle_sec >= 3600 else "resume_or_restart"
        if status == "failed":
            return "restart_auth"
        return "review_session"

    for row in summary.get("items") or []:
        account_id = row.get("accountId") or row.get("localAccountId") or ""
        if account_id:
            seen_accounts.add(account_id)
        ready = bool(row.get("usable"))
        next_action = row.get("nextAction") or ("use_account" if ready else "authorize_account")
        if ready:
            state = "ready"
            counts["ready"] += 1
            action_label = "\u67e5\u770b\u8d26\u53f7"
            customer_hint = "\u8d26\u53f7\u5df2\u53ef\u7528\uff0c\u5ba2\u6237\u65e0\u9700\u91cd\u590d\u767b\u5f55\u3002"
        elif next_action == "repair_node":
            state = "node_issue"
            counts["nodeIssue"] += 1
            action_label = "\u68c0\u67e5\u8282\u70b9"
            customer_hint = "\u8be5\u8d26\u53f7\u6240\u5c5e\u6267\u884c\u8282\u70b9\u4e0d\u53ef\u7528\uff0c\u9700\u5b9e\u65bd/\u7ba1\u7406\u5458\u5148\u6062\u590d\u8282\u70b9\u3002"
        elif next_action == "resume_auth":
            state = "in_progress"
            counts["inProgress"] += 1
            action_label = "\u6062\u590d\u6388\u6743"
            customer_hint = "\u5df2\u6709\u6388\u6743\u4f1a\u8bdd\u5728\u8fdb\u884c\uff0c\u5efa\u8bae\u5148\u6062\u590d\u753b\u9762\u7ee7\u7eed\u626b\u7801/\u77ed\u4fe1\u9a8c\u8bc1\u3002"
        else:
            state = "need_auth"
            counts["needAuth"] += 1
            action_label = "\u5f00\u59cb\u6388\u6743"
            customer_hint = "\u9700\u8981\u5ba2\u6237\u5b8c\u6210\u626b\u7801\u6216\u77ed\u4fe1\u9a8c\u8bc1\uff0c\u6210\u529f\u540e\u7cfb\u7edf\u4f1a\u81ea\u52a8\u4fdd\u5b58\u4f1a\u8bdd\u3002"
        _add({
            "id": "authacct-" + _short_hash(account_id or row.get("supportRef") or json.dumps(row, ensure_ascii=False, sort_keys=True)),
            "type": "account",
            "accountId": account_id,
            "localAccountId": row.get("localAccountId") or "",
            "nodeId": row.get("nodeId") or "",
            "nodeName": row.get("nodeName") or "",
            "name": row.get("name") or "Douyin",
            "state": state,
            "severity": row.get("severity") or ("info" if ready else "warning"),
            "summary": row.get("summary") or customer_hint,
            "customerHint": customer_hint,
            "operatorHint": row.get("handoffNote") or "",
            "nextAction": next_action,
            "actionLabel": action_label,
            "updatedAt": row.get("updatedAt") or now_ts,
            "supportRef": row.get("supportRef") or "",
        })
    sess_rows = sessions.get("sessions") or []
    for s in sess_rows:
        status = s.get("status") or "unknown"
        if status in ("closed", "no_session"):
            continue
        if status == "stale":
            counts["stale"] += 1
        elif status == "failed":
            counts["failed"] += 1
        elif status in ("running", "active", "logged_in"):
            counts["inProgress"] += 1
        account_id = s.get("accountId") or ""
        if account_id and account_id in seen_accounts and status not in ("logged_in", "stale", "failed"):
            continue
        sev = "critical" if status == "failed" else ("warning" if status == "stale" else "info")
        action = _session_action(status, s.get("idleSec") or 0)
        label = {
            "complete_save": "\u5b8c\u6210\u5e76\u4fdd\u5b58",
            "continue_auth": "\u7ee7\u7eed\u6388\u6743",
            "resume_or_restart": "\u6062\u590d\u4f1a\u8bdd",
            "cleanup_and_restart": "\u5173\u95ed\u91cd\u5f00",
            "restart_auth": "\u91cd\u65b0\u5f00\u59cb",
        }.get(action, "\u67e5\u770b\u4f1a\u8bdd")
        _add({
            "id": "authsess-" + _short_hash(s.get("id") or s.get("sessionIdShort") or json.dumps(s, ensure_ascii=False, sort_keys=True)),
            "type": "session",
            "sessionId": s.get("sessionId") or "",
            "sessionIdShort": s.get("sessionIdShort") or "",
            "accountId": account_id,
            "nodeId": s.get("nodeId") or "",
            "nodeName": s.get("nodeName") or "",
            "name": account_id or (s.get("nodeName") or "\u6388\u6743\u4f1a\u8bdd"),
            "state": status,
            "severity": sev,
            "summary": s.get("handoffNote") or s.get("customerAction") or status,
            "customerHint": s.get("customerAction") or "\u8bf7\u6309\u4f1a\u8bdd\u72b6\u6001\u7ee7\u7eed\u6388\u6743\u3002",
            "operatorHint": s.get("handoffNote") or "",
            "nextAction": action,
            "actionLabel": label,
            "updatedAt": s.get("updatedAt") or now_ts,
            "idleSec": s.get("idleSec") or 0,
            "canResume": bool(s.get("canResume")),
            "canClose": bool(s.get("canClose")),
        })
    if not items:
        counts["needAuth"] = 1
        _add({
            "id": "auth-first-account",
            "type": "first_auth",
            "accountId": "douyin-self",
            "nodeId": "",
            "name": "\u9996\u4e2a\u6296\u97f3\u8d26\u53f7",
            "state": "need_auth",
            "severity": "warning",
            "summary": "\u5f53\u524d\u5ba2\u6237\u5de5\u4f5c\u533a\u8fd8\u6ca1\u6709\u53ef\u7528\u6296\u97f3\u8d26\u53f7\u3002",
            "customerHint": "\u8bf7\u5f15\u5bfc\u5ba2\u6237\u5b8c\u6210\u7b2c\u4e00\u4e2a\u8d26\u53f7\u6388\u6743\uff0c\u6388\u6743\u540e\u624d\u80fd\u8fdb\u884c\u8bd5\u8fd0\u884c\u3002",
            "operatorHint": "\u70b9\u51fb\u5f00\u59cb\u6388\u6743\uff0c\u8ba9\u5ba2\u6237\u626b\u7801\u6216\u63a5\u6536\u77ed\u4fe1\u9a8c\u8bc1\u3002",
            "nextAction": "authorize_account",
            "actionLabel": "\u5f00\u59cb\u6388\u6743",
            "updatedAt": now_ts,
        })
    counts["total"] = len(items)
    items = sorted(items, key=lambda x: (_severity_rank(x.get("severity")), -(float(x.get("updatedAt") or 0))))[:limit]
    if counts.get("nodeIssue") or counts.get("failed"):
        status = "blocked"
        headline = "\u8d26\u53f7\u6388\u6743\u6709\u963b\u585e"
        message = "\u5148\u5904\u7406\u8282\u70b9\u79bb\u7ebf\u6216\u6388\u6743\u5931\u8d25\uff0c\u518d\u5f15\u5bfc\u5ba2\u6237\u91cd\u65b0\u6388\u6743\u3002"
    elif counts.get("needAuth") or counts.get("stale") or counts.get("inProgress"):
        status = "needs_attention"
        headline = "\u8d26\u53f7\u6388\u6743\u9700\u5ba2\u6237\u914d\u5408"
        message = "\u8bf7\u4f7f\u7528\u6388\u6743\u5411\u5bfc\u5b8c\u6210\u626b\u7801/\u77ed\u4fe1\u9a8c\u8bc1\uff0c\u5b8c\u6210\u540e\u56de\u5230\u7cfb\u7edf\u5237\u65b0\u72b6\u6001\u3002"
    else:
        status = "ready"
        headline = "\u8d26\u53f7\u6388\u6743\u5df2\u5c31\u7eea"
        message = "\u5ba2\u6237\u8d26\u53f7\u5df2\u53ef\u7528\uff0c\u65e0\u9700\u91cd\u590d\u626b\u7801\uff0c\u53ef\u8fdb\u5165\u8bd5\u8fd0\u884c\u3002"
    next_item = next((x for x in items if x.get("severity") == "critical"), None) or next((x for x in items if x.get("state") != "ready"), None) or (items[0] if items else None)
    cards = [
        {"key": "ready", "label": "\u53ef\u7528\u8d26\u53f7", "value": str(counts.get("ready") or 0)},
        {"key": "needAuth", "label": "\u9700\u6388\u6743", "value": str(counts.get("needAuth") or 0)},
        {"key": "inProgress", "label": "\u8fdb\u884c\u4e2d", "value": str(counts.get("inProgress") or 0)},
        {"key": "stale", "label": "\u5361\u4f4f/\u5931\u8d25", "value": str((counts.get("stale") or 0) + (counts.get("failed") or 0))},
    ]
    playbook = [
        {"key": "start", "label": "\u6253\u5f00\u6388\u6743", "detail": "\u7531\u5ba2\u6237\u5728\u4e91\u7aef\u753b\u9762\u626b\u7801\u6216\u8f93\u5165\u77ed\u4fe1\u9a8c\u8bc1\u7801\u3002"},
        {"key": "verify", "label": "\u5b8c\u6210\u9a8c\u8bc1", "detail": "\u82e5\u51fa\u73b0\u4e8c\u6b21\u9a8c\u8bc1\uff0c\u9009\u62e9\u63a5\u6536\u77ed\u4fe1\u9a8c\u8bc1\u7801\uff0c\u4e0d\u8ba9\u7528\u6237\u590d\u5236 Cookie\u3002"},
        {"key": "save", "label": "\u5b8c\u6210\u5e76\u4fdd\u5b58", "detail": "\u767b\u5f55\u6210\u529f\u540e\u70b9\u51fb\u5b8c\u6210\u5e76\u4fdd\u5b58\uff0c\u7cfb\u7edf\u56de\u5199\u8d26\u53f7\u8d44\u4ea7\u3002"},
        {"key": "confirm", "label": "\u5237\u65b0\u786e\u8ba4", "detail": "\u786e\u8ba4\u72b6\u6001\u53d8\u4e3a\u53ef\u7528\u540e\u518d\u8fdb\u5165\u53d1\u5e03/\u5bfb\u5ba2\u8bd5\u8fd0\u884c\u3002"},
    ]
    return {
        "ok": True,
        "orgId": org_id,
        "status": status,
        "headline": headline,
        "message": message,
        "counts": counts,
        "cards": cards,
        "items": items,
        "nextItem": next_item,
        "playbook": playbook,
        "sessionCounts": sessions.get("counts") or {},
        "summaryStatus": summary.get("status"),
        "generatedAt": now_ts,
    }

def compact_login_task(task):
    task = dict(task or {})
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    body = task.get("body") if isinstance(task.get("body"), dict) else {}
    return {
        "id": task.get("id"),
        "path": task.get("path"),
        "status": task.get("status"),
        "nodeId": task.get("nodeId"),
        "createdAt": task.get("createdAt"),
        "updatedAt": task.get("updatedAt"),
        "error": public_error_text(task.get("error") or result.get("error") or ""),
        "accountId": body.get("centralAccountId") or body.get("accountId") or result.get("accountId") or "",
        "sessionIdShort": short_session_id(body.get("sessionId") or result.get("sessionId") or ""),
        "hasSession": result.get("hasSession"),
        "loggedIn": result.get("loggedIn"),
        "message": result.get("message") or "",
    }


def short_session_id(session_id):
    session_id = str(session_id or "")
    if not session_id:
        return ""
    return session_id[:8] + "..." + session_id[-4:] if len(session_id) > 14 else session_id



def public_cloud_login_progress(item):
    item = item or {}
    ts = float(item.get("ts") or item.get("updatedAt") or item.get("createdAt") or now())
    status = str(item.get("status") or "open")[:40]
    return {
        "id": item.get("id") or "",
        "type": "matrix-login-progress",
        "orgId": item_org_id(item),
        "status": status,
        "label": str(item.get("label") or "")[:120],
        "detail": str(item.get("detail") or "")[:360],
        "accountId": str(item.get("accountId") or "")[:120],
        "nodeId": str(item.get("nodeId") or "")[:160],
        "sessionIdShort": str(item.get("sessionIdShort") or "")[:40],
        "source": str(item.get("source") or "server")[:40],
        "ts": ts,
        "createdAt": float(item.get("createdAt") or ts),
        "updatedAt": float(item.get("updatedAt") or ts),
    }


def record_cloud_login_progress(org_id=None, body=None, user=None):
    org_id = normalize_org_id(org_id)
    body = body if isinstance(body, dict) else {}
    status = str(body.get("status") or "open").strip().lower()[:40] or "open"
    allowed = {"starting", "recovering", "active", "verify", "logged_in", "saving", "saved", "idle", "error", "failed", "open"}
    if status not in allowed:
        status = "open"
    ts = now()
    try:
        client_ts = float(body.get("ts") or 0) / (1000.0 if float(body.get("ts") or 0) > 100000000000 else 1.0)
        if 0 < client_ts <= ts + 300:
            ts = client_ts
    except Exception:
        pass
    session_short = str(body.get("sessionIdShort") or "").strip()
    if not session_short and body.get("sessionId"):
        session_short = short_session_id(str(body.get("sessionId") or ""))
    item = {
        "id": "clp-" + uuid.uuid4().hex[:12],
        "orgId": org_id,
        "status": status,
        "label": str(body.get("label") or "")[:120],
        "detail": str(body.get("detail") or "")[:360],
        "accountId": str(body.get("accountId") or body.get("centralAccountId") or "douyin-self")[:120],
        "nodeId": str(body.get("nodeId") or body.get("preferredNode") or "")[:160],
        "sessionIdShort": session_short[:40],
        "source": str(body.get("source") or "login-page")[:40],
        "actorUserId": (user or {}).get("id") or "",
        "createdAt": ts,
        "updatedAt": ts,
        "ts": ts,
    }
    with LOCK:
        rows = STATE.setdefault("cloudLoginProgress", [])
        rows.append(item)
        if len(rows) > 1000:
            STATE["cloudLoginProgress"] = rows[-800:]
        persist()
    return {"ok": True, "orgId": org_id, "progress": public_cloud_login_progress(item)}


def list_cloud_login_progress(org_id=None, limit=20, account_id="", node_id="", fresh_sec=86400, since=0):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(100, max(1, int(limit or 20)))
    except Exception:
        limit = 20
    try:
        fresh_sec = max(0, min(86400 * 7, int(float(fresh_sec or 86400))))
    except Exception:
        fresh_sec = 86400
    try:
        since = float(since or 0)
    except Exception:
        since = 0
    account_id = str(account_id or "").strip()
    node_id = str(node_id or "").strip()
    cutoff = now() - fresh_sec if fresh_sec else 0
    with LOCK:
        rows = [dict(x) for x in (STATE.setdefault("cloudLoginProgress", []) or []) if item_org_id(x) == org_id]
    if account_id:
        rows = [x for x in rows if str(x.get("accountId") or "") == account_id]
    if node_id:
        rows = [x for x in rows if str(x.get("nodeId") or "") == node_id]
    if cutoff:
        rows = [x for x in rows if float(x.get("updatedAt") or x.get("ts") or 0) >= cutoff]
    if since:
        rows = [x for x in rows if float(x.get("updatedAt") or x.get("ts") or 0) >= since]
    rows.sort(key=lambda x: float(x.get("updatedAt") or x.get("ts") or 0), reverse=True)
    items = [public_cloud_login_progress(x) for x in rows[:limit]]
    counts = {}
    for x in rows:
        st = str(x.get("status") or "open")
        counts[st] = counts.get(st, 0) + 1
    return {"ok": True, "orgId": org_id, "items": items, "latest": items[0] if items else None, "counts": counts, "matched": len(rows), "total": len(rows)}


def _cloud_login_event_match(account_id, node_id, session_ref, ev_account="", ev_node="", ev_session_short="", ev_session_id=""):
    account_id = str(account_id or "").strip()
    node_id = str(node_id or "").strip()
    session_ref = str(session_ref or "").strip()
    ev_account = str(ev_account or "").strip()
    ev_node = str(ev_node or "").strip()
    ev_session_short = str(ev_session_short or "").strip()
    ev_session_id = str(ev_session_id or "").strip()
    if account_id and ev_account and account_id != ev_account:
        return False
    if node_id and ev_node and node_id != ev_node:
        return False
    if session_ref:
        ref_short = short_session_id(session_ref)
        if ev_session_id and session_ref != ev_session_id and ref_short != short_session_id(ev_session_id):
            return False
        if ev_session_short and session_ref != ev_session_short and ref_short != ev_session_short:
            return False
    return True


def cloud_login_task_event(task):
    task = dict(task or {})
    path = str(task.get("path") or "")
    body = task.get("body") if isinstance(task.get("body"), dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    sid = body.get("sessionId") or result.get("sessionId") or ""
    account_id = body.get("centralAccountId") or body.get("accountId") or result.get("accountId") or ""
    node_id = task.get("nodeId") or body.get("preferredNode") or body.get("nodeId") or result.get("nodeId") or ""
    phase = path.replace("/api/cloud-login/", "")
    title_map = {
        "start": "\u521b\u5efa\u6388\u6743\u4f1a\u8bdd",
        "current": "\u68c0\u67e5\u5f53\u524d\u4f1a\u8bdd",
        "status": "\u6062\u590d/\u68c0\u67e5\u4f1a\u8bdd",
        "screenshot": "\u5237\u65b0\u6388\u6743\u753b\u9762",
        "click": "\u4e91\u7aef\u70b9\u51fb",
        "type": "\u4e91\u7aef\u8f93\u5165",
        "key": "\u4e91\u7aef\u6309\u952e",
        "sms": "\u89e6\u53d1\u77ed\u4fe1\u9a8c\u8bc1",
        "refresh": "\u91cd\u8f7d\u6388\u6743\u9875",
        "close": "\u5173\u95ed\u6388\u6743\u4f1a\u8bdd",
        "finish": "\u4fdd\u5b58\u6388\u6743\u7ed3\u679c",
    }
    status = str(task.get("status") or "")
    err = public_error_text(task.get("error") or result.get("error") or "")
    ok = status == "done" and not err
    severity = "critical" if status == "failed" or err else ("warning" if status in ("queued", "running") else "info")
    detail_parts = []
    if status:
        detail_parts.append(status)
    if err:
        detail_parts.append(err)
    if result.get("message"):
        detail_parts.append(str(result.get("message"))[:180])
    if result.get("loggedIn") is True:
        detail_parts.append("logged_in")
    if result.get("hasSession") is False:
        detail_parts.append("no_session")
    return {
        "id": "task:" + str(task.get("id") or uuid.uuid4().hex[:8]),
        "ts": float(task.get("updatedAt") or task.get("createdAt") or now()),
        "kind": "task",
        "phase": phase,
        "title": title_map.get(phase, phase or "cloud_login_task"),
        "detail": " \u00B7 ".join([x for x in detail_parts if x])[:360],
        "status": status,
        "severity": severity,
        "ok": ok,
        "accountId": account_id,
        "nodeId": node_id,
        "sessionIdShort": short_session_id(sid),
        "taskId": task.get("id") or "",
    }


def cloud_login_timeline(org_id=None, account_id="", node_id="", session_ref="", limit=80):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(120, max(1, int(limit or 80)))
    except Exception:
        limit = 80
    account_id = str(account_id or "").strip()
    node_id = str(node_id or "").strip()
    session_ref = str(session_ref or "").strip()
    session = find_cloud_login_session(org_id, session_ref) if session_ref else None
    if session:
        account_id = account_id or session.get("accountId") or ""
        node_id = node_id or session.get("nodeId") or ""
        session_ref = session.get("sessionId") or session.get("sessionIdShort") or session_ref
    events = []
    with LOCK:
        progress_rows = [dict(x) for x in (STATE.setdefault("cloudLoginProgress", []) or []) if item_org_id(x) == org_id]
        task_rows = [dict(t) for t in (STATE.get("tasks") or {}).values() if item_org_id(t) == org_id and str(t.get("path") or "").startswith("/api/cloud-login/")]
        audit_rows = [dict(a) for a in (STATE.get("auditLogs") or []) if audit_log_org_id(a) in ("", org_id)]
    for p in progress_rows:
        ev = public_cloud_login_progress(p)
        if not _cloud_login_event_match(account_id, node_id, session_ref, ev.get("accountId"), ev.get("nodeId"), ev.get("sessionIdShort"), ""):
            continue
        st = ev.get("status") or "open"
        events.append({
            "id": "progress:" + (ev.get("id") or uuid.uuid4().hex[:8]),
            "ts": ev.get("updatedAt") or ev.get("ts") or now(),
            "kind": "progress",
            "phase": st,
            "title": ev.get("label") or st,
            "detail": ev.get("detail") or "",
            "status": st,
            "severity": "critical" if st in ("error", "failed") else ("warning" if st in ("verify", "idle") else "info"),
            "ok": st in ("logged_in", "saved"),
            "accountId": ev.get("accountId") or "",
            "nodeId": ev.get("nodeId") or "",
            "sessionIdShort": ev.get("sessionIdShort") or "",
        })
    for task in task_rows:
        body = task.get("body") if isinstance(task.get("body"), dict) else {}
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        sid = body.get("sessionId") or result.get("sessionId") or ""
        ev_account = body.get("centralAccountId") or body.get("accountId") or result.get("accountId") or ""
        ev_node = task.get("nodeId") or body.get("preferredNode") or body.get("nodeId") or result.get("nodeId") or ""
        if not _cloud_login_event_match(account_id, node_id, session_ref, ev_account, ev_node, short_session_id(sid), sid):
            continue
        events.append(cloud_login_task_event(task))
    for a in audit_rows:
        action = str(a.get("action") or "")
        target = str(a.get("target") or "")
        if "cloud_login" not in action and "cloud-login" not in target:
            continue
        meta = a.get("meta") if isinstance(a.get("meta"), dict) else {}
        ev_account = str(meta.get("accountId") or meta.get("centralAccountId") or "")
        ev_node = str(meta.get("nodeId") or "")
        ev_session = str(meta.get("sessionRef") or meta.get("sessionId") or "")
        if not _cloud_login_event_match(account_id, node_id, session_ref, ev_account, ev_node, ev_session, ev_session):
            continue
        title = {
            "cloud_login.session.close": "\u624b\u52a8\u5173\u95ed\u6388\u6743\u4f1a\u8bdd",
            "account.authorization.recover": "\u4e00\u952e\u6062\u590d\u6388\u6743",
            "cloud_login.session.cleanup": "\u6279\u91cf\u6e05\u7406\u6388\u6743\u4f1a\u8bdd",
        }.get(action, action or "audit")
        events.append({
            "id": "audit:" + str(a.get("id") or uuid.uuid4().hex[:8]),
            "ts": float(a.get("ts") or now()),
            "kind": "audit",
            "phase": action,
            "title": title,
            "detail": ("OK" if a.get("ok") else "FAILED") + (" \u00B7 " + json.dumps(meta, ensure_ascii=False)[:240] if meta else ""),
            "status": "ok" if a.get("ok") else "failed",
            "severity": "info" if a.get("ok") else "critical",
            "ok": bool(a.get("ok")),
            "accountId": ev_account,
            "nodeId": ev_node,
            "sessionIdShort": ev_session,
        })
    seen = set()
    deduped = []
    for ev in sorted(events, key=lambda x: float(x.get("ts") or 0), reverse=True):
        k = ev.get("id") or (str(ev.get("kind")) + ":" + str(ev.get("ts")) + ":" + str(ev.get("title")))
        if k in seen:
            continue
        seen.add(k)
        deduped.append(ev)
    counts = {}
    for ev in deduped:
        counts[ev.get("kind") or "event"] = counts.get(ev.get("kind") or "event", 0) + 1
    return {"ok": True, "orgId": org_id, "accountId": account_id, "nodeId": node_id, "sessionRef": short_session_id(session_ref) or session_ref, "items": deduped[:limit], "total": len(deduped), "counts": counts, "latest": deduped[0] if deduped else None}

def cloud_login_sessions(org_id=None, limit=50):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(100, max(1, int(limit or 50)))
    except Exception:
        limit = 50
    with LOCK:
        tasks = [dict(t) for t in (STATE.get("tasks") or {}).values() if item_org_id(t) == org_id and str(t.get("path") or "").startswith("/api/cloud-login/")]
        nodes = {nid: public_node(n) for nid, n in (STATE.get("nodes") or {}).items()}
    tasks = sorted(tasks, key=lambda x: x.get("updatedAt") or x.get("createdAt") or 0, reverse=True)
    grouped = {}
    for t in tasks[:500]:
        body = t.get("body") if isinstance(t.get("body"), dict) else {}
        result = t.get("result") if isinstance(t.get("result"), dict) else {}
        sid = body.get("sessionId") or result.get("sessionId") or ""
        account_id = body.get("centralAccountId") or body.get("accountId") or result.get("accountId") or ""
        node_id = t.get("nodeId") or body.get("preferredNode") or body.get("nodeId") or result.get("nodeId") or ""
        key = (node_id or "auto") + ":" + (sid or account_id or t.get("id") or "unknown")
        g = grouped.setdefault(key, {
            "id": "cls-" + _short_hash(key),
            "sessionId": sid,
            "sessionIdShort": short_session_id(sid),
            "accountId": account_id,
            "nodeId": node_id,
            "nodeName": (nodes.get(node_id) or {}).get("name") or node_id,
            "createdAt": t.get("createdAt") or now(),
            "updatedAt": t.get("updatedAt") or t.get("createdAt") or now(),
            "taskCount": 0,
            "tasks": [],
            "latestTask": None,
            "latestPath": "",
            "latestError": "",
            "loggedIn": False,
            "hasSession": None,
            "lastScreenshotAt": 0,
            "canClose": False,
        })
        if sid and not g.get("sessionId"):
            g["sessionId"] = sid
            g["sessionIdShort"] = short_session_id(sid)
        if account_id and not g.get("accountId"):
            g["accountId"] = account_id
        if node_id and not g.get("nodeId"):
            g["nodeId"] = node_id
            g["nodeName"] = (nodes.get(node_id) or {}).get("name") or node_id
        g["createdAt"] = min(float(g.get("createdAt") or t.get("createdAt") or now()), float(t.get("createdAt") or now()))
        g["updatedAt"] = max(float(g.get("updatedAt") or 0), float(t.get("updatedAt") or t.get("createdAt") or 0))
        g["taskCount"] += 1
        if len(g["tasks"]) < 8:
            g["tasks"].append(compact_login_task(t))
        if not g.get("latestTask") or float(t.get("updatedAt") or t.get("createdAt") or 0) >= float((g.get("latestTask") or {}).get("updatedAt") or 0):
            g["latestTask"] = compact_login_task(t)
            g["latestPath"] = t.get("path") or ""
            g["latestError"] = public_error_text(t.get("error") or (result.get("error") if isinstance(result, dict) else "") or "")
        if result.get("loggedIn"):
            g["loggedIn"] = True
        if result.get("hasSession") is not None:
            g["hasSession"] = result.get("hasSession")
        if t.get("path") in ("/api/cloud-login/screenshot", "/api/cloud-login/qr") and t.get("status") == "done":
            g["lastScreenshotAt"] = max(float(g.get("lastScreenshotAt") or 0), float(t.get("updatedAt") or 0))
    rows = []
    ts = now()
    for g in grouped.values():
        latest = g.get("latestTask") or {}
        latest_path = g.get("latestPath") or ""
        latest_status = latest.get("status") or ""
        latest_error = g.get("latestError") or ""
        age = ts - float(g.get("updatedAt") or ts)
        status = "unknown"
        if latest_path == "/api/cloud-login/close" and latest_status == "done":
            status = "closed"
        elif latest_status in ("queued", "running"):
            status = "running"
        elif latest_error in ("cloud_login_session_not_found", "not_found") or latest.get("message") == "no_active_cloud_login_session" or g.get("hasSession") is False:
            status = "no_session"
        elif g.get("loggedIn"):
            status = "logged_in"
        elif age > 1800:
            status = "stale"
        elif g.get("sessionId"):
            status = "active"
        elif latest_status == "failed":
            status = "failed"
        g["status"] = status
        g["ageSec"] = round(ts - float(g.get("createdAt") or ts), 1)
        g["idleSec"] = round(age, 1)
        g["canClose"] = bool(g.get("sessionId") and status not in ("closed", "no_session"))
        g["canResume"] = bool(g.get("sessionId") and status in ("running", "active", "logged_in", "stale"))
        g["recoverable"] = bool(g.get("canResume"))
        g["staleAfterSec"] = 1800
        g["staleAt"] = float(g.get("updatedAt") or ts) + 1800
        g["timeToStaleSec"] = round(max(0, g["staleAt"] - ts), 1)
        if status == "logged_in":
            g["customerAction"] = "\u70b9\u51fb\u5b8c\u6210\u5e76\u4fdd\u5b58"
        elif status in ("running", "active"):
            g["customerAction"] = "\u7ee7\u7eed\u626b\u7801/\u77ed\u4fe1\u9a8c\u8bc1"
        elif status == "stale":
            g["customerAction"] = "\u5148\u6062\u590d\u67e5\u770b\uff0c\u5fc5\u8981\u65f6\u91cd\u65b0\u5f00\u59cb"
        elif status == "failed":
            g["customerAction"] = "\u91cd\u65b0\u5f00\u59cb\u6388\u6743"
        else:
            g["customerAction"] = "\u65e0\u9700\u64cd\u4f5c"
        g.update(cloud_login_handoff(status, latest_path=latest_path, latest_error=latest_error, idle_sec=age))
        rows.append(g)
    rows = sorted(rows, key=lambda x: x.get("updatedAt") or 0, reverse=True)[:limit]
    counts = {}
    for r in rows:
        counts[r.get("status") or "unknown"] = counts.get(r.get("status") or "unknown", 0) + 1
    return {"ok": True, "orgId": org_id, "sessions": rows, "counts": counts, "total": len(rows)}


def cloud_login_session_audit(org_id=None, limit=100, status="", q=""):
    org_id = normalize_org_id(org_id)
    status = (status or "").strip().lower()
    q = (q or "").strip().lower()
    try:
        limit = min(200, max(1, int(limit or 100)))
    except Exception:
        limit = 100
    data = cloud_login_sessions(org_id, limit=min(100, max(limit, 100)))
    rows = []
    for s in data.get("sessions") or []:
        tasks = s.get("tasks") or []
        latest = s.get("latestTask") or {}
        row = {
            "id": s.get("id") or "",
            "sessionIdShort": s.get("sessionIdShort") or "",
            "accountId": s.get("accountId") or "",
            "nodeId": s.get("nodeId") or "",
            "nodeName": s.get("nodeName") or "",
            "status": s.get("status") or "",
            "slaLabel": s.get("slaLabel") or "",
            "handoffSeverity": s.get("handoffSeverity") or "",
            "handoffNote": s.get("handoffNote") or "",
            "latestPath": s.get("latestPath") or "",
            "latestError": public_error_text(s.get("latestError") or ""),
            "latestTaskId": latest.get("id") or "",
            "taskIds": [t.get("id") for t in tasks if t.get("id")],
            "taskCount": s.get("taskCount") or 0,
            "createdAt": s.get("createdAt") or 0,
            "updatedAt": s.get("updatedAt") or 0,
            "idleSec": s.get("idleSec") or 0,
            "ageSec": s.get("ageSec") or 0,
            "lastScreenshotAt": s.get("lastScreenshotAt") or 0,
            "canClose": bool(s.get("canClose")),
        }
        blob = " ".join([
            row["id"], row["sessionIdShort"], row["accountId"], row["nodeId"], row["nodeName"],
            row["status"], row["slaLabel"], row["handoffSeverity"], row["handoffNote"],
            row["latestPath"], row["latestError"], row["latestTaskId"], " ".join(row["taskIds"]),
        ]).lower()
        if status and status != "all" and row["status"].lower() != status:
            continue
        if q and q not in blob:
            continue
        rows.append(row)
    rows = rows[:limit]
    counts = {}
    for r in rows:
        counts[r.get("status") or "unknown"] = counts.get(r.get("status") or "unknown", 0) + 1
    return {
        "ok": True,
        "orgId": org_id,
        "rows": rows,
        "total": data.get("total") or len(rows),
        "matched": len(rows),
        "counts": counts,
        "filters": {"status": status or "all", "q": q, "limit": limit},
    }



def cloud_login_session_watchdog(org_id=None, limit=50):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(100, max(1, int(limit or 50)))
    except Exception:
        limit = 50
    data = cloud_login_sessions(org_id, limit=limit)
    sessions = data.get("sessions") or []
    counts = dict(data.get("counts") or {})
    active = [s for s in sessions if s.get("status") in ("running", "active", "logged_in")]
    stale = [s for s in sessions if s.get("status") == "stale"]
    failed = [s for s in sessions if s.get("status") == "failed"]
    closeable = [s for s in sessions if s.get("canClose") and s.get("status") in ("stale", "failed")]
    resumable = [s for s in sessions if s.get("canResume") and s.get("status") in ("running", "active", "logged_in", "stale")]
    long_running = [s for s in active if float(s.get("idleSec") or 0) > 900]
    if failed:
        status = "blocked"
        headline = "\u6388\u6743\u4f1a\u8bdd\u6709\u5931\u8d25\u9879"
        message = "\u6709 " + str(len(failed)) + " \u4e2a\u6388\u6743\u4f1a\u8bdd\u5931\u8d25\uff0c\u5efa\u8bae\u5148\u5173\u95ed\u5931\u8d25\u4f1a\u8bdd\u540e\u91cd\u65b0\u53d1\u8d77\u6388\u6743\u3002"
    elif stale:
        status = "needs_attention"
        headline = "\u6388\u6743\u4f1a\u8bdd\u7591\u4f3c\u5361\u4f4f"
        message = "\u6709 " + str(len(stale)) + " \u4e2a\u4f1a\u8bdd\u8d85\u8fc7\u7b49\u5f85\u65f6\u95f4\uff0c\u53ef\u5148\u6062\u590d\u67e5\u770b\uff0c\u5fc5\u8981\u65f6\u5173\u95ed\u91cd\u5f00\u3002"
    elif long_running:
        status = "needs_attention"
        headline = "\u6388\u6743\u4f1a\u8bdd\u957f\u65f6\u95f4\u672a\u66f4\u65b0"
        message = "\u6709 " + str(len(long_running)) + " \u4e2a\u4f1a\u8bdd\u8d85\u8fc7 15 \u5206\u949f\u672a\u66f4\u65b0\uff0c\u8bf7\u5ba2\u6237\u7ee7\u7eed\u626b\u7801/\u77ed\u4fe1\u6216\u8fdb\u5165\u65f6\u95f4\u7ebf\u786e\u8ba4\u3002"
    elif active:
        status = "active"
        headline = "\u6388\u6743\u4f1a\u8bdd\u6b63\u5728\u8fdb\u884c"
        message = "\u6709 " + str(len(active)) + " \u4e2a\u6388\u6743\u4f1a\u8bdd\u6d3b\u8dc3\uff0c\u7b49\u5f85\u5ba2\u6237\u626b\u7801\u6216\u77ed\u4fe1\u9a8c\u8bc1\u5b8c\u6210\u3002"
    else:
        status = "ready"
        headline = "\u6388\u6743\u4f1a\u8bdd\u65e0\u5361\u6b7b"
        message = "\u5f53\u524d\u6ca1\u6709\u9700\u5904\u7406\u7684\u6388\u6743\u4f1a\u8bdd\uff1b\u5982\u9700\u65b0\u589e\u8d26\u53f7\uff0c\u53ef\u76f4\u63a5\u53d1\u8d77\u65b0\u6388\u6743\u3002"
    actions = []
    def _act(key, label, action, severity="info", resource=None, detail=""):
        actions.append({"key": key, "label": label, "action": action, "severity": severity, "resource": resource or {}, "detail": detail})
    first_close = closeable[0] if closeable else None
    first_resume = resumable[0] if resumable else None
    if first_close:
        _act("recover_authorization", "\u4e00\u952e\u6062\u590d\u6388\u6743", "recover_authorization", "warning", {"sessionId": first_close.get("id"), "accountId": first_close.get("accountId"), "nodeId": first_close.get("nodeId")}, "\u5173\u95ed\u5361\u4f4f\u4f1a\u8bdd\u5e76\u6253\u5f00\u65b0\u7684\u5ba2\u6237\u6388\u6743\u9875\uff0c\u540e\u53f0\u7559\u5b58\u6062\u590d\u8bc1\u636e\u3002")
        _act("cleanup_stale", "\u6e05\u7406\u5361\u4f4f\u4f1a\u8bdd", "cleanup_stale_sessions", "warning", {"sessionId": first_close.get("id"), "accountId": first_close.get("accountId"), "nodeId": first_close.get("nodeId")}, "\u6279\u91cf\u5173\u95ed\u5361\u4f4f/\u5931\u8d25\u6388\u6743\u4f1a\u8bdd\u3002")
    if first_resume:
        _act("resume_session", "\u7ee7\u7eed\u6388\u6743", "resume_session", "info", {"sessionId": first_resume.get("id"), "accountId": first_resume.get("accountId"), "nodeId": first_resume.get("nodeId")}, "\u6253\u5f00\u5df2\u6709\u6388\u6743\u4f1a\u8bdd\u7ee7\u7eed\u64cd\u4f5c\u3002")
    _act("start_auth", "\u65b0\u589e\u6388\u6743", "start_auth", "info", {"accountId": "douyin-self"}, "\u6253\u5f00\u65b0\u7684\u5ba2\u6237\u6388\u6743\u9875\u3002")
    cards = [
        {"key": "active", "label": "\u6d3b\u8dc3", "value": str(len(active))},
        {"key": "stale", "label": "\u5361\u4f4f", "value": str(len(stale))},
        {"key": "failed", "label": "\u5931\u8d25", "value": str(len(failed))},
        {"key": "closeable", "label": "\u53ef\u6e05\u7406", "value": str(len(closeable))},
    ]
    return {
        "ok": True,
        "orgId": org_id,
        "status": status,
        "headline": headline,
        "message": message,
        "counts": {"total": len(sessions), "active": len(active), "stale": len(stale), "failed": len(failed), "closeable": len(closeable), "resumable": len(resumable)},
        "cards": cards,
        "actions": actions[:4],
        "nextAction": actions[0] if actions else None,
        "sessions": sessions[:limit],
        "rawCounts": counts,
        "generatedAt": now(),
    }

def find_cloud_login_session(org_id, session_ref):
    session_ref = (session_ref or "").strip()
    if not session_ref:
        return None
    data = cloud_login_sessions(org_id, limit=100)
    for s in data.get("sessions") or []:
        if session_ref in (s.get("id"), s.get("sessionId"), s.get("sessionIdShort")):
            return s
    return None



# P2.01 account authorization flow state machine for customer-facing login UX.
def cloud_login_step_model(phase, account_ready=False, platform="douyin"):
    platform = infer_account_platform(platform=platform)
    app_label = "小红书 App" if platform == "xhs" else "抖音 App"
    order = ["prepare", "scan", "verify", "save"]
    labels = {
        "prepare": "\u521b\u5efa\u4f1a\u8bdd",
        "scan": "\u626b\u7801\u767b\u5f55",
        "verify": "\u77ed\u4fe1\u9a8c\u8bc1",
        "save": "\u4fdd\u5b58 Cookie",
    }
    details = {
        "prepare": "\u5206\u914d\u4e91\u7aef\u6267\u884c\u8282\u70b9",
        "scan": app_label + " 扫码",
        "verify": "\u6309\u9700\u63a5\u6536\u5e76\u8f93\u5165\u77ed\u4fe1\u9a8c\u8bc1\u7801",
        "save": "\u767b\u5f55\u6210\u529f\u540e\u56de\u5199\u5230\u6267\u884c\u8282\u70b9",
    }
    idx = order.index(phase) if phase in order else 0
    rows = []
    for i, key in enumerate(order):
        status = "done" if i < idx or account_ready else ("active" if i == idx else "wait")
        if phase == "verify" and key == "scan":
            status = "done"
        if phase == "save" and key in ("scan", "verify"):
            status = "done"
        rows.append({"key": key, "label": labels[key], "detail": details[key], "status": status})
    return rows


def cloud_login_flow_state(org_id=None, account_id="", node_id="", session_ref="", platform=""):
    org_id = normalize_org_id(org_id)
    platform = infer_account_platform(account_id, platform=platform)
    default_account = "xhs-self" if platform == "xhs" else "douyin-self"
    account_id = (account_id or default_account).strip() or default_account
    node_id = (node_id or "").strip()
    session_ref = (session_ref or "").strip()
    asset = find_account_asset(account_id, org_id)
    platform = infer_account_platform(account_id, asset, platform)
    if asset and not node_id:
        node_id = asset.get("nodeId") or node_id
    diag = auth_diagnosis(org_id, account_id=account_id, node_id=node_id)
    diag = diag if isinstance(diag, dict) else {"code": "diagnosis_unavailable", "severity": "warning", "summary": "Diagnosis unavailable", "suggestions": []}
    data = cloud_login_sessions(org_id, limit=100)
    sessions = data.get("sessions") or []
    account_refs = account_ref_candidates(account_id)
    relevant = []
    for s in sessions:
        sess_refs = account_ref_candidates(s.get("accountId") or "")
        if session_ref and session_ref not in (s.get("id"), s.get("sessionId"), s.get("sessionIdShort")):
            continue
        if node_id and s.get("nodeId") and s.get("nodeId") != node_id:
            continue
        if account_refs and sess_refs and not (account_refs & sess_refs):
            continue
        relevant.append(s)
    relevant = sorted(relevant, key=lambda x: x.get("updatedAt") or 0, reverse=True)
    session = relevant[0] if relevant else None
    resume = cloud_login_resume(org_id, account_id=account_id, node_id=node_id, allow_stale=True, session_ref=session_ref) if (session_ref or account_id or node_id) else {"ok": True, "hasSession": False}
    if resume.get("hasSession"):
        session = session or find_cloud_login_session(org_id, resume.get("sessionRef") or resume.get("sessionId") or "") or {}
    account_ready = bool(asset and asset.get("usable"))
    status = "not_started"
    phase = "prepare"
    severity = "info"
    headline = "\u53ef\u4ee5\u5f00\u59cb\u8d26\u53f7\u6388\u6743"
    detail = "\u70b9\u51fb\u5f00\u59cb\u6388\u6743\uff0c\u4e91\u7aef\u8282\u70b9\u4f1a\u6253\u5f00\u5b98\u65b9\u767b\u5f55\u9875\u3002"
    next_action = "start_auth"
    can_start = True
    can_resume = bool(resume.get("hasSession"))
    can_force_new = True
    can_sms = False
    can_save = False
    if diag.get("code") in ("no_online_node", "target_node_offline"):
        status = "blocked"
        phase = "prepare"
        severity = "critical"
        headline = diag.get("summary") or "\u6267\u884c\u8282\u70b9\u4e0d\u53ef\u7528"
        detail = "\u8bf7\u5148\u6062\u590d\u4e91\u7aef\u6267\u884c\u8282\u70b9\uff0c\u5426\u5219\u5ba2\u6237\u65e0\u6cd5\u5b8c\u6210\u626b\u7801\u548c Cookie \u56de\u5199\u3002"
        next_action = "repair_node"
        can_start = False
        can_force_new = False
    elif account_ready:
        status = "ready"
        phase = "save"
        severity = "info"
        headline = "\u8d26\u53f7\u5df2\u53ef\u7528"
        detail = "\u8282\u70b9\u5728\u7ebf\u4e14 Cookie \u6709\u6548\uff0c\u5ba2\u6237\u53ef\u76f4\u63a5\u521b\u5efa\u5bfb\u5ba2\u6216\u53d1\u5e03\u4efb\u52a1\u3002"
        next_action = "use_account"
        can_start = False
        can_resume = False
        can_force_new = True
    elif resume.get("hasSession"):
        sess_status = resume.get("status") or (session or {}).get("status") or "active"
        if sess_status == "logged_in":
            status = "logged_in"
            phase = "save"
            severity = "info"
            headline = "\u5df2\u68c0\u6d4b\u5230\u767b\u5f55\uff0c\u5f85\u4fdd\u5b58"
            detail = "\u8bf7\u70b9\u51fb\u5b8c\u6210\u5e76\u4fdd\u5b58\uff0c\u7cfb\u7edf\u4f1a\u5173\u95ed\u4f1a\u8bdd\u5e76\u7b49\u5f85\u8282\u70b9\u540c\u6b65\u8d26\u53f7\u8d44\u4ea7\u3002"
            next_action = "complete_save"
            can_save = True
            can_sms = False
        elif sess_status == "stale":
            status = "stale"
            phase = "scan"
            severity = "warning"
            headline = "\u6388\u6743\u4f1a\u8bdd\u7591\u4f3c\u5361\u4f4f"
            detail = (session or {}).get("handoffNote") or resume.get("handoffNote") or "\u4f1a\u8bdd\u8f83\u957f\u65f6\u95f4\u65e0\u66f4\u65b0\uff0c\u5efa\u8bae\u5148\u6062\u590d\u67e5\u770b\u753b\u9762\uff0c\u5fc5\u8981\u65f6\u91cd\u65b0\u5f00\u59cb\u3002"
            next_action = "resume_or_restart"
            can_sms = True
        elif sess_status in ("running", "active"):
            status = "active"
            phase = "scan"
            severity = "info"
            headline = "\u6388\u6743\u4f1a\u8bdd\u8fdb\u884c\u4e2d"
            detail = "\u8bf7\u5728\u4e91\u7aef\u753b\u9762\u5b8c\u6210\u626b\u7801\uff1b\u82e5\u51fa\u73b0\u4e8c\u6b21\u9a8c\u8bc1\uff0c\u70b9\u51fb\u63a5\u6536\u77ed\u4fe1\u9a8c\u8bc1\u7801\u3002"
            next_action = "continue_auth"
            can_sms = True
        else:
            status = sess_status or "active"
            phase = "prepare"
            severity = "warning" if sess_status in ("failed", "no_session") else "info"
            headline = (session or {}).get("slaLabel") or "\u6388\u6743\u4f1a\u8bdd\u5f85\u786e\u8ba4"
            detail = (session or {}).get("handoffNote") or "\u8bf7\u5237\u65b0\u6216\u91cd\u65b0\u5f00\u59cb\u6388\u6743\u3002"
            next_action = "restart_auth"
    elif diag.get("code") == "auth_session_in_progress":
        status = "in_progress"
        phase = "prepare"
        severity = "warning"
        headline = diag.get("summary") or "\u5df2\u6709\u6388\u6743\u4efb\u52a1\u5728\u6267\u884c"
        detail = "\u8bf7\u5148\u70b9\u51fb\u6062\u590d\u4f1a\u8bdd\u67e5\u770b\u753b\u9762\uff0c\u907f\u514d\u91cd\u590d\u6253\u5f00\u591a\u4e2a\u6d4f\u89c8\u5668\u4f1a\u8bdd\u3002"
        next_action = "resume_auth"
        can_resume = True
    return {
        "ok": True,
        "orgId": org_id,
        "accountId": account_id,
        "platform": platform,
        "nodeId": node_id,
        "status": status,
        "phase": phase,
        "severity": severity,
        "headline": headline,
        "detail": detail,
        "nextAction": next_action,
        "steps": cloud_login_step_model(phase, account_ready=account_ready, platform=platform),
        "canStart": bool(can_start),
        "canResume": bool(can_resume),
        "canForceNew": bool(can_force_new),
        "canSms": bool(can_sms),
        "canSave": bool(can_save),
        "diagnosis": {"code": diag.get("code"), "severity": diag.get("severity"), "summary": diag.get("summary"), "suggestions": diag.get("suggestions") or []},
        "session": None if not (resume.get("hasSession") or session) else {
            "sessionRef": resume.get("sessionRef") or (session or {}).get("id") or "",
            "sessionId": resume.get("sessionId") or (session or {}).get("sessionId") or "",
            "sessionIdShort": resume.get("sessionIdShort") or (session or {}).get("sessionIdShort") or "",
            "status": resume.get("status") or (session or {}).get("status") or "",
            "nodeId": resume.get("nodeId") or (session or {}).get("nodeId") or "",
            "nodeName": (session or {}).get("nodeName") or "",
            "idleSec": resume.get("idleSec") or (session or {}).get("idleSec") or 0,
            "updatedAt": resume.get("updatedAt") or (session or {}).get("updatedAt") or 0,
            "handoffNote": resume.get("handoffNote") or (session or {}).get("handoffNote") or "",
        },
        "account": asset,
        "updatedAt": now(),
    }



# P2.04 account authorization asset-sync visibility for customer-facing UX.
def account_authorization_status(org_id, account_id="", node_id="", session_ref="", platform=""):
    org_id = normalize_org_id(org_id)
    platform = infer_account_platform(account_id, platform=platform)
    default_account = "xhs-self" if platform == "xhs" else "douyin-self"
    account_id = (account_id or default_account).strip() or default_account
    node_id = (node_id or "").strip()
    session_ref = (session_ref or "").strip()
    asset = find_account_asset(account_id, org_id)
    platform = infer_account_platform(account_id, asset, platform)
    if asset and not node_id:
        node_id = asset.get("nodeId") or node_id
    detail = account_detail(asset.get("id") or account_id, org_id) if asset else None
    diag = auth_diagnosis(org_id, account_id=(asset or {}).get("id") or account_id, node_id=node_id)
    diag = diag if isinstance(diag, dict) else {"code": "diagnosis_unavailable", "severity": "warning", "summary": "Diagnosis unavailable", "suggestions": []}
    flow = cloud_login_flow_state(org_id, account_id=(asset or {}).get("id") or account_id, node_id=node_id, session_ref=session_ref, platform=platform)
    sess_data = cloud_login_sessions(org_id, limit=100)
    account_refs = account_ref_candidates(account_id) | account_ref_candidates((asset or {}).get("id") or "") | account_ref_candidates((asset or {}).get("localAccountId") or "")
    related = []
    for s in sess_data.get("sessions") or []:
        sess_refs = account_ref_candidates(s.get("accountId") or "")
        if session_ref and session_ref not in (s.get("id"), s.get("sessionId"), s.get("sessionIdShort")):
            continue
        if node_id and s.get("nodeId") and s.get("nodeId") != node_id:
            continue
        if account_refs and sess_refs and not (account_refs & sess_refs):
            continue
        related.append(s)
    related = sorted(related, key=lambda x: x.get("updatedAt") or 0, reverse=True)[:8]
    latest = related[0] if related else {}
    capabilities = normalize_account_capabilities((asset or {}).get("capabilities"), platform, bool(asset and asset.get("cookieReady")), (asset or {}).get("cookieCount", 0) if asset else 0)
    ready = bool(asset and asset.get("usable") and capabilities.get("ready"))
    node_online = bool((detail or {}).get("node", {}).get("online") or (asset and asset.get("online")))
    cookie_ready = bool(asset and asset.get("cookieReady"))
    has_session = bool((flow or {}).get("session") or related)
    login_detected = bool((flow or {}).get("status") == "logged_in" or any(s.get("loggedIn") or s.get("status") == "logged_in" for s in related))
    latest_status = latest.get("status") or ""
    latest_path = latest.get("latestPath") or ""
    recently_closed = bool(latest_status == "closed" or latest_path == "/api/cloud-login/close")
    status = "needs_auth"
    severity = "info"
    headline = "\u9700\u8981\u8d26\u53f7\u6388\u6743"
    message = "\u8bf7\u5148\u5b8c\u6210\u626b\u7801\u6216\u77ed\u4fe1\u9a8c\u8bc1\uff0c\u767b\u5f55\u6210\u529f\u540e\u7cfb\u7edf\u4f1a\u540c\u6b65 Cookie \u8d44\u4ea7\u3002"
    next_action = "authorize_account"
    syncing = False
    blocked = False
    if ready:
        status = "ready"
        severity = "info"
        headline = "\u8d26\u53f7\u5df2\u53ef\u7528"
        message = "\u8282\u70b9\u5728\u7ebf\u4e14 Cookie \u6709\u6548\uff0c\u53ef\u7ee7\u7eed\u521b\u5efa\u53d1\u5e03\u3001\u91c7\u96c6\u6216\u5bfb\u5ba2\u4efb\u52a1\u3002"
        next_action = "use_account"
    elif diag.get("code") in ("no_online_node", "target_node_offline") or (asset and not node_online):
        status = "node_blocked"
        severity = "critical"
        blocked = True
        headline = diag.get("summary") or "\u6267\u884c\u8282\u70b9\u4e0d\u53ef\u7528"
        message = "\u8d26\u53f7\u9700\u8981\u4e91\u7aef\u8282\u70b9\u5728\u7ebf\u624d\u80fd\u767b\u5f55\u3001\u4fdd\u5b58\u548c\u4f7f\u7528 Cookie\u3002"
        next_action = "repair_node"
    elif login_detected and has_session and not recently_closed:
        status = "login_detected"
        severity = "info"
        headline = "\u5df2\u68c0\u6d4b\u5230\u767b\u5f55\uff0c\u5f85\u4fdd\u5b58"
        message = "\u8bf7\u70b9\u51fb\u5b8c\u6210\u5e76\u4fdd\u5b58\uff0c\u7cfb\u7edf\u4f1a\u5173\u95ed\u4e91\u7aef\u4f1a\u8bdd\u5e76\u89e6\u53d1\u8d26\u53f7\u8d44\u4ea7\u540c\u6b65\u3002"
        next_action = "complete_save"
    elif recently_closed or login_detected or (asset and node_online and not cookie_ready):
        status = "cookie_syncing"
        severity = "warning"
        syncing = True
        headline = "\u767b\u5f55\u5df2\u4fdd\u5b58\uff0c\u6b63\u5728\u540c\u6b65 Cookie"
        message = "\u8282\u70b9\u6b63\u5728\u56de\u5199\u8d26\u53f7\u8d44\u4ea7\uff1b\u82e5 1-2 \u5206\u949f\u540e\u4ecd\u4e0d\u53ef\u7528\uff0c\u8bf7\u91cd\u65b0\u6388\u6743\u6216\u68c0\u67e5\u8282\u70b9\u8fdb\u7a0b\u3002"
        next_action = "wait_or_retry"
    elif (flow or {}).get("status") in ("active", "in_progress") or latest_status in ("active", "running"):
        status = "auth_in_progress"
        severity = "info"
        headline = "\u8d26\u53f7\u6388\u6743\u8fdb\u884c\u4e2d"
        message = "\u8bf7\u5728\u4e91\u7aef\u753b\u9762\u5b8c\u6210\u626b\u7801\uff1b\u5982\u679c\u51fa\u73b0\u4e8c\u6b21\u9a8c\u8bc1\uff0c\u70b9\u51fb\u63a5\u6536\u77ed\u4fe1\u9a8c\u8bc1\u7801\u3002"
        next_action = "continue_auth"
    elif (flow or {}).get("status") == "stale" or latest_status == "stale":
        status = "stale_session"
        severity = "warning"
        headline = "\u6388\u6743\u4f1a\u8bdd\u7591\u4f3c\u5361\u4f4f"
        message = (latest.get("handoffNote") or (flow or {}).get("detail") or "\u8bf7\u5148\u6062\u590d\u4f1a\u8bdd\uff0c\u5fc5\u8981\u65f6\u91cd\u65b0\u5f00\u59cb\u3002")
        next_action = "resume_or_restart"
    elif latest_status == "failed" or diag.get("code") == "last_auth_task_failed":
        status = "failed"
        severity = "warning"
        headline = diag.get("summary") or "\u6700\u8fd1\u4e00\u6b21\u6388\u6743\u4efb\u52a1\u5931\u8d25"
        message = "\u8bf7\u91cd\u65b0\u5f00\u59cb\u6388\u6743\uff1b\u5982\u591a\u6b21\u5931\u8d25\uff0c\u68c0\u67e5\u8282\u70b9\u6d4f\u89c8\u5668\u4f1a\u8bdd\u548c\u7f51\u7edc\u3002"
        next_action = "restart_auth"
    def stage(key, label, done=False, active=False, blocked_stage=False, detail_text=""):
        st = "done" if done else ("blocked" if blocked_stage else ("active" if active else "wait"))
        return {"key": key, "label": label, "status": st, "done": bool(done), "detail": detail_text}
    stages = [
        stage("login", "\u5b98\u65b9\u767b\u5f55", done=ready or login_detected or recently_closed, active=status in ("auth_in_progress", "stale_session"), blocked_stage=blocked, detail_text=(flow or {}).get("headline") or ""),
        stage("session", "\u4f1a\u8bdd\u4fdd\u5b58", done=ready or recently_closed or bool(asset), active=status == "login_detected", blocked_stage=blocked, detail_text=latest.get("sessionIdShort") or ""),
        stage("registry", "\u8d44\u4ea7\u767b\u8bb0", done=bool(asset), active=status == "cookie_syncing" and not asset, blocked_stage=False, detail_text=(asset or {}).get("id") or account_id),
        stage("node", "\u8282\u70b9\u5728\u7ebf", done=node_online, active=bool(asset) and not node_online, blocked_stage=blocked, detail_text=node_id or (asset or {}).get("nodeId") or ""),
        stage("cookie", "Cookie \u53ef\u7528", done=cookie_ready, active=status == "cookie_syncing", blocked_stage=False, detail_text=("ready" if cookie_ready else "pending")),
    ]
    support_ref = "authstatus-" + _short_hash(json.dumps({"orgId": org_id, "accountId": account_id, "nodeId": node_id, "status": status, "code": diag.get("code")}, ensure_ascii=False, sort_keys=True))
    return {
        "ok": True,
        "orgId": org_id,
        "accountId": account_id,
        "platform": platform,
        "nodeId": node_id,
        "status": status,
        "severity": severity,
        "ready": ready,
        "syncing": bool(syncing),
        "blocked": bool(blocked),
        "headline": headline,
        "message": message,
        "nextAction": next_action,
        "supportRef": support_ref,
        "stages": stages,
        "capabilities": capabilities,
        "flow": flow,
        "diagnosis": {"code": diag.get("code"), "severity": diag.get("severity"), "summary": diag.get("summary"), "suggestions": diag.get("suggestions") or [], "handoffNote": diag.get("handoffNote") or ""},
        "account": (detail or {}).get("account") if detail else asset,
        "accountDetail": detail,
        "sessions": related,
        "generatedAt": now(),
    }


def account_ref_candidates(value):
    value = str(value or "").strip()
    out = set()
    if value:
        out.add(value)
        if ":" in value:
            out.add(value.split(":", 1)[-1])
    return {x for x in out if x}


def cloud_login_resume(org_id, account_id="", node_id="", allow_stale=True, session_ref=""):
    org_id = normalize_org_id(org_id)
    account_id = (account_id or "").strip()
    node_id = (node_id or "").strip()
    session_ref = (session_ref or "").strip()
    account_refs = account_ref_candidates(account_id)
    data = cloud_login_sessions(org_id, limit=100)
    usable_status = {"running", "active", "logged_in"}
    if allow_stale:
        usable_status.add("stale")
    rows = []
    exact_ref_mode = bool(session_ref)
    if exact_ref_mode:
        exact = find_cloud_login_session(org_id, session_ref)
        if not exact:
            return {"ok": True, "orgId": org_id, "hasSession": False, "resumed": False, "error": "cloud_login_session_ref_not_found", "message": "cloud_login_session_ref_not_found", "sessionRef": session_ref}
        if not exact.get("sessionId") or exact.get("status") not in usable_status:
            return {"ok": True, "orgId": org_id, "hasSession": False, "resumed": False, "error": "cloud_login_session_not_resumable", "message": "cloud_login_session_not_resumable", "sessionRef": session_ref, "status": exact.get("status") or "unknown", "session": {k: exact.get(k) for k in ("id", "sessionIdShort", "accountId", "nodeId", "status")}}
        rows.append((1000, exact))
    for s in ([] if exact_ref_mode else (data.get("sessions") or [])):
        if not s.get("sessionId"):
            continue
        if s.get("status") not in usable_status:
            continue
        sess_refs = account_ref_candidates(s.get("accountId") or "")
        account_match = bool(not account_refs or not sess_refs or (account_refs & sess_refs))
        node_match = bool(not node_id or s.get("nodeId") == node_id)
        if account_refs and sess_refs and not account_match:
            continue
        if node_id and not node_match:
            continue
        status_score = {"running": 40, "active": 35, "logged_in": 30, "stale": 10}.get(s.get("status"), 0)
        score = status_score + (20 if account_match else 0) + (10 if node_match else 0) + min(10, float(s.get("updatedAt") or 0) / max(1, now()) * 10)
        rows.append((score, s))
    rows.sort(key=lambda x: (x[0], float(x[1].get("updatedAt") or 0)), reverse=True)
    if not rows:
        return {"ok": True, "orgId": org_id, "hasSession": False, "resumed": False, "error": "no_resumable_cloud_login_session", "message": "no_resumable_cloud_login_session"}
    sess = rows[0][1]
    exec_node = None
    with LOCK:
        raw_node = (STATE.get("nodes") or {}).get(sess.get("nodeId") or "")
        if raw_node:
            exec_node = public_node(raw_node)
    return {
        "ok": True,
        "orgId": org_id,
        "hasSession": True,
        "resumed": True,
        "resumeSource": "central-session-ref" if exact_ref_mode else "central-session-index",
        "sessionRef": sess.get("id") or session_ref,
        "sessionId": sess.get("sessionId"),
        "sessionIdShort": sess.get("sessionIdShort") or short_session_id(sess.get("sessionId")),
        "nodeId": sess.get("nodeId") or "",
        "accountId": sess.get("accountId") or account_id,
        "status": sess.get("status") or "unknown",
        "stale": sess.get("status") == "stale",
        "idleSec": sess.get("idleSec") or 0,
        "updatedAt": sess.get("updatedAt") or 0,
        "latestPath": sess.get("latestPath") or "",
        "latestError": sess.get("latestError") or "",
        "executionNode": exec_node,
        "handoffNote": sess.get("handoffNote") or "",
        "slaLabel": sess.get("slaLabel") or "",
    }


def close_cloud_login_session(org_id, session_ref, wait_sec=20):
    org_id = normalize_org_id(org_id)
    sess = find_cloud_login_session(org_id, session_ref)
    if not sess:
        return {"ok": False, "error": "cloud_login_session_not_found"}, 404
    if not sess.get("sessionId"):
        return {"ok": False, "error": "cloud_login_session_missing_id", "session": sess}, 409
    body = {
        "orgId": org_id,
        "sessionId": sess.get("sessionId"),
        "nodeId": sess.get("nodeId") or "",
        "preferredNode": sess.get("nodeId") or "",
        "accountId": (sess.get("accountId") or "douyin-self").split(":", 1)[-1],
        "centralAccountId": sess.get("accountId") or "",
        "waitSec": wait_sec,
        "force": True,
    }
    result, status, task = dispatch_task_sync("/api/cloud-login/close", body)
    return {"ok": status < 400 and bool(result.get("ok", True)), "status": status, "result": result, "task": public_task(task), "session": {k: sess.get(k) for k in ("id", "sessionIdShort", "accountId", "nodeId", "status")}}, status


def restart_account_authorization(org_id, body, user=None):
    org_id = normalize_org_id(org_id)
    body = body if isinstance(body, dict) else {}
    account_id = (body.get("centralAccountId") or body.get("accountId") or "douyin-self").strip() or "douyin-self"
    node_id = (body.get("preferredNode") or body.get("nodeId") or "").strip()
    session_ref = (body.get("sessionId") or body.get("id") or body.get("sessionRef") or "").strip()
    try:
        wait_sec = max(5, min(45, float(body.get("waitSec") or 12)))
    except Exception:
        wait_sec = 12
    selected = None
    if session_ref:
        selected = find_cloud_login_session(org_id, session_ref)
    if not selected:
        try:
            sessions = cloud_login_sessions(org_id, limit=100).get("sessions") or []
        except Exception:
            sessions = []
        refs = account_ref_candidates(account_id)
        for sess in sessions:
            if not isinstance(sess, dict):
                continue
            if sess.get("status") in ("closed", "no_session"):
                continue
            sess_refs = account_ref_candidates(sess.get("accountId") or "")
            node_match = (not node_id) or (not sess.get("nodeId")) or sess.get("nodeId") == node_id
            acct_match = (not refs) or (sess_refs and (refs & sess_refs)) or (account_id in ("douyin-self", ""))
            if node_match and acct_match:
                selected = sess
                break
    close_payload = {"ok": True, "skipped": True, "reason": "no_active_session"}
    close_status = 200
    if selected and (selected.get("id") or selected.get("sessionId")):
        ref = selected.get("id") or selected.get("sessionId")
        close_payload, close_status = close_cloud_login_session(org_id, ref, wait_sec=wait_sec)
    node_id = node_id or ((selected or {}).get("nodeId") or "")
    query = {"resume": "1", "orgId": org_id, "accountId": account_id}
    if node_id:
        query["nodeId"] = node_id
    login_path = "/login-douyin.html?" + urlencode(query)
    watch_query = {"accountId": account_id}
    if node_id:
        watch_query["nodeId"] = node_id
    if selected and selected.get("sessionId"):
        watch_query["sessionRef"] = selected.get("sessionId")
    watch_path = "/api/accounts/authorization-watch?" + urlencode(watch_query)
    close_ok = bool(isinstance(close_payload, dict) and close_payload.get("ok")) and close_status < 500
    return {
        "ok": close_ok,
        "orgId": org_id,
        "accountId": account_id,
        "nodeId": node_id,
        "closed": bool(selected),
        "selectedSession": {k: (selected or {}).get(k) for k in ("id", "sessionIdShort", "accountId", "nodeId", "status")},
        "closeStatus": close_status,
        "closeResult": close_payload if isinstance(close_payload, dict) else {},
        "loginPath": login_path,
        "watchPath": watch_path,
        "message": "\u65e7\u4f1a\u8bdd\u5df2\u5904\u7406\uff0c\u8bf7\u5728\u65b0\u6253\u5f00\u7684\u6388\u6743\u9875\u5b8c\u6210\u626b\u7801\u6216\u77ed\u4fe1\u9a8c\u8bc1\u3002" if close_ok else "\u65e7\u4f1a\u8bdd\u5173\u95ed\u672a\u5b8c\u5168\u786e\u8ba4\uff0c\u4f46\u53ef\u91cd\u65b0\u6253\u5f00\u6388\u6743\u5e76\u7531\u7cfb\u7edf\u7ee7\u7eed\u8f6e\u8be2\u3002",
        "generatedAt": now(),
    }, 200 if close_ok else 409


def recover_account_authorization(org_id, body, user=None):
    org_id = normalize_org_id(org_id)
    body = body if isinstance(body, dict) else {}
    account_id = (body.get("centralAccountId") or body.get("accountId") or "douyin-self").strip() or "douyin-self"
    node_id = (body.get("preferredNode") or body.get("nodeId") or "").strip()
    session_ref = (body.get("sessionId") or body.get("id") or body.get("sessionRef") or "").strip()
    dry_run = bool(body.get("dryRun"))
    recovery_id = "authrec-" + uuid.uuid4().hex[:12]
    try:
        before = cloud_login_session_watchdog(org_id, limit=50)
    except Exception as exc:
        before = {"ok": False, "error": str(exc), "sessions": [], "counts": {}}
    selected = None
    sessions = before.get("sessions") or []
    refs = account_ref_candidates(account_id)
    if session_ref:
        selected = find_cloud_login_session(org_id, session_ref)
    if not selected:
        preferred_status = ("stale", "failed", "active", "running", "logged_in")
        for st in preferred_status:
            for sess in sessions:
                if not isinstance(sess, dict) or sess.get("status") != st:
                    continue
                sess_refs = account_ref_candidates(sess.get("accountId") or "")
                node_match = (not node_id) or (not sess.get("nodeId")) or sess.get("nodeId") == node_id
                acct_match = (not refs) or (sess_refs and (refs & sess_refs)) or account_id in ("douyin-self", "")
                if node_match and acct_match:
                    selected = sess
                    break
            if selected:
                break
    if selected:
        account_id = selected.get("accountId") or account_id
        node_id = selected.get("nodeId") or node_id
        session_ref = selected.get("id") or selected.get("sessionId") or session_ref
    query = {"resume": "1", "orgId": org_id, "accountId": account_id}
    if node_id:
        query["nodeId"] = node_id
    login_path = "/login-douyin.html?" + urlencode(query)
    watch_query = {"accountId": account_id}
    if node_id:
        watch_query["nodeId"] = node_id
    if session_ref:
        watch_query["sessionRef"] = session_ref
    watch_path = "/api/accounts/authorization-watch?" + urlencode(watch_query)
    if dry_run:
        return {
            "ok": True,
            "dryRun": True,
            "recoveryId": recovery_id,
            "orgId": org_id,
            "accountId": account_id,
            "nodeId": node_id,
            "selectedSession": {k: (selected or {}).get(k) for k in ("id", "sessionIdShort", "accountId", "nodeId", "status", "idleSec")},
            "loginPath": login_path,
            "watchPath": watch_path,
            "headline": "\u6388\u6743\u6062\u590d\u9884\u68c0\u5df2\u751f\u6210",
            "message": "\u5df2\u751f\u6210\u5ba2\u6237\u6388\u6743\u6062\u590d\u5165\u53e3\uff0c\u672a\u5173\u95ed\u4efb\u4f55\u4f1a\u8bdd\u3002",
            "nextAction": {"action": "open_login", "label": "\u6253\u5f00\u6388\u6743\u9875", "url": login_path},
            "before": {"status": before.get("status"), "counts": before.get("counts")},
            "generatedAt": now(),
        }, 200
    restart_body = dict(body)
    restart_body.update({"orgId": org_id, "accountId": account_id, "centralAccountId": account_id, "nodeId": node_id, "preferredNode": node_id, "waitSec": body.get("waitSec") or 12})
    if session_ref:
        restart_body["sessionId"] = session_ref
        restart_body["id"] = session_ref
    restart_payload, restart_status = restart_account_authorization(org_id, restart_body, user=user)
    try:
        after = cloud_login_session_watchdog(org_id, limit=50)
    except Exception as exc:
        after = {"ok": False, "error": str(exc), "sessions": [], "counts": {}}
    ok = bool(isinstance(restart_payload, dict) and restart_payload.get("loginPath"))
    status = 200 if ok else (restart_status if isinstance(restart_status, int) else 500)
    payload = {
        "ok": ok,
        "dryRun": False,
        "recoveryId": recovery_id,
        "orgId": org_id,
        "accountId": (restart_payload or {}).get("accountId") or account_id,
        "nodeId": (restart_payload or {}).get("nodeId") or node_id,
        "selectedSession": (restart_payload or {}).get("selectedSession") or {k: (selected or {}).get(k) for k in ("id", "sessionIdShort", "accountId", "nodeId", "status")},
        "closed": bool((restart_payload or {}).get("closed")),
        "closeStatus": (restart_payload or {}).get("closeStatus"),
        "loginPath": (restart_payload or {}).get("loginPath") or login_path,
        "watchPath": (restart_payload or {}).get("watchPath") or watch_path,
        "headline": "\u5df2\u751f\u6210\u65b0\u6388\u6743\u5165\u53e3" if ok else "\u6388\u6743\u6062\u590d\u672a\u5b8c\u6210",
        "message": (restart_payload or {}).get("message") or "\u8bf7\u5728\u65b0\u6253\u5f00\u7684\u6388\u6743\u9875\u5b8c\u6210\u626b\u7801\u6216\u77ed\u4fe1\u9a8c\u8bc1\u3002",
        "nextAction": {"action": "open_login", "label": "\u6253\u5f00\u6388\u6743\u9875", "url": (restart_payload or {}).get("loginPath") or login_path},
        "before": {"status": before.get("status"), "counts": before.get("counts")},
        "after": {"status": after.get("status"), "counts": after.get("counts")},
        "restart": audit_safe_body(restart_payload if isinstance(restart_payload, dict) else {}),
        "generatedAt": now(),
    }
    if not ok:
        payload["error"] = (restart_payload or {}).get("error") or "authorization_recovery_failed"
    return payload, status


# P2.02 centralized account authorization finish endpoint.
def finish_cloud_login_session(org_id, body, user=None):
    org_id = normalize_org_id(org_id)
    body = body if isinstance(body, dict) else {}
    session_id = (body.get("sessionId") or "").strip()
    account_id = (body.get("centralAccountId") or body.get("accountId") or "douyin-self").strip() or "douyin-self"
    node_id = (body.get("preferredNode") or body.get("nodeId") or "").strip()
    try:
        wait_sec = max(5, min(60, float(body.get("waitSec") or 30)))
    except Exception:
        wait_sec = 30
    if not session_id:
        flow = cloud_login_flow_state(org_id, account_id=account_id, node_id=node_id)
        auth_status = account_authorization_status(org_id, account_id=account_id, node_id=node_id)
        return {"ok": False, "error": "missing_session_id", "flow": flow, "authorization": auth_status}, 400
    status_body = {
        "orgId": org_id,
        "sessionId": session_id,
        "nodeId": node_id,
        "preferredNode": node_id,
        "accountId": account_id.split(":", 1)[-1],
        "centralAccountId": account_id,
        "waitSec": wait_sec,
    }
    status_result, status_code, status_task = dispatch_task_sync("/api/cloud-login/status", dict(status_body))
    logged_in = bool(isinstance(status_result, dict) and status_result.get("loggedIn"))
    if status_code >= 400 or not logged_in:
        flow = cloud_login_flow_state(org_id, account_id=account_id, node_id=node_id, session_ref=session_id)
        return {
            "ok": False,
            "error": "login_not_detected" if status_code < 400 else (status_result.get("error") if isinstance(status_result, dict) else "status_failed"),
            "loggedIn": logged_in,
            "status": status_code,
            "statusResult": status_result if isinstance(status_result, dict) else {},
            "statusTask": public_task(status_task),
            "flow": flow,
        }, 409 if status_code < 400 else status_code
    close_body = dict(status_body)
    close_body["force"] = True
    close_result, close_code, close_task = dispatch_task_sync("/api/cloud-login/close", close_body)
    cleared = clear_action_snoozes_for_resource(org_id, account_id=account_id, node_id=node_id or ((close_task or {}).get("nodeId") if close_task else ""))
    detail = account_detail(account_id, org_id) if account_id else None
    flow = cloud_login_flow_state(org_id, account_id=account_id, node_id=node_id, session_ref=session_id)
    auth_status = account_authorization_status(org_id, account_id=account_id, node_id=node_id, session_ref=session_id)
    ok = close_code < 400 and bool(close_result.get("ok", True) if isinstance(close_result, dict) else True)
    return {
        "ok": ok,
        "loggedIn": True,
        "accountId": account_id,
        "nodeId": node_id or ((close_task or {}).get("nodeId") if close_task else ""),
        "statusResult": status_result,
        "statusTask": public_task(status_task),
        "closeResult": close_result if isinstance(close_result, dict) else {},
        "closeStatus": close_code,
        "closeTask": public_task(close_task),
        "clearedActionSnoozes": cleared.get("cleared", 0),
        "account": detail,
        "flow": flow,
        "authorization": auth_status,
        "message": "\u767b\u5f55\u72b6\u6001\u5df2\u4fdd\u5b58\uff0c\u6b63\u5728\u7b49\u5f85\u8282\u70b9\u540c\u6b65\u8d26\u53f7\u8d44\u4ea7\u3002" if ok else "\u767b\u5f55\u5df2\u68c0\u6d4b\uff0c\u4f46\u5173\u95ed\u4f1a\u8bdd\u672a\u5b8c\u5168\u6210\u529f\uff0c\u8bf7\u5237\u65b0\u8d26\u53f7\u72b6\u6001\u3002",
    }, 200 if ok else 207



def bulk_close_cloud_login_sessions(org_id, statuses=None, limit=20, wait_sec=8, dry_run=False, node_id=""):
    org_id = normalize_org_id(org_id)
    node_id = (node_id or "").strip()
    statuses = statuses or ["stale", "failed"]
    if isinstance(statuses, str):
        statuses = [x.strip() for x in statuses.split(",") if x.strip()]
    allowed = {"stale", "failed"}
    statuses = [s for s in statuses if s in allowed] or ["stale", "failed"]
    try:
        limit = min(50, max(1, int(limit or 20)))
    except Exception:
        limit = 20
    try:
        wait_sec = max(1, min(30, float(wait_sec or 8)))
    except Exception:
        wait_sec = 8
    data = cloud_login_sessions(org_id, limit=100)
    candidates = [s for s in data.get("sessions") or [] if s.get("status") in statuses and s.get("canClose") and s.get("sessionId")]
    if node_id:
        candidates = [s for s in candidates if (s.get("nodeId") or "") == node_id]
    candidates = candidates[:limit]
    results = []
    ok_count = 0
    failed = 0
    for sess in candidates:
        if dry_run:
            results.append({
                "id": sess.get("id"),
                "sessionIdShort": sess.get("sessionIdShort"),
                "accountId": sess.get("accountId"),
                "nodeId": sess.get("nodeId"),
                "status": sess.get("status"),
                "closed": False,
                "dryRun": True,
                "error": "",
                "taskId": "",
            })
            continue
        payload, status = close_cloud_login_session(org_id, sess.get("id") or sess.get("sessionId"), wait_sec=wait_sec)
        ok = bool(payload.get("ok")) and status < 400
        if ok:
            ok_count += 1
        else:
            failed += 1
        results.append({
            "id": sess.get("id"),
            "sessionIdShort": sess.get("sessionIdShort"),
            "accountId": sess.get("accountId"),
            "nodeId": sess.get("nodeId"),
            "status": sess.get("status"),
            "closed": ok,
            "error": payload.get("error") or ((payload.get("result") or {}).get("error") if isinstance(payload.get("result"), dict) else ""),
            "taskId": ((payload.get("task") or {}).get("id") if isinstance(payload.get("task"), dict) else ""),
        })
    add_event("cloud_login_sessions_cleanup", {"orgId": org_id, "nodeId": node_id, "statuses": statuses, "matched": len(candidates), "closed": ok_count, "failed": failed, "dryRun": bool(dry_run)})
    return {"ok": failed == 0, "orgId": org_id, "nodeId": node_id, "statuses": statuses, "matched": len(candidates), "closed": ok_count, "failed": failed, "dryRun": bool(dry_run), "results": results}, 200 if failed == 0 else 207


def auth_diagnosis(org_id, account_id="", node_id=""):
    org_id = normalize_org_id(org_id)
    account_id = (account_id or "").strip()
    node_id = (node_id or "").strip()
    asset = find_account_asset(account_id, org_id) if account_id else None
    if asset and not node_id:
        node_id = asset.get("nodeId") or node_id
    with LOCK:
        raw_node = (STATE.get("nodes") or {}).get(node_id) if node_id else None
        nodes = [public_node(n) for n in (STATE.get("nodes") or {}).values() if item_org_id(n) == org_id]
        tasks = [dict(t) for t in (STATE.get("tasks") or {}).values() if item_org_id(t) == org_id and "cloud-login" in (t.get("path") or "")]
    if node_id:
        tasks = [t for t in tasks if (t.get("nodeId") == node_id or (t.get("body") or {}).get("preferredNode") == node_id or (t.get("body") or {}).get("nodeId") == node_id)]
    if account_id:
        account_candidates = {account_id, account_id.split(":", 1)[-1] if ":" in account_id else account_id}
        tasks = [t for t in tasks if ((t.get("body") or {}).get("accountId") in account_candidates or (t.get("body") or {}).get("centralAccountId") == account_id)] or tasks
    tasks = sorted(tasks, key=lambda x: x.get("updatedAt") or x.get("createdAt") or 0, reverse=True)[:8]
    node = public_node(raw_node) if raw_node else None
    online_nodes_count = len([n for n in nodes if n.get("online")])
    recent_failed = next((t for t in tasks if t.get("status") == "failed"), None)
    running = next((t for t in tasks if t.get("status") in ("queued", "running")), None)
    code = "ready_for_auth"
    summary = "\u53ef\u4ee5\u5f00\u59cb\u6388\u6743\u3002"
    severity = "info"
    suggestions = ["\u70b9\u51fb\u5f00\u59cb\u6388\u6743\uff0c\u5b8c\u6210\u626b\u7801\u6216\u77ed\u4fe1\u9a8c\u8bc1\u3002"]
    if online_nodes_count <= 0:
        code = "no_online_node"
        severity = "critical"
        summary = "\u5f53\u524d\u4f01\u4e1a\u6ca1\u6709\u5728\u7ebf\u6267\u884c\u8282\u70b9\u3002"
        suggestions = ["\u68c0\u67e5\u4e91\u670d\u52a1\u5668\u4e0a\u7684 matrix-node-api \u548c matrix-worker \u662f\u5426\u5728\u8fd0\u884c\u3002", "\u7b49\u8282\u70b9\u6062\u590d\u540e\u518d\u8fdb\u884c\u6388\u6743\u3002"]
    elif node_id and (not node or not node.get("online")):
        code = "target_node_offline"
        severity = "critical"
        summary = "\u6307\u5b9a\u7684\u6267\u884c\u8282\u70b9\u79bb\u7ebf\u3002"
        suggestions = ["\u68c0\u67e5\u8be5\u8282\u70b9\u8fdb\u7a0b\u548c\u670d\u52a1\u5668\u7f51\u7edc\u3002", "\u4e5f\u53ef\u5148\u53bb\u6389\u8282\u70b9\u9650\u5b9a\uff0c\u8ba9\u7cfb\u7edf\u81ea\u52a8\u5206\u914d\u5728\u7ebf\u8282\u70b9\u3002"]
    elif running:
        code = "auth_session_in_progress"
        severity = "warning"
        summary = "\u5df2\u6709\u6388\u6743\u4f1a\u8bdd\u6216\u6388\u6743\u4efb\u52a1\u5728\u6267\u884c\u3002"
        suggestions = ["\u5148\u70b9\u51fb\u6062\u590d\u4f1a\u8bdd\u67e5\u770b\u753b\u9762\u3002", "\u5982\u679c\u753b\u9762\u5361\u6b7b\uff0c\u518d\u70b9\u51fb\u91cd\u65b0\u5f00\u59cb\u521b\u5efa\u65b0\u4f1a\u8bdd\u3002"]
    elif asset and asset.get("usable"):
        code = "account_usable"
        severity = "info"
        summary = "\u8d26\u53f7\u5df2\u53ef\u7528\uff0c\u8282\u70b9\u5728\u7ebf\u4e14 Cookie \u6709\u6548\u3002"
        suggestions = ["\u53ef\u76f4\u63a5\u8fd4\u56de\u7cfb\u7edf\u6267\u884c\u53d1\u5e03\u3001\u641c\u7d22\u6216\u91c7\u96c6\u4efb\u52a1\u3002"]
    elif account_id and not asset:
        code = "account_not_registered"
        severity = "info"
        summary = "\u4e2d\u5fc3\u6682\u672a\u767b\u8bb0\u8be5\u8d26\u53f7\u8d44\u4ea7\u3002"
        suggestions = ["\u8fd9\u901a\u5e38\u8868\u793a\u9996\u6b21\u6388\u6743\uff0c\u8bf7\u7ee7\u7eed\u626b\u7801\u6216\u77ed\u4fe1\u767b\u5f55\u3002"]
    elif recent_failed:
        code = "last_auth_task_failed"
        severity = "warning"
        summary = "\u6700\u8fd1\u4e00\u6b21\u6388\u6743\u4efb\u52a1\u5931\u8d25\u3002"
        suggestions = ["\u70b9\u51fb\u91cd\u65b0\u5f00\u59cb\u91cd\u5efa\u4f1a\u8bdd\u3002", "\u5982\u679c\u591a\u6b21\u5931\u8d25\uff0c\u68c0\u67e5\u8282\u70b9\u6d4f\u89c8\u5668\u662f\u5426\u88ab\u5360\u7528\u6216\u88ab\u98ce\u63a7\u3002"]
    elif asset and not asset.get("cookieReady"):
        code = "cookie_unavailable"
        severity = "warning"
        summary = "\u8d26\u53f7 Cookie \u4e0d\u53ef\u7528\uff0c\u9700\u8981\u91cd\u65b0\u6388\u6743\u3002"
        suggestions = ["\u4f7f\u7528\u5f53\u524d\u9875\u9762\u5b8c\u6210\u626b\u7801\u6216\u63a5\u6536\u77ed\u4fe1\u9a8c\u8bc1\u7801\u3002"]
    if asset:
        repair_sla = account_repair_sla(asset)
    elif node_id and node and not node.get("online"):
        repair_sla = account_repair_sla({"id": account_id, "nodeId": node_id, "online": False, "cookieReady": False, "updatedAt": now()})
    else:
        repair_sla = account_repair_sla({})
    return {
        "ok": True,
        "orgId": org_id,
        "accountId": account_id,
        "nodeId": node_id,
        "code": code,
        "severity": severity,
        "summary": summary,
        "suggestions": suggestions,
        "repairSla": repair_sla,
        "handoffNote": repair_sla.get("handoffNote") or (suggestions[0] if suggestions else ""),
        "account": asset,
        "node": node,
        "onlineNodes": online_nodes_count,
        "recentTasks": [public_task(t) for t in tasks],
    }


def reset_publish_runtime_day():
    day = today_key()
    if PUBLISH_RT.get("day") != day:
        PUBLISH_RT["day"] = day
        PUBLISH_RT["counts"] = {}
        PUBLISH_RT["last_ts_by_org"] = {}


def publish_count_for(org_id, account_id):
    reset_publish_runtime_day()
    return int(PUBLISH_RT.get("counts", {}).get(normalize_org_id(org_id) + ":" + (account_id or "douyin-self"), 0) or 0)


def record_publish_success(org_id, account_id):
    reset_publish_runtime_day()
    key = normalize_org_id(org_id) + ":" + (account_id or "douyin-self")
    PUBLISH_RT.setdefault("counts", {})[key] = int(PUBLISH_RT.get("counts", {}).get(key, 0) or 0) + 1
    PUBLISH_RT["last_ts"] = now()
    PUBLISH_RT.setdefault("last_ts_by_org", {})[normalize_org_id(org_id)] = PUBLISH_RT["last_ts"]


def queued_count_for(org_id, account_id):
    org_id = normalize_org_id(org_id)
    return len([
        q for q in load_queue(org_id)
        if q.get("accountId") == account_id and q.get("status") in ("pending", "running")
    ])


def material_ready(mid, org_id):
    m = find_material(mid, org_id)
    if not m:
        return None, "material_not_found"
    files = m.get("files") or []
    if not files:
        return m, "material_empty"
    try:
        base = material_dir(mid)
        for fn in files:
            fp = os.path.normpath(os.path.join(base, safe_filename(fn, "file")))
            if not os.path.isfile(fp):
                return m, "material_file_missing"
    except Exception:
        return m, "material_file_missing"
    return m, ""


def publish_preflight(org_id, account_id, material_id, mode="publish", dry_run=False):
    org_id = normalize_org_id(org_id)
    account_id = (account_id or "").strip()
    material_id = (material_id or "").strip()
    errors = []
    warnings = []
    material, m_err = material_ready(material_id, org_id)
    if m_err:
        errors.append(m_err)
    blocker = xhs_note_replacement.image_note_publish_blocker(material or {})
    if blocker:
        errors.append(blocker)
    asset = find_account_asset(account_id, org_id)
    auth_diag = auth_diagnosis(org_id, account_id=account_id, node_id=(asset or {}).get("nodeId") or "") if account_id else {}
    auth_support_ref = "authdiag-" + _short_hash(json.dumps({"orgId": org_id, "accountId": account_id, "nodeId": (asset or {}).get("nodeId"), "code": auth_diag.get("code")}, ensure_ascii=False, sort_keys=True)) if account_id else ""
    account_auth = {
        "ready": bool(asset and asset.get("usable")),
        "code": auth_diag.get("code") or "account_not_selected",
        "severity": auth_diag.get("severity") or "warning",
        "summary": auth_diag.get("summary") or "",
        "suggestions": auth_diag.get("suggestions") or [],
        "handoffNote": auth_diag.get("handoffNote") or "",
        "supportRef": auth_support_ref,
        "nextAction": "use_account" if asset and asset.get("usable") else ("repair_node" if auth_diag.get("code") in ("no_online_node", "target_node_offline") else "authorize_account"),
    }
    a_err = account_unusable_reason(asset)
    if a_err:
        errors.append(a_err)
    settings = load_settings(org_id)
    if not settings.get("enabled"):
        warnings.append("publish_disabled")
    per_day = int(settings.get("perAccountPerDay", 1) or 1)
    done_today = publish_count_for(org_id, account_id)
    queued = queued_count_for(org_id, account_id)
    quota_used = done_today + (queued if mode == "queue" else 0)
    if not dry_run and per_day > 0 and quota_used >= per_day:
        errors.append("account_daily_quota_exceeded")
    return {
        "ok": not errors,
        "orgId": org_id,
        "mode": mode,
        "dryRun": bool(dry_run),
        "errors": errors,
        "warnings": warnings,
        "error": errors[0] if errors else "",
        "account": asset,
        "accountAuthorization": account_auth,
        "authDiagnosis": auth_diag,
        "material": public_material(material) if material else None,
        "settings": settings,
        "quota": {
            "perDay": per_day,
            "doneToday": done_today,
            "queued": queued,
            "remaining": max(0, per_day - quota_used) if per_day > 0 else 999999,
        },
        "canQueue": not errors,
        "canPublish": not errors,
    }


def online_nodes(org_id=None):
    org_id = normalize_org_id(org_id) if org_id else None
    with LOCK:
        return [
            public_node(n)
            for n in (STATE.get("nodes") or {}).values()
            if now() - float(n.get("lastSeen") or 0) <= NODE_TIMEOUT_SEC
            and (not org_id or item_org_id(n) == org_id)
        ]


def task_requires_node_cookie(path, body=None):
    path = str(path or "")
    body = body or {}
    platform = str(body.get("platform") or body.get("pf") or body.get("sourcePlatform") or "").strip().lower()
    if path.startswith("/api/cloud-login/"):
        return False
    if path in ("/api/xhs/search", "/api/xhs/comments", "/api/xhs/download"):
        return False
    if path == "/api/finder/discover" and platform in ("xhs", "xiaohongshu", "rednote", "小红书"):
        return False
    # XHS outreach/comment/publish still needs a browser profile, but not the
    # Douyin cookieReady flag.  Platform profile readiness is checked by the
    # local execution node/account registry.
    if path in ("/api/outreach/run", "/api/xhs/comment/publish") and platform in ("xhs", "xiaohongshu", "rednote", "小红书"):
        return False
    return True


def pick_node(task=None):
    task_body = (task or {}).get("body") or {}
    org_id = normalize_org_id(task_body.get("orgId")) if task_body.get("orgId") else None
    nodes = online_nodes(org_id)
    path = (task or {}).get("path") or ""
    if task_requires_node_cookie(path, task_body):
        nodes = [n for n in nodes if n.get("cookieReady")]
    nodes = [n for n in nodes if not (n.get("capacity") or {}).get("paused")]
    if not nodes:
        return None
    ts = now()
    def _node_sort_key(n):
        cap = n.get("capacity") or node_capacity_snapshot(n.get("id"))
        cooldown_until = float(cap.get("cooldownUntil") or 0)
        cooling = 1 if cooldown_until > ts else 0
        at_capacity = 1 if int(cap.get("running") or 0) >= int(cap.get("maxConcurrency") or 1) else 0
        return (cooling, cooldown_until if cooling else 0, at_capacity, int(cap.get("running") or 0), int(cap.get("queued") or 0), 1 if n.get("busy") else 0, -(n.get("lastSeen") or 0))
    nodes.sort(key=_node_sort_key)
    return nodes[0]


def create_task(path, method="POST", body=None, wait_sec=None, preferred_node=None):
    recover_stale_tasks(normalize_org_id((body or {}).get("orgId")), dry_run=False, limit=50)
    tid = uuid.uuid4().hex
    if wait_sec is None:
        wait_sec = TASK_WAIT_LONG if path in LONG_TASK_PATHS else TASK_WAIT_DEFAULT
    if is_billable_task_path(path):
        quota_block = quota_guard(normalize_org_id((body or {}).get("orgId")), "tasksPerDay", 1)
        if quota_block:
            return None, quota_block, 429
    node = None
    if preferred_node:
        with LOCK:
            n = (STATE.get("nodes") or {}).get(preferred_node)
            if n and now() - float(n.get("lastSeen") or 0) <= NODE_TIMEOUT_SEC:
                node = public_node(n)
    node = node or pick_node({"path": path, "body": body or {}})
    if not node:
        org_id = normalize_org_id((body or {}).get("orgId")) if (body or {}).get("orgId") else None
        base_nodes = [n for n in online_nodes(org_id) if not (n.get("capacity") or {}).get("paused")]
        if task_requires_node_cookie(path, body or {}) and base_nodes:
            return None, {
                "ok": False,
                "needLogin": True,
                "platform": "douyin",
                "error": "account_cookie_unavailable",
                "message": "执行节点在线，但抖音账号未授权或 Cookie 已失效；请先到账号矩阵完成抖音授权。",
            }, 401
        return None, {"ok": False, "error": "no_online_node", "message": "没有可用执行节点：请先启动至少一个节点 Agent 并完成抖音登录"}, 503
    # Login screenshots are disposable UI frames.  When an operator clicks an
    # interactive control (SMS/click/type/key), stale screenshot tasks must not
    # block the action for tens of seconds.
    if path in INTERACTIVE_TASK_PATHS:
        with LOCK:
            for old in (STATE.get("tasks") or {}).values():
                if (
                    old.get("status") == "queued"
                    and old.get("path") == "/api/cloud-login/screenshot"
                    and old.get("nodeId") == node.get("id")
                ):
                    old["status"] = "failed"
                    old["error"] = "superseded_by_interactive_login_action"
                    old["updatedAt"] = now()
    task = {
        "id": tid,
        "path": path,
        "method": method,
        "body": body or {},
        "orgId": normalize_org_id((body or {}).get("orgId")),
        "status": "queued",
        "nodeId": node.get("id"),
        "createdAt": now(),
        "updatedAt": now(),
        "waitSec": wait_sec,
        "result": None,
        "error": None,
    }
    with LOCK:
        STATE.setdefault("tasks", {})[tid] = task
    add_event("task_created", {"taskId": tid, "path": path, "nodeId": task["nodeId"]})
    persist()
    return task, None, 200


def wait_task(task_id, timeout_sec):
    deadline = now() + max(0.1, float(timeout_sec or TASK_WAIT_DEFAULT))
    while now() < deadline:
        with LOCK:
            task = (STATE.get("tasks") or {}).get(task_id) or {}
            status = task.get("status")
            if status in ("done", "failed"):
                return task
        time.sleep(0.5)
    with LOCK:
        return (STATE.get("tasks") or {}).get(task_id) or {}



def task_age_meta(task, ts=None):
    ts = ts or now()
    task = task or {}
    try:
        wait_sec = max(1.0, float(task.get("waitSec") or TASK_WAIT_DEFAULT))
    except Exception:
        wait_sec = TASK_WAIT_DEFAULT
    created = float(task.get("createdAt") or task.get("updatedAt") or ts)
    started = float(task.get("startedAt") or created)
    status = task.get("status") or "queued"
    base = started if status == "running" else created
    age = max(0.0, ts - base)
    running_limit = max(180.0, wait_sec + TASK_RECOVERY_GRACE_SEC, wait_sec * 1.25)
    queued_limit = max(TASK_QUEUED_MAX_SEC, wait_sec * 2.0)
    if task.get("path") == "/api/cloud-login/screenshot":
        queued_limit = min(queued_limit, 120.0)
    return {"waitSec": wait_sec, "ageSec": age, "runningLimitSec": running_limit, "queuedLimitSec": queued_limit, "createdAt": created, "startedAt": started}


def node_online_raw(node_id, ts=None):
    if not node_id:
        return False
    ts = ts or now()
    with LOCK:
        n = (STATE.get("nodes") or {}).get(node_id) or {}
    return bool(n and ts - float(n.get("lastSeen") or 0) <= NODE_TIMEOUT_SEC)


def task_recovery_candidates(org_id=None, limit=50):
    org_id = normalize_org_id(org_id) if org_id else None
    ts = now()
    rows = []
    counts = {"runningStale": 0, "queuedAged": 0, "offlineAssigned": 0, "disposableExpired": 0, "total": 0}
    with LOCK:
        tasks = [dict(t) for t in (STATE.get("tasks") or {}).values()]
        nodes = {k: dict(v) for k, v in (STATE.get("nodes") or {}).items()}
    if org_id:
        tasks = [t for t in tasks if item_org_id(t) == org_id]
    for t in tasks:
        st = t.get("status") or ""
        if st not in ("running", "queued"):
            continue
        meta = task_age_meta(t, ts)
        node_id = t.get("nodeId") or ""
        node = nodes.get(node_id) or {}
        node_online = bool(node_id and node and ts - float(node.get("lastSeen") or 0) <= NODE_TIMEOUT_SEC)
        reasons = []
        action = "observe"
        if st == "running" and meta["ageSec"] > meta["runningLimitSec"]:
            reasons.append("running_stale")
            counts["runningStale"] += 1
            action = "release_running"
        if st == "queued":
            if node_id and not node_online:
                reasons.append("assigned_node_offline")
                counts["offlineAssigned"] += 1
                action = "reassign_queued"
            if meta["ageSec"] > meta["queuedLimitSec"]:
                reasons.append("queued_aged")
                counts["queuedAged"] += 1
                if t.get("path") == "/api/cloud-login/screenshot":
                    reasons.append("disposable_expired")
                    counts["disposableExpired"] += 1
                    action = "expire_disposable"
        if not reasons:
            continue
        counts["total"] += 1
        rows.append({
            "taskId": t.get("id"),
            "path": t.get("path") or "",
            "type": task_type_key(t.get("path") or ""),
            "status": st,
            "nodeId": node_id,
            "nodeOnline": node_online,
            "ageSec": int(meta["ageSec"]),
            "limitSec": int(meta["runningLimitSec"] if st == "running" else meta["queuedLimitSec"]),
            "reasons": reasons,
            "action": action,
            "createdAt": t.get("createdAt"),
            "updatedAt": t.get("updatedAt"),
            "startedAt": t.get("startedAt"),
        })
    rows = sorted(rows, key=lambda x: (0 if x.get("status") == "running" else 1, -float(x.get("ageSec") or 0)))
    return {"ok": True, "orgId": org_id or "all", "generatedAt": ts, "counts": counts, "items": rows[:limit]}


def release_node_if_idle(node_id):
    if not node_id:
        return
    with LOCK:
        running = any(t.get("status") == "running" and t.get("nodeId") == node_id for t in (STATE.get("tasks") or {}).values())
        if node_id in (STATE.get("nodes") or {}) and not running:
            STATE["nodes"][node_id]["busy"] = False
            STATE["nodes"][node_id]["lastFinishedAt"] = now()


def recover_stale_tasks(org_id=None, dry_run=False, limit=100, force=False, node_id=""):
    org_id = normalize_org_id(org_id) if org_id else None
    node_id = (node_id or "").strip()
    snapshot = task_recovery_candidates(org_id, limit=limit)
    if node_id:
        snapshot = filter_recovery_snapshot_for_node(snapshot, node_id) if "filter_recovery_snapshot_for_node" in globals() else snapshot
    changed = []
    if dry_run:
        snapshot["dryRun"] = True
        snapshot["changed"] = []
        return snapshot
    ts = now()
    for row in snapshot.get("items") or []:
        if len(changed) >= max(1, int(limit or 100)):
            break
        task_id = row.get("taskId") or ""
        action = row.get("action") or "observe"
        with LOCK:
            cur = (STATE.get("tasks") or {}).get(task_id)
            if not cur or cur.get("status") not in ("running", "queued"):
                continue
            cur_org = item_org_id(cur)
            if org_id and cur_org != org_id:
                continue
            old_node = cur.get("nodeId") or ""
            if action == "release_running" or (force and cur.get("status") == "running"):
                cur["status"] = "failed"
                cur["error"] = "task_stale_timeout"
                cur["result"] = cur.get("result") or {"ok": False, "error": "task_stale_timeout"}
                cur["finishedAt"] = ts
                cur["updatedAt"] = ts
                cur["recovery"] = {"action": "release_running", "recoveredAt": ts, "oldNodeId": old_node, "reasons": row.get("reasons") or []}
                changed.append({"taskId": task_id, "action": "release_running", "oldNodeId": old_node})
            elif action == "expire_disposable" or (force and cur.get("status") == "queued" and cur.get("path") == "/api/cloud-login/screenshot"):
                cur["status"] = "failed"
                cur["error"] = "stale_disposable_task"
                cur["updatedAt"] = ts
                cur["finishedAt"] = ts
                cur["recovery"] = {"action": "expire_disposable", "recoveredAt": ts, "oldNodeId": old_node, "reasons": row.get("reasons") or []}
                changed.append({"taskId": task_id, "action": "expire_disposable", "oldNodeId": old_node})
            elif action == "reassign_queued" or (force and cur.get("status") == "queued"):
                new_node = pick_node(cur)
                if new_node and new_node.get("id") and new_node.get("id") != old_node:
                    cur["nodeId"] = new_node.get("id")
                    cur["updatedAt"] = ts
                    cur["recovery"] = {"action": "reassign_queued", "recoveredAt": ts, "oldNodeId": old_node, "newNodeId": new_node.get("id"), "reasons": row.get("reasons") or []}
                    changed.append({"taskId": task_id, "action": "reassign_queued", "oldNodeId": old_node, "newNodeId": new_node.get("id")})
                else:
                    cur["recoveryReason"] = "waiting_for_available_node"
                    if not cur.get("firstRecoverySeenAt"):
                        cur["firstRecoverySeenAt"] = ts
                    changed.append({"taskId": task_id, "action": "mark_waiting", "oldNodeId": old_node})
    for item in changed:
        release_node_if_idle(item.get("oldNodeId"))
        add_queue_event_for_task(item.get("taskId"), "task_recovered", {"action": item.get("action"), "oldNodeId": item.get("oldNodeId"), "newNodeId": item.get("newNodeId")})
    if changed:
        add_event("task_recovery", {"orgId": org_id or "all", "changed": len(changed), "items": changed[:20]})
        persist()
    fresh = task_recovery_candidates(org_id, limit=limit)
    fresh["changed"] = changed
    fresh["dryRun"] = False
    return fresh



def filter_recovery_snapshot_for_node(snapshot, node_id):
    node_id = (node_id or "").strip()
    if not node_id:
        return snapshot
    items = [r for r in (snapshot.get("items") or []) if (r or {}).get("nodeId") == node_id]
    counts = {"runningStale": 0, "queuedAged": 0, "offlineAssigned": 0, "disposableExpired": 0, "total": len(items)}
    for r in items:
        reasons = set((r or {}).get("reasons") or [])
        if "running_stale" in reasons:
            counts["runningStale"] += 1
        if "queued_aged" in reasons:
            counts["queuedAged"] += 1
        if "assigned_node_offline" in reasons:
            counts["offlineAssigned"] += 1
        if "disposable_expired" in reasons:
            counts["disposableExpired"] += 1
    out = dict(snapshot or {})
    out["nodeId"] = node_id
    out["items"] = items
    out["counts"] = counts
    return out


def probe_node_local_api(local_api, timeout_sec=4):
    local_api = (local_api or "").strip()
    if not local_api:
        return {"ok": False, "checked": False, "error": "local_api_missing"}
    if not (local_api.startswith("http://") or local_api.startswith("https://")):
        return {"ok": False, "checked": False, "error": "local_api_invalid"}
    url = local_api.rstrip("/") + "/api/health"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=max(1, float(timeout_sec or 4))) as resp:
            raw = resp.read(1024 * 64).decode("utf-8", "replace")
            try:
                data = json.loads(raw)
            except Exception:
                data = {"raw": raw[:500]}
            return {"ok": bool(data.get("ok", resp.status < 400)), "checked": True, "status": resp.status, "url": url, "data": audit_safe_body(data)}
    except Exception as exc:
        return {"ok": False, "checked": True, "url": url, "error": public_error_text(str(exc))}


def node_runtime_probe(org_id, node_id="", action="probe", dry_run=False, limit=50, clean_sessions=False):
    org_id = normalize_org_id(org_id)
    node_id = (node_id or "").strip()
    action = (action or "probe").strip().lower()
    if action not in ("probe", "repair"):
        action = "probe"
    try:
        limit = min(100, max(1, int(limit or 50)))
    except Exception:
        limit = 50
    with LOCK:
        raw_node = dict((STATE.get("nodes") or {}).get(node_id) or {}) if node_id else {}
        tasks = [dict(t) for t in (STATE.get("tasks") or {}).values() if item_org_id(t) == org_id and (not node_id or (t.get("nodeId") or "") == node_id)]
    if not raw_node:
        return {"ok": False, "error": "node_not_found", "orgId": org_id, "nodeId": node_id}, 404
    if item_org_id(raw_node) != org_id:
        return {"ok": False, "error": "node_not_in_org", "orgId": org_id, "nodeId": node_id}, 403
    node = public_node(raw_node)
    cap = node_capacity_snapshot(node_id)
    recent_tasks = sorted(tasks, key=lambda x: x.get("updatedAt") or x.get("createdAt") or 0, reverse=True)[:20]
    status_counts = {}
    failed_runtime = 0
    for t in tasks:
        st = queue_task_status(t.get("status") or "")
        status_counts[st] = status_counts.get(st, 0) + 1
        if st == "failed" and task_failure_category(t).get("key") == "node_runtime":
            failed_runtime += 1
    recovery = filter_recovery_snapshot_for_node(task_recovery_candidates(org_id, limit=limit), node_id)
    sessions_data = cloud_login_sessions(org_id, limit=100)
    node_sessions = [s for s in (sessions_data.get("sessions") or []) if (s or {}).get("nodeId") == node_id]
    stale_sessions = [s for s in node_sessions if s.get("status") in ("stale", "failed") and s.get("canClose")]
    local_health = probe_node_local_api(node.get("localApi") or raw_node.get("localApi") or "")
    issues = []
    suggestions = []
    if not node.get("online"):
        issues.append("node_offline")
        suggestions.append("\u8282\u70b9\u79bb\u7ebf\uff1a\u68c0\u67e5 matrix-node-api / matrix-worker \u670d\u52a1\u548c\u5b89\u5168\u7ec4\u3002")
    if not local_health.get("ok"):
        issues.append("local_health_unavailable")
        suggestions.append("\u672c\u5730\u6267\u884c\u7aef health \u4e0d\u53ef\u7528\uff1a\u4f18\u5148\u68c0\u67e5\u8282\u70b9 API \u8fdb\u7a0b\u3002")
    if (cap or {}).get("paused"):
        issues.append("node_paused")
        suggestions.append("\u8282\u70b9\u5df2\u6682\u505c\uff1a\u9700\u7ba1\u7406\u5458\u6062\u590d\u540e\u624d\u80fd\u63a5\u5355\u3002")
    if (cap or {}).get("status") == "at_capacity":
        issues.append("node_at_capacity")
        suggestions.append("\u8282\u70b9\u5df2\u6ee1\u8f7d\uff1a\u7b49\u5f85\u5f53\u524d\u4efb\u52a1\u7ed3\u675f\u6216\u589e\u52a0\u5e76\u53d1\u4e0a\u9650\u3002")
    if int((cap or {}).get("cooldownRemainingSec") or 0) > 0:
        issues.append("node_cooldown")
        suggestions.append("\u8282\u70b9\u51b7\u5374\u4e2d\uff1a\u51b7\u5374\u7ed3\u675f\u540e\u518d\u5b89\u5168\u91cd\u8bd5\u3002")
    if int(((recovery.get("counts") or {}).get("total") or 0)) > 0:
        issues.append("stale_tasks")
        suggestions.append("\u5b58\u5728\u5361\u4f4f/\u8d85\u65f6\u4efb\u52a1\uff1a\u5148\u6062\u590d\u5361\u6b7b\u4efb\u52a1\uff0c\u518d\u91cd\u8bd5\u65b0\u4efb\u52a1\u3002")
    if stale_sessions:
        issues.append("stale_cloud_login_sessions")
        suggestions.append("\u5b58\u5728\u8fc7\u671f\u6388\u6743\u4f1a\u8bdd\uff1a\u5efa\u8bae\u6e05\u7406\u540e\u8ba9\u7528\u6237\u91cd\u65b0\u6388\u6743\u3002")
    if not node.get("cookieReady"):
        issues.append("cookie_unavailable")
        suggestions.append("Cookie \u4e0d\u53ef\u7528\uff1a\u53d1\u5e03/\u5bfb\u5ba2\u524d\u9700\u5b8c\u6210\u8d26\u53f7\u6388\u6743\u3002")
    severity = "critical" if ("node_offline" in issues or "local_health_unavailable" in issues) else ("warning" if issues else "info")
    repair_result = None
    session_cleanup = None
    if action == "repair":
        repair_result = recover_stale_tasks(org_id, dry_run=bool(dry_run), limit=limit, force=False, node_id=node_id)
        if clean_sessions or stale_sessions:
            session_cleanup, _cleanup_status = bulk_close_cloud_login_sessions(org_id, statuses=["stale", "failed"], limit=limit, wait_sec=8, dry_run=bool(dry_run), node_id=node_id)
    return {
        "ok": True,
        "orgId": org_id,
        "nodeId": node_id,
        "action": action,
        "dryRun": bool(dry_run),
        "generatedAt": now(),
        "severity": severity,
        "headline": "\u8282\u70b9\u9700\u5904\u7406" if issues else "\u8282\u70b9\u72b6\u6001\u6b63\u5e38",
        "message": suggestions[0] if suggestions else "\u672a\u53d1\u73b0\u8282\u70b9\u8fd0\u884c\u963b\u65ad\uff0c\u53ef\u8fdb\u5165\u4efb\u52a1\u4e2d\u5fc3\u6309\u5f52\u56e0\u91cd\u8bd5\u3002",
        "node": node,
        "capacity": cap,
        "localHealth": local_health,
        "issues": issues,
        "suggestions": suggestions,
        "statusCounts": status_counts,
        "failedRuntimeCount": failed_runtime,
        "recovery": recovery,
        "staleSessions": stale_sessions[:10],
        "recentTasks": [public_task(t) for t in recent_tasks[:8]],
        "repair": repair_result,
        "sessionCleanup": session_cleanup,
    }, 200


def prepare_task_body(path, body):
    body = dict(body or {})
    if path.startswith("/api/cloud-login/"):
        aid = (body.get("centralAccountId") or body.get("accountId") or "").strip()
        if ":" in aid:
            node_id, local_id = aid.split(":", 1)
            if node_id:
                body.setdefault("preferredNode", node_id)
            body["centralAccountId"] = aid
            body["accountId"] = local_id or "douyin-self"
    if path == "/api/publish/run":
        aid = (body.get("accountId") or "").strip()
        if ":" in aid:
            node_id, local_id = aid.split(":", 1)
            if node_id:
                body.setdefault("preferredNode", node_id)
            body["centralAccountId"] = aid
            body["accountId"] = local_id or "douyin-self"
        mid = (body.get("materialId") or "").strip()
        if mid and not body.get("centralMaterial"):
            mp = material_payload(mid, normalize_org_id(body.get("orgId")))
            if not mp:
                return None, {"ok": False, "error": "material_not_found"}, 404
            body["centralMaterial"] = mp
            body["centralMaterialId"] = mid
    return body, None, 200


def local_agent_headers():
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    tok = (os.getenv("LOCAL_AGENT_TOKEN") or os.getenv("MATRIX_AGENT_TOKEN") or os.getenv("DY_AGENT_TOKEN") or "").strip()
    if tok:
        h["X-Matrix-Agent-Token"] = tok
    return h


def record_direct_task(path, body, result, status_code, node_id, elapsed_sec):
    ts = now()
    tid = "direct-" + uuid.uuid4().hex
    result_for_state = strip_large_payloads(result if isinstance(result, dict) else {"result": result})
    ok = bool(status_code < 400 and (not isinstance(result, dict) or result.get("ok", True) is not False))
    task = {
        "id": tid,
        "path": path,
        "method": "POST",
        "body": body or {},
        "orgId": normalize_org_id((body or {}).get("orgId")),
        "status": "done" if ok else "failed",
        "nodeId": node_id,
        "createdAt": ts,
        "startedAt": ts,
        "finishedAt": ts,
        "updatedAt": ts,
        "waitSec": 0,
        "result": result_for_state,
        "error": "" if ok else (result.get("error") if isinstance(result, dict) else "direct_node_task_failed"),
        "directNodeProxy": True,
        "executionElapsedSec": round(float(elapsed_sec or 0), 3),
    }
    with LOCK:
        STATE.setdefault("tasks", {})[tid] = task
        if node_id in (STATE.get("nodes") or {}):
            STATE["nodes"][node_id]["lastSeen"] = ts
            STATE["nodes"][node_id]["lastFinishedAt"] = ts
            STATE["nodes"][node_id]["busy"] = False
    add_event("task_direct_proxy", {"taskId": tid, "path": path, "nodeId": node_id, "ok": ok})
    persist()
    return task


def dispatch_cloud_login_direct(path, prepared, preferred_node=""):
    if path not in DIRECT_CLOUD_LOGIN_PATHS:
        return None
    if (prepared or {}).get("useNodeQueue") is True or (prepared or {}).get("forceNodeQueue") is True:
        return None
    node_id = (preferred_node or (prepared or {}).get("preferredNode") or (prepared or {}).get("nodeId") or "").strip()
    raw_node = None
    if node_id:
        with LOCK:
            raw_node = dict((STATE.get("nodes") or {}).get(node_id) or {})
    if not raw_node:
        picked = pick_node({"path": path, "body": prepared or {}})
        node_id = (picked or {}).get("id") or ""
        if node_id:
            with LOCK:
                raw_node = dict((STATE.get("nodes") or {}).get(node_id) or {})
    if not raw_node:
        return None
    local_api = str(raw_node.get("localApi") or "").strip().rstrip("/")
    if not local_api:
        return None
    body = dict(prepared or {})
    # The node-local API only knows the local account id.  Keep centralAccountId
    # for audit, but ensure accountId is the local id after prepare_task_body().
    timeout_sec = 45.0 if path == "/api/cloud-login/start" else 15.0
    try:
        timeout_sec = float(body.get("directTimeoutSec") or timeout_sec)
    except Exception:
        pass
    started = now()
    url = local_api + path
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=local_agent_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=max(2.0, timeout_sec)) as resp:
                raw = resp.read(1024 * 1024 * 8).decode("utf-8", "replace")
                status_code = int(getattr(resp, "status", 200) or 200)
        except urllib.error.HTTPError as e:
            raw = e.read(1024 * 1024 * 8).decode("utf-8", "replace")
            status_code = int(getattr(e, "code", 500) or 500)
        try:
            result = json.loads(raw) if raw else {}
        except Exception:
            result = {"ok": False, "error": "invalid_node_json", "raw": raw[:1000]}
        if not isinstance(result, dict):
            result = {"ok": True, "result": result}
        elapsed = now() - started
        task = record_direct_task(path, body, result, status_code, node_id, elapsed)
        result.setdefault("centralTaskId", task["id"])
        result.setdefault("nodeId", node_id)
        result.setdefault("taskReceiptId", "task:" + task["id"])
        result.setdefault("latestEventId", "task:" + task["id"])
        result.setdefault("directNodeProxy", True)
        result.setdefault("executionElapsedSec", round(elapsed, 3))
        return result, (200 if status_code < 400 else status_code), task
    except Exception as exc:
        # Direct mode is an optimization.  If the node-local API is not reachable
        # from central (e.g. remote node), fall back to the worker queue.
        add_event("task_direct_proxy_fallback", {"path": path, "nodeId": node_id, "error": public_error_text(str(exc))})
        return None


def dispatch_task_sync(path, body=None, qs=None):
    qs = qs or {}
    prepared, err, status = prepare_task_body(path, body or {})
    if err:
        return err, status, None
    preferred = prepared.get("nodeId") or prepared.get("preferredNode") or (qs.get("nodeId") or [""])[0]
    direct = dispatch_cloud_login_direct(path, prepared, preferred)
    if direct is not None:
        return direct
    wait_sec = prepared.get("waitSec")
    try:
        wait_sec = float(wait_sec) if wait_sec is not None else None
    except Exception:
        wait_sec = None
    task, err, status = create_task(path, "POST", prepared, wait_sec=wait_sec, preferred_node=preferred)
    if err:
        if isinstance(err, dict) and str(err.get("error") or "").startswith("quota_"):
            add_event("quota_block", {"orgId": err.get("orgId"), "resource": err.get("resource"), "used": err.get("used"), "limit": err.get("limit"), "path": path})
        return err, status, None
    task = wait_task(task["id"], task.get("waitSec") or TASK_WAIT_DEFAULT)
    if task.get("status") == "done":
        result = task.get("result")
        if isinstance(result, dict):
            result.setdefault("centralTaskId", task["id"])
            result.setdefault("nodeId", task.get("nodeId"))
            result.setdefault("taskReceiptId", "task:" + str(task["id"]))
            result.setdefault("latestEventId", "task:" + str(task["id"]))
            return result, 200, task
        return {"ok": True, "result": result, "centralTaskId": task["id"], "nodeId": task.get("nodeId"), "taskReceiptId": "task:" + str(task["id"]), "latestEventId": "task:" + str(task["id"])}, 200, task
    if task.get("status") == "failed":
        result = task.get("result")
        if isinstance(result, dict):
            out = dict(result)
            out["ok"] = False
            out.setdefault("error", task.get("error") or result.get("error") or "node_task_failed")
            out.setdefault("result", result)
        else:
            out = {"ok": False, "error": task.get("error") or "node_task_failed", "result": result}
        out.setdefault("centralTaskId", task["id"])
        out.setdefault("nodeId", task.get("nodeId"))
        out.setdefault("taskReceiptId", "task:" + str(task["id"]))
        out.setdefault("latestEventId", "task:" + str(task["id"]))
        return out, 500, task
    return {"ok": False, "accepted": True, "status": task.get("status"), "centralTaskId": task["id"], "nodeId": task.get("nodeId"), "taskReceiptId": "task:" + str(task["id"]), "latestEventId": "task:" + str(task["id"]), "error": "task_timeout_waiting_result"}, 202, task


def finder_intent_score(intent):
    intent = (intent or "").strip()
    if intent in ("高意向", "high", "hot"):
        return 90
    if intent in ("中意向", "medium", "warm"):
        return 70
    if intent in ("咨询", "ask", "question"):
        return 62
    return 30


def public_finder_lead(item):
    item = dict(item or {})
    return {
        "id": item.get("id") or "",
        "orgId": item_org_id(item),
        "keyword": item.get("keyword") or "",
        "platform": item.get("platform") or "douyin",
        "text": item.get("text") or "",
        "c": item.get("text") or "",
        "user": item.get("user") or "",
        "u": item.get("user") or "",
        "intent": item.get("intent") or "",
        "score": int(item.get("score") or 0),
        "status": item.get("status") or "new",
        "stage": item.get("stage") or item.get("status") or "new",
        "sourceVideoTitle": item.get("sourceVideoTitle") or "",
        "sourceVideoUrl": item.get("sourceVideoUrl") or "",
        "sourceAuthor": item.get("sourceAuthor") or "",
        "awemeId": item.get("awemeId") or item.get("sourceAwemeId") or "",
        "noteId": item.get("noteId") or "",
        "commentId": item.get("commentId") or "",
        "ip": item.get("ip") or "",
        "diggCount": int(item.get("diggCount") or 0),
        "replyCount": int(item.get("replyCount") or 0),
        "centralTaskId": item.get("centralTaskId") or "",
        "nodeId": item.get("nodeId") or "",
        "ownerName": item.get("ownerName") or "",
        "note": item.get("note") or "",
        "firstSeenAt": item.get("firstSeenAt") or 0,
        "lastSeenAt": item.get("lastSeenAt") or item.get("updatedAt") or 0,
        "updatedAt": item.get("updatedAt") or 0,
    }


def normalize_finder_lead(raw, org_id, keyword="", task_id="", node_id="", source="finder"):
    raw = raw if isinstance(raw, dict) else {}
    text = str(raw.get("text") or raw.get("c") or raw.get("comment") or "").strip()[:500]
    user = str(raw.get("user") or raw.get("u") or raw.get("nickname") or raw.get("secUid") or "").strip()[:120]
    if not text and not user:
        return None
    aweme_id = str(raw.get("awemeId") or raw.get("sourceAwemeId") or raw.get("aweme_id") or "").strip()[:80]
    note_id = str(raw.get("noteId") or raw.get("note_id") or raw.get("noteId") or "").strip()[:80]
    if note_id and not aweme_id:
        aweme_id = note_id
    comment_id = str(raw.get("commentId") or raw.get("cid") or raw.get("id") or raw.get("comment_id") or "").strip()[:120]
    intent = str(raw.get("intent") or "").strip()[:40] or "普通"
    ts = now()
    seed = "|".join([normalize_org_id(org_id), aweme_id, comment_id, user, text[:160]])
    lead_id = "lead_" + _short_hash(seed)
    return {
        "id": lead_id,
        "orgId": normalize_org_id(org_id),
        "keyword": str(keyword or raw.get("keyword") or "").strip()[:120],
        "platform": str(raw.get("platform") or ("xhs" if note_id else "douyin")).strip()[:40],
        "text": text,
        "user": user or ("小红书用户" if note_id else "抖音用户"),
        "intent": intent,
        "score": finder_intent_score(intent),
        "status": "new",
        "stage": "new",
        "source": str(source or raw.get("source") or "finder")[:80],
        "sourceVideoTitle": str(raw.get("sourceVideoTitle") or raw.get("videoTitle") or "").strip()[:240],
        "sourceVideoUrl": str(raw.get("sourceVideoUrl") or raw.get("videoUrl") or raw.get("work_url") or "").strip()[:500],
        "sourceAuthor": str(raw.get("sourceAuthor") or raw.get("author") or "").strip()[:120],
        "awemeId": aweme_id,
        "noteId": note_id,
        "commentId": comment_id,
        "ip": str(raw.get("ip") or raw.get("ipLabel") or "").strip()[:80],
        "diggCount": int(raw.get("diggCount") or raw.get("digg_count") or 0),
        "replyCount": int(raw.get("replyCount") or raw.get("reply_count") or 0),
        "centralTaskId": task_id or str(raw.get("centralTaskId") or ""),
        "nodeId": node_id or str(raw.get("nodeId") or ""),
        "firstSeenAt": ts,
        "lastSeenAt": ts,
        "updatedAt": ts,
    }


def finder_lead_stats(rows):
    rows = list(rows or [])
    stats = {"total": len(rows), "new": 0, "follow": 0, "dm": 0, "done": 0, "ignored": 0, "high": 0, "medium": 0, "ask": 0}
    for r in rows:
        st = (r.get("status") or r.get("stage") or "new")
        stats[st] = stats.get(st, 0) + 1
        intent = r.get("intent") or ""
        if intent == "高意向":
            stats["high"] += 1
        elif intent == "中意向":
            stats["medium"] += 1
        elif intent == "咨询":
            stats["ask"] += 1
    return stats


def upsert_finder_leads(org_id, leads=None, keyword="", task_id="", node_id="", source="finder", user=None):
    org_id = normalize_org_id(org_id)
    incoming = []
    for raw in (leads or [])[:500]:
        lead = normalize_finder_lead(raw, org_id, keyword=keyword, task_id=task_id, node_id=node_id, source=source)
        if lead:
            incoming.append(lead)
    if not incoming:
        return {"ok": True, "orgId": org_id, "created": 0, "updated": 0, "total": 0, "leads": [], "stats": finder_lead_stats([])}, 200
    created = 0
    updated = 0
    ts = now()
    with LOCK:
        store = STATE.setdefault("finderLeads", {})
        bucket = list(store.get(org_id) or [])
        by_id = {x.get("id"): x for x in bucket if x.get("id")}
        for lead in incoming:
            old = by_id.get(lead.get("id"))
            if old:
                keep = {k: old.get(k) for k in ("status", "stage", "ownerName", "note", "firstSeenAt") if old.get(k) not in (None, "")}
                old.update(lead)
                old.update(keep)
                old["lastSeenAt"] = ts
                old["updatedAt"] = ts
                updated += 1
            else:
                lead["createdBy"] = (user or {}).get("id") or ""
                bucket.append(lead)
                by_id[lead.get("id")] = lead
                created += 1
        bucket = sorted(bucket, key=lambda x: float(x.get("lastSeenAt") or x.get("updatedAt") or 0), reverse=True)[:2000]
        store[org_id] = bucket
        persist()
        public_rows = [public_finder_lead(x) for x in bucket]
    return {"ok": True, "orgId": org_id, "created": created, "updated": updated, "total": len(public_rows), "leads": public_rows[:100], "stats": finder_lead_stats(public_rows)}, 200


def list_finder_leads(org_id=None, q="", status="", intent="", limit=80):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(200, max(1, int(limit or 80)))
    except Exception:
        limit = 80
    q = (q or "").strip().lower()
    status = (status or "").strip()
    intent = (intent or "").strip()
    with LOCK:
        rows = [public_finder_lead(x) for x in (STATE.setdefault("finderLeads", {}).get(org_id) or [])]
    if status and status != "all":
        rows = [r for r in rows if (r.get("status") or r.get("stage")) == status]
    if intent and intent != "all":
        rows = [r for r in rows if (r.get("intent") or "") == intent]
    if q:
        rows = [r for r in rows if q in " ".join([r.get("id") or "", r.get("platform") or "", r.get("keyword") or "", r.get("text") or "", r.get("user") or "", r.get("sourceVideoTitle") or "", r.get("sourceAuthor") or "", r.get("awemeId") or "", r.get("noteId") or ""]).lower()]
    return {"ok": True, "orgId": org_id, "leads": rows[:limit], "items": rows[:limit], "matched": len(rows), "total": len(rows), "stats": finder_lead_stats(rows), "filters": {"q": q, "status": status or "all", "intent": intent or "all"}}


def update_finder_lead(org_id, body=None, user=None):
    org_id = normalize_org_id(org_id)
    body = body or {}
    lead_id = (body.get("id") or body.get("leadId") or "").strip()
    if not lead_id:
        return {"ok": False, "error": "lead_id_required"}, 400
    allowed_status = {"new", "follow", "dm", "done", "ignored"}
    with LOCK:
        bucket = STATE.setdefault("finderLeads", {}).setdefault(org_id, [])
        found = None
        for x in bucket:
            if x.get("id") == lead_id:
                found = x
                break
        if not found:
            return {"ok": False, "error": "lead_not_found"}, 404
        if "status" in body or "stage" in body:
            st = (body.get("status") or body.get("stage") or "new").strip()
            if st not in allowed_status:
                return {"ok": False, "error": "invalid_status"}, 400
            found["status"] = st
            found["stage"] = st
        if "note" in body:
            found["note"] = str(body.get("note") or "")[:500]
        if "ownerName" in body:
            found["ownerName"] = str(body.get("ownerName") or "")[:80]
        found["updatedAt"] = now()
        found["updatedBy"] = (user or {}).get("id") or ""
        persist()
        row = public_finder_lead(found)
    return {"ok": True, "orgId": org_id, "lead": row}, 200


def aggregate_accounts(org_id=None):
    org_id = normalize_org_id(org_id) if org_id else None
    with LOCK:
        assets = [public_account_asset(a) for a in (STATE.get("accountsRegistry") or [])]
    if org_id:
        assets = [a for a in assets if item_org_id(a) == org_id]
    if assets:
        return assets
    accounts = []
    for n in online_nodes(org_id):
        for a in n.get("accounts") or []:
            item = dict(a)
            item["orgId"] = normalize_org_id(item.get("orgId") or n.get("orgId"))
            if org_id and item["orgId"] != org_id:
                continue
            local_id = str(item.get("id") or item.get("name") or "account")
            item["localAccountId"] = local_id
            item["id"] = n["id"] + ":" + local_id
            item["nodeId"] = n["id"]
            item["nodeName"] = n.get("name")
            item["cookieReady"] = bool(item.get("cookieReady", n.get("cookieReady")))
            item["cookieCount"] = item.get("cookieCount", n.get("cookieCount", 0))
            item["capabilities"] = normalize_account_capabilities(item.get("capabilities"), item.get("platform") or "douyin", bool(item.get("cookieReady")), item.get("cookieCount", 0))
            item["online"] = True
            item["status"] = "online" if item.get("cookieReady") else "offline"
            item["usable"] = bool(item.get("cookieReady") and item["capabilities"].get("ready"))
            item["lastSeen"] = n.get("lastSeen")
            accounts.append(item)
    return accounts


def dedupe_accounts_latest(accounts):
    rows = [a for a in (accounts or []) if isinstance(a, dict)]
    rows = sorted(rows, key=lambda a: (
        1 if a.get("online") else 0,
        1 if a.get("cookieReady") else 0,
        float(a.get("updatedAt") or a.get("lastSeen") or 0),
    ), reverse=True)
    out = []
    seen = set()
    for a in rows:
        platform = str(a.get("platform") or "douyin").strip()
        identity = str(a.get("localAccountId") or a.get("handle") or a.get("name") or a.get("id") or "").strip()
        key = (platform, identity)
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def accounts_for_response(org_id=None, user=None, include_all=False):
    org_id = normalize_org_id(org_id) if org_id else None
    accounts = aggregate_accounts(org_id)
    role = product_role_for_user(user, org_id)
    if include_all or role in (PRODUCT_ROLE_PLATFORM_ADMIN, PRODUCT_ROLE_ENTERPRISE_ADMIN):
        return dedupe_accounts_latest(accounts)
    if not user:
        return []
    uid = user.get("id")
    with LOCK:
        local_browser_housekeeping_locked()
        clients = list((STATE.get("localBrowserClients") or {}).values())
        owned_online_clients = {
            c.get("id") or c.get("clientId") or ""
            for c in clients
            if (not org_id or item_org_id(c) == org_id)
            and same_user_id(c.get("ownerUserId"), uid)
            and public_local_browser_client(c).get("online")
        }
    visible = []
    for a in accounts:
        owner = a.get("ownerUserId")
        if owner not in (None, "") and not same_user_id(owner, uid):
            continue
        if owned_online_clients and (a.get("nodeId") or "") not in owned_online_clients:
            continue
        if not (a.get("online") and a.get("cookieReady")):
            continue
        visible.append(a)
    return dedupe_accounts_latest(visible)


def account_repair_metrics(org_id=None, state="", owner="", severity="", q="", limit=50):
    org_id = normalize_org_id(org_id)
    state_filter = (state or "").strip()
    owner_filter = (owner or "").strip()
    severity_filter = (severity or "").strip()
    q_filter = (q or "").strip().lower()
    try:
        limit = max(1, min(200, int(limit or 50)))
    except Exception:
        limit = 50
    ts_now = now()
    accounts = aggregate_accounts(org_id)
    with LOCK:
        raw_nodes = [dict(n) for n in (STATE.get("nodes") or {}).values() if item_org_id(n) == org_id]
    nodes = [public_node(n) for n in raw_nodes]

    state_labels = {
        "healthy": "\u6b63\u5e38",
        "node_offline": "\u8282\u70b9\u79bb\u7ebf",
        "cookie_unavailable": "\u9700\u91cd\u65b0\u6388\u6743",
        "unknown": "\u5f85\u786e\u8ba4",
    }
    owner_labels = {
        "operator": "\u8fd0\u8425\u5904\u7406",
        "admin": "\u7ba1\u7406\u5458\u5904\u7406",
        "unknown": "\u5f85\u5206\u914d",
    }
    severity_counts = {"info": 0, "warning": 0, "critical": 0}
    state_counts = {"healthy": 0, "node_offline": 0, "cookie_unavailable": 0, "unknown": 0}
    owner_counts = {"operator": 0, "admin": 0, "unknown": 0}
    repair_rows = []
    total_age = 0.0
    age_count = 0
    max_overdue = 0.0
    next_due_at = 0.0

    for a in accounts:
        sla = a.get("repairSla") or account_repair_sla(a, ts_now)
        state = sla.get("state") or "unknown"
        severity = sla.get("severity") or "info"
        owner = sla.get("ownerRole") or "unknown"
        state_counts[state] = state_counts.get(state, 0) + 1
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        owner_counts[owner] = owner_counts.get(owner, 0) + 1
        age = float(sla.get("ageSec") or 0)
        if state != "healthy":
            total_age += age
            age_count += 1
            due_at = float(sla.get("dueAt") or 0)
            if due_at and (not next_due_at or due_at < next_due_at):
                next_due_at = due_at
        max_overdue = max(max_overdue, float(sla.get("overdueSec") or 0))
        if state != "healthy" or severity in ("warning", "critical"):
            account_id = a.get("id") or ""
            repair_rows.append({
                "id": "repair:" + account_id if account_id else "repair:unknown",
                "accountId": account_id,
                "localAccountId": a.get("localAccountId") or "",
                "name": a.get("name") or a.get("localAccountId") or "douyin",
                "nodeId": a.get("nodeId"),
                "nodeName": a.get("nodeName") or a.get("nodeId"),
                "online": bool(a.get("online")),
                "cookieReady": bool(a.get("cookieReady")),
                "state": state,
                "stateLabel": state_labels.get(state, state),
                "severity": severity,
                "ownerRole": owner,
                "ownerLabel": owner_labels.get(owner, owner),
                "ageSec": round(age, 1),
                "remainingSec": sla.get("remainingSec") or 0,
                "overdueSec": sla.get("overdueSec") or 0,
                "dueAt": sla.get("dueAt") or 0,
                "since": sla.get("since") or 0,
                "handoffNote": sla.get("handoffNote") or "",
            })

    node_status_counts = {}
    for n in nodes:
        cap = n.get("capacity") or {}
        st = cap.get("status") or ("offline" if n.get("online") is False else "available")
        node_status_counts[st] = node_status_counts.get(st, 0) + 1

    needs_repair = len([a for a in accounts if not a.get("usable")])
    overdue = len([r for r in repair_rows if float(r.get("overdueSec") or 0) > 0])
    repair_rows.sort(key=lambda r: (0 if r.get("severity") == "critical" else (1 if r.get("severity") == "warning" else 2), -(float(r.get("overdueSec") or 0)), float(r.get("dueAt") or 0) or 9999999999))
    total_repair_rows = len(repair_rows)
    def _repair_row_match(row):
        if state_filter and state_filter != "all" and row.get("state") != state_filter:
            return False
        if owner_filter and owner_filter != "all" and row.get("ownerRole") != owner_filter:
            return False
        if severity_filter and severity_filter != "all" and row.get("severity") != severity_filter:
            return False
        if q_filter:
            blob = " ".join(str(row.get(k) or "") for k in ("id", "accountId", "localAccountId", "name", "nodeId", "nodeName", "state", "stateLabel", "severity", "ownerRole", "ownerLabel", "handoffNote")).lower()
            if q_filter not in blob:
                return False
        return True
    filtered_repair_rows = [r for r in repair_rows if _repair_row_match(r)]
    by_state = [{"key": k, "label": state_labels.get(k, k), "count": v} for k, v in sorted(state_counts.items(), key=lambda kv: (-kv[1], kv[0])) if v]
    by_owner = [{"key": k, "label": owner_labels.get(k, k), "count": v} for k, v in sorted(owner_counts.items(), key=lambda kv: (-kv[1], kv[0])) if v]
    summary = "\u8d26\u53f7\u548c\u8282\u70b9\u72b6\u6001\u6b63\u5e38"
    if overdue:
        summary = "\u6709 %d \u4e2a\u8d26\u53f7 SLA \u8d85\u65f6\uff0c\u9700\u7acb\u5373\u4ea4\u63a5\u5904\u7406" % overdue
    elif needs_repair:
        summary = "\u6709 %d \u4e2a\u8d26\u53f7\u9700\u7ef4\u62a4\uff0c\u8bf7\u6309\u8d23\u4efb\u5206\u5e03\u5904\u7406" % needs_repair

    return {
        "ok": True,
        "orgId": org_id,
        "updatedAt": ts_now,
        "summary": summary,
        "accounts": {
            "total": len(accounts),
            "usable": len([a for a in accounts if a.get("usable")]),
            "needsRepair": needs_repair,
            "offline": len([a for a in accounts if a.get("online") is False]),
            "cookieUnavailable": len([a for a in accounts if a.get("online") is not False and not a.get("cookieReady")]),
            "states": state_counts,
        },
        "nodes": {
            "total": len(nodes),
            "online": len([n for n in nodes if n.get("online")]),
            "offline": len([n for n in nodes if not n.get("online")]),
            "cookieReady": len([n for n in nodes if n.get("cookieReady")]),
            "status": node_status_counts,
        },
        "sla": {
            "targetSec": ACCOUNT_REPAIR_SLA_SEC,
            "warnSec": ACCOUNT_REPAIR_WARN_SEC,
            "severityCounts": severity_counts,
            "ownerCounts": owner_counts,
            "warning": severity_counts.get("warning", 0),
            "critical": severity_counts.get("critical", 0),
            "overdue": overdue,
            "maxOverdueSec": round(max_overdue, 1),
            "avgRepairAgeSec": round(total_age / max(1, age_count), 1),
            "nextDueAt": next_due_at,
        },
        "byState": by_state,
        "byOwner": by_owner,
        "totalRows": total_repair_rows,
        "matchedRows": len(filtered_repair_rows),
        "filters": {"state": state_filter or "all", "owner": owner_filter or "all", "severity": severity_filter or "all", "q": q_filter, "limit": limit},
        "rows": filtered_repair_rows[:limit],
    }



PLAN_FEATURES = [
    "cloudLogin", "publish", "finder", "outreach", "commentSend", "library", "knowledgeBase",
    "taskCenter", "audit", "supportLinks", "notifications", "webhook", "healthSnapshots",
    "multiUser", "nodePool", "quotaControls",
]


def feature_set(*enabled):
    enabled = set(enabled)
    return {k: (k in enabled) for k in PLAN_FEATURES}


PLAN_CATALOG = {
    "trial": {
        "code": "trial",
        "name": "Trial",
        "rank": 1,
        "limits": {"tasksPerDay": 30, "accounts": 1, "nodes": 1, "materials": 20, "enforce": True},
        "features": feature_set("cloudLogin", "finder", "library", "knowledgeBase", "taskCenter"),
    },
    "starter": {
        "code": "starter",
        "name": "Starter",
        "rank": 2,
        "limits": {"tasksPerDay": 100, "accounts": 3, "nodes": 1, "materials": 100, "enforce": True},
        "features": feature_set("cloudLogin", "publish", "finder", "library", "knowledgeBase", "taskCenter", "notifications"),
    },
    "standard": {
        "code": "standard",
        "name": "Standard",
        "rank": 3,
        "limits": {"tasksPerDay": 500, "accounts": 50, "nodes": 10, "materials": 1000, "enforce": False},
        "features": {k: True for k in PLAN_FEATURES},
    },
    "pro": {
        "code": "pro",
        "name": "Pro",
        "rank": 4,
        "limits": {"tasksPerDay": 2000, "accounts": 200, "nodes": 30, "materials": 5000, "enforce": True},
        "features": {k: True for k in PLAN_FEATURES},
    },
    "enterprise": {
        "code": "enterprise",
        "name": "Enterprise",
        "rank": 5,
        "limits": {"tasksPerDay": 10000, "accounts": 1000, "nodes": 200, "materials": 50000, "enforce": True},
        "features": {k: True for k in PLAN_FEATURES},
    },
}


DEFAULT_ORG_QUOTAS = dict(PLAN_CATALOG["standard"]["limits"])


def org_record(org_id=None):
    org_id = normalize_org_id(org_id)
    with LOCK:
        return next((dict(o) for o in (STATE.get("organizations") or []) if normalize_org_id(o.get("id")) == org_id), None)


def org_plan_code(org_id=None):
    org = org_record(org_id) or {}
    code = str(org.get("plan") or "standard").strip().lower()
    return code if code in PLAN_CATALOG else "standard"


def org_plan_config(org_id=None):
    cfg = dict(PLAN_CATALOG.get(org_plan_code(org_id)) or PLAN_CATALOG["standard"])
    cfg["limits"] = dict(cfg.get("limits") or {})
    cfg["features"] = dict(cfg.get("features") or {})
    return cfg


def org_quota(org_id=None):
    org_id = normalize_org_id(org_id)
    quota = dict((org_plan_config(org_id).get("limits") or DEFAULT_ORG_QUOTAS))
    with LOCK:
        saved = dict((STATE.setdefault("orgQuotas", {}) or {}).get(org_id) or {})
    for k in ("tasksPerDay", "accounts", "nodes", "materials"):
        if k in saved:
            try:
                quota[k] = max(0, int(saved.get(k) or 0))
            except Exception:
                pass
    if "enforce" in saved:
        quota["enforce"] = bool(saved.get("enforce"))
    return quota


def plan_feature_for_path(path):
    path = str(path or "")
    if path.startswith("/api/cloud-login/"):
        return "cloudLogin"
    mapping = {
        "/api/publish/run": "publish",
        "/api/publish/preflight": "publish",
        "/api/publish/queue/add": "publish",
        "/api/finder/discover": "finder",
        "/api/douyin/search": "finder",
        "/api/xhs/search": "finder",
        "/api/douyin/work": "finder",
        "/api/douyin/comments": "finder",
        "/api/xhs/comments": "finder",
        "/api/douyin/download": "finder",
        "/api/xhs/download": "finder",
        "/api/outreach/run": "outreach",
        "/api/douyin/comment/publish": "commentSend",
        "/api/xhs/comment/publish": "commentSend",
        "/api/library/upload": "library",
        "/api/library/delete": "library",
        "/api/kb/add": "knowledgeBase",
        "/api/kb/upload": "knowledgeBase",
        "/api/kb/delete": "knowledgeBase",
        "/api/kb/ask": "knowledgeBase",
    }
    return mapping.get(path)


def org_entitlements(org_id=None):
    org_id = normalize_org_id(org_id)
    plan = org_plan_config(org_id)
    quota = org_quota(org_id)
    features = dict(plan.get("features") or {})
    for k in PLAN_FEATURES:
        features.setdefault(k, False)
    module_features = {
        "accounts": "cloudLogin",
        "autopub": "publish",
        "finder": "finder",
        "outreach": "outreach",
        "kb": "knowledgeBase",
        "tasks": "taskCenter",
        "enterprise": "audit",
        "sales": "outreach",
    }
    modules = []
    for module, feature in module_features.items():
        modules.append({"id": module, "feature": feature, "enabled": bool(features.get(feature))})
    blocked = [m for m in modules if not m.get("enabled")]
    return {
        "ok": True,
        "orgId": org_id,
        "plan": {"code": plan.get("code"), "name": plan.get("name"), "rank": plan.get("rank")},
        "features": features,
        "modules": modules,
        "blockedModules": blocked,
        "planLimits": dict(plan.get("limits") or {}),
        "effectiveQuota": quota,
        "catalog": [{"code": c.get("code"), "name": c.get("name"), "rank": c.get("rank"), "limits": dict(c.get("limits") or {}), "features": dict(c.get("features") or {})} for c in PLAN_CATALOG.values()],
        "upgradeSuggestion": "upgrade_plan" if blocked else "",
    }


def feature_allowed(org_id, feature):
    if not feature:
        return True
    return bool((org_entitlements(org_id).get("features") or {}).get(feature))


def require_feature(handler, org_id, feature):
    if feature_allowed(org_id, feature):
        return True
    ent = org_entitlements(org_id)
    json_response(handler, {"ok": False, "error": "feature_not_in_plan", "feature": feature, "orgId": normalize_org_id(org_id), "plan": ent.get("plan"), "upgradeSuggestion": ent.get("upgradeSuggestion")}, 403)
    return False


def update_org_plan(org_id, body):
    org_id = normalize_org_id(org_id)
    code = str(body.get("plan") or body.get("planCode") or "").strip().lower()
    if code not in PLAN_CATALOG:
        return {"ok": False, "error": "invalid_plan", "allowed": list(PLAN_CATALOG.keys())}, 400
    with LOCK:
        orgs = STATE.setdefault("organizations", [])
        org = next((o for o in orgs if normalize_org_id(o.get("id")) == org_id), None)
        if not org:
            org = {"id": org_id, "name": org_id, "status": "active", "createdAt": now()}
            orgs.append(org)
        org["plan"] = code
        if body.get("syncQuota"):
            STATE.setdefault("orgQuotas", {})[org_id] = dict(PLAN_CATALOG[code]["limits"])
        persist()
    return {"ok": True, "orgId": org_id, "entitlements": org_entitlements(org_id), "usage": enterprise_usage(org_id)}, 200



def _safe_slug(value, prefix="org"):
    raw = str(value or "").strip().lower()
    out = []
    for ch in raw:
        if ch.isalnum():
            out.append(ch)
        elif ch in ("-", "_", "."):
            out.append("-")
    slug = "".join(out).strip("-")[:36]
    return slug or (prefix + "-" + uuid.uuid4().hex[:8])


def _generated_initial_password():
    return "Ms" + uuid.uuid4().hex[:10] + "!"


def provision_customer_workspace(body, actor=None):
    body = body if isinstance(body, dict) else {}
    org_name = (body.get("orgName") or body.get("name") or body.get("company") or "").strip()
    owner_name = (body.get("ownerName") or body.get("contactName") or body.get("userName") or "").strip()
    owner_phone = (body.get("ownerPhone") or body.get("phone") or body.get("identifier") or "").strip()
    owner_email = (body.get("ownerEmail") or body.get("email") or "").strip()
    role = (body.get("role") or "owner").strip() or "owner"
    if role not in ("owner", "admin", "member", "auditor"):
        role = "owner"
    plan = (body.get("plan") or body.get("planCode") or "standard").strip().lower() or "standard"
    if plan not in PLAN_CATALOG:
        plan = "standard"
    if not org_name:
        return {"ok": False, "error": "missing_org_name"}, 400
    if not owner_name:
        owner_name = owner_phone or owner_email or "Customer Owner"
    if not (owner_phone or owner_email):
        return {"ok": False, "error": "missing_owner_contact"}, 400
    explicit_password = (body.get("password") or body.get("initialPassword") or "").strip()
    generated_password = "" if explicit_password else _generated_initial_password()
    initial_password = explicit_password or generated_password
    force_password_change = body.get("forcePasswordChange")
    if force_password_change is None:
        force_password_change = True
    requested_org_id = (body.get("orgId") or body.get("id") or "").strip()
    org_id = normalize_org_id(requested_org_id or ("org-" + _safe_slug(org_name, "customer")))
    ts = now()
    with LOCK:
        orgs = STATE.setdefault("organizations", [])
        if not requested_org_id:
            exists = {normalize_org_id(o.get("id")) for o in orgs}
            if org_id in exists:
                org_id = org_id + "-" + uuid.uuid4().hex[:5]
        org = upsert_by_id(orgs, {"id": org_id, "name": org_name, "status": "active", "plan": plan})
        users = STATE.setdefault("users", [])
        user = None
        for u in users:
            if owner_phone and str(u.get("phone") or "").strip() == owner_phone:
                user = u
                break
            if owner_email and str(u.get("email") or "").strip().lower() == owner_email.lower():
                user = u
                break
        if user:
            user.update({"name": owner_name, "phone": owner_phone or user.get("phone") or "", "email": owner_email or user.get("email") or "", "status": "active", "updatedAt": ts})
        else:
            user = {"id": "user-" + uuid.uuid4().hex[:12], "name": owner_name, "phone": owner_phone, "email": owner_email, "status": "active", "createdAt": ts, "updatedAt": ts}
            users.append(user)
        if initial_password:
            set_user_password(user, initial_password)
            user["passwordChangeRequired"] = bool(force_password_change)
        memberships = STATE.setdefault("memberships", [])
        membership = upsert_by_id(memberships, {"id": "m-%s-%s" % (org_id, user["id"]), "orgId": org_id, "userId": user["id"], "role": role, "status": "active"})
        persist()
    defaults = ensure_org_delivery_defaults(org_id, plan)
    login_identifier = owner_phone or owner_email or user.get("id")
    next_actions = [
        {"key": "share_login", "label": "\u4ea4\u4ed8\u4f01\u4e1a\u767b\u5f55\u4fe1\u606f", "detail": "\u5c06\u767b\u5f55\u8d26\u53f7\u548c\u521d\u59cb\u5bc6\u7801\u4ea4\u7ed9\u5ba2\u6237\u8d1f\u8d23\u4eba\u3002"},
        {"key": "authorize_account", "label": "\u5ba2\u6237\u6388\u6743\u6296\u97f3\u8d26\u53f7", "detail": "\u8d1f\u8d23\u4eba\u767b\u5f55\u540e\u6253\u5f00\u8d26\u53f7\u6388\u6743\u9875\u5b8c\u6210\u626b\u7801/\u77ed\u4fe1\u3002"},
        {"key": "run_startup", "label": "\u8fd0\u884c\u5ba2\u6237\u542f\u52a8\u68c0\u67e5", "detail": "\u6838\u5bf9\u8282\u70b9\u3001\u8d26\u53f7\u3001\u7d20\u6750\u3001\u961f\u5217\u548c\u5ba1\u8ba1\u662f\u5426\u5c31\u7eea\u3002"},
    ]
    return {
        "ok": True,
        "orgId": org_id,
        "organization": dict(org),
        "owner": public_user(user),
        "membership": dict(membership),
        "defaults": defaults,
        "credential": {"identifier": login_identifier, "initialPassword": initial_password, "generated": bool(generated_password)},
        "loginUrl": "/",
        "nextActions": next_actions,
        "message": "\u5ba2\u6237\u5de5\u4f5c\u533a\u5df2\u5f00\u901a\uff0c\u8bf7\u4ea4\u4ed8\u4f01\u4e1a\u767b\u5f55\u4fe1\u606f\u5e76\u5f15\u5bfc\u6388\u6743\u6296\u97f3\u8d26\u53f7\u3002",
        "createdAt": ts,
    }, 200


def replace_enterprise_memberships(body):
    body = body if isinstance(body, dict) else {}
    org_id = normalize_org_id(body.get("orgId") or body.get("id"))
    name = (body.get("name") or body.get("orgName") or "").strip()
    if not org_id:
        return {"ok": False, "error": "missing_org_id"}, 400
    if not name:
        return {"ok": False, "error": "missing_name"}, 400
    raw_members = body.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        return {"ok": False, "error": "missing_members"}, 400
    assignments = []
    for item in raw_members:
        if not isinstance(item, dict):
            continue
        user_id = str(item.get("userId") or item.get("id") or "").strip()
        role = str(item.get("role") or "member").strip().lower() or "member"
        if not user_id:
            continue
        if role not in ("owner", "admin", "member", "auditor"):
            return {"ok": False, "error": "invalid_role", "userId": user_id, "role": role}, 400
        assignments.append({"userId": user_id, "role": role})
    if not assignments:
        return {"ok": False, "error": "missing_members"}, 400
    exclusive = bool(body.get("exclusive", True))
    plan = (body.get("plan") or "standard").strip().lower() or "standard"
    ts = now()
    with LOCK:
        users = STATE.setdefault("users", [])
        existing_user_ids = {str(user.get("id") or "") for user in users if isinstance(user, dict)}
        missing = [item["userId"] for item in assignments if item["userId"] not in existing_user_ids]
        if missing:
            return {"ok": False, "error": "user_not_found", "missingUsers": missing}, 404
        org = upsert_by_id(STATE.setdefault("organizations", []), {
            "id": org_id,
            "name": name,
            "status": body.get("status") or "active",
            "plan": plan,
        })
        memberships = STATE.setdefault("memberships", [])
        target_users = {item["userId"] for item in assignments}
        removed = 0
        if exclusive:
            kept = []
            for membership in memberships:
                if str(membership.get("userId") or "") in target_users:
                    removed += 1
                else:
                    kept.append(membership)
            memberships[:] = kept
        upserted = []
        for item in assignments:
            membership = upsert_by_id(memberships, {
                "id": "m-%s-%s" % (org_id, item["userId"]),
                "orgId": org_id,
                "userId": item["userId"],
                "role": item["role"],
                "status": "active",
                "updatedAt": ts,
            })
            upserted.append(dict(membership))
        persist()
    return {
        "ok": True,
        "organization": dict(org),
        "memberships": upserted,
        "removed": removed,
        "exclusive": exclusive,
    }, 200


def reset_enterprise_user_password(org_id, body=None):
    body = body if isinstance(body, dict) else {}
    org_id = normalize_org_id(org_id or body.get("orgId"))
    user_id = (body.get("userId") or body.get("id") or "").strip()
    explicit_password = (body.get("password") or body.get("initialPassword") or body.get("newPassword") or "").strip()
    force_password_change = body.get("forcePasswordChange")
    if force_password_change is None:
        force_password_change = True
    if not user_id:
        return {"ok": False, "error": "missing_user_id"}, 400
    generated_password = "" if explicit_password else _generated_initial_password()
    password = explicit_password or generated_password
    with LOCK:
        membership = next((m for m in STATE.get("memberships") or [] if m.get("userId") == user_id and normalize_org_id(m.get("orgId")) == org_id), None)
        if not membership:
            return {"ok": False, "error": "membership_not_found", "orgId": org_id, "userId": user_id}, 404
        user = next((u for u in STATE.get("users") or [] if u.get("id") == user_id), None)
        if not user:
            return {"ok": False, "error": "user_not_found", "orgId": org_id, "userId": user_id}, 404
        set_user_password(user, password)
        user["passwordChangeRequired"] = bool(force_password_change)
        user["status"] = user.get("status") or "active"
        user["updatedAt"] = now()
        persist()
    return {"ok": True, "orgId": org_id, "user": public_user(user), "credential": {"identifier": user.get("phone") or user.get("email") or user.get("id"), "initialPassword": password, "generated": bool(generated_password)}}, 200


def update_enterprise_user_status(org_id, body=None):
    body = body if isinstance(body, dict) else {}
    org_id = normalize_org_id(org_id or body.get("orgId"))
    user_id = (body.get("userId") or body.get("id") or "").strip()
    action = (body.get("action") or body.get("status") or "").strip().lower()
    if action in ("disable", "disabled", "inactive", "deactivate"):
        next_user_status = "inactive"
        next_member_status = "inactive"
    elif action in ("enable", "active", "restore", "resume"):
        next_user_status = "active"
        next_member_status = "active"
    else:
        return {"ok": False, "error": "invalid_status_action", "allowed": ["disable", "enable"]}, 400
    if not user_id:
        return {"ok": False, "error": "missing_user_id"}, 400
    if user_id == "user-owner" and next_user_status != "active" and not bool(body.get("force")):
        return {"ok": False, "error": "owner_disable_requires_force"}, 409
    ts = now()
    with LOCK:
        membership = next((m for m in STATE.get("memberships") or [] if m.get("userId") == user_id and normalize_org_id(m.get("orgId")) == org_id), None)
        if not membership:
            return {"ok": False, "error": "membership_not_found", "orgId": org_id, "userId": user_id}, 404
        user = next((u for u in STATE.get("users") or [] if u.get("id") == user_id), None)
        if not user:
            return {"ok": False, "error": "user_not_found", "orgId": org_id, "userId": user_id}, 404
        membership["status"] = next_member_status
        membership["updatedAt"] = ts
        if next_member_status == "inactive":
            membership["disabledAt"] = ts
        else:
            membership["restoredAt"] = ts
        if next_user_status == "inactive":
            active_elsewhere = any(m.get("userId") == user_id and normalize_org_id(m.get("orgId")) != org_id and m.get("status", "active") == "active" for m in (STATE.get("memberships") or []))
            if not active_elsewhere:
                user["status"] = "inactive"
                user["disabledAt"] = ts
        else:
            user["status"] = "active"
            user["restoredAt"] = ts
        user["updatedAt"] = ts
        # Revoke sessions when disabling so access stops immediately.
        revoked = 0
        if next_user_status == "inactive":
            kept = []
            for s in STATE.get("sessions") or []:
                if s.get("userId") == user_id:
                    revoked += 1
                    continue
                kept.append(s)
            STATE["sessions"] = kept
        persist()
    return {"ok": True, "orgId": org_id, "user": public_user(user), "membership": dict(membership), "status": next_user_status, "membershipStatus": next_member_status, "revokedSessions": revoked, "updatedAt": ts}, 200



INVITE_ROLES = {"member", "admin", "auditor"}


def enterprise_invite_token_hash(token):
    token = (token or "").strip()
    if not token:
        return ""
    return hashlib.sha256(("matrixship-invite:" + token).encode("utf-8")).hexdigest()


def enterprise_invite_status(invite):
    if not invite:
        return "invalid"
    status = invite.get("status") or "active"
    if status in ("accepted", "revoked", "disabled"):
        return status
    if float(invite.get("expiresAt") or 0) <= now():
        return "expired"
    return "active"


def public_enterprise_invite(invite):
    item = dict(invite or {})
    item.pop("token", None)
    item.pop("tokenHash", None)
    item.pop("inviteCode", None)
    item["status"] = enterprise_invite_status(invite)
    return item


def find_enterprise_invite_by_token(token):
    token_hash = enterprise_invite_token_hash(token)
    if not token_hash:
        return None
    with LOCK:
        for inv in STATE.setdefault("enterpriseInvites", []):
            if inv.get("tokenHash") == token_hash:
                return dict(inv)
    return None


def enterprise_invite_verify(token):
    invite = find_enterprise_invite_by_token(token)
    if not invite:
        return {"ok": False, "error": "invalid_invite"}, 404
    status = enterprise_invite_status(invite)
    org_id = normalize_org_id(invite.get("orgId"))
    with LOCK:
        org = next((dict(o) for o in (STATE.get("organizations") or []) if normalize_org_id(o.get("id")) == org_id), None)
    if not org or (org.get("status") or "active") != "active":
        return {"ok": False, "error": "organization_inactive", "status": status}, 410
    if status != "active":
        return {"ok": False, "error": "invite_" + status, "status": status, "invite": public_enterprise_invite(invite)}, 410
    out = public_enterprise_invite(invite)
    out["organization"] = {"id": org.get("id"), "name": org.get("name"), "plan": org.get("plan") or "standard"}
    return {"ok": True, "invite": out, "organization": out["organization"]}, 200


def list_enterprise_invites(org_id, limit=40):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(100, max(1, int(limit or 40)))
    except Exception:
        limit = 40
    with LOCK:
        rows = [dict(x) for x in (STATE.get("enterpriseInvites") or []) if normalize_org_id(x.get("orgId")) == org_id]
    rows = sorted(rows, key=lambda x: float(x.get("createdAt") or 0), reverse=True)[:limit]
    active = 0
    expired = 0
    accepted = 0
    for r in rows:
        st = enterprise_invite_status(r)
        if st == "active":
            active += 1
        elif st == "accepted":
            accepted += 1
        elif st == "expired":
            expired += 1
    return {"ok": True, "orgId": org_id, "items": [public_enterprise_invite(x) for x in rows], "counts": {"total": len(rows), "active": active, "accepted": accepted, "expired": expired}}


def create_enterprise_invite(org_id, body, actor=None):
    org_id = normalize_org_id(org_id)
    role = (body.get("role") or "member").strip()
    if role not in INVITE_ROLES:
        role = "member"
    recipient_name = (body.get("recipientName") or body.get("name") or "").strip()[:80]
    recipient_phone = (body.get("recipientPhone") or body.get("phone") or "").strip()[:40]
    recipient_email = (body.get("recipientEmail") or body.get("email") or "").strip()[:120]
    try:
        ttl_hours = int(body.get("ttlHours") or 168)
    except Exception:
        ttl_hours = 168
    ttl_hours = min(24 * 30, max(1, ttl_hours))
    ts = now()
    token = uuid.uuid4().hex + uuid.uuid4().hex
    invite = {
        "id": "inv-" + uuid.uuid4().hex[:16],
        "orgId": org_id,
        "role": role,
        "recipientName": recipient_name,
        "recipientPhone": recipient_phone,
        "recipientEmail": recipient_email,
        "tokenHash": enterprise_invite_token_hash(token),
        "status": "active",
        "createdAt": ts,
        "updatedAt": ts,
        "expiresAt": ts + ttl_hours * 3600,
        "createdBy": (actor or {}).get("id") or "",
        "createdByName": (actor or {}).get("name") or "",
    }
    with LOCK:
        org = next((o for o in (STATE.get("organizations") or []) if normalize_org_id(o.get("id")) == org_id), None)
        if not org:
            return {"ok": False, "error": "org_not_found", "orgId": org_id}, 404
        if (org.get("status") or "active") != "active":
            return {"ok": False, "error": "organization_inactive", "orgId": org_id}, 409
        invites = STATE.setdefault("enterpriseInvites", [])
        invites.append(invite)
        STATE["enterpriseInvites"] = invites[-1000:]
        persist()
    out = public_enterprise_invite(invite)
    return {
        "ok": True,
        "orgId": org_id,
        "inviteCode": token,
        "invite": out,
        "message": "invite_created",
    }, 200



def revoke_enterprise_invite(org_id, body):
    org_id = normalize_org_id(org_id or body.get("orgId"))
    invite_id = (body.get("inviteId") or body.get("id") or "").strip()
    if not invite_id:
        return {"ok": False, "error": "missing_invite_id", "orgId": org_id}, 400
    ts = now()
    with LOCK:
        invite = next((x for x in STATE.setdefault("enterpriseInvites", []) if x.get("id") == invite_id and normalize_org_id(x.get("orgId")) == org_id), None)
        if not invite:
            return {"ok": False, "error": "invite_not_found", "orgId": org_id, "inviteId": invite_id}, 404
        st = enterprise_invite_status(invite)
        if st == "accepted":
            return {"ok": False, "error": "invite_already_accepted", "orgId": org_id, "inviteId": invite_id, "status": st}, 409
        if st == "revoked":
            return {"ok": True, "orgId": org_id, "invite": public_enterprise_invite(invite), "status": st, "revoked": False}, 200
        invite["status"] = "revoked"
        invite["revokedAt"] = ts
        invite["updatedAt"] = ts
        persist()
        out = public_enterprise_invite(invite)
    return {"ok": True, "orgId": org_id, "invite": out, "status": "revoked", "revoked": True}, 200


def accept_enterprise_invite(body, handler=None):
    token = (body.get("token") or "").strip()
    name = (body.get("name") or body.get("recipientName") or "").strip()[:80]
    phone = (body.get("phone") or body.get("recipientPhone") or "").strip()[:40]
    email = (body.get("email") or body.get("recipientEmail") or "").strip()[:120]
    password = (body.get("password") or "").strip()
    current_password = body.get("currentPassword") or ""
    if not token:
        return {"ok": False, "error": "missing_token"}, 400
    payload, status_code = enterprise_invite_verify(token)
    if not payload.get("ok"):
        return payload, status_code
    invite = find_enterprise_invite_by_token(token)
    if invite:
        name = name or invite.get("recipientName") or ""
        phone = phone or invite.get("recipientPhone") or ""
        email = email or invite.get("recipientEmail") or ""
    if not name:
        return {"ok": False, "error": "missing_name"}, 400
    if not (phone or email):
        return {"ok": False, "error": "missing_identifier"}, 400
    if len(password) < 8:
        return {"ok": False, "error": "password_too_short", "minLength": 8}, 400
    org_id = normalize_org_id(invite.get("orgId"))
    role = invite.get("role") or "member"
    ts = now()
    with LOCK:
        invites = STATE.setdefault("enterpriseInvites", [])
        actual_invite = next((x for x in invites if x.get("tokenHash") == enterprise_invite_token_hash(token)), None)
        if not actual_invite:
            return {"ok": False, "error": "invalid_invite"}, 404
        st = enterprise_invite_status(actual_invite)
        if st != "active":
            return {"ok": False, "error": "invite_" + st, "status": st}, 410
        users = STATE.setdefault("users", [])
        low_phone = phone.lower()
        low_email = email.lower()
        user = None
        for u in users:
            if (low_phone and str(u.get("phone") or "").strip().lower() == low_phone) or (low_email and str(u.get("email") or "").strip().lower() == low_email):
                user = u
                break
        if user and user.get("passwordHash") and not verify_user_password(user, current_password):
            return {"ok": False, "error": "existing_user_login_required"}, 409
        if not user:
            user = {"id": "user-" + uuid.uuid4().hex[:12], "name": name, "phone": phone, "email": email, "status": "active", "createdAt": ts, "updatedAt": ts}
            users.append(user)
        else:
            user["name"] = name or user.get("name") or ""
            if phone:
                user["phone"] = phone
            if email:
                user["email"] = email
            user["status"] = "active"
            user["updatedAt"] = ts
        set_user_password(user, password)
        user["passwordChangeRequired"] = False
        memberships = STATE.setdefault("memberships", [])
        membership = upsert_by_id(memberships, {"id": "m-%s-%s" % (org_id, user["id"]), "orgId": org_id, "userId": user["id"], "role": role, "status": "active"})
        actual_invite["status"] = "accepted"
        actual_invite["usedAt"] = ts
        actual_invite["acceptedBy"] = user["id"]
        actual_invite["updatedAt"] = ts
        persist()
        out_user = public_user(user)
        out_membership = dict(membership)
    session = create_user_session(out_user, {
        "ip": handler.client_address[0] if handler and getattr(handler, "client_address", None) else "",
        "userAgent": handler.headers.get("User-Agent") if handler else "",
        "inviteId": invite.get("id") or "",
    })
    ctx = auth_context_for_user(out_user)
    return dict(ctx, **{
        "ok": True,
        "token": session.get("token"),
        "expiresAt": session.get("expiresAt"),
        "user": out_user,
        "membership": out_membership,
        "memberships": user_memberships(out_user),
        "organizations": user_orgs(out_user.get("id")),
        "orgId": org_id,
        "message": "invite_accepted",
    }), 200


def archive_customer_workspace(org_id, body=None):
    body = body if isinstance(body, dict) else {}
    org_id = normalize_org_id(org_id or body.get("orgId"))
    if not org_id:
        return {"ok": False, "error": "missing_org_id"}, 400
    if org_id == DEFAULT_ORG_ID and not body.get("force"):
        return {"ok": False, "error": "default_org_archive_requires_force"}, 409
    disable_users = bool(body.get("disableUsers"))
    ts = now()
    changed_members = 0
    disabled_users = 0
    with LOCK:
        org = next((o for o in STATE.get("organizations") or [] if normalize_org_id(o.get("id")) == org_id), None)
        if not org:
            return {"ok": False, "error": "org_not_found", "orgId": org_id}, 404
        org["status"] = "archived"
        org["archivedAt"] = ts
        org["updatedAt"] = ts
        user_ids = set()
        for m in STATE.get("memberships") or []:
            if normalize_org_id(m.get("orgId")) == org_id and m.get("status", "active") != "archived":
                m["status"] = "archived"
                m["archivedAt"] = ts
                m["updatedAt"] = ts
                changed_members += 1
                if m.get("userId"):
                    user_ids.add(m.get("userId"))
        if disable_users and user_ids:
            active_elsewhere = {m.get("userId") for m in (STATE.get("memberships") or []) if m.get("userId") in user_ids and normalize_org_id(m.get("orgId")) != org_id and m.get("status", "active") == "active"}
            for u in STATE.get("users") or []:
                if u.get("id") in user_ids and u.get("id") not in active_elsewhere:
                    u["status"] = "inactive"
                    u["updatedAt"] = ts
                    disabled_users += 1
        persist()
    return {"ok": True, "orgId": org_id, "organization": dict(org), "archivedMemberships": changed_members, "disabledUsers": disabled_users, "archivedAt": ts}, 200


def update_org_quota(org_id, body):
    org_id = normalize_org_id(org_id)
    current = org_quota(org_id)
    next_quota = dict(current)
    for k in ("tasksPerDay", "accounts", "nodes", "materials"):
        if k in body:
            try:
                next_quota[k] = max(0, min(1000000, int(body.get(k) or 0)))
            except Exception:
                return {"ok": False, "error": "invalid_" + k}, 400
    if "enforce" in body:
        next_quota["enforce"] = bool(body.get("enforce"))
    with LOCK:
        STATE.setdefault("orgQuotas", {})[org_id] = next_quota
        persist()
    return {"ok": True, "orgId": org_id, "quota": org_quota(org_id), "usage": enterprise_usage(org_id)}, 200






ONBOARDING_STEP_LABELS = {
    "workspace": "\u4f01\u4e1a\u5de5\u4f5c\u533a",
    "node": "\u6267\u884c\u8282\u70b9",
    "account": "\u8d26\u53f7\u6388\u6743",
    "assets": "\u7d20\u6750\u4e0e\u77e5\u8bc6",
    "controls": "\u9650\u989d\u4e0e\u544a\u8b66",
}


# P1.98 customer delivery summary: server-side onboarding next action for SaaS tenants.
ONBOARDING_DELIVERY_META = {
    "workspace": {
        "action": "open_enterprise",
        "module": "enterprise",
        "requiredRole": "admin",
        "ctaLabel": "\u67e5\u770b\u4f01\u4e1a\u4e0e\u6210\u5458",
        "businessImpact": "\u5ba2\u6237\u8fd8\u6ca1\u6709\u5b8c\u6574\u7684\u79df\u6237\u5de5\u4f5c\u533a\uff0c\u65e0\u6cd5\u505a\u6210\u591a\u7528\u6237\u4ea4\u4ed8\u3002",
        "operatorHint": "\u5148\u786e\u8ba4\u4f01\u4e1a\u6210\u5458\u548c\u89d2\u8272\uff0c\u518d\u8fdb\u884c\u8282\u70b9\u548c\u8d26\u53f7\u4ea4\u4ed8\u3002",
    },
    "node": {
        "action": "check_node",
        "module": "enterprise",
        "requiredRole": "admin",
        "ctaLabel": "\u68c0\u67e5\u8282\u70b9\u6c60",
        "businessImpact": "\u6ca1\u6709\u5728\u7ebf\u6267\u884c\u8282\u70b9\uff0c\u5ba2\u6237\u65e0\u6cd5\u8fd0\u884c\u641c\u7d22\u3001\u53d1\u5e03\u548c\u6388\u6743\u4efb\u52a1\u3002",
        "operatorHint": "\u68c0\u67e5 matrix-node-api / worker / \u6d4f\u89c8\u5668\u8282\u70b9\u8fdb\u7a0b\uff0c\u786e\u4fdd\u81f3\u5c11 1 \u4e2a\u8282\u70b9\u5728\u7ebf\u3002",
    },
    "account": {
        "action": "authorize_account",
        "module": "accounts",
        "requiredRole": "member",
        "ctaLabel": "\u5f00\u59cb\u8d26\u53f7\u6388\u6743",
        "businessImpact": "\u6ca1\u6709\u53ef\u7528\u6296\u97f3\u8d26\u53f7\uff0c\u5ba2\u6237\u65e0\u6cd5\u5b8c\u6210\u5bfb\u5ba2\u6216\u53d1\u5e03\u3002",
        "operatorHint": "\u5f15\u5bfc\u5ba2\u6237\u5728\u524d\u7aef\u6253\u5f00\u6388\u6743\u6d41\u7a0b\uff0c\u626b\u7801\u540e\u6309\u77ed\u4fe1\u9a8c\u8bc1\u5b8c\u6210 Cookie/Profile \u5165\u5e93\u3002",
    },
    "assets": {
        "action": "upload_assets",
        "module": "autopub",
        "requiredRole": "member",
        "ctaLabel": "\u4e0a\u4f20\u7d20\u6750/\u77e5\u8bc6",
        "businessImpact": "\u5ba2\u6237\u8fd8\u6ca1\u6709\u7d20\u6750\u6216\u4ea7\u54c1\u77e5\u8bc6\uff0cAI \u56de\u590d\u548c\u53d1\u5e03\u7f3a\u5c11\u4f9d\u636e\u3002",
        "operatorHint": "\u5148\u6536\u96c6\u4ea7\u54c1\u5173\u952e\u8bcd\u3001\u89c6\u9891\u7d20\u6750\u548c\u8bdd\u672f\u77e5\u8bc6\uff0c\u518d\u5f00\u59cb\u8bd5\u8fd0\u884c\u3002",
    },
    "controls": {
        "action": "configure_controls",
        "module": "enterprise",
        "requiredRole": "admin",
        "ctaLabel": "\u914d\u7f6e\u9650\u989d\u544a\u8b66",
        "businessImpact": "\u672a\u5f00\u542f\u9650\u989d\u6216\u5173\u952e\u544a\u8b66\uff0c\u5546\u4e1a\u5ba2\u6237\u51fa\u95ee\u9898\u65f6\u96be\u4ee5\u63a7\u5236\u5f71\u54cd\u9762\u3002",
        "operatorHint": "\u5efa\u8bae\u542f\u7528\u65e5\u4efb\u52a1\u9650\u989d\u6267\u884c\u548c critical Webhook\uff0c\u5f62\u6210\u5546\u4e1a\u8fd0\u7ef4\u95ed\u73af\u3002",
    },
}


def onboarding_delivery_summary(org_id, steps, state=None):
    org_id = normalize_org_id(org_id)
    state = state if isinstance(state, dict) else {}
    steps = steps if isinstance(steps, list) else []
    total = len(steps)
    ready = len([x for x in steps if x.get("currentDone") or x.get("done")])
    progress = int(round((ready / max(1, total)) * 100)) if total else 0
    pending = [x for x in steps if not (x.get("currentDone") or x.get("done"))]
    all_ready = bool(total and ready == total)
    status = "ready" if all_ready else ("not_started" if ready == 0 else "in_progress")
    next_step = None if all_ready else (pending[0] if pending else None)
    next_key = str((next_step or {}).get("key") or "")
    action = dict(ONBOARDING_DELIVERY_META.get(next_key) or {})
    if all_ready:
        action = {
            "action": "start_pilot",
            "module": "finder",
            "requiredRole": "member",
            "ctaLabel": "\u521b\u5efa\u9996\u4e2a\u8bd5\u8fd0\u884c\u4efb\u52a1",
            "businessImpact": "\u57fa\u7840\u4ea4\u4ed8\u5df2\u5b8c\u6210\uff0c\u53ef\u8fdb\u5165\u4ea7\u54c1\u5173\u952e\u8bcd\u5bfb\u5ba2\u6216\u53d1\u5e03\u8bd5\u8fd0\u884c\u3002",
            "operatorHint": "\u5148\u4f7f\u7528\u4f4e\u9891\u8bd5\u8fd0\u884c\u4efb\u52a1\u786e\u8ba4\u8d26\u53f7\u3001\u8282\u70b9\u3001\u7d20\u6750\u548c\u544a\u8b66\u94fe\u8def\u3002",
        }
    elif not action:
        action = {
            "action": "open_enterprise",
            "module": "enterprise",
            "ctaLabel": "\u7ee7\u7eed\u5904\u7406",
            "requiredRole": "member",
            "businessImpact": "\u5f85\u5b8c\u6210\u7684\u4ea4\u4ed8\u9879\u4f1a\u5f71\u54cd\u5ba2\u6237\u6b63\u5e38\u4f7f\u7528\u3002",
            "operatorHint": "\u6309\u7167\u4ea4\u4ed8\u6e05\u5355\u9010\u9879\u6392\u969c\u3002",
        }
    action["key"] = action.get("action") or next_key or "open_enterprise"
    action["stepKey"] = next_key if next_key else ("ready" if all_ready else "")
    roadmap = []
    for idx, step in enumerate(steps):
        key = str(step.get("key") or "")
        meta = ONBOARDING_DELIVERY_META.get(key) or {}
        done = bool(step.get("currentDone") or step.get("done"))
        roadmap.append({
            "sequence": idx + 1,
            "key": key,
            "label": step.get("label") or ONBOARDING_STEP_LABELS.get(key) or key,
            "done": done,
            "detail": step.get("detail") or "",
            "action": meta.get("action") or "open_enterprise",
            "module": meta.get("module") or step.get("source") or "enterprise",
            "ctaLabel": meta.get("ctaLabel") or "\u5904\u7406",
            "businessImpact": meta.get("businessImpact") or "",
            "operatorHint": meta.get("operatorHint") or "",
            "blocking": (not done) and key in ("workspace", "node", "account"),
            "checkedAt": step.get("checkedAt") or now(),
            "firstCompletedAt": float(step.get("firstCompletedAt") or step.get("completedAt") or 0),
        })
    try:
        plan = org_plan_config(org_id)
    except Exception:
        plan = {}
    next_label = (next_step or {}).get("label") or ("\u5df2\u5c31\u7eea" if all_ready else "\u7b49\u5f85\u540c\u6b65")
    next_detail = (next_step or {}).get("detail") or action.get("operatorHint") or ""
    customer_message = "\u57fa\u7840\u4ea4\u4ed8\u5df2\u5b8c\u6210\uff0c\u53ef\u4ee5\u8fdb\u5165\u9996\u4e2a\u4f4e\u98ce\u9669\u8bd5\u8fd0\u884c\u4efb\u52a1\u3002" if all_ready else ("\u5f53\u524d\u9700\u5148\u5904\u7406\u3010" + str(next_label) + "\u3011\uff1a" + str(action.get("businessImpact") or next_detail))
    return {
        "version": 1,
        "status": status,
        "ready": all_ready,
        "blocked": bool(next_key in ("workspace", "node", "account")),
        "progressPct": progress,
        "readyCount": ready,
        "totalCount": total,
        "pendingCount": max(0, total - ready),
        "nextStep": None if all_ready else {
            "key": next_key,
            "label": next_label,
            "detail": next_detail,
            "source": (next_step or {}).get("source") or "enterprise",
        },
        "nextAction": action,
        "customerMessage": customer_message,
        "roadmap": roadmap,
        "plan": {"code": plan.get("code") or plan.get("id") or "", "name": plan.get("name") or ""},
        "updatedAt": state.get("updatedAt") or now(),
    }



def enterprise_delivery_checklist(org_id=None, steps=None):
    org_id = normalize_org_id(org_id)
    ts = now()
    steps = steps if isinstance(steps, list) else onboarding_step_snapshot(org_id)
    checks = []

    def add_check(key, label, ok, severity="info", detail="", action="open_enterprise", module="enterprise", owner_role="member", evidence=None):
        ok = bool(ok)
        sev = str(severity or "info").lower()
        if sev not in ("critical", "warning", "info"):
            sev = "info"
        checks.append({
            "key": key,
            "label": label,
            "ok": ok,
            "severity": sev,
            "detail": str(detail or "")[:260],
            "action": action or "open_enterprise",
            "module": module or "enterprise",
            "ownerRole": owner_role or "member",
            "evidence": evidence or {},
            "checkedAt": ts,
        })

    for step in steps:
        key = str(step.get("key") or "")
        meta = ONBOARDING_DELIVERY_META.get(key) or {}
        done = bool(step.get("currentDone") or step.get("done"))
        sev = "critical" if key in ("workspace", "node", "account") else ("warning" if key in ("assets", "controls") else "info")
        add_check(
            "onboarding_" + key,
            step.get("label") or ONBOARDING_STEP_LABELS.get(key) or key,
            done,
            sev,
            step.get("detail") or meta.get("operatorHint") or "",
            meta.get("action") or "open_enterprise",
            meta.get("module") or step.get("source") or "enterprise",
            meta.get("requiredRole") or "member",
            {"source": step.get("source") or "", "firstCompletedAt": step.get("firstCompletedAt") or 0},
        )

    try:
        pf_publish = enterprise_preflight(org_id, scope="publish")
    except Exception as e:
        pf_publish = {"ok": False, "summary": "publish_preflight_error", "blockers": [{"key": "publish_preflight", "detail": str(e)[:160]}]}
    try:
        pf_finder = enterprise_preflight(org_id, scope="finder")
    except Exception as e:
        pf_finder = {"ok": False, "summary": "finder_preflight_error", "blockers": [{"key": "finder_preflight", "detail": str(e)[:160]}]}
    for scope, pf, label, module in (
        ("publish", pf_publish, "\u53d1\u5e03\u4efb\u52a1\u9884\u68c0", "autopub"),
        ("finder", pf_finder, "\u5bfb\u5ba2\u4efb\u52a1\u9884\u68c0", "finder"),
    ):
        blockers = pf.get("blockers") if isinstance(pf.get("blockers"), list) else []
        warnings = pf.get("warnings") if isinstance(pf.get("warnings"), list) else []
        add_check(
            "preflight_" + scope,
            label,
            len(blockers) == 0,
            "critical" if blockers else ("warning" if warnings else "info"),
            pf.get("summary") or ("\u5df2\u901a\u8fc7" if not blockers else "\u5b58\u5728\u963b\u585e\u9879"),
            "open_" + module,
            module,
            "member",
            {"blockers": len(blockers), "warnings": len(warnings)},
        )

    with LOCK:
        queue_rows = [dict(q) for q in (STATE.get("queue") or []) if item_org_id(q) == org_id]
    failed_queue = [q for q in queue_rows if str(q.get("status") or "").lower() in ("fail", "failed")]
    running_queue = [q for q in queue_rows if str(q.get("status") or "").lower() in ("queued", "pending", "running")]
    add_check(
        "queue_health",
        "\u53d1\u5e03\u961f\u5217\u5065\u5eb7",
        len(failed_queue) == 0,
        "warning" if failed_queue else "info",
        ("\u5931\u8d25\u961f\u5217 " + str(len(failed_queue)) + " \u4e2a\uff0c\u8fd0\u884c/\u5f85\u53d1 " + str(len(running_queue)) + " \u4e2a") if failed_queue else ("\u8fd0\u884c/\u5f85\u53d1\u961f\u5217 " + str(len(running_queue)) + " \u4e2a"),
        "open_autopub",
        "autopub",
        "member",
        {"failed": len(failed_queue), "active": len(running_queue)},
    )

    try:
        sessions = cloud_login_sessions(org_id, limit=30)
        stale_sessions = [s for s in (sessions.get("sessions") or []) if s.get("status") in ("stale", "failed")]
    except Exception:
        sessions = {"sessions": []}
        stale_sessions = []
    add_check(
        "auth_session_handoff",
        "\u6388\u6743\u4f1a\u8bdd\u4ea4\u63a5",
        len(stale_sessions) == 0,
        "warning" if stale_sessions else "info",
        ("\u5b58\u5728 " + str(len(stale_sessions)) + " \u4e2a\u5361\u4f4f/\u5931\u8d25\u7684\u6388\u6743\u4f1a\u8bdd") if stale_sessions else "\u6388\u6743\u4f1a\u8bdd\u65e0\u9700\u4ea4\u63a5\u5904\u7406",
        "open_accounts",
        "accounts",
        "member",
        {"stale": len(stale_sessions), "total": len(sessions.get("sessions") or [])},
    )

    try:
        support = list_support_links(org_id, limit=30, include_archived=False)
        open_support = support.get("items") or []
        critical_support = [x for x in open_support if x.get("severity") == "critical"]
    except Exception:
        open_support = []
        critical_support = []
    add_check(
        "support_cases",
        "\u652f\u6301\u6848\u4f8b\u95ed\u73af",
        len(critical_support) == 0,
        "warning" if critical_support else "info",
        ("\u5b58\u5728 " + str(len(critical_support)) + " \u4e2a\u9ad8\u4f18\u5148\u7ea7\u652f\u6301\u6848\u4f8b") if critical_support else ("\u6d3b\u8dc3\u652f\u6301\u6848\u4f8b " + str(len(open_support)) + " \u4e2a"),
        "open_support",
        "enterprise",
        "auditor",
        {"critical": len(critical_support), "active": len(open_support)},
    )

    blockers = [c for c in checks if c.get("severity") == "critical" and not c.get("ok")]
    warnings = [c for c in checks if c.get("severity") == "warning" and not c.get("ok")]
    ready_count = len([c for c in checks if c.get("ok")])
    total = len(checks)
    score = int(round((ready_count / max(1, total)) * 100)) if total else 0
    status = "blocked" if blockers else ("needs_attention" if warnings else "ready")
    if blockers:
        message = "\u4ea4\u4ed8\u88ab " + str(len(blockers)) + " \u4e2a\u5173\u952e\u9879\u963b\u585e\uff0c\u8bf7\u5148\u5904\u7406\u3010" + str(blockers[0].get("label") or "") + "\u3011\u3002"
        next_check = blockers[0]
    elif warnings:
        message = "\u57fa\u7840\u53ef\u7528\uff0c\u4f46\u8fd8\u6709 " + str(len(warnings)) + " \u4e2a\u8fd0\u8425\u98ce\u9669\u9700\u5904\u7406\u3002"
        next_check = warnings[0]
    else:
        message = "\u4ea4\u4ed8\u68c0\u67e5\u5df2\u901a\u8fc7\uff0c\u53ef\u4ee5\u5b89\u6392\u4f4e\u9891\u8bd5\u8fd0\u884c\u3002"
        next_check = None
    return {
        "version": 1,
        "orgId": org_id,
        "status": status,
        "score": score,
        "readyCount": ready_count,
        "totalCount": total,
        "blockerCount": len(blockers),
        "warningCount": len(warnings),
        "message": message,
        "nextCheck": next_check,
        "checks": checks,
        "summaryCards": [
            {"key": "score", "label": "\u4ea4\u4ed8\u5206", "value": str(score)},
            {"key": "blockers", "label": "\u963b\u585e\u9879", "value": str(len(blockers))},
            {"key": "warnings", "label": "\u98ce\u9669\u9879", "value": str(len(warnings))},
            {"key": "ready", "label": "\u5df2\u901a\u8fc7", "value": str(ready_count) + "/" + str(total)},
        ],
        "updatedAt": ts,
    }


def _md_cell(v):
    return str(v if v is not None else "").replace("|", "\\|").replace("\r", " ").replace("\n", " ")[:500]


def enterprise_delivery_acceptance_report(org_id=None):
    org_id = normalize_org_id(org_id)
    ob = org_onboarding(org_id)
    checklist = ob.get("deliveryChecklist") or {}
    delivery = ob.get("delivery") or {}
    with LOCK:
        org = next((dict(o) for o in (STATE.get("organizations") or []) if normalize_org_id(o.get("id")) == org_id), None)
    org_name = (org or {}).get("name") or org_id
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    status_label = {"ready": "\u5df2\u901a\u8fc7", "blocked": "\u6709\u963b\u585e", "needs_attention": "\u9700\u5173\u6ce8"}.get(checklist.get("status") or "", checklist.get("status") or "")
    lines = []
    lines.append("# \u77e9\u9635\u661f\u8230\u4f01\u4e1a\u4ea4\u4ed8\u9a8c\u6536\u6458\u8981")
    lines.append("")
    lines.append("- \u5de5\u4f5c\u533a\uff1a" + _md_cell(org_name) + " (`" + _md_cell(org_id) + "`)")
    lines.append("- \u751f\u6210\u65f6\u95f4\uff1a" + generated_at)
    lines.append("- \u4ea4\u4ed8\u72b6\u6001\uff1a" + _md_cell(status_label))
    lines.append("- \u4ea4\u4ed8\u5206\uff1a" + str(checklist.get("score") if checklist.get("score") is not None else "--"))
    lines.append("- \u963b\u585e\u9879/\u98ce\u9669\u9879\uff1a" + str(checklist.get("blockerCount") or 0) + " / " + str(checklist.get("warningCount") or 0))
    lines.append("")
    lines.append("## \u4ea4\u4ed8\u7ed3\u8bba")
    lines.append("")
    lines.append(_md_cell(checklist.get("message") or delivery.get("customerMessage") or ""))
    lines.append("")
    next_check = checklist.get("nextCheck") if isinstance(checklist.get("nextCheck"), dict) else None
    if next_check:
        lines.append("## \u4e0b\u4e00\u6b65")
        lines.append("")
        lines.append("- \u5904\u7406\u9879\uff1a" + _md_cell(next_check.get("label") or next_check.get("key") or ""))
        lines.append("- \u8d23\u4efb\u89d2\u8272\uff1a" + _md_cell(next_check.get("ownerRole") or "member"))
        lines.append("- \u5efa\u8bae\u52a8\u4f5c\uff1a" + _md_cell(next_check.get("action") or ""))
        lines.append("")
    lines.append("## \u68c0\u67e5\u9879")
    lines.append("")
    lines.append("| \u9879\u76ee | \u72b6\u6001 | \u7ea7\u522b | \u8bf4\u660e |")
    lines.append("| --- | --- | --- | --- |")
    for c in checklist.get("checks") or []:
        ok = "OK" if c.get("ok") else "WAIT"
        lines.append("| " + _md_cell(c.get("label") or c.get("key") or "") + " | " + ok + " | " + _md_cell(c.get("severity") or "") + " | " + _md_cell(c.get("detail") or "") + " |")
    lines.append("")
    lines.append("## \u8bf4\u660e")
    lines.append("")
    lines.append("- \u672c\u6458\u8981\u7531\u4e2d\u592e\u8c03\u5ea6\u670d\u52a1\u81ea\u52a8\u751f\u6210\uff0c\u4e0d\u5305\u542b Cookie\u3001Token\u3001\u77ed\u4fe1\u9a8c\u8bc1\u7801\u7b49\u654f\u611f\u4fe1\u606f\u3002")
    lines.append("- \u82e5\u72b6\u6001\u4e3a\u201c\u6709\u963b\u585e\u201d\uff0c\u5efa\u8bae\u5148\u5904\u7406\u5173\u952e\u963b\u585e\u9879\uff1b\u82e5\u4e3a\u201c\u9700\u5173\u6ce8\u201d\uff0c\u53ef\u4f4e\u9891\u8bd5\u8fd0\u884c\u5e76\u540c\u6b65\u5904\u7406\u98ce\u9669\u9879\u3002")
    markdown = "\n".join(lines).strip() + "\n"
    filename = "matrixship-delivery-" + org_id.replace("/", "-") + "-" + time.strftime("%Y%m%d", time.localtime()) + ".md"

    return {
        "ok": True,
        "orgId": org_id,
        "organization": {"id": org_id, "name": org_name},
        "filename": filename,
        "markdown": markdown,
        "summary": {
            "status": checklist.get("status"),
            "score": checklist.get("score"),
            "blockerCount": checklist.get("blockerCount") or 0,
            "warningCount": checklist.get("warningCount") or 0,
            "generatedAt": generated_at,
        },
    }



def enterprise_delivery_risks(org_id=None, limit=30):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(100, max(1, int(limit or 30)))
    except Exception:
        limit = 30
    onboarding = org_onboarding(org_id)
    checklist = (onboarding.get("deliveryChecklist") or {}) if isinstance(onboarding, dict) else {}
    action_snapshot = enterprise_action_items(org_id, limit=100, include_snoozed=False)
    ts_now = now()
    risks = []

    def _owner_for(module="", action="", kind=""):
        m = str(module or "").lower()
        a = str(action or "").lower()
        k = str(kind or "").lower()
        if m == "accounts" or "auth" in a or "account" in k:
            return "member"
        if m == "enterprise" or "node" in k:
            return "admin"
        if "support" in k:
            return "auditor"
        return "member"

    def _severity(v):
        v = str(v or "info").lower()
        return v if v in ("critical", "warning", "info") else "info"

    def _add(source, key, severity, title, description, action_label="", module="enterprise", action="", owner_role="", resource=None, ts=None):
        title = str(title or "").strip()
        description = str(description or "").strip()
        if not title and not description:
            return
        resource = resource if isinstance(resource, dict) else {}
        owner_role = owner_role or _owner_for(module, action, key)
        rid = "drisk_" + _short_hash(json.dumps({"orgId": org_id, "source": source, "key": key, "resource": resource, "title": title}, ensure_ascii=False, sort_keys=True))
        if any(x.get("id") == rid for x in risks):
            return
        risks.append({
            "id": rid,
            "source": source,
            "key": key or rid,
            "severity": _severity(severity),
            "title": title,
            "description": description,
            "actionLabel": action_label or "\u5904\u7406",
            "module": module or "enterprise",
            "action": action or "open_enterprise",
            "ownerRole": owner_role,
            "resource": resource,
            "ts": ts or ts_now,
            "ageSec": max(0, int(ts_now - float(ts or ts_now))) if ts else 0,
        })

    for c in checklist.get("checks") or []:
        if not isinstance(c, dict) or c.get("ok"):
            continue
        _add(
            "delivery_check",
            c.get("key") or c.get("label") or "delivery_check",
            c.get("severity") or "warning",
            c.get("label") or "\u4ea4\u4ed8\u68c0\u67e5\u672a\u901a\u8fc7",
            c.get("detail") or checklist.get("message") or "",
            c.get("actionLabel") or "\u5904\u7406\u4ea4\u4ed8\u9879",
            c.get("module") or "enterprise",
            c.get("action") or "open_enterprise",
            c.get("ownerRole") or "",
            {"checkKey": c.get("key") or ""},
            checklist.get("updatedAt") or onboarding.get("updatedAt") or ts_now,
        )

    for it in action_snapshot.get("items") or []:
        if not isinstance(it, dict):
            continue
        sev = _severity(it.get("severity"))
        if sev == "info" and len(risks) >= max(6, limit // 2):
            continue
        ref = it.get("ref") if isinstance(it.get("ref"), dict) else {}
        act = it.get("action") if isinstance(it.get("action"), dict) else {}
        module = act.get("module") or ("accounts" if act.get("type") in ("account", "account_auth") else ("autopub" if act.get("type") == "queue" else "enterprise"))
        _add(
            "action_item",
            it.get("id") or it.get("kind") or "action_item",
            sev,
            it.get("title") or "\u5f85\u5904\u7406\u4e8b\u9879",
            it.get("description") or "",
            it.get("actionLabel") or "\u5904\u7406",
            module,
            act.get("type") or it.get("kind") or "open_enterprise",
            ref.get("ownerRole") or "",
            ref,
            it.get("ts") or ts_now,
        )

    order = {"critical": 0, "warning": 1, "info": 2}
    risks = sorted(risks, key=lambda x: (order.get(x.get("severity"), 9), -(float(x.get("ts") or 0))))[:limit]
    counts = {"critical": 0, "warning": 0, "info": 0, "total": len(risks)}
    by_owner = {}
    by_source = {}
    for r in risks:
        sev = r.get("severity") or "info"
        counts[sev] = counts.get(sev, 0) + 1
        owner = r.get("ownerRole") or "member"
        by_owner[owner] = by_owner.get(owner, 0) + 1
        source = r.get("source") or "unknown"
        by_source[source] = by_source.get(source, 0) + 1
    if counts.get("critical"):
        status = "blocked"
        headline = "\u5ba2\u6237\u4ea4\u4ed8\u6709 " + str(counts.get("critical") or 0) + " \u4e2a\u963b\u585e\u9879"
        message = "\u8bf7\u5148\u5904\u7406\u7ea2\u8272\u963b\u585e\uff0c\u5426\u5219\u5ba2\u6237\u4f1a\u5728\u767b\u5f55\u3001\u53d1\u5e03\u6216\u552e\u540e\u56de\u6267\u4e0a\u4f53\u611f\u5230\u4e0d\u53ef\u7528\u3002"
    elif counts.get("warning"):
        status = "needs_attention"
        headline = "\u5ba2\u6237\u4ea4\u4ed8\u9700\u5173\u6ce8 " + str(counts.get("warning") or 0) + " \u4e2a\u98ce\u9669\u9879"
        message = "\u53ef\u8fdb\u884c\u4f4e\u9891\u8bd5\u8fd0\u884c\uff0c\u4f46\u5e94\u5728\u5ba2\u6237\u4ea4\u4ed8\u524d\u5b8c\u6210\u8d23\u4efb\u5206\u6d3e\u548c\u95ed\u73af\u3002"
    else:
        status = "ready"
        headline = "\u5ba2\u6237\u4ea4\u4ed8\u98ce\u9669\u5df2\u95ed\u73af"
        message = "\u5f53\u524d\u6ca1\u6709\u660e\u786e\u7684\u963b\u585e\u6216\u98ce\u9669\u9879\uff0c\u53ef\u6309\u9a8c\u6536\u6d41\u7a0b\u63a8\u8fdb\u3002"
    return {
        "ok": True,
        "orgId": org_id,
        "status": status,
        "headline": headline,
        "message": message,
        "counts": counts,
        "byOwner": by_owner,
        "bySource": by_source,
        "nextRisk": risks[0] if risks else None,
        "items": risks,
        "summaryCards": [
            {"key": "critical", "label": "\u963b\u585e", "value": str(counts.get("critical") or 0)},
            {"key": "warning", "label": "\u98ce\u9669", "value": str(counts.get("warning") or 0)},
            {"key": "support", "label": "\u552e\u540e", "value": str(by_source.get("action_item") or 0)},
            {"key": "owner", "label": "\u8d23\u4efb\u89d2\u8272", "value": str(len(by_owner))},
        ],
        "generatedAt": ts_now,
    }






def account_authorization_watch(org_id=None, account_id="douyin-self", node_id="", session_ref="", platform=""):
    org_id = normalize_org_id(org_id)
    account_id = (account_id or "douyin-self").strip() or "douyin-self"
    node_id = (node_id or "").strip()
    session_ref = (session_ref or "").strip()
    auth = account_authorization_status(org_id, account_id=account_id, node_id=node_id, session_ref=session_ref, platform=platform)
    try:
        flow = cloud_login_flow_state(org_id, account_id=account_id, node_id=node_id, session_ref=session_ref, platform=platform)
    except Exception as exc:
        flow = {"ok": False, "error": public_error_text(str(exc))}
    try:
        startup = enterprise_customer_startup(org_id)
    except Exception as exc:
        startup = {"ok": False, "status": "needs_attention", "headline": "\u5ba2\u6237\u542f\u52a8\u72b6\u6001\u6682\u4e0d\u53ef\u7528", "message": public_error_text(str(exc)), "nextAction": None}
    try:
        handoff = account_authorization_handoff(org_id, limit=10)
    except Exception:
        handoff = {"ok": False, "items": [], "nextItem": None}
    ready = bool(auth.get("ready"))
    blocked = bool(auth.get("blocked")) or str(auth.get("severity") or "") == "critical"
    flow_status = str((flow.get("status") or "") if isinstance(flow, dict) else "")
    if ready:
        status = "ready"
        headline = "\u8d26\u53f7\u6388\u6743\u5df2\u786e\u8ba4"
        message = "\u8d26\u53f7 Cookie \u548c\u6267\u884c\u8282\u70b9\u5df2\u53ef\u7528\uff0c\u53ef\u7ee7\u7eed\u53d1\u5e03\u961f\u5217\u6216\u5ba2\u6237\u8bd5\u8fd0\u884c\u3002"
    elif blocked:
        status = "blocked"
        headline = auth.get("headline") or "\u8d26\u53f7\u6388\u6743\u9700\u5904\u7406"
        message = auth.get("message") or "\u8bf7\u6309\u8bca\u65ad\u4fe1\u606f\u5904\u7406\u8282\u70b9\u6216\u6388\u6743\u72b6\u6001\u3002"
    elif flow_status in ("logged_in", "save_pending"):
        status = "checking"
        headline = "\u5df2\u68c0\u6d4b\u5230\u767b\u5f55\uff0c\u6b63\u5728\u4fdd\u5b58"
        message = "\u8bf7\u5728\u6388\u6743\u9875\u70b9\u51fb\u5b8c\u6210\u5e76\u4fdd\u5b58\uff0c\u7cfb\u7edf\u4f1a\u81ea\u52a8\u540c\u6b65\u8d26\u53f7\u8d44\u4ea7\u3002"
    elif flow_status in ("running", "active", "open") or flow.get("hasSession"):
        status = "waiting"
        headline = "\u7b49\u5f85\u5ba2\u6237\u5b8c\u6210\u6388\u6743"
        message = "\u8bf7\u5ba2\u6237\u5728\u65b0\u6253\u5f00\u7684\u6388\u6743\u9875\u5b8c\u6210\u626b\u7801\u6216\u77ed\u4fe1\u9a8c\u8bc1\u3002"
    else:
        status = "waiting"
        headline = auth.get("headline") or "\u7b49\u5f85\u6388\u6743\u4f1a\u8bdd"
        message = auth.get("message") or "\u82e5\u5ba2\u6237\u5df2\u5b8c\u6210\u64cd\u4f5c\uff0c\u8bf7\u7a0d\u7b49\u8d26\u53f7\u8d44\u4ea7\u540c\u6b65\u3002"
    receipt = {
        "status": status,
        "headline": headline,
        "message": message,
        "startupStatus": startup.get("status"),
        "startupHeadline": startup.get("headline"),
        "nextAction": startup.get("nextAction") if isinstance(startup.get("nextAction"), dict) else None,
        "generatedAt": now(),
    }
    return {
        "ok": True,
        "orgId": org_id,
        "accountId": account_id,
        "nodeId": node_id or auth.get("nodeId") or flow.get("nodeId") or "",
        "sessionRef": session_ref,
        "status": status,
        "ready": ready,
        "blocked": blocked,
        "headline": headline,
        "message": message,
        "authorization": auth,
        "flow": flow,
        "customerStartup": startup,
        "handoff": handoff,
        "receipt": receipt,
        "generatedAt": now(),
    }

def enterprise_customer_startup(org_id=None):
    org_id = normalize_org_id(org_id)
    onboarding = org_onboarding(org_id)
    delivery = (onboarding.get("delivery") or {}) if isinstance(onboarding, dict) else {}
    checklist = (onboarding.get("deliveryChecklist") or {}) if isinstance(onboarding, dict) else {}
    checks = {str(c.get("key") or ""): c for c in (checklist.get("checks") or []) if isinstance(c, dict)}
    risks = enterprise_delivery_risks(org_id, limit=30)
    pilot = enterprise_pilot_runbook(org_id)
    try:
        queue_auth = publish_queue_auth_handoff(org_id, limit=50)
    except Exception as exc:
        queue_auth = {"ok": False, "status": "needs_attention", "headline": "\u961f\u5217\u6388\u6743\u4ea4\u63a5\u6682\u4e0d\u53ef\u7528", "message": public_error_text(str(exc)), "counts": {}, "items": [], "nextItem": None}
    try:
        queue_recovery = publish_queue_recovery_advice(org_id, limit=50)
    except Exception as exc:
        queue_recovery = {"ok": False, "status": "needs_attention", "headline": "\u961f\u5217\u6062\u590d\u5efa\u8bae\u6682\u4e0d\u53ef\u7528", "message": public_error_text(str(exc)), "actions": [], "counts": {}}
    auth = queue_auth.get("authHandoff") if isinstance(queue_auth.get("authHandoff"), dict) else account_authorization_handoff(org_id, limit=30)
    usage = enterprise_usage(org_id)
    with LOCK:
        library_count = len([dict(m) for m in (STATE.get("library") or []) if item_org_id(m) == org_id])
        queue_count = len([dict(q) for q in (STATE.get("queue") or []) if item_org_id(q) == org_id])
    risk_counts = risks.get("counts") if isinstance(risks.get("counts"), dict) else {}
    auth_counts = auth.get("counts") if isinstance(auth.get("counts"), dict) else {}
    queue_counts = queue_auth.get("counts") if isinstance(queue_auth.get("counts"), dict) else {}

    def _check_ok(key):
        c = checks.get(key) or {}
        return bool(c.get("ok"))

    def _card(key, label, value, status, detail, module="enterprise", action="open_enterprise", cta="\u5904\u7406"):
        status = status if status in ("ready", "blocked", "needs_attention") else "needs_attention"
        return {
            "key": key,
            "label": label,
            "value": str(value),
            "status": status,
            "detail": detail,
            "module": module,
            "action": action,
            "ctaLabel": cta,
        }

    tenant_ready = _check_ok("tenant") or _check_ok("controls")
    auth_ready = (auth.get("status") == "ready")
    assets_ready = (library_count > 0) or _check_ok("onboarding_assets")
    queue_ready = (queue_auth.get("status") == "ready") and int(queue_counts.get("authBlocked") or 0) == 0
    pilot_ready = bool(pilot.get("canStart")) and pilot.get("status") != "blocked"
    risk_blocked = int(risk_counts.get("critical") or 0) > 0
    risk_warning = int(risk_counts.get("warning") or 0) > 0

    cards = [
        _card("tenant", "\u4f01\u4e1a\u5de5\u4f5c\u533a", "OK" if tenant_ready else "WAIT", "ready" if tenant_ready else "needs_attention", "\u5ba2\u6237\u7ec4\u7ec7\u3001\u89d2\u8272\u548c\u5ba1\u8ba1\u57fa\u7840\u80fd\u529b\u3002", "enterprise", "open_enterprise", "\u67e5\u770b"),
        _card("auth", "\u8d26\u53f7\u6388\u6743", str(auth_counts.get("ready") or 0) + "/" + str(auth_counts.get("total") or 0), "ready" if auth_ready else ("blocked" if auth.get("status") == "blocked" else "needs_attention"), auth.get("message") or "", "accounts", "authorize_account", "\u53bb\u6388\u6743"),
        _card("assets", "\u7d20\u6750\u8bdd\u672f", library_count, "ready" if assets_ready else "needs_attention", "\u81f3\u5c11\u51c6\u5907 1 \u4e2a\u53ef\u8bd5\u8fd0\u884c\u7d20\u6750\u548c\u4ea7\u54c1\u8bdd\u672f\u3002", "autopub", "upload_assets", "\u53bb\u7d20\u6750"),
        _card("queue", "\u53d1\u5e03\u961f\u5217", queue_count, "ready" if queue_ready else ("blocked" if queue_auth.get("status") == "blocked" else "needs_attention"), queue_auth.get("message") or "", "autopub", "queue_auth_handoff", "\u5904\u7406\u961f\u5217"),
        _card("pilot", "\u8bd5\u8fd0\u884c", str(pilot.get("doneCount") or 0) + "/" + str(pilot.get("totalCount") or 0), "ready" if pilot_ready else "blocked", pilot.get("message") or "", "finder" if pilot_ready else ((pilot.get("nextPhase") or {}).get("module") or "enterprise"), (pilot.get("nextPhase") or {}).get("action") or "start_pilot", "\u5f00\u59cb\u8bd5\u8fd0\u884c" if pilot_ready else ((pilot.get("nextPhase") or {}).get("ctaLabel") or "\u5904\u7406")),
    ]

    def _step_from_card(c, idx):
        return {
            "key": c.get("key"),
            "label": c.get("label"),
            "status": c.get("status"),
            "detail": c.get("detail"),
            "order": idx,
            "module": c.get("module"),
            "action": c.get("action"),
            "ctaLabel": c.get("ctaLabel"),
        }

    steps = [_step_from_card(c, i + 1) for i, c in enumerate(cards)]
    blockers = []
    if queue_auth.get("status") != "ready":
        nxt = queue_auth.get("nextItem") if isinstance(queue_auth.get("nextItem"), dict) else None
        blockers.append({"source": "queue_auth", "title": queue_auth.get("headline") or "\u961f\u5217\u6388\u6743\u672a\u5c31\u7eea", "description": queue_auth.get("message") or "", "resource": nxt or {}, "module": "accounts", "action": (nxt or {}).get("nextAction") or "authorize_account", "actionLabel": (nxt or {}).get("actionLabel") or "\u5904\u7406\u6388\u6743"})
    if risks.get("nextRisk"):
        r = risks.get("nextRisk") or {}
        blockers.append({"source": "delivery_risk", "title": r.get("title") or risks.get("headline") or "\u4ea4\u4ed8\u98ce\u9669", "description": r.get("description") or risks.get("message") or "", "resource": r, "module": r.get("module") or "enterprise", "action": r.get("action") or "open_enterprise", "actionLabel": r.get("actionLabel") or "\u5904\u7406\u98ce\u9669"})

    next_action = None
    queue_next = queue_auth.get("nextItem") if isinstance(queue_auth.get("nextItem"), dict) else None
    if queue_auth.get("status") != "ready" and queue_next:
        next_action = {"key": "account_auth_handoff", "label": queue_auth.get("headline") or "\u5904\u7406\u8d26\u53f7\u6388\u6743", "detail": queue_auth.get("message") or "", "module": "accounts", "action": queue_next.get("nextAction") or "authorize_account", "ctaLabel": queue_next.get("actionLabel") or "\u5904\u7406\u6388\u6743", "resource": queue_next, "ownerRole": "member"}
    elif not assets_ready:
        next_action = {"key": "upload_assets", "label": "\u51c6\u5907\u8bd5\u8fd0\u884c\u7d20\u6750", "detail": "\u5148\u4e0a\u4f20\u4e00\u4e2a\u5ba2\u6237\u4ea7\u54c1\u76f8\u5173\u7d20\u6750\uff0c\u518d\u8fdb\u5165\u4f4e\u9891\u8bd5\u8fd0\u884c\u3002", "module": "autopub", "action": "upload_assets", "ctaLabel": "\u53bb\u7d20\u6750", "resource": {}, "ownerRole": "member"}
    elif not pilot_ready:
        ph = pilot.get("nextPhase") if isinstance(pilot.get("nextPhase"), dict) else {}
        next_action = {"key": ph.get("key") or "pilot_phase", "label": ph.get("label") or "\u5b8c\u6210\u8bd5\u8fd0\u884c\u524d\u7f6e\u9879", "detail": ph.get("detail") or pilot.get("message") or "", "module": ph.get("module") or "enterprise", "action": ph.get("action") or "open_enterprise", "ctaLabel": ph.get("ctaLabel") or "\u5904\u7406", "resource": ph, "ownerRole": "member"}
    elif risk_warning:
        r = risks.get("nextRisk") or {}
        next_action = {"key": "close_delivery_risk", "label": r.get("title") or "\u95ed\u73af\u4ea4\u4ed8\u98ce\u9669", "detail": r.get("description") or risks.get("message") or "", "module": r.get("module") or "enterprise", "action": r.get("action") or "open_enterprise", "ctaLabel": r.get("actionLabel") or "\u5904\u7406\u98ce\u9669", "resource": r, "ownerRole": r.get("ownerRole") or "member"}
    else:
        next_action = {"key": "start_pilot", "label": "\u5f00\u59cb\u5ba2\u6237\u4f4e\u9891\u8bd5\u8fd0\u884c", "detail": "\u4ece 1 \u4e2a\u7d20\u6750\u30011 \u4e2a\u8d26\u53f7\u3001\u4f4e\u9891\u95f4\u9694\u5f00\u59cb\uff0c\u8dd1\u901a\u56de\u6267\u540e\u518d\u6269\u5927\u3002", "module": "finder", "action": "start_pilot", "ctaLabel": "\u5f00\u59cb\u8bd5\u8fd0\u884c", "resource": {}, "ownerRole": "member"}

    if risk_blocked or queue_auth.get("status") == "blocked" or pilot.get("status") == "blocked":
        status = "blocked"
        headline = "\u5ba2\u6237\u542f\u52a8\u8fd8\u6709\u963b\u585e"
        message = "\u5148\u95ed\u73af\u6388\u6743\u3001\u7d20\u6750\u6216\u961f\u5217\u963b\u585e\uff0c\u518d\u5bf9\u5ba2\u6237\u5f00\u653e\u8bd5\u8fd0\u884c\u3002"
    elif queue_auth.get("status") != "ready" or not assets_ready or risk_warning:
        status = "needs_attention"
        headline = "\u5ba2\u6237\u542f\u52a8\u9700\u914d\u5408"
        message = "\u53ef\u6309\u4e0b\u4e00\u6b65\u6307\u5f15\u5904\u7406\uff0c\u5b8c\u6210\u540e\u7cfb\u7edf\u4f1a\u81ea\u52a8\u56de\u5230\u8bd5\u8fd0\u884c\u8def\u5f84\u3002"
    else:
        status = "ready"
        headline = "\u5ba2\u6237\u542f\u52a8\u5df2\u5c31\u7eea"
        message = "\u4f01\u4e1a\u3001\u8d26\u53f7\u3001\u7d20\u6750\u3001\u961f\u5217\u548c\u8bd5\u8fd0\u884c\u524d\u7f6e\u9879\u5df2\u8fbe\u5230\u5ba2\u6237\u53ef\u7528\u6807\u51c6\u3002"

    return {
        "ok": True,
        "orgId": org_id,
        "status": status,
        "headline": headline,
        "message": message,
        "nextAction": next_action,
        "cards": cards,
        "steps": steps,
        "blockers": blockers[:5],
        "metrics": {"libraryCount": library_count, "queueCount": queue_count, "slaScore": usage.get("slaScore"), "riskCritical": risk_counts.get("critical") or 0, "riskWarning": risk_counts.get("warning") or 0},
        "safeDefaults": pilot.get("safeDefaults") or {"sampleSize": 1, "publishPerAccountPerDay": 1, "intervalMin": 60},
        "delivery": delivery,
        "riskStatus": risks.get("status"),
        "queueAuthStatus": queue_auth.get("status"),
        "queueRecovery": queue_recovery,
        "authStatus": auth.get("status"),
        "generatedAt": now(),
    }




def _security_audit_category(action, target):
    action = str(action or "")
    target = str(target or "")
    low = (action + " " + target).lower()
    if action in ("auth.login", "auth.logout"):
        return "login"
    if action in ("auth.change_password", "auth.sessions.revoke_others", "enterprise.user.reset_password", "enterprise.user.status"):
        return "account_security"
    if action.startswith("account.authorization") or action.startswith("cloud_login") or "cloud-login" in low or "authorization" in low:
        return "authorization"
    if action.startswith("enterprise.workspace") or action.startswith("enterprise.user") or action.startswith("enterprise.org") or action.startswith("enterprise.invite"):
        return "workspace"
    if "auth" in low or "cookie" in low or "login" in low or "account" in low:
        return "authorization"
    return "other"


def _security_audit_action_label(action):
    labels = {
        "auth.login": "\u4f01\u4e1a\u8d26\u53f7\u767b\u5f55",
        "auth.logout": "\u9000\u51fa\u4f01\u4e1a\u8d26\u53f7",
        "auth.change_password": "\u4fee\u6539\u5bc6\u7801",
        "auth.sessions.revoke_others": "\u4f5c\u5e9f\u5176\u4ed6\u4f1a\u8bdd",
        "enterprise.user.reset_password": "\u7ba1\u7406\u5458\u91cd\u7f6e\u5bc6\u7801",
        "enterprise.user.status": "\u6210\u5458\u72b6\u6001\u53d8\u66f4",
        "enterprise.workspace.provision": "\u5f00\u901a\u5ba2\u6237\u5de5\u4f5c\u533a",
        "enterprise.workspace.archive": "\u5f52\u6863\u5ba2\u6237\u5de5\u4f5c\u533a",
        "enterprise.invite.create": "\u521b\u5efa\u6210\u5458\u9080\u8bf7",
        "enterprise.invite.accept": "\u63a5\u53d7\u6210\u5458\u9080\u8bf7",
        "enterprise.invite.revoke": "\u64a4\u9500\u6210\u5458\u9080\u8bf7",
        "account.authorization.restart": "\u91cd\u65b0\u53d1\u8d77\u8d26\u53f7\u6388\u6743",
        "account.authorization.recover": "\u4e00\u952e\u6062\u590d\u8d26\u53f7\u6388\u6743",
        "cloud_login.session.cleanup": "\u6e05\u7406\u6388\u6743\u4f1a\u8bdd",
        "cloud_login.session.close": "\u5173\u95ed\u6388\u6743\u4f1a\u8bdd",
    }
    return labels.get(str(action or ""), str(action or "event"))


def enterprise_security_audit(org_id=None, limit=80, q="", category="", hours=168, include_all=False):
    org_id = normalize_org_id(org_id)
    q = (q or "").strip().lower()
    category = (category or "").strip().lower()
    try:
        limit = min(200, max(1, int(limit or 80)))
    except Exception:
        limit = 80
    try:
        hours = min(24 * 90, max(1, int(hours or 168)))
    except Exception:
        hours = 168
    cutoff = now() - hours * 3600
    security_actions = {
        "auth.login", "auth.logout", "auth.change_password", "auth.sessions.revoke_others",
        "enterprise.user.reset_password", "enterprise.user.status", "enterprise.workspace.provision",
        "enterprise.workspace.archive", "account.authorization.restart", "account.authorization.recover",
        "cloud_login.session.cleanup", "cloud_login.session.close",
    }
    with LOCK:
        logs = [dict(x) for x in (STATE.get("auditLogs") or []) if isinstance(x, dict)]
        users = [dict(x) for x in (STATE.get("users") or []) if isinstance(x, dict)]
        memberships = [dict(x) for x in (STATE.get("memberships") or []) if isinstance(x, dict)]
    user_orgs_map = {}
    for m in memberships:
        uid = m.get("userId") or ""
        oid = normalize_org_id(m.get("orgId"))
        if uid and oid and (m.get("status", "active") == "active" or m.get("status") == "inactive"):
            user_orgs_map.setdefault(uid, set()).add(oid)
    users_by_id = {u.get("id"): u for u in users if u.get("id")}
    ident_to_uid = {}
    for u in users:
        uid = u.get("id") or ""
        for key in (u.get("id"), u.get("phone"), u.get("email"), u.get("name")):
            val = str(key or "").strip().lower()
            if val and uid:
                ident_to_uid[val] = uid
    rows = []
    counts = {"total": 0, "ok": 0, "failed": 0, "login": 0, "account_security": 0, "authorization": 0, "workspace": 0, "other": 0}
    actor_counts = {}
    action_counts = {}
    for log in sorted(logs, key=lambda x: float(x.get("ts") or 0), reverse=True):
        ts = float(log.get("ts") or log.get("createdAt") or 0)
        if ts < cutoff:
            continue
        action = str(log.get("action") or "")
        target = str(log.get("target") or "")
        meta = log.get("meta") if isinstance(log.get("meta"), dict) else {}
        cat = _security_audit_category(action, target)
        if action not in security_actions and cat == "other":
            continue
        event_orgs = set()
        direct_org = audit_log_org_id(log)
        if direct_org:
            event_orgs.add(direct_org)
        for uid in (log.get("actorUserId"), meta.get("userId"), meta.get("ownerId")):
            if uid and uid in user_orgs_map:
                event_orgs.update(user_orgs_map.get(uid) or set())
        ident = str(meta.get("identifier") or "").strip().lower()
        if ident and ident in ident_to_uid:
            event_orgs.update(user_orgs_map.get(ident_to_uid[ident]) or set())
        if not include_all and org_id and org_id not in event_orgs:
            continue
        if category and category != "all" and cat != category:
            continue
        actor_id = log.get("actorUserId") or meta.get("userId") or meta.get("ownerId") or ""
        actor = users_by_id.get(actor_id) or {}
        actor_name = log.get("actorName") or actor.get("name") or actor.get("phone") or actor_id or (meta.get("identifier") or "")
        hay = " ".join([action, target, actor_name, str(meta.get("accountId") or ""), str(meta.get("nodeId") or ""), str(meta.get("orgId") or "")]).lower()
        if q and q not in hay:
            continue
        ok = log.get("ok") is not False
        counts["total"] += 1
        counts["ok" if ok else "failed"] += 1
        counts[cat] = counts.get(cat, 0) + 1
        actor_key = actor_name or "unknown"
        actor_counts[actor_key] = actor_counts.get(actor_key, 0) + 1
        action_counts[action] = action_counts.get(action, 0) + 1
        safe_meta = {}
        for k in ("orgId", "userId", "ownerId", "accountId", "nodeId", "status", "error", "revokedSessions", "generatedPassword", "closed", "matched", "failed"):
            if k in meta:
                safe_meta[k] = meta.get(k)
        rows.append({
            "id": log.get("id") or "",
            "ts": ts,
            "action": action,
            "actionLabel": _security_audit_action_label(action),
            "category": cat,
            "ok": ok,
            "target": target,
            "actorUserId": actor_id,
            "actorName": actor_name,
            "ip": log.get("ip") or "",
            "orgIds": sorted(event_orgs),
            "summary": (safe_meta.get("error") or safe_meta.get("status") or target or action),
            "meta": safe_meta,
        })
        if len(rows) >= limit:
            # Counts remain accurate only up to filtered scan when we break; keep scanning
            # would be expensive in large JSON state. The next fields are labelled as windowRows.
            pass
    rows = rows[:limit]
    top_actors = sorted(actor_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_actions = sorted(action_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    cards = [
        {"key": "total", "label": "\u5b89\u5168\u4e8b\u4ef6", "value": str(counts.get("total") or 0)},
        {"key": "failed", "label": "\u5931\u8d25/\u5f02\u5e38", "value": str(counts.get("failed") or 0)},
        {"key": "authorization", "label": "\u6388\u6743\u94fe\u8def", "value": str(counts.get("authorization") or 0)},
        {"key": "account_security", "label": "\u8d26\u53f7\u5b89\u5168", "value": str(counts.get("account_security") or 0)},
    ]
    status = "needs_attention" if counts.get("failed") else "ready"
    return {
        "ok": True,
        "orgId": org_id,
        "scope": "all" if include_all else "org",
        "status": status,
        "headline": "\u767b\u5f55\u4e0e\u6388\u6743\u5ba1\u8ba1\u5df2\u540c\u6b65" if status == "ready" else "\u5b58\u5728\u9700\u590d\u6838\u7684\u767b\u5f55/\u6388\u6743\u4e8b\u4ef6",
        "message": "\u8fd1 " + str(hours) + "h \u5171 " + str(counts.get("total") or 0) + " \u6761\u5b89\u5168\u5ba1\u8ba1\uff0c\u5931\u8d25 " + str(counts.get("failed") or 0) + " \u6761\u3002",
        "cards": cards,
        "counts": counts,
        "topActors": [{"name": k, "count": v} for k, v in top_actors],
        "topActions": [{"action": k, "label": _security_audit_action_label(k), "count": v} for k, v in top_actions],
        "items": rows,
        "filters": {"category": category or "all", "q": q, "hours": hours, "limit": limit},
        "generatedAt": now(),
    }


def enterprise_commercial_readiness(org_id=None):
    org_id = normalize_org_id(org_id)
    ts_now = now()
    with LOCK:
        org = next((dict(o) for o in (STATE.get("organizations") or []) if normalize_org_id(o.get("id")) == org_id), None)
        memberships = [dict(m) for m in (STATE.get("memberships") or []) if normalize_org_id(m.get("orgId")) == org_id and m.get("status", "active") == "active"]
        users_all = list(STATE.get("users") or [])
        member_user_ids = {m.get("userId") for m in memberships}
        users = [dict(u) for u in users_all if u.get("id") in member_user_ids]
        nodes = [dict(n) for n in (STATE.get("nodes") or {}).values() if item_org_id(n) == org_id]
        library = [dict(m) for m in (STATE.get("library") or []) if item_org_id(m) == org_id]
        queue = [dict(q) for q in (STATE.get("queue") or []) if item_org_id(q) == org_id]
        audits = [dict(a) for a in (STATE.get("auditLogs") or []) if item_org_id(a) == org_id or ((a.get("meta") or {}).get("orgId") == org_id)]
    accounts = aggregate_accounts(org_id)
    entitlements = org_entitlements(org_id)
    try:
        usage = enterprise_usage(org_id)
    except Exception:
        usage = {"ok": False}
    try:
        startup = enterprise_customer_startup(org_id)
    except Exception:
        startup = {"ok": False, "status": "blocked", "headline": "startup_unavailable"}
    try:
        recovery = publish_queue_recovery_advice(org_id, limit=50)
    except Exception:
        recovery = {"ok": False, "status": "needs_attention", "counts": {}}

    online_nodes = [n for n in nodes if n.get("online") is not False]
    usable_accounts = [a for a in accounts if a.get("usable")]
    admin_members = [m for m in memberships if (m.get("role") or "") in ("owner", "admin")]
    recent_audits = [a for a in audits if float(a.get("ts") or a.get("createdAt") or 0) >= ts_now - 7 * 86400]
    queue_counts = recovery.get("counts") if isinstance(recovery.get("counts"), dict) else {}
    features = entitlements.get("features") if isinstance(entitlements.get("features"), dict) else {}
    quota = entitlements.get("effectiveQuota") if isinstance(entitlements.get("effectiveQuota"), dict) else {}
    checks = []

    def _check(key, label, ok, severity, detail, module="enterprise", action="", resource=None, value=""):
        severity = severity if severity in ("critical", "warning", "info") else "info"
        status = "ready" if ok else ("blocked" if severity == "critical" else "needs_attention")
        checks.append({
            "key": key,
            "label": label,
            "title": label,
            "ok": bool(ok),
            "status": status,
            "severity": severity,
            "detail": detail,
            "module": module,
            "action": action,
            "actionLabel": "\u5904\u7406" if not ok else "\u67e5\u770b",
            "resource": resource or {},
            "value": str(value),
        })

    _check("tenant", "\u79df\u6237\u9694\u79bb", bool(org or org_id), "critical", "orgId=" + org_id, "enterprise", "open_tenant", {"orgId": org_id}, org_id)
    _check("roles", "\u4f01\u4e1a\u89d2\u8272", len(admin_members) > 0, "warning", "admins=" + str(len(admin_members)) + ", users=" + str(len(users)), "enterprise", "manage_users", {"orgId": org_id}, len(admin_members))
    _check("nodes", "\u8282\u70b9\u6c60", len(online_nodes) > 0, "critical", "online=" + str(len(online_nodes)) + "/" + str(len(nodes)), "enterprise", "check_node", {"orgId": org_id}, len(online_nodes))
    _check("accounts", "\u8d26\u53f7\u6388\u6743", len(usable_accounts) > 0, "critical", "usable=" + str(len(usable_accounts)) + "/" + str(len(accounts)), "accounts", "authorize_account", {"accountId": "douyin-self"}, len(usable_accounts))
    _check("assets", "\u7d20\u6750\u8d44\u4ea7", len(library) > 0, "warning", "materials=" + str(len(library)), "autopub", "upload_assets", {}, len(library))
    recovery_ok = bool(recovery.get("ok")) and recovery.get("status") != "blocked" and int(queue_counts.get("blocked") or 0) == 0
    _check("queue_recovery", "\u961f\u5217\u6062\u590d", recovery_ok, "warning", recovery.get("headline") or recovery.get("message") or ("queue=" + str(len(queue))), "autopub", (recovery.get("nextAction") or {}).get("action") or "batch_preflight", (recovery.get("nextAction") or {}).get("resource") or {}, len(queue))
    _check("audit", "\u5ba1\u8ba1\u8bc1\u636e", len(audits) > 0, "warning", "audit7d=" + str(len(recent_audits)) + ", total=" + str(len(audits)), "enterprise", "open_audit", {"orgId": org_id}, len(audits))
    _check("quota", "\u5957\u9910\u989d\u5ea6", bool(quota) and bool(features), "warning", "plan=" + str((entitlements.get("plan") or {}).get("code") or "standard"), "enterprise", "open_usage", {"orgId": org_id}, (entitlements.get("plan") or {}).get("code") or "standard")
    _check("startup", "\u542f\u52a8\u72b6\u6001", startup.get("status") == "ready", "critical" if startup.get("status") == "blocked" else "warning", startup.get("headline") or startup.get("message") or "startup", (startup.get("nextAction") or {}).get("module") or "enterprise", (startup.get("nextAction") or {}).get("action") or "open_startup", (startup.get("nextAction") or {}).get("resource") or {}, startup.get("status") or "")

    critical = [c for c in checks if not c.get("ok") and c.get("severity") == "critical"]
    warning = [c for c in checks if not c.get("ok") and c.get("severity") != "critical"]
    ready_count = len([c for c in checks if c.get("ok")])
    total = len(checks) or 1
    score = int(round(ready_count * 100.0 / total))
    status = "blocked" if critical else ("needs_attention" if warning else "ready")
    headline = "\u5546\u4e1a\u7248\u4e0a\u7ebf\u6761\u4ef6\u5df2\u5c31\u7eea" if status == "ready" else ("\u5546\u4e1a\u7248\u4e0a\u7ebf\u8fd8\u6709\u5173\u952e\u963b\u585e" if status == "blocked" else "\u5546\u4e1a\u7248\u4e0a\u7ebf\u9700\u8865\u9f50\u914d\u7f6e")
    message = "\u5df2\u5b8c\u6210 " + str(ready_count) + "/" + str(total) + " \u9879\u4e0a\u7ebf\u68c0\u67e5\uff0c\u963b\u585e " + str(len(critical)) + "\uff0c\u9700\u5904\u7406 " + str(len(warning)) + "\u3002"
    next_check = (critical or warning or checks[:1])[0] if checks else {}
    next_action = {
        "label": next_check.get("label") or "\u67e5\u770b\u4e0a\u7ebf\u68c0\u67e5",
        "detail": next_check.get("detail") or "",
        "module": next_check.get("module") or "enterprise",
        "action": next_check.get("action") or "open_readiness",
        "ctaLabel": next_check.get("actionLabel") or "\u5904\u7406",
        "resource": next_check.get("resource") or {},
    }
    return {
        "ok": True,
        "orgId": org_id,
        "status": status,
        "score": score,
        "headline": headline,
        "message": message,
        "cards": [
            {"key": "score", "label": "\u4e0a\u7ebf\u5206", "value": str(score)},
            {"key": "checks", "label": "\u68c0\u67e5\u9879", "value": str(total)},
            {"key": "critical", "label": "\u963b\u585e", "value": str(len(critical))},
            {"key": "warning", "label": "\u9700\u5904\u7406", "value": str(len(warning))},
        ],
        "checks": checks,
        "nextAction": next_action,
        "counts": {"users": len(users), "admins": len(admin_members), "nodes": len(nodes), "onlineNodes": len(online_nodes), "accounts": len(accounts), "usableAccounts": len(usable_accounts), "materials": len(library), "queue": len(queue), "audits": len(audits)},
        "usage": {"plan": (entitlements.get("plan") or {}), "quota": quota, "slaScore": usage.get("slaScore") if isinstance(usage, dict) else None},
        "generatedAt": now(),
    }

def enterprise_customer_startup_receipt(org_id=None):
    org_id = normalize_org_id(org_id)
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    with LOCK:
        org = next((dict(o) for o in (STATE.get("organizations") or []) if normalize_org_id(o.get("id")) == org_id), None)
    org_name = (org or {}).get("name") or org_id
    startup = enterprise_customer_startup(org_id)
    status_label = {"ready": "\u5df2\u5c31\u7eea", "blocked": "\u6709\u963b\u585e", "needs_attention": "\u9700\u914d\u5408"}.get(startup.get("status") or "", startup.get("status") or "-")
    next_action = startup.get("nextAction") if isinstance(startup.get("nextAction"), dict) else {}
    safe = startup.get("safeDefaults") if isinstance(startup.get("safeDefaults"), dict) else {}
    metrics = startup.get("metrics") if isinstance(startup.get("metrics"), dict) else {}
    lines = []
    lines.append("# \u77e9\u9635\u661f\u8230\u5ba2\u6237\u542f\u52a8\u56de\u6267")
    lines.append("")
    lines.append("- \u5de5\u4f5c\u533a\uff1a" + _md_cell(org_name) + " (`" + _md_cell(org_id) + "`)")
    lines.append("- \u751f\u6210\u65f6\u95f4\uff1a" + generated_at)
    lines.append("- \u542f\u52a8\u72b6\u6001\uff1a" + _md_cell(status_label))
    lines.append("- \u6388\u6743\u72b6\u6001\uff1a" + _md_cell(startup.get("authStatus") or "-") + "\uff1b\u961f\u5217\u6388\u6743\uff1a" + _md_cell(startup.get("queueAuthStatus") or "-"))
    lines.append("")
    lines.append("## \u4e00\u3001\u7ba1\u7406\u7ed3\u8bba")
    lines.append("")
    lines.append(_md_cell(startup.get("headline") or "") + "\u3002" + _md_cell(startup.get("message") or ""))
    lines.append("")
    lines.append("## \u4e8c\u3001\u5f53\u524d\u6700\u5e94\u505a")
    lines.append("")
    lines.append("- \u52a8\u4f5c\uff1a" + _md_cell(next_action.get("label") or "-"))
    lines.append("- \u6309\u94ae\uff1a" + _md_cell(next_action.get("ctaLabel") or "-"))
    lines.append("- \u8d23\u4efb\u89d2\u8272\uff1a" + _md_cell(next_action.get("ownerRole") or "member"))
    lines.append("- \u8bf4\u660e\uff1a" + _md_cell(next_action.get("detail") or "-"))
    lines.append("")
    lines.append("## \u4e09\u3001\u542f\u52a8\u5361\u7247")
    lines.append("")
    lines.append("| \u9879\u76ee | \u72b6\u6001 | \u6570\u503c | \u8bf4\u660e |")
    lines.append("| --- | --- | --- | --- |")
    for c in startup.get("cards") or []:
        lines.append("| " + _md_cell(c.get("label") or c.get("key") or "") + " | " + _md_cell(c.get("status") or "") + " | " + _md_cell(c.get("value") or "") + " | " + _md_cell(c.get("detail") or "") + " |")
    lines.append("")
    lines.append("## \u56db\u3001\u963b\u585e\u4e0e\u98ce\u9669")
    lines.append("")
    blockers = startup.get("blockers") if isinstance(startup.get("blockers"), list) else []
    if blockers:
        lines.append("| \u6765\u6e90 | \u6807\u9898 | \u5904\u7406\u52a8\u4f5c | \u8bf4\u660e |")
        lines.append("| --- | --- | --- | --- |")
        for b in blockers:
            lines.append("| " + _md_cell(b.get("source") or "") + " | " + _md_cell(b.get("title") or "") + " | " + _md_cell(b.get("actionLabel") or "") + " | " + _md_cell(b.get("description") or "") + " |")
    else:
        lines.append("- \u5f53\u524d\u6ca1\u6709\u9700\u8981\u989d\u5916\u4ea4\u63a5\u7684\u963b\u585e\u9879\u3002")
    lines.append("")
    lines.append("## \u4e94\u3001\u8bd5\u8fd0\u884c\u5b89\u5168\u9ed8\u8ba4")
    lines.append("")
    lines.append("- \u6837\u672c\u91cf\uff1a" + str(safe.get("sampleSize") or 1))
    lines.append("- \u5355\u8d26\u53f7\u65e5\u53d1\u5e03\uff1a" + str(safe.get("publishPerAccountPerDay") or 1))
    lines.append("- \u95f4\u9694\uff1a" + str(safe.get("intervalMin") or 60) + " min")
    lines.append("- \u7d20\u6750\u6570\uff1a" + str(metrics.get("libraryCount") or 0) + "\uff1b\u961f\u5217\u6570\uff1a" + str(metrics.get("queueCount") or 0) + "\uff1bSLA\u5206\uff1a" + str(metrics.get("slaScore") if metrics.get("slaScore") is not None else "-"))
    lines.append("")
    lines.append("## \u516d\u3001\u5408\u89c4\u8bf4\u660e")
    lines.append("")
    lines.append("- \u672c\u56de\u6267\u4ec5\u5305\u542b\u4ea4\u4ed8\u72b6\u6001\u3001\u4e0b\u4e00\u6b65\u52a8\u4f5c\u548c\u8fd0\u8425\u5efa\u8bae\uff0c\u4e0d\u5305\u542b Cookie\u3001Token\u3001\u77ed\u4fe1\u9a8c\u8bc1\u7801\u7b49\u654f\u611f\u4fe1\u606f\u3002")
    lines.append("- \u5ba2\u6237\u5b8c\u6210\u6388\u6743\u540e\uff0c\u8bf7\u56de\u5230\u7cfb\u7edf\u5237\u65b0\u72b6\u6001\uff0c\u518d\u5f00\u59cb\u4f4e\u9891\u8bd5\u8fd0\u884c\u3002")
    markdown = "\n".join(lines).strip() + "\n"
    filename = "matrixship-startup-receipt-" + org_id.replace("/", "-") + "-" + time.strftime("%Y%m%d", time.localtime()) + ".md"
    return {"ok": True, "orgId": org_id, "filename": filename, "markdown": markdown, "summary": {"status": startup.get("status"), "headline": startup.get("headline"), "nextLabel": next_action.get("label"), "generatedAt": generated_at}}

def enterprise_pilot_runbook(org_id=None):
    org_id = normalize_org_id(org_id)
    onboarding = org_onboarding(org_id)
    checklist = (onboarding.get("deliveryChecklist") or {}) if isinstance(onboarding, dict) else {}
    checks = {str(c.get("key") or ""): c for c in (checklist.get("checks") or []) if isinstance(c, dict)}
    risks = enterprise_delivery_risks(org_id, limit=30)
    usage = enterprise_usage(org_id)
    try:
        pf_publish = enterprise_preflight(org_id, scope="publish")
    except Exception:
        pf_publish = {"ok": False, "blockers": ["publish_preflight_unavailable"]}
    try:
        pf_finder = enterprise_preflight(org_id, scope="finder")
    except Exception:
        pf_finder = {"ok": False, "blockers": ["finder_preflight_unavailable"]}
    with LOCK:
        library_count = len([dict(m) for m in (STATE.get("library") or []) if item_org_id(m) == org_id])
        queue_count = len([dict(q) for q in (STATE.get("queue") or []) if item_org_id(q) == org_id])
    risk_counts = risks.get("counts") or {}

    def _check_ok(key):
        c = checks.get(key) or {}
        return bool(c.get("ok"))

    def _phase(key, label, detail, module, action, cta, done=False, blocked=False, evidence=""):
        return {
            "key": key,
            "label": label,
            "detail": detail,
            "module": module,
            "action": action,
            "ctaLabel": cta,
            "done": bool(done),
            "blocked": bool(blocked),
            "evidence": evidence,
        }

    publish_blockers = pf_publish.get("blockers") if isinstance(pf_publish.get("blockers"), list) else []
    finder_blockers = pf_finder.get("blockers") if isinstance(pf_finder.get("blockers"), list) else []
    phases = [
        _phase("tenant_ready", "\u4f01\u4e1a\u4e0e\u6743\u9650", "\u786e\u8ba4\u5ba2\u6237\u5de5\u4f5c\u533a\u3001\u89d2\u8272\u548c\u5ba1\u8ba1\u80fd\u529b\u53ef\u7528\u3002", "enterprise", "open_enterprise", "\u67e5\u770b\u4f01\u4e1a\u4e2d\u5fc3", done=_check_ok("tenant") or _check_ok("controls"), evidence="delivery_checklist"),
        _phase("account_ready", "\u8d26\u53f7\u6388\u6743", "\u5ba2\u6237\u5b8c\u6210\u6296\u97f3\u8d26\u53f7\u6388\u6743\uff0c\u4e14\u6267\u884c\u8282\u70b9\u5728\u7ebf\u3002", "accounts", "authorize_account", "\u53bb\u6388\u6743", done=_check_ok("onboarding_account"), blocked=not _check_ok("onboarding_account"), evidence="account_authorization"),
        _phase("asset_ready", "\u7d20\u6750\u4e0e\u8bdd\u672f", "\u51c6\u5907\u81f3\u5c11 1 \u4e2a\u89c6\u9891/\u56fe\u6587\u7d20\u6750\uff0c\u5e76\u5b8c\u6210\u5ba2\u6237\u4ea7\u54c1\u8bdd\u672f\u914d\u7f6e\u3002", "autopub", "upload_assets", "\u53bb\u7d20\u6750", done=library_count > 0 or _check_ok("onboarding_assets"), blocked=library_count <= 0, evidence="library_count:" + str(library_count)),
        _phase("dry_run", "\u5e72\u8dd1\u4e0e\u56de\u6267", "\u5148\u6267\u884c\u4e0d\u771f\u53d1\u7684\u4e0a\u4f20/\u586b\u5199\u5e72\u8dd1\uff0c\u786e\u8ba4\u56de\u6267\u548c\u552e\u540e\u94fe\u63a5\u6b63\u5e38\u3002", "autopub", "dry_run", "\u53bb\u53d1\u5e03\u6d4b\u8bd5", done=bool(pf_publish.get("ok")) and not publish_blockers, blocked=bool(publish_blockers), evidence="publish_preflight"),
        _phase("finder_trial", "\u5bfb\u5ba2\u4f4e\u9891\u8bd5\u8fd0\u884c", "\u7528\u5ba2\u6237\u4ea7\u54c1\u5173\u952e\u8bcd\u505a\u5c0f\u6837\u672c\u641c\u7d22\u548c\u610f\u5411\u5206\u6790\uff0c\u5148\u770b\u6548\u679c\u518d\u6269\u5927\u91cf\u3002", "finder", "finder_trial", "\u53bb\u5bfb\u5ba2", done=bool(pf_finder.get("ok")) and not finder_blockers, blocked=bool(finder_blockers), evidence="finder_preflight"),
        _phase("acceptance", "\u9a8c\u6536\u4e0e\u590d\u76d8", "\u5bfc\u51fa\u4ea4\u4ed8\u5305\uff0c\u7559\u5b58\u8d26\u53f7\u6388\u6743\u3001\u961f\u5217\u3001\u652f\u6301\u6848\u4f8b\u548c\u5ba1\u8ba1\u8bb0\u5f55\u3002", "enterprise", "export_delivery_package", "\u5bfc\u51fa\u4ea4\u4ed8\u5305", done=(risk_counts.get("critical") or 0) == 0, blocked=False, evidence="delivery_package"),
    ]
    done_count = len([p for p in phases if p.get("done")])
    blocked_count = len([p for p in phases if p.get("blocked")])
    if blocked_count or (risk_counts.get("critical") or 0):
        status = "blocked"
        headline = "\u8bd5\u8fd0\u884c\u8fd8\u4e0d\u80fd\u5f00\u59cb"
        message = "\u5148\u5904\u7406\u8d26\u53f7\u6388\u6743\u3001\u7d20\u6750\u6216\u53d1\u5e03\u9884\u68c0\u963b\u585e\uff0c\u518d\u5411\u5ba2\u6237\u5f00\u653e\u8bd5\u8fd0\u884c\u3002"
    elif risk_counts.get("warning"):
        status = "needs_attention"
        headline = "\u53ef\u4f4e\u9891\u8bd5\u8fd0\u884c\uff0c\u9700\u5e76\u884c\u95ed\u73af\u98ce\u9669"
        message = "\u4f7f\u7528\u4f4e\u9891\u3001\u5c0f\u6837\u672c\u3001\u6709\u56de\u6267\u7684\u8bd5\u8fd0\u884c\u65b9\u5f0f\uff0c\u5e76\u5c06\u98ce\u9669\u5206\u6d3e\u7ed9\u8d23\u4efb\u4eba\u3002"
    else:
        status = "ready"
        headline = "\u53ef\u5f00\u59cb\u5ba2\u6237\u8bd5\u8fd0\u884c"
        message = "\u5efa\u8bae\u5148\u8fdb\u884c 1 \u4e2a\u7d20\u6750\u30011 \u4e2a\u8d26\u53f7\u3001\u4f4e\u9891\u95f4\u9694\u7684\u8bd5\u8fd0\u884c\uff0c\u786e\u8ba4\u56de\u6267\u540e\u518d\u6269\u5c55\u3002"
    next_phase = next((p for p in phases if p.get("blocked")), None) or next((p for p in phases if not p.get("done")), phases[-1] if phases else None)
    return {
        "ok": True,
        "orgId": org_id,
        "status": status,
        "headline": headline,
        "message": message,
        "canStart": status != "blocked",
        "doneCount": done_count,
        "totalCount": len(phases),
        "progressPct": int(round(done_count / max(1, len(phases)) * 100)),
        "blockedCount": blocked_count,
        "warningCount": risk_counts.get("warning") or 0,
        "nextPhase": next_phase,
        "phases": phases,
        "safeDefaults": {"sampleSize": 1, "publishPerAccountPerDay": 1, "intervalMin": 60, "queueCount": queue_count, "slaScore": usage.get("slaScore")},
        "generatedAt": now(),
    }

def enterprise_delivery_package_report(org_id=None):
    org_id = normalize_org_id(org_id)
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    with LOCK:
        org = next((dict(o) for o in (STATE.get("organizations") or []) if normalize_org_id(o.get("id")) == org_id), None)
    org_name = (org or {}).get("name") or org_id

    acceptance = enterprise_delivery_acceptance_report(org_id)
    onboarding = org_onboarding(org_id)
    checklist = (onboarding.get("deliveryChecklist") or {}) if isinstance(onboarding, dict) else {}
    auth = account_authorization_summary(org_id)
    usage = enterprise_usage(org_id)
    entitlements = org_entitlements(org_id)
    try:
        support = list_support_links(org_id, limit=50, include_archived=False)
    except Exception:
        support = {"ok": False, "items": [], "stats": {}, "counts": {}}
    try:
        queue_pf, _queue_status = publish_queue_batch_preflight(org_id, {"operation": "preview", "limit": 200, "statuses": ["pending", "queued", "fail", "failed"]}, user=None)
    except Exception as exc:
        queue_pf = {"ok": False, "error": "queue_preflight_unavailable", "summary": public_error_text(str(exc)), "items": [], "counts": {}}

    auth_counts = auth.get("counts") if isinstance(auth.get("counts"), dict) else {}
    queue_counts = queue_pf.get("counts") if isinstance(queue_pf.get("counts"), dict) else {}
    support_items = support.get("items") if isinstance(support.get("items"), list) else []
    support_stats = support.get("stats") if isinstance(support.get("stats"), dict) else {}
    quota = usage.get("quota") if isinstance(usage.get("quota"), dict) else {}
    quota_usage = usage.get("quotaUsage") if isinstance(usage.get("quotaUsage"), dict) else {}
    plan = entitlements.get("plan") if isinstance(entitlements.get("plan"), dict) else {}

    def _ts_label(v):
        try:
            v = float(v or 0)
            if v <= 0:
                return "-"
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v))
        except Exception:
            return "-"

    def _pct(v):
        try:
            return str(round(float(v or 0) * 100, 1)) + "%"
        except Exception:
            return "0%"

    delivery_status_label = {"ready": "\u5df2\u901a\u8fc7", "blocked": "\u6709\u963b\u585e", "needs_attention": "\u9700\u5173\u6ce8"}.get(checklist.get("status") or "", checklist.get("status") or "-")
    auth_status_label = {"healthy": "\u6388\u6743\u5065\u5eb7", "critical": "\u9700\u7acb\u5373\u5904\u7406", "warning": "\u9700\u7ef4\u62a4", "empty": "\u672a\u6388\u6743", "info": "\u5df2\u68c0\u6d4b"}.get(auth.get("status") or "", auth.get("status") or "-")
    queue_status_label = "\u53ef\u8fd0\u884c" if int(queue_counts.get("blocked") or 0) == 0 else "\u9700\u5904\u7406"
    package_status = "ready" if checklist.get("status") == "ready" and int(queue_counts.get("blocked") or 0) == 0 and auth.get("status") in ("healthy", "info") else "needs_attention"

    lines = []
    lines.append("# \u77e9\u9635\u661f\u8230\u5ba2\u6237\u4ea4\u4ed8\u5305")
    lines.append("")
    lines.append("- \u5de5\u4f5c\u533a\uff1a" + _md_cell(org_name) + " (`" + _md_cell(org_id) + "`)")
    lines.append("- \u751f\u6210\u65f6\u95f4\uff1a" + generated_at)
    lines.append("- \u4ea4\u4ed8\u72b6\u6001\uff1a" + _md_cell(delivery_status_label) + " / \u6388\u6743\uff1a" + _md_cell(auth_status_label) + " / \u961f\u5217\uff1a" + _md_cell(queue_status_label))
    lines.append("- \u5957\u9910\uff1a" + _md_cell(plan.get("name") or plan.get("code") or "Standard"))
    lines.append("")
    lines.append("## \u4e00\u3001\u7ba1\u7406\u6458\u8981")
    lines.append("")
    lines.append("| \u6307\u6807 | \u6570\u503c |")
    lines.append("| --- | --- |")
    summary_rows = [
        ("\u4ea4\u4ed8\u5206", str(checklist.get("score") if checklist.get("score") is not None else "-")),
        ("SLA \u5065\u5eb7\u5206", str(usage.get("slaScore") if usage.get("slaScore") is not None else "-")),
        ("\u8d26\u53f7\u5c31\u7eea", str(auth_counts.get("ready") or 0) + " / " + str(auth_counts.get("total") or 0)),
        ("\u6267\u884c\u8282\u70b9\u5728\u7ebf", str(auth.get("onlineNodes") or usage.get("onlineNodes") or 0) + " / " + str(auth.get("nodeCount") or usage.get("nodes") or 0)),
        ("\u53d1\u5e03\u961f\u5217\u4f53\u68c0", str(queue_counts.get("checked") or 0) + " \u4e2a\uff0c\u53ef\u6267\u884c " + str(queue_counts.get("ready") or 0) + "\uff0c\u9700\u5904\u7406 " + str(queue_counts.get("blocked") or 0)),
        ("\u672a\u95ed\u73af\u652f\u6301\u6848\u4f8b", str(len(support_items))),
        ("24h \u4efb\u52a1", str(usage.get("tasks24h") or 0) + " \u4e2a\uff0c\u6210\u529f\u7387 " + _pct(usage.get("successRate24h"))),
    ]
    for k, v in summary_rows:
        lines.append("| " + _md_cell(k) + " | " + _md_cell(v) + " |")
    lines.append("")
    lines.append("## \u4e8c\u3001\u8d26\u53f7\u6388\u6743\u4e0e\u8282\u70b9")
    lines.append("")
    lines.append("- \u72b6\u6001\uff1a" + _md_cell(auth_status_label) + "\uff1b" + _md_cell(auth.get("headline") or ""))
    lines.append("- \u9700\u91cd\u65b0\u6388\u6743\uff1a" + str(auth_counts.get("needAuth") or 0) + "\uff1b\u8282\u70b9\u95ee\u9898\uff1a" + str(auth_counts.get("nodeIssue") or 0) + "\uff1b\u6388\u6743\u8fdb\u884c\u4e2d\uff1a" + str(auth_counts.get("inProgress") or 0))
    lines.append("")
    lines.append("| \u8d26\u53f7 | \u8282\u70b9 | \u72b6\u6001 | \u8bca\u65ad | \u5efa\u8bae |")
    lines.append("| --- | --- | --- | --- | --- |")
    for a in (auth.get("items") or [])[:20]:
        state = "READY" if a.get("usable") else (a.get("code") or "WAIT")
        sug = "\uff1b".join([str(x) for x in (a.get("suggestions") or [])[:2]])
        lines.append("| " + _md_cell(a.get("name") or a.get("accountId") or "-") + " | " + _md_cell(a.get("nodeName") or a.get("nodeId") or "-") + " | " + _md_cell(state) + " | " + _md_cell(a.get("summary") or "") + " | " + _md_cell(sug or a.get("nextAction") or "") + " |")
    if not (auth.get("items") or []):
        lines.append("| - | - | WAIT | \u5c1a\u672a\u5b8c\u6210\u4efb\u4f55\u6296\u97f3\u8d26\u53f7\u6388\u6743 | \u5148\u5b8c\u6210\u7b2c\u4e00\u4e2a\u5ba2\u6237\u8d26\u53f7\u6388\u6743 |")
    lines.append("")
    lines.append("## \u4e09\u3001\u53d1\u5e03\u961f\u5217\u4f53\u68c0")
    lines.append("")
    lines.append("- " + _md_cell(queue_pf.get("summary") or ""))
    lines.append("- \u4e0b\u4e00\u6b65\uff1a" + _md_cell(queue_pf.get("nextActionLabel") or "-"))
    lines.append("")
    lines.append("| \u961f\u5217\u7f16\u53f7 | \u7d20\u6750 | \u8d26\u53f7 | \u4f53\u68c0 | \u539f\u56e0/\u5efa\u8bae |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in (queue_pf.get("items") or [])[:30]:
        state = "READY" if r.get("ready") else "BLOCKED"
        reason = r.get("error") or r.get("nextActionLabel") or ""
        lines.append("| " + _md_cell(r.get("receiptId") or r.get("queueId") or "-") + " | " + _md_cell(r.get("materialTitle") or r.get("materialId") or "-") + " | " + _md_cell(r.get("accountName") or r.get("accountId") or "-") + " | " + state + " | " + _md_cell(reason) + " |")
    if not (queue_pf.get("items") or []):
        lines.append("| - | - | - | EMPTY | \u5f53\u524d\u6ca1\u6709\u9700\u4f53\u68c0\u7684\u53d1\u5e03\u961f\u5217 |")
    lines.append("")
    lines.append("## \u56db\u3001\u652f\u6301\u6848\u4f8b\u4e0e\u95ed\u73af")
    lines.append("")
    lines.append("- \u6d3b\u8dc3\u6848\u4f8b\uff1a" + str(len(support_items)) + "\uff1b\u9ad8\u4f18\u5148\u7ea7\uff1a" + str((support_stats.get("bySeverity") or {}).get("critical") or 0))
    lines.append("")
    lines.append("| \u6848\u4f8b | \u7ea7\u522b | \u72b6\u6001 | \u4e3b\u9898 | \u8d23\u4efb\u4eba |")
    lines.append("| --- | --- | --- | --- | --- |")
    for s in support_items[:30]:
        lines.append("| " + _md_cell(s.get("id") or s.get("receipt") or "-") + " | " + _md_cell(s.get("severity") or "info") + " | " + _md_cell(s.get("status") or "open") + " | " + _md_cell(s.get("title") or s.get("summary") or "-") + " | " + _md_cell(s.get("owner") or s.get("assignee") or "-") + " |")
    if not support_items:
        lines.append("| - | - | - | \u6682\u65e0\u6d3b\u8dc3\u652f\u6301\u6848\u4f8b | - |")
    lines.append("")
    lines.append("## \u4e94\u3001\u7528\u91cf\u4e0e\u989d\u5ea6")
    lines.append("")
    lines.append("| \u9879\u76ee | \u5df2\u7528 | \u4e0a\u9650 | \u4f7f\u7528\u7387 |")
    lines.append("| --- | --- | --- | --- |")
    quota_labels = {"tasksPerDay": "\u6bcf\u65e5\u4efb\u52a1", "accounts": "\u8d26\u53f7\u6570", "nodes": "\u8282\u70b9\u6570", "materials": "\u7d20\u6750\u6570"}
    for key in ("tasksPerDay", "accounts", "nodes", "materials"):
        q = quota_usage.get(key) if isinstance(quota_usage.get(key), dict) else {}
        used = q.get("used") if q.get("used") is not None else "-"
        limit = q.get("limit") if q.get("limit") is not None else quota.get(key, "-")
        lines.append("| " + _md_cell(quota_labels.get(key, key)) + " | " + _md_cell(used) + " | " + _md_cell(limit) + " | " + _md_cell(_pct(q.get("ratio") or 0)) + " |")
    lines.append("")
    lines.append("## \u516d\u3001\u4ea4\u4ed8\u9a8c\u6536\u6458\u8981")
    lines.append("")
    acc_lines = (acceptance.get("markdown") or "").splitlines()
    if acc_lines and acc_lines[0].startswith("#"):
        acc_lines = acc_lines[1:]
    lines.extend(acc_lines)
    lines.append("")
    lines.append("## \u4e03\u3001\u5ba2\u6237\u4ea4\u4ed8\u8fb9\u754c")
    lines.append("")
    lines.append("- \u672c\u4ea4\u4ed8\u5305\u53ea\u5305\u542b\u4f01\u4e1a\u8fd0\u8425\u3001\u6388\u6743\u72b6\u6001\u3001\u961f\u5217\u4f53\u68c0\u548c\u552e\u540e\u95ed\u73af\u4fe1\u606f\uff0c\u4e0d\u5305\u542b Cookie\u3001Token\u3001\u77ed\u4fe1\u9a8c\u8bc1\u7801\u7b49\u654f\u611f\u5185\u5bb9\u3002")
    lines.append("- \u5ba2\u6237\u89c6\u89d2\u7684\u4ea4\u4ed8\u6807\u51c6\uff1a\u767b\u5f55\u6388\u6743\u53ef\u7ef4\u62a4\u3001\u4efb\u52a1\u6709\u56de\u6267\u3001\u5f02\u5e38\u6709\u6848\u4f8b\u3001\u98ce\u9669\u6709\u9884\u8b66\u3001\u7528\u91cf\u53ef\u5bf9\u8d26\u3002")
    markdown = "\n".join(lines).strip() + "\n"
    filename = "matrixship-delivery-package-" + org_id.replace("/", "-") + "-" + time.strftime("%Y%m%d", time.localtime()) + ".md"
    return {
        "ok": True,
        "orgId": org_id,
        "organization": {"id": org_id, "name": org_name},
        "filename": filename,
        "markdown": markdown,
        "summary": {
            "status": package_status,
            "deliveryStatus": checklist.get("status"),
            "deliveryScore": checklist.get("score"),
            "authStatus": auth.get("status"),
            "accountReady": auth_counts.get("ready") or 0,
            "accountTotal": auth_counts.get("total") or 0,
            "queueChecked": queue_counts.get("checked") or 0,
            "queueBlocked": queue_counts.get("blocked") or 0,
            "supportActive": len(support_items),
            "slaScore": usage.get("slaScore"),
            "generatedAt": generated_at,
        },
    }


def onboarding_step_snapshot(org_id=None):
    org_id = normalize_org_id(org_id)
    ts = now()
    with LOCK:
        org = next((dict(o) for o in (STATE.get("organizations") or []) if normalize_org_id(o.get("id")) == org_id), None)
        memberships = [dict(m) for m in (STATE.get("memberships") or []) if normalize_org_id(m.get("orgId")) == org_id]
        library = [dict(m) for m in (STATE.get("library") or []) if item_org_id(m) == org_id]
        kb_docs = [dict(d) for d in (STATE.get("kb") or []) if item_org_id(d) == org_id]
    nodes = online_nodes(org_id)
    accounts = aggregate_accounts(org_id)
    usable_accounts = [a for a in accounts if a.get("usable")]
    quota = org_quota(org_id)
    notify = notification_settings(org_id)
    controls_ready = bool(quota.get("enforce") or notify.get("criticalWebhookEnabled"))
    items = [
        {
            "key": "workspace",
            "label": ONBOARDING_STEP_LABELS["workspace"],
            "done": bool(org and memberships),
            "detail": "\u4f01\u4e1a\u5df2\u521b\u5efa\uff0c\u6210\u5458 " + str(len(memberships)) + " \u4eba" if org else "\u5c1a\u672a\u521b\u5efa\u4f01\u4e1a\u5de5\u4f5c\u533a",
            "source": "enterprise",
        },
        {
            "key": "node",
            "label": ONBOARDING_STEP_LABELS["node"],
            "done": len(nodes) > 0,
            "detail": "\u5728\u7ebf\u6267\u884c\u8282\u70b9 " + str(len(nodes)) + " \u4e2a",
            "source": "node",
        },
        {
            "key": "account",
            "label": ONBOARDING_STEP_LABELS["account"],
            "done": len(usable_accounts) > 0,
            "detail": "\u53ef\u7528\u8d26\u53f7 " + str(len(usable_accounts)) + " / " + str(len(accounts)) + " \u4e2a",
            "source": "account",
        },
        {
            "key": "assets",
            "label": ONBOARDING_STEP_LABELS["assets"],
            "done": (len(library) + len(kb_docs)) > 0,
            "detail": "\u7d20\u6750 " + str(len(library)) + " \u4e2a \u00b7 \u77e5\u8bc6 " + str(len(kb_docs)) + " \u4efd",
            "source": "content",
        },
        {
            "key": "controls",
            "label": ONBOARDING_STEP_LABELS["controls"],
            "done": controls_ready,
            "detail": ("\u5df2\u542f\u7528\u9650\u989d\u6216\u5173\u952e\u544a\u8b66" if controls_ready else "\u5efa\u8bae\u5f00\u542f\u9650\u989d\u6267\u884c\u6216 Webhook \u544a\u8b66"),
            "source": "governance",
        },
    ]
    for item in items:
        item["checkedAt"] = ts
    return items


def sync_org_onboarding_steps(org_id=None):
    org_id = normalize_org_id(org_id)
    snapshot = onboarding_step_snapshot(org_id)
    ts = now()
    changed = False
    with LOCK:
        bucket = STATE.setdefault("orgOnboarding", {})
        saved = dict(bucket.get(org_id) or {})
        saved_steps = saved.get("steps") if isinstance(saved.get("steps"), dict) else {}
        next_steps = {}
        for item in snapshot:
            key = item.get("key") or ""
            prev = dict(saved_steps.get(key) or {})
            first_at = float(prev.get("firstCompletedAt") or 0)
            if item.get("done") and not first_at:
                first_at = ts
                changed = True
            step = dict(prev)
            step.update(item)
            step["firstCompletedAt"] = first_at
            step["completedAt"] = first_at
            step["currentDone"] = bool(item.get("done"))
            next_steps[key] = step
        if saved.get("steps") != next_steps:
            saved["steps"] = next_steps
            saved["stepsUpdatedAt"] = ts
            changed = True
        if changed:
            bucket[org_id] = saved
            persist()
    return snapshot




def clean_onboarding_step_meta(raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key, max_len in (("owner", 60), ("assignee", 60), ("dueDate", 32), ("note", 240), ("status", 32)):
        if key in raw:
            out[key] = str(raw.get(key) or "").strip()[:max_len]
    if "owner" in out and "assignee" not in out:
        out["assignee"] = out.get("owner") or ""
    if "assignee" in out and "owner" not in out:
        out["owner"] = out.get("assignee") or ""
    return out


def apply_onboarding_step_meta(next_state, step_meta, ts, user=None):
    if not isinstance(step_meta, dict):
        return False
    key = str(step_meta.get("key") or "").strip()
    if key not in ONBOARDING_STEP_LABELS:
        return False
    meta = clean_onboarding_step_meta(step_meta)
    if not meta and not step_meta.get("clear"):
        return False
    steps = next_state.get("steps") if isinstance(next_state.get("steps"), dict) else {}
    steps = {k: dict(v or {}) for k, v in steps.items()}
    cur = dict(steps.get(key) or {})
    if step_meta.get("clear"):
        for f in ("owner", "assignee", "dueDate", "note", "status"):
            cur.pop(f, None)
    cur.update(meta)
    cur["metaUpdatedAt"] = ts
    if user and user.get("id"):
        cur["metaUpdatedBy"] = str(user.get("id") or "")[:80]
    steps[key] = cur
    next_state["steps"] = steps
    next_state["stepsUpdatedAt"] = ts
    return True

def org_onboarding(org_id=None):
    org_id = normalize_org_id(org_id)
    base = {
        "welcomeDismissed": False,
        "completed": False,
        "dismissedAt": 0,
        "completedAt": 0,
        "updatedAt": 0,
        "version": 2,
    }
    sync_org_onboarding_steps(org_id)
    with LOCK:
        saved = dict((STATE.setdefault("orgOnboarding", {}) or {}).get(org_id) or {})
    for k in ("welcomeDismissed", "completed"):
        if k in saved:
            base[k] = bool(saved.get(k))
    for k in ("dismissedAt", "completedAt", "updatedAt", "stepsUpdatedAt"):
        try:
            base[k] = float(saved.get(k) or 0)
        except Exception:
            base[k] = 0
    if saved.get("updatedBy"):
        base["updatedBy"] = str(saved.get("updatedBy") or "")[:80]
    saved_steps = saved.get("steps") if isinstance(saved.get("steps"), dict) else {}
    steps = []
    for item in onboarding_step_snapshot(org_id):
        prev = dict(saved_steps.get(item.get("key")) or {})
        merged = dict(prev)
        merged.update(item)
        merged["currentDone"] = bool(item.get("done"))
        merged["firstCompletedAt"] = float(prev.get("firstCompletedAt") or 0)
        merged["completedAt"] = float(prev.get("completedAt") or prev.get("firstCompletedAt") or 0)
        steps.append(merged)
    base["steps"] = steps
    base["readyCount"] = len([x for x in steps if x.get("currentDone")])
    base["totalCount"] = len(steps)
    base["allReady"] = bool(steps and base["readyCount"] == base["totalCount"])
    base["delivery"] = onboarding_delivery_summary(org_id, steps, base)
    base["deliveryChecklist"] = enterprise_delivery_checklist(org_id, steps)
    base["delivery"]["checklist"] = {
        "status": (base.get("deliveryChecklist") or {}).get("status"),
        "score": (base.get("deliveryChecklist") or {}).get("score"),
        "blockerCount": (base.get("deliveryChecklist") or {}).get("blockerCount"),
        "warningCount": (base.get("deliveryChecklist") or {}).get("warningCount"),
    }
    return base


def update_org_onboarding(org_id, body, user=None):
    org_id = normalize_org_id(org_id)
    org_onboarding(org_id)  # sync real-step timestamps before preserving raw state
    with LOCK:
        current = dict((STATE.setdefault("orgOnboarding", {}) or {}).get(org_id) or {})
    next_state = dict(current)
    ts = now()
    if body.get("reset"):
        next_state.update({"welcomeDismissed": False, "completed": False, "dismissedAt": 0, "completedAt": 0})
    if body.get("resetSteps"):
        next_state["steps"] = {}
        next_state["stepsUpdatedAt"] = ts
    if "welcomeDismissed" in body or "dismissed" in body:
        val = bool(body.get("welcomeDismissed", body.get("dismissed")))
        next_state["welcomeDismissed"] = val
        next_state["dismissedAt"] = ts if val else 0
    if "completed" in body:
        val = bool(body.get("completed"))
        next_state["completed"] = val
        next_state["completedAt"] = ts if val else 0
        if val:
            next_state["welcomeDismissed"] = True
            if not next_state.get("dismissedAt"):
                next_state["dismissedAt"] = ts
    step_meta = body.get("stepMeta") or body.get("step")
    apply_onboarding_step_meta(next_state, step_meta, ts, user=user)
    bulk_meta = body.get("stepsMeta") if isinstance(body.get("stepsMeta"), dict) else {}
    for key, raw in bulk_meta.items():
        if isinstance(raw, dict):
            row = dict(raw)
            row.setdefault("key", key)
            apply_onboarding_step_meta(next_state, row, ts, user=user)
    next_state["updatedAt"] = ts
    if user and user.get("id"):
        next_state["updatedBy"] = str(user.get("id") or "")[:80]
    with LOCK:
        STATE.setdefault("orgOnboarding", {})[org_id] = next_state
        persist()
    return {"ok": True, "orgId": org_id, "onboarding": org_onboarding(org_id)}, 200


def is_billable_task_path(path):
    path = str(path or "")
    if path.startswith("/api/cloud-login/"):
        return False
    return path in TASK_POST_PATHS


def quota_usage_count(org_id, resource):
    org_id = normalize_org_id(org_id)
    ts = now()
    with LOCK:
        if resource == "tasksPerDay":
            return len([
                t for t in (STATE.get("tasks") or {}).values()
                if item_org_id(t) == org_id
                and is_billable_task_path(t.get("path") or "")
                and float(t.get("createdAt") or 0) >= ts - 86400
            ])
        if resource == "materials":
            return len([m for m in (STATE.get("library") or []) if item_org_id(m) == org_id])
        if resource == "nodes":
            return len([n for n in (STATE.get("nodes") or {}).values() if item_org_id(n) == org_id])
    if resource == "accounts":
        return len(aggregate_accounts(org_id))
    return 0


def quota_guard(org_id, resource, increment=1):
    org_id = normalize_org_id(org_id)
    quota = org_quota(org_id)
    if not quota.get("enforce"):
        return None
    limit = int(quota.get(resource) or 0)
    if limit <= 0:
        return None
    used = quota_usage_count(org_id, resource)
    if used + int(increment or 1) <= limit:
        return None
    return {
        "ok": False,
        "error": "quota_" + resource + "_exceeded",
        "message": "\u5957\u9910\u989d\u5ea6\u5df2\u7528\u5b8c\uff0c\u8bf7\u5347\u7ea7\u5957\u9910\u6216\u8054\u7cfb\u7ba1\u7406\u5458\u8c03\u6574\u989d\u5ea6",
        "orgId": org_id,
        "resource": resource,
        "used": used,
        "limit": limit,
        "enforce": True,
        "quota": quota,
    }

def ratio(n, d):
    try:
        d = float(d or 0)
        if d <= 0:
            return 0.0
        return round(float(n or 0) / d, 4)
    except Exception:
        return 0.0


def enterprise_usage(org_id=None):
    org_id = normalize_org_id(org_id)
    ts = now()
    with LOCK:
        tasks = [dict(t) for t in (STATE.get("tasks") or {}).values() if item_org_id(t) == org_id]
        nodes = [dict(n) for n in (STATE.get("nodes") or {}).values() if item_org_id(n) == org_id]
        library = [dict(m) for m in (STATE.get("library") or []) if item_org_id(m) == org_id]
        queue = [dict(q) for q in (STATE.get("queue") or []) if item_org_id(q) == org_id]
    accounts = aggregate_accounts(org_id)
    tasks24 = [t for t in tasks if float(t.get("createdAt") or 0) >= ts - 86400]
    tasks7 = [t for t in tasks if float(t.get("createdAt") or 0) >= ts - 7 * 86400]
    billable_tasks24 = [t for t in tasks24 if is_billable_task_path(t.get("path") or "")]
    billable_tasks7 = [t for t in tasks7 if is_billable_task_path(t.get("path") or "")]
    def count_by(rows, fn):
        out = {}
        for row in rows:
            key = fn(row) or "unknown"
            out[key] = out.get(key, 0) + 1
        return out
    status24 = count_by(tasks24, lambda t: t.get("status") or "unknown")
    status7 = count_by(tasks7, lambda t: t.get("status") or "unknown")
    type24 = count_by(tasks24, lambda t: task_type_key(t.get("path") or ""))
    type7 = count_by(tasks7, lambda t: task_type_key(t.get("path") or ""))
    finished = [t for t in tasks7 if t.get("status") in ("done", "failed") and t.get("startedAt") and t.get("finishedAt")]
    durations = [max(0, float(t.get("finishedAt") or 0) - float(t.get("startedAt") or 0)) for t in finished]
    done24 = status24.get("done", 0)
    failed24 = status24.get("failed", 0)
    terminal24 = done24 + failed24
    success_rate = ratio(done24, terminal24) if terminal24 else 1.0
    failure_rate = ratio(failed24, terminal24) if terminal24 else 0.0
    online_nodes = len([n for n in nodes if ts - float(n.get("lastSeen") or 0) <= NODE_TIMEOUT_SEC])
    node_rate = ratio(online_nodes, len(nodes)) if nodes else 0.0
    usable_accounts = len([a for a in accounts if a.get("usable")])
    account_rate = ratio(usable_accounts, len(accounts)) if accounts else 0.0
    quota = org_quota(org_id)
    quota_usage = {
        "tasksPerDay": {"used": len(billable_tasks24), "limit": quota.get("tasksPerDay", 0), "ratio": ratio(len(billable_tasks24), quota.get("tasksPerDay")) if quota.get("tasksPerDay") else 0},
        "accounts": {"used": len(accounts), "limit": quota.get("accounts", 0), "ratio": ratio(len(accounts), quota.get("accounts")) if quota.get("accounts") else 0},
        "nodes": {"used": len(nodes), "limit": quota.get("nodes", 0), "ratio": ratio(len(nodes), quota.get("nodes")) if quota.get("nodes") else 0},
        "materials": {"used": len(library), "limit": quota.get("materials", 0), "ratio": ratio(len(library), quota.get("materials")) if quota.get("materials") else 0},
    }
    sla_score = round(max(0, min(100, (success_rate * 60) + (node_rate * 25) + (account_rate * 15))), 1)
    return {
        "ok": True,
        "orgId": org_id,
        "generatedAt": ts,
        "window24hSec": 86400,
        "tasks24h": len(tasks24),
        "tasks7d": len(tasks7),
        "billableTasks24h": len(billable_tasks24),
        "billableTasks7d": len(billable_tasks7),
        "status24h": status24,
        "status7d": status7,
        "type24h": type24,
        "type7d": type7,
        "queueCount": len(queue),
        "accounts": len(accounts),
        "usableAccounts": usable_accounts,
        "nodes": len(nodes),
        "onlineNodes": online_nodes,
        "materials": len(library),
        "successRate24h": success_rate,
        "failureRate24h": failure_rate,
        "nodeOnlineRate": node_rate,
        "accountReadyRate": account_rate,
        "avgDurationSec7d": round(sum(durations) / len(durations), 2) if durations else 0,
        "slaScore": sla_score,
        "quota": quota,
        "quotaUsage": quota_usage,
        "taskRecovery": task_recovery_candidates(org_id, limit=20),
    }



def enterprise_preflight_repair_actions(org_id, nodes, accounts, usable_accounts, materials, quota_ok, quota=None, tasks_used=0, task_limit=0):
    org_id = normalize_org_id(org_id)
    actions = []
    accounts = accounts or []
    usable_accounts = usable_accounts or []
    nodes = nodes or []
    materials = materials or []
    quota = quota or {}

    def add_action(action):
        if not action:
            return
        key = action.get("key") or action.get("type") or ("action_" + str(len(actions) + 1))
        if any(a.get("key") == key for a in actions):
            return
        action.setdefault("key", key)
        action.setdefault("severity", "info")
        actions.append(action)

    bad_accounts = [a for a in accounts if not a.get("usable")]
    primary = bad_accounts[0] if bad_accounts else (accounts[0] if accounts else {})

    if len(nodes) <= 0:
        add_action({
            "key": "node_check",
            "type": "node_check",
            "label": "\u68c0\u67e5\u6267\u884c\u8282\u70b9",
            "detail": "\u5f53\u524d\u6ca1\u6709\u5728\u7ebf\u6267\u884c\u8282\u70b9\uff0c\u8bf7\u5148\u6062\u590d\u8282\u70b9\u670d\u52a1\u6216\u8ba9\u5ba2\u670d\u534f\u52a9\u3002",
            "severity": "critical",
        })

    if len(usable_accounts) <= 0:
        add_action({
            "key": "account_auth",
            "type": "account_auth",
            "label": "\u53bb\u6388\u6743\u6296\u97f3\u8d26\u53f7",
            "detail": "\u6253\u5f00\u5ba2\u6237\u53ef\u7406\u89e3\u7684\u6388\u6743\u5411\u5bfc\uff0c\u652f\u6301\u626b\u7801\u548c\u77ed\u4fe1\u9a8c\u8bc1\u7801\u3002",
            "severity": "critical",
            "accountId": primary.get("id") or "",
            "nodeId": primary.get("nodeId") or "",
        })
        add_action({
            "key": "accounts",
            "type": "accounts",
            "label": "\u67e5\u770b\u8d26\u53f7\u77e9\u9635",
            "detail": "\u786e\u8ba4\u662f\u672a\u6388\u6743\u3001Cookie \u5931\u6548\uff0c\u8fd8\u662f\u8282\u70b9\u79bb\u7ebf\u5bfc\u81f4\u4e0d\u53ef\u7528\u3002",
            "severity": "warning" if accounts else "info",
        })
        if primary:
            sla = primary.get("repairSla") or account_repair_sla(primary)
            add_action({
                "key": "account_sla",
                "type": "account_detail",
                "label": "\u67e5\u770b\u4fee\u590d SLA",
                "detail": sla.get("handoffNote") or "\u67e5\u770b\u8d26\u53f7\u72b6\u6001\u548c\u4fee\u590d\u5efa\u8bae\u3002",
                "severity": sla.get("severity") or "warning",
                "accountId": primary.get("id") or "",
                "nodeId": primary.get("nodeId") or "",
            })

    if len(materials) <= 0:
        add_action({
            "key": "material_upload",
            "type": "material_upload",
            "label": "\u4e0a\u4f20\u53d1\u5e03\u7d20\u6750",
            "detail": "\u53d1\u5e03\u4efb\u52a1\u9700\u8981\u5148\u6709\u89c6\u9891\u6216\u56fe\u6587\u7d20\u6750\uff0c\u5bfb\u5ba2/\u62d3\u5ba2\u53ef\u5148\u5ffd\u7565\u8fd9\u9879\u5efa\u8bae\u3002",
            "severity": "info",
        })

    if not quota_ok:
        add_action({
            "key": "quota_review",
            "type": "quota_review",
            "label": "\u67e5\u770b\u5957\u9910\u989d\u5ea6",
            "detail": "\u4eca\u65e5\u4efb\u52a1\u5df2\u7528 " + str(tasks_used) + " / " + str(task_limit) + "\uff0c\u9700\u5347\u7ea7\u5957\u9910\u6216\u8c03\u6574\u79df\u6237\u9650\u989d\u3002",
            "severity": "warning",
        })

    return actions[:5]


def public_preflight_attempt(item):
    item = dict(item or {})
    item.setdefault("id", "")
    item.setdefault("orgId", DEFAULT_ORG_ID)
    item.setdefault("scope", "general")
    item.setdefault("module", "")
    item.setdefault("action", "")
    item.setdefault("summary", "")
    item.setdefault("blockers", [])
    item.setdefault("warnings", [])
    item.setdefault("createdAt", 0)
    return item


def preflight_attempt_stats(rows, window_sec=86400):
    ts_now = now()
    cutoff = ts_now - float(window_sec or 86400)
    recent = [r for r in (rows or []) if float(r.get("createdAt") or 0) >= cutoff]

    def top_counts(items, key_fn, limit=6):
        counts = {}
        last_seen = {}
        for it in items:
            key = (key_fn(it) or "").strip() or "unknown"
            counts[key] = counts.get(key, 0) + 1
            last_seen[key] = max(last_seen.get(key, 0), float(it.get("createdAt") or 0))
        return [
            {"key": k, "count": v, "lastAt": last_seen.get(k, 0)}
            for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
        ]

    blocker_items = []
    for row in recent:
        for b in row.get("blockers") or []:
            text = str(b or "").strip()
            label = text.split(":", 1)[0].strip() if text else "unknown"
            blocker_items.append({"blocker": label or "unknown", "createdAt": row.get("createdAt") or 0})

    by_scope = top_counts(recent, lambda x: x.get("scope") or x.get("module"), limit=8)
    by_module = top_counts(recent, lambda x: x.get("module") or x.get("scope"), limit=8)
    by_blocker = top_counts(blocker_items, lambda x: x.get("blocker"), limit=8)
    auth_blockers = sum(1 for x in blocker_items if "\u8d26\u53f7" in (x.get("blocker") or "") or "account" in (x.get("blocker") or "").lower())
    material_blockers = sum(1 for x in blocker_items if "\u7d20\u6750" in (x.get("blocker") or "") or "material" in (x.get("blocker") or "").lower())
    node_blockers = sum(1 for x in blocker_items if "\u8282\u70b9" in (x.get("blocker") or "") or "node" in (x.get("blocker") or "").lower())
    quota_blockers = sum(1 for x in blocker_items if "\u989d\u5ea6" in (x.get("blocker") or "") or "quota" in (x.get("blocker") or "").lower())
    return {
        "windowSec": int(window_sec or 86400),
        "total": len(rows or []),
        "windowTotal": len(recent),
        "blockerTotal": len(blocker_items),
        "byScope": by_scope,
        "byModule": by_module,
        "byBlocker": by_blocker,
        "focus": {
            "account": auth_blockers,
            "material": material_blockers,
            "node": node_blockers,
            "quota": quota_blockers,
        },
        "latestAt": max([float(r.get("createdAt") or 0) for r in (rows or [])] or [0]),
    }


def list_preflight_attempts(org_id=None, limit=30, window_sec=86400, scope="", module="", q=""):
    org_id = normalize_org_id(org_id)
    limit = max(1, min(100, int(limit or 30)))
    scope = (scope or "").strip().lower()
    module = (module or "").strip().lower()
    q = (q or "").strip().lower()
    with LOCK:
        all_rows = [public_preflight_attempt(x) for x in (STATE.get("preflightAttempts") or []) if item_org_id(x) == org_id]
    rows = list(all_rows)
    if scope and scope != "all":
        rows = [r for r in rows if (r.get("scope") or "").lower() == scope]
    if module and module != "all":
        rows = [r for r in rows if module in (r.get("module") or "").lower()]
    if q:
        def match(row):
            blob = " ".join([
                row.get("id") or "",
                row.get("scope") or "",
                row.get("module") or "",
                row.get("action") or "",
                row.get("summary") or "",
                " ".join(row.get("blockers") or []),
                " ".join(row.get("warnings") or []),
            ]).lower()
            return q in blob
        rows = [r for r in rows if match(r)]
    rows.sort(key=lambda x: x.get("createdAt") or 0, reverse=True)
    return {
        "ok": True,
        "orgId": org_id,
        "items": rows[:limit],
        "total": len(all_rows),
        "matched": len(rows),
        "filters": {"scope": scope or "all", "module": module, "q": q},
        "stats": preflight_attempt_stats(rows, window_sec=window_sec),
    }


def record_preflight_attempt(org_id, body=None, user=None):
    org_id = normalize_org_id(org_id)
    body = body or {}
    scope = (body.get("scope") or body.get("kind") or "general").strip().lower()
    if scope not in ("general", "publish", "finder", "outreach"):
        scope = "general"
    pf = body.get("preflight") if isinstance(body.get("preflight"), dict) else enterprise_preflight(org_id, scope=scope)
    checks = pf.get("checks") if isinstance(pf.get("checks"), list) else []
    blockers = body.get("blockers") if isinstance(body.get("blockers"), list) else []
    if not blockers:
        blockers = [(c.get("label") or c.get("key") or "") + (": " + (c.get("detail") or "") if c.get("detail") else "") for c in checks if c.get("severity") == "critical" and not c.get("ok")]
    warnings = [(c.get("label") or c.get("key") or "") + (": " + (c.get("detail") or "") if c.get("detail") else "") for c in checks if c.get("severity") == "warning" and not c.get("ok")]
    item = {
        "id": "pfa_" + uuid.uuid4().hex[:12],
        "orgId": org_id,
        "scope": scope,
        "module": (body.get("module") or "").strip()[:60],
        "action": (body.get("action") or body.get("msgKey") or "").strip()[:80],
        "summary": (body.get("summary") or pf.get("summary") or "").strip()[:240],
        "blockers": [str(x)[:260] for x in blockers[:8]],
        "warnings": [str(x)[:260] for x in warnings[:8]],
        "ready": bool(pf.get("ready")),
        "createdAt": now(),
        "actorUserId": (user or {}).get("id") or "",
        "actorName": (user or {}).get("name") or (user or {}).get("phone") or "",
    }
    with LOCK:
        rows = STATE.setdefault("preflightAttempts", [])
        rows.insert(0, item)
        STATE["preflightAttempts"] = rows[:500]
        persist()
    add_event("preflight_attempt_blocked", {"orgId": org_id, "scope": scope, "id": item["id"], "blockers": len(item["blockers"])})
    return {"ok": True, "orgId": org_id, "attempt": public_preflight_attempt(item)}, 200


def enterprise_preflight(org_id=None, scope="general"):
    org_id = normalize_org_id(org_id)
    scope = (scope or "general").strip().lower()
    if scope not in ("general", "publish", "finder", "outreach"):
        scope = "general"
    entitlements = org_entitlements(org_id)
    scope_feature = {"general": "taskCenter", "publish": "publish", "finder": "finder", "outreach": "outreach"}.get(scope, "taskCenter")
    plan_ok = bool((entitlements.get("features") or {}).get(scope_feature, True))
    nodes = online_nodes(org_id)
    accounts = aggregate_accounts(org_id)
    usable_accounts = [a for a in accounts if a.get("usable")]
    materials = load_library(org_id)
    quota = org_quota(org_id)
    tasks_used = quota_usage_count(org_id, "tasksPerDay")
    task_limit = int(quota.get("tasksPerDay") or 0)
    quota_ok = (not quota.get("enforce")) or task_limit <= 0 or tasks_used < task_limit
    material_count = len(materials)
    if scope == "publish":
        material_check = {
            "key": "material",
            "label": "\u7d20\u6750\u8d44\u4ea7",
            "ok": material_count > 0,
            "severity": "critical" if material_count <= 0 else "info",
            "detail": ("\u53d1\u5e03\u4efb\u52a1\u5fc5\u987b\u5148\u4e0a\u4f20\u7d20\u6750\uff0c\u5f53\u524d\u7d20\u6750\u5e93 0 \u4e2a\u3002" if material_count <= 0 else ("\u7d20\u6750\u5e93 " + str(material_count) + " \u4e2a\uff0c\u53ef\u521b\u5efa\u53d1\u5e03\u4efb\u52a1\u3002")),
        }
    elif scope in ("finder", "outreach"):
        material_check = {
            "key": "material",
            "label": "\u7d20\u6750\u8d44\u4ea7",
            "ok": True,
            "severity": "info",
            "detail": "\u7d20\u6750\u5e93 " + str(material_count) + " \u4e2a\uff1b\u5bfb\u5ba2/\u62d3\u5ba2\u4efb\u52a1\u4e0d\u5f3a\u5236\u8981\u6c42\u7d20\u6750\u3002",
        }
    else:
        material_check = {
            "key": "material",
            "label": "\u7d20\u6750\u8d44\u4ea7",
            "ok": material_count > 0,
            "severity": "warning" if material_count <= 0 else "info",
            "detail": "\u7d20\u6750\u5e93 " + str(material_count) + " \u4e2a\uff1b\u53d1\u5e03\u4efb\u52a1\u9700\u5148\u5165\u5e93\u7d20\u6750\u3002",
        }
    checks = [
        {
            "key": "central",
            "label": "\u4e2d\u592e\u8c03\u5ea6",
            "ok": True,
            "severity": "info",
            "detail": "\u4e91\u7aef API \u53ef\u8bbf\u95ee\uff0c\u4efb\u52a1\u4f1a\u7edf\u4e00\u8fdb\u5165\u8c03\u5ea6\u961f\u5217\u3002",
        },
        {
            "key": "plan",
            "label": "\u5957\u9910\u80fd\u529b",
            "ok": plan_ok,
            "severity": "critical" if not plan_ok else "info",
            "detail": ("\u5f53\u524d\u5957\u9910 " + str((entitlements.get("plan") or {}).get("name") or "") + " \u672a\u5305\u542b " + scope_feature + " \u80fd\u529b\uff0c\u8bf7\u5347\u7ea7\u6216\u8c03\u6574\u5957\u9910\u3002") if not plan_ok else ("\u5f53\u524d\u5957\u9910\u5df2\u5305\u542b " + scope_feature + " \u80fd\u529b\u3002"),
        },
        {
            "key": "node",
            "label": "\u6267\u884c\u8282\u70b9",
            "ok": len(nodes) > 0,
            "severity": "critical" if len(nodes) <= 0 else "info",
            "detail": "\u5728\u7ebf\u8282\u70b9 " + str(len(nodes)) + " \u4e2a",
        },
        {
            "key": "account",
            "label": "\u8d26\u53f7\u6388\u6743",
            "ok": len(usable_accounts) > 0,
            "severity": "critical" if len(usable_accounts) <= 0 else "info",
            "detail": "\u53ef\u7528\u8d26\u53f7 " + str(len(usable_accounts)) + " / " + str(len(accounts)) + " \u4e2a",
        },
        {
            "key": "quota",
            "label": "\u5957\u9910\u989d\u5ea6",
            "ok": quota_ok,
            "severity": "warning" if not quota_ok else "info",
            "detail": ("\u5df2\u7528 " + str(tasks_used) + " / " + str(task_limit) + " \u4e2a\u65e5\u4efb\u52a1") if quota.get("enforce") else "\u9650\u989d\u672a\u5f3a\u5236\uff0c\u5efa\u8bae\u5546\u4e1a\u7248\u5f00\u542f\u3002",
        },
        material_check,
    ]
    blockers = [c for c in checks if c.get("severity") == "critical" and not c.get("ok")]
    warnings = [c for c in checks if c.get("severity") == "warning" and not c.get("ok")]
    ready = len(blockers) == 0
    if ready and not warnings:
        summary = "\u53ef\u521b\u5efa\u5ba2\u6237\u4efb\u52a1"
    elif ready:
        summary = "\u53ef\u8bd5\u8fd0\u884c\uff0c\u4ecd\u6709 " + str(len(warnings)) + " \u9879\u5efa\u8bae\u4f18\u5316"
    else:
        summary = "\u6682\u4e0d\u5efa\u8bae\u521b\u5efa\u4efb\u52a1\uff0c\u9700\u5148\u5904\u7406 " + str(len(blockers)) + " \u9879\u963b\u65ad"
    repair_actions = enterprise_preflight_repair_actions(
        org_id,
        nodes,
        accounts,
        usable_accounts,
        materials,
        quota_ok,
        quota=quota,
        tasks_used=tasks_used,
        task_limit=task_limit,
    )
    return {
        "ok": True,
        "orgId": org_id,
        "scope": scope,
        "ready": ready,
        "summary": summary,
        "blockers": len(blockers),
        "warnings": len(warnings),
        "checks": checks,
        "entitlements": entitlements,
        "repairActions": repair_actions,
        "updatedAt": now(),
    }

def enterprise_summary(user=None):
    with LOCK:
        orgs = list(STATE.get("organizations") or [])
        users = list(STATE.get("users") or [])
        memberships = list(STATE.get("memberships") or [])
        tasks = list((STATE.get("tasks") or {}).values())
        audits = list(STATE.get("auditLogs") or [])
        nodes = list((STATE.get("nodes") or {}).values())
        library = list(STATE.get("library") or [])
        kb_docs = list(STATE.get("kb") or [])
        queue = list(STATE.get("queue") or [])
    app_role = product_role_for_user(user, "*")
    scope = "all" if app_role == PRODUCT_ROLE_PLATFORM_ADMIN else ("org" if app_role == PRODUCT_ROLE_ENTERPRISE_ADMIN else "self")
    if user and app_role != PRODUCT_ROLE_PLATFORM_ADMIN:
        allowed_orgs = {normalize_org_id(m.get("orgId")) for m in memberships if m.get("userId") == user.get("id") and m.get("status", "active") == "active"}
        orgs = [o for o in orgs if normalize_org_id(o.get("id")) in allowed_orgs]
        memberships = [m for m in memberships if normalize_org_id(m.get("orgId")) in allowed_orgs]
        if app_role == PRODUCT_ROLE_ENTERPRISE_ADMIN:
            allowed_users = {m.get("userId") for m in memberships}
        else:
            allowed_users = {user.get("id")}
            memberships = [m for m in memberships if same_user_id(m.get("userId"), user.get("id"))]
        users = [u for u in users if u.get("id") in allowed_users]
        tasks = [t for t in tasks if item_org_id(t) in allowed_orgs]
        audits = [a for a in audits if item_org_id(a) in allowed_orgs or ((a.get("meta") or {}).get("orgId") in allowed_orgs)]
        nodes = [n for n in nodes if item_org_id(n) in allowed_orgs]
        library = [m for m in library if item_org_id(m) in allowed_orgs]
        kb_docs = [d for d in kb_docs if item_org_id(d) in allowed_orgs]
        queue = [q for q in queue if item_org_id(q) in allowed_orgs]
        if app_role == PRODUCT_ROLE_NORMAL_USER:
            tasks = filter_items_for_product_role(tasks, user)
            audits = filter_items_for_product_role(audits, user)
            nodes = []
            library = filter_items_for_product_role(library, user)
            kb_docs = filter_items_for_product_role(kb_docs, user)
            queue = filter_items_for_product_role(queue, user)
        accounts = []
        for oid in sorted(allowed_orgs):
            accounts.extend(accounts_for_response(oid, user=user))
    else:
        accounts = aggregate_accounts()
    task_stats = {}
    for t in tasks:
        st = t.get("status") or "unknown"
        task_stats[st] = task_stats.get(st, 0) + 1
    orgs_public = []
    for o in orgs:
        oid = normalize_org_id(o.get("id"))
        item = dict(o)
        item["nodeCount"] = len([n for n in nodes if item_org_id(n) == oid])
        org_accounts = [a for a in accounts if item_org_id(a) == oid]
        item["accountCount"] = len(org_accounts)
        item["usableAccountCount"] = len([a for a in org_accounts if a.get("usable")])
        item["offlineAccountCount"] = len([a for a in org_accounts if not a.get("online")])
        item["materialCount"] = len([m for m in library if item_org_id(m) == oid])
        item["kbCount"] = len([d for d in kb_docs if item_org_id(d) == oid])
        item["queueCount"] = len([q for q in queue if item_org_id(q) == oid])
        item["publishSettings"] = load_settings(oid)
        orgs_public.append(item)
    return {
        "ok": True,
        "scope": scope,
        "appRole": app_role,
        "productRole": app_role,
        "organizations": orgs_public,
        "users": [public_user(u) for u in users],
        "memberships": memberships,
        "counts": {
            "organizations": len(orgs),
            "users": len(users),
            "memberships": len(memberships),
            "nodesOnline": len(online_nodes()),
            "accounts": len(accounts),
            "usableAccounts": len([a for a in accounts if a.get("usable")]),
            "offlineAccounts": len([a for a in accounts if not a.get("online")]),
            "tasks": len(tasks),
            "auditLogs": len(audits),
            "kbDocs": len(kb_docs),
        },
        "taskStats": task_stats,
    }


def public_error_text(code):
    code = str(code or "")
    messages = {
        "account_offline": "账号所属节点离线",
        "account_cookie_unavailable": "账号 Cookie 不可用",
        "account_not_found": "账号资产不存在",
        "material_file_missing": "素材文件缺失",
        "material_empty": "素材为空",
        "not_logged_in": "节点登录态失效",
        "login_invalid_on_publish": "发布时登录态失效",
        "user_cancelled": "用户已取消",
        "task_not_retryable": "任务不支持直接重试",
        "publish_busy": "发布任务繁忙",
        "publish_disabled": "自动发布未开启",
    }
    return messages.get(code, code or "未知错误")


def action_item(kind, severity, title, description, action_label="", action=None, ref=None, ts=None):
    ref = ref or {}
    stable = _short_hash(json.dumps({"kind": kind, "ref": ref, "title": title}, ensure_ascii=False, sort_keys=True))
    return {
        "id": "act-" + stable,
        "kind": kind,
        "severity": severity,
        "title": title,
        "description": description,
        "actionLabel": action_label,
        "action": action or {},
        "ref": ref,
        "ts": ts or now(),
    }


def action_stable_id(kind, title, ref=None):
    ref = ref or {}
    return "act-" + _short_hash(json.dumps({"kind": kind, "ref": ref, "title": title}, ensure_ascii=False, sort_keys=True))


def snooze_until(value):
    if isinstance(value, dict):
        value = value.get("until") or value.get("snoozedUntil") or 0
    try:
        return float(value or 0)
    except Exception:
        return 0


def snooze_meta(value):
    return value.get("meta") if isinstance(value, dict) and isinstance(value.get("meta"), dict) else {}


def snoozed_action_ids(org_id):
    org_id = normalize_org_id(org_id)
    ts_now = now()
    with LOCK:
        all_snoozes = STATE.setdefault("actionSnoozes", {})
        org_snoozes = dict(all_snoozes.get(org_id) or {})
        active = {k: snooze_until(v) for k, v in org_snoozes.items() if snooze_until(v) > ts_now}
        if len(active) != len(org_snoozes):
            all_snoozes[org_id] = {k: v for k, v in org_snoozes.items() if k in active}
    return active


def snooze_action_item(org_id, item_id, hours=24, meta=None):
    org_id = normalize_org_id(org_id)
    item_id = (item_id or "").strip()
    if not item_id:
        return {"ok": False, "error": "missing_id"}, 400
    try:
        hours = float(hours or 24)
    except Exception:
        hours = 24
    hours = min(168, max(1, hours))
    until = now() + hours * 3600
    with LOCK:
        STATE.setdefault("actionSnoozes", {}).setdefault(org_id, {})[item_id] = {"until": until, "meta": meta or {}, "updatedAt": now()}
        persist()
    return {"ok": True, "id": item_id, "orgId": org_id, "snoozedUntil": until}, 200


def restore_action_item(org_id, item_id):
    org_id = normalize_org_id(org_id)
    item_id = (item_id or "").strip()
    if not item_id:
        return {"ok": False, "error": "missing_id"}, 400
    removed = False
    with LOCK:
        org_snoozes = STATE.setdefault("actionSnoozes", {}).setdefault(org_id, {})
        if item_id in org_snoozes:
            org_snoozes.pop(item_id, None)
            removed = True
        persist()
    return {"ok": True, "id": item_id, "orgId": org_id, "restored": removed}, 200


def action_item_blob(item):
    return " ".join([
        str(item.get("id") or ""),
        str(item.get("kind") or ""),
        str(item.get("severity") or ""),
        str(item.get("title") or ""),
        str(item.get("description") or ""),
        str((item.get("ref") or {}).get("accountId") or ""),
        str((item.get("ref") or {}).get("nodeId") or ""),
        str((item.get("ref") or {}).get("taskId") or ""),
        str((item.get("ref") or {}).get("queueId") or ""),
        str((item.get("ref") or {}).get("materialId") or ""),
        str((item.get("ref") or {}).get("supportId") or ""),
        str((item.get("ref") or {}).get("leadId") or ""),
        str((item.get("ref") or {}).get("keyword") or ""),
        str(((item.get("action") if isinstance(item.get("action"), dict) else {}) or {}).get("supportId") or ""),
        str(((item.get("action") if isinstance(item.get("action"), dict) else {}) or {}).get("leadId") or ""),
        str(((item.get("action") if isinstance(item.get("action"), dict) else {}) or {}).get("keyword") or ""),
    ]).lower()


def action_item_matches(item, kind="", severity="", q=""):
    kind = (kind or "").strip()
    severity = (severity or "").strip()
    q = (q or "").strip().lower()
    if kind and kind != "all" and item.get("kind") != kind:
        return False
    if severity and severity != "all":
        if severity == "snoozed":
            if not item.get("snoozed"):
                return False
        elif item.get("severity") != severity:
            return False
    if q and q not in action_item_blob(item):
        return False
    return True


def clear_action_snoozes_for_resource(org_id, account_id="", node_id=""):
    org_id = normalize_org_id(org_id)
    account_id = (account_id or "").strip()
    node_id = (node_id or "").strip()
    account_candidates = {x for x in [account_id] if x}
    if account_id and ":" not in account_id and node_id:
        account_candidates.add(node_id + ":" + account_id)
    if account_id and ":" in account_id and not node_id:
        node_id = account_id.split(":", 1)[0]
    candidate_ids = set()
    for aid in account_candidates:
        candidate_ids.add(action_stable_id("account_reauth", "账号需要重新授权", {"accountId": aid, "nodeId": node_id}))
        candidate_ids.add(action_stable_id("account_offline", "账号所属节点离线", {"accountId": aid, "nodeId": node_id}))
    if node_id:
        candidate_ids.add(action_stable_id("node_cookie_unavailable", "节点登录态失效", {"nodeId": node_id}))
    removed = []
    with LOCK:
        org_snoozes = STATE.setdefault("actionSnoozes", {}).setdefault(org_id, {})
        for sid, raw in list(org_snoozes.items()):
            meta = snooze_meta(raw)
            ref = meta.get("ref") if isinstance(meta.get("ref"), dict) else {}
            action = meta.get("action") if isinstance(meta.get("action"), dict) else {}
            meta_kind = meta.get("kind") or ""
            ref_account = ref.get("accountId") or action.get("accountId") or ""
            ref_node = ref.get("nodeId") or action.get("nodeId") or ""
            auth_related = meta_kind in ("account_reauth", "account_offline", "node_cookie_unavailable")
            if sid in candidate_ids or (auth_related and ((account_candidates and ref_account in account_candidates) or (node_id and ref_node == node_id))):
                org_snoozes.pop(sid, None)
                removed.append(sid)
        if removed:
            persist()
    return {"ok": True, "orgId": org_id, "cleared": len(removed), "ids": removed[:50], "accountId": account_id, "nodeId": node_id}


def action_item_meta(item):
    return {
        "kind": (item or {}).get("kind") or "",
        "severity": (item or {}).get("severity") or "",
        "title": (item or {}).get("title") or "",
        "ref": (item or {}).get("ref") if isinstance((item or {}).get("ref"), dict) else {},
        "action": (item or {}).get("action") if isinstance((item or {}).get("action"), dict) else {},
    }


def batch_action_items(org_id, operation="", ids=None, q="", kind="", severity="", hours=24, limit=100):
    org_id = normalize_org_id(org_id)
    operation = (operation or "").strip()
    ids = {str(x).strip() for x in (ids or []) if str(x).strip()}
    try:
        limit = min(100, max(1, int(limit or 100)))
    except Exception:
        limit = 100
    # Batch operations intentionally re-select server-side by current org/filter so a browser cannot act on cross-tenant items.
    include_snoozed = True if operation in ("restore_snoozed", "snooze") else False
    snapshot = enterprise_action_items(org_id, limit=limit, include_snoozed=include_snoozed, kind=kind, severity=severity, q=q)
    items = list(snapshot.get("items") or [])
    if ids:
        items = [it for it in items if it.get("id") in ids]
    result = {"ok": True, "orgId": org_id, "operation": operation, "matched": len(items), "processed": 0, "failed": 0, "results": []}

    if operation == "restore_snoozed":
        for it in items:
            if not it.get("snoozed"):
                continue
            payload, status = restore_action_item(org_id, it.get("id"))
            ok = bool(payload.get("ok")) and status < 400
            result["processed"] += 1 if ok and payload.get("restored") else 0
            result["failed"] += 0 if ok else 1
            result["results"].append({"id": it.get("id"), "ok": ok, "restored": payload.get("restored"), "error": payload.get("error")})
        return result, 200

    if operation == "snooze":
        for it in items:
            if it.get("snoozed"):
                continue
            payload, status = snooze_action_item(org_id, it.get("id"), hours=hours, meta=action_item_meta(it))
            ok = bool(payload.get("ok")) and status < 400
            result["processed"] += 1 if ok else 0
            result["failed"] += 0 if ok else 1
            result["results"].append({"id": it.get("id"), "ok": ok, "error": payload.get("error")})
        return result, 200

    if operation == "retry_tasks":
        task_ids = []
        for it in items:
            action = it.get("action") if isinstance(it.get("action"), dict) else {}
            task_id = (action.get("taskId") or (it.get("ref") or {}).get("taskId") or "").strip()
            if action.get("type") == "task" and action.get("retryable") and task_id and task_id not in task_ids:
                task_ids.append(task_id)
        for task_id in task_ids[:20]:
            old, payload, status = retry_task(task_id, org_id)
            ok = bool(payload.get("ok")) and status < 400
            result["processed"] += 1 if ok else 0
            result["failed"] += 0 if ok else 1
            result["results"].append({"taskId": task_id, "ok": ok, "newTaskId": (payload.get("task") or {}).get("id"), "error": payload.get("error")})
        result["taskIds"] = task_ids[:20]
        result["skipped"] = max(0, len(task_ids) - 20)
        return result, 200

    return {"ok": False, "error": "unsupported_batch_operation", "operation": operation}, 400


def enterprise_action_items(org_id=None, limit=50, include_snoozed=False, kind="", severity="", q=""):
    org_id = normalize_org_id(org_id)
    ts_now = now()
    accounts = aggregate_accounts(org_id)
    queue = load_queue(org_id)
    with LOCK:
        nodes = [public_node(n) for n in (STATE.get("nodes") or {}).values() if item_org_id(n) == org_id]
        tasks = [dict(t) for t in (STATE.get("tasks") or {}).values() if item_org_id(t) == org_id]
        support_links = [dict(x) for x in (STATE.get("supportLinks") or []) if item_org_id(x) == org_id and not x.get("archived")]
        finder_leads = [public_finder_lead(x) for x in (STATE.setdefault("finderLeads", {}).get(org_id) or [])]
    items = []

    for a in accounts:
        repair_sla = a.get("repairSla") or account_repair_sla(a, ts_now)
        if not a.get("online"):
            it = action_item(
                "account_offline",
                "critical",
                "\u8d26\u53f7\u6240\u5c5e\u8282\u70b9\u79bb\u7ebf",
                (a.get("name") or "\u6296\u97f3\u8d26\u53f7") + " \u7684\u6267\u884c\u8282\u70b9\u4e0d\u53ef\u8fbe\uff0c\u53d1\u5e03\u3001\u91c7\u96c6\u548c\u8bc4\u8bba\u80fd\u529b\u4f1a\u5931\u8d25\u3002",
                "\u67e5\u770b\u8d26\u53f7",
                {"type": "account", "accountId": a.get("id"), "nodeId": a.get("nodeId")},
                {"accountId": a.get("id"), "nodeId": a.get("nodeId")},
                a.get("offlineSince") or a.get("lastSeen") or a.get("updatedAt"),
            )
            it["sla"] = repair_sla
            it["handoffNote"] = repair_sla.get("handoffNote")
            items.append(it)
        elif not a.get("cookieReady"):
            it = action_item(
                "account_reauth",
                "critical" if repair_sla.get("severity") == "critical" else "warning",
                "\u8d26\u53f7\u9700\u8981\u91cd\u65b0\u6388\u6743",
                (a.get("name") or "\u6296\u97f3\u8d26\u53f7") + " \u7684 Cookie \u4e0d\u53ef\u7528\uff0c\u9700\u8981\u8fd0\u8425\u91cd\u65b0\u626b\u7801/\u77ed\u4fe1\u9a8c\u8bc1\u3002",
                "\u53bb\u6388\u6743\u6062\u590d",
                {"type": "account_auth", "accountId": a.get("id"), "nodeId": a.get("nodeId")},
                {"accountId": a.get("id"), "nodeId": a.get("nodeId")},
                a.get("cookieLostAt") or a.get("cookieUpdatedAt") or a.get("updatedAt"),
            )
            it["sla"] = repair_sla
            it["handoffNote"] = repair_sla.get("handoffNote")
            items.append(it)


    for n in nodes:
        if not n.get("online"):
            items.append(action_item(
                "node_offline",
                "critical",
                "执行节点离线",
                (n.get("name") or n.get("id") or "节点") + " 已离线，当前企业下该节点账号无法执行任务。",
                "查看节点",
                {"type": "node", "nodeId": n.get("id")},
                {"nodeId": n.get("id")},
                n.get("lastSeen"),
            ))
        elif n.get("accountCount") and not n.get("cookieReady"):
            items.append(action_item(
                "node_cookie_unavailable",
                "warning",
                "节点登录态失效",
                (n.get("name") or n.get("id") or "节点") + " 在线但 Cookie 不可用，需要重新授权账号。",
                "去授权恢复",
                {"type": "account_auth", "nodeId": n.get("id")},
                {"nodeId": n.get("id")},
                n.get("lastSeen"),
            ))

    for lead in sorted(finder_leads, key=lambda x: (int(x.get("score") or 0), float(x.get("lastSeenAt") or x.get("updatedAt") or 0)), reverse=True)[:60]:
        st = lead.get("status") or "new"
        if st not in ("new", "follow", "dm"):
            continue
        score = int(lead.get("score") or 0)
        intent = lead.get("intent") or ""
        if st == "new" and score < 60 and intent not in ("高意向", "中意向", "咨询"):
            continue
        sev = "warning" if score >= 70 or st in ("follow", "dm") else "info"
        title = "新寻客线索待跟进" if st == "new" else ("线索待私信" if st == "dm" else "线索待关注")
        cta = "进入寻客" if st == "new" else ("继续私信" if st == "dm" else "继续关注")
        desc = (lead.get("user") or "抖音用户") + "：" + (lead.get("text") or "")[:90]
        if lead.get("keyword"):
            desc += " · " + lead.get("keyword")
        items.append(action_item(
            "finder_lead_followup",
            sev,
            title,
            desc,
            cta,
            {"type": "finder_lead", "leadId": lead.get("id"), "keyword": lead.get("keyword"), "status": st},
            {"leadId": lead.get("id"), "keyword": lead.get("keyword"), "intent": intent, "status": st},
            lead.get("lastSeenAt") or lead.get("updatedAt") or lead.get("firstSeenAt"),
        ))

    for link in sorted(support_links, key=lambda x: x.get("updatedAt") or x.get("createdAt") or 0, reverse=True)[:40]:
        plink = public_support_link(link)
        meta = plink.get("meta") if isinstance(plink.get("meta"), dict) else {}
        task_id = meta.get("taskId") or plink.get("refId") or ""
        owner = plink.get("ownerName") or plink.get("ownerRole") or "support"
        sla = plink.get("sla") or {}
        sev = (plink.get("severity") or sla.get("severity") or "info").lower()
        if sev not in ("critical", "warning", "info"):
            sev = "info"
        case_title = plink.get("title") or plink.get("receipt") or plink.get("id")
        it = action_item(
            "support_case_open",
            sev,
            "支持案例待跟进",
            "客户支持案例 " + (case_title or plink.get("id") or "") + "：请查看时间线、确认下一步处理动作。",
            "打开支持案例",
            {"type": "support_case", "supportId": plink.get("id"), "taskId": task_id, "ownerRole": plink.get("ownerRole")},
            {"supportId": plink.get("id"), "taskId": task_id, "ownerRole": plink.get("ownerRole"), "receipt": plink.get("receipt")},
            plink.get("updatedAt") or plink.get("createdAt"),
        )
        it["sla"] = sla
        it["handoffNote"] = "责任人：" + owner + (" · " + (plink.get("note") or "")[:80] if plink.get("note") else "")
        items.append(it)

    for t in sorted(tasks, key=lambda x: x.get("updatedAt") or x.get("createdAt") or 0, reverse=True):
        status = t.get("status") or ""
        age = ts_now - float(t.get("updatedAt") or t.get("createdAt") or ts_now)
        if status == "failed":
            retryable = is_task_retryable(t)
            items.append(action_item(
                "task_failed_retryable" if retryable else "task_failed",
                "warning" if retryable else "info",
                "云端任务失败" + ("，可重试" if retryable else ""),
                (t.get("path") or "任务") + " 失败：" + public_error_text(t.get("error") or "unknown"),
                "重试任务" if retryable else "查看详情",
                {"type": "task", "taskId": t.get("id"), "retryable": retryable},
                {"taskId": t.get("id"), "path": t.get("path"), "nodeId": t.get("nodeId")},
                t.get("updatedAt") or t.get("createdAt"),
            ))
        elif status == "running" and age > 1800:
            items.append(action_item(
                "task_stuck",
                "warning",
                "任务运行时间过长",
                (t.get("path") or "任务") + " 已运行超过 30 分钟，建议查看节点或任务详情。",
                "查看任务",
                {"type": "task", "taskId": t.get("id")},
                {"taskId": t.get("id"), "path": t.get("path"), "nodeId": t.get("nodeId")},
                t.get("updatedAt") or t.get("createdAt"),
            ))
        elif status == "queued" and age > 3600:
            items.append(action_item(
                "task_queued_long",
                "info",
                "任务排队时间过长",
                (t.get("path") or "任务") + " 已排队超过 1 小时，建议检查节点容量。",
                "查看任务",
                {"type": "task", "taskId": t.get("id")},
                {"taskId": t.get("id"), "path": t.get("path"), "nodeId": t.get("nodeId")},
                t.get("updatedAt") or t.get("createdAt"),
            ))
        if len(items) >= limit * 2:
            break

    for q in sorted(queue, key=lambda x: x.get("updatedAt") or x.get("createdAt") or 0, reverse=True):
        st = q.get("status") or "pending"
        if st in ("fail", "failed", "canceled"):
            items.append(action_item(
                "queue_retry",
                "warning",
                "发布队列需要处理",
                (q.get("materialTitle") or "素材") + " → " + (q.get("accountName") or "账号") + "：" + public_error_text(q.get("lastError") or st),
                "重试队列",
                {"type": "queue", "queueId": q.get("id"), "retryable": True},
                {"queueId": q.get("id"), "accountId": q.get("accountId"), "materialId": q.get("materialId")},
                q.get("updatedAt") or q.get("createdAt"),
            ))
        elif st in ("pending", "queued") and ts_now - float(q.get("createdAt") or ts_now) > 3600:
            items.append(action_item(
                "queue_waiting",
                "info",
                "发布队列等待过久",
                (q.get("materialTitle") or "素材") + " 已等待超过 1 小时，建议检查自动发布开关和节点。",
                "查看队列",
                {"type": "queue", "queueId": q.get("id")},
                {"queueId": q.get("id"), "accountId": q.get("accountId"), "materialId": q.get("materialId")},
                q.get("createdAt"),
            ))

    snoozes = snoozed_action_ids(org_id)
    for it in items:
        sid = it.get("id")
        if sid in snoozes:
            it["snoozed"] = True
            it["snoozedUntil"] = snoozes.get(sid)
    if not include_snoozed:
        items = [it for it in items if not it.get("snoozed")]
    items = [it for it in items if action_item_matches(it, kind=kind, severity=severity, q=q)]
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    items = sorted(items, key=lambda x: (severity_order.get(x.get("severity"), 9), -(float(x.get("ts") or 0))))[:limit]
    counts = {"critical": 0, "warning": 0, "info": 0, "total": len(items)}
    by_kind = {}
    for it in items:
        sev = it.get("severity") or "info"
        counts[sev] = counts.get(sev, 0) + 1
        by_kind[it.get("kind")] = by_kind.get(it.get("kind"), 0) + 1
    counts["snoozed"] = len([it for it in items if it.get("snoozed")])
    return {"ok": True, "orgId": org_id, "items": items, "counts": counts, "byKind": by_kind, "includeSnoozed": bool(include_snoozed), "filters": {"kind": kind or "all", "severity": severity or "all", "q": q or ""}}


DEFAULT_NOTIFICATION_SETTINGS = {
    "enabled": True,
    "roleSeverities": {
        "owner": ["critical", "warning", "info"],
        "admin": ["critical", "warning", "info"],
        "member": ["critical", "warning"],
        "auditor": ["critical", "warning", "info"],
    },
    "mutedKinds": [],
    "criticalWebhookEnabled": False,
    "criticalWebhookUrl": "",
    "webhookSecretSet": False,
    "webhookMinIntervalSec": 300,
    "webhookMaxPerHour": 12,
}


def default_org_onboarding_state(source="tenant_default"):
    ts = now()
    return {
        "welcomeDismissed": False,
        "completed": False,
        "source": source,
        "createdAt": ts,
        "updatedAt": ts,
        "steps": {},
    }


def ensure_org_delivery_defaults(org_id=None, plan_code="standard"):
    org_id = normalize_org_id(org_id)
    plan_code = str(plan_code or "standard").strip().lower()
    if plan_code not in PLAN_CATALOG:
        plan_code = "standard"
    changed = False
    created = []
    with LOCK:
        org_settings = STATE.setdefault("orgSettings", {})
        if org_id not in org_settings:
            org_settings[org_id] = default_publish_settings()
            created.append("publish_settings")
            changed = True
        org_quotas = STATE.setdefault("orgQuotas", {})
        if org_id not in org_quotas:
            org_quotas[org_id] = dict((PLAN_CATALOG.get(plan_code) or PLAN_CATALOG["standard"]).get("limits") or DEFAULT_ORG_QUOTAS)
            created.append("quota")
            changed = True
        notifications = STATE.setdefault("notificationSettings", {})
        if org_id not in notifications:
            notifications[org_id] = json.loads(json.dumps(DEFAULT_NOTIFICATION_SETTINGS))
            created.append("notification_settings")
            changed = True
        onboarding = STATE.setdefault("orgOnboarding", {})
        if org_id not in onboarding:
            onboarding[org_id] = default_org_onboarding_state()
            created.append("onboarding")
            changed = True
    if changed:
        persist()
    return {
        "ok": True,
        "orgId": org_id,
        "created": created,
        "publishSettings": load_settings(org_id),
        "quota": org_quota(org_id),
        "notificationSettings": notification_settings(org_id),
        "onboarding": org_onboarding(org_id) if "org_onboarding" in globals() else None,
    }


def user_role_for_org(user, org_id):
    org_id = normalize_org_id(org_id)
    if not user:
        return "member"
    if user.get("_authType") == "root-token":
        return "owner"
    uid = user.get("id") or ""
    best = "member"
    best_rank = ROLE_RANK.get(best, 0)
    with LOCK:
        for m in STATE.get("memberships") or []:
            if m.get("userId") != uid or m.get("status", "active") != "active":
                continue
            if normalize_org_id(m.get("orgId")) != org_id:
                continue
            role = m.get("role") or "member"
            rank = ROLE_RANK.get(role, 0)
            if rank >= best_rank:
                best = role
                best_rank = rank
    return best


def notification_user_key(user):
    if not user:
        return "anonymous"
    return user.get("id") or user.get("_sessionId") or "anonymous"



def raw_notification_settings(org_id=None):
    org_id = normalize_org_id(org_id)
    with LOCK:
        return dict((STATE.setdefault("notificationSettings", {}) or {}).get(org_id) or {})


def webhook_delivery_status(org_id=None, limit=10):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(50, max(1, int(limit or 10)))
    except Exception:
        limit = 10
    ts = now()
    with LOCK:
        bucket = dict((STATE.setdefault("webhookDeliveries", {}) or {}).get(org_id) or {})
        items = [dict(x) for x in (bucket.get("items") or {}).values() if isinstance(x, dict)]
        recent = [float(x or 0) for x in (bucket.get("recent") or []) if ts - float(x or 0) < 3600]
    items = sorted(items, key=lambda x: float(x.get("updatedAt") or x.get("createdAt") or 0), reverse=True)
    counts = {"pending": 0, "sent": 0, "failed": 0, "rate_limited": 0, "total": len(items)}
    for it in items:
        st = it.get("status") or "pending"
        counts[st] = counts.get(st, 0) + 1
    public_items = []
    for it in items[:limit]:
        public_items.append({
            "id": it.get("id"),
            "notificationId": it.get("notificationId"),
            "title": it.get("title") or "",
            "severity": it.get("severity") or "critical",
            "status": it.get("status") or "pending",
            "statusCode": it.get("statusCode"),
            "error": it.get("error") or "",
            "createdAt": it.get("createdAt"),
            "updatedAt": it.get("updatedAt"),
            "deliveredAt": it.get("deliveredAt"),
        })
    return {"lastSentAt": bucket.get("lastSentAt") or 0, "recentHour": len(recent), "counts": counts, "items": public_items}

def notification_settings(org_id=None):
    org_id = normalize_org_id(org_id)
    base = json.loads(json.dumps(DEFAULT_NOTIFICATION_SETTINGS))
    with LOCK:
        saved = dict((STATE.setdefault("notificationSettings", {}) or {}).get(org_id) or {})
    if isinstance(saved.get("roleSeverities"), dict):
        for role, vals in saved.get("roleSeverities", {}).items():
            if isinstance(vals, list):
                base["roleSeverities"][role] = [str(x) for x in vals if str(x) in ("critical", "warning", "info")]
    for k in ("enabled", "criticalWebhookEnabled"):
        if k in saved:
            base[k] = bool(saved.get(k))
    for k, lo, hi in (("webhookMinIntervalSec", 30, 86400), ("webhookMaxPerHour", 1, 100)):
        if k in saved:
            try:
                base[k] = max(lo, min(hi, int(saved.get(k) or base.get(k) or lo)))
            except Exception:
                pass
    if isinstance(saved.get("mutedKinds"), list):
        base["mutedKinds"] = sorted({str(x).strip() for x in saved.get("mutedKinds") if str(x).strip()})
    if saved.get("criticalWebhookUrl"):
        base["criticalWebhookUrl"] = str(saved.get("criticalWebhookUrl") or "")[:500]
    if saved.get("webhookSecret"):
        base["webhookSecretSet"] = True
    base["webhookDelivery"] = webhook_delivery_status(org_id)
    return base


def update_notification_settings(org_id, body):
    org_id = normalize_org_id(org_id)
    current = notification_settings(org_id)
    next_settings = dict(current)
    if "enabled" in body:
        next_settings["enabled"] = bool(body.get("enabled"))
    if "criticalWebhookEnabled" in body:
        next_settings["criticalWebhookEnabled"] = bool(body.get("criticalWebhookEnabled"))
    if "criticalWebhookUrl" in body:
        next_settings["criticalWebhookUrl"] = str(body.get("criticalWebhookUrl") or "").strip()[:500]
    for k, lo, hi in (("webhookMinIntervalSec", 30, 86400), ("webhookMaxPerHour", 1, 100)):
        if k in body:
            try:
                next_settings[k] = max(lo, min(hi, int(body.get(k) or current.get(k) or lo)))
            except Exception:
                return {"ok": False, "error": "invalid_" + k}, 400
    if body.get("webhookSecret") is not None:
        secret = str(body.get("webhookSecret") or "").strip()
        if secret:
            next_settings["webhookSecret"] = secret[:200]
            next_settings["webhookSecretSet"] = True
        elif body.get("clearWebhookSecret"):
            next_settings.pop("webhookSecret", None)
            next_settings["webhookSecretSet"] = False
    if isinstance(body.get("mutedKinds"), list):
        next_settings["mutedKinds"] = sorted({str(x).strip() for x in body.get("mutedKinds") if str(x).strip()})[:50]
    if isinstance(body.get("roleSeverities"), dict):
        role_map = {}
        for role in ("owner", "admin", "member", "auditor"):
            vals = body.get("roleSeverities", {}).get(role, current.get("roleSeverities", {}).get(role, []))
            if not isinstance(vals, list):
                vals = []
            role_map[role] = [str(x) for x in vals if str(x) in ("critical", "warning", "info")]
        next_settings["roleSeverities"] = role_map
    with LOCK:
        STATE.setdefault("notificationSettings", {})[org_id] = next_settings
        persist()
    public = notification_settings(org_id)
    return {"ok": True, "orgId": org_id, "settings": public}, 200


def notification_allowed(item, settings, role):
    settings = settings or notification_settings()
    if not settings.get("enabled", True):
        return False
    kind = (item or {}).get("kind") or ""
    if kind in set(settings.get("mutedKinds") or []):
        return False
    severity = (item or {}).get("severity") or "info"
    allowed = settings.get("roleSeverities", {}).get(role) or settings.get("roleSeverities", {}).get("member") or []
    return severity in allowed


def notification_read_bucket_locked(org_id, user_key):
    org_id = normalize_org_id(org_id)
    user_key = user_key or "anonymous"
    root = STATE.setdefault("notificationReads", {}).setdefault(org_id, {})
    if not isinstance(root, dict):
        root = {}
        STATE.setdefault("notificationReads", {})[org_id] = root
    legacy = {k: v for k, v in root.items() if k not in ("byUser", "legacy") and not isinstance(v, dict)}
    if legacy:
        root["legacy"] = dict(root.get("legacy") or {}, **legacy)
        for k in legacy:
            root.pop(k, None)
    by_user = root.setdefault("byUser", {})
    reads = dict(root.get("legacy") or {})
    reads.update(dict(by_user.get(user_key) or {}))
    return root, by_user, reads



def sign_webhook_payload(secret, timestamp, body_bytes):
    secret = (secret or "").encode("utf-8")
    if not secret:
        return ""
    base = str(timestamp).encode("utf-8") + b"." + body_bytes
    return "sha256=" + hmac.new(secret, base, hashlib.sha256).hexdigest()


def webhook_url_valid(url):
    try:
        u = urlparse(str(url or ""))
        return u.scheme in ("http", "https") and bool(u.netloc)
    except Exception:
        return False


def update_webhook_delivery(org_id, delivery_id, **fields):
    org_id = normalize_org_id(org_id)
    with LOCK:
        bucket = STATE.setdefault("webhookDeliveries", {}).setdefault(org_id, {})
        items = bucket.setdefault("items", {})
        item = items.setdefault(delivery_id, {"id": delivery_id, "createdAt": now()})
        item.update(fields)
        item["updatedAt"] = now()
        # Bound delivery history to the latest 300 records per org.
        if len(items) > 300:
            ordered = sorted(items.values(), key=lambda x: float(x.get("updatedAt") or x.get("createdAt") or 0), reverse=True)
            keep = {x.get("id") for x in ordered[:300]}
            for k in list(items.keys()):
                if k not in keep:
                    items.pop(k, None)
        persist()


def send_webhook_delivery(org_id, notification, delivery_id):
    org_id = normalize_org_id(org_id)
    raw = raw_notification_settings(org_id)
    url = raw.get("criticalWebhookUrl") or ""
    if not webhook_url_valid(url):
        update_webhook_delivery(org_id, delivery_id, status="failed", error="invalid_webhook_url")
        return
    ts = int(now())
    payload = {
        "event": "matrixship.notification.critical",
        "orgId": org_id,
        "deliveryId": delivery_id,
        "timestamp": ts,
        "notification": {
            "id": notification.get("id"),
            "actionItemId": notification.get("actionItemId"),
            "kind": notification.get("kind") or "",
            "severity": notification.get("severity") or "critical",
            "title": notification.get("title") or "",
            "description": notification.get("description") or "",
            "ts": notification.get("ts") or now(),
            "ref": notification.get("ref") or {},
            "action": notification.get("action") or {},
        },
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "MatrixShip-Webhook/1.0",
        "X-MatrixShip-Event": "matrixship.notification.critical",
        "X-MatrixShip-Timestamp": str(ts),
    }
    sig = sign_webhook_payload(raw.get("webhookSecret") or "", ts, body)
    if sig:
        headers["X-MatrixShip-Signature"] = sig
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            status_code = int(getattr(resp, "status", 0) or resp.getcode() or 0)
            status = "sent" if 200 <= status_code < 300 else "failed"
            snippet = (resp.read(500) or b"").decode("utf-8", "replace")[:300]
            update_webhook_delivery(org_id, delivery_id, status=status, statusCode=status_code, responseSnippet=snippet, deliveredAt=now() if status == "sent" else 0, error="" if status == "sent" else "http_" + str(status_code))
            add_event("webhook_delivery", {"orgId": org_id, "deliveryId": delivery_id, "status": status, "statusCode": status_code})
    except urllib.error.HTTPError as e:
        try:
            snippet = (e.read(500) or b"").decode("utf-8", "replace")[:300]
        except Exception:
            snippet = ""
        update_webhook_delivery(org_id, delivery_id, status="failed", statusCode=int(getattr(e, "code", 0) or 0), responseSnippet=snippet, error="http_" + str(getattr(e, "code", 0) or 0))
    except Exception as e:
        update_webhook_delivery(org_id, delivery_id, status="failed", error=str(e)[:300])


def schedule_webhook_delivery(org_id, notification, force=False):
    org_id = normalize_org_id(org_id)
    settings = notification_settings(org_id)
    raw = raw_notification_settings(org_id)
    if not settings.get("enabled", True):
        return {"ok": False, "reason": "notifications_disabled"}
    if not settings.get("criticalWebhookEnabled") or not settings.get("criticalWebhookUrl"):
        return {"ok": False, "reason": "webhook_disabled"}
    if not webhook_url_valid(settings.get("criticalWebhookUrl")):
        return {"ok": False, "reason": "invalid_webhook_url"}
    nid = str(notification.get("id") or uuid.uuid4().hex)
    delivery_id = "wh-" + _short_hash(org_id + ":" + nid)
    ts = now()
    with LOCK:
        bucket = STATE.setdefault("webhookDeliveries", {}).setdefault(org_id, {})
        items = bucket.setdefault("items", {})
        existing = items.get(delivery_id) or {}
        if existing.get("status") in ("pending", "sent") and not force:
            return {"ok": False, "reason": "already_scheduled", "deliveryId": delivery_id}
        recent = [float(x or 0) for x in (bucket.get("recent") or []) if ts - float(x or 0) < 3600]
        min_interval = max(30, min(86400, int(raw.get("webhookMinIntervalSec") or settings.get("webhookMinIntervalSec") or 300)))
        max_per_hour = max(1, min(100, int(raw.get("webhookMaxPerHour") or settings.get("webhookMaxPerHour") or 12)))
        last_sent = float(bucket.get("lastSentAt") or 0)
        if not force and last_sent and ts - last_sent < min_interval:
            return {"ok": False, "reason": "rate_limited", "retryAfterSec": int(min_interval - (ts - last_sent))}
        if not force and len(recent) >= max_per_hour:
            return {"ok": False, "reason": "hourly_limit", "retryAfterSec": int(max(60, 3600 - (ts - min(recent)))) if recent else 3600}
        recent.append(ts)
        bucket["recent"] = recent[-max_per_hour:]
        bucket["lastSentAt"] = ts
        items[delivery_id] = {
            "id": delivery_id,
            "notificationId": nid,
            "title": notification.get("title") or "",
            "severity": notification.get("severity") or "critical",
            "status": "pending",
            "createdAt": ts,
            "updatedAt": ts,
        }
        persist()
    th = threading.Thread(target=send_webhook_delivery, args=(org_id, notification, delivery_id), daemon=True)
    th.start()
    return {"ok": True, "deliveryId": delivery_id, "status": "pending"}


def maybe_schedule_critical_webhooks(org_id, notifications):
    for n in sorted((notifications or []), key=lambda x: float(x.get("ts") or 0), reverse=True):
        if (n.get("severity") or "") != "critical":
            continue
        if n.get("read"):
            continue
        res = schedule_webhook_delivery(org_id, n, force=False)
        if res.get("ok") or res.get("reason") in ("rate_limited", "hourly_limit"):
            return res
    return {"ok": False, "reason": "no_critical_notification"}


def trigger_test_webhook(org_id):
    org_id = normalize_org_id(org_id)
    n = {
        "id": "ntf-test-" + uuid.uuid4().hex[:12],
        "actionItemId": "webhook-test",
        "kind": "webhook_test",
        "severity": "critical",
        "title": "MatrixShip critical webhook test",
        "description": "This is a signed test event from MatrixShip Enterprise Center.",
        "ts": now(),
        "read": False,
        "action": {},
        "ref": {"source": "manual_test"},
    }
    res = schedule_webhook_delivery(org_id, n, force=True)
    status = 200 if res.get("ok") else 400
    return {"ok": bool(res.get("ok")), "orgId": org_id, "result": res, "delivery": webhook_delivery_status(org_id)}, status

def enterprise_notifications(org_id=None, limit=30, include_read=False, user=None):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(100, max(1, int(limit or 30)))
    except Exception:
        limit = 30
    role = user_role_for_org(user, org_id)
    settings = notification_settings(org_id)
    actions = enterprise_action_items(org_id, limit=100, include_snoozed=False)
    user_key = notification_user_key(user)
    with LOCK:
        _, _, reads = notification_read_bucket_locked(org_id, user_key)
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    all_items = []
    for it in actions.get("items") or []:
        if not notification_allowed(it, settings, role):
            continue
        nid = "ntf-" + str(it.get("id") or _short_hash(json.dumps(it, ensure_ascii=False, sort_keys=True)))
        read_at = float(reads.get(nid) or 0)
        n = {
            "id": nid,
            "actionItemId": it.get("id"),
            "kind": it.get("kind") or "",
            "severity": it.get("severity") or "info",
            "title": it.get("title") or "",
            "description": it.get("description") or "",
            "ts": it.get("ts") or now(),
            "read": bool(read_at),
            "readAt": read_at,
            "action": it.get("action") or {},
            "ref": it.get("ref") or {},
        }
        all_items.append(n)
    unread_all = len([x for x in all_items if not x.get("read")])
    maybe_schedule_critical_webhooks(org_id, all_items)
    settings = notification_settings(org_id)
    items = [x for x in all_items if include_read or not x.get("read")]
    items = sorted(items, key=lambda x: (x.get("read", False), severity_order.get(x.get("severity"), 9), -(float(x.get("ts") or 0))))
    return {"ok": True, "orgId": org_id, "items": items[:limit], "unread": unread_all, "total": len(items), "includeRead": bool(include_read), "role": role, "settings": settings}


def mark_notifications_read(org_id, ids=None, all_items=False, user=None):
    org_id = normalize_org_id(org_id)
    ids = [str(x).strip() for x in (ids or []) if str(x).strip()]
    if all_items:
        current = enterprise_notifications(org_id, limit=100, include_read=True, user=user)
        ids = [x.get("id") for x in current.get("items") or [] if x.get("id")]
    if not ids:
        return {"ok": True, "orgId": org_id, "read": 0, "ids": []}, 200
    ts = now()
    user_key = notification_user_key(user)
    with LOCK:
        _, by_user, _ = notification_read_bucket_locked(org_id, user_key)
        user_reads = by_user.setdefault(user_key, {})
        for nid in ids:
            user_reads[nid] = ts
        persist()
    return {"ok": True, "orgId": org_id, "userKey": user_key, "read": len(ids), "ids": ids[:100]}, 200


def upsert_by_id(items, item):
    item = dict(item or {})
    if not item.get("id"):
        item["id"] = uuid.uuid4().hex
    item.setdefault("createdAt", now())
    item["updatedAt"] = now()
    found = False
    for i, old in enumerate(items):
        if old.get("id") == item["id"]:
            merged = dict(old)
            merged.update(item)
            items[i] = merged
            found = True
            return merged
    if not found:
        items.append(item)
    return item


def set_queue_status(qid, status, **extra):
    event_action = extra.pop("eventAction", None)
    event_meta = extra.pop("eventMeta", None)
    ts = now()
    with LOCK:
        q = list(STATE.get("queue") or [])
        for item in q:
            if item.get("id") == qid:
                prev_status = item.get("status") or ""
                item["status"] = status
                item["updatedAt"] = ts
                item.update(extra)
                meta = dict(event_meta or {})
                if prev_status and prev_status != status:
                    meta.setdefault("fromStatus", prev_status)
                append_queue_event(item, action=event_action or ("status_" + str(status or "")), status=status, meta=meta, ts=ts)
                break
        STATE["queue"] = q
        persist()


def find_queue_item(qid, org_id=None):
    qid = (qid or "").strip()
    org_id = normalize_org_id(org_id) if org_id else None
    if not qid:
        return None
    for item in load_queue(org_id):
        receipt = item.get("receiptId") or queue_receipt_id(item.get("id") or "")
        latest = item.get("latestEventId") or ""
        events = item.get("events") or []
        if item.get("id") == qid or receipt == qid or latest == qid:
            return dict(item)
        if qid.startswith("queue:") and qid == queue_receipt_id(item.get("id") or ""):
            return dict(item)
        if any((evt or {}).get("id") == qid for evt in events):
            return dict(item)
    return None


TASK_OPERATION_LABELS = {
    "auth": "\u8d26\u53f7\u6388\u6743",
    "publish": "\u81ea\u52a8\u53d1\u5e03",
    "finder": "\u5bfb\u5ba2\u91c7\u96c6",
    "outreach": "AI \u62d3\u5ba2",
    "download": "\u89c6\u9891\u4e0b\u8f7d",
    "search": "\u89c6\u9891\u641c\u7d22",
    "comments": "\u8bc4\u8bba\u6293\u53d6",
    "other": "\u4e91\u7aef\u4efb\u52a1",
}


DIRECT_CLOUD_LOGIN_PATHS = {
    "/api/cloud-login/start",
    "/api/cloud-login/current",
    "/api/cloud-login/screenshot",
    "/api/cloud-login/qr",
    "/api/cloud-login/status",
    "/api/cloud-login/click",
    "/api/cloud-login/type",
    "/api/cloud-login/code",
    "/api/cloud-login/key",
    "/api/cloud-login/sms",
    "/api/cloud-login/refresh",
    "/api/cloud-login/close",
}

LARGE_PAYLOAD_KEYS = {
    "image", "screenshot", "qrimage", "qr_image", "base64", "dataurl",
    "data_url", "png", "jpg", "jpeg", "html", "rawhtml", "raw_html",
}

TASK_STATUS_HINTS = {
    "queued": "\u5df2\u8fdb\u5165\u4e91\u7aef\u961f\u5217\uff0c\u7b49\u5f85\u8282\u70b9\u6267\u884c\u3002",
    "running": "\u6267\u884c\u8282\u70b9\u6b63\u5728\u5904\u7406\uff0c\u8bf7\u52ff\u91cd\u590d\u63d0\u4ea4\u3002",
    "done": "\u4efb\u52a1\u5df2\u5b8c\u6210\uff0c\u53ef\u67e5\u770b\u7ed3\u679c\u6216\u56de\u6267\u3002",
    "failed": "\u4efb\u52a1\u5931\u8d25\uff0c\u8bf7\u6309\u5931\u8d25\u539f\u56e0\u5904\u7406\u540e\u518d\u91cd\u8bd5\u3002",
    "canceled": "\u4efb\u52a1\u5df2\u53d6\u6d88\uff0c\u4e0d\u4f1a\u7ee7\u7eed\u6267\u884c\u3002",
}


def task_customer_title(task, operation, body):
    task = task or {}
    body = body if isinstance(body, dict) else {}
    material = first_nonempty(body.get("materialTitle"), body.get("title"), body.get("keyword"), body.get("url"))
    account = first_nonempty(body.get("accountName"), body.get("accountId"), body.get("centralAccountId"))
    if operation == "publish":
        return ("\u53d1\u5e03 " + str(material or "\u7d20\u6750")) + ((" \u2192 " + str(account)) if account else "")
    if operation == "auth":
        return "\u8d26\u53f7\u6388\u6743 " + str(account or body.get("sessionId") or "")
    if operation == "finder":
        return "\u5bfb\u5ba2\u91c7\u96c6 " + str(body.get("keyword") or body.get("product") or "")
    if operation == "download":
        return "\u89c6\u9891\u4e0b\u8f7d " + str(material or body.get("url") or "")
    if operation == "search":
        return "\u89c6\u9891\u641c\u7d22 " + str(body.get("keyword") or "")
    if operation == "comments":
        return "\u8bc4\u8bba\u6293\u53d6 " + str(body.get("url") or body.get("awemeId") or "")
    if operation == "outreach":
        return "AI \u62d3\u5ba2 " + str(body.get("keyword") or body.get("platform") or "")
    return str(TASK_OPERATION_LABELS.get(operation, "\u4e91\u7aef\u4efb\u52a1"))


def task_next_action_label(task, status, operation, failure_category=None):
    if status == "failed":
        action = (failure_category or {}).get("repairCtaLabel") or ""
        return action or ("\u7ef4\u62a4\u8d26\u53f7" if operation == "auth" else "\u67e5\u770b\u5931\u8d25\u539f\u56e0")
    if status == "queued":
        return "\u67e5\u770b\u6392\u961f"
    if status == "running":
        return "\u67e5\u770b\u8fdb\u5ea6"
    if status == "done":
        return "\u67e5\u770b\u7ed3\u679c"
    if status == "canceled":
        return "\u5df2\u53d6\u6d88"
    return "\u67e5\u770b\u8be6\u60c5"


def public_task(task):
    item = dict(task or {})
    raw_body = item.get("body") if isinstance(item.get("body"), dict) else {}
    safe_body = audit_safe_body(raw_body or {})
    item["body"] = safe_body
    status = queue_task_status(item.get("status") or "")
    operation = task_type_key(item.get("path") or "")
    queue_id = first_nonempty(item.get("queueId"), safe_body.get("queueId"))
    receipt_id = first_nonempty(safe_body.get("receiptId"), item.get("receiptId"))
    if queue_id and not receipt_id:
        receipt_id = queue_receipt_id(str(queue_id))
    if not receipt_id and item.get("id"):
        receipt_id = "task:" + str(item.get("id"))
    latest_event_id = first_nonempty(safe_body.get("latestEventId"), item.get("latestEventId"), receipt_id)
    failure_category = {}

    item["retryable"] = is_task_retryable(task)
    item["cancelable"] = is_task_cancelable(task)
    if status == "failed":
        try:
            cat = dict(task_failure_category(task))
            cat.update(task_failure_group_customer_fields(cat))
            retry_ok, retry_reason = is_task_bulk_retryable(task)
            item["failureCategory"] = cat
            item["retryBlockedReason"] = "" if retry_ok else retry_reason
            item["retryBlockedLabel"] = retry_blocked_reason_label(retry_reason)
            failure_category = cat
        except Exception:
            item.setdefault("failureCategory", {})
            failure_category = item.get("failureCategory") or {}

    item["operation"] = operation
    item["operationLabel"] = TASK_OPERATION_LABELS.get(operation, TASK_OPERATION_LABELS["other"])
    item["customerTitle"] = task_customer_title(item, operation, safe_body)
    item["customerHint"] = TASK_STATUS_HINTS.get(status, "")
    item["primaryResource"] = first_nonempty(
        safe_body.get("materialTitle"),
        safe_body.get("keyword"),
        safe_body.get("url"),
        safe_body.get("accountName"),
        safe_body.get("accountId"),
        item.get("path"),
    )
    item["receiptId"] = str(receipt_id or "")
    item["latestEventId"] = str(latest_event_id or "")
    item["queueId"] = str(queue_id or "")
    item["nextActionLabel"] = task_next_action_label(item, status, operation, failure_category)
    item["repairAction"] = str((failure_category or {}).get("repairAction") or "")
    item["supportRef"] = str(first_nonempty(safe_body.get("accountAuthRef"), safe_body.get("supportRef")) or "")
    return item


def is_task_retryable(task):
    if not task:
        return False
    path = (task or {}).get("path") or ""
    if path not in RETRYABLE_TASK_PATHS:
        return False
    return (task or {}).get("status") in ("failed", "queued")


def is_task_cancelable(task):
    if not task:
        return False
    status = (task or {}).get("status") or ""
    if (task or {}).get("queueOnly"):
        return status in ("queued", "failed")
    return status == "queued"


def task_type_key(path):
    path = path or ""
    if "cloud-login" in path:
        return "auth"
    if "/publish/" in path:
        return "publish"
    if "/finder/" in path:
        return "finder"
    if "/outreach/" in path:
        return "outreach"
    if "/douyin/download" in path:
        return "download"
    if "/douyin/search" in path:
        return "search"
    if "/douyin/comments" in path:
        return "comments"
    return "other"


def task_search_blob(task):
    safe_body = audit_safe_body((task or {}).get("body") or {})
    public = public_task(task or {})
    failure = public.get("failureCategory") if isinstance(public.get("failureCategory"), dict) else {}
    parts = [
        (task or {}).get("id") or "",
        public.get("receiptId") or "",
        public.get("latestEventId") or "",
        public.get("queueId") or "",
        public.get("operation") or "",
        public.get("operationLabel") or "",
        public.get("customerTitle") or "",
        public.get("customerHint") or "",
        public.get("primaryResource") or "",
        public.get("nextActionLabel") or "",
        public.get("repairAction") or "",
        public.get("supportRef") or "",
        failure.get("key") or "",
        failure.get("label") or "",
        failure.get("repairAction") or "",
        (task or {}).get("path") or "",
        (task or {}).get("method") or "",
        (task or {}).get("nodeId") or "",
        (task or {}).get("status") or "",
        (task or {}).get("error") or "",
        item_org_id(task or {}) or "",
        json.dumps(safe_body, ensure_ascii=False, sort_keys=True),
    ]
    return " ".join(str(x) for x in parts if x).lower()


def queue_task_status(status):
    status = (status or "").strip()
    return {"pending": "queued", "queued": "queued", "running": "running", "done": "done", "fail": "failed", "failed": "failed", "canceled": "canceled", "cancelled": "canceled"}.get(status, status or "queued")


def queue_item_as_task(item):
    q = public_queue_item(item)
    qid = q.get("id") or ""
    pf = q.get("preflight") if isinstance(q.get("preflight"), dict) else {}
    aa = pf.get("accountAuthorization") if isinstance(pf.get("accountAuthorization"), dict) else {}
    body = {
        "queueId": qid,
        "receiptId": q.get("receiptId") or queue_receipt_id(qid),
        "latestEventId": q.get("latestEventId") or "",
        "accountId": q.get("accountId") or "",
        "accountName": q.get("accountName") or "",
        "materialId": q.get("materialId") or "",
        "materialTitle": q.get("materialTitle") or "",
        "preflightError": pf.get("error") or q.get("lastError") or "",
        "accountAuthRef": aa.get("supportRef") or "",
    }
    return {
        "id": "queue:" + qid,
        "queueId": qid,
        "queueOnly": True,
        "path": "/api/publish/queue",
        "method": "QUEUE",
        "body": body,
        "orgId": item_org_id(q),
        "status": queue_task_status(q.get("status")),
        "nodeId": q.get("nodeId") or ((pf.get("account") or {}).get("nodeId") if isinstance(pf.get("account"), dict) else "") or "",
        "createdAt": q.get("createdAt") or q.get("updatedAt") or now(),
        "updatedAt": q.get("updatedAt") or q.get("createdAt") or now(),
        "waitSec": 0,
        "result": None,
        "error": q.get("lastError") or pf.get("error") or "",
    }


def queue_task_detail(queue_ref, org_id=None, include_all=False):
    item = find_queue_item(queue_ref, None if include_all else org_id)
    if not item:
        return None
    public_item = public_queue_item(item)
    task = queue_item_as_task(item)
    node_id = task.get("nodeId") or ""
    node = None
    if node_id:
        with LOCK:
            raw_node = (STATE.get("nodes") or {}).get(node_id)
        node = public_node(raw_node) if raw_node else None
    return {
        "ok": True,
        "task": public_task(task),
        "queueItems": [public_item],
        "node": node,
        "auditLogs": [],
        "trace": {
            "taskId": task.get("id") or "",
            "nodeId": node_id,
            "queueCount": 1,
            "queueReceiptCount": len(public_item.get("events") or []),
            "auditCount": 0,
            "queueOnly": True,
        },
    }


def queue_search_blob(item):
    q = public_queue_item(item or {})
    parts = [
        q.get("id") or "",
        q.get("receiptId") or "",
        q.get("latestEventId") or "",
        q.get("centralTaskId") or "",
        q.get("accountId") or "",
        q.get("accountName") or "",
        q.get("materialId") or "",
        q.get("materialTitle") or "",
        q.get("status") or "",
        q.get("lastError") or "",
        item_org_id(q) or "",
    ]
    for evt in q.get("events") or []:
        if not isinstance(evt, dict):
            continue
        parts.extend([evt.get("id") or "", evt.get("action") or "", evt.get("status") or "", json.dumps(audit_safe_body(evt.get("meta") or {}), ensure_ascii=False, sort_keys=True)])
    return " ".join(str(x) for x in parts if x).lower()


def queue_task_search_hits(q, org_id=None, include_all=False):
    q = (q or "").strip().lower()
    if not q:
        return set(), []
    items = load_queue(None if include_all else org_id)
    task_ids = set()
    queue_ids = []
    for item in items:
        if q in queue_search_blob(item):
            qid = item.get("id") or ""
            if qid:
                queue_ids.append(qid)
            tid = item.get("centralTaskId") or ""
            if tid:
                task_ids.add(tid)
    return task_ids, queue_ids


def task_matches_filters(task, q="", status_filter="", type_filter=""):
    if status_filter and status_filter != "all" and queue_task_status((task or {}).get("status") or "") != status_filter:
        return False
    if type_filter and type_filter != "all" and task_type_key((task or {}).get("path") or "") != type_filter:
        return False
    q = (q or "").strip().lower()
    if q and not task_query_matches(task, q):
        return False
    return True


def task_query_matches(task, q):
    q = (q or "").strip().lower()
    if not q:
        return True
    if q in task_search_blob(task):
        return True
    refs = {x.lower() for x in task_ref_values(task)}
    if q in refs:
        return True
    if q.startswith("task:") and q[5:] and q[5:] in refs:
        return True
    if q.startswith("queue:") and q[6:] and q[6:] in refs:
        return True
    tid = ((task or {}).get("id") or "").lower()
    if tid and ("task:" + tid) == q:
        return True
    return False


def find_task(task_id, org_id=None, include_all=False):
    task_id = (task_id or "").strip()
    if not task_id:
        return None
    if task_id.startswith("task:"):
        task_id = task_id.split(":", 1)[-1]
    org_id = normalize_org_id(org_id) if org_id else None
    with LOCK:
        task = (STATE.get("tasks") or {}).get(task_id)
    if not task:
        return None
    if not include_all and org_id and item_org_id(task) != org_id:
        return None
    return dict(task)


def queue_items_for_task(task_id, org_id=None):
    task_id = (task_id or "").strip()
    if not task_id:
        return []
    org_id = normalize_org_id(org_id) if org_id else None
    items = []
    for q in load_queue(org_id):
        if q.get("centralTaskId") == task_id:
            items.append(public_queue_item(q))
    return items


def public_task_audit(log):
    meta = (log or {}).get("meta") or {}
    return {
        "id": (log or {}).get("id") or "",
        "ts": (log or {}).get("ts") or 0,
        "action": (log or {}).get("action") or "",
        "target": (log or {}).get("target") or "",
        "ok": bool((log or {}).get("ok")),
        "actorName": (log or {}).get("actorName") or "",
        "meta": audit_safe_body(meta if isinstance(meta, dict) else {}),
    }


def task_related_audits(task, queue_items=None, limit=20):
    task = task or {}
    task_id = task.get("id") or ""
    node_id = task.get("nodeId") or ""
    queue_ids = set((q or {}).get("id") for q in (queue_items or []) if (q or {}).get("id"))
    related = []
    with LOCK:
        logs = sorted((STATE.get("auditLogs") or []), key=lambda x: x.get("ts", 0), reverse=True)
    for log in logs:
        meta = (log or {}).get("meta") or {}
        if not isinstance(meta, dict):
            continue
        if meta.get("taskId") == task_id or meta.get("newTaskId") == task_id:
            related.append(public_task_audit(log))
        elif meta.get("itemId") in queue_ids:
            related.append(public_task_audit(log))
        elif task_id and isinstance(meta.get("body"), dict) and meta.get("body", {}).get("retryOfTaskId") == task_id:
            related.append(public_task_audit(log))
        elif node_id and meta.get("nodeId") == node_id and meta.get("taskId") == task_id:
            related.append(public_task_audit(log))
        if len(related) >= limit:
            break
    return related


def task_detail(task_id, org_id=None, include_all=False):
    task = find_task(task_id, org_id, include_all=include_all)
    if not task:
        return None
    queue_items = queue_items_for_task(task_id, item_org_id(task) if not include_all else org_id)
    node_id = task.get("nodeId") or ""
    node = None
    if node_id:
        with LOCK:
            raw_node = (STATE.get("nodes") or {}).get(node_id)
        node = public_node(raw_node) if raw_node else None
    audits = task_related_audits(task, queue_items)
    return {
        "ok": True,
        "task": public_task(task),
        "queueItems": queue_items,
        "node": node,
        "auditLogs": audits,
        "trace": {
            "taskId": task.get("id") or "",
            "nodeId": node_id,
            "queueCount": len(queue_items),
            "queueReceiptCount": sum(len((q or {}).get("events") or []) for q in queue_items),
            "auditCount": len(audits),
        },
    }


# P2.06 enterprise task-center summary for customer-facing operations.
def task_failure_category(task):
    task = task or {}
    body = task.get("body") if isinstance(task.get("body"), dict) else {}
    err = public_error_text(task.get("error") or body.get("preflightError") or "")
    path = task.get("path") or ""
    err_blob = err.lower()
    path_blob = path.lower()
    blob = (err_blob + " " + path_blob).strip()
    if any(x in err_blob for x in ("stale_timeout", "timeout", "node", "offline", "browser", "playwright", "capacity", "cooldown")):
        return {"key": "node_runtime", "label": "\u8282\u70b9/\u6d4f\u89c8\u5668", "action": "repair_node", "severity": "warning"}
    if any(x in err_blob for x in ("account", "cookie", "auth", "login", "session", "captcha", "sms")) or "cloud-login" in path_blob:
        return {"key": "account_auth", "label": "\u8d26\u53f7\u6388\u6743", "action": "repair_account", "severity": "warning"}
    if any(x in blob for x in ("material", "file", "upload", "video", "cover")):
        return {"key": "material", "label": "\u7d20\u6750\u95ee\u9898", "action": "repair_material", "severity": "warning"}
    if any(x in blob for x in ("quota", "limit", "risk", "rate", "forbid", "blocked")):
        return {"key": "quota_policy", "label": "\u9650\u989d/\u7b56\u7565", "action": "review_policy", "severity": "critical" if "blocked" in blob else "warning"}
    if any(x in blob for x in ("network", "connection", "dns", "proxy", "http")):
        return {"key": "network", "label": "\u7f51\u7edc\u8fde\u63a5", "action": "check_network", "severity": "warning"}
    return {"key": "platform_response", "label": "\u5e73\u53f0\u54cd\u5e94/\u672a\u5206\u7c7b", "action": "review_failed_tasks", "severity": "info"}



def first_nonempty(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
        if value != "":
            return value
    return ""


def task_resource_refs(task):
    task = task or {}
    body = task.get("body") if isinstance(task.get("body"), dict) else {}
    account_id = first_nonempty(
        task.get("accountId"),
        task.get("centralAccountId"),
        body.get("centralAccountId"),
        body.get("accountId"),
        body.get("localAccountId"),
        body.get("account"),
    )
    account_name = first_nonempty(
        body.get("accountName"),
        body.get("nickname"),
        body.get("name"),
        task.get("accountName"),
    )
    node_id = first_nonempty(
        task.get("nodeId"),
        body.get("preferredNode"),
        body.get("nodeId"),
        body.get("centralNodeId"),
    )
    return str(account_id or ""), str(account_name or ""), str(node_id or "")


def task_failure_group_customer_fields(group):
    key = (group or {}).get("key") or ""
    action = (group or {}).get("action") or ""
    if key == "account_auth" or action == "repair_account":
        return {
            "repairAction": "open_auth_repair_wizard",
            "repairCtaLabel": "打开授权修复向导",
            "customerHint": "这些失败需要用户重新授权或恢复登录会话，不能在后台直接批量重试。",
            "retrySafe": False,
        }
    if key == "node_runtime" or action == "repair_node":
        return {
            "repairAction": "recover_or_check_node",
            "repairCtaLabel": "恢复节点任务",
            "customerHint": "先检查节点在线、浏览器进程和容量，然后只重试可重试的任务。",
            "retrySafe": True,
        }
    if key == "material" or action == "repair_material":
        return {
            "repairAction": "review_material",
            "repairCtaLabel": "检查素材",
            "customerHint": "请检查素材文件是否存在、可读和符合上传要求。",
            "retrySafe": True,
        }
    if key == "quota_policy" or action == "review_policy":
        return {
            "repairAction": "review_quota_policy",
            "repairCtaLabel": "检查套餐/策略",
            "customerHint": "请先核对套餐额度、频控策略或客户账号限制，再安全重试。",
            "retrySafe": False,
        }
    return {
        "repairAction": "review_failed_tasks",
        "repairCtaLabel": "查看失败任务",
        "customerHint": "请先查看任务详情和回执记录，确认可重试后再执行批量操作。",
        "retrySafe": True,
    }


def retry_blocked_reason_label(reason):
    reason = (reason or "").strip()
    labels = {
        "requires_account_reauth": "需要客户重新授权",
        "not_retryable": "任务类型不支持直接重试",
        "status_not_retryable": "当前状态不可重试",
    }
    return labels.get(reason, reason or "")


def enterprise_task_center(org_id=None, limit=12):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(50, max(1, int(limit or 12)))
    except Exception:
        limit = 12
    with LOCK:
        raw_tasks = [dict(t) for t in (STATE.get("tasks") or {}).values() if item_org_id(t) == org_id]
        nodes = {nid: public_node(n) for nid, n in (STATE.get("nodes") or {}).items()}
    account_assets = aggregate_accounts(org_id)
    accounts_by_id = {}
    for a in account_assets:
        for ak in (a.get("id"), a.get("localAccountId"), a.get("name")):
            if ak and str(ak) not in accounts_by_id:
                accounts_by_id[str(ak)] = a
    queue_items = load_queue(org_id)
    queue_tasks = [queue_item_as_task(x) for x in queue_items if not (x.get("centralTaskId") or "")]
    rows = sorted(raw_tasks + queue_tasks, key=lambda x: x.get("updatedAt") or x.get("createdAt") or 0, reverse=True)
    status_counts = {"total": len(rows), "queued": 0, "running": 0, "done": 0, "failed": 0, "canceled": 0, "other": 0}
    type_counts = {}
    for task in rows:
        st = queue_task_status(task.get("status") or "")
        if st in status_counts:
            status_counts[st] += 1
        else:
            status_counts["other"] += 1
        tk = task_type_key(task.get("path") or "")
        type_counts[tk] = type_counts.get(tk, 0) + 1
    recovery = task_recovery_candidates(org_id, limit=limit)
    recovery_count = int(((recovery or {}).get("counts") or {}).get("total") or 0)
    failed_rows = [t for t in rows if queue_task_status(t.get("status") or "") == "failed"]
    active_rows = [t for t in rows if queue_task_status(t.get("status") or "") in ("queued", "running")]
    failure_groups = {}
    for ft in failed_rows:
        cat = task_failure_category(ft)
        g = failure_groups.setdefault(cat["key"], {"key": cat["key"], "label": cat["label"], "action": cat["action"], "severity": cat.get("severity") or "warning", "count": 0, "latestAt": 0, "sampleTaskId": "", "sampleError": "", "_accountRefs": {}, "_nodeRefs": {}})
        g["count"] += 1
        account_id, account_name, node_id = task_resource_refs(ft)
        if account_id:
            a = accounts_by_id.get(account_id) or {}
            ref_id = str(a.get("id") or account_id)
            if ref_id not in g["_accountRefs"]:
                g["_accountRefs"][ref_id] = {
                    "id": ref_id,
                    "name": a.get("name") or account_name or ref_id,
                    "nodeId": a.get("nodeId") or node_id or "",
                    "usable": bool(a.get("usable")),
                    "cookieReady": bool(a.get("cookieReady")),
                    "online": bool(a.get("online")),
                }
        if node_id:
            n = nodes.get(node_id) or {}
            if node_id not in g["_nodeRefs"]:
                g["_nodeRefs"][node_id] = {
                    "id": node_id,
                    "name": n.get("name") or node_id,
                    "online": bool(n.get("online", True)),
                    "busy": bool(n.get("busy")),
                }
        updated = float(ft.get("updatedAt") or ft.get("createdAt") or 0)
        if updated >= float(g.get("latestAt") or 0):
            body = ft.get("body") if isinstance(ft.get("body"), dict) else {}
            g["latestAt"] = updated
            g["sampleTaskId"] = ft.get("id") or ""
            g["sampleError"] = public_error_text(ft.get("error") or body.get("preflightError") or "")
            g["sampleAccountId"] = account_id
            g["sampleNodeId"] = node_id
    failure_group_rows = []
    for g in failure_groups.values():
        accounts = list((g.pop("_accountRefs", {}) or {}).values())
        nodes_ref = list((g.pop("_nodeRefs", {}) or {}).values())
        g["affectedAccounts"] = accounts[:8]
        g["affectedNodes"] = nodes_ref[:8]
        g["affectedAccountCount"] = len(accounts)
        g["affectedNodeCount"] = len(nodes_ref)
        if not g.get("sampleAccountId") and accounts:
            g["sampleAccountId"] = accounts[0].get("id") or ""
        if not g.get("sampleNodeId"):
            g["sampleNodeId"] = (nodes_ref[0].get("id") if nodes_ref else "") or ((accounts[0].get("nodeId") if accounts else "") or "")
        g.update(task_failure_group_customer_fields(g))
        failure_group_rows.append(g)
    failure_group_rows = sorted(failure_group_rows, key=lambda x: (x.get("severity") != "critical", -int(x.get("count") or 0), -float(x.get("latestAt") or 0)))
    if recovery_count > 0:
        status = "blocked"
        severity = "critical"
        headline = "\u6709\u5361\u4f4f\u7684\u4e91\u7aef\u4efb\u52a1"
        message = "\u68c0\u6d4b\u5230\u8d85\u65f6\u6267\u884c\u6216\u957f\u65f6\u95f4\u6392\u961f\u7684\u4efb\u52a1\uff0c\u5efa\u8bae\u7ba1\u7406\u5458\u5148\u6267\u884c\u6062\u590d\u3002"
        next_action = "recover_stale_tasks"
    elif status_counts.get("failed", 0) > 0:
        status = "attention"
        severity = "warning"
        headline = "\u5b58\u5728\u5931\u8d25\u4efb\u52a1"
        message = "\u8bf7\u6309\u5931\u8d25\u539f\u56e0\u5206\u522b\u5904\u7406\u8d26\u53f7\u6388\u6743\u3001\u8282\u70b9\u6216\u7d20\u6750\u95ee\u9898\uff0c\u53ef\u5728\u4efb\u52a1\u4e2d\u5fc3\u91cd\u8bd5\u3002"
        next_action = "review_failed_tasks"
    elif status_counts.get("queued", 0) + status_counts.get("running", 0) > 0:
        status = "running"
        severity = "info"
        headline = "\u4e91\u7aef\u4efb\u52a1\u6b63\u5728\u6267\u884c"
        message = "\u5f53\u524d\u6709\u6392\u961f\u6216\u8fd0\u884c\u4e2d\u7684\u4efb\u52a1\uff0c\u8bf7\u5728\u4efb\u52a1\u4e2d\u5fc3\u67e5\u770b\u8fdb\u5ea6\u3002"
        next_action = "open_task_center"
    else:
        status = "healthy"
        severity = "info"
        headline = "\u4efb\u52a1\u961f\u5217\u7a33\u5b9a"
        message = "\u6682\u65e0\u5361\u4f4f\u6216\u6b63\u5728\u6267\u884c\u7684\u4efb\u52a1\uff0c\u53ef\u7ee7\u7eed\u521b\u5efa\u53d1\u5e03\u3001\u5bfb\u5ba2\u6216\u91c7\u96c6\u4efb\u52a1\u3002"
        next_action = "create_task"
    type_labels = {
        "auth": "\u8d26\u53f7\u6388\u6743",
        "publish": "\u81ea\u52a8\u53d1\u5e03",
        "finder": "\u5bfb\u5ba2\u91c7\u96c6",
        "outreach": "AI \u62d3\u5ba2",
        "download": "\u89c6\u9891\u4e0b\u8f7d",
        "search": "\u89c6\u9891\u641c\u7d22",
        "comments": "\u8bc4\u8bba\u6293\u53d6",
        "other": "\u5176\u4ed6\u4efb\u52a1",
    }
    status_labels = {
        "queued": "\u6392\u961f\u4e2d",
        "running": "\u6267\u884c\u4e2d",
        "done": "\u5df2\u5b8c\u6210",
        "failed": "\u5931\u8d25",
        "canceled": "\u5df2\u53d6\u6d88",
    }
    def row_view(task):
        pt = public_task(task)
        body = pt.get("body") if isinstance(pt.get("body"), dict) else {}
        tk = pt.get("operation") or task_type_key(pt.get("path") or "")
        st = queue_task_status(pt.get("status") or "")
        node_id = pt.get("nodeId") or body.get("preferredNode") or body.get("nodeId") or ""
        node = nodes.get(node_id) or {}
        account_id = body.get("centralAccountId") or body.get("accountId") or body.get("accountName") or ""
        err = public_error_text(pt.get("error") or body.get("preflightError") or "")
        action = "view_task"
        if st == "failed" and is_task_retryable(pt):
            action = "retry_task"
        elif st == "queued" and is_task_cancelable(pt):
            action = "cancel_task"
        if err in ("account_not_found", "account_offline", "account_cookie_unavailable", "account_org_invalid"):
            action = "repair_account"
        return {
            "id": pt.get("id") or "",
            "queueId": pt.get("queueId") or body.get("queueId") or "",
            "receiptId": pt.get("receiptId") or body.get("receiptId") or "",
            "latestEventId": pt.get("latestEventId") or body.get("latestEventId") or "",
            "type": tk,
            "typeLabel": pt.get("operationLabel") or type_labels.get(tk, type_labels["other"]),
            "title": pt.get("customerTitle") or pt.get("primaryResource") or pt.get("path") or "",
            "customerHint": pt.get("customerHint") or "",
            "nextActionLabel": pt.get("nextActionLabel") or "",
            "status": st,
            "statusLabel": status_labels.get(st, st or "unknown"),
            "path": pt.get("path") or "",
            "nodeId": node_id,
            "nodeName": node.get("name") or node_id,
            "accountId": account_id,
            "error": err,
            "retryable": bool(is_task_retryable(pt)),
            "cancelable": bool(is_task_cancelable(pt)),
            "nextAction": action,
            "createdAt": pt.get("createdAt") or 0,
            "updatedAt": pt.get("updatedAt") or 0,
        }
    focus = sorted((failed_rows + active_rows), key=lambda x: x.get("updatedAt") or x.get("createdAt") or 0, reverse=True)[:limit]
    if not focus:
        focus = rows[:limit]
    cards = [
        {"key": "running", "label": "\u6267\u884c\u4e2d", "value": status_counts.get("running", 0)},
        {"key": "queued", "label": "\u6392\u961f\u4e2d", "value": status_counts.get("queued", 0)},
        {"key": "failed", "label": "\u5931\u8d25", "value": status_counts.get("failed", 0)},
        {"key": "recovery", "label": "\u9700\u6062\u590d", "value": recovery_count},
    ]
    return {
        "ok": True,
        "orgId": org_id,
        "generatedAt": now(),
        "status": status,
        "severity": severity,
        "headline": headline,
        "message": message,
        "nextAction": next_action,
        "counts": status_counts,
        "typeCounts": type_counts,
        "cards": cards,
        "focus": [row_view(t) for t in focus],
        "failureGroups": failure_group_rows,
        "recovery": recovery,
        "recent": [row_view(t) for t in rows[:limit]],
    }


def task_center_candidate_rows(org_id=None, include_all=False):
    org_id = normalize_org_id(org_id) if org_id else None
    with LOCK:
        raw_tasks = [dict(t) for t in (STATE.get("tasks") or {}).values()]
    if not include_all and org_id:
        raw_tasks = [t for t in raw_tasks if item_org_id(t) == org_id]
    queue_items = load_queue(None if include_all else org_id)
    queue_tasks = [queue_item_as_task(x) for x in queue_items if not (x.get("centralTaskId") or "")]
    return sorted(raw_tasks + queue_tasks, key=lambda x: x.get("updatedAt") or x.get("createdAt") or 0, reverse=True)


def task_ref_values(task):
    task = task or {}
    body = task.get("body") if isinstance(task.get("body"), dict) else {}
    try:
        public = public_task(task)
    except Exception:
        public = {}
    vals = {
        task.get("id") or "",
        ("task:" + str(task.get("id"))) if task.get("id") else "",
        task.get("queueId") or "",
        public.get("queueId") or "",
        public.get("receiptId") or "",
        public.get("latestEventId") or "",
        body.get("queueId") or "",
        body.get("receiptId") or "",
        body.get("latestEventId") or "",
    }
    tid = task.get("id") or ""
    if tid.startswith("queue:"):
        vals.add(tid.split(":", 1)[-1])
    qid = task.get("queueId") or body.get("queueId") or ""
    if qid:
        vals.add("queue:" + qid)
    return {str(x) for x in vals if x}


def select_task_center_candidates(org_id, body=None, include_all=False):
    org_id = normalize_org_id(org_id)
    body = body if isinstance(body, dict) else {}
    status_filter = (body.get("status") or "all").strip() if isinstance(body.get("status") or "all", str) else "all"
    type_filter = (body.get("type") or "all").strip() if isinstance(body.get("type") or "all", str) else "all"
    q = (body.get("q") or "").strip().lower() if isinstance(body.get("q") or "", str) else ""
    failure_group = (body.get("failureGroup") or body.get("group") or "").strip() if isinstance(body.get("failureGroup") or body.get("group") or "", str) else ""
    ids_raw = body.get("ids") or []
    if isinstance(ids_raw, str):
        ids = {x.strip() for x in ids_raw.split(",") if x.strip()}
    elif isinstance(ids_raw, list):
        ids = {str(x).strip() for x in ids_raw if str(x).strip()}
    else:
        ids = set()
    try:
        limit = min(200, max(1, int(body.get("limit") or 50)))
    except Exception:
        limit = 50
    rows = task_center_candidate_rows(org_id, include_all=include_all)
    out = []
    for task in rows:
        st = queue_task_status(task.get("status") or "")
        if ids and not (task_ref_values(task) & ids):
            continue
        if status_filter and status_filter != "all" and st != status_filter:
            continue
        if type_filter and type_filter != "all" and task_type_key(task.get("path") or "") != type_filter:
            continue
        if failure_group and failure_group != "all":
            if st != "failed" or task_failure_category(task).get("key") != failure_group:
                continue
        if q and q not in task_search_blob(task):
            continue
        out.append(task)
        if len(out) >= limit:
            break
    return out, {"status": status_filter, "type": type_filter, "q": q, "failureGroup": failure_group or "all", "ids": sorted(ids), "limit": limit}


def is_task_bulk_retryable(task):
    cat = task_failure_category(task)
    if cat.get("key") == "account_auth":
        return False, "requires_account_reauth"
    if not is_task_retryable(task):
        return False, "not_retryable"
    st = queue_task_status((task or {}).get("status") or "")
    if st not in ("failed", "queued"):
        return False, "status_not_retryable"
    return True, ""


def task_center_bulk_action(org_id, body=None, include_all=False):
    org_id = normalize_org_id(org_id)
    body = body if isinstance(body, dict) else {}
    action = (body.get("action") or "preview").strip().lower() if isinstance(body.get("action") or "preview", str) else "preview"
    if action not in ("preview", "retry", "cancel", "recover"):
        return {"ok": False, "error": "unsupported_bulk_action", "action": action}, 400
    dry_run = bool(body.get("dryRun") or action == "preview")
    if action == "recover":
        try:
            limit = min(200, max(1, int(body.get("limit") or 100)))
        except Exception:
            limit = 100
        payload = recover_stale_tasks(org_id, dry_run=dry_run, limit=limit, force=bool(body.get("force")))
        payload["action"] = action
        payload["bulk"] = True
        payload["message"] = "\u5df2\u626b\u63cf\u5361\u4f4f\u4efb\u52a1" if dry_run else "\u5361\u4f4f\u4efb\u52a1\u6062\u590d\u5df2\u6267\u884c"
        payload["taskCenter"] = enterprise_task_center(org_id, limit=8)
        return payload, 200
    candidates, filters = select_task_center_candidates(org_id, body, include_all=include_all)
    results = []
    eligible = 0
    retryable_count = 0
    cancelable_count = 0
    changed = 0
    failed = 0
    skipped = 0
    for task in candidates:
        task_id = task.get("id") or ""
        cat = task_failure_category(task) if queue_task_status(task.get("status") or "") == "failed" else {"key": "", "label": "", "action": ""}
        can_retry, retry_block_reason = is_task_bulk_retryable(task)
        can_cancel = bool(is_task_cancelable(task))
        if can_retry:
            retryable_count += 1
        if can_cancel:
            cancelable_count += 1
        can_act = (can_retry or can_cancel) if action == "preview" else (can_retry if action == "retry" else can_cancel)
        row = {
            "taskId": task_id,
            "path": task.get("path") or "",
            "status": queue_task_status(task.get("status") or ""),
            "type": task_type_key(task.get("path") or ""),
            "category": cat.get("key") or "",
            "categoryLabel": cat.get("label") or "",
            "eligible": can_act,
            "retryable": can_retry,
            "retryBlockedReason": retry_block_reason,
            "cancelable": can_cancel,
            "dryRun": dry_run,
        }
        if not can_act:
            skipped += 1
            row.update({"ok": False, "skipped": True, "error": "not_eligible_for_" + action})
            results.append(row)
            continue
        eligible += 1
        if dry_run:
            row.update({"ok": True, "preview": True})
            results.append(row)
            continue
        if action == "retry":
            _, payload, status = retry_task(task_id, org_id, include_all=include_all)
        else:
            _, payload, status = cancel_task(task_id, org_id, include_all=include_all)
        ok = bool(payload.get("ok")) and status < 400
        if ok:
            changed += 1
        else:
            failed += 1
        row.update({"ok": ok, "statusCode": status, "error": payload.get("error") or "", "newTaskId": ((payload.get("task") or {}).get("id") if isinstance(payload.get("task"), dict) else "")})
        results.append(row)
    payload = {
        "ok": failed == 0,
        "orgId": org_id,
        "action": action,
        "dryRun": dry_run,
        "filters": filters,
        "matched": len(candidates),
        "eligible": eligible,
        "retryable": retryable_count,
        "cancelable": cancelable_count,
        "changed": changed,
        "failed": failed,
        "skipped": skipped,
        "results": results,
        "taskCenter": enterprise_task_center(org_id, limit=8),
        "message": "\u9884\u89c8\u5b8c\u6210" if dry_run else ("\u6279\u91cf\u64cd\u4f5c\u5b8c\u6210" if failed == 0 else "\u6279\u91cf\u64cd\u4f5c\u90e8\u5206\u5931\u8d25"),
    }
    return payload, 200 if failed == 0 else 207


def support_link_sla(item):
    item = item or {}
    if item.get("archived"):
        return {"label": "closed", "severity": "info", "dueAt": 0, "overdueSec": 0, "remainingSec": 0}
    created = _safe_ts(item.get("createdAt"), now())
    target = float(item.get("slaTargetSec") or 24 * 3600)
    warn = float(item.get("slaWarnSec") or 12 * 3600)
    due_at = created + target
    remaining = max(0, due_at - now())
    overdue = max(0, now() - due_at)
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    raw_severity = (item.get("severity") or "").strip().lower()
    if overdue > 0:
        sev = "critical"
        label = "overdue"
    elif remaining <= warn:
        sev = "warning"
        label = "due_soon"
    elif (meta.get("status") or "").lower() in ("failed", "fail", "error"):
        sev = "warning"
        label = "needs_review"
    else:
        sev = "info"
        label = "tracking"
    if raw_severity in ("critical", "warning", "info"):
        sev = raw_severity
    return {
        "label": label,
        "severity": sev,
        "dueAt": due_at,
        "overdueSec": round(overdue, 1),
        "remainingSec": round(remaining, 1),
        "targetSec": target,
    }


def public_support_link(item):
    item = dict(item or {})
    sla = support_link_sla(item)
    return {
        "id": item.get("id") or "",
        "orgId": item_org_id(item),
        "kind": item.get("kind") or "",
        "refId": item.get("refId") or "",
        "receipt": item.get("receipt") or "",
        "title": item.get("title") or "",
        "url": item.get("url") or ("/?support=" + quote(item.get("id") or "")),
        "createdAt": item.get("createdAt") or 0,
        "createdBy": item.get("createdBy") or "",
        "createdByName": item.get("createdByName") or "",
        "note": item.get("note") or "",
        "ownerRole": item.get("ownerRole") or "support",
        "ownerName": item.get("ownerName") or "",
        "severity": item.get("severity") or sla.get("severity") or "info",
        "sla": sla,
        "archived": bool(item.get("archived")),
        "archivedAt": item.get("archivedAt") or 0,
        "lastOpenedAt": item.get("lastOpenedAt") or 0,
        "openCount": int(item.get("openCount") or 0),
        "meta": audit_safe_body(item.get("meta") if isinstance(item.get("meta"), dict) else {}),
    }


def support_link_match_query(row, q=""):
    q = (q or "").strip().lower()
    if not q:
        return True
    blob = " ".join([
        row.get("id") or "",
        row.get("kind") or "",
        row.get("refId") or "",
        row.get("receipt") or "",
        row.get("title") or "",
        row.get("note") or "",
        row.get("ownerRole") or "",
        row.get("ownerName") or "",
        row.get("severity") or "",
        json.dumps(audit_safe_body(row.get("meta") or {}), ensure_ascii=False, sort_keys=True),
    ]).lower()
    return q in blob


def support_link_stats(rows):
    rows = list(rows or [])
    stats = {
        "total": len(rows),
        "active": 0,
        "archived": 0,
        "critical": 0,
        "warning": 0,
        "info": 0,
        "overdue": 0,
        "dueSoon": 0,
        "opened": 0,
        "unopened": 0,
        "byOwner": [],
        "bySla": [],
    }
    owner_counts = {}
    sla_counts = {}
    for raw in rows:
        r = public_support_link(raw)
        archived = bool(r.get("archived"))
        if archived:
            stats["archived"] += 1
        else:
            stats["active"] += 1
        sev = (r.get("severity") or (r.get("sla") or {}).get("severity") or "info").lower()
        if sev not in ("critical", "warning", "info"):
            sev = "info"
        stats[sev] = stats.get(sev, 0) + 1
        sla = r.get("sla") or {}
        label = sla.get("label") or "tracking"
        if label == "overdue":
            stats["overdue"] += 1
        elif label == "due_soon":
            stats["dueSoon"] += 1
        if int(r.get("openCount") or 0) > 0:
            stats["opened"] += 1
        else:
            stats["unopened"] += 1
        owner = (r.get("ownerName") or r.get("ownerRole") or "unassigned").strip() or "unassigned"
        owner_counts[owner] = owner_counts.get(owner, 0) + 1
        sla_counts[label] = sla_counts.get(label, 0) + 1
    stats["byOwner"] = [{"key": k, "count": v} for k, v in sorted(owner_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
    stats["bySla"] = [{"key": k, "count": v} for k, v in sorted(sla_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
    return stats



def normalize_health_snapshot_rows(rows):
    out = []
    if not isinstance(rows, list):
        return out
    for r in rows[:120]:
        if not isinstance(r, dict):
            continue
        section = str(r.get("section") or "")[:60]
        metric = str(r.get("metric") or "")[:100]
        value = str(r.get("value") if r.get("value") is not None else "")[:160]
        detail = str(r.get("detail") or "")[:300]
        if not section and not metric:
            continue
        out.append({"section": section, "metric": metric, "value": value, "detail": detail})
    return out


def public_health_snapshot(item):
    item = dict(item or {})
    return {
        "id": item.get("id") or "",
        "orgId": item_org_id(item),
        "kind": item.get("kind") or "checkpoint",
        "label": item.get("label") or "",
        "note": item.get("note") or "",
        "createdAt": item.get("createdAt") or item.get("savedAt") or 0,
        "savedAt": item.get("savedAt") or item.get("createdAt") or 0,
        "createdBy": item.get("createdBy") or "",
        "createdByName": item.get("createdByName") or "",
        "rowCount": len(item.get("rows") or []),
        "rows": normalize_health_snapshot_rows(item.get("rows") or []),
    }


def list_health_snapshots(org_id=None, kind="checkpoint", limit=20):
    org_id = normalize_org_id(org_id)
    kind = (kind or "checkpoint").strip().lower()
    if kind not in ("checkpoint", "last_export", "manual", "all"):
        kind = "checkpoint"
    try:
        limit = min(50, max(1, int(limit or 20)))
    except Exception:
        limit = 20
    with LOCK:
        store = STATE.setdefault("healthSnapshots", {})
        rows = [dict(x) for x in (store.get(org_id) or []) if item_org_id(x) == org_id]
    if kind != "all":
        rows = [r for r in rows if (r.get("kind") or "checkpoint") == kind]
    rows.sort(key=lambda x: x.get("createdAt") or x.get("savedAt") or 0, reverse=True)
    items = [public_health_snapshot(x) for x in rows[:limit]]
    return {"ok": True, "orgId": org_id, "kind": kind, "items": items, "latest": items[0] if items else None, "matched": len(rows)}


def save_health_snapshot(org_id=None, body=None, user=None):
    org_id = normalize_org_id(org_id)
    body = body or {}
    kind = (body.get("kind") or "checkpoint").strip().lower()
    if kind not in ("checkpoint", "last_export", "manual"):
        kind = "checkpoint"
    rows = normalize_health_snapshot_rows(body.get("rows") or [])
    if not rows:
        return {"ok": False, "error": "snapshot_rows_required"}, 400
    ts = now()
    item = {
        "id": "hs_" + uuid.uuid4().hex[:18],
        "orgId": org_id,
        "kind": kind,
        "label": str(body.get("label") or "")[:120],
        "note": str(body.get("note") or "")[:300],
        "rows": rows,
        "rowCount": len(rows),
        "createdAt": ts,
        "savedAt": ts,
        "createdBy": (user or {}).get("id") or "",
        "createdByName": (user or {}).get("name") or "",
    }
    with LOCK:
        store = STATE.setdefault("healthSnapshots", {})
        bucket = store.setdefault(org_id, [])
        bucket.append(item)
        bucket.sort(key=lambda x: x.get("createdAt") or 0, reverse=True)
        store[org_id] = bucket[:80]
        persist()
    add_event("enterprise_health_snapshot_saved", {"orgId": org_id, "kind": kind, "id": item["id"], "rows": len(rows)})
    return {"ok": True, "orgId": org_id, "snapshot": public_health_snapshot(item)}, 200


def list_support_links(org_id=None, limit=50, q="", include_archived=False):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(100, max(1, int(limit or 50)))
    except Exception:
        limit = 50
    q = (q or "").strip().lower()
    with LOCK:
        rows = [dict(x) for x in (STATE.get("supportLinks") or []) if item_org_id(x) == org_id]
    if not include_archived:
        rows = [r for r in rows if not r.get("archived")]
    if q:
        rows = [r for r in rows if support_link_match_query(r, q)]
    rows.sort(key=lambda x: x.get("createdAt") or 0, reverse=True)
    counts = {"active": sum(1 for r in rows if not r.get("archived")), "archived": sum(1 for r in rows if r.get("archived"))}
    return {"ok": True, "orgId": org_id, "items": [public_support_link(x) for x in rows[:limit]], "matched": len(rows), "total": len(rows), "counts": counts, "stats": support_link_stats(rows), "filters": {"q": q, "includeArchived": bool(include_archived)}}


def support_link_detail(link_id, org_id=None):
    link_id = (link_id or "").strip()
    org_id = normalize_org_id(org_id) if org_id else None
    if not link_id:
        return None
    with LOCK:
        rows = STATE.get("supportLinks") or []
        found = None
        for x in rows:
            if x.get("id") == link_id:
                found = x
                break
        if found:
            found["lastOpenedAt"] = now()
            found["openCount"] = int(found.get("openCount") or 0) + 1
            persist()
            link = dict(found)
        else:
            link = None
    if not link:
        return None
    if org_id and item_org_id(link) != org_id:
        return None
    payload = {"ok": True, "link": public_support_link(link)}
    kind = link.get("kind") or ""
    ref_id = link.get("refId") or ""
    if kind == "task":
        payload["target"] = task_detail(ref_id, item_org_id(link), include_all=False) or {}
    elif kind == "queue":
        payload["target"] = queue_detail(ref_id, item_org_id(link)) or {}
    payload.update(support_link_auth_context(link, payload.get("target") or {}))
    return payload


def support_link_auth_context(link, target=None):
    link = link or {}
    target = target if isinstance(target, dict) else {}
    org_id = item_org_id(link)
    meta = link.get("meta") if isinstance(link.get("meta"), dict) else {}
    account_id = first_nonempty(meta.get("accountId"), meta.get("centralAccountId"))
    node_id = first_nonempty(meta.get("nodeId"))
    task = target.get("task") if isinstance(target.get("task"), dict) else {}
    if task:
        t_account, _t_account_name, t_node = task_resource_refs(task)
        account_id = first_nonempty(account_id, t_account)
        node_id = first_nonempty(node_id, t_node)
    item = target.get("item") if isinstance(target.get("item"), dict) else {}
    if item:
        health = item.get("health") if isinstance(item.get("health"), dict) else {}
        pf = item.get("preflight") if isinstance(item.get("preflight"), dict) else {}
        pf_account = pf.get("account") if isinstance(pf.get("account"), dict) else {}
        account_id = first_nonempty(account_id, item.get("accountId"), pf_account.get("id"), pf_account.get("localAccountId"))
        node_id = first_nonempty(node_id, item.get("nodeId"), health.get("nodeId"), pf_account.get("nodeId"))
    queue_items = target.get("queueItems") if isinstance(target.get("queueItems"), list) else []
    for q in queue_items:
        if not isinstance(q, dict):
            continue
        health = q.get("health") if isinstance(q.get("health"), dict) else {}
        pf = q.get("preflight") if isinstance(q.get("preflight"), dict) else {}
        pf_account = pf.get("account") if isinstance(pf.get("account"), dict) else {}
        account_id = first_nonempty(account_id, q.get("accountId"), pf_account.get("id"), pf_account.get("localAccountId"))
        node_id = first_nonempty(node_id, q.get("nodeId"), health.get("nodeId"), pf_account.get("nodeId"))
        if account_id:
            break
    if not account_id:
        return {"accountContext": {"available": False, "reason": "account_not_related"}}
    asset = find_account_asset(str(account_id), org_id)
    canonical_account = (asset or {}).get("id") or str(account_id)
    canonical_node = node_id or (asset or {}).get("nodeId") or ""
    context = {
        "available": True,
        "orgId": org_id,
        "accountId": canonical_account,
        "localAccountId": (asset or {}).get("localAccountId") or "",
        "accountName": (asset or {}).get("name") or (asset or {}).get("handle") or canonical_account,
        "nodeId": canonical_node,
        "nodeName": (asset or {}).get("nodeName") or "",
        "usable": bool((asset or {}).get("usable")),
        "cookieReady": bool((asset or {}).get("cookieReady")),
        "source": "support_link",
    }
    try:
        auth = account_authorization_status(org_id, account_id=canonical_account, node_id=canonical_node)
    except Exception as exc:
        auth = {"ok": False, "error": "auth_status_unavailable", "message": public_error_text(str(exc))}
    try:
        timeline = cloud_login_timeline(org_id, account_id=canonical_account, node_id=canonical_node, limit=12)
    except Exception as exc:
        timeline = {"ok": False, "error": "auth_timeline_unavailable", "message": public_error_text(str(exc)), "items": []}
    return {
        "accountContext": context,
        "accountAuthorization": auth,
        "authTimeline": timeline,
    }


def update_support_link(org_id, body=None, user=None):
    org_id = normalize_org_id(org_id)
    body = body or {}
    link_id = (body.get("id") or body.get("supportId") or "").strip()
    if not link_id:
        return {"ok": False, "error": "support_link_id_required"}, 400
    with LOCK:
        rows = STATE.setdefault("supportLinks", [])
        found = None
        for x in rows:
            if x.get("id") == link_id and item_org_id(x) == org_id:
                found = x
                break
        if not found:
            return {"ok": False, "error": "support_link_not_found"}, 404
        if "note" in body:
            found["note"] = str(body.get("note") or "")[:500]
            found["noteUpdatedAt"] = now()
            found["noteUpdatedBy"] = (user or {}).get("id") or ""
        if "ownerName" in body:
            found["ownerName"] = str(body.get("ownerName") or "")[:80]
        if "ownerRole" in body:
            role = str(body.get("ownerRole") or "").strip().lower()
            found["ownerRole"] = role[:40] or found.get("ownerRole") or "support"
        if "severity" in body:
            sev = str(body.get("severity") or "").strip().lower()
            if sev in ("critical", "warning", "info"):
                found["severity"] = sev
        if "archived" in body:
            found["archived"] = bool(body.get("archived"))
            found["archivedAt"] = now() if found["archived"] else 0
            found["archivedBy"] = (user or {}).get("id") or ""
        found["updatedAt"] = now()
        persist()
        return {"ok": True, "orgId": org_id, "link": public_support_link(found)}, 200


def apply_support_link_patch(item, patch=None, user=None):
    patch = patch or {}
    if "note" in patch:
        item["note"] = str(patch.get("note") or "")[:500]
        item["noteUpdatedAt"] = now()
        item["noteUpdatedBy"] = (user or {}).get("id") or ""
    if "ownerName" in patch:
        item["ownerName"] = str(patch.get("ownerName") or "")[:80]
    if "ownerRole" in patch:
        role = str(patch.get("ownerRole") or "").strip().lower()
        item["ownerRole"] = role[:40] or item.get("ownerRole") or "support"
    if "severity" in patch:
        sev = str(patch.get("severity") or "").strip().lower()
        if sev in ("critical", "warning", "info"):
            item["severity"] = sev
    if "archived" in patch:
        item["archived"] = bool(patch.get("archived"))
        item["archivedAt"] = now() if item["archived"] else 0
        item["archivedBy"] = (user or {}).get("id") or ""
    item["updatedAt"] = now()
    return item


def bulk_update_support_links(org_id, body=None, user=None):
    org_id = normalize_org_id(org_id)
    body = body or {}
    operation = (body.get("operation") or "").strip().lower()
    filters = body.get("filters") if isinstance(body.get("filters"), dict) else {}
    ids = body.get("ids") if isinstance(body.get("ids"), list) else []
    ids = {str(x).strip() for x in ids if str(x).strip()}
    q = (filters.get("q") or body.get("q") or "").strip()
    include_archived = bool(filters.get("includeArchived") or body.get("includeArchived"))
    try:
        limit = min(500, max(1, int(body.get("limit") or 200)))
    except Exception:
        limit = 200
    patch = {}
    if operation == "archive":
        patch["archived"] = True
    elif operation == "restore":
        patch["archived"] = False
    elif operation == "assign_owner":
        patch["ownerName"] = str(body.get("ownerName") or "").strip()[:80]
        patch["ownerRole"] = str(body.get("ownerRole") or "support").strip().lower()[:40] or "support"
        if not patch["ownerName"] and not patch["ownerRole"]:
            return {"ok": False, "error": "owner_required"}, 400
    elif operation == "set_severity":
        sev = str(body.get("severity") or "").strip().lower()
        if sev not in ("critical", "warning", "info"):
            return {"ok": False, "error": "invalid_severity"}, 400
        patch["severity"] = sev
    elif operation == "append_note":
        note = str(body.get("note") or "").strip()
        if not note:
            return {"ok": False, "error": "note_required"}, 400
        patch["_appendNote"] = note[:300]
    else:
        return {"ok": False, "error": "unsupported_bulk_operation"}, 400
    processed = []
    skipped = 0
    with LOCK:
        rows = STATE.setdefault("supportLinks", [])
        for item in rows:
            if item_org_id(item) != org_id:
                continue
            if ids and item.get("id") not in ids:
                continue
            if not ids:
                if item.get("archived") and not include_archived:
                    continue
                if q and not support_link_match_query(item, q):
                    continue
            if len(processed) >= limit:
                skipped += 1
                continue
            if "_appendNote" in patch:
                old = str(item.get("note") or "").strip()
                item["note"] = (old + ("\n" if old else "") + patch["_appendNote"])[:500]
                item["noteUpdatedAt"] = now()
                item["noteUpdatedBy"] = (user or {}).get("id") or ""
                item["updatedAt"] = now()
            else:
                apply_support_link_patch(item, patch, user=user)
            processed.append(item.get("id") or "")
        persist()
    return {
        "ok": True,
        "orgId": org_id,
        "operation": operation,
        "matched": len(processed) + skipped,
        "processed": len(processed),
        "skipped": skipped,
        "ids": processed[:100],
    }, 200


def create_support_link(org_id, body=None, user=None):
    org_id = normalize_org_id(org_id)
    body = body or {}
    kind = (body.get("kind") or "").strip().lower()
    ref_id = (body.get("refId") or body.get("taskId") or body.get("queueId") or body.get("id") or "").strip()
    receipt = (body.get("receipt") or "").strip()
    if not kind:
        kind = "queue" if receipt.startswith("queue:") or body.get("queueId") else "task"
    if kind not in ("task", "queue"):
        return {"ok": False, "error": "unsupported_support_link_kind"}, 400
    meta = {}
    title = (body.get("title") or "").strip()[:120]
    if kind == "task":
        detail = task_detail(ref_id, org_id, include_all=False)
        if not detail:
            return {"ok": False, "error": "task_not_found"}, 404
        task = detail.get("task") or {}
        queue_items = detail.get("queueItems") or []
        receipts = [q.get("receiptId") for q in queue_items if q.get("receiptId")]
        events = [q.get("latestEventId") for q in queue_items if q.get("latestEventId")]
        receipt = receipt or (events[0] if events else (receipts[0] if receipts else ("task:" + (task.get("id") or ref_id))))
        title = title or ("Task " + (task.get("id") or ref_id)[:12])
        meta = {
            "taskId": task.get("id") or ref_id,
            "path": task.get("path") or "",
            "status": task.get("status") or "",
            "nodeId": task.get("nodeId") or "",
            "error": public_error_text(task.get("error") or ""),
            "queueReceipts": receipts[:8],
            "eventReceipts": events[:8],
            "auditCount": len(detail.get("auditLogs") or []),
        }
        ref_id = task.get("id") or ref_id
    else:
        item = find_queue_item(ref_id or receipt, org_id)
        if not item:
            return {"ok": False, "error": "queue_item_not_found"}, 404
        public_item = public_queue_item(item)
        ref_id = public_item.get("id") or ref_id
        receipt = receipt or public_item.get("latestEventId") or public_item.get("receiptId") or queue_receipt_id(ref_id)
        title = title or ("Queue " + ref_id[:12])
        meta = {
            "queueId": ref_id,
            "receiptId": public_item.get("receiptId") or "",
            "latestEventId": public_item.get("latestEventId") or "",
            "centralTaskId": public_item.get("centralTaskId") or "",
            "status": public_item.get("status") or "",
            "accountId": public_item.get("accountId") or "",
            "materialId": public_item.get("materialId") or "",
            "error": public_error_text(public_item.get("lastError") or ""),
            "eventCount": len(public_item.get("events") or []),
        }
    extra_meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    if extra_meta:
        meta.update(audit_safe_body(extra_meta))
    item = {
        "id": "sup_" + uuid.uuid4().hex[:12],
        "orgId": org_id,
        "kind": kind,
        "refId": ref_id,
        "receipt": receipt,
        "title": title,
        "url": "/?support=" + quote("sup_" + uuid.uuid4().hex[:12]),
        "createdAt": now(),
        "updatedAt": now(),
        "createdBy": (user or {}).get("id") or "",
        "createdByName": (user or {}).get("name") or (user or {}).get("phone") or "",
        "note": (body.get("note") or "").strip()[:500] if isinstance(body.get("note") or "", str) else "",
        "ownerRole": (body.get("ownerRole") or "support").strip()[:40] if isinstance(body.get("ownerRole") or "support", str) else "support",
        "ownerName": (body.get("ownerName") or "").strip()[:80] if isinstance(body.get("ownerName") or "", str) else "",
        "severity": (body.get("severity") or "").strip().lower() if isinstance(body.get("severity") or "", str) else "",
        "meta": meta,
    }
    if item.get("severity") not in ("critical", "warning", "info"):
        item["severity"] = ""
    item["url"] = "/?support=" + quote(item["id"])
    with LOCK:
        rows = STATE.setdefault("supportLinks", [])
        rows.insert(0, item)
        STATE["supportLinks"] = rows[:1000]
        persist()
    return {"ok": True, "orgId": org_id, "link": public_support_link(item)}, 200


def ensure_task_support_link(org_id, task_id, reason="", meta=None, user=None, severity=""):
    org_id = normalize_org_id(org_id)
    task_id = (task_id or "").strip()
    if not task_id:
        return None
    detail = task_detail(task_id, org_id, include_all=False)
    if not detail:
        return None
    task = detail.get("task") or {}
    ts = now()
    safe_meta = audit_safe_body(meta if isinstance(meta, dict) else {})
    safe_meta.update({
        "taskId": task.get("id") or task_id,
        "path": task.get("path") or "",
        "status": task.get("status") or "",
        "lastSupportReason": (reason or "")[:80],
        "lastSupportUpdatedAt": ts,
    })
    sev = (severity or "").strip().lower()
    if sev not in ("critical", "warning", "info"):
        sev = "warning" if task.get("status") == "failed" else "info"
    note = "\u7cfb\u7edf\u81ea\u52a8\u6c89\u6dc0\uff1a\u4efb\u52a1\u8fd0\u884c\u63a2\u6d4b\u6216\u4fee\u590d\u4e8b\u4ef6\uff0c\u7528\u4e8e\u5ba2\u670d\u548c\u8fd0\u7ef4\u590d\u76d8\u3002"
    with LOCK:
        rows = STATE.setdefault("supportLinks", [])
        found = None
        for item in rows:
            if item_org_id(item) == org_id and (item.get("kind") or "") == "task" and (item.get("refId") or "") == task_id and not item.get("archived"):
                found = item
                break
        if found:
            old_meta = found.get("meta") if isinstance(found.get("meta"), dict) else {}
            old_meta.update(safe_meta)
            found["meta"] = old_meta
            found["updatedAt"] = ts
            found["lastTouchedAt"] = ts
            if sev:
                found["severity"] = sev
            if not found.get("note"):
                found["note"] = note
            persist()
            return {"created": False, "link": public_support_link(found)}
    body = {
        "kind": "task",
        "refId": task_id,
        "title": "Task " + task_id[:12] + " runtime case",
        "ownerRole": "support",
        "severity": sev,
        "note": note,
        "meta": safe_meta,
    }
    payload, status = create_support_link(org_id, body, user=user)
    if status != 200 or not payload.get("ok"):
        return None
    return {"created": True, "link": payload.get("link")}


def cancel_task(task_id, org_id=None, include_all=False):
    task = find_task(task_id, org_id, include_all=include_all)
    if not task:
        qitem = find_queue_item(task_id, None if include_all else org_id)
        if qitem:
            item, payload, status = cancel_queue_item(qitem.get("id"), item_org_id(qitem), reason="task_center_cancelled")
            synthetic = queue_item_as_task(item or qitem)
            payload = dict(payload or {})
            payload["task"] = public_task(synthetic)
            payload["queueOnly"] = True
            return synthetic, payload, status
        return None, {"ok": False, "error": "task_not_found"}, 404
    if task.get("status") == "running":
        return task, {"ok": False, "error": "task_running", "message": "任务正在执行，不能直接取消"}, 409
    if task.get("status") in ("done", "failed"):
        return task, {"ok": True, "task": public_task(task), "noop": True}, 200
    with LOCK:
        cur = (STATE.get("tasks") or {}).get(task.get("id"))
        if cur:
            cur["status"] = "failed"
            cur["error"] = "user_cancelled"
            cur["updatedAt"] = now()
            persist()
            task = dict(cur)
    return task, {"ok": True, "task": public_task(task)}, 200


def retry_task(task_id, org_id=None, include_all=False):
    old = find_task(task_id, org_id, include_all=include_all)
    if not old:
        qitem = find_queue_item(task_id, None if include_all else org_id)
        if qitem:
            old_task = queue_item_as_task(qitem)
            item, payload, status = retry_queue_item(qitem.get("id"), item_org_id(qitem))
            synthetic = queue_item_as_task(item or qitem)
            payload = dict(payload or {})
            payload["task"] = public_task(synthetic)
            payload["retryOfTaskId"] = old_task.get("id")
            payload["queueOnly"] = True
            return synthetic, payload, status
        return None, {"ok": False, "error": "task_not_found"}, 404
    if not is_task_retryable(old):
        return old, {"ok": False, "error": "task_not_retryable"}, 409
    body = dict(old.get("body") or {})
    body.setdefault("orgId", item_org_id(old))
    body["retryOfTaskId"] = old.get("id")
    try:
        wait_sec = float(old.get("waitSec") or TASK_WAIT_DEFAULT)
    except Exception:
        wait_sec = TASK_WAIT_DEFAULT
    task, err, status = create_task(old.get("path") or "", old.get("method") or "POST", body, wait_sec=wait_sec, preferred_node=old.get("nodeId") or None)
    if err:
        return old, err, status
    return task, {"ok": True, "task": public_task(task), "retryOfTaskId": old.get("id")}, 200


def task_for_queue_item(item):
    task_id = (item or {}).get("centralTaskId") or ""
    if not task_id:
        return None
    with LOCK:
        task = (STATE.get("tasks") or {}).get(task_id)
    return public_task(task) if task else None



def publish_queue_auth_handoff(org_id=None, limit=50):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(100, max(1, int(limit or 50)))
    except Exception:
        limit = 50
    auth = account_authorization_handoff(org_id, limit=50)
    auth_items = auth.get("items") if isinstance(auth.get("items"), list) else []
    def _refs(v):
        return account_ref_candidates(v)
    def _match_auth(account_id, node_id=""):
        acc_refs = _refs(account_id)
        node_id = str(node_id or "")
        fallback = None
        for it in auth_items:
            if not isinstance(it, dict):
                continue
            if not fallback and it.get("state") != "ready":
                fallback = it
            it_refs = _refs(it.get("accountId") or it.get("localAccountId") or "")
            node_match = (not node_id) or (not it.get("nodeId")) or it.get("nodeId") == node_id
            if acc_refs and it_refs and (acc_refs & it_refs) and node_match:
                return it
        return fallback
    rows = []
    ready = blocked = warning = 0
    queue_rows = [public_queue_item(q) for q in load_queue(org_id)]
    for q in queue_rows:
        h = q.get("health") if isinstance(q.get("health"), dict) else {}
        status = queue_task_status(q.get("status") or "")
        if status in ("done", "running", "canceled"):
            continue
        next_action = h.get("nextAction") or ""
        blocked_by = str(h.get("blockedBy") or q.get("lastError") or "")
        is_auth_block = next_action in ("authorize_account", "resume_auth", "repair_node", "continue_auth", "complete_save", "wait_or_retry", "cleanup_and_restart") or blocked_by.startswith("account_") or "cookie" in blocked_by or "auth" in blocked_by
        if not is_auth_block:
            if h.get("severity") in ("critical", "warning"):
                warning += 1
            continue
        blocked += 1
        account_id = q.get("accountId") or (h.get("accountId") if isinstance(h, dict) else "") or "douyin-self"
        node_id = h.get("nodeId") or q.get("nodeId") or ""
        auth_item = _match_auth(account_id, node_id) or {}
        action = auth_item.get("nextAction") or next_action or "authorize_account"
        action_label = auth_item.get("actionLabel") or h.get("actionLabel") or "\u4fee\u590d\u8d26\u53f7"
        if action == "cleanup_and_restart":
            action_label = "\u5173\u95ed\u91cd\u5f00"
        rows.append({
            "queueId": q.get("id") or "",
            "receiptId": q.get("receiptId") or queue_receipt_id(q.get("id") or ""),
            "materialId": q.get("materialId") or "",
            "materialTitle": q.get("materialTitle") or "",
            "accountId": account_id,
            "accountName": q.get("accountName") or account_id,
            "nodeId": node_id or auth_item.get("nodeId") or "",
            "nodeName": auth_item.get("nodeName") or node_id or "",
            "status": status,
            "severity": auth_item.get("severity") or h.get("severity") or "warning",
            "blockedBy": blocked_by,
            "summary": auth_item.get("customerHint") or h.get("message") or public_error_text(blocked_by) or "\u8d26\u53f7\u6388\u6743\u963b\u585e\u53d1\u5e03\u961f\u5217",
            "nextAction": action,
            "actionLabel": action_label,
            "authItem": auth_item,
            "supportRef": h.get("supportRef") or auth_item.get("supportRef") or "",
            "updatedAt": q.get("updatedAt") or q.get("createdAt") or now(),
        })
    ready = len([q for q in queue_rows if queue_task_status(q.get("status") or "") in ("queued", "failed")]) - blocked
    rows = sorted(rows, key=lambda x: ({"critical": 0, "warning": 1, "info": 2}.get(x.get("severity") or "warning", 1), -(float(x.get("updatedAt") or 0))))[:limit]
    if blocked:
        status = "blocked"
        headline = "\u53d1\u5e03\u961f\u5217\u88ab\u8d26\u53f7\u6388\u6743\u963b\u585e"
        message = "\u8bf7\u5148\u6309\u961f\u5217\u5173\u8054\u7684\u8d26\u53f7\u5b8c\u6210\u6388\u6743/\u5173\u95ed\u91cd\u5f00\uff0c\u518d\u6267\u884c\u6279\u91cf\u4f53\u68c0\u6216\u91cd\u8bd5\u961f\u5217\u3002"
    elif (auth.get("status") or "") != "ready":
        status = "needs_attention"
        headline = "\u961f\u5217\u5c1a\u65e0\u660e\u786e\u6388\u6743\u963b\u585e\uff0c\u4f46\u8d26\u53f7\u6388\u6743\u672a\u5c31\u7eea"
        message = auth.get("message") or "\u5efa\u8bae\u5148\u5b8c\u6210\u5ba2\u6237\u6388\u6743\u4ea4\u63a5\u3002"
    else:
        status = "ready"
        headline = "\u961f\u5217\u6388\u6743\u72b6\u6001\u5df2\u5c31\u7eea"
        message = "\u53ef\u7ee7\u7eed\u6267\u884c\u961f\u5217\u4f53\u68c0\u6216\u4f4e\u9891\u8bd5\u8fd0\u884c\u3002"
    next_item = rows[0] if rows else (auth.get("nextItem") if isinstance(auth.get("nextItem"), dict) else None)
    return {
        "ok": True,
        "orgId": org_id,
        "status": status,
        "headline": headline,
        "message": message,
        "counts": {"queueTotal": len(queue_rows), "authBlocked": blocked, "warning": warning, "ready": max(0, ready), "items": len(rows)},
        "items": rows,
        "nextItem": next_item,
        "authHandoff": auth,
        "generatedAt": now(),
    }




def publish_queue_watchdog(org_id=None, limit=100):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(200, max(1, int(limit or 100)))
    except Exception:
        limit = 100
    ts_now = now()
    queue_rows = load_queue(org_id)
    with LOCK:
        tasks = [dict(t) for t in (STATE.get("tasks") or {}).values() if item_org_id(t) == org_id]
        nodes = [dict(n) for n in (STATE.get("nodes") or {}).values() if item_org_id(n) == org_id]
    pending = [q for q in queue_rows if queue_task_status(q.get("status") or "") in ("pending", "queued")]
    running = [q for q in queue_rows if queue_task_status(q.get("status") or "") == "running"]
    failed = [q for q in queue_rows if queue_task_status(q.get("status") or "") in ("fail", "failed")]
    done = [q for q in queue_rows if queue_task_status(q.get("status") or "") == "done"]
    stalled = []
    for q in running:
        updated = float(q.get("updatedAt") or q.get("startedAt") or q.get("createdAt") or ts_now)
        if ts_now - updated > 1800:
            stalled.append(q)
    online_nodes = [n for n in nodes if n.get("online") is not False]
    publish_tasks = [t for t in tasks if str(t.get("path") or "").startswith("/api/publish/")]
    running_tasks = [t for t in publish_tasks if t.get("status") in ("queued", "running")]
    failed_tasks_24h = [t for t in publish_tasks if t.get("status") == "failed" and float(t.get("updatedAt") or t.get("createdAt") or 0) >= ts_now - 86400]
    queue_total = len(queue_rows)
    if stalled:
        status = "blocked"
        headline = "\u53d1\u5e03\u961f\u5217\u6709\u5361\u4f4f\u7684\u8fd0\u884c\u9879"
        message = "\u6709 " + str(len(stalled)) + " \u4e2a\u961f\u5217\u9879\u8fd0\u884c\u8d85\u8fc7 30 \u5206\u949f\uff0c\u5efa\u8bae\u5148\u4f53\u68c0\u5e76\u4fee\u590d\u3002"
    elif failed:
        status = "needs_attention"
        headline = "\u53d1\u5e03\u961f\u5217\u6709\u5931\u8d25\u9879\u53ef\u590d\u76d8"
        message = "\u6709 " + str(len(failed)) + " \u4e2a\u5931\u8d25\u961f\u5217\u9879\uff0c\u53ef\u5148\u6279\u91cf\u4f53\u68c0\uff0c\u518d\u5c06\u53ef\u6062\u590d\u9879\u91cd\u65b0\u6392\u961f\u3002"
    elif pending and not online_nodes:
        status = "blocked"
        headline = "\u961f\u5217\u5f85\u53d1\uff0c\u4f46\u6ca1\u6709\u5728\u7ebf\u8282\u70b9"
        message = "\u5f53\u524d\u6709 " + str(len(pending)) + " \u4e2a\u5f85\u53d1\u9879\uff0c\u4f46\u8282\u70b9\u6c60\u4e0d\u53ef\u7528\u3002"
    elif pending or running:
        status = "active"
        headline = "\u53d1\u5e03\u961f\u5217\u6b63\u5e38\u8c03\u5ea6\u4e2d"
        message = "\u5f85\u53d1 " + str(len(pending)) + "\uff0c\u8fd0\u884c " + str(len(running)) + "\uff0c\u8bf7\u4fdd\u6301\u4f4e\u9891\u8c03\u5ea6\u548c\u56de\u6267\u68c0\u67e5\u3002"
    else:
        status = "ready"
        headline = "\u53d1\u5e03\u961f\u5217\u65e0\u5361\u6b7b\u9879"
        message = "\u5f53\u524d\u6ca1\u6709\u5f85\u5904\u7406\u7684\u53d1\u5e03\u961f\u5217\u963b\u585e\u3002"
    actions = []
    def _act(key, label, action, severity="info", detail=""):
        actions.append({"key": key, "label": label, "action": action, "severity": severity, "detail": detail, "module": "autopub", "resource": {}})
    if stalled or failed or pending:
        _act("batch_preflight", "\u6279\u91cf\u4f53\u68c0", "batch_preflight", "warning", "\u4ec5\u68c0\u67e5\u961f\u5217\u53ef\u6267\u884c\u6027\uff0c\u4e0d\u4f1a\u7acb\u5373\u53d1\u5e03\u3002")
        _act("batch_repair", "\u4f53\u68c0\u5e76\u4fee\u590d", "batch_repair", "warning", "\u5c06\u53ef\u6062\u590d\u7684\u5931\u8d25\u9879\u91cd\u65b0\u6392\u961f\uff0c\u4e0d\u4f1a\u8df3\u8fc7\u6388\u6743\u6216\u7d20\u6750\u68c0\u67e5\u3002")
    _act("export_preflight", "\u5bfc\u51fa\u4f53\u68c0", "export_preflight", "info", "\u751f\u6210\u961f\u5217\u4f53\u68c0\u56de\u6267\uff0c\u4fbf\u4e8e\u5ba2\u670d\u590d\u76d8\u3002")
    samples = []
    for q in (stalled + failed + pending)[:limit]:
        samples.append({
            "id": q.get("id") or "",
            "receiptId": q.get("receiptId") or "",
            "status": q.get("status") or "",
            "accountId": q.get("accountId") or "",
            "materialId": q.get("materialId") or "",
            "materialTitle": q.get("materialTitle") or q.get("title") or "",
            "lastError": public_error_text(q.get("lastError") or ""),
            "updatedAt": q.get("updatedAt") or q.get("createdAt") or 0,
        })
    return {
        "ok": True,
        "orgId": org_id,
        "status": status,
        "headline": headline,
        "message": message,
        "cards": [
            {"key": "pending", "label": "\u5f85\u53d1", "value": str(len(pending))},
            {"key": "running", "label": "\u8fd0\u884c", "value": str(len(running))},
            {"key": "stalled", "label": "\u5361\u4f4f", "value": str(len(stalled))},
            {"key": "failed", "label": "\u5931\u8d25", "value": str(len(failed))},
        ],
        "counts": {"total": queue_total, "pending": len(pending), "running": len(running), "stalled": len(stalled), "failed": len(failed), "done": len(done), "onlineNodes": len(online_nodes), "runningTasks": len(running_tasks), "failedTasks24h": len(failed_tasks_24h)},
        "actions": actions[:4],
        "nextAction": actions[0] if actions else None,
        "items": samples,
        "generatedAt": ts_now,
    }

def publish_queue_recovery_advice(org_id=None, limit=50):
    org_id = normalize_org_id(org_id)
    try:
        limit = min(100, max(1, int(limit or 50)))
    except Exception:
        limit = 50
    queue_auth = publish_queue_auth_handoff(org_id, limit=limit)
    queue_rows = [public_queue_item(q) for q in load_queue(org_id)]
    actionable = [q for q in queue_rows if queue_task_status(q.get("status") or "") in ("pending", "queued", "fail", "failed")]
    with LOCK:
        library_count = len([dict(m) for m in (STATE.get("library") or []) if item_org_id(m) == org_id])
    try:
        accounts = aggregate_accounts(org_id)
    except Exception:
        accounts = []
    usable_accounts = len([a for a in accounts if isinstance(a, dict) and a.get("usable")])
    preview = {"ok": True, "checked": 0, "ready": 0, "blocked": 0, "warnings": 0, "items": [], "counts": {}}
    if actionable:
        try:
            preview, _status = publish_queue_batch_preflight(org_id, {"operation": "preview", "limit": limit, "statuses": ["pending", "queued", "fail", "failed"]}, user=None)
        except Exception as exc:
            preview = {"ok": False, "error": "queue_preflight_unavailable", "summary": public_error_text(str(exc)), "checked": len(actionable), "ready": 0, "blocked": len(actionable), "items": [], "counts": {}}
    actions = []
    def _action(key, label, detail, action, module="autopub", severity="info", resource=None):
        actions.append({"key": key, "label": label, "detail": detail, "action": action, "module": module, "severity": severity, "resource": resource or {}})

    qa_status = queue_auth.get("status") or "ready"
    if qa_status != "ready":
        status = "blocked" if qa_status == "blocked" else "needs_attention"
        headline = "\u5148\u5904\u7406\u8d26\u53f7\u6388\u6743\uff0c\u518d\u6062\u590d\u961f\u5217"
        message = queue_auth.get("message") or "\u961f\u5217\u6267\u884c\u4f9d\u8d56\u5ba2\u6237\u8d26\u53f7\u6388\u6743\uff0c\u5b8c\u6210\u540e\u7cfb\u7edf\u4f1a\u81ea\u52a8\u7ed9\u51fa\u4f53\u68c0/\u6062\u590d\u5efa\u8bae\u3002"
        nxt = queue_auth.get("nextItem") if isinstance(queue_auth.get("nextItem"), dict) else {}
        _action("auth_handoff", (nxt.get("actionLabel") or "\u5904\u7406\u6388\u6743"), queue_auth.get("headline") or "", nxt.get("nextAction") or "authorize_account", "accounts", "warning", nxt)
    elif not queue_rows:
        if library_count <= 0:
            status = "needs_attention"
            headline = "\u6388\u6743\u5df2\u5c31\u7eea\uff0c\u4f46\u8fd8\u6ca1\u6709\u53ef\u6392\u961f\u7d20\u6750"
            message = "\u8bf7\u5148\u4e0a\u4f20\u4e00\u4e2a\u5ba2\u6237\u4ea7\u54c1\u76f8\u5173\u7d20\u6750\uff0c\u518d\u52a0\u5165\u4f4e\u9891\u53d1\u5e03\u961f\u5217\u3002"
            _action("upload_assets", "\u4e0a\u4f20\u7d20\u6750", message, "upload_assets", "autopub", "warning")
        elif usable_accounts <= 0:
            status = "needs_attention"
            headline = "\u7d20\u6750\u5df2\u6709\uff0c\u4f46\u8d26\u53f7\u8fd8\u9700\u786e\u8ba4"
            message = "\u5efa\u8bae\u56de\u5230\u8d26\u53f7\u6388\u6743\u68c0\u67e5\uff0c\u786e\u8ba4\u6709\u53ef\u53d1\u5e03\u8d26\u53f7\u540e\u518d\u52a0\u5165\u961f\u5217\u3002"
            _action("authorize_account", "\u786e\u8ba4\u8d26\u53f7", message, "authorize_account", "accounts", "warning", {"accountId": "douyin-self"})
        else:
            status = "ready"
            headline = "\u6388\u6743\u548c\u7d20\u6750\u5df2\u5c31\u7eea\uff0c\u53ef\u521b\u5efa\u9996\u4e2a\u53d1\u5e03\u961f\u5217"
            message = "\u5efa\u8bae\u5148\u9009\u62e9 1 \u4e2a\u7d20\u6750\u30011 \u4e2a\u8d26\u53f7\u52a0\u5165\u4f4e\u9891\u961f\u5217\uff0c\u8dd1\u901a\u56de\u6267\u540e\u518d\u6269\u5927\u3002"
            _action("browse_assets", "\u4ece\u7d20\u6750\u52a0\u5165\u961f\u5217", message, "browse_assets", "autopub", "info")
    else:
        checked = int(preview.get("checked") or 0)
        ready = int(preview.get("ready") or 0)
        blocked = int(preview.get("blocked") or 0)
        if blocked > 0:
            status = "needs_attention"
            headline = "\u961f\u5217\u6709 " + str(blocked) + " \u4e2a\u9879\u76ee\u9700\u5904\u7406"
            message = preview.get("summary") or "\u5efa\u8bae\u5148\u6267\u884c\u6279\u91cf\u4f53\u68c0\uff0c\u6309\u963b\u585e\u539f\u56e0\u4fee\u590d\u540e\u518d\u91cd\u8bd5\u3002"
            _action("batch_preflight", "\u6279\u91cf\u4f53\u68c0", message, "batch_preflight", "autopub", "warning")
            _action("batch_repair", "\u4f53\u68c0\u5e76\u4fee\u590d", "\u5c06\u53ef\u6267\u884c\u7684\u5931\u8d25\u961f\u5217\u91cd\u65b0\u6392\u961f\uff0c\u4fdd\u7559\u4ecd\u9700\u4eba\u5de5\u5904\u7406\u7684\u963b\u585e\u9879\u3002", "batch_repair", "autopub", "warning")
        elif ready > 0:
            status = "ready"
            headline = "\u961f\u5217\u53ef\u6062\u590d\u6267\u884c"
            message = "\u5df2\u4f53\u68c0 " + str(checked) + " \u4e2a\u961f\u5217\uff0c" + str(ready) + " \u4e2a\u53ef\u6267\u884c\u3002\u53ef\u5148\u4f4e\u9891\u6062\u590d\u8c03\u5ea6\u3002"
            _action("batch_repair", "\u6062\u590d\u53ef\u6267\u884c\u961f\u5217", "\u5c06\u53ef\u6267\u884c\u7684\u961f\u5217\u91cd\u65b0\u7f6e\u4e3a\u5f85\u53d1\u72b6\u6001\u3002", "batch_repair", "autopub", "info")
            _action("export_preflight", "\u5bfc\u51fa\u4f53\u68c0\u56de\u6267", "\u5bfc\u51fa\u961f\u5217\u4f53\u68c0\u7ed3\u679c\uff0c\u4fbf\u4e8e\u5ba2\u670d/\u5ba2\u6237\u6210\u529f\u590d\u76d8\u3002", "export_preflight", "autopub", "info")
        else:
            status = "needs_attention"
            headline = "\u961f\u5217\u6682\u65e0\u53ef\u6267\u884c\u9879"
            message = preview.get("summary") or "\u5efa\u8bae\u68c0\u67e5\u7d20\u6750\u3001\u8d26\u53f7\u548c\u53d1\u5e03\u5f00\u5173\u3002"
            _action("batch_preflight", "\u91cd\u65b0\u4f53\u68c0", message, "batch_preflight", "autopub", "warning")
    cards = [
        {"key": "queue", "label": "\u961f\u5217", "value": str(len(queue_rows))},
        {"key": "actionable", "label": "\u53ef\u68c0\u67e5", "value": str(len(actionable))},
        {"key": "ready", "label": "\u4f53\u68c0\u53ef\u6267\u884c", "value": str(preview.get("ready") or 0)},
        {"key": "blocked", "label": "\u9700\u5904\u7406", "value": str(preview.get("blocked") or 0)},
    ]
    return {
        "ok": True,
        "orgId": org_id,
        "status": status,
        "headline": headline,
        "message": message,
        "cards": cards,
        "actions": actions[:4],
        "nextAction": actions[0] if actions else None,
        "queueAuth": queue_auth,
        "preflight": preview,
        "counts": {"queueTotal": len(queue_rows), "actionable": len(actionable), "library": library_count, "usableAccounts": usable_accounts, "ready": int(preview.get("ready") or 0), "blocked": int(preview.get("blocked") or 0)},
        "items": (preview.get("items") or [])[:limit],
        "generatedAt": now(),
    }

def queue_detail(qid, org_id):
    item = find_queue_item(qid, org_id)
    if not item:
        return None
    public_item = public_queue_item(item)
    receipt = queue_operation_receipt("detail", item, {"ok": True}, 200)
    return {
        "ok": True,
        "receiptId": receipt.get("receiptId") or public_item.get("receiptId"),
        "latestEventId": receipt.get("latestEventId") or public_item.get("latestEventId"),
        "receipt": receipt,
        "item": public_item,
        "events": public_item.get("events") or [],
        "task": task_for_queue_item(item),
        "preflight": item.get("preflight") or None,
    }



def queue_operation_receipt(action, item=None, payload=None, status=200):
    payload = dict(payload or {})
    public_item = public_queue_item(item) if item else {}
    events = list(public_item.get("events") or [])[-8:]
    ok = bool(payload.get("ok")) and int(status or 0) < 400
    queue_id = public_item.get("id") or (item or {}).get("id") or payload.get("queueId") or ""
    receipt_id = public_item.get("receiptId") or payload.get("receiptId") or queue_receipt_id(queue_id)
    latest_event_id = public_item.get("latestEventId") or payload.get("latestEventId") or receipt_id
    action_label = {"retry": "\u961f\u5217\u91cd\u8bd5", "cancel": "\u961f\u5217\u53d6\u6d88", "detail": "\u961f\u5217\u8be6\u60c5"}.get(action, action or "queue")
    queue_status = queue_task_status(public_item.get("status") or "") if public_item else ""
    if ok:
        if action == "retry":
            summary = "\u961f\u5217\u91cd\u8bd5\u5df2\u53d7\u7406\uff0c\u4efb\u52a1\u5df2\u56de\u5230\u5f85\u53d1\u5e03\u961f\u5217"
            next_action = "watch_queue"
        elif action == "cancel":
            summary = "\u53d1\u5e03\u8ba1\u5212\u5df2\u53d6\u6d88\uff0c\u4e0d\u4f1a\u7ee7\u7eed\u6267\u884c"
            next_action = "done"
        else:
            summary = "\u961f\u5217\u8be6\u60c5\u5df2\u8bfb\u53d6"
            next_action = "inspect"
    else:
        err = payload.get("error") or "queue_operation_failed"
        summary = payload.get("message") or public_error_text(err)
        next_action = "repair_preflight" if payload.get("preflight") else "inspect"
    return {
        "id": receipt_id,
        "receiptId": receipt_id,
        "latestEventId": latest_event_id,
        "queueId": queue_id,
        "action": action,
        "actionLabel": action_label,
        "ok": ok,
        "statusCode": int(status or 0),
        "queueStatus": queue_status,
        "summary": summary,
        "nextAction": next_action,
        "eventCount": len(public_item.get("events") or []),
        "events": events,
        "item": public_item,
        "generatedAt": now(),
    }



def cancel_queue_item(qid, org_id, reason="user_cancelled"):
    item = find_queue_item(qid, org_id)
    if not item:
        payload = {"ok": False, "error": "queue_item_not_found", "queueId": qid}
        payload["receipt"] = queue_operation_receipt("cancel", None, payload, 404)
        payload["receiptId"] = payload["receipt"].get("receiptId")
        payload["latestEventId"] = payload["receipt"].get("latestEventId")
        payload["events"] = payload["receipt"].get("events")
        return None, payload, 404
    if item.get("status") == "running":
        payload = {"ok": False, "error": "queue_item_running", "message": "\u4efb\u52a1\u6b63\u5728\u6267\u884c\uff0c\u6682\u4e0d\u80fd\u76f4\u63a5\u53d6\u6d88"}
        payload["receipt"] = queue_operation_receipt("cancel", item, payload, 409)
        payload["receiptId"] = payload["receipt"].get("receiptId")
        payload["latestEventId"] = payload["receipt"].get("latestEventId")
        payload["events"] = payload["receipt"].get("events")
        return item, payload, 409
    if item.get("status") in ("done", "canceled"):
        payload = {"ok": True, "item": public_queue_item(item), "noop": True}
        payload["receipt"] = queue_operation_receipt("cancel", item, payload, 200)
        payload["receiptId"] = payload["receipt"].get("receiptId")
        payload["latestEventId"] = payload["receipt"].get("latestEventId")
        payload["events"] = payload["receipt"].get("events")
        payload["message"] = payload["receipt"].get("summary")
        return item, payload, 200
    set_queue_status(item["id"], "canceled", lastError=reason, canceledAt=now(), eventAction="canceled", eventMeta={"reason": reason})
    item = find_queue_item(qid, org_id)
    payload = {"ok": True, "item": public_queue_item(item)}
    payload["receipt"] = queue_operation_receipt("cancel", item, payload, 200)
    payload["receiptId"] = payload["receipt"].get("receiptId")
    payload["latestEventId"] = payload["receipt"].get("latestEventId")
    payload["events"] = payload["receipt"].get("events")
    payload["message"] = payload["receipt"].get("summary")
    return item, payload, 200



def retry_queue_item(qid, org_id):
    item = find_queue_item(qid, org_id)
    if not item:
        payload = {"ok": False, "error": "queue_item_not_found", "queueId": qid}
        payload["receipt"] = queue_operation_receipt("retry", None, payload, 404)
        payload["receiptId"] = payload["receipt"].get("receiptId")
        payload["latestEventId"] = payload["receipt"].get("latestEventId")
        payload["events"] = payload["receipt"].get("events")
        return None, payload, 404
    if item.get("status") == "running":
        payload = {"ok": False, "error": "queue_item_running"}
        payload["receipt"] = queue_operation_receipt("retry", item, payload, 409)
        payload["receiptId"] = payload["receipt"].get("receiptId")
        payload["latestEventId"] = payload["receipt"].get("latestEventId")
        payload["events"] = payload["receipt"].get("events")
        return item, payload, 409
    if item.get("status") == "done":
        payload = {"ok": False, "error": "queue_item_done"}
        payload["receipt"] = queue_operation_receipt("retry", item, payload, 409)
        payload["receiptId"] = payload["receipt"].get("receiptId")
        payload["latestEventId"] = payload["receipt"].get("latestEventId")
        payload["events"] = payload["receipt"].get("events")
        return item, payload, 409
    pf = publish_preflight(org_id, item.get("accountId") or "douyin-self", item.get("materialId") or "", mode="queue_retry", dry_run=False)
    if not pf.get("ok"):
        set_queue_status(item["id"], "fail", lastError=pf.get("error") or "preflight_failed", preflight=pf, eventAction="retry_blocked", eventMeta={"reason": pf.get("error") or "preflight_failed", "accountAuthRef": ((pf.get("accountAuthorization") or {}).get("supportRef"))})
        item = find_queue_item(qid, org_id)
        payload = {"ok": False, "error": pf.get("error"), "message": "\u91cd\u8bd5\u524d\u7f6e\u6821\u9a8c\u672a\u901a\u8fc7", "preflight": pf, "item": public_queue_item(item)}
        payload["receipt"] = queue_operation_receipt("retry", item, payload, 400)
        payload["receiptId"] = payload["receipt"].get("receiptId")
        payload["latestEventId"] = payload["receipt"].get("latestEventId")
        payload["events"] = payload["receipt"].get("events")
        return item, payload, 400
    set_queue_status(
        item["id"],
        "pending",
        lastError="",
        result=None,
        preflight=pf,
        centralTaskId=None,
        retriedAt=now(),
        retryCount=int(item.get("retryCount") or 0) + 1,
        eventAction="retry_queued",
        eventMeta={"retryCount": int(item.get("retryCount") or 0) + 1},
    )
    item = find_queue_item(qid, org_id)
    payload = {"ok": True, "item": public_queue_item(item), "preflight": pf}
    payload["receipt"] = queue_operation_receipt("retry", item, payload, 200)
    payload["receiptId"] = payload["receipt"].get("receiptId")
    payload["latestEventId"] = payload["receipt"].get("latestEventId")
    payload["events"] = payload["receipt"].get("events")
    payload["message"] = payload["receipt"].get("summary")
    return item, payload, 200


QUEUE_TRANSIENT_PREFLIGHT_ERRORS = {
    "account_offline",
    "account_cookie_unavailable",
    "account_daily_quota_exceeded",
    "no_online_node",
    "target_node_offline",
    "publish_busy",
    "publish_disabled",
}


def publish_queue_batch_preflight(org_id, body=None, user=None):
    org_id = normalize_org_id(org_id)
    body = body if isinstance(body, dict) else {}
    operation = (body.get("operation") or "preview").strip().lower() if isinstance(body.get("operation") or "preview", str) else "preview"
    if operation in ("check", "scan", "probe", "preflight"):
        operation = "preview"
    if operation in ("fix", "apply", "requeue"):
        operation = "repair"
    if operation not in ("preview", "repair"):
        return {"ok": False, "error": "unsupported_queue_batch_operation", "operation": operation}, 400
    dry_run = bool(body.get("dryRun") or operation == "preview")
    try:
        limit = min(200, max(1, int(body.get("limit") or 100)))
    except Exception:
        limit = 100
    raw_statuses = body.get("statuses") if isinstance(body.get("statuses"), list) else body.get("status")
    if isinstance(raw_statuses, str):
        statuses = [x.strip().lower() for x in raw_statuses.split(",") if x.strip()]
    elif isinstance(raw_statuses, list):
        statuses = [str(x).strip().lower() for x in raw_statuses if str(x).strip()]
    else:
        statuses = ["pending", "queued", "fail", "failed"]
    account_filter = (body.get("accountId") or body.get("centralAccountId") or "").strip()
    q_filter = (body.get("q") or "").strip().lower()
    rows = []
    ready = blocked = warnings = changed = requeued = failed = skipped = 0
    candidates = []
    for item in load_queue(org_id):
        raw_status = (item.get("status") or "pending").strip().lower()
        norm_status = queue_task_status(raw_status)
        if raw_status in ("running", "done"):
            continue
        if statuses and raw_status not in statuses and norm_status not in statuses:
            continue
        if account_filter and (item.get("accountId") or "") != account_filter:
            continue
        if q_filter and q_filter not in queue_search_blob(item):
            continue
        candidates.append(dict(item))
        if len(candidates) >= limit:
            break
    for item in candidates:
        qid = item.get("id") or ""
        before = (item.get("status") or "pending").strip().lower()
        try:
            pf = publish_preflight(org_id, item.get("accountId") or "douyin-self", item.get("materialId") or "", mode="queue_batch", dry_run=False)
        except Exception as exc:
            pf = {"ok": False, "error": "preflight_unavailable", "errors": ["preflight_unavailable"], "message": public_error_text(str(exc))}
        ok = bool(pf.get("ok"))
        reason = pf.get("error") or ((pf.get("errors") or [""])[0] if isinstance(pf.get("errors"), list) else "") or ""
        aa = pf.get("accountAuthorization") if isinstance(pf.get("accountAuthorization"), dict) else {}
        next_action = aa.get("nextAction") or ("authorize_account" if str(reason).startswith("account_") else ("quota_review" if "quota" in str(reason) else "repair_queue"))
        warn_count = len(pf.get("warnings") or []) if isinstance(pf.get("warnings"), list) else 0
        warnings += warn_count
        after = before
        row_changed = False
        if ok:
            ready += 1
            if before in ("fail", "failed", "canceled", "cancelled"):
                after = "pending"
            if not dry_run:
                set_queue_status(
                    qid,
                    after,
                    lastError="",
                    preflight=pf,
                    eventAction="batch_preflight_ready" if after == before else "batch_preflight_requeued",
                    eventMeta={"operation": operation, "warnings": pf.get("warnings") or []},
                )
                changed += 1
                row_changed = True
                if after != before:
                    requeued += 1
        else:
            blocked += 1
            transient = reason in QUEUE_TRANSIENT_PREFLIGHT_ERRORS
            if before in ("fail", "failed") or not transient:
                after = "fail"
            if not dry_run:
                set_queue_status(
                    qid,
                    after,
                    lastError=reason or "preflight_failed",
                    preflight=pf,
                    eventAction="batch_preflight_blocked",
                    eventMeta={"operation": operation, "reason": reason or "preflight_failed", "nextAction": next_action, "supportRef": aa.get("supportRef") or ""},
                )
                changed += 1
                row_changed = True
                if after == "fail" and before not in ("fail", "failed"):
                    failed += 1
        rows.append({
            "queueId": qid,
            "receiptId": item.get("receiptId") or queue_receipt_id(qid),
            "materialId": item.get("materialId") or "",
            "materialTitle": item.get("materialTitle") or "",
            "accountId": item.get("accountId") or "",
            "accountName": item.get("accountName") or "",
            "beforeStatus": before,
            "afterStatus": after,
            "ready": ok,
            "blocked": not ok,
            "changed": row_changed,
            "error": "" if ok else (reason or "preflight_failed"),
            "warnings": pf.get("warnings") or [],
            "nextAction": next_action,
            "nextActionLabel": (aa.get("summary") or public_error_text(reason) or ""),
            "supportRef": aa.get("supportRef") or "",
        })
    checked = len(candidates)
    skipped = max(0, len(load_queue(org_id)) - checked) if q_filter or account_filter else 0
    next_action_counts = {}
    for r in rows:
        if r.get("blocked"):
            key = r.get("nextAction") or "repair_queue"
            next_action_counts[key] = next_action_counts.get(key, 0) + 1
    if next_action_counts:
        next_action = sorted(next_action_counts.items(), key=lambda x: -x[1])[0][0]
    else:
        next_action = "wait_schedule" if ready else "upload_or_queue"
    next_action_label = {
        "authorize_account": "维护账号授权",
        "resume_auth": "继续授权会话",
        "repair_node": "检查执行节点",
        "quota_review": "调整套餐/发布额度",
        "repair_queue": "查看队列详情",
        "wait_schedule": "等待调度执行",
        "upload_or_queue": "上传素材并加入队列",
    }.get(next_action, "查看队列详情")
    summary = ("已体检 %d 个发布队列：%d 个可执行，%d 个需处理" % (checked, ready, blocked))
    if not dry_run:
        summary += "；已更新 %d 个，重新排队 %d 个" % (changed, requeued)
    payload = {
        "ok": True,
        "orgId": org_id,
        "operation": operation,
        "dryRun": dry_run,
        "checked": checked,
        "ready": ready,
        "blocked": blocked,
        "warnings": warnings,
        "changed": changed,
        "requeued": requeued,
        "failed": failed,
        "skipped": skipped,
        "nextAction": next_action,
        "nextActionLabel": next_action_label,
        "counts": {
            "checked": checked,
            "ready": ready,
            "blocked": blocked,
            "warnings": warnings,
            "changed": changed,
            "requeued": requeued,
            "failed": failed,
            "skipped": skipped,
        },
        "summary": summary,
        "items": rows,
        "queue": [public_queue_item(x) for x in load_queue(org_id)],
    }
    add_event("queue_batch_preflight", {"orgId": org_id, "operation": operation, "dryRun": dry_run, "checked": checked, "ready": ready, "blocked": blocked, "changed": changed})
    persist()
    return payload, 200


def run_queue_item(item):
    qid = item.get("id")
    mid = item.get("materialId")
    acc = item.get("accountId") or "douyin-self"
    org_id = item_org_id(item)
    pf = publish_preflight(org_id, acc, mid, mode="queue_run", dry_run=False)
    if not pf.get("ok"):
        reason = pf.get("error") or "preflight_failed"
        transient = reason in ("account_offline", "account_cookie_unavailable", "account_daily_quota_exceeded")
        set_queue_status(qid, "pending" if transient else "fail", lastError=reason, preflight=pf, eventAction="preflight_blocked", eventMeta={"reason": reason, "transient": transient, "accountAuthRef": ((pf.get("accountAuthorization") or {}).get("supportRef"))})
        add_event("queue_preflight_block", {"id": qid, "orgId": org_id, "accountId": acc, "materialId": mid, "reason": reason, "errors": pf.get("errors"), "accountAuthRef": ((pf.get("accountAuthorization") or {}).get("supportRef"))})
        return
    set_queue_status(qid, "running", eventAction="started")
    result, status, task = dispatch_task_sync("/api/publish/run", {
        "orgId": org_id,
        "accountId": acc,
        "materialId": mid,
        "dryRun": False,
        "waitSec": TASK_WAIT_LONG,
    })
    PUBLISH_RT["last_ts"] = now()
    PUBLISH_RT.setdefault("last_ts_by_org", {})[org_id] = PUBLISH_RT["last_ts"]
    if status == 200 and isinstance(result, dict) and result.get("published"):
        record_publish_success(org_id, acc)
        bump_published(mid)
        set_queue_status(qid, "done", result=result, centralTaskId=(task or {}).get("id"), eventAction="published", eventMeta={"taskId": (task or {}).get("id")})
    elif isinstance(result, dict) and result.get("error") in ("publish_busy", "task_timeout_waiting_result"):
        set_queue_status(qid, "pending", lastError=result.get("error"), centralTaskId=(task or {}).get("id"), eventAction="run_deferred", eventMeta={"taskId": (task or {}).get("id"), "error": result.get("error")})
    else:
        queue_error = (result or {}).get("error") if isinstance(result, dict) else str(result)
        set_queue_status(qid, "fail", lastError=queue_error, result=result, centralTaskId=(task or {}).get("id") if task else None, eventAction="failed", eventMeta={"taskId": (task or {}).get("id") if task else None, "error": queue_error})


def publish_scheduler():
    while True:
        try:
            reset_publish_runtime_day()
            PUBLISH_RT.setdefault("last_ts_by_org", {})
            nxt = None
            for item in load_queue():
                if item.get("status") != "pending":
                    continue
                org_id = item_org_id(item)
                settings = load_settings(org_id)
                if not settings.get("enabled"):
                    continue
                interval = float(settings.get("intervalMin", 60) or 60) * 60.0
                per_day = int(settings.get("perAccountPerDay", 1) or 1)
                count_key = org_id + ":" + (item.get("accountId") or "douyin-self")
                if now() - float(PUBLISH_RT["last_ts_by_org"].get(org_id) or 0) >= interval and PUBLISH_RT["counts"].get(count_key, 0) < per_day:
                    nxt = item
                    break
            if nxt:
                run_queue_item(nxt)
        except Exception:
            add_event("scheduler_error", {"trace": traceback.format_exc()})
        time.sleep(20)


LOCAL_BROWSER_STALE_SEC = float(os.getenv("CENTRAL_LOCAL_BROWSER_STALE_SEC", "45") or 45)
LOCAL_BROWSER_TASK_TIMEOUT_SEC = float(os.getenv("CENTRAL_LOCAL_BROWSER_TASK_TIMEOUT_SEC", "300") or 300)

# Canonical local-browser task types -> node-local api_server paths.
# The local client (agent_worker) forwards each task.type to this path on its
# 127.0.0.1:9081 engine, so the FULL Douyin+XHS surface runs in the user's own
# browser + residential IP instead of a cloud node. This is the single execution
# channel after migration; the /api/node/* channel is legacy/transition-only.
LOCAL_BROWSER_TASK_PATHS = {
    "douyin.search": "/api/douyin/search",
    "douyin.work": "/api/douyin/work",
    "douyin.comments": "/api/douyin/comments",
    "douyin.comment.publish": "/api/douyin/comment/publish",
    "douyin.dm": "/api/douyin/dm",
    "douyin.download": "/api/douyin/download",
    "douyin.publish": "/api/publish/run",
    "xhs.search": "/api/xhs/search",
    "xhs.comments": "/api/xhs/comments",
    "xhs.comment.publish": "/api/xhs/comment/publish",
    "xhs.download": "/api/xhs/download",
    "xhs.discover": "/api/finder/discover",
    "finder.discover": "/api/finder/discover",
    "outreach.run": "/api/outreach/run",
    "publish.run": "/api/publish/run",
}
# Login task types are handled by a dedicated client-side login handler (Phase 2),
# not a plain api_server path.
LOCAL_BROWSER_LOGIN_TYPES = ("douyin.login", "xhs.login")
LOCAL_BROWSER_ALLOWED_TYPES = set(LOCAL_BROWSER_TASK_PATHS.keys()) | set(LOCAL_BROWSER_LOGIN_TYPES)
LOCAL_BROWSER_ALL_CAPS = sorted(LOCAL_BROWSER_ALLOWED_TYPES)
# Legacy default advertised by the XHS-only browser extension.
LOCAL_BROWSER_LEGACY_CAPS = ["xhs.search", "xhs.comments", "xhs.discover"]


def local_browser_housekeeping_locked():
    clients = STATE.setdefault("localBrowserClients", {})
    tasks = STATE.setdefault("localBrowserTasks", {})
    ts = now()
    for c in clients.values():
        try:
            c["online"] = (ts - float(c.get("lastSeen") or 0)) <= LOCAL_BROWSER_STALE_SEC
        except Exception:
            c["online"] = False
    changed = False
    for t in tasks.values():
        if (t.get("status") == "running") and (ts - float(t.get("updatedAt") or t.get("startedAt") or 0) > LOCAL_BROWSER_TASK_TIMEOUT_SEC):
            t["status"] = "queued"
            t["clientId"] = ""
            t["error"] = "local_browser_task_requeued"
            t["updatedAt"] = ts
            changed = True
    if len(tasks) > 1000:
        keep = sorted(tasks.values(), key=lambda x: x.get("createdAt", 0), reverse=True)[:800]
        STATE["localBrowserTasks"] = {x["id"]: x for x in keep if x.get("id")}
        changed = True
    return changed


def public_local_browser_client(c):
    c = dict(c or {})
    ts = now()
    last = float(c.get("lastSeen") or 0)
    return {
        "id": c.get("id") or c.get("clientId") or "",
        "clientId": c.get("id") or c.get("clientId") or "",
        "orgId": item_org_id(c),
        "name": c.get("name") or "?????",
        "version": c.get("version") or "",
        "browser": c.get("browser") or "",
        "platform": c.get("platform") or "",
        "capabilities": c.get("capabilities") or [],
        "lastSeen": last,
        "online": bool(last and ts - last <= LOCAL_BROWSER_STALE_SEC),
        "currentUrl": c.get("currentUrl") or "",
        "lastStatus": c.get("lastStatus") or "",
        "lastError": c.get("lastError") or "",
    }


def _local_browser_list(value):
    return value if isinstance(value, list) else []


def _local_browser_comments_for_storage(result, body=None):
    result = result if isinstance(result, dict) else {}
    body = body if isinstance(body, dict) else {}
    for value in (result.get("comments"), body.get("comments"), result.get("items"), body.get("items")):
        if isinstance(value, list):
            return value
    for value in (result.get("comments"), body.get("comments")):
        if isinstance(value, dict):
            nested = value.get("comments") or value.get("items") or value.get("data")
            if isinstance(nested, list):
                return nested
    return []


def public_local_browser_task(t):
    t = dict(t or {})
    result = t.get("result") if isinstance(t.get("result"), dict) else {}
    comments = _local_browser_comments_for_storage(result, t)
    out = {
        "ok": True,
        "id": t.get("id") or "",
        "taskId": t.get("id") or "",
        "orgId": item_org_id(t),
        "type": t.get("type") or "",
        "status": t.get("status") or "queued",
        "clientId": t.get("clientId") or "",
        "createdAt": t.get("createdAt") or 0,
        "updatedAt": t.get("updatedAt") or 0,
        "startedAt": t.get("startedAt") or 0,
        "finishedAt": t.get("finishedAt") or 0,
        "error": t.get("error") or result.get("error") or "",
        "payload": t.get("payload") or {},
        "result": strip_large_payloads(result),
        "items": _local_browser_list(result.get("items")) or _local_browser_list(t.get("items")),
        "comments": comments,
        "leads": _local_browser_list(result.get("leads")) or _local_browser_list(t.get("leads")),
    }
    out["itemCount"] = len(out.get("items") or [])
    out["commentCount"] = len(out.get("comments") or [])
    out["leadCount"] = len(out.get("leads") or [])
    return out


def local_browser_capability_for(task_type):
    task_type = (task_type or "").strip() or "xhs.discover"
    if task_type.startswith("xhs."):
        return task_type
    return task_type


def local_browser_online_clients(org_id, capability="", owner_user_id=None):
    org_id = normalize_org_id(org_id)
    cap = local_browser_capability_for(capability)
    with LOCK:
        local_browser_housekeeping_locked()
        clients = list((STATE.get("localBrowserClients") or {}).values())
    out = []
    for c in clients:
        pc = public_local_browser_client(c)
        if pc.get("orgId") != org_id or not pc.get("online"):
            continue
        if owner_user_id not in (None, "") and not same_user_id(c.get("ownerUserId"), owner_user_id):
            continue
        caps = pc.get("capabilities") or []
        if cap and cap not in caps and "xhs.*" not in caps and "*" not in caps:
            continue
        out.append(pc)
    return out


def local_browser_status(org_id, limit=30):
    org_id = normalize_org_id(org_id)
    with LOCK:
        changed = local_browser_housekeeping_locked()
        clients = [public_local_browser_client(c) for c in (STATE.get("localBrowserClients") or {}).values() if item_org_id(c) == org_id]
        tasks = [public_local_browser_task(t) for t in (STATE.get("localBrowserTasks") or {}).values() if item_org_id(t) == org_id]
    tasks = sorted(tasks, key=lambda x: x.get("updatedAt") or x.get("createdAt") or 0, reverse=True)[:limit]
    if changed:
        try:
            persist()
        except Exception:
            pass
    return {"ok": True, "orgId": org_id, "online": any(c.get("online") for c in clients), "clients": clients, "tasks": tasks, "staleSec": LOCAL_BROWSER_STALE_SEC}


LOCAL_BROWSER_PAIR_TTL_SEC = float(os.getenv("CENTRAL_PAIR_TTL_SEC", "600") or 600)
LOCAL_BROWSER_CLIENT_SESSION_TTL_SEC = float(os.getenv("CENTRAL_CLIENT_SESSION_TTL_SEC", str(365 * 24 * 3600)) or (365 * 24 * 3600))


def local_browser_pair_create(handler, body):
    """SPA (logged-in user) mints a short-lived 6-digit pairing code that carries a
    long-lived org-scoped session token; the desktop client redeems it once so the
    user never copies raw tokens. Replaces the old agent_token copy-paste."""
    org_id = request_org_id(handler, body)
    if not require_role(handler, org_id, "member"):
        return None, None
    user = current_user(handler) or {}
    sess = create_user_session(user, {"kind": "local-client", "orgId": org_id})
    ts = now()
    with LOCK:
        for s in STATE.setdefault("sessions", []):
            if s.get("token") == sess.get("token"):
                s["expiresAt"] = ts + LOCAL_BROWSER_CLIENT_SESSION_TTL_SEC
                s["meta"] = {"kind": "local-client", "orgId": org_id}
                break
        pairings = STATE.setdefault("localBrowserPairings", {})
        for k in list(pairings.keys()):
            if float(pairings[k].get("expiresAt") or 0) < ts:
                pairings.pop(k, None)
        code = None
        for _ in range(8):
            candidate = "%06d" % (uuid.uuid4().int % 1000000)
            if candidate not in pairings:
                code = candidate
                break
        code = code or ("%06d" % (uuid.uuid4().int % 1000000))
        pairings[code] = {"token": sess.get("token"), "orgId": org_id, "userId": user.get("id"),
                          "expiresAt": ts + LOCAL_BROWSER_PAIR_TTL_SEC, "used": False, "createdAt": ts}
        persist()
    add_audit(handler, "local_browser.pair.create", "/api/local-browser/pair/create", ok=True, meta={"orgId": org_id})
    return {"ok": True, "code": code, "expiresInSec": int(LOCAL_BROWSER_PAIR_TTL_SEC)}, 200


def local_browser_pair_redeem(handler, body):
    """Desktop client redeems a pairing code (NO prior auth) -> receives the
    org-scoped token + clientId to persist locally."""
    code = (body.get("code") or "").strip()
    if not code:
        return {"ok": False, "error": "missing_code"}, 400
    ts = now()
    with LOCK:
        pairings = STATE.setdefault("localBrowserPairings", {})
        rec = pairings.get(code)
        if not rec or rec.get("used") or float(rec.get("expiresAt") or 0) < ts:
            return {"ok": False, "error": "invalid_or_expired_code"}, 404
        rec["used"] = True
        rec["redeemedAt"] = ts
        persist()
    return {"ok": True, "token": rec.get("token"), "orgId": rec.get("orgId"),
            "clientId": "lb-" + uuid.uuid4().hex[:10]}, 200


def local_browser_register(handler, body):
    org_id = request_org_id(handler, body)
    if not require_role(handler, org_id, "member"):
        return None, None
    user = current_user(handler) or {}
    client_id = (body.get("clientId") or body.get("id") or "").strip() or ("lb-" + uuid.uuid4().hex[:12])
    caps = body.get("capabilities") if isinstance(body.get("capabilities"), list) else []
    if not caps:
        caps = list(LOCAL_BROWSER_LEGACY_CAPS)
    ts = now()
    with LOCK:
        clients = STATE.setdefault("localBrowserClients", {})
        c = clients.setdefault(client_id, {"id": client_id, "createdAt": ts})
        c.update({
            "id": client_id,
            "orgId": org_id,
            "ownerUserId": user.get("id") or "",
            "name": body.get("name") or c.get("name") or "?????",
            "version": body.get("version") or c.get("version") or "",
            "browser": body.get("browser") or c.get("browser") or "",
            "platform": body.get("platform") or c.get("platform") or "",
            "capabilities": caps,
            "currentUrl": body.get("currentUrl") or c.get("currentUrl") or "",
            "lastStatus": body.get("status") or c.get("lastStatus") or "registered",
            "lastError": body.get("error") or "",
            "lastSeen": ts,
            "online": True,
            "updatedAt": ts,
        })
        local_browser_housekeeping_locked()
    persist()
    add_audit(handler, "local_browser.register", "/api/local-browser/register", ok=True, meta={"orgId": org_id, "clientId": client_id, "capabilities": caps})
    return {"ok": True, "clientId": client_id, "pollIntervalSec": 2, "client": public_local_browser_client(c)}, 200


def local_browser_create_task(handler, body):
    org_id = request_org_id(handler, body)
    if not require_role(handler, org_id, "member"):
        return None, None
    user = current_user(handler) or {}
    task_type = (body.get("type") or "xhs.discover").strip()
    if task_type not in LOCAL_BROWSER_ALLOWED_TYPES:
        return {"ok": False, "error": "unsupported_local_browser_task", "type": task_type}, 400
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    if not payload:
        _ctrl = {"type", "orgId", "org_id", "allowOffline", "payload", "clientId", "id"}
        payload = {k: v for k, v in body.items() if k not in _ctrl}
    # Publish tasks need the material's files attached so the local client can
    # download them to its engine before publishing (parity with the node path).
    if task_type in ("publish.run", "douyin.publish"):
        aid = (payload.get("accountId") or "").strip()
        if ":" in aid:
            _node, _local = aid.split(":", 1)
            payload["centralAccountId"] = aid
            payload["accountId"] = _local or "douyin-self"
        mid = (payload.get("materialId") or payload.get("centralMaterialId") or "").strip()
        if mid and not payload.get("centralMaterial"):
            mp = material_payload(mid, normalize_org_id(org_id))
            if not mp:
                return {"ok": False, "error": "material_not_found", "materialId": mid}, 404
            payload["centralMaterial"] = mp
            payload["centralMaterialId"] = mid
    online = local_browser_online_clients(org_id, task_type, user.get("id"))
    if not online and not body.get("allowOffline"):
        return {"ok": False, "error": "local_browser_offline", "orgId": org_id, "type": task_type,
                "message": "本地浏览器客户端未在线,请先启动客户端并登录对应平台账号后重试。"}, 409
    task_id = "lbt-" + uuid.uuid4().hex
    ts = now()
    task = {
        "id": task_id,
        "orgId": org_id,
        "type": task_type,
        "payload": payload,
        "status": "queued",
        "clientId": "",
        "createdBy": user.get("id") or "",
        "createdAt": ts,
        "updatedAt": ts,
        "error": "",
        "result": {},
    }
    with LOCK:
        STATE.setdefault("localBrowserTasks", {})[task_id] = task
    persist()
    add_audit(handler, "local_browser.task.create", "/api/local-browser/task", ok=True, meta={"orgId": org_id, "taskId": task_id, "type": task_type, "payload": audit_safe_body(payload)})
    return {"ok": True, "taskId": task_id, "task": public_local_browser_task(task), "onlineClients": online}, 200


def local_browser_poll(handler, body):
    org_id = request_org_id(handler, body)
    if not require_role(handler, org_id, "member"):
        return None, None
    user = current_user(handler) or {}
    client_id = (body.get("clientId") or body.get("id") or "").strip()
    if not client_id:
        return {"ok": False, "error": "missing_client_id"}, 400
    caps = body.get("capabilities") if isinstance(body.get("capabilities"), list) else []
    ts = now()
    selected = None
    with LOCK:
        clients = STATE.setdefault("localBrowserClients", {})
        c = clients.setdefault(client_id, {"id": client_id, "createdAt": ts})
        if not caps:
            caps = c.get("capabilities") or list(LOCAL_BROWSER_LEGACY_CAPS)
        c.update({"id": client_id, "orgId": org_id, "capabilities": caps, "lastSeen": ts, "updatedAt": ts, "online": True, "lastStatus": body.get("status") or "polling", "currentUrl": body.get("currentUrl") or c.get("currentUrl") or "", "lastError": body.get("error") or ""})
        local_browser_housekeeping_locked()
        queued = sorted([
            t for t in (STATE.get("localBrowserTasks") or {}).values()
            if item_org_id(t) == org_id
            and t.get("status") == "queued"
            and (not t.get("createdBy") or same_user_id(t.get("createdBy"), user.get("id")))
        ], key=lambda x: x.get("createdAt") or 0)
        for t in queued:
            cap = local_browser_capability_for(t.get("type"))
            if cap in caps or "xhs.*" in caps or "*" in caps:
                t["status"] = "running"
                t["clientId"] = client_id
                t["startedAt"] = t.get("startedAt") or ts
                t["updatedAt"] = ts
                selected = dict(t)
                break
    if selected:
        persist()
        add_event("local_browser_task_started", {"taskId": selected.get("id"), "clientId": client_id, "orgId": org_id})
        return {"ok": True, "task": public_local_browser_task(selected), "pollIntervalSec": 1}, 200
    return {"ok": True, "task": None, "pollIntervalSec": 2}, 200


def local_browser_upsert_account(org_id, client_id, platform, info, cookie_count=0):
    """Register/refresh a social account from a local-browser login result. The
    account is bound to the local client (executor=local); cookies stay on the
    user's machine — only identity + cookie STATUS is stored centrally."""
    org_id = normalize_org_id(org_id)
    client_id = client_id or "local"
    info = info or {}
    local_id = str(info.get("id") or info.get("handle") or info.get("name") or (platform + "-self"))
    asset_id = client_id + ":" + local_id
    ts = now()
    try:
        caps = normalize_account_capabilities(None, platform, True, cookie_count or 0)
    except Exception:
        caps = []
    with LOCK:
        client = (STATE.get("localBrowserClients") or {}).get(client_id) or {}
        owner_user_id = client.get("ownerUserId") or info.get("ownerUserId") or ""
        registry = STATE.setdefault("accountsRegistry", [])
        by_id = {a.get("id"): a for a in registry if a.get("id")}
        old = by_id.get(asset_id) or {"id": asset_id, "createdAt": ts}
        for aid, other in list(by_id.items()):
            if aid == asset_id:
                continue
            if item_org_id(other) != org_id:
                continue
            if str(other.get("platform") or "") != str(platform or ""):
                continue
            if str(other.get("localAccountId") or "") != local_id:
                continue
            if owner_user_id and not same_user_id(other.get("ownerUserId"), owner_user_id):
                continue
            other["online"] = False
            other["status"] = "offline"
            other["supersededBy"] = asset_id
            other["offlineSince"] = ts
            other["updatedAt"] = ts
        old.update({
            "id": asset_id, "orgId": org_id, "platform": platform, "localAccountId": local_id,
            "ownerUserId": owner_user_id,
            "nodeId": client_id, "nodeName": info.get("nodeName") or "本地浏览器", "executor": "local",
            "name": info.get("name") or info.get("handle") or ("小红书账号" if platform == "xhs" else "抖音账号"),
            "handle": info.get("handle") or "", "fans": info.get("fans") or "", "avatar": info.get("avatar") or "",
            "cookieReady": True, "cookieCount": cookie_count or info.get("cookieCount") or 0, "capabilities": caps,
            "online": True, "status": "online",
            "authorizedAt": old.get("authorizedAt") or ts, "cookieUpdatedAt": ts, "lastSeen": ts, "updatedAt": ts,
        })
        old.pop("cookieLostAt", None)
        old.pop("offlineSince", None)
        by_id[asset_id] = old
        STATE["accountsRegistry"] = sorted(by_id.values(), key=lambda x: x.get("updatedAt", 0), reverse=True)
    return asset_id


def local_browser_apply_side_effects(handler, task, result):
    """Run the same post-processing the /api/node/* channel runs, but keyed by the
    local-browser task TYPE and triggered when the async result returns. Keeps
    publish/download/finder results landing in the library / leads / bookkeeping
    no matter whether a cloud node or a user's local browser executed the task.

    MUST be called OUTSIDE the STATE lock: the helpers below take LOCK themselves.
    Mutates `result` in place (adds material/leadSync markers)."""
    if not isinstance(result, dict) or result.get("ok") is False:
        return True
    ttype = (task.get("type") or "").strip()
    org_id = item_org_id(task)
    payload = task.get("payload") or {}
    path = LOCAL_BROWSER_TASK_PATHS.get(ttype, "")
    if path in ("/api/douyin/download", "/api/xhs/download"):
        try:
            mirrored = mirror_download_material_to_library(result, org_id, task.get("clientId") or "")
        except Exception as exc:
            raw_log = json_log(
                logger,
                "download_library_import_failed",
                exc=exc,
                endpoint="/api/local-browser/result",
                task_id=task.get("id") or "",
                org_id=org_id,
                node_id=task.get("clientId") or "",
                source_url=payload.get("url") or payload.get("noteUrl") or "",
            )
            error_id = (json.loads(raw_log) or {}).get("errorId")
        else:
            if isinstance(mirrored, dict) and mirrored.get("id"):
                result["material"] = public_material(mirrored)
                result["materialId"] = mirrored.get("id")
                result["libraryImported"] = True
                return True
            raw_log = json_log(
                logger,
                "download_library_import_failed",
                endpoint="/api/local-browser/result",
                task_id=task.get("id") or "",
                org_id=org_id,
                node_id=task.get("clientId") or "",
                source_url=payload.get("url") or payload.get("noteUrl") or "",
                reason="missing_material_id",
            )
            error_id = (json.loads(raw_log) or {}).get("errorId")
        result.update({
            "ok": False,
            "error": "library_import_failed",
            "errorId": error_id,
            "stage": "library",
            "libraryImported": False,
        })
        return False
    try:
        if ttype in LOCAL_BROWSER_LOGIN_TYPES:
            if result.get("loggedIn") or result.get("ok"):
                plat = "xhs" if ttype.startswith("xhs") else "douyin"
                local_browser_upsert_account(org_id, task.get("clientId") or "", plat, result.get("account") or {}, result.get("cookieCount") or 0)
            return True
        if path == "/api/publish/run" and result.get("published"):
            bump_published(payload.get("materialId") or payload.get("centralMaterialId") or "")
            record_publish_success(org_id, payload.get("centralAccountId") or payload.get("accountId") or "douyin-self")
        elif path == "/api/finder/discover":
            leads = result.get("leads") or task.get("leads") or []
            sync_payload, _sync_status = upsert_finder_leads(
                org_id, leads,
                keyword=payload.get("keyword") or payload.get("query") or "",
                task_id=task.get("id") or "",
                node_id=task.get("clientId") or "",
                source="local_browser_discover",
                user=current_user(handler),
            )
            result["leadSync"] = {k: sync_payload.get(k) for k in ("ok", "created", "updated", "total", "stats")}
    except Exception as e:
        try:
            add_event("local_browser_side_effect_error", {"taskId": task.get("id"), "type": task.get("type"), "error": str(e)})
        except Exception:
            pass
    return True


def local_browser_result(handler, body):
    org_id = request_org_id(handler, body)
    if not require_role(handler, org_id, "member"):
        return None, None
    task_id = (body.get("taskId") or body.get("id") or "").strip()
    client_id = (body.get("clientId") or "").strip()
    if not task_id:
        return {"ok": False, "error": "missing_task_id"}, 400
    ok = body.get("ok") is not False
    result = body.get("result") if isinstance(body.get("result"), dict) else {}
    if not result:
        result = {"ok": ok, "items": body.get("items") or [], "comments": body.get("comments") or [], "leads": body.get("leads") or [], "error": body.get("error") or ""}
    ts = now()
    task_ref = None
    with LOCK:
        task = (STATE.get("localBrowserTasks") or {}).get(task_id)
        if not task or item_org_id(task) != org_id:
            return {"ok": False, "error": "local_browser_task_not_found", "taskId": task_id}, 404
        if task.get("clientId") and client_id and task.get("clientId") != client_id:
            return {"ok": False, "error": "local_browser_client_mismatch", "taskId": task_id}, 409
        task["status"] = "running" if ok else "failed"
        task["clientId"] = client_id or task.get("clientId") or ""
        task["result"] = strip_large_payloads(result, max_inline=20000)
        task["items"] = (_local_browser_list(result.get("items")) or _local_browser_list(body.get("items")))[:100]
        task["comments"] = _local_browser_comments_for_storage(result, body)[:500]
        task["leads"] = (_local_browser_list(result.get("leads")) or _local_browser_list(body.get("leads")))[:500]
        task["error"] = body.get("error") or result.get("error") or ""
        task["updatedAt"] = ts
        if client_id in STATE.get("localBrowserClients", {}):
            STATE["localBrowserClients"][client_id]["lastSeen"] = ts
            STATE["localBrowserClients"][client_id]["lastStatus"] = "task_finalizing" if ok else "task_failed"
            STATE["localBrowserClients"][client_id]["lastError"] = task.get("error") or ""
        task_ref = task
    # Post-processing (library mirror / publish bookkeeping / finder-lead sync)
    # runs on the FULL result and OUTSIDE the lock (the helpers take LOCK).
    if task_ref is not None and ok:
        side_effect_ok = local_browser_apply_side_effects(handler, task_ref, result)
        if side_effect_ok is False or result.get("ok") is False:
            ok = False
        with LOCK:
            task_ref["result"] = strip_large_payloads(result, max_inline=20000)
            task_ref["leads"] = (_local_browser_list(result.get("leads")) or _local_browser_list(task_ref.get("leads")))[:500]
    if task_ref is not None:
        finished_at = now()
        with LOCK:
            task_ref["status"] = "done" if ok else "failed"
            task_ref["error"] = "" if ok else (
                body.get("error") or result.get("error") or "local_browser_task_failed"
            )
            task_ref["finishedAt"] = finished_at
            task_ref["updatedAt"] = finished_at
            if client_id in STATE.get("localBrowserClients", {}):
                STATE["localBrowserClients"][client_id]["lastStatus"] = "task_done" if ok else "task_failed"
                STATE["localBrowserClients"][client_id]["lastError"] = task_ref["error"]
    persist()
    add_event("local_browser_task_finished", {"taskId": task_id, "clientId": client_id, "ok": ok, "orgId": org_id})
    add_audit(handler, "local_browser.task.result", "/api/local-browser/result", ok=ok, meta={"orgId": org_id, "taskId": task_id, "clientId": client_id, "error": body.get("error") or result.get("error") or ""})
    return {"ok": True, "task": public_local_browser_task(task_ref)}, 200


def local_browser_task_detail(handler, qs):
    org_id = request_org_id(handler, qs=qs)
    if not require_role(handler, org_id, "member"):
        return None, None
    task_id = (qs.get("id") or qs.get("taskId") or [""])[0]
    with LOCK:
        local_browser_housekeeping_locked()
        task = (STATE.get("localBrowserTasks") or {}).get(task_id)
    if not task or item_org_id(task) != org_id:
        return {"ok": False, "error": "local_browser_task_not_found", "taskId": task_id}, 404
    return public_local_browser_task(task), 200


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_OPTIONS(self):
        return json_response(self, {"ok": True})

    def serve_material_file(self, path):
        rel = path[len("/api/library/file/"):]
        parts = [p for p in rel.split("/") if p]
        if len(parts) != 2:
            return json_response(self, {"ok": False, "error": "bad_path"}, 400)
        mid = safe_filename(unquote(parts[0]), "material")
        name = safe_filename(unquote(parts[1]), "file")
        try:
            base = material_dir(mid)
        except Exception:
            return json_response(self, {"ok": False, "error": "forbidden"}, 403)
        fp = os.path.normpath(os.path.join(base, name))
        if fp != base and not fp.startswith(base + os.sep):
            return json_response(self, {"ok": False, "error": "forbidden"}, 403)
        if not os.path.isfile(fp):
            return json_response(self, {"ok": False, "error": "not_found", "path": path}, 404)
        ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        try:
            size = os.path.getsize(fp)
            rng = parse_http_range(self.headers.get("Range"), size)
            if self.headers.get("Range") and rng is None:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
                self.end_headers()
                return
            if rng:
                start, end = rng
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            else:
                start, length = 0, size
                self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
            self.send_header("Vary", "Origin")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with open(fp, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except Exception as e:
            return json_response(self, {"ok": False, "error": str(e)}, 500)

    def serve_public_media_file(self, parsed):
        path = parsed.path
        rel = path[len("/api/public-media/"):]
        parts = [p for p in rel.split("/") if p]
        if len(parts) != 2:
            return json_response(self, {"ok": False, "error": "bad_path"}, 400)
        mid = safe_filename(unquote(parts[0]), "material")
        name = safe_filename(unquote(parts[1]), "file")
        qs = parse_qs(parsed.query or "")
        org_id = normalize_org_id((qs.get("orgId") or [""])[0])
        expires = (qs.get("expires") or [""])[0]
        token = (qs.get("token") or [""])[0]
        ok, reason = verify_public_media_token(mid, name, org_id, expires, token)
        if not ok:
            return json_response(self, {"ok": False, "error": "public_media_" + reason}, 403)
        material = find_material(mid, org_id)
        if not material or name not in (material.get("files") or []):
            return json_response(self, {"ok": False, "error": "not_found"}, 404)
        try:
            base = material_dir(mid)
        except Exception:
            return json_response(self, {"ok": False, "error": "forbidden"}, 403)
        fp = os.path.normpath(os.path.join(base, name))
        if fp != base and not fp.startswith(base + os.sep):
            return json_response(self, {"ok": False, "error": "forbidden"}, 403)
        if not os.path.isfile(fp):
            return json_response(self, {"ok": False, "error": "not_found"}, 404)
        ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        try:
            size = os.path.getsize(fp)
            rng = parse_http_range(self.headers.get("Range"), size)
            if self.headers.get("Range") and rng is None:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                return
            if rng:
                start, end = rng
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            else:
                start, length = 0, size
                self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=300")
            self.end_headers()
            with open(fp, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except Exception as e:
            return json_response(self, {"ok": False, "error": str(e)}, 500)

    def serve_agent_installer(self):
        candidates = [
            os.path.abspath(os.path.expandvars(os.getenv("MATRIXSHIP_AGENT_INSTALLER", ""))),
            "/root/juzhen-xingjian/MatrixShipAgent-Setup.exe",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "MatrixShipAgent-Setup.exe")),
        ]
        fp = next((p for p in candidates if p and os.path.isfile(p)), "")
        if not fp:
            return json_response(self, {"ok": False, "error": "installer_not_found"}, 404)
        try:
            size = os.path.getsize(fp)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", 'attachment; filename="MatrixShipAgent-Setup.exe"')
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with open(fp, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
        except Exception as e:
            return json_response(self, {"ok": False, "error": str(e)}, 500)

    def handle_multipart(self, path):
        if path not in ("/api/library/upload", "/api/kb/upload"):
            return json_response(self, {"ok": False, "error": "not_found"}, 404)
        fields, files = parse_multipart(self)
        if path == "/api/kb/upload":
            org_id = request_org_id(self, fields)
            if not require_role(self, org_id, "member"):
                return
            if not require_feature(self, org_id, "knowledgeBase"):
                return
            title = (fields.get("title") or "").strip()
            ktype = (fields.get("type") or "company").strip()
            if not files:
                return json_response(self, {"ok": False, "error": "no_files"}, 400)
            texts = []
            names = []
            for _field, filename, data in files:
                names.append(safe_filename(filename, "file"))
                txt = decode_uploaded_text(filename, data)
                if txt.strip():
                    texts.append("【%s】\n%s" % (safe_filename(filename, "file"), txt.strip()))
            text = "\n\n".join(texts).strip()
            if not text:
                return json_response(self, {"ok": False, "error": "no_text_extracted"}, 400)
            actor = current_user(self) or {}
            item = add_kb_doc(title or (names[0] if names else "上传资料"), ktype, text, org_id, source=",".join(names[:8]), created_by=actor.get("id"))
            add_audit(self, "kb.upload", path, ok=True, meta={"orgId": org_id, "docId": item["id"], "files": names[:8], "chars": len(text)})
            return json_response(self, {"ok": True, "id": item["id"], "chunks": len(item.get("chunkTexts") or []), "chars": len(text)})
        title = (fields.get("title") or "").strip()
        mtype = (fields.get("type") or "video").strip()
        org_id = request_org_id(self, fields)
        if not require_role(self, org_id, "member"):
            return
        if not require_feature(self, org_id, "library"):
            return
        if not files:
            return json_response(self, {"ok": False, "error": "no_files"}, 400)
        quota_block = quota_guard(org_id, "materials", 1)
        if quota_block:
            add_audit(self, "quota.block", path, ok=False, meta={"orgId": org_id, "resource": "materials", "used": quota_block.get("used"), "limit": quota_block.get("limit")})
            return json_response(self, quota_block, 429)
        mid = uuid.uuid4().hex
        mdir = material_dir(mid)
        os.makedirs(mdir, exist_ok=True)
        saved = []
        for idx, (_field, filename, data) in enumerate(files):
            safe = safe_filename(filename, "file_%d" % idx)
            root, ext = os.path.splitext(safe)
            final = safe
            n = 1
            while os.path.exists(os.path.join(mdir, final)):
                final = "%s_%d%s" % (root or "file", n, ext)
                n += 1
            with open(os.path.join(mdir, final), "wb") as f:
                f.write(data)
            saved.append(final)
        item = {
            "id": mid,
            "orgId": org_id,
            "title": title or saved[0],
            "type": mtype,
            "files": saved,
            "published": 0,
            "createdBy": (current_user(self) or {}).get("id") or "",
            "createdByUserId": (current_user(self) or {}).get("id") or "",
            "createdAt": now(),
        }
        with LOCK:
            lib = list(STATE.get("library") or [])
            lib.insert(0, item)
            STATE["library"] = lib
            persist()
        pub = public_material(item)
        return json_response(self, {"ok": True, "id": mid, "files": saved, "urls": pub.get("urls") or [], "material": pub})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path == "/lk888" or path.startswith("/lk888/"):
            return lk888_proxy(self, "GET", parsed)
        if path.startswith("/manju-media/"):
            return manju_media_proxy(self, parsed)
        if path == "/MatrixShipAgent-Setup.exe":
            return self.serve_agent_installer()
        if path == "/api/shared-assets":
            return shared_assets_list(self, parsed)
        if path == "/api/version":
            with LOCK:
                rel = dict(STATE.get("releaseConfig") or {})
            return json_response(self, {"ok": True, "version": CENTRAL_VERSION, "release": rel,
                                        "latest": rel.get("latestVersion"), "downloadUrl": rel.get("downloadUrl"),
                                        "notice": rel.get("notice"), "force": bool(rel.get("force"))})
        if path.startswith("/api/cloud-login/"):
            return json_response(self, {"ok": False, "error": "cloud_login_removed", "message": "云端登录已下线，请在本机客户端用本地浏览器登录"}, 410)
        if path.startswith("/api/library/file/"):
            return self.serve_material_file(path)
        if path.startswith("/api/public-media/"):
            return self.serve_public_media_file(parsed)
        if path == "/api/health":
            authorized = user_authorized(self)
            org_id = request_org_id(self, qs=qs)
            nodes = online_nodes(org_id)
            payload = {
                "ok": True,
                "mode": "central",
                "version": CENTRAL_VERSION,
                "agentReady": True,
                "authorized": authorized,
                "cookieReady": bool(authorized and any(n.get("cookieReady") for n in nodes)),
                "onlineNodes": len(nodes),
                "nodeCount": len([n for n in (STATE.get("nodes") or {}).values() if item_org_id(n) == org_id]),
                "orgId": org_id,
            }
            if authorized:
                payload["nodes"] = nodes
            return json_response(self, payload)
        if path == "/api/auth/me":
            tok = extract_user_token(self)
            u = current_user(self)
            if not u and USER_TOKEN:
                return json_response(self, {"ok": False, "error": "not_authenticated"}, 401)
            if not u:
                return json_response(self, {"ok": True, "user": None, "organizations": [], "memberships": []})
            memberships = user_memberships(u)
            sess = user_session_by_token(tok) if u.get("_authType") == "session" else None
            exp = float((sess or {}).get("expiresAt") or 0)
            ctx = auth_context_for_user(u, auth_type=u.get("_authType"))
            return json_response(self, dict(ctx, ok=True, user=public_user(u), memberships=memberships, expiresAt=(sess or {}).get("expiresAt"), expiresInSec=max(0, int(exp - now())) if exp else 0, sessionTtlSec=int(SESSION_TTL_SEC)))
        if path == "/api/auth/sessions":
            u = current_user(self)
            payload, status = list_authenticated_user_sessions(u)
            return json_response(self, payload, status)
        if not require_user(self):
            return
        if path == "/api/account/balance":
            u = current_user(self)
            if not u:
                return json_response(self, {"ok": False, "error": "not_authenticated"}, 401)
            return json_response(self, {"ok": True, "userId": u.get("id"),
                                        "phone": u.get("phone"), "balance": get_balance(u.get("id"))})
        if path == "/api/billing/ledger":
            u = current_user(self)
            if not u:
                return json_response(self, {"ok": False, "error": "not_authenticated"}, 401)
            with LOCK:
                rows = [dict(x) for x in (STATE.get("ledger") or []) if x.get("userId") == u.get("id")]
            rows = list(reversed(rows))[:100]
            return json_response(self, {"ok": True, "ledger": rows, "balance": get_balance(u.get("id"))})
        if path == "/api/billing/recharge/packages":
            if not require_platform_admin(self):
                return
            if maindb_on():
                _rate = MAINDB_YUAN_TO_POWER  # 算力/元(默认 10)
                _pkgs = [{"id": p["id"], "yuan": p["yuan"], "power": round(p["yuan"] * _rate, 2),
                          "yundou": round(p["yuan"] * _rate, 2)} for p in RECHARGE_PACKAGES]
                return json_response(self, {"ok": True, "packages": _pkgs, "rate": _rate, "unit": "算力",
                                            "minYuan": RECHARGE_MIN_FEN // 100, "maxYuan": RECHARGE_MAX_FEN // 100,
                                            "enabled": wxpay().configured})
            return json_response(self, {"ok": True, "packages": RECHARGE_PACKAGES,
                                        "rate": 100, "unit": "云豆", "minYuan": RECHARGE_MIN_FEN // 100,
                                        "maxYuan": RECHARGE_MAX_FEN // 100,
                                        "enabled": wxpay().configured})
        if path == "/api/billing/recharge/status":
            if not require_platform_admin(self):
                return
            u = current_user(self)
            if not u:
                return json_response(self, {"ok": False, "error": "not_authenticated"}, 401)
            order_no = (parse_qs(parsed.query).get("orderNo") or [""])[0].strip()
            ok, res, err = poll_recharge_order(u.get("id"), order_no)
            if not ok:
                return json_response(self, {"ok": False, "error": err}, 400)
            return json_response(self, dict(res, ok=True))
        if path == "/api/admin/users":
            if not require_platform_admin(self):
                return
            with LOCK:
                users = [public_user(x) for x in (STATE.get("users") or [])]
            for x in users:
                x["balance"] = get_balance(x.get("id"))
            return json_response(self, {"ok": True, "users": users})
        if path == "/api/admin/redeem-codes":
            if not require_platform_admin(self):
                return
            try:
                limit = min(1000, int((qs.get("limit") or ["200"])[0] or 200))
            except Exception:
                limit = 200
            data = list_redeem_codes(limit=limit)
            data["ok"] = True
            return json_response(self, data)
        if path == "/api/local-browser/status":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            limit = min(100, int((qs.get("limit") or ["30"])[0] or 30))
            return json_response(self, local_browser_status(org_id, limit=limit))
        if path == "/api/local-browser/task":
            payload, status = local_browser_task_detail(self, qs)
            if payload is None:
                return
            return json_response(self, payload, status)
        if path == "/api/central/nodes":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            user = current_user(self)
            include_all = bool(user and user.get("_authType") == "root-token" and (qs.get("all") or [""])[0] in ("1", "true", "yes"))
            all_nodes = [public_node(n) for n in (STATE.get("nodes") or {}).values()]
            if not include_all:
                all_nodes = [n for n in all_nodes if item_org_id(n) == org_id]
            return json_response(self, {"ok": True, "nodes": online_nodes(org_id), "allNodes": all_nodes})
        if path == "/api/central/node-capacity":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            return json_response(self, org_node_capacity(org_id))
        if path == "/api/central/node-runtime-probe":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            node_id = (qs.get("nodeId") or qs.get("id") or [""])[0]
            payload, status = node_runtime_probe(org_id, node_id=node_id, action="probe", dry_run=True, limit=(qs.get("limit") or ["50"])[0], clean_sessions=False)
            return json_response(self, payload, status)
        if path == "/api/enterprise/task-center":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            limit = min(50, int((qs.get("limit") or ["12"])[0] or 12))
            return json_response(self, enterprise_task_center(org_id, limit=limit))
        if path == "/api/central/tasks":
            limit = min(500, int((qs.get("limit") or ["100"])[0] or 100))
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            q = (qs.get("q") or [""])[0].strip()
            status_filter = (qs.get("status") or ["all"])[0].strip() or "all"
            type_filter = (qs.get("type") or ["all"])[0].strip() or "all"
            failure_group_filter = (qs.get("failureGroup") or qs.get("group") or ["all"])[0].strip() or "all"
            user = current_user(self)
            include_all = bool(user and user.get("_authType") == "root-token" and (qs.get("all") or [""])[0] in ("1", "true", "yes"))
            with LOCK:
                tasks = list((STATE.get("tasks") or {}).values())
            if not include_all:
                tasks = [t for t in tasks if item_org_id(t) == org_id]
                tasks = filter_items_for_product_role(tasks, user, org_id)
            queue_items = load_queue(None if include_all else org_id)
            if not include_all:
                queue_items = filter_items_for_product_role(queue_items, user, org_id)
            queue_tasks = [queue_item_as_task(x) for x in queue_items if not (x.get("centralTaskId") or "")]
            tasks = sorted(list(tasks) + queue_tasks, key=lambda x: x.get("updatedAt") or x.get("createdAt", 0), reverse=True)
            total = len(tasks)
            q_task_ids, q_queue_ids = queue_task_search_hits(q, org_id=org_id, include_all=include_all) if q else (set(), [])
            base_filtered = [t for t in tasks if task_matches_filters(t, q="", status_filter=status_filter, type_filter=type_filter)]
            if failure_group_filter and failure_group_filter != "all":
                base_filtered = [t for t in base_filtered if queue_task_status((t or {}).get("status") or "") == "failed" and task_failure_category(t).get("key") == failure_group_filter]
            if q:
                q_lower = q.lower()
                tasks = [t for t in base_filtered if task_query_matches(t, q_lower) or (t.get("id") or "") in q_task_ids]
            else:
                tasks = base_filtered
            return json_response(self, {"ok": True, "tasks": [public_task(t) for t in tasks[:limit]], "scope": "all" if include_all else "org", "orgId": org_id, "total": total, "matched": len(tasks), "filters": {"q": q, "status": status_filter, "type": type_filter, "failureGroup": failure_group_filter, "queueMatches": len(q_queue_ids)}})
        if path == "/api/central/tasks/detail":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            user = current_user(self)
            include_all = bool(user and user.get("_authType") == "root-token" and (qs.get("all") or [""])[0] in ("1", "true", "yes"))
            task_id = (qs.get("id") or qs.get("taskId") or [""])[0]
            detail = task_detail(task_id, org_id, include_all=include_all) or queue_task_detail(task_id, org_id, include_all=include_all)
            if not detail:
                return json_response(self, {"ok": False, "error": "task_not_found"}, 404)
            if not include_all and not item_visible_to_user(detail.get("task") if isinstance(detail.get("task"), dict) else detail, user, org_id):
                return json_response(self, {"ok": False, "error": "task_not_found"}, 404)
            return json_response(self, detail)
        if path == "/api/central/tasks/recovery":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            limit = min(100, int((qs.get("limit") or ["50"])[0] or 50))
            return json_response(self, task_recovery_candidates(org_id, limit=limit))
        if path == "/api/enterprise/invites":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "admin"):
                return
            limit = min(100, int((qs.get("limit") or ["40"])[0] or 40))
            return json_response(self, list_enterprise_invites(org_id, limit=limit))
        if path == "/api/enterprise/security-audit":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            user = current_user(self)
            include_all = bool(user and user.get("_authType") == "root-token" and (qs.get("all") or [""])[0] in ("1", "true", "yes"))
            limit = min(200, int((qs.get("limit") or ["80"])[0] or 80))
            hours = min(24 * 90, int((qs.get("hours") or ["168"])[0] or 168))
            q = (qs.get("q") or [""])[0]
            category_filter = (qs.get("category") or [""])[0]
            return json_response(self, enterprise_security_audit(org_id, limit=limit, q=q, category=category_filter, hours=hours, include_all=include_all))
        if path == "/api/audit/logs":
            limit = min(500, int((qs.get("limit") or ["100"])[0] or 100))
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            user = current_user(self)
            root = bool(user and user.get("_authType") == "root-token")
            with LOCK:
                logs = sorted((STATE.get("auditLogs") or []), key=lambda x: x.get("ts", 0), reverse=True)
            if root and (qs.get("all") or [""])[0] in ("1", "true", "yes"):
                scoped = logs
            elif has_role(self, org_id, "auditor"):
                scoped = [l for l in logs if audit_log_org_id(l) == org_id or (not audit_log_org_id(l) and l.get("actorUserId") == (user or {}).get("id"))]
            else:
                scoped = [l for l in logs if l.get("actorUserId") == (user or {}).get("id")]
            return json_response(self, {"ok": True, "logs": scoped[:limit], "scope": "all" if root and (qs.get("all") or [""])[0] in ("1", "true", "yes") else ("org" if has_role(self, org_id, "auditor") else "self"), "orgId": org_id})
        if path == "/api/enterprise/summary":
            if not require_role(self, "*", "auditor"):
                return
            return json_response(self, enterprise_summary(current_user(self)))
        if path == "/api/enterprise/onboarding":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            return json_response(self, {"ok": True, "orgId": org_id, "role": user_role_for_org(current_user(self), org_id), "onboarding": org_onboarding(org_id)})
        if path == "/api/enterprise/delivery-acceptance":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            return json_response(self, enterprise_delivery_acceptance_report(org_id))
        if path == "/api/enterprise/delivery-package":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            return json_response(self, enterprise_delivery_package_report(org_id))
        if path == "/api/enterprise/delivery-risks":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            try:
                limit = min(100, max(1, int((qs.get("limit") or ["30"])[0] or 30)))
            except Exception:
                limit = 30
            return json_response(self, enterprise_delivery_risks(org_id, limit=limit))
        if path == "/api/enterprise/commercial-readiness":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            return json_response(self, enterprise_commercial_readiness(org_id))
        if path == "/api/enterprise/persistence-health":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            refresh = (qs.get("refresh") or [""])[0] in ("1", "true", "yes")
            return json_response(self, persistence_health(org_id, refresh=refresh))
        if path == "/api/enterprise/customer-startup":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            return json_response(self, enterprise_customer_startup(org_id))
        if path == "/api/enterprise/customer-startup/receipt":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            return json_response(self, enterprise_customer_startup_receipt(org_id))
        if path == "/api/enterprise/pilot-runbook":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            return json_response(self, enterprise_pilot_runbook(org_id))
        if path == "/api/enterprise/usage":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            return json_response(self, enterprise_usage(org_id))
        if path == "/api/enterprise/entitlements":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            return json_response(self, org_entitlements(org_id))
        if path == "/api/enterprise/preflight":
            org_id = request_org_id(self, qs=qs)
            scope = (qs.get("scope") or ["general"])[0]
            if not require_role(self, org_id, "member"):
                return
            return json_response(self, enterprise_preflight(org_id, scope=scope))
        if path == "/api/enterprise/preflight-attempts":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            limit = min(100, int((qs.get("limit") or ["30"])[0] or 30))
            window_sec = min(86400 * 30, max(3600, int((qs.get("windowSec") or ["86400"])[0] or 86400)))
            scope_filter = (qs.get("scope") or [""])[0]
            module_filter = (qs.get("module") or [""])[0]
            q_filter = (qs.get("q") or [""])[0]
            return json_response(self, list_preflight_attempts(org_id, limit=limit, window_sec=window_sec, scope=scope_filter, module=module_filter, q=q_filter))
        if path == "/api/enterprise/repair-metrics":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            limit = min(200, int((qs.get("limit") or ["50"])[0] or 50))
            state_filter = (qs.get("state") or [""])[0]
            owner_filter = (qs.get("owner") or [""])[0]
            severity_filter = (qs.get("severity") or [""])[0]
            q_filter = (qs.get("q") or [""])[0]
            return json_response(self, account_repair_metrics(org_id, state=state_filter, owner=owner_filter, severity=severity_filter, q=q_filter, limit=limit))
        if path == "/api/enterprise/health-snapshots":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            kind = (qs.get("kind") or ["checkpoint"])[0]
            limit = min(50, int((qs.get("limit") or ["20"])[0] or 20))
            return json_response(self, list_health_snapshots(org_id, kind=kind, limit=limit))
        if path == "/api/enterprise/support-links":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            limit = min(100, int((qs.get("limit") or ["50"])[0] or 50))
            q_filter = (qs.get("q") or [""])[0]
            include_archived = (qs.get("includeArchived") or qs.get("archived") or [""])[0] in ("1", "true", "yes")
            return json_response(self, list_support_links(org_id, limit=limit, q=q_filter, include_archived=include_archived))
        if path == "/api/enterprise/support-links/detail":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            link_id = (qs.get("id") or qs.get("support") or [""])[0]
            detail = support_link_detail(link_id, org_id)
            if not detail:
                return json_response(self, {"ok": False, "error": "support_link_not_found"}, 404)
            return json_response(self, detail)
        if path == "/api/finder/leads":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            limit = min(200, int((qs.get("limit") or ["80"])[0] or 80))
            q = (qs.get("q") or [""])[0]
            status_filter = (qs.get("status") or [""])[0]
            intent_filter = (qs.get("intent") or [""])[0]
            return json_response(self, list_finder_leads(org_id, q=q, status=status_filter, intent=intent_filter, limit=limit))
        if path == "/api/enterprise/action-items":
            limit = min(100, int((qs.get("limit") or ["50"])[0] or 50))
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            include_snoozed = (qs.get("includeSnoozed") or qs.get("snoozed") or [""])[0] in ("1", "true", "yes")
            kind = (qs.get("kind") or [""])[0].strip()
            severity = (qs.get("severity") or [""])[0].strip()
            q = (qs.get("q") or [""])[0].strip()
            return json_response(self, enterprise_action_items(org_id, limit=limit, include_snoozed=include_snoozed, kind=kind, severity=severity, q=q))
        if path == "/api/enterprise/notifications":
            limit = min(100, int((qs.get("limit") or ["30"])[0] or 30))
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            include_read = (qs.get("includeRead") or qs.get("read") or [""])[0] in ("1", "true", "yes")
            return json_response(self, enterprise_notifications(org_id, limit=limit, include_read=include_read, user=current_user(self)))
        if path == "/api/enterprise/notification-settings":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            return json_response(self, {"ok": True, "orgId": org_id, "role": user_role_for_org(current_user(self), org_id), "settings": notification_settings(org_id)})
        if path == "/api/enterprise/webhook-deliveries":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            limit = min(50, int((qs.get("limit") or ["10"])[0] or 10))
            return json_response(self, {"ok": True, "orgId": org_id, "delivery": webhook_delivery_status(org_id, limit=limit)})
        if path == "/api/accounts":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            user = current_user(self)
            want_all = (qs.get("all") or [""])[0] in ("1", "true", "yes")
            include_all = bool(want_all and is_platform_admin(self))
            return json_response(self, accounts_for_response(org_id, user=user, include_all=include_all))
        if path == "/api/accounts/detail":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            account_id = (qs.get("accountId") or qs.get("id") or [""])[0]
            detail = account_detail(account_id, org_id)
            if not detail:
                return json_response(self, {"ok": False, "error": "account_not_found"}, 404)
            if not item_visible_to_user(detail, current_user(self), org_id):
                return json_response(self, {"ok": False, "error": "account_not_found"}, 404)
            return json_response(self, detail)
        if path == "/api/accounts/authorization-status":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            account_id = (qs.get("accountId") or qs.get("id") or ["douyin-self"])[0]
            node_id = (qs.get("nodeId") or qs.get("preferredNode") or [""])[0]
            session_ref = (qs.get("sessionRef") or qs.get("sessionId") or [""])[0]
            platform = (qs.get("platform") or qs.get("pf") or [""])[0]
            return json_response(self, account_authorization_status(org_id, account_id=account_id, node_id=node_id, session_ref=session_ref, platform=platform))
        if path == "/api/accounts/authorization-watch":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            account_id = (qs.get("accountId") or qs.get("id") or ["douyin-self"])[0]
            node_id = (qs.get("nodeId") or qs.get("preferredNode") or [""])[0]
            session_ref = (qs.get("sessionRef") or qs.get("sessionId") or [""])[0]
            platform = (qs.get("platform") or qs.get("pf") or [""])[0]
            return json_response(self, account_authorization_watch(org_id, account_id=account_id, node_id=node_id, session_ref=session_ref, platform=platform))
        if path == "/api/accounts/authorization-summary":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            return json_response(self, account_authorization_summary(org_id))
        if path == "/api/accounts/auth-handoff":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            try:
                limit = min(100, max(1, int((qs.get("limit") or ["30"])[0] or 30)))
            except Exception:
                limit = 30
            return json_response(self, account_authorization_handoff(org_id, limit=limit))
        if path == "/api/accounts/auth-diagnosis":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            account_id = (qs.get("accountId") or qs.get("id") or [""])[0]
            node_id = (qs.get("nodeId") or qs.get("preferredNode") or [""])[0]
            return json_response(self, auth_diagnosis(org_id, account_id=account_id, node_id=node_id))
        if path == "/api/cloud-login/resume":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            account_id = (qs.get("accountId") or qs.get("centralAccountId") or [""])[0]
            node_id = (qs.get("nodeId") or qs.get("preferredNode") or [""])[0]
            allow_stale = (qs.get("allowStale") or ["1"])[0] not in ("0", "false", "no")
            session_ref = (qs.get("sessionRef") or qs.get("id") or qs.get("sessionId") or [""])[0]
            payload = cloud_login_resume(org_id, account_id=account_id, node_id=node_id, allow_stale=allow_stale, session_ref=session_ref)
            return json_response(self, payload)
        if path == "/api/cloud-login/flow":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            account_id = (qs.get("accountId") or qs.get("centralAccountId") or ["douyin-self"])[0]
            node_id = (qs.get("nodeId") or qs.get("preferredNode") or [""])[0]
            session_ref = (qs.get("sessionRef") or qs.get("id") or qs.get("sessionId") or [""])[0]
            platform = (qs.get("platform") or qs.get("pf") or [""])[0]
            return json_response(self, cloud_login_flow_state(org_id, account_id=account_id, node_id=node_id, session_ref=session_ref, platform=platform))
        if path == "/api/cloud-login/progress":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            limit = min(100, int((qs.get("limit") or ["20"])[0] or 20))
            account_id = (qs.get("accountId") or qs.get("centralAccountId") or [""])[0]
            node_id = (qs.get("nodeId") or qs.get("preferredNode") or [""])[0]
            fresh_sec = (qs.get("freshSec") or ["86400"])[0]
            since = (qs.get("since") or ["0"])[0]
            return json_response(self, list_cloud_login_progress(org_id, limit=limit, account_id=account_id, node_id=node_id, fresh_sec=fresh_sec, since=since))
        if path == "/api/cloud-login/session-watchdog":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            limit = min(100, int((qs.get("limit") or ["50"])[0] or 50))
            return json_response(self, cloud_login_session_watchdog(org_id, limit=limit))
        if path == "/api/cloud-login/sessions":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            limit = min(100, int((qs.get("limit") or ["50"])[0] or 50))
            return json_response(self, cloud_login_sessions(org_id, limit=limit))
        if path == "/api/cloud-login/session-audit":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            limit = min(200, int((qs.get("limit") or ["100"])[0] or 100))
            status_filter = (qs.get("status") or [""])[0]
            q_filter = (qs.get("q") or [""])[0]
            return json_response(self, cloud_login_session_audit(org_id, limit=limit, status=status_filter, q=q_filter))
        if path == "/api/cloud-login/timeline":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "member"):
                return
            limit = min(120, int((qs.get("limit") or ["80"])[0] or 80))
            account_id = (qs.get("accountId") or qs.get("centralAccountId") or [""])[0]
            node_id = (qs.get("nodeId") or qs.get("preferredNode") or [""])[0]
            session_ref = (qs.get("sessionRef") or qs.get("id") or qs.get("sessionId") or [""])[0]
            return json_response(self, cloud_login_timeline(org_id, account_id=account_id, node_id=node_id, session_ref=session_ref, limit=limit))
        if path == "/api/library":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            rows = filter_items_for_product_role(load_library(org_id), current_user(self), org_id)
            return json_response(self, [public_material(m) for m in rows])
        if path == "/api/kb/list":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            rows = filter_items_for_product_role(load_kb(org_id), current_user(self), org_id)
            return json_response(self, [public_kb_doc(d) for d in rows])
        if path == "/api/publish/settings":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            return json_response(self, load_settings(org_id))
        if path == "/api/publish/queue/watchdog":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            try:
                limit = min(200, max(1, int((qs.get("limit") or ["100"])[0] or 100)))
            except Exception:
                limit = 100
            return json_response(self, publish_queue_watchdog(org_id, limit=limit))
        if path == "/api/publish/queue/recovery-advice":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            try:
                limit = min(100, max(1, int((qs.get("limit") or ["50"])[0] or 50)))
            except Exception:
                limit = 50
            return json_response(self, publish_queue_recovery_advice(org_id, limit=limit))
        if path == "/api/publish/queue/detail":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            qid = (qs.get("id") or qs.get("queueId") or [""])[0]
            detail = queue_detail(qid, org_id)
            if not detail:
                return json_response(self, {"ok": False, "error": "queue_item_not_found"}, 404)
            return json_response(self, detail)
        if path == "/api/publish/queue/auth-handoff":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            try:
                limit = min(100, max(1, int((qs.get("limit") or ["50"])[0] or 50)))
            except Exception:
                limit = 50
            return json_response(self, publish_queue_auth_handoff(org_id, limit=limit))
        if path == "/api/publish/queue":
            org_id = request_org_id(self, qs=qs)
            if not require_role(self, org_id, "auditor"):
                return
            rows = filter_items_for_product_role(load_queue(org_id), current_user(self), org_id)
            return json_response(self, [public_queue_item(q) for q in rows])
        return json_response(self, {"ok": False, "error": "not_found", "path": path}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path == "/lk888" or path.startswith("/lk888/"):
            return lk888_proxy(self, "POST", parsed)
        if path.startswith("/api/cloud-login/"):
            return json_response(self, {"ok": False, "error": "cloud_login_removed", "message": "云端登录已下线，请在本机客户端用本地浏览器登录"}, 410)

        try:
            if path in ("/api/library/upload", "/api/kb/upload"):
                if not require_user(self):
                    return
                return self.handle_multipart(path)

            body = read_body(self)

            if path == "/api/enterprise/invites/verify":
                payload, status = enterprise_invite_verify(body.get("token"))
                invite = payload.get("invite") if isinstance(payload.get("invite"), dict) else {}
                organization = payload.get("organization") if isinstance(payload.get("organization"), dict) else {}
                add_audit(self, "enterprise.invite.verify", path, ok=bool(payload.get("ok")), meta={
                    "inviteId": invite.get("id"),
                    "orgId": organization.get("id") or invite.get("orgId"),
                    "status": status,
                    "error": payload.get("error"),
                })
                return json_response(self, payload, status)

            if path == "/api/shared-assets/add":
                return shared_assets_add(self, body)

            if path == "/api/auth/login":
                legal_consent, legal_error = validate_legal_consent(body)
                if legal_error:
                    return json_response(self, legal_consent_error_response(legal_error), 428)
                identifier = (body.get("identifier") or body.get("phone") or body.get("username") or body.get("email") or "").strip()
                password = body.get("password") or body.get("token") or ""
                code = str(body.get("code") or "").strip()
                user = find_login_user(identifier)
                if not user or user.get("status", "active") != "active" or not verify_user_password(user, password):
                    add_audit(self, "auth.login", path, ok=False, meta={"identifier": identifier})
                    return json_response(self, {"ok": False, "error": "invalid_credentials"}, 401)
                # 手机号 + 密码登录需要短信验证码;用户名/账号名 + 密码登录不需要验证码。
                phone2fa = str(user.get("phone") or "").strip()
                if login_requires_phone_code(identifier, user):
                    if not code:
                        add_audit(self, "auth.login", path, ok=False, meta={"userId": user.get("id"), "stage": "need_code"})
                        return json_response(self, {"ok": False, "error": "need_phone_code",
                                                    "need2fa": True, "phone": phone2fa}, 401)
                    if not verify_phone_code(phone2fa, code, expected_scene="login"):
                        add_audit(self, "auth.login", path, ok=False, meta={"userId": user.get("id"), "stage": "bad_code"})
                        return json_response(self, {"ok": False, "error": "验证码错误或已过期"}, 400)
                record_legal_consent(self, user, legal_consent)
                session = create_user_session(user, {
                    "ip": self.client_address[0] if getattr(self, "client_address", None) else "",
                    "userAgent": self.headers.get("User-Agent") or "",
                })
                add_audit(self, "auth.login", path, ok=True, meta={"userId": user.get("id")})
                ctx = auth_context_for_user(user)
                return json_response(self, dict(ctx, **{
                    "ok": True,
                    "token": session["token"],
                    "expiresAt": session["expiresAt"],
                    "user": public_user(user),
                }))
            if path == "/api/auth/send-code":
                phone = str(body.get("phone") or "").strip()
                scene = str(body.get("scene") or "login").lower()
                if not (phone.isdigit() and len(phone) == 11):
                    return json_response(self, {"ok": False, "error": "手机号格式不正确"}, 400)
                if scene not in ("login", "register"):
                    scene = "login"
                ip = self.client_address[0] if getattr(self, "client_address", None) else ""
                if not _send_ip_allowed(ip):
                    return json_response(self, {"ok": False, "error": "操作过于频繁,请稍后再试"}, 429)
                code, cerr = gen_phone_code(phone, scene)
                if cerr:
                    return json_response(self, {"ok": False, "error": cerr}, 429)
                if SMS_DEV_MODE:
                    add_audit(self, "auth.send_code", path, ok=True, meta={"phone": phone, "dev": True})
                    return json_response(self, {"ok": True, "message": "开发模式:验证码 %s" % code,
                                                "devCode": code, "expire": _PHONE_CODE_TTL})
                tmpl = SMS_CFG["tmpl_register"] if scene == "register" else SMS_CFG["tmpl_login"]
                ok, msg = aliyun_send_sms(phone, tmpl, {"code": code})
                add_audit(self, "auth.send_code", path, ok=ok, meta={"phone": phone})
                if not ok:
                    _PHONE_CODES.pop(phone, None)  # 发送失败清掉,允许立即重发
                    return json_response(self, {"ok": False, "error": msg}, 502)
                return json_response(self, {"ok": True, "message": "验证码已发送", "expire": _PHONE_CODE_TTL})
            if path == "/api/auth/login/phone":
                # 纯手机验证码登录(旧客户端 + 历史无密码账号)。已设密码的账号**禁止**走此路径,
                # 必须账号密码 + 2FA(/api/auth/login),否则等于绕过密码 —— 关掉这个 2FA 后门。
                legal_consent, legal_error = validate_legal_consent(body)
                if legal_error:
                    return json_response(self, legal_consent_error_response(legal_error), 428)
                phone = str(body.get("phone") or "").strip()
                code = str(body.get("code") or "").strip()
                if not verify_phone_code(phone, code, expected_scene="login"):
                    add_audit(self, "auth.login.phone", path, ok=False, meta={"phone": phone})
                    return json_response(self, {"ok": False, "error": "验证码错误或已过期"}, 400)
                user = get_or_create_phone_user(phone)
                if user.get("passwordHash"):
                    add_audit(self, "auth.login.phone", path, ok=False,
                              meta={"userId": user.get("id"), "reason": "has_password"})
                    return json_response(self, {"ok": False,
                                                "error": "该账号已设密码,请用账号密码登录"}, 403)
                record_legal_consent(self, user, legal_consent)
                session = create_user_session(user, {
                    "ip": self.client_address[0] if getattr(self, "client_address", None) else "",
                    "userAgent": self.headers.get("User-Agent") or "",
                })
                add_audit(self, "auth.login.phone", path, ok=True, meta={"userId": user.get("id")})
                ctx = auth_context_for_user(user)
                return json_response(self, dict(ctx, **{
                    "ok": True, "token": session["token"], "expiresAt": session["expiresAt"],
                    "user": public_user(user),
                    "balance": get_balance(user.get("id")),
                }))
            if path == "/api/auth/register":
                legal_consent, legal_error = validate_legal_consent(body)
                if legal_error:
                    return json_response(self, legal_consent_error_response(legal_error), 428)
                phone = str(body.get("phone") or "").strip()
                code = str(body.get("code") or "").strip()
                password = body.get("password") or ""
                name = str(body.get("name") or "").strip()
                if not (phone.isdigit() and len(phone) == 11):
                    return json_response(self, {"ok": False, "error": "手机号格式不对"}, 400)
                if len(password) < 6:
                    return json_response(self, {"ok": False, "error": "密码至少 6 位"}, 400)
                if not verify_phone_code(phone, code, expected_scene="register"):
                    return json_response(self, {"ok": False, "error": "验证码错误或已过期"}, 400)
                if maindb_on():
                    # ===== 漫剧模式:注册直接写主库 users(与漫剧共用同一账号体系)=====
                    try:
                        existing = maindb.get_user_by_phone(phone)
                    except Exception:
                        existing = None
                    if existing and existing.get("password_hash"):
                        add_audit(self, "auth.register", path, ok=False,
                                  meta={"phone": phone, "reason": "already_registered", "mdb": True})
                        return json_response(self, {"ok": False, "error": "该手机号已注册,请直接登录"}, 409)
                    try:
                        if existing:  # 历史无密码账号:注册=设置首个密码(claim),不新建、不重复赠算力
                            uid = existing.get("id")
                            maindb.set_password(uid, password)
                        else:
                            row = maindb.create_phone_user(phone, password=password, signup_bonus=MAINDB_SIGNUP_BONUS)
                            uid = (row or {}).get("id")
                        if name and uid:
                            maindb.set_username(uid, name[:40])
                    except Exception as _e:
                        add_audit(self, "auth.register", path, ok=False, meta={"phone": phone, "err": str(_e)[:80]})
                        return json_response(self, {"ok": False, "error": "注册失败:" + str(_e)[:80]}, 500)
                    user = shape_mdb_user(maindb.get_user_by_id(uid), "session") if uid else None
                    if not user:
                        return json_response(self, {"ok": False, "error": "注册失败,请重试"}, 500)
                    record_legal_consent(self, user, legal_consent)
                    session = create_user_session(user, {
                        "ip": self.client_address[0] if getattr(self, "client_address", None) else "",
                        "userAgent": self.headers.get("User-Agent") or "",
                    })
                    add_audit(self, "auth.register", path, ok=True, meta={"userId": user.get("id"), "mdb": True})
                    ctx = auth_context_for_user(user)
                    return json_response(self, dict(ctx, **{
                        "ok": True, "token": session["token"], "expiresAt": session["expiresAt"],
                        "user": public_user(user),
                        "balance": get_balance(user.get("id")),
                    }))
                # 检查-建号-设密全程持锁(RLock 可重入),原子:
                #  ①已注册手机一律拒绝(不静默改密→防"凭验证码接管已有账号");
                #  ②并发同号只会成功一次(第二个进来时已存在→拒),不产生重复用户/企业。
                with LOCK:
                    existing = next((x for x in (STATE.get("users") or [])
                                     if str(x.get("phone") or "").strip() == phone), None)
                    if existing and existing.get("passwordHash"):
                        # 已设密码的账号禁止重复注册/静默改密(防"凭验证码接管")
                        add_audit(self, "auth.register", path, ok=False,
                                  meta={"phone": phone, "reason": "already_registered"})
                        return json_response(self, {"ok": False,
                                                    "error": "该手机号已注册,请直接登录"}, 409)
                    if existing:
                        # 历史无密码账号(旧的纯验证码用户):注册=设置首个密码(claim),
                        # 不新建、不重复赠豆;无密码可设=与验证码登录同等信任,安全。
                        u = existing
                    else:
                        created = create_phone_user(phone)  # RLock 可重入
                        u = next((x for x in STATE.get("users") or []
                                  if x.get("id") == created.get("id")), None)
                    set_user_password(u, password)
                    if name:
                        u["name"] = name[:40]
                    u["updatedAt"] = now()
                    persist()
                    user = dict(u)
                record_legal_consent(self, user, legal_consent)
                session = create_user_session(user, {
                    "ip": self.client_address[0] if getattr(self, "client_address", None) else "",
                    "userAgent": self.headers.get("User-Agent") or "",
                })
                add_audit(self, "auth.register", path, ok=True, meta={"userId": user.get("id")})
                ctx = auth_context_for_user(user)
                return json_response(self, dict(ctx, **{
                    "ok": True, "token": session["token"], "expiresAt": session["expiresAt"],
                    "user": public_user(user),
                    "balance": get_balance(user.get("id")),
                }))
            if path == "/api/auth/logout":
                token = extract_user_token(self) or (body.get("token") or "")
                ok = revoke_user_session(token)
                add_audit(self, "auth.logout", path, ok=True, meta={"revoked": ok})
                return json_response(self, {"ok": True, "revoked": ok})
            if path == "/api/auth/refresh":
                token = extract_user_token(self) or (body.get("token") or "")
                user = current_user(self)
                if not user:
                    return json_response(self, {"ok": False, "error": "not_authenticated"}, 401)
                if not user_has_current_legal_consent(user):
                    return json_response(self, legal_consent_error_response("legal_consent_required"), 428)
                session = refresh_user_session(token) if user.get("_authType") == "session" else None
                add_audit(self, "auth.refresh", path, ok=True, meta={"userId": user.get("id"), "authType": user.get("_authType")})
                exp = float((session or {}).get("expiresAt") or 0)
                ctx = auth_context_for_user(user, auth_type=user.get("_authType"))
                return json_response(self, dict(ctx, **{
                    "ok": True,
                    "token": token if user.get("_authType") == "session" else "",
                    "expiresAt": (session or {}).get("expiresAt"),
                    "expiresInSec": max(0, int(exp - now())) if exp else 0,
                    "sessionTtlSec": int(SESSION_TTL_SEC),
                    "refreshed": bool(session),
                    "user": public_user(user),
                }))

            if path == "/api/auth/change-password":
                user = current_user(self)
                payload, status = change_authenticated_user_password(
                    user,
                    body.get("currentPassword") or body.get("oldPassword") or "",
                    body.get("newPassword") or body.get("password") or "",
                    (user or {}).get("_sessionId") or "",
                )
                add_audit(self, "auth.change_password", path, ok=bool(payload.get("ok")), meta={"userId": (user or {}).get("id"), "revokedSessions": payload.get("revokedSessions"), "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/auth/sessions/revoke-others":
                user = current_user(self)
                payload, status = revoke_authenticated_user_other_sessions(user)
                add_audit(self, "auth.sessions.revoke_others", path, ok=bool(payload.get("ok")), meta={"userId": (user or {}).get("id"), "revokedSessions": payload.get("revokedSessions"), "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/invites/accept":
                payload, status = accept_enterprise_invite(body, handler=self)
                add_audit(self, "enterprise.invite.accept", path, ok=bool(payload.get("ok")), meta={"orgId": payload.get("orgId"), "userId": ((payload.get("user") or {}).get("id")), "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/node/register":
                if not node_authorized(self):
                    return json_response(self, {"ok": False, "error": "node_secret_invalid"}, 401)
                node_id = body.get("nodeId") or uuid.uuid4().hex[:12]
                org_id = request_org_id(self, body)
                accounts = body.get("accounts") or []
                for a in accounts:
                    if isinstance(a, dict) and not a.get("orgId"):
                        a["orgId"] = org_id
                node = {
                    "id": node_id,
                    "orgId": org_id,
                    "name": body.get("name") or node_id,
                    "region": body.get("region") or "",
                    "tags": body.get("tags") or [],
                    "version": body.get("version") or "",
                    "localApi": body.get("localApi") or "",
                    "lastSeen": now(),
                    "registeredAt": now(),
                    "cookieReady": bool(body.get("cookieReady")),
                    "cookieCount": body.get("cookieCount", 0),
                    "accounts": accounts,
                    "busy": False,
                    "stats": {},
                    "risk": {},
                }
                with LOCK:
                    old = (STATE.setdefault("nodes", {}).get(node_id) or {})
                    old.update(node)
                    STATE["nodes"][node_id] = old
                    sync_node_accounts_locked(old)
                add_event("node_registered", {"nodeId": node_id})
                persist()
                return json_response(self, {"ok": True, "nodeId": node_id, "pollIntervalSec": 0.5})

            if path == "/api/node/heartbeat":
                if not node_authorized(self):
                    return json_response(self, {"ok": False, "error": "node_secret_invalid"}, 401)
                node_id = body.get("nodeId") or ""
                if not node_id:
                    return json_response(self, {"ok": False, "error": "missing_node_id"}, 400)
                org_id = request_org_id(self, body)
                accounts = body.get("accounts")
                if accounts:
                    for a in accounts:
                        if isinstance(a, dict) and not a.get("orgId"):
                            a["orgId"] = org_id
                with LOCK:
                    node = STATE.setdefault("nodes", {}).setdefault(node_id, {"id": node_id})
                    node.update({
                        "lastSeen": now(),
                        "orgId": org_id or item_org_id(node),
                        "name": body.get("name") or node.get("name") or node_id,
                        "region": body.get("region") or node.get("region") or "",
                        "tags": body.get("tags") or node.get("tags") or [],
                        "version": body.get("version") or node.get("version") or "",
                        "localApi": body.get("localApi") or node.get("localApi") or "",
                        "cookieReady": bool(body.get("cookieReady")),
                        "cookieCount": body.get("cookieCount", 0),
                        "accounts": accounts or node.get("accounts") or [],
                        "busy": bool(body.get("busy")),
                        "stats": body.get("stats") or node.get("stats") or {},
                        "risk": body.get("risk") or node.get("risk") or {},
                    })
                    sync_node_accounts_locked(node)
                persist()
                return json_response(self, {"ok": True})

            if path == "/api/node/tasks/poll":
                if not node_authorized(self):
                    return json_response(self, {"ok": False, "error": "node_secret_invalid"}, 401)
                node_id = body.get("nodeId") or ""
                recover_stale_tasks(None, dry_run=False, limit=100)
                cap = node_capacity_snapshot(node_id)
                if cap.get("paused") or int(cap.get("running") or 0) >= int(cap.get("maxConcurrency") or 1) or int(cap.get("cooldownRemainingSec") or 0) > 0:
                    with LOCK:
                        if node_id in STATE.get("nodes", {}):
                            STATE["nodes"][node_id]["lastSeen"] = now()
                            STATE["nodes"][node_id]["busy"] = int(cap.get("running") or 0) > 0
                    return json_response(self, {"ok": True, "task": None, "reason": cap.get("reason"), "capacity": cap})
                with LOCK:
                    task = None
                    def _task_sort_key(x):
                        return (
                            0 if x.get("path") in INTERACTIVE_TASK_PATHS else 1,
                            2 if x.get("path") == "/api/cloud-login/screenshot" else 1,
                            x.get("createdAt", 0),
                        )
                    for t in sorted((STATE.get("tasks") or {}).values(), key=_task_sort_key):
                        if t.get("status") == "queued" and (not t.get("nodeId") or t.get("nodeId") == node_id):
                            t["status"] = "running"
                            t["nodeId"] = node_id
                            t["startedAt"] = now()
                            t["updatedAt"] = now()
                            task = dict(t)
                            break
                    if node_id in STATE.get("nodes", {}):
                        STATE["nodes"][node_id]["lastSeen"] = now()
                        STATE["nodes"][node_id]["busy"] = bool(task)
                if task:
                    add_event("task_started", {"taskId": task["id"], "nodeId": node_id})
                    persist()
                    return json_response(self, {"ok": True, "task": task})
                return json_response(self, {"ok": True, "task": None})

            if path == "/api/node/tasks/result":
                if not node_authorized(self):
                    return json_response(self, {"ok": False, "error": "node_secret_invalid"}, 401)
                task_id = body.get("taskId") or ""
                node_id = body.get("nodeId") or ""
                with LOCK:
                    task = (STATE.get("tasks") or {}).get(task_id)
                    if not task:
                        return json_response(self, {"ok": False, "error": "task_not_found"}, 404)
                    task["status"] = "done" if body.get("ok", True) else "failed"
                    task["result"] = body.get("result")
                    task["error"] = body.get("error")
                    task["finishedAt"] = now()
                    task["updatedAt"] = now()
                    if node_id in STATE.get("nodes", {}):
                        STATE["nodes"][node_id]["lastSeen"] = now()
                        STATE["nodes"][node_id]["lastFinishedAt"] = now()
                        STATE["nodes"][node_id]["busy"] = False
                add_event("task_finished", {"taskId": task_id, "nodeId": node_id, "ok": body.get("ok", True)})
                persist()
                return json_response(self, {"ok": True})

            if not require_user(self):
                return

            if path == "/api/auth/bind-phone":
                u = current_user(self)
                if not u:
                    return json_response(self, {"ok": False, "error": "not_authenticated"}, 401)
                phone = str(body.get("phone") or "").strip()
                code = str(body.get("code") or "").strip()
                if not verify_phone_code(phone, code):
                    return json_response(self, {"ok": False, "error": "验证码错误或已过期"}, 400)
                other = find_user_by_phone(phone)
                if other and other.get("id") != u.get("id"):
                    return json_response(self, {"ok": False, "error": "该手机号已被其他账号绑定"}, 409)
                with LOCK:
                    for x in STATE.get("users") or []:
                        if x.get("id") == u.get("id"):
                            x["phone"] = phone
                            x["phoneVerified"] = True
                            x["updatedAt"] = now()
                    persist()
                add_audit(self, "auth.bind_phone", path, ok=True, meta={"userId": u.get("id")})
                return json_response(self, {"ok": True, "phone": phone})
            if path == "/api/billing/charge":
                u = current_user(self)
                if not u:
                    return json_response(self, {"ok": False, "error": "not_authenticated"}, 401)
                ok, bal, err = charge_capability_user(
                    u.get("id"),
                    body.get("capability") or body.get("reason") or "",
                    body.get("amount"),
                    body.get("ref") or "",
                )
                bal_out = None if bal == float("inf") else bal
                return json_response(self, {"ok": ok, "balance": bal_out, "error": err}, 200 if ok else 402)
            if path == "/api/billing/refund":
                u = current_user(self)
                if not u:
                    return json_response(self, {"ok": False, "error": "not_authenticated"}, 401)
                ok, bal, amt, err = refund_user_by_ref(u.get("id"), body.get("ref") or "")
                bal_out = None if bal == float("inf") else bal
                add_audit(self, "billing.refund", path, ok=ok, meta={"ref": body.get("ref"), "amount": amt})
                return json_response(self, {"ok": ok, "balance": bal_out, "refunded": amt, "error": err}, 200 if ok else 400)
            if path == "/api/billing/topup":
                if not require_platform_admin(self):
                    return
                target = str(body.get("userId") or "").strip()
                ok, bal, err = topup_user(target, body.get("amount"),
                                          body.get("reason") or "管理员充值", body.get("ref") or "")
                add_audit(self, "billing.topup", path, ok=ok, meta={"target": target, "amount": body.get("amount")})
                return json_response(self, {"ok": ok, "balance": bal, "error": err}, 200 if ok else 400)
            if path == "/api/billing/redeem":
                if not require_platform_admin(self):
                    return
                u = current_user(self)
                if not u:
                    return json_response(self, {"ok": False, "error": "not_authenticated"}, 401)
                ok, bal, amt, err = redeem_code(u.get("id"), body.get("code") or "")
                bal_out = None if bal == float("inf") else bal
                add_audit(self, "billing.redeem", path, ok=ok, meta={"amount": amt})
                return json_response(self, {"ok": ok, "balance": bal_out, "amount": amt, "error": err}, 200 if ok else 400)
            if path == "/api/billing/recharge/create":
                if not require_platform_admin(self):
                    return
                u = current_user(self)
                if not u:
                    return json_response(self, {"ok": False, "error": "not_authenticated"}, 401)
                pkg_id = str(body.get("packageId") or "").strip()
                if pkg_id:
                    pk = next((p for p in RECHARGE_PACKAGES if p["id"] == pkg_id), None)
                    if not pk:
                        return json_response(self, {"ok": False, "error": "档位不存在"}, 400)
                    amount_fen = int(pk["yuan"]) * 100
                else:
                    try:
                        amount_fen = int(round(float(body.get("amountYuan") or 0) * 100)) if body.get("amountYuan") is not None else int(body.get("amountFen") or 0)
                    except Exception:
                        return json_response(self, {"ok": False, "error": "金额无效"}, 400)
                ok, order, err = create_recharge_order(u.get("id"), amount_fen)
                add_audit(self, "billing.recharge.create", path, ok=ok,
                          meta={"userId": u.get("id"), "amountFen": amount_fen, "error": err})
                if not ok:
                    return json_response(self, {"ok": False, "error": err}, 400)
                return json_response(self, {"ok": True, "orderNo": order["orderNo"], "codeUrl": order["codeUrl"],
                                            "amountFen": order["amountFen"], "yundou": order["yundou"]})
            if path == "/api/admin/redeem-codes/generate":
                if not require_platform_admin(self):
                    return
                ok, codes, err = gen_redeem_codes(body.get("count"), body.get("amount"),
                                                  body.get("note") or "", (current_user(self) or {}).get("id") or "")
                add_audit(self, "billing.gen_codes", path, ok=ok,
                          meta={"count": body.get("count"), "amount": body.get("amount")})
                return json_response(self, {"ok": ok, "codes": codes, "error": err}, 200 if ok else 400)
            if path == "/api/admin/redeem-codes/void":
                if not require_platform_admin(self):
                    return
                ok, err = void_redeem_code(body.get("code") or "")
                add_audit(self, "billing.void_code", path, ok=ok, meta={"code": body.get("code")})
                return json_response(self, {"ok": ok, "error": err}, 200 if ok else 400)
            if path == "/api/admin/release":
                if not require_platform_admin(self):
                    return
                with LOCK:
                    STATE["releaseConfig"] = {
                        "latestVersion": str(body.get("latestVersion") or "").strip(),
                        "downloadUrl": str(body.get("downloadUrl") or "").strip(),
                        "notice": str(body.get("notice") or "").strip(),
                        "force": bool(body.get("force")),
                        "updatedAt": now(),
                    }
                    persist()
                add_audit(self, "admin.release", path, ok=True, meta={"latestVersion": body.get("latestVersion")})
                return json_response(self, {"ok": True})

            if path == "/api/local-browser/pair/create":
                payload, status = local_browser_pair_create(self, body)
                if payload is None:
                    return
                return json_response(self, payload, status)
            if path == "/api/local-browser/pair/redeem":
                payload, status = local_browser_pair_redeem(self, body)
                return json_response(self, payload, status)
            if path == "/api/local-browser/register":
                payload, status = local_browser_register(self, body)
                if payload is None:
                    return
                return json_response(self, payload, status)
            if path == "/api/local-browser/task":
                payload, status = local_browser_create_task(self, body)
                if payload is None:
                    return
                return json_response(self, payload, status)
            if path == "/api/local-browser/poll":
                payload, status = local_browser_poll(self, body)
                if payload is None:
                    return
                return json_response(self, payload, status)
            if path == "/api/local-browser/result":
                payload, status = local_browser_result(self, body)
                if payload is None:
                    return
                return json_response(self, payload, status)

            if path in ("/api/accounts/remove", "/api/accounts/delete"):
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "auditor"):
                    return
                account_id = (body.get("id") or body.get("accountId") or body.get("account") or "").strip()
                payload, status = delete_account(org_id, account_id)
                add_audit(self, "account.remove", path, ok=bool(payload.get("ok")),
                          meta={"orgId": org_id, "accountId": account_id, "removed": payload.get("removed", 0)})
                return json_response(self, payload, status)

            if path == "/api/cloud-login/resume" or (path == "/api/cloud-login/current" and not (body.get("sessionId") or "").strip()):
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                session_ref = body.get("sessionRef") or body.get("id") or (body.get("sessionId") if path == "/api/cloud-login/resume" else "") or ""
                payload = cloud_login_resume(org_id, account_id=body.get("centralAccountId") or body.get("accountId") or "", node_id=body.get("preferredNode") or body.get("nodeId") or "", allow_stale=body.get("allowStale", True) is not False, session_ref=session_ref)
                add_audit(self, "cloud_login.session.resume", path, ok=bool(payload.get("hasSession")), meta={"orgId": org_id, "accountId": body.get("centralAccountId") or body.get("accountId"), "nodeId": body.get("preferredNode") or body.get("nodeId"), "sessionRef": short_session_id(session_ref), "hasSession": payload.get("hasSession"), "status": payload.get("status"), "source": payload.get("resumeSource")})
                return json_response(self, payload)

            if path == "/api/cloud-login/finish":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                payload, status = finish_cloud_login_session(org_id, body, user=current_user(self))
                add_audit(self, "cloud_login.finish", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "accountId": body.get("centralAccountId") or body.get("accountId"), "nodeId": body.get("preferredNode") or body.get("nodeId"), "status": status, "error": payload.get("error"), "loggedIn": payload.get("loggedIn")})
                return json_response(self, payload, status)

            if path == "/api/cloud-login/flow":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                return json_response(self, cloud_login_flow_state(org_id, account_id=body.get("centralAccountId") or body.get("accountId") or "douyin-self", node_id=body.get("preferredNode") or body.get("nodeId") or "", session_ref=body.get("sessionRef") or body.get("id") or body.get("sessionId") or "", platform=body.get("platform") or body.get("pf") or ""))

            if path == "/api/enterprise/health-snapshots":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "auditor"):
                    return
                payload, status = save_health_snapshot(org_id, body, user=current_user(self))
                add_audit(self, "enterprise.health_snapshot.save", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "kind": body.get("kind"), "rows": len(body.get("rows") or []), "snapshotId": (payload.get("snapshot") or {}).get("id"), "error": payload.get("error")})
                return json_response(self, payload, status)
            if path == "/api/enterprise/support-links":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "auditor"):
                    return
                payload, status = create_support_link(org_id, body, user=current_user(self))
                add_audit(self, "enterprise.support_link.create", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "kind": body.get("kind"), "refId": body.get("refId") or body.get("taskId") or body.get("queueId"), "receipt": body.get("receipt"), "supportId": (payload.get("link") or {}).get("id"), "error": payload.get("error")})
                return json_response(self, payload, status)
            if path == "/api/enterprise/support-links/update":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "auditor"):
                    return
                payload, status = update_support_link(org_id, body, user=current_user(self))
                add_audit(self, "enterprise.support_link.update", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "supportId": body.get("id") or body.get("supportId"), "archived": body.get("archived"), "noteChanged": "note" in body, "error": payload.get("error")})
                return json_response(self, payload, status)
            if path == "/api/enterprise/support-links/bulk":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "auditor"):
                    return
                payload, status = bulk_update_support_links(org_id, body, user=current_user(self))
                add_audit(self, "enterprise.support_link.bulk", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "operation": body.get("operation"), "processed": payload.get("processed"), "skipped": payload.get("skipped"), "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/action-items/snooze":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                item_id = (body.get("id") or body.get("itemId") or "").strip()
                meta = {
                    "kind": body.get("kind") or "",
                    "severity": body.get("severity") or "",
                    "title": body.get("title") or "",
                    "ref": body.get("ref") if isinstance(body.get("ref"), dict) else {},
                    "action": body.get("action") if isinstance(body.get("action"), dict) else {},
                }
                payload, status = snooze_action_item(org_id, item_id, body.get("hours") or 24, meta=meta)
                add_audit(self, "enterprise.action.snooze", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "itemId": item_id, "hours": body.get("hours") or 24, "error": payload.get("error")})
                return json_response(self, payload, status)
            if path == "/api/enterprise/action-items/restore":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                item_id = (body.get("id") or body.get("itemId") or "").strip()
                payload, status = restore_action_item(org_id, item_id)
                add_audit(self, "enterprise.action.restore", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "itemId": item_id, "restored": payload.get("restored"), "error": payload.get("error")})
                return json_response(self, payload, status)
            if path == "/api/enterprise/action-items/clear-resource":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                account_id = (body.get("accountId") or body.get("centralAccountId") or "").strip()
                node_id = (body.get("nodeId") or body.get("preferredNode") or "").strip()
                payload = clear_action_snoozes_for_resource(org_id, account_id=account_id, node_id=node_id)
                add_audit(self, "enterprise.action.clear_resource", path, ok=True, meta={"orgId": org_id, "accountId": account_id, "nodeId": node_id, "cleared": payload.get("cleared")})
                return json_response(self, payload)

            if path == "/api/central/node-capacity/update":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                node_id = (body.get("nodeId") or body.get("id") or "").strip()
                payload, status = update_node_capacity(org_id, node_id, body)
                add_audit(self, "node.capacity.update", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "nodeId": node_id, "status": status, "error": payload.get("error"), "capacity": payload.get("capacity")})
                return json_response(self, payload, status)

            if path == "/api/central/node-runtime-probe":
                org_id = request_org_id(self, body)
                action = (body.get("action") or "probe").strip().lower()
                required = "admin" if action == "repair" else "auditor"
                if not require_role(self, org_id, required):
                    return
                user = current_user(self)
                node_id = (body.get("nodeId") or body.get("id") or "").strip()
                task_id = (body.get("taskId") or body.get("centralTaskId") or "").strip()
                task_context = task_detail(task_id, org_id, include_all=False) if task_id else None
                if task_id and not task_context:
                    payload = {"ok": False, "error": "task_not_found", "taskId": task_id, "orgId": org_id}
                    add_audit(self, "node.runtime_probe", path, ok=False, meta={"orgId": org_id, "nodeId": node_id, "taskId": task_id, "action": action, "status": 404, "error": payload.get("error")})
                    return json_response(self, payload, 404)
                task_obj = (task_context or {}).get("task") or {}
                task_node_id = (task_obj.get("nodeId") or ((task_obj.get("body") or {}).get("nodeId")) or ((task_obj.get("body") or {}).get("preferredNode")) or "").strip()
                if task_node_id and not node_id:
                    node_id = task_node_id
                if task_node_id and node_id and task_node_id != node_id:
                    payload = {"ok": False, "error": "task_node_mismatch", "taskId": task_id, "nodeId": node_id, "taskNodeId": task_node_id, "orgId": org_id}
                    add_audit(self, "node.runtime_probe", path, ok=False, meta={"orgId": org_id, "nodeId": node_id, "taskId": task_id, "taskNodeId": task_node_id, "action": action, "status": 409, "error": payload.get("error")})
                    return json_response(self, payload, 409)
                payload, status = node_runtime_probe(org_id, node_id=node_id, action=action, dry_run=bool(body.get("dryRun")), limit=body.get("limit") or 50, clean_sessions=bool(body.get("cleanSessions", action == "repair")))
                changed = len(((payload.get("repair") or {}).get("changed") or [])) if isinstance(payload.get("repair"), dict) else 0
                cleanup = payload.get("sessionCleanup") if isinstance(payload.get("sessionCleanup"), dict) else {}
                support_info = None
                if task_context:
                    support_info = ensure_task_support_link(org_id, task_id, reason="node_runtime_probe", user=user, severity=payload.get("severity") or "warning", meta={
                        "nodeId": node_id,
                        "action": action,
                        "probeStatus": status,
                        "probeOk": bool(payload.get("ok")),
                        "severity": payload.get("severity"),
                        "issues": payload.get("issues") or [],
                        "changed": changed,
                        "cleanupMatched": cleanup.get("matched"),
                        "cleanupClosed": cleanup.get("closed"),
                        "failedRuntimeCount": payload.get("failedRuntimeCount"),
                        "error": payload.get("error"),
                    })
                    if support_info and support_info.get("link"):
                        payload["supportLink"] = support_info.get("link")
                        payload["supportLinkCreated"] = bool(support_info.get("created"))
                support_link = (support_info or {}).get("link") or {}
                add_audit(self, "node.runtime_probe", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "nodeId": node_id, "taskId": task_id, "supportId": support_link.get("id"), "supportLinkCreated": bool((support_info or {}).get("created")), "action": action, "dryRun": bool(body.get("dryRun")), "cleanSessions": bool(body.get("cleanSessions", action == "repair")), "status": status, "severity": payload.get("severity"), "issues": payload.get("issues"), "changed": changed, "cleanupMatched": cleanup.get("matched"), "cleanupClosed": cleanup.get("closed"), "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/accounts/authorization-restart":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                payload, status = restart_account_authorization(org_id, body, user=current_user(self))
                add_audit(self, "account.authorization.restart", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "accountId": payload.get("accountId"), "nodeId": payload.get("nodeId"), "closed": payload.get("closed"), "status": status, "closeStatus": payload.get("closeStatus")})
                return json_response(self, payload, status)

            if path == "/api/accounts/authorization-recover":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                payload, status = recover_account_authorization(org_id, body, user=current_user(self))
                add_audit(self, "account.authorization.recover", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "accountId": payload.get("accountId"), "nodeId": payload.get("nodeId"), "recoveryId": payload.get("recoveryId"), "dryRun": bool(payload.get("dryRun")), "closed": payload.get("closed"), "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/cloud-login/progress":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                payload = record_cloud_login_progress(org_id, body, user=current_user(self))
                return json_response(self, payload)

            if path == "/api/cloud-login/sessions/cleanup":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                payload, status = bulk_close_cloud_login_sessions(org_id, statuses=body.get("statuses") or body.get("status") or ["stale", "failed"], limit=body.get("limit") or 20, wait_sec=body.get("waitSec") or 8, dry_run=bool(body.get("dryRun")), node_id=(body.get("nodeId") or "").strip())
                add_audit(self, "cloud_login.session.cleanup", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "statuses": payload.get("statuses"), "matched": payload.get("matched"), "closed": payload.get("closed"), "failed": payload.get("failed"), "dryRun": payload.get("dryRun")})
                return json_response(self, payload, status)

            if path == "/api/cloud-login/sessions/close":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                session_ref = (body.get("sessionId") or body.get("id") or "").strip()
                try:
                    wait_sec = float(body.get("waitSec") or 20)
                except Exception:
                    wait_sec = 20
                payload, status = close_cloud_login_session(org_id, session_ref, wait_sec=wait_sec)
                add_audit(self, "cloud_login.session.close", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "sessionRef": short_session_id(session_ref), "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/notification-settings":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                payload, status = update_notification_settings(org_id, body)
                add_audit(self, "enterprise.notification.settings", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "enabled": (payload.get("settings") or {}).get("enabled")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/notifications/read":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                ids = body.get("ids") if isinstance(body.get("ids"), list) else []
                if body.get("id"):
                    ids.append(body.get("id"))
                payload, status = mark_notifications_read(org_id, ids=ids, all_items=bool(body.get("all")), user=current_user(self))
                add_audit(self, "enterprise.notification.read", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "read": payload.get("read"), "all": bool(body.get("all"))})
                return json_response(self, payload, status)

            if path == "/api/enterprise/webhook-deliveries/test":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                payload, status = trigger_test_webhook(org_id)
                add_audit(self, "enterprise.webhook.test", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "status": status, "error": (payload.get("result") or {}).get("reason")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/onboarding":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                user = current_user(self)
                payload, status = update_org_onboarding(org_id, body, user=user)
                add_audit(self, "enterprise.onboarding", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "status": status, "onboarding": payload.get("onboarding")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/preflight-attempts":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                user = current_user(self)
                payload, status = record_preflight_attempt(org_id, body, user=user)
                add_audit(self, "enterprise.preflight.attempt", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "status": status, "scope": (payload.get("attempt") or {}).get("scope"), "attemptId": (payload.get("attempt") or {}).get("id")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/usage/quota":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                if not require_feature(self, org_id, "quotaControls"):
                    return
                payload, status = update_org_quota(org_id, body)
                add_audit(self, "enterprise.usage.quota", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "status": status, "error": payload.get("error"), "quota": payload.get("quota")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/plan":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                payload, status = update_org_plan(org_id, body)
                add_audit(self, "enterprise.plan", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "status": status, "error": payload.get("error"), "plan": (payload.get("entitlements") or {}).get("plan")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/action-items/batch":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                operation = (body.get("operation") or body.get("action") or "").strip()
                filters = body.get("filters") if isinstance(body.get("filters"), dict) else {}
                ids = body.get("ids") if isinstance(body.get("ids"), list) else []
                payload, status = batch_action_items(
                    org_id,
                    operation=operation,
                    ids=ids,
                    q=(filters.get("q") or body.get("q") or ""),
                    kind=(filters.get("kind") or body.get("kind") or ""),
                    severity=(filters.get("severity") or body.get("severity") or ""),
                    hours=body.get("hours") or 24,
                    limit=body.get("limit") or 100,
                )
                add_audit(self, "enterprise.action.batch", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "operation": operation, "matched": payload.get("matched"), "processed": payload.get("processed"), "failed": payload.get("failed"), "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/kb/add":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                if not require_feature(self, org_id, "knowledgeBase"):
                    return
                text = (body.get("text") or body.get("content") or body.get("body") or body.get("value") or "").strip()
                if not text:
                    return json_response(self, {"ok": False, "error": "missing_text"}, 400)
                item = add_kb_doc(body.get("title") or "\u624b\u5de5\u8d44\u6599", body.get("type") or "company", text, org_id, source="manual", created_by=(current_user(self) or {}).get("id"))
                add_audit(self, "kb.add", path, ok=True, meta={"orgId": org_id, "docId": item["id"], "title": item["title"], "chunks": len(item.get("chunkTexts") or [])})
                return json_response(self, {"ok": True, "id": item["id"], "chunks": len(item.get("chunkTexts") or []), "chars": len(text)})
            if path == "/api/kb/delete":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                if not require_feature(self, org_id, "knowledgeBase"):
                    return
                doc_id = (body.get("id") or body.get("docId") or "").strip()
                if not doc_id:
                    return json_response(self, {"ok": False, "error": "missing_id"}, 400)
                ok = delete_kb_doc(doc_id, org_id)
                add_audit(self, "kb.delete", path, ok=ok, meta={"orgId": org_id, "docId": doc_id})
                return json_response(self, {"ok": ok, "error": None if ok else "not_found"}, 200 if ok else 404)
            if path == "/api/kb/ask":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "auditor"):
                    return
                if not require_feature(self, org_id, "knowledgeBase"):
                    return
                query = (body.get("query") or body.get("q") or "").strip()
                if not query:
                    return json_response(self, {"ok": False, "error": "missing_query"}, 400)
                sources = search_kb(query, org_id, limit=int(body.get("limit") or 5))
                if sources:
                    answer = "根据当前企业知识库，优先参考：\n" + "\n".join(["%d. %s：%s" % (i + 1, x["title"], x["text"][:180].replace("\n", " ")) for i, x in enumerate(sources[:3])])
                else:
                    answer = "当前企业知识库没有检索到直接相关内容。建议先补充产品资料、价格政策、售后规则或常见问答。"
                add_audit(self, "kb.ask", path, ok=True, meta={"orgId": org_id, "queryHash": _short_hash(query), "sources": len(sources)})
                return json_response(self, {"ok": True, "answer": answer, "sources": sources})
            if path == "/api/publish/preflight":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                if not require_feature(self, org_id, "publish"):
                    return
                pf = publish_preflight(
                    org_id,
                    body.get("accountId") or "douyin-self",
                    body.get("materialId") or "",
                    mode=body.get("mode") or "publish",
                    dry_run=bool(body.get("dryRun")),
                )
                add_audit(self, "publish.preflight", path, ok=bool(pf.get("ok")), meta={"orgId": org_id, "accountId": body.get("accountId"), "materialId": body.get("materialId"), "error": pf.get("error"), "warnings": pf.get("warnings")})
                return json_response(self, pf, 200 if pf.get("ok") else 400)

            if path == "/api/finder/leads/import":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                payload, status = upsert_finder_leads(org_id, body.get("leads") or body.get("items") or [], keyword=body.get("keyword") or "", task_id=body.get("taskId") or body.get("centralTaskId") or "", node_id=body.get("nodeId") or "", source=body.get("source") or "manual_import", user=current_user(self))
                add_audit(self, "finder.leads.import", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "created": payload.get("created"), "updated": payload.get("updated"), "total": payload.get("total"), "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/finder/leads/update":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                payload, status = update_finder_lead(org_id, body, user=current_user(self))
                add_audit(self, "finder.leads.update", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "leadId": body.get("id") or body.get("leadId"), "status": body.get("status") or body.get("stage"), "error": payload.get("error")})
                return json_response(self, payload, status)

            if path in TASK_POST_PATHS:
                body.setdefault("orgId", request_org_id(self, body))
                if not require_role(self, body.get("orgId"), "member"):
                    return
                actor = current_user(self) or {}
                body.setdefault("createdBy", actor.get("id") or "")
                body.setdefault("createdByUserId", actor.get("id") or "")
                feature = plan_feature_for_path(path)
                if feature and not require_feature(self, body.get("orgId"), feature):
                    return
                if path == "/api/publish/run":
                    org_id = normalize_org_id(body.get("orgId"))
                    account_id = (body.get("accountId") or "").strip()
                    pf = publish_preflight(org_id, account_id, body.get("materialId") or body.get("centralMaterialId") or "", mode="publish", dry_run=bool(body.get("dryRun")))
                    if not pf.get("ok"):
                        add_audit(self, "publish.preflight.block", path, ok=False, meta={"orgId": org_id, "accountId": account_id, "materialId": body.get("materialId"), "reason": pf.get("error"), "errors": pf.get("errors")})
                        return json_response(self, {"ok": False, "error": pf.get("error"), "message": "发布前置校验未通过", "preflight": pf}, 400)
                result, status, task = dispatch_task_sync(path, body, qs)
                if path.startswith("/api/cloud-login/") and isinstance(result, dict):
                    task_id = (task or {}).get("id") or result.get("centralTaskId") or ""
                    task_node = (task or {}).get("nodeId") or result.get("nodeId") or result.get("dispatchNodeId") or ""
                    if task_id:
                        result.setdefault("centralTaskId", task_id)
                        result.setdefault("receiptId", "cmd:" + task_id[:12])
                    if task_node:
                        result.setdefault("dispatchNodeId", task_node)
                    result.setdefault("dispatchPath", path)
                    result.setdefault("dispatchStatus", status)
                if path in ("/api/douyin/download", "/api/xhs/download") and status == 200 and isinstance(result, dict) and result.get("ok"):
                    try:
                        mirrored = mirror_download_material_to_library(result, body.get("orgId"), (task or {}).get("nodeId") if task else result.get("nodeId"))
                    except Exception as exc:
                        raw_log = json_log(
                            logger,
                            "download_library_import_failed",
                            exc=exc,
                            endpoint=path,
                            org_id=body.get("orgId"),
                            node_id=(task or {}).get("nodeId") if task else result.get("nodeId"),
                            source_url=body.get("url") or body.get("noteUrl") or "",
                        )
                        result = {
                            "ok": False,
                            "error": "library_import_failed",
                            "errorId": (json.loads(raw_log) or {}).get("errorId"),
                            "stage": "library",
                        }
                        status = 500
                    else:
                        if isinstance(mirrored, dict) and mirrored.get("id"):
                            result["material"] = public_material(mirrored)
                            result["materialId"] = mirrored.get("id")
                            result["libraryImported"] = True
                        else:
                            raw_log = json_log(
                                logger,
                                "download_library_import_failed",
                                endpoint=path,
                                org_id=body.get("orgId"),
                                node_id=(task or {}).get("nodeId") if task else result.get("nodeId"),
                                source_url=body.get("url") or body.get("noteUrl") or "",
                                reason="missing_material_id",
                            )
                            result = {
                                "ok": False,
                                "error": "library_import_failed",
                                "errorId": (json.loads(raw_log) or {}).get("errorId"),
                                "stage": "library",
                            }
                            status = 500
                if path == "/api/publish/run" and status == 200 and isinstance(result, dict) and result.get("published"):
                    bump_published(body.get("materialId") or body.get("centralMaterialId") or "")
                    record_publish_success(
                        body.get("orgId"),
                        body.get("centralAccountId") or body.get("accountId") or "douyin-self",
                    )
                if path == "/api/finder/discover" and status == 200 and isinstance(result, dict):
                    sync_payload, sync_status = upsert_finder_leads(
                        body.get("orgId"),
                        result.get("leads") or [],
                        keyword=body.get("keyword") or "",
                        task_id=(task or {}).get("id") or result.get("centralTaskId") or "",
                        node_id=(task or {}).get("nodeId") or result.get("nodeId") or "",
                        source=body.get("source") or "finder_discover",
                        user=current_user(self),
                    )
                    result["leadSync"] = {k: sync_payload.get(k) for k in ("ok", "created", "updated", "total", "stats")}
                    add_audit(self, "finder.leads.sync", path, ok=bool(sync_payload.get("ok")), meta={"orgId": body.get("orgId"), "taskId": (task or {}).get("id"), "nodeId": (task or {}).get("nodeId"), "created": sync_payload.get("created"), "updated": sync_payload.get("updated"), "total": sync_payload.get("total"), "status": sync_status})
                if path == "/api/cloud-login/close" and status == 200:
                    cleared = clear_action_snoozes_for_resource(
                        body.get("orgId"),
                        account_id=body.get("centralAccountId") or body.get("accountId") or "",
                        node_id=body.get("preferredNode") or body.get("nodeId") or ((task or {}).get("nodeId") if task else "") or "",
                    )
                    if isinstance(result, dict):
                        result["clearedActionSnoozes"] = cleared.get("cleared", 0)
                add_audit(self, "task.dispatch", path, ok=(200 <= int(status) < 400), meta={
                    "status": status,
                    "taskId": (task or {}).get("id"),
                    "nodeId": (task or {}).get("nodeId") if task else (result or {}).get("nodeId") if isinstance(result, dict) else None,
                    "body": audit_safe_body(body),
                    "resultOk": result.get("ok") if isinstance(result, dict) else None,
                    "error": result.get("error") if isinstance(result, dict) else None,
                })
                return json_response(self, result, status)

            if path in ("/api/login/start", "/api/login/sync"):
                return json_response(self, {"ok": False, "error": "login_on_execution_node_required", "message": "方案3使用预配置执行节点账号；请在节点机器上登录抖音。"}, 400)
            if path == "/api/publish/settings":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                saved = save_settings({
                    "perAccountPerDay": int(body.get("perAccountPerDay") or body.get("perAccount") or 1),
                    "intervalMin": int(body.get("intervalMin") or 60),
                    "enabled": bool(body.get("enabled")),
                }, org_id)
                add_audit(self, "settings.update", path, ok=True, meta={"orgId": org_id, "body": audit_safe_body(body)})
                return json_response(self, {"ok": True, **saved})
            if path == "/api/publish/queue/add":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                mid = (body.get("materialId") or "").strip()
                material = find_material(mid, org_id)
                if not material:
                    return json_response(self, {"ok": False, "error": "material_not_found"}, 404)
                account_id = (body.get("accountId") or "douyin-self").strip()
                pf = publish_preflight(org_id, account_id, mid, mode="queue", dry_run=False)
                if not pf.get("ok"):
                    add_audit(self, "queue.add.block", path, ok=False, meta={"orgId": org_id, "accountId": account_id, "materialId": mid, "reason": pf.get("error"), "errors": pf.get("errors")})
                    return json_response(self, {"ok": False, "error": pf.get("error"), "message": "发布计划前置校验未通过", "preflight": pf}, 400)
                acc_name = "抖音账号"
                for a in aggregate_accounts(org_id):
                    if a.get("id") == account_id:
                        acc_name = a.get("name") or acc_name
                        break
                item = {
                    "id": uuid.uuid4().hex,
                    "orgId": org_id,
                    "accountId": account_id,
                    "accountName": acc_name,
                    "materialId": mid,
                    "materialTitle": material.get("title") or "",
                    "status": "pending",
                    "createdAt": now(),
                }
                item["receiptId"] = queue_receipt_id(item["id"])
                append_queue_event(item, action="created", status="pending", meta={"accountId": account_id, "materialId": mid}, ts=item["createdAt"])
                q = load_queue()
                q.append(item)
                save_queue(q)
                add_audit(self, "queue.add", path, ok=True, meta={"itemId": item["id"], "materialId": mid, "accountId": account_id, "orgId": org_id})
                return json_response(self, {"ok": True, "id": item["id"], "receiptId": item.get("receiptId") or queue_receipt_id(item["id"]), "latestEventId": item.get("latestEventId"), "item": public_queue_item(item), "warnings": pf.get("warnings") or [], "preflight": pf})
            if path == "/api/publish/queue/clear":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                save_queue([j for j in load_queue() if j.get("status") == "running" or item_org_id(j) != org_id])
                add_audit(self, "queue.clear", path, ok=True, meta={"orgId": org_id})
                return json_response(self, {"ok": True})
            if path == "/api/publish/queue/cancel":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                qid = (body.get("id") or body.get("queueId") or "").strip()
                item, payload, status = cancel_queue_item(qid, org_id)
                add_audit(self, "queue.cancel", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "itemId": qid, "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)
            if path == "/api/publish/queue/retry":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                qid = (body.get("id") or body.get("queueId") or "").strip()
                item, payload, status = retry_queue_item(qid, org_id)
                add_audit(self, "queue.retry", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "itemId": qid, "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)
            if path == "/api/publish/queue/batch-preflight":
                org_id = request_org_id(self, body)
                operation = (body.get("operation") or "preview").strip().lower() if isinstance(body.get("operation") or "preview", str) else "preview"
                if not require_role(self, org_id, "member"):
                    return
                payload, status = publish_queue_batch_preflight(org_id, body, user=current_user(self))
                add_audit(self, "queue.batch_preflight", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "operation": operation, "checked": payload.get("checked"), "ready": payload.get("ready"), "blocked": payload.get("blocked"), "changed": payload.get("changed"), "error": payload.get("error")})
                return json_response(self, payload, status)
            if path == "/api/enterprise/task-center/bulk":
                org_id = request_org_id(self, body)
                action = (body.get("action") or "preview").strip().lower() if isinstance(body.get("action") or "preview", str) else "preview"
                needed_role = "auditor" if action == "preview" else ("admin" if action == "recover" else "member")
                if not require_role(self, org_id, needed_role):
                    return
                user = current_user(self)
                include_all = bool(user and user.get("_authType") == "root-token" and bool(body.get("all")))
                payload, status = task_center_bulk_action(org_id, body, include_all=include_all)
                add_audit(self, "task_center.bulk." + action, path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "action": action, "matched": payload.get("matched") or ((payload.get("counts") or {}).get("total") if isinstance(payload.get("counts"), dict) else 0), "changed": payload.get("changed"), "dryRun": bool(payload.get("dryRun")), "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/central/tasks/recover":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                limit = min(200, int(body.get("limit") or 100))
                payload = recover_stale_tasks(org_id, dry_run=bool(body.get("dryRun")), limit=limit, force=bool(body.get("force")))
                add_audit(self, "task.recover", path, ok=True, meta={"orgId": org_id, "changed": len(payload.get("changed") or []), "dryRun": bool(body.get("dryRun")), "force": bool(body.get("force"))})
                return json_response(self, payload)

            if path == "/api/central/tasks/cancel":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                user = current_user(self)
                include_all = bool(user and user.get("_authType") == "root-token" and bool(body.get("all")))
                task_id = (body.get("id") or body.get("taskId") or "").strip()
                task, payload, status = cancel_task(task_id, org_id, include_all=include_all)
                add_audit(self, "task.cancel", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "taskId": task_id, "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)
            if path == "/api/central/tasks/retry":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                user = current_user(self)
                include_all = bool(user and user.get("_authType") == "root-token" and bool(body.get("all")))
                task_id = (body.get("id") or body.get("taskId") or "").strip()
                task, payload, status = retry_task(task_id, org_id, include_all=include_all)
                add_audit(self, "task.retry", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "taskId": task_id, "status": status, "error": payload.get("error"), "newTaskId": (payload.get("task") or {}).get("id")})
                return json_response(self, payload, status)
            if path == "/api/enterprise/workspace/archive":
                org_id = request_org_id(self, body)
                if not require_platform_admin(self):
                    return
                payload, status = archive_customer_workspace(org_id, body)
                add_audit(self, "enterprise.workspace.archive", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "archivedMemberships": payload.get("archivedMemberships"), "disabledUsers": payload.get("disabledUsers"), "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/workspace/provision":
                if not require_platform_admin(self):
                    return
                payload, status = provision_customer_workspace(body, actor=current_user(self))
                add_audit(self, "enterprise.workspace.provision", path, ok=bool(payload.get("ok")), meta={"orgId": payload.get("orgId") or body.get("orgId"), "ownerId": (payload.get("owner") or {}).get("id"), "generatedPassword": bool(((payload.get("credential") or {}).get("generated"))), "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/orgs/upsert":
                if not require_platform_admin(self):
                    return
                name = (body.get("name") or "").strip()
                if not name:
                    return json_response(self, {"ok": False, "error": "missing_name"}, 400)
                with LOCK:
                    orgs = STATE.setdefault("organizations", [])
                    item = upsert_by_id(orgs, {
                        "id": (body.get("id") or "").strip() or None,
                        "name": name,
                        "status": body.get("status") or "active",
                        "plan": body.get("plan") or "standard",
                    })
                    persist()
                defaults = ensure_org_delivery_defaults(item.get("id"), item.get("plan") or body.get("plan") or "standard")
                add_audit(self, "enterprise.org.upsert", path, ok=True, meta={"orgId": item["id"], "name": name, "defaultsCreated": defaults.get("created")})
                return json_response(self, {"ok": True, "organization": item, "defaults": defaults})
            if path == "/api/enterprise/memberships/replace":
                if not require_platform_admin(self):
                    return
                payload, status = replace_enterprise_memberships(body)
                add_audit(self, "enterprise.memberships.replace", path, ok=bool(payload.get("ok")), meta={"orgId": body.get("orgId") or body.get("id"), "members": len(body.get("members") or []), "exclusive": bool(body.get("exclusive", True)), "removed": payload.get("removed"), "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)
            if path == "/api/enterprise/users/reset-password":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                payload, status = reset_enterprise_user_password(org_id, body)
                add_audit(self, "enterprise.user.reset_password", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "userId": body.get("userId") or body.get("id"), "generatedPassword": bool(((payload.get("credential") or {}).get("generated"))), "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/users/status":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                payload, status = update_enterprise_user_status(org_id, body)
                add_audit(self, "enterprise.user.status", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "userId": body.get("userId") or body.get("id"), "action": body.get("action") or body.get("status"), "revokedSessions": payload.get("revokedSessions"), "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/invites/create":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                payload, status = create_enterprise_invite(org_id, body, actor=current_user(self))
                add_audit(self, "enterprise.invite.create", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "inviteId": ((payload.get("invite") or {}).get("id")), "role": ((payload.get("invite") or {}).get("role")), "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/invites/revoke":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                payload, status = revoke_enterprise_invite(org_id, body)
                add_audit(self, "enterprise.invite.revoke", path, ok=bool(payload.get("ok")), meta={"orgId": org_id, "inviteId": body.get("inviteId") or body.get("id"), "revoked": payload.get("revoked"), "status": status, "error": payload.get("error")})
                return json_response(self, payload, status)

            if path == "/api/enterprise/users/upsert":
                name = (body.get("name") or "").strip()
                if not name:
                    return json_response(self, {"ok": False, "error": "missing_name"}, 400)
                org_id = (body.get("orgId") or "").strip() or request_org_id(self, body)
                if not require_role(self, org_id, "admin"):
                    return
                with LOCK:
                    users = STATE.setdefault("users", [])
                    item = upsert_by_id(users, {
                        "id": (body.get("id") or "").strip() or None,
                        "name": name,
                        "phone": (body.get("phone") or "").strip(),
                        "email": (body.get("email") or "").strip(),
                        "status": body.get("status") or "active",
                    })
                    if (body.get("password") or "").strip():
                        set_user_password(item, (body.get("password") or "").strip())
                    if org_id:
                        memberships = STATE.setdefault("memberships", [])
                        upsert_by_id(memberships, {
                            "id": "m-%s-%s" % (org_id, item["id"]),
                            "orgId": org_id,
                            "userId": item["id"],
                            "role": body.get("role") or "member",
                            "status": "active",
                        })
                    persist()
                add_audit(self, "enterprise.user.upsert", path, ok=True, meta={"userId": item["id"], "name": name, "orgId": (body.get("orgId") or "")})
                return json_response(self, {"ok": True, "user": public_user(item)})
            if path == "/api/enterprise/nodes/assign":
                node_id = (body.get("nodeId") or "").strip()
                org_id = normalize_org_id(body.get("orgId"))
                if not require_role(self, org_id, "admin"):
                    return
                if not node_id:
                    return json_response(self, {"ok": False, "error": "missing_node_id"}, 400)
                with LOCK:
                    org_exists = any(o.get("id") == org_id for o in (STATE.get("organizations") or []))
                    node = (STATE.get("nodes") or {}).get(node_id)
                    if not org_exists:
                        return json_response(self, {"ok": False, "error": "org_not_found"}, 404)
                    if not node:
                        return json_response(self, {"ok": False, "error": "node_not_found"}, 404)
                    old_org = item_org_id(node)
                    node["orgId"] = org_id
                    for a in node.get("accounts") or []:
                        if isinstance(a, dict):
                            a["orgId"] = org_id
                    node["updatedAt"] = now()
                    sync_node_accounts_locked(node)
                    persist()
                    public = public_node(node)
                add_audit(self, "enterprise.node.assign", path, ok=True, meta={"nodeId": node_id, "fromOrgId": old_org, "toOrgId": org_id})
                return json_response(self, {"ok": True, "node": public, "fromOrgId": old_org, "toOrgId": org_id})
            if path == "/api/library/delete":
                org_id = request_org_id(self, body)
                if not require_role(self, org_id, "member"):
                    return
                mid = (body.get("id") or body.get("materialId") or "").strip()
                if not mid:
                    return json_response(self, {"ok": False, "error": "missing_id"}, 400)
                if not find_material(mid, org_id):
                    return json_response(self, {"ok": False, "error": "material_not_found"}, 404)
                with LOCK:
                    STATE["library"] = [m for m in (STATE.get("library") or []) if not (m.get("id") == mid and item_org_id(m) == org_id)]
                    STATE["queue"] = [j for j in (STATE.get("queue") or []) if not (j.get("materialId") == mid and item_org_id(j) == org_id)]
                    persist()
                try:
                    shutil.rmtree(material_dir(mid), ignore_errors=True)
                except Exception:
                    pass
                add_audit(self, "library.delete", path, ok=True, meta={"materialId": mid, "orgId": org_id})
                return json_response(self, {"ok": True})
            return json_response(self, {"ok": False, "error": "not_found", "path": path}, 404)
        except Exception as e:
            return json_response(self, {"ok": False, "error": str(e), "trace": traceback.format_exc()}, 500)


def main():
    print("=" * 72)
    print(f"MatrixShip Central Scheduler {CENTRAL_VERSION}")
    print(f"Listening: http://{HOST}:{PORT}")
    print(f"Data dir : {DATA_DIR}")
    print(f"Node secret header: X-Node-Secret")
    if USER_TOKEN:
        print("User API token enabled: X-Matrix-User-Token")
    else:
        print("User API token disabled")
    print("=" * 72)
    threading.Thread(target=publish_scheduler, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
