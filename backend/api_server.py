# coding: utf-8
import asyncio
import base64
import json
import mimetypes
import os
import re
import secrets
import hashlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urljoin, urlparse

from loguru import logger

from builder.auth import DouyinAuth
from main import Data_Spider
from utils.common_util import init
from utils.data_util import MediaDownloadError, download_work, handle_work_info
from utils.media_validation import cleanup_quarantine, validate_image_file, validate_video_file
from utils.structured_log import json_log
from runtime_paths import agent_data_dir
from utils.cookie_util import (
    get_new_cookies,
    get_login_cookies,
    get_login_cookies_persistent,
    get_persistent_profile_cookies,
)
from utils.publish_util import publish_to_douyin
import xhs_note_replacement
try:
    from edge_ui_comment import send_comment_via_edge_ui
except Exception:
    send_comment_via_edge_ui = None
from platform_adapters import (
    discover_xhs_leads_by_keyword,
    platform_code,
    platform_label,
    xhs_download_note,
    xhs_get_comments,
    xhs_guest_collection_default,
    xhs_profile_ready,
    xhs_publish_comment,
    xhs_publish_material,
    xhs_search_notes,
)


APP_NAME = 'MatrixShipAgent'
AGENT_VERSION = '1.0.0-local-agent'


def _default_agent_data_dir():
    explicit = os.getenv('MATRIX_AGENT_DATA_DIR') or os.getenv('DY_DATA_DIR')
    if explicit:
        return os.path.abspath(os.path.expandvars(explicit))
    return agent_data_dir()


def _legacy_data_dir():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), 'datas'))


def _migrate_legacy_data(new_dir):
    """Best-effort migration for existing dev/user installs."""
    old_dir = _legacy_data_dir()
    if os.path.normcase(old_dir) == os.path.normcase(new_dir) or not os.path.isdir(old_dir):
        return
    os.makedirs(new_dir, exist_ok=True)
    for name in (
        'auth_cookie.json', 'library.json', 'publish_settings.json',
        'publish_queue.json', 'outreach_last_result.json',
        'finder_last_result.json', 'comment_risk_state.json'
    ):
        src = os.path.join(old_dir, name)
        dst = os.path.join(new_dir, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            try:
                import shutil
                shutil.copy2(src, dst)
            except Exception:
                pass
    for name in ('materials', 'media_datas', 'excel_datas', 'dy_profile'):
        src = os.path.join(old_dir, name)
        dst = os.path.join(new_dir, name)
        if os.path.isdir(src) and not os.path.exists(dst):
            try:
                import shutil
                shutil.copytree(src, dst)
            except Exception:
                pass


# Local-agent mode must not expose raw account/browser capability on LAN by
# default. Users access the native client remotely, but the browser always calls the
# user's own 127.0.0.1 agent.
HOST = os.getenv("API_HOST", "127.0.0.1")
PORT = int(os.getenv("API_PORT", "9080"))

SPIDER = Data_Spider()
try:
    DEFAULT_AUTH, BASE_PATH = init()
except Exception:
    DEFAULT_AUTH = DouyinAuth()
    BASE_PATH = {
        'media': os.path.abspath(os.path.join(os.path.dirname(__file__), 'datas/media_datas')),
        'excel': os.path.abspath(os.path.join(os.path.dirname(__file__), 'datas/excel_datas')),
    }
    for p in BASE_PATH.values():
        os.makedirs(p, exist_ok=True)

STATE = {
    'auth': DEFAULT_AUTH if getattr(DEFAULT_AUTH, 'cookie', None) else DouyinAuth(),
    'cookie_jobs': {},
    'login_running': False,
}
STATE_LOCK = threading.RLock()
CLOUD_LOGIN_SESSIONS = {}
CLOUD_LOGIN_LOCK = threading.RLock()

# ---- 自动化发布：素材库 / 设置 / 队列 持久化 ----
DATA_DIR = _default_agent_data_dir()
_migrate_legacy_data(DATA_DIR)
MATERIALS_DIR = os.path.join(DATA_DIR, 'materials')
MATERIAL_QUARANTINE_DIR = os.path.join(DATA_DIR, 'quarantine')
LIBRARY_JSON = os.path.join(DATA_DIR, 'library.json')
PUBLISH_SETTINGS_JSON = os.path.join(DATA_DIR, 'publish_settings.json')
PUBLISH_QUEUE_JSON = os.path.join(DATA_DIR, 'publish_queue.json')
AUTH_CACHE_JSON = os.path.join(DATA_DIR, 'auth_cookie.json')
DOUYIN_ACCOUNTS_JSON = os.path.join(DATA_DIR, 'douyin_accounts.json')
DOUYIN_ACCOUNT_PROFILES_DIR = os.path.join(DATA_DIR, 'douyin_accounts')
OUTREACH_LAST_JSON = os.path.join(DATA_DIR, 'outreach_last_result.json')
FINDER_LAST_JSON = os.path.join(DATA_DIR, 'finder_last_result.json')
DOUYIN_SEARCH_CACHE_JSON = os.path.join(DATA_DIR, 'douyin_search_cache.json')
COMMENT_RISK_JSON = os.path.join(DATA_DIR, 'comment_risk_state.json')
DOUYIN_CAPABILITY_STATE_JSON = os.path.join(DATA_DIR, 'douyin_capability_state.json')
AGENT_CONFIG_JSON = os.path.join(DATA_DIR, 'agent_config.json')
RISK_CONFIG_JSON = os.path.join(DATA_DIR, 'risk_config.json')
XHS_SAFETY_STATE_JSON = os.path.join(DATA_DIR, 'xhs_safety_state.json')
DOUYIN_MAIN_LOGIN_URL = 'https://www.douyin.com/?recommend=1'
CREATOR_LOGIN_URL = 'https://creator.douyin.com/creator-micro/content/upload'
for _d in (DATA_DIR, MATERIALS_DIR, MATERIAL_QUARANTINE_DIR, DOUYIN_ACCOUNT_PROFILES_DIR):
    os.makedirs(_d, exist_ok=True)

# Force browser profile into the per-user agent directory unless the operator
# explicitly supplied a profile path.
os.environ.setdefault('DY_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_profile'))


def load_agent_config():
    cfg = _load_json(AGENT_CONFIG_JSON, {})
    if not isinstance(cfg, dict):
        cfg = {}
    changed = False
    if not cfg.get('token'):
        cfg['token'] = secrets.token_urlsafe(24)
        changed = True
    cfg.setdefault('createdAt', time.time())
    cfg.setdefault('allowedOrigins', [])
    if changed:
        try:
            _save_json(AGENT_CONFIG_JSON, cfg)
        except Exception:
            pass
    return cfg


def agent_token():
    return (os.getenv('MATRIX_AGENT_TOKEN') or load_agent_config().get('token') or '').strip()


def token_auth_enabled():
    return os.getenv('MATRIX_AGENT_TOKEN_AUTH', '1').strip().lower() not in ('0', 'false', 'no', 'off')


def is_loopback_host(host):
    host = (host or '').split(':', 1)[0].strip().lower()
    return host in ('localhost', '127.0.0.1', '::1', '[::1]')


def origin_allowed(origin):
    if not origin:
        return True
    try:
        u = urlparse(origin)
        host = (u.hostname or '').lower()
        if host in ('localhost', '127.0.0.1', '::1'):
            return True
        cfg = load_agent_config()
        allowed = set(x.strip().rstrip('/') for x in (cfg.get('allowedOrigins') or []) if x)
        extra = os.getenv('MATRIX_AGENT_ALLOWED_ORIGINS', '')
        allowed.update(x.strip().rstrip('/') for x in extra.split(',') if x.strip())
        # Commercial default: token authentication is the primary protection, so
        # API callers can work out-of-the-box from any domain. Operators
        # that want strict origin pinning can set MATRIX_AGENT_ALLOWED_ORIGINS or
        # write allowedOrigins into agent_config.json.
        if not allowed:
            return True
        return origin.rstrip('/') in allowed
    except Exception:
        return False


def request_token(handler):
    h = handler.headers
    tok = h.get('X-Matrix-Agent-Token') or h.get('X-Agent-Token') or ''
    auth = h.get('Authorization') or ''
    if auth.lower().startswith('bearer '):
        tok = auth[7:].strip()
    return (tok or '').strip()


def request_authorized(handler):
    if not token_auth_enabled():
        return True
    return bool(agent_token()) and secrets.compare_digest(request_token(handler), agent_token())


def cors_origin(handler):
    origin = handler.headers.get('Origin') or ''
    if origin and origin_allowed(origin):
        return origin
    return '*'


def send_cors_headers(handler):
    handler.send_header('Access-Control-Allow-Origin', cors_origin(handler))
    handler.send_header('Vary', 'Origin')
    handler.send_header('Access-Control-Allow-Headers', 'content-type, authorization, x-matrix-agent-token, x-agent-token')
    handler.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    handler.send_header('Access-Control-Allow-Private-Network', 'true')
    handler.send_header('Cache-Control', 'no-store')


def ensure_agent_request(handler, path):
    if not origin_allowed(handler.headers.get('Origin') or ''):
        json_response(handler, {'ok': False, 'error': 'origin_not_allowed'}, 403)
        return False
    # Health is allowed unauthenticated so the native client can detect an
    # installed local agent and ask for the authorization code.
    if path in ('/api/health', '/api/agent/status') or path.startswith('/api/library/file/'):
        return True
    if not request_authorized(handler):
        json_response(handler, {
            'ok': False,
            'error': 'agent_token_required',
            'requiresToken': token_auth_enabled(),
            'agentReady': True,
            'version': AGENT_VERSION,
        }, 401)
        return False
    return True

# 浏览器发布串行锁（试发 + 调度器共用，避免同时弹多个浏览器）
PUBLISH_LOCK = threading.Lock()
# 发布频率运行时状态（按天/按账号限流）
PUBLISH_RT = {'last_ts': 0.0, 'day': '', 'counts': {}}


def _load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _load_json_with_error(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f), None
    except Exception as exc:
        return default, exc


def _save_json(path, data):
    # 原子写：临时文件 + fsync + os.replace，避免崩溃时留下半截 JSON 被下次启动当空数据
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _cookie_value(cookie_str, key):
    m = re.search(r'(?:^|;\s*)' + re.escape(key) + r'=([^;]+)', cookie_str or '')
    return (m.group(1) if m else '').strip()


def douyin_account_id_from_cookie(cookie_str):
    """Build a stable local account id without exposing raw cookie values."""
    basis = ''
    for key in ('uid_tt', 'uid_tt_ss', 'sid_tt', 'sessionid', 'sessionid_ss'):
        basis = _cookie_value(cookie_str, key)
        if basis:
            break
    if not basis:
        basis = cookie_str or str(time.time())
    digest = hashlib.sha256(str(basis).encode('utf-8')).hexdigest()[:16]
    return 'douyin-' + digest


def _backup_invalid_douyin_accounts_json():
    if not os.path.isfile(DOUYIN_ACCOUNTS_JSON):
        return ''
    backup = DOUYIN_ACCOUNTS_JSON + '.invalid'
    try:
        shutil.copy2(DOUYIN_ACCOUNTS_JSON, backup)
        return backup
    except Exception:
        return ''


def _recover_douyin_accounts_from_profile_dirs():
    rows = []
    root = DOUYIN_ACCOUNT_PROFILES_DIR
    if not os.path.isdir(root):
        return rows
    for name in sorted(os.listdir(root)):
        if not re.match(r'^douyin-[A-Za-z0-9_-]+$', name or ''):
            continue
        account_root = os.path.join(root, name)
        if not os.path.isdir(account_root):
            continue
        profile_dir = os.path.join(account_root, 'dy_profile')
        auth_cache = os.path.join(account_root, 'auth_cookie.json')
        cache = _load_json(auth_cache, {})
        if not isinstance(cache, dict):
            cache = {}
        saved_at = float(cache.get('savedAt') or 0)
        has_cookie = bool(cache.get('hasLoginCookie') or cache.get('cookie'))
        rows.append({
            'id': name,
            'platform': 'douyin',
            'name': '抖音账号 ' + name[-6:],
            'handle': '',
            'avatar': '',
            'profileDir': profile_dir,
            'authCache': auth_cache,
            'cookieCount': len([p for p in str(cache.get('cookie') or '').split(';') if p.strip()]),
            'cookieReady': has_cookie,
            'usable': has_cookie,
            'online': has_cookie,
            'status': 'online' if has_cookie else 'offline',
            'source': cache.get('source') or 'profile-recovery',
            'lastLoginAt': saved_at,
            'updatedAt': saved_at or os.path.getmtime(account_root),
        })
    rows.sort(key=lambda x: x.get('lastLoginAt') or x.get('updatedAt') or 0, reverse=True)
    return rows


def load_douyin_accounts():
    data, load_error = _load_json_with_error(DOUYIN_ACCOUNTS_JSON, [])
    if not isinstance(data, list):
        return []
    rows = []
    for row in data:
        if isinstance(row, dict) and row.get('id'):
            rows.append(row)
    if not rows and load_error is not None:
        recovered = _recover_douyin_accounts_from_profile_dirs()
        if recovered:
            backup = _backup_invalid_douyin_accounts_json()
            save_douyin_accounts(recovered)
            json_log(
                logger,
                'douyin_accounts_registry_recovered',
                recoveredCount=len(recovered),
                backupPath=backup,
            )
            return recovered
    return rows


def save_douyin_accounts(rows):
    rows = [r for r in (rows or []) if isinstance(r, dict) and r.get('id')]
    rows = sorted(rows, key=lambda x: x.get('lastLoginAt') or x.get('updatedAt') or 0, reverse=True)
    _save_json(DOUYIN_ACCOUNTS_JSON, rows)


def account_display_meta_path():
    return os.path.join(DATA_DIR, 'account_display_meta.json')


def load_account_display_meta():
    data = _load_json(account_display_meta_path(), {})
    return data if isinstance(data, dict) else {}


def save_account_display_meta(data):
    _save_json(account_display_meta_path(), data if isinstance(data, dict) else {})


def local_account_id(account_id):
    account_id = _safe_account_key(account_id or '') if '_safe_account_key' in globals() else (account_id or '')
    if ':' in account_id:
        account_id = account_id.rsplit(':', 1)[-1]
    return account_id


def apply_account_display_meta(row):
    if not isinstance(row, dict):
        return row
    meta = load_account_display_meta().get(str(row.get('id') or '').strip()) or {}
    if isinstance(meta, dict):
        display_name = str(meta.get('name') or meta.get('nickname') or '').strip()
        if display_name:
            row = dict(row)
            row['name'] = display_name
            row['nickname'] = display_name
            row['displayName'] = display_name
    return row


def account_disabled(account_id):
    meta = load_account_display_meta().get(str(account_id or '').strip()) or {}
    return bool(isinstance(meta, dict) and meta.get('disabled'))


def set_account_disabled(account_id, disabled=True):
    account_id = local_account_id(account_id or '')
    if not account_id:
        return
    meta = load_account_display_meta()
    row = meta.get(account_id) if isinstance(meta.get(account_id), dict) else {}
    row = dict(row)
    if disabled:
        row['disabled'] = True
        row['removedAt'] = time.time()
    else:
        row.pop('disabled', None)
        row.pop('removedAt', None)
    meta[account_id] = row
    save_account_display_meta(meta)


def douyin_account_paths(account_id):
    safe = _safe_account_key(account_id or 'douyin-self') if '_safe_account_key' in globals() else (account_id or 'douyin-self')
    if safe in ('douyin-self', 'default'):
        profile = os.path.abspath(os.getenv('DY_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_profile')))
        auth_cache = os.path.abspath(AUTH_CACHE_JSON)
    else:
        root = os.path.abspath(os.path.join(DOUYIN_ACCOUNT_PROFILES_DIR, safe))
        profile = os.path.join(root, 'dy_profile')
        auth_cache = os.path.join(root, 'auth_cookie.json')
    return {'root': os.path.dirname(profile), 'profileDir': profile, 'authCache': auth_cache}


def find_douyin_account(account_id):
    account_id = _safe_account_key(account_id or '')
    for row in load_douyin_accounts():
        if row.get('id') == account_id:
            return dict(row)
    if account_id in ('douyin-self', 'default', ''):
        paths = douyin_account_paths('douyin-self')
        return {
            'id': 'douyin-self',
            'platform': 'douyin',
            'name': os.getenv('DY_ACCOUNT_NAME', '抖音账号'),
            'profileDir': paths['profileDir'],
            'authCache': paths['authCache'],
        }
    return None


def default_douyin_comment_account_id(account_id=''):
    explicit = _safe_account_key(account_id or '') if '_safe_account_key' in globals() else (account_id or '')
    if explicit and explicit not in ('douyin-self', 'default'):
        return explicit
    rows = sorted(
        load_douyin_accounts(),
        key=lambda x: x.get('lastLoginAt') or x.get('updatedAt') or 0,
        reverse=True,
    )
    for row in rows:
        if row.get('platform') and row.get('platform') != 'douyin':
            continue
        if row.get('cookieReady') is False or row.get('usable') is False:
            continue
        if str(row.get('status') or '').lower() in ('offline', 'disabled', 'removed'):
            continue
        account_row_id = row.get('id') or ''
        if not account_row_id:
            continue
        cache = load_cookie_cache(account_row_id)
        if cookie_str_has_login((cache.get('cookie') or '').strip()):
            return account_row_id
    return ''


def register_douyin_account(cookie_str, profile_dir='', source='login', web_protect='', keys='', name=''):
    if not cookie_str or not cookie_str_has_login(cookie_str):
        raise RuntimeError('invalid_douyin_cookie')
    account_id = douyin_account_id_from_cookie(cookie_str)
    paths = douyin_account_paths(account_id)
    os.makedirs(os.path.dirname(paths['authCache']), exist_ok=True)
    os.makedirs(paths['profileDir'], exist_ok=True)
    src_profile = os.path.abspath(profile_dir or '')
    dst_profile = os.path.abspath(paths['profileDir'])
    if src_profile and os.path.isdir(src_profile) and os.path.normcase(src_profile) != os.path.normcase(dst_profile):
        if os.path.isdir(dst_profile):
            shutil.rmtree(dst_profile, ignore_errors=True)
        os.makedirs(os.path.dirname(dst_profile), exist_ok=True)
        shutil.move(src_profile, dst_profile)
    cache = {
        'cookie': cookie_str,
        'source': source or 'login',
        'savedAt': time.time(),
        'hasLoginCookie': cookie_str_has_login(cookie_str),
        'web_protect': web_protect or '',
        'keys': keys or '',
        'hasSecurityKeys': bool(web_protect and keys),
    }
    _save_json(paths['authCache'], cache)
    rows = load_douyin_accounts()
    by_id = {r.get('id'): dict(r) for r in rows if r.get('id')}
    old = by_id.get(account_id) or {'id': account_id, 'createdAt': time.time()}
    old.update({
        'id': account_id,
        'platform': 'douyin',
        'name': name or old.get('name') or ('抖音账号 ' + account_id[-6:]),
        'handle': old.get('handle') or '',
        'avatar': old.get('avatar') or '',
        'profileDir': dst_profile,
        'authCache': paths['authCache'],
        'cookieCount': len(parse_cookie_dict(cookie_str)),
        'cookieReady': True,
        'usable': True,
        'online': True,
        'status': 'online',
        'source': source or 'login',
        'lastLoginAt': time.time(),
        'updatedAt': time.time(),
    })
    by_id[account_id] = old
    save_douyin_accounts(list(by_id.values()))
    set_account_disabled(account_id, False)
    os.environ['DY_PROFILE_DIR'] = dst_profile
    set_auth_from_cookie(cookie_str, source=source, persist=True, web_protect=web_protect, keys=keys, account_id=account_id)
    return dict(old)


def remove_douyin_account(account_id, delete_files=False):
    account_id = local_account_id(account_id or '')
    if not account_id:
        return {'ok': False, 'error': 'missing_account_id'}
    if account_id in ('douyin-self', 'default'):
        set_account_disabled('douyin-self', True)
        with STATE_LOCK:
            STATE['auth'] = DouyinAuth()
        if delete_files:
            paths = douyin_account_paths('douyin-self')
            try:
                if os.path.isfile(paths['authCache']):
                    os.remove(paths['authCache'])
            except Exception:
                pass
            shutil.rmtree(paths['profileDir'], ignore_errors=True)
        return {'ok': True, 'removed': 1, 'id': 'douyin-self', 'platform': 'douyin'}
    rows = load_douyin_accounts()
    kept = [r for r in rows if r.get('id') != account_id]
    removed = len(rows) - len(kept)
    if removed:
        save_douyin_accounts(kept)
        if delete_files:
            shutil.rmtree(os.path.dirname(douyin_account_paths(account_id)['profileDir']), ignore_errors=True)
    return {'ok': True, 'removed': removed, 'id': account_id}


def remove_xhs_account(account_id='xhs-self', delete_files=False):
    account_id = local_account_id(account_id or 'xhs-self')
    if account_id not in ('xhs-self', 'xiaohongshu-self', 'rednote-self'):
        return {'ok': False, 'error': 'unsupported_xhs_account'}
    profile_dir = os.path.abspath(os.getenv('XHS_PROFILE_DIR', os.path.join(DATA_DIR, 'xhs_profile')))
    _save_json(os.path.join(DATA_DIR, 'xhs_auth_state.json'), {
        'loggedIn': False,
        'cookieCount': 0,
        'disabled': True,
        'removedAt': time.time(),
        'profileDir': profile_dir,
    })
    if delete_files and os.path.isdir(profile_dir):
        shutil.rmtree(profile_dir, ignore_errors=True)
    return {'ok': True, 'removed': 1, 'id': 'xhs-self', 'platform': 'xhs'}


def remove_local_account(account_id, delete_files=False):
    account_id = local_account_id(account_id or '')
    if account_id in ('xhs-self', 'xiaohongshu-self', 'rednote-self') or account_id.startswith('xhs-'):
        return remove_xhs_account(account_id, delete_files=delete_files)
    return remove_douyin_account(account_id, delete_files=delete_files)


def rename_account_display_name(account_id, name):
    account_id = local_account_id(account_id or '')
    name = re.sub(r'[\r\n\t]+', ' ', str(name or '')).strip()
    if not account_id:
        return {'ok': False, 'error': 'missing_account_id'}
    if not name:
        return {'ok': False, 'error': 'missing_name'}
    if len(name) > 40:
        name = name[:40].strip()

    updated = False
    rows = []
    for row in load_douyin_accounts():
        row = dict(row)
        if row.get('id') == account_id:
            row['name'] = name
            row['nickname'] = name
            row['displayName'] = name
            row['updatedAt'] = time.time()
            updated = True
        rows.append(row)
    if updated:
        save_douyin_accounts(rows)

    meta = load_account_display_meta()
    meta[account_id] = {'name': name, 'nickname': name, 'updatedAt': time.time()}
    save_account_display_meta(meta)
    return {'ok': True, 'id': account_id, 'name': name, 'updated': updated}


def douyin_account_scope(account_id):
    account = find_douyin_account(account_id)
    paths = douyin_account_paths((account or {}).get('id') or account_id or 'douyin-self')
    old_profile = os.environ.get('DY_PROFILE_DIR')
    old_auth = None
    with STATE_LOCK:
        old_auth = STATE.get('auth')
    class _Scope:
        def __enter__(self_inner):
            os.environ['DY_PROFILE_DIR'] = paths['profileDir']
            auth = ensure_auth_from_cache((account or {}).get('id') or account_id or 'douyin-self')
            return auth, paths
        def __exit__(self_inner, exc_type, exc, tb):
            if old_profile is None:
                os.environ.pop('DY_PROFILE_DIR', None)
            else:
                os.environ['DY_PROFILE_DIR'] = old_profile
            with STATE_LOCK:
                STATE['auth'] = old_auth
            return False
    return _Scope()


@contextmanager
def douyin_auth_for_request(account_id=''):
    selected = default_douyin_comment_account_id(account_id or '')
    if selected:
        with douyin_account_scope(selected) as scoped:
            yield scoped[0], selected
    else:
        yield require_auth(), ''


def parse_cookie_dict(cookie_str):
    out = {}
    for part in str(cookie_str or '').split(';'):
        if '=' not in part:
            continue
        k, v = part.split('=', 1)
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


LOGIN_COOKIE_KEYS = ('sessionid', 'sessionid_ss', 'sid_guard', 'uid_tt', 'sid_tt')
DOUYIN_FINGERPRINT_COOKIE_KEYS = ('s_v_web_id', 'verifyFp', 'fp', 'x-web-secsdk-uid', 'webid', 'ttwid')
DOUYIN_AUTH_ERRORS = {'no_auth', 'douyin_auth_incomplete'}


def cookie_str_has_login(cookie_str):
    if not cookie_str:
        return False
    s = str(cookie_str)
    return ('LOGIN_STATUS=1' in s) or any((k + '=') in s for k in LOGIN_COOKIE_KEYS)


def cookie_dict_has_douyin_fingerprint(cookie):
    if not isinstance(cookie, dict):
        return False
    return any(str(cookie.get(k) or '').strip() for k in DOUYIN_FINGERPRINT_COOKIE_KEYS)


def is_douyin_auth_error(error):
    return str(error) in DOUYIN_AUTH_ERRORS


def _capability(key, label, ready, domain='', reason=''):
    return {
        'key': key,
        'label': label,
        'ready': bool(ready),
        'status': 'ready' if ready else 'needs_auth',
        'domain': domain,
        'reason': reason or ('' if ready else 'login_required'),
    }


def douyin_capabilities_needs_auth(reason='login_required', profile_dir=None):
    caps = {
        'search': _capability('search', '\u641c\u7d22\u89c6\u9891', False, 'www.douyin.com', reason),
        'commentRead': _capability('commentRead', '\u67e5\u770b\u8bc4\u8bba', False, 'www.douyin.com', reason),
        'commentWrite': _capability('commentWrite', '\u53d1\u9001\u8bc4\u8bba', False, 'www.douyin.com', reason),
        'publish': _capability('publish', '\u53d1\u5e03\u89c6\u9891', False, 'creator.douyin.com', reason),
    }
    return {
        'profileUnified': True,
        'profileDir': profile_dir or os.getenv('DY_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_profile')),
        'cookieReady': False,
        'cookieCount': 0,
        'hasSecuritySdk': False,
        'ready': False,
        'readyCount': 0,
        'total': len(caps),
        'items': caps,
    }


def load_douyin_capability_state():
    data = _load_json(DOUYIN_CAPABILITY_STATE_JSON, {})
    return data if isinstance(data, dict) else {}


def save_douyin_capability_state(data):
    _save_json(DOUYIN_CAPABILITY_STATE_JSON, data if isinstance(data, dict) else {})


def mark_douyin_capability(key, ready, reason='', proof=None, requires_reauth=False):
    """Persist runtime capability truth discovered by real browser/API probes.

    Cookie presence is only an asset signal. Write actions such as comments must
    reflect the latest real preflight result, otherwise the commercial UI lies by
    showing "4/4 ready" while the actual task is blocked by a login panel.
    """
    key = str(key or '').strip()
    if not key:
        return {}
    st = load_douyin_capability_state()
    items = st.get('items') if isinstance(st.get('items'), dict) else {}
    if ready:
        items.pop(key, None)
        if key == 'commentWrite':
            # A successful real browser preflight proves the old
            # comment_login_required cache is stale. Clear it immediately so
            # /api/health and the native client do not keep showing 3/4.
            try:
                risk = load_comment_risk_state() if 'load_comment_risk_state' in globals() else {}
                rr = str((risk.get('lastResponse') or {}).get('reason') or risk.get('lastReason') or '')
                if rr in ('comment_login_required', 'comment_input_not_ready', 'preflight_blocked'):
                    risk.update({
                        'lastReason': 'cleared_by_preflight_ok',
                        'clearedAt': time.time(),
                        'cooldownUntil': 0,
                    })
                    save_comment_risk_state(risk)
            except Exception:
                pass
    else:
        p = proof if isinstance(proof, dict) else {}
        items[key] = {
            'ready': False,
            'reason': reason or 'runtime_probe_failed',
            'updatedAt': time.time(),
            'requiresReauth': bool(requires_reauth),
            'proof': {
                'reason': p.get('reason') or reason,
                'url': p.get('url') or '',
                'hasLoginHint': bool(p.get('hasLoginHint')),
                'hasVisibleCommentInput': bool(p.get('hasVisibleCommentInput')),
                'loginButtonCount': p.get('loginButtonCount', 0),
                'text': (p.get('text') or '')[:260],
            },
        }
    st.update({'items': items, 'updatedAt': time.time()})
    try:
        save_douyin_capability_state(st)
    except Exception:
        pass
    return st


def clear_douyin_capability_state(reason='reauth'):
    try:
        save_douyin_capability_state({'items': {}, 'clearedAt': time.time(), 'clearReason': reason})
    except Exception:
        pass


def apply_douyin_capability_overrides(caps):
    if not isinstance(caps, dict):
        return caps
    items = caps.get('items')
    if not isinstance(items, dict):
        return caps
    overrides = []
    st = load_douyin_capability_state()
    cap_items = st.get('items') if isinstance(st.get('items'), dict) else {}
    for key, rec in cap_items.items():
        if isinstance(rec, dict) and rec.get('ready') is False:
            overrides.append((key, rec))
    # Backward compatibility: comment preflight failures recorded before this
    # file existed should still de-green the UI until the user re-authorizes.
    risk = load_comment_risk_state() if 'load_comment_risk_state' in globals() else {}
    risk_last = str(risk.get('lastReason') or '')
    risk_reason = '' if risk_last.startswith('cleared_') else str((risk.get('lastResponse') or {}).get('reason') or risk_last or '')
    risk_age = time.time() - float(risk.get('lastAt') or 0)
    if risk_reason in ('comment_login_required', 'comment_input_not_ready', 'preflight_blocked') and risk_age < 86400:
        overrides.append(('commentWrite', {
            'reason': risk_reason,
            'requiresReauth': risk_reason == 'comment_login_required',
            'updatedAt': risk.get('lastAt') or time.time(),
            'proof': risk.get('lastResponse') or {},
        }))
    for key, rec in overrides:
        if key not in items:
            continue
        items[key] = dict(items[key])
        items[key].update({
            'ready': False,
            'status': 'needs_auth' if rec.get('requiresReauth') else 'blocked',
            'reason': rec.get('reason') or 'runtime_probe_failed',
            'requiresReauth': bool(rec.get('requiresReauth')),
            'lastProbeAt': rec.get('updatedAt'),
            'proof': rec.get('proof') or {},
        })
    ready_count = len([c for c in items.values() if c.get('ready')])
    caps['readyCount'] = ready_count
    caps['total'] = len(items)
    caps['ready'] = ready_count == len(items)
    caps['runtimeChecked'] = bool(overrides)
    caps['runtimeStateUpdatedAt'] = st.get('updatedAt') or risk.get('lastAt')
    return caps


def douyin_capabilities(auth=None, cookie_cache=None, profile_dir=None):
    """Unified capability model for one Douyin account/profile.

    A single browser profile is the source of truth.  The UI should present this
    as one authorization; these capability flags are internal readiness checks,
    not separate user logins.
    """
    auth = auth or ensure_auth_from_cache()
    cookie_str = auth_to_cookie_str(auth)
    cache = cookie_cache if isinstance(cookie_cache, dict) else load_cookie_cache()
    login_ready = bool(auth and getattr(auth, 'cookie', None) and cookie_str_has_login(cookie_str))
    security_ready = bool((cache.get('web_protect') or '') and (cache.get('keys') or ''))
    # Playwright/Profile flows can use the same persisted browser context for
    # both client interaction and creator publishing.  Security SDK material
    # improves publish/comment stability, but lack of it should not force a
    # second user login when the profile itself is authenticated.
    publish_ready = bool(login_ready)
    interact_ready = bool(login_ready)
    caps = {
        'search': _capability('search', '\u641c\u7d22\u89c6\u9891', interact_ready, 'www.douyin.com'),
        'commentRead': _capability('commentRead', '\u67e5\u770b\u8bc4\u8bba', interact_ready, 'www.douyin.com'),
        'commentWrite': _capability('commentWrite', '\u53d1\u9001\u8bc4\u8bba', interact_ready, 'www.douyin.com', '' if interact_ready else 'login_required'),
        'publish': _capability('publish', '\u53d1\u5e03\u89c6\u9891', publish_ready, 'creator.douyin.com', '' if publish_ready else 'creator_cookie_required'),
    }
    ready_count = len([c for c in caps.values() if c.get('ready')])
    caps_out = {
        'profileUnified': True,
        'profileDir': profile_dir or os.getenv('DY_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_profile')),
        'cookieReady': login_ready,
        'cookieCount': len(getattr(auth, 'cookie', {}) or {}) if auth else 0,
        'hasSecuritySdk': security_ready,
        'ready': ready_count == len(caps),
        'readyCount': ready_count,
        'total': len(caps),
        'items': caps,
    }
    return apply_douyin_capability_overrides(caps_out)


def load_cookie_cache(account_id=None):
    path = douyin_account_paths(account_id)['authCache'] if account_id else AUTH_CACHE_JSON
    data = _load_json(path, {})
    return data if isinstance(data, dict) else {}


def save_cookie_cache(cookie_str, source='unknown', web_protect='', keys='', account_id=None):
    """持久化发布 Cookie，解决 API 重启后 STATE 丢失导致重复扫码。"""
    if not cookie_str:
        return
    path = douyin_account_paths(account_id)['authCache'] if account_id else AUTH_CACHE_JSON
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _save_json(path, {
        'cookie': cookie_str,
        'source': source,
        'savedAt': time.time(),
        'hasLoginCookie': cookie_str_has_login(cookie_str),
        'web_protect': web_protect or '',
        'keys': keys or '',
        'hasSecurityKeys': bool(web_protect and keys),
    })


def default_settings():
    return {'perAccountPerDay': 1, 'intervalMin': 60, 'enabled': False}


# 内存为唯一权威数据源（启动时从磁盘载入），改动后回写磁盘做持久化。
# 不每次「从磁盘读改写」：Windows 下对刚写入文件的二次读取可能拿到旧内容，
# 串行锁也救不了（已实测确认）；用内存做真相、磁盘仅持久化，彻底规避读后写不一致。
def _init_mem():
    lib = _load_json(LIBRARY_JSON, [])
    queue = _load_json(PUBLISH_QUEUE_JSON, [])
    settings = _load_json(PUBLISH_SETTINGS_JSON, None)
    queue = queue if isinstance(queue, list) else []
    # 启动对账：上次崩溃/重启时残留的 'running' 不可能还在发布，重置为 pending 让其重试
    for j in queue:
        if j.get('status') == 'running':
            j['status'] = 'pending'
    return {
        'library': lib if isinstance(lib, list) else [],
        'queue': queue,
        'settings': settings if isinstance(settings, dict) else default_settings(),
    }


_MEM = _init_mem()


def load_library():
    with STATE_LOCK:
        return list(_MEM['library'])


def save_library(lib):
    with STATE_LOCK:
        _MEM['library'] = list(lib)
        _save_json(LIBRARY_JSON, _MEM['library'])


def library_upload_metadata(fields):
    fields = fields if isinstance(fields, dict) else {}
    out = {}
    for key in (
        'platform', 'body', 'status', 'sourceTitle', 'sourceBody',
        'replacementJobId', 'sourceTemplateId', 'localDraftMaterialId',
    ):
        value = str(fields.get(key) or '').strip()
        if value:
            out[key] = value
    for key in ('tags', 'sourceTags'):
        raw = str(fields.get(key) or '').strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = re.split(r'[,，\s]+', raw)
        if isinstance(parsed, (list, tuple, set)):
            tags = [str(x or '').strip() for x in parsed if str(x or '').strip()]
            if tags:
                out[key] = tags
    if str(fields.get('importedFromXhsNoteReplacement') or '').strip().lower() in ('1', 'true', 'yes', 'on'):
        out['importedFromXhsNoteReplacement'] = True
    return out


def _slot_material_filename(src, mapping=None, ordinal=1, used=None):
    used = used if isinstance(used, set) else set()
    mapping = mapping if isinstance(mapping, dict) else {}
    base = os.path.basename(str(src or '').replace('\\', '/')) or ('image_%02d' % int(ordinal or 1))
    slot_index = mapping.get('slotIndex') or mapping.get('index') or ordinal or 1
    try:
        slot_prefix = '%02d' % max(1, int(slot_index))
    except Exception:
        slot_prefix = '%02d' % max(1, int(ordinal or 1))
    candidate = '%s_%s' % (slot_prefix, base)
    stem, ext = os.path.splitext(candidate)
    counter = 2
    while candidate in used:
        candidate = '%s_%d%s' % (stem, counter, ext)
        counter += 1
    used.add(candidate)
    return candidate


def _copy_material_file(src, dst):
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    try:
        shutil.copy2(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def load_settings():
    with STATE_LOCK:
        return dict(_MEM['settings'])


def save_settings(s):
    with STATE_LOCK:
        _MEM['settings'] = dict(s)
        _save_json(PUBLISH_SETTINGS_JSON, _MEM['settings'])


def load_queue():
    with STATE_LOCK:
        return list(_MEM['queue'])


def save_queue(q):
    with STATE_LOCK:
        _MEM['queue'] = list(q)
        _save_json(PUBLISH_QUEUE_JSON, _MEM['queue'])


def current_accounts():
    """Return accounts and internal capability state from the current profile/cookie."""
    accounts = []
    registry = load_douyin_accounts()
    if registry:
        for row in registry:
            if account_disabled(row.get('id')):
                continue
            cache = load_cookie_cache(row.get('id'))
            cookie_str = (cache.get('cookie') or '').strip()
            auth = DouyinAuth()
            if cookie_str:
                auth.perepare_auth(cookie_str, cache.get('web_protect') or '', cache.get('keys') or '')
            caps = douyin_capabilities(
                auth,
                cookie_cache=cache,
                profile_dir=row.get('profileDir') or douyin_account_paths(row.get('id'))['profileDir'],
            )
            ready = bool(caps.get('cookieReady'))
            out = dict(row)
            out.update({
                'platform': 'douyin',
                'cookieReady': ready,
                'cookieCount': caps.get('cookieCount', row.get('cookieCount', 0)),
                'usable': bool(ready and caps.get('ready')),
                'online': ready,
                'status': 'online' if ready else 'offline',
                'needLogin': not ready,
                'capabilities': caps,
            })
            out = apply_account_display_meta(out)
            accounts.append(out)
    else:
        if account_disabled('douyin-self'):
            auth = None
            douyin_cookie_ready = False
        else:
            auth = ensure_auth_from_cache()
            caps = douyin_capabilities(auth)
            douyin_cookie_ready = bool(caps.get('cookieReady'))
        if not account_disabled('douyin-self'):
            accounts.append(apply_account_display_meta({
                'id': 'douyin-self',
                'platform': 'douyin',
                'name': os.getenv('DY_ACCOUNT_NAME', '\u6296\u97f3\u8d26\u53f7'),
                'handle': '',
                'fans': '',
                'avatar': '',
                'cookieReady': douyin_cookie_ready,
                'cookieCount': caps.get('cookieCount', 0),
                'usable': bool(douyin_cookie_ready and caps.get('ready')),
                'online': douyin_cookie_ready,
                'status': 'online' if douyin_cookie_ready else 'offline',
                'needLogin': not douyin_cookie_ready,
                'capabilities': caps,
                'profileDir': os.getenv('DY_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_profile')),
            }))
    if xhs_profile_ready(DATA_DIR):
        xhs_caps = {
            'profileUnified': True,
            'ready': True,
            'readyCount': 4,
            'total': 4,
            'items': {
                'search': _capability('search', '\u641c\u7d22\u7b14\u8bb0', True, 'xiaohongshu.com'),
                'commentRead': _capability('commentRead', '\u67e5\u770b\u8bc4\u8bba', True, 'xiaohongshu.com'),
                'commentWrite': _capability('commentWrite', '\u53d1\u9001\u8bc4\u8bba', True, 'xiaohongshu.com'),
                'publish': _capability('publish', '\u53d1\u5e03\u5185\u5bb9', True, 'creator.xiaohongshu.com'),
            }
        }
        accounts.append(apply_account_display_meta({
            'id': 'xhs-self',
            'platform': 'xhs',
            'name': os.getenv('XHS_ACCOUNT_NAME', '\u5c0f\u7ea2\u4e66\u8d26\u53f7'),
            'handle': '',
            'fans': '',
            'avatar': '',
            'cookieReady': True,
            'cookieCount': 1,
            'usable': True,
            'capabilities': xhs_caps,
        }))
    return accounts
def find_material(mid):
    for m in load_library():
        if m.get('id') == mid:
            return m
    return None


def material_files(m):
    files = [os.path.join(MATERIALS_DIR, m['id'], fn) for fn in (m.get('files') or [])]
    return [f for f in files if os.path.exists(f)]


def stage_central_material(mp):
    """把中央调度服务传下来的素材落到执行节点本地。

    云端商业版中，用户上传素材进入 central；真正发布在 execution node。
    如果节点只查本地 library，会出现 material_not_found。这里按 centralMaterial
    的文件 URL 下载一份到节点沙箱，再复用现有 run_publish。
    """
    if not isinstance(mp, dict) or not mp.get('id'):
        return None
    mid = str(mp.get('id') or '').strip()
    existing = find_material(mid)
    if existing and material_files(existing):
        return existing
    import requests
    central_base = (
        os.getenv('MATRIX_CENTRAL_URL')
        or os.getenv('CENTRAL_API_URL')
        or os.getenv('MATRIXSHIP_CENTRAL_URL')
        or 'http://127.0.0.1:9080'
    ).rstrip('/') + '/'
    mdir = os.path.join(MATERIALS_DIR, mid)
    os.makedirs(mdir, exist_ok=True)
    saved = []
    for idx, f in enumerate(mp.get('files') or []):
        name = os.path.basename(str(f.get('name') or ('file_%d' % idx)).replace('\\', '/')) or ('file_%d' % idx)
        rel = str(f.get('url') or '').strip()
        if not rel:
            continue
        url = rel if rel.startswith('http') else urljoin(central_base, rel.lstrip('/'))
        r = requests.get(url, timeout=90)
        r.raise_for_status()
        with open(os.path.join(mdir, name), 'wb') as out:
            out.write(r.content)
        saved.append(name)
    if not saved:
        return None
    item = {
        'id': mid,
        'title': mp.get('title') or saved[0],
        'type': mp.get('type') or 'video',
        'files': saved,
        'urls': ['/api/library/file/%s/%s' % (mid, fn) for fn in saved],
        'published': 0,
        'createdAt': time.time(),
        'stagedFromCentral': True,
    }
    for key in (
        'platform', 'body', 'tags', 'status', 'sourceTitle', 'sourceBody', 'sourceTags',
        'replacementJobId', 'sourceTemplateId', 'localDraftMaterialId',
        'importedFromXhsNoteReplacement',
    ):
        if key in mp:
            item[key] = mp.get(key)
    with STATE_LOCK:
        lib = [x for x in load_library() if x.get('id') != mid]
        lib.insert(0, item)
        save_library(lib)
    return item


def _fmt_count(v):
    try:
        n = int(v or 0)
    except Exception:
        return str(v or '')
    if n >= 100000000:
        return ('%.1f亿' % (n / 100000000.0)).rstrip('0').rstrip('.')
    if n >= 10000:
        return ('%.1f万' % (n / 10000.0)).rstrip('0').rstrip('.')
    return str(n)


def classify_comment_intent(text):
    """给寻客中心用的轻量意向分类；只影响客户端标签，不改变原始评论。"""
    t = (text or '').lower()
    high = ['求链接', '链接', '怎么买', '哪里买', '在哪买', '多少钱', '价格', '优惠', '下单', '购买', '同款', '怎么买']
    mid = ['收藏', '蹲', '想试', '想要', '不错', '种草', '看着', '心动', '安排']
    consult = ['吗', '？', '?', '怎么', '能用', '适合', '敏感肌', '会不会', '哪个', '区别', '多久']
    if any(k in t for k in high):
        return '高意向'
    if any(k in t for k in mid):
        return '中意向'
    if any(k in t for k in consult):
        return '咨询'
    return '普通'


def normalize_comment(comment, level=1, parent_id=''):
    """把 Douyin 原始评论压成客户端寻客中心需要的稳定字段。"""
    comment = comment or {}
    user = comment.get('user') or {}
    text = comment.get('text') or comment.get('share_info', {}).get('share_desc') or ''
    cid = str(comment.get('cid') or comment.get('comment_id') or uuid.uuid4().hex)
    nickname = user.get('nickname') or user.get('unique_id') or user.get('short_id') or '抖音用户'
    unique_id = user.get('unique_id') or user.get('short_id') or ''
    sec_uid = user.get('sec_uid') or user.get('secUid') or comment.get('sec_uid') or ''
    profile_url = ('https://www.douyin.com/user/' + sec_uid) if sec_uid else ''
    avatar = ''
    try:
        avatar = (user.get('avatar_thumb') or {}).get('url_list', [''])[0]
    except Exception:
        avatar = ''
    return {
        'id': cid,
        'parentId': parent_id,
        'level': level,
        'text': text,
        'user': nickname,
        'uniqueId': unique_id,
        'secUid': sec_uid,
        'profileUrl': profile_url,
        'userUrl': profile_url,
        'user_url': profile_url,
        'fans': _fmt_count(user.get('follower_count') or user.get('mplatform_followers_count') or 0),
        'avatar': avatar,
        'intent': classify_comment_intent(text),
        'diggCount': comment.get('digg_count') or 0,
        'replyCount': comment.get('reply_comment_total') or 0,
        'ip': comment.get('ip_label') or comment.get('ip_location') or '',
        'createTime': comment.get('create_time') or 0,
        'awemeId': comment.get('aweme_id') or '',
    }


def normalize_comments(comments, limit=200):
    if isinstance(comments, dict):
        comments = comments.get('comments') or comments.get('data') or comments.get('items') or []
    items = []
    for c in comments or []:
        if not isinstance(c, dict):
            continue
        item = normalize_comment(c, level=1)
        items.append(item)
        for r in (c.get('reply_comment') or []):
            if not isinstance(r, dict):
                continue
            items.append(normalize_comment(r, level=2, parent_id=item['id']))
        if len(items) >= limit:
            break
    return items[:limit]


def normalize_search_item_aliases(item):
    """Expose stable aliases used by API callers and action endpoints."""
    if not isinstance(item, dict):
        return item
    work_id = str(item.get('work_id') or item.get('aweme_id') or item.get('awemeId') or item.get('id') or '')
    work_url = item.get('work_url') or item.get('url') or (('https://www.douyin.com/video/' + work_id) if work_id else '')
    if work_id:
        item.setdefault('work_id', work_id)
        item.setdefault('aweme_id', work_id)
        item.setdefault('awemeId', work_id)
        item.setdefault('id', work_id)
    if work_url:
        item.setdefault('work_url', work_url)
        item.setdefault('url', work_url)
    return item


def normalize_douyin_search_results(raw, limit=20):
    """Normalize Douyin search responses from API/browser JSON into work_info rows."""
    candidates = []

    def walk(obj, depth=0):
        if depth > 8 or obj is None:
            return
        if isinstance(obj, dict):
            for key in ('aweme_info', 'aweme_detail', 'aweme'):
                val = obj.get(key)
                if isinstance(val, dict):
                    candidates.append(val)
                    walk(val, depth + 1)
            if (obj.get('aweme_id') or obj.get('group_id') or obj.get('item_id')) and (
                obj.get('video') or obj.get('images') or obj.get('statistics') or obj.get('author') or obj.get('desc')
            ):
                candidates.append(obj)
            for key in ('data', 'items', 'aweme_list', 'search_result', 'list', 'mix_infos'):
                if key in obj:
                    walk(obj.get(key), depth + 1)
            for key in ('business_data', 'raw_data'):
                val = obj.get(key)
                if isinstance(val, str) and val and len(val) < 2_000_000:
                    try:
                        walk(json.loads(val), depth + 1)
                    except Exception:
                        pass
        elif isinstance(obj, list):
            for val in obj:
                walk(val, depth + 1)

    walk(raw)
    items = []
    seen = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        aweme = item.get('aweme_info') if isinstance(item.get('aweme_info'), dict) else item
        if not isinstance(aweme, dict):
            continue
        try:
            info = handle_work_info(aweme)
        except Exception:
            info = safe_work_info(aweme)
        work_id = str(info.get('work_id') or extract_aweme_id(info.get('work_url')) or '')
        if work_id and work_id not in seen:
            seen.add(work_id)
            if not info.get('work_url'):
                info['work_url'] = 'https://www.douyin.com/video/' + work_id
            normalize_search_item_aliases(info)
            items.append(info)
        if len(items) >= limit:
            break
    return items[:limit]


def douyin_search_cache_key(keyword, limit=20):
    return '%s|%s' % ((keyword or '').strip(), int(limit or 20))


def save_douyin_search_cache(keyword, limit, items, source='search'):
    if not keyword or not items:
        return
    try:
        cache = _load_json(DOUYIN_SEARCH_CACHE_JSON, {})
        if not isinstance(cache, dict):
            cache = {}
        lim = int(limit or 20)
        key = douyin_search_cache_key(keyword, lim)
        payload = {
            'keyword': keyword,
            'limit': lim,
            'items': items[:lim],
            'count': len(items[:lim]),
            'source': source,
            'savedAt': time.time(),
        }
        cache[key] = payload
        cache[(keyword or '').strip()] = payload
        _save_json(DOUYIN_SEARCH_CACHE_JSON, cache)
    except Exception:
        pass


def load_douyin_search_cache(keyword, limit=20, ttl_sec=None):
    keyword = (keyword or '').strip()
    if not keyword:
        return None
    if ttl_sec is None:
        ttl_sec = int(os.getenv('DY_SEARCH_CACHE_TTL_SEC', '86400') or 86400)
    try:
        cache = _load_json(DOUYIN_SEARCH_CACHE_JSON, {})
        if not isinstance(cache, dict):
            return None
        item = cache.get(douyin_search_cache_key(keyword, limit)) or cache.get(keyword)
        if not isinstance(item, dict):
            return None
        age = time.time() - float(item.get('savedAt') or 0)
        if ttl_sec > 0 and age > ttl_sec:
            return None
        items = item.get('items') or []
        if not items:
            return None
        out = dict(item)
        out['ageSec'] = round(age, 3)
        out['items'] = [normalize_search_item_aliases(dict(x)) if isinstance(x, dict) else x for x in items[:int(limit or 20)]]
        out['count'] = len(out['items'])
        return out
    except Exception:
        return None


def _first_url(obj):
    try:
        urls = (obj or {}).get('url_list') or []
        if isinstance(urls, str):
            return urls.split(' ')[0]
        return urls[0] if urls else ''
    except Exception:
        return ''


def safe_work_info(data):
    """搜索结果字段在不同接口版本下会缺 images/video 等字段；这里给客户端兜底。"""
    data = data or {}
    author = data.get('author') or {}
    stats = data.get('statistics') or {}
    video = data.get('video') or {}
    aweme_id = str(data.get('aweme_id') or data.get('group_id') or data.get('item_id') or '')
    images = data.get('images') or []
    if not isinstance(images, list):
        images = []
    cover = _first_url(video.get('cover')) or _first_url(video.get('origin_cover')) or _first_url(video.get('dynamic_cover'))
    play = _first_url(video.get('play_addr')) or _first_url(video.get('download_addr'))
    sec_uid = author.get('sec_uid') or ''
    duration = data.get('duration') or data.get('duration_sec') or video.get('duration') or video.get('duration_sec') or 0
    try:
        duration = float(duration or 0)
        if duration > 10000:
            duration = duration / 1000.0
    except (TypeError, ValueError):
        duration = 0
    return {
        'work_id': aweme_id,
        'work_url': ('https://www.douyin.com/video/' + aweme_id) if aweme_id else '',
        'work_type': '图集' if data.get('aweme_type') == 68 else '视频',
        'title': data.get('desc') or data.get('item_title') or aweme_id or '无标题',
        'desc': data.get('desc') or '',
        'admire_count': stats.get('admire_count') or 0,
        'digg_count': stats.get('digg_count') or 0,
        'comment_count': stats.get('comment_count') or 0,
        'collect_count': stats.get('collect_count') or 0,
        'share_count': stats.get('share_count') or 0,
        'duration': duration,
        'video_addr': play,
        'images': images,
        'topics': [],
        'create_time': data.get('create_time') or 0,
        'video_cover': cover,
        'user_url': ('https://www.douyin.com/user/' + sec_uid) if sec_uid else '',
        'user_id': author.get('unique_id') or author.get('short_id') or '',
        'nickname': author.get('nickname') or '未知作者',
        'author_avatar': _first_url(author.get('avatar_thumb')),
        'user_desc': author.get('signature') or '',
        'following_count': author.get('following_count') or 0,
        'follower_count': author.get('follower_count') or 0,
        'total_favorited': author.get('total_favorited') or 0,
        'aweme_count': author.get('aweme_count') or 0,
        'user_age': author.get('user_age') or '',
        'gender': author.get('gender') or '',
        'ip_location': data.get('ip_label') or data.get('ip_location') or '',
    }


def _seed_login_state_into_profile(dest, login_profile=None):
    """把持久化登录态(cookie + localStorage)播种到一个全新的搜索用临时 profile。

    抖音网页搜索页不仅看 cookie，还看 localStorage(HasUserLogin / webid 等)判断登录态；
    只注入 cookie 的空 profile 会弹「登录后即可搜索」二维码墙。这里从登录 profile
    (DY_PROFILE_DIR) 复制关键登录文件到临时 profile，使搜索浏览器天然处于已登录态，
    且因为每次搜索用独立临时副本、不锁登录 profile，可完全并发。
    """
    try:
        login_profile = os.path.abspath(login_profile or os.getenv('DY_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_profile')))
        if not os.path.isdir(login_profile):
            return False
        # 经实测验证可过登录墙的最小文件集(不含体积大的 IndexedDB)
        rels = [
            'Local State',
            'Default/Preferences',
            'Default/Secure Preferences',
            'Default/Cookies',
            'Default/Cookies-journal',
            'Default/Network',            # 新版 Chromium 的 Cookies 存这里
            'Default/Local Storage',      # 关键:HasUserLogin / webid 等登录态
            'Default/Session Storage',
            'Default/Web Data',
        ]
        copied = 0
        _ignore = shutil.ignore_patterns('LOCK', 'LOG', 'LOG.old', '*.lock')
        for rel in rels:
            src = os.path.join(login_profile, rel)
            dst = os.path.join(dest, rel)
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=_ignore)
                    copied += 1
                elif os.path.isfile(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    copied += 1
            except Exception:
                continue
        return copied > 0
    except Exception:
        return False


def _resolve_douyin_dm_login_source(account_id=''):
    requested = _safe_account_key(account_id or '') if '_safe_account_key' in globals() else str(account_id or '').strip()
    if requested and requested not in ('default', 'douyin-self'):
        candidates = [requested]
    else:
        default_id = default_douyin_comment_account_id('')
        candidates = [x for x in (default_id, 'douyin-self') if x]
    seen = set()
    checks = []
    for candidate in candidates:
        candidate = _safe_account_key(candidate or 'douyin-self') if '_safe_account_key' in globals() else (candidate or 'douyin-self')
        if candidate in seen:
            continue
        seen.add(candidate)
        paths = douyin_account_paths(candidate)
        cache = load_cookie_cache(candidate if candidate not in ('douyin-self', 'default') else None)
        cookie_str = str(cache.get('cookie') or '').strip()
        profile_dir = os.path.abspath(paths.get('profileDir') or '')
        ready = bool(cookie_str_has_login(cookie_str) and os.path.isdir(profile_dir))
        checks.append({
            'accountId': candidate,
            'profileDir': profile_dir,
            'profileExists': os.path.isdir(profile_dir),
            'hasLoginCookie': cookie_str_has_login(cookie_str),
        })
        if ready:
            return {
                'ok': True,
                'accountId': candidate,
                'profileDir': profile_dir,
                'authCache': paths.get('authCache') or '',
                'checks': checks,
            }
    return {
        'ok': False,
        'error': 'dm_login_profile_not_ready',
        'accountId': requested or '',
        'needLogin': True,
        'checks': checks,
    }


def browser_search_videos(keyword, max_videos=5, cookie_dict=None):
    """Browser fallback for Douyin search: inject cookie, parse search API responses, then DOM links."""
    from playwright.sync_api import sync_playwright

    keyword = (keyword or '').strip()
    max_videos = max(1, min(int(max_videos or 5), 20))
    if os.getenv('DY_SEARCH_CHILD', '').strip() != '1' and os.getenv('DY_SEARCH_ISOLATED', '1').strip().lower() not in ('0', 'false', 'no', 'off'):
        child_env = os.environ.copy()
        child_env['DY_SEARCH_CHILD'] = '1'
        child_env.setdefault('MATRIX_AGENT_DATA_DIR', DATA_DIR)
        child_env.setdefault('DY_DATA_DIR', DATA_DIR)
        child_env['DY_SEARCH_KEYWORD_B64'] = base64.b64encode(keyword.encode('utf-8')).decode('ascii')
        child_env['DY_SEARCH_LIMIT'] = str(max_videos)
        child_code = r"""
import base64, json, os, sys
os.chdir(r'__BACKEND_DIR__')
sys.path.insert(0, r'__BACKEND_DIR__')
kw = base64.b64decode(os.environ.get('DY_SEARCH_KEYWORD_B64', '')).decode('utf-8')
limit = int(os.environ.get('DY_SEARCH_LIMIT', '5') or '5')
import api_server
auth = api_server.require_auth()
items = api_server.browser_search_videos(kw, limit, getattr(auth, 'cookie', None))
print('__MATRIX_SEARCH_JSON__' + json.dumps({'ok': True, 'items': items}, ensure_ascii=False))
""".replace('__BACKEND_DIR__', os.path.dirname(os.path.abspath(__file__)).replace('\\', '\\\\'))
        try:
            child_cmd = [sys.executable, '-c', child_code]
            xvfb = shutil.which('xvfb-run')
            if os.name != 'nt' and xvfb and os.getenv('DY_SEARCH_CHILD_XVFB', '1').strip().lower() not in ('0', 'false', 'no', 'off'):
                child_cmd = [xvfb, '-a', '-s', '-screen 0 1280x900x24'] + child_cmd
            proc = subprocess.run(
                child_cmd,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=child_env,
                capture_output=True,
                text=True,
                timeout=int(os.getenv('DY_SEARCH_CHILD_TIMEOUT', '180') or '180'),
            )
            if os.getenv('DY_SEARCH_DEBUG', '').strip().lower() in ('1', 'true', 'yes', 'on'):
                try:
                    os.makedirs(os.path.join(DATA_DIR, 'debug'), exist_ok=True)
                    _save_json(os.path.join(DATA_DIR, 'debug', 'douyin_search_isolated_parent.json'), {
                        'returncode': proc.returncode,
                        'cmd': child_cmd[:4] + ['...'],
                        'stdoutTail': (proc.stdout or '')[-4000:],
                        'stderrTail': (proc.stderr or '')[-4000:],
                    })
                except Exception:
                    pass
            marker = '__MATRIX_SEARCH_JSON__'
            if marker in (proc.stdout or ''):
                payload = (proc.stdout or '').rsplit(marker, 1)[1].strip().splitlines()[0]
                data = json.loads(payload)
                return data.get('items') or []
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or proc.stdout or 'isolated_search_failed')[-1200:])
        except Exception:
            # Fall back to in-process browser search; caller will receive normal errors if it fails.
            pass
    edge_exe = os.getenv('DY_EDGE_PATH', r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    profile_base = os.path.abspath(os.getenv('DY_SEARCH_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_search_profile')))
    os.makedirs(profile_base, exist_ok=True)
    reuse_profile = os.getenv('DY_SEARCH_REUSE_PROFILE', '').strip().lower() in ('1', 'true', 'yes', 'on')
    profile_dir = profile_base if reuse_profile else tempfile.mkdtemp(prefix='session_', dir=profile_base)
    seeded_login = False
    if not reuse_profile:
        # 用登录 profile 的登录态(含 localStorage)播种，避免搜索页弹二维码登录墙
        seeded_login = _seed_login_state_into_profile(profile_dir)
    args = [
        '--disable-blink-features=AutomationControlled',
        '--disable-infobars',
        '--no-first-run',
        '--no-default-browser-check',
        '--lang=zh-CN',
        '--no-sandbox',
        '--disable-dev-shm-usage',
    ]
    url = 'https://www.douyin.com/search/%s?type=video' % quote(keyword)
    videos = []
    debug = {'keyword': keyword, 'url': url, 'events': []}

    def save_debug():
        if os.getenv('DY_SEARCH_DEBUG', '').strip().lower() not in ('1', 'true', 'yes', 'on'):
            return
        try:
            os.makedirs(os.path.join(DATA_DIR, 'debug'), exist_ok=True)
            _save_json(os.path.join(DATA_DIR, 'debug', 'douyin_search_runtime.json'), debug)
        except Exception:
            pass

    def add_videos(found):
        for v in found or []:
            if not isinstance(v, dict):
                continue
            work_id = str(v.get('work_id') or extract_aweme_id(v.get('work_url')) or '')
            if not work_id:
                continue
            if not v.get('work_url'):
                v['work_url'] = 'https://www.douyin.com/video/' + work_id
            v['work_id'] = work_id
            normalize_search_item_aliases(v)
            if not any(x.get('work_id') == work_id for x in videos):
                videos.append(v)
            if len(videos) >= max_videos:
                return

    with sync_playwright() as p:
        kw = dict(
            headless=os.getenv('DY_SEARCH_HEADLESS', '').strip().lower() in ('1', 'true', 'yes', 'on'),
            args=args,
            ignore_default_args=['--enable-automation'],
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            viewport={'width': 1280, 'height': 900},
        )
        if edge_exe and os.path.exists(edge_exe):
            kw['executable_path'] = edge_exe
        ctx = p.chromium.launch_persistent_context(profile_dir, **kw)
        try:
            # 已从登录 profile 播种(含正确作用域的 Cookies + localStorage)时，
            # 不要再叠加强制 .douyin.com 域的 cookie —— 那会污染登录态导致搜索被风控。
            if cookie_dict and not seeded_login:
                cookies = []
                for k, v in (cookie_dict or {}).items():
                    if str(k).lower() == 'mstoken':
                        continue
                    cookies.append({'name': k, 'value': str(v), 'domain': '.douyin.com', 'path': '/'})
                try:
                    ctx.add_cookies(cookies)
                except Exception:
                    pass
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            def on_response(resp):
                if len(videos) >= max_videos:
                    return
                resp_url = resp.url or ''
                if 'douyin.com' not in resp_url:
                    return
                if not (
                    '/aweme/v1/web/search/item/' in resp_url
                    or '/aweme/v1/web/general/search/' in resp_url
                    or '/aweme/v1/web/discover/search' in resp_url
                ):
                    return
                try:
                    data = resp.json()
                except Exception:
                    return
                parsed = normalize_douyin_search_results(data, max_videos)
                debug['events'].append({'type': 'api-response', 'url': resp_url[:220], 'parsed': len(parsed), 'keys': list(data.keys())[:20] if isinstance(data, dict) else type(data).__name__})
                add_videos(parsed)

            page.on('response', on_response)
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            try:
                page.wait_for_load_state('networkidle', timeout=15000)
            except Exception:
                pass
            try:
                page.wait_for_selector('a[href*="/video/"], a[href*="modal_id="]', timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            try:
                debug['title'] = page.title()
                debug['pageUrl'] = page.url
                debug['linkCountBeforeLoop'] = page.locator('a[href]').count()
                debug['videoLinkCountBeforeLoop'] = page.locator('a[href*="/video/"]').count()
                debug['linksBeforeLoop'] = page.evaluate("""() => Array.from(document.querySelectorAll('a[href]')).filter(a=>/video|modal_id/.test(a.href)).slice(0,10).map(a=>({href:a.href,text:(a.innerText||a.textContent||'').replace(/\s+/g,' ').trim().slice(0,80)}))""")
            except Exception as e:
                debug['preLoopError'] = str(e)
            for loop_idx in range(6):
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(1500)
                found = page.evaluate(
                    """(maxN) => {
                      const out = [];
                      const seen = new Set();
                      const push = (href, title, cover, author) => {
                        if (!href) return;
                        let id = '';
                        try {
                          const u = new URL(href, location.href);
                          href = u.href;
                          const m1 = href.match(/\/video\/(\d+)/);
                          const m2 = href.match(/[?&]modal_id=(\d+)/);
                          id = (m1 && m1[1]) || (m2 && m2[1]) || '';
                        } catch (_) {}
                        if (!id || seen.has(id)) return;
                        seen.add(id);
                        out.push({work_id:id, work_url:'https://www.douyin.com/video/'+id, title:title||id, video_cover:cover||'', nickname:author||'', work_type:'??'});
                      };
                      for (const a of Array.from(document.querySelectorAll('a[href]'))) {
                        const href = a.href || '';
                        if (!(/\/video\//.test(href) || /modal_id=\d+/.test(href))) continue;
                        const txt = (a.innerText || a.textContent || '').replace(/\s+/g,' ').trim();
                        const img = a.querySelector('img');
                        const cover = img && (img.currentSrc || img.src) || '';
                        push(href, txt.slice(0,120), cover, '');
                        if (out.length >= maxN) break;
                      }
                      return out;
                    }""",
                    max_videos,
                )
                debug['events'].append({'type': 'dom-loop', 'loop': loop_idx, 'found': len(found or []), 'total': len(videos)})
                add_videos(found)
                if len(videos) >= max_videos:
                    break
        finally:
            try:
                debug['finalCount'] = len(videos)
                debug['finalItems'] = videos[:max_videos]
                save_debug()
            finally:
                ctx.close()
                if not reuse_profile:
                    shutil.rmtree(profile_dir, ignore_errors=True)
    return videos[:max_videos]


def _python_c_child_cmd():
    override = (os.getenv('MATRIX_PYTHON_EXE') or os.getenv('PYTHON_EXE') or '').strip()
    candidates = [override, sys.executable]
    for exe in candidates:
        exe = str(exe or '').strip()
        if not exe:
            continue
        base = os.path.basename(exe).lower()
        if base.startswith('python') or base in ('py.exe', 'py'):
            return [exe, '-c']
    return None


def _is_douyin_dm_button_label(label):
    normalized = ''.join(str(label or '').replace('\n', ' ').split())
    return any(normalized == expected * repeat
               for expected in ('私信', '发私信', '发消息')
               for repeat in range(1, 5))


def _douyin_dm_context_cookies(cookie_str):
    cookie_dict = parse_cookie_dict(cookie_str or '')
    return [
        {'name': str(name), 'value': str(value), 'domain': '.douyin.com', 'path': '/'}
        for name, value in cookie_dict.items()
        if str(name).lower() != 'mstoken'
    ]


def browser_send_dm(target, content, account_id=''):
    """用已登录浏览器给指定抖音用户发私信。

    抖音 IM 的 conversation/create、message/send 用一套只有私信才用的 web_protect ECDSA
    签名(reuqest_sign/ts_sign/client_cert),纯 Python 复刻极易被判 INVALID_REQUEST。
    这里改用「已登录 profile 的真实浏览器 + 抖音自有 JS 签名」直接在网页 IM 里发消息,
    与搜索同一套 seeded profile 方案,天然过签名、跨账号并发安全、契合本地客户端方向。

    target: 用户主页URL / sec_uid;content: 文本内容。返回 dict。
    """
    target = (target or '').strip()
    content = (content or '').strip()
    if not target or not content:
        return {'ok': False, 'error': 'missing_target_or_content'}
    if target.startswith('http'):
        profile_url = target
    elif not target.isdigit():
        profile_url = 'https://www.douyin.com/user/' + target
    else:
        # 网页私信要主页地址;纯数字 uid 无法直接定位主页
        return {'ok': False, 'error': 'numeric_uid_unsupported_in_browser_dm',
                'hint': '请粘贴对方主页链接或 sec_uid'}

    login_source = _resolve_douyin_dm_login_source(account_id)
    if not login_source.get('ok'):
        return {
            'ok': False,
            'error': 'not_authenticated',
            'reason': login_source.get('error') or 'dm_login_profile_not_ready',
            'needLogin': True,
            'accountId': login_source.get('accountId') or account_id or '',
            'dmLoginDiagnostics': login_source,
        }

    # 隔离子进程执行:避免在 ThreadingHTTPServer 处理线程里跑 sync_playwright 的信号/锁问题
    child_cmd = _python_c_child_cmd()
    if os.getenv('DY_DM_CHILD', '').strip() != '1' and os.getenv('DY_DM_ISOLATED', '1').strip().lower() not in ('0', 'false', 'no', 'off') and child_cmd is not None:
        child_env = os.environ.copy()
        child_env['DY_DM_CHILD'] = '1'
        child_env.setdefault('MATRIX_AGENT_DATA_DIR', DATA_DIR)
        child_env.setdefault('DY_DATA_DIR', DATA_DIR)
        child_env['DY_DM_TARGET_B64'] = base64.b64encode(profile_url.encode('utf-8')).decode('ascii')
        child_env['DY_DM_CONTENT_B64'] = base64.b64encode(content.encode('utf-8')).decode('ascii')
        child_env['DY_DM_ACCOUNT_ID'] = str(login_source.get('accountId') or account_id or '')
        child_code = r"""
import base64, json, os, sys, traceback
try:
    os.chdir(r'__BACKEND_DIR__')
    sys.path.insert(0, r'__BACKEND_DIR__')
    import api_server
    t = base64.b64decode(os.environ.get('DY_DM_TARGET_B64', '')).decode('utf-8')
    c = base64.b64decode(os.environ.get('DY_DM_CONTENT_B64', '')).decode('utf-8')
    a = os.environ.get('DY_DM_ACCOUNT_ID', '')
    res = api_server.browser_send_dm(t, c, a)
except Exception as e:
    res = {
        'ok': False,
        'error': 'dm_child_inner_exception',
        'exceptionType': type(e).__name__,
        'message': str(e)[:300],
        'stackTail': traceback.format_exc()[-1200:],
    }
print('__MATRIX_DM_JSON__' + json.dumps(res, ensure_ascii=False))
""".replace('__BACKEND_DIR__', os.path.dirname(os.path.abspath(__file__)).replace('\\', '\\\\'))
        try:
            proc = subprocess.run(
                child_cmd + [child_code],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=child_env, capture_output=True, text=True,
                timeout=int(os.getenv('DY_DM_CHILD_TIMEOUT', '150') or '150'),
            )
            marker = '__MATRIX_DM_JSON__'
            if marker in (proc.stdout or ''):
                payload = (proc.stdout or '').rsplit(marker, 1)[1].strip().splitlines()[0]
                return json.loads(payload)
            return {'ok': False, 'error': 'dm_child_no_json_marker',
                    'returncode': proc.returncode,
                    'stderr': (proc.stderr or '')[-800:],
                    'stdout': (proc.stdout or '')[-400:],
                    'stderrTail': (proc.stderr or '')[-1600:],
                    'stdoutTail': (proc.stdout or '')[-1200:]}
        except Exception as e:
            return {'ok': False, 'error': 'dm_child_exception:' + str(e)}

    edge_exe = os.getenv('DY_EDGE_PATH', r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    profile_base = os.path.abspath(os.getenv('DY_DM_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_dm_profile')))
    os.makedirs(profile_base, exist_ok=True)
    profile_dir = tempfile.mkdtemp(prefix='dm_', dir=profile_base)
    seeded_login = _seed_login_state_into_profile(profile_dir, login_source.get('profileDir'))
    if not seeded_login:
        shutil.rmtree(profile_dir, ignore_errors=True)
        return {
            'ok': False,
            'error': 'not_authenticated',
            'reason': 'dm_login_profile_seed_failed',
            'needLogin': True,
            'accountId': login_source.get('accountId') or account_id or '',
            'dmLoginDiagnostics': {
                'accountId': login_source.get('accountId') or '',
                'profileDir': login_source.get('profileDir') or '',
                'seededLogin': False,
            },
        }

    def disable_chromium_password_prompts(user_data_dir):
        """Keep Chrome/Edge password bubbles from covering Douyin profile actions."""
        prefs_path = os.path.join(user_data_dir, 'Default', 'Preferences')
        try:
            os.makedirs(os.path.dirname(prefs_path), exist_ok=True)
            prefs = {}
            if os.path.isfile(prefs_path):
                try:
                    with open(prefs_path, 'r', encoding='utf-8') as f:
                        prefs = json.load(f)
                except Exception:
                    prefs = {}
            if not isinstance(prefs, dict):
                prefs = {}
            prefs['credentials_enable_service'] = False
            profile = prefs.get('profile')
            if not isinstance(profile, dict):
                profile = {}
            profile['password_manager_enabled'] = False
            prefs['profile'] = profile
            autofill = prefs.get('autofill')
            if not isinstance(autofill, dict):
                autofill = {}
            autofill['profile_enabled'] = False
            prefs['autofill'] = autofill
            with open(prefs_path, 'w', encoding='utf-8') as f:
                json.dump(prefs, f, ensure_ascii=False, separators=(',', ':'))
            return True
        except Exception as e:
            json_log(
                logger,
                'douyin_dm_password_prompt_pref_failed',
                level='warning',
                exceptionType=type(e).__name__,
                message=str(e)[:180],
            )
            return False

    password_prompt_prefs_disabled = disable_chromium_password_prompts(profile_dir)
    from playwright.sync_api import sync_playwright
    args = [
        '--disable-blink-features=AutomationControlled', '--disable-infobars', '--no-first-run',
        '--no-default-browser-check', '--lang=zh-CN', '--no-sandbox', '--disable-dev-shm-usage',
        '--disable-save-password-bubble',
    ]
    state = {'send_fired': False, 'send_status': None}
    result = {
        'ok': False,
        'target': profile_url,
        'accountId': login_source.get('accountId') or account_id or '',
        'passwordPromptPrefsDisabled': password_prompt_prefs_disabled,
    }
    with sync_playwright() as p:
        headless = os.getenv('DY_DM_HEADLESS', '').strip().lower() in ('1', 'true', 'yes', 'on')
        kw = dict(
            headless=headless,
            args=args, ignore_default_args=['--enable-automation'],
            locale='zh-CN', timezone_id='Asia/Shanghai', viewport={'width': 1280, 'height': 900},
        )
        if edge_exe and os.path.exists(edge_exe):
            kw['executable_path'] = edge_exe
        ctx = p.chromium.launch_persistent_context(profile_dir, **kw)
        try:
            dm_cache = load_cookie_cache(login_source.get('accountId') or account_id or '')
            dm_context_cookies = _douyin_dm_context_cookies(dm_cache.get('cookie') or '')
            result['dmCookieInjection'] = {
                'attemptedCount': len(dm_context_cookies),
                'addedCount': 0,
            }
            if dm_context_cookies:
                try:
                    ctx.add_cookies(dm_context_cookies)
                    result['dmCookieInjection']['addedCount'] = len(dm_context_cookies)
                except Exception as e:
                    result['dmCookieInjection']['error'] = type(e).__name__
                    json_log(
                        logger,
                        'douyin_dm_cookie_injection_failed',
                        level='warning',
                        accountId=login_source.get('accountId') or account_id or '',
                        attemptedCount=len(dm_context_cookies),
                        exceptionType=type(e).__name__,
                        message=str(e)[:180],
                    )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            def on_resp(resp):
                if '/v1/message/send' in (resp.url or ''):
                    state['send_fired'] = True
                    try:
                        state['send_status'] = resp.status
                    except Exception:
                        pass
            page.on('response', on_resp)

            page.goto(profile_url, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(5000)
            btn = None
            dm_button_selector = ''
            dm_profile_button_selectors = [
                # Edge and Chrome expose the profile action row with slightly different button indexes.
                'xpath=//*[@id="user_detail_element"]/div/div[2]/div/div[1]/div[3]/div[2]/button[1]',
                'xpath=//*[@id="user_detail_element"]/div/div[2]/div/div[1]/div[3]/div[3]/div[1]/button[2]',
                'xpath=//*[@id="user_detail_element"]//button[normalize-space()="私信"]',
                'xpath=//*[@id="user_detail_element"]//*[normalize-space()="私信" and (@role="button" or self::button or ancestor::button)]',
                'button:has-text("私信")',
                'text=私信',
                'text=发私信',
                'text=发消息',
            ]
            rejected_buttons = []

            def is_dm_button_label(label):
                return _is_douyin_dm_button_label(label)

            def locator_label(loc):
                try:
                    return loc.evaluate(r"""el => String([
                        el.innerText || '',
                        el.textContent || '',
                        el.getAttribute('aria-label') || '',
                        el.getAttribute('title') || ''
                    ].join(' ')).replace(/\s+/g, ' ').trim().slice(0, 120)""")
                except Exception:
                    try:
                        return (loc.inner_text(timeout=1000) or '').strip()
                    except Exception:
                        return ''

            def dismiss_douyin_save_login_prompt():
                save_prompt_click_js = r"""(arg) => {
                    const vw = window.innerWidth || 1280;
                    const vh = window.innerHeight || 900;
                    const visible = el => {
                        if (!el) return false;
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 4 && r.height > 4 &&
                            s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' &&
                        r.bottom > 0 && r.right > 0 && r.left < vw && r.top < vh;
                    };
                    const textOf = el => String([
                        el.innerText || '',
                        el.textContent || '',
                        el.getAttribute('aria-label') || '',
                        el.getAttribute('title') || '',
                        el.getAttribute('class') || ''
                    ].join(' ')).replace(/\s+/g, ' ').trim();
                    const directText = el => String([
                        el.innerText || '',
                        el.textContent || '',
                        el.getAttribute('aria-label') || '',
                        el.getAttribute('title') || ''
                    ].join(' ')).replace(/\s+/g, '').trim();
                    const clickLike = el => {
                        const r = el.getBoundingClientRect();
                        const x = r.left + r.width / 2;
                        const y = r.top + r.height / 2;
                        el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, clientX:x, clientY:y}));
                        el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x, clientY:y}));
                        el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:x, clientY:y}));
                        el.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:x, clientY:y}));
                        try { el.click(); } catch(e) {}
                        return {x:Math.round(x), y:Math.round(y), width:Math.round(r.width), height:Math.round(r.height)};
                    };
                    const nodes = Array.from(document.querySelectorAll('div,section,aside,[role="dialog"],button,[role="button"],span,svg,i'));
                    const promptNodes = nodes.filter(el => visible(el) && /是否保存登录信息|下次登录更便捷|保存登录信息|保存登录状态|保存本次登录|记住登录/.test(textOf(el)));
                    if (!promptNodes.length) return {promptVisible:false, clicked:false, finalPromptVisible:false, candidates:[]};
                    const promptRects = promptNodes.map(el => el.getBoundingClientRect()).filter(r => r.width > 80 && r.height > 20);
                    const nearPrompt = r => {
                        if (!promptRects.length) return true;
                        return promptRects.some(pr =>
                            r.left >= pr.left - 30 && r.right <= pr.right + 30 &&
                            r.top >= pr.top - 80 && r.bottom <= pr.bottom + 140
                        );
                    };
                    const clickableOf = el => el.closest('button,[role="button"]') || el;
                    const dismissWords = ['以后再说', '暂不保存', '不保存', '暂不', '取消', '关闭', '跳过', '稍后', '稍后再说', '下次再说', '知道了', '我知道了'];
                    const saveWords = ['保存', '确认', '确定'];
                    const buttons = [];
                    for (const el of nodes) {
                        if (!visible(el)) continue;
                        const clickable = clickableOf(el);
                        if (!visible(clickable)) continue;
                        const r = clickable.getBoundingClientRect();
                        if (!nearPrompt(r)) continue;
                        const text = directText(clickable);
                        const rawText = textOf(clickable);
                        const lower = rawText.toLowerCase();
                        const isDismiss = dismissWords.some(word => text.includes(word));
                        const isSave = saveWords.some(word => text === word || text.includes(word));
                        const isCloseIcon = (text === '×' || text === 'x' || lower.includes('close')) &&
                            r.width <= 80 && r.height <= 80;
                        if (!isDismiss && !isSave && !isCloseIcon) continue;
                        if (r.width > 220 || r.height > 100) continue;
                        let score = 0;
                        if (isDismiss) score += 260;
                        if (isCloseIcon) score += 240;
                        if (isSave) score += 80;
                        if (clickable.tagName === 'BUTTON' || clickable.getAttribute('role') === 'button') score += 50;
                        if (r.top < vh * 0.45) score += 20;
                        buttons.push({el: clickable, score, text: text || rawText.slice(0, 20) || 'close', x:r.left, y:r.top, width:r.width, height:r.height});
                    }
                    buttons.sort((a, b) => b.score - a.score);
                    const safe = row => ({score:row.score, text:row.text, x:Math.round(row.x), y:Math.round(row.y), width:Math.round(row.width), height:Math.round(row.height)});
                    if (!buttons[0]) return {promptVisible:true, clicked:false, reason:'save_login_button_not_found', candidates:[]};
                    if (!arg || !arg.click) {
                        return {promptVisible:true, clicked:false, action:buttons[0].text, clickedBox:safe(buttons[0]), candidates:buttons.slice(0, 6).map(safe)};
                    }
                    const clicked = clickLike(buttons[0].el);
                    return {promptVisible:true, clicked:true, action:buttons[0].text, clickedBox:clicked, candidates:buttons.slice(0, 6).map(safe)};
                }"""
                info = {}
                deadline = time.time() + max(2.0, float(os.getenv('DY_DM_SAVE_LOGIN_PROMPT_WAIT_MS', '9000') or '9000') / 1000.0)
                while time.time() < deadline:
                    try:
                        info = page.evaluate(save_prompt_click_js, {'click': False})
                    except Exception as e:
                        info = {'promptVisible': False, 'clicked': False, 'error': str(e)[:200]}
                        break
                    if not info.get('promptVisible'):
                        break
                    try:
                        click_info = page.evaluate(save_prompt_click_js, {'click': True})
                        info.update({
                            'clicked': bool(click_info.get('clicked')),
                            'action': click_info.get('action') or info.get('action'),
                            'clickedBox': click_info.get('clickedBox') or info.get('clickedBox'),
                            'candidates': click_info.get('candidates') or info.get('candidates') or [],
                        })
                    except Exception as e:
                        info.update({'clicked': False, 'error': str(e)[:200]})
                    page.wait_for_timeout(900 if info.get('clicked') else 500)
                    try:
                        after = page.evaluate(save_prompt_click_js, {'click': False})
                    except Exception as e:
                        after = {'promptVisible': False, 'clicked': False, 'error': str(e)[:200]}
                    if after.get('promptVisible') and info.get('clickedBox'):
                        try:
                            box = info.get('clickedBox') or {}
                            x = float(box.get('x') or 0)
                            y = float(box.get('y') or 0)
                            if x > 0 and y > 0:
                                page.mouse.click(x, y, delay=80)
                                info['realMouseClick'] = {'x': round(x), 'y': round(y)}
                                page.wait_for_timeout(700)
                                after = page.evaluate(save_prompt_click_js, {'click': False})
                        except Exception as e:
                            info['realMouseClick'] = {'error': str(e)[:180]}
                    info['afterClick'] = after
                    if not after.get('promptVisible'):
                        break
                    page.wait_for_timeout(500)
                info['finalPromptVisible'] = bool((info.get('afterClick') or info).get('promptVisible'))
                return info

            def maybe_keep_browser_for_blocked_save_prompt():
                prompt = result.get('saveLoginPrompt') if isinstance(result.get('saveLoginPrompt'), dict) else {}
                if not prompt.get('finalPromptVisible') or headless:
                    return
                try:
                    keep_ms = int(os.getenv('DY_DM_KEEP_BROWSER_ON_BLOCKED_PROMPT_MS', '20000') or '20000')
                except Exception:
                    keep_ms = 20000
                keep_ms = max(0, min(120000, keep_ms))
                if keep_ms <= 0:
                    return
                result['browserKeptOpenMs'] = keep_ms
                page.wait_for_timeout(keep_ms)

            result['saveLoginPrompt'] = dismiss_douyin_save_login_prompt()

            for sel in dm_profile_button_selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        label = locator_label(loc)
                        if not is_dm_button_label(label):
                            rejected_buttons.append({
                                'selector': sel,
                                'label': str(label or '')[:80],
                                'reason': 'dm_button_rejected',
                            })
                            continue
                        btn = loc
                        dm_button_selector = sel
                        break
                except Exception:
                    continue
            if btn is None:
                result['error'] = 'dm_button_not_found'
                result['dmButtonDiagnostics'] = {
                    'selectors': dm_profile_button_selectors,
                    'rejectedButtons': rejected_buttons[:8],
                    'saveLoginPrompt': result.get('saveLoginPrompt') or None,
                }
                maybe_keep_browser_for_blocked_save_prompt()
                return result
            result['dmButtonSelector'] = dm_button_selector

            dm_panel_probe_js = r"""() => {
                const vw = window.innerWidth || 1280;
                const vh = window.innerHeight || 900;
                const visible = el => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 8 && r.height > 8 &&
                        s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' &&
                        r.bottom > 0 && r.right > 0 && r.left < vw && r.top < vh;
                };
                const labelOf = el => String([
                    el.innerText || '',
                    el.textContent || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || '',
                    el.getAttribute('placeholder') || '',
                    el.getAttribute('class') || ''
                ].join(' ')).replace(/\s+/g, ' ').trim();
                const markers = [];
                const strongMarkers = [];
                for (const el of Array.from(document.querySelectorAll('div,section,aside,button,[role="dialog"],[role="textbox"],input,textarea'))) {
                    if (!visible(el)) continue;
                    const r = el.getBoundingClientRect();
                    const text = labelOf(el);
                    if (r.left < vw * 0.35) continue;
                    const role = el.getAttribute('role') || '';
                    const tag = el.tagName;
                    const editableLike = role === 'textbox' || tag === 'TEXTAREA' || tag === 'INPUT';
                    if (!text && !editableLike) continue;
                    let score = 0;
                    let strong = false;
                    if (text.includes('收起会话')) { score += 280; strong = true; }
                    if (text.includes('发送消息') || text.includes('输入消息')) { score += 260; strong = true; }
                    if (text.includes('确认聊天') || text.includes('可以继续向你发送消息')) { score += 180; strong = true; }
                    if (editableLike && r.top > vh * 0.45 && r.width > 160 && r.height > 20) { score += 180; strong = true; }
                    if (text.includes('私信') || text.includes('消息')) score += 40;
                    if (r.top > 80 && r.width > 260 && r.height > 160) score += 70;
                    if (score <= 0) continue;
                    const marker = {score, strong, text:text.slice(0,80), tag, role, x:Math.round(r.left), y:Math.round(r.top), width:Math.round(r.width), height:Math.round(r.height)};
                    markers.push(marker);
                    if (strong) strongMarkers.push(marker);
                }
                markers.sort((a, b) => b.score - a.score);
                strongMarkers.sort((a, b) => b.score - a.score);
                return {panelOpened: strongMarkers.length > 0, markers: markers.slice(0, 8), strongMarkers: strongMarkers.slice(0, 8)};
            }"""

            def probe_dm_panel():
                try:
                    return page.evaluate(dm_panel_probe_js)
                except Exception as e:
                    return {'panelOpened': False, 'panelError': str(e)[:200]}

            def click_profile_dm_button(dm_button, selector):
                click_attempts = []

                def record(method, ok, err='', box=None, panel=None):
                    item = {
                        'method': method,
                        'ok': bool(ok),
                        'error': str(err or '')[:180],
                        'box': box or None,
                        'panelOpened': bool((panel or {}).get('panelOpened')),
                    }
                    click_attempts.append(item)
                    return item

                def button_box():
                    try:
                        box = dm_button.bounding_box(timeout=1500)
                    except Exception:
                        box = None
                    if not box:
                        try:
                            box = dm_button.evaluate(r"""el => {
                                const r = el.getBoundingClientRect();
                                return {x:r.left, y:r.top, width:r.width, height:r.height};
                            }""")
                        except Exception:
                            box = None
                    if not box:
                        return None
                    return {
                        'x': round(float(box.get('x') or 0), 1),
                        'y': round(float(box.get('y') or 0), 1),
                        'width': round(float(box.get('width') or 0), 1),
                        'height': round(float(box.get('height') or 0), 1),
                    }

                try:
                    dm_button.scroll_into_view_if_needed(timeout=3000)
                    page.wait_for_timeout(300)
                except Exception:
                    pass

                last_panel = probe_dm_panel()
                if last_panel.get('panelOpened'):
                    return {
                        'clicked': False,
                        'clickedPanelOpened': True,
                        'selector': selector,
                        'clickAttempts': click_attempts,
                        'panelProbe': last_panel,
                    }

                try:
                    dm_button.click(timeout=3000, force=False)
                    page.wait_for_timeout(900)
                    last_panel = probe_dm_panel()
                    record('playwright_click', True, box=button_box(), panel=last_panel)
                    if last_panel.get('panelOpened'):
                        return {
                            'clicked': True,
                            'clickedPanelOpened': True,
                            'selector': selector,
                            'clickAttempts': click_attempts,
                            'panelProbe': last_panel,
                        }
                except Exception as e:
                    record('playwright_click', False, err=e, box=button_box(), panel=last_panel)

                box = button_box()
                if box and box.get('width', 0) > 4 and box.get('height', 0) > 4:
                    try:
                        x = float(box['x']) + float(box['width']) / 2.0
                        y = float(box['y']) + float(box['height']) / 2.0
                        page.mouse.move(x, y)
                        page.mouse.click(x, y, delay=120)
                        page.wait_for_timeout(1000)
                        last_panel = probe_dm_panel()
                        record('mouse_coordinate_click', True, box=box, panel=last_panel)
                        if last_panel.get('panelOpened'):
                            return {
                                'clicked': True,
                                'clickedPanelOpened': True,
                                'selector': selector,
                                'clickAttempts': click_attempts,
                                'panelProbe': last_panel,
                            }
                    except Exception as e:
                        record('mouse_coordinate_click', False, err=e, box=box, panel=last_panel)

                try:
                    js_click = dm_button.evaluate(r"""el => {
                        const r = el.getBoundingClientRect();
                        const x = r.left + r.width / 2;
                        const y = r.top + r.height / 2;
                        el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, clientX:x, clientY:y}));
                        el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x, clientY:y}));
                        el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:x, clientY:y}));
                        el.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:x, clientY:y}));
                        try { el.click(); } catch(e) {}
                        return {x:Math.round(x), y:Math.round(y), width:Math.round(r.width), height:Math.round(r.height)};
                    }""")
                    page.wait_for_timeout(1000)
                    last_panel = probe_dm_panel()
                    record('dom_event_click', True, box=js_click, panel=last_panel)
                except Exception as e:
                    record('dom_event_click', False, err=e, box=box, panel=last_panel)

                return {
                    'clicked': any(x.get('ok') for x in click_attempts),
                    'clickedPanelOpened': bool((last_panel or {}).get('panelOpened')),
                    'selector': selector,
                    'clickAttempts': click_attempts,
                    'panelProbe': last_panel,
                }

            click_result = click_profile_dm_button(btn, dm_button_selector)
            result['dmButtonClick'] = click_result
            panel_info = click_result.get('panelProbe') if isinstance(click_result, dict) else {}
            panel_deadline = time.time() + max(2.0, float(os.getenv('DY_DM_PANEL_WAIT_MS', '6000') or '6000') / 1000.0)
            while time.time() < panel_deadline:
                panel_info = probe_dm_panel()
                if panel_info.get('panelOpened'):
                    if isinstance(click_result, dict):
                        click_result['clickedPanelOpened'] = True
                        click_result['panelProbe'] = panel_info
                    break
                page.wait_for_timeout(300)
            if not panel_info.get('panelOpened'):
                result['error'] = 'dm_panel_not_open'
                result['dmButtonDiagnostics'] = {
                    'clickedSelector': dm_button_selector,
                    'panelOpened': False,
                    'clickedPanelOpened': bool((click_result or {}).get('clickedPanelOpened')) if isinstance(click_result, dict) else False,
                    'clickAttempts': (click_result or {}).get('clickAttempts', []) if isinstance(click_result, dict) else [],
                    'panelProbe': panel_info,
                }
                return result

            dm_editor_focus_js = r"""() => {
                const vw = window.innerWidth || 1280;
                const vh = window.innerHeight || 900;
                const visible = el => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 8 && r.height > 8 &&
                        s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' &&
                        r.bottom > 0 && r.right > 0 && r.left < vw && r.top < vh;
                };
                const labelOf = el => String([
                    el.getAttribute('placeholder') || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || '',
                    el.innerText || '',
                    el.textContent || '',
                    el.getAttribute('class') || ''
                ].join(' ')).replace(/\s+/g, ' ').trim();
                const clickLike = el => {
                    const r = el.getBoundingClientRect();
                    const x = r.left + Math.min(Math.max(r.width / 2, 12), Math.max(r.width - 12, 12));
                    const y = r.top + Math.min(Math.max(r.height / 2, 12), Math.max(r.height - 12, 12));
                    el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, clientX:x, clientY:y}));
                    el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x, clientY:y}));
                    el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:x, clientY:y}));
                    el.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:x, clientY:y}));
                    try { el.click(); } catch(e) {}
                    try { el.focus(); } catch(e) {}
                    return {x:Math.round(x), y:Math.round(y), width:Math.round(r.width), height:Math.round(r.height)};
                };
                const rows = [];
                for (const el of Array.from(document.querySelectorAll('textarea,input,[role="textbox"],[contenteditable],div,span'))) {
                    if (!visible(el)) continue;
                    const r = el.getBoundingClientRect();
                    if (!(r.top > vh * 0.55)) continue;
                    if (r.width < 120 || r.height < 18) continue;
                    if (r.width > vw * 0.86 || r.height > vh * 0.28) continue;
                    const text = labelOf(el);
                    const lower = text.toLowerCase();
                    if (lower.includes('search') || text.includes('搜索')) continue;
                    let score = 0;
                    if (text.includes('发送消息')) score += 320;
                    if (text.includes('输入消息') || text.includes('请输入')) score += 240;
                    if (el.isContentEditable || el.getAttribute('contenteditable')) score += 120;
                    if (el.getAttribute('role') === 'textbox') score += 100;
                    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') score += 80;
                    if (r.left > vw * 0.45) score += 90;
                    if (r.top > vh * 0.70) score += 70;
                    if (String(el.className || '').includes('DraftEditor')) score += 90;
                    if (r.width * r.height > 120000) score -= 140;
                    if (score <= 0) continue;
                    rows.push({el, score, text:text.slice(0,80), tag:el.tagName, role:el.getAttribute('role') || '', x:r.left, y:r.top, width:r.width, height:r.height});
                }
                rows.sort((a, b) => b.score - a.score);
                const safe = row => ({score:row.score, text:row.text, tag:row.tag, role:row.role, x:Math.round(row.x), y:Math.round(row.y), width:Math.round(row.width), height:Math.round(row.height)});
                if (!rows[0]) return {clicked:false, focusCandidateCount:0, candidates:[]};
                const clicked = clickLike(rows[0].el);
                return {clicked:true, clicked, focusCandidateCount:rows.length, selected:safe(rows[0]), candidates:rows.slice(0,8).map(safe)};
            }"""

            dm_editor_scan_js = r"""(arg) => {
                const selectors = [
                    '[role="textbox"]',
                    '[contenteditable="plaintext-only"]',
                    '[contenteditable="true"]',
                    '[contenteditable]',
                    'textarea',
                    'input'
                ];
                const vw = window.innerWidth || 1280;
                const vh = window.innerHeight || 900;
                const textOf = el => String(
                    el.getAttribute('placeholder') ||
                    el.getAttribute('aria-label') ||
                    el.getAttribute('title') ||
                    el.value ||
                    el.innerText ||
                    el.textContent ||
                    ''
                ).replace(/\s+/g, ' ').trim();
                const visible = el => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 8 && r.height > 8 &&
                        s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' &&
                        r.bottom > 0 && r.right > 0 && r.left < vw && r.top < vh;
                };
                const attrText = el => String([
                    el.getAttribute('placeholder') || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || '',
                    el.getAttribute('name') || '',
                    el.getAttribute('id') || '',
                    el.getAttribute('class') || ''
                ].join(' ')).toLowerCase();
                const isSearchLike = (el, r, text) => {
                    const hay = (attrText(el) + ' ' + String(text || '').toLowerCase()).trim();
                    if (hay.includes('search') || hay.includes('搜索')) return true;
                    if (r.top < 120 && (el.tagName === 'INPUT' || el.getAttribute('role') === 'textbox')) return true;
                    return false;
                };
                const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
                if (document.activeElement && !nodes.includes(document.activeElement) &&
                    !['BODY', 'HTML'].includes(document.activeElement.tagName)) {
                    nodes.unshift(document.activeElement);
                }
                const rows = [];
                let search_box_rejected = 0;
                for (const el of nodes) {
                    if (!visible(el)) continue;
                    const tag = el.tagName;
                    const role = String(el.getAttribute('role') || '');
                    const ce = String(el.getAttribute('contenteditable') || '');
                    const type = String(el.getAttribute('type') || '').toLowerCase();
                    if (tag === 'INPUT' && ['hidden', 'password', 'file', 'checkbox', 'radio'].includes(type)) continue;
                    if (tag === 'BODY' || tag === 'HTML') continue;
                    const r = el.getBoundingClientRect();
                    const cls = String(el.className || '');
                    const text = textOf(el);
                    const editable = el.isContentEditable || ce === 'true' || ce === 'plaintext-only' ||
                        tag === 'TEXTAREA' || tag === 'INPUT' || role === 'textbox';
                    if (!editable) continue;
                    if (isSearchLike(el, r, text)) {
                        search_box_rejected += 1;
                        continue;
                    }
                    let score = 0;
                    if (document.activeElement === el) score += 240;
                    if (el.isContentEditable || ce === 'true' || ce === 'plaintext-only') score += 150;
                    if (role === 'textbox') score += 100;
                    if (tag === 'TEXTAREA') score += 90;
                    if (tag === 'INPUT') score += 45;
                    if (text.includes('\u6d88\u606f') || text.includes('\u8f93\u5165') || text.includes('\u79c1\u4fe1')) score += 70;
                    if (text.includes('发送消息')) score += 180;
                    if (cls.includes('DraftEditor') || cls.includes('public-DraftEditor')) score += 80;
                    if (r.width > 160 && r.height > 20) score += 35;
                    if (r.top > vh * 0.45) score += 45;
                    if (r.left > vw * 0.45) score += 40;
                    if (r.top < 160) score -= 180;
                    if (r.width * r.height > 260000 && !(el.isContentEditable || tag === 'TEXTAREA' || role === 'textbox')) score -= 120;
                    rows.push({
                        el, score, tag, role, contenteditable: ce, text: text.slice(0, 80),
                        cls: cls.slice(0, 120), x: r.left, y: r.top, width: r.width, height: r.height
                    });
                }
                rows.sort((a, b) => (b.score - a.score) || ((a.width * a.height) - (b.width * b.height)));
                const safe = row => ({
                    score: row.score,
                    tag: row.tag,
                    role: row.role,
                    contenteditable: row.contenteditable,
                    text: row.text,
                    cls: row.cls,
                    x: Math.round(row.x),
                    y: Math.round(row.y),
                    width: Math.round(row.width),
                    height: Math.round(row.height)
                });
                const selected = rows[0] || null;
                if (selected && arg.token) selected.el.setAttribute('data-matrix-dm-editor', arg.token);
                return {
                    found: !!selected,
                    editorCandidateCount: rows.length,
                    search_box_rejected,
                    selected: selected ? safe(selected) : null,
                    candidates: rows.slice(0, 12).map(safe)
                };
            }"""

            def annotate_frame_info(scan_info, frame_index, frame):
                scan_info = scan_info if isinstance(scan_info, dict) else {}
                scan_info['frameIndex'] = frame_index
                try:
                    scan_info['frameUrl'] = (frame.url or '')[:240]
                except Exception:
                    pass
                return scan_info

            def focus_dm_editor_contexts():
                best = {}
                for frame_index, frame in enumerate(page.frames):
                    try:
                        focus_info = frame.evaluate(dm_editor_focus_js)
                        focus_info = annotate_frame_info(focus_info, frame_index, frame)
                        if focus_info.get('clicked'):
                            return frame, focus_info
                        if int(focus_info.get('focusCandidateCount') or 0) > int(best.get('focusCandidateCount') or 0):
                            best = focus_info
                    except Exception as e:
                        if not best:
                            best = {'clicked': False, 'focusError': str(e)[:200], 'frameIndex': frame_index}
                return page.main_frame, best

            def scan_dm_editor_contexts(token, focus_info=None):
                best_frame = page.main_frame
                best_info = {}
                for frame_index, frame in enumerate(page.frames):
                    try:
                        scan_info = frame.evaluate(dm_editor_scan_js, {'token': token})
                        scan_info = annotate_frame_info(scan_info, frame_index, frame)
                        if focus_info:
                            scan_info['focusProbe'] = focus_info
                        if scan_info.get('found'):
                            return frame, scan_info
                        if int(scan_info.get('editorCandidateCount') or 0) > int(best_info.get('editorCandidateCount') or 0):
                            best_frame = frame
                            best_info = scan_info
                    except Exception as e:
                        if not best_info:
                            best_info = {'found': False, 'scanError': str(e)[:200], 'frameIndex': frame_index}
                if focus_info:
                    best_info['focusProbe'] = focus_info
                return best_frame, best_info

            def dm_editor_diagnostics(scan_info):
                scan_info = scan_info if isinstance(scan_info, dict) else {}
                diag = {
                    'editorCandidateCount': int(scan_info.get('editorCandidateCount') or 0),
                    'searchBoxRejected': int(scan_info.get('search_box_rejected') or 0),
                    'selected': scan_info.get('selected') or None,
                    'candidates': list(scan_info.get('candidates') or [])[:12],
                    'frameIndex': scan_info.get('frameIndex'),
                    'frameUrl': scan_info.get('frameUrl') or '',
                    'focusProbe': scan_info.get('focusProbe') or None,
                }
                try:
                    diag['url'] = (page.url or '')[:240]
                except Exception:
                    pass
                try:
                    diag['title'] = (page.title() or '')[:120]
                except Exception:
                    pass
                return diag

            editor_token = 'matrix_dm_editor_' + uuid.uuid4().hex
            wait_ms = int(os.getenv('DY_DM_EDITOR_WAIT_MS', '15000') or '15000')
            deadline = time.time() + max(3.0, wait_ms / 1000.0)
            editor_info = {}
            editor_context = page.main_frame
            focus_info = {}
            while time.time() < deadline:
                try:
                    editor_context, editor_info = scan_dm_editor_contexts(editor_token, focus_info)
                    if editor_info.get('found'):
                        break
                except Exception as e:
                    editor_info = {'found': False, 'scanError': str(e)[:200]}
                try:
                    editor_context, focus_info = focus_dm_editor_contexts()
                except Exception as e:
                    focus_info = {'clicked': False, 'focusError': str(e)[:200]}
                page.wait_for_timeout(300)
                try:
                    editor_context, editor_info = scan_dm_editor_contexts(editor_token, focus_info)
                    if editor_info.get('found'):
                        break
                except Exception as e:
                    editor_info = {'found': False, 'scanError': str(e)[:200], 'focusProbe': focus_info}
                page.wait_for_timeout(500)

            if not editor_info.get('found'):
                result['error'] = 'dm_input_not_found'
                result['dmEditorDiagnostics'] = dm_editor_diagnostics(editor_info)
                json_log(
                    logger,
                    'douyin_dm_send_editor_not_found',
                    level='warning',
                    targetFingerprint=_dm_text_fingerprint(profile_url),
                    editorCandidateCount=result['dmEditorDiagnostics'].get('editorCandidateCount', 0),
                    pageTitle=result['dmEditorDiagnostics'].get('title', ''),
                    pageUrl=result['dmEditorDiagnostics'].get('url', ''),
                )
                return result

            inp = editor_context.locator('[data-matrix-dm-editor="%s"]' % editor_token).first
            inp.click(timeout=4000, force=True)
            try:
                inp.focus(timeout=2000)
            except Exception:
                pass
            page.wait_for_timeout(300)
            try:
                inp.fill('', timeout=2500)
                inp.fill(content, timeout=3500)
            except Exception:
                try:
                    page.keyboard.press('Control+A')
                    page.keyboard.press('Backspace')
                    page.keyboard.type(content, delay=60)
                except Exception:
                    try:
                        page.keyboard.insert_text(content)
                    except Exception:
                        pass
            typed = editor_context.evaluate(r"""(arg) => {
                const el = document.querySelector('[data-matrix-dm-editor="' + arg.token + '"]');
                if (!el) return false;
                const value = String(el.value || el.innerText || el.textContent || '');
                return value.includes(arg.content);
            }""", {'token': editor_token, 'content': content})
            if not typed:
                try:
                    editor_context.evaluate(r"""(arg) => {
                        const el = document.querySelector('[data-matrix-dm-editor="' + arg.token + '"]');
                        if (!el) return false;
                        el.focus();
                        if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                            el.value = arg.content;
                        } else {
                            try { document.execCommand('selectAll', false, null); } catch(e) {}
                            try { document.execCommand('delete', false, null); } catch(e) {}
                            const inserted = document.execCommand('insertText', false, arg.content);
                            if (!inserted) el.innerText = arg.content;
                        }
                        el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:arg.content}));
                        el.dispatchEvent(new Event('change', {bubbles:true}));
                        return true;
                    }""", {'token': editor_token, 'content': content})
                    page.wait_for_timeout(400)
                    typed = editor_context.evaluate(r"""(arg) => {
                        const el = document.querySelector('[data-matrix-dm-editor="' + arg.token + '"]');
                        if (!el) return false;
                        const value = String(el.value || el.innerText || el.textContent || '');
                        return value.includes(arg.content);
                    }""", {'token': editor_token, 'content': content})
                except Exception:
                    typed = False
            if not typed:
                result['error'] = 'dm_type_failed'
                result['dmEditorDiagnostics'] = dm_editor_diagnostics(editor_info)
                return result
            page.wait_for_timeout(400)

            dm_send_button_click_js = r"""(arg) => {
                const token = arg.token;
                const editor = document.querySelector('[data-matrix-dm-editor="' + token + '"]');
                if (!editor) return {clicked:false, reason:'editor_missing', buttonCandidates:[]};
                const vw = window.innerWidth || 1280;
                const vh = window.innerHeight || 900;
                const visible = el => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 6 && r.height > 6 &&
                        s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' &&
                        !el.disabled && r.bottom > 0 && r.right > 0 && r.left < vw && r.top < vh;
                };
                const labelOf = el => String([
                    el.innerText || '',
                    el.textContent || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || '',
                    el.getAttribute('class') || ''
                ].join(' ')).replace(/\s+/g, ' ').trim();
                const clickLike = el => {
                    const r = el.getBoundingClientRect();
                    const x = r.left + r.width / 2;
                    const y = r.top + r.height / 2;
                    el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, clientX:x, clientY:y}));
                    el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x, clientY:y}));
                    el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:x, clientY:y}));
                    el.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:x, clientY:y}));
                    try { el.click(); } catch(e) {}
                    return {x:Math.round(x), y:Math.round(y), width:Math.round(r.width), height:Math.round(r.height)};
                };
                const er = editor.getBoundingClientRect();
                const editorRect = {x:er.left, y:er.top, right:er.right, bottom:er.bottom, width:er.width, height:er.height};
                const rows = [];
                for (const el of Array.from(document.querySelectorAll('button,[role="button"],svg,div,span'))) {
                    if (!visible(el)) continue;
                    const r = el.getBoundingClientRect();
                    if (r.top < 120) continue;
                    const text = labelOf(el);
                    const lower = text.toLowerCase();
                    const nearEditorY = r.top <= er.bottom + 90 && r.bottom >= er.top - 90;
                    const nearEditorX = r.left >= er.left - 40 && r.right <= Math.max(er.right + 220, er.right);
                    if (!nearEditorY || !nearEditorX) continue;
                    let score = 0;
                    if (text.includes('发送')) score += 220;
                    if (lower.includes('send')) score += 160;
                    if (r.left >= er.right - 20) score += 80;
                    if (r.top >= er.top - 20 && r.bottom <= er.bottom + 80) score += 60;
                    if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') score += 60;
                    if (r.width <= 80 && r.height <= 80) score += 30;
                    if (lower.includes('search') || text.includes('搜索')) score -= 400;
                    if (score <= 0) continue;
                    rows.push({el, score, text:text.slice(0,80), tag:el.tagName, role:el.getAttribute('role') || '', x:r.left, y:r.top, width:r.width, height:r.height});
                }
                rows.sort((a,b) => b.score - a.score);
                const safe = row => ({score:row.score, text:row.text, tag:row.tag, role:row.role, x:Math.round(row.x), y:Math.round(row.y), width:Math.round(row.width), height:Math.round(row.height)});
                const buttonCandidates = rows.slice(0, 8).map(safe);
                if (!rows[0]) return {clicked:false, reason:'dm_send_button_not_found', editorRect, buttonCandidates};
                const clicked = clickLike(rows[0].el);
                return {clicked:true, editorRect, clicked, buttonCandidates};
            }"""
            send_click = {}
            try:
                send_click = editor_context.evaluate(dm_send_button_click_js, {'token': editor_token})
            except Exception as e:
                send_click = {'clicked': False, 'reason': 'send_button_scan_failed', 'error': str(e)[:200], 'buttonCandidates': []}
            if not send_click.get('clicked'):
                selected = editor_info.get('selected') if isinstance(editor_info, dict) else {}
                if str((selected or {}).get('tag') or '').upper() != 'INPUT':
                    try:
                        page.keyboard.press('Enter')
                    except Exception:
                        pass
                else:
                    result['error'] = 'dm_send_button_not_found'
                    result['dmEditorDiagnostics'] = dm_editor_diagnostics(editor_info)
                    result['dmSendDiagnostics'] = send_click
                    return result
            page.wait_for_timeout(4500)
            result['msgSendStatus'] = state['send_status']
            if state['send_fired'] and (state['send_status'] is None or state['send_status'] == 200):
                result['ok'] = True
                result['sent'] = content
            else:
                result['error'] = result.get('error') or 'dm_send_not_confirmed'
                result['dmSendDiagnostics'] = send_click
            return result
        finally:
            try:
                ctx.close()
            finally:
                shutil.rmtree(profile_dir, ignore_errors=True)


def _dm_text_fingerprint(value):
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]


def _normalize_dm_inbox_message(raw, index=0):
    raw = raw if isinstance(raw, dict) else {}
    kind = str(raw.get("kind") or raw.get("type") or "text").strip().lower()
    if kind not in ("text", "image", "voice", "video", "card", "emoji", "unknown"):
        kind = "unknown"
    direction = str(raw.get("direction") or raw.get("from") or "").strip().lower()
    if direction in ("me", "self", "mine"):
        direction = "me"
    elif direction in ("customer", "user", "other", "left", "friend"):
        direction = "customer"
    else:
        direction = "unknown"
    text = str(raw.get("text") or raw.get("content") or "").strip()
    if kind != "text":
        text = ""
    text = text[:1000]
    created_at_text = str(raw.get("createdAtText") or raw.get("time") or "")
    ordinal = raw.get("ordinal")
    ordinal_text = "" if ordinal is None else str(ordinal)
    basis = "|".join([direction, kind, text, created_at_text, ordinal_text])
    fingerprint = str(raw.get("fingerprint") or raw.get("id") or _dm_text_fingerprint(basis))
    return {
        "id": str(raw.get("id") or fingerprint),
        "fingerprint": fingerprint,
        "direction": direction,
        "kind": kind,
        "text": text,
        "createdAtText": created_at_text,
    }


def browser_read_dm_inbox(target, limit=10, since_fingerprint="", account_id=''):
    target = (target or "").strip()
    if not target:
        return {"ok": False, "error": "missing_target"}
    try:
        limit = max(1, min(int(limit or 10), 20))
    except Exception:
        limit = 10
    if target.startswith("http"):
        profile_url = target
    elif not target.isdigit():
        profile_url = "https://www.douyin.com/user/" + target
    else:
        return {"ok": False, "error": "numeric_uid_unsupported_in_browser_dm"}
    login_source = _resolve_douyin_dm_login_source(account_id)
    target_fingerprint = _dm_text_fingerprint(profile_url)
    json_log(
        logger,
        "douyin_dm_inbox_poll_started",
        level="info",
        targetFingerprint=target_fingerprint,
        accountId=login_source.get('accountId') or account_id or '',
        limit=limit,
        hasSinceFingerprint=bool(since_fingerprint),
    )

    def _finish(payload):
        payload = payload if isinstance(payload, dict) else {"ok": False, "error": "dm_inbox_invalid_result"}
        json_log(
            logger,
            "douyin_dm_inbox_poll_finished",
            level="info",
            targetFingerprint=target_fingerprint,
            accountId=payload.get('accountId') or login_source.get('accountId') or account_id or '',
            ok=bool(payload.get("ok")),
            messageCount=len(payload.get("messages") or []),
            nonTextCount=payload.get("nonTextCount") or 0,
            error=payload.get("error") or "",
        )
        return payload

    if not login_source.get('ok'):
        return _finish({
            'ok': False,
            'platform': 'douyin',
            'target': profile_url,
            'messages': [],
            'nonTextCount': 0,
            'needLogin': True,
            'error': 'not_authenticated',
            'reason': login_source.get('error') or 'dm_login_profile_not_ready',
            'accountId': login_source.get('accountId') or account_id or '',
        })

    if os.getenv("DY_DM_INBOX_CHILD", "").strip() != "1" and os.getenv("DY_DM_ISOLATED", "1").strip().lower() not in ("0", "false", "no", "off"):
        child_env = os.environ.copy()
        child_env["DY_DM_INBOX_CHILD"] = "1"
        child_env.setdefault("MATRIX_AGENT_DATA_DIR", DATA_DIR)
        child_env.setdefault("DY_DATA_DIR", DATA_DIR)
        child_env["DY_DM_INBOX_TARGET_B64"] = base64.b64encode(profile_url.encode("utf-8")).decode("ascii")
        child_env["DY_DM_INBOX_LIMIT"] = str(limit)
        child_env["DY_DM_INBOX_SINCE"] = str(since_fingerprint or "")
        child_env["DY_DM_INBOX_ACCOUNT_ID"] = str(login_source.get('accountId') or account_id or '')
        child_code = r"""
import base64, json, os, sys
os.chdir(r'__BACKEND_DIR__')
sys.path.insert(0, r'__BACKEND_DIR__')
import api_server
t = base64.b64decode(os.environ.get('DY_DM_INBOX_TARGET_B64', '')).decode('utf-8')
limit = int(os.environ.get('DY_DM_INBOX_LIMIT', '10') or '10')
since = os.environ.get('DY_DM_INBOX_SINCE', '')
account_id = os.environ.get('DY_DM_INBOX_ACCOUNT_ID', '')
res = api_server.browser_read_dm_inbox(t, limit, since, account_id=account_id)
print('__MATRIX_DM_INBOX_JSON__' + json.dumps(res, ensure_ascii=False))
""".replace("__BACKEND_DIR__", os.path.dirname(os.path.abspath(__file__)).replace("\\", "\\\\"))
        try:
            proc = subprocess.run(
                [sys.executable, "-c", child_code],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=child_env,
                capture_output=True,
                text=True,
                timeout=int(os.getenv("DY_DM_INBOX_CHILD_TIMEOUT", "120") or "120"),
            )
            marker = "__MATRIX_DM_INBOX_JSON__"
            if marker in (proc.stdout or ""):
                payload = (proc.stdout or "").rsplit(marker, 1)[1].strip().splitlines()[0]
                return _finish(json.loads(payload))
            return _finish({
                "ok": False,
                "error": "dm_inbox_child_failed",
                "stderr": (proc.stderr or "")[-800:],
                "stdout": (proc.stdout or "")[-400:],
            })
        except Exception as exc:
            return _finish({"ok": False, "error": "dm_inbox_child_exception", "detail": str(exc)})

    from playwright.sync_api import sync_playwright

    edge_exe = os.getenv("DY_EDGE_PATH", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    profile_base = os.path.abspath(os.getenv("DY_DM_PROFILE_DIR", os.path.join(DATA_DIR, "dy_dm_profile")))
    os.makedirs(profile_base, exist_ok=True)
    profile_dir = os.path.abspath(os.getenv("DY_DM_PROFILE_CURRENT_DIR", os.path.join(profile_base, "current")))
    os.makedirs(profile_dir, exist_ok=True)
    seeded_login = _seed_login_state_into_profile(profile_dir, login_source.get('profileDir'))
    if not seeded_login:
        return _finish({
            'ok': False,
            'platform': 'douyin',
            'target': profile_url,
            'messages': [],
            'nonTextCount': 0,
            'needLogin': True,
            'error': 'not_authenticated',
            'reason': 'dm_login_profile_seed_failed',
            'accountId': login_source.get('accountId') or account_id or '',
        })
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
        "--lang=zh-CN",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]
    result = {
        "ok": False,
        "platform": "douyin",
        "target": profile_url,
        "messages": [],
        "nonTextCount": 0,
        "sinceFingerprint": str(since_fingerprint or ""),
        "limit": limit,
        "accountId": login_source.get('accountId') or account_id or '',
    }
    with sync_playwright() as p:
        kw = dict(
            headless=os.getenv("DY_DM_HEADLESS", "").strip().lower() in ("1", "true", "yes", "on"),
            args=args,
            ignore_default_args=["--enable-automation"],
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1280, "height": 900},
        )
        if edge_exe and os.path.exists(edge_exe):
            kw["executable_path"] = edge_exe
        ctx = p.chromium.launch_persistent_context(profile_dir, **kw)
        try:
            dm_cache = load_cookie_cache(login_source.get('accountId') or account_id or '')
            dm_context_cookies = _douyin_dm_context_cookies(dm_cache.get('cookie') or '')
            result['dmCookieInjection'] = {
                'attemptedCount': len(dm_context_cookies),
                'addedCount': 0,
            }
            if dm_context_cookies:
                try:
                    ctx.add_cookies(dm_context_cookies)
                    result['dmCookieInjection']['addedCount'] = len(dm_context_cookies)
                except Exception as exc:
                    result['dmCookieInjection']['error'] = type(exc).__name__
                    json_log(
                        logger,
                        'douyin_dm_inbox_cookie_injection_failed',
                        level='warning',
                        accountId=login_source.get('accountId') or account_id or '',
                        attemptedCount=len(dm_context_cookies),
                        exceptionType=type(exc).__name__,
                        message=str(exc)[:180],
                    )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(profile_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(5000)
            if page.locator("text=登录").count() and not page.locator("text=私信").count() and not page.locator("text=发私信").count():
                result.update({"needLogin": True, "error": "not_authenticated"})
                return _finish(result)
            btn = None
            for sel in ['text=私信', 'text=发私信', 'text=发消息', 'button:has-text("私信")']:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        btn = loc
                        break
                except Exception:
                    continue
            if btn is None:
                result["error"] = "dm_inbox_button_not_found"
                return _finish(result)
            btn.click()
            page.wait_for_timeout(4000)
            raw_messages = page.evaluate("""(limit) => {
                const nodes = Array.from(document.querySelectorAll('[class*="message"], [class*="Message"], [data-e2e*="message"], div[role="listitem"]')).slice(-Math.max(limit * 4, 20));
                const seen = new Map();
                return nodes.map((node, index) => {
                    const text = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
                    const html = (node.innerHTML || '').toLowerCase();
                    let kind = 'text';
                    if (!text) kind = 'unknown';
                    if (html.includes('img') || html.includes('image')) kind = 'image';
                    if (html.includes('voice') || text.includes('[语音]')) kind = 'voice';
                    if (html.includes('video') || text.includes('[视频]')) kind = 'video';
                    if (html.includes('emoji') || text === '[表情]') kind = 'emoji';
                    if (html.includes('card') || text.includes('分享')) kind = 'card';
                    const cls = (node.className || '').toString().toLowerCase();
                    let direction = 'unknown';
                    if (cls.includes('self') || cls.includes('right') || cls.includes('mine')) {
                        direction = 'me';
                    } else if (cls.includes('left') || cls.includes('other') || cls.includes('customer') || cls.includes('friend')) {
                        direction = 'customer';
                    }
                    const duplicateKey = [direction, kind, text].join('|');
                    const ordinal = seen.get(duplicateKey) || 0;
                    seen.set(duplicateKey, ordinal + 1);
                    return { direction, kind, text, createdAtText: '', ordinal, index };
                }).filter(x => x.text || x.kind !== 'text').slice(-limit);
            }""", limit)
            messages = [_normalize_dm_inbox_message(x, i) for i, x in enumerate(raw_messages or [])]
            if not messages:
                result["error"] = "dm_inbox_messages_not_found"
                result["empty"] = True
                return _finish(result)
            if since_fingerprint:
                seen = False
                filtered = []
                for item in messages:
                    if item.get("fingerprint") == since_fingerprint:
                        seen = True
                        filtered = []
                        continue
                    if seen:
                        filtered.append(item)
                if seen:
                    messages = filtered
            result["messages"] = messages[-limit:]
            result["nonTextCount"] = len([x for x in result["messages"] if x.get("kind") != "text"])
            result["ok"] = True
            result.pop("error", None)
            if not result["messages"]:
                result["empty"] = True
            return _finish(result)
        finally:
            ctx.close()


def list_download_files(save_path):
    out = []
    if not save_path or not os.path.isdir(save_path):
        return out
    for root, _dirs, files in os.walk(save_path):
        for name in files:
            fp = os.path.join(root, name)
            out.append({
                'name': name,
                'path': fp,
                'size': os.path.getsize(fp) if os.path.exists(fp) else 0,
            })
    return out


def _safe_material_filename(name, idx=0):
    base = os.path.basename(str(name or '').replace('\\', '/')).strip()
    if not base:
        base = 'file_%d' % idx
    # Windows/Unix unsafe chars are normalized so downloaded titles cannot escape the material dir.
    for ch in '<>:"/\\|?*\r\n\t':
        base = base.replace(ch, '_')
    return base[:160] or ('file_%d' % idx)


def _copy_or_link_file(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        if os.path.exists(dst):
            os.remove(dst)
        os.link(src, dst)
    except Exception:
        import shutil
        shutil.copy2(src, dst)


def _write_material_quarantine_metadata(path, metadata):
    temp_path = path + '.tmp-' + uuid.uuid4().hex[:10]
    try:
        with open(temp_path, 'w', encoding='utf-8') as handle:
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
    safe_mid = re.sub(r'[^A-Za-z0-9._-]+', '_', str(material_id or '').strip())[:120] or 'unknown-material'
    stamp = time.strftime('%Y%m%d_%H%M%S') + ('_%03d_' % int((time.time() % 1) * 1000)) + uuid.uuid4().hex[:8]
    target_dir = os.path.join(quarantine_root, safe_mid, stamp)
    backup_path = os.path.join(target_dir, os.path.basename(path))
    metadata_path = os.path.join(target_dir, 'metadata.json')
    os.makedirs(target_dir, exist_ok=False)
    try:
        shutil.copy2(path, backup_path)
        if not os.path.isfile(backup_path) or os.path.getsize(backup_path) != os.path.getsize(path):
            raise OSError('quarantine_copy_incomplete')
        _write_material_quarantine_metadata(metadata_path, {
            'materialId': str(material_id or ''),
            'reason': str(reason or 'media_invalid'),
            'originalPath': os.path.abspath(path),
            'quarantinedAt': time.time(),
        })
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    return {
        'backupPath': backup_path,
        'metadataPath': metadata_path,
        'originalPath': path,
    }


def _restore_material_files_from_quarantine(backups, installed_paths):
    by_original = {item['originalPath']: item for item in backups if item}
    first_error = None
    for path in reversed(installed_paths):
        restore_temp = path + '.restore-' + uuid.uuid4().hex[:10]
        try:
            backup = by_original.get(path)
            if backup and os.path.isfile(backup.get('backupPath') or ''):
                shutil.copy2(backup['backupPath'], restore_temp)
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


def import_download_to_library(save_path, work=None, source_url='', platform='douyin'):
    """???????????????
    ?????????????? files????????????????
    info.json/detail.txt/cover.jpg ?? metadata ??? sourceDownloadPath???????????
    """
    work = work if isinstance(work, dict) else {}
    files = list_download_files(save_path)
    if not files:
        return None
    video_exts = {'.mp4', '.mov', '.m4v', '.webm', '.avi'}
    image_exts = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
    media = []
    saw_video_candidate = False
    for f in files:
        ext = os.path.splitext(f.get('name') or '')[1].lower()
        if ext in video_exts:
            saw_video_candidate = True
            validation = validate_video_file(f.get('path') or '')
            if validation.get('ok'):
                media.append(dict(f, mediaType='video', validation=validation))
    if media:
        mtype = 'video'
        # ?????????????????? cover/detail ??????????
        media = sorted(media, key=lambda x: int(x.get('size') or 0), reverse=True)[:1]
    elif saw_video_candidate:
        return None
    else:
        for f in files:
            ext = os.path.splitext(f.get('name') or '')[1].lower()
            if ext in image_exts:
                validation = validate_image_file(f.get('path') or '')
                if validation.get('ok'):
                    media.append(dict(f, mediaType='image', validation=validation))
        mtype = 'image'
    if not media:
        return None

    dedupe_key = str(work.get('aweme_id') or work.get('awemeId') or work.get('work_id') or source_url or save_path)
    cleanup_quarantine(MATERIAL_QUARANTINE_DIR, int(os.getenv('MEDIA_QUARANTINE_RETENTION_DAYS', '7') or 7))
    os.makedirs(MATERIALS_DIR, exist_ok=True)
    candidate_id = uuid.uuid4().hex
    staging_dir = os.path.join(MATERIALS_DIR, '.incoming-' + candidate_id)
    os.makedirs(staging_dir, exist_ok=False)

    def find_existing(rows):
        for index, old in enumerate(rows):
            if old.get('sourceDownloadKey') == dedupe_key or old.get('sourceDownloadPath') == save_path:
                return index, old
        return None, None

    def record_token(record):
        return json.dumps(record or {}, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)

    def record_is_valid(record):
        mid = str((record or {}).get('id') or '')
        if not mid:
            return False
        names = list((record or {}).get('files') or [])
        video_names = [name for name in names if os.path.splitext(name)[1].lower() in video_exts]
        if video_names:
            return any(validate_video_file(os.path.join(MATERIALS_DIR, mid, name)).get('ok') for name in video_names)
        if (record or {}).get('type') == 'video':
            return False
        image_names = [name for name in names if os.path.splitext(name)[1].lower() in image_exts]
        return any(validate_image_file(os.path.join(MATERIALS_DIR, mid, name)).get('ok') for name in image_names)

    saved = []
    validations = []
    try:
        for idx, f in enumerate(media):
            src = f.get('path') or ''
            if not src or not os.path.isfile(src):
                continue
            name = _safe_material_filename(f.get('name'), idx)
            if name in saved:
                stem, ext = os.path.splitext(name)
                name = '%s_%d%s' % (stem, idx, ext)
            staged_path = os.path.join(staging_dir, name)
            _copy_or_link_file(src, staged_path)
            validation = validate_video_file(staged_path) if mtype == 'video' else validate_image_file(staged_path)
            if not validation.get('ok'):
                return None
            saved.append(name)
            validations.append(validation)
        if not saved:
            return None

        first_validation = validations[0] if validations else {}
        title = (work.get('desc') or work.get('title') or work.get('aweme_desc') or os.path.basename(save_path) or saved[0]).strip()
        body = str(work.get('body') or work.get('noteBody') or '').strip()
        raw_tags = work.get('tags') or []
        tags = [str(x or '').strip() for x in raw_tags if str(x or '').strip()] if isinstance(raw_tags, (list, tuple, set)) else []
        note_id = str(work.get('noteId') or work.get('note_id') or '').strip()
        metadata_updates = {
            'sourceDownloadPath': save_path,
            'sourceDownloadKey': dedupe_key,
            'sourceAuthor': work.get('nickname') or work.get('author') or '',
        }
        if body:
            metadata_updates['body'] = body
        if tags:
            metadata_updates['tags'] = tags
        if note_id:
            metadata_updates['noteId'] = note_id

        while True:
            with STATE_LOCK:
                library = load_library()
                existing_index, existing = find_existing(library)
                if existing is None:
                    mid = candidate_id
                    material_dir = os.path.join(MATERIALS_DIR, mid)
                    item = {
                        'id': mid,
                        'title': title[:120] or saved[0],
                        'type': mtype,
                        'files': list(saved),
                        'urls': ['/api/library/file/%s/%s' % (mid, fn) for fn in saved],
                        'published': 0,
                        'createdAt': time.time(),
                        'platform': platform or 'douyin',
                        'sourceUrl': source_url or '',
                        'sourceDownloadPath': save_path,
                        'sourceDownloadKey': dedupe_key,
                        'sourceAuthor': work.get('nickname') or work.get('author') or '',
                        'importedFromDownload': True,
                    }
                    item.update({k: v for k, v in metadata_updates.items() if v})
                    if mtype == 'video':
                        item.update({
                            'duration': first_validation.get('duration'),
                            'width': first_validation.get('width'),
                            'height': first_validation.get('height'),
                        })
                    previous_library = list(library)
                    moved = False
                    try:
                        os.replace(staging_dir, material_dir)
                        moved = True
                        library.insert(0, item)
                        save_library(library)
                    except Exception:
                        try:
                            save_library(previous_library)
                        except Exception:
                            pass
                        if moved:
                            try:
                                os.replace(material_dir, staging_dir)
                            except OSError:
                                shutil.rmtree(material_dir, ignore_errors=True)
                        raise
                    return item
                snapshot = dict(existing)
                snapshot_token = record_token(existing)

            existing_valid = record_is_valid(snapshot)

            prepared_mid = None
            prepared_material_dir = None
            prepared_backups = []
            if not existing_valid:
                prepared_mid = str(snapshot.get('id') or uuid.uuid4().hex)
                prepared_material_dir = os.path.join(MATERIALS_DIR, prepared_mid)
                for old_name in snapshot.get('files') or []:
                    old_path = os.path.join(prepared_material_dir, old_name)
                    if os.path.isfile(old_path):
                        backup = _prepare_material_quarantine(
                            old_path, MATERIAL_QUARANTINE_DIR, prepared_mid, 'invalid_historical_media'
                        )
                        if backup:
                            prepared_backups.append(backup)
                backed_up_paths = {item['originalPath'] for item in prepared_backups}
                for name in saved:
                    final_path = os.path.join(prepared_material_dir, name)
                    if os.path.isfile(final_path) and final_path not in backed_up_paths:
                        backup = _prepare_material_quarantine(
                            final_path, MATERIAL_QUARANTINE_DIR, prepared_mid, 'overwritten_historical_media'
                        )
                        if backup:
                            prepared_backups.append(backup)
                            backed_up_paths.add(final_path)

            with STATE_LOCK:
                library = load_library()
                existing_index, current = find_existing(library)
                if current is None or record_token(current) != snapshot_token:
                    continue
                if existing_valid:
                    updated = dict(current)
                    current_title = str(updated.get('title') or '')
                    if title and (not current_title or current_title == os.path.basename(save_path) or current_title == source_url):
                        updated['title'] = title[:120]
                    for key, value in metadata_updates.items():
                        if value and not updated.get(key):
                            updated[key] = value
                    if updated != current:
                        library[existing_index] = updated
                        save_library(library)
                        return updated
                    return current

                mid = prepared_mid
                material_dir = prepared_material_dir
                os.makedirs(material_dir, exist_ok=True)
                previous_library = list(library)
                backups = prepared_backups
                installed_paths = []
                try:
                    for name in saved:
                        staged_path = os.path.join(staging_dir, name)
                        final_path = os.path.join(material_dir, name)
                        os.replace(staged_path, final_path)
                        installed_paths.append(final_path)

                    repaired = dict(current)
                    repair_updates = {
                        'id': mid,
                        'title': (work.get('desc') or work.get('title') or current.get('title') or saved[0])[:120],
                        'type': mtype,
                        'files': list(saved),
                        'urls': ['/api/library/file/%s/%s' % (mid, fn) for fn in saved],
                        'platform': platform or current.get('platform') or 'douyin',
                        'sourceUrl': source_url or current.get('sourceUrl') or '',
                        'sourceDownloadPath': save_path,
                        'sourceDownloadKey': dedupe_key,
                        'sourceAuthor': work.get('nickname') or work.get('author') or current.get('sourceAuthor') or '',
                        'repaired': True,
                        'repairedAt': time.time(),
                    }
                    repair_updates.update({k: v for k, v in metadata_updates.items() if v})
                    if mtype == 'video':
                        for key in ('duration', 'width', 'height'):
                            value = first_validation.get(key)
                            if isinstance(value, (int, float)) and value > 0:
                                repair_updates[key] = value
                    repaired.update(repair_updates)
                    library[existing_index] = repaired
                    save_library(library)
                except Exception:
                    restore_error = None
                    try:
                        _restore_material_files_from_quarantine(backups, installed_paths)
                    except Exception as exc:
                        restore_error = exc
                    try:
                        save_library(previous_library)
                    except Exception:
                        pass
                    if restore_error:
                        raise restore_error
                    raise
                final_paths = {os.path.join(material_dir, name) for name in saved}
                for backup in backups:
                    old_path = backup.get('originalPath') or ''
                    if old_path and old_path not in final_paths:
                        try:
                            if os.path.isfile(old_path):
                                os.remove(old_path)
                        except OSError:
                            pass
                return repaired
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def download_douyin_work_with_refresh(auth, url, save_choice='all'):
    for attempt in range(2):
        work = SPIDER.spider_work(auth, url)
        try:
            return work, download_work(work, BASE_PATH['media'], save_choice, auth=auth)
        except MediaDownloadError as exc:
            if exc.code == 'download_http_403' and attempt == 0:
                continue
            raise
    raise MediaDownloadError('download_http_403')


def discover_leads_by_keyword(auth, keyword, video_num=5, comment_mode='page'):
    """自动寻客：产品词 -> 搜索相关视频 -> 抓评论 -> 识别意向客户。"""
    keyword = (keyword or '').strip()
    if not keyword:
        raise RuntimeError('missing_keyword')
    video_num = max(1, min(int(video_num or 5), 20))

    search_errors = []
    browser_search_error = None
    videos = []

    fast_cache_ttl = int(os.getenv('DY_SEARCH_CACHE_FAST_TTL_SEC', '900') or 900)
    if fast_cache_ttl > 0:
        fast_cache = load_douyin_search_cache(keyword, video_num, ttl_sec=fast_cache_ttl)
        if fast_cache:
            videos = fast_cache.get('items') or []
            search_errors.append({'stage': 'search-cache-fast', 'ageSec': fast_cache.get('ageSec'), 'reason': 'recent_verified_cache'})

    if not videos:
        try:
            videos = browser_search_videos(keyword, video_num, getattr(auth, 'cookie', None))
        except Exception as e:
            browser_search_error = str(e)

    # Legacy API fallback only after browser search fails. Calling it first can trigger
    # verify_check with generated msToken cookies and poison the following browser pass.
    if not videos:
        try:
            raw = SPIDER.douyin_apis.search_some_general_work(
                auth, keyword, video_num, '0', '0', '', '', '1'
            )
        except Exception as e:
            raw = []
            search_errors.append({'stage': 'search-video', 'error': str(e)})
        for item in raw or []:
            aweme = item.get('aweme_info') if isinstance(item, dict) else None
            aweme = aweme or item
            if not isinstance(aweme, dict):
                continue
            try:
                info = handle_work_info(aweme)
            except Exception:
                info = safe_work_info(aweme)
            if info.get('work_url'):
                videos.append(info)

    if not videos:
        try:
            raw = SPIDER.douyin_apis.search_some_general_work(
                auth, keyword, video_num, '0', '0', '', '', '0'
            )
        except Exception as e:
            raw = []
            search_errors.append({'stage': 'search-all', 'error': str(e)})
        for item in raw or []:
            aweme = item.get('aweme_info') if isinstance(item, dict) else None
            aweme = aweme or item
            if not isinstance(aweme, dict):
                continue
            try:
                info = handle_work_info(aweme)
            except Exception:
                info = safe_work_info(aweme)
            if info.get('work_url'):
                videos.append(info)

    if videos:
        save_douyin_search_cache(keyword, video_num, videos, source='finder-discover')

    if not videos:
        search_cache = load_douyin_search_cache(keyword, video_num)
        if search_cache:
            videos = search_cache.get('items') or []
            search_errors.append({'stage': 'search-cache-fallback', 'ageSec': search_cache.get('ageSec'), 'reason': 'live_search_empty'})

    if not videos:
        cached = _load_json(FINDER_LAST_JSON, {})
        if isinstance(cached, dict) and (cached.get('keyword') or '') == keyword and cached.get('videos'):
            data = {k: v for k, v in cached.items() if k != 'ok'}
            data['cacheFallback'] = True
            data['errors'] = (data.get('errors') or []) + search_errors
            return data

    seen = set()
    comments = []
    errors = list(search_errors)
    for v in videos[:video_num]:
        url = v.get('work_url')
        try:
            if comment_mode == 'all':
                raw_comments = SPIDER.douyin_apis.get_work_all_out_comment(auth, url)
            else:
                page = SPIDER.douyin_apis.get_work_out_comment(auth, url, '0')
                raw_comments = page.get('comments') if isinstance(page, dict) else page
            items = normalize_comments(raw_comments, limit=80)
            for it in items:
                it['sourceVideoUrl'] = url
                it['sourceVideoTitle'] = v.get('title') or ''
                it['sourceAuthor'] = v.get('nickname') or ''
                it['sourceAwemeId'] = str(v.get('work_id') or extract_aweme_id(url) or '')
                if not it.get('awemeId'):
                    it['awemeId'] = it['sourceAwemeId']
                key = (it.get('uniqueId') or it.get('user') or '') + '|' + (it.get('text') or '')
                if key in seen:
                    continue
                seen.add(key)
                comments.append(it)
        except Exception as e:
            errors.append({'url': url, 'error': str(e)})

    priority = {'高意向': 0, '中意向': 1, '咨询': 2, '普通': 3}
    comments.sort(key=lambda x: (priority.get(x.get('intent'), 9), -int(x.get('diggCount') or 0)))
    leads = [x for x in comments if x.get('intent') in ('高意向', '中意向', '咨询')]
    return {
        'keyword': keyword,
        'platform': 'douyin',
        'videos': videos[:video_num],
        'videoCount': len(videos[:video_num]),
        'comments': comments,
        'commentCount': len(comments),
        'leads': leads,
        'leadCount': len(leads),
        'errors': errors,
        'browserSearchError': browser_search_error,
    }


def discover_leads_by_keyword_platform(platform, auth, keyword, video_num=5, comment_mode='page', guest_mode=True):
    platform = platform_code(platform)
    if platform == 'xhs':
        return discover_xhs_leads_by_keyword(
            keyword,
            video_num=video_num,
            comment_mode=comment_mode,
            data_dir=DATA_DIR,
            guest_mode=guest_mode,
        )
    data = discover_leads_by_keyword(auth, keyword, video_num=video_num, comment_mode=comment_mode)
    data.setdefault('platform', 'douyin')
    return data


AWEME_PATTERNS = (
    re.compile(r'/video/(\d{6,})'),
    re.compile(r'[?&]modal_id=(\d{6,})'),
    re.compile(r'[?&]aweme_id=(\d{6,})'),
    re.compile(r'(^|\D)(\d{10,})(\D|$)'),
)


def bool_arg(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ('1', 'true', 'yes', 'y', 'on'):
        return True
    if s in ('0', 'false', 'no', 'n', 'off'):
        return False
    return default


def extract_aweme_id(value):
    """Extract aweme_id from a Douyin URL, modal_id or raw numeric ID."""
    text = str(value or '').strip()
    if not text:
        return ''
    if re.fullmatch(r'\d{6,}', text):
        return text
    for pat in AWEME_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1 if pat.pattern.startswith('/') or 'modal_id' in pat.pattern or 'aweme_id' in pat.pattern else 2)
    if text.startswith('http'):
        try:
            import requests
            res = requests.get(text, allow_redirects=True, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if res.url and res.url != text:
                return extract_aweme_id(res.url)
            m = re.search(r'(?:video/|modal_id=)(\d{6,})', res.text or '')
            if m:
                return m.group(1)
        except Exception:
            pass
    return ''


def cached_douyin_comments_for_url(url, limit=120):
    """Return recently captured real Douyin comments for the same aweme_id."""
    aweme_id = extract_aweme_id(url)
    if not aweme_id:
        return []
    try:
        data = _load_json(FINDER_LAST_JSON, {})
    except Exception:
        data = {}
    comments = data.get('comments') if isinstance(data, dict) else []
    out = []
    for c in comments or []:
        if not isinstance(c, dict):
            continue
        cid_aweme = str(c.get('awemeId') or c.get('sourceAwemeId') or extract_aweme_id(c.get('sourceVideoUrl')) or '')
        if cid_aweme != str(aweme_id):
            continue
        out.append(c)
        if len(out) >= int(limit or 120):
            break
    return out


def compact_text(text, max_len=110):
    text = re.sub(r'\s+', ' ', str(text or '').replace('\u200b', '')).strip()
    replacements = {
        '\u5168\u7f51\u6700\u597d': '\u53e3\u7891\u4e0d\u9519',
        '\u6700': '\u5f88',
        '\u7b2c\u4e00': '\u9760\u524d',
        '\u56fd\u5bb6\u7ea7': '\u4f18\u8d28',
        '\u514d\u8d39': '\u8d60\u9001',
        '\u7edd\u5bf9': '\u6bd4\u8f83',
        '\u6c38\u4e45': '\u957f\u671f',
        '100%': '\u9ad8',
        '\u9876\u7ea7': '\u4f18\u8d28',
        '\u79d2\u6740': '\u9650\u65f6\u4f18\u60e0',
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    if max_len and len(text) > max_len:
        text = text[:max_len - 1].rstrip('\uff0c\u3002,. ') + '\u2026'
    return text


def fill_template(template, values):
    text = str(template or '')
    for k, v in values.items():
        text = text.replace('{' + k + '}', str(v or ''))
    return text


def build_ai_outreach_comment(keyword, template='', lead=None, video=None):
    """Local AI-like outreach copy generator used by the native outreach center."""
    lead = lead or {}
    video = video or {}
    title = compact_text(video.get('title') or lead.get('sourceVideoTitle') or '', 36)
    comment = compact_text(lead.get('text') or lead.get('c') or '', 42)
    if not comment:
        comment = title or compact_text(keyword, 36)
    author = compact_text(video.get('nickname') or lead.get('sourceAuthor') or '', 20)
    intent = lead.get('intent') or ''
    values = {
        'keyword': keyword or '',
        'product': keyword or '',
        'comment': comment,
        'lead': comment,
        'title': title,
        'author': author,
        'intent': intent,
        'user': lead.get('user') or lead.get('u') or '',
    }
    if template:
        return compact_text(fill_template(template, values), 110)
    if comment and ('?' in comment or '\uff1f' in comment or intent == '\u54a8\u8be2'):
        text = '\u770b\u5230\u4f60\u95ee\u201c{comment}\u201d\uff0c{keyword}\u8fd9\u7c7b\u6211\u521a\u6574\u7406\u8fc7\u9009\u8d2d\u5efa\u8bae\u548c\u540c\u6b3e\u4fe1\u606f\uff0c\u9700\u8981\u7684\u8bdd\u53ef\u4ee5\u770b\u4e3b\u9875/\u79c1\u4fe1\u6211\uff5e'
    elif intent in ('\u9ad8\u610f\u5411', '\u4e2d\u610f\u5411'):
        text = '{keyword}\u76f8\u5173\u6e05\u5355\u6211\u8fd9\u8fb9\u6709\u6574\u7406\uff0c\u9002\u5408\u60f3\u5bf9\u6bd4\u529f\u6548/\u4ef7\u683c\u7684\u59d0\u59b9\uff0c\u9700\u8981\u53ef\u770b\u4e3b\u9875\u4e86\u89e3\uff5e'
    else:
        text = '{keyword}\u76f8\u5173\u597d\u7269\u548c\u907f\u5751\u70b9\u5df2\u6574\u7406\u597d\uff0c\u611f\u5174\u8da3\u53ef\u4ee5\u770b\u4e3b\u9875\u4ea4\u6d41\uff5e'
    return compact_text(fill_template(text, values), 110)


def comment_publish_ok(resp):
    if not isinstance(resp, dict):
        return False
    if resp.get('dryRun'):
        return True
    code = resp.get('status_code', resp.get('statusCode', resp.get('code')))
    msg = str(resp.get('status_msg') or resp.get('statusMsg') or resp.get('message') or resp.get('msg') or '')
    if code in (0, '0', None) and not any(x in msg.lower() for x in ('error', 'fail', '\u5931\u8d25')):
        return True
    return bool(resp.get('comment') or resp.get('cid') or resp.get('comment_id'))


def verify_comment_visible(auth, aweme_id, content, timeout_sec=12):
    """Verify a just-submitted comment by reading the target video's comments.

    Douyin's web publish endpoint can occasionally return HTTP 200 with an empty
    body. The product must not mark that as success unless the comment can be
    observed afterwards.
    """
    aweme_id = extract_aweme_id(aweme_id)
    content = compact_text(content or '', 160)
    if not aweme_id or not content:
        return {'ok': False, 'reason': 'missing_verify_target'}
    url = 'https://www.douyin.com/video/' + aweme_id
    deadline = time.time() + max(3, min(float(timeout_sec or 12), 30))
    last_error = ''
    attempts = 0
    while time.time() < deadline:
        attempts += 1
        try:
            data = SPIDER.douyin_apis.get_work_out_comment(auth, url, '0')
            items = normalize_comments(data.get('comments') if isinstance(data, dict) else data, limit=120)
            for it in items:
                txt = compact_text(it.get('text') or '', 180)
                if content and (txt == content or content in txt or txt in content):
                    return {
                        'ok': True,
                        'attempts': attempts,
                        'matched': {
                            'id': it.get('id') or '',
                            'text': txt,
                            'user': it.get('user') or '',
                            'createTime': it.get('createTime') or 0,
                        },
                    }
        except Exception as e:
            last_error = str(e)
        time.sleep(2.0)
    return {'ok': False, 'attempts': attempts, 'reason': 'comment_not_visible_after_publish', 'lastError': last_error}



COMMENT_RISK_WORDS = {
    '\u4e3b\u9875': '\u7b14\u8bb0',
    '\u79c1\u4fe1': '\u4ea4\u6d41',
    '\u94fe\u63a5': '\u4fe1\u606f',
    '\u4e0b\u5355': '\u4e86\u89e3',
    '\u4f18\u60e0': '\u6d3b\u52a8',
    '\u540c\u6b3e': '\u76f8\u5173',
    '\u5fae\u4fe1': '\u8054\u7cfb\u65b9\u5f0f',
    'VX': '\u8054\u7cfb\u65b9\u5f0f',
    'vx': '\u8054\u7cfb\u65b9\u5f0f',
}


def sanitize_comment_for_risk(text):
    text = compact_text(text, 110)
    for a, b in COMMENT_RISK_WORDS.items():
        text = text.replace(a, b)
    # Add a soft suffix when the generated comment has no natural closing tone.
    tails = ['\uff5e', '\u54c8', '\u53ef\u4ee5\u53c2\u8003\u4e0b']
    if text and not any(text.endswith(t) for t in tails):
        text = text.rstrip('~\uff5e\u3002') + '\uff5e'
    return compact_text(text, 110)


def load_comment_risk_state():
    data = _load_json(COMMENT_RISK_JSON, {})
    return data if isinstance(data, dict) else {}


def save_comment_risk_state(data):
    data = data if isinstance(data, dict) else {}
    _save_json(COMMENT_RISK_JSON, data)


def comment_risk_cooldown_left():
    st = load_comment_risk_state()
    until = float(st.get('cooldownUntil') or 0)
    left = int(max(0, until - time.time()))
    return left, st


def mark_comment_risk(reason, resp=None, cooldown_sec=None):
    if cooldown_sec is None:
        cooldown_sec = int(os.getenv('DY_COMMENT_RISK_COOLDOWN', '1800') or 1800)
    st = load_comment_risk_state()
    st.update({
        'lastReason': reason,
        'lastAt': time.time(),
        'cooldownUntil': time.time() + max(60, cooldown_sec),
        'lastResponse': resp or {},
    })
    try:
        save_comment_risk_state(st)
    except Exception:
        pass
    return st


def is_comment_risk_response(resp):
    if not isinstance(resp, dict):
        return False
    r = resp.get('response') if isinstance(resp.get('response'), dict) else resp
    code = r.get('status_code', r.get('statusCode', r.get('code')))
    msg = str(r.get('status_msg') or r.get('message') or r.get('msg') or '')
    return str(code) in ('8', '9', '10000', '10001') or any(x in msg for x in ('\u98ce\u63a7', '\u9a8c\u8bc1', '\u767b\u5f55', '\u9891\u7e41'))


def browser_comment_preflight(aweme_id, auth=None, timeout_sec=18):
    """Use the persisted browser profile as a low-risk gate before writing comments.

    If the visible platform UI is not in an interactive-login state, direct publish is
    likely to return status_code=8. In safe mode we stop before touching publish.
    """
    # If the customer already has the cloud browser open, it owns the persistent
    # Chromium profile. Do not launch a second persistent context for preflight;
    # that can block on "Opening in existing browser session". The actual cloud
    # UI fallback will still detect verification/login pages before sending.
    try:
        sid, sess = find_cloud_session_for_account('douyin-self')
        if sess and not getattr(sess, 'closed', False):
            st = sess.status()
            if st.get('loggedIn'):
                return {
                    'ok': True,
                    'usingCloudSession': True,
                    'sessionId': sid,
                    'url': st.get('url') or '',
                    'hasUser': True,
                    'text': 'cloud browser session is active',
                }
    except Exception:
        pass
    try:
        from playwright.sync_api import sync_playwright
        from utils.cookie_util import LOGIN_STEALTH_INIT_JS
    except Exception as e:
        return {'ok': True, 'skipped': True, 'reason': 'playwright_unavailable', 'error': str(e)}
    edge_exe = os.getenv('DY_EDGE_PATH', r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    profile_dir = os.path.abspath(os.getenv('DY_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_profile')))
    os.makedirs(profile_dir, exist_ok=True)
    url = 'https://www.douyin.com/video/' + str(aweme_id)
    args = ['--disable-blink-features=AutomationControlled', '--disable-infobars', '--no-first-run', '--no-default-browser-check', '--lang=zh-CN']
    with sync_playwright() as p:
        kw = dict(
            headless=os.getenv('DY_COMMENT_PREFLIGHT_HEADLESS', '1').strip().lower() not in ('0', 'false', 'no'),
            args=args,
            ignore_default_args=['--enable-automation'],
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            viewport={'width': 1280, 'height': 900},
        )
        if edge_exe and os.path.exists(edge_exe):
            kw['executable_path'] = edge_exe
        ctx = p.chromium.launch_persistent_context(profile_dir, **kw)
        try:
            try:
                ctx.add_init_script(LOGIN_STEALTH_INIT_JS)
            except Exception:
                pass
            if auth and getattr(auth, 'cookie', None):
                try:
                    ctx.add_cookies([{'name': k, 'value': str(v), 'url': 'https://www.douyin.com/'} for k, v in (auth.cookie or {}).items()])
                except Exception:
                    pass
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=int(timeout_sec * 1000))
            page.wait_for_timeout(4500)
            info = page.evaluate("""() => {
              const title = document.title || '';
              const text = document.body ? document.body.innerText : '';
              const verifyTitle = title.includes('\u9a8c\u8bc1\u7801\u4e2d\u95f4\u9875') || title.toLowerCase().includes('captcha');
              const verifyText = text.includes('\u8bf7\u5b8c\u6210\u4e0b\u5217\u9a8c\u8bc1\u540e\u7ee7\u7eed') || text.includes('\u6309\u4f4f\u5de6\u8fb9\u6309\u94ae\u62d6\u52a8\u5b8c\u6210\u4e0a\u65b9\u62fc\u56fe');
              const loginHints = ['\u8bf7\u5148\u767b\u5f55\u540e\u53d1\u8868\u8bc4\u8bba','\u767b\u5f55\u540e\u5373\u53ef\u53c2\u4e0e\u4e92\u52a8\u8ba8\u8bba','\u7acb\u5373\u767b\u5f55','\u767b\u5f55'];
              const hasLoginHint = loginHints.some(x => text.includes(x));
              const visible = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el); return r.width > 20 && r.height > 12 && st.visibility !== 'hidden' && st.display !== 'none'; };
              const inputs = Array.from(document.querySelectorAll('textarea,[contenteditable=true],[role="textbox"],input')).filter(visible);
              const hasVisibleCommentInput = inputs.some(el => {
                const s = ((el.placeholder || el.innerText || el.textContent || el.value || '') + ' ' + (el.className || '')).toString();
                return /\u8bc4\u8bba|\u53d1\u8868|comment|\u56de\u590d/.test(s) || (el.tagName === 'TEXTAREA' && el.offsetParent);
              });
              const loginButtons = Array.from(document.querySelectorAll('button,[role=button],a')).filter(visible).filter(el => /\u767b\u5f55|\u7acb\u5373\u767b\u5f55/.test(el.innerText || el.textContent || ''));
              const hasUser = localStorage.getItem('HasUserLogin') === '1' || !!localStorage.getItem('user_info');
              return {url: location.href, title, hasVerification: !!(verifyTitle || verifyText), hasLoginHint, hasVisibleCommentInput, loginButtonCount: loginButtons.length, hasUser, text: text.slice(0, 300)};
            }""")
            if info.get('hasVerification'):
                return {'ok': False, 'reason': 'comment_verification_required', **info}
            if info.get('loginButtonCount') or (info.get('hasLoginHint') and not info.get('hasVisibleCommentInput')):
                # Douyin video pages can show generic "login" text in nav/sidebar even
                # when the persisted profile is already authenticated.  If localStorage
                # confirms a user session and there is no visible login button, do not
                # block the write path solely because the comment editor has not been
                # rendered yet.
                if info.get('hasUser') and not info.get('loginButtonCount'):
                    return {'ok': True, 'warning': 'comment_input_not_visible_but_user_logged_in', **info}
                return {'ok': False, 'reason': 'comment_login_required', **info}
            if not info.get('hasVisibleCommentInput'):
                if info.get('hasUser'):
                    return {'ok': True, 'warning': 'comment_input_not_visible_but_user_logged_in', **info}
                return {'ok': False, 'reason': 'comment_input_not_ready', **info}
            return {'ok': True, **info}
        finally:
            ctx.close()

def comment_edge_ui_fallback_enabled():
    return os.getenv('DY_COMMENT_EDGE_UI_FALLBACK', '1').strip().lower() not in ('0', 'false', 'no', 'off')


def should_edge_ui_fallback(resp=None, preflight=None):
    if preflight and (preflight.get('reason') in ('comment_login_required', 'comment_input_not_ready', 'comment_verification_required')):
        return True
    if not isinstance(resp, dict):
        return False
    r = resp.get('response') if isinstance(resp.get('response'), dict) else resp
    code = str(r.get('status_code', r.get('statusCode', r.get('code', ''))))
    msg = str(r.get('status_msg') or r.get('message') or r.get('msg') or '')
    return code in ('8', '9') or (code == '200' and 'non_json_response' in msg) or any(x in msg for x in ('登录', '验证', 'login', 'verify'))


COMMENT_UI_LOCK = threading.RLock()


def publish_comment_via_cloud_ui(auth, aweme_id, content, reply_id='', payload=None, reason='cloud_ui'):
    if os.getenv('DY_COMMENT_CLOUD_UI_FALLBACK', '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return {'request': payload or {}, 'ok': False, 'status': 'cloud_ui_disabled', 'channel': 'cloud-ui'}
    aweme_id = extract_aweme_id(aweme_id)
    content = compact_text(content or '', 160)
    if not aweme_id or not content:
        return {'request': payload or {}, 'ok': False, 'status': 'invalid_target', 'channel': 'cloud-ui'}
    with COMMENT_UI_LOCK:
        sid, sess = find_cloud_session_for_account('douyin-self')
        created = False
        if not sess:
            sid = uuid.uuid4().hex
            release_chromium_profile_if_stale(_cloud_profile_dir('douyin-self'))
            sess = CloudLoginSession(sid, account_id='douyin-self', login_url='https://www.douyin.com/video/' + str(aweme_id))
            with CLOUD_LOGIN_LOCK:
                CLOUD_LOGIN_SESSIONS[sid] = sess
            try:
                sess.start(timeout=45)
                created = True
            except Exception as e:
                with CLOUD_LOGIN_LOCK:
                    CLOUD_LOGIN_SESSIONS.pop(sid, None)
                try:
                    sess.close()
                except Exception:
                    pass
                return {
                    'request': payload or {},
                    'ok': False,
                    'status': 'cloud_ui_start_failed',
                    'channel': 'cloud-ui',
                    'error': str(e),
                    'trace': traceback.format_exc(),
                }
        try:
            ui = sess.send_comment(aweme_id, content, reply_id=reply_id)
        except Exception as e:
            return {
                'request': payload or {},
                'ok': False,
                'status': 'cloud_ui_exception',
                'channel': 'cloud-ui',
                'sessionId': sid,
                'createdSession': created,
                'error': str(e),
                'trace': traceback.format_exc(),
            }
        verify = {'ok': False, 'skipped': True, 'reason': 'ui_not_clicked'}
        if ui.get('ok') or ui.get('clicked'):
            try:
                verify_auth = auth or ensure_auth_from_cache()
                verify = verify_comment_visible(verify_auth, aweme_id, content, timeout_sec=int(os.getenv('DY_COMMENT_VERIFY_TIMEOUT', '14') or 14))
            except Exception as e:
                verify = {'ok': False, 'reason': 'readback_exception', 'error': str(e)}
        ok = bool(ui.get('ok') and (ui.get('domVerified') or verify.get('ok')))
        return {
            'request': payload or {},
            'response': ui,
            'verification': verify,
            'ok': ok,
            'status': 'sent_verified' if ok else 'cloud_ui_failed',
            'channel': 'cloud-ui',
            'sessionId': sid,
            'createdSession': created,
            'verifiedBy': 'comment_readback' if verify.get('ok') else ('cloud_browser_dom' if ui.get('domVerified') else ''),
            'fallbackReason': reason,
        }


def publish_comment_via_edge_ui(aweme_id, content, reply_id='', payload=None, reason='edge_ui', auth=None):
    cloud = publish_comment_via_cloud_ui(auth, aweme_id, content, reply_id=reply_id, payload=payload, reason=reason)
    if cloud.get('ok') or os.getenv('DY_COMMENT_EDGE_UI_ONLY', '0').strip().lower() in ('1', 'true', 'yes'):
        return cloud
    # The legacy Edge/pyautogui fallback is Windows-desktop only.  On the Linux
    # execution node the product path is the cloud browser; returning the legacy
    # error hides the real cloud-browser diagnosis.
    if os.name != 'nt':
        return cloud
    if (cloud.get('response') or {}).get('reason') in ('comment_verification_required', 'comment_login_required'):
        return cloud
    if not send_comment_via_edge_ui:
        return {
            'request': payload or {},
            'response': {'ok': False, 'error': 'edge_ui_module_unavailable', 'channel': 'edge-ui'},
            'ok': False,
            'status': 'edge_ui_unavailable',
            'channel': 'edge-ui',
        }
    ui = send_comment_via_edge_ui(aweme_id, content, reply_id=reply_id)
    return {
        'request': payload or {},
        'response': ui,
        'ok': bool(ui.get('ok')),
        'status': 'sent' if ui.get('ok') else 'edge_ui_failed',
        'channel': 'edge-ui',
        'fallbackReason': reason,
    }


def publish_comment_to_douyin(auth, aweme_id, content, reply_id='', dry_run=False, safe_mode=True, preflight=True, force=False, channel='auto'):
    auth = ensure_auth_security_material(auth)
    aweme_id = extract_aweme_id(aweme_id)
    content = sanitize_comment_for_risk(content) if safe_mode else compact_text(content, 160)
    reply_id = str(reply_id or '').strip()
    channel = (channel or 'auto').strip().lower()
    if not aweme_id:
        raise RuntimeError('missing_aweme_id')
    if not content:
        raise RuntimeError('missing_content')
    payload = {'awemeId': aweme_id, 'content': content, 'replyId': reply_id, 'safeMode': bool(safe_mode), 'channel': channel}
    if dry_run:
        return {'dryRun': True, 'ok': True, **payload}
    if channel in ('edge-ui', 'edge_ui', 'ui', 'browser-ui', 'browser_ui', 'cloud-ui', 'cloud_ui'):
        return publish_comment_via_edge_ui(aweme_id, content, reply_id=reply_id, payload=payload, reason='forced_edge_ui', auth=auth)
    if safe_mode and not force:
        left, st = comment_risk_cooldown_left()
        if left > 0:
            return {'ok': False, 'skipped': True, 'status': 'risk_cooldown', 'cooldownLeft': left, 'riskState': st, 'request': payload}
        if preflight:
            pf = browser_comment_preflight(aweme_id, auth=auth)
            if not pf.get('ok'):
                reason = pf.get('reason') or 'preflight_blocked'
                mark_douyin_capability(
                    'commentWrite',
                    False,
                    reason,
                    pf,
                    requires_reauth=reason in ('comment_login_required', 'comment_input_not_ready', 'comment_verification_required'),
                )
                if channel in ('auto', '') and comment_edge_ui_fallback_enabled() and should_edge_ui_fallback(preflight=pf):
                    return publish_comment_via_edge_ui(aweme_id, content, reply_id=reply_id, payload={**payload, 'preflight': pf}, reason=pf.get('reason') or 'preflight', auth=auth)
                mark_comment_risk(reason, pf, cooldown_sec=900)
                return {'ok': False, 'skipped': True, 'status': 'preflight_blocked', 'preflight': pf, 'request': payload}
            payload['preflight'] = pf
            mark_douyin_capability('commentWrite', True, 'preflight_ok', pf)
    resp = SPIDER.douyin_apis.publish_comment(auth, aweme_id, content, reply_id=reply_id)
    out = {'request': payload, 'response': resp, 'ok': comment_publish_ok(resp)}
    if not out['ok'] and isinstance(resp, dict) and str(resp.get('status_code')) == '200' and str(resp.get('status_msg') or '') == 'non_json_response':
        verify = verify_comment_visible(auth, aweme_id, content, timeout_sec=int(os.getenv('DY_COMMENT_VERIFY_TIMEOUT', '14') or 14))
        out['verification'] = verify
        if verify.get('ok'):
            out['ok'] = True
            out['status'] = 'sent_verified'
            out['verifiedBy'] = 'comment_readback'
    if (not out['ok']) and channel in ('auto', '') and comment_edge_ui_fallback_enabled() and should_edge_ui_fallback(resp=resp):
        ui_out = publish_comment_via_edge_ui(aweme_id, content, reply_id=reply_id, payload={**payload, 'apiResponse': resp}, reason='api_status_%s' % (resp.get('status_code') if isinstance(resp, dict) else 'unknown'), auth=auth)
        if ui_out.get('ok'):
            return ui_out
        out['edgeUiFallback'] = ui_out
    if safe_mode and is_comment_risk_response(resp):
        out['status'] = 'risk_blocked'
        out['riskState'] = mark_comment_risk('publish_status_code_%s' % (resp.get('status_code') if isinstance(resp, dict) else 'unknown'), resp)
    return out


def publish_comment_to_platform(platform, auth, target_id, content, reply_id='', dry_run=False, safe_mode=True, preflight=True, force=False, channel='auto', target_url=''):
    platform = platform_code(platform)
    if platform == 'xhs':
        note_url = target_url or target_id
        account_id = _xhs_safety_account_id('')
        gate = xhs_safety_preflight("comment", account_id, dry_run=dry_run)
        if not gate.get("ok"):
            return {'ok': False, **gate}
        resp = xhs_publish_comment(note_url, content, dry_run=dry_run, safe_mode=safe_mode, data_dir=DATA_DIR)
        record = xhs_safety_record("comment", account_id, resp, dry_run=dry_run)
        resp.setdefault('ok', bool(resp.get('clicked') or resp.get('dryRun')))
        resp.setdefault('safety', record.get('safety'))
        return resp
    return publish_comment_to_douyin(auth, target_id, content, reply_id=reply_id, dry_run=dry_run, safe_mode=safe_mode, preflight=preflight, force=force, channel=channel)


def find_video_for_lead(videos, lead):
    aweme_id = str(lead.get('awemeId') or lead.get('sourceAwemeId') or '')
    url = lead.get('sourceVideoUrl') or ''
    for v in videos or []:
        if aweme_id and str(v.get('work_id') or extract_aweme_id(v.get('work_url'))) == aweme_id:
            return v
        if url and v.get('work_url') == url:
            return v
    return {}


def build_outreach_targets(discovery, limit=5, send_mode='reply'):
    limit = max(1, min(int(limit or 5), 30))
    send_mode = (send_mode or 'reply').lower()
    videos = discovery.get('videos') or []
    leads = discovery.get('leads') or []
    targets = []
    seen = set()
    for lead in leads:
        aweme_id = str(lead.get('awemeId') or lead.get('sourceAwemeId') or extract_aweme_id(lead.get('sourceVideoUrl')) or '')
        if not aweme_id:
            continue
        reply_id = str(lead.get('id') or '') if send_mode in ('reply', 'comment_reply', 'reply_comment') else ''
        key = reply_id or aweme_id
        if key in seen:
            continue
        seen.add(key)
        video = find_video_for_lead(videos, lead)
        targets.append({'type': 'lead', 'awemeId': aweme_id, 'replyId': reply_id, 'lead': lead, 'video': video})
        if len(targets) >= limit:
            return targets
    # Fallback: if no intent leads are found, comment once per related video.
    for v in videos:
        aweme_id = str(v.get('work_id') or extract_aweme_id(v.get('work_url')) or '')
        if not aweme_id or aweme_id in seen:
            continue
        seen.add(aweme_id)
        targets.append({'type': 'video', 'awemeId': aweme_id, 'replyId': '', 'lead': {}, 'video': v})
        if len(targets) >= limit:
            break
    return targets


def run_ai_outreach(auth, keyword, template='', video_num=5, limit=5, dry_run=False, send_mode='reply', interval_sec=45, safe_mode=True, preflight=True, force=False, channel='auto', platform='douyin'):
    platform = platform_code(platform)
    discovery = discover_leads_by_keyword_platform(platform, auth, keyword, video_num, 'page')
    targets = build_outreach_targets(discovery, limit=limit, send_mode=send_mode)
    results = []
    for idx, target in enumerate(targets):
        lead = target.get('lead') or {}
        video = target.get('video') or {}
        content = build_ai_outreach_comment(keyword, template, lead, video)
        item = {
            'id': uuid.uuid4().hex,
            'platform': platform,
            'type': target.get('type'),
            'awemeId': target.get('awemeId'),
            'videoUrl': video.get('work_url') or video.get('note_url') or lead.get('sourceVideoUrl') or (('https://www.xiaohongshu.com/explore/' if platform == 'xhs' else 'https://www.douyin.com/video/') + str(target.get('awemeId'))),
            'videoTitle': video.get('title') or lead.get('sourceVideoTitle') or '',
            'author': video.get('nickname') or lead.get('sourceAuthor') or '',
            'leadUser': lead.get('user') or '',
            'leadText': lead.get('text') or '',
            'intent': lead.get('intent') or '',
            'replyId': target.get('replyId') or '',
            'content': content,
            'dryRun': bool(dry_run),
        }
        try:
            target_url = item.get('videoUrl') or lead.get('sourceVideoUrl') or video.get('note_url') or ''
            resp = publish_comment_to_platform(platform, auth, item['awemeId'], content, item['replyId'], dry_run=dry_run, safe_mode=safe_mode, preflight=preflight, force=force, channel=channel, target_url=target_url)
            item['ok'] = bool(resp.get('ok', comment_publish_ok(resp)))
            item['response'] = resp
            item['status'] = 'dry_run' if dry_run else (resp.get('status') or ('sent' if item['ok'] else 'failed'))
        except Exception as e:
            item['ok'] = False
            item['status'] = 'error'
            item['error'] = str(e)
            item['trace'] = traceback.format_exc()
        results.append(item)
        if safe_mode and item.get('status') in ('risk_blocked', 'risk_cooldown', 'preflight_blocked'):
            break
        if not dry_run and idx < len(targets) - 1 and interval_sec:
            time.sleep(max(0.0, min(float(interval_sec), 120.0)))
    summary = {
        'platform': platform,
        'keyword': keyword,
        'dryRun': bool(dry_run),
        'sendMode': send_mode,
        'channel': channel,
        'safeMode': bool(safe_mode),
        'videoCount': discovery.get('videoCount', 0),
        'commentCount': discovery.get('commentCount', 0),
        'leadCount': discovery.get('leadCount', 0),
        'targetCount': len(targets),
        'sentCount': len([x for x in results if x.get('ok')]),
        'results': results,
        'discovery': discovery,
        'errors': discovery.get('errors') or [],
    }
    try:
        _save_json(OUTREACH_LAST_JSON, summary)
    except Exception:
        pass
    return summary


def run_douyin_dm(target, content, account_id=''):
    """给指定抖音用户发私信。target 可为 用户主页URL / sec_uid。

    走「已登录浏览器 + 抖音自有 JS 签名」(browser_send_dm),绕开已失效的 IM
    web_protect ECDSA 签名(纯 Python 复刻会被抖音判 INVALID_REQUEST)。登录态由
    browser_send_dm() 从账号矩阵 profile 中解析；不可用时直接返回 not_authenticated。
    """
    return browser_send_dm(target, content, account_id)


def run_douyin_dm_inbox(target, limit=10, since_fingerprint="", account_id=''):
    target = (target or "").strip()
    if not target:
        return {"ok": False, "error": "missing_target"}
    try:
        limit = max(1, min(int(limit or 10), 20))
    except Exception:
        limit = 10
    return browser_read_dm_inbox(
        target,
        limit=limit,
        since_fingerprint=since_fingerprint,
        account_id=account_id,
    )


def bump_published(mid, n=1):
    with STATE_LOCK:
        lib = load_library()
        for m in lib:
            if m.get('id') == mid:
                m['published'] = int(m.get('published', 0) or 0) + n
        save_library(lib)


def set_queue_status(jid, status):
    with STATE_LOCK:
        q = load_queue()
        for j in q:
            if j.get('id') == jid:
                j['status'] = status
        save_queue(q)


def _today():
    return time.strftime('%Y-%m-%d', time.localtime())


DEFAULT_RISK_CONFIG = {"dailyPublish": 3, "dailyComment": 30, "minInterval": 45, "concurrency": 2}
XHS_SAFETY_ACTIONS = ("search", "download", "comment_read", "comment", "publish")


def load_risk_config():
    cfg = _load_json(RISK_CONFIG_JSON, {})
    if not isinstance(cfg, dict):
        cfg = {}
    out = dict(DEFAULT_RISK_CONFIG)
    for key in out:
        try:
            out[key] = max(0, int(cfg.get(key, out[key])))
        except Exception:
            pass
    return out


def _xhs_safety_day(now=None):
    return time.strftime('%Y-%m-%d', time.localtime(time.time() if now is None else float(now)))


def _xhs_safety_account_id(account_id=""):
    raw = str(account_id or "").strip()
    if not raw or raw.lower() == "douyin-self":
        return "xhs-self"
    return raw


def load_xhs_safety_state():
    state = _load_json(XHS_SAFETY_STATE_JSON, {})
    if not isinstance(state, dict):
        state = {}
    accounts = state.get("accounts")
    if not isinstance(accounts, dict):
        accounts = {}
    state["accounts"] = accounts
    return state


def save_xhs_safety_state(state):
    if not isinstance(state, dict):
        state = {"accounts": {}}
    state.setdefault("accounts", {})
    state["updatedAt"] = time.time()
    _save_json(XHS_SAFETY_STATE_JSON, state)


def _xhs_safety_usage(state, account_id, now=None):
    account_id = _xhs_safety_account_id(account_id)
    accounts = state.setdefault("accounts", {})
    usage = accounts.get(account_id)
    if not isinstance(usage, dict):
        usage = {}
        accounts[account_id] = usage
    day = _xhs_safety_day(now)
    if usage.get("day") != day:
        paused = bool(usage.get("paused"))
        paused_reason = str(usage.get("pausedReason") or "")
        paused_at = usage.get("pausedAt")
        usage.clear()
        usage.update({"day": day, "paused": paused, "pausedReason": paused_reason, "pausedAt": paused_at})
    for action in XHS_SAFETY_ACTIONS:
        usage.setdefault(action + "Count", 0)
    usage.setdefault("lastActionAt", 0)
    usage.setdefault("lastAction", "")
    usage.setdefault("paused", False)
    usage.setdefault("pausedReason", "")
    return usage


def _xhs_safety_snapshot(account_id, usage=None, cfg=None, now=None):
    cfg = cfg or load_risk_config()
    if usage is None:
        state = load_xhs_safety_state()
        usage = _xhs_safety_usage(state, account_id, now=now)
    last = float(usage.get("lastActionAt") or 0)
    interval = int(cfg.get("minInterval") or 0)
    cooldown_left = max(0, int(interval - (float(time.time() if now is None else now) - last))) if last and interval else 0
    return {
        "accountId": _xhs_safety_account_id(account_id),
        "day": usage.get("day") or _xhs_safety_day(now),
        "dailyPublish": int(cfg.get("dailyPublish") or 0),
        "dailyComment": int(cfg.get("dailyComment") or 0),
        "publishCount": int(usage.get("publishCount") or 0),
        "commentCount": int(usage.get("commentCount") or 0),
        "searchCount": int(usage.get("searchCount") or 0),
        "downloadCount": int(usage.get("downloadCount") or 0),
        "commentReadCount": int(usage.get("comment_readCount") or 0),
        "lastAction": usage.get("lastAction") or "",
        "lastActionAt": last,
        "cooldownLeft": cooldown_left,
        "paused": bool(usage.get("paused")),
        "pausedReason": str(usage.get("pausedReason") or ""),
        "pausedAt": usage.get("pausedAt") or None,
    }


def xhs_safety_preflight(action, account_id="xhs-self", now=None, dry_run=False):
    if bool_arg(os.getenv("XHS_SAFETY_MODE", "1"), True) is False:
        return {"ok": True, "safety": {"disabled": True}}
    if dry_run:
        return {"ok": True, "safety": {"dryRun": True}}
    action = str(action or "").strip()
    cfg = load_risk_config()
    state = load_xhs_safety_state()
    usage = _xhs_safety_usage(state, account_id, now=now)
    snapshot = _xhs_safety_snapshot(account_id, usage=usage, cfg=cfg, now=now)
    if usage.get("paused"):
        return {"ok": False, "blocked": True, "error": "xhs_safety_paused", "safety": snapshot}
    if action == "publish" and int(usage.get("publishCount") or 0) >= int(cfg.get("dailyPublish") or 0):
        return {"ok": False, "blocked": True, "error": "xhs_daily_publish_limit", "safety": snapshot}
    if action == "comment" and int(usage.get("commentCount") or 0) >= int(cfg.get("dailyComment") or 0):
        return {"ok": False, "blocked": True, "error": "xhs_daily_comment_limit", "safety": snapshot}
    if snapshot.get("cooldownLeft", 0) > 0:
        return {"ok": False, "blocked": True, "error": "xhs_safety_interval", "safety": snapshot}
    return {"ok": True, "safety": snapshot}


def xhs_collection_guest_mode(body, default=None):
    body = body if isinstance(body, dict) else {}
    default_guest = xhs_guest_collection_default(os.environ) if default is None else bool(default)
    return bool_arg(body.get("guestMode", body.get("guest_mode", default_guest)), default_guest)


def xhs_account_collection_confirmed(body):
    body = body if isinstance(body, dict) else {}
    return bool_arg(body.get("accountCollectionConfirmed"), False)


def _xhs_url_fingerprint(url):
    text = str(url or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def xhs_collection_account_gate(action, account_id, guest_mode, confirmed, dry_run=False):
    if guest_mode:
        return {"ok": True, "guestMode": True}
    if not confirmed:
        return {
            "ok": False,
            "blocked": True,
            "error": "xhs_account_collection_unconfirmed",
            "guestMode": False,
        }
    if not xhs_profile_ready(DATA_DIR):
        return {
            "ok": False,
            "blocked": True,
            "needLogin": True,
            "error": "xhs_login_required",
            "guestMode": False,
            "accountId": _xhs_safety_account_id(account_id),
        }
    gate = xhs_safety_preflight(action, account_id, dry_run=dry_run)
    if gate.get("ok"):
        json_log(
            logger,
            "xhs_account_collection_confirmed",
            level="info",
            action=str(action or ""),
            accountId=_xhs_safety_account_id(account_id),
            safety=gate.get("safety") or {},
        )
    gate.setdefault("guestMode", False)
    return gate


def xhs_log_guest_collection_block(action, result, keyword="", url=""):
    result = result if isinstance(result, dict) else {}
    if not result.get("guestMode"):
        return
    error = str(result.get("error") or "")
    should_log = error in ("xhs_guest_login_required", "xhs_guest_access_limited", "xhs_ip_risk")
    should_log = should_log or bool(result.get("blocked"))
    if not should_log:
        return
    json_log(
        logger,
        "xhs_guest_collection_blocked",
        level="warning",
        action=str(action or ""),
        error=error,
        riskCode=str(result.get("riskCode") or ""),
        keywordLength=len(str(keyword or "")),
        urlFingerprint=_xhs_url_fingerprint(url),
    )


def _xhs_result_has_platform_risk(result):
    text = json.dumps(result or {}, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result or "")
    lowered = text.lower()
    return any(token in lowered for token in (
        "xhs_ip_risk", "300012", "300031", "captcha", "验证码",
        "verification", "安全验证", "creator_login_required", "xhs_creator_login_required",
    ))


def xhs_safety_record(action, account_id, result, now=None, dry_run=False):
    if dry_run or bool_arg(os.getenv("XHS_SAFETY_MODE", "1"), True) is False:
        return {"ok": True, "safety": {"dryRun": bool(dry_run)}}
    action = str(action or "").strip()
    state = load_xhs_safety_state()
    usage = _xhs_safety_usage(state, account_id, now=now)
    ts = time.time() if now is None else float(now)
    usage["lastActionAt"] = ts
    usage["lastAction"] = action
    success = bool(isinstance(result, dict) and (result.get("ok") or result.get("published") or result.get("clicked")))
    if success and action in XHS_SAFETY_ACTIONS:
        key = action + "Count"
        usage[key] = int(usage.get(key) or 0) + 1
    if _xhs_result_has_platform_risk(result):
        risk_code = str((result or {}).get("riskCode") or "") if isinstance(result, dict) else ""
        error = str((result or {}).get("error") or "") if isinstance(result, dict) else ""
        reason = "小红书平台风险"
        if risk_code:
            reason += " " + risk_code
        if error:
            reason += " " + error
        usage["paused"] = True
        usage["pausedReason"] = reason.strip()
        usage["pausedAt"] = ts
    save_xhs_safety_state(state)
    return {"ok": True, "safety": _xhs_safety_snapshot(account_id, usage=usage, now=now)}


def run_publish(material, account_id, dry_run, title_override=None, platform=None):
    """同步执行一次发布（持锁）。返回 publish_util 的结果 dict。"""
    files = material_files(material)
    if not files:
        return {'ok': False, 'error': 'no_files'}
    publish_platform = platform_code(platform or material.get('platform') or ('xhs' if 'xhs' in str(account_id or '').lower() else 'douyin'))
    if publish_platform == 'xhs':
        gate = xhs_safety_preflight("publish", account_id, dry_run=dry_run)
        if not gate.get("ok"):
            return {'ok': False, **gate}
    if not PUBLISH_LOCK.acquire(timeout=2):
        return {'ok': False, 'error': 'publish_busy'}
    try:
        publish_title = material.get('title', '') if title_override is None else str(title_override)
        publish_body = material.get('body', '') or material.get('content', '') or ''
        publish_tags = material.get('tags') or []
        if publish_platform == 'xhs':
            res = xhs_publish_material(
                files, publish_title, material.get('type', 'video'),
                dry_run=dry_run, data_dir=DATA_DIR, body=publish_body, tags=publish_tags,
            )
            record = xhs_safety_record("publish", account_id, res, dry_run=dry_run)
            if isinstance(res, dict):
                res.setdefault("safety", record.get("safety"))
        else:
            # 发布链路以「持久化 profile」为一等登录态；内存 auth 只是补充 cookie。
            # 因此先从缓存恢复；如果 API 重启后内存没有，再从本地 profile 无交互同步。
            with douyin_account_scope(account_id or 'douyin-self') as scoped:
                auth, paths = scoped
                if not auth or not getattr(auth, 'cookie', None):
                    try:
                        auth, sync_res = sync_auth_from_profile(source='profile-before-publish', account_id=account_id or 'douyin-self')
                    except Exception as e:
                        sync_res = {'error': str(e)}
                        auth = None
                if not auth or not getattr(auth, 'cookie', None):
                    return {'ok': False, 'error': 'no_auth', 'profileSync': sync_res if 'sync_res' in locals() else None}
                try:
                    close_cloud_sessions_for_account(account_id or 'douyin-self')
                    release_chromium_profile_if_stale(paths.get('profileDir') or os.getenv('DY_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_profile')))
                except Exception:
                    pass
                res = publish_to_douyin(
                    auth.cookie, files, publish_title,
                    material.get('type', 'video'), dry_run=dry_run,
                )
    except Exception as e:
        res = {'ok': False, 'published': False, 'error': str(e)}
    finally:
        PUBLISH_LOCK.release()
    if res.get('published'):
        bump_published(material['id'])
    return res


def run_queue_item(j):
    m = find_material(j.get('materialId'))
    if not m:
        set_queue_status(j['id'], 'fail')
        return
    set_queue_status(j['id'], 'running')
    res = run_publish(m, j.get('accountId', ''), dry_run=False)
    if res.get('error') == 'publish_busy':
        # 锁忙（多为手动试发占用），不算尝试、放回排队，下次再试（不推进节流时钟）
        set_queue_status(j['id'], 'pending')
        return
    # 只要真正启动过浏览器尝试（无论成败），都推进节流时钟，避免 cookie 失效时
    # 调度器无视间隔、对整个队列连开浏览器（stampede）。
    acc = j.get('accountId', '')
    PUBLISH_RT['last_ts'] = time.time()
    if res.get('published'):
        set_queue_status(j['id'], 'done')
        PUBLISH_RT['counts'][acc] = PUBLISH_RT['counts'].get(acc, 0) + 1
    else:
        set_queue_status(j['id'], 'fail')


def publish_scheduler():
    """后台调度：开启自动发布后，按间隔/每日上限自动从队列取 pending 发布。"""
    while True:
        try:
            settings = load_settings()
            if settings.get('enabled'):
                if PUBLISH_RT['day'] != _today():
                    PUBLISH_RT['day'] = _today()
                    PUBLISH_RT['counts'] = {}
                interval = float(settings.get('intervalMin', 60) or 60) * 60.0
                per_day = int(settings.get('perAccountPerDay', 1) or 1)
                if time.time() - PUBLISH_RT['last_ts'] >= interval:
                    nxt = None
                    for j in load_queue():
                        if j.get('status') == 'pending':
                            if PUBLISH_RT['counts'].get(j.get('accountId', ''), 0) < per_day:
                                nxt = j
                                break
                    if nxt is not None:
                        run_queue_item(nxt)
        except Exception:
            pass
        time.sleep(20)


def json_response(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    send_cors_headers(handler)
    handler.end_headers()
    handler.wfile.write(body)


def read_body(handler):
    length = int(handler.headers.get('Content-Length', '0') or '0')
    raw = handler.rfile.read(length) if length else b''
    if not raw:
        return {}
    try:
        return json.loads(raw.decode('utf-8'))
    except Exception:
        return {}


def parse_multipart(handler):
    """二进制安全的 multipart/form-data 解析，返回 (fields, files)。
    fields: {name: str}; files: [(name, filename, bytes)]。"""
    ctype = handler.headers.get('Content-Type', '') or ''
    boundary = None
    for part in ctype.split(';'):
        part = part.strip()
        if part.startswith('boundary='):
            boundary = part[len('boundary='):].strip('"')
    if not boundary:
        return {}, []
    length = int(handler.headers.get('Content-Length', '0') or '0')
    body = handler.rfile.read(length) if length else b''
    delim = b'--' + boundary.encode('utf-8')
    fields = {}
    files = []
    for raw in body.split(delim):
        if raw[:2] == b'\r\n':
            raw = raw[2:]
        if not raw or raw[:2] == b'--':
            continue
        if raw.endswith(b'\r\n'):
            raw = raw[:-2]
        if b'\r\n\r\n' not in raw:
            continue
        head, data = raw.split(b'\r\n\r\n', 1)
        disp = ''
        for line in head.decode('utf-8', 'ignore').split('\r\n'):
            if line.lower().startswith('content-disposition'):
                disp = line
        name = None
        filename = None
        for seg in disp.split(';'):
            seg = seg.strip()
            if seg.startswith('name='):
                name = seg[len('name='):].strip('"')
            elif seg.startswith('filename='):
                filename = seg[len('filename='):].strip('"')
        if filename is not None:
            files.append((name or 'files', filename, data))
        elif name is not None:
            fields[name] = data.decode('utf-8', 'ignore')
    return fields, files


def auth_to_cookie_str(auth):
    if not auth or not getattr(auth, 'cookie', None):
        return ''
    return '; '.join([f'{k}={v}' for k, v in auth.cookie.items()])


def set_auth_from_cookie(cookie_str, source='manual', persist=True, web_protect='', keys='', account_id=None):
    auth = DouyinAuth()
    auth.perepare_auth(cookie_str or '', web_protect or '', keys or '')
    with STATE_LOCK:
        STATE['auth'] = auth
    if persist and cookie_str:
        try:
            save_cookie_cache(cookie_str, source=source, web_protect=web_protect, keys=keys, account_id=account_id)
            set_account_disabled(account_id or 'douyin-self', False)
        except Exception:
            pass
        # Only an interactive authorization should clear runtime capability
        # blockers. Passive profile-sync must not hide a real comment-login
        # failure discovered by preflight.
        if str(source or '') in ('cloud-login', 'creator-login', 'capture', 'manual'):
            clear_douyin_capability_state('new_auth:' + str(source or ''))
    return auth


def ensure_auth_from_cache(account_id=None):
    """???????? auth????????? Cookie ????????"""
    if not account_id:
        with STATE_LOCK:
            auth = STATE.get('auth')
        mem_cookie_str = auth_to_cookie_str(auth)
        if auth and getattr(auth, 'cookie', None) and cookie_str_has_login(mem_cookie_str):
            return auth
    cached = load_cookie_cache(account_id)
    cookie_str = (cached.get('cookie') or '').strip()
    if cookie_str and cookie_str_has_login(cookie_str):
        return set_auth_from_cookie(cookie_str, source='cache', persist=False, web_protect=cached.get('web_protect') or '', keys=cached.get('keys') or '')
    return None if account_id else auth

def sync_auth_from_profile(source='profile-sync', account_id=None):
    """从持久化浏览器 profile 读取 creator 登录态并写入内存/缓存。

    这是无扫码恢复链路：只要客户端「登录抖音」曾成功且 profile 未被清理，就能恢复。
    调用方应在 PUBLISH_LOCK 内或确认没有发布/登录任务并发时使用，避免 profile 被占用。
    """
    res = get_persistent_profile_cookies(login_url=os.getenv('DY_LOGIN_URL') or DOUYIN_MAIN_LOGIN_URL, headless=True)
    profile_cookie_str = res.get('cookie_str') or ''
    cached = load_cookie_cache(account_id)
    with STATE_LOCK:
        cur = STATE.get('auth')
    existing_cookie_str = auth_to_cookie_str(cur) or (cached.get('cookie') or '')
    # Headless profile reads may not expose every login cookie for the current URL,
    # but they do expose the security-sdk localStorage keys. Combine those keys with
    # the already verified login cookie cache when possible.
    cookie_str = profile_cookie_str if res.get('logged_in') else (existing_cookie_str or profile_cookie_str)
    if cookie_str and (res.get('logged_in') or cookie_str_has_login(cookie_str)):
        web_protect = res.get('web_protect') or cached.get('web_protect') or ''
        keys = res.get('keys') or cached.get('keys') or ''
        auth = set_auth_from_cookie(cookie_str, source=source, persist=True, web_protect=web_protect, keys=keys, account_id=account_id)
        return auth, res
    return None, res


def bootstrap_auth_from_cache():
    """API 启动时恢复上次登录 Cookie，客户端无需重新扫码。"""
    try:
        auth = ensure_auth_from_cache()
        cache = load_cookie_cache()
        if auth and getattr(auth, 'cookie', None) and not (cache.get('cookie') or '').strip():
            save_cookie_cache(auth_to_cookie_str(auth), source='startup-env')
    except Exception:
        pass



def ensure_auth_security_material(auth):
    if auth and getattr(auth, 'private_key', None) and getattr(auth, 'ticket', None) and getattr(auth, 'ts_sign', None):
        return auth
    cache = load_cookie_cache()
    cookie_str = auth_to_cookie_str(auth) or (cache.get('cookie') or '')
    if cookie_str and cache.get('web_protect') and cache.get('keys'):
        return set_auth_from_cookie(cookie_str, source='cache-security', persist=False,
                                    web_protect=cache.get('web_protect') or '', keys=cache.get('keys') or '')
    # 只读缓存,不开浏览器(避免 API 操作触发 profile→临时 profile→二维码)。
    # 安全材料缺失时按现状返回,由调用方降级或提示重登。
    return auth

def require_auth():
    # API 类操作(搜索/评论/私信/下载/寻客)只读磁盘缓存里的登录态,绝不开浏览器,
    # 因此它们之间可以随意并发,也不会再莫名其妙弹二维码。登录态由「登录抖音」一次
    # 性写入缓存(cookie + 安全材料),跨重启有效。若缓存里没有(从未登录/已过期),
    # 直接 no_auth,由用户点一次「登录抖音」补上,而不是偷偷开一个空浏览器弹码。
    auth = ensure_auth_from_cache()
    if not auth or not getattr(auth, 'cookie', None):
        raise RuntimeError('no_auth')
    cookie_str = auth_to_cookie_str(auth)
    if not cookie_str_has_login(cookie_str) or not cookie_dict_has_douyin_fingerprint(getattr(auth, 'cookie', None)):
        raise RuntimeError('douyin_auth_incomplete')
    return auth


def run_cookie_capture(job_id):
    try:
        res = get_new_cookies()
        cookie_str = res.get('cookie_str') or auth_to_cookie_str(DouyinAuth())
        if not cookie_str:
            cookie_str = '; '.join([f'{k}={v}' for k, v in (res.get('cookies') or {}).items()])
        auth = set_auth_from_cookie(cookie_str, source='capture')
        job = {
            'status': 'success',
            'result': res,
            'cookie_str': cookie_str,
            'auth_cookie_count': len(auth.cookie or {}),
        }
    except Exception as e:
        job = {'status': 'error', 'error': str(e), 'trace': traceback.format_exc()}
    with STATE_LOCK:
        STATE['cookie_jobs'][job_id] = job


def _profile_backup_aside(profile_dir):
    """把已存在且非空的持久化浏览器 profile 目录整体挪到备份名，使随后的登录在
    一个【全新空 profile】里进行（=不带任何已登录状态的干净浏览器，用于"添加新账号"）。
    返回备份路径；若无内容可挪 / 挪动失败则返回 ''（此时降级为复用现有 profile）。"""
    try:
        profile_dir = os.path.abspath(profile_dir)
        if os.path.isdir(profile_dir) and os.listdir(profile_dir):
            bak = profile_dir + '.old-' + str(int(time.time()))
            # 抗 Windows 文件锁瞬态:重试几次 rename
            for attempt in range(3):
                try:
                    os.rename(profile_dir, bak)
                    os.makedirs(profile_dir, exist_ok=True)
                    return bak
                except Exception as e:
                    print('[fresh-login] backup attempt %d failed: %r' % (attempt, e))
                    time.sleep(1.0)
            # 三次都失败:旧 profile 原封未动,降级为复用现有 profile(数据安全,只是非全新)
            print('[fresh-login] backup gave up; degrading to reuse (old profile intact)')
    except Exception as e:
        print('[fresh-login] backup aside failed:', repr(e))
    return ''


def _profile_restore_aside(profile_dir, bak):
    """新账号登录失败时，把挪走的旧 profile 还原回来，避免丢失原账号登录态。
    抗 Windows 文件锁:重试;若最终仍失败,备份目录 .old-<ts> 保留(可手动恢复),不静默丢数据。"""
    if not bak:
        return
    profile_dir = os.path.abspath(profile_dir)
    for attempt in range(3):
        try:
            if os.path.isdir(profile_dir):
                shutil.rmtree(profile_dir, ignore_errors=True)
            if not os.path.isdir(profile_dir):
                os.rename(bak, profile_dir)
                return
        except Exception as e:
            print('[fresh-login] restore attempt %d failed: %r' % (attempt, e))
        time.sleep(1.0)
    print('[fresh-login] RESTORE FAILED — 旧账号登录态已保留在备份目录,可手动恢复: %s' % bak)


def _profile_discard_aside(bak):
    """新账号登录成功后，丢弃旧 profile 备份（新账号成为当前活跃账号）。"""
    if not bak:
        return
    try:
        shutil.rmtree(bak, ignore_errors=True)
    except Exception:
        pass


def run_login(job_id, fresh=False):
    """持久化 profile 登录：登录态(含 localStorage)留存供发布复用，同时写入 auth 供爬虫。
    与发布共用 PUBLISH_LOCK，避免登录与发布同时打开同一 profile。
    fresh=True 时先把旧 profile 挪走，用全新空浏览器登录另一个账号（成功后新账号生效，
    失败则还原旧账号）。"""
    if not PUBLISH_LOCK.acquire(timeout=10):
        with STATE_LOCK:
            STATE['cookie_jobs'][job_id] = {'status': 'error', 'error': 'publish_busy'}
            STATE['login_running'] = False
        return
    dy_profile = os.path.abspath(os.getenv('DY_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_profile')))
    old_profile_env = os.environ.get('DY_PROFILE_DIR')
    pending_profile = ''
    if fresh:
        pending_profile = os.path.abspath(os.path.join(DOUYIN_ACCOUNT_PROFILES_DIR, '_pending_' + job_id))
        shutil.rmtree(pending_profile, ignore_errors=True)
        os.makedirs(pending_profile, exist_ok=True)
        os.environ['DY_PROFILE_DIR'] = pending_profile
    logged_in = False
    account = None
    try:
        # 默认先打开抖音主站完成统一登录。评论/搜索/互动都依赖 www.douyin.com
        # 的真实互动登录态；创作者中心只在登录成功后的能力预热阶段访问，避免
        # 用户误以为必须单独登录多个入口。
        res = get_login_cookies_persistent(login_url=os.getenv('DY_LOGIN_URL') or DOUYIN_MAIN_LOGIN_URL)
        logged_in = bool(res.get('logged_in'))
        cookie_str = res.get('cookie_str') or ''
        cookie_count = 0
        if logged_in and cookie_str:
            if fresh:
                account = register_douyin_account(
                    cookie_str,
                    profile_dir=pending_profile,
                    source='creator-login',
                    web_protect=res.get('web_protect') or '',
                    keys=res.get('keys') or '',
                    name=res.get('nickname') or res.get('name') or res.get('displayName') or '',
                )
                auth = ensure_auth_from_cache(account.get('id'))
            else:
                auth = set_auth_from_cookie(cookie_str, source='creator-login', web_protect=res.get('web_protect') or '', keys=res.get('keys') or '')
            cookie_count = len(auth.cookie or {})
        job = {
            'status': 'success' if logged_in else 'error',
            'loggedIn': logged_in,
            'cookieCount': cookie_count,
            'fresh': bool(fresh),
            'accountId': account.get('id') if logged_in and fresh and account else ('douyin-self' if logged_in else ''),
            'error': None if logged_in else 'login_not_detected',
        }
    except Exception as e:
        job = {'status': 'error', 'error': str(e), 'trace': traceback.format_exc()}
    finally:
        if fresh and not (account and logged_in):
            shutil.rmtree(pending_profile, ignore_errors=True)
            if old_profile_env is None:
                os.environ['DY_PROFILE_DIR'] = dy_profile
            else:
                os.environ['DY_PROFILE_DIR'] = old_profile_env
        PUBLISH_LOCK.release()
    with STATE_LOCK:
        STATE['cookie_jobs'][job_id] = job
        STATE['login_running'] = False


def run_xhs_login(job_id, fresh=False):
    """Visible Xiaohongshu login into the persistent xhs_profile (local client).
    fresh=True 时先把旧 xhs_profile 挪走，用全新空浏览器登录另一个小红书账号。"""
    if not PUBLISH_LOCK.acquire(timeout=10):
        with STATE_LOCK:
            STATE['cookie_jobs'][job_id] = {'status': 'error', 'error': 'publish_busy', 'platform': 'xhs'}
            STATE['login_running'] = False
        return
    xhs_profile = os.path.abspath(os.getenv('XHS_PROFILE_DIR', os.path.join(DATA_DIR, 'xhs_profile')))
    bak = _profile_backup_aside(xhs_profile) if fresh else ''
    try:
        from platform_adapters import xhs_login
        res = xhs_login(data_dir=DATA_DIR)
        logged = bool(res.get('logged_in'))
        if fresh:
            if logged:
                _profile_discard_aside(bak)
            else:
                _profile_restore_aside(xhs_profile, bak)
            bak = ''
        job = {
            'status': 'success' if logged else 'error',
            'loggedIn': logged,
            'cookieCount': res.get('cookieCount', 0),
            'platform': 'xhs',
            'fresh': bool(fresh),
            'error': None if logged else 'login_not_detected',
        }
    except Exception as e:
        if fresh and bak:
            _profile_restore_aside(xhs_profile, bak)
            bak = ''
        job = {'status': 'error', 'error': str(e), 'trace': traceback.format_exc(), 'platform': 'xhs'}
    finally:
        PUBLISH_LOCK.release()
    with STATE_LOCK:
        STATE['cookie_jobs'][job_id] = job
        STATE['login_running'] = False


def _safe_account_key(v):
    v = (v or 'douyin-self').strip()
    v = re.sub(r'[^0-9A-Za-z_.:-]+', '_', v)[:80].strip('._:-')
    return v or 'douyin-self'


def _cloud_profile_dir(account_id):
    account_id = _safe_account_key(account_id)
    if account_id in ('douyin-self', 'default'):
        return os.path.abspath(os.getenv('DY_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_profile')))
    if account_id in ('xhs-self', 'xiaohongshu-self', 'rednote-self'):
        return os.path.abspath(os.getenv('XHS_PROFILE_DIR', os.path.join(DATA_DIR, 'xhs_profile')))
    return os.path.abspath(os.path.join(DATA_DIR, 'cloud_profiles', account_id))


def _cloud_browser_args():
    args = [
        '--disable-blink-features=AutomationControlled',
        '--disable-infobars',
        '--no-first-run',
        '--no-default-browser-check',
        '--lang=zh-CN',
    ]
    if os.name != 'nt':
        args.extend(['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
    extra = os.getenv('DY_BROWSER_ARGS', '').strip()
    if extra:
        args.extend([x for x in extra.split(' ') if x])
    return list(dict.fromkeys(args))


class CloudLoginSession:
    """Interactive cloud browser login session.

    用户在客户端看到的是抖音官方登录页的远程浏览器截图；扫码、手机号、
    短信验证码都在这一个浏览器会话里完成。后端只保存登录完成后的
    cookie/profile，供该执行节点后续任务复用。
    """

    def __init__(self, session_id, account_id='douyin-self', login_url=None):
        self.id = session_id
        self.account_id = _safe_account_key(account_id)
        self.login_url = login_url or os.getenv('DY_LOGIN_URL') or DOUYIN_MAIN_LOGIN_URL
        self.platform = 'xhs' if ('xhs' in self.account_id.lower() or 'xiaohongshu' in self.login_url.lower()) else 'douyin'
        self.profile_dir = _cloud_profile_dir(self.account_id)
        self.created_at = time.time()
        self.last_seen = time.time()
        self.error = ''
        self.loop = None
        self.thread = None
        self.ready = threading.Event()
        self.closed = False
        self.playwright = None
        self.context = None
        self.page = None
        self.capability_warmed = False
        self.capability_warmup = {}

    def start(self, timeout=35):
        self.thread = threading.Thread(target=self._thread_main, name='cloud-login-' + self.id[:8], daemon=True)
        self.thread.start()
        if not self.ready.wait(timeout=timeout):
            raise RuntimeError('cloud_login_start_timeout')
        if self.error:
            raise RuntimeError(self.error)

    def _thread_main(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._open())
            self.ready.set()
            self.loop.run_forever()
        except Exception as e:
            self.error = str(e)
            self.ready.set()
        finally:
            try:
                self.loop.run_until_complete(self._close_async())
            except Exception:
                pass
            try:
                self.loop.close()
            except Exception:
                pass

    async def _open(self):
        from playwright.async_api import async_playwright
        os.makedirs(self.profile_dir, exist_ok=True)
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            self.profile_dir,
            headless=False,
            args=_cloud_browser_args(),
            ignore_default_args=['--enable-automation'],
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            viewport={'width': 1280, 'height': 900},
        )
        try:
            from utils.cookie_util import LOGIN_STEALTH_INIT_JS
            await self.context.add_init_script(LOGIN_STEALTH_INIT_JS)
        except Exception:
            pass
        # Keep the customer-facing verification page on the same authenticated
        # Douyin account as search/comment/publish tasks.  The runtime task path
        # injects the cached Cookie before probing comments; without doing the
        # same here, the handoff page falls back to a QR login modal instead of
        # showing the real comment verification/captcha blocker.
        try:
            auth = ensure_auth_from_cache()
            ck = getattr(auth, 'cookie', None) or {}
            cookies = []
            for k, v in ck.items():
                if not k or v is None:
                    continue
                cookies.append({'name': str(k), 'value': str(v), 'domain': '.douyin.com', 'path': '/'})
            if cookies:
                await self.context.add_cookies(cookies)
        except Exception:
            pass
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        try:
            await self.page.goto(self.login_url, wait_until='domcontentloaded', timeout=45000)
        except Exception:
            # 登录页偶发长连接/验证脚本导致超时，页面仍可交互。
            pass
        await asyncio.sleep(1.0)

    def _submit(self, coro, timeout=30):
        if self.closed:
            raise RuntimeError('session_closed')
        if not self.loop:
            raise RuntimeError('session_not_ready')
        self.last_seen = time.time()
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return fut.result(timeout=timeout)

    async def _warmup_douyin_capabilities(self):
        if self.platform != 'douyin':
            return {'ok': True, 'skipped': 'non_douyin'}
        if self.capability_warmed:
            return self.capability_warmup or {'ok': True, 'skipped': 'already_warmed'}
        result = {'ok': True, 'visited': [], 'errors': []}
        urls = [
            os.getenv('DY_INTERACT_URL') or DOUYIN_MAIN_LOGIN_URL,
            os.getenv('DY_CREATOR_URL') or CREATOR_LOGIN_URL,
        ]
        seen = set()
        for url in urls:
            url = (url or '').strip()
            if not url or url in seen:
                continue
            seen.add(url)
            page = None
            try:
                page = await self.context.new_page()
                await page.goto(url, wait_until='domcontentloaded', timeout=12000)
                await asyncio.sleep(0.8)
                result['visited'].append(url)
            except Exception as e:
                result['errors'].append({'url': url, 'error': str(e)[:300]})
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
        self.capability_warmed = True
        self.capability_warmup = result
        return result

    async def _douyin_visible_login_state(self):
        """Return whether the current Douyin page is visibly asking the user to log in.

        Cookie presence alone is not enough for comment/write capabilities: Douyin
        can keep stale session cookies while the page still renders a login modal.
        The commercial UI must treat that as "needs auth" instead of showing green.
        """
        if not self.page:
            return {'checked': False, 'blocked': False, 'reason': 'no_page'}
        try:
            return await self.page.evaluate("""() => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 10 && r.height > 10 && st.visibility !== 'hidden' && st.display !== 'none' && +st.opacity !== 0;
              };
              const text = document.body ? document.body.innerText : '';
              const buttons = Array.from(document.querySelectorAll('button,[role=button],a,div'))
                .filter(visible)
                .map(el => (el.innerText || el.textContent || '').trim())
                .filter(Boolean);
              const exactLoginButtons = buttons.filter(t => t === '\u767b\u5f55' || t === '\u7acb\u5373\u767b\u5f55');
              const loginPanel = (
                text.includes('\u767b\u5f55\u540e\u514d\u8d39\u7545\u4eab\u9ad8\u6e05\u89c6\u9891') ||
                (text.includes('\u626b\u7801\u767b\u5f55') && text.includes('\u9a8c\u8bc1\u7801\u767b\u5f55')) ||
                text.includes('\u8bf7\u5148\u767b\u5f55\u540e\u53d1\u8868\u8bc4\u8bba') ||
                text.includes('\u767b\u5f55\u540e\u5373\u53ef\u53c2\u4e0e\u4e92\u52a8\u8ba8\u8bba')
              );
              return {
                checked: true,
                blocked: !!(loginPanel || exactLoginButtons.length > 0),
                loginPanel: !!loginPanel,
                loginButtonCount: exactLoginButtons.length,
                hasUser: localStorage.getItem('HasUserLogin') === '1' || !!localStorage.getItem('user_info'),
                url: location.href,
                text: text.slice(0, 260)
              };
            }""")
        except Exception as e:
            return {'checked': False, 'blocked': False, 'reason': 'eval_failed', 'error': str(e)[:300]}

    async def _read_login_state(self, persist=True):
        cookies = {c['name']: c['value'] for c in await self.context.cookies()}
        cookie_str = '; '.join([f'{k}={v}' for k, v in cookies.items()])
        if self.platform == 'xhs':
            logged = bool(cookies.get('web_session') or cookies.get('customerClientId') or cookies.get('access-token'))
        else:
            logged = cookie_str_has_login(cookie_str)
        login_page_state = {}
        if self.platform == 'douyin':
            login_page_state = await self._douyin_visible_login_state()
            if login_page_state.get('blocked'):
                logged = False
        warmup = self.capability_warmup or {}
        if logged and persist and self.platform == 'douyin' and not self.capability_warmed:
            warmup = await self._warmup_douyin_capabilities()
            cookies = {c['name']: c['value'] for c in await self.context.cookies()}
            cookie_str = '; '.join([f'{k}={v}' for k, v in cookies.items()])
            logged = cookie_str_has_login(cookie_str)
            login_page_state = await self._douyin_visible_login_state()
            if login_page_state.get('blocked'):
                logged = False
        storage = {}
        try:
            storage = await self.page.evaluate("""() => ({
                web_protect: localStorage.getItem('security-sdk/s_sdk_sign_data_key/web_protect') || '',
                keys: localStorage.getItem('security-sdk/s_sdk_crypt_sdk') || ''
            })""")
        except Exception:
            storage = {}
        auth = None
        if logged and persist:
            if self.platform == 'douyin':
                auth = set_auth_from_cookie(
                    cookie_str,
                    source='cloud-login',
                    persist=True,
                    web_protect=(storage or {}).get('web_protect', ''),
                    keys=(storage or {}).get('keys', ''),
                )
            elif self.platform == 'xhs':
                try:
                    _save_json(os.path.join(DATA_DIR, 'xhs_auth_state.json'), {
                        'loggedIn': True,
                        'cookieCount': len(cookies),
                        'url': self.page.url if self.page else '',
                        'profileDir': self.profile_dir,
                        'savedAt': time.time(),
                    })
                except Exception:
                    pass
        if self.platform == 'douyin':
            capabilities = douyin_capabilities(auth) if logged else douyin_capabilities_needs_auth('visible_login_required')
        else:
            capabilities = {}
        return {
            'loggedIn': bool(logged),
            'cookieCount': len(cookies),
            'url': self.page.url if self.page else '',
            'accountId': self.account_id,
            'platform': self.platform,
            'profileDir': self.profile_dir,
            'capabilities': capabilities,
            'capabilityWarmup': warmup,
            'loginPageState': login_page_state,
        }

    async def _screenshot(self):
        await asyncio.sleep(0.2)
        png = await self.page.screenshot(type='png', full_page=False)
        st = await self._read_login_state(persist=True)
        return {
            'ok': True,
            'sessionId': self.id,
            'image': 'data:image/png;base64,' + base64.b64encode(png).decode('ascii'),
            'width': 1280,
            'height': 900,
            **st,
        }

    async def _refresh_qr_if_expired(self):
        if self.platform != 'douyin':
            return {'expired': False, 'refreshed': False}
        try:
            text = await self.page.locator('body').inner_text(timeout=3000)
        except Exception:
            text = ''
        expired = any(x in text for x in ('二维码失效', '二维码已失效', '点击刷新', '刷新二维码', '二维码过期'))
        if not expired:
            return {'expired': False, 'refreshed': False}
        clicked = False
        for sel in ('text=点击刷新', 'text=刷新二维码', 'text=二维码失效', 'text=二维码已失效'):
            try:
                loc = self.page.locator(sel).first
                if await loc.count():
                    await loc.click(timeout=3000)
                    clicked = True
                    break
            except Exception:
                pass
        if not clicked:
            try:
                # Fallback: click the middle of the QR area in the standard
                # creator-center login card.
                await self.page.mouse.click(900, 430)
                clicked = True
            except Exception:
                pass
        if clicked:
            await asyncio.sleep(1.5)
        return {'expired': True, 'refreshed': bool(clicked)}

    async def _login_panel_clip(self):
        """Return a crop around the active Douyin login surface.

        QR login can use a narrow crop.  After the customer scans the QR code,
        Douyin may show an identity/SMS verification dialog that is wider and
        often positioned outside the QR card.  In that state we deliberately use
        a wider crop so the code field and verify button are both visible.
        """
        viewport = self.page.viewport_size or {'width': 1280, 'height': 900}
        vw = float(viewport.get('width', 1280) or 1280)
        vh = float(viewport.get('height', 900) or 900)
        rect = None
        try:
            rect = await self.page.evaluate(
                r"""() => {
                  const vw = window.innerWidth || 1280;
                  const vh = window.innerHeight || 900;
                  const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 80 && r.height > 50 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0' && r.bottom > 0 && r.right > 0 && r.left < vw && r.top < vh;
                  };
                  const textOf = el => (el.innerText || el.textContent || '').replace(/\s+/g,' ').trim();
                  const rectOf = (el, mode, score) => {
                    const r = el.getBoundingClientRect();
                    return {mode, score, x:r.left, y:r.top, width:r.width, height:r.height, area:r.width*r.height};
                  };
                  const nodes = Array.from(document.querySelectorAll('[role="dialog"],div,section,main,form'));
                  const dialogHints = ['\u8eab\u4efd\u9a8c\u8bc1','\u77ed\u4fe1\u5df2\u53d1\u9001','\u91cd\u65b0\u53d1\u9001','\u8bf7\u8f93\u5165\u9a8c\u8bc1\u7801'];
                  const dialogCands = [];
                  for (const el of nodes) {
                    if (!visible(el)) continue;
                    const t = textOf(el);
                    if (!t || !dialogHints.some(h => t.includes(h))) continue;
                    const r = el.getBoundingClientRect();
                    const area = r.width * r.height;
                    if (area < 25000 || area > 850000 || r.width < 260 || r.height < 150) continue;
                    let score = 0;
                    if (t.includes('\u8eab\u4efd\u9a8c\u8bc1')) score += 20;
                    if (t.includes('\u77ed\u4fe1\u5df2\u53d1\u9001') || t.includes('\u91cd\u65b0\u53d1\u9001')) score += 12;
                    if (t.includes('\u8bf7\u8f93\u5165\u9a8c\u8bc1\u7801') || t.includes('\u9a8c\u8bc1\u7801')) score += 10;
                    if (t.includes('\u9a8c\u8bc1')) score += 3;
                    const st = getComputedStyle(el);
                    if (st.position === 'fixed' || st.position === 'absolute') score += 2;
                    dialogCands.push(rectOf(el, 'verification', score));
                  }
                  dialogCands.sort((a,b) => (b.score-a.score) || (b.area-a.area));
                  if (dialogCands[0]) return dialogCands[0];

                  const loginHints = ['\u626b\u7801\u767b\u5f55','\u9a8c\u8bc1\u7801\u767b\u5f55','\u4e8c\u7ef4\u7801','\u6211\u662f\u521b\u4f5c\u8005'];
                  const loginCands = [];
                  for (const el of nodes) {
                    if (!visible(el)) continue;
                    const t = textOf(el);
                    if (!loginHints.some(h => t.includes(h))) continue;
                    const r = el.getBoundingClientRect();
                    const area = r.width * r.height;
                    if (area < 50000 || area > 650000) continue;
                    let score = 0;
                    if (t.includes('\u626b\u7801\u767b\u5f55')) score += 4;
                    if (t.includes('\u9a8c\u8bc1\u7801\u767b\u5f55')) score += 3;
                    if (t.includes('\u4e8c\u7ef4\u7801')) score += 2;
                    if (t.includes('\u6211\u662f\u521b\u4f5c\u8005')) score += 1;
                    loginCands.push(rectOf(el, 'login', score));
                  }
                  loginCands.sort((a,b) => (b.score-a.score) || (b.area-a.area));
                  return loginCands[0] || null;
                }"""
            )
        except Exception:
            rect = None
        if not rect:
            rect = {'mode': 'login', 'x': 700, 'y': 135, 'width': 580, 'height': 560}
        mode = str(rect.get('mode') or 'login')
        if mode == 'verification':
            pad = 70.0
            cx = float(rect.get('x', 0)) + float(rect.get('width', 700)) / 2.0
            cy = float(rect.get('y', 0)) + float(rect.get('height', 520)) / 2.0
            desired_w = min(vw, max(float(rect.get('width', 700)) + pad * 2, 1020.0))
            desired_h = min(vh, max(float(rect.get('height', 520)) + pad * 2, 700.0))
            x = max(0.0, min(vw - desired_w, cx - desired_w / 2.0))
            y = max(0.0, min(vh - desired_h, cy - desired_h / 2.0))
            return {'x': x, 'y': y, 'width': max(520.0, desired_w), 'height': max(420.0, desired_h), 'mode': mode}
        pad = 12.0
        x = max(0.0, float(rect.get('x', 0)) - pad)
        y = max(0.0, float(rect.get('y', 0)) - pad)
        w = min(vw - x, float(rect.get('width', 520)) + pad * 2)
        h = min(vh - y, float(rect.get('height', 520)) + pad * 2)
        return {'x': x, 'y': y, 'width': max(260.0, w), 'height': max(220.0, h), 'mode': mode}

    async def _qr(self):
        await asyncio.sleep(0.2)
        refresh_info = await self._refresh_qr_if_expired()
        clip = await self._login_panel_clip()
        png = await self.page.screenshot(type='png', clip=clip)
        st = await self._read_login_state(persist=True)
        return {
            'ok': True,
            'sessionId': self.id,
            'qrMode': True,
            'clipMode': clip.get('mode') or 'login',
            'qrExpiredDetected': bool(refresh_info.get('expired')),
            'qrRefreshed': bool(refresh_info.get('refreshed')),
            'image': 'data:image/png;base64,' + base64.b64encode(png).decode('ascii'),
            'width': int(clip['width']),
            'height': int(clip['height']),
            'offsetX': int(clip['x']),
            'offsetY': int(clip['y']),
            **st,
        }

    async def _status(self):
        st = await self._read_login_state(persist=True)
        return {'ok': True, 'sessionId': self.id, 'closed': self.closed, **st}

    async def _click(self, x, y):
        await self.page.mouse.click(float(x), float(y))
        return await self._status()

    async def _drag(self, x1, y1, x2, y2, steps=24):
        x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
        steps = max(5, min(int(steps or 24), 80))
        await self.page.mouse.move(x1, y1)
        await self.page.mouse.down()
        for i in range(1, steps + 1):
            t = i / float(steps)
            # Slight easing makes slider captcha interaction closer to human drag.
            ease = 1 - (1 - t) * (1 - t)
            await self.page.mouse.move(x1 + (x2 - x1) * ease, y1 + (y2 - y1) * ease)
            await asyncio.sleep(0.015)
        await self.page.mouse.up()
        await asyncio.sleep(0.8)
        return await self._status()

    async def _fill_verification_code(self, text):
        code = ('' if text is None else str(text)).strip()
        if not re.fullmatch(r'\d{4,8}', code):
            return None
        token = 'matrix-code-' + uuid.uuid4().hex
        try:
            info = await self.page.evaluate(r"""(arg) => {
                const code = String(arg.code || '');
                const token = String(arg.token || '');
                const vw = window.innerWidth || 1280;
                const vh = window.innerHeight || 900;
                const visible = el => {
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 4 && r.height > 4 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' && !el.disabled && !el.readOnly && r.bottom > 0 && r.right > 0 && r.left < vw && r.top < vh;
                };
                const textOf = el => (el.innerText || el.textContent || '').replace(/\s+/g,' ').trim();
                const centerIn = (r, box) => !!box && (r.left + r.width/2) >= box.x && (r.left + r.width/2) <= box.x + box.width && (r.top + r.height/2) >= box.y && (r.top + r.height/2) <= box.y + box.height;
                const rectObj = el => { const r = el.getBoundingClientRect(); return {x:r.left, y:r.top, width:r.width, height:r.height, area:r.width*r.height}; };
                const findDialog = () => {
                    const nodes = Array.from(document.querySelectorAll('[role="dialog"],div,section,main,form'));
                    const rows = [];
                    for (const el of nodes) {
                        if (!visible(el)) continue;
                        const t = textOf(el);
                        if (!t) continue;
                        const r = el.getBoundingClientRect();
                        const area = r.width * r.height;
                        if (area < 50000 || area > 900000 || r.width < 360 || r.height < 260) continue;
                        let score = 0;
                        if (t.includes('\u63a5\u6536\u77ed\u4fe1\u9a8c\u8bc1\u7801')) score += 60;
                        if (t.includes('\u77ed\u4fe1\u5df2\u53d1\u9001')) score += 50;
                        if (t.includes('\u91cd\u65b0\u53d1\u9001')) score += 25;
                        if (t.includes('\u65e0\u6cd5\u9a8c\u8bc1\u901a\u8fc7') || t.includes('\u9009\u62e9\u5176\u4ed6\u9a8c\u8bc1\u65b9\u5f0f')) score += 20;
                        if (t.includes('\u8eab\u4efd\u9a8c\u8bc1')) score += 30;
                        if (t.includes('\u9a8c\u8bc1\u7801\u767b\u5f55') && !t.includes('\u77ed\u4fe1\u5df2\u53d1\u9001')) score -= 50;
                        if (score > 0) rows.push({el, score, rect:rectObj(el), text:t.slice(0,120)});
                    }
                    rows.sort((a,b) => (b.score-a.score) || (a.rect.area-b.rect.area));
                    return rows[0] || null;
                };
                const dialog = findDialog();
                const dialogRect = dialog ? dialog.rect : null;
                const metaOf = el => [el.placeholder, el.name, el.id, el.className, el.getAttribute('aria-label'), el.getAttribute('autocomplete'), (el.parentElement && textOf(el.parentElement))].join(' ');
                const allInputs = Array.from(document.querySelectorAll('input,textarea,[contenteditable="true"],[role="textbox"]')).filter(visible);
                const scopedInputs = dialogRect ? allInputs.filter(el => centerIn(el.getBoundingClientRect(), dialogRect)) : [];
                const inputs = scopedInputs.length ? scopedInputs : allInputs;
                const body = document.body ? textOf(document.body) : '';
                const oneChar = inputs.filter(el => (el.maxLength === 1 || String(el.getAttribute('maxlength') || '') === '1') && /^(text|tel|number|password|)$/i.test(el.type || 'text'));
                if (oneChar.length >= 4 && oneChar.length <= 8) {
                    oneChar[0].setAttribute('data-matrix-code-target', token);
                    const r = oneChar[0].getBoundingClientRect();
                    return {found:true, multi:true, count:oneChar.length, x:r.left+r.width/2, y:r.top+r.height/2, reason:'multi-one-char', scoped:!!scopedInputs.length, dialog:dialogRect};
                }
                const scored = [];
                for (const el of inputs) {
                    const r = el.getBoundingClientRect();
                    const meta = metaOf(el);
                    const inDialog = dialogRect && centerIn(r, dialogRect);
                    let score = inDialog ? 300 : 0;
                    if (/\u8bf7\u8f93\u5165\u9a8c\u8bc1\u7801|\u9a8c\u8bc1\u7801|\u6821\u9a8c\u7801|captcha|verify|verification|code/i.test(meta)) score += 120;
                    if (/\u77ed\u4fe1|sms/i.test(meta + ' ' + body)) score += 30;
                    if (/\u8eab\u4efd\u9a8c\u8bc1|\u77ed\u4fe1\u5df2\u53d1\u9001|\u91cd\u65b0\u53d1\u9001/.test(body)) score += 20;
                    if (/\u624b\u673a\u53f7|\u624b\u673a|phone|mobile|tel/i.test(meta) && !/\u9a8c\u8bc1\u7801|code/i.test(meta)) score -= 180;
                    const type = (el.type || '').toLowerCase();
                    if (type === 'tel' || type === 'text' || type === 'number' || !type) score += 8;
                    const ml = Number(el.maxLength || el.getAttribute('maxlength') || 0);
                    if (ml >= code.length && ml <= 8) score += 12;
                    if (r.width >= 120 && r.width <= 460) score += 8;
                    if (score > 0) scored.push({el, score, x:r.left+r.width/2, y:r.top+r.height/2, meta:String(meta).slice(0,120), inDialog});
                }
                scored.sort((a,b) => b.score - a.score);
                if (!scored[0]) {
                    if (dialogRect) return {found:true, coordinate:true, x:dialogRect.x + dialogRect.width * 0.50, y:dialogRect.y + dialogRect.height * 0.36, dialog:dialogRect, reason:'dialog-coordinate-fallback', inputCount:allInputs.length};
                    return {found:false, inputCount:allInputs.length, bodyHint:body.slice(0,160)};
                }
                const best = scored[0];
                best.el.setAttribute('data-matrix-code-target', token);
                return {found:true, multi:false, score:best.score, x:best.x, y:best.y, meta:best.meta, inputCount:allInputs.length, scopedInputCount:scopedInputs.length, inDialog:!!best.inDialog, dialog:dialogRect};
            }""", {'code': code, 'token': token})
        except Exception as e:
            return {'found': False, 'error': str(e)}
        if not info or not info.get('found'):
            return info or {'found': False}
        try:
            if info.get('coordinate'):
                await self.page.mouse.click(float(info.get('x') or 0), float(info.get('y') or 0))
                await asyncio.sleep(0.15)
                await self.page.keyboard.press('Control+A')
                await self.page.keyboard.press('Backspace')
                for ch in code:
                    await self.page.keyboard.insert_text(ch)
                    await asyncio.sleep(0.03)
                info['filled'] = True
                info['codeLength'] = len(code)
                info['fillMethod'] = 'coordinate-keyboard'
                return info
            selector = '[data-matrix-code-target="%s"]' % token
            loc = self.page.locator(selector).first
            await loc.scroll_into_view_if_needed(timeout=2000)
            await loc.click(timeout=3000, force=True)
            try:
                await loc.fill('', timeout=2000)
            except Exception:
                try:
                    await self.page.keyboard.press('Control+A')
                    await self.page.keyboard.press('Backspace')
                except Exception:
                    pass
            # Type digit-by-digit. Some Douyin inputs ignore bulk insert_text.
            for ch in code:
                await self.page.keyboard.insert_text(ch)
                await asyncio.sleep(0.03)
            await asyncio.sleep(0.25)
            info['filled'] = True
            info['codeLength'] = len(code)
            info['fillMethod'] = 'locator-keyboard'
        except Exception as e:
            info['filled'] = False
            info['fillError'] = str(e)
            try:
                patched = await self.page.evaluate(r"""(arg) => {
                    const el = document.querySelector('[data-matrix-code-target="' + arg.token + '"]');
                    if (!el) return false;
                    el.focus();
                    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                    if (desc && desc.set) desc.set.call(el, arg.code); else el.value = arg.code;
                    el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:arg.code}));
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                    return true;
                }""", {'token': token, 'code': code})
                info['filled'] = bool(patched)
                info['patchedValue'] = bool(patched)
            except Exception as ee:
                info['patchError'] = str(ee)
        return info

    async def _click_verify_button(self):
        try:
            clicked = await self.page.evaluate(r"""() => {
                const vw = window.innerWidth || 1280;
                const vh = window.innerHeight || 900;
                const visible = el => {
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 8 && r.height > 8 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' && !el.disabled && r.bottom > 0 && r.right > 0 && r.left < vw && r.top < vh;
                };
                const norm = s => String(s || '').replace(/\s+/g,'');
                const textOf = el => (el.innerText || el.textContent || '').replace(/\s+/g,' ').trim();
                const rectObj = el => { const r = el.getBoundingClientRect(); return {x:r.left, y:r.top, width:r.width, height:r.height, area:r.width*r.height}; };
                const centerIn = (r, box) => !!box && (r.left + r.width/2) >= box.x && (r.left + r.width/2) <= box.x + box.width && (r.top + r.height/2) >= box.y && (r.top + r.height/2) <= box.y + box.height;
                const findDialog = () => {
                    const nodes = Array.from(document.querySelectorAll('[role="dialog"],div,section,main,form'));
                    const rows = [];
                    for (const el of nodes) {
                        if (!visible(el)) continue;
                        const t = textOf(el);
                        if (!t) continue;
                        const r = el.getBoundingClientRect();
                        const area = r.width * r.height;
                        if (area < 50000 || area > 900000 || r.width < 360 || r.height < 260) continue;
                        let score = 0;
                        if (t.includes('\u63a5\u6536\u77ed\u4fe1\u9a8c\u8bc1\u7801')) score += 60;
                        if (t.includes('\u77ed\u4fe1\u5df2\u53d1\u9001')) score += 50;
                        if (t.includes('\u91cd\u65b0\u53d1\u9001')) score += 25;
                        if (t.includes('\u65e0\u6cd5\u9a8c\u8bc1\u901a\u8fc7') || t.includes('\u9009\u62e9\u5176\u4ed6\u9a8c\u8bc1\u65b9\u5f0f')) score += 20;
                        if (score > 0) rows.push({el, score, rect:rectObj(el), text:t.slice(0,120)});
                    }
                    rows.sort((a,b) => (b.score-a.score) || (a.rect.area-b.rect.area));
                    return rows[0] || null;
                };
                const dialog = findDialog();
                const dialogRect = dialog ? dialog.rect : null;
                const nodes = Array.from(document.querySelectorAll('button,[role="button"],a,div,span'));
                const rows = [];
                for (const el of nodes) {
                    if (!visible(el)) continue;
                    const r = el.getBoundingClientRect();
                    if (dialogRect && !centerIn(r, dialogRect)) continue;
                    const txt = norm(el.innerText || el.textContent || '');
                    if (!txt) continue;
                    if (txt.includes('\u83b7\u53d6') || txt.includes('\u91cd\u65b0\u53d1\u9001') || txt.includes('\u53d1\u9001') || txt.includes('\u9a8c\u8bc1\u7801\u767b\u5f55') || txt.includes('\u65e0\u6cd5\u9a8c\u8bc1') || txt.includes('\u65b9\u5f0f')) continue;
                    let score = dialogRect ? 100 : 0;
                    if (txt === '\u9a8c\u8bc1') score += 300;
                    else if (txt.includes('\u9a8c\u8bc1') && txt.length <= 8) score += 160;
                    else if (txt === '\u786e\u8ba4') score += 80;
                    else continue;
                    score -= Math.max(0, txt.length - 2) * 5;
                    rows.push({el, score, text:txt.slice(0,40), x:r.left+r.width/2, y:r.top+r.height/2, area:r.width*r.height});
                }
                rows.sort((a,b) => b.score - a.score);
                let target = rows[0] && rows[0].el;
                if (!target && dialogRect) {
                    return {clicked:false, coordinateFallback:true, x:dialogRect.x + dialogRect.width * 0.63, y:dialogRect.y + dialogRect.height * 0.83, dialog:dialogRect};
                }
                if (!target) return {clicked:false};
                const r = target.getBoundingClientRect();
                const x = r.left + r.width / 2, y = r.top + r.height / 2;
                target.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, clientX:x, clientY:y}));
                target.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x, clientY:y}));
                target.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:x, clientY:y}));
                target.click();
                return {clicked:true, text:(rows[0] && rows[0].text) || '', x, y, score:(rows[0] && rows[0].score) || 0, dialog:dialogRect};
            }""")
            if clicked and clicked.get('clicked'):
                await asyncio.sleep(1.0)
                return clicked
            if clicked and clicked.get('coordinateFallback'):
                await self.page.mouse.click(float(clicked.get('x') or 0), float(clicked.get('y') or 0))
                await asyncio.sleep(1.0)
                clicked['clicked'] = True
                clicked['method'] = 'dialog-coordinate-fallback'
                return clicked
        except Exception as e:
            return {'clicked': False, 'error': str(e)}
        try:
            await self.page.keyboard.press('Enter')
            await asyncio.sleep(0.8)
            return {'clicked': True, 'method': 'enter'}
        except Exception as e:
            return {'clicked': False, 'error': str(e)}

    async def _code(self, text, submit=True):
        fill_info = await self._fill_verification_code(text)
        if not fill_info or not fill_info.get('found') or not fill_info.get('filled'):
            # Preserve old behavior as a fallback when no code field is detected.
            try:
                await self.page.keyboard.insert_text('' if text is None else str(text))
            except Exception:
                await self.page.keyboard.type('' if text is None else str(text), delay=25)
        submit_info = {'clicked': False}
        if submit:
            submit_info = await self._click_verify_button()
        st = await self._status()
        st.update({'codeInput': fill_info or {}, 'submitted': bool((submit_info or {}).get('clicked')), 'submitInfo': submit_info or {}})
        return st

    async def _type(self, text):
        text = '' if text is None else str(text)
        fill_info = await self._fill_verification_code(text)
        if fill_info and fill_info.get('found') and fill_info.get('filled'):
            st = await self._status()
            st.update({'codeInput': fill_info, 'typed': True, 'typedAs': 'verification_code'})
            return st
        try:
            await self.page.keyboard.insert_text(text)
        except Exception:
            await self.page.keyboard.type(text, delay=25)
        return await self._status()

    async def _key(self, key):
        await self.page.keyboard.press(str(key or 'Enter'))
        return await self._status()

    async def _auto_sms(self):
        """Click the first SMS verification option in the cloud browser.

        Enterprise UX rule: after a customer scans the QR code, if the identity
        verification dialog appears, choose the first-row SMS receive path.
        The implementation prefers an exact first-option match and reports
        detailed evidence so the API caller can explain failures.
        """
        preferred = [
            '\u63a5\u6536\u77ed\u4fe1\u9a8c\u8bc1\u7801', '\u63a5\u6536\u9a8c\u8bc1\u7801',
            '\u83b7\u53d6\u77ed\u4fe1\u9a8c\u8bc1\u7801', '\u83b7\u53d6\u9a8c\u8bc1\u7801',
            '\u77ed\u4fe1\u9a8c\u8bc1\u7801', '\u77ed\u4fe1\u9a8c\u8bc1',
            '\u624b\u673a\u9a8c\u8bc1\u7801', '\u624b\u673a\u9a8c\u8bc1',
        ]
        fallback = [
            '\u53d1\u9001\u77ed\u4fe1\u9a8c\u8bc1\u7801', '\u53d1\u9001\u9a8c\u8bc1\u7801',
            '\u9a8c\u8bc1\u624b\u673a\u53f7', '\u53bb\u9a8c\u8bc1', '\u7ee7\u7eed\u9a8c\u8bc1', '\u786e\u8ba4',
        ]
        candidates = preferred + fallback
        last_error = ''

        async def after_click(text, method, exact=None):
            await asyncio.sleep(0.55)
            prompt_accepted = self._accept_external_protocol_prompt()
            await asyncio.sleep(0.75)
            # If the same choice screen is still visible, click the first option
            # again. Douyin sometimes requires the web choice click after Chrome's
            # native external-protocol prompt has been accepted.
            try:
                still_choice = await self.page.evaluate("""(text) => {
                    const body = document.body && (document.body.innerText || document.body.textContent || '');
                    return !!body && body.includes('\u8eab\u4efd\u9a8c\u8bc1') && body.includes(text) && !body.includes('\u77ed\u4fe1\u5df2\u53d1\u9001');
                }""", text)
                if still_choice:
                    info = await self.page.evaluate("""(text) => {
                        const norm = s => String(s || '').replace(/\\s+/g, '');
                        const visible = el => {
                            const r = el.getBoundingClientRect();
                            const s = window.getComputedStyle(el);
                            return r.width > 4 && r.height > 4 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
                        };
                        const clickable = el => {
                            let cur = el;
                            for (let i = 0; cur && i < 7; i++, cur = cur.parentElement) {
                                if (!visible(cur)) continue;
                                const role = (cur.getAttribute('role') || '').toLowerCase();
                                const tag = cur.tagName.toLowerCase();
                                const cs = window.getComputedStyle(cur);
                                if (tag === 'button' || tag === 'a' || role === 'button' || cur.onclick || cs.cursor === 'pointer') return cur;
                            }
                            return el;
                        };
                        const nodes = Array.from(document.querySelectorAll('button,a,div,span,p,li,[role="button"]'));
                        for (const el of nodes) {
                            if (!visible(el) || !norm(el.innerText || el.textContent).includes(norm(text))) continue;
                            const target = clickable(el);
                            const r = target.getBoundingClientRect();
                            target.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, clientX:r.left+r.width/2, clientY:r.top+r.height/2}));
                            target.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:r.left+r.width/2, clientY:r.top+r.height/2}));
                            target.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:r.left+r.width/2, clientY:r.top+r.height/2}));
                            target.click();
                            return {clicked:true, x:r.left+r.width/2, y:r.top+r.height/2, snippet:norm(target.innerText || target.textContent).slice(0,80)};
                        }
                        return {clicked:false};
                    }""", text)
                    if info and info.get('clicked'):
                        method = method + '+second-dom-click'
                        await asyncio.sleep(0.75)
            except Exception:
                pass
            st = await self._status()
            st.update({'clicked': True, 'clickedText': text, 'exact': exact, 'clickMethod': method, 'externalPromptAccepted': bool(prompt_accepted)})
            return st

        # 1) Prefer Playwright text locators, but click by bounding-box center.
        # This avoids cases where loc.first.click() lands on a nested text node
        # while the real handler is bound on the row container.
        for exact in (True, False):
            for text in candidates:
                try:
                    loc = self.page.get_by_text(text, exact=exact)
                    cnt = await loc.count()
                    if cnt > 0:
                        target = loc.first
                        await target.scroll_into_view_if_needed(timeout=2000)
                        box = await target.bounding_box(timeout=2500)
                        if box:
                            await self.page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                            return await after_click(text, 'locator-center', exact)
                        await target.click(timeout=2500)
                        return await after_click(text, 'locator-click', exact)
                except Exception as e:
                    last_error = str(e)

        # 2) DOM fallback: find visible nodes, climb to a clickable parent, fire
        # pointer/mouse/click events. The receive-SMS variants are first.
        try:
            clicked = await self.page.evaluate("""(candidates) => {
                const norm = s => String(s || '').replace(/\\s+/g, '');
                const visible = el => {
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 4 && r.height > 4 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
                };
                const clickable = el => {
                    let cur = el;
                    for (let i = 0; cur && i < 8; i++, cur = cur.parentElement) {
                        if (!visible(cur)) continue;
                        const role = (cur.getAttribute('role') || '').toLowerCase();
                        const tag = cur.tagName.toLowerCase();
                        const cs = window.getComputedStyle(cur);
                        if (tag === 'button' || tag === 'a' || tag === 'li' || role === 'button' || cur.onclick || cs.cursor === 'pointer') return cur;
                    }
                    return el;
                };
                const nodes = Array.from(document.querySelectorAll('button,a,div,span,p,li,[role="button"]'));
                for (const pat of candidates) {
                    for (const el of nodes) {
                        const txt = norm(el.innerText || el.textContent || '');
                        if (!txt || !txt.includes(norm(pat)) || !visible(el)) continue;
                        const target = clickable(el);
                        const r = target.getBoundingClientRect();
                        const x = r.left + r.width / 2;
                        const y = r.top + r.height / 2;
                        target.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, clientX:x, clientY:y}));
                        target.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x, clientY:y}));
                        target.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:x, clientY:y}));
                        target.click();
                        return {text:pat, x, y, snippet:txt.slice(0,100)};
                    }
                }
                return null;
            }""", candidates)
            if clicked:
                return await after_click(clicked.get('text') or '\u63a5\u6536\u77ed\u4fe1\u9a8c\u8bc1\u7801', 'dom-dispatch', None)
        except Exception as e:
            last_error = str(e)

        # 3) Last-resort coordinate click for the known Douyin identity dialog.
        # Only used when the page explicitly contains the identity-verification
        # dialog and the first-row SMS option text, so it is not a blind click.
        try:
            page_state = await self.page.evaluate("""() => {
                const body = document.body && (document.body.innerText || document.body.textContent || '');
                return {identity: body.includes('\u8eab\u4efd\u9a8c\u8bc1'), receiveSms: body.includes('\u63a5\u6536\u77ed\u4fe1\u9a8c\u8bc1\u7801') || body.includes('\u63a5\u6536\u9a8c\u8bc1\u7801')};
            }""")
            if page_state and page_state.get('identity') and page_state.get('receiveSms'):
                await self.page.mouse.click(610, 565)
                return await after_click('\u63a5\u6536\u77ed\u4fe1\u9a8c\u8bc1\u7801', 'known-dialog-coordinate', None)
        except Exception as e:
            last_error = str(e)

        st = await self._status()
        st.update({'clicked': False, 'error': 'sms_option_not_found', 'lastError': last_error, 'clickMethod': 'not-found'})
        return st

    def _accept_external_protocol_prompt(self):
        """Accept Chrome's native external-protocol prompt in the Xvfb node.

        Some Douyin verification options trigger an xdg-open external helper
        dialog before the web flow advances.  This prompt is not part of the
        web page DOM, so Playwright cannot click it.  In cloud-node mode we own
        the Xvfb display, so a tightly scoped xdotool click is acceptable.
        """
        if os.name == 'nt':
            return False
        try:
            import subprocess
            env = os.environ.copy()
            if not env.get('DISPLAY'):
                return False
            cmd = r'''
W=$(xwininfo -root -tree 2>/dev/null | awk '/抖音创作者中心 - Google Chrome for Testing|Google Chrome for Testing|Chromium-browser/ {print $1; exit}')
[ -n "$W" ] || exit 0
xdotool windowactivate --sync "$W" 2>/dev/null || true
# Enable "always allow" if the checkbox exists, then click Open xdg-open.
xdotool mousemove --window "$W" 370 195 click 1 2>/dev/null || true
sleep 0.15
xdotool mousemove --window "$W" 875 281 click 1 2>/dev/null || true
'''
            subprocess.run(['bash', '-lc', cmd], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            return True
        except Exception:
            return False

    async def _refresh(self):
        try:
            await self.page.reload(wait_until='domcontentloaded', timeout=30000)
        except Exception:
            pass
        return await self._status()

    async def _close_async(self):
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
            self.context = None
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None

    def screenshot(self):
        return self._submit(self._screenshot(), timeout=45)

    def qr(self):
        return self._submit(self._qr(), timeout=45)

    def status(self):
        return self._submit(self._status(), timeout=20)

    def click(self, x, y):
        return self._submit(self._click(x, y), timeout=25)

    def drag(self, x1, y1, x2, y2, steps=24):
        return self._submit(self._drag(x1, y1, x2, y2, steps=steps), timeout=35)

    def type_text(self, text):
        return self._submit(self._type(text), timeout=25)

    def code(self, text, submit=True):
        return self._submit(self._code(text, submit=bool(submit)), timeout=35)

    def key(self, key):
        return self._submit(self._key(key), timeout=25)

    def auto_sms(self):
        return self._submit(self._auto_sms(), timeout=30)

    def refresh(self):
        return self._submit(self._refresh(), timeout=45)

    async def _send_comment(self, aweme_id, content, reply_id='', attempt=0):
        if self.platform != 'douyin':
            return {'ok': False, 'reason': 'non_douyin_session', 'platform': self.platform, 'channel': 'cloud-ui'}
        aweme_id = extract_aweme_id(aweme_id)
        content = compact_text(content or '', 160)
        if not aweme_id or not content:
            return {'ok': False, 'reason': 'missing_target_or_content', 'channel': 'cloud-ui'}
        page = self.page or (self.context.pages[0] if self.context and self.context.pages else None)
        if page is None:
            page = await self.context.new_page()
            self.page = page
        url = 'https://www.douyin.com/video/' + str(aweme_id)
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=45000)
        except Exception:
            # Douyin pages often keep long-running requests open; the DOM can still
            # be fully usable after a navigation timeout.
            pass
        await asyncio.sleep(4.0)
        state = await page.evaluate(r"""() => {
            const text = document.body ? (document.body.innerText || document.body.textContent || '') : '';
            const title = document.title || '';
            const verify = title.includes('验证码中间页') || title.toLowerCase().includes('captcha') || text.includes('请完成下列验证后继续') || text.includes('按住左边按钮拖动完成上方拼图') || text.includes('安全验证');
            const login = text.includes('扫码登录') || text.includes('验证码登录') || text.includes('请先登录后发表评论') || text.includes('登录后即可参与互动讨论');
            const hasCommentHint = text.includes('留下你的精彩评论') || text.includes('说点什么') || text.includes('评论');
            return {url: location.href, title, hasVerification: !!verify, hasLoginHint: !!login, hasCommentHint: !!hasCommentHint, text: text.slice(0, 260)};
        }""")
        if state.get('hasVerification'):
            return {'ok': False, 'clicked': False, 'reason': 'comment_verification_required', 'state': state, 'channel': 'cloud-ui'}
        if state.get('hasLoginHint') and not state.get('hasCommentHint'):
            return {'ok': False, 'clicked': False, 'reason': 'comment_login_required', 'state': state, 'channel': 'cloud-ui'}

        open_info = {'found': False}
        for _attempt in range(3):
            open_info = await page.evaluate(r"""() => {
                const vw = window.innerWidth || 1280;
                const vh = window.innerHeight || 900;
                const visible = el => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 8 && r.height > 8 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' && r.bottom > 0 && r.right > 0 && r.left < vw && r.top < vh;
                };
                const textOf = el => String(el.placeholder || el.value || el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                const clickLike = el => {
                    el.scrollIntoView({block:'center', inline:'center'});
                    const r = el.getBoundingClientRect();
                    const x = r.left + r.width / 2, y = r.top + r.height / 2;
                    el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, clientX:x, clientY:y}));
                    el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x, clientY:y}));
                    el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:x, clientY:y}));
                    el.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:x, clientY:y}));
                    try { el.click(); } catch(e) {}
                    return {x, y, width:r.width, height:r.height};
                };
                const directText = el => Array.from(el.childNodes || []).filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent || '').join(' ').replace(/\s+/g, ' ').trim();
                const exactRows = [];
                for (const el of Array.from(document.querySelectorAll('*'))) {
                    if (!visible(el)) continue;
                    const r = el.getBoundingClientRect();
                    const area = r.width * r.height;
                    const own = String(el.placeholder || el.getAttribute('aria-label') || el.getAttribute('title') || directText(el) || '').replace(/\s+/g, ' ').trim();
                    if (!own.includes('留下你的精彩评论')) continue;
                    if (area > 160000) continue;
                    exactRows.push({el, score: 1000 - Math.min(400, area / 500), text: own.slice(0,80), tag: el.tagName, role: el.getAttribute('role') || '', cls: String(el.className || '').slice(0,120), x:r.left, y:r.top, width:r.width, height:r.height, area});
                }
                exactRows.sort((a,b) => (b.score - a.score) || (a.area - b.area));
                if (exactRows[0]) {
                    const rect = clickLike(exactRows[0].el);
                    return {found:true, score:exactRows[0].score, text:exactRows[0].text, tag:exactRows[0].tag, role:exactRows[0].role, cls:exactRows[0].cls, rect};
                }
                const nodes = Array.from(document.querySelectorAll('textarea,input,[contenteditable="true"],[role="textbox"],[role="combobox"],div,span,p'));
                const rows = [];
                for (const el of nodes) {
                    if (!visible(el)) continue;
                    const t = textOf(el);
                    const cls = String(el.className || '');
                    const role = String(el.getAttribute('role') || '');
                    const tag = el.tagName;
                    const r = el.getBoundingClientRect();
                    const area = r.width * r.height;
                    if (tag === 'BODY' || tag === 'HTML') continue;
                    if (area > 220000 && !el.isContentEditable && tag !== 'TEXTAREA' && tag !== 'INPUT' && role !== 'textbox' && role !== 'combobox') continue;
                    if (t.length > 220 && !el.isContentEditable && tag !== 'TEXTAREA' && tag !== 'INPUT' && role !== 'textbox' && role !== 'combobox') continue;
                    let score = 0;
                    if (t.includes('留下你的精彩评论')) score += 220;
                    if (t.includes('说点什么')) score += 140;
                    if (t.includes('评论')) score += 80;
                    if (el.isContentEditable) score += 70;
                    if (tag === 'TEXTAREA') score += 60;
                    if (tag === 'INPUT') score += 30;
                    if (role === 'textbox' || role === 'combobox') score += 50;
                    if (cls.includes('DraftEditor') || cls.includes('public-DraftEditor')) score += 80;
                    if (r.width > 180 && r.height > 24) score += 30;
                    if (score > 0) rows.push({el, score, text:t.slice(0,80), tag, role, cls:cls.slice(0,120), x:r.left, y:r.top, width:r.width, height:r.height, area});
                }
                rows.sort((a,b) => (b.score - a.score) || ((a.area || 0) - (b.area || 0)));
                if (!rows[0]) return {found:false};
                const rect = clickLike(rows[0].el);
                return {found:true, score:rows[0].score, text:rows[0].text, tag:rows[0].tag, cls:rows[0].cls, rect};
            }""")
            if open_info and open_info.get('found'):
                break
            try:
                await page.mouse.wheel(0, 420)
            except Exception:
                pass
            await asyncio.sleep(1.0)
        await asyncio.sleep(0.8)
        if not open_info.get('found'):
            return {'ok': False, 'clicked': False, 'reason': 'comment_editor_not_found', 'state': state, 'openInfo': open_info, 'channel': 'cloud-ui'}
        try:
            r = open_info.get('rect') or {}
            mx = float(r.get('x') or 0)
            my = float(r.get('y') or 0)
            mw = float(r.get('width') or 0)
            mh = float(r.get('height') or 0)
            if mx and my:
                await page.mouse.click(mx + max(8, min(mw / 2, 80)), my + max(8, min(mh / 2, 18)))
                await asyncio.sleep(0.7)
            # Known Douyin desktop layout fallback: this point is inside the
            # visible comment input on a 1280x900 viewport.
            await page.mouse.click(420, 758)
            await asyncio.sleep(0.9)
        except Exception:
            pass

        token = 'mx_comment_editor_' + uuid.uuid4().hex
        editor = await page.evaluate(r"""(arg) => {
            const token = arg.token;
            const targetRect = arg.rect || null;
            const vw = window.innerWidth || 1280;
            const vh = window.innerHeight || 900;
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 8 && r.height > 8 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' && r.bottom > 0 && r.right > 0 && r.left < vw && r.top < vh;
            };
            const scoreNode = el => {
                if (!visible(el)) return -1;
                const r = el.getBoundingClientRect();
                if (targetRect) {
                    const cx = r.left + r.width / 2;
                    const cy = r.top + r.height / 2;
                    const padX = 180, padY = 120;
                    if (cx < targetRect.x - padX || cx > targetRect.x + targetRect.width + padX || cy < targetRect.y - padY || cy > targetRect.y + targetRect.height + padY) return -1;
                }
                const tag = el.tagName;
                const cls = String(el.className || '');
                const role = String(el.getAttribute('role') || '');
                if (tag === 'BODY' || tag === 'HTML') return -1;
                if (!(el.isContentEditable || tag === 'TEXTAREA' || tag === 'INPUT' || role === 'textbox' || role === 'combobox')) return -1;
                let score = 0;
                if (document.activeElement === el) score += 300;
                if (el.isContentEditable) score += 150;
                if (role === 'textbox' || role === 'combobox') score += 80;
                if (cls.includes('DraftEditor') || cls.includes('public-DraftEditor')) score += 120;
                if (r.width > 180 && r.height > 20) score += 30;
                return score;
            };
            const nodes = Array.from(document.querySelectorAll('[contenteditable="true"],textarea,input,[role="textbox"],[role="combobox"]'));
            if (document.activeElement && !nodes.includes(document.activeElement) && !['BODY','HTML'].includes(document.activeElement.tagName)) nodes.unshift(document.activeElement);
            const rows = nodes.map(el => ({el, score:scoreNode(el)})).filter(x => x.score > 0).sort((a,b) => b.score - a.score);
            if (!rows[0]) return {found:false};
            const el = rows[0].el;
            el.setAttribute('data-matrix-comment-editor', token);
            const r = el.getBoundingClientRect();
            return {found:true, score:rows[0].score, tag:el.tagName, role:el.getAttribute('role') || '', cls:String(el.className || '').slice(0,120), x:r.left, y:r.top, width:r.width, height:r.height};
        }""", {'token': token, 'rect': (open_info.get('rect') or {})})
        if not editor.get('found'):
            nearby = {}
            try:
                nearby = await page.evaluate(r"""(rect) => {
                    const visible = el => {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
                    };
                    const textOf = el => String(el.placeholder || el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.textContent || el.value || '').replace(/\s+/g,' ').trim();
                    const rows = [];
                    for (const el of Array.from(document.querySelectorAll('*'))) {
                        if (!visible(el)) continue;
                        const r = el.getBoundingClientRect();
                        const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
                        if (rect && rect.x !== undefined) {
                            if (cx < rect.x - 260 || cx > rect.x + rect.width + 260 || cy < rect.y - 180 || cy > rect.y + rect.height + 180) continue;
                        }
                        const t = textOf(el);
                        const cls = String(el.className || '');
                        const role = el.getAttribute('role') || '';
                        const ce = el.getAttribute('contenteditable') || '';
                        const pe = getComputedStyle(el).pointerEvents;
                        const cursor = getComputedStyle(el).cursor;
                        let score = 0;
                        if (t.includes('留下你的精彩评论')) score += 100;
                        if (t.includes('评论')) score += 30;
                        if (ce === 'true' || el.isContentEditable) score += 80;
                        if (role === 'textbox' || role === 'combobox') score += 60;
                        if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') score += 50;
                        if (cursor === 'pointer') score += 10;
                        if (score <= 0 && rows.length > 80) continue;
                        rows.push({score, tag:el.tagName, role, ce, cls:cls.slice(0,120), text:t.slice(0,120), x:r.left, y:r.top, width:r.width, height:r.height, pointerEvents:pe, cursor, tabIndex:el.tabIndex});
                    }
                    rows.sort((a,b) => (b.score-a.score) || ((a.width*a.height)-(b.width*b.height)));
                    return {count: rows.length, rows: rows.slice(0,80)};
                }""", (open_info.get('rect') or {}))
            except Exception as e:
                nearby = {'error': str(e)}
            return {'ok': False, 'clicked': False, 'reason': 'comment_editor_focus_failed', 'state': state, 'openInfo': open_info, 'editor': editor, 'nearby': nearby, 'channel': 'cloud-ui'}
        try:
            loc = page.locator('[data-matrix-comment-editor="%s"]' % token).first
            await loc.click(timeout=3000, force=True)
            try:
                await loc.focus(timeout=2000)
            except Exception:
                pass
            try:
                await loc.fill('', timeout=2500)
                await loc.fill(content, timeout=3500)
            except Exception:
                pass
        except Exception:
            try:
                await page.mouse.click(float(editor.get('x') or 0) + min(float(editor.get('width') or 20) / 2, 60), float(editor.get('y') or 0) + float(editor.get('height') or 20) / 2)
            except Exception:
                pass
        try:
            await page.mouse.click(float(editor.get('x') or 0) + 16, float(editor.get('y') or 0) + max(8, min(float(editor.get('height') or 20) / 2, 18)))
            await asyncio.sleep(0.2)
        except Exception:
            pass
        try:
            await page.keyboard.press('Control+A')
            await page.keyboard.press('Backspace')
        except Exception:
            pass
        try:
            await page.keyboard.type(content, delay=25)
        except Exception:
            try:
                await page.keyboard.insert_text(content)
            except Exception:
                pass
        await asyncio.sleep(0.8)
        typed = await page.evaluate(r"""(arg) => {
            const content = arg.content;
            const nodes = Array.from(document.querySelectorAll('[contenteditable="true"],textarea,input,[role="textbox"],[role="combobox"]'));
            const vals = nodes.map(el => String(el.value || el.innerText || el.textContent || '').trim()).filter(Boolean);
            return {ok: vals.some(v => v.includes(content)), values: vals.slice(0,6)};
        }""", {'content': content})
        if not typed.get('ok'):
            try:
                await page.evaluate(r"""(arg) => {
                    const el = document.querySelector('[data-matrix-comment-editor="' + arg.token + '"]');
                    if (!el) return false;
                    el.focus();
                    document.getSelection && document.getSelection().removeAllRanges();
                    try { document.execCommand('selectAll', false, null); } catch(e) {}
                    try { document.execCommand('delete', false, null); } catch(e) {}
                    const ok = document.execCommand('insertText', false, arg.content);
                    el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:arg.content}));
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                    return ok;
                }""", {'token': token, 'content': content})
                await asyncio.sleep(0.6)
                typed = await page.evaluate(r"""(arg) => {
                    const content = arg.content;
                    const nodes = Array.from(document.querySelectorAll('[contenteditable="true"],textarea,input,[role="textbox"],[role="combobox"]'));
                    const vals = nodes.map(el => String(el.value || el.innerText || el.textContent || '').trim()).filter(Boolean);
                    return {ok: vals.some(v => v.includes(content)), values: vals.slice(0,6), fallback:'execCommand'};
                }""", {'content': content})
            except Exception as e:
                typed['fallbackError'] = str(e)
        if not typed.get('ok'):
            if attempt < 2:
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                except Exception:
                    pass
                await asyncio.sleep(2.0)
                return await self._send_comment(aweme_id, content, reply_id=reply_id, attempt=attempt + 1)
            return {'ok': False, 'clicked': False, 'reason': 'comment_type_failed', 'state': state, 'openInfo': open_info, 'editor': editor, 'typed': typed, 'channel': 'cloud-ui'}

        arrow = await page.evaluate(r"""(arg) => {
            const content = arg.content;
            const vw = window.innerWidth || 1280;
            const vh = window.innerHeight || 900;
            const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 8 && r.height > 8 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' && !el.disabled && r.bottom > 0 && r.right > 0 && r.left < vw && r.top < vh;
            };
            const clickLike = el => {
                const r = el.getBoundingClientRect();
                const x = r.left + r.width / 2, y = r.top + r.height / 2;
                el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, clientX:x, clientY:y}));
                el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x, clientY:y}));
                el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:x, clientY:y}));
                el.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:x, clientY:y}));
                try { el.click(); } catch(e) {}
                return {x,y,width:r.width,height:r.height};
            };
            let editorRect = null;
            for (const el of Array.from(document.querySelectorAll('[contenteditable="true"],textarea,input,[role="textbox"],[role="combobox"]'))) {
                const txt = String(el.value || el.innerText || el.textContent || '');
                if (txt.includes(content) && visible(el)) {
                    const r = el.getBoundingClientRect();
                    editorRect = {x:r.left,y:r.top,width:r.width,height:r.height,right:r.right,bottom:r.bottom};
                    break;
                }
            }
            const nodes = Array.from(document.querySelectorAll('button,[role="button"],a,span,div,svg'));
                const rows = [];
                for (const el of nodes) {
                    if (!visible(el)) continue;
                    const r = el.getBoundingClientRect();
                    const cls = String(el.className || '');
                    const txt = String(el.innerText || el.textContent || '').replace(/\s+/g,'').trim();
                    if (txt.includes('举报')) continue;
                    if (txt && txt.length > 8) continue;
                    let score = 0;
                    if (txt === '发送' || txt === '评论') score += 260;
                    if (cls.includes('wchsYBpK')) score += 260;
                    if (cls.includes('jfGCpJo0')) score += 160;
                if (r.width >= 20 && r.width <= 90 && r.height >= 20 && r.height <= 90) score += 50;
                    if (editorRect) {
                        const cy = r.top + r.height / 2;
                        const cx = r.left + r.width / 2;
                    const dy = Math.abs(cy - (editorRect.y + editorRect.height / 2));
                    if (dy > 80) continue;
                    if (Math.abs(cy - (editorRect.y + editorRect.height / 2)) < 45) score += 130;
                    else score += 70;
                    if (cx > editorRect.x + editorRect.width * 0.65) score += 90;
                    if (cx > editorRect.right - 85 && cx < editorRect.right + 230) score += 120;
                    else continue;
                } else if (r.left > vw * 0.55) {
                    score += 40;
                }
                if (score > 0) rows.push({el, score, tag:el.tagName, cls:cls.slice(0,120), text:txt.slice(0,20), x:r.left, y:r.top, width:r.width, height:r.height});
            }
            rows.sort((a,b) => (b.score - a.score) || (b.x - a.x));
            if (!rows[0]) return {clicked:false, candidates:[]};
            const rect = clickLike(rows[0].el);
            return {clicked:true, score:rows[0].score, tag:rows[0].tag, cls:rows[0].cls, text:rows[0].text, rect, candidates: rows.slice(0,5).map(x => ({score:x.score, tag:x.tag, cls:x.cls, text:x.text, x:x.x, y:x.y, width:x.width, height:x.height}))};
        }""", {'content': content})
        if not arrow.get('clicked'):
            try:
                await page.get_by_text('发送', exact=True).first.click(timeout=2500, force=True)
                arrow = {'clicked': True, 'method': 'text-send'}
            except Exception as e:
                arrow['fallbackError'] = str(e)
        await asyncio.sleep(3.0)
        shot_dir = os.path.join(DATA_DIR, 'ui_comment_debug')
        os.makedirs(shot_dir, exist_ok=True)
        shot_path = os.path.join(shot_dir, 'comment_%s_%s.png' % (aweme_id, int(time.time())))
        try:
            await page.screenshot(path=shot_path, type='png', full_page=False)
        except Exception:
            shot_path = ''
        evidence = await page.evaluate(r"""(arg) => {
            const content = arg.content;
            const body = document.body ? (document.body.innerText || document.body.textContent || '') : '';
            const editors = Array.from(document.querySelectorAll('[contenteditable="true"],textarea,input,[role="textbox"],[role="combobox"]')).map(el => String(el.value || el.innerText || el.textContent || '').trim()).filter(Boolean);
            const inputStillContains = editors.some(v => v.includes(content));
            const bodyContains = body.includes(content);
            return {bodyContains, inputStillContains, domVerified: !!(bodyContains && !inputStillContains), editorValues: editors.slice(0,6), bodySnippet: body.includes(content) ? body.slice(Math.max(0, body.indexOf(content)-80), Math.min(body.length, body.indexOf(content)+content.length+120)) : body.slice(0,260), url: location.href};
        }""", {'content': content})
        ok = bool(arrow.get('clicked') and evidence.get('domVerified'))
        if (not ok) and attempt < 2 and evidence.get('inputStillContains'):
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            except Exception:
                pass
            await asyncio.sleep(2.0)
            return await self._send_comment(aweme_id, content, reply_id=reply_id, attempt=attempt + 1)
        return {
            'ok': ok,
            'clicked': bool(arrow.get('clicked')),
            'domVerified': bool(evidence.get('domVerified')),
            'reason': '' if ok else ('comment_not_visible_in_dom' if arrow.get('clicked') else 'send_button_not_clicked'),
            'channel': 'cloud-ui',
            'attempt': attempt,
            'url': page.url,
            'state': state,
            'openInfo': open_info,
            'editor': editor,
            'typed': typed,
            'sendButton': arrow,
            'evidence': evidence,
            'screenshot': shot_path,
        }

    def send_comment(self, aweme_id, content, reply_id=''):
        return self._submit(self._send_comment(aweme_id, content, reply_id=reply_id), timeout=210)

    def close(self):
        self.closed = True
        if self.loop:
            try:
                asyncio.run_coroutine_threadsafe(self._close_async(), self.loop).result(timeout=15)
            except Exception:
                pass
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except Exception:
                pass
        return {'ok': True, 'sessionId': self.id, 'closed': True}


def cloud_session(session_id):
    with CLOUD_LOGIN_LOCK:
        s = CLOUD_LOGIN_SESSIONS.get(session_id or '')
    if not s:
        raise RuntimeError('cloud_login_session_not_found')
    return s


def find_cloud_session_for_account(account_id):
    safe_account = _safe_account_key(account_id or 'douyin-self')
    with CLOUD_LOGIN_LOCK:
        for sid, sess in list(CLOUD_LOGIN_SESSIONS.items()):
            if getattr(sess, 'closed', False):
                continue
            if getattr(sess, 'account_id', '') == safe_account or getattr(sess, 'profile_dir', '') == _cloud_profile_dir(safe_account):
                return sid, sess
    return '', None


def close_cloud_sessions_for_account(account_id):
    """Close any existing interactive browser for the same account/profile.

    Chromium persistent profiles are single-writer.  If the operator clicks
    "开始授权" twice, or a previous native client session loses its session id, opening
    the same DY_PROFILE_DIR again fails with:
    "Opening in existing browser session".
    """
    safe_account = _safe_account_key(account_id or 'douyin-self')
    old = []
    with CLOUD_LOGIN_LOCK:
        for sid, sess in list(CLOUD_LOGIN_SESSIONS.items()):
            if getattr(sess, 'account_id', '') == safe_account or getattr(sess, 'profile_dir', '') == _cloud_profile_dir(safe_account):
                old.append((sid, sess))
                CLOUD_LOGIN_SESSIONS.pop(sid, None)
    for _sid, sess in old:
        try:
            sess.close()
        except Exception:
            pass


def release_chromium_profile_if_stale(profile_dir):
    """Best-effort cleanup for orphaned Playwright/Chromium profile locks.

    This is intentionally scoped to the exact --user-data-dir path used by this
    execution node, so it will not kill unrelated Chrome/Chromium processes.
    """
    profile_dir = os.path.abspath(profile_dir)
    if os.name == 'nt':
        return
    lock_names = [
        os.path.join(profile_dir, 'SingletonLock'),
        os.path.join(profile_dir, 'SingletonSocket'),
        os.path.join(profile_dir, 'SingletonCookie'),
        os.path.join(profile_dir, 'Default', 'LOCK'),
    ]
    if not any(os.path.lexists(p) for p in lock_names):
        return
    try:
        import subprocess
        subprocess.run(
            ['pkill', '-TERM', '-f', '--', '--user-data-dir=' + profile_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        time.sleep(1.0)
        subprocess.run(
            ['pkill', '-KILL', '-f', '--', '--user-data-dir=' + profile_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        pass
    for p in lock_names:
        try:
            if os.path.lexists(p):
                os.unlink(p)
        except Exception:
            pass


def cleanup_cloud_sessions(max_age=1800):
    now = time.time()
    stale = []
    with CLOUD_LOGIN_LOCK:
        for sid, sess in list(CLOUD_LOGIN_SESSIONS.items()):
            if sess.closed or now - sess.last_seen > max_age:
                stale.append((sid, sess))
                CLOUD_LOGIN_SESSIONS.pop(sid, None)
    for _sid, sess in stale:
        try:
            sess.close()
        except Exception:
            pass


bootstrap_auth_from_cache()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_OPTIONS(self):
        if not origin_allowed(self.headers.get('Origin') or ''):
            return json_response(self, {'ok': False, 'error': 'origin_not_allowed'}, 403)
        json_response(self, {'ok': True})

    def handle_multipart(self, path):
        fields, files = parse_multipart(self)
        if path == '/api/library/upload':
            title = (fields.get('title') or '').strip()
            mtype = (fields.get('type') or 'video').strip()
            if not files:
                return json_response(self, {'ok': False, 'error': 'no_files'}, 400)
            mid = uuid.uuid4().hex
            mdir = os.path.join(MATERIALS_DIR, mid)
            os.makedirs(mdir, exist_ok=True)
            saved = []
            for (_field, filename, data) in files:
                safe = os.path.basename(filename) or ('file_%d' % len(saved))
                with open(os.path.join(mdir, safe), 'wb') as f:
                    f.write(data)
                saved.append(safe)
            urls = ['/api/library/file/%s/%s' % (mid, fn) for fn in saved]
            with STATE_LOCK:
                lib = load_library()
                item = {
                    'id': mid, 'title': title or saved[0], 'type': mtype,
                    'files': saved, 'urls': urls, 'published': 0, 'createdAt': time.time(),
                }
                item.update(library_upload_metadata(fields))
                lib.insert(0, item)
                save_library(lib)
            return json_response(self, {'ok': True, 'id': mid})
        return json_response(self, {'ok': False, 'error': 'not_found'}, 404)

    def serve_material_file(self, path):
        rel = path[len('/api/library/file/'):]
        parts = [p for p in rel.split('/') if p]
        if len(parts) != 2:
            return json_response(self, {'ok': False, 'error': 'bad_path'}, 400)
        # 防目录穿越：两段都取 basename，再规范化并校验仍在 materials 沙箱内
        mid = os.path.basename(parts[0].replace('\\', '/'))
        name = os.path.basename(parts[1].replace('\\', '/'))
        fp = os.path.normpath(os.path.join(MATERIALS_DIR, mid, name))
        if fp != MATERIALS_DIR and not fp.startswith(MATERIALS_DIR + os.sep):
            return json_response(self, {'ok': False, 'error': 'forbidden'}, 403)
        if not os.path.isfile(fp):
            return json_response(self, {'ok': False, 'error': 'not_found', 'path': path}, 404)
        ctype = mimetypes.guess_type(fp)[0] or 'application/octet-stream'
        try:
            with open(fp, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            send_cors_headers(self)
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            return json_response(self, {'ok': False, 'error': str(e)}, 500)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if not ensure_agent_request(self, path):
            return
        if path in ('/api/health', '/api/agent/status'):
            authorized = request_authorized(self)
            if not authorized:
                return json_response(self, {
                    'ok': True,
                    'agentReady': True,
                    'authorized': False,
                    'requiresToken': token_auth_enabled(),
                    'version': AGENT_VERSION,
                    'host': HOST,
                    'port': PORT,
                    'message': 'agent_token_required',
                })
            auth = ensure_auth_from_cache()
            profile_sync = None
            # health 只读磁盘缓存,绝不开浏览器(心跳/客户端轮询若触发 profile 会导致
            # profile 被占→退化临时 profile→莫名弹二维码)。需要从 profile 恢复登录态
            # 请显式调用 /api/login/sync。
            cache = load_cookie_cache()
            cookie_str = auth_to_cookie_str(auth)
            has_login_cookie = bool(
                auth and getattr(auth, 'cookie', None)
                and cookie_str_has_login(cookie_str)
                and cookie_dict_has_douyin_fingerprint(getattr(auth, 'cookie', None))
            )
            capabilities = douyin_capabilities(auth)
            return json_response(self, {
                'ok': True,
                'cookieReady': has_login_cookie,
                'cookieCount': len(getattr(auth, 'cookie', {}) or {}),
                'capabilities': capabilities,
                'cookieSavedAt': cache.get('savedAt'),
                'cookieSource': cache.get('source'),
                'profileSync': profile_sync,
                'agentReady': True,
                'authorized': True,
                'requiresToken': token_auth_enabled(),
                'version': AGENT_VERSION,
                'host': HOST,
                'port': PORT,
                'dataDir': DATA_DIR,
            })
        if path == '/api/cookie/current':
            auth = ensure_auth_from_cache()
            if not auth or not getattr(auth, 'cookie', None):
                return json_response(self, {'ok': False, 'error': 'no_cookie'}, 400)
            return json_response(self, {'ok': True, 'cookie': auth_to_cookie_str(auth), 'cookieCount': len(auth.cookie or {})})
        if path == '/api/cookie/status':
            job_id = (qs.get('sessionId') or qs.get('jobId') or [''])[0]
            with STATE_LOCK:
                job = STATE['cookie_jobs'].get(job_id)
            if not job:
                return json_response(self, {'ok': False, 'error': 'not_found'}, 404)
            return json_response(self, {'ok': True, 'sessionId': job_id, **job})
        if path == '/api/login/status':
            job_id = (qs.get('sessionId') or qs.get('jobId') or [''])[0]
            with STATE_LOCK:
                job = STATE['cookie_jobs'].get(job_id)
            if not job:
                return json_response(self, {'ok': False, 'error': 'not_found'}, 404)
            return json_response(self, {'ok': True, 'sessionId': job_id, **job})
        if path == '/api/douyin/comments':
            try:
                url = (qs.get('url') or [''])[0]
                if not url:
                    raise RuntimeError('missing_url')
                cursor = (qs.get('cursor') or ['0'])[0]
                account_id = default_douyin_comment_account_id((qs.get('accountId') or qs.get('account') or [''])[0])
                if account_id:
                    with douyin_account_scope(account_id) as scoped:
                        auth = scoped[0]
                        data = SPIDER.douyin_apis.get_work_all_comment(auth, url) if cursor == 'all' else SPIDER.douyin_apis.get_work_out_comment(auth, url, cursor)
                else:
                    auth = require_auth()
                    data = SPIDER.douyin_apis.get_work_all_comment(auth, url) if cursor == 'all' else SPIDER.douyin_apis.get_work_out_comment(auth, url, cursor)
                raw_comments = data.get('comments') if isinstance(data, dict) else data
                items = normalize_comments(raw_comments)
                return json_response(self, {'ok': True, 'data': data, 'items': items, 'count': len(items), 'accountId': account_id})
            except Exception as e:
                need_login = is_douyin_auth_error(e)
                code = 401 if need_login else 500
                return json_response(self, {'ok': False, 'needLogin': need_login, 'platform': 'douyin', 'error': str(e), 'trace': traceback.format_exc()}, code)
        if path == '/api/xhs/comments':
            try:
                url = (qs.get('url') or qs.get('noteUrl') or [''])[0]
                if not url:
                    raise RuntimeError('missing_url')
                limit = int((qs.get('limit') or ['120'])[0] or 120)
                account_id = _xhs_safety_account_id((qs.get('accountId') or qs.get('account') or [''])[0])
                flag_body = {
                    "guestMode": (qs.get('guestMode') or qs.get('guest_mode') or [None])[0],
                    "accountCollectionConfirmed": (qs.get('accountCollectionConfirmed') or [None])[0],
                }
                guest_mode = xhs_collection_guest_mode(flag_body, default=False)
                confirmed = xhs_account_collection_confirmed(flag_body)
                gate = xhs_collection_account_gate("comment_read", account_id, guest_mode, confirmed)
                if not gate.get("ok"):
                    return json_response(self, {'ok': False, **gate}, 429)
                data = xhs_get_comments(url, limit=limit, data_dir=DATA_DIR, guest_mode=guest_mode)
                xhs_log_guest_collection_block("comment_read", data, url=url)
                record = xhs_safety_record("comment_read", account_id, data) if not guest_mode else {"safety": gate.get("safety")}
                if isinstance(data, dict):
                    data.setdefault("safety", record.get("safety"))
                return json_response(self, {'ok': True, **data})
            except Exception as e:
                return json_response(self, {'ok': False, 'error': str(e), 'trace': traceback.format_exc()}, 500)
        if path == '/api/xhs-note-replacement/job':
            if not xhs_note_replacement.feature_enabled():
                return json_response(self, {'ok': False, 'error': 'feature_disabled'}, 404)
            job_id = (qs.get('id') or qs.get('jobId') or [''])[0]
            try:
                job = xhs_note_replacement.load_job(DATA_DIR, job_id)
            except Exception as e:
                return json_response(self, {'ok': False, 'error': str(e)}, 400)
            if not job:
                return json_response(self, {'ok': False, 'error': 'not_found'}, 404)
            return json_response(self, {'ok': True, 'job': job})
        if path == '/api/accounts':
            return json_response(self, current_accounts())
        if path == '/api/library':
            return json_response(self, load_library())
        if path == '/api/publish/settings':
            return json_response(self, load_settings())
        if path == '/api/publish/queue':
            return json_response(self, load_queue())
        if path.startswith('/api/library/file/'):
            return self.serve_material_file(path)
        return json_response(self, {'ok': False, 'error': 'not_found'}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        ctype = self.headers.get('Content-Type', '') or ''
        if not ensure_agent_request(self, path):
            return
        if 'multipart/form-data' in ctype:
            try:
                return self.handle_multipart(path)
            except Exception as e:
                return json_response(self, {'ok': False, 'error': str(e), 'trace': traceback.format_exc()}, 500)
        body = read_body(self)
        try:
            if path == '/api/xhs-note-replacement/template':
                if not xhs_note_replacement.feature_enabled():
                    return json_response(self, {'ok': False, 'error': 'feature_disabled'}, 404)
                material = body.get('material') if isinstance(body.get('material'), dict) else {}
                source_note = body.get('sourceNote') if isinstance(body.get('sourceNote'), dict) else None
                if not material and body.get('materialId'):
                    material = find_material(str(body.get('materialId') or '').strip()) or {}
                template = xhs_note_replacement.build_template(material, source_note)
                job = {
                    'id': xhs_note_replacement.new_job_id(),
                    'status': 'template',
                    'templateId': template.get('id'),
                    'template': template,
                    'sourceMaterialId': template.get('sourceMaterialId') or material.get('id') or '',
                    'sourceNoteId': template.get('sourceNoteId') or '',
                    'aiSlotCount': 0,
                    'createdAt': time.time(),
                    'updatedAt': time.time(),
                }
                xhs_note_replacement.save_job(DATA_DIR, job)
                return json_response(self, {'ok': True, 'jobId': job['id'], 'template': template, 'job': job})

            if path == '/api/xhs-note-replacement/preview':
                if not xhs_note_replacement.feature_enabled():
                    return json_response(self, {'ok': False, 'error': 'feature_disabled'}, 404)
                template = body.get('template') if isinstance(body.get('template'), dict) else None
                job = None
                if not template and body.get('jobId'):
                    job = xhs_note_replacement.load_job(DATA_DIR, str(body.get('jobId') or ''))
                    template = (job or {}).get('template')
                preview = xhs_note_replacement.build_replacement_preview(template or {}, body.get('businessInput') or {}, body.get('providedAssets') or body.get('assets') or [])
                if job:
                    job.update({
                        'status': 'preview',
                        'businessInput': body.get('businessInput') or {},
                        'slotMappings': preview.get('slotMappings') or [],
                        'copyCandidates': preview.get('copyCandidates') or [],
                        'selectedCopyIndex': preview.get('selectedCopyIndex') or 0,
                        'aiSlotCount': preview.get('aiSlotCount') or 0,
                        'updatedAt': time.time(),
                    })
                    xhs_note_replacement.save_job(DATA_DIR, job)
                return json_response(self, {'ok': True, 'preview': preview, 'job': job})

            if path == '/api/xhs-note-replacement/confirm-ai-image':
                if not xhs_note_replacement.feature_enabled():
                    return json_response(self, {'ok': False, 'error': 'feature_disabled'}, 404)
                job = xhs_note_replacement.load_job(DATA_DIR, str(body.get('jobId') or ''))
                if not job:
                    return json_response(self, {'ok': False, 'error': 'not_found'}, 404)
                slot_index = body.get('slotIndex')
                for mapping in job.get('slotMappings') or []:
                    if str(mapping.get('slotIndex')) == str(slot_index):
                        mapping['confirmationStatus'] = 'confirmed'
                        if body.get('filePath'):
                            mapping['filePath'] = str(body.get('filePath') or '')
                job['updatedAt'] = time.time()
                xhs_note_replacement.save_job(DATA_DIR, job)
                return json_response(self, {'ok': True, 'job': job})

            if path == '/api/xhs-note-replacement/save-draft':
                if not xhs_note_replacement.feature_enabled():
                    return json_response(self, {'ok': False, 'error': 'feature_disabled'}, 404)
                try:
                    job = body.get('job') if isinstance(body.get('job'), dict) else None
                    if not job and body.get('jobId'):
                        job = xhs_note_replacement.load_job(DATA_DIR, str(body.get('jobId') or ''))
                    if not job:
                        return json_response(self, {'ok': False, 'error': 'not_found'}, 404)
                    if 'selectedCopyIndex' in body:
                        job['selectedCopyIndex'] = int(body.get('selectedCopyIndex') or 0)
                    copy_override = body.get('copyOverride') if isinstance(body.get('copyOverride'), dict) else {}
                    if copy_override:
                        selected_idx = int(job.get('selectedCopyIndex') or 0)
                        candidates = job.get('copyCandidates') if isinstance(job.get('copyCandidates'), list) else []
                        while len(candidates) <= selected_idx:
                            candidates.append({})
                        current_copy = candidates[selected_idx] if isinstance(candidates[selected_idx], dict) else {}
                        edited = dict(current_copy)
                        if 'title' in copy_override:
                            edited['title'] = str(copy_override.get('title') or '').strip()
                        if 'body' in copy_override:
                            edited['body'] = str(copy_override.get('body') or '').strip()
                        if 'tags' in copy_override:
                            raw_tags = copy_override.get('tags')
                            if isinstance(raw_tags, str):
                                raw_tags = re.split(r'[,，\s]+', raw_tags)
                            tags = []
                            for tag in raw_tags if isinstance(raw_tags, list) else []:
                                text = str(tag or '').strip()
                                if not text:
                                    continue
                                if not text.startswith('#'):
                                    text = '#' + text
                                if text not in tags:
                                    tags.append(text)
                            edited['tags'] = tags
                        candidates[selected_idx] = edited
                        job['copyCandidates'] = candidates
                    material_error = xhs_note_replacement.replacement_material_error(job)
                    if material_error:
                        return json_response(self, {'ok': False, 'error': material_error, 'stage': 'save_draft'}, 400)
                    source_paths = []
                    missing_slots = []
                    for mapping in job.get('slotMappings') or []:
                        fp = str(mapping.get('filePath') or '').strip()
                        if not fp:
                            missing_slots.append(mapping.get('slotIndex'))
                            continue
                        src = fp
                        if not os.path.isabs(src):
                            src = os.path.join(MATERIALS_DIR, os.path.basename(src))
                        if not os.path.isfile(src) or not validate_image_file(src).get('ok'):
                            missing_slots.append(mapping.get('slotIndex'))
                            continue
                        source_paths.append((mapping, src))
                    expected_slots = len(((job.get('template') or {}).get('imageSlots') or []))
                    if missing_slots or not source_paths or (expected_slots and len(source_paths) < expected_slots):
                        return json_response(self, {
                            'ok': False,
                            'error': 'xhs_note_replacement_missing_images',
                            'stage': 'save_draft',
                            'missingSlots': [x for x in missing_slots if x],
                        }, 400)
                    mid = uuid.uuid4().hex
                    mdir = os.path.join(MATERIALS_DIR, mid)
                    os.makedirs(mdir, exist_ok=True)
                    saved = []
                    used_names = set()
                    for idx, (_mapping, src) in enumerate(source_paths, start=1):
                        safe = _slot_material_filename(src, _mapping, idx, used_names)
                        dst = os.path.join(mdir, safe)
                        _copy_material_file(src, dst)
                        saved.append(safe)
                    payload = xhs_note_replacement.build_draft_material_payload(job, saved)
                    payload.update({
                        'id': mid,
                        'title': payload.get('title') or (job.get('template') or {}).get('originalCopy', {}).get('title') or '图文同款草稿',
                        'urls': ['/api/library/file/%s/%s' % (mid, fn) for fn in saved],
                        'createdAt': time.time(),
                    })
                    with STATE_LOCK:
                        lib = load_library()
                        lib.insert(0, payload)
                        save_library(lib)
                    job.update({'status': 'draft', 'publishDraftMaterialId': mid, 'updatedAt': time.time()})
                    xhs_note_replacement.save_job(DATA_DIR, job)
                    return json_response(self, {'ok': True, 'id': mid, 'material': payload, 'job': job})
                except Exception as exc:
                    raw_log = json_log(logger, 'xhs_note_save_failed', exc=exc, endpoint=path)
                    return json_response(self, {'ok': False, 'error': 'xhs_note_save_failed', 'errorId': (json.loads(raw_log) or {}).get('errorId'), 'stage': 'save_draft'}, 500)
            if path == '/api/cookie/import':
                cookie = (body.get('cookie') or '').strip()
                if not cookie:
                    raise RuntimeError('missing_cookie')
                auth = set_auth_from_cookie(cookie, source='import')
                return json_response(self, {'ok': True, 'cookieCount': len(auth.cookie or {}), 'cookie': auth_to_cookie_str(auth)})

            if path == '/api/cookie/capture/start':
                job_id = uuid.uuid4().hex
                with STATE_LOCK:
                    STATE['cookie_jobs'][job_id] = {'status': 'running'}
                threading.Thread(target=run_cookie_capture, args=(job_id,), daemon=True).start()
                return json_response(self, {'ok': True, 'sessionId': job_id})

            if path == '/api/cloud-login/start':
                cleanup_cloud_sessions()
                sid = uuid.uuid4().hex
                account_id = body.get('accountId') or body.get('account') or 'douyin-self'
                login_url = body.get('loginUrl') or os.getenv('DY_LOGIN_URL') or DOUYIN_MAIN_LOGIN_URL
                safe_account = _safe_account_key(account_id)
                force_new = bool(body.get('forceNew') or body.get('force'))
                if not force_new:
                    old_sid, old_sess = find_cloud_session_for_account(safe_account)
                    if old_sess:
                        try:
                            st = old_sess.status()
                        except Exception:
                            st = {'ok': False, 'error': 'existing_session_unhealthy'}
                        if st.get('ok') is not False:
                            st.update({
                                'ok': True,
                                'hasSession': True,
                                'reused': True,
                                'sessionId': old_sid,
                                'accountId': old_sess.account_id,
                                'loginUrl': old_sess.login_url,
                                'message': 'cloud_browser_reused',
                            })
                            return json_response(self, st)
                        try:
                            old_sess.close()
                        except Exception:
                            pass
                        with CLOUD_LOGIN_LOCK:
                            CLOUD_LOGIN_SESSIONS.pop(old_sid, None)
                close_cloud_sessions_for_account(safe_account)
                release_chromium_profile_if_stale(_cloud_profile_dir(safe_account))
                sess = CloudLoginSession(sid, account_id=account_id, login_url=login_url)
                with CLOUD_LOGIN_LOCK:
                    CLOUD_LOGIN_SESSIONS[sid] = sess
                try:
                    sess.start()
                    return json_response(self, {
                        'ok': True,
                        'sessionId': sid,
                        'accountId': sess.account_id,
                        'loginUrl': sess.login_url,
                        'message': 'cloud_browser_ready',
                    })
                except Exception as e:
                    with CLOUD_LOGIN_LOCK:
                        CLOUD_LOGIN_SESSIONS.pop(sid, None)
                    try:
                        sess.close()
                    except Exception:
                        pass
                    return json_response(self, {'ok': False, 'error': str(e), 'trace': traceback.format_exc()}, 500)

            if path == '/api/cloud-login/current':
                cleanup_cloud_sessions()
                account_id = body.get('accountId') or body.get('account') or 'douyin-self'
                sid, sess = find_cloud_session_for_account(account_id)
                if not sess:
                    return json_response(self, {
                        'ok': True,
                        'hasSession': False,
                        'accountId': _safe_account_key(account_id),
                        'message': 'no_active_cloud_login_session',
                    })
                st = sess.status()
                st.update({
                    'ok': True,
                    'hasSession': True,
                    'sessionId': sid,
                    'accountId': sess.account_id,
                    'loginUrl': sess.login_url,
                    'message': 'active_cloud_login_session',
                })
                return json_response(self, st)

            if path == '/api/cloud-login/screenshot':
                sess = cloud_session(body.get('sessionId'))
                return json_response(self, sess.screenshot())

            if path == '/api/cloud-login/qr':
                sess = cloud_session(body.get('sessionId'))
                return json_response(self, sess.qr())

            if path == '/api/cloud-login/status':
                sess = cloud_session(body.get('sessionId'))
                return json_response(self, sess.status())

            if path == '/api/cloud-login/click':
                sess = cloud_session(body.get('sessionId'))
                return json_response(self, sess.click(body.get('x', 0), body.get('y', 0)))

            if path == '/api/cloud-login/drag':
                sess = cloud_session(body.get('sessionId'))
                return json_response(self, sess.drag(body.get('x1', 0), body.get('y1', 0), body.get('x2', 0), body.get('y2', 0), body.get('steps', 24)))

            if path == '/api/cloud-login/type':
                sess = cloud_session(body.get('sessionId'))
                return json_response(self, sess.type_text(body.get('text', '')))

            if path == '/api/cloud-login/code':
                sess = cloud_session(body.get('sessionId'))
                return json_response(self, sess.code(body.get('code', body.get('text', '')), body.get('submit', True) is not False))

            if path == '/api/cloud-login/key':
                sess = cloud_session(body.get('sessionId'))
                return json_response(self, sess.key(body.get('key', 'Enter')))

            if path == '/api/cloud-login/sms':
                sess = cloud_session(body.get('sessionId'))
                return json_response(self, sess.auto_sms())

            if path == '/api/cloud-login/refresh':
                sess = cloud_session(body.get('sessionId'))
                return json_response(self, sess.refresh())

            if path == '/api/cloud-login/close':
                sid = body.get('sessionId')
                sess = cloud_session(sid)
                res = sess.close()
                with CLOUD_LOGIN_LOCK:
                    CLOUD_LOGIN_SESSIONS.pop(sid or '', None)
                return json_response(self, res)

            if path == '/api/login/start':
                fresh = bool(body.get('fresh') or body.get('newAccount') or body.get('new'))
                with STATE_LOCK:
                    if STATE.get('login_running'):
                        return json_response(self, {'ok': False, 'error': 'login_in_progress'}, 409)
                    STATE['login_running'] = True
                    job_id = uuid.uuid4().hex
                    STATE['cookie_jobs'][job_id] = {'status': 'running', 'fresh': fresh}
                try:
                    threading.Thread(target=run_login, args=(job_id,), kwargs={'fresh': fresh}, daemon=True).start()
                except Exception:
                    with STATE_LOCK:
                        STATE['login_running'] = False
                        STATE['cookie_jobs'][job_id] = {'status': 'error', 'error': 'thread_start_failed', 'trace': traceback.format_exc()}
                    raise
                return json_response(self, {'ok': True, 'sessionId': job_id})

            if path == '/api/xhs/login':
                fresh = bool(body.get('fresh') or body.get('newAccount') or body.get('new'))
                with STATE_LOCK:
                    if STATE.get('login_running'):
                        return json_response(self, {'ok': False, 'error': 'login_in_progress'}, 409)
                    STATE['login_running'] = True
                    job_id = uuid.uuid4().hex
                    STATE['cookie_jobs'][job_id] = {'status': 'running', 'platform': 'xhs', 'fresh': fresh}
                try:
                    threading.Thread(target=run_xhs_login, args=(job_id,), kwargs={'fresh': fresh}, daemon=True).start()
                except Exception:
                    with STATE_LOCK:
                        STATE['login_running'] = False
                        STATE['cookie_jobs'][job_id] = {'status': 'error', 'error': 'thread_start_failed', 'trace': traceback.format_exc()}
                    raise
                return json_response(self, {'ok': True, 'sessionId': job_id})

            if path == '/api/login/sync':
                if not PUBLISH_LOCK.acquire(timeout=2):
                    return json_response(self, {'ok': False, 'error': 'publish_busy'}, 409)
                try:
                    auth, res = sync_auth_from_profile(source='manual-profile-sync')
                finally:
                    PUBLISH_LOCK.release()
                return json_response(self, {
                    'ok': bool(auth and getattr(auth, 'cookie', None)),
                    'loggedIn': bool(res.get('logged_in')) if isinstance(res, dict) else False,
                    'cookieCount': len(getattr(auth, 'cookie', {}) or {}) if auth else 0,
                    'error': None if auth else 'no_profile_login',
                })

            if path in ('/api/accounts/remove', '/api/accounts/delete'):
                account_id = (body.get('id') or body.get('accountId') or body.get('account') or '').strip()
                delete_files = bool(body.get('deleteFiles') or body.get('purge'))
                res = remove_local_account(account_id, delete_files=delete_files)
                return json_response(self, res, 200 if res.get('ok') else 400)

            if path in ('/api/accounts/rename', '/api/accounts/update-name'):
                account_id = (body.get('id') or body.get('accountId') or body.get('account') or '').strip()
                name = (body.get('name') or body.get('nickname') or body.get('displayName') or '').strip()
                res = rename_account_display_name(account_id, name)
                return json_response(self, res, 200 if res.get('ok') else 400)

            if path == '/api/finder/discover':
                platform = platform_code(body.get('platform') or body.get('pf') or body.get('sourcePlatform') or 'douyin')
                keyword = (body.get('keyword') or body.get('product') or '').strip()
                video_num = int(body.get('videoNum', body.get('num', 5)) or 5)
                comment_mode = (body.get('commentMode') or 'page').strip()
                account_id = ''
                if platform == 'douyin':
                    account_id = default_douyin_comment_account_id(body.get('accountId') or body.get('account') or '')
                    if account_id:
                        with douyin_account_scope(account_id) as scoped:
                            auth = scoped[0]
                            data = discover_leads_by_keyword_platform(platform, auth, keyword, video_num, comment_mode)
                    else:
                        auth = require_auth()
                        data = discover_leads_by_keyword_platform(platform, auth, keyword, video_num, comment_mode)
                else:
                    if platform == 'xhs':
                        account_id = _xhs_safety_account_id(body.get('accountId') or body.get('account') or '')
                        guest_mode = xhs_collection_guest_mode(body, default=False)
                        confirmed = xhs_account_collection_confirmed(body)
                        gate = xhs_collection_account_gate("comment_read", account_id, guest_mode, confirmed)
                        if not gate.get("ok"):
                            return json_response(self, {'ok': False, **gate}, 429)
                        data = discover_leads_by_keyword_platform(platform, None, keyword, video_num, comment_mode, guest_mode=guest_mode)
                        xhs_log_guest_collection_block("comment_read", data, keyword=keyword)
                        record = xhs_safety_record("comment_read", account_id, data) if not guest_mode else {"safety": gate.get("safety")}
                        if isinstance(data, dict):
                            data.setdefault("safety", record.get("safety"))
                    else:
                        data = discover_leads_by_keyword_platform(platform, None, keyword, video_num, comment_mode)
                try:
                    _save_json(FINDER_LAST_JSON, {'ok': True, 'accountId': account_id, **data})
                except Exception:
                    pass
                return json_response(self, {'ok': True, 'accountId': account_id, **data})

            if path == '/api/douyin/comment/publish':
                with douyin_auth_for_request(body.get('accountId') or body.get('account') or '') as (auth, account_id):
                    aweme_id = (body.get('awemeId') or body.get('aweme_id') or '').strip()
                    url = (body.get('url') or body.get('workUrl') or '').strip()
                    aweme_id = extract_aweme_id(aweme_id or url)
                    content = (body.get('content') or body.get('text') or body.get('comment') or '').strip()
                    reply_id = (body.get('replyId') or body.get('reply_id') or '').strip()
                    dry = bool_arg(body.get('dryRun'), False)
                    safe_mode = bool_arg(body.get('safeMode'), True)
                    preflight = bool_arg(body.get('preflight'), True)
                    force = bool_arg(body.get('force'), False)
                    channel = (body.get('channel') or body.get('commentChannel') or 'auto').strip()
                    if dry and not aweme_id:
                        return json_response(self, {'ok': True, 'dryRun': True, 'validTarget': False, 'error': 'missing_aweme_id', 'status': 'invalid_target', 'content': sanitize_comment_for_risk(content) if safe_mode else compact_text(content, 160), 'accountId': account_id})
                    resp = publish_comment_to_douyin(auth, aweme_id, content, reply_id=reply_id, dry_run=dry, safe_mode=safe_mode, preflight=preflight, force=force, channel=channel)
                    return json_response(self, {'ok': bool(resp.get('ok', comment_publish_ok(resp))), 'accountId': account_id, **resp})

            if path == '/api/xhs/comment/publish':
                note_id = (body.get('noteId') or body.get('note_id') or '').strip()
                url = (body.get('url') or body.get('noteUrl') or '').strip()
                content = (body.get('content') or body.get('text') or body.get('comment') or '').strip()
                dry = bool_arg(body.get('dryRun'), False)
                safe_mode = bool_arg(body.get('safeMode'), True)
                account_id = _xhs_safety_account_id(body.get('accountId') or body.get('account') or '')
                gate = xhs_safety_preflight("comment", account_id, dry_run=dry)
                if not gate.get("ok"):
                    return json_response(self, {'ok': False, **gate}, 429)
                resp = xhs_publish_comment(url or note_id, content, dry_run=dry, safe_mode=safe_mode, data_dir=DATA_DIR)
                record = xhs_safety_record("comment", account_id, resp, dry_run=dry)
                if isinstance(resp, dict):
                    resp.setdefault("safety", record.get("safety"))
                return json_response(self, {'ok': bool(resp.get('ok')), **resp})

            if path == '/api/outreach/run':
                platform = platform_code(body.get('platform') or body.get('pf') or body.get('sourcePlatform') or 'douyin')
                account_id = body.get('accountId') or body.get('account') or ''
                keyword = (body.get('keyword') or body.get('product') or '').strip()
                if not keyword:
                    raise RuntimeError('missing_keyword')
                template = (body.get('template') or body.get('messageTemplate') or '').strip()
                video_num = int(body.get('videoNum', body.get('num', 5)) or 5)
                limit = int(body.get('limit', body.get('maxComments', 5)) or 5)
                dry = bool_arg(body.get('dryRun'), False)
                safe_mode = bool_arg(body.get('safeMode'), True)
                preflight = bool_arg(body.get('preflight'), True)
                force = bool_arg(body.get('force'), False)
                send_mode = (body.get('sendMode') or 'reply').strip()
                channel = (body.get('channel') or body.get('commentChannel') or 'auto').strip()
                interval_sec = float(body.get('intervalSec', 45 if safe_mode else 0.8) or 0)
                if platform == 'douyin':
                    with douyin_auth_for_request(account_id) as (auth, selected_account_id):
                        data = run_ai_outreach(auth, keyword, template=template, video_num=video_num, limit=limit, dry_run=dry, send_mode=send_mode, interval_sec=interval_sec, safe_mode=safe_mode, preflight=preflight, force=force, channel=channel, platform=platform)
                        return json_response(self, {'ok': True, 'accountId': selected_account_id, **data})
                data = run_ai_outreach(None, keyword, template=template, video_num=video_num, limit=limit, dry_run=dry, send_mode=send_mode, interval_sec=interval_sec, safe_mode=safe_mode, preflight=preflight, force=force, channel=channel, platform=platform)
                return json_response(self, {'ok': True, **data})

            if path == '/api/douyin/dm':
                try:
                    data = run_douyin_dm(
                        body.get('target') or body.get('userUrl') or body.get('toUserId') or body.get('secUid') or '',
                        body.get('content') or body.get('text') or '',
                        body.get('accountId') or body.get('account') or '',
                    )
                    return json_response(self, data, 200 if data.get('ok') else 500)
                except Exception as e:
                    need_login = is_douyin_auth_error(e)
                    code = 401 if need_login else 500
                    return json_response(self, {'ok': False, 'needLogin': need_login, 'error': str(e), 'trace': traceback.format_exc()}, code)

            if path == '/api/douyin/dm/inbox':
                try:
                    data = run_douyin_dm_inbox(
                        body.get('target') or body.get('userUrl') or body.get('secUid') or '',
                        body.get('limit') or 10,
                        body.get('sinceFingerprint') or '',
                        body.get('accountId') or body.get('account') or '',
                    )
                    status = 200 if data.get('ok') else (400 if data.get('error') == 'missing_target' else 500)
                    return json_response(self, data, status)
                except Exception as e:
                    need_login = is_douyin_auth_error(e)
                    code = 401 if need_login else 500
                    return json_response(self, {'ok': False, 'needLogin': need_login, 'error': str(e), 'trace': traceback.format_exc()}, code)

            if path == '/api/douyin/search':
                with douyin_auth_for_request(body.get('accountId') or body.get('account') or '') as (auth, account_id):
                    query = (body.get('query') or body.get('keyword') or body.get('q') or '').strip()
                    require_num = int(body.get('num', body.get('limit', 20)) or 20)
                    sort_type = str(body.get('sort_type', '0'))
                    publish_time = str(body.get('publish_time', '0'))
                    filter_duration = str(body.get('filter_duration', ''))
                    search_range = str(body.get('search_range', '0'))
                    content_type = str(body.get('content_type', '0'))
                    errors = []
                    items = []
                    fast_cache_ttl = int(os.getenv('DY_SEARCH_CACHE_FAST_TTL_SEC', '900') or 900)
                    prefer_fresh = bool_arg(body.get('preferFresh', body.get('refresh')), False)
                    if fast_cache_ttl > 0 and not prefer_fresh:
                        cached = load_douyin_search_cache(query, require_num, ttl_sec=fast_cache_ttl)
                        if cached:
                            errors.append({'stage': 'cache-fast', 'ageSec': cached.get('ageSec'), 'reason': 'recent_verified_cache'})
                            return json_response(self, {'ok': True, 'platform': 'douyin', 'accountId': account_id, 'keyword': query, 'count': cached.get('count') or len(cached.get('items') or []), 'items': cached.get('items') or [], 'errors': errors, 'cacheFallback': True, 'cacheFast': True, 'cacheAgeSec': cached.get('ageSec')})
                    # Browser-first is intentional: the legacy signed API can return verify_check
                    # when DouyinAuth injects a generated msToken into Cookie. A clean browser
                    # profile with the persisted login Cookie is the stable commercial path.
                    try:
                        items = browser_search_videos(query, require_num, getattr(auth, 'cookie', None))
                    except Exception as e:
                        errors.append({'stage': 'browser-search', 'error': str(e)})
                    if not items:
                        try:
                            raw = SPIDER.douyin_apis.search_some_general_work(auth, query, require_num, sort_type, publish_time, filter_duration, search_range, content_type)
                            items = normalize_douyin_search_results(raw, require_num)
                        except Exception as e:
                            errors.append({'stage': 'api-search', 'error': str(e)})
                    if items:
                        save_douyin_search_cache(query, require_num, items, source='douyin-search')
                        return json_response(self, {'ok': True, 'platform': 'douyin', 'accountId': account_id, 'keyword': query, 'count': len(items), 'items': items, 'errors': errors, 'cacheFallback': False})
                    cached = load_douyin_search_cache(query, require_num)
                    if cached:
                        errors.append({'stage': 'cache-fallback', 'ageSec': cached.get('ageSec'), 'reason': 'live_search_empty'})
                        return json_response(self, {'ok': True, 'platform': 'douyin', 'accountId': account_id, 'keyword': query, 'count': cached.get('count') or len(cached.get('items') or []), 'items': cached.get('items') or [], 'errors': errors, 'cacheFallback': True, 'cacheAgeSec': cached.get('ageSec')})
                    return json_response(self, {'ok': True, 'platform': 'douyin', 'accountId': account_id, 'keyword': query, 'count': 0, 'items': [], 'errors': errors, 'cacheFallback': False})

            if path == '/api/xhs/search':
                query = body.get('query', '') or body.get('keyword', '')
                require_num = int(body.get('num', 20) or 20)
                account_id = _xhs_safety_account_id(body.get('accountId') or body.get('account') or '')
                guest_mode = xhs_collection_guest_mode(body)
                confirmed = xhs_account_collection_confirmed(body)
                gate = xhs_collection_account_gate("search", account_id, guest_mode, confirmed)
                if not gate.get("ok"):
                    return json_response(self, {'ok': False, **gate}, 429)
                result = xhs_search_notes(query, require_num, data_dir=DATA_DIR, guest_mode=guest_mode)
                xhs_log_guest_collection_block("search", result, keyword=query)
                record = xhs_safety_record("search", account_id, result) if not guest_mode else {"safety": gate.get("safety")}
                if isinstance(result, dict):
                    result.setdefault("safety", record.get("safety"))
                return json_response(self, result)

            if path == '/api/douyin/work':
                auth = require_auth()
                url = (body.get('url') or '').strip()
                if not url:
                    raise RuntimeError('missing_url')
                work = SPIDER.spider_work(auth, url)
                return json_response(self, {'ok': True, 'work': work})

            if path == '/api/douyin/comments':
                url = (body.get('url') or '').strip()
                mode = (body.get('mode') or 'page').strip().lower()
                if not url:
                    raise RuntimeError('missing_url')
                account_id = default_douyin_comment_account_id(body.get('accountId') or body.get('account') or '')
                try:
                    if account_id:
                        with douyin_account_scope(account_id) as scoped:
                            auth = scoped[0]
                            if mode == 'all':
                                data = SPIDER.douyin_apis.get_work_all_comment(auth, url)
                            elif mode in ('all_out', 'out_all', 'allout'):
                                data = SPIDER.douyin_apis.get_work_all_out_comment(auth, url)
                            else:
                                data = SPIDER.douyin_apis.get_work_out_comment(auth, url, str(body.get('cursor') or '0'))
                    else:
                        auth = require_auth()
                        if mode == 'all':
                            data = SPIDER.douyin_apis.get_work_all_comment(auth, url)
                        elif mode in ('all_out', 'out_all', 'allout'):
                            data = SPIDER.douyin_apis.get_work_all_out_comment(auth, url)
                        else:
                            data = SPIDER.douyin_apis.get_work_out_comment(auth, url, str(body.get('cursor') or '0'))
                    raw_comments = data.get('comments') if isinstance(data, dict) else data
                    items = normalize_comments(raw_comments)
                    return json_response(self, {'ok': True, 'comments': data, 'items': items, 'count': len(items), 'cacheFallback': False, 'accountId': account_id})
                except Exception as e:
                    cached_items = cached_douyin_comments_for_url(url, int(body.get('limit') or 120))
                    if cached_items:
                        return json_response(self, {
                            'ok': True,
                            'comments': {'comments': cached_items, 'source': 'finder_last_result'},
                            'items': cached_items,
                            'count': len(cached_items),
                            'cacheFallback': True,
                            'liveError': str(e)[:500],
                        })
                    return json_response(self, {'ok': False, 'error': str(e), 'cacheFallback': False}, 502)

            if path == '/api/xhs/comments':
                url = (body.get('url') or body.get('noteUrl') or '').strip()
                limit = int(body.get('limit', 120) or 120)
                account_id = _xhs_safety_account_id(body.get('accountId') or body.get('account') or '')
                guest_mode = xhs_collection_guest_mode(body, default=False)
                confirmed = xhs_account_collection_confirmed(body)
                gate = xhs_collection_account_gate("comment_read", account_id, guest_mode, confirmed)
                if not gate.get("ok"):
                    return json_response(self, {'ok': False, **gate}, 429)
                data = xhs_get_comments(url, limit=limit, data_dir=DATA_DIR, guest_mode=guest_mode)
                xhs_log_guest_collection_block("comment_read", data, url=url)
                record = xhs_safety_record("comment_read", account_id, data) if not guest_mode else {"safety": gate.get("safety")}
                if isinstance(data, dict):
                    data.setdefault("safety", record.get("safety"))
                return json_response(self, {'ok': True, **data})

            if path == '/api/douyin/download':
                with douyin_auth_for_request(body.get('accountId') or body.get('account') or '') as (auth, account_id):
                    url = (body.get('url') or '').strip()
                    save_choice = body.get('save_choice', 'all')
                    dry = bool_arg(body.get('dryRun'), False)
                    if not url:
                        raise RuntimeError('missing_url')
                    if dry:
                        work = SPIDER.spider_work(auth, url)
                        return json_response(self, {
                            'ok': True,
                            'accountId': account_id,
                            'dryRun': True,
                            'wouldDownload': True,
                            'work': work,
                            'saveChoice': save_choice,
                            'files': [],
                        })
                    try:
                        work, save_path = download_douyin_work_with_refresh(auth, url, save_choice)
                    except MediaDownloadError as exc:
                        status = 403 if exc.code == 'download_http_403' else 502
                        return json_response(self, {
                            'ok': False,
                            'accountId': account_id,
                            'error': exc.code,
                            'stage': 'download',
                            'context': exc.context,
                        }, status)
                    files = list_download_files(save_path)
                    try:
                        material = import_download_to_library(save_path, work, source_url=url, platform='douyin')
                    except Exception as exc:
                        raw_log = json_log(
                            logger,
                            'download_library_import_failed',
                            exc=exc,
                            endpoint=path,
                            platform='douyin',
                            source_url=url,
                        )
                        error_id = (json.loads(raw_log) or {}).get('errorId')
                        return json_response(self, {
                            'ok': False,
                            'accountId': account_id,
                            'error': 'library_import_failed',
                            'errorId': error_id,
                            'stage': 'library',
                        }, 500)
                    if not isinstance(material, dict) or not material.get('id'):
                        raw_log = json_log(
                            logger,
                            'download_library_import_failed',
                            endpoint=path,
                            platform='douyin',
                            source_url=url,
                            reason='missing_material_id',
                        )
                        return json_response(self, {
                            'ok': False,
                            'accountId': account_id,
                            'error': 'library_import_failed',
                            'errorId': (json.loads(raw_log) or {}).get('errorId'),
                            'stage': 'library',
                            'work': work,
                            'savePath': save_path,
                            'files': files,
                        }, 500)
                    return json_response(self, {'ok': True, 'accountId': account_id, 'work': work, 'savePath': save_path, 'files': files, 'material': material, 'materialId': (material or {}).get('id')})

            if path == '/api/xhs/download':
                url = (body.get('url') or body.get('noteUrl') or '').strip()
                if not url:
                    raise RuntimeError('missing_url')
                account_id = _xhs_safety_account_id(body.get('accountId') or body.get('account') or '')
                guest_mode = xhs_collection_guest_mode(body)
                confirmed = xhs_account_collection_confirmed(body)
                gate = xhs_collection_account_gate("download", account_id, guest_mode, confirmed)
                if not gate.get("ok"):
                    return json_response(self, {'ok': False, **gate}, 429)
                res = xhs_download_note(url, BASE_PATH['media'], data_dir=DATA_DIR, guest_mode=guest_mode)
                xhs_log_guest_collection_block("download", res, url=url)
                record = xhs_safety_record("download", account_id, res) if not guest_mode else {"safety": gate.get("safety")}
                if isinstance(res, dict):
                    res.setdefault("safety", record.get("safety"))
                if isinstance(res, dict) and res.get('ok'):
                    sp = res.get('savePath') or res.get('path') or res.get('save_path')
                    note_info = {}
                    if isinstance(res.get('note'), dict):
                        note_info.update(res.get('note') or {})
                    elif isinstance(res.get('work'), dict):
                        note_info.update(res.get('work') or {})
                    for key in ('title', 'body', 'tags', 'noteId', 'note_id'):
                        if key in res and key not in note_info:
                            note_info[key] = res.get(key)
                    try:
                        material = import_download_to_library(sp, note_info, source_url=url, platform='xhs') if sp else None
                    except Exception as exc:
                        raw_log = json_log(
                            logger,
                            'download_library_import_failed',
                            exc=exc,
                            endpoint=path,
                            platform='xhs',
                            source_url=url,
                        )
                        return json_response(self, {
                            'ok': False,
                            'error': 'library_import_failed',
                            'errorId': (json.loads(raw_log) or {}).get('errorId'),
                            'stage': 'library',
                        }, 500)
                    if not isinstance(material, dict) or not material.get('id'):
                        raw_log = json_log(
                            logger,
                            'download_library_import_failed',
                            endpoint=path,
                            platform='xhs',
                            source_url=url,
                            reason='missing_material_id',
                        )
                        return json_response(self, {
                            'ok': False,
                            'error': 'library_import_failed',
                            'errorId': (json.loads(raw_log) or {}).get('errorId'),
                            'stage': 'library',
                        }, 500)
                    res['material'] = material
                    res['materialId'] = (material or {}).get('id')
                return json_response(self, res)

            if path == '/api/library/delete':
                mid = (body.get('id') or '').strip()
                with STATE_LOCK:
                    save_library([m for m in load_library() if m.get('id') != mid])
                try:
                    shutil.rmtree(os.path.join(MATERIALS_DIR, mid), ignore_errors=True)
                except Exception:
                    pass
                return json_response(self, {'ok': True})

            if path == '/api/library/update-title':
                mid = (body.get('id') or '').strip()
                title = str(body.get('title') or '').strip()
                updated = False
                with STATE_LOCK:
                    lib = load_library()
                    for m in lib:
                        if m.get('id') == mid:
                            m['title'] = title
                            updated = True
                            break
                    if updated:
                        save_library(lib)
                if not updated:
                    return json_response(self, {'ok': False, 'error': 'material_not_found'}, 404)
                return json_response(self, {'ok': True, 'id': mid, 'title': title})

            if path == '/api/publish/settings':
                s = {
                    'perAccountPerDay': int(body.get('perAccountPerDay', body.get('perAccount', 1)) or 1),
                    'intervalMin': int(body.get('intervalMin', 60) or 60),
                    'enabled': bool(body.get('enabled', False)),
                }
                save_settings(s)
                return json_response(self, {'ok': True, **s})

            if path == '/api/publish/queue/add':
                material_id = (body.get('materialId') or '').strip()
                account_id = (body.get('accountId') or 'douyin-self').strip()
                m = find_material(material_id)
                if not m:
                    raise RuntimeError('material_not_found')
                accs = {a['id']: a for a in current_accounts()}
                acc = accs.get(account_id) or {'name': '抖音账号'}
                with STATE_LOCK:
                    q = load_queue()
                    q.append({
                        'id': uuid.uuid4().hex, 'accountId': account_id, 'accountName': acc.get('name', ''),
                        'materialId': material_id, 'materialTitle': m.get('title', ''),
                        'type': m.get('type', 'video'), 'status': 'pending', 'addedAt': time.time(),
                    })
                    save_queue(q)
                return json_response(self, {'ok': True})

            if path == '/api/publish/queue/clear':
                with STATE_LOCK:
                    save_queue([j for j in load_queue() if j.get('status') == 'running'])
                return json_response(self, {'ok': True})

            if path == '/api/publish/run':
                material_id = (body.get('materialId') or '').strip()
                account_id = (body.get('accountId') or 'douyin-self').strip()
                publish_platform = platform_code(body.get('platform') or ('xhs' if 'xhs' in account_id.lower() else 'douyin'))
                dry = bool(body.get('dryRun', True))
                m = find_material(material_id)
                if not m and isinstance(body.get('centralMaterial'), dict):
                    m = stage_central_material(body.get('centralMaterial'))
                if not m:
                    raise RuntimeError('material_not_found')
                publish_title = str(body.get('publishTitle') if body.get('publishTitle') is not None else m.get('title', '')).strip()
                # run_publish 会先从缓存 / 持久化 profile 无交互恢复登录态；
                # 这里不能提前 require_auth，否则 API 重启后会误判 no_auth 并要求重新扫码。
                res = run_publish(m, account_id, dry_run=dry, title_override=publish_title, platform=publish_platform)
                if res.get('error') == 'publish_busy':
                    return json_response(self, {'ok': False, 'error': 'publish_busy'}, 409)
                return json_response(self, {
                    'ok': bool(res.get('ok')), 'filled': bool(res.get('filled')),
                    'published': bool(res.get('published')), 'dryRun': bool(dry), 'error': res.get('error'),
                    'platform': publish_platform, 'finalUrl': res.get('final_url'),
                    'steps': res.get('steps'), 'shot': res.get('shot'), 'button': res.get('button'),
                })

            return json_response(self, {'ok': False, 'error': 'not_found', 'path': path}, 404)
        except Exception as e:
            need_login = is_douyin_auth_error(e)
            code = 401 if need_login else (400 if str(e) in {'missing_cookie', 'missing_url'} else 500)
            return json_response(self, {'ok': False, 'needLogin': need_login, 'platform': 'douyin' if need_login else '', 'error': str(e), 'trace': traceback.format_exc()}, code)


def main():
    os.chdir(os.path.dirname(__file__))
    tok = agent_token()
    try:
        with open(os.path.join(DATA_DIR, 'agent_token.txt'), 'w', encoding='utf-8') as f:
            f.write(tok + '\n')
    except Exception:
        pass
    threading.Thread(target=publish_scheduler, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'MatrixShipAgent {AGENT_VERSION} listening on http://{HOST}:{PORT}')
    print(f'Data dir: {DATA_DIR}')
    if token_auth_enabled():
        print(f'Authorization code: {tok}')
    server.serve_forever()


if __name__ == '__main__':
    main()
