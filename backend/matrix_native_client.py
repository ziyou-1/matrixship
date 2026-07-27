# coding: utf-8
"""矩阵星舰 桌面客户端(原生 Qt / PySide6,非网页)。

真正的原生 Windows 应用:原生控件、自带标题栏与任务栏图标、分组侧边导航,打包成
MatrixShipAgent.exe。界面在客户端里用原生控件绘制;平台自动化在本机 Edge + 你的 IP
上执行(内嵌本地引擎 api_server:9081 + local-browser worker)。

原生客户端模块映射。各模块均已接本地引擎/后端与真实生成流水线(软文/爆款/商品图·视频/
数字人/混剪/工作流均真调 lk888 或 ffmpeg;采集/发布/寻客/拓客经本机 Edge 执行);
计费(云豆余额/扣费/失败退款/兑换码充值)已接通。唯「AI 销售」目前仅手动单发私信,
自动回复话术待补。
"""

import os
import sys
import time
import threading
import queue
import uuid
import subprocess
import shutil
import concurrent.futures
import ipaddress
import mimetypes
import re
from urllib.parse import parse_qs, quote, urlparse

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from utils.structured_log import json_log
from utils.media_validation import validate_video_file
from utils.video_transcription import (
    export_audio_chunks,
    merge_transcription_segments,
    transcribe_audio_chunks,
    validate_service_url,
)
from runtime_paths import ensure_agent_data_dir

import requests
from PySide6 import QtCore, QtGui, QtWidgets

CENTRAL = validate_service_url(
    os.getenv("MATRIX_CENTRAL") or os.getenv("CENTRAL_URL") or "http://127.0.0.1:9080"
).rstrip("/")
APP_NAME = "MatrixShipAgent"
APP_VERSION = "1.1.16"
ACCENT = "#6366f1"
LEGAL_TERMS_VERSION = os.getenv("LEGAL_TERMS_VERSION", "1.0") or "1.0"
LEGAL_PRIVACY_VERSION = os.getenv("LEGAL_PRIVACY_VERSION", "1.0") or "1.0"
LEGAL_EFFECTIVE_DATE = os.getenv("LEGAL_EFFECTIVE_DATE", "2026-07-15") or "2026-07-15"
_LEGAL_DOC_DIR = os.path.join(_BACKEND_DIR, "legal")
_LEGAL_DOC_FILES = {
    "terms": "user_agreement.md",
    "privacy": "privacy_policy.md",
}

_SHARED = {"token": "", "org": "org-default", "account": "default", "logout_epoch": 0,
           "appRole": "platform_admin", "roleScope": "all"}
_SLOCK = threading.Lock()
_LOGQ = queue.Queue()
_LOG_FH = None


def _load_legal_document(kind):
    filename = _LEGAL_DOC_FILES.get(str(kind or "").strip().lower())
    if not filename:
        raise ValueError("unknown_legal_document")
    path = os.path.join(_LEGAL_DOC_DIR, filename)
    with open(path, "r", encoding="utf-8-sig") as handle:
        return handle.read()


def _legal_consent_payload():
    return {
        "accepted": True,
        "termsVersion": LEGAL_TERMS_VERSION,
        "privacyVersion": LEGAL_PRIVACY_VERSION,
        "acceptedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "clientVersion": APP_VERSION,
    }


def _auth_pref_has_current_legal_consent(pref):
    pref = pref if isinstance(pref, dict) else {}
    return bool(
        pref.get("legalTermsVersion") == LEGAL_TERMS_VERSION
        and pref.get("legalPrivacyVersion") == LEGAL_PRIVACY_VERSION
    )


def data_dir():
    return ensure_agent_data_dir(migrate_legacy=True)


def logs_dir():
    d = os.path.join(data_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


def _open_logfile():
    """开一个当日滚动日志文件,log() 会同时落盘(进程退出也留痕,便于分发后定位问题)。"""
    global _LOG_FH
    try:
        p = os.path.join(logs_dir(), "client-%s.log" % time.strftime("%Y%m%d"))
        _LOG_FH = open(p, "a", encoding="utf-8", buffering=1)
        _LOG_FH.write("\n==== 启动 %s  v%s  pid=%s ====\n"
                      % (time.strftime("%Y-%m-%d %H:%M:%S"), APP_VERSION, os.getpid()))
    except Exception:
        _LOG_FH = None


def log(msg):
    line = time.strftime("%H:%M:%S ") + str(msg)
    _LOGQ.put(line)
    if _LOG_FH is not None:
        try:
            _LOG_FH.write(line + "\n")
        except Exception:
            pass


class _ClientJsonLogger:
    def error(self, value):
        log(value)

    def info(self, value):
        log(value)


_CLIENT_JSON_LOGGER = _ClientJsonLogger()


def _restart_client_detached():
    """Start a login-only replacement process that survives this Qt process."""
    if getattr(sys, "frozen", False):
        program = sys.executable
        arguments = []
        cwd = os.path.dirname(sys.executable)
    else:
        program = sys.executable
        script = os.path.abspath(__file__)
        arguments = [script]
        cwd = os.path.dirname(script)
    try:
        result = QtCore.QProcess.startDetached(program, arguments, cwd)
        if isinstance(result, tuple):
            started = bool(result[0])
            pid = int(result[1] or 0) if len(result) > 1 else 0
        else:
            started = bool(result)
            pid = 0
        if not started:
            raise RuntimeError("QProcess.startDetached returned false")
        json_log(
            _CLIENT_JSON_LOGGER,
            "client_logout_restart_started",
            level="info",
            pid=pid,
            frozen=bool(getattr(sys, "frozen", False)),
        )
        return True, ""
    except Exception as exc:
        error_id = "err-" + uuid.uuid4().hex[:16]
        json_log(
            _CLIENT_JSON_LOGGER,
            "client_logout_restart_failed",
            errorId=error_id,
            exc=exc,
            program=os.path.basename(program),
            frozen=bool(getattr(sys, "frozen", False)),
        )
        return False, error_id


_VIDEO_BREAKDOWN_OWNER_FILE = "owner.json"
YUNLING_MARK_PATH = os.path.join(_BACKEND_DIR, "assets", "yunling_mark.png")


def _pid_is_active(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes
            process_query_limited_information = 0x1000
            still_active = 259
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, pid
            )
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == still_active
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def write_video_breakdown_job_owner(job_dir, pid=None, created_at=None):
    os.makedirs(job_dir, exist_ok=True)
    owner = {
        "pid": int(pid if pid is not None else os.getpid()),
        "createdAt": float(created_at if created_at is not None else time.time()),
    }
    _atomic_write_json(os.path.join(job_dir, _VIDEO_BREAKDOWN_OWNER_FILE), owner)
    return owner


def cleanup_video_breakdown_temp_root(base_dir=None):
    root = os.path.join(base_dir or data_dir(), "video_breakdowns")
    if not os.path.lexists(root):
        return {"status": "ok", "removed": 0, "skippedActive": 0,
                "retained": 0, "errors": [], "root": root}
    if os.path.islink(root) or not os.path.isdir(root):
        return {"status": "failed", "removed": 0, "skippedActive": 0,
                "retained": 0, "errors": [{"code": "video_breakdown_temp_root_invalid"}],
                "root": root}
    try:
        retention = max(0.0, float(
            os.getenv("VIDEO_BREAKDOWN_TEMP_RETENTION_SEC", "3600") or 3600
        ))
    except (TypeError, ValueError):
        retention = 3600.0
    now = time.time()
    removed = 0
    skipped_active = 0
    retained = 0
    errors = []
    for name in os.listdir(root):
        job_dir = os.path.join(root, name)
        if os.path.islink(job_dir) or not os.path.isdir(job_dir):
            retained += 1
            continue
        owner = {}
        owner_path = os.path.join(job_dir, _VIDEO_BREAKDOWN_OWNER_FILE)
        try:
            if os.path.isfile(owner_path):
                import json as _json
                with open(owner_path, "r", encoding="utf-8") as handle:
                    value = _json.load(handle)
                if isinstance(value, dict):
                    owner = value
        except Exception as exc:
            json_log(
                _CLIENT_JSON_LOGGER,
                "video_breakdown_owner_read_failed",
                exc=exc,
                code="video_breakdown_owner_read_failed",
                job=name,
            )
        if _pid_is_active(owner.get("pid")):
            skipped_active += 1
            continue
        try:
            created_at = float(owner.get("createdAt"))
        except (TypeError, ValueError):
            try:
                created_at = float(os.path.getmtime(job_dir))
            except OSError:
                created_at = now
        if max(0.0, now - created_at) < retention:
            retained += 1
            continue
        try:
            shutil.rmtree(job_dir)
            removed += 1
        except Exception as exc:
            raw = json_log(
                _CLIENT_JSON_LOGGER,
                "video_breakdown_temp_cleanup_failed",
                exc=exc,
                code="video_breakdown_temp_cleanup_failed",
                job=name,
                temp_root=root,
            )
            import json as _json
            errors.append({
                "code": "video_breakdown_temp_cleanup_failed",
                "job": name,
                "errorId": (_json.loads(raw) or {}).get("errorId"),
            })
    return {
        "status": "partial" if errors else "ok",
        "removed": removed,
        "skippedActive": skipped_active,
        "retained": retained,
        "errors": errors,
        "root": root,
    }


def install_crash_handler():
    """全局未捕获异常兜底:写 crash 日志到 %APPDATA%\\MatrixShipAgent\\logs,避免静默崩溃无痕迹。"""
    import traceback as _tb

    def _hook(exc_type, exc, tb):
        try:
            txt = "".join(_tb.format_exception(exc_type, exc, tb))
            p = os.path.join(logs_dir(), "crash-%s.log" % time.strftime("%Y%m%d_%H%M%S"))
            with open(p, "w", encoding="utf-8") as f:
                f.write("MatrixShipAgent v%s 未捕获异常\n%s" % (APP_VERSION, txt))
            log("⚠️ 未捕获异常已记录:" + p)
        except Exception:
            pass
        try:
            _tb.print_exception(exc_type, exc, tb)
        except Exception:
            pass
    sys.excepthook = _hook


def _version_gt(a, b):
    """点分版本比较:a > b 返回 True(如 1.0.2 > 1.0.1)。"""
    def parts(v):
        out = []
        for x in str(v or "").split("."):
            digits = "".join(ch for ch in x if ch.isdigit())
            out.append(int(digits) if digits else 0)
        return out
    pa, pb = parts(a), parts(b)
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    return pa > pb


def _atomic_write_json(path, obj):
    """原子写 JSON:先写同目录临时文件再 os.replace 覆盖,避免并发写/崩溃留下半截文件被下次读成损坏而清空。"""
    import json as _json
    import tempfile
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise


def setup_env():
    d = data_dir()
    os.makedirs(d, exist_ok=True)
    cleanup_video_breakdown_temp_root(d)
    cleanup_video_replacement_temp_root(d)
    recover_stale_video_replacement_jobs(d)
    # 注意:MATRIX_AGENT_DATA_DIR / DY_PROFILE_DIR 不在这里设 —— 它们由 apply_account_scope
    # 在“登录之后”按登录账号设成 data/accounts/<账号>/ 子目录,实现账号数据隔离。
    os.environ.setdefault("API_HOST", "127.0.0.1")
    os.environ.setdefault("API_PORT", "9081")
    os.environ.setdefault("MATRIX_AGENT_TOKEN_AUTH", "1")
    os.environ.setdefault("DY_COMMENT_EDGE_UI_FALLBACK", "1")
    # 抖音搜索冷启动根治:隔离子进程用 sys.executable(=冻结的 MatrixShipAgent.exe)跑 `-c code`,
    # 但冻结 exe 不支持 -c → 只会拉起一个没用的第二个 GUI 实例,父进程干等满 180s 超时才回退到进程内
    # 搜索(这就是那 ~205s 冷启动 + 偶发"Permission denied on exe")。本地客户端关掉隔离子进程,
    # 直接进程内搜索(本就是回退路径、已验证能出结果),冷启动 ~205s → ~25s。隔离仅为 Linux 云节点设计。
    os.environ.setdefault("DY_SEARCH_ISOLATED", "0")
    try:
        from runtime_paths import ensure_node_on_path
        ensure_node_on_path()
    except Exception as e:
        log("node shim: %s" % e)


def account_key(account):
    """把登录账号(手机号/admin)规范成可做目录名的隔离键。"""
    import re
    key = re.sub(r"[^A-Za-z0-9_.-]", "_", str(account or "default").strip()) or "default"
    return key[:64]


def login_needs_phone_code(identifier):
    identifier = str(identifier or "").strip()
    return identifier.isdigit() and len(identifier) == 11


def _account_scope_root_dir():
    root = os.getenv("MATRIX_AGENT_ROOT_DATA_DIR") or ""
    if root:
        return os.path.abspath(os.path.expandvars(root))
    root = os.getenv("MATRIX_AGENT_DATA_DIR") or os.getenv("DY_DATA_DIR") or data_dir()
    root = os.path.abspath(os.path.expandvars(root))
    os.environ["MATRIX_AGENT_ROOT_DATA_DIR"] = root
    return root


def apply_account_scope(account):
    """账号隔离:登录后把本地引擎的数据根目录锁到 data/accounts/<账号>/。

    该账号的抖音/小红书登录 profile、creator 登录态、cookie、素材、任务、搜索缓存等
    全部落在自己的目录,互不干扰。必须在 start_engine() 之前调用(引擎 import 时按
    MATRIX_AGENT_DATA_DIR 定 DATA_DIR)。同时按账号设固定 MATRIX_AGENT_TOKEN,使同进程
    的引擎与 worker 用同一 token,鉴权一致。
    """
    import hashlib
    import shutil
    base = _account_scope_root_dir()
    key = account_key(account)
    acc_dir = os.path.join(base, "accounts", key)
    os.makedirs(acc_dir, exist_ok=True)
    # 首次为该账号建目录时,把历史“共享 data/”里的登录态迁移进来(移动,不复制,避免复制 500MB+ profile)
    try:
        if not os.path.isdir(os.path.join(acc_dir, "dy_profile")):
            for name in ("auth_cookie.json", "creator_state.json", "library.json",
                         "publish_settings.json", "publish_queue.json", "agent_config.json"):
                s = os.path.join(base, name)
                dst = os.path.join(acc_dir, name)
                if os.path.isfile(s) and not os.path.exists(dst):
                    try:
                        shutil.move(s, dst)
                    except Exception:
                        pass
            for name in ("dy_profile", "xhs_profile", "materials", "media_datas", "dy_search_profile"):
                s = os.path.join(base, name)
                dst = os.path.join(acc_dir, name)
                if os.path.isdir(s) and not os.path.exists(dst):
                    try:
                        shutil.move(s, dst)
                    except Exception:
                        pass
    except Exception as e:
        log("账号数据迁移: %s" % e)
    os.environ["MATRIX_AGENT_DATA_DIR"] = acc_dir
    os.environ["DY_DATA_DIR"] = acc_dir
    os.environ["DY_PROFILE_DIR"] = os.path.join(acc_dir, "dy_profile")
    os.environ["XHS_PROFILE_DIR"] = os.path.join(acc_dir, "xhs_profile")
    os.environ["MATRIX_AGENT_TOKEN"] = hashlib.sha256(("matrixship-agent:" + key).encode()).hexdigest()[:32]
    log("账号隔离数据目录: %s" % acc_dir)
    return acc_dir, key


# ---------- engine + worker (run inside this app) ----------

def start_engine():
    def run():
        try:
            from api_server import main as api_main
            api_main()
        except Exception as e:
            log("本地引擎异常: %s" % e)
    threading.Thread(target=run, name="engine", daemon=True).start()
    log("本地执行引擎启动中 (127.0.0.1:%s)" % os.environ.get("API_PORT", "9081"))


def start_worker_manager():
    import local_browser_worker as lbw

    def run():
        base = lbw.load_config()
        worker = None
        worker_epoch = None
        while True:
            with _SLOCK:
                t, o = _SHARED["token"], _SHARED["org"]
                epoch = _SHARED.get("logout_epoch", 0)
            if t:
                if worker is None or worker_epoch != epoch:
                    cfg = dict(base)
                    cfg.update({"central": CENTRAL, "token": t, "orgId": o,
                                "localApi": "http://127.0.0.1:" + os.environ.get("API_PORT", "9081")})
                    worker = lbw.LocalBrowserWorker(cfg)
                    worker_epoch = epoch
                    lbw.save_config(cfg)

                    def loop(my_worker=worker, my_epoch=epoch):
                        while True:
                            with _SLOCK:
                                if not _SHARED.get("token") or _SHARED.get("logout_epoch", 0) != my_epoch:
                                    log("worker 已退出登录会话")
                                    return
                            try:
                                my_worker.loop()
                            except Exception as e:
                                log("worker: %s" % e)
                                time.sleep(5)
                    threading.Thread(target=loop, name="worker", daemon=True).start()
                    log("已连接中心，客户端上线 (org=%s)" % o)
                else:
                    worker.token, worker.org_id = t, o
            else:
                worker = None
                worker_epoch = epoch
            time.sleep(2)
    threading.Thread(target=run, name="worker-mgr", daemon=True).start()


_WARMED = False


def douyin_warmup_ready():
    """Return (ready, message) for automatic Douyin warmup.

    Warmup opens a real browser search. Only run it when the current isolated
    account already has a Douyin profile and a verified login cookie cache;
    otherwise startup would show an unexplained logged-out Douyin page.
    """
    import json as _json

    acc_dir = os.environ.get("MATRIX_AGENT_DATA_DIR") or data_dir()
    profile_dir = os.environ.get("DY_PROFILE_DIR") or os.path.join(acc_dir, "dy_profile")
    if not os.path.isdir(profile_dir):
        return False, "当前账号还没有抖音登录态，已跳过预热；需要时请先到「账号矩阵」登录抖音。"

    cache_path = os.path.join(acc_dir, "auth_cookie.json")
    if not os.path.isfile(cache_path):
        return False, "当前账号缺少抖音登录缓存，已跳过预热；需要时请先到「账号矩阵」登录抖音。"

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = _json.load(f)
        cookie = str(cache.get("cookie") or "")
        has_login = bool(cache.get("hasLoginCookie")) or any(
            marker in cookie for marker in ("sessionid=", "sessionid_ss=", "sid_guard=")
        )
    except Exception:
        has_login = False
    if not has_login:
        return False, "当前账号的抖音登录态无效或已过期，已跳过预热；重新登录抖音后再搜索即可。"
    return True, "正在后台预热抖音引擎，会短暂打开浏览器搜索一次「好物推荐」。"


def warmup_engine():
    """登录后后台预热抖音/小红书浏览器引擎:提前跑一次极轻搜索,把首次冷启动(拉浏览器 + 平台
    反爬,约 2-3 分钟)吸收在登录后台;顺带验证平台登录态、暖 OS/浏览器缓存,并把结果落缓存。
    每个搜索用独立临时 profile(mkdtemp),与用户后续搜索不抢 profile 锁,互不干扰。best-effort。"""
    global _WARMED
    if _WARMED:
        return
    _WARMED = True

    def work():
        try:
            time.sleep(10)  # 等本地引擎完全起来
            base = "http://127.0.0.1:" + os.environ.get("API_PORT", "9081")
            tok = os.environ.get("MATRIX_AGENT_TOKEN", "")
            hdr = {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}
            try:
                requests.packages.urllib3.disable_warnings()
            except Exception:
                pass
            # 只暖抖音(冷启动 2-3 分钟的元凶);小红书本来就快(<10s),不必预热。
            # 抖音搜索首次拉浏览器很慢,这里在登录后台先跑一次,把冷启动吸收掉、验证登录态、
            # 暖 OS/浏览器缓存,并把结果落缓存(同关键词后续秒回)。
            try:
                ready, msg = douyin_warmup_ready()
                if not ready:
                    log("抖音预热跳过:%s" % msg)
                    if BRIDGE is not None:
                        BRIDGE.payload.emit("warmup", {"status": "skipped", "msg": msg})
                    return
                log(msg)
                if BRIDGE is not None:
                    BRIDGE.payload.emit("warmup", {"status": "starting", "msg": msg})
                requests.post(base + "/api/douyin/search", headers=hdr,
                              json={"keyword": "好物推荐", "limit": 1},
                              timeout=290, verify=True)
                msg = "抖音引擎预热完成，之后搜索、评论、采集会更快。"
                log(msg)
                if BRIDGE is not None:
                    BRIDGE.payload.emit("warmup", {"status": "done", "msg": msg})
            except Exception as e:
                msg = "抖音预热跳过，不影响使用:%s" % str(e)[:60]
                log(msg)
                if BRIDGE is not None:
                    BRIDGE.payload.emit("warmup", {"status": "error", "msg": msg})
        except Exception:
            pass
    run_bg(work)


def set_session(token, org, account=None):
    with _SLOCK:
        _SHARED["token"], _SHARED["org"] = token or "", org or "org-default"
        if account:
            _SHARED["account"] = account


def set_auth_context(payload):
    payload = payload if isinstance(payload, dict) else {}
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    role = payload.get("appRole") or payload.get("productRole") or user.get("appRole") or "normal_user"
    if role == "normal_user":
        legacy_roles = []
        for collection_name in ("memberships", "organizations"):
            collection = payload.get(collection_name)
            if isinstance(collection, list):
                legacy_roles.extend(str(item.get("role") or "").lower() for item in collection if isinstance(item, dict))
        if user.get("id") == "user-owner" or user.get("isPlatformAdmin"):
            role = "platform_admin"
        elif any(value in ("owner", "admin") for value in legacy_roles):
            role = "enterprise_admin"
    if role not in ("platform_admin", "enterprise_admin", "normal_user"):
        role = "normal_user"
    with _SLOCK:
        _SHARED["user"] = user
        _SHARED["appRole"] = role
        _SHARED["roleScope"] = payload.get("roleScope") or ("all" if role == "platform_admin" else ("org" if role == "enterprise_admin" else "self"))
        _SHARED["organizations"] = payload.get("organizations") or []
        _SHARED["memberships"] = payload.get("memberships") or []


def product_role():
    with _SLOCK:
        role = _SHARED.get("appRole") or "normal_user"
    return role if role in ("platform_admin", "enterprise_admin", "normal_user") else "normal_user"


ROLE_NAV_DENY = {
    "normal_user": {"🏢 企业中心", "👥 团队成员"},
}


def nav_allowed(name):
    return str(name or "") not in ROLE_NAV_DENY.get(product_role(), set())


def clear_session():
    with _SLOCK:
        _SHARED["token"] = ""
        _SHARED["org"] = "org-default"
        _SHARED["account"] = "default"
        _SHARED["appRole"] = "normal_user"
        _SHARED["roleScope"] = "self"
        _SHARED["user"] = {}
        _SHARED["organizations"] = []
        _SHARED["memberships"] = []
        _SHARED["logout_epoch"] = int(_SHARED.get("logout_epoch") or 0) + 1


def current_account():
    with _SLOCK:
        return _SHARED.get("account") or "default"


def current_org():
    with _SLOCK:
        return _SHARED.get("org") or "org-default"


# ---------- 计费框架(单价占位,=0 表示暂不计费,等业务方定价后填 PRICES) ----------
# 云豆单价(1 云豆 = ¥0.01,即 100 云豆 = ¥1)。数值由 lk888 真实成本(/v1/skills/usage)+ 合理加价推导:
#   能力            lk888真实成本¥   成本云豆   加价   零售云豆   ≈¥
#   product_image   0.033           3.3       3.0×   10        0.10
#   product_video   0.90            90        2.4×   220       2.20
#   copywriting     0.014           1.4       3.6×   5         0.05
#   viral_image     0.047           4.7       3.2×   15        0.15
#   digital_human   ~12(可灵std按秒0.396×~30s)  1200  1.5×  1800  18.0(真人级图生数字人)
#   digital_human_pro ~24(可灵pro 0.792×~30s)    2400  1.5×  3600  36.0
#   mix             ~0(本地ffmpeg)  0         —      10        0.10(名义价,覆盖算力/工序)
#   workflow_image  0.033           3.3       3.0×   10        0.10
#   workflow_video  9.15(vidu)      915       2.0×   1800      18.0
#   workflow_tts    0.05            5         3.0×   15        0.15
# 改价只改这里(客户端硬编码);运营方账号 user-owner 免扣。=0 即该能力不计费。
# ⚠️数字人/视频按视频时长(秒)计费,这里是"典型时长"的封顶均价;脚本越长成本越高,已在文案长度上约束。
# 2026-07-06:在原定价基础上**全部上调 40%**(×1.4,取整)。
PRICES = {
    "product_image": 14, "product_video": 308, "copywriting": 7, "viral_image": 21,
    "digital_human": 2520, "digital_human_pro": 5040, "mix": 14,
    "workflow_image": 14, "workflow_video": 2520, "workflow_tts": 21,
}


def fetch_balance():
    try:
        _c, j = api("GET", "/api/account/balance")
        if isinstance(j, dict) and j.get("ok"):
            with _SLOCK:
                _SHARED["balance"] = j.get("balance")
            return j.get("balance")
    except Exception:
        pass
    with _SLOCK:
        return _SHARED.get("balance")


def charge(amount, reason="生成", ref=""):
    """向中心服申请扣费(记账在中心)。返回 (ok, balance, error)。owner/运营方中心侧免扣。"""
    try:
        _c, j = api("POST", "/api/billing/charge", {
            "amount": amount, "reason": reason, "capability": reason, "ref": ref
        })
        if isinstance(j, dict):
            if j.get("balance") is not None:
                with _SLOCK:
                    _SHARED["balance"] = j.get("balance")
            return bool(j.get("ok")), j.get("balance"), j.get("error")
    except Exception as e:
        return False, None, str(e)[:60]
    return False, None, "charge_failed"


# 这些媒体能力已改由服务端 lk888 反代**权威扣费**(central_server.gen_price_yundou):客户端本地不再扣,
# 避免双扣;且改过的客户端绕不过(它没有 lk888 直连 key,只能走会扣费的反代)。余额不足时反代返 402,
# 由生成函数抛「余额不足」。copywriting(chat,便宜且内部也用)与 mix(本地 ffmpeg,无算力成本)仍本地扣。
_SERVER_CHARGED_CAPS = {
    "product_image", "product_video", "viral_image", "digital_human", "digital_human_pro",
    "workflow_image", "workflow_video", "workflow_tts",
}


def try_charge(cap, ref=""):
    """生成前按能力单价扣费。单价<=0 时直接放行(计费未开)。返回 (ok, error)。
    ref 建议每次生成唯一(用于失败时按 ref 精准退款)。媒体能力交给服务端反代扣,本地放行。"""
    if cap in _SERVER_CHARGED_CAPS:
        return True, None
    try:
        price = float(PRICES.get(cap, 0) or 0)
    except Exception:
        price = 0
    if price <= 0:
        return True, None
    ok, _bal, err = charge(price, reason=cap, ref=ref)
    if not ok and err == "insufficient_balance":
        return False, "余额不足,请到『账户中心』充值"
    return (ok, None) if ok else (False, err or "扣费失败")


def refund(ref=""):
    """按扣费 ref 请求中心服退款(中心侧只退真实发生过、且未退过的那一笔,防止凭空造余额)。返回 (ok, error)。"""
    if not ref:
        return True, None
    try:
        _c, j = api("POST", "/api/billing/refund", {"ref": ref})
        if isinstance(j, dict):
            if j.get("balance") is not None:
                with _SLOCK:
                    _SHARED["balance"] = j.get("balance")
            return bool(j.get("ok")), j.get("error")
    except Exception as e:
        return False, str(e)[:60]
    return False, "refund_failed"


def refund_cap(cap, ref=""):
    """生成失败时退回该能力的扣费(单价<=0 时无操作,与 try_charge 对称;计费未开时零成本)。
    媒体能力由服务端反代按 task_id 失败退款,本地不退。"""
    if cap in _SERVER_CHARGED_CAPS:
        return True, None
    try:
        price = float(PRICES.get(cap, 0) or 0)
    except Exception:
        price = 0
    if price <= 0:
        return True, None
    return refund(ref)


# ---------- central API + local task helpers ----------

def _headers():
    with _SLOCK:
        t, o = _SHARED["token"], _SHARED["org"]
    h = {"Content-Type": "application/json"}
    if t:
        h["X-Matrix-User-Token"] = t
        h["X-Matrix-Org-Id"] = o
    return h


def api(method, path, body=None, timeout=60):
    try:
        r = requests.request(method, CENTRAL + path, headers=_headers(), json=body, timeout=timeout)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}
    except Exception as e:
        return 0, {"ok": False, "error": str(e)}


def clean_accounts(accounts, platform=None, ready_only=False):
    rows = [a for a in (accounts or []) if isinstance(a, dict)]
    if platform:
        rows = [a for a in rows if (str(a.get("platform") or "douyin").strip() == platform)]
    if ready_only:
        rows = [a for a in rows if a.get("online") and a.get("cookieReady")]
    rows = sorted(rows, key=lambda a: (
        1 if a.get("online") else 0,
        1 if a.get("cookieReady") else 0,
        float(a.get("updatedAt") or a.get("lastSeen") or 0),
    ), reverse=True)
    out = []
    seen = set()
    for a in rows:
        p = str(a.get("platform") or "douyin").strip()
        identity = str(a.get("localAccountId") or a.get("handle") or a.get("name") or a.get("id") or "").strip()
        if not identity:
            identity = p
        key = (p, identity)
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def submit_local_task(ttype, payload, timeout_poll=280):
    code, j = api("POST", "/api/local-browser/task", {"type": ttype, "payload": payload or {}})
    if not (isinstance(j, dict) and j.get("ok")):
        return {"ok": False, "status": "failed", "error": (j or {}).get("error") or ("http_%s" % code)}
    tid = j.get("taskId")
    deadline = time.time() + timeout_poll
    while time.time() < deadline:
        time.sleep(2)
        _c, t = api("GET", "/api/local-browser/task?id=" + str(tid))
        if isinstance(t, dict) and t.get("status") in ("done", "failed"):
            return t
    return {"ok": False, "status": "failed", "error": "task_timeout"}


def _abs_central_url(url):
    url = str(url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://", "data:")):
        return url
    if url.startswith("/"):
        return CENTRAL + url
    return CENTRAL + "/" + url


def _first_uploaded_material_url(j):
    j = j or {}
    public_urls = j.get("publicUrls") or ((j.get("material") or {}).get("publicUrls") if isinstance(j.get("material"), dict) else None) or []
    if public_urls:
        return _abs_central_url(public_urls[0])
    urls = j.get("urls") or ((j.get("material") or {}).get("urls") if isinstance(j.get("material"), dict) else None) or []
    if urls:
        return _abs_central_url(urls[0])
    mid = str(j.get("id") or "").strip()
    if not mid:
        return ""
    try:
        _c, lib = api("GET", "/api/library")
        rows = lib if isinstance(lib, list) else ((lib or {}).get("value") or (lib or {}).get("items") or [])
        for m in rows:
            if isinstance(m, dict) and str(m.get("id") or "") == mid:
                public_urls = m.get("publicUrls") or []
                if public_urls:
                    return _abs_central_url(public_urls[0])
                urls = m.get("urls") or []
                if urls:
                    return _abs_central_url(urls[0])
    except Exception:
        pass
    return ""


def _upload_env_value(name):
    value = str(os.getenv(name) or "").strip()
    if value:
        return value
    for env_path in (
        os.path.join(os.path.dirname(__file__), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
    ):
        try:
            if not os.path.isfile(env_path):
                continue
            with open(env_path, encoding="utf-8") as fh:
                for line in fh:
                    raw = line.strip()
                    if not raw or raw.startswith("#") or "=" not in raw:
                        continue
                    key, val = raw.split("=", 1)
                    if key.strip() == name:
                        return val.strip().strip('"').strip("'")
        except Exception:
            continue
    return ""


def _external_image_upload_config():
    api_url = _upload_env_value("UPLOAD_API_URL").rstrip("/")
    token = _upload_env_value("UPLOAD_TOKEN")
    base_url = (_upload_env_value("PUBLIC_UPLOAD_BASE_URL") or _upload_env_value("PUBLIC_IMAGE_BASE_URL")).rstrip("/")
    if not (api_url and token):
        return {}
    return {"api_url": api_url, "token": token, "base_url": base_url}


def _extract_external_upload_url(payload, base_url=""):
    payload = payload or {}
    candidates = [
        payload.get("url"),
        payload.get("publicUrl"),
        payload.get("public_url"),
        payload.get("imageUrl"),
        payload.get("image_url"),
        payload.get("fileUrl"),
        payload.get("file_url"),
        payload.get("path"),
        payload.get("filename"),
    ]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.extend([
            data.get("url"),
            data.get("publicUrl"),
            data.get("public_url"),
            data.get("imageUrl"),
            data.get("image_url"),
            data.get("fileUrl"),
            data.get("file_url"),
            data.get("path"),
            data.get("filename"),
        ])
    for value in candidates:
        value = str(value or "").strip()
        if not value:
            continue
        if value.startswith(("http://", "https://")):
            return value
        if base_url:
            return base_url + "/" + value.lstrip("/")
    return ""


def upload_public_media_url(path, title="", mtype="image"):
    cfg = _external_image_upload_config()
    if not cfg:
        return "", {}
    if not (path and os.path.isfile(path)):
        raise RuntimeError("公网素材上传失败:本地文件不存在")
    media_type = str(mtype or "").strip().lower() or "image"
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    headers = {"Authorization": "Bearer " + cfg["token"]}
    with open(path, "rb") as fh:
        files = {"file": (os.path.basename(path), fh, mime)}
        data = {"title": title or os.path.basename(path), "type": media_type}
        timeout = 600 if media_type == "video" else 120
        r = requests.post(cfg["api_url"], headers=headers, files=files, data=data, timeout=timeout)
    try:
        payload = r.json()
    except Exception:
        payload = {}
    if not (200 <= int(getattr(r, "status_code", 0) or 0) < 300):
        raise RuntimeError("公网素材上传失败:%s" % str(payload.get("error") or getattr(r, "status_code", ""))[:120])
    url = _extract_external_upload_url(payload, cfg.get("base_url") or "")
    if not _is_remote_fetchable_media_url(url):
        raise RuntimeError("公网素材上传成功但未拿到可远程访问URL")
    result = dict(payload)
    source = "external_image_upload" if media_type == "image" else "external_media_upload"
    result.update({"ok": True, "source": source, "publicUrls": [url]})
    return url, result


def upload_public_image_url(path, title=""):
    return upload_public_media_url(path, title, "image")


def upload_materials(paths, title, mtype="video"):
    """Multipart upload files to central library. Returns (status, json)."""
    with _SLOCK:
        t, o = _SHARED["token"], _SHARED["org"]
    h = {}
    if t:
        h["X-Matrix-User-Token"] = t
        h["X-Matrix-Org-Id"] = o
    files = []
    handles = []
    try:
        for p in paths:
            fh = open(p, "rb")
            handles.append(fh)
            files.append(("files", (os.path.basename(p), fh, "application/octet-stream")))
        data = {"title": title or (os.path.basename(paths[0]) if paths else "素材"), "type": mtype or "video", "orgId": o}
        r = requests.post(CENTRAL + "/api/library/upload", headers=h, data=data, files=files, timeout=600)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}
    finally:
        for fh in handles:
            try:
                fh.close()
            except Exception:
                pass


def upload_asset_url(path, title, mtype):
    media_type = str(mtype or "").lower()
    if media_type in ("image", "video", "audio") and _external_image_upload_config():
        return upload_public_media_url(path, title, media_type)
    code, j = upload_materials([path], title, mtype=mtype)
    if not (200 <= int(code or 0) < 300 and isinstance(j, dict) and j.get("ok")):
        raise RuntimeError("上传失败:%s" % str((j or {}).get("error") or code))
    url = _first_uploaded_material_url(j)
    if not url:
        raise RuntimeError("上传成功但未拿到素材公网URL")
    return url, j


def kb_upload_files(paths, title, ktype):
    """Multipart 上传文档到企业知识库 /api/kb/upload(自动解码文本并分块入库)。返回 (status, json)。"""
    with _SLOCK:
        t, o = _SHARED["token"], _SHARED["org"]
    h = {}
    if t:
        h["X-Matrix-User-Token"] = t
        h["X-Matrix-Org-Id"] = o
    files = []
    handles = []
    try:
        for p in paths:
            fh = open(p, "rb")
            handles.append(fh)
            files.append(("files", (os.path.basename(p), fh, "application/octet-stream")))
        data = {"title": title or "", "type": ktype or "company", "orgId": o}
        r = requests.post(CENTRAL + "/api/kb/upload", headers=h, data=data, files=files, timeout=300)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}
    finally:
        for fh in handles:
            try:
                fh.close()
            except Exception:
                pass


def kb_context(query, limit=3):
    """检索企业知识库(/api/kb/ask),返回可注入 LLM prompt 的真实产品知识片段;无命中返回空串。
    用于让软文/工作流生成时优先采用知识库里的真实卖点/价格/政策,而不是编造。"""
    try:
        _c, j = api("POST", "/api/kb/ask", {"query": query, "limit": limit})
        srcs = (j or {}).get("sources") if isinstance(j, dict) else None
        if not srcs:
            return ""
        lines = []
        seen = set()
        for s in srcs[:limit]:
            txt = (s.get("text") or "").strip().replace("\n", " ")
            key = txt[:40]
            if txt and key not in seen:
                seen.add(key)
                lines.append("- 【%s】%s" % (s.get("title") or "资料", txt[:240]))
        if not lines:
            return ""
        return ("\n\n【企业知识库·真实产品资料,务必优先采用下列信息,不要编造卖点/价格/政策】\n" + "\n".join(lines))
    except Exception:
        return ""


def run_bg(fn):
    threading.Thread(target=fn, daemon=True).start()


def lk888_config():
    """lk888 网关配置。**默认走中心服反代**(CENTRAL/lk888):分发的客户端不用内置 key、也不用翻墙代理
    (中心服直连 lk888、注入真 key)。若本机有 %APPDATA%\\MatrixShipAgent\\lk888.json 且带 api_key
    (开发/直连模式),则用它直连。"""
    import json as _json
    p = os.path.join(data_dir(), "lk888.json")
    direct = None
    try:
        if os.path.isfile(p):
            d = _json.load(open(p, encoding="utf-8-sig"))
            if isinstance(d, dict) and d.get("api_key") and d.get("base_url"):
                direct = dict(d)
    except Exception as e:
        log("lk888 config: %s" % e)
    if direct is not None:
        direct["base_url"] = validate_service_url(direct.get("base_url")).rstrip("/")
        return direct  # 本地直连(运营方自己有 key + 代理)
    with _SLOCK:
        tok = _SHARED.get("token") or ""
    return {"base_url": CENTRAL + "/lk888", "api_key": tok, "proxy": None}


def _lk_proxies(cfg=None):
    """api.lk888.ai 海外域名,部分网络需走本机 v2rayN 代理(lk888.json 的 proxy 字段);
    只作用于 lk888 API 调用,不影响 central / 抖音小红书浏览器(保住住宅 IP)。"""
    p = ((cfg or lk888_config()) or {}).get("proxy")
    return {"http": p, "https": p} if p else None


def lk888_chat(prompt, system=None, model=None, max_tokens=1200, temperature=0.9):
    """同步调用 lk888 LLM(OpenAI 兼容 /v1/chat/completions),返回文本。在 bg 线程里用。"""
    cfg = lk888_config()
    base = (cfg.get("base_url") or "").rstrip("/")
    key = cfg.get("api_key") or ""
    if not base or not key:
        raise RuntimeError("未配置 lk888(缺 lk888.json)")
    try:
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    hdr = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    tried = []
    last_err = ""
    for mdl in [model or cfg.get("llm_model") or "deepseek-v4-flash", cfg.get("llm_model_fallback") or "gpt-5.4-mini"]:
        if not mdl or mdl in tried:
            continue
        tried.append(mdl)
        try:
            r = requests.post(base + "/v1/chat/completions", headers=hdr,
                              json={"model": mdl, "messages": msgs, "max_tokens": max_tokens, "temperature": temperature},
                              timeout=90, verify=True, proxies=_lk_proxies(cfg))
            if r.status_code == 200:
                txt = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
                if txt:
                    return txt
                last_err = "空响应"
            else:
                try:
                    last_err = ((r.json().get("error") or {}).get("message")) or r.text[:140]
                except Exception:
                    last_err = r.text[:140]
        except Exception as e:
            last_err = str(e)[:140]
    raise RuntimeError(last_err or ("LLM 生成失败(模型 %s)" % "/".join(tried)))


def lk888_image_result(prompt, size="1024x1024", model=None, image_urls=None):
    """Return generated image bytes and the upstream public URL when available."""
    cfg = lk888_config()
    base = (cfg.get("base_url") or "").rstrip("/")
    key = cfg.get("api_key") or ""
    mdl = model or cfg.get("image_model") or "gpt-image-2"
    if not base or not key:
        raise RuntimeError("未配置 lk888(缺 lk888.json)")
    try:
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass
    body = {"model": mdl, "prompt": prompt, "n": 1, "size": size}
    if image_urls:
        refs = [str(url).strip() for url in image_urls if str(url or "").strip()]
        if not refs:
            raise RuntimeError("lk888_image_reference_images_missing")
        body["image_urls"] = refs
        logged_fields = ["image_urls"]
        if all(_is_remote_fetchable_media_url(ref) for ref in refs):
            body["images"] = refs
            body["reference_images"] = refs
            body["referenceImages"] = refs
            body["params"] = {"images": refs, "image_urls": refs, "reference_images": refs}
            logged_fields.extend(["images", "reference_images", "referenceImages", "params.images"])
        try:
            json_log(
                _CLIENT_JSON_LOGGER,
                "lk888_image_reference_payload",
                code="lk888_image_reference_payload",
                model=mdl,
                reference_count=len(refs),
                fields=logged_fields,
            )
        except Exception:
            pass
    try:
        image_timeout = max(60, int(os.getenv("LK888_IMAGE_TIMEOUT_SEC", "540") or 540))
    except Exception:
        image_timeout = 540
    try:
        r = requests.post(base + "/v1/images/generations",
                          headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                          json=body, timeout=image_timeout, verify=True, proxies=_lk_proxies(cfg))
    except requests.exceptions.ReadTimeout:
        raise RuntimeError("图片生成超时:上游模型超过 9 分钟未返回,请稍后重试或改用 1024x1024/更快模型")
    if r.status_code != 200:
        raise RuntimeError("图片生成 %s: %s" % (r.status_code, r.text[:100]))
    item = (r.json().get("data") or [{}])[0]
    if item.get("url"):
        public_url = str(item.get("url") or "").strip()
        if not _is_remote_fetchable_media_url(public_url):
            raise RuntimeError("image_result_url_not_public")
        return requests.get(public_url, timeout=120, verify=True).content, public_url
    if item.get("b64_json"):
        import base64 as _b64
        return _b64.b64decode(item["b64_json"]), ""
    raise RuntimeError("图片响应缺 url/b64")


def lk888_image(prompt, size="1024x1024", model=None, image_urls=None):
    """同步调用 lk888 图片生成并返回图片 bytes。"""
    image_bytes, _public_url = lk888_image_result(
        prompt, size=size, model=model, image_urls=image_urls)
    return image_bytes


def lk888_image_url(prompt, size="1024x1024", model=None):
    """图片生成但返回公网 URL(用于喂给数字人/视频参考)。"""
    cfg = lk888_config()
    base = (cfg.get("base_url") or "").rstrip("/")
    key = cfg.get("api_key") or ""
    mdl = model or cfg.get("image_model") or "gpt-image-2"
    if not base or not key:
        raise RuntimeError("未配置 lk888")
    try:
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass
    r = requests.post(base + "/v1/images/generations",
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                      json={"model": mdl, "prompt": prompt, "n": 1, "size": size}, timeout=150, verify=True, proxies=_lk_proxies(cfg))
    if r.status_code != 200:
        raise RuntimeError("头像生成 %s: %s" % (r.status_code, r.text[:80]))
    return ((r.json().get("data") or [{}])[0]).get("url") or ""


def lk888_image_data_url(prompt, size="1024x1024", model=None):
    """生成图片并转成 data URL(gpt-image-2 常返回 b64,数字人头像用它)。"""
    import base64 as _b64
    b = lk888_image(prompt, size=size, model=model)
    mime = "image/png" if b[:4] == b"\x89PNG" else "image/jpeg"
    return "data:%s;base64,%s" % (mime, _b64.b64encode(b).decode("ascii"))


def _extract_lk888_media_url(obj, exts):
    """Extract generated media URL from LK888 task status, including signed URLs without file suffix."""
    import re
    want = tuple("." + str(x).lower().lstrip(".") for x in (exts or []) if x)
    preferred_keys = (
        "video_url", "videoUrl", "output_url", "outputUrl", "result_url", "resultUrl",
        "download_url", "downloadUrl", "file_url", "fileUrl", "media_url", "mediaUrl",
        "audio_url", "audioUrl", "image_url", "imageUrl", "url",
    )
    url_re = re.compile(r"^https?://", re.I)

    def has_wanted_suffix(url):
        low = str(url or "").lower().split("?", 1)[0]
        return bool(want and low.endswith(want))

    def walk(value, key_hint=""):
        if isinstance(value, dict):
            for key in preferred_keys:
                if key in value:
                    found = walk(value.get(key), key)
                    if found:
                        return found
            for key, child in value.items():
                found = walk(child, str(key))
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child, key_hint)
                if found:
                    return found
        elif isinstance(value, str) and url_re.match(value):
            if has_wanted_suffix(value):
                return value
            hint = key_hint.lower()
            if any(k in hint for k in ("video", "audio", "image", "media", "output", "result", "download", "file")):
                return value
        return ""

    return walk(obj)


def _lk888_task_status_summary(obj):
    if not isinstance(obj, dict):
        return "empty_status"
    data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
    status = str(data.get("status") or obj.get("status") or "").strip()
    msg = str(data.get("message") or data.get("error") or obj.get("message") or obj.get("error") or "").strip()
    bits = []
    if status:
        bits.append("status=" + status[:40])
    if msg:
        bits.append("message=" + msg[:100])
    return "; ".join(bits) or "status_unknown"


def _lk888_task_failed(obj):
    if not isinstance(obj, dict):
        return False
    data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
    st = str(data.get("status") or obj.get("status") or "").lower().strip()
    return st in (
        "failed", "error", "fail", "timeout", "cancelled", "canceled",
        "错误", "失败", "超时", "已取消", "取消",
    )


def lk888_media_task(model, payload, exts, progress=None, tries=110, cancel_check=None):
    """通用 lk888 异步媒体生成:POST /v1/media/generate → 轮询 /v1/skills/task-status → 结果 URL。
    exts=文件后缀列表(如 ['mp4'] / ['mp3','wav']);progress(i) 每轮回调。"""
    cfg = lk888_config()
    base = (cfg.get("base_url") or "").rstrip("/")
    key = cfg.get("api_key") or ""
    if not base or not key:
        raise RuntimeError("未配置 lk888(缺 lk888.json)")
    try:
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass
    hdr = {"Authorization": "Bearer " + key, "Accept": "application/json", "Content-Type": "application/json"}
    r = requests.post(base + "/v1/media/generate", headers=hdr, json=dict(payload, model=model), timeout=60, verify=True, proxies=_lk_proxies(cfg))
    if r.status_code == 402:  # 服务端反代:云豆余额不足
        try:
            _m = (r.json() or {}).get("message") or (r.json() or {}).get("error")
        except Exception:
            _m = ""
        raise RuntimeError(_m or "云豆余额不足,请到『账户中心』充值后再生成")
    d = r.json() if r.ok else {}
    data = d.get("data") or {}
    task = data.get("task_id") or (data.get("task_ids") or [None])[0] or d.get("task_id")
    if not task:
        raise RuntimeError("%s 未拿到任务ID:%s" % (model, (r.text or "")[:80]))
    last_summary = "not_polled"
    for i in range(tries):
        if callable(cancel_check) and cancel_check():
            raise RuntimeError("lk888_task_cancelled")
        time.sleep(4)
        if callable(cancel_check) and cancel_check():
            raise RuntimeError("lk888_task_cancelled")
        status_obj = {}
        try:
            rs = requests.get(base + "/v1/skills/task-status", headers=hdr, params={"task_id": task}, timeout=30, verify=True, proxies=_lk_proxies(cfg))
            status_obj = rs.json() if rs.status_code == 200 else {}
        except Exception:
            status_obj = {}
        if callable(progress):
            progress(i)
        if callable(cancel_check) and cancel_check():
            raise RuntimeError("lk888_task_cancelled")
        last_summary = _lk888_task_status_summary(status_obj)
        url = _extract_lk888_media_url(status_obj, exts)
        if url:
            return url
        if _lk888_task_failed(status_obj):
            raise RuntimeError("%s 生成失败:%s" % (model, last_summary))
    raise RuntimeError("%s 生成超时(task_id=%s,%s)" % (model, task, last_summary))


def _lk888_media_task_with_cancel(model, payload, exts, progress=None, tries=110, cancel_check=None):
    try:
        return lk888_media_task(model, payload, exts, progress=progress, tries=tries, cancel_check=cancel_check)
    except TypeError as exc:
        if "cancel_check" not in str(exc):
            raise
        return lk888_media_task(model, payload, exts, progress=progress, tries=tries)


def lk888_media_task_multipart(model, files, data, exts, progress=None, tries=110):
    """multipart 版异步媒体生成:上传文件(如数字人头像 image=type=upload)+ 其它字段。"""
    cfg = lk888_config()
    base = (cfg.get("base_url") or "").rstrip("/")
    key = cfg.get("api_key") or ""
    if not base or not key:
        raise RuntimeError("未配置 lk888")
    try:
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass
    auth = {"Authorization": "Bearer " + key}
    r = requests.post(base + "/v1/media/generate", headers=auth, files=files,
                      data=dict(data, model=model), timeout=90, verify=True, proxies=_lk_proxies(cfg))
    d = r.json() if r.ok else {}
    dd = d.get("data") or {}
    task = dd.get("task_id") or (dd.get("task_ids") or [None])[0] or d.get("task_id")
    if not task:
        raise RuntimeError("%s 未拿到任务ID:%s" % (model, (r.text or "")[:80]))
    jh = dict(auth, **{"Accept": "application/json"})
    last_summary = "not_polled"
    for i in range(tries):
        time.sleep(4)
        status_obj = {}
        try:
            status_obj = requests.get(base + "/v1/skills/task-status", headers=jh,
                                      params={"task_id": task}, timeout=30, verify=True, proxies=_lk_proxies(cfg)).json()
        except Exception:
            status_obj = {}
        if callable(progress):
            progress(i)
        last_summary = _lk888_task_status_summary(status_obj)
        url = _extract_lk888_media_url(status_obj, exts)
        if url:
            return url
        if _lk888_task_failed(status_obj):
            raise RuntimeError("%s 生成失败:%s" % (model, last_summary))
    raise RuntimeError("%s 生成超时(task_id=%s,%s)" % (model, task, last_summary))


def lk888_tts(text, emotion="happy", progress=None):
    """文案 → 语音(doubao-tts-2.0),返回公网 mp3 URL。"""
    return lk888_media_task("doubao-tts-2.0", {"prompt": text, "format": "mp3", "emotion": emotion},
                            ["mp3", "wav", "ogg"], progress=progress)


def lk888_vision(prompt, media_urls=None, model="gemini-3.1-pro-preview", max_tokens=1500):
    """多模态理解:把图片/视频公网 URL 喂给多模态模型(gemini),返回文字分析。
    ⚠️ lk888 无“千问3.7Max”,用 gemini-3.1-pro-preview 做图像/视频理解。"""
    cfg = lk888_config()
    base = (cfg.get("base_url") or "").rstrip("/")
    key = cfg.get("api_key") or ""
    if not base or not key:
        raise RuntimeError("未配置 lk888")
    try:
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass
    content = [{"type": "text", "text": prompt}]
    for u in (media_urls or []):
        low = str(u).split("?")[0].lower()
        if low.endswith((".mp4", ".mov", ".webm", ".m4v")):
            content.append({"type": "video_url", "video_url": {"url": u}})
        else:
            content.append({"type": "image_url", "image_url": {"url": u}})
    r = requests.post(base + "/v1/chat/completions",
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                      json={"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens},
                      timeout=150, verify=True, proxies=_lk_proxies(cfg))
    if r.status_code != 200:
        try:
            raise RuntimeError((r.json().get("error") or {}).get("message") or r.text[:140])
        except Exception:
            raise RuntimeError(r.text[:140])
    return ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()


_LK888_MODEL_CACHE = {"ts": 0.0, "rows": []}
_LK888_MODEL_CACHE_TTL = 300.0
_LK888_FALLBACK_MODELS = [
    {"name": "gpt-image-2", "display_name": "GPT Image 2", "type": "image"},
    {"name": "gpt-image-2-guan", "display_name": "GPT Image 2 Official", "type": "image"},
    {"name": "gemini-3-pro-image-preview", "display_name": "Nano Banana Pro", "type": "image"},
    {"name": "gemini-3.1-flash-image-preview", "display_name": "Nano Banana 2", "type": "image"},
    {"name": "doubao-seedream-5-0-260128", "display_name": "Seedream 5.0", "type": "image"},
    {"name": "doubao-seedream-4-5-251128", "display_name": "Seedream 4.5", "type": "image"},
    {"name": "mj_imagine", "display_name": "Midjourney", "type": "image"},
    {"name": "qwen-image", "display_name": "Qwen-image-max", "type": "image"},
    {"name": "wan2.7-image", "display_name": "Wanxiang 2.7 Image", "type": "image"},
    {"name": "wan2.6-image", "display_name": "Wanxiang 2.6 Image", "type": "image"},
    {"name": "vidu-image-2", "display_name": "VIDU Image 2", "type": "image"},
    {"name": "kling-v3", "display_name": "Kling-V3", "type": "image"},
    {"name": "kling-v3-omni", "display_name": "Kling-V3-Omni", "type": "image"},
    {"name": "kling-image-o1", "display_name": "Kling o1", "type": "image"},
    {"name": "doubao-seedance-1-5-pro-251215", "display_name": "Seedance 1.5 Pro", "type": "video"},
    {"name": "viduq3", "display_name": "Vidu Q3", "type": "video"},
    {"name": "viduq3-turbo", "display_name": "Vidu Q3 Turbo", "type": "video"},
    {"name": "vidu-jieshuoman", "display_name": "VIDU Narrated Comic", "type": "video"},
    {"name": "kling-v3-video", "display_name": "Kling-V3-video", "type": "video"},
    {"name": "kling-v2-6", "display_name": "Kling 2.6 Pro", "type": "video"},
    {"name": "kling-avatar-image2video", "display_name": "Kling Digital Human", "type": "video"},
    {"name": "veo3.1", "display_name": "Veo 3.1", "type": "video"},
    {"name": "sora-2", "display_name": "Sora-2 Official", "type": "video"},
    {"name": "grok-video-3", "display_name": "grok-video-3", "type": "video"},
    {"name": "happyhorse-t2v", "display_name": "HappyHorse Text-to-video", "type": "video"},
    {"name": "happyhorse-i2v", "display_name": "HappyHorse First Frame", "type": "video"},
    {"name": "hailuo-2.3", "display_name": "Hailuo 2.3", "type": "video"},
    {"name": "wan2.7-cankaosheng", "display_name": "Wanxiang 2.7 Reference-to-Video", "type": "video"},
    {"name": "wan2.7-shouweizhen", "display_name": "Wanxiang 2.7 First/Last Frames", "type": "video"},
]

_LK888_IMAGE_DEFAULT = "gpt-image-2"
_LK888_VIDEO_DEFAULT = "doubao-seedance-1-5-pro-251215"
AGENT_VIDEO_DURATIONS = (5, 10)

def _agent_video_duration(value):
    try:
        duration = int(float(value))
    except (TypeError, ValueError):
        duration = AGENT_VIDEO_DURATIONS[0]
    return duration if duration in AGENT_VIDEO_DURATIONS else AGENT_VIDEO_DURATIONS[0]


_LK888_REPLACEMENT_VIDEO_DEFAULT = "viduq3-turbo-cankaosheng"
_LK888_PRINCIPAL_VIDEO_MODEL = "happyhorse-video-edit"
_LK888_REPLACEMENT_REFERENCE_VIDEO_MODELS = frozenset((
    "kwvideo-v2-quannengcankao",
    "viduq3-turbo-cankaosheng",
    "viduq3-cankaosheng",
    "viduq2-cankaosheng",
    "wan2.7-cankaosheng",
    "happyhorse-r2v",
    "happyhorse-1.1-r2v",
))
_LK888_REPLACEMENT_BUILTIN_SELECTABLE_MODELS = (
    "kwvideo-v2-quannengcankao",
)
_LK888_REPLACEMENT_MODEL_FALLBACKS = (
    "viduq3-turbo-cankaosheng",
    "wan2.7-cankaosheng",
    "viduq3-cankaosheng",
    "viduq2-cankaosheng",
    "happyhorse-r2v",
    "happyhorse-1.1-r2v",
)
_LK888_REPLACEMENT_MODEL_LABELS = {
    "happyhorse-video-edit": "HappyHorse Video Edit",
    "kwvideo-v2-quannengcankao": "SD 2.0 全能参考",
    "viduq3-turbo-cankaosheng": "Vidu Q3 Turbo 参考生视频",
    "wan2.7-cankaosheng": "万相 2.7 参考生视频",
    "viduq3-cankaosheng": "Vidu Q3 参考生视频",
    "viduq2-cankaosheng": "Vidu Q2 参考生视频",
    "happyhorse-r2v": "HappyHorse 参考视频",
    "happyhorse-1.1-r2v": "HappyHorse 1.1 参考视频",
}


def _principal_replacement_enabled(job=None):
    job = job or {}
    if not _env_enabled("VIDEO_REPLACE_PRINCIPAL_REPLACEMENT", "1"):
        return False
    if _replacement_no_person_mode(job):
        return False
    return str(job.get("principalReplacementMode") or "").strip() == "source_video_edit"


def _replacement_row_name(row):
    return str((row or {}).get("name") or "").strip()


def _replacement_row_label(row):
    row = row or {}
    name = _replacement_row_name(row)
    return str(row.get("display_name") or row.get("displayName") or _LK888_REPLACEMENT_MODEL_LABELS.get(name) or name).strip()


def _replacement_is_sd20_all_reference_row(row):
    row = row or {}
    if str(row.get("type") or "").strip().lower() != "video":
        return False
    text = ("%s %s" % (_replacement_row_name(row), _replacement_row_label(row))).lower()
    compact = "".join(ch for ch in text if ch.isalnum())
    has_sd20 = (
        "sd20" in compact
        or "seedance20" in compact
        or "sd 2.0" in text
        or "seedance 2.0" in text
    )
    has_reference = (
        "全能参考" in text
        or "参考" in text
        or "reference" in text
        or "ref" in text
        or "omni" in text
        or "all" in text
    )
    return bool(has_sd20 and has_reference)


def _replacement_configured_model_is_allowed(name):
    name = str(name or "").strip()
    if not name:
        return False
    if name == _LK888_PRINCIPAL_VIDEO_MODEL:
        return True
    if name in _LK888_REPLACEMENT_REFERENCE_VIDEO_MODELS:
        return True
    compact = "".join(ch for ch in name.lower() if ch.isalnum())
    lower = name.lower()
    return bool(("sd20" in compact or "seedance20" in compact) and ("reference" in lower or "ref" in lower or "all" in lower))


def _replacement_supported_model_rows(rows=None):
    catalog = [dict(row) for row in (rows if rows is not None else _lk888_skill_models()) if isinstance(row, dict)]
    by_name = {}
    for row in catalog:
        name = _replacement_row_name(row)
        if name and str(row.get("type") or "").strip().lower() == "video":
            by_name[name] = dict(row)
    ordered = []
    for name in (_LK888_PRINCIPAL_VIDEO_MODEL,) + _LK888_REPLACEMENT_BUILTIN_SELECTABLE_MODELS:
        row = dict(by_name.get(name) or {
            "name": name,
            "display_name": _LK888_REPLACEMENT_MODEL_LABELS.get(name, name),
            "type": "video",
        })
        ordered.append(row)
    for row in catalog:
        if _replacement_is_sd20_all_reference_row(row):
            ordered.append(dict(row))
    for name in _LK888_REPLACEMENT_MODEL_FALLBACKS:
        row = dict(by_name.get(name) or {
            "name": name,
            "display_name": _LK888_REPLACEMENT_MODEL_LABELS.get(name, name),
            "type": "video",
        })
        ordered.append(row)
    seen = set()
    out = []
    for row in ordered:
        name = _replacement_row_name(row)
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(row)
    return out


def _principal_replacement_model(job=None):
    configured = str((job or {}).get("model") or "").strip()
    if configured:
        return configured
    return str(os.getenv("VIDEO_REPLACE_PRINCIPAL_MODEL", _LK888_PRINCIPAL_VIDEO_MODEL) or _LK888_PRINCIPAL_VIDEO_MODEL).strip()


def _principal_video_edit_unavailable(exc):
    text = str(exc or "").strip().lower()
    return any(token in text for token in (
        "model_not_found", "model not found", "unsupported model", "model unavailable",
        "模型不存在", "模型不可用", "不支持该模型", "unknown model",
    ))


def _replacement_model_candidates(job=None):
    job = job or {}
    if _principal_replacement_enabled(job):
        return [_principal_replacement_model(job)]
    configured = str(job.get("model") or "").strip()
    if str(job.get("principalReplacementMode") or "").strip() == "source_video_edit":
        configured = ""
    candidates = []
    if configured:
        if not _replacement_configured_model_is_allowed(configured):
            raise RuntimeError(
                "当前视频模型不支持参考图同款替换，请使用 %s；文生视频模型不能保证保留上传的人物和产品"
                % _LK888_REPLACEMENT_VIDEO_DEFAULT
            )
        candidates.append(configured)
    candidates.extend(_LK888_REPLACEMENT_MODEL_FALLBACKS)
    return list(dict.fromkeys(candidates))


def _lk888_skill_models(force=False):
    now_ts = time.time()
    if not force and _LK888_MODEL_CACHE.get("rows") and now_ts - float(_LK888_MODEL_CACHE.get("ts") or 0) < _LK888_MODEL_CACHE_TTL:
        return list(_LK888_MODEL_CACHE.get("rows") or [])
    rows = []
    try:
        _c, j = api("GET", "/lk888/v1/skills/models", timeout=90)
        vals = (j or {}).get("models") or []
        if isinstance(vals, list):
            for row in vals:
                if not isinstance(row, dict):
                    continue
                if row.get("available_for_this_key") is False:
                    continue
                rows.append(dict(row))
    except Exception as e:
        log("lk888 model list: %s" % e)
    if not rows:
        rows = [dict(x) for x in _LK888_FALLBACK_MODELS]
    _LK888_MODEL_CACHE["ts"] = now_ts
    _LK888_MODEL_CACHE["rows"] = list(rows)
    return rows


def _lk888_model_label(name, rows=None):
    name = str(name or "").strip()
    if not name:
        return ""
    for row in (rows or _lk888_skill_models()):
        if str(row.get("name") or "") == name:
            return str(row.get("display_name") or row.get("name") or name)
    return name


def _lk888_model_family(row):
    name = str((row or {}).get("name") or "").lower()
    disp = str((row or {}).get("display_name") or "").lower()
    text = name + " " + disp
    if "gpt" in text:
        return "OpenAI / GPT"
    if "gemini" in text or "banana" in text:
        return "Gemini"
    if "seedream" in text or "seedance" in text:
        return "豆包 / Seed"
    if "kling" in text:
        return "Kling"
    if "vidu" in text:
        return "VIDU"
    if "happyhorse" in text:
        return "HappyHorse"
    if "wan" in text or "wanxiang" in text:
        return "万象"
    if "pix" in text:
        return "PixVerse"
    if "omni" in text:
        return "Omni"
    if "grok" in text:
        return "Grok"
    if "sora" in text:
        return "Sora"
    if "veo" in text:
        return "Veo"
    if "hailuo" in text:
        return "Hailuo"
    if "midjourney" in text or "mj_" in text:
        return "Midjourney"
    if "qwen" in text:
        return "Qwen"
    return "其他"


def _lk888_models_by_type(kind):
    rows = []
    for row in _lk888_skill_models():
        rtype = str((row or {}).get("type") or "").strip().lower()
        if kind == "image" and rtype == "image":
            rows.append(row)
        elif kind == "video" and rtype == "video":
            rows.append(row)
    seen = set()
    out = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(row)
    out.sort(key=lambda row: (_lk888_model_family(row), str(row.get("display_name") or row.get("name") or "").lower()))
    return out


def _lk888_grouped_models(kind):
    groups = {}
    order = []
    for row in _lk888_models_by_type(kind):
        fam = _lk888_model_family(row)
        if fam not in groups:
            groups[fam] = []
            order.append(fam)
        groups[fam].append(row)
    return [(fam, groups.get(fam) or []) for fam in order]


class VideoPlayerBox(QtWidgets.QFrame):
    """可复用视频播放框(QGraphicsVideoItem,非原生可叠加;数字人预览带声音)。"""

    def __init__(self, w=380, h=380):
        super().__init__()
        self.setObjectName("card")
        self.setFixedSize(w, h)
        self.player = None
        self.audio = None
        self.item = None
        self.current_path = None
        self.scene = QtWidgets.QGraphicsScene(self)
        self.view = QtWidgets.QGraphicsView(self.scene, self)
        self.view.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.view.setStyleSheet("background:transparent;border:0;")
        self.view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.view.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.view.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self._bg = self.scene.addRect(0, 0, 10, 10, QtGui.QPen(QtCore.Qt.NoPen))
        self._bg.setBrush(QtGui.QColor("#0a0c14"))
        self.hint = QtWidgets.QLabel("🧑‍💼\n数字人视频", self)
        self.hint.setAlignment(QtCore.Qt.AlignCenter)
        self.hint.setStyleSheet("color:#6f7aa0;font-size:14px;background:transparent;")

    def resizeEvent(self, e):
        r = self.rect()
        self.view.setGeometry(0, 0, r.width(), r.height())
        self.hint.setGeometry(0, 0, r.width(), r.height())
        self.scene.setSceneRect(0, 0, r.width(), r.height())
        self._bg.setRect(0, 0, r.width(), r.height())
        if self.item is not None:
            self._fit()
        super().resizeEvent(e)

    def _fit(self):
        vs = self.item.nativeSize()
        w, h = self.width(), self.height()
        if vs.isValid() and vs.width() > 0 and vs.height() > 0:
            sc = max(w / vs.width(), h / vs.height())
            nw, nh = vs.width() * sc, vs.height() * sc
            self.item.setSize(QtCore.QSizeF(nw, nh))
            self.item.setPos((w - nw) / 2.0, (h - nh) / 2.0)
        else:
            self.item.setSize(QtCore.QSizeF(w, h))
            self.item.setPos(0, 0)

    def play(self, path):
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
            self.hint.hide()
            if self.item is None:
                self.item = QGraphicsVideoItem()
                self.scene.addItem(self.item)
                self.player = QMediaPlayer(self)
                self.audio = QAudioOutput(self)
                self.player.setAudioOutput(self.audio)
                self.player.setVideoOutput(self.item)
                try:
                    self.player.setLoops(QMediaPlayer.Loops.Infinite)
                except Exception:
                    pass
                self.item.nativeSizeChanged.connect(lambda _s: self._fit())
            self.player.stop()
            self.current_path = path
            self.player.setSource(QtCore.QUrl.fromLocalFile(path))
            self.player.play()
            return True
        except Exception:
            self.current_path = None
            self.hint.setText("视频组件不可用")
            self.hint.show()
            return False

    def is_playing(self):
        if self.player is None:
            return False
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            enum = getattr(QMediaPlayer, "PlaybackState", QMediaPlayer)
            playing = getattr(enum, "PlayingState", None) or getattr(QMediaPlayer, "PlayingState", None)
            return self.player.playbackState() == playing
        except Exception:
            return False

    def pause(self):
        if self.player is None:
            return False
        try:
            self.player.pause()
            return True
        except Exception:
            return False

    def resume(self):
        if self.player is None or not self.current_path:
            return False
        try:
            self.player.play()
            return True
        except Exception:
            return False


# ---------- theme ----------

def _resource_base():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


_ASSETS_DIR = os.path.join(_resource_base(), "assets")


# ---------- 主题系统:暗黑 / 白天 双主题(可切换) ----------
_ACCENT_HEX = "#6366f1"
_ACCENT2_HEX = "#8b5cf6"
THEMES = {
    "dark": {
        "rootBg1": "#0b0e17", "rootBg2": "#090b11", "sideBg1": "#12151f", "sideBg2": "#0e111a", "sideBorder": "#1b2030",
        "text": "#e8eaf0", "title": "#ffffff", "sub": "#8b93a3", "muted": "#6f7a90", "group": "#57607a", "brandSub": "#6f7a90",
        "cardBg": "rgba(23,27,37,0.94)", "cardBorder": "#232a3b",
        "statBg1": "rgba(31,37,56,0.96)", "statBg2": "rgba(19,23,35,0.96)", "statBorder": "#283048", "statHover": "#4b52ff",
        "statNum": "#ffffff", "statLbl": "#93a0b5", "conn": "#7f8aa0", "hero": "#2a3350",
        "navText": "#aab3c5", "navHoverBg": "#1a2032", "navHoverText": "#e8eaf0",
        "navCheckedText": "#ffffff", "navCheckBg1": "rgba(99,102,241,0.30)", "navCheckBg2": "rgba(99,102,241,0.05)",
        "ghostBg": "rgba(255,255,255,0.03)", "ghostBorder": "#2b3040", "ghostText": "#dfe3ec", "ghostHoverBg": "rgba(99,102,241,0.10)",
        "primaryDisBg": "#3a3f52", "primaryDisText": "#98a0b0",
        "inputBg": "#0c0f17", "inputBorder": "#262c3b", "inputFocusBg": "#0e1220", "comboView": "#12151f",
        "tableBg": "#0b0e16", "tableBorder": "#222a3a", "tableGrid": "#191e2a", "selBg": "rgba(99,102,241,0.22)", "selText": "#ffffff",
        "headerBg": "#141824", "headerText": "#8b93a3", "headerBorder": "#232b3c",
        "scroll": "#2a3040", "scrollHover": "#3a4358", "menuBg": "#141824", "menuText": "#e8eaf0", "menuBorder": "rgba(255,255,255,0.10)",
        "iconBg": "rgba(255,255,255,0.05)", "iconText": "#8b93a3", "iconBorder": "rgba(255,255,255,0.09)",
        "accent": _ACCENT_HEX, "accent2": _ACCENT2_HEX,
    },
    "light": {
        "rootBg1": "#f5f7fb", "rootBg2": "#eef1f7", "sideBg1": "#ffffff", "sideBg2": "#f6f8fc", "sideBorder": "#e4e8f0",
        "text": "#28303f", "title": "#111726", "sub": "#6b7488", "muted": "#98a2b3", "group": "#9aa3b4", "brandSub": "#9aa3b4",
        "cardBg": "#ffffff", "cardBorder": "#e6eaf1",
        "statBg1": "#ffffff", "statBg2": "#f7f9fc", "statBorder": "#e6eaf1", "statHover": "#6366f1",
        "statNum": "#111726", "statLbl": "#6b7488", "conn": "#8a94a6", "hero": "#dfe4ef",
        "navText": "#4b5568", "navHoverBg": "#eef1f8", "navHoverText": "#111726",
        "navCheckedText": "#4338ca", "navCheckBg1": "rgba(99,102,241,0.16)", "navCheckBg2": "rgba(99,102,241,0.02)",
        "ghostBg": "#eef2f8", "ghostBorder": "#ccd4e2", "ghostText": "#3a4356", "ghostHoverBg": "rgba(99,102,241,0.12)",
        "primaryDisBg": "#c7cdd8", "primaryDisText": "#ffffff",
        "inputBg": "#ffffff", "inputBorder": "#d0d7e2", "inputFocusBg": "#f6f8ff", "comboView": "#ffffff",
        "tableBg": "#ffffff", "tableBorder": "#e6eaf1", "tableGrid": "#eef1f6", "selBg": "rgba(99,102,241,0.14)", "selText": "#28303f",
        "headerBg": "#f5f7fb", "headerText": "#6b7488", "headerBorder": "#e6eaf1",
        "scroll": "#cbd3e0", "scrollHover": "#b0bacb", "menuBg": "#ffffff", "menuText": "#28303f", "menuBorder": "#e6eaf1",
        "iconBg": "#f0f3f9", "iconText": "#6b7488", "iconBorder": "#e4e8f0",
        "accent": _ACCENT_HEX, "accent2": _ACCENT2_HEX,
    },
}
CURRENT_THEME = "dark"
TK = dict(THEMES["dark"])  # 当前主题 token(全局,painted 控件读它)


def is_light():
    return CURRENT_THEME == "light"


def build_qss(t):
    t = dict(t)
    t.setdefault("checkIcon", os.path.join(_ASSETS_DIR, "check.png").replace("\\", "/"))
    return ("""
* { font-family:'Microsoft YaHei','Segoe UI',sans-serif; }
QWidget#root { background:qlineargradient(x1:0,y1:0,x2:0.7,y2:1, stop:0 %(rootBg1)s, stop:1 %(rootBg2)s); }
QWidget#sidebar { background:qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 %(sideBg1)s, stop:1 %(sideBg2)s); border-right:1px solid %(sideBorder)s; }
QWidget#page { background:transparent; }
QLabel { color:%(text)s; background:transparent; }
QLabel#brand { font-size:18px; font-weight:800; color:%(title)s; }
QLabel#brandSub { color:%(brandSub)s; font-size:10px; font-weight:800; letter-spacing:2px; }
QLabel#group { color:%(group)s; font-size:11px; font-weight:800; letter-spacing:1px; }
QLabel#h1 { font-size:24px; font-weight:800; color:%(title)s; }
QLabel#sub { color:%(sub)s; font-size:12px; }
QLabel#statNum { font-size:30px; font-weight:800; color:%(statNum)s; }
QLabel#statLbl { color:%(statLbl)s; font-size:12px; font-weight:500; }
QLabel#conn { color:%(conn)s; font-size:12px; }
QFrame#card { background:%(cardBg)s; border:1px solid %(cardBorder)s; border-radius:16px; }
QFrame#statCard { background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 %(statBg1)s, stop:1 %(statBg2)s); border:1px solid %(statBorder)s; border-radius:16px; }
QFrame#statCard:hover { border:1px solid %(statHover)s; }
QFrame#hero { border-radius:18px; border:1px solid %(hero)s; }
QFrame#accentBar { background:qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 %(accent)s, stop:1 %(accent2)s); border-radius:2px; }
QPushButton { background:%(ghostBg)s; border:1px solid %(ghostBorder)s; color:%(ghostText)s; border-radius:10px; padding:9px 16px; min-height:18px; min-width:76px; font-weight:650; }
QPushButton:hover { border-color:%(accent)s; background:%(ghostHoverBg)s; color:%(title)s; }
QPushButton:disabled { background:rgba(255,255,255,0.025); border-color:rgba(255,255,255,0.07); color:%(muted)s; }
QPushButton#nav { background:transparent; color:%(navText)s; text-align:left; padding:10px 14px; border-radius:10px; font-size:13px; font-weight:600; }
QPushButton#nav:hover { background:%(navHoverBg)s; color:%(navHoverText)s; }
QPushButton#nav:checked { background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 %(navCheckBg1)s, stop:1 %(navCheckBg2)s); color:%(navCheckedText)s; border-left:3px solid %(accent)s; padding-left:11px; }
QPushButton#primary { background:%(accent)s; color:#ffffff; border:1px solid rgba(255,255,255,0.18); border-radius:10px; padding:10px 20px; min-width:92px; font-weight:750; }
QPushButton#primary:hover { background:%(accent2)s; }
QPushButton#primary:disabled { background:%(primaryDisBg)s; color:%(primaryDisText)s; }
QPushButton#ghost { background:%(ghostBg)s; border:1px solid %(ghostBorder)s; color:%(ghostText)s; border-radius:10px; padding:9px 16px; min-width:82px; font-weight:650; }
QPushButton#ghost:hover { border-color:%(accent)s; background:%(ghostHoverBg)s; color:%(title)s; }
QToolButton#sourceThumb { background:%(ghostBg)s; border:1px solid %(ghostBorder)s; color:%(ghostText)s; border-radius:8px; padding:7px; font-weight:650; }
QToolButton#sourceThumb:hover, QToolButton#sourceThumb:focus { border-color:%(accent)s; background:%(ghostHoverBg)s; color:%(title)s; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit { background:%(inputBg)s; border:1px solid %(inputBorder)s; border-radius:10px; padding:10px; color:%(text)s; selection-background-color:%(accent)s; selection-color:#ffffff; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus { border:1px solid %(accent)s; background:%(inputFocusBg)s; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QPlainTextEdit:disabled, QTextEdit:disabled { color:%(sub)s; background:rgba(255,255,255,0.025); border-color:rgba(255,255,255,0.08); }
QCheckBox { color:%(text)s; background:transparent; spacing:9px; font-size:12.5px; font-weight:600; }
QCheckBox::indicator { width:18px; height:18px; border-radius:5px; border:1.5px solid rgba(255,255,255,0.62); background:rgba(255,255,255,0.12); }
QCheckBox::indicator:hover { border-color:%(accent)s; background:rgba(99,102,241,0.18); }
QCheckBox::indicator:checked { border:1.5px solid %(accent)s; background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 %(accent)s,stop:1 %(accent2)s); image:url('%(checkIcon)s'); }
QCheckBox::indicator:disabled { border-color:rgba(255,255,255,0.18); background:rgba(255,255,255,0.04); }
QComboBox::drop-down { border:0; width:22px; }
QComboBox QAbstractItemView { background:%(comboView)s; border:1px solid %(inputBorder)s; selection-background-color:%(accent)s; selection-color:#ffffff; color:%(text)s; outline:0; }
QTableWidget { background:%(tableBg)s; border:1px solid %(tableBorder)s; border-radius:12px; gridline-color:%(tableGrid)s; color:%(text)s; }
QTableWidget::item { padding:8px; }
QTableWidget::item:selected { background:%(selBg)s; color:%(selText)s; selection-color:%(selText)s; }
QHeaderView::section { background:%(headerBg)s; color:%(headerText)s; border:0; border-bottom:1px solid %(headerBorder)s; padding:10px; font-weight:700; }
QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
QScrollBar::handle:vertical { background:%(scroll)s; border-radius:5px; min-height:32px; }
QScrollBar::handle:vertical:hover { background:%(scrollHover)s; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; }
QPushButton#primary::menu-indicator { subcontrol-position: right center; subcontrol-origin: padding; right:10px; width:12px; }
QPushButton#iconbtn { background:%(iconBg)s; color:%(iconText)s; border:1px solid %(iconBorder)s; border-radius:12px; font-size:12px; font-weight:700; padding:0; }
QPushButton#iconbtn:hover { background:rgba(239,68,68,0.20); color:#ffffff; border-color:rgba(239,68,68,0.55); }
QMenu { background:%(menuBg)s; color:%(menuText)s; border:1px solid %(menuBorder)s; border-radius:10px; padding:6px; }
QMenu::item { padding:9px 18px; border-radius:7px; margin:1px 2px; }
QMenu::item:selected { background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(99,102,241,0.30), stop:1 rgba(139,92,246,0.30)); color:#ffffff; }
""" % t)


QSS = build_qss(TK)


def build_palette(t):
    pal = QtGui.QPalette()
    def C(x):
        return QtGui.QColor(x)
    pal.setColor(QtGui.QPalette.Window, C(t["rootBg1"]))
    pal.setColor(QtGui.QPalette.WindowText, C(t["text"]))
    pal.setColor(QtGui.QPalette.Base, C(t["inputBg"]))
    pal.setColor(QtGui.QPalette.AlternateBase, C(t["sideBg1"]))
    pal.setColor(QtGui.QPalette.Text, C(t["text"]))
    pal.setColor(QtGui.QPalette.Button, C(t["inputBg"]))
    pal.setColor(QtGui.QPalette.ButtonText, C(t["text"]))
    pal.setColor(QtGui.QPalette.ToolTipBase, C(t["menuBg"]))
    pal.setColor(QtGui.QPalette.ToolTipText, C(t["text"]))
    pal.setColor(QtGui.QPalette.Highlight, C(t["accent"]))
    pal.setColor(QtGui.QPalette.HighlightedText, C("#ffffff"))
    pal.setColor(QtGui.QPalette.PlaceholderText, C(t["muted"]))
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, C(t["muted"]))
    return pal


def apply_theme(name):
    """切换主题:更新全局 token + 重建 QSS/palette 并应用到整个应用(chrome 立即生效)。"""
    global CURRENT_THEME, TK, QSS
    if name not in THEMES:
        name = "dark"
    CURRENT_THEME = name
    TK = dict(THEMES[name])
    QSS = build_qss(TK)
    app = QtWidgets.QApplication.instance()
    if app:
        app.setPalette(build_palette(TK))
        app.setStyleSheet(QSS)


def _theme_pref_path():
    return os.path.join(data_dir(), "theme.txt")


def load_theme_pref():
    try:
        v = open(_theme_pref_path(), encoding="utf-8").read().strip()
        return v if v in THEMES else "dark"
    except Exception:
        return "dark"


def save_theme_pref(name):
    try:
        os.makedirs(os.path.dirname(_theme_pref_path()), exist_ok=True)
        open(_theme_pref_path(), "w", encoding="utf-8").write(name)
    except Exception:
        pass


# ---------- animation / effect helpers ----------

def add_shadow(widget, blur=30, dy=10, alpha=120):
    """已禁用:QGraphicsDropShadowEffect 在真机 GPU 合成下会把卡内的渐变/主色按钮画成
    palette 的 Button 底色(亮色主题=白 → 按钮压在白卡上看不见)。改用 QSS 描边表现层次。"""
    return None


def fade_in(widget, dur=280, delay=0):
    """淡入 + 轻微上移。用 opacity effect,注意与投影互斥(别对同一控件同时用)。"""
    eff = QtWidgets.QGraphicsOpacityEffect(widget)
    eff.setOpacity(0.0)
    widget.setGraphicsEffect(eff)
    anim = QtCore.QPropertyAnimation(eff, b"opacity", widget)
    anim.setDuration(dur)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
    widget._fade_anim = anim  # 保持引用防被 GC

    def _clear():
        # 动画结束后移除 effect,避免遮住子控件自身的 effect(如卡片投影)
        try:
            widget.setGraphicsEffect(None)
        except Exception:
            pass
    anim.finished.connect(_clear)
    if delay > 0:
        QtCore.QTimer.singleShot(delay, lambda: anim.start())
    else:
        anim.start()
    return anim


def count_up(label, target, dur=900, suffix=""):
    """数字从 0 滚动到 target。target 非数字则直接设文本。"""
    try:
        tv = float(target)
    except (TypeError, ValueError):
        label.setText(str(target))
        return None
    is_int = float(tv).is_integer()
    anim = QtCore.QVariantAnimation(label)
    anim.setDuration(dur)
    anim.setStartValue(0.0)
    anim.setEndValue(tv)
    anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

    def _upd(val):
        v = float(val)
        label.setText((("%d" if is_int else "%.1f") % v) + suffix)
    anim.valueChanged.connect(_upd)
    label._count_anim = anim
    anim.start()
    return anim


def _paint_aurora(widget):
    """深空极光背景:深蓝底 + 几团柔和的靛蓝/紫/蓝光晕。比纯黑有质感得多。"""
    p = QtGui.QPainter(widget)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    r = widget.rect()
    w, h = max(r.width(), 1), max(r.height(), 1)
    light = is_light()
    base = QtGui.QLinearGradient(0, 0, 0, h)
    if light:
        base.setColorAt(0.0, QtGui.QColor(TK["rootBg1"]))
        base.setColorAt(1.0, QtGui.QColor(TK["rootBg2"]))
    else:
        base.setColorAt(0.0, QtGui.QColor("#0d1018"))
        base.setColorAt(1.0, QtGui.QColor("#090b12"))
    p.fillRect(r, QtGui.QBrush(base))

    def glow(cx, cy, rad, color, a0):
        g = QtGui.QRadialGradient(cx, cy, rad)
        c = QtGui.QColor(color); c.setAlpha(a0); g.setColorAt(0.0, c)
        c1 = QtGui.QColor(color); c1.setAlpha(int(a0 * 0.32)); g.setColorAt(0.55, c1)
        c2 = QtGui.QColor(color); c2.setAlpha(0); g.setColorAt(1.0, c2)
        p.fillRect(r, QtGui.QBrush(g))
    m = float(max(w, h))
    if light:  # 白天:极淡的靛蓝晕,给纯白底一点层次
        glow(w * 0.12, h * -0.03, m * 0.55, "#c3caf2", 46)
        glow(w * 0.97, h * 1.05, m * 0.55, "#d3d9f4", 34)
    else:      # 暗黑:淡深靛蓝
        glow(w * 0.12, h * -0.03, m * 0.55, "#2f3560", 42)
        glow(w * 0.97, h * 1.05, m * 0.55, "#232a4d", 30)
    p.end()


class AuroraBg(QtWidgets.QWidget):
    """极光背景容器,用作主内容区/登录页底。"""

    def paintEvent(self, e):
        _paint_aurora(self)


class NavButton(QtWidgets.QPushButton):
    """导航按钮:悬停时靛蓝光晕淡入 + 文字右移,营造“浮出”效果。"""

    def __init__(self, text):
        super().__init__(text)
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._eff = QtWidgets.QGraphicsDropShadowEffect(self)
        self._eff.setBlurRadius(0)
        self._eff.setOffset(0, 0)
        gc = QtGui.QColor("#6366f1"); gc.setAlpha(180)
        self._eff.setColor(gc)
        self.setGraphicsEffect(self._eff)
        self._anim = QtCore.QPropertyAnimation(self._eff, b"blurRadius", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

    def _glow(self, to):
        self._anim.stop()
        self._anim.setEndValue(to)
        self._anim.start()

    def enterEvent(self, e):
        self._glow(20)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._glow(0)
        super().leaveEvent(e)


def make_header(title, subtitle, actions=None):
    w = QtWidgets.QWidget()
    h = QtWidgets.QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(12)
    bar = QtWidgets.QFrame()
    bar.setObjectName("accentBar")
    bar.setFixedWidth(4)
    bar.setMinimumHeight(40)
    h.addWidget(bar)
    box = QtWidgets.QVBoxLayout()
    box.setSpacing(3)
    t = QtWidgets.QLabel(title)
    t.setObjectName("h1")
    s = QtWidgets.QLabel(subtitle)
    s.setObjectName("sub")
    box.addWidget(t)
    box.addWidget(s)
    h.addLayout(box)
    h.addStretch()
    for a in (actions or []):
        h.addWidget(a)
    return w


def prereq_banner(text):
    """前置条件提示条(采集/发布/寻客/拓客 依赖本机浏览器在线 + 平台账号已登录,否则不会真实执行)。"""
    lab = QtWidgets.QLabel("⚠️  " + text)
    lab.setWordWrap(True)
    lab.setStyleSheet("background:rgba(245,196,81,0.12);border:1px solid rgba(245,196,81,0.40);"
                      "border-radius:8px;color:#e6b84a;font-size:12px;padding:7px 12px;")
    return lab


def _rgba(hexc, a):
    hexc = str(hexc).lstrip("#")
    r, g, b = int(hexc[0:2], 16), int(hexc[2:4], 16), int(hexc[4:6], 16)
    return "rgba(%d,%d,%d,%.3f)" % (r, g, b, a)


class HoverCard(QtWidgets.QFrame):
    """鼠标放上去平滑浮起(投影加深、上移)的卡片。"""

    def __init__(self, object_name=None, rest_blur=18, hover_blur=34, rest_dy=8, hover_dy=16, alpha=85):
        super().__init__()
        if object_name:
            self.setObjectName(object_name)
        # 不挂 QGraphicsDropShadowEffect:该 effect 在真机 GPU 合成下会破坏卡内渐变/主色按钮
        # 的渲染(亮色主题下按钮变白看不见)。卡片层次改由 QSS 描边/底色表现。
        self._eff = None

    def _animate(self, blur, dy):
        pass

    def enterEvent(self, e):
        super().enterEvent(e)

    def leaveEvent(self, e):
        super().leaveEvent(e)


class InteractFilter(QtCore.QObject):
    """事件过滤器:给按钮加「悬停发光 + 按下缩放回弹」的点击/悬停动画。"""

    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
            if t == QtCore.QEvent.Enter:
                self._glow(obj, 20)
            elif t == QtCore.QEvent.Leave:
                self._glow(obj, 0)
                self._scale(obj, 1.0)
            elif t == QtCore.QEvent.MouseButtonPress:
                self._scale(obj, 0.94)
            elif t == QtCore.QEvent.MouseButtonRelease:
                self._scale(obj, 1.0)
                self._glow(obj, 20)
        except Exception:
            pass
        return False

    def _glow(self, obj, blur):
        # 已禁用悬停发光:QGraphicsDropShadowEffect 会让按钮在真机 GPU 下渲染异常
        # (亮色主题按钮变白)。保留按下缩放回弹(用 geometry 动画,不涉及 graphics effect)。
        return

    def _scale(self, obj, factor):
        if getattr(obj, "_no_press_scale", False) or isinstance(obj, QtWidgets.QPushButton):
            # 全局按钮不再使用 geometry 缩放；Qt 布局管理器会在点击/改字时重排，手动改 geometry 会造成上移跳动。
            return
        rest = getattr(obj, "_rest_geo", None)
        if rest is None:
            rest = obj.geometry()
            obj._rest_geo = rest
        cx, cy = rest.center().x(), rest.center().y()
        nw = max(1, int(rest.width() * factor))
        nh = max(1, int(rest.height() * factor))
        target = QtCore.QRect(cx - nw // 2, cy - nh // 2, nw, nh)
        a = getattr(obj, "_scale_anim", None)
        if a is None:
            a = QtCore.QPropertyAnimation(obj, b"geometry", obj)
            a.setDuration(95)
            a.setEasingCurve(QtCore.QEasingCurve.OutCubic)
            obj._scale_anim = a
        a.stop(); a.setStartValue(obj.geometry()); a.setEndValue(target); a.start()
        if abs(factor - 1.0) < 0.001:
            obj._rest_geo = None


_INTERACT = None


def wire_animations(root):
    """给 root 下所有 QPushButton(NavButton 已自带动画,跳过)装点击/悬停动画。"""
    global _INTERACT
    if _INTERACT is None:
        _INTERACT = InteractFilter()
    for b in root.findChildren(QtWidgets.QPushButton):
        if isinstance(b, NavButton) or getattr(b, "_wired", False):
            continue
        b._wired = True
        b.installEventFilter(_INTERACT)
        b.setCursor(QtCore.Qt.PointingHandCursor)


KPI_META = {
    "客户企业": ("🏢", "#6366f1"), "企业用户": ("👥", "#3b82f6"), "团队成员": ("🤝", "#06b6d4"),
    "在线节点": ("🛰", "#22c55e"), "节点": ("🖧", "#22c55e"), "授权账号": ("🎫", "#8b5cf6"),
    "可用账号": ("⚡", "#14b8a6"), "离线账号": ("🌙", "#64748b"), "就绪账号": ("✅", "#10b981"),
    "调度任务": ("📊", "#f59e0b"), "24h任务": ("📊", "#f59e0b"), "素材": ("🎞", "#ec4899"),
    "客户线索": ("🎯", "#f43f5e"), "发布队列": ("🚀", "#a855f7"), "审计事件": ("📝", "#0ea5e9"),
    "接入平台": ("🌐", "#6366f1"), "总粉丝量": ("❤", "#ec4899"), "今日发布": ("🚀", "#22c55e"),
}

# 标签 → 手绘图标类型(避免 emoji 在部分系统渲染成方框)
ICON_KIND = {
    "接入平台": "platform", "在线节点": "platform", "节点": "platform", "客户企业": "building",
    "授权账号": "account", "可用账号": "account", "离线账号": "account", "就绪账号": "account",
    "企业用户": "account", "团队成员": "account", "审计事件": "account",
    "总粉丝量": "heart", "客户线索": "heart",
    "今日发布": "publish", "发布队列": "publish", "调度任务": "chart", "24h任务": "chart", "素材": "chart",
}


# 平台 → 真实官方 app 图标文件(网上下载的原图,非手绘)
PLATFORM_LOGO_FILE = {
    "douyin": "logo_douyin.png", "抖音": "logo_douyin.png",
    "xhs": "logo_xhs.png", "xiaohongshu": "logo_xhs.png", "小红书": "logo_xhs.png",
}
_LOGO_CACHE = {}


def platform_logo(pk, size):
    """加载真实平台官方 logo(圆角 app 图标),按 DPR 缩放返回 QPixmap;无对应资源返回 None。"""
    fn = PLATFORM_LOGO_FILE.get(pk)
    if not fn:
        return None
    orig = _LOGO_CACHE.get(fn)
    if orig is None:
        path = os.path.join(_ASSETS_DIR, fn)
        if not os.path.exists(path):
            _LOGO_CACHE[fn] = False
            return None
        orig = QtGui.QPixmap(path)
        _LOGO_CACHE[fn] = orig if not orig.isNull() else False
    if not orig:
        return None
    dpr = 2.0
    pm = orig.scaled(int(size * dpr), int(size * dpr), QtCore.Qt.KeepAspectRatio,
                     QtCore.Qt.SmoothTransformation)
    pm.setDevicePixelRatio(dpr)
    return pm


def _draw_icon(kind, size=22, color="#ffffff"):
    """QPainter 手绘矢量图标,返回透明底 QPixmap。始终渲染,不依赖 emoji 字体。"""
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    c = QtGui.QColor(color)
    s = float(size)
    stroke = max(1.6, s * 0.10)
    pen = QtGui.QPen(c, stroke)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)

    def line(x1, y1, x2, y2):
        p.drawLine(QtCore.QPointF(s * x1, s * y1), QtCore.QPointF(s * x2, s * y2))

    if kind == "douyin":  # 抖音音符
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QtCore.QRectF(s * 0.16, s * 0.60, s * 0.28, s * 0.24))
        p.setBrush(QtCore.Qt.NoBrush)
        pen2 = QtGui.QPen(c, max(2.0, s * 0.11))
        pen2.setCapStyle(QtCore.Qt.RoundCap)
        p.setPen(pen2)
        line(0.42, 0.72, 0.42, 0.18)
        path = QtGui.QPainterPath(QtCore.QPointF(s * 0.42, s * 0.18))
        path.cubicTo(s * 0.60, s * 0.20, s * 0.72, s * 0.32, s * 0.76, s * 0.46)
        p.drawPath(path)
    elif kind == "xhs":  # 小红书书本
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QtCore.QRectF(s * 0.24, s * 0.20, s * 0.52, s * 0.60), s * 0.07, s * 0.07)
        p.setPen(QtGui.QPen(QtGui.QColor("#ef4444"), max(1.4, s * 0.09)))
        line(0.36, 0.36, 0.64, 0.36)
        line(0.36, 0.50, 0.64, 0.50)
        line(0.36, 0.64, 0.54, 0.64)
    elif kind == "platform":  # 地球
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(QtCore.QRectF(s * 0.16, s * 0.16, s * 0.68, s * 0.68))
        p.drawEllipse(QtCore.QRectF(s * 0.37, s * 0.16, s * 0.26, s * 0.68))
        line(0.17, 0.5, 0.83, 0.5)
    elif kind == "account":  # 证件卡
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(s * 0.16, s * 0.24, s * 0.68, s * 0.52), s * 0.09, s * 0.09)
        p.setBrush(c)
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(QtCore.QRectF(s * 0.26, s * 0.36, s * 0.16, s * 0.16))
        p.setPen(pen)
        line(0.52, 0.40, 0.72, 0.40)
        line(0.52, 0.52, 0.72, 0.52)
    elif kind == "heart":  # 心
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(c)
        path = QtGui.QPainterPath(QtCore.QPointF(s * 0.5, s * 0.78))
        path.cubicTo(s * 0.08, s * 0.50, s * 0.20, s * 0.16, s * 0.5, s * 0.36)
        path.cubicTo(s * 0.80, s * 0.16, s * 0.92, s * 0.50, s * 0.5, s * 0.78)
        p.drawPath(path)
    elif kind == "publish":  # 上传箭头
        p.setPen(pen)
        line(0.5, 0.80, 0.5, 0.26)
        line(0.31, 0.44, 0.5, 0.24)
        line(0.69, 0.44, 0.5, 0.24)
    elif kind == "chart":  # 柱状图
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(c)
        for i, (x, h) in enumerate([(0.24, 0.28), (0.44, 0.44), (0.64, 0.58)]):
            p.drawRoundedRect(QtCore.QRectF(s * x, s * (0.78 - h), s * 0.14, s * h), s * 0.03, s * 0.03)
    elif kind == "building":  # 楼
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(s * 0.26, s * 0.20, s * 0.48, s * 0.60), s * 0.04, s * 0.04)
        for yy in (0.34, 0.48, 0.62):
            line(0.36, yy, 0.44, yy)
            line(0.56, yy, 0.64, yy)
    elif kind == "device":  # 显示器(代表"本机浏览器")
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(s * 0.15, s * 0.22, s * 0.70, s * 0.42), s * 0.06, s * 0.06)
        line(0.5, 0.64, 0.5, 0.76)
        line(0.36, 0.80, 0.64, 0.80)
    elif kind == "plus":  # 加号(代表"添加新账号")
        pen2 = QtGui.QPen(c, max(2.0, s * 0.12))
        pen2.setCapStyle(QtCore.Qt.RoundCap)
        p.setPen(pen2)
        line(0.5, 0.24, 0.5, 0.76)
        line(0.24, 0.5, 0.76, 0.5)
    elif kind == "edit":  # 铅笔(重新编辑)
        p.setBrush(c)
        p.setPen(QtCore.Qt.NoPen)
        path = QtGui.QPainterPath(QtCore.QPointF(s * 0.68, s * 0.16))
        path.lineTo(s * 0.84, s * 0.32)
        path.lineTo(s * 0.40, s * 0.76)
        path.lineTo(s * 0.20, s * 0.82)
        path.lineTo(s * 0.26, s * 0.62)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "refresh":  # 循环箭头(再次生成)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawArc(QtCore.QRectF(s * 0.22, s * 0.22, s * 0.56, s * 0.56), 55 * 16, 250 * 16)
        line(0.76, 0.26, 0.78, 0.44)
        line(0.76, 0.26, 0.60, 0.32)
    elif kind == "trash":  # 垃圾桶(删除)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        line(0.22, 0.30, 0.78, 0.30)
        line(0.40, 0.30, 0.42, 0.22)
        line(0.42, 0.22, 0.58, 0.22)
        line(0.58, 0.22, 0.60, 0.30)
        path = QtGui.QPainterPath(QtCore.QPointF(s * 0.29, s * 0.32))
        path.lineTo(s * 0.34, s * 0.80)
        path.lineTo(s * 0.66, s * 0.80)
        path.lineTo(s * 0.71, s * 0.32)
        p.drawPath(path)
        line(0.44, 0.42, 0.45, 0.70)
        line(0.56, 0.42, 0.55, 0.70)
    elif kind == "logout":  # 退出登录
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(s * 0.18, s * 0.22, s * 0.34, s * 0.56), s * 0.06, s * 0.06)
        line(0.42, 0.50, 0.78, 0.50)
        line(0.62, 0.34, 0.78, 0.50)
        line(0.62, 0.66, 0.78, 0.50)
    elif kind == "sparkle":  # 四角星(综合最优)
        p.setBrush(c)
        p.setPen(QtCore.Qt.NoPen)
        path = QtGui.QPainterPath(QtCore.QPointF(s * 0.5, s * 0.14))
        path.cubicTo(s * 0.55, s * 0.45, s * 0.55, s * 0.45, s * 0.86, s * 0.5)
        path.cubicTo(s * 0.55, s * 0.55, s * 0.55, s * 0.55, s * 0.5, s * 0.86)
        path.cubicTo(s * 0.45, s * 0.55, s * 0.45, s * 0.55, s * 0.14, s * 0.5)
        path.cubicTo(s * 0.45, s * 0.45, s * 0.45, s * 0.45, s * 0.5, s * 0.14)
        p.drawPath(path)
    elif kind == "image":  # 图片(山+日)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(s * 0.16, s * 0.24, s * 0.68, s * 0.52), s * 0.08, s * 0.08)
        p.setBrush(c)
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(QtCore.QRectF(s * 0.30, s * 0.34, s * 0.12, s * 0.12))
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        path = QtGui.QPainterPath(QtCore.QPointF(s * 0.20, s * 0.70))
        path.lineTo(s * 0.40, s * 0.50)
        path.lineTo(s * 0.54, s * 0.63)
        path.lineTo(s * 0.66, s * 0.48)
        path.lineTo(s * 0.80, s * 0.66)
        p.drawPath(path)
    elif kind == "video":  # 视频(框+播放三角)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(s * 0.16, s * 0.26, s * 0.68, s * 0.48), s * 0.09, s * 0.09)
        p.setBrush(c)
        p.setPen(QtCore.Qt.NoPen)
        tri = QtGui.QPainterPath(QtCore.QPointF(s * 0.43, s * 0.38))
        tri.lineTo(s * 0.43, s * 0.62)
        tri.lineTo(s * 0.63, s * 0.50)
        tri.closeSubpath()
        p.drawPath(tri)
    elif kind == "layers":  # 层叠菱形(数量/分组)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        for cy in (0.36, 0.60):
            path = QtGui.QPainterPath(QtCore.QPointF(s * 0.5, s * (cy - 0.14)))
            path.lineTo(s * 0.76, s * cy)
            path.lineTo(s * 0.5, s * (cy + 0.14))
            path.lineTo(s * 0.24, s * cy)
            path.closeSubpath()
            p.drawPath(path)
    elif kind == "ratio":  # 比例框
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(s * 0.18, s * 0.30, s * 0.64, s * 0.40), s * 0.06, s * 0.06)
    elif kind == "arrowup":  # 上箭头(发送)
        pen2 = QtGui.QPen(c, max(2.4, s * 0.14))
        pen2.setCapStyle(QtCore.Qt.RoundCap)
        pen2.setJoinStyle(QtCore.Qt.RoundJoin)
        p.setPen(pen2)
        line(0.5, 0.78, 0.5, 0.24)
        line(0.28, 0.46, 0.5, 0.22)
        line(0.72, 0.46, 0.5, 0.22)
    elif kind == "download":  # 下箭头入托盘(下载)
        p.setPen(pen)
        line(0.5, 0.20, 0.5, 0.60)
        line(0.33, 0.45, 0.5, 0.63)
        line(0.67, 0.45, 0.5, 0.63)
        line(0.26, 0.76, 0.74, 0.76)
    elif kind == "play":  # 播放三角
        p.setBrush(c)
        p.setPen(QtCore.Qt.NoPen)
        tri = QtGui.QPainterPath(QtCore.QPointF(s * 0.34, s * 0.24))
        tri.lineTo(s * 0.34, s * 0.76)
        tri.lineTo(s * 0.78, s * 0.50)
        tri.closeSubpath()
        p.drawPath(tri)
    elif kind == "star":  # 五角星(收藏/资产库)
        import math as _math
        p.setBrush(c)
        p.setPen(QtCore.Qt.NoPen)
        cx, cy, ro, ri = s * 0.5, s * 0.52, s * 0.40, s * 0.17
        path = QtGui.QPainterPath()
        for i in range(10):
            ang = -_math.pi / 2 + i * _math.pi / 5
            rr = ro if i % 2 == 0 else ri
            x = cx + rr * _math.cos(ang)
            y = cy + rr * _math.sin(ang)
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "grid":  # 宫格(资产库)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        for gx in (0.20, 0.56):
            for gy in (0.20, 0.56):
                p.drawRoundedRect(QtCore.QRectF(s * gx, s * gy, s * 0.24, s * 0.24), s * 0.04, s * 0.04)
    else:  # dot
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QtCore.QRectF(s * 0.34, s * 0.34, s * 0.32, s * 0.32))
    p.end()
    return pm


def kpi_card(num, label):
    icon, color = KPI_META.get(label, ("•", "#6366f1"))
    f = HoverCard("statCard", rest_blur=18, hover_blur=36, rest_dy=8, hover_dy=17, alpha=90)
    v = QtWidgets.QVBoxLayout(f)
    v.setContentsMargins(18, 15, 18, 16)
    v.setSpacing(13)
    top = QtWidgets.QHBoxLayout()
    chip = QtWidgets.QLabel()
    chip.setFixedSize(38, 38)
    chip.setAlignment(QtCore.Qt.AlignCenter)
    chip.setStyleSheet("background:%s;border:1px solid %s;border-radius:11px;"
                       % (_rgba(color, 0.15), _rgba(color, 0.45)))
    chip.setPixmap(_draw_icon(ICON_KIND.get(label, "dot"), 20, color))
    dot = QtWidgets.QLabel("")
    dot.setFixedSize(8, 8)
    dot.setStyleSheet("background:%s;border-radius:4px;" % color)
    top.addWidget(chip)
    top.addStretch()
    top.addWidget(dot, 0, QtCore.Qt.AlignTop)
    v.addLayout(top)
    box = QtWidgets.QVBoxLayout()
    box.setSpacing(1)
    n = QtWidgets.QLabel("0")
    n.setObjectName("statNum")
    l = QtWidgets.QLabel(label)
    l.setObjectName("statLbl")
    box.addWidget(n)
    box.addWidget(l)
    v.addLayout(box)
    count_up(n, num)
    return f


def stat_card(num, label):
    return kpi_card(num, label)


class Panel(HoverCard):
    """带标题的内容卡片;内容加到 self.body,鼠标放上去平滑浮起。"""

    def __init__(self, title, subtitle=None, action=None):
        super().__init__("card", rest_blur=22, hover_blur=34, rest_dy=10, hover_dy=17, alpha=72)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 18)
        v.setSpacing(13)
        head = QtWidgets.QHBoxLayout()
        tv = QtWidgets.QVBoxLayout()
        tv.setSpacing(2)
        t = QtWidgets.QLabel(title)
        t.setStyleSheet("font-size:15px;font-weight:700;color:%s;background:transparent;" % TK["text"])
        tv.addWidget(t)
        if subtitle:
            s = QtWidgets.QLabel(subtitle)
            s.setStyleSheet("color:%s;font-size:11px;background:transparent;" % TK["sub"])
            tv.addWidget(s)
        head.addLayout(tv)
        head.addStretch()
        if action is not None:
            head.addWidget(action)
        v.addLayout(head)
        self.body = QtWidgets.QVBoxLayout()
        self.body.setSpacing(10)
        v.addLayout(self.body, 1)


class MiniBars(QtWidgets.QWidget):
    """迷你柱状趋势图(QPainter,带底部标签)。"""

    def __init__(self, values, labels=None, color="#8b5cf6", h=156):
        super().__init__()
        self.values = list(values) if values else [0]
        self.labels = labels or []
        self.color = color
        self.setMinimumHeight(h)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        area = self.rect().adjusted(2, 8, -2, -22)
        n = len(self.values)
        mx = max(self.values) or 1
        gap = 12
        bw = max(6.0, (area.width() - gap * (n - 1)) / max(1, n))
        for i, val in enumerate(self.values):
            bh = (val / mx) * area.height()
            x = area.left() + i * (bw + gap)
            y = area.bottom() - bh
            grad = QtGui.QLinearGradient(0, y, 0, area.bottom())
            c0 = QtGui.QColor(self.color); c0.setAlpha(240)
            c1 = QtGui.QColor(self.color); c1.setAlpha(60)
            grad.setColorAt(0, c0)
            grad.setColorAt(1, c1)
            path = QtGui.QPainterPath()
            path.addRoundedRect(QtCore.QRectF(x, y, bw, max(3.0, bh)), 5, 5)
            p.fillPath(path, QtGui.QBrush(grad))
        p.setPen(QtGui.QColor("#6b7488"))
        p.setFont(QtGui.QFont("Microsoft YaHei", 8))
        for i, lb in enumerate(self.labels[:n]):
            x = area.left() + i * (bw + gap)
            p.drawText(QtCore.QRectF(x, area.bottom() + 3, bw, 16), QtCore.Qt.AlignCenter, str(lb))
        p.end()


class _Bar(QtWidgets.QWidget):
    def __init__(self, frac, color):
        super().__init__()
        self.frac = max(0.03, min(1.0, frac))
        self.color = color
        self.setFixedHeight(8)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = self.rect()
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#1a2030"))
        p.drawRoundedRect(r, 4, 4)
        w = int(r.width() * self.frac)
        grad = QtGui.QLinearGradient(0, 0, max(1, w), 0)
        c1 = QtGui.QColor(self.color); c1.setAlpha(150)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, QtGui.QColor(self.color))
        p.setBrush(QtGui.QBrush(grad))
        p.drawRoundedRect(QtCore.QRect(r.left(), r.top(), w, r.height()), 4, 4)
        p.end()


class BreakdownBars(QtWidgets.QWidget):
    """横向标签进度条组:items = [(label, display, frac, color)]。"""

    def __init__(self, items):
        super().__init__()
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 2, 0, 0)
        v.setSpacing(14)
        for label, display, frac, color in items:
            top = QtWidgets.QHBoxLayout()
            l = QtWidgets.QLabel(label)
            l.setStyleSheet("color:#c3cbdf;font-size:12px;background:transparent;")
            num = QtWidgets.QLabel(str(display))
            num.setStyleSheet("color:#ffffff;font-weight:700;font-size:13px;background:transparent;")
            top.addWidget(l)
            top.addStretch()
            top.addWidget(num)
            v.addLayout(top)
            v.addWidget(_Bar(frac, color))
        v.addStretch()


class ActivityList(QtWidgets.QWidget):
    """最近动态:items = [(dot_color, text, time)]。"""

    def __init__(self, items):
        super().__init__()
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 2, 0, 0)
        v.setSpacing(13)
        for color, text, tm in items:
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(10)
            dot = QtWidgets.QLabel("")
            dot.setFixedSize(8, 8)
            dot.setStyleSheet("background:%s;border-radius:4px;" % color)
            t = QtWidgets.QLabel(text)
            t.setStyleSheet("color:#d2d8ea;font-size:12px;background:transparent;")
            t.setWordWrap(True)
            tl = QtWidgets.QLabel(tm)
            tl.setStyleSheet("color:#6b7488;font-size:11px;background:transparent;")
            row.addWidget(dot, 0, QtCore.Qt.AlignTop)
            row.addWidget(t, 1)
            row.addWidget(tl, 0, QtCore.Qt.AlignTop)
            v.addLayout(row)
        v.addStretch()


_PILL_COLORS = {
    "在线": "#22c55e", "就绪": "#22c55e", "有效": "#22c55e", "成功": "#22c55e", "已发布": "#22c55e", "正常": "#22c55e",
    "离线": "#64748b", "空闲": "#64748b", "未就绪": "#f59e0b", "待处理": "#f59e0b", "审核中": "#f59e0b", "排队中": "#f59e0b",
    "失效": "#ef4444", "失败": "#ef4444", "未通过": "#ef4444", "违规": "#ef4444", "异常": "#ef4444",
    "抖音": "#ec4899", "小红书": "#ef4444",
}


def pill(text, color=None):
    c = color or _PILL_COLORS.get(str(text).strip(), "#6b7488")
    lab = QtWidgets.QLabel(str(text))
    lab.setAlignment(QtCore.Qt.AlignCenter)
    lab.setStyleSheet(
        "background:%s;color:%s;border:1px solid %s;border-radius:9px;padding:3px 12px;font-size:11px;font-weight:700;"
        % (_rgba(c, 0.16), c, _rgba(c, 0.40)))
    return lab


def cell_pill(table, r, c, text, color=None):
    wrap = QtWidgets.QWidget()
    wrap.setStyleSheet("background:transparent;")
    h = QtWidgets.QHBoxLayout(wrap)
    h.setContentsMargins(10, 0, 10, 0)
    h.addWidget(pill(text, color))
    h.addStretch()
    table.setCellWidget(r, c, wrap)


def style_table(table, row_h=46):
    table.verticalHeader().setDefaultSectionSize(row_h)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setFocusPolicy(QtCore.Qt.NoFocus)
    table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)


class Bridge(QtCore.QObject):
    log_line = QtCore.Signal(str)
    logged_in = QtCore.Signal(bool, str)
    payload = QtCore.Signal(str, object)   # tag, data


BRIDGE = None


# ---------- pages ----------

class BasePage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.v = QtWidgets.QVBoxLayout(self)
        self.v.setContentsMargins(24, 22, 24, 22)
        self.v.setSpacing(14)

    def on_show(self):
        pass


HERO_VIDEO = os.path.join(data_dir(), "hero.mp4")


class VideoHero(QtWidgets.QFrame):
    """全宽影院式品牌 Hero:有 hero.mp4 则铺满背景循环播放,
    标题叠加其上;无视频时显示紫调渐变。用 QGraphicsVideoItem(非原生窗口),
    可被普通子控件叠加,规避原生 QVideoWidget 的覆盖限制。"""

    def __init__(self, on_generate=None):
        super().__init__()
        self.setObjectName("hero")
        self.setFixedHeight(216)
        self.setStyleSheet("QFrame#hero{border:1px solid #34305f;border-radius:18px;}")
        self._on_generate = on_generate
        self.player = None
        self.video_item = None

        # 背景层:QGraphicsView(渐变底 + 视频铺满)
        self.scene = QtWidgets.QGraphicsScene(self)
        self.view = QtWidgets.QGraphicsView(self.scene, self)
        self.view.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.view.setStyleSheet("background:transparent;border:0;")
        self.view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.view.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.view.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self._bg_item = self.scene.addRect(0, 0, 10, 10, QtGui.QPen(QtCore.Qt.NoPen))
        self._bg_item.setZValue(-2)
        self._shade = self.scene.addRect(0, 0, 10, 10, QtGui.QPen(QtCore.Qt.NoPen))
        self._shade.setZValue(0)

        # 叠加层:徽标 + 标题(在 view 之上)
        self.overlay = QtWidgets.QWidget(self)
        self.overlay.setStyleSheet("background:transparent;")
        ov = QtWidgets.QVBoxLayout(self.overlay)
        ov.setContentsMargins(32, 24, 32, 22)
        ov.setSpacing(8)
        self.badge = QtWidgets.QLabel("●  本地节点运行中 · 全域矩阵")
        self.badge.setStyleSheet("color:#7fe3c0;font-size:11px;font-weight:800;letter-spacing:1px;background:transparent;")
        title = QtWidgets.QLabel("云灵星图 · AI爆款复刻平台")
        title.setStyleSheet("font-size:29px;font-weight:800;color:#ffffff;background:transparent;")
        sub = QtWidgets.QLabel("本地浏览器 · 你的住宅 IP · 抖音 / 小红书多账号自动化增长")
        sub.setStyleSheet("color:#d2d8f2;font-size:13px;background:transparent;")
        ov.addWidget(self.badge)
        ov.addWidget(title)
        ov.addWidget(sub)
        self.status = QtWidgets.QLabel("")
        self.status.setStyleSheet("color:#d2d8f2;font-size:12px;background:transparent;")
        ov.addWidget(self.status)
        ov.addStretch()

        QtCore.QTimer.singleShot(300, self.try_load_video)

    def resizeEvent(self, e):
        r = self.rect()
        self.view.setGeometry(0, 0, r.width(), r.height())
        self.overlay.setGeometry(0, 0, r.width(), r.height())
        self.scene.setSceneRect(0, 0, r.width(), r.height())
        self._layout_bg(r.width(), r.height())
        super().resizeEvent(e)

    def _layout_bg(self, w, h):
        if w <= 0 or h <= 0:
            return
        grad = QtGui.QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QtGui.QColor("#2b2064"))
        grad.setColorAt(0.5, QtGui.QColor("#2c1b54"))
        grad.setColorAt(1.0, QtGui.QColor("#141a3e"))
        self._bg_item.setRect(0, 0, w, h)
        self._bg_item.setBrush(QtGui.QBrush(grad))
        # 左侧压暗,保证叠加文字清晰(有视频时更强)
        sg = QtGui.QLinearGradient(0, 0, w, 0)
        a0 = 165 if self.video_item is not None else 0
        c0 = QtGui.QColor(6, 8, 20); c0.setAlpha(a0)
        cm = QtGui.QColor(6, 8, 20); cm.setAlpha(int(a0 * 0.3))
        c1 = QtGui.QColor(6, 8, 20); c1.setAlpha(0)
        sg.setColorAt(0.0, c0); sg.setColorAt(0.6, cm); sg.setColorAt(1.0, c1)
        self._shade.setRect(0, 0, w, h)
        self._shade.setBrush(QtGui.QBrush(sg))
        if self.video_item is not None:
            self._fit_video(w, h)

    def _fit_video(self, w, h):
        vs = self.video_item.nativeSize()
        if not vs.isValid() or vs.width() <= 0 or vs.height() <= 0:
            self.video_item.setSize(QtCore.QSizeF(w, h))
            self.video_item.setPos(0, 0)
            return
        scale = max(w / vs.width(), h / vs.height())  # cover 铺满
        nw, nh = vs.width() * scale, vs.height() * scale
        self.video_item.setSize(QtCore.QSizeF(nw, nh))
        self.video_item.setPos((w - nw) / 2.0, (h - nh) / 2.0)

    def try_load_video(self):
        if self.player is not None or not os.path.exists(HERO_VIDEO):
            return
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
            self.video_item = QGraphicsVideoItem()
            self.video_item.setZValue(-1)
            self.scene.addItem(self.video_item)
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.audio.setMuted(True)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video_item)
            try:
                self.player.setLoops(QMediaPlayer.Loops.Infinite)
            except Exception:
                self.player.mediaStatusChanged.connect(self._loop)
            self.video_item.nativeSizeChanged.connect(lambda _s: self._layout_bg(self.width(), self.height()))
            self.player.setSource(QtCore.QUrl.fromLocalFile(HERO_VIDEO))
            self.player.play()
            self._layout_bg(self.width(), self.height())
            self.status.setText("")
        except Exception as ex:
            self.status.setText("视频组件不可用:%s" % str(ex)[:40])

    def _loop(self, st):
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            if st == QMediaPlayer.MediaStatus.EndOfMedia and self.player:
                self.player.setPosition(0)
                self.player.play()
        except Exception:
            pass

def _clear_layout(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.deleteLater()
        elif it.layout() is not None:
            _clear_layout(it.layout())


def _to_pct(v):
    try:
        return max(0.0, min(1.0, float(str(v).replace("%", "").strip()) / 100.0))
    except Exception:
        return 0.0


class DashboardPage(BasePage):
    def __init__(self):
        super().__init__()
        self._no_fade = True  # 含原生视频,跳过页面淡入(graphics effect 会破坏原生渲染)
        self.v.setSpacing(16)
        self.hero = VideoHero()
        self.v.addWidget(self.hero)
        self.refresh_btn = QtWidgets.QPushButton("刷新数据")
        self.refresh_btn.setObjectName("ghost")
        self.refresh_btn.clicked.connect(self.load)
        self.v.addWidget(make_header("企业中心", "多租户总览 · 账号 · 节点 · 任务 · 审计", [self.refresh_btn]))
        self.host = QtWidgets.QVBoxLayout()
        self.host.setSpacing(14)
        self.v.addLayout(self.host)
        self.v.addStretch()
        self._build({})
        BRIDGE.payload.connect(self._on)

    def on_show(self):
        self.load()

    def load(self):
        def work():
            _c, s = api("GET", "/api/enterprise/summary")
            _c2, u = api("GET", "/api/enterprise/usage")
            BRIDGE.payload.emit("dashboard", {"summary": s, "usage": u})
        run_bg(work)

    def _on(self, tag, d):
        if tag != "dashboard":
            return
        self._build(d or {})

    def _build(self, d):
        _clear_layout(self.host)
        s = (d or {}).get("summary") or {}
        u = (d or {}).get("usage") or {}
        counts = s.get("counts") or {}
        label_map = {"organizations": "客户企业", "orgs": "客户企业", "users": "企业用户",
                     "memberships": "团队成员", "nodes": "节点", "onlineNodes": "在线节点",
                     "nodesOnline": "在线节点", "accounts": "授权账号", "usableAccounts": "可用账号",
                     "offlineAccounts": "离线账号", "readyAccounts": "就绪账号", "tasks": "调度任务",
                     "audit": "审计事件", "auditLogs": "审计事件", "materials": "素材",
                     "leads": "客户线索", "queue": "发布队列", "queueCount": "发布队列"}
        cards = []
        for k, val in counts.items():
            if isinstance(val, (int, float, str)):
                cards.append((val, label_map.get(k, k)))
        if not cards:
            cards = [(u.get("accounts", 0), "授权账号"), (u.get("onlineNodes", 0), "在线节点"),
                     (u.get("usableAccounts", 0), "可用账号"), (u.get("offlineAccounts", 0), "离线账号"),
                     (u.get("materials", 0), "素材"), (u.get("queueCount", 0), "发布队列"),
                     (u.get("tasks24h", 0), "24h任务"), (u.get("leads", 0), "客户线索")]

        def cnt(*names):
            for nm in names:
                for (v, lb) in cards:
                    if lb == nm:
                        try:
                            return int(float(v))
                        except Exception:
                            return 0
            return 0

        # KPI 卡片网格
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(13)
        shown = cards[:8]
        for i, (num, lbl) in enumerate(shown):
            grid.addWidget(kpi_card(num, lbl), i // 4, i % 4)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        self.host.addLayout(grid)

        # 内容行:任务趋势 + 运行健康 + 账号分布
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(14)

        tasks = cnt("调度任务", "24h任务") or 280
        base = max(1, tasks // 7)
        vals = [int(base * x) for x in (0.72, 0.88, 1.05, 0.94, 1.2, 1.34, 1.06)]
        p1 = Panel("任务趋势", "近 7 天调度任务量")
        p1.body.addWidget(MiniBars(vals, ["一", "二", "三", "四", "五", "六", "日"], color="#8b5cf6"))
        row.addWidget(p1, 3)

        p2 = Panel("运行健康", "近 24 小时")
        p2.body.addWidget(BreakdownBars([
            ("成功率", u.get("successRate24h", "—"), _to_pct(u.get("successRate24h", 0)), "#22c55e"),
            ("节点在线率", u.get("nodeOnlineRate", "—"), _to_pct(u.get("nodeOnlineRate", 0)), "#6366f1"),
            ("账号就绪率", u.get("accountReadyRate", "—"), _to_pct(u.get("accountReadyRate", 0)), "#f59e0b"),
        ]))
        row.addWidget(p2, 2)

        auth, usable, offline = cnt("授权账号"), cnt("可用账号"), cnt("离线账号")
        mx = max(auth, usable, offline, 1)
        p3 = Panel("账号分布", "授权 / 可用 / 离线")
        p3.body.addWidget(BreakdownBars([
            ("授权账号", auth, auth / mx, "#8b5cf6"),
            ("可用账号", usable, usable / mx, "#14b8a6"),
            ("离线账号", offline, offline / mx, "#64748b"),
        ]))
        row.addWidget(p3, 2)
        self.host.addLayout(row)


class EnterpriseMembersPage(BasePage):
    """企业中心内的成员管理页，服务端仍负责最终权限校验。"""

    def __init__(self):
        super().__init__()
        self._loading_orgs = False
        self._busy = False
        self._summary = {}
        self._pending_org_id = ""

        self.refresh_btn = QtWidgets.QPushButton("刷新")
        self.refresh_btn.setObjectName("ghost")
        self.refresh_btn.clicked.connect(self.load)
        self.create_org_btn = QtWidgets.QPushButton("添加企业")
        self.create_org_btn.setObjectName("ghost")
        self.create_org_btn.clicked.connect(self.create_enterprise)
        self.create_org_btn.setVisible(product_role() == "platform_admin")
        self.add_btn = QtWidgets.QPushButton("添加成员")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self.add_member)
        self.invite_btn = QtWidgets.QPushButton("邀请成员")
        self.invite_btn.setObjectName("ghost")
        self.invite_btn.clicked.connect(self.invite_member)
        self.v.addWidget(make_header(
            "团队成员",
            "管理员可切换企业；企业家仅管理自己企业内的成员。",
            [self.refresh_btn, self.create_org_btn, self.add_btn, self.invite_btn],
        ))

        selector = QtWidgets.QHBoxLayout()
        selector.setSpacing(8)
        selector.addWidget(QtWidgets.QLabel("当前企业:"))
        self.org_combo = QtWidgets.QComboBox()
        self.org_combo.setMinimumWidth(260)
        self.org_combo.currentIndexChanged.connect(self._org_changed)
        selector.addWidget(self.org_combo)
        selector.addStretch()
        self.v.addLayout(selector)
        self.org_combo.setVisible(product_role() == "platform_admin")
        selector.itemAt(0).widget().setVisible(product_role() == "platform_admin")

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["成员", "登录账号", "角色", "状态", "所属企业", "操作"])
        style_table(self.table, row_h=52)
        self.table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.Fixed)
        self.table.setColumnWidth(5, 174)
        self.table.setMinimumHeight(300)
        self.v.addWidget(self.table, 1)

        self.invite_status = QtWidgets.QLabel("")
        self.invite_status.setObjectName("sub")
        self.v.addWidget(self.invite_status)
        BRIDGE.payload.connect(self._on)

    def on_show(self):
        self.load()

    def _selected_org(self):
        value = self.org_combo.currentData()
        return str(value or current_org()).strip() or "org-default"

    def _org_changed(self, _index):
        if not self._loading_orgs:
            self.load()

    def _set_busy(self, busy):
        self._busy = bool(busy)
        self.refresh_btn.setEnabled(not busy)
        self.create_org_btn.setEnabled(not busy)
        self.add_btn.setEnabled(not busy)
        self.invite_btn.setEnabled(not busy)
        self.org_combo.setEnabled(not busy)

    def load(self):
        if self._busy:
            return
        self._set_busy(True)
        requested_org = self._selected_org()

        def work():
            _code, summary = api("GET", "/api/enterprise/summary")
            _invite_code, invites = api("GET", "/api/enterprise/invites" + "?orgId=" + quote(requested_org, safe=""))
            BRIDGE.payload.emit("team_members_load", {
                "orgId": requested_org,
                "summary": summary,
                "invites": invites,
            })

        run_bg(work)

    def _populate_orgs(self, summary):
        organizations = [x for x in (summary.get("organizations") or []) if isinstance(x, dict)]
        selected = self._pending_org_id or self._selected_org()
        self._pending_org_id = ""
        self._loading_orgs = True
        try:
            self.org_combo.clear()
            for org in organizations:
                org_id = str(org.get("id") or "").strip()
                if org_id:
                    self.org_combo.addItem(str(org.get("name") or org_id), org_id)
            if self.org_combo.count() == 0:
                self.org_combo.addItem(selected, selected)
            index = self.org_combo.findData(selected)
            self.org_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self._loading_orgs = False

    def _build_rows(self, summary):
        self.table.setRowCount(0)
        org_id = self._selected_org()
        org_names = {
            str(x.get("id") or ""): str(x.get("name") or x.get("id") or "")
            for x in (summary.get("organizations") or [])
            if isinstance(x, dict)
        }
        users = {
            str(x.get("id") or ""): x
            for x in (summary.get("users") or [])
            if isinstance(x, dict)
        }
        memberships = [
            x for x in (summary.get("memberships") or [])
            if isinstance(x, dict) and str(x.get("orgId") or "") == org_id
        ]
        memberships.sort(key=lambda x: (str(x.get("role") or ""), str(x.get("userId") or "")))
        role_names = {"owner": "企业家", "admin": "企业家", "member": "普通用户", "auditor": "查看员"}
        for membership in memberships:
            user_id = str(membership.get("userId") or "")
            user = users.get(user_id) or {"id": user_id}
            row = self.table.rowCount()
            self.table.insertRow(row)
            identifier = user.get("phone") or user.get("email") or user_id or "-"
            role = str(membership.get("role") or "member").lower()
            status = str(membership.get("status") or user.get("status") or "active").lower()
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(user.get("name") or user_id or "-")))
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(identifier)))
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(role_names.get(role, role)))
            cell_pill(self.table, row, 3, "已启用" if status == "active" else "已停用",
                      "#22c55e" if status == "active" else "#ef4444")
            self.table.setItem(row, 4, QtWidgets.QTableWidgetItem(org_names.get(org_id, org_id)))

            actions = QtWidgets.QWidget()
            action_layout = QtWidgets.QHBoxLayout(actions)
            action_layout.setContentsMargins(6, 0, 6, 0)
            action_layout.setSpacing(6)
            reset_btn = QtWidgets.QPushButton("重置密码")
            reset_btn.setObjectName("ghost")
            reset_btn.setFixedWidth(82)
            reset_btn.clicked.connect(lambda _=False, uid=user_id: self.reset_password(uid))
            status_btn = QtWidgets.QPushButton("恢复" if status != "active" else "停用")
            status_btn.setObjectName("ghost")
            status_btn.setFixedWidth(58)
            status_btn.clicked.connect(
                lambda _=False, uid=user_id, active=(status == "active"): self.change_status(uid, active)
            )
            action_layout.addWidget(reset_btn)
            action_layout.addWidget(status_btn)
            action_layout.addStretch()
            self.table.setCellWidget(row, 5, actions)

    def _on(self, tag, data):
        if tag == "team_members_load":
            self._set_busy(False)
            data = data or {}
            summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
            if not summary.get("ok"):
                self.invite_status.setText("成员数据加载失败：" + str(summary.get("error") or "请检查登录状态"))
                return
            self._summary = summary
            self._populate_orgs(summary)
            if str(data.get("orgId") or "") != self._selected_org():
                self.load()
                return
            self._build_rows(summary)
            invites = data.get("invites") if isinstance(data.get("invites"), dict) else {}
            counts = invites.get("counts") or {}
            if invites.get("ok"):
                self.invite_status.setText(
                    "待接受邀请 %s 条，已接受 %s 条。" % (
                        counts.get("active", 0), counts.get("accepted", 0)
                    )
                )
            else:
                self.invite_status.setText("邀请记录加载失败：" + str(invites.get("error") or "无权限"))
        elif tag == "team_members_action":
            self._set_busy(False)
            data = data or {}
            response = data.get("response") if isinstance(data.get("response"), dict) else {}
            if not response.get("ok"):
                QtWidgets.QMessageBox.warning(
                    self, "操作失败", str(response.get("error") or "请稍后重试")
                )
                return
            action = data.get("action") or ""
            if action == "reset":
                credential = response.get("credential") or {}
                self._show_copy_dialog(
                    "已重置密码",
                    "登录账号：%s\n临时密码：%s\n\n请将临时密码交给该成员，并要求其首次登录后修改。"
                    % (credential.get("identifier") or "-", credential.get("initialPassword") or "-"),
                )
            elif action == "invite":
                self._show_copy_dialog(
                    "邀请已创建",
                    "邀请码：\n%s\n\n请通过可信渠道发送给对方，对方在本地客户端登录页选择“加入企业”。"
                    % (response.get("inviteCode") or "-"),
                )
            elif action == "add":
                QtWidgets.QMessageBox.information(self, "添加成员", "成员已加入当前企业。")
            elif action == "create_org":
                organization = response.get("organization") or {}
                self._pending_org_id = str(organization.get("id") or "").strip()
                QtWidgets.QMessageBox.information(self, "添加企业", "企业已创建。")
            elif action == "status":
                QtWidgets.QMessageBox.information(self, "成员状态", "成员状态已更新。")
            self.load()

    def _post_action(self, action, path, body):
        if self._busy:
            return
        self._set_busy(True)

        def work():
            code, response = api("POST", path, body)
            BRIDGE.payload.emit("team_members_action", {
                "action": action,
                "httpStatus": code,
                "response": response,
            })

        run_bg(work)

    def _show_copy_dialog(self, title, text):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(560, 250)
        layout = QtWidgets.QVBoxLayout(dialog)
        content = QtWidgets.QPlainTextEdit()
        content.setPlainText(text)
        content.setReadOnly(True)
        layout.addWidget(content, 1)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        copy_btn = QtWidgets.QPushButton("复制")
        copy_btn.setObjectName("ghost")
        copy_btn.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(content.toPlainText()))
        close_btn = QtWidgets.QPushButton("关闭")
        close_btn.setObjectName("primary")
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(copy_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        dialog.exec()

    def create_enterprise(self):
        if product_role() != "platform_admin":
            QtWidgets.QMessageBox.warning(self, "无权操作", "只有管理员可以添加企业。")
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("添加企业")
        dialog.resize(460, 240)
        layout = QtWidgets.QVBoxLayout(dialog)
        form = QtWidgets.QFormLayout()
        name = QtWidgets.QLineEdit()
        name.setPlaceholderText("例如：丰田汽车")
        org_id = QtWidgets.QLineEdit()
        org_id.setPlaceholderText("可留空，系统自动生成")
        form.addRow("企业名称", name)
        form.addRow("企业 ID", org_id)
        layout.addLayout(form)
        tip = QtWidgets.QLabel("创建后可在当前企业下拉框中选择，再添加企业家和普通用户。")
        tip.setObjectName("sub")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("创建")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        enterprise_name = name.text().strip()
        if not enterprise_name:
            QtWidgets.QMessageBox.warning(self, "无法添加", "请填写企业名称。")
            return
        body = {"name": enterprise_name, "plan": "standard", "status": "active"}
        if org_id.text().strip():
            body["id"] = org_id.text().strip()
        self._post_action("create_org", "/api/enterprise/orgs/upsert", body)

    def add_member(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("添加企业成员")
        dialog.resize(460, 360)
        layout = QtWidgets.QVBoxLayout(dialog)
        form = QtWidgets.QFormLayout()
        name = QtWidgets.QLineEdit()
        phone = QtWidgets.QLineEdit()
        email = QtWidgets.QLineEdit()
        password = QtWidgets.QLineEdit()
        password.setEchoMode(QtWidgets.QLineEdit.Password)
        password.setPlaceholderText("可留空，后续可用“重置密码”生成临时密码")
        role = QtWidgets.QComboBox()
        role.addItem("普通用户", "member")
        if product_role() == "platform_admin":
            role.addItem("企业家", "admin")
        form.addRow("姓名", name)
        form.addRow("手机号", phone)
        form.addRow("邮箱", email)
        form.addRow("初始密码", password)
        form.addRow("成员角色", role)
        layout.addLayout(form)
        tip = QtWidgets.QLabel("至少填写手机号或邮箱，作为该成员的登录账号。")
        tip.setObjectName("sub")
        layout.addWidget(tip)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("添加")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        if not name.text().strip():
            QtWidgets.QMessageBox.warning(self, "无法添加", "请填写成员姓名。")
            return
        if not (phone.text().strip() or email.text().strip()):
            QtWidgets.QMessageBox.warning(self, "无法添加", "请至少填写手机号或邮箱。")
            return
        self._post_action("add", "/api/enterprise/users/upsert", {
            "orgId": self._selected_org(),
            "name": name.text().strip(),
            "phone": phone.text().strip(),
            "email": email.text().strip(),
            "password": password.text(),
            "role": role.currentData() or "member",
        })

    def invite_member(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("邀请企业成员")
        dialog.resize(460, 340)
        layout = QtWidgets.QVBoxLayout(dialog)
        form = QtWidgets.QFormLayout()
        name = QtWidgets.QLineEdit()
        phone = QtWidgets.QLineEdit()
        email = QtWidgets.QLineEdit()
        ttl = QtWidgets.QSpinBox()
        ttl.setRange(1, 24 * 30)
        ttl.setValue(168)
        ttl.setSuffix(" 小时")
        role = QtWidgets.QComboBox()
        role.addItem("普通用户", "member")
        if product_role() == "platform_admin":
            role.addItem("企业家", "admin")
        form.addRow("受邀人姓名", name)
        form.addRow("手机号", phone)
        form.addRow("邮箱", email)
        form.addRow("成员角色", role)
        form.addRow("邀请码有效期", ttl)
        layout.addLayout(form)
        tip = QtWidgets.QLabel("至少填写手机号或邮箱；创建后复制邀请码发送给对方。")
        tip.setObjectName("sub")
        layout.addWidget(tip)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("创建邀请")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        if not (phone.text().strip() or email.text().strip()):
            QtWidgets.QMessageBox.warning(self, "无法邀请", "请至少填写手机号或邮箱。")
            return
        self._post_action("invite", "/api/enterprise/invites/create", {
            "orgId": self._selected_org(),
            "recipientName": name.text().strip(),
            "phone": phone.text().strip(),
            "email": email.text().strip(),
            "role": role.currentData() or "member",
            "ttlHours": ttl.value(),
        })

    def reset_password(self, user_id):
        if not user_id:
            return
        answer = QtWidgets.QMessageBox.question(
            self, "重置密码", "确定为该成员生成新的临时密码吗？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        self._post_action("reset", "/api/enterprise/users/reset-password", {
            "orgId": self._selected_org(),
            "userId": user_id,
        })

    def change_status(self, user_id, currently_active):
        if not user_id:
            return
        action = "disable" if currently_active else "enable"
        message = "停用后，该成员当前会话将失效。确定继续吗？" if currently_active else "确定恢复该成员吗？"
        answer = QtWidgets.QMessageBox.question(
            self, "成员状态", message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        self._post_action("status", "/api/enterprise/users/status", {
            "orgId": self._selected_org(),
            "userId": user_id,
            "action": action,
        })


PLATFORM_META = {
    "douyin": ("抖音", "🎵", "#ec4899"), "抖音": ("抖音", "🎵", "#ec4899"),
    "xhs": ("小红书", "📕", "#ef4444"), "xiaohongshu": ("小红书", "📕", "#ef4444"), "小红书": ("小红书", "📕", "#ef4444"),
}


class _OptionRow(QtWidgets.QFrame):
    """浮层里的一张可点选项卡:整卡可点、悬停高亮描边+浮起。"""
    clicked = QtCore.Signal()

    def __init__(self, accent):
        super().__init__()
        self.setObjectName("optRow")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._base = ("QFrame#optRow{background:%s;border:1px solid %s;border-radius:13px;}"
                      % (("#f5f7fb" if is_light() else "rgba(255,255,255,0.022)"),
                         ("#e2e7f0" if is_light() else "rgba(255,255,255,0.06)")))
        self._hover = ("QFrame#optRow{background:%s;border:1px solid %s;border-radius:13px;}"
                       % (_rgba(accent, 0.16), _rgba(accent, 0.55)))
        self.setStyleSheet(self._base)

    def enterEvent(self, e):
        self.setStyleSheet(self._hover)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setStyleSheet(self._base)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class LoginModePopup(QtWidgets.QWidget):
    """点"登录/添加"按钮弹出的漂亮两选浮层:① 获取本机已登录账号  ② 添加新账号(全新浏览器)。
    用 Qt.Popup 实现点外部自动关闭;整体玻璃卡 + 投影 + 两张富选项卡。"""

    def __init__(self, platform_key, platform_name, accent, on_login, anchor=None):
        super().__init__(anchor, QtCore.Qt.Popup)
        # 不用 WA_TranslucentBackground:部分 Windows 下 Qt.Popup 的透明外边距会渲染成黑框。
        # 改为不透明 + 背景取当前主题卡片色,与圆角卡自然融合,不再有黑边。
        self.setAutoFillBackground(True)
        _pal = self.palette()
        _pal.setColor(QtGui.QPalette.Window, QtGui.QColor("#ffffff" if is_light() else "#161a28"))
        self.setPalette(_pal)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self._pk = platform_key
        self._on_login = on_login
        self.setFixedWidth(340)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QtWidgets.QFrame()
        card.setObjectName("popupCard")
        _pc_bg = "#ffffff" if is_light() else "#161a28"
        _pc_bd = TK["cardBorder"] if is_light() else "rgba(255,255,255,0.09)"
        card.setStyleSheet("QFrame#popupCard{background:%s;border:1px solid %s;border-radius:18px;}" % (_pc_bg, _pc_bd))
        cv = QtWidgets.QVBoxLayout(card)
        cv.setContentsMargins(14, 14, 14, 14)
        cv.setSpacing(10)
        title = QtWidgets.QLabel("选择登录 %s 的方式" % platform_name)
        title.setStyleSheet("color:%s;font-size:12px;font-weight:800;background:transparent;padding:2px 4px 4px 4px;" % TK["text"])
        cv.addWidget(title)
        cv.addWidget(self._option("reuse", "device", "#22c55e", "获取本机已登录账号",
                                   "读取本机浏览器里已登录好的账号,直接入矩阵"))
        cv.addWidget(self._option("fresh", "plus", accent or "#8b5cf6", "添加新账号（全新浏览器）",
                                   "打开全新、不带任何登录状态的浏览器,登录另一个账号"))
        outer.addWidget(card)

    def _round_mask(self):
        # 把窗口物理裁成圆角:不透明矩形窗的四角(圆角卡之外)在真机上会露出深色 → 黑边;
        # setMask 后窗口本身就是圆角形状,任何背景下都不再有黑角(比 WA_TranslucentBackground 稳,
        # 后者在部分 Windows 上反而渲染成黑框)。
        r = self.rect()
        if r.width() <= 0 or r.height() <= 0:
            return
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(r), 18.0, 18.0)
        self.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._round_mask()

    def showEvent(self, e):
        super().showEvent(e)
        self._round_mask()

    def _option(self, mode, icon_kind, accent, title, desc):
        row = _OptionRow(accent)
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(13, 12, 12, 12)
        h.setSpacing(13)
        chip = QtWidgets.QLabel()
        chip.setFixedSize(40, 40)
        chip.setAlignment(QtCore.Qt.AlignCenter)
        chip.setStyleSheet("background:%s;border:1px solid %s;border-radius:11px;"
                           % (_rgba(accent, 0.16), _rgba(accent, 0.42)))
        chip.setPixmap(_draw_icon(icon_kind, 21, accent))
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(3)
        t = QtWidgets.QLabel(title)
        t.setStyleSheet("color:%s;font-size:14px;font-weight:800;background:transparent;" % TK["text"])
        d = QtWidgets.QLabel(desc)
        d.setStyleSheet("color:%s;font-size:11px;background:transparent;" % TK["sub"])
        d.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(d)
        arrow = QtWidgets.QLabel("›")
        arrow.setStyleSheet("color:#6b7488;font-size:22px;font-weight:700;background:transparent;")
        h.addWidget(chip, 0, QtCore.Qt.AlignTop)
        h.addLayout(col, 1)
        h.addWidget(arrow, 0, QtCore.Qt.AlignVCenter)
        row.clicked.connect(lambda: self._pick(mode))
        return row

    def _pick(self, mode):
        self.close()
        self._on_login(self._pk, mode)

    @staticmethod
    def pop_under(button, platform_key, platform_name, accent, on_login):
        pop = LoginModePopup(platform_key, platform_name, accent, on_login, button)
        pop.adjustSize()
        gp = button.mapToGlobal(QtCore.QPoint(0, button.height() + 4))
        x = gp.x() + (button.width() - pop.width()) // 2
        pop.move(max(gp.x() - 40, x), gp.y())
        pop.show()
        return pop


class PlatformCard(HoverCard):
    """账号矩阵单个平台卡:平台头 + 账号行(状态胶囊)+ 就绪/登录按钮 + 提示。"""

    def __init__(self, platform_key, accounts, on_login, on_delete=None):
        super().__init__("card", rest_blur=20, hover_blur=34, rest_dy=9, hover_dy=17, alpha=80)
        name, icon, color = PLATFORM_META.get(platform_key, (platform_key, "🌐", "#6366f1"))
        pk = "douyin" if name == "抖音" else ("xhs" if name == "小红书" else platform_key)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QtWidgets.QFrame()
        bar.setFixedHeight(3)
        bar.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 %s, stop:1 %s);"
                          "border-top-left-radius:16px;border-top-right-radius:16px;" % (color, _rgba(color, 0.2)))
        outer.addWidget(bar)
        inner = QtWidgets.QWidget()
        inner.setStyleSheet("background:transparent;")
        v = QtWidgets.QVBoxLayout(inner)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(13)
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(12)
        chip = QtWidgets.QLabel()
        chip.setFixedSize(44, 44)
        chip.setAlignment(QtCore.Qt.AlignCenter)
        logo = platform_logo(pk, 44)
        if logo is not None:  # 真实官方 app 图标(自带圆角底色),不加额外底框
            chip.setStyleSheet("background:transparent;")
            chip.setPixmap(logo)
        else:
            chip.setStyleSheet("background:%s;border:1px solid %s;border-radius:12px;"
                               % (_rgba(color, 0.16), _rgba(color, 0.42)))
            chip.setPixmap(_draw_icon(pk, 24, color))
        htext = QtWidgets.QVBoxLayout()
        htext.setSpacing(1)
        nm = QtWidgets.QLabel(name)
        nm.setStyleSheet("font-size:16px;font-weight:800;color:#ffffff;background:transparent;")
        cnt = QtWidgets.QLabel("%d 个授权账号" % len(accounts))
        cnt.setStyleSheet("color:#8b93a3;font-size:12px;background:transparent;")
        htext.addWidget(nm)
        htext.addWidget(cnt)
        head.addWidget(chip)
        head.addLayout(htext)
        head.addStretch()
        v.addLayout(head)
        st_map = {"online": "在线", "offline": "离线", "idle": "空闲", "ready": "就绪"}
        ready = False
        if accounts:
            for a in accounts:
                st = a.get("status") or ("online" if a.get("online") else "offline")
                st_cn = st_map.get(str(st), str(st))
                if st_cn in ("在线", "就绪"):
                    ready = True
                row = QtWidgets.QHBoxLayout()
                row.setSpacing(10)
                ic = QtWidgets.QLabel()
                ic.setFixedSize(30, 30)
                ic.setAlignment(QtCore.Qt.AlignCenter)
                rlogo = platform_logo(pk, 30)
                if rlogo is not None:
                    ic.setStyleSheet("background:transparent;")
                    ic.setPixmap(rlogo)
                else:
                    ic.setStyleSheet("background:%s;border-radius:8px;" % _rgba(color, 0.16))
                    ic.setPixmap(_draw_icon(pk, 16, color))
                acol = QtWidgets.QVBoxLayout()
                acol.setSpacing(0)
                an = QtWidgets.QLabel(a.get("name") or a.get("nickname") or a.get("handle")
                                      or a.get("displayName") or a.get("title") or a.get("account")
                                      or a.get("uid") or (name + "账号"))
                an.setStyleSheet("color:%s;font-size:13px;font-weight:600;background:transparent;" % TK["text"])
                node = QtWidgets.QLabel(str(a.get("node") or a.get("nodeId") or a.get("id") or "-"))
                node.setStyleSheet("color:#6b7488;font-size:11px;background:transparent;")
                acol.addWidget(an)
                acol.addWidget(node)
                row.addWidget(ic)
                row.addLayout(acol)
                row.addStretch()
                row.addWidget(pill(st_cn))
                aid = a.get("id") or a.get("nodeId") or ""
                if on_delete and aid:
                    delb = QtWidgets.QPushButton("×")
                    delb.setObjectName("iconbtn")
                    delb.setFixedSize(24, 24)
                    delb.setCursor(QtCore.Qt.PointingHandCursor)
                    delb.setToolTip("从矩阵移除该账号（不影响本机浏览器登录态）")
                    delb.clicked.connect(lambda _=False, i=aid, nm=an.text(): self._confirm_delete(i, nm, on_delete))
                    row.addWidget(delb)
                v.addLayout(row)
        else:
            empty = QtWidgets.QLabel("暂无授权账号,点下方登录")
            empty.setStyleSheet("color:#6b7488;font-size:12px;background:transparent;padding:8px 0;")
            v.addWidget(empty)
        btn = QtWidgets.QPushButton("＋  登录 / 添加 %s 账号" % name)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setMinimumHeight(40)
        btn.setStyleSheet("QPushButton{background:%s;color:#ffffff;border:0;border-radius:10px;"
                          "padding:10px 16px;font-weight:700;}QPushButton:hover{background:%s;}"
                          % (TK["accent"], TK["accent2"]))
        btn.clicked.connect(lambda: LoginModePopup.pop_under(btn, pk, name, color, on_login))
        v.addWidget(btn)
        hint = QtWidgets.QLabel("① 读取本机浏览器里已登录的账号  ·  ② 用全新浏览器登录另一个账号")
        hint.setStyleSheet("color:#6b7488;font-size:11px;background:transparent;")
        hint.setAlignment(QtCore.Qt.AlignCenter)
        hint.setWordWrap(True)
        v.addWidget(hint)
        outer.addWidget(inner)
        wire_animations(inner)

    def _confirm_delete(self, account_id, name, on_delete):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("从矩阵移除账号")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText("确定从账号矩阵移除「%s」吗？" % (name or account_id))
        box.setInformativeText("只移除矩阵里的这条记录，不会退出你本机浏览器里的登录。")
        yes = box.addButton("移除", QtWidgets.QMessageBox.YesRole)
        box.addButton("取消", QtWidgets.QMessageBox.NoRole)
        box.exec()
        if box.clickedButton() is yes:
            on_delete(account_id, name)


class AccountsPage(BasePage):
    def __init__(self):
        super().__init__()
        self.v.setSpacing(16)
        self.b_ref = QtWidgets.QPushButton("刷新")
        self.b_ref.setObjectName("ghost")
        self.b_ref.clicked.connect(self.load)
        self.v.addWidget(make_header("账号矩阵", "本机浏览器 + 你的住宅 IP 登录,账号自动入矩阵",
                                     [self.b_ref]))
        self.hint = QtWidgets.QLabel("")
        self.hint.setObjectName("sub")
        self.v.addWidget(self.hint)
        self.host = QtWidgets.QVBoxLayout()
        self.host.setSpacing(14)
        self.v.addLayout(self.host)
        self.v.addStretch()
        self._build([])
        BRIDGE.payload.connect(self._on)

    def on_show(self):
        self.load()

    def load(self):
        def work():
            _c, j = api("GET", "/api/accounts")
            arr = j if isinstance(j, list) else (j.get("value") or j.get("accounts") or [])
            BRIDGE.payload.emit("accounts", clean_accounts(arr if isinstance(arr, list) else []))
        run_bg(work)

    def login(self, platform, mode="reuse"):
        label = "抖音" if platform == "douyin" else "小红书"
        if mode == "fresh":
            self.hint.setText("正在打开【全新浏览器】(不带任何已登录状态),请在弹出的窗口里扫码/登录要添加的%s新账号…" % label)
        else:
            self.hint.setText("正在本机浏览器读取已登录的%s账号,请稍候…" % label)
        run_bg(lambda: BRIDGE.payload.emit("acct_login", submit_local_task(platform + ".login", {"fresh": mode == "fresh"}, 300)))

    def delete(self, account_id, name=""):
        self.hint.setText("正在移除账号「%s」…" % (name or account_id))

        def work():
            code, j = api("POST", "/api/accounts/remove", {"id": account_id})
            ok = isinstance(j, dict) and j.get("ok")
            BRIDGE.payload.emit("acct_delete", {"ok": bool(ok), "id": account_id, "name": name,
                                                "error": (j or {}).get("error") or ("http_%s" % code)})
        run_bg(work)

    def _on(self, tag, d):
        if tag == "accounts":
            self._build(d if isinstance(d, list) else [])
        elif tag == "acct_login":
            rr = (d or {}).get("result") or {}
            ok = (d.get("status") == "done") and (rr.get("loggedIn") or rr.get("ok"))
            self.hint.setText("登录成功,账号已入矩阵。" if ok else ("登录未完成:" + str(d.get("error") or rr.get("error") or "")))
            if ok:
                self.load()
        elif tag == "acct_delete":
            if (d or {}).get("ok"):
                self.hint.setText("已移除账号「%s」。" % ((d or {}).get("name") or (d or {}).get("id")))
                self.load()
            else:
                self.hint.setText("移除失败:" + str((d or {}).get("error") or ""))

    def _build(self, accounts):
        _clear_layout(self.host)
        accounts = clean_accounts(accounts)

        def plat_of(a):
            p = str(a.get("platform") or "")
            if p in ("douyin", "抖音"):
                return "douyin"
            if p in ("xhs", "xiaohongshu", "小红书"):
                return "xhs"
            return p or "douyin"
        groups = {"douyin": [], "xhs": []}
        for a in accounts:
            groups.setdefault(plat_of(a), []).append(a)

        used = sum(1 for k in groups if groups.get(k))
        total = len(accounts)
        followers = sum(int(a.get("followers") or a.get("fans") or 0) for a in accounts)
        today = sum(int(a.get("publishedToday") or a.get("todayPublish") or 0) for a in accounts)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(13)
        for i, (num, lbl) in enumerate([(used or 2, "接入平台"), (total, "授权账号"),
                                        (followers, "总粉丝量"), (today, "今日发布")]):
            grid.addWidget(kpi_card(num, lbl), 0, i)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        self.host.addLayout(grid)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(14)
        for pk in ("douyin", "xhs"):
            card = PlatformCard(pk, groups.get(pk, []), self.login, self.delete)
            card.setMaximumWidth(500)
            row.addWidget(card, 1, QtCore.Qt.AlignTop)
        row.addStretch(1)
        self.host.addLayout(row)


class TablePage(BasePage):
    """通用列表页(素材/知识库等)。"""
    def __init__(self, title, subtitle, endpoint, columns, extract):
        super().__init__()
        self.endpoint = endpoint
        self.columns = columns
        self.extract = extract
        self.b_ref = QtWidgets.QPushButton("刷新")
        self.b_ref.setObjectName("ghost")
        self.b_ref.clicked.connect(self.load)
        self.v.addWidget(make_header(title, subtitle, [self.b_ref]))
        self.table = QtWidgets.QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        style_table(self.table)
        self.v.addWidget(self.table)
        self.tag = "table:" + endpoint
        BRIDGE.payload.connect(self._on)

    def on_show(self):
        self.load()

    def load(self):
        def work():
            _c, j = api("GET", self.endpoint)
            arr = j if isinstance(j, list) else (j.get("value") or j.get("items") or j.get("docs") or j.get("list") or [])
            BRIDGE.payload.emit(self.tag, arr if isinstance(arr, list) else [])
        run_bg(work)

    def _on(self, tag, d):
        if tag != self.tag:
            return
        self.table.setRowCount(0)
        for it in d:
            row = self.extract(it) if isinstance(it, dict) else None
            if not row:
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, val in enumerate(row):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(str(val)))


class FinderPage(BasePage):
    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("寻找线索", "搜关键词 → 读评论 → 识别意向客户与主页链接(本机浏览器执行)"))
        row = QtWidgets.QHBoxLayout()
        self.kw = QtWidgets.QLineEdit()
        self.kw.setPlaceholderText("产品关键词,例如:化妆品")
        self.platform = QtWidgets.QComboBox()
        self.platform.addItems(["抖音", "小红书"])
        self.num = QtWidgets.QSpinBox()
        self.num.setRange(1, 20)
        self.num.setValue(5)
        self.num.setPrefix("视频数 ")
        self.btn = QtWidgets.QPushButton("开始寻客")
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(self.run)
        row.addWidget(self.kw, 3)
        row.addWidget(self.platform)
        row.addWidget(self.num)
        row.addWidget(self.btn)
        self.v.addLayout(row)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("sub")
        self.v.addWidget(self.status)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["用户", "主页链接", "意向", "评论"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.cellDoubleClicked.connect(self._open_profile)
        self.v.addWidget(self.table)
        BRIDGE.payload.connect(self._on)

    def _lead_profile_url(self, lead):
        if not isinstance(lead, dict):
            return ""
        u = (lead.get("profileUrl") or lead.get("userUrl") or lead.get("user_url") or lead.get("homepage") or "").strip()
        if not u:
            sec = str(lead.get("secUid") or lead.get("sec_uid") or "").strip()
            if sec:
                u = "https://www.douyin.com/user/" + sec
        return u

    def _open_profile(self, row, col):
        if col != 1:
            return
        it = self.table.item(row, 1)
        u = it.text().strip() if it else ""
        if u and u != "-":
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(u))

    def run(self):
        kw = self.kw.text().strip()
        if not kw:
            self.status.setText("请输入关键词")
            return
        self.btn.setEnabled(False)
        self.status.setText("寻客中…(在你本机浏览器执行,请稍候)")
        platform = "xhs" if self.platform.currentText() == "小红书" else "douyin"
        payload = {"keyword": kw, "videoNum": self.num.value(), "commentMode": "page", "platform": platform}
        run_bg(lambda: BRIDGE.payload.emit("finder", submit_local_task("finder.discover", payload, 300)))

    def _on(self, tag, d):
        if tag != "finder":
            return
        self.btn.setEnabled(True)
        rr = (d or {}).get("result") or {}
        leads = d.get("leads") or rr.get("leads") or []
        if d.get("status") != "done":
            self.status.setText("未完成:" + str(d.get("error") or rr.get("error") or "(客户端可能还没连上或需先登录账号)"))
            return
        self.table.setRowCount(0)
        for x in leads:
            if not isinstance(x, dict):
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            profile_url = self._lead_profile_url(x)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(x.get("user") or x.get("u") or "-")))
            url_item = QtWidgets.QTableWidgetItem(profile_url or "-")
            url_item.setToolTip(profile_url or "")
            self.table.setItem(r, 1, url_item)
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(str(x.get("intent") or "-")))
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(x.get("text") or x.get("c") or "")))
        self.status.setText("完成:识别到 %d 个意向客户" % len(leads))


class OutreachPage(BasePage):
    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("AI 触达", "对意向客户在其视频/笔记下批量评论触达(本机浏览器执行)"))
        row = QtWidgets.QHBoxLayout()
        self.kw = QtWidgets.QLineEdit()
        self.kw.setPlaceholderText("产品关键词")
        self.btn = QtWidgets.QPushButton("开始触达")
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(self.run)
        row.addWidget(self.kw, 3)
        row.addWidget(self.btn)
        self.v.addLayout(row)
        self.status = QtWidgets.QLabel("提示:会在筛出的意向客户的视频/笔记下发起评论触达(非私信),请确保账号已登录并遵守平台规则。")
        self.status.setObjectName("sub")
        self.v.addWidget(self.status)
        self.v.addStretch()
        BRIDGE.payload.connect(self._on)

    def run(self):
        self.btn.setEnabled(False)
        self.status.setText("触达任务已下发到本机执行…")
        run_bg(lambda: BRIDGE.payload.emit("outreach", submit_local_task("outreach.run", {"keyword": self.kw.text().strip()}, 300)))

    def _on(self, tag, d):
        if tag != "outreach":
            return
        self.btn.setEnabled(True)
        ok = d.get("status") == "done"
        self.status.setText("触达完成。" if ok else ("未完成:" + str(d.get("error") or "")))


class GrowthPage(BasePage):
    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("获客中心", "寻找线索 · AI 触达"))
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(FinderPage(), "寻找线索")
        tabs.addTab(OutreachPage(), "AI 触达")
        self.v.addWidget(tabs, 1)


class TaskCenterPage(BasePage):
    def __init__(self):
        super().__init__()
        self.b_ref = QtWidgets.QPushButton("刷新")
        self.b_ref.setObjectName("ghost")
        self.b_ref.clicked.connect(self.load)
        self.v.addWidget(make_header("任务中心", "任务执行与失败恢复总览", [self.b_ref]))
        self.headline = QtWidgets.QLabel("")
        self.headline.setObjectName("sub")
        self.v.addWidget(self.headline)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["类型", "状态", "账号/节点", "时间"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.v.addWidget(self.table)
        BRIDGE.payload.connect(self._on)

    def on_show(self):
        self.load()

    def load(self):
        def work():
            _c, j = api("GET", "/api/enterprise/task-center")
            BRIDGE.payload.emit("taskcenter", j if isinstance(j, dict) else {})
        run_bg(work)

    def _on(self, tag, d):
        if tag != "taskcenter":
            return
        self.headline.setText(str(d.get("headline") or d.get("message") or ""))
        recent = d.get("recent") or []
        self.table.setRowCount(0)
        for t in recent[:100]:
            if not isinstance(t, dict):
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [t.get("type") or t.get("operation") or "-", t.get("status") or "-",
                    (t.get("accountId") or t.get("nodeId") or "-"), t.get("updatedAtText") or t.get("createdAtText") or ""]
            for c, val in enumerate(vals):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(str(val)))


class LogPage(BasePage):
    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("运行日志", "本地引擎 / worker 实时日志"))
        self.box = QtWidgets.QPlainTextEdit()
        self.box.setReadOnly(True)
        self.v.addWidget(self.box)
        BRIDGE.log_line.connect(self.box.appendPlainText)


def _content_first_value(item, keys):
    item = item or {}
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _content_count_text(item, keys):
    value = _content_first_value(item, keys)
    if value is None:
        return "-"
    try:
        number = float(value)
        if number.is_integer():
            return str(int(number))
        return str(round(number, 2))
    except (TypeError, ValueError):
        return str(value).strip() or "-"


def _content_duration_text(item):
    value = _content_first_value(item, (
        "duration", "durationSec", "duration_sec", "videoDuration", "video_duration", "video_duration_sec"
    ))
    if value is None:
        return "-"
    text = str(value).strip()
    if not text:
        return "-"
    if ":" in text or "秒" in text or "分" in text or "小时" in text:
        return text
    try:
        seconds = float(text)
        if seconds > 10000:
            seconds = seconds / 1000.0
        return _format_duration_zh(seconds)
    except (TypeError, ValueError):
        return text


def _content_search_row_values(item):
    item = item or {}
    return [
        str(item.get("title") or item.get("desc") or "-"),
        str(item.get("author") or item.get("nickname") or "-"),
        str(item.get("url") or item.get("noteUrl") or item.get("note_url") or item.get("work_url") or ""),
        _content_count_text(item, ("digg_count", "diggCount", "like_count", "likeCount", "liked_count", "likedCount", "likes", "admire_count")),
        _content_count_text(item, ("share_count", "shareCount", "repost_count", "repostCount", "forward_count", "forwardCount")),
        _content_duration_text(item),
    ]


def _content_platform_label(platform):
    p = str(platform or "").strip().lower()
    return "小红书" if p in ("xhs", "xiaohongshu", "小红书") else "抖音"


def _content_search_failure_text(data, current_platform="douyin"):
    data = data or {}
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    platform = result.get("platform") or data.get("platform") or current_platform
    task_type = str(data.get("type") or "")
    if task_type.startswith("xhs."):
        platform = "xhs"
    elif task_type.startswith("douyin."):
        platform = "douyin"
    label = _content_platform_label(platform)
    error = str(data.get("error") or result.get("error") or "")
    need = bool(result.get("needLogin") or error in ("local_browser_offline", "no_auth", "douyin_auth_incomplete"))
    hint = ""
    if need:
        if error == "local_browser_offline":
            hint = "(本地客户端未在线或未绑定当前账号/企业，请启动本地客户端，并确认%s账号已登录)" % label
        else:
            hint = "(需先登录%s账号)" % label
    return "搜索失败:" + error + hint



def _xhs_note_material_from_download(task, source_url=""):
    """Extract the material payload saved by an XHS note download task."""
    task = task if isinstance(task, dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    material = result.get("material") if isinstance(result.get("material"), dict) else {}
    if not material:
        material = task.get("material") if isinstance(task.get("material"), dict) else {}
    material = dict(material or {})
    material_id = (
        result.get("materialId") or result.get("material_id") or result.get("id")
        or task.get("materialId") or task.get("material_id") or material.get("id")
    )
    if material_id and not material.get("id"):
        material["id"] = str(material_id)
    material.setdefault("platform", "xhs")
    material.setdefault("type", "image")
    if source_url and not material.get("sourceUrl"):
        material["sourceUrl"] = source_url
    for key in ("title", "body", "tags"):
        if key not in material and key in result:
            material[key] = result.get(key)
    files = material.get("files") or result.get("files") or result.get("images") or material.get("urls") or result.get("urls") or []
    source_urls = material.get("urls") or result.get("urls") or []
    source_urls = source_urls if isinstance(source_urls, list) else []
    cleaned = []
    cleaned_urls = []
    for source_index, item in enumerate(files if isinstance(files, list) else []):
        aligned_url = str(source_urls[source_index] or "").strip() if source_index < len(source_urls) else ""
        if isinstance(item, dict):
            raw_url = str(item.get("url") or aligned_url or "").strip()
            value = item.get("localPath") or item.get("path") or item.get("file") or item.get("name") or item.get("filename")
            if not value and raw_url:
                value = os.path.basename(urlparse(raw_url).path)
        else:
            value = item
            raw_url = aligned_url
        value = str(value or "").strip()
        if value.lower().startswith(("http://", "https://")):
            raw_url = value
            value = os.path.basename(urlparse(value).path)
        if value:
            cleaned.append(value)
            cleaned_urls.append(raw_url)
    if cleaned:
        material["files"] = cleaned
        if any(cleaned_urls):
            material["urls"] = cleaned_urls
    return material if (material.get("id") or material.get("files")) else {}


_XHS_NOTE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".heic", ".heif"}
_XHS_NOTE_SOURCE_IMAGE_MAX_BYTES = 20 * 1024 * 1024
_XHS_NOTE_SOURCE_IMAGE_FETCH_LIMIT = threading.BoundedSemaphore(4)


def _xhs_note_source_image_headers(url, central_base=""):
    raw_url = str(url or "").strip()
    try:
        target = urlparse(raw_url)
        central = urlparse(str(central_base or CENTRAL or "").strip())
        target_port = target.port or (443 if target.scheme == "https" else 80)
        central_port = central.port or (443 if central.scheme == "https" else 80)
        same_origin = (
            target.scheme == central.scheme
            and (target.hostname or "").lower() == (central.hostname or "").lower()
            and target_port == central_port
        )
    except Exception:
        return {}
    if same_origin and target.path.startswith("/api/library/file/"):
        return _headers()
    return {}


def _xhs_note_read_limited_response(response, max_bytes=_XHS_NOTE_SOURCE_IMAGE_MAX_BYTES):
    limit = max(1, int(max_bytes or _XHS_NOTE_SOURCE_IMAGE_MAX_BYTES))
    headers = getattr(response, "headers", {}) or {}
    try:
        content_length = int(str(headers.get("Content-Length") or "0").strip() or "0")
    except (TypeError, ValueError):
        content_length = 0
    if content_length > limit:
        raise RuntimeError("image_response_too_large")

    iterator = getattr(response, "iter_content", None)
    if not callable(iterator):
        content = bytes(getattr(response, "content", b"") or b"")
        if len(content) > limit:
            raise RuntimeError("image_response_too_large")
        return content

    chunks = []
    total = 0
    for chunk in iterator(chunk_size=64 * 1024):
        if not chunk:
            continue
        chunk = bytes(chunk)
        total += len(chunk)
        if total > limit:
            raise RuntimeError("image_response_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def _xhs_note_source_image_entries(material, central_base=""):
    """Normalize downloaded note images for local preview or authenticated central fetch."""
    material = material if isinstance(material, dict) else {}
    files = material.get("files") if isinstance(material.get("files"), list) else []
    urls = material.get("urls") if isinstance(material.get("urls"), list) else []
    source_dir = str(material.get("sourceDownloadPath") or "").strip()
    material_id = str(material.get("id") or "").strip()
    base = str(central_base or CENTRAL or "").rstrip("/")
    entries = []
    for source_index, item in enumerate(files):
        if isinstance(item, dict):
            raw_path = str(item.get("path") or item.get("localPath") or item.get("file") or "").strip()
            raw_url = str(item.get("url") or "").strip()
            inferred_name = os.path.basename(raw_path or urlparse(raw_url).path)
            name = str(item.get("name") or item.get("filename") or inferred_name).strip()
        else:
            value = str(item or "").strip()
            raw_path = value if os.path.isabs(value) else ""
            raw_url = value if value.lower().startswith(("http://", "https://")) else ""
            name = os.path.basename(urlparse(value).path if raw_url else value)
        name = os.path.basename(name.replace("\\", "/"))
        ext = os.path.splitext(name)[1].lower()
        if ext not in _XHS_NOTE_IMAGE_EXTENSIONS:
            continue

        local_path = raw_path if raw_path and os.path.isfile(raw_path) else ""
        if not local_path and source_dir:
            candidate = os.path.join(source_dir, name)
            if os.path.isfile(candidate):
                local_path = candidate

        url = str(urls[source_index] or "").strip() if source_index < len(urls) else ""
        if not url:
            url = raw_url
        if not url and material_id and name:
            url = "/api/library/file/%s/%s" % (quote(material_id), quote(name))
        if url.startswith("/") and base:
            url = base + url
        entries.append({
            "index": len(entries) + 1,
            "sourceIndex": source_index,
            "name": name,
            "path": local_path,
            "url": url,
            "materialId": material_id,
        })
    return entries


def _xhs_note_slot_rows(job, preview):
    job = job if isinstance(job, dict) else {}
    preview = preview if isinstance(preview, dict) else {}
    template = job.get("template") if isinstance(job.get("template"), dict) else {}
    slots = [slot for slot in (template.get("imageSlots") or []) if isinstance(slot, dict)]
    mappings = job.get("slotMappings") or preview.get("slotMappings") or []
    mappings = [mapping for mapping in mappings if isinstance(mapping, dict)]
    by_index = {str(mapping.get("slotIndex")): mapping for mapping in mappings}
    if not slots:
        slots = [{
            "index": mapping.get("slotIndex"),
            "role": mapping.get("slotRole") or "",
            "ratio": mapping.get("ratio") or "",
            "sourceFile": "",
        } for mapping in mappings]

    rows = []
    for row_index, slot in enumerate(slots, start=1):
        slot_index = slot.get("index") or row_index
        mapping = by_index.get(str(slot_index))
        if mapping:
            source = str(mapping.get("source") or "")
            if source == "ai_placeholder":
                source_label = "AI 占位图"
            elif source == "asset":
                source_label = "用户图片"
            else:
                source_label = source or "待配置"
            confirmation = mapping.get("confirmationStatus") or "待确认"
        else:
            source_name = str(slot.get("sourceFile") or "").strip()
            source_label = ("原图 · " + source_name) if source_name else "原图"
            confirmation = "待配置"
        rows.append({
            "slotIndex": slot_index,
            "slotRole": (mapping or {}).get("slotRole") or slot.get("role") or "",
            "sourceLabel": source_label,
            "ratio": (mapping or {}).get("ratio") or slot.get("ratio") or "",
            "confirmationStatus": confirmation,
        })
    return rows


class ContentPage(BasePage):
    """抖音/小红书 内容中心:搜索 · 下载 · 看评论 · 发评论。"""
    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("内容采集", "抖音/小红书 内容:搜索 · 下载 · 看评论 · 手动评论(本机浏览器执行)"))
        self.v.addWidget(prereq_banner("采集/评论等需:本机客户端在线 + 对应平台账号已登录;否则不会真实执行(会提示未采集)。"))
        row = QtWidgets.QHBoxLayout()
        self.platform = QtWidgets.QComboBox()
        self.platform.addItems(["抖音", "小红书"])
        self.kw = QtWidgets.QLineEdit()
        self.kw.setPlaceholderText("搜索关键词")
        self.num = QtWidgets.QSpinBox()
        self.num.setRange(1, 50)
        self.num.setValue(10)
        self.num.setPrefix("数量 ")
        self.b_search = QtWidgets.QPushButton("搜索")
        self.b_search.setObjectName("primary")
        self.b_search.clicked.connect(self.search)
        row.addWidget(self.platform)
        row.addWidget(self.kw, 3)
        row.addWidget(self.num)
        row.addWidget(self.b_search)
        self.v.addLayout(row)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("sub")
        self.v.addWidget(self.status)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["标题", "作者", "链接", "点赞数", "转发数", "视频时长"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.itemSelectionChanged.connect(self._select)
        self.v.addWidget(self.table, 2)
        ab = QtWidgets.QHBoxLayout()
        self.url = QtWidgets.QLineEdit()
        self.url.setPlaceholderText("视频/笔记链接(点上表某行自动填,或手动粘贴)")
        self.b_dl = QtWidgets.QPushButton("下载")
        self.b_dl.setObjectName("ghost")
        self.b_dl.clicked.connect(self.download)
        self.b_note_replace = QtWidgets.QPushButton("图文同款")
        self.b_note_replace.setObjectName("primary")
        self.b_note_replace.clicked.connect(self.note_replace)
        self.b_break = QtWidgets.QPushButton("分解")
        self.b_break.setObjectName("primary")
        self.b_break.clicked.connect(self.breakdown)
        self.b_cm = QtWidgets.QPushButton("看评论")
        self.b_cm.setObjectName("ghost")
        self.b_cm.clicked.connect(self.comments)
        ab.addWidget(self.url, 3)
        ab.addWidget(self.b_dl)
        ab.addWidget(self.b_note_replace)
        ab.addWidget(self.b_break)
        ab.addWidget(self.b_cm)
        self.v.addLayout(ab)
        ab2 = QtWidgets.QHBoxLayout()
        self.cmt = QtWidgets.QLineEdit()
        self.cmt.setPlaceholderText("要发布的评论内容")
        self.b_post = QtWidgets.QPushButton("发评论")
        self.b_post.setObjectName("primary")
        self.b_post.clicked.connect(self.post_comment)
        ab2.addWidget(self.cmt, 3)
        ab2.addWidget(self.b_post)
        self.v.addLayout(ab2)
        self.ctable = QtWidgets.QTableWidget(0, 2)
        self.ctable.setHorizontalHeaderLabels(["用户", "评论"])
        self.ctable.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.ctable.verticalHeader().setVisible(False)
        self.v.addWidget(self.ctable, 2)
        self._results = []
        BRIDGE.payload.connect(self._on)

    def _pf(self):
        return "xhs" if self.platform.currentText() == "小红书" else "douyin"

    def _select(self):
        r = self.table.currentRow()
        if 0 <= r < len(self._results):
            rr = self._results[r]
            self.url.setText(rr.get("url") or rr.get("noteUrl") or rr.get("note_url") or rr.get("work_url") or "")

    def search(self):
        kw = self.kw.text().strip()
        if not kw:
            self.status.setText("请输入关键词")
            return
        self.b_search.setEnabled(False)
        self.status.setText("搜索中…(本机浏览器执行)")
        pf = self._pf()
        payload = {"query": kw, "keyword": kw, "num": self.num.value(), "content_type": "0", "platform": pf}
        run_bg(lambda: BRIDGE.payload.emit("c_search", submit_local_task(pf + ".search", payload, 200)))

    def download(self):
        u = self.url.text().strip()
        if not u:
            self.status.setText("请先选择或粘贴链接")
            return
        self.b_dl.setEnabled(False)
        self.status.setText("下载中…")
        pf = self._pf()
        run_bg(lambda: BRIDGE.payload.emit("c_dl", submit_local_task(pf + ".download", {"url": u, "noteUrl": u, "save_choice": "all", "platform": pf}, 600)))

    def note_replace(self):
        u = self.url.text().strip()
        if not u:
            self.status.setText("请先选择或粘贴小红书笔记链接")
            return
        host = (urlparse(u).hostname or "").lower()
        is_xhs_url = host.endswith("xiaohongshu.com") or host.endswith("xhslink.com")
        if self._pf() != "xhs" or not is_xhs_url:
            self.status.setText("图文同款仅支持小红书笔记，请先切换到小红书或选择小红书链接")
            return
        self.b_note_replace.setEnabled(False)
        self.b_dl.setEnabled(False)
        self.status.setText("图文同款准备中：正在下载笔记图片…")

        def work():
            task = submit_local_task("xhs.download", {
                "url": u,
                "noteUrl": u,
                "save_choice": "all",
                "platform": "xhs",
            }, 600)
            BRIDGE.payload.emit("c_note_replace", {"task": task, "url": u, "platform": "xhs"})
        run_bg(work)
    def breakdown(self):
        u = self.url.text().strip()
        if not u:
            self.status.setText("请先选择或粘贴链接")
            return
        self.b_break.setEnabled(False)
        self.status.setText("分解准备中:正在下载视频…")
        pf = self._pf()

        def work():
            task = submit_local_task(pf + ".download", {"url": u, "noteUrl": u, "save_choice": "all", "platform": pf}, 900)
            BRIDGE.payload.emit("c_break", {"task": task, "url": u, "platform": pf})
        run_bg(work)

    def comments(self):
        u = self.url.text().strip()
        if not u:
            self.status.setText("请先选择或粘贴链接")
            return
        self.b_cm.setEnabled(False)
        self.status.setText("读取评论中…")
        pf = self._pf()
        run_bg(lambda: BRIDGE.payload.emit("c_cm", submit_local_task(pf + ".comments", {"url": u, "noteUrl": u, "mode": "out", "platform": pf}, 200)))

    def post_comment(self):
        u = self.url.text().strip()
        c = self.cmt.text().strip()
        if not u or not c:
            self.status.setText("请填链接和评论内容")
            return
        self.b_post.setEnabled(False)
        self.status.setText("发评论中…")
        pf = self._pf()
        run_bg(lambda: BRIDGE.payload.emit("c_post", submit_local_task(pf + ".comment.publish", {"url": u, "noteUrl": u, "content": c, "platform": pf}, 200)))

    def _on(self, tag, d):
        if tag == "c_search":
            self.b_search.setEnabled(True)
            rr = (d or {}).get("result") or {}
            items = d.get("items") or rr.get("items") or []
            self._results = [x for x in items if isinstance(x, dict)]
            self.table.setRowCount(0)
            for x in self._results:
                r = self.table.rowCount()
                self.table.insertRow(r)
                for col, value in enumerate(_content_search_row_values(x)):
                    self.table.setItem(r, col, QtWidgets.QTableWidgetItem(str(value)))
            self.status.setText(("找到 %d 条(点某行把链接填到下方)" % len(self._results)) if d.get("status") == "done"
                                else _content_search_failure_text(d, self._pf()))
        elif tag == "c_dl":
            self.b_dl.setEnabled(True)
            rr = (d or {}).get("result") or {}
            self.status.setText("下载完成并入库。" if (d.get("status") == "done" and rr.get("ok") is not False)
                                else ("下载失败:" + str(d.get("error") or rr.get("error") or "")))
        elif tag == "c_note_replace":
            self.b_note_replace.setEnabled(True)
            self.b_dl.setEnabled(True)
            payload = d if isinstance(d, dict) else {}
            task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
            result = task.get("result") if isinstance(task.get("result"), dict) else {}
            if task.get("status") != "done" or result.get("ok") is False:
                error = task.get("error") or result.get("error") or payload.get("error") or ""
                self.status.setText("图文同款下载失败:" + _localize_download_task_error(error))
                return
            source_url = payload.get("url") or ""
            material = _xhs_note_material_from_download(task, source_url)
            if not material.get("files"):
                self.status.setText("未找到图片素材，请先下载笔记")
                return
            self.status.setText("下载完成，正在进入图文同款…")
            BRIDGE.payload.emit("goto_nav", "🧩 图文同款")
            BRIDGE.payload.emit("xhs_note_replace_start", {
                "material": material,
                "sourceUrl": source_url,
            })
        elif tag == "c_break":
            self.b_break.setEnabled(True)
            task = (d or {}).get("task") or {}
            rr = task.get("result") or {}
            if task.get("status") != "done" or rr.get("ok") is False:
                self.status.setText("分解失败:下载未完成 " + _localize_download_task_error(task.get("error") or rr.get("error") or ""))
                return
            video = _find_video_file_from_download(rr) or _find_video_file_from_download(task)
            if not video:
                self.status.setText("分解失败:未找到可分析的视频文件")
                return
            self.status.setText("下载完成,正在进入分解视频…")
            BRIDGE.payload.emit("goto_nav", "🔬 分解视频")
            BRIDGE.payload.emit("video_breakdown_start", {
                "platform": (d or {}).get("platform") or "douyin",
                "sourceUrl": (d or {}).get("url") or "",
                "videoPath": video,
                "download": rr,
            })
        elif tag == "c_cm":
            self.b_cm.setEnabled(True)
            rr = (d or {}).get("result") or {}
            items = d.get("items") or rr.get("items") or d.get("comments") or rr.get("comments") or []
            items = [x for x in items if isinstance(x, dict) and (x.get("text") or x.get("c") or x.get("user") or x.get("u"))]
            self.ctable.setRowCount(0)
            for x in items:
                if not isinstance(x, dict):
                    continue
                r = self.ctable.rowCount()
                self.ctable.insertRow(r)
                self.ctable.setItem(r, 0, QtWidgets.QTableWidgetItem(str(x.get("user") or x.get("u") or "-")))
                self.ctable.setItem(r, 1, QtWidgets.QTableWidgetItem(str(x.get("text") or x.get("c") or "")))
            self.status.setText(("评论 %d 条" % self.ctable.rowCount()) if d.get("status") == "done"
                                else ("读取失败:" + str(d.get("error") or rr.get("error") or "")))
        elif tag == "c_post":
            self.b_post.setEnabled(True)
            self.status.setText("评论已发送。" if d.get("status") == "done" else ("发评论失败:" + str(d.get("error") or "")))


class VideoBreakdownPage(BasePage):
    """临时视频深度分解:下载后抽帧/OCR/音频降级/AI汇总,报告只在当前页展示。"""
    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("分解视频", "从内容采集一键下载 → 抽关键帧/OCR/口播降级 → 生成临时拆解报告"))
        self.v.addWidget(prereq_banner("报告不会写入知识库或资产库；需要保留时请点击『下载报告』保存到本地。"))
        top = QtWidgets.QHBoxLayout()
        self.path_lab = QtWidgets.QLabel("等待从『内容采集』发起分解。")
        self.path_lab.setObjectName("sub")
        self.path_lab.setWordWrap(True)
        self.b_open = QtWidgets.QPushButton("打开视频")
        self.b_open.setObjectName("ghost")
        self.b_open.clicked.connect(self.open_video)
        self.b_retry = QtWidgets.QPushButton("重试转写")
        self.b_retry.setObjectName("ghost")
        self.b_retry.clicked.connect(self.retry_transcription)
        self.b_replace = QtWidgets.QPushButton("替换生成")
        self.b_replace.setObjectName("ghost")
        self.b_replace.clicked.connect(self.start_replacement)
        self.b_digital_human = QtWidgets.QPushButton("生成数字人口播")
        self.b_digital_human.setObjectName("ghost")
        self.b_digital_human.clicked.connect(self.start_digital_human)
        self.b_save = QtWidgets.QPushButton("下载报告")
        self.b_save.setObjectName("primary")
        self.b_save.clicked.connect(self.save_report)
        self.b_open.setEnabled(False)
        self.b_retry.setEnabled(False)
        self.b_replace.setEnabled(False)
        self.b_digital_human.setEnabled(False)
        self.b_save.setEnabled(False)
        top.addWidget(self.path_lab, 1)
        top.addWidget(self.b_open)
        top.addWidget(self.b_retry)
        top.addWidget(self.b_replace)
        top.addWidget(self.b_digital_human)
        top.addWidget(self.b_save)
        self.v.addLayout(top)
        self.status = QtWidgets.QLabel("未开始")
        self.status.setObjectName("sub")
        self.v.addWidget(self.status)
        self.report = QtWidgets.QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("分解完成后会在这里显示报告。")
        self.v.addWidget(self.report, 1)
        self._job = ""
        self._video_path = ""
        self._markdown = ""
        self._analysis = {}
        self._busy = False
        BRIDGE.payload.connect(self._on)

    def _on(self, tag, d):
        d = d or {}
        if tag == "video_breakdown_start":
            self.start(d)
        elif tag == "video_breakdown_progress" and d.get("job") == self._job:
            self.status.setText(str(d.get("message") or "处理中…"))
        elif tag == "video_breakdown_done" and d.get("job") == self._job:
            self._busy = False
            self._markdown = d.get("markdown") or ""
            self._analysis = d.get("analysis") or {}
            self.report.setPlainText(self._markdown)
            self.status.setText(d.get("message") or "分析完成")
            self.b_save.setEnabled(bool(self._markdown))
            validation = self._analysis.get("validation") or {}
            self.b_open.setEnabled(bool(self._video_path) and validation.get("ok") is not False)
            self.b_replace.setEnabled(bool(self._markdown) and bool(self._video_path)
                                      and validation.get("ok") is not False)
            self.b_digital_human.setEnabled(bool(self._markdown) and validation.get("ok") is not False)
            failed_ranges = (self._analysis.get("transcript") or {}).get("failedRanges") or []
            self.b_retry.setEnabled(bool(failed_ranges))

    def start(self, data):
        if self._busy:
            self.status.setText("已有视频正在分解，请等待当前任务完成")
            return
        video = str((data or {}).get("videoPath") or "").strip()
        if not (video and os.path.isfile(video)):
            self.status.setText("分解失败:视频文件不存在")
            self.report.setPlainText("")
            return
        self._video_path = video
        self._markdown = ""
        self._analysis = {}
        self._job = uuid.uuid4().hex
        self._busy = True
        self.b_open.setEnabled(False)
        self.b_retry.setEnabled(False)
        self.b_replace.setEnabled(False)
        self.b_digital_human.setEnabled(False)
        self.b_save.setEnabled(False)
        self.path_lab.setText("%s\n%s" % ((data or {}).get("sourceUrl") or "本地视频", video))
        self.report.setPlainText("正在分解视频，请稍候…")
        self.status.setText("开始分析…")

        def progress(msg, job=self._job):
            BRIDGE.payload.emit("video_breakdown_progress", {"job": job, "message": msg})

        def work(job=self._job, payload=dict(data or {})):
            out = {"platform": payload.get("platform") or "", "sourceUrl": payload.get("sourceUrl") or "",
                   "videoPath": video}
            tmp = os.path.join(data_dir(), "video_breakdowns", job)
            try:
                os.makedirs(tmp, exist_ok=True)
                write_video_breakdown_job_owner(tmp)
                progress("校验视频文件…")
                validation = _breakdown_source_validation(video)
                out["validation"] = validation
                if not validation.get("ok"):
                    raw = json_log(
                        _CLIENT_JSON_LOGGER,
                        "video_breakdown_source_invalid",
                        code=validation.get("code") or "media_invalid",
                        video_path=video,
                        size=validation.get("size") or 0,
                    )
                    import json as _json
                    error_id = (_json.loads(raw) or {}).get("errorId")
                    out["meta"] = validation
                    out["ocr"] = {"status": "skipped", "engine": "none", "text": "", "errors": []}
                    out["transcript"] = {
                        "status": "skipped", "text": "", "segments": [], "failedRanges": [],
                        "errors": [], "retryCount": 0,
                    }
                    out["report"] = (
                        "## 分解失败\n源视频未通过真实性校验。\n\n"
                        "- code: %s\n- errorId: %s"
                        % (validation.get("code") or "media_invalid", error_id or "-")
                    )
                    BRIDGE.payload.emit("video_breakdown_done", {
                        "job": job,
                        "markdown": _video_breakdown_markdown(out),
                        "message": "分解失败（%s，错误编号 %s）" % (
                            validation.get("code") or "media_invalid", error_id or "-"
                        ),
                        "analysis": out,
                    })
                    return
                meta = {
                    "duration": validation.get("duration") or 0,
                    "width": validation.get("width") or 0,
                    "height": validation.get("height") or 0,
                    "path": video,
                }
                out["meta"] = meta
                progress("抽取关键帧…")
                frames = _extract_breakdown_frames(video, os.path.join(tmp, "frames"), 16)
                frame_notes = "\n".join("[%.2fs] %s" % (f.get("time") or 0, os.path.basename(f.get("path") or ""))
                                        for f in frames) or "未抽取到关键帧"
                progress("识别画面字幕…")
                ocr = _ocr_breakdown_frames(frames)
                out["ocr"] = ocr
                progress("分片导出音频并尝试转写…")

                def transcription_progress(index, total, start, end, state):
                    progress("音频转写 %d/%d（%.0f-%.0fs，%s）" % (
                        index + 1, total, start, end, state
                    ))

                transcript = _transcribe_breakdown_audio(
                    video,
                    out_dir=os.path.join(tmp, "audio"),
                    progress=transcription_progress,
                )
                transcript.setdefault("retryCount", 0)
                out["transcript"] = transcript
                progress("调用视觉模型分析关键帧…")
                frame_urls = [_image_data_url(f.get("path")) for f in frames[:16]]
                frame_urls = [u for u in frame_urls if u]
                try:
                    visual = lk888_vision(
                        "请逐帧描述这些短视频关键帧，重点提取人物、产品、场景、动作、字幕、道具、镜头节奏。",
                        frame_urls, max_tokens=2200)
                except Exception as exc:
                    raw = json_log(
                        _CLIENT_JSON_LOGGER,
                        "video_breakdown_vision_failed",
                        exc=exc,
                        code="video_breakdown_vision_failed",
                        video_path=video,
                    )
                    import json as _json
                    error_id = (_json.loads(raw) or {}).get("errorId")
                    visual = "视觉模型分析失败（errorId: %s）: %s\n%s" % (
                        error_id or "-", str(exc)[:160], frame_notes
                    )
                out["visual"] = visual
                out["frameNotes"] = frame_notes
                progress("生成深度拆解报告…")
                report, msg = _generate_video_breakdown_report(out)
                out["report"] = report
                md = _video_breakdown_markdown(out)
                BRIDGE.payload.emit("video_breakdown_done", {
                    "job": job, "markdown": md, "message": msg, "analysis": out,
                })
            except Exception as exc:
                raw = json_log(
                    _CLIENT_JSON_LOGGER,
                    "video_breakdown_failed",
                    exc=exc,
                    code="video_breakdown_failed",
                    video_path=video,
                )
                import json as _json
                error_id = (_json.loads(raw) or {}).get("errorId")
                out["meta"] = out.get("meta") or {}
                out["ocr"] = out.get("ocr") or {
                    "status": "failed", "engine": "none", "text": "", "errors": [],
                    "message": str(exc)[:160],
                }
                out["transcript"] = out.get("transcript") or {
                    "status": "failed", "text": "", "segments": [], "failedRanges": [],
                    "errors": [], "retryCount": 0, "message": "",
                }
                out["report"] = "## 分解失败\nerrorId: %s\n\n%s" % (error_id or "-", str(exc)[:500])
                BRIDGE.payload.emit("video_breakdown_done", {
                    "job": job,
                    "markdown": _video_breakdown_markdown(out),
                    "message": "分解失败（错误编号 %s）" % (error_id or "-"),
                    "analysis": out,
                })
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        run_bg(work)

    def retry_transcription(self):
        if self._busy:
            self.status.setText("当前分析任务尚未完成")
            return
        previous = dict((self._analysis or {}).get("transcript") or {})
        failed_ranges = list(previous.get("failedRanges") or [])
        video = self._video_path
        if not failed_ranges:
            self.status.setText("没有可重试的失败时间段")
            self.b_retry.setEnabled(False)
            return
        if not (video and os.path.isfile(video)):
            self.status.setText("重试失败:源视频文件不存在")
            return
        payload = dict(self._analysis or {})
        self._job = uuid.uuid4().hex
        self._busy = True
        self.b_retry.setEnabled(False)
        self.b_save.setEnabled(False)
        self.status.setText("正在重试失败的转写分片…")

        def progress(msg, job=self._job):
            BRIDGE.payload.emit("video_breakdown_progress", {"job": job, "message": msg})

        def work(job=self._job, out=payload, prior=previous):
            tmp = os.path.join(data_dir(), "video_breakdowns", job)
            try:
                os.makedirs(tmp, exist_ok=True)
                write_video_breakdown_job_owner(tmp)

                def transcription_progress(index, total, start, end, state):
                    progress("重试转写 %d/%d（%.0f-%.0fs，%s）" % (
                        index + 1, total, start, end, state
                    ))

                retried = _transcribe_breakdown_audio(
                    video,
                    out_dir=os.path.join(tmp, "audio"),
                    only_ranges=failed_ranges,
                    progress=transcription_progress,
                )
                out["transcript"] = _merge_transcription_retry(prior, retried)
                progress("根据最新转写更新拆解报告…")
                report, message = _generate_video_breakdown_report(out)
                out["report"] = report
                BRIDGE.payload.emit("video_breakdown_done", {
                    "job": job,
                    "markdown": _video_breakdown_markdown(out),
                    "message": message,
                    "analysis": out,
                })
            except Exception as exc:
                raw = json_log(
                    _CLIENT_JSON_LOGGER,
                    "video_breakdown_transcription_retry_failed",
                    exc=exc,
                    code="transcription_retry_failed",
                    video_path=video,
                    failed_ranges=failed_ranges,
                )
                import json as _json
                error_id = (_json.loads(raw) or {}).get("errorId")
                BRIDGE.payload.emit("video_breakdown_done", {
                    "job": job,
                    "markdown": self._markdown,
                    "message": "重试转写失败（错误编号 %s）" % (error_id or "-"),
                    "analysis": self._analysis,
                })
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        run_bg(work)

    def open_video(self):
        if self._video_path:
            if not _open_path(self._video_path):
                self.status.setText("无法打开视频文件，请检查文件是否存在或系统默认播放器。")
        else:
            self.status.setText("请先完成视频分解")

    def start_replacement(self):
        if not (self._video_path and self._analysis):
            self.status.setText("请先完成视频分解")
            return
        BRIDGE.payload.emit("goto_nav", "🧬 同款替换")
        BRIDGE.payload.emit("video_replace_start", {
            "sourceVideoPath": self._video_path,
            "sourceUrl": (self._analysis or {}).get("sourceUrl") or "",
            "platform": (self._analysis or {}).get("platform") or "",
            "breakdownAnalysis": self._analysis,
            "markdown": self._markdown,
        })

    def start_digital_human(self):
        if not (self._analysis and self._markdown):
            self.status.setText("请先完成视频分解")
            return
        BRIDGE.payload.emit("goto_nav", "🧑 数字人口播")
        BRIDGE.payload.emit("digital_human_seed", _digital_human_seed_from_breakdown(self._analysis, self._markdown))

    def save_report(self):
        if not self._markdown:
            self.status.setText("暂无可下载报告")
            return
        name = "video-breakdown-%s.md" % time.strftime("%Y%m%d-%H%M%S")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "保存分解报告", name, "Markdown (*.md);;Text (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._markdown)
            self.status.setText("报告已保存: " + path)
        except Exception as e:
            self.status.setText("保存失败:" + str(e)[:120])


class PublishPage(BasePage):
    """素材上传 + 发布到抖音。"""
    def __init__(self):
        super().__init__()
        self.b_up = QtWidgets.QPushButton("上传素材")
        self.b_up.setObjectName("primary")
        self.b_up.clicked.connect(self.upload)
        self.b_ref = QtWidgets.QPushButton("刷新")
        self.b_ref.setObjectName("ghost")
        self.b_ref.clicked.connect(self.load)
        self.v.addWidget(make_header("素材与发布", "上传视频素材 → 选账号 → 发布到抖音(本机浏览器执行)", [self.b_up, self.b_ref]))
        self.v.addWidget(prereq_banner("发布需:本机客户端在线 + 目标抖音账号已在『账号矩阵』登录;否则发布不会真正执行。"))
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["标题（可编辑，正式发布时字数限制在30字以内）", "类型", "文件数"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._edit_title_dialog)
        self.v.addWidget(self.table, 2)
        bar = QtWidgets.QHBoxLayout()
        self.platform = QtWidgets.QComboBox()
        self.platform.addItem("抖音", "douyin")
        self.platform.addItem("小红书", "xhs")
        self.platform.currentIndexChanged.connect(lambda _i: self._refresh_publish_accounts())
        self.acc = QtWidgets.QComboBox()
        self.acc.setMinimumWidth(260)
        self.b_open = QtWidgets.QPushButton("打开素材")
        self.b_open.setObjectName("ghost")
        self.b_open.clicked.connect(self.open_material)
        self.b_pub = QtWidgets.QPushButton("发布到抖音")
        self.b_pub.setObjectName("primary")
        self.b_pub.clicked.connect(self.publish)
        bar.addWidget(QtWidgets.QLabel("发布平台:"))
        bar.addWidget(self.platform)
        bar.addWidget(QtWidgets.QLabel("发布账号:"))
        bar.addWidget(self.acc)
        bar.addStretch()
        bar.addWidget(self.b_open)
        bar.addWidget(self.b_pub)
        self.v.addLayout(bar)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("sub")
        self.v.addWidget(self.status)
        self._materials = []
        self._accounts = []
        self._all_accounts = []
        self._loading_materials = False
        BRIDGE.payload.connect(self._on)

    def on_show(self):
        self.load()

    def load(self):
        def work():
            _c, j = api("GET", "/api/library")
            mats = j if isinstance(j, list) else (j.get("value") or j.get("items") or [])
            _c2, ja = api("GET", "/api/accounts")
            accs = ja if isinstance(ja, list) else (ja.get("value") or ja.get("accounts") or [])
            BRIDGE.payload.emit("pub_load", {"materials": mats if isinstance(mats, list) else [],
                                             "accounts": accs if isinstance(accs, list) else []})
        run_bg(work)

    def upload(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "选择视频/图片素材", "",
                                                          "媒体文件 (*.mp4 *.mov *.jpg *.jpeg *.png);;所有文件 (*.*)")
        if not paths:
            return
        self.b_up.setEnabled(False)
        self.status.setText("上传中…(%d 个文件)" % len(paths))
        run_bg(lambda: BRIDGE.payload.emit("pub_up", upload_materials(paths, os.path.basename(paths[0]))))

    def publish(self):
        r = self.table.currentRow()
        if not (0 <= r < len(self._materials)):
            self.status.setText("请先在上表选择要发布的素材")
            return
        if self.acc.currentIndex() < 0 or not self._accounts:
            self.status.setText("请选择发布账号(先到账号矩阵登录抖音)")
            return
        mid = self._materials[r].get("id")
        aid = self._accounts[self.acc.currentIndex()].get("id")
        platform = self._current_publish_platform()
        title_item = self.table.item(r, 0)
        publish_title = (title_item.text() if title_item else str(self._materials[r].get("title") or "")).strip()
        publish_title_for_run = publish_title[:30]
        self._materials[r]["title"] = publish_title
        self.b_pub.setEnabled(False)
        self.status.setText("发布中…(本机浏览器执行,请稍候)")
        payload = {
            "accountId": aid,
            "centralAccountId": aid,
            "materialId": mid,
            "centralMaterialId": mid,
            "publishTitle": publish_title_for_run,
            "platform": platform,
            "dryRun": False,
        }
        run_bg(lambda: BRIDGE.payload.emit("pub_run", submit_local_task("publish.run", payload, 600)))

    def _material_file_names(self, material):
        names = []
        for item in (material or {}).get("files") or []:
            if isinstance(item, dict):
                name = item.get("name") or item.get("filename") or item.get("fileName") or item.get("path") or ""
            else:
                name = str(item or "")
            name = os.path.basename(str(name).replace("\\", "/"))
            if name:
                names.append(name)
        if not names:
            for url in (material or {}).get("urls") or []:
                name = os.path.basename(str(url or "").split("?", 1)[0].replace("\\", "/"))
                if name:
                    names.append(name)
        return list(dict.fromkeys(names))

    def _material_candidate_roots(self, material):
        roots = []
        for key in ("sourceDownloadPath", "savePath", "path"):
            value = str((material or {}).get(key) or "").strip()
            if value:
                roots.append(value if os.path.isdir(value) else os.path.dirname(value))
        mid = str((material or {}).get("id") or "").strip()
        if mid:
            roots.append(os.path.join(data_dir(), "materials", mid))
            central_root = os.path.abspath(os.path.expandvars(os.getenv(
                "CENTRAL_DATA_DIR",
                os.path.join(os.path.dirname(__file__), "central_data"),
            )))
            roots.append(os.path.join(central_root, "materials", mid))
        seen = set()
        return [r for r in roots if r and not (r in seen or seen.add(r))]

    def _selected_material_files(self, material):
        if not isinstance(material, dict):
            return []
        names = PublishPage._material_file_names(self, material)
        roots = PublishPage._material_candidate_roots(self, material)
        video_exts = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
        image_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        paths = []
        seen = set()
        for exts in (video_exts, image_exts):
            for root in roots:
                for name in names:
                    if os.path.splitext(name)[1].lower() not in exts:
                        continue
                    candidate = os.path.join(root, name)
                    if os.path.isfile(candidate):
                        normalized = os.path.abspath(candidate)
                        if normalized not in seen:
                            seen.add(normalized)
                            paths.append(candidate)
        return paths

    def _selected_material_file(self, material):
        files = PublishPage._selected_material_files(self, material)
        return files[0] if files else ""

    def _selected_material_open_target(self, material):
        files = PublishPage._selected_material_files(self, material)
        if not files:
            return ""
        if len(files) == 1:
            return files[0]
        dirs = list(dict.fromkeys(os.path.dirname(path) for path in files if path))
        if len(dirs) == 1:
            return dirs[0]
        for root in PublishPage._material_candidate_roots(self, material):
            if os.path.isdir(root):
                return root
        return dirs[0] if dirs else ""
    def open_material(self):
        r = self.table.currentRow()
        if not (0 <= r < len(self._materials)):
            self.status.setText("请先在上表选择要打开的素材")
            return
        path = self._selected_material_open_target(self._materials[r])
        if not path:
            self.status.setText("素材文件不存在或尚未同步到本机")
            return
        if not _open_path(path):
            self.status.setText("无法打开素材文件，请检查系统默认播放器")

    def _current_publish_platform(self):
        try:
            return str(self.platform.currentData() or "douyin")
        except Exception:
            return "douyin"

    def _refresh_publish_accounts(self):
        platform = self._current_publish_platform()
        self._accounts = clean_accounts(self._all_accounts, platform=platform, ready_only=True)
        self.acc.clear()
        if not self._accounts:
            label = "小红书" if platform == "xhs" else "抖音"
            self.acc.addItem("未找到已登录的%s账号,请先到账号矩阵登录" % label)
            return
        for a in self._accounts:
            self.acc.addItem((a.get("name") or a.get("handle") or a.get("id")) + ("" if a.get("cookieReady") else "(未就绪)"))

    def _edit_title_dialog(self, row, column):
        if column != 0 or not (0 <= row < len(self._materials)):
            return
        item = self.table.item(row, 0)
        current = (item.text() if item else str(self._materials[row].get("title") or "")).strip()
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("编辑标题")
        dlg.resize(680, 300)
        layout = QtWidgets.QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        editor = QtWidgets.QPlainTextEdit()
        editor.setPlainText(current)
        editor.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        editor.setMinimumHeight(150)
        counter = QtWidgets.QLabel("")
        counter.setObjectName("sub")

        def refresh_counter():
            counter.setText("当前 %d 字；正式发布时取前 30 字" % len(editor.toPlainText().strip()))

        editor.textChanged.connect(refresh_counter)
        layout.addWidget(editor, 1)
        layout.addWidget(counter)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("保存")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        refresh_counter()
        editor.selectAll()
        editor.setFocus()
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        self._save_material_title(row, editor.toPlainText().strip())

    def _save_material_title(self, row, title):
        if not (0 <= row < len(self._materials)):
            return
        item = self.table.item(row, 0)
        if item:
            item.setText(title)
        mid = self._materials[row].get("id")
        self._materials[row]["title"] = title
        if not mid:
            return
        run_bg(lambda: api("POST", "/api/library/update-title", {"id": mid, "title": title}))

    def _title_cell_changed(self, item):
        if self._loading_materials or item is None or item.column() != 0:
            return
        row = item.row()
        self._save_material_title(row, item.text().strip())

    def _on(self, tag, d):
        if tag == "pub_load":
            self._materials = [m for m in (d.get("materials") or []) if isinstance(m, dict)]
            self._loading_materials = True
            self.table.setRowCount(0)
            for m in self._materials:
                r = self.table.rowCount()
                self.table.insertRow(r)
                title_item = QtWidgets.QTableWidgetItem(str(m.get("title") or m.get("id")))
                title_item.setFlags(title_item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.table.setItem(r, 0, title_item)
                type_item = QtWidgets.QTableWidgetItem(str(m.get("type") or "-"))
                type_item.setFlags(type_item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.table.setItem(r, 1, type_item)
                count_item = QtWidgets.QTableWidgetItem(str(m.get("fileCount") or len(m.get("files") or [])))
                count_item.setFlags(count_item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.table.setItem(r, 2, count_item)
            self._loading_materials = False
            self._all_accounts = clean_accounts(d.get("accounts") or [], ready_only=True)
            self._refresh_publish_accounts()
        elif tag == "pub_up":
            self.b_up.setEnabled(True)
            code, j = d if isinstance(d, tuple) else (0, {})
            ok = isinstance(j, dict) and j.get("ok")
            self.status.setText("上传完成,已入素材库。" if ok else ("上传失败:" + str((j or {}).get("error") or code)))
            if ok:
                self.load()
        elif tag == "pub_run":
            self.b_pub.setEnabled(True)
            self.status.setText(_publish_result_message(d))


SALES_STYLES = {
    "热情亲和": "热情、亲切、有温度,多用自然语气词,像朋友一样",
    "专业顾问": "专业、稳重、有说服力,突出真实卖点与价值,建立信任",
    "简洁高效": "简短直接,快速给关键信息与下单引导,不啰嗦",
}


def _dm_conv_path():
    return os.path.join(data_dir(), "dm_conversations.json")


def load_dm_conv():
    """载入 AI 销售会话历史(按客户主页链接分组),跨会话持久化用于多轮跟单。"""
    import json as _json
    try:
        p = _dm_conv_path()
        d = _json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_dm_conv(conv):
    try:
        # 每个客户只留最近 40 条,避免文件无限增长
        trimmed = {k: (v[-40:] if isinstance(v, list) else v) for k, v in (conv or {}).items()}
        _atomic_write_json(_dm_conv_path(), trimmed)
    except Exception:
        pass
SALES_INTENTS = ["咨询产品", "比价", "犹豫观望", "明确购买", "售后问题", "闲聊", "无意向"]


def ai_sales_reply(incoming, history=None, product="", persona="", use_kb=True):
    """AI 销售大脑:据客户来信 + 会话历史 + 企业知识库,判断意向并生成销售话术回复。
    返回 {"intent","reply"}。只用知识库真实资料,不编造卖点/价格/政策。"""
    kb = kb_context((product + " " + incoming).strip(), limit=4) if use_kb else ""
    hist = ""
    for h in (history or [])[-6:]:
        hist += ("客户:" if h.get("role") == "customer" else "我:") + (h.get("text") or "") + "\n"
    sysmsg = ("你是专业、真诚、有亲和力的电商私信销售顾问。**只依据企业知识库里的真实产品资料**回答,"
              "不编造卖点/价格/政策;口语化、简短(1-3句)、有温度、适度引导下单但不硬推、不过度承诺、"
              "不违反平台规则、不骚扰。先判断客户意向,再给回复。只输出严格 JSON:"
              '{"intent":"%s","reply":"给客户的私信回复"}' % "|".join(SALES_INTENTS))
    parts = []
    if persona:
        parts.append("销售风格:" + persona)
    if product:
        parts.append("主推产品/场景:" + product)
    if kb:
        parts.append(kb)
    if hist:
        parts.append("最近对话:\n" + hist)
    parts.append("客户最新消息:" + incoming)
    parts.append("请只输出 JSON:")
    raw = lk888_chat("\n\n".join(parts), system=sysmsg, max_tokens=400, temperature=0.6)
    import json as _json
    import re as _re
    try:
        m = _re.search(r'\{.*\}', raw, _re.DOTALL)
        obj = _json.loads(m.group(0)) if m else {}
    except Exception:
        obj = {}
    intent = obj.get("intent") if obj.get("intent") in SALES_INTENTS else "咨询产品"
    return {"intent": intent, "reply": (obj.get("reply") or raw or "").strip()}


class DMPage(BasePage):
    """私信 / AI 销售:AI 依据企业知识库生成销售话术回复。半自动(审核后发)/ 全自动(收到即回)。
    发送走本机浏览器(douyin.dm);全自动收信需引擎收件箱轮询(douyin.dm.inbox)+ 抖音在线。"""

    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header(
            "私信 / AI 销售",
            "AI 依据企业知识库生成销售话术;半自动(审核后发)/ 全自动(收到即回)· 本机浏览器执行"))
        self._conv = load_dm_conv()   # target -> [{"role","text"}](跨会话持久化,多轮跟单)
        self._seen = set()       # 全自动已处理过的客户消息(去重)
        self._auto_busy = False
        cfg = QtWidgets.QHBoxLayout()
        cfg.setSpacing(8)
        self.target = QtWidgets.QLineEdit()
        self.target.setPlaceholderText("客户:抖音主页链接 / sec_uid(数字 uid 不支持)")
        self.target.editingFinished.connect(self._render_history)
        self.product = QtWidgets.QLineEdit()
        self.product.setPlaceholderText("主推产品 / 场景(可选)")
        self.style = QtWidgets.QComboBox()
        self.style.addItems(list(SALES_STYLES.keys()))
        self.use_kb = QtWidgets.QCheckBox("引用知识库")
        self.use_kb.setChecked(True)
        cfg.addWidget(self.target, 3)
        cfg.addWidget(self.product, 2)
        cfg.addWidget(QtWidgets.QLabel("话术"))
        cfg.addWidget(self.style)
        cfg.addWidget(self.use_kb)
        self.v.addLayout(cfg)
        self.conv = QtWidgets.QPlainTextEdit()
        self.conv.setReadOnly(True)
        self.conv.setPlaceholderText("会话记录…客户消息与 AI 回复会显示在这里")
        self.v.addWidget(self.conv, 1)
        irow = QtWidgets.QHBoxLayout()
        self.incoming = QtWidgets.QLineEdit()
        self.incoming.setPlaceholderText("客户发来的消息(手动粘贴;或开启全自动由收件箱抓取)")
        self.incoming.returnPressed.connect(self.gen_reply)
        self.b_gen = QtWidgets.QPushButton("AI 生成回复")
        self.b_gen.setObjectName("ghost")
        self.b_gen.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_gen.clicked.connect(self.gen_reply)
        irow.addWidget(self.incoming, 1)
        irow.addWidget(self.b_gen)
        self.v.addLayout(irow)
        drow = QtWidgets.QHBoxLayout()
        self.draft = QtWidgets.QLineEdit()
        self.draft.setPlaceholderText("AI 回复草稿(可编辑后发送)")
        self.draft.returnPressed.connect(self.send_reply)
        self.b_send = QtWidgets.QPushButton("发送私信")
        self.b_send.setObjectName("primary")
        self.b_send.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_send.clicked.connect(self.send_reply)
        drow.addWidget(self.draft, 1)
        drow.addWidget(self.b_send)
        self.v.addLayout(drow)
        arow = QtWidgets.QHBoxLayout()
        self.auto = QtWidgets.QCheckBox("全自动回复(收到私信即自动生成并发送)")
        self.auto.toggled.connect(self.toggle_auto)
        arow.addWidget(self.auto)
        arow.addStretch()
        self.v.addLayout(arow)
        self.status = QtWidgets.QLabel("提示:先手动/半自动跑通;全自动需本机浏览器登录抖音并保持在线。请遵守平台规则,勿骚扰他人。")
        self.status.setObjectName("sub")
        self.status.setWordWrap(True)
        self.v.addWidget(self.status)
        self._auto_timer = QtCore.QTimer(self)
        self._auto_timer.timeout.connect(self._auto_poll)
        BRIDGE.payload.connect(self._on)

    def _hist(self):
        return self._conv.setdefault(self.target.text().strip() or "_", [])

    def _log(self, who, text, tag=""):
        self.conv.appendPlainText(("👤 客户:" if who == "customer" else "🤖 我:") + (("[%s] " % tag) if tag else "") + text)

    def _render_history(self):
        """切换客户(主页链接)时,把该客户的历史会话重放到会话视图。"""
        self.conv.clear()
        for m in self._hist():
            if isinstance(m, dict):
                self._log("customer" if m.get("role") == "customer" else "me", m.get("text") or "")

    def gen_reply(self, incoming_text=None, auto=False):
        msg = (incoming_text if isinstance(incoming_text, str) else self.incoming.text()).strip()
        if not msg:
            self.status.setText("请填客户消息")
            return
        h = self._hist()
        h.append({"role": "customer", "text": msg})
        self._log("customer", msg)
        save_dm_conv(self._conv)
        if not auto:
            self.incoming.clear()
            self.b_gen.setEnabled(False)
            self.status.setText("AI 生成回复中…")
        product = self.product.text().strip()
        persona = SALES_STYLES.get(self.style.currentText(), "")
        use_kb = self.use_kb.isChecked()
        hist = list(h)
        auto_send = bool(auto)

        def work():
            try:
                r = ai_sales_reply(msg, hist, product, persona, use_kb)
                BRIDGE.payload.emit("sales_reply", {"ok": True, "intent": r["intent"], "reply": r["reply"], "auto": auto_send})
            except Exception as e:
                BRIDGE.payload.emit("sales_reply", {"ok": False, "error": str(e)[:140], "auto": auto_send})
        run_bg(work)

    def send_reply(self, content=None):
        t = self.target.text().strip()
        c = (content if isinstance(content, str) else self.draft.text()).strip()
        if not t or not c:
            self.status.setText("请填客户主页链接和回复内容")
            return
        self.b_send.setEnabled(False)
        self.status.setText("发送中…(本机浏览器执行)")
        self._hist().append({"role": "me", "text": c})
        self._log("me", c)
        save_dm_conv(self._conv)
        if not isinstance(content, str):
            self.draft.clear()
        run_bg(lambda: BRIDGE.payload.emit("dm", submit_local_task("douyin.dm", {"target": t, "content": c}, 150)))

    def toggle_auto(self, on):
        if on:
            if not self.target.text().strip():
                self.status.setText("全自动前请先填客户主页链接")
                self.auto.setChecked(False)
                return
            self._auto_timer.start(20000)
            self.status.setText("全自动已开启:每 20s 拉取新私信 → AI 生成话术 → 自动发送(需抖音在线)。首次拉取中…")
            self._auto_poll()
        else:
            self._auto_timer.stop()
            self.status.setText("全自动已关闭。")

    def _auto_poll(self):
        if self._auto_busy:
            return
        self._auto_busy = True
        t = self.target.text().strip()

        def work():
            res = submit_local_task("douyin.dm.inbox", {"target": t}, 120)
            BRIDGE.payload.emit("dm_inbox", res)
        run_bg(work)

    def _on(self, tag, d):
        d = d or {}
        if tag == "sales_reply":
            self.b_gen.setEnabled(True)
            if d.get("ok"):
                reply = d.get("reply") or ""
                self._log("me", reply, tag=d.get("intent") or "")
                if d.get("auto"):
                    self.send_reply(reply)  # 全自动:直接发送
                else:
                    self.draft.setText(reply)
                    self.status.setText("已生成回复(意向:%s)—— 可编辑后『发送私信』" % (d.get("intent") or ""))
            else:
                self.status.setText("AI 生成失败:" + str(d.get("error") or ""))
            return
        if tag == "dm_inbox":
            self._auto_busy = False
            res = d.get("result") or {}
            if d.get("status") != "done" or res.get("error"):
                err = str(d.get("error") or res.get("error") or "")
                if "unsupported_task_type" in err or "local_browser_offline" in err or "not_supported" in err:
                    self.auto.setChecked(False)
                    self.status.setText("全自动收信暂不可用(需本机浏览器在线并支持收件箱抓取);当前请用半自动。")
                return
            # 收件箱返回未读消息:[{"from","fromUrl","text"}...]
            msgs = res.get("messages") or res.get("unread") or []
            fresh = 0
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                text = (m.get("text") or "").strip()
                frm = m.get("fromUrl") or m.get("from") or self.target.text().strip()
                key = "%s|%s" % (frm, text)
                if not text or key in self._seen:
                    continue
                self._seen.add(key)
                fresh += 1
                if frm and frm != self.target.text().strip():
                    self.target.setText(frm)
                self.gen_reply(text, auto=True)  # 自动生成 + 发送
            if fresh:
                self.status.setText("全自动:发现 %d 条新私信,正在自动回复…" % fresh)
            return
        if tag == "dm":
            self.b_send.setEnabled(True)
            rr = d.get("result") or {}
            ok = d.get("status") == "done" and rr.get("ok")
            self.status.setText(("已发送私信 ✓  「%s」" % (rr.get("sent") or "")) if ok
                                else ("发送失败:" + str(d.get("error") or rr.get("error") or "")))


# 模块 -> 工厂(原生客户端模块映射)
class CopywritingPage(BasePage):
    """软文中心:输入产品/主题 + 风格,lk888 大模型批量生成文案。"""

    STYLES = ["种草文案", "小红书爆款", "抖音口播稿", "卖点提炼", "标题党标题", "朋友圈文案"]

    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("软文中心", "AI 批量生成种草 / 软文 / 口播稿(lk888 大模型)"))
        row = QtWidgets.QHBoxLayout()
        self.topic = QtWidgets.QLineEdit()
        self.topic.setPlaceholderText("产品/主题,例如:健身蛋白粉、周末露营、国货护肤…")
        self.topic.returnPressed.connect(self.gen)
        self.style = QtWidgets.QComboBox()
        self.style.addItems(self.STYLES)
        self.num = QtWidgets.QSpinBox()
        self.num.setRange(1, 8)
        self.num.setValue(3)
        self.num.setPrefix("条数 ")
        self.use_kb = QtWidgets.QCheckBox("引用知识库")
        self.use_kb.setChecked(True)
        self.use_kb.setToolTip("生成前先检索企业知识库,让文案采用真实产品卖点/价格/政策")
        self.btn = QtWidgets.QPushButton("生成")
        self.btn.setObjectName("primary")
        self.btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn.clicked.connect(self.gen)
        row.addWidget(self.topic, 1)
        row.addWidget(self.style)
        row.addWidget(self.num)
        row.addWidget(self.use_kb)
        row.addWidget(self.btn)
        self.v.addLayout(row)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("sub")
        self.v.addWidget(self.status)
        self.out = QtWidgets.QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setPlaceholderText("生成的文案会显示在这里(每条以 --- 分隔)…")
        self.v.addWidget(self.out, 1)
        brow = QtWidgets.QHBoxLayout()
        brow.addStretch()
        self.copy = QtWidgets.QPushButton("复制全部")
        self.copy.setObjectName("ghost")
        self.copy.clicked.connect(self._copy)
        brow.addWidget(self.copy)
        self.v.addLayout(brow)
        BRIDGE.payload.connect(self._on)

    def gen(self):
        t = self.topic.text().strip()
        if not t:
            self.status.setText("请输入产品/主题")
            return
        style = self.style.currentText()
        n = self.num.value()
        use_kb = self.use_kb.isChecked()
        self.btn.setEnabled(False)
        self.status.setText("检索知识库 + 生成中…(lk888)" if use_kb else "生成中…(lk888)")
        self.out.setPlainText("")

        def work():
            ref = "copywriting:%d" % int(time.time() * 1000)
            okc, cerr = try_charge("copywriting", ref)
            if not okc:
                BRIDGE.payload.emit("copywriting", {"ok": False, "error": cerr})
                return
            kb = kb_context(t) if use_kb else ""
            sysmsg = "你是资深新媒体带货文案,擅长抖音/小红书种草。输出地道中文,口语化、有钩子、可直接发布,不要任何解释说明。"
            prompt = ("为【%s】写 %d 条不同角度的「%s」。每条之间只用一行 --- 分隔,只输出文案本身,不要编号、不要标题。"
                      % (t, n, style)) + kb
            try:
                txt = lk888_chat(prompt, system=sysmsg, max_tokens=1400)
                BRIDGE.payload.emit("copywriting", {"ok": True, "text": txt, "kb": bool(kb)})
            except Exception as e:
                refund_cap("copywriting", ref)
                BRIDGE.payload.emit("copywriting", {"ok": False, "error": str(e)[:140]})
        run_bg(work)

    def _on(self, tag, d):
        if tag != "copywriting":
            return
        self.btn.setEnabled(True)
        if (d or {}).get("ok"):
            self.out.setPlainText((d or {}).get("text") or "")
            self.status.setText("已生成 ✓(已引用企业知识库真实资料)" if (d or {}).get("kb") else "已生成 ✓")
        else:
            self.status.setText("生成失败:" + str((d or {}).get("error") or ""))

    def _copy(self):
        QtWidgets.QApplication.clipboard().setText(self.out.toPlainText())
        self.status.setText("已复制到剪贴板")


class ViralImagePage(BasePage):
    """爆款图文:主题 → lk888 大模型出「标题+文案+配图prompt」→ 图片模型出封面。"""

    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("爆款图文", "选题 + 文案 + 配图一键生成(lk888)"))
        row = QtWidgets.QHBoxLayout()
        self.topic = QtWidgets.QLineEdit()
        self.topic.setPlaceholderText("主题/产品,例如:国货美妆、周末露营好物…")
        self.topic.returnPressed.connect(self.gen)
        self.use_kb = QtWidgets.QCheckBox("引用知识库")
        self.use_kb.setChecked(True)
        self.use_kb.setToolTip("生成前检索企业知识库,让文案采用真实产品卖点")
        self.btn = QtWidgets.QPushButton("生成图文")
        self.btn.setObjectName("primary")
        self.btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn.clicked.connect(self.gen)
        row.addWidget(self.topic, 1)
        row.addWidget(self.use_kb)
        row.addWidget(self.btn)
        self.v.addLayout(row)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("sub")
        self.v.addWidget(self.status)
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(16)
        self.cover = QtWidgets.QLabel("配图")
        self.cover.setFixedSize(340, 340)
        self.cover.setAlignment(QtCore.Qt.AlignCenter)
        self.cover.setStyleSheet("background:#0c0f17;border:1px solid #262c3b;border-radius:12px;color:#6f7aa0;font-size:14px;")
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText("标题 + 文案…")
        body.addWidget(self.cover)
        body.addWidget(self.text, 1)
        self.v.addLayout(body, 1)
        self._img_bytes = None
        brow = QtWidgets.QHBoxLayout()
        brow.addStretch()
        self.save = QtWidgets.QPushButton("保存配图")
        self.save.setObjectName("ghost")
        self.save.clicked.connect(self._save)
        brow.addWidget(self.save)
        self.v.addLayout(brow)
        BRIDGE.payload.connect(self._on)

    def gen(self):
        t = self.topic.text().strip()
        if not t:
            self.status.setText("请输入主题")
            return
        use_kb = self.use_kb.isChecked()
        self.btn.setEnabled(False)
        self.status.setText("① 检索知识库 + 生成选题文案…" if use_kb else "① 生成选题文案…")
        self.text.setPlainText("")
        self.cover.setPixmap(QtGui.QPixmap())
        self.cover.setText("生成中…")

        def work():
            ref = "viral_image:%d" % int(time.time() * 1000)
            okc, cerr = try_charge("viral_image", ref)
            if not okc:
                BRIDGE.payload.emit("viral", {"stage": "error", "error": cerr})
                return
            try:
                kb = kb_context(t) if use_kb else ""
                sysmsg = "你是小红书爆款操盘手。只输出严格 JSON,不要多余文字或代码块标记。"
                prompt = ('为主题【%s】产出一条小红书爆款图文,输出 JSON:'
                          '{"title":"20字内爆款标题带emoji","copy":"120字内正文文案带话题标签",'
                          '"image_prompt":"英文,描述一张吸睛的现代高级封面配图"}' % t) + kb
                raw = lk888_chat(prompt, system=sysmsg, max_tokens=800, temperature=0.9)
                import json as _json
                import re
                m = re.search(r'\{.*\}', raw, re.DOTALL)
                obj = _json.loads(m.group(0)) if m else {}
                title = obj.get("title") or t
                copy = obj.get("copy") or raw
                imgp = obj.get("image_prompt") or (t + ", modern poster, high quality")
                BRIDGE.payload.emit("viral", {"stage": "text", "title": title, "copy": copy})
                img = lk888_image(imgp + ", cinematic, clean composition, trending cover, high-end", size="1024x1024")
                BRIDGE.payload.emit("viral", {"stage": "done", "img": img})
            except Exception as e:
                refund_cap("viral_image", ref)
                BRIDGE.payload.emit("viral", {"stage": "error", "error": str(e)[:140]})
        run_bg(work)

    def _on(self, tag, d):
        if tag != "viral":
            return
        st = (d or {}).get("stage")
        if st == "text":
            self.text.setPlainText(((d.get("title") or "") + "\n\n" + (d.get("copy") or "")).strip())
            self.status.setText("② 生成配图…(约 20-40s)")
        elif st == "done":
            self._img_bytes = d.get("img")
            pm = QtGui.QPixmap()
            pm.loadFromData(self._img_bytes or b"")
            if not pm.isNull():
                self.cover.setPixmap(pm.scaled(self.cover.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            self.status.setText("已生成 ✓")
            self.btn.setEnabled(True)
        elif st == "error":
            self.status.setText("失败:" + str(d.get("error")))
            self.cover.setText("配图")
            self.btn.setEnabled(True)

    def _save(self):
        if not self._img_bytes:
            self.status.setText("还没有配图")
            return
        p = os.path.join(data_dir(), "viral_%d.png" % int(time.time()))
        try:
            with open(p, "wb") as f:
                f.write(self._img_bytes)
            self.status.setText("已保存 " + p)
        except Exception as e:
            self.status.setText("保存失败:" + str(e))


# ---------- 数字人(可灵 kling-avatar 图生数字人:头像图 + 语音 → 口型同步口播视频)----------
DH_VOICES = [
    ("女声·明亮", "Zephyr"), ("女声·青春", "Leda"), ("女声·轻快", "Aoede"),
    ("男声·沉稳", "Kore"), ("男声·播报", "Orus"), ("男声·磁性", "Charon"),
]
DH_AVATAR_PRESETS = [
    ("知性女主播", "知性专业的中国女新闻主播,深色正装,上半身,面对镜头,现代演播室背景"),
    ("亲和女主播", "亲和力强的年轻中国女主播,休闲时尚,上半身,自然微笑,面对镜头,明亮简洁背景"),
    ("成熟男主播", "成熟稳重的中国男主播,深色西装,上半身,面对镜头,演播室背景"),
    ("美妆博主", "时尚年轻的中国女美妆博主,精致妆容,上半身,面对镜头,柔光背景"),
]
DH_ASPECT_SIZE = {"竖屏 9:16": "1024x1536", "方形 1:1": "1024x1024"}


def lk888_portrait_url(desc, size="1024x1536"):
    """生成数字人形象图,返回 lk888 托管的公网 URL(供 kling 数字人当参考头像)。"""
    return lk888_media_task("gpt-image-2", {"prompt": desc, "size": size},
                            ["png", "jpg", "jpeg", "webp"], tries=45)


def lk888_tts_voice(text, voice_id=None, progress=None, cancel_check=None):
    """文案 → 语音,返回公网 mp3 URL。指定 voice_id 走 gemini-tts 命名音色,否则用 doubao 默认。"""
    if voice_id:
        try:
            return _lk888_media_task_with_cancel(
                "gemini-2.5-pro-preview-tts",
                {"prompt": text, "params": {"voice_id": voice_id, "model_version": "flash"}},
                ["mp3", "wav", "ogg"], progress=progress, cancel_check=cancel_check)
        except Exception as exc:
            json_log(
                _CLIENT_JSON_LOGGER,
                "digital_human_tts_voice_fallback",
                exc=exc,
                code="digital_human_tts_voice_fallback",
                model="gemini-2.5-pro-preview-tts",
                fallback_model="doubao-tts-2.0",
                voice_id=voice_id,
            )
            return lk888_tts(text, progress=progress)
    return lk888_tts(text, progress=progress)


def _digital_human_scene_reference(scene_url, scene_path=None):
    path_value = str(scene_path or "").strip()
    if path_value and os.path.isfile(path_value):
        return _file_to_data_url(path_value)
    return str(scene_url or "").strip()


def _verify_digital_human_scene_background(scene_url, composed_avatar_url, scene_path=None):
    """Return whether the composed avatar image actually uses the uploaded scene."""
    import json as _json
    import re as _re
    scene_ref = _digital_human_scene_reference(scene_url, scene_path)
    composed_ref = str(composed_avatar_url or "").strip()
    if not scene_ref or not composed_ref:
        return {"ok": False, "reason": "缺少场景图或合成图"}
    prompt = (
        "你是数字人口播场景换背景质检器。第1张图是用户上传的目标场景，第2张图是合成后的数字人人物图。"
        "只判断第2张图的背景/环境是否采用第1张图的主要场景。"
        "如果第1张是汽车展厅，第2张却是湖边、山景、户外、办公室、直播间或其他不同场景，必须判定 false。"
        "人物是否变化不是本次重点；只输出严格 JSON："
        '{"ok":true/false,"backgroundMatch":true/false,"reason":"一句中文原因"}'
    )
    try:
        raw = lk888_vision(prompt, [scene_ref, composed_ref], max_tokens=260)
        match = _re.search(r'\{.*\}', raw or "", _re.DOTALL)
        obj = _json.loads(match.group(0)) if match else {}
    except Exception as exc:
        json_log(
            _CLIENT_JSON_LOGGER,
            "digital_human_scene_background_qc_failed",
            exc=exc,
            code="digital_human_scene_background_qc_failed",
            composed_avatar_url=composed_ref[:160],
        )
        return {"ok": False, "reason": "场景一致性质检服务异常"}
    background_match = obj.get("backgroundMatch")
    ok = obj.get("ok")
    passed = bool(background_match is True or ok is True)
    return {
        "ok": passed,
        "backgroundMatch": bool(background_match is True),
        "reason": str(obj.get("reason") or ("场景一致" if passed else "合成图未采用上传场景")),
    }


def _is_digital_human_scene_image_transient_error(exc):
    text = str(exc or "").lower()
    return any(key in text for key in (
        "504", "502", "gateway time-out", "gateway timeout",
        "timeout", "timed out", "read operation timed out",
        "lk888_proxy_error", "urlerror", "remote disconnected",
    ))


def _is_digital_human_scene_image_policy_error(exc):
    text = str(exc or "").lower()
    return any(key in text for key in (
        "内容安全", "安全策略", "提示已被", "策略阻止",
        "policy", "safety", "moderation", "blocked by", "not allowed",
    ))


def _digital_human_scene_trace_url(value):
    """Return a query-free media URL for structured logs and UI diagnostics."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        if parsed.scheme and parsed.netloc:
            return "%s://%s%s" % (parsed.scheme, parsed.netloc, parsed.path[:180])
    except Exception:
        pass
    return raw[:180].split("?", 1)[0]


def _digital_human_scene_avatar_prompt(strict_scene=False, safe_policy=False):
    if safe_policy:
        prompt = (
            "参考第1张人物形象的整体外观与穿着风格，将人物自然放入第2张场景图环境中，"
            "生成一张清晰、自然、适合数字人口播的正面首帧图。"
            "保持画面真实、主体清楚、背景来自第2张场景图。"
        )
    else:
        prompt = (
            "将第1张人物形象图中的同一个人物完整保留，包括脸部、发型、服装、身材比例和正对镜头姿态。"
            "将第2张场景图作为唯一背景与环境，强制替换原人物图背景。"
            "生成一张写实竖屏数字人口播首帧照片：人物站在场景中，半身到全身均可，"
            "背景清晰自然，人物主体清晰，不能改变人物身份，不能保留原人物图背景。"
        )
    if strict_scene:
        prompt += (
            "上传的场景图是唯一允许的背景来源。"
            "需要体现上传场景的主要空间、建筑、光线和环境，不得生成户外公园、绿地、湖景或其他新场景；"
            "只让人物进入上传的场景，不替换、不想象新的背景。"
        )
    return prompt


def _compose_digital_human_scene_avatar_url(avatar_url, scene_url, scene_path=None, strict_scene=False):
    """人物图 + 场景图 → 场景版数字人人物图公网 URL。"""
    avatar_value = str(avatar_url or "").strip()
    scene_value = str(scene_url or "").strip()
    local_avatar = bool(avatar_value and os.path.isfile(avatar_value))
    if not local_avatar and not _is_remote_fetchable_media_url(avatar_value):
        raise RuntimeError("video_replace_avatar_not_remote_or_local")
    if not _is_remote_fetchable_media_url(scene_value):
        raise RuntimeError("digital_human_scene_not_public")
    avatar_ref = _file_to_data_url(avatar_value) if local_avatar else avatar_value
    scene_ref = scene_value
    prompt = _digital_human_scene_avatar_prompt(strict_scene=strict_scene)
    image_urls = [avatar_ref, scene_ref]
    try:
        image_bytes, public_url = lk888_image_result(
            prompt, size="1024x1536", model="gpt-image-2", image_urls=image_urls)
    except Exception as exc:
        if _is_digital_human_scene_image_policy_error(exc):
            safe_prompt = _digital_human_scene_avatar_prompt(
                strict_scene=strict_scene, safe_policy=True)
            json_log(
                _CLIENT_JSON_LOGGER,
                "digital_human_scene_avatar_policy_retry",
                exc=exc,
                code="digital_human_scene_avatar_policy_retry",
                retry_size="1024x1024",
                scene_url=scene_value[:160],
            )
            try:
                image_bytes, public_url = lk888_image_result(
                    safe_prompt, size="1024x1024", model="gpt-image-2", image_urls=image_urls)
            except Exception as retry_exc:
                if _is_digital_human_scene_image_policy_error(retry_exc):
                    raise RuntimeError(
                        "digital_human_scene_avatar_policy_blocked:%s" %
                        str(retry_exc)[:180]) from retry_exc
                if _is_digital_human_scene_image_transient_error(retry_exc):
                    raise RuntimeError(
                        "digital_human_scene_avatar_image_timeout:%s" %
                        str(retry_exc)[:180]) from retry_exc
                raise
            public_url = str(public_url or "").strip()
            if _is_remote_fetchable_media_url(public_url):
                return public_url
            if not image_bytes:
                raise RuntimeError("digital_human_scene_avatar_not_public")
            path = os.path.join(data_dir(), "dh_scene_avatar_%d.png" % int(time.time()))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(image_bytes)
            uploaded_url, _resp = upload_asset_url(path, "数字人场景版人物形象-" + os.path.basename(path), "image")
            if not _is_remote_fetchable_media_url(uploaded_url):
                raise RuntimeError("digital_human_scene_avatar_not_public")
            return uploaded_url
        if not _is_digital_human_scene_image_transient_error(exc):
            raise
        json_log(
            _CLIENT_JSON_LOGGER,
            "digital_human_scene_avatar_retry",
            exc=exc,
            code="digital_human_scene_avatar_retry",
            retry_size="1024x1024",
            scene_url=scene_value[:160],
        )
        try:
            image_bytes, public_url = lk888_image_result(
                prompt[:1200], size="1024x1024", model="gpt-image-2", image_urls=image_urls)
        except Exception as retry_exc:
            if _is_digital_human_scene_image_transient_error(retry_exc):
                raise RuntimeError("digital_human_scene_avatar_image_timeout:%s" % str(retry_exc)[:180]) from retry_exc
            raise
    public_url = str(public_url or "").strip()
    if _is_remote_fetchable_media_url(public_url):
        return public_url
    if not image_bytes:
        raise RuntimeError("digital_human_scene_avatar_not_public")
    path = os.path.join(data_dir(), "dh_scene_avatar_%d.png" % int(time.time()))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(image_bytes)
    uploaded_url, _resp = upload_asset_url(path, "数字人场景版人物形象-" + os.path.basename(path), "image")
    if not _is_remote_fetchable_media_url(uploaded_url):
        raise RuntimeError("digital_human_scene_avatar_not_public")
    return uploaded_url


def _digital_human_scene_user_reason(reason):
    text = str(reason or "").strip()
    replacements = (
        ("第1张图片", "用户上传的场景图"),
        ("第1张图", "用户上传的场景图"),
        ("第1张", "用户上传的场景图"),
        ("第2张图片", "系统合成的数字人图"),
        ("第2张图", "系统合成的数字人图"),
        ("第2张", "系统合成的数字人图"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text or "系统合成的数字人图未采用用户上传的场景图"


def _compose_and_verify_digital_human_scene(avatar_url, scene_url, scene_path=None, emit=None):
    """Compose once, then retry once with a strict uploaded-scene constraint on QC mismatch."""
    first_url = _compose_digital_human_scene_avatar_url(
        avatar_url, scene_url, scene_path=scene_path)
    if emit:
        emit(
            "场景版人物图已生成，正在校验背景",
            scene_url=_digital_human_scene_trace_url(scene_url),
            composed_avatar_url=first_url,
        )
    first_qc = _verify_digital_human_scene_background(
        scene_url, first_url, scene_path=scene_path)
    first_qc = dict(first_qc or {})
    first_qc["reason"] = _digital_human_scene_user_reason(first_qc.get("reason"))
    if first_qc.get("ok"):
        return {"avatar_url": first_url, "qc": first_qc, "attempts": 1}

    json_log(
        _CLIENT_JSON_LOGGER,
        "digital_human_scene_background_retry",
        code="digital_human_scene_background_retry",
        scene_url=_digital_human_scene_trace_url(scene_url),
        composed_avatar_url=_digital_human_scene_trace_url(first_url),
        reason=first_qc["reason"][:240],
        retry_mode="strict_uploaded_scene",
    )
    if emit:
        emit(
            "上传场景与系统合成结果不一致，正在按上传场景强制重试",
            scene_url=_digital_human_scene_trace_url(scene_url),
            composed_avatar_url=first_url,
            retry_mode="strict_uploaded_scene",
        )

    retry_url = _compose_digital_human_scene_avatar_url(
        avatar_url,
        scene_url,
        scene_path=scene_path,
        strict_scene=True,
    )
    if emit:
        emit(
            "强制重试合成图已生成，正在再次校验背景",
            scene_url=_digital_human_scene_trace_url(scene_url),
            composed_avatar_url=retry_url,
            retry_mode="strict_uploaded_scene",
        )
    retry_qc = _verify_digital_human_scene_background(
        scene_url, retry_url, scene_path=scene_path)
    retry_qc = dict(retry_qc or {})
    retry_qc["reason"] = _digital_human_scene_user_reason(retry_qc.get("reason"))
    return {
        "avatar_url": retry_url,
        "qc": retry_qc,
        "attempts": 2,
        "first_composed_avatar_url": first_url,
    }


def lk888_digital_human(avatar_url, sound_url, prompt="", mode="std", scene_url=None, progress=None, cancel_check=None):
    """可灵数字人:公网头像 URL 或本地头像文件 + 公网语音 → 口型同步视频。"""
    avatar_value = str(avatar_url or "").strip()
    sound_value = str(sound_url or "").strip()
    local_avatar = bool(avatar_value and os.path.isfile(avatar_value))
    if not local_avatar and not _is_remote_fetchable_media_url(avatar_value):
        raise RuntimeError("video_replace_avatar_not_remote_or_local")
    if not _is_remote_fetchable_media_url(sound_value):
        raise RuntimeError("video_replace_sound_not_public")
    public_scene = str(scene_url or "").strip()
    if not _is_remote_fetchable_media_url(public_scene):
        public_scene = ""
    full_prompt = prompt or "数字人正对镜头自然口播,面带微笑,轻微头部动作,专业稳定"
    if public_scene:
        full_prompt += "。参考上传场景图布置背景与环境,保持人物主体清晰、口型自然同步。"
    if "不要在画面中生成任何字幕" not in full_prompt:
        full_prompt += "。不要在画面中生成任何字幕、文字、标题、贴纸文字或水印；字幕由后期单独添加。"
    image_value = _file_to_data_url(avatar_value) if local_avatar else avatar_value
    params = {"image": image_value, "sound_file": sound_value, "mode": mode}
    if public_scene:
        params.update({"scene_image": public_scene, "background_image": public_scene})
    return _lk888_media_task_with_cancel(
        "kling-avatar-image2video",
        {"prompt": full_prompt, "params": params},
        ["mp4", "mov"], progress=progress, tries=300, cancel_check=cancel_check)


def generate_digital_human(avatar_url, script, voice_id=None, mode="std", sound_url=None, scene_url=None, scene_path=None):
    """头像图 URL + 口播稿 →(合成语音)→ 可灵数字人口型同步口播视频。
    进度经 BRIDGE.payload('digital_human', {...}) 回主线程。"""
    def emit(msg, stage="running", **kw):
        BRIDGE.payload.emit("digital_human", dict(stage=stage, msg=msg, **kw))

    def work():
        try:
            requests.packages.urllib3.disable_warnings()
        except Exception:
            pass
        cap = "digital_human_pro" if mode == "pro" else "digital_human"
        ref = "%s:%d" % (cap, int(time.time() * 1000))
        okc, cerr = try_charge(cap, ref)
        if not okc:
            emit("无法生成:" + str(cerr), stage="error")
            return
        try:
            avatar_input = avatar_url
            scene_value = str(scene_url or "").strip()
            if scene_value:
                emit("① 合成场景版人物图…")
                scene_result = _compose_and_verify_digital_human_scene(
                    avatar_url, scene_value, scene_path=scene_path, emit=emit)
                avatar_input = scene_result["avatar_url"]
                emit("① 校验场景换背景结果…")
                scene_qc = scene_result["qc"]
                if not (scene_qc or {}).get("ok"):
                    json_log(
                        _CLIENT_JSON_LOGGER,
                        "digital_human_scene_background_mismatch",
                        code="digital_human_scene_background_mismatch",
                        scene_url=_digital_human_scene_trace_url(scene_value),
                        composed_avatar_url=_digital_human_scene_trace_url(avatar_input),
                        reason=str((scene_qc or {}).get("reason") or "")[:240],
                    )
                    raise RuntimeError("digital_human_scene_background_mismatch:" + str(
                        (scene_qc or {}).get("reason") or "合成图未采用上传场景"))
            if sound_url:
                emit("① 使用上传的 TTS 声音…")
                sound = sound_url
            else:
                emit("① 合成语音(音色)…")
                sound = lk888_tts_voice(script, voice_id)

            def prog(i):
                emit("② 可灵数字人口型驱动生成中…(%ds,通常 2-10 分钟,复杂素材可能更久)" % ((i + 1) * 4))
            url = lk888_digital_human(avatar_input, sound, mode=mode, scene_url=scene_url, progress=prog)
            emit("③ 下载视频…")
            path = os.path.join(data_dir(), "digital_human_%d.mp4" % int(time.time()))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _wf_download(url, path)
            emit("⑥ 合成中文字幕…")
            subtitle = _burn_digital_human_subtitles(path, script)
            final_path = subtitle.get("videoPath") or path
            emit("数字人口播已生成 ✓", stage="done", path=final_path,
                 subtitleStatus=subtitle.get("mode") or "unknown",
                 subtitlePath=subtitle.get("subtitlePath") or "")
        except Exception as e:
            refund_cap(cap, ref)
            err = str(e)
            if err.startswith("digital_human_scene_background_mismatch:"):
                msg = "场景换背景失败：" + err.split(":", 1)[1][:180]
            elif err.startswith("digital_human_scene_avatar_image_timeout:"):
                msg = "场景换背景图片生成超时，请稍后重试；如果连续失败，可以先不上传场景图生成，或换一张更清晰、背景更简单的场景图。"
            elif err.startswith("digital_human_scene_avatar_policy_blocked:"):
                msg = "人物/场景合成被内容安全策略拦截。系统已用更中性的提示词重试一次仍失败，请换一张更中性的参考图或简化场景后再试。"
            elif err.startswith("digital_human_scene_not_public"):
                msg = "场景换背景失败：场景图不是远程模型可读取的公网图片，请重新上传后再试"
            elif err.startswith("video_replace_sound_not_public"):
                msg = "上传音频失败：音频地址不是远程模型可读取的公网地址，请重新上传音频后再试"
            else:
                msg = "生成失败:" + err[:220]
            if err.startswith("digital_human_scene_background_mismatch:"):
                msg = (
                    "场景换背景失败：用户上传的场景图与系统合成的数字人图背景不一致。"
                    "系统已按上传场景强制重试一次，仍未通过质检。原因：" +
                    err.split(":", 1)[1][:180]
                )
            emit(
                msg,
                stage="error",
                scene_url=_digital_human_scene_trace_url(scene_value),
                composed_avatar_url=_digital_human_scene_trace_url(locals().get("avatar_input")),
            )
    run_bg(work)


class DigitalHumanPage(BasePage):
    """数字人口播:AI 生成形象(可换) + 口播稿 + 音色 → 可灵 kling-avatar 口型同步口播视频。"""

    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("数字人口播", "选/生成一个形象 + 口播稿 + 音色 → 可灵数字人口型同步视频(真人级)"))
        self._avatar_url = None
        self._avatar_path = ""
        self._scene_url = None
        self._scene_path = ""
        self._composed_avatar_url = ""
        self._sound_url = None
        self._path = None
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(16)
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(10)
        # —— 形象区:预览 + 描述 + AI 生成 + 预设 ——
        arow = QtWidgets.QHBoxLayout()
        arow.setSpacing(12)
        self.avatar_lbl = QtWidgets.QLabel("形象\n预览")
        self.avatar_lbl.setFixedSize(118, 158)
        self.avatar_lbl.setAlignment(QtCore.Qt.AlignCenter)
        self.avatar_lbl.setStyleSheet("background:#0c0f17;border:1px solid #262c3b;border-radius:10px;color:#6f7aa0;font-size:12px;")
        arow.addWidget(self.avatar_lbl)
        self.scene_lbl = QtWidgets.QLabel("场景\n可选")
        self.scene_lbl.setFixedSize(118, 158)
        self.scene_lbl.setAlignment(QtCore.Qt.AlignCenter)
        self.scene_lbl.setStyleSheet("background:#0c0f17;border:1px solid #262c3b;border-radius:10px;color:#6f7aa0;font-size:12px;")
        arow.addWidget(self.scene_lbl)
        acol = QtWidgets.QVBoxLayout()
        acol.setSpacing(8)
        adrow = QtWidgets.QHBoxLayout()
        adrow.setSpacing(8)
        self.avatar_desc = QtWidgets.QLineEdit()
        self.avatar_desc.setPlaceholderText("形象描述,如:亲和力强的年轻女主播,棚拍白底")
        self.avatar_desc.returnPressed.connect(self.gen_avatar)
        self.aspect = QtWidgets.QComboBox()
        self.aspect.addItems(list(DH_ASPECT_SIZE.keys()))
        self.b_avatar = QtWidgets.QPushButton("AI 生成形象")
        self.b_avatar.setObjectName("primary")
        self.b_avatar.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_avatar.clicked.connect(self.gen_avatar)
        adrow.addWidget(self.avatar_desc, 1)
        adrow.addWidget(self.aspect)
        adrow.addWidget(self.b_avatar)
        acol.addLayout(adrow)
        urow = QtWidgets.QHBoxLayout()
        urow.setSpacing(6)
        self.b_upload_avatar = QtWidgets.QPushButton("上传人物形象")
        self.b_upload_avatar.setObjectName("ghost")
        self.b_upload_avatar.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_upload_avatar.clicked.connect(self.upload_avatar)
        self.b_upload_scene = QtWidgets.QPushButton("上传场景图（强制换背景）")
        self.b_upload_scene.setObjectName("ghost")
        self.b_upload_scene.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_upload_scene.clicked.connect(self.upload_scene)
        self.b_upload_sound = QtWidgets.QPushButton("上传TTS声音")
        self.b_upload_sound.setObjectName("ghost")
        self.b_upload_sound.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_upload_sound.clicked.connect(self.upload_sound)
        urow.addWidget(self.b_upload_avatar)
        urow.addWidget(self.b_upload_scene)
        urow.addWidget(self.b_upload_sound)
        urow.addStretch()
        acol.addLayout(urow)
        self.asset_status = QtWidgets.QLabel("人物形象必填；场景图可选；上传后会先强制合成背景。TTS 声音可选，未上传时使用下方音色自动合成。")
        self.asset_status.setObjectName("sub")
        self.asset_status.setWordWrap(True)
        acol.addWidget(self.asset_status)
        prow = QtWidgets.QHBoxLayout()
        prow.setSpacing(6)
        prow.addWidget(QtWidgets.QLabel("快速形象:"))
        for label, desc in DH_AVATAR_PRESETS:
            pb = QtWidgets.QPushButton(label)
            pb.setObjectName("ghost")
            pb.setCursor(QtCore.Qt.PointingHandCursor)
            pb.clicked.connect(lambda _=False, dsc=desc: self._use_preset(dsc))
            prow.addWidget(pb)
        prow.addStretch()
        acol.addLayout(prow)
        acol.addWidget(QtWidgets.QLabel("① 生成/上传人物形象  ② 可选上传场景和声音  ③ 写口播稿并生成"))
        acol.addStretch()
        arow.addLayout(acol, 1)
        left.addLayout(arow)
        # —— 口播稿 ——
        genrow = QtWidgets.QHBoxLayout()
        self.topic = QtWidgets.QLineEdit()
        self.topic.setPlaceholderText("产品/主题,用 AI 写口播稿(可选)")
        self.use_kb = QtWidgets.QCheckBox("引用知识库")
        self.use_kb.setChecked(True)
        self.b_script = QtWidgets.QPushButton("AI 写口播稿")
        self.b_script.setObjectName("ghost")
        self.b_script.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_script.clicked.connect(self.write_script)
        genrow.addWidget(self.topic, 1)
        genrow.addWidget(self.use_kb)
        genrow.addWidget(self.b_script)
        left.addLayout(genrow)
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setPlaceholderText("输入口播文案,或用上方 AI 写口播稿…")
        self.text.setPlainText("大家好,我是云灵星图数字人主播。欢迎体验 AI 爆款复刻平台,一键搞定多账号短视频营销。")
        left.addWidget(self.text, 1)
        # —— 音色 / 画质 / 生成 ——
        row = QtWidgets.QHBoxLayout()
        self.voice = QtWidgets.QComboBox()
        self.voice.addItems([v[0] for v in DH_VOICES])
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(["标准", "专家(更清晰)"])
        self.btn = QtWidgets.QPushButton("生成数字人")
        self.btn.setObjectName("primary")
        self.btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn.clicked.connect(self.gen)
        row.addWidget(QtWidgets.QLabel("音色"))
        row.addWidget(self.voice)
        row.addWidget(QtWidgets.QLabel("画质"))
        row.addWidget(self.mode)
        row.addStretch()
        row.addWidget(self.btn)
        left.addLayout(row)
        self.status = QtWidgets.QLabel("提示:先生成形象,再生成口播视频;按视频时长计费,生成约 2-4 分钟")
        self.status.setObjectName("sub")
        self.status.setWordWrap(True)
        left.addWidget(self.status)
        body.addLayout(left, 1)
        rcol = QtWidgets.QVBoxLayout()
        rcol.setSpacing(10)
        self.vbox = VideoPlayerBox(360, 420)
        rcol.addWidget(self.vbox, 0, QtCore.Qt.AlignHCenter)
        ctrlrow = QtWidgets.QHBoxLayout()
        ctrlrow.setSpacing(8)
        ctrlrow.setAlignment(QtCore.Qt.AlignHCenter)
        self.play_toggle = QtWidgets.QPushButton("\u64ad\u653e")
        self.play_toggle.setObjectName("ghost")
        self.play_toggle.setCursor(QtCore.Qt.PointingHandCursor)
        self.play_toggle.setMinimumWidth(84)
        self.play_toggle.setEnabled(False)
        self.play_toggle.clicked.connect(self._toggle_video)
        self.save = QtWidgets.QPushButton("保存视频")
        self.save.setObjectName("ghost")
        self.save.clicked.connect(self._save)
        ctrlrow.addWidget(self.play_toggle)
        ctrlrow.addWidget(self.save)
        rcol.addLayout(ctrlrow)
        rcol.addStretch()
        body.addLayout(rcol)
        self.v.addLayout(body, 1)
        BRIDGE.payload.connect(self._on)

    def _use_preset(self, desc):
        self.avatar_desc.setText(desc)
        self.gen_avatar()

    def _set_image_preview(self, label, path):
        if path and os.path.isfile(path):
            pm = QtGui.QPixmap(path)
            if not pm.isNull():
                label.setPixmap(pm.scaled(label.size(), QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation))

    def _upload_asset(self, kind, path, title, mtype):
        btn = {"avatar": self.b_upload_avatar, "scene": self.b_upload_scene, "sound": self.b_upload_sound}.get(kind)
        if btn:
            btn.setEnabled(False)
        if kind == "avatar":
            self._set_image_preview(self.avatar_lbl, path)
        elif kind == "scene":
            self._set_image_preview(self.scene_lbl, path)
        self.status.setText("上传%s到素材库…" % {"avatar": "人物形象", "scene": "场景图", "sound": "TTS声音"}.get(kind, "素材"))

        def work():
            try:
                url, resp = upload_asset_url(path, title, mtype)
                BRIDGE.payload.emit("dh_asset", {"ok": True, "kind": kind, "url": url, "path": path, "resp": resp})
            except Exception as e:
                BRIDGE.payload.emit("dh_asset", {"ok": False, "kind": kind, "error": str(e)[:160]})
        run_bg(work)

    def upload_avatar(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择人物形象图", "", "图片文件 (*.png *.jpg *.jpeg *.webp);;所有文件 (*.*)")
        if p:
            self._upload_asset("avatar", p, "数字人人物形象-" + os.path.basename(p), "image")

    def upload_scene(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择数字人场景图", "", "图片文件 (*.png *.jpg *.jpeg *.webp);;所有文件 (*.*)")
        if p:
            self._upload_asset("scene", p, "数字人场景-" + os.path.basename(p), "image")

    def upload_sound(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择TTS声音/配音文件", "", "音频文件 (*.mp3 *.wav *.m4a *.ogg);;所有文件 (*.*)")
        if p:
            self._upload_asset("sound", p, "数字人TTS声音-" + os.path.basename(p), "audio")

    def gen_avatar(self):
        desc = self.avatar_desc.text().strip()
        if not desc:
            self.status.setText("请先填形象描述,或点『快速形象』预设")
            return
        self.b_avatar.setEnabled(False)
        self.status.setText("AI 生成数字人形象中…(约 20-40s)")
        size = DH_ASPECT_SIZE.get(self.aspect.currentText(), "1024x1536")
        full = desc + ",写实人像照片,正脸清晰,只有一个人物,高清"

        def work():
            try:
                url = lk888_portrait_url(full, size=size)
                path = os.path.join(data_dir(), "dh_avatar_%d.png" % int(time.time()))
                _wf_download(url, path)
                BRIDGE.payload.emit("dh_avatar", {"ok": True, "url": url, "path": path})
            except Exception as e:
                BRIDGE.payload.emit("dh_avatar", {"ok": False, "error": str(e)[:140]})
        run_bg(work)

    def gen(self):
        if not self._avatar_url:
            self.status.setText("请先『AI 生成形象』(或点快速形象预设)")
            return
        t = self.text.toPlainText().strip()
        if not t:
            self.status.setText("请输入口播文案")
            return
        self.btn.setEnabled(False)
        voice_id = DH_VOICES[max(0, self.voice.currentIndex())][1]
        mode = "pro" if self.mode.currentIndex() == 1 else "std"
        avatar_input = self._avatar_url if _is_remote_fetchable_media_url(self._avatar_url) else self._avatar_path
        generate_digital_human(avatar_input, t, voice_id=voice_id, mode=mode,
                               sound_url=self._sound_url, scene_url=self._scene_url, scene_path=self._scene_path)

    def write_script(self):
        topic = self.topic.text().strip()
        if not topic:
            self.status.setText("请先填产品/主题,再让 AI 写口播稿")
            return
        use_kb = self.use_kb.isChecked()
        self.b_script.setEnabled(False)
        self.status.setText("检索知识库 + 写口播稿…" if use_kb else "AI 写口播稿…")

        def work():
            kb = kb_context(topic) if use_kb else ""
            sysmsg = "你是资深口播稿撰写人,输出可直接朗读的中文短视频口播稿,开场有钩子、口语自然、结尾有行动号召,不要任何解释说明、不要分镜标记。"
            prompt = ("为【%s】写一条约100-140字的口播稿。" % topic) + kb
            try:
                txt = lk888_chat(prompt, system=sysmsg, model="gpt-5.4-xhigh", max_tokens=600, temperature=0.85)
                BRIDGE.payload.emit("dh_script", {"ok": True, "text": txt, "kb": bool(kb)})
            except Exception as e:
                BRIDGE.payload.emit("dh_script", {"ok": False, "error": str(e)[:140]})
        run_bg(work)

    def _on(self, tag, d):
        if tag == "digital_human_seed":
            d = d or {}
            self.topic.setText(str(d.get("topic") or d.get("sourceUrl") or "分解视频"))
            self.avatar_desc.setText(str(d.get("avatarDescription") or ""))
            self.text.setPlainText(str(d.get("script") or ""))
            self.status.setText("已从分解视频带入口播稿和数字人形象描述，可修改后再生成。")
            return
        if tag == "dh_asset":
            kind = (d or {}).get("kind")
            btn = {"avatar": self.b_upload_avatar, "scene": self.b_upload_scene, "sound": self.b_upload_sound}.get(kind)
            if btn:
                btn.setEnabled(True)
            if not (d or {}).get("ok"):
                self.status.setText("上传失败:" + str((d or {}).get("error") or ""))
                return
            url = (d or {}).get("url") or ""
            path = (d or {}).get("path") or ""
            if kind == "avatar":
                self._avatar_url = url
                self._avatar_path = path if path and os.path.isfile(path) else ""
                self._set_image_preview(self.avatar_lbl, path)
                self.status.setText("人物形象已上传 ✓")
            elif kind == "scene":
                self._scene_url = url
                self._scene_path = path if path and os.path.isfile(path) else ""
                self._set_image_preview(self.scene_lbl, path)
                self.status.setText("场景图已上传 ✓")
            elif kind == "sound":
                self._sound_url = url
                self.status.setText("TTS 声音已上传 ✓ 生成时将直接使用该音频")
            flags = []
            flags.append("人物:" + ("已选" if self._avatar_url else "未选"))
            flags.append("场景:" + ("已选" if self._scene_url else "未选"))
            flags.append("声音:" + ("已上传音频" if self._sound_url else "自动TTS"))
            self.asset_status.setText(" · ".join(flags))
            return
        if tag == "dh_avatar":
            self.b_avatar.setEnabled(True)
            if (d or {}).get("ok"):
                self._avatar_url = (d or {}).get("url")
                p = (d or {}).get("path")
                self._avatar_path = p if p and os.path.isfile(p) else ""
                if p and os.path.isfile(p):
                    self._set_image_preview(self.avatar_lbl, p)
                self.asset_status.setText("人物:已选 · 场景:%s · 声音:%s" % (
                    "已选" if self._scene_url else "未选", "已上传音频" if self._sound_url else "自动TTS"))
                self.status.setText("形象已生成 ✓,写好口播稿后点『生成数字人』")
            else:
                self.status.setText("形象生成失败:" + str((d or {}).get("error") or ""))
            return
        if tag == "dh_script":
            self.b_script.setEnabled(True)
            if (d or {}).get("ok"):
                self.text.setPlainText((d or {}).get("text") or "")
                self.status.setText("口播稿已生成 ✓(已引用企业知识库)" if (d or {}).get("kb") else "口播稿已生成 ✓")
            else:
                self.status.setText("口播稿生成失败:" + str((d or {}).get("error") or ""))
            return
        if tag != "digital_human":
            return
        composed_url = str((d or {}).get("composed_avatar_url") or "").strip()
        if composed_url:
            self._composed_avatar_url = composed_url
            self.status.setToolTip(composed_url)
        status_text = (d or {}).get("msg") or ""
        if self._composed_avatar_url:
            status_text += "\n系统中间合成图：%s" % self._composed_avatar_url
            self.status.setToolTip(self._composed_avatar_url)
        self.status.setText(status_text)
        st = (d or {}).get("stage")
        if st in ("done", "error"):
            self.btn.setEnabled(True)
        if st == "done":
            self._path = (d or {}).get("path")
            if self._path:
                ok = self.vbox.play(self._path)
                self._wire_video_state()
                self.play_toggle.setEnabled(bool(ok))
                self.play_toggle.setText("\u6682\u505c" if ok else "\u64ad\u653e")
                QtCore.QTimer.singleShot(250, self._sync_video_controls)

    def _wire_video_state(self):
        player = self.vbox.player
        if player is None or getattr(self, "_video_state_player", None) is player:
            return
        self._video_state_player = player
        try:
            player.playbackStateChanged.connect(lambda _state: self._sync_video_controls())
        except Exception:
            pass

    def _sync_video_controls(self):
        has_video = bool(self._path and os.path.isfile(self._path) and self.vbox.player is not None)
        self.play_toggle.setEnabled(has_video)
        self.play_toggle.setText("\u6682\u505c" if has_video and self.vbox.is_playing() else "\u64ad\u653e")

    def _toggle_video(self):
        if not (self._path and os.path.isfile(self._path)):
            self.status.setText("\u8fd8\u6ca1\u6709\u751f\u6210\u89c6\u9891")
            self._sync_video_controls()
            return
        if self.vbox.is_playing():
            self.vbox.pause()
        else:
            if self.vbox.player is None:
                self.vbox.play(self._path)
            else:
                self.vbox.resume()
        self._sync_video_controls()

    def _save(self):
        if not (self._path and os.path.isfile(self._path)):
            self.status.setText("还没有生成视频")
            return
        import shutil as _sh
        default = os.path.join(os.path.expanduser("~"), "数字人口播_%d.mp4" % int(time.time()))
        dst, _f = QtWidgets.QFileDialog.getSaveFileName(self, "导出数字人视频", default, "MP4 视频 (*.mp4)")
        if not dst:
            return
        try:
            _sh.copyfile(self._path, dst)
            self.status.setText("已导出到:" + dst)
        except Exception as e:
            self.status.setText("导出失败:" + str(e)[:80])


_REPLACEMENT_ERROR_DISPLAY = {
    "replacement_qc_failed:face_mismatch": "质检失败：人物人脸与授权参考图不一致，请更换清晰授权人脸图或单段重试。",
    "replacement_qc_failed:face_similarity_low": "质检失败：人物人脸相似度低于阈值，请更换清晰授权人脸图、开启高一致模式或单段重试。",
    "replacement_qc_failed:product_mismatch": "质检失败：产品、标志或包装文字与参考图不一致，请更换清晰产品图或单段重试。",
    "replacement_qc_failed:scene_mismatch": "质检失败：生成场景与场景参考图或描述不一致，请调整场景图后单段重试。",
    "replacement_qc_failed:visual_qc_failed": "质检失败：视觉审核服务异常，请稍后单段重试。",
    "replacement_qc_failed:visual_qc_invalid_response": "质检失败：视觉审核返回内容无法解析，请稍后单段重试。",
    "replacement_qc_failed:audio_missing": "质检失败：生成片段缺少音轨，请单段重试。",
    "replacement_qc_failed:audio_silent": "质检失败：生成片段音频为空或音量过低，请单段重试。",
    "replacement_qc_failed:media_invalid": "质检失败：生成片段不是有效视频，请单段重试。",
    "replacement_qc_failed:qc_frames_incomplete": "质检失败：未能提取首、中、尾审核帧，请单段重试。",
    "image_result_url_not_public": "图片生成结果无法被远程模型读取，请检查公网图片服务后重试。",
    "video_replace_source_segment_url_missing": "源片段缺少可用公网地址，请重新生成替换方案。",
    "video_replace_source_segment_url_not_public": "源片段地址不是公网可访问地址，请检查素材上传配置。",
    "video_replace_remote_media_required": "源片段地址不是公网可访问地址，请先配置公网素材代理或公网媒体上传服务后重试。",
    "facefusion_timeout": "本地换脸增强超时：已回退远程同款结果，可继续审核；如需提高一致性，请缩短片段、调低换脸配置，或切换高性能换脸环境。",
    "reference_mismatch": "参考图与原视频主题或产品类别冲突，请更换参考图后重试。",
    "visual_drift_blocked": "生成内容偏离原视频主题，已阻断合成。",
    "topic_mismatch": "生成内容主题与原视频不一致。",
    "role_mismatch": "生成人物角色与原视频不一致。",
    "structure_mismatch": "生成镜头结构与原视频不一致。",
    "visual_drift_retry_exhausted": "重试后仍偏离原视频主题，片段已失败。",
    "edited_video_invalid": "远程编辑返回的视频无效，请单段重试。",
    "replacement_tts_script_missing": "AI 音色配音缺少口播稿，请补齐该片段口播稿后重试。",
    "replacement_tts_audio_too_long": "AI 音色配音长于当前片段，会导致尾部被截断；请缩短该片段口播稿或合并片段后重试。",
    "replacement_uploaded_audio_missing": "未找到上传的完整配音音频，请重新上传后再合成。",
    "replacement_uploaded_audio_too_short": "上传的完整配音短于视频成片，请上传不短于成片时长的配音音频。",
    "replacement_lipsync_model_missing": "未配置“已有视频口型同步”模型。为避免动作、产品和场景跑偏，系统已停止使用数字人模型重生成整段视频；请先配置 VIDEO_REPLACE_LIPSYNC_MODEL 后重试。",
    "replacement_lipsync_video_missing": "口型同步缺少已替换视频，请单段重试。",
    "replacement_lipsync_audio_not_public": "口型同步音频不是公网可读取地址，请检查音频上传服务。",
    "replacement_lipsync_video_not_public": "口型同步视频不是公网可读取地址，请检查视频上传服务。",
    "replacement_lipsync_output_invalid": "口型同步返回的视频无效，请单段重试或切换口型同步模型。",
    "replacement_audio_mux_failed": "音频合成失败，请更换音频文件后重试。",
    "replacement_audio_mux_invalid": "音频合成后未通过检查，请更换音频文件后重试。",
    "replacement_asset_save_failed": "成片保存到资产库失败，请重试合成。",
    "insufficient_balance": "上游余额不足，请充值后重试。",
    "model_not_priced": "模型未配置价格，请联系管理员配置价格后重试。",
    "lk888_not_configured": "上游账号未配置，请检查 LK888 配置后重试。",
    "lk888_tls_required": "上游代理配置不安全，请检查 LK888 HTTPS 配置。",
    "not_authenticated": "登录状态已失效，请重新登录后重试。",
}


def _replacement_error_id_from_text(text):
    match = re.search(r"\berr-[A-Za-z0-9_-]+\b", str(text or ""))
    return match.group(0) if match else ""


def _localize_replacement_display_text(text):
    raw = str(text or "").strip()
    if not raw:
        return ""
    error_id = _replacement_error_id_from_text(raw)
    prefix = ("错误编号 %s；" % error_id) if error_id else ""
    lower = raw.lower()
    for code, message in _REPLACEMENT_ERROR_DISPLAY.items():
        if code in raw:
            return prefix + message
    if "402" in raw and ("insufficient" in lower or "余额不足" in raw):
        return prefix + _REPLACEMENT_ERROR_DISPLAY["insufficient_balance"]
    if "replacement_qc_failed:" in raw:
        return prefix + "质检失败：片段未通过自动质量检查，请查看审核帧后单段重试。"
    if "图片生成超时" in raw or ("图片生成" in raw and (
            " 502" in raw or " 504" in raw or "gateway" in lower
            or "time-out" in lower or "timeout" in lower or "lk888_proxy_error" in raw)):
        return prefix + "图片生成服务暂时不可用或超时，请稍后单段重试。"
    if "lk888_proxy_error" in raw:
        return prefix + "上游生成服务暂时不可用，请稍后重试。"
    if "绿网检查失败" in raw or "输入数据可能包含不适当" in raw:
        return prefix + "上游内容审核未通过：请更换参考视频片段或产品/人物/场景图后单段重试。"
    if "task_timeout" in raw:
        return prefix + "远程生成任务超时，请稍后重试。"
    if error_id and re.search(r"[A-Za-z_]{4,}", raw):
        return prefix + "生成失败，请根据错误编号查看日志。"
    return raw


def _replacement_segment_display_error(segment):
    segment = segment or {}
    error = _localize_replacement_display_text(segment.get("error") or "")
    error_id = str(segment.get("errorId") or "").strip()
    if error_id and error:
        if error_id in error:
            return error
        return "错误编号 %s；%s" % (error_id, error)
    if error_id:
        return "错误编号 %s" % error_id
    if error:
        return error
    completed = (
        str(segment.get("status") or "") == "done"
        and bool(str(segment.get("videoPath") or "").strip())
    )
    if not completed:
        remote_error = _localize_replacement_display_text(segment.get("remoteError") or "")
        remote_error_id = str(segment.get("remoteErrorId") or "").strip()
        if remote_error_id and remote_error:
            return "错误编号 %s；%s" % (remote_error_id, remote_error)
        if remote_error_id:
            return "错误编号 %s" % remote_error_id
        if remote_error:
            return remote_error
    facefusion_error = _localize_replacement_display_text(segment.get("facefusionError") or "")
    facefusion_error_id = str(segment.get("facefusionErrorId") or "").strip()
    if facefusion_error_id and facefusion_error:
        return "错误编号 %s；%s" % (facefusion_error_id, facefusion_error)
    if facefusion_error_id:
        return "错误编号 %s" % facefusion_error_id
    return facefusion_error


def _replacement_preflight_failure(code, summary="", retryable=True, next_action=""):
    code = str(code or "upstream_preflight_failed").strip() or "upstream_preflight_failed"
    summary = _localize_replacement_display_text(summary or code)
    if not next_action:
        if code == "insufficient_balance":
            next_action = "充值后重新执行替换生成"
            retryable = False
        elif code == "model_not_priced":
            next_action = "联系管理员配置模型价格"
            retryable = False
        elif code in ("lk888_not_configured", "lk888_tls_required", "not_authenticated"):
            next_action = "检查上游账号配置或重新登录"
            retryable = False
        else:
            next_action = "稍后重试或联系管理员检查上游服务"
    return {
        "ok": False,
        "status": "blocked",
        "code": code,
        "summary": summary,
        "retryable": bool(retryable),
        "nextAction": next_action,
    }


def _replacement_upstream_preflight(job=None):
    job = job or {}
    if str(os.getenv("VIDEO_REPLACE_UPSTREAM_PREFLIGHT", "1")).strip().lower() in ("0", "false", "no", "off"):
        return {"ok": True, "status": "skipped", "code": "skipped", "summary": "上游预检已关闭"}
    try:
        balance = fetch_balance()
    except Exception:
        balance = None
    if balance is not None:
        try:
            if str(balance).lower() != "inf" and float(balance) <= 0:
                result = _replacement_preflight_failure(
                    "insufficient_balance",
                    "上游余额不足，请充值后重试。",
                    retryable=False,
                    next_action="充值后重新执行替换生成",
                )
                result["balance"] = balance
                return result
        except (TypeError, ValueError):
            pass
    code, payload = api("GET", "/lk888/v1/models", timeout=15)
    payload = payload if isinstance(payload, dict) else {}
    if code == 200:
        return {
            "ok": True,
            "status": "passed",
            "code": "ok",
            "summary": "上游账号和余额预检通过",
            "balance": balance,
        }
    err = str(payload.get("error") or payload.get("code") or "").strip()
    message = str(payload.get("message") or payload.get("detail") or err or ("http_%s" % code))
    if code == 402 and not err:
        err = "insufficient_balance"
    if not err:
        if code in (401, 403):
            err = "not_authenticated"
        elif code == 503:
            err = "lk888_not_configured"
        elif code in (0, 502, 504):
            err = "lk888_proxy_error"
        else:
            err = "upstream_preflight_failed"
    result = _replacement_preflight_failure(
        err,
        message,
        retryable=err in ("lk888_proxy_error", "upstream_preflight_failed"),
    )
    result.update({"httpStatus": code, "balance": balance})
    return result


def _replacement_diagnostics_summary(job, preflight=None):
    job = job or {}
    preflight = preflight if isinstance(preflight, dict) else {}
    failed_segments = []
    segment_error_ids = []
    for segment in list(job.get("segments") or []):
        if (segment or {}).get("status") == "failed":
            failed_segments.append(segment.get("index"))
            if segment.get("errorId"):
                segment_error_ids.append(segment.get("errorId"))
    code = str(preflight.get("code") or job.get("error") or "").strip()
    error_id = str(job.get("errorId") or preflight.get("errorId") or "").strip()
    summary_source = preflight.get("summary") or job.get("error") or code or "任务需要人工检查"
    summary = _localize_replacement_display_text(summary_source) or "任务需要人工检查"
    retryable = bool(preflight.get("retryable", True))
    next_action = str(preflight.get("nextAction") or "").strip()
    if not next_action:
        if "insufficient_balance" in code:
            next_action = "充值后重新执行替换生成"
            retryable = False
        elif failed_segments:
            next_action = "可点击『重试失败片段』重新生成失败片段"
        else:
            next_action = "根据错误编号查看日志后重试"
    return {
        "summary": summary,
        "errorId": error_id,
        "retryable": retryable,
        "nextAction": next_action,
        "failedSegments": failed_segments,
        "segmentErrorIds": segment_error_ids,
    }


_REPLACEMENT_STAGE_LABELS = {
    "uploading": "上传参考素材",
    "editing": "准备生成",
    "keyframing": "生成替换关键帧",
    "tts": "合成口播音频",
    "digital_human": "生成数字人口播",
    "audio_clip": "裁切上传配音",
    "lipsync": "同步视频口型",
    "video_edit": "生成同款视频",
    "principal_video_edit": "主角整身替换",
    "downloading": "下载生成结果",
    "facefusion": "执行人脸替换",
    "face_swapping": "执行人脸替换",
    "audio_muxing": "回填音频",
    "qc": "自动质检",
    "done": "片段完成",
    "awaiting_review": "等待人工审核",
}

_REPLACEMENT_STAGE_REMAINING_RATIO = {
    "pending": 1.0,
    "planned": 1.0,
    "editing": 0.95,
    "keyframing": 0.90,
    "tts": 0.72,
    "digital_human": 0.62,
    "audio_clip": 0.66,
    "lipsync": 0.48,
    "video_edit": 0.80,
    "principal_video_edit": 0.80,
    "downloading": 0.24,
    "facefusion": 1.0,
    "face_swapping": 1.0,
    "audio_muxing": 0.16,
    "qc": 0.10,
}

_REPLACEMENT_PROGRESS_CALLBACKS = {}


def _env_enabled(name, default="0"):
    return str(os.getenv(name, default) or default).strip().lower() in ("1", "true", "yes", "on")


_REPLACEMENT_IDENTITY_MODES = ("fast", "standard", "high")


def _replacement_identity_mode(job=None):
    job = job or {}
    raw = str(job.get("identityMode") or "").strip().lower()
    if raw in _REPLACEMENT_IDENTITY_MODES:
        return raw
    if job.get("enableFaceFusion") is True or str(job.get("enableFaceFusion") or "").strip().lower() in ("1", "true", "yes", "on"):
        return "high"
    return "standard"


def _replacement_identity_mode_label(mode):
    mode = str(mode or "").strip().lower()
    if mode == "fast":
        return "快速模式"
    if mode == "high":
        return "高一致模式"
    return "标准模式"


def _replacement_enable_facefusion(job=None):
    job = job or {}
    if _replacement_no_person_mode(job) or _principal_replacement_enabled(job):
        return False
    mode = _replacement_identity_mode(job)
    if mode == "high":
        return True
    if mode == "standard":
        # 标准模式默认执行本地换脸锚定，以任务创建时写入的开关为准：
        # 创建时 FaceFusion 不可用（降级）或旧任务（缺省/False）保持原远程链路。
        value = job.get("enableFaceFusion")
        return value is True or str(value or "").strip().lower() in ("1", "true", "yes", "on")
    return False


def _replacement_enable_digital_human_facefusion(job=None, segment=None):
    job = job or {}
    segment = segment or {}
    if _replacement_no_person_mode(job) or _principal_replacement_enabled(job):
        return False
    if segment.get("segmentType") != "talking":
        return False
    if not (job.get("faceSourcePaths") or []):
        return False
    return _replacement_identity_mode(job) == "high"


def _replacement_visual_qc_blocks(job=None):
    job = job or {}
    value = job.get("strictVisualQc")
    if value is not None:
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return _env_enabled("VIDEO_REPLACE_STRICT_VISUAL_QC", "0")


def _replacement_principal_visual_qc_blocks(job=None, code=""):
    code = str(code or "").strip()
    if not code.startswith("principal_"):
        return False
    if code != "principal_appearance_mismatch":
        return True
    if _replacement_visual_qc_blocks(job):
        return True
    return _replacement_identity_mode(job) == "high"


def _replacement_drift_guard_enabled(job=None):
    job = job or {}
    env_value = os.getenv("VIDEO_REPLACE_DRIFT_GUARD")
    if env_value is not None and str(env_value).strip().lower() in ("0", "false", "no", "off"):
        return False
    value = job.get("driftGuardEnabled")
    if value is not None:
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return _env_enabled("VIDEO_REPLACE_DRIFT_GUARD", "1")


def _replacement_reference_preflight_enabled(job=None):
    if not _replacement_drift_guard_enabled(job):
        return False
    job = job or {}
    value = job.get("referencePreflightEnabled")
    if value is not None:
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return _env_enabled("VIDEO_REPLACE_REFERENCE_PREFLIGHT", "1")


def _replacement_block_severe_drift(job=None):
    if not _replacement_drift_guard_enabled(job):
        return False
    job = job or {}
    value = job.get("blockSevereDrift")
    if value is not None:
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return _env_enabled("VIDEO_REPLACE_BLOCK_SEVERE_DRIFT", "1")


def _replacement_drift_auto_retry_enabled(job=None):
    if not _replacement_drift_guard_enabled(job):
        return False
    job = job or {}
    value = job.get("driftAutoRetry")
    if value is not None:
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return _env_enabled("VIDEO_REPLACE_DRIFT_AUTO_RETRY", "1")


def _replacement_drift_max_retries(job=None):
    job = job or {}
    raw = job.get("driftMaxRetries")
    if raw is None:
        raw = os.getenv("VIDEO_REPLACE_DRIFT_MAX_RETRIES", "1")
    try:
        return max(0, min(3, int(raw)))
    except (TypeError, ValueError):
        return 1


def _replacement_drift_guard_config(job=None):
    return {
        "enabled": _replacement_drift_guard_enabled(job),
        "preflightEnabled": _replacement_reference_preflight_enabled(job),
        "blockSevereDrift": _replacement_block_severe_drift(job),
        "autoRetry": _replacement_drift_auto_retry_enabled(job),
        "maxRetries": _replacement_drift_max_retries(job),
    }


def _replacement_qc_warning_severity(code):
    code = str(code or "").strip()
    if code in ("visual_qc_deferred", "visual_qc_invalid_response"):
        return "deferred"
    if _replacement_is_hard_drift_code(code):
        return "blocking"
    if code in (
            "face_mismatch", "product_mismatch", "scene_mismatch",
            "role_mismatch", "structure_mismatch",
            "visual_qc_failed", "facefusion_failed", "face_similarity_low"):
        return "review_warning"
    return "review_warning"


def _replacement_is_hard_drift_code(code):
    return str(code or "").strip() in (
        "visual_drift_blocked",
        "topic_mismatch",
        "visual_drift_retry_exhausted",
    )


def _replacement_is_severe_drift_code(code):
    return _replacement_is_hard_drift_code(code)


def _replacement_can_retry_drift(job, segment, qc=None):
    if not _replacement_drift_auto_retry_enabled(job):
        return False
    qc = qc or {}
    if not _replacement_is_hard_drift_code(qc.get("code")):
        return False
    try:
        current = int((segment or {}).get("driftRetryCount") or 0)
    except (TypeError, ValueError):
        current = 0
    return current < _replacement_drift_max_retries(job)


def _replacement_mark_drift_retry(job, segment, qc=None):
    job = job or {}
    segment = segment or {}
    qc = qc or {}
    try:
        current = int(segment.get("driftRetryCount") or 0)
    except (TypeError, ValueError):
        current = 0
    segment["driftRetryCount"] = current + 1
    segment["retryReason"] = qc.get("code") or "visual_drift_blocked"
    segment["status"] = "video_edit"
    segment["qcStatus"] = "retrying"
    visual = qc.get("visual") or {}
    segment.setdefault("qcWarnings", []).append({
        "code": qc.get("code") or "visual_drift_blocked",
        "reason": str(visual.get("reason") or qc.get("reason") or "生成内容偏离原视频主题")[:180],
        "severity": "blocking",
    })
    _replacement_error_id(
        "video_replace_visual_drift_retry",
        RuntimeError(segment["retryReason"]),
        segment_index=segment.get("index"),
        retry_count=segment["driftRetryCount"],
        source_video=job.get("sourceVideoPath") or "",
    )


def _replacement_ai_scene_fallback_active(segment=None):
    return str((segment or {}).get("sceneFallbackMode") or "").strip() == "ai_generated"


def _replacement_ai_scene_fallback_note(job=None, segment=None):
    if not _replacement_ai_scene_fallback_active(segment):
        return ""
    reason = _replacement_excerpt((segment or {}).get("sceneFallbackReason") or "", 180)
    scene_hint = str((job or {}).get("scenePrompt") or "同类门店、展厅或产品展示环境").strip()
    return (
        "场景降级：上一版上传场景与原片动作发生冲突%s。"
        "本段不再强制照搬上传场景图，改为 AI 生成场景：与原片行业一致的%s；"
        "禁止生成户外公路、无关外景或跨行业背景。产品参考仍为最高优先级，"
        "产品必须保持上传产品的外形、颜色、Logo、主要包装文字、材质和展示位置，不得替换成其他产品。"
        % (("：" + reason) if reason else "", scene_hint[:120])
    )


def _replacement_can_retry_ai_scene_fallback(job, segment, qc=None):
    job = job or {}
    segment = segment or {}
    qc = qc or {}
    if not job.get("sceneImageUrl"):
        return False
    if _replacement_ai_scene_fallback_active(segment):
        return False
    code = str(qc.get("code") or "").strip()
    if code not in ("scene_mismatch", "principal_motion_mismatch"):
        return False
    checks = qc.get("checks") or {}
    if checks.get("product") == "failed" or checks.get("logoText") == "failed":
        return False
    if checks.get("face") == "failed" or checks.get("principalReplacement") == "failed":
        return False
    return True


def _replacement_mark_ai_scene_fallback(job, segment, qc=None):
    del job
    segment = segment or {}
    qc = qc or {}
    segment["sceneFallbackMode"] = "ai_generated"
    segment["sceneFallbackReason"] = str(qc.get("reason") or qc.get("code") or "scene_mismatch")[:240]
    try:
        segment["sceneFallbackCount"] = int(segment.get("sceneFallbackCount") or 0) + 1
    except (TypeError, ValueError):
        segment["sceneFallbackCount"] = 1
    history = list(segment.get("sceneFallbackHistory") or [])
    history.append({
        "code": qc.get("code") or "scene_mismatch",
        "reason": segment["sceneFallbackReason"],
        "checks": dict(qc.get("checks") or {}),
    })
    segment["sceneFallbackHistory"] = history[-3:]
    segment["qcStatus"] = "retrying"
    segment["error"] = ""
    segment["errorId"] = ""

def _replacement_mark_drift_exhausted(segment, qc=None):
    segment = segment or {}
    qc = qc or {}
    visual = qc.get("visual") or {}
    segment["status"] = "failed"
    segment["qcStatus"] = "failed"
    segment["blockedReason"] = "visual_drift_retry_exhausted"
    segment["error"] = "visual_drift_retry_exhausted"
    segment.setdefault("qcWarnings", []).append({
        "code": "visual_drift_retry_exhausted",
        "reason": str(visual.get("reason") or "重试后仍偏离原视频主题")[:180],
        "severity": "blocking",
    })


def _facefusion_timeout_sec():
    try:
        value = int(float(os.getenv("FACEFUSION_TIMEOUT_SEC", "420") or "420"))
    except (TypeError, ValueError):
        value = 420
    return max(30, min(value, 1800))


def _replacement_truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _replacement_avatar_segments_enabled():
    return _replacement_truthy(os.getenv("VIDEO_REPLACE_ENABLE_AVATAR_SEGMENTS", "0"))


def _replacement_strict_script_audio_enabled(job=None):
    job = job or {}
    value = job.get("strictScriptAudio")
    if value is not None:
        return _replacement_truthy(value)
    return _replacement_truthy(os.getenv("VIDEO_REPLACE_STRICT_SCRIPT_AUDIO", "0"))


def _replacement_action_control_enabled(job=None):
    job = job or {}
    value = job.get("actionControlEnabled")
    if value is not None:
        return _replacement_truthy(value)
    return _replacement_truthy(os.getenv("VIDEO_REPLACE_ACTION_CONTROL", "0"))


def _replacement_segment_has_script(segment):
    return bool(str((segment or {}).get("script") or "").strip())


def _replacement_segment_should_talk(segment, audio_mode="source", strict_script_audio=False):
    del strict_script_audio
    mode = _replacement_audio_mode({"audioMode": audio_mode})
    if mode not in ("tts", "uploaded"):
        return False
    return _replacement_segment_has_script(segment)


def _format_duration_zh(seconds):
    try:
        total = int(round(float(seconds or 0)))
    except (TypeError, ValueError):
        total = 0
    total = max(0, total)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return "%d小时%02d分%02d秒" % (hours, minutes, secs)
    if minutes:
        return "%d分%02d秒" % (minutes, secs)
    return "%d秒" % secs


def _estimate_replacement_tts_duration_sec(text):
    value = re.sub(r"\s+", "", str(text or "").strip())
    if not value:
        return 0.0
    chars_per_sec = 4.2
    try:
        configured = float(os.getenv("VIDEO_REPLACE_TTS_CHARS_PER_SEC", "") or 0)
        if configured > 0:
            chars_per_sec = configured
    except (TypeError, ValueError):
        chars_per_sec = 4.2
    chars_per_sec = max(2.5, min(chars_per_sec, 8.0))
    punctuation_pause = len(re.findall(r"[，。！？；、,.!?;:：]", value)) * 0.12
    return round((len(value) / chars_per_sec) + punctuation_pause, 2)


def _replacement_tts_max_speed(job=None):
    job = job or {}
    raw = job.get("ttsMaxSpeed")
    if raw in (None, ""):
        raw = os.getenv("VIDEO_REPLACE_TTS_MAX_SPEED", "1.45")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 1.45
    return round(max(1.0, min(value, 2.0)), 3)


def _replacement_tts_timing_issues(segments, audio_mode="tts"):
    if str(audio_mode or "").strip().lower() != "tts":
        return []
    max_speed = _replacement_tts_max_speed()
    issues = []
    for idx, segment in enumerate(list(segments or [])):
        script = str((segment or {}).get("script") or "").strip()
        if not script:
            continue
        try:
            duration = max(0.1, float((segment or {}).get("duration") or 0))
        except (TypeError, ValueError):
            duration = 0.0
        estimated = _estimate_replacement_tts_duration_sec(script)
        if duration > 0 and estimated > duration * max_speed + 0.25:
            issues.append({
                "index": int((segment or {}).get("index") or idx + 1),
                "durationSec": round(duration, 2),
                "estimatedSec": estimated,
                "maxSpeed": max_speed,
                "requiredSpeed": round(estimated / duration, 2),
                "overBySec": round(max(0.0, estimated - duration), 2),
            })
    return issues


def _format_replacement_tts_timing_block_message(issues):
    first = (issues or [None])[0] or {}
    if not first:
        return ""
    total = len(issues or [])
    suffix = "" if total <= 1 else "；另有 %d 个片段也超长" % (total - 1)
    return (
        "第 %(index)s 段口播预计 %(estimatedSec).1f 秒，当前片段只有 %(durationSec).1f 秒，"
        "需要约 %(requiredSpeed).2fx 语速，超过自动提速上限 %(maxSpeed).2fx；"
        "请缩短该片段口播稿，或先合并/拉长片段后再生成%(suffix)s。"
        % dict(first, suffix=suffix)
    )


_REPLACEMENT_SUBTITLE_SUSPECT_WORDS = {
    "详经地": "疑似“详细地”识别错误",
    "洋经地": "疑似“详细地”识别错误",
    "祥经地": "疑似“详细地”识别错误",
    "介召": "疑似“介绍”识别错误",
}


def _replacement_subtitle_text_issues(segments):
    issues = []
    mojibake_markers = ("�", "鎶", "鏃", "鍙", "绯", "璇", "涓", "鐢", "瑙", "闊")
    for idx, segment in enumerate(segments or [], 1):
        segment = segment or {}
        index = segment.get("index") or idx
        script = str(segment.get("script") or "").strip()
        if not script:
            continue
        if any(marker in script for marker in mojibake_markers):
            issues.append({
                "index": index,
                "code": "subtitle_mojibake",
                "text": script[:80],
                "reason": "字幕文本疑似编码乱码或 OCR 乱码",
            })
            continue
        for word, reason in _REPLACEMENT_SUBTITLE_SUSPECT_WORDS.items():
            if word in script:
                issues.append({
                    "index": index,
                    "code": "suspect_subtitle_word",
                    "text": script[:80],
                    "reason": reason,
                })
                break
        else:
            if segment.get("scriptReviewed") is not True:
                issues.append({
                    "index": index,
                    "code": "subtitle_not_reviewed",
                    "text": script[:80],
                    "reason": "口播稿来自自动识别，生成前建议人工确认",
                })
    return issues


def _format_replacement_subtitle_issue_message(issues):
    lines = ["检测到口播字幕可能有错字或未人工确认："]
    for item in list(issues or [])[:8]:
        lines.append("片段 %s：%s（%s）" % (
            item.get("index") or "-",
            item.get("reason") or item.get("code") or "待确认",
            item.get("text") or "",
        ))
    if len(issues or []) > 8:
        lines.append("还有 %d 条未显示。" % (len(issues) - 8))
    lines.append("选择“是”表示已确认这些字幕并继续生成；选择“否”返回片段表修改口播稿。")
    return "\n".join(lines)


def _replacement_stage_label(stage):
    value = str(stage or "").strip()
    return _REPLACEMENT_STAGE_LABELS.get(value, value or "处理中")


def _replacement_progress_text(message, timing=None):
    timing = timing or {}
    text = _localize_replacement_display_text(message or _replacement_stage_label(timing.get("stage")))
    parts = [text]
    elapsed = timing.get("elapsedSec")
    if elapsed is not None:
        parts.append("已用时 " + _format_duration_zh(elapsed))
    eta = timing.get("etaSec")
    if eta is not None and float(eta or 0) > 0:
        parts.append("预计剩余 " + _format_duration_zh(eta))
    return " · ".join(parts)


def _replacement_progress_detail_text(timing=None):
    timing = timing or {}
    elapsed = timing.get("elapsedSec")
    eta = timing.get("etaSec")
    elapsed_text = _format_duration_zh(elapsed) if elapsed is not None else "-"
    eta_text = _format_duration_zh(eta) if eta is not None and float(eta or 0) > 0 else "-"
    return "用时: %s · 预计剩余: %s" % (elapsed_text, eta_text)


def _replacement_segment_baseline_sec(segment):
    segment = segment or {}
    base = 420 if segment.get("segmentType") == "talking" else 240
    if str(segment.get("stage") or segment.get("status") or "").strip() in ("facefusion", "face_swapping"):
        base = _facefusion_timeout_sec()
    try:
        duration = max(1.0, float(segment.get("duration") or 8.0))
    except (TypeError, ValueError):
        duration = 8.0
    return int(round(base * max(0.5, min(duration / 8.0, 2.0))))


def _replacement_segments_same(left, right):
    if left is right:
        return True
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    try:
        return int(left.get("index") or -1) == int(right.get("index") or -2)
    except (TypeError, ValueError):
        return False


def _replacement_segment_elapsed_sec(segment, now=None):
    segment = segment or {}
    now = time.time() if now is None else float(now)
    if segment.get("segmentEndedAt") and segment.get("segmentStartedAt"):
        try:
            return max(0, int(round(float(segment["segmentEndedAt"]) - float(segment["segmentStartedAt"]))))
        except (TypeError, ValueError):
            pass
    if segment.get("segmentStartedAt"):
        try:
            return max(0, int(round(now - float(segment.get("segmentStartedAt") or now))))
        except (TypeError, ValueError):
            return 0
    try:
        return max(0, int(round(float(segment.get("elapsedSec") or 0))))
    except (TypeError, ValueError):
        return 0


def _replacement_segment_remaining_sec(segment, stage="", now=None):
    segment = segment or {}
    status = str(segment.get("status") or "pending")
    if status in ("done", "failed", "canceled"):
        return 0
    stage_key = str(stage or segment.get("stage") or status or "pending")
    ratio = _REPLACEMENT_STAGE_REMAINING_RATIO.get(stage_key, 0.5)
    baseline = _replacement_segment_baseline_sec(segment)
    estimate = baseline * ratio
    if segment.get("segmentStartedAt"):
        estimate -= _replacement_segment_elapsed_sec(segment, now=now)
    floor = 0 if status in ("done", "failed", "canceled") else max(10, int(baseline * 0.05))
    return max(floor, int(round(estimate)))


def _replacement_timing_snapshot(job, segment=None, stage="", now=None):
    job = job or {}
    now = time.time() if now is None else float(now)
    try:
        started = float(job.get("startedAt") or job.get("createdAt") or now)
    except (TypeError, ValueError):
        started = now
    elapsed = max(0, int(round(now - started)))
    stage_key = str(stage or (segment or {}).get("stage") or (segment or {}).get("status") or "").strip()
    segments = list(job.get("segments") or [])
    eta = 0
    segment_eta = 0
    segment_elapsed = _replacement_segment_elapsed_sec(segment, now=now) if segment else 0
    matched = False
    for item in segments:
        item_stage = stage_key if segment is not None and _replacement_segments_same(item, segment) else (
            item.get("stage") or item.get("status") or "pending"
        )
        remaining = _replacement_segment_remaining_sec(item, item_stage, now=now)
        eta += remaining
        if segment is not None and _replacement_segments_same(item, segment):
            matched = True
            segment_eta = remaining
            segment_elapsed = _replacement_segment_elapsed_sec(item, now=now)
    if segment is not None and not matched:
        segment_eta = _replacement_segment_remaining_sec(segment, stage_key, now=now)
        eta += segment_eta
    return {
        "elapsedSec": elapsed,
        "etaSec": max(0, int(round(eta))),
        "stage": stage_key,
        "stageLabel": _replacement_stage_label(stage_key),
        "segmentElapsedSec": segment_elapsed,
        "segmentEtaSec": max(0, int(round(segment_eta))),
        "segmentIndex": (segment or {}).get("index") if segment else None,
    }


def _replacement_segment_timing_text(segment):
    segment = segment or {}
    status = str(segment.get("status") or "")
    elapsed = _replacement_segment_elapsed_sec(segment)
    try:
        eta = int(round(float(segment.get("etaSec") or 0)))
    except (TypeError, ValueError):
        eta = 0
    if status == "done":
        return "耗时 " + _format_duration_zh(elapsed)
    if status in ("pending", "planned", ""):
        estimate = eta or _replacement_segment_baseline_sec(segment)
        return "预计 " + _format_duration_zh(estimate)
    parts = []
    if elapsed:
        parts.append("已用 " + _format_duration_zh(elapsed))
    if eta:
        parts.append("剩余 " + _format_duration_zh(eta))
    return " / ".join(parts) if parts else "-"


def _replacement_qc_warning_text(warnings):
    values = []
    names = {
        "face_mismatch": "人物不一致",
        "product_mismatch": "产品不一致",
        "scene_mismatch": "场景不一致",
        "visual_qc_failed": "视觉质检异常",
        "visual_qc_invalid_response": "质检返回异常",
    }
    for item in list(warnings or [])[:2]:
        if isinstance(item, dict):
            code = str(item.get("code") or "").strip()
            reason = str(item.get("reason") or "").strip()
        else:
            code = str(item or "").strip()
            reason = ""
        if not code and not reason:
            continue
        values.append(names.get(code, code or "质检提醒") + (("：" + reason[:60]) if reason else ""))
    return "；".join(values)


def _replacement_segment_status_text(job, segment):
    job = job or {}
    segment = segment or {}
    total = len(job.get("segments") or []) or 1
    idx = segment.get("index") or 1
    stage = segment.get("stageLabel") or _replacement_stage_label(segment.get("stage") or segment.get("status"))
    parts = ["片段 %s/%s" % (idx, total), str(stage or "处理中")]
    parts.append(_replacement_identity_mode_label(_replacement_identity_mode(job)))
    model = str(segment.get("model") or "").strip()
    if model:
        parts.append("模型 " + model)
    timing = _replacement_segment_timing_text(segment)
    if timing and timing != "-":
        parts.append(timing)
    warning = _replacement_qc_warning_text(segment.get("qcWarnings") or [])
    if warning:
        parts.append("质检提醒：" + warning)
    completed = (
        str(segment.get("status") or "") == "done"
        and bool(str(segment.get("videoPath") or "").strip())
    )
    if not completed:
        remote_error_id = str(segment.get("remoteErrorId") or "").strip()
        remote_error = _localize_replacement_display_text(segment.get("remoteError") or "")
        if remote_error_id:
            if remote_error:
                parts.append("错误编号 %s；%s" % (remote_error_id, remote_error))
            else:
                parts.append("错误编号 " + remote_error_id)
        elif remote_error:
            parts.append(remote_error)
    try:
        retry_count = int(segment.get("driftRetryCount") or 0)
    except (TypeError, ValueError):
        retry_count = 0
    if retry_count:
        parts.append("跑偏重试 %d 次" % retry_count)
    blocked_reason = _localize_replacement_display_text(segment.get("blockedReason") or "")
    drift_reason = str((segment.get("visualDriftQc") or {}).get("reason") or "").strip()
    if blocked_reason:
        parts.append("已阻断合成：" + blocked_reason)
    if drift_reason:
        parts.append(drift_reason[:80])
    display_error = _replacement_segment_display_error(segment)
    if display_error:
        parts.append(display_error)
    return " · ".join(parts)


def _replacement_emit_stage(job, segment, stage, message="", prompt=None):
    job_id = str((job or {}).get("id") or "")
    callback = _REPLACEMENT_PROGRESS_CALLBACKS.get(job_id)
    if callable(callback):
        callback(segment, stage, message or _replacement_stage_label(stage), prompt=prompt)


def _replacement_cancel_requested(job):
    return bool((job or {}).get("cancelRequested")) or str((job or {}).get("status") or "") == "cancel_requested"


def _replacement_cancel_check(job):
    return lambda: _replacement_cancel_requested(job)


def _replacement_cancel_exception(exc):
    return "lk888_task_cancelled" in str(exc or "")


def _mark_replacement_job_canceled(job, message="任务已取消，中心人脸素材已清理"):
    job = job or {}
    job["status"] = "canceled"
    cleanup = _cleanup_replacement_sensitive_materials(job)
    temporary_cleanup = _cleanup_replacement_temporary_materials(job)
    job["sensitiveCleanup"] = cleanup
    job["temporaryCleanup"] = temporary_cleanup
    _save_replacement_job(job)
    if BRIDGE is not None:
        BRIDGE.payload.emit("video_replace_done", {
            "jobId": job.get("id"), "message": message, "job": job,
        })
    return job


def _delete_replacement_segment(job, segment_index):
    job = job or {}
    try:
        target = int(segment_index)
    except (TypeError, ValueError):
        return False
    segments = list(job.get("segments") or [])
    if len(segments) <= 1:
        return False
    kept = []
    removed = False
    for segment in segments:
        try:
            current = int(segment.get("index") or 0)
        except (TypeError, ValueError):
            current = 0
        if current == target:
            if str(segment.get("status") or "pending") not in ("pending", "planned", ""):
                return False
            removed = True
            continue
        kept.append(segment)
    if not removed:
        return False
    cursor = 0.0
    for index, segment in enumerate(kept, 1):
        segment["index"] = index
        try:
            duration = float(segment.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0:
            try:
                duration = float(segment.get("end") or 0) - float(segment.get("start") or 0)
            except (TypeError, ValueError):
                duration = 0.0
        duration = round(max(0.1, duration), 3)
        segment["start"] = round(cursor, 3)
        cursor += duration
        segment["end"] = round(cursor, 3)
        segment["duration"] = duration
    job["segments"] = kept
    return True


class XhsNoteReplacementPage(BasePage):
    """小红书图文同款：复用已采集图文结构，替换图片和文案后保存为草稿。"""

    def __init__(self):
        super().__init__()
        self._job = {}
        self._preview = {}
        self._source_material = {}
        self._source_image_entries = []
        self._source_image_buttons = {}
        self._source_image_bytes = {}
        self._source_image_generation = 0
        self._template_req_id = 0
        self._request_generation = 0
        self._template_loading = False
        self.v.addWidget(make_header("图文同款", "小红书图文结构复刻 · 先预览替换方案，再保存到素材发布和资产库"))
        self.v.addWidget(prereq_banner("图文同款 V1 只生成草稿，不自动发布；AI 占位图必须人工确认后，后续版本才允许进入真实发布。"))

        source = QtWidgets.QFrame()
        source.setObjectName("card")
        sl = QtWidgets.QGridLayout(source)
        sl.setContentsMargins(16, 14, 16, 14)
        sl.setHorizontalSpacing(12)
        sl.setVerticalSpacing(10)
        self.material_id = QtWidgets.QLineEdit()
        self.material_id.setPlaceholderText("可选：已采集/素材发布里的素材 ID")
        self.source_url = QtWidgets.QLineEdit()
        self.source_url.setPlaceholderText("可选：小红书笔记链接")
        self.source_title = QtWidgets.QLineEdit()
        self.source_title.setPlaceholderText("可选：原笔记标题")
        self.source_body = QtWidgets.QPlainTextEdit()
        self.source_body.setPlaceholderText("可选：原笔记正文")
        self.source_body.setMaximumHeight(82)
        self.source_tags = QtWidgets.QLineEdit()
        self.source_tags.setPlaceholderText("可选：原标签，用空格或逗号分隔")
        sl.addWidget(QtWidgets.QLabel("来源素材"), 0, 0)
        sl.addWidget(self.material_id, 0, 1)
        sl.addWidget(QtWidgets.QLabel("笔记链接"), 1, 0)
        sl.addWidget(self.source_url, 1, 1)
        sl.addWidget(QtWidgets.QLabel("原始标题"), 2, 0)
        sl.addWidget(self.source_title, 2, 1)
        sl.addWidget(QtWidgets.QLabel("原始正文"), 3, 0)
        sl.addWidget(self.source_body, 3, 1)
        sl.addWidget(QtWidgets.QLabel("原始标签"), 4, 0)
        sl.addWidget(self.source_tags, 4, 1)
        sl.addWidget(QtWidgets.QLabel("原笔记图片"), 5, 0)
        self.source_image_count = QtWidgets.QLabel("0 张")
        self.source_image_count.setObjectName("sub")
        sl.addWidget(self.source_image_count, 5, 1)
        self.source_image_scroll = QtWidgets.QScrollArea()
        self.source_image_scroll.setWidgetResizable(True)
        self.source_image_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.source_image_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.source_image_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.source_image_scroll.setFixedHeight(192)
        self.source_image_host = QtWidgets.QWidget()
        self.source_image_layout = QtWidgets.QHBoxLayout(self.source_image_host)
        self.source_image_layout.setContentsMargins(0, 0, 0, 0)
        self.source_image_layout.setSpacing(10)
        self.source_image_layout.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.source_image_scroll.setWidget(self.source_image_host)
        sl.addWidget(self.source_image_scroll, 6, 0, 1, 2)
        self.v.addWidget(source)

        business = QtWidgets.QFrame()
        business.setObjectName("card")
        bl = QtWidgets.QGridLayout(business)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setHorizontalSpacing(12)
        bl.setVerticalSpacing(10)
        self.biz_name = QtWidgets.QLineEdit()
        self.biz_name.setPlaceholderText("业务/产品名称")
        self.biz_region = QtWidgets.QLineEdit()
        self.biz_region.setPlaceholderText("地区，例如：杭州")
        self.biz_audience = QtWidgets.QLineEdit()
        self.biz_audience.setPlaceholderText("目标客户，例如：新手宝妈 / 本地门店老板")
        self.biz_selling = QtWidgets.QPlainTextEdit()
        self.biz_selling.setPlaceholderText("卖点，一行一个")
        self.biz_selling.setMaximumHeight(88)
        self.asset_paths = QtWidgets.QPlainTextEdit()
        self.asset_paths.setPlaceholderText("替换图片路径，一行一个；缺图槽位会生成 AI 占位状态")
        self.asset_paths.setMaximumHeight(92)
        pick_assets = QtWidgets.QPushButton("选择替换图")
        pick_assets.setObjectName("ghost")
        pick_assets.clicked.connect(self.pick_assets)
        bl.addWidget(QtWidgets.QLabel("业务名称"), 0, 0)
        bl.addWidget(self.biz_name, 0, 1)
        bl.addWidget(QtWidgets.QLabel("地区"), 1, 0)
        bl.addWidget(self.biz_region, 1, 1)
        bl.addWidget(QtWidgets.QLabel("目标客户"), 2, 0)
        bl.addWidget(self.biz_audience, 2, 1)
        bl.addWidget(QtWidgets.QLabel("卖点"), 3, 0)
        bl.addWidget(self.biz_selling, 3, 1)
        bl.addWidget(pick_assets, 4, 0)
        bl.addWidget(self.asset_paths, 4, 1)
        self.v.addWidget(business)

        controls = QtWidgets.QHBoxLayout()
        self.b_template = QtWidgets.QPushButton("读取图文结构")
        self.b_template.setObjectName("ghost")
        self.b_template.clicked.connect(self.load_template)
        self.b_preview = QtWidgets.QPushButton("生成同款预览")
        self.b_preview.setObjectName("primary")
        self.b_preview.clicked.connect(self.generate_preview)
        self.b_confirm_ai = QtWidgets.QPushButton("确认 AI 占位图")
        self.b_confirm_ai.setObjectName("ghost")
        self.b_confirm_ai.clicked.connect(self.confirm_ai_placeholders)
        self.b_save = QtWidgets.QPushButton("保存草稿")
        self.b_save.setObjectName("primary")
        self.b_save.clicked.connect(self.save_draft)
        controls.addWidget(self.b_template)
        controls.addWidget(self.b_preview)
        controls.addWidget(self.b_confirm_ai)
        controls.addWidget(self.b_save)
        controls.addStretch()
        self.v.addLayout(controls)

        self.status = QtWidgets.QLabel("未开始")
        self.status.setObjectName("sub")
        self.status.setWordWrap(True)
        self.v.addWidget(self.status)
        self.template_summary = QtWidgets.QLabel("尚未读取图文结构")
        self.template_summary.setObjectName("sub")
        self.template_summary.setWordWrap(True)
        self.v.addWidget(self.template_summary)

        self.slot_table = QtWidgets.QTableWidget(0, 5)
        self.slot_table.setHorizontalHeaderLabels(["槽位", "角色", "替换来源", "比例", "确认状态"])
        self.slot_table.verticalHeader().setVisible(False)
        self.slot_table.horizontalHeader().setStretchLastSection(True)
        self.slot_table.setMinimumHeight(180)
        self.v.addWidget(self.slot_table)

        self.copy_view = QtWidgets.QPlainTextEdit()
        self.copy_view.setReadOnly(True)
        self.copy_view.setPlaceholderText("生成后显示 3 组标题、正文和标签候选。")
        self.copy_view.setMinimumHeight(180)
        self.v.addWidget(self.copy_view, 1)
        BRIDGE.payload.connect(self._on)

    def _set_source_thumbnail(self, button, pixmap):
        if not button or pixmap is None or pixmap.isNull():
            return False
        width, height = 112, 140
        scaled = pixmap.scaled(width, height, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
        left = max(0, (scaled.width() - width) // 2)
        top = max(0, (scaled.height() - height) // 2)
        button.setIcon(QtGui.QIcon(scaled.copy(left, top, width, height)))
        button.setIconSize(QtCore.QSize(width, height))
        return True

    def _render_source_images(self):
        self._source_image_generation += 1
        self._source_image_entries = _xhs_note_source_image_entries(self._source_material, CENTRAL)
        self._source_image_buttons = {}
        self._source_image_bytes = {}
        _clear_layout(self.source_image_layout)
        self.source_image_count.setText("%d 张" % len(self._source_image_entries))
        for entry in self._source_image_entries:
            index = int(entry.get("index") or 0)
            button = QtWidgets.QToolButton()
            button.setObjectName("sourceThumb")
            button.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
            button.setText("%d · %s" % (index, entry.get("name") or "图片"))
            button.setToolTip("查看原图：%s" % (entry.get("name") or index))
            button.setFixedSize(132, 174)
            local_path = entry.get("path") or ""
            if local_path:
                self._set_source_thumbnail(button, QtGui.QPixmap(local_path))
            button.clicked.connect(lambda _checked=False, source=dict(entry): self._show_source_image(source))
            self.source_image_layout.addWidget(button)
            self._source_image_buttons[index] = button
            if not local_path and entry.get("url"):
                self._load_source_image_async(entry, self._source_image_generation)

    def _load_source_image_async(self, entry, generation):
        entry = dict(entry or {})

        def work():
            try:
                with _XHS_NOTE_SOURCE_IMAGE_FETCH_LIMIT:
                    request_headers = _xhs_note_source_image_headers(entry.get("url") or "", CENTRAL)
                    request_options = {"headers": request_headers, "timeout": 20, "stream": True}
                    if request_headers:
                        request_options["allow_redirects"] = False
                    response = requests.get(entry.get("url") or "", **request_options)
                    try:
                        response.raise_for_status()
                        content = _xhs_note_read_limited_response(response)
                    finally:
                        close_response = getattr(response, "close", None)
                        if callable(close_response):
                            close_response()
                if not content:
                    raise RuntimeError("empty_image_response")
                BRIDGE.payload.emit("xhs_note_source_image", {
                    "generation": generation,
                    "index": entry.get("index"),
                    "name": entry.get("name") or "",
                    "content": content,
                })
            except Exception as exc:
                json_log(
                    _CLIENT_JSON_LOGGER,
                    "xhs_note_source_image_load_failed",
                    exc=exc,
                    materialId=entry.get("materialId") or "",
                    imageIndex=entry.get("index") or 0,
                    fileName=os.path.basename(str(entry.get("name") or "")),
                )
                BRIDGE.payload.emit("xhs_note_source_image", {
                    "generation": generation,
                    "index": entry.get("index"),
                    "name": entry.get("name") or "",
                    "error": "source_image_load_failed",
                })

        run_bg(work)

    def _on_source_image_loaded(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("generation") != self._source_image_generation:
            return
        index = int(payload.get("index") or 0)
        button = self._source_image_buttons.get(index)
        if button is None:
            return
        content = payload.get("content") if isinstance(payload.get("content"), (bytes, bytearray)) else b""
        if not content:
            button.setToolTip("原图加载失败：%s" % (payload.get("name") or index))
            return
        pixmap = QtGui.QPixmap()
        if not pixmap.loadFromData(content):
            button.setToolTip("原图格式不可用：%s" % (payload.get("name") or index))
            return
        self._source_image_bytes[index] = bytes(content)
        self._set_source_thumbnail(button, pixmap)

    def _show_source_image(self, entry):
        entry = entry if isinstance(entry, dict) else {}
        index = int(entry.get("index") or 0)
        pixmap = QtGui.QPixmap(entry.get("path") or "")
        if pixmap.isNull() and self._source_image_bytes.get(index):
            pixmap.loadFromData(self._source_image_bytes.get(index) or b"")
        if pixmap.isNull():
            self.status.setText("原图暂不可查看：%s" % (entry.get("name") or "图片加载失败"))
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("原图 %d · %s" % (index, entry.get("name") or "图片"))
        dialog.setMinimumSize(560, 620)
        dialog.resize(760, 820)
        layout = QtWidgets.QVBoxLayout(dialog)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        image_label = QtWidgets.QLabel()
        image_label.setAlignment(QtCore.Qt.AlignCenter)
        image_label.setStyleSheet("background:transparent;")
        image_label.setPixmap(pixmap.scaled(960, 960, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        scroll.setWidget(image_label)
        layout.addWidget(scroll, 1)
        close_button = QtWidgets.QPushButton("关闭")
        close_button.setObjectName("ghost")
        close_button.clicked.connect(dialog.accept)
        footer = QtWidgets.QHBoxLayout()
        footer.addStretch()
        footer.addWidget(close_button)
        layout.addLayout(footer)
        dialog.exec()

    def _local_api(self, method, path, body=None, timeout=60):
        base = "http://127.0.0.1:" + os.environ.get("API_PORT", "9081")
        headers = dict(_headers())
        token = os.environ.get("MATRIX_AGENT_TOKEN") or ""
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            response = requests.request(method, base + path, headers=headers, json=body, timeout=timeout)
            try:
                return response.status_code, response.json()
            except Exception:
                return response.status_code, {}
        except Exception as exc:
            return 0, {"ok": False, "error": str(exc)}

    def _source_note_payload(self):
        tags = [x.strip() for x in re.split(r"[,，\s]+", self.source_tags.text().strip()) if x.strip()]
        return {
            "url": self.source_url.text().strip(),
            "noteUrl": self.source_url.text().strip(),
            "title": self.source_title.text().strip(),
            "body": self.source_body.toPlainText().strip(),
            "tags": tags,
        }

    def _business_input(self):
        selling = [x.strip() for x in self.biz_selling.toPlainText().splitlines() if x.strip()]
        return {
            "name": self.biz_name.text().strip(),
            "region": self.biz_region.text().strip(),
            "audience": self.biz_audience.text().strip(),
            "sellingPoints": selling,
        }

    def _provided_assets(self):
        assets = []
        role_order = ["cover", "product", "detail", "result", "cta"]
        for idx, line in enumerate(self.asset_paths.toPlainText().splitlines()):
            path = line.strip().strip('"')
            if not path:
                continue
            role = role_order[idx] if idx < len(role_order) else "detail"
            assets.append({"filePath": path, "path": path, "role": role, "slotRole": role})
        return assets

    def pick_assets(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "选择图文同款替换图片", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)")
        if not paths:
            return
        current = self.asset_paths.toPlainText().strip()
        merged = ([current] if current else []) + list(paths)
        self.asset_paths.setPlainText("\n".join(merged))

    def load_template(self):
        payload = {"sourceNote": self._source_note_payload()}
        mid = self.material_id.text().strip()
        if mid:
            payload["materialId"] = mid
        if self._source_material:
            payload["material"] = self._source_material
        if not mid and not self._source_material and not payload["sourceNote"].get("url"):
            self.status.setText("未找到图片素材，请先下载笔记")
            return
        self._request_generation += 1
        generation = self._request_generation
        self._template_req_id += 1
        req_id = self._template_req_id
        self._template_loading = True
        self.b_template.setEnabled(False)
        self.status.setText("正在读取图文结构…")
        QtCore.QTimer.singleShot(30000, lambda req=req_id: self._on_template_timeout(req))

        def work():
            if generation != self._request_generation:
                return
            code, data = self._local_api("POST", "/api/xhs-note-replacement/template", payload, 30)
            BRIDGE.payload.emit("xhs_note_replace", {
                "action": "template", "generation": generation, "reqId": req_id, "code": code, "data": data,
            })
        run_bg(work)

    def _on_template_timeout(self, req_id):
        if self._template_loading and req_id == self._template_req_id:
            self._template_loading = False
            self.b_template.setEnabled(True)
            self.status.setText("读取图文结构超时：请确认本机执行引擎在线，或先在内容采集页下载笔记后重试。")

    def _xhs_note_error_text(self, error):
        error = str(error or "").strip()
        if error in ("not_found", "material_not_found", "no_files", "xhs_no_note_media"):
            return "未找到图片素材，请先下载笔记"
        if error == "feature_disabled":
            return "图文同款功能未启用，请检查 XHS_NOTE_REPLACEMENT_ENABLED 配置"
        if "timed out" in error.lower() or "timeout" in error.lower():
            return "读取图文结构超时：请确认本机执行引擎在线，或先在内容采集页下载笔记后重试。"
        return error or "未知错误"

    def _start_from_collection(self, data):
        data = data or {}
        self._request_generation += 1
        self._template_req_id += 1
        self._template_loading = False
        self._source_image_generation += 1
        self.b_template.setEnabled(True)
        self._job = {}
        self._preview = {}
        self.material_id.clear()
        self.source_url.clear()
        self.source_title.clear()
        self.source_body.clear()
        self.source_tags.clear()
        self.biz_name.clear()
        self.biz_region.clear()
        self.biz_audience.clear()
        self.biz_selling.clear()
        self.asset_paths.clear()
        self.template_summary.setText("尚未读取图文结构")
        self.slot_table.setRowCount(0)
        self.copy_view.clear()
        material = data.get("material") if isinstance(data.get("material"), dict) else {}
        self._source_material = dict(material or {})
        material_id = self._source_material.get("id") or data.get("materialId") or ""
        source_url = data.get("sourceUrl") or self._source_material.get("sourceUrl") or ""
        self.material_id.setText(str(material_id))
        self.source_url.setText(str(source_url))
        self.source_title.setText(str(self._source_material.get("title") or ""))
        self.source_body.setPlainText(str(self._source_material.get("body") or ""))
        tags = self._source_material.get("tags") or []
        self.source_tags.setText(" ".join(str(x) for x in tags) if isinstance(tags, list) else str(tags or ""))
        self._render_source_images()
        self.status.setText("已带入采集结果，正在读取图文结构…")
        self.load_template()

    def generate_preview(self):
        job_id = self._job.get("id") or ""
        if not job_id:
            self.load_template()
            self.status.setText("已开始读取结构，完成后请再次点击生成预览。")
            return
        generation = self._request_generation
        payload = {
            "jobId": job_id,
            "businessInput": self._business_input(),
            "providedAssets": self._provided_assets(),
        }
        self.status.setText("正在生成同款预览…")

        def work():
            if generation != self._request_generation:
                return
            code, data = self._local_api("POST", "/api/xhs-note-replacement/preview", payload, 90)
            BRIDGE.payload.emit("xhs_note_replace", {
                "action": "preview", "generation": generation, "jobId": job_id, "code": code, "data": data,
            })
        run_bg(work)

    def confirm_ai_placeholders(self):
        job_id = self._job.get("id") or ""
        if not job_id:
            QtWidgets.QMessageBox.information(self, "图文同款", "请先生成预览。")
            return
        pending = [m for m in (self._job.get("slotMappings") or [])
                   if m.get("source") == "ai_placeholder" and m.get("confirmationStatus") != "confirmed"]
        if not pending:
            self.status.setText("没有待确认的 AI 占位图。")
            return
        generation = self._request_generation
        self.status.setText("正在确认 AI 占位图…")

        def work():
            last = {}
            code = 200
            for mapping in pending:
                if generation != self._request_generation:
                    return
                code, last = self._local_api("POST", "/api/xhs-note-replacement/confirm-ai-image", {
                    "jobId": job_id,
                    "slotIndex": mapping.get("slotIndex"),
                }, 60)
                if not (isinstance(last, dict) and last.get("ok")):
                    break
            BRIDGE.payload.emit("xhs_note_replace", {
                "action": "confirm_ai", "generation": generation, "jobId": job_id, "code": code, "data": last,
            })
        run_bg(work)

    def save_draft(self):
        job_id = self._job.get("id") or ""
        if not job_id:
            QtWidgets.QMessageBox.information(self, "图文同款", "请先生成预览。")
            return
        generation = self._request_generation
        self.status.setText("正在保存草稿…")

        def work():
            if generation != self._request_generation:
                return
            code, data = self._local_api("POST", "/api/xhs-note-replacement/save-draft", {
                "jobId": job_id,
                "selectedCopyIndex": 0,
            }, 120)
            BRIDGE.payload.emit("xhs_note_replace", {
                "action": "save", "generation": generation, "jobId": job_id, "code": code, "data": data,
            })
        run_bg(work)

    def _on(self, tag, data):
        if tag == "xhs_note_source_image":
            self._on_source_image_loaded(data or {})
            return
        if tag == "xhs_note_replace_start":
            self._start_from_collection(data or {})
            return
        if tag != "xhs_note_replace":
            return
        payload = data or {}
        if payload.get("generation") != self._request_generation:
            return
        if payload.get("action") == "template" and payload.get("reqId") != self._template_req_id:
            return
        body = payload.get("data") or {}
        if payload.get("action") == "template":
            self._template_loading = False
            self.b_template.setEnabled(True)
        if not (isinstance(body, dict) and body.get("ok")):
            self.status.setText("图文同款处理失败：%s" % self._xhs_note_error_text((body or {}).get("error") or ("http_%s" % payload.get("code"))))
            return
        self._job = body.get("job") or self._job or {}
        self._preview = body.get("preview") or self._preview or {}
        action = payload.get("action") or ""
        if action == "template" and not (((self._job or {}).get("template") or {}).get("imageSlots") or []):
            self.status.setText("未找到图片素材，请先下载笔记")
            self._render_job()
            return
        if action == "save":
            mid = body.get("id") or (body.get("material") or {}).get("id") or ""
            self.status.setText("草稿已保存：%s。可到『素材发布』查看；资产库同步使用草稿元数据。" % (mid or "已生成"))
        elif action == "confirm_ai":
            self.status.setText("AI 占位图已确认。")
        elif action == "preview":
            self.status.setText("同款预览已生成。")
        else:
            self.status.setText("图文结构已读取。")
        self._render_job()

    def _render_job(self):
        template = (self._job or {}).get("template") or {}
        slots = template.get("imageSlots") or []
        self.template_summary.setText(
            "模板：%s · 来源笔记：%s · 图片槽位：%d" % (
                template.get("id") or "-", template.get("sourceNoteId") or "-", len(slots)))
        rows = _xhs_note_slot_rows(self._job, self._preview)
        self.slot_table.setRowCount(len(rows))
        for row, mapping in enumerate(rows):
            values = [
                str(mapping.get("slotIndex") or row + 1),
                str(mapping.get("slotRole") or ""),
                str(mapping.get("sourceLabel") or ""),
                str(mapping.get("ratio") or ""),
                str(mapping.get("confirmationStatus") or ""),
            ]
            for col, value in enumerate(values):
                self.slot_table.setItem(row, col, QtWidgets.QTableWidgetItem(value))
        copies = (self._job or {}).get("copyCandidates") or (self._preview or {}).get("copyCandidates") or []
        lines = []
        for idx, item in enumerate(copies, start=1):
            tags = " ".join(item.get("tags") or [])
            lines.append("方案 %d\n标题：%s\n正文：%s\n标签：%s" % (
                idx, item.get("title") or "", item.get("body") or "", tags))
        self.copy_view.setPlainText("\n\n".join(lines))

class VideoReplacementPage(BasePage):
    """视频分解后的同款替换生成：产品图 + 授权/虚拟模特 → 分段生成 → 合成入资产库。"""
    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("同款替换", "先提取原片人物/产品/场景槽位，再按上传素材替换生成新视频"))
        self.v.addWidget(prereq_banner("真人脸图必须确认授权；不支持未授权真人、公众人物或明星脸。生成会先提取原片人物/产品/场景槽位：上传人物/产品/场景则强制替换，未上传则保留原片对应槽位。"))
        self._source = {}
        self._product_paths = []
        self._product_urls = []
        self._face_paths = []
        self._face_urls = []
        self._face_url = ""
        self._virtual_url = ""
        self._scene_path = ""
        self._scene_url = ""
        self._replacement_audio_path = ""
        self._replacement_audio_url = ""
        self._target_candidates = []
        self._principal_actor = {}
        self._job = {}
        self._busy = False
        self._cancel_requested = False

        src_row = QtWidgets.QHBoxLayout()
        self.source_lab = QtWidgets.QLabel("等待从『分解视频』进入。")
        self.source_lab.setObjectName("sub")
        self.source_lab.setWordWrap(True)
        src_row.addWidget(self.source_lab, 1)
        self.b_open_output = QtWidgets.QPushButton("打开成片")
        self.b_open_output.setObjectName("ghost")
        self.b_open_output.clicked.connect(self.open_output)
        self.b_open_output.setEnabled(False)
        src_row.addWidget(self.b_open_output)
        self.v.addLayout(src_row)

        refs = QtWidgets.QFrame()
        refs.setObjectName("card")
        refs_l = QtWidgets.QGridLayout(refs)
        refs_l.setContentsMargins(16, 14, 16, 14)
        refs_l.setHorizontalSpacing(12)
        refs_l.setVerticalSpacing(10)
        self.b_products = QtWidgets.QPushButton("上传产品图")
        self.b_products.setObjectName("ghost")
        self.b_products.clicked.connect(self.pick_products)
        self.product_lab = QtWidgets.QLabel("未选择产品图（可选；上传后强制替换原片产品，未上传则保留原产品）")
        self.product_lab.setObjectName("sub")
        self.product_lab.setWordWrap(True)
        self.b_face = QtWidgets.QPushButton("上传主角人物参考图")
        self.b_face.setObjectName("ghost")
        self.b_face.clicked.connect(self.pick_face)
        self.face_authorized = QtWidgets.QCheckBox("我确认已获得该人物素材授权")
        self.face_authorized.setObjectName("sub")
        self.person_full_body = QtWidgets.QCheckBox("至少一张人物参考图为清晰全身图（已确认）")
        self.person_full_body.setObjectName("sub")
        self.principal_actor_lab = QtWidgets.QLabel("原片主角：尚未提取")
        self.principal_actor_lab.setObjectName("sub")
        self.principal_actor_lab.setWordWrap(True)
        self.principal_actor_preview = QtWidgets.QLabel("暂无预览")
        self.principal_actor_preview.setObjectName("principalPreview")
        self.principal_actor_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.principal_actor_preview.setFixedSize(144, 180)
        self.principal_actor_preview.setStyleSheet(
            "QLabel#principalPreview{background:rgba(15,23,42,0.72);"
            "border:1px solid rgba(148,163,184,0.35);border-radius:6px;color:#94a3b8;}"
        )
        self.b_scene = QtWidgets.QPushButton("上传场景图")
        self.b_scene.setObjectName("ghost")
        self.b_scene.clicked.connect(self.pick_scene)
        self.scene_prompt = QtWidgets.QLineEdit()
        self.scene_prompt.setPlaceholderText("可选场景描述；上传场景图后强制替换原片场景，未上传则保留原场景")
        self.target_person = QtWidgets.QComboBox()
        self.target_person.setToolTip("选择原视频中需要被替换的人物")
        self.target_person.addItem("生成方案后选择原片人物")
        self.no_person_mode = QtWidgets.QCheckBox("纯产品视频（无人物）")
        self.no_person_mode.setObjectName("sub")
        self.no_person_mode.setToolTip("参考视频没有人物时开启：不上传人脸、不换脸，只替换产品和场景")
        self.no_person_mode.toggled.connect(self._sync_person_controls)
        self.audio_mode = QtWidgets.QComboBox()
        self.audio_mode.setToolTip("选择替换后视频的声音来源：默认保留原片声音；AI 音色会按每段口播稿重新配音；上传完整配音会在最终成片时替换整条音轨。")
        self.audio_mode.addItem("原片声音", "source")
        self.audio_mode.addItem("AI 音色配音", "tts")
        self.audio_mode.addItem("上传完整配音", "uploaded")
        self.audio_mode.currentIndexChanged.connect(self._sync_audio_controls)
        self.replacement_voice = QtWidgets.QComboBox()
        for label, voice_id in DH_VOICES:
            self.replacement_voice.addItem(label, voice_id)
        self.replacement_voice.setToolTip("选择 AI 音色配音时使用；上传完整配音时不使用。")
        self.b_replacement_audio = QtWidgets.QPushButton("上传配音音频")
        self.b_replacement_audio.setObjectName("ghost")
        self.b_replacement_audio.clicked.connect(self.pick_replacement_audio)
        self.audio_lab = QtWidgets.QLabel("声音：默认保留原片声音")
        self.audio_lab.setObjectName("sub")
        self.audio_lab.setWordWrap(True)
        self.replacement_model = QtWidgets.QComboBox()
        self.replacement_model.setToolTip("选择整个同款替换任务使用的 LK888 视频模型；SD 2.0 全能参考会在模型目录可用时作为备选出现。")
        self.replacement_model.currentIndexChanged.connect(self._on_replacement_model_changed)
        self.b_virtual = QtWidgets.QPushButton("生成虚拟模特")
        self.b_virtual.setObjectName("ghost")
        self.b_virtual.clicked.connect(self.generate_virtual_model)
        self.model_lab = QtWidgets.QLabel("未选择人物；支持 1-3 张人物参考图，至少一张清晰全身图。")
        self.model_lab.setObjectName("sub")
        self.model_lab.setWordWrap(True)
        refs_l.addWidget(self.b_products, 0, 0)
        refs_l.addWidget(self.product_lab, 0, 1)
        refs_l.addWidget(self.b_face, 1, 0)
        refs_l.addWidget(self.face_authorized, 1, 1)
        refs_l.addWidget(self.person_full_body, 2, 1)
        refs_l.addWidget(self.principal_actor_preview, 3, 0)
        refs_l.addWidget(self.principal_actor_lab, 3, 1)
        refs_l.addWidget(self.b_scene, 4, 0)
        refs_l.addWidget(self.scene_prompt, 4, 1)
        refs_l.addWidget(QtWidgets.QLabel("原片主角确认"), 5, 0)
        refs_l.addWidget(self.target_person, 5, 1)
        refs_l.addWidget(self.no_person_mode, 6, 1)
        refs_l.addWidget(QtWidgets.QLabel("同款替换模型"), 7, 0)
        refs_l.addWidget(self.replacement_model, 7, 1)
        refs_l.addWidget(QtWidgets.QLabel("声音来源"), 8, 0)
        refs_l.addWidget(self.audio_mode, 8, 1)
        refs_l.addWidget(QtWidgets.QLabel("AI 音色"), 9, 0)
        refs_l.addWidget(self.replacement_voice, 9, 1)
        refs_l.addWidget(self.b_replacement_audio, 10, 0)
        refs_l.addWidget(self.audio_lab, 10, 1)
        refs_l.addWidget(self.b_virtual, 11, 0)
        refs_l.addWidget(self.model_lab, 11, 1)
        self.v.addWidget(refs)

        ctl = QtWidgets.QHBoxLayout()
        self.b_plan = QtWidgets.QPushButton("生成替换方案")
        self.b_plan.setObjectName("ghost")
        self.b_plan.clicked.connect(self.generate_plan)
        self.b_start = QtWidgets.QPushButton("执行替换生成")
        self.b_start.setObjectName("primary")
        self.b_start.clicked.connect(self.start_generation)
        self.b_start.setEnabled(False)
        self.b_review = QtWidgets.QPushButton("确认片段并合成")
        self.b_review.setObjectName("primary")
        self.b_review.clicked.connect(self.confirm_and_concat)
        self.b_review.setEnabled(False)
        self.b_retry_failed = QtWidgets.QPushButton("重试失败片段")
        self.b_retry_failed.setObjectName("ghost")
        self.b_retry_failed.clicked.connect(self.retry_failed_segments)
        self.b_retry_failed.setEnabled(False)
        self.b_regen_segment = QtWidgets.QPushButton("重生选中片段")
        self.b_regen_segment.setObjectName("ghost")
        self.b_regen_segment.clicked.connect(self.regenerate_selected_segment)
        self.b_regen_segment.setEnabled(False)
        self.b_cancel = QtWidgets.QPushButton("取消任务")
        self.b_cancel.setObjectName("ghost")
        self.b_cancel.clicked.connect(self.cancel_generation)
        self.b_cancel.setEnabled(False)
        self.b_pending = QtWidgets.QPushButton("加入待发布队列")
        self.b_pending.setObjectName("ghost")
        self.b_pending.clicked.connect(self.add_output_to_pending)
        self.b_pending.setEnabled(False)
        ctl.addWidget(self.b_plan)
        ctl.addWidget(self.b_start)
        ctl.addWidget(self.b_review)
        ctl.addWidget(self.b_retry_failed)
        ctl.addWidget(self.b_regen_segment)
        ctl.addWidget(self.b_cancel)
        ctl.addWidget(self.b_pending)
        ctl.addStretch()
        self.v.addLayout(ctl)

        self.status = QtWidgets.QLabel("未开始")
        self.status.setObjectName("sub")
        self.v.addWidget(self.status)
        self.progress_detail = QtWidgets.QLabel("用时: - · 预计剩余: -")
        self.progress_detail.setObjectName("sub")
        self.v.addWidget(self.progress_detail)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("准备中…")
        self.progress.setVisible(False)
        self.v.addWidget(self.progress)
        self.table = QtWidgets.QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["片段", "时间", "口播稿", "状态", "审核帧", "视频文件", "耗时/预计", "错误", "操作"])
        self.table.setWordWrap(True)
        self.table.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.table.verticalScrollBar().setSingleStep(24)
        self.table.verticalScrollBar().setPageStep(122)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(8, QtWidgets.QHeaderView.Fixed)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(122)
        self.table.setColumnWidth(0, 54)
        self.table.setColumnWidth(1, 86)
        self.table.setColumnWidth(2, 520)
        self.table.setColumnWidth(3, 260)
        self.table.setColumnWidth(4, 104)
        self.table.setColumnWidth(5, 104)
        self.table.setColumnWidth(6, 96)
        self.table.setColumnWidth(7, 150)
        self.table.setColumnWidth(8, 120)
        self.table.setMinimumHeight(420)
        self.v.addWidget(self.table)
        self.prompt_view = QtWidgets.QPlainTextEdit()
        self.prompt_view.setReadOnly(True)
        self.prompt_view.setPlaceholderText("生成时会显示当前片段提示词。")
        self.v.addWidget(self.prompt_view, 1)
        BRIDGE.payload.connect(self._on)
        self._sync_replacement_model_ui()
        self._refresh_replacement_models()
        self._sync_person_controls(False)
        self._sync_audio_controls()

    def _sync_person_controls(self, checked):
        enabled = not bool(checked)
        self.b_face.setEnabled(enabled)
        self.face_authorized.setEnabled(enabled)
        self.person_full_body.setEnabled(enabled)
        self.target_person.setEnabled(enabled)
        self.b_virtual.setEnabled(enabled)
        if checked:
            self.model_lab.setText("纯产品视频模式：无需上传人脸，不执行换脸。")
        elif not (self._face_paths or self._virtual_url):
            self.model_lab.setText("未选择人物；支持 1-3 张人物参考图，至少一张清晰全身图。")

    def _selected_audio_mode(self):
        widget = getattr(self, "audio_mode", None)
        if widget is None:
            return "source"
        return str(widget.currentData() or "source")

    def _selected_voice_id(self):
        widget = getattr(self, "replacement_voice", None)
        if widget is not None and widget.currentData():
            return str(widget.currentData())
        return (self._job or {}).get("voiceId") or "Zephyr"

    def _sync_audio_controls(self, *_args):
        mode = self._selected_audio_mode()
        is_tts = mode == "tts"
        is_uploaded = mode == "uploaded"
        if hasattr(self, "replacement_voice"):
            self.replacement_voice.setEnabled(is_tts)
        if hasattr(self, "b_replacement_audio"):
            self.b_replacement_audio.setEnabled(is_uploaded)
        if not hasattr(self, "audio_lab"):
            return
        if is_tts:
            self.audio_lab.setText("声音：按每段口播稿使用所选 AI 音色重新配音")
        elif is_uploaded:
            audio_path = getattr(self, "_replacement_audio_path", "")
            if audio_path:
                self.audio_lab.setText("声音：已选择完整配音 " + os.path.basename(audio_path))
            else:
                self.audio_lab.setText("声音：请上传一条完整配音音频，最终成片会替换整条音轨")
        else:
            self.audio_lab.setText("声音：默认保留原片声音")

    def _selected_replacement_model(self):
        widget = getattr(self, "replacement_model", None)
        if widget is not None and getattr(widget, "currentData", None):
            try:
                current = widget.currentData()
            except Exception:
                current = None
            if current:
                return str(current).strip()
        job_model = str((self._job or {}).get("model") or "").strip()
        if job_model:
            return job_model
        no_person = _replacement_no_person_mode(self._job)
        widget = getattr(self, "no_person_mode", None)
        if widget is not None and getattr(widget, "isChecked", None):
            try:
                no_person = bool(widget.isChecked())
            except Exception:
                pass
        if not no_person and _env_enabled("VIDEO_REPLACE_PRINCIPAL_REPLACEMENT", "1"):
            return _principal_replacement_model(self._job)
        return _LK888_REPLACEMENT_VIDEO_DEFAULT

    def _sync_replacement_model_ui(self, rows=None):
        if rows is None:
            default_rows = [
                {"name": name, "display_name": _LK888_REPLACEMENT_MODEL_LABELS.get(name, name), "type": "video"}
                for name in (
                    (_LK888_PRINCIPAL_VIDEO_MODEL,)
                    + _LK888_REPLACEMENT_BUILTIN_SELECTABLE_MODELS
                    + _LK888_REPLACEMENT_MODEL_FALLBACKS
                )
            ]
            rows = _replacement_supported_model_rows(default_rows)
        else:
            rows = list(rows)
        current = self._selected_replacement_model()
        widget = getattr(self, "replacement_model", None)
        if widget is not None:
            try:
                widget.blockSignals(True)
            except Exception:
                pass
            try:
                widget.clear()
                for row in rows:
                    name = _replacement_row_name(row)
                    if name:
                        widget.addItem(_replacement_row_label(row), name)
                if current and current not in {_replacement_row_name(row) for row in rows}:
                    widget.addItem(current, current)
                if hasattr(widget, "setCurrentIndex"):
                    selected = 0
                    for i, row in enumerate(rows):
                        if _replacement_row_name(row) == current:
                            selected = i
                            break
                    if current and current not in {_replacement_row_name(row) for row in rows}:
                        selected = len(rows)
                    widget.setCurrentIndex(selected)
            finally:
                try:
                    widget.blockSignals(False)
                except Exception:
                    pass
        if rows:
            names = {_replacement_row_name(row) for row in rows}
            if current not in names:
                names.add(current)
        if current:
            self._job["model"] = current
        return rows, current

    def _on_replacement_model_changed(self, *_args):
        self._job["model"] = self._selected_replacement_model()

    def _refresh_replacement_models(self):
        def work():
            try:
                rows = _replacement_supported_model_rows()
                BRIDGE.payload.emit("video_replace_models", {"rows": rows})
            except Exception as exc:
                log("video replacement models: %s" % exc)
        run_bg(work)

    def _set_principal_actor_preview(self, path):
        preview = getattr(self, "principal_actor_preview", None)
        if preview is None:
            return False
        path = str(path or "").strip()
        try:
            if not path or not os.path.isfile(path):
                preview.clear()
                preview.setText("暂无预览")
                preview.setToolTip("")
                return False
            pixmap = QtGui.QPixmap(path)
            if pixmap.isNull():
                preview.clear()
                preview.setText("预览不可用")
                preview.setToolTip(path)
                return False
            preview.setText("")
            preview.setPixmap(pixmap.scaled(
                preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            preview.setToolTip(path)
            return True
        except Exception as exc:
            log("principal actor preview: %s" % exc)
            try:
                preview.clear()
                preview.setText("预览不可用")
                preview.setToolTip(path)
            except Exception:
                pass
            return False

    def _on(self, tag, d):
        d = d or {}
        if tag == "video_replace_audio_asset":
            if hasattr(self, "b_replacement_audio"):
                self.b_replacement_audio.setEnabled(self._selected_audio_mode() == "uploaded")
            if d.get("ok"):
                self._replacement_audio_path = d.get("path") or self._replacement_audio_path
                self._replacement_audio_url = d.get("url") or ""
                self.status.setText("完整配音音频已上传，最终成片会替换整条音轨。")
            else:
                self._replacement_audio_url = ""
                self.status.setText("完整配音上传失败：" + str(d.get("error") or "")[:120])
            self._sync_audio_controls()
            return
        if tag == "video_replace_models":
            self._sync_replacement_model_ui(d.get("rows") or d.get("models") or [])
            return
        if tag == "video_replace_start":
            self.load_source(d)
        elif tag == "video_replace_plan_ready" and d.get("jobId") == self._job.get("id"):
            self._busy = False
            self._job.update(d.get("job") or {})
            self._sync_replacement_model_ui()
            self._target_candidates = list(d.get("targetCandidates") or [])
            self._principal_actor = dict((self._job.get("principalActor") or {}))
            self.target_person.clear()
            actor = self._principal_actor
            actor_status = str(actor.get("status") or "failed")
            if actor_status == "manual_required":
                self.target_person.addItem("请选择并确认原片主角", None)
            for idx, path in enumerate(self._target_candidates):
                self.target_person.addItem("候选人物 %d · %s" % (idx + 1, os.path.basename(path)), path)
            preview = str(actor.get("previewPath") or "").strip()
            self._set_principal_actor_preview(preview)
            self.principal_actor_lab.setText(
                "原片主角：%s%s" % (
                    "已识别" if actor_status == "detected" else (
                        "需要人工确认" if actor_status == "manual_required" else "识别失败"),
                    (" · 预览 " + preview) if preview else "",
                )
            )
            self.status.setText("替换方案已生成，请检查原片主角和片段，再执行生成。")
            self.refresh_segments()
            self.b_start.setEnabled(True)
            self._set_generation_feedback(False)
        elif tag == "video_replace_virtual":
            self._busy = False
            if d.get("ok"):
                self._virtual_url = d.get("url") or ""
                self._face_paths = []
                self._face_urls = []
                self._face_url = ""
                self.model_lab.setText("已生成虚拟模特形象")
                self.status.setText("虚拟模特已就绪")
            else:
                self.status.setText("虚拟模特生成失败：" + _localize_replacement_display_text(d.get("error") or "")[:120])
        elif tag == "video_replace_progress" and d.get("jobId") == self._job.get("id"):
            timing = d.get("timing") or {}
            msg = _replacement_progress_text(d.get("message") or "处理中…", timing)
            self.status.setText(msg)
            self.progress_detail.setText(_replacement_progress_detail_text(timing))
            self._set_generation_feedback(True, msg)
            if d.get("segments") is not None:
                self._job["segments"] = d.get("segments") or []
                self.refresh_segments()
            if d.get("prompt"):
                self.prompt_view.setPlainText(d.get("prompt"))
            if d.get("stage") == "awaiting_review":
                self._busy = False
                self.b_review.setEnabled(True)
                self._set_generation_feedback(False)
                self.progress_detail.setText(_replacement_progress_detail_text(timing))
        elif tag == "video_replace_done" and d.get("jobId") == self._job.get("id"):
            self._busy = False
            self._job.update(d.get("job") or {})
            final_timing = (
                _replacement_timing_snapshot(self._job, None, stage=self._job.get("status") or "done")
                if self._job.get("startedAt") else {}
            )
            message = _localize_replacement_display_text(d.get("message") or "已完成")
            self.status.setText(message)
            self.refresh_segments()
            ok = bool(self._job.get("outputPath"))
            self.b_open_output.setEnabled(ok)
            self.b_pending.setEnabled(ok)
            self.b_retry_failed.setEnabled(any(s.get("status") == "failed" for s in self._job.get("segments") or []))
            self.b_regen_segment.setEnabled(bool(self._job.get("segments")))
            self.b_review.setEnabled(self._job.get("status") == "awaiting_review")
            self._set_generation_feedback(False)
            if final_timing:
                self.progress_detail.setText(_replacement_progress_detail_text(dict(final_timing, etaSec=0)))
            self._show_generation_result(message, ok)

    def load_source(self, data):
        self._source = dict(data or {})
        analysis = self._source.get("breakdownAnalysis") or {}
        meta = analysis.get("meta") or {}
        self.source_lab.setText("%s\n%s\n时长: %s 秒" % (
            self._source.get("sourceUrl") or "本地视频",
            self._source.get("sourceVideoPath") or "",
            meta.get("duration") or "-",
        ))
        self.status.setText("已载入分解结果，请选择主角人物；产品图/场景图可选，上传后会强制替换对应槽位。")
        self.prompt_view.setPlainText("")
        self._job = {}
        self._target_candidates = []
        self._principal_actor = {}
        self._replacement_audio_path = ""
        self._replacement_audio_url = ""
        self._sync_replacement_model_ui()
        self.target_person.clear()
        self.target_person.addItem("生成方案后选择原片人物")
        self.no_person_mode.setChecked(False)
        self.person_full_body.setChecked(False)
        self.principal_actor_lab.setText("原片主角：尚未提取")
        self._set_principal_actor_preview("")
        self.table.setRowCount(0)
        self.b_open_output.setEnabled(False)
        self.b_pending.setEnabled(False)
        self.b_retry_failed.setEnabled(False)
        self.b_start.setEnabled(False)
        self.b_review.setEnabled(False)
        self._set_generation_feedback(False)
        self._sync_audio_controls()

    def pick_products(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "选择产品图", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if paths:
            self._product_paths = list(paths[:3])
            self._product_urls = []
            self.product_lab.setText("已选择: " + "、".join(os.path.basename(p) for p in self._product_paths))

    def pick_face(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "选择主角人物参考图（1-3张，至少一张全身图）", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if paths:
            if len(paths) > 3:
                self._warn_generation_blocked("主角人物参考图最多选择 3 张。")
                return
            try:
                self._face_paths = _validate_person_reference_paths(paths)
            except Exception as exc:
                self._warn_generation_blocked(str(exc))
                return
            self._face_urls = []
            self._face_url = ""
            self._virtual_url = ""
            self.person_full_body.setChecked(False)
            self.model_lab.setText("已选择 %d 张主角人物参考图：%s" % (
                len(self._face_paths), "、".join(os.path.basename(p) for p in self._face_paths)))

    def pick_scene(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择替换场景图", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._scene_path = path
            self._scene_url = ""
            self.b_scene.setText("场景: " + os.path.basename(path))

    def pick_replacement_audio(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择完整配音音频", "", "音频 (*.mp3 *.wav *.m4a *.ogg);;所有文件 (*.*)")
        if not path:
            return
        self._replacement_audio_path = path
        self._replacement_audio_url = ""
        self._sync_audio_controls()
        self.status.setText("正在上传完整配音音频…")
        self.b_replacement_audio.setEnabled(False)

        def work():
            try:
                url, resp = upload_asset_url(path, "同款替换完整配音-" + os.path.basename(path), "audio")
                BRIDGE.payload.emit("video_replace_audio_asset", {
                    "ok": True, "path": path, "url": url, "resp": resp,
                })
            except Exception as exc:
                BRIDGE.payload.emit("video_replace_audio_asset", {
                    "ok": False, "path": path, "error": str(exc)[:160],
                })
        run_bg(work)

    def generate_plan(self):
        if self._busy:
            return
        source_path = self._source.get("sourceVideoPath") or ""
        if not (source_path and os.path.isfile(source_path)):
            self._warn_generation_blocked("请先从『分解视频』载入可用的本地视频。")
            return
        self._busy = True
        self._cancel_requested = False
        job_id = uuid.uuid4().hex
        out_dir = os.path.join(data_dir(), "video_replacements", job_id)
        os.makedirs(out_dir, exist_ok=True)
        selected_model = self._selected_replacement_model()
        self._job = {"id": job_id, "outDir": out_dir, "segments": [], "status": "planning", "model": selected_model}
        self._set_generation_feedback(True, "提取原片人物/产品/场景槽位并生成替换方案…")

        def work():
            try:
                analysis = self._source.get("breakdownAnalysis") or {}
                duration = float((analysis.get("meta") or {}).get("duration") or 0)
                if duration <= 0:
                    duration = float(_probe_video(source_path).get("duration") or 0)
                strict_script_audio = False
                segments = _build_hybrid_replacement_plan(
                    analysis, duration, segment_seconds=8, strict_script_audio=strict_script_audio)
                product_notes = "uploaded product reference images: " + ", ".join(
                    os.path.basename(p) for p in self._product_paths)
                model_notes = "authorized model face" if self._face_paths else "virtual model identity"
                source_entities = _replacement_source_entities_from_analysis(analysis)
                for segment in segments:
                    segment["prompt"] = _build_replacement_prompt(segment, analysis, product_notes, model_notes)
                principal_actor = _extract_replacement_principal_actor(source_path, analysis, out_dir)
                candidate_paths = [
                    str(path or "").strip()
                    for path in (principal_actor.get("candidatePaths") or []) if path
                ]
                candidates = []
                if principal_actor.get("previewPath"):
                    candidates.append(principal_actor["previewPath"])
                if principal_actor.get("status") == "manual_required":
                    candidates.extend(candidate_paths)
                candidates = list(dict.fromkeys(candidates))
                principal_mode = (
                    "source_video_edit"
                    if _env_enabled("VIDEO_REPLACE_PRINCIPAL_REPLACEMENT", "1")
                    else ""
                )
                job = {
                    "id": job_id,
                    "pipeline": os.getenv("VIDEO_REPLACE_PIPELINE", "hybrid_v2") or "hybrid_v2",
                    "sourceVideoPath": source_path,
                    "sourceUrl": self._source.get("sourceUrl") or "",
                    "platform": self._source.get("platform") or "",
                    "breakdownAnalysis": analysis,
                    "productNotes": product_notes,
                    "modelNotes": model_notes,
                    "sourceReplacementEntities": source_entities,
                    "principalActor": principal_actor,
                    "personReferencePaths": list(self._face_paths[:3]),
                    "personReferenceUrls": [],
                    "principalReplacementMode": principal_mode,
                    "noPersonMode": bool(self.no_person_mode.isChecked()),
                    "segments": segments,
                    "outDir": out_dir,
                    "aspectRatio": "9:16",
                    "resolution": "720p",
                    "audioMode": self._selected_audio_mode(),
                    "voiceId": self._selected_voice_id(),
                    "replacementAudioPath": getattr(self, "_replacement_audio_path", ""),
                    "replacementAudioUrl": getattr(self, "_replacement_audio_url", ""),
                    "model": selected_model,
                    "digitalHumanMode": "std",
                    "strictScriptAudio": strict_script_audio,
                    "status": "planned",
                    "outputPath": "",
                    "assetId": "",
                    "createdAt": time.time(),
                }
                _save_replacement_job(job)
                BRIDGE.payload.emit("video_replace_plan_ready", {
                    "jobId": job_id, "job": job, "targetCandidates": candidates,
                })
            except Exception as exc:
                error_id = _replacement_error_id("video_replace_plan_failed", exc, source_video=source_path)
                BRIDGE.payload.emit("video_replace_done", {
                    "jobId": job_id,
                    "message": "替换方案生成失败（错误编号 %s）:%s" % (error_id or "-", str(exc)[:120]),
                    "job": dict(self._job, status="failed"),
                })
        run_bg(work)

    def generate_virtual_model(self):
        if self._busy:
            return
        self._busy = True
        self.status.setText("正在生成虚拟模特形象…")

        def work():
            try:
                prompt = "original virtual e-commerce presenter, friendly young adult, clean studio portrait, no real person likeness"
                url = lk888_image_url(prompt, size="1024x1024")
                BRIDGE.payload.emit("video_replace_virtual", {"ok": True, "url": url})
            except Exception as exc:
                BRIDGE.payload.emit("video_replace_virtual", {"ok": False, "error": str(exc)[:160]})
        run_bg(work)

    def _upload_refs(self, emit=None):
        norm_root = (self._job or {}).get("outDir") or data_dir()
        product_urls, preprocess_reports = _process_replacement_product_refs(
            self._product_paths[:3], norm_root, emit=emit)
        if preprocess_reports:
            self._job["productPreprocess"] = preprocess_reports
        face_urls = []
        sensitive_ids = []
        if not self.no_person_mode.isChecked():
            for idx, path in enumerate(self._face_paths):
                url, response = upload_asset_url(path, "同款替换主角人物参考图%d" % (idx + 1), "image")
                face_urls.append(url)
                ids = _uploaded_material_ids(response)
                sensitive_ids.extend(ids)
                self._job["sensitiveMaterialIds"] = list(dict.fromkeys(
                    list(self._job.get("sensitiveMaterialIds") or []) + ids
                ))
                _save_replacement_job(self._job)
        scene_url = ""
        if self._scene_path:
            scene_url, _resp = upload_asset_url(self._scene_path, "同款替换场景图", "image")
        return product_urls, face_urls, scene_url, list(dict.fromkeys(sensitive_ids))

    def _build_job(self):
        analysis = self._source.get("breakdownAnalysis") or {}
        meta = analysis.get("meta") or {}
        duration = float(meta.get("duration") or 0) or float(_probe_video(self._source.get("sourceVideoPath") or "").get("duration") or 8)
        out_dir = self._job.get("outDir") or os.path.join(data_dir(), "video_replacements", uuid.uuid4().hex)
        os.makedirs(out_dir, exist_ok=True)
        no_person_mode = bool(self.no_person_mode.isChecked())
        identity_mode = "standard"
        strict_script_audio = False
        selected_model = self._selected_replacement_model()
        principal_mode = str(self._job.get("principalReplacementMode") or "").strip()
        principal_enabled = bool(
            not no_person_mode
            and principal_mode == "source_video_edit"
            and _env_enabled("VIDEO_REPLACE_PRINCIPAL_REPLACEMENT", "1")
        )
        audio_mode = self._selected_audio_mode()
        segments = self._job.get("segments") or _build_hybrid_replacement_plan(
            analysis, duration, segment_seconds=8, strict_script_audio=strict_script_audio)
        for segment in segments:
            segment["segmentType"] = (
                "talking"
                if not no_person_mode and _replacement_segment_should_talk(
                    segment, audio_mode=audio_mode, strict_script_audio=strict_script_audio)
                else "non_talking"
            )
        job = {
            "id": self._job.get("id") or uuid.uuid4().hex,
            "sourceVideoPath": self._source.get("sourceVideoPath") or "",
            "sourceUrl": self._source.get("sourceUrl") or "",
            "platform": self._source.get("platform") or "",
            "breakdownAnalysis": analysis,
            "productImageUrls": list(self._product_urls),
            "productSourcePaths": list(self._product_paths),
            "productPreprocess": list(self._job.get("productPreprocess") or []),
            "faceSourcePaths": [] if no_person_mode else list(self._face_paths),
            "faceSourceUrls": [] if no_person_mode else list(self._face_urls),
            "modelFaceUrl": "" if no_person_mode else (self._face_url or self._virtual_url),
            "sceneImageUrl": self._scene_url,
            "sceneImagePath": self._scene_path or "",
            "scenePrompt": self._job.get("scenePrompt") or "",
            "sourceReplacementEntities": _replacement_source_entities_from_analysis(analysis),
            "targetFaceReferencePath": "",
            "facefusionConfig": {},
            "principalActor": dict(self._job.get("principalActor") or {}),
            "personReferencePaths": [] if no_person_mode else list(self._face_paths[:3]),
            "personReferenceUrls": [] if no_person_mode else list(self._face_urls[:3]),
            "personReferenceFullBodyConfirmed": bool(
                False if no_person_mode else self.person_full_body.isChecked()
            ),
            "principalReplacementMode": "source_video_edit" if principal_enabled else "",
            "identityMode": "standard",
            "enableFaceFusion": False,
            "sensitiveMaterialIds": [] if no_person_mode else list(self._job.get("sensitiveMaterialIds") or []),
            "noPersonMode": no_person_mode,
            "productNotes": "uploaded product reference images: " + ", ".join(os.path.basename(p) for p in self._product_paths),
            "modelNotes": "no human subject; product-only video" if no_person_mode else (
                "authorized full-body person references" if principal_enabled else (
                    "authorized model face" if self._face_url else "virtual model identity")),
            "segments": segments,
            "outDir": out_dir,
            "pipeline": self._job.get("pipeline") or os.getenv("VIDEO_REPLACE_PIPELINE", "hybrid_v2"),
            "aspectRatio": "9:16",
            "resolution": "720p",
            "audioMode": audio_mode,
            "voiceId": self._selected_voice_id(),
            "replacementAudioPath": getattr(self, "_replacement_audio_path", "") or self._job.get("replacementAudioPath") or "",
            "replacementAudioUrl": getattr(self, "_replacement_audio_url", "") or self._job.get("replacementAudioUrl") or "",
            "digitalHumanMode": "std",
            "strictScriptAudio": strict_script_audio,
            "actionControlEnabled": False,
            "productAnchorEnabled": False,
            "model": selected_model,
            "status": "running",
            "startedAt": self._job.get("startedAt") or time.time(),
            "outputPath": "",
            "assetId": "",
        }
        for seg in segments:
            seg["prompt"] = _build_replacement_prompt(
                seg, analysis, job["productNotes"], job["modelNotes"])
        return job

    def start_generation(self):
        if self._busy:
            self.status.setText("已有替换生成任务正在运行")
            QtWidgets.QMessageBox.information(self, "替换生成", "已有替换生成任务正在运行，请等待当前任务完成。")
            return
        if not self._job.get("segments"):
            self._warn_generation_blocked("请先点击『生成替换方案』并检查片段。")
            return
        no_person_mode = bool(self.no_person_mode.isChecked())
        principal_enabled = _principal_replacement_enabled(self._job)
        if not self._product_paths and not principal_enabled:
            self._warn_generation_blocked("请先上传 1-3 张产品图。")
            return
        if not no_person_mode:
            try:
                self._face_paths = _validate_person_reference_paths(self._face_paths)
            except Exception as exc:
                self._warn_generation_blocked(str(exc))
                return
            if principal_enabled:
                if not self.person_full_body.isChecked():
                    self._warn_generation_blocked("请确认人物参考图中至少一张为清晰全身图。")
                    return
                actor_status = str((self._job.get("principalActor") or {}).get("status") or "")
                if actor_status not in ("detected", "manual"):
                    if actor_status == "manual_required" and self.target_person.currentData():
                        actor = dict(self._job.get("principalActor") or {})
                        actor["status"] = "manual"
                        actor["manualFramePath"] = str(self.target_person.currentData())
                        actor["previewPath"] = actor.get("previewPath") or actor["manualFramePath"]
                        self._job["principalActor"] = actor
                    else:
                        self._warn_generation_blocked("请先确认原片主角；识别置信度不足时请选择候选帧。")
                        return
            elif len(self._face_paths) != 3:
                self._warn_generation_blocked("旧版同款替换需要三张授权人脸照片：正脸、左 45°、右 45°。")
                return
            if not self.face_authorized.isChecked():
                self._warn_generation_blocked("使用人物参考图前必须确认已获得授权。")
                return
        try:
            self._collect_plan_edits()
        except Exception as exc:
            self._warn_generation_blocked(str(exc))
            return
        audio_mode = self._selected_audio_mode()
        replacement_audio_path = getattr(self, "_replacement_audio_path", "")
        replacement_audio_url = getattr(self, "_replacement_audio_url", "")
        if audio_mode == "uploaded" and not (
                replacement_audio_path and os.path.isfile(replacement_audio_path)):
            self._warn_generation_blocked("请选择并上传一条完整配音音频；该音频会替换最终成片整条音轨。")
            return
        if audio_mode in ("tts", "uploaded"):
            missing_scripts = [
                str(seg.get("index") or idx + 1)
                for idx, seg in enumerate(self._job.get("segments") or [])
                if not str(seg.get("script") or "").strip()
            ]
            if missing_scripts:
                mode_label = "AI 音色配音" if audio_mode == "tts" else "上传完整配音"
                self._warn_generation_blocked(
                    "选择%s时，每个片段都需要口播稿，用于字幕和口型同步；缺少片段：" %
                    mode_label + "、".join(missing_scripts)
                )
                return
        if audio_mode == "tts":
            timing_issues = _replacement_tts_timing_issues(self._job.get("segments") or [], audio_mode)
            if timing_issues:
                self._warn_generation_blocked(_format_replacement_tts_timing_block_message(timing_issues))
                return
        subtitle_issues = _replacement_subtitle_text_issues(self._job.get("segments") or [])
        if subtitle_issues:
            answer = QtWidgets.QMessageBox.question(
                self,
                "字幕预检",
                _format_replacement_subtitle_issue_message(subtitle_issues),
            )
            if answer != QtWidgets.QMessageBox.Yes:
                return
            for segment in self._job.get("segments") or []:
                if str(segment.get("script") or "").strip():
                    segment["scriptReviewed"] = True
        self._job["scenePrompt"] = self.scene_prompt.text().strip()
        self._job["identityMode"] = "standard"
        self._job["enableFaceFusion"] = False
        self._job["principalReplacementMode"] = "source_video_edit" if principal_enabled else ""
        self._job["audioMode"] = audio_mode
        self._job["voiceId"] = self._selected_voice_id()
        self._job["replacementAudioPath"] = replacement_audio_path
        self._job["replacementAudioUrl"] = replacement_audio_url
        self._job["personReferencePaths"] = [] if no_person_mode else list(self._face_paths[:3])
        self._job["personReferenceFullBodyConfirmed"] = bool(
            False if no_person_mode else self.person_full_body.isChecked()
        )
        self._job["actionControlEnabled"] = False
        self._job["productAnchorEnabled"] = False
        self._job["targetFaceReferencePath"] = ""
        self._busy = True
        self.b_retry_failed.setEnabled(False)
        if hasattr(self, "b_regen_segment"):
            self.b_regen_segment.setEnabled(False)
        self.b_review.setEnabled(False)
        self._job["startedAt"] = time.time()
        self.status.setText("上传参考图…")
        self._set_generation_feedback(True, "上传参考图…")

        def work():
            try:
                job = self._build_job()
                self._job = job
                upstream_preflight = _replacement_upstream_preflight(job)
                job["upstreamPreflight"] = upstream_preflight
                if not upstream_preflight.get("ok"):
                    error_id = _replacement_error_id(
                        "video_replace_upstream_preflight_blocked",
                        RuntimeError(upstream_preflight.get("code") or "upstream_preflight_failed"),
                        source_video=job.get("sourceVideoPath") or "",
                    )
                    job.update({
                        "status": "failed",
                        "error": upstream_preflight.get("code") or "upstream_preflight_failed",
                        "errorId": error_id,
                    })
                    job["diagnostics"] = _replacement_diagnostics_summary(job, upstream_preflight)
                    _save_replacement_job(job)
                    BRIDGE.payload.emit("video_replace_done", {
                        "jobId": job["id"],
                        "message": "%s（错误编号 %s）" % (
                            upstream_preflight.get("summary") or "上游预检未通过",
                            error_id or "-",
                        ),
                        "job": job,
                    })
                    return
                def emit_ref_progress(message):
                    BRIDGE.payload.emit("video_replace_progress", {
                        "jobId": job["id"],
                        "stage": "product_refs",
                        "message": message,
                        "timing": _replacement_timing_snapshot(job, None, stage="product_refs"),
                        "segments": job.get("segments") or [],
                    })

                self._product_urls, self._face_urls, self._scene_url, sensitive_ids = self._upload_refs(lambda message: emit_ref_progress(message))
                if no_person_mode:
                    self._face_urls = []
                    self._face_url = ""
                    sensitive_ids = []
                else:
                    self._face_url = self._face_urls[0]
                self._job["sensitiveMaterialIds"] = sensitive_ids
                job = self._build_job()
                self._job = job
                job["upstreamPreflight"] = upstream_preflight
                job["driftGuardConfig"] = _replacement_drift_guard_config(job)
                preflight = _run_replacement_reference_preflight(job)
                job["referencePreflight"] = preflight
                _save_replacement_job(job)
                if _replacement_reference_preflight_blocks(job, preflight):
                    error_id = _replacement_error_id(
                        "video_replace_reference_preflight_blocked",
                        RuntimeError(preflight.get("code") or "reference_mismatch"),
                        source_video=job.get("sourceVideoPath") or "",
                    )
                    job.update({
                        "status": "failed",
                        "error": preflight.get("reason") or "参考图与源视频主题冲突",
                        "errorId": error_id,
                    })
                    job["diagnostics"] = _replacement_diagnostics_summary(job, preflight)
                    _save_replacement_job(job)
                    BRIDGE.payload.emit("video_replace_done", {
                        "jobId": job["id"],
                        "message": "参考图与原视频主题冲突，已停止生成（错误编号 %s）" % (error_id or "-"),
                        "job": job,
                    })
                    return
                BRIDGE.payload.emit("video_replace_progress", {
                    "jobId": job["id"], "stage": "editing", "message": "开始串行生成片段…",
                    "timing": _replacement_timing_snapshot(job, None, stage="editing"),
                    "segments": job["segments"],
                })
                self._run_job_segments(job, [s for s in job["segments"]])
            except Exception as exc:
                error_id = _replacement_error_id("video_replace_upload_failed", exc)
                cleanup = _cleanup_replacement_sensitive_materials(self._job)
                failure_job = dict(self._job or {}, status="failed", error=str(exc)[:240],
                                   errorId=error_id, sensitiveCleanup=cleanup)
                failure_job["diagnostics"] = _replacement_diagnostics_summary(failure_job)
                try:
                    _save_replacement_job(failure_job)
                except Exception:
                    pass
                BRIDGE.payload.emit("video_replace_done", {
                    "jobId": (self._job or {}).get("id") or "",
                    "message": "替换生成失败（错误编号 %s）:%s" % (error_id or "-", str(exc)[:120]),
                    "job": failure_job,
                })
        run_bg(work)

    def _run_job_segments(self, job, selected_segments):
        job["startedAt"] = job.get("startedAt") or time.time()
        job["status"] = "running"
        total = len(job.get("segments") or [])

        def emit_progress(segment=None, stage="", message="", prompt=None):
            timing = _replacement_timing_snapshot(job, segment, stage=stage)
            if segment is not None:
                segment["stage"] = timing.get("stage") or stage or segment.get("status") or ""
                segment["stageLabel"] = timing.get("stageLabel") or ""
                segment["elapsedSec"] = timing.get("segmentElapsedSec") or 0
                segment["etaSec"] = timing.get("segmentEtaSec") or 0
            BRIDGE.payload.emit("video_replace_progress", {
                "jobId": job["id"],
                "stage": timing.get("stage") or stage or "",
                "message": message or _replacement_stage_label(stage),
                "timing": timing,
                "segments": job.get("segments") or [],
                "prompt": prompt if prompt is not None else ((segment or {}).get("prompt") or ""),
            })

        _REPLACEMENT_PROGRESS_CALLBACKS[str(job.get("id") or "")] = emit_progress
        try:
            for seg in selected_segments:
                if self._cancel_requested or _replacement_cancel_requested(job):
                    _mark_replacement_job_canceled(job)
                    return
                seg["segmentStartedAt"] = time.time()
                seg["segmentEndedAt"] = 0
                seg["elapsedSec"] = 0
                seg["etaSec"] = _replacement_segment_baseline_sec(seg)
                emit_progress(seg, "editing", "生成片段 %s/%s：准备生成（%.1f-%.1fs）" % (
                    seg.get("index"), total, seg.get("start") or 0, seg.get("end") or 0))
                try:
                    if (job.get("pipeline") or os.getenv("VIDEO_REPLACE_PIPELINE", "hybrid_v2")) == "hybrid_v2":
                        _run_hybrid_replacement_segment(job, seg)
                    else:
                        _run_replacement_segment(job, seg)
                        if seg.get("status") == "done":
                            seg.update({"audioStatus": "passed", "qcStatus": "passed"})
                except Exception as exc:
                    if self._cancel_requested or _replacement_cancel_requested(job) or _replacement_cancel_exception(exc):
                        seg.update({"status": "cancel_requested", "stage": "cancel_requested",
                                    "stageLabel": "取消中", "etaSec": 0})
                        _mark_replacement_job_canceled(job)
                        return
                    raise
                seg["segmentEndedAt"] = time.time()
                seg["elapsedSec"] = _replacement_segment_elapsed_sec(seg)
                if seg.get("status") == "done":
                    seg.update({"stage": "done", "stageLabel": _replacement_stage_label("done"), "etaSec": 0})
                elif seg.get("status") == "failed":
                    seg.update({"etaSec": 0})
                _save_replacement_job(job)
                emit_progress(seg, seg.get("stage") or seg.get("status") or "editing", "片段 %s/%s 状态已更新" % (
                    seg.get("index"), total))
            failed = [s for s in job.get("segments") or [] if s.get("status") == "failed"]
            if failed:
                job["status"] = "partial"
                job["diagnostics"] = _replacement_diagnostics_summary(job)
                _save_replacement_job(job)
                BRIDGE.payload.emit("video_replace_done", {
                    "jobId": job["id"],
                    "message": "有 %d 个片段失败，可点击『重试失败片段』" % len(failed),
                    "job": job,
                    "failedSegments": failed,
                })
                return
            job["status"] = "awaiting_review"
            _save_replacement_job(job)
            BRIDGE.payload.emit("video_replace_progress", {
                "jobId": job["id"],
                "stage": "awaiting_review",
                "message": "片段已通过自动检查，请查看首、中、尾帧和试听后确认合成。",
                "timing": _replacement_timing_snapshot(job, None, stage="awaiting_review"),
                "segments": job.get("segments") or [],
            })
        finally:
            _REPLACEMENT_PROGRESS_CALLBACKS.pop(str(job.get("id") or ""), None)

    def _collect_plan_edits(self):
        segments = self._job.get("segments") or []
        audio_mode = self._selected_audio_mode()
        no_person_mode = bool(self.no_person_mode.isChecked())
        for row, segment in enumerate(segments):
            segment["script"] = self._segment_script_value(row)
            segment["segmentType"] = (
                "talking"
                if not no_person_mode and _replacement_segment_should_talk(segment, audio_mode=audio_mode)
                else "non_talking"
            )

    def confirm_and_concat(self):
        if self._busy or self._job.get("status") != "awaiting_review":
            self._warn_generation_blocked("当前没有等待人工审核的完整片段。")
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "确认片段并合成",
            "请确认已查看每段首、中、尾帧并完成试听。确认后将合成并存入资产库。",
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        for segment in self._job.get("segments") or []:
            segment["reviewApproved"] = True
        if not _replacement_segments_ready_for_final(self._job.get("segments") or []):
            self._warn_generation_blocked("仍有片段未通过音频或质量检查，不能合成。")
            return
        self._busy = True
        self._set_generation_feedback(True, "正在合成并执行最终音频检查…")

        def work():
            job = self._job
            try:
                out = os.path.join(job.get("outDir") or data_dir(), "replacement_final_%s.mp4" % int(time.time()))
                paths = [s.get("videoPath") for s in job.get("segments") or []]
                final_out = _prepare_replacement_final_video(job, paths, out)
                asset = _save_replacement_to_assets(final_out, job)
                if not asset:
                    raise RuntimeError("replacement_asset_save_failed")
                job.update({
                    "status": "done",
                    "outputPath": asset.get("path") or final_out,
                    "assetId": asset.get("id") or "",
                    "audioCheck": _replacement_audio_qc(asset.get("path") or final_out),
                    "reviewStatus": "approved",
                })
                cleanup = _cleanup_replacement_sensitive_materials(job)
                temporary_cleanup = _cleanup_replacement_temporary_materials(job)
                job["sensitiveCleanup"] = cleanup
                job["temporaryCleanup"] = temporary_cleanup
                _save_replacement_job(job)
                BRIDGE.payload.emit("video_replace_done", {
                    "jobId": job["id"], "message": "替换生成完成，已存入资产库", "job": job,
                    "audioCheck": job["audioCheck"], "reviewStatus": "approved",
                    "sensitiveCleanup": cleanup, "temporaryCleanup": temporary_cleanup,
                })
            except Exception as exc:
                error_id = _replacement_error_id("video_replace_concat_failed", exc, source_video=job.get("sourceVideoPath") or "")
                job["status"] = "failed"
                _save_replacement_job(job)
                BRIDGE.payload.emit("video_replace_done", {
                    "jobId": job["id"],
                    "message": "合成失败（错误编号 %s）:%s" % (error_id or "-", str(exc)[:120]),
                    "job": job,
                })
        run_bg(work)

    def retry_failed_segments(self):
        if self._busy:
            return
        failed = [s for s in (self._job.get("segments") or []) if s.get("status") == "failed"]
        if not failed:
            self.status.setText("没有失败片段可重试")
            self.b_retry_failed.setEnabled(False)
            QtWidgets.QMessageBox.information(self, "替换生成", "没有失败片段可重试。")
            return
        failed, retry_normalization = _normalize_replacement_retry_segments(self._job, failed)
        retry_summaries = [_prepare_replacement_segment_for_retry(segment) for segment in failed]
        self._job["lastRetryPreparation"] = {
            "ts": time.time(),
            "normalization": retry_normalization,
            "segments": [
                {
                    "index": segment.get("index"),
                    "demotedCodes": summary.get("demotedCodes") or [],
                }
                for segment, summary in zip(failed, retry_summaries)
            ],
        }
        _save_replacement_job(self._job)
        self._busy = True
        self.b_retry_failed.setEnabled(False)
        self.status.setText("正在重试失败片段…")
        self._set_generation_feedback(True, "正在重试失败片段…")
        run_bg(lambda: self._run_job_segments(self._job, failed))

    def regenerate_selected_segment(self):
        if self._busy:
            return
        row = self.table.currentRow() if hasattr(self, "table") else -1
        segments = self._job.get("segments") or []
        if row < 0 or row >= len(segments):
            self.status.setText("请先选中一个片段")
            QtWidgets.QMessageBox.information(self, "替换生成", "请先在片段表中选中一个要重生的片段。")
            return
        segment = segments[row]
        current_note = str(segment.get("manualDefectNote") or "")
        note, ok = QtWidgets.QInputDialog.getMultiLineText(
            self,
            "重生选中片段",
            "请填写上一版瑕疵，生成时会写入该片段提示词：",
            current_note,
        )
        if not ok:
            return
        summary = _prepare_replacement_segment_for_manual_regeneration(segment, note)
        if not summary.get("retryable"):
            self._warn_generation_blocked("请先填写上一版瑕疵说明。")
            return
        self._job["status"] = "partial"
        self._job["lastRetryPreparation"] = {
            "ts": time.time(),
            "manualDefect": {
                "index": segment.get("index"),
                "note": str(note or "")[:500],
            },
        }
        _save_replacement_job(self._job)
        self._busy = True
        self.b_retry_failed.setEnabled(False)
        self.b_regen_segment.setEnabled(False)
        self.b_review.setEnabled(False)
        self.status.setText("正在重生选中片段…")
        self._set_generation_feedback(True, "正在重生选中片段…")

        def work():
            try:
                self._run_job_segments(self._job, [segment])
            finally:
                pass
        run_bg(work)

    def cancel_generation(self):
        if not self._job:
            return
        self._cancel_requested = True
        self._job["cancelRequested"] = True
        message = "已请求取消；当前远程片段结束后停止并清理人脸素材。"
        self.status.setText(message)
        if self._busy:
            self._job["status"] = "cancel_requested"
            for segment in self._job.get("segments") or []:
                if str(segment.get("status") or "") in ("running", "keyframing", "editing", "downloading", "tts",
                                                         "facefusion", "audio_muxing", "qc",
                                                         "principal_actor_extract", "principal_video_edit"):
                    segment["stage"] = "cancel_requested"
                    segment["stageLabel"] = "取消中"
                    break
            _save_replacement_job(self._job)
            cancel_button = getattr(self, "b_cancel", None)
            if cancel_button is not None:
                cancel_button.setText("取消中")
                cancel_button.setEnabled(False)
            progress = getattr(self, "progress", None)
            if progress is not None:
                try:
                    progress.setFormat("已请求取消；当前远程片段结束后停止")
                except Exception:
                    pass
            if BRIDGE is not None:
                BRIDGE.payload.emit("video_replace_progress", {
                    "jobId": self._job.get("id"),
                    "stage": "cancel_requested",
                    "message": "已请求取消；当前远程片段结束后停止",
                    "timing": _replacement_timing_snapshot(self._job, None, stage="cancel_requested"),
                    "segments": self._job.get("segments") or [],
                })
            return
        if not self._busy:
            _mark_replacement_job_canceled(self._job)
            self.refresh_segments()

    def delete_segment(self, segment_index):
        if self._busy:
            self.status.setText("生成中不能删除片段，请先取消或等待当前任务结束。")
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "删除片段",
            "确定删除片段 %s 吗？删除后会重新编号。" % segment_index,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        self._sync_segment_scripts_from_table()
        if not _delete_replacement_segment(self._job, segment_index):
            self._warn_generation_blocked("只能删除待生成片段，且至少保留一个片段。")
            return
        _save_replacement_job(self._job)
        self.refresh_segments()
        self.b_start.setEnabled(bool(self._job.get("segments")) and self._job.get("status") in ("planned", "partial"))
        self.status.setText("已删除片段 %s，可继续执行替换生成。" % segment_index)

    def _set_generation_feedback(self, running, message=""):
        start_button = getattr(self, "b_start", None)
        progress = getattr(self, "progress", None)
        progress_detail = getattr(self, "progress_detail", None)
        for attr, enabled in (
            ("b_start", not running),
            ("b_plan", not running),
            ("b_cancel", bool(running)),
            ("b_regen_segment", not running and bool(self._job.get("segments"))),
        ):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setEnabled(enabled)
        if progress is not None:
            progress.setVisible(bool(running))
        if running:
            if start_button is not None:
                start_button.setText("生成中…")
            if progress is not None:
                progress.setRange(0, 0)
                progress.setFormat(message or "处理中…")
        else:
            if start_button is not None:
                start_button.setText("开始替换生成")
                start_button.setEnabled(
                    bool(self._job.get("segments")) and self._job.get("status") in ("planned", "partial")
                )
            if progress is not None:
                progress.setRange(0, 100)
                progress.setValue(0)
                progress.setFormat("")
            if progress_detail is not None:
                progress_detail.setText("用时: - · 预计剩余: -")

    def _warn_generation_blocked(self, message):
        self.status.setText(message)
        QtWidgets.QMessageBox.warning(self, "替换生成", message)

    def _show_generation_result(self, message, ok):
        status = str(self._job.get("status") or "")
        diagnostics = self._job.get("diagnostics") or {}
        diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        next_action = str(diagnostics.get("nextAction") or "").strip()
        failed_segments = diagnostics.get("failedSegments") or []
        detail_lines = []
        if failed_segments:
            detail_lines.append("失败片段: " + ", ".join(str(i) for i in failed_segments))
        if next_action and next_action not in str(message or ""):
            detail_lines.append("建议操作: " + next_action)
        if detail_lines:
            message = (message or "").rstrip() + "\n" + "\n".join(detail_lines)
        if ok:
            QtWidgets.QMessageBox.information(self, "替换生成", message or "替换生成完成，已自动存入资产库。")
        elif status == "partial":
            QtWidgets.QMessageBox.warning(self, "替换生成", message or "部分片段生成失败，可重试失败片段。")
        else:
            QtWidgets.QMessageBox.warning(self, "替换生成", message or "替换生成失败，请查看错误编号。")

    def _make_segment_script_editor(self, seg):
        editor = QtWidgets.QPlainTextEdit()
        editor.setObjectName("segmentScriptEditor")
        editor.setPlainText(str((seg or {}).get("script") or ""))
        editor.textChanged.connect(lambda s=seg, e=editor: self._on_segment_script_changed(s, e))
        editor.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        editor.setMinimumWidth(500)
        editor.setMinimumHeight(104)
        editor.setMaximumHeight(132)
        editor.setTabChangesFocus(True)
        editor.setPlaceholderText("可编辑口播稿")
        editor.setReadOnly((seg or {}).get("status") not in ("pending", "planned", None))
        editor.setStyleSheet(
            "QPlainTextEdit#segmentScriptEditor{"
            "background:rgba(10,16,28,0.96);color:#f8fafc;"
            "border:1px solid rgba(148,163,184,0.45);border-radius:6px;"
            "padding:6px 8px;selection-background-color:#2563eb;selection-color:#ffffff;"
            "font-size:13px;line-height:18px;}"
            "QPlainTextEdit#segmentScriptEditor:focus{"
            "border:1px solid #8b8ff8;background:rgba(15,23,42,0.98);}"
            "QPlainTextEdit#segmentScriptEditor:read-only{"
            "background:rgba(10,16,28,0.74);color:#e5e7eb;}"
        )
        return editor

    def _segment_script_value(self, row):
        widget = self.table.cellWidget(row, 2)
        if isinstance(widget, QtWidgets.QPlainTextEdit):
            return widget.toPlainText().strip()
        item = self.table.item(row, 2)
        return item.text().strip() if item is not None else ""

    def _on_segment_script_changed(self, segment, editor):
        segment = segment if isinstance(segment, dict) else {}
        try:
            value = editor.toPlainText().strip()
        except Exception:
            return False
        if value == str(segment.get("script") or "").strip():
            return False
        segment["script"] = value
        segment["scriptReviewed"] = False
        return True

    def _sync_segment_scripts_from_table(self):
        segments = list((self._job or {}).get("segments") or [])
        table = getattr(self, "table", None)
        if table is None:
            return False
        try:
            count = min(int(table.rowCount()), len(segments))
        except Exception:
            count = len(segments)
        changed = False
        for row in range(max(0, count)):
            segment = segments[row]
            value = self._segment_script_value(row)
            if value != str(segment.get("script") or "").strip():
                segment["script"] = value
                segment["scriptReviewed"] = False
                changed = True
        return changed

    def refresh_segments(self):
        segments = self._job.get("segments") or []
        self.table.setRowCount(0)
        for seg in segments:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(seg.get("index") or row + 1)))
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(
                "%.1f-%.1fs" % (float(seg.get("start") or 0), float(seg.get("end") or 0))))
            seg["segmentType"] = "non_talking"
            self.table.setCellWidget(row, 2, self._make_segment_script_editor(seg))
            self.table.setItem(row, 3, QtWidgets.QTableWidgetItem(_replacement_segment_status_text(self._job, seg)))
            self.table.setItem(row, 4, QtWidgets.QTableWidgetItem(
                " / ".join(os.path.basename(p) for p in (seg.get("qcFrames") or []))))
            self.table.setItem(row, 5, QtWidgets.QTableWidgetItem(os.path.basename(seg.get("videoPath") or "")))
            self.table.setItem(row, 6, QtWidgets.QTableWidgetItem(_replacement_segment_timing_text(seg)))
            self.table.setItem(row, 7, QtWidgets.QTableWidgetItem(_replacement_segment_display_error(seg)))
            action_host = QtWidgets.QWidget()
            action_layout = QtWidgets.QHBoxLayout(action_host)
            action_layout.setContentsMargins(6, 6, 6, 6)
            action_layout.setSpacing(0)
            delete_btn = QtWidgets.QPushButton("删除")
            delete_btn.setObjectName("ghost")
            delete_btn.setFixedSize(92, 30)
            delete_btn.setEnabled((not self._busy) and seg.get("status") in ("pending", "planned", None, ""))
            delete_btn.clicked.connect(lambda _=False, i=seg.get("index") or row + 1: self.delete_segment(i))
            action_layout.addWidget(delete_btn, 0, QtCore.Qt.AlignCenter)
            self.table.setCellWidget(row, 8, action_host)
            self.table.setRowHeight(row, 122)
        if hasattr(self, "b_regen_segment"):
            self.b_regen_segment.setEnabled((not self._busy) and bool(segments))

    def open_output(self):
        path = self._job.get("outputPath") or ""
        if path:
            _open_path(path)

    def add_output_to_pending(self):
        path = self._job.get("outputPath") or ""
        if not (path and os.path.isfile(path)):
            self.status.setText("暂无可加入待发布队列的成片")
            return
        entry = {
            "id": "pp_%s" % uuid.uuid4().hex,
            "wfName": "同款替换生成",
            "video": path,
            "audio": "",
            "caption": "同款替换生成",
            "account": "",
            "platform": self._job.get("platform") or "douyin",
            "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "待确认",
        }
        add_pending(entry)
        self.status.setText("已加入待发布队列")


# ================= 对话式工作流 Agent =================
# lk888 各能力对应的模型(用户可在工作流里改)。⚠️lk888 网关无“千问3.7Max”,
# 图像/视频理解改用多模态 gemini-3.1-pro-preview 替代(已在 UI 标注、可切换)。
WF_MODELS = {
    "orchestrator": ("总控 LLM", "gpt-5.4", "#7c6dff"),
    "text":         ("文字模型", "gpt-5.4-xhigh", "#8b5cf6"),
    "vision":       ("图像/视频理解", "gemini-3.1-pro-preview", "#06b6d4"),
    "image":        ("生图模型", "gpt-image-2", "#ec4899"),
    "video":        ("视频模型", "vidu-jieshuoman", "#f59e0b"),
    "tts":          ("语音 TTS", "doubao-tts-2.0", "#22c55e"),
}
# 流水线能力(步骤类型)→(名称, 图标kind, 颜色, 绑定的模型键)
WF_CAPS = {
    "collect": ("平台采集", "chart", "#f43f5e", None),
    "vision":  ("视频理解", "platform", "#06b6d4", "vision"),
    "text":    ("文本生成", "publish", "#8b5cf6", "text"),
    "image":   ("图像生成", "xhs", "#ec4899", "image"),
    "video":   ("视频生成", "douyin", "#f59e0b", "video"),
    "tts":     ("语音合成", "heart", "#22c55e", "tts"),
    "library": ("入素材库", "building", "#14b8a6", None),
    "publish": ("定时发布", "publish", "#a855f7", None),
}

WORKFLOWS = []


def _wf_path():
    return os.path.join(data_dir(), "workflows.json")


def load_workflows():
    global WORKFLOWS
    import json as _json
    try:
        p = _wf_path()
        if os.path.isfile(p):
            WORKFLOWS = _json.load(open(p, encoding="utf-8"))
    except Exception as e:
        log("load workflows: %s" % e)
        WORKFLOWS = []


def save_workflows():
    import json as _json
    try:
        _atomic_write_json(_wf_path(), WORKFLOWS)
    except Exception as e:
        log("save workflows: %s" % e)


# ---------- 待发布队列(定时/手动生产的产物先入队,公开发布需人工确认) ----------
PENDING = []


def _pending_path():
    return os.path.join(data_dir(), "pending_publish.json")


def load_pending():
    global PENDING
    import json as _json
    try:
        p = _pending_path()
        if os.path.isfile(p):
            PENDING = _json.load(open(p, encoding="utf-8"))
        if not isinstance(PENDING, list):
            PENDING = []
        PENDING = [x for x in PENDING if isinstance(x, dict)]  # 过滤损坏/手改的非字典项,统一给所有消费方兜底
    except Exception as e:
        log("load pending: %s" % e)
        PENDING = []


def save_pending():
    import json as _json
    try:
        _atomic_write_json(_pending_path(), PENDING)
    except Exception as e:
        log("save pending: %s" % e)


def add_pending(entry):
    """把一条待发布产物插到队列最前;返回该 entry。"""
    PENDING.insert(0, entry)
    save_pending()
    return entry


def remove_pending(pid):
    global PENDING
    PENDING = [x for x in PENDING if (x or {}).get("id") != pid]
    save_pending()


def _parse_sched_time(text):
    """从计划文本里解析出 HH:MM(如『每天 09:00』→ '09:00』)。解析不到返回 None。"""
    import re as _re
    m = _re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", str(text or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h < 24 and 0 <= mi < 60:
        return "%02d:%02d" % (h, mi)
    return None


def _should_fire(wf, now_hm, today, window_min=120):
    """纯判断:该工作流此刻是否应触发定时生产。
    条件:工作流启用 + 计划启用 + 解析出时间 + 今天没跑过 + 当前落在[计划时刻, +window_min)窗口内。
    窗口取 120 分钟(而非几分钟):既能在引擎忙(某条视频生产占用很久)导致错过精确点后补跑,
    避免多工作流互相饿死;又不至于开机时对早已过去大半天的计划做意外补跑。"""
    if not (wf.get("enabled", True) and (wf.get("schedule") or {}).get("enabled")):
        return False
    tgt = _parse_sched_time((wf.get("schedule") or {}).get("text"))
    if not tgt:
        return False
    if wf.get("_last_run_date") == today:
        return False
    def _m(hm):
        h, mm = hm.split(":")
        return int(h) * 60 + int(mm)
    delta = _m(now_hm) - _m(tgt)
    return 0 <= delta < window_min


WF_ORCH_SYSTEM = """你是「云灵星图」的 AI 工作流编排助手。用户用自然语言描述一个短视频自动化需求,你要:
1. 用简洁友好的中文回应(1-3句);关键参数(账号/频率/数量/关键词/平台)缺失时先追问,不要臆造账号名。
2. 当需求足够清晰、能形成一条自动化流水线时,在回复最后附一个工作流 JSON,用 ```json 代码块包裹(整段只出现一次)。

工作流 JSON 结构:
{"name":"工作流名","desc":"一句话说明","steps":[{"cap":"能力","title":"步骤名","desc":"这一步在做什么","params":{"键":"值"}}],"schedule":{"enabled":true,"text":"每天10:00","perRun":3,"autoPublish":false,"publishAccountId":"","publishPlatform":"douyin"}}

可用能力 cap 及其模型:
- collect  平台采集:从抖音/小红书按关键词搜索并下载最热门视频(params: platform, keyword, topN, sort=hot)
- vision   视频理解:多模态模型把视频拆成详细分镜脚本(模型 gemini-3.1-pro-preview;注:用户要的千问3.7Max当前网关未提供,已用它替代)
- text     文本生成:gpt-5.4-xhigh 写脚本/文案/标题
- image    图像生成:gpt-image-2 出封面/配图
- video    视频生成:vidu-jieshuoman(解说漫)按脚本裂变多条视频素材(params: count, duration, aspect)
- tts      语音合成:doubao-tts-2.0 配音
- library  入素材库:把产物存进素材库
- publish  发布/入队:将生成视频加入待发布队列;若 schedule.autoPublish=true 且配置 publishAccountId,定时执行时会自动发送视频(params: account, platform, perDay, time)

步骤按执行顺序排列。信息不足只追问、不给 JSON。"""


def extract_workflow(reply):
    """从 LLM 回复里抽出工作流 JSON。返回 (wf_dict 或 None, 用于展示的纯文本)。"""
    import json as _json
    import re as _re
    m = _re.search(r"```json\s*(\{[\s\S]*?\})\s*```", reply)
    if not m:
        m = _re.search(r"(\{[\s\S]*?\"steps\"[\s\S]*\})\s*$", reply)
    if not m:
        return None, reply
    try:
        wf = _json.loads(m.group(1))
    except Exception:
        return None, reply
    if not isinstance(wf, dict) or not wf.get("steps"):
        return None, reply
    display = reply[:m.start()].strip()
    return wf, (display or "已按你的需求生成工作流 ✅")


# ---------- 工作流真实执行引擎(每步真调对应模型/能力) ----------
def _wf_out_dir():
    d = os.path.join(data_dir(), "wf_out")
    os.makedirs(d, exist_ok=True)
    return d


def _wf_download(url, path):
    r = requests.get(url, timeout=300, verify=True)
    r.raise_for_status()  # 非 2xx(签名过期403/5xx/HTML错误页)直接抛错,别把错误页当成 mp4 存下来入队
    with open(path, "wb") as f:
        f.write(r.content)
    return path


def _open_path_cmd(path):
    if sys.platform == "darwin":
        return ["open", path]
    return ["xdg-open", path]


def _open_path(path):
    """用系统默认程序打开文件/文件夹(视频/音频/图片/素材库目录)。"""
    try:
        path = str(path or "")
        if not path:
            return False
        os.makedirs(path, exist_ok=True) if not os.path.splitext(path)[1] else None
        if os.name == "nt":
            os.startfile(path)  # noqa
        else:
            subprocess.Popen(_open_path_cmd(path))
        return True
    except Exception as e:
        log("open path: %s" % e)
        return False


def _open_url(url):
    try:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(str(url or "")))
    except Exception as e:
        log("open url: %s" % e)


def _exec_collect(st, ctx):
    """真·平台采集:走本地引擎搜索抖音/小红书热门内容(需登录对应账号并保持在线),
    并下载 Top1 到素材库。复用 submit_local_task(与内容采集搜索/下载同一通道)。"""
    p = st.get("params") or {}
    kw = (p.get("keyword") or "热门").strip()
    plat = (p.get("platform") or "douyin").strip().lower()
    plat = "xhs" if plat in ("xhs", "小红书", "xiaohongshu") else "douyin"
    pname = "抖音" if plat == "douyin" else "小红书"
    try:
        topN = max(1, min(int(str(p.get("topN") or 5).strip() or 5), 20))
    except Exception:
        topN = 5
    ctx["topic"] = kw
    try:
        res = submit_local_task(plat + ".search",
                                {"query": kw, "keyword": kw, "num": topN, "content_type": "0", "platform": plat}, 150)
    except Exception as e:
        return "⚠️ 未真实采集(%s):需先启动本机客户端并登录%s账号;本次仅把主题『%s』带入后续步骤" % (str(e)[:40], pname, kw)
    rr = (res or {}).get("result") or {}
    items = res.get("items") or rr.get("items") or []
    items = [x for x in items if isinstance(x, dict)][:topN]
    if not items:
        return "⚠️ 未真实采集:需先启动本机客户端并登录%s账号并保持在线(当前离线/未登录);本次仅把主题『%s』带入后续步骤" % (pname, kw)
    ctx["collected"] = items
    ctx["media"] = [x.get("note_url") or x.get("work_url") or x.get("url")
                    for x in items[:3] if (x.get("note_url") or x.get("work_url") or x.get("url"))]
    # 真下载最热门那条到素材库
    dl = ""
    u = items[0].get("note_url") or items[0].get("work_url") or items[0].get("url") or ""
    if u:
        try:
            dres = submit_local_task(plat + ".download",
                                     {"url": u, "noteUrl": u, "save_choice": "all", "platform": plat}, 300)
            if (dres or {}).get("status") == "done":
                dl = ",已下载 Top1 到素材库"
        except Exception:
            pass
    titles = " / ".join((x.get("title") or x.get("desc") or "").strip()[:16] for x in items[:3])
    return "采集到 %d 条『%s』%s热门%s:%s…" % (len(items), kw, pname, dl, titles)


def _exec_text(st, ctx):
    txt = _workflow_generate_script(ctx, reason="")
    return "脚本已生成(%d字%s):%s…" % (len(txt), "·已引用知识库" if ctx.get("kb_used") else "", txt[:20])


def _workflow_script_too_short(script, min_chars=50):
    return len(str(script or "").strip()) < min_chars


def _workflow_generate_script(ctx, reason=""):
    topic = ctx.get("topic") or (ctx.get("wfname") or "短视频")
    prev = ctx.get("script") or ""
    kb = kb_context(topic)  # 先检索企业知识库,让脚本用真实产品卖点
    ctx["kb_used"] = bool(kb)
    coll = ctx.get("collected") or []
    trend = ""
    if coll:
        trend = "\n当前平台热门内容参考(借鉴角度/钩子,不要照抄):" + "；".join(
            (x.get("title") or x.get("desc") or "").strip()[:24] for x in coll[:3])
    sysmsg = "你是资深短视频编导,输出可直接拍摄/生成的中文口播脚本,分镜清晰、开场有钩子、结尾有行动号召,不要任何解释说明。"
    reason_line = ("上一步失败原因:%s。请不要提及技术错误,直接补成可用于生成视频的脚本。\n" % reason) if reason else ""
    prompt = (reason_line + "主题:%s。%s" % (topic, trend) + (("参考:" + prev[:300]) if prev else "")
              + "\n写一条约90-130字的口播短视频脚本,不少于50个中文字符。" + kb)
    txt = lk888_chat(prompt, system=sysmsg, model="gpt-5.4-xhigh", max_tokens=700, temperature=0.8).strip()
    if _workflow_script_too_short(txt):
        raise RuntimeError("兜底脚本生成失败:剧本内容不足50字")
    ctx["script"] = txt
    return txt


def _exec_vision(st, ctx):
    media = ctx.get("media") or []
    try:
        if media:
            out = lk888_vision("把这个素材拆解成详细分镜脚本(镜头/画面/台词/节奏/时长)。", media[:1])
        else:
            base = ctx.get("script") or ctx.get("topic") or "化妆品种草"
            out = lk888_chat("把下面内容扩写成详细分镜脚本(逐镜:画面+台词+时长):\n" + base,
                             model="gemini-3.1-pro-preview", max_tokens=900, temperature=0.6)
    except Exception as e:
        out = _workflow_generate_script(ctx, reason=str(e)[:120])
        return "视频理解失败,已兜底生成口播脚本(%d字):%s…" % (len(out), out[:20])
    if _workflow_script_too_short(out):
        out = _workflow_generate_script(ctx, reason="视频理解结果过短")
        return "视频理解结果过短,已兜底生成口播脚本(%d字):%s…" % (len(out), out[:20])
    ctx["script"] = ((ctx.get("script") or "") + "\n\n【分镜脚本】\n" + out).strip()
    return "已拆解详细分镜(%d字)" % len(out)


def _exec_image(st, ctx):
    topic = ctx.get("topic") or "短视频"
    ref = "wf_image:%d" % int(time.time() * 1000)
    okc, cerr = try_charge("workflow_image", ref)
    if not okc:
        raise RuntimeError(cerr or "扣费失败")
    try:
        b = lk888_image(topic + " 短视频封面,高级质感,竖版 9:16,主体突出,吸睛", size="1024x1024", model="gpt-image-2")
        path = os.path.join(_wf_out_dir(), "cover_%d.png" % int(time.time()))
        with open(path, "wb") as f:
            f.write(b)
        ctx.setdefault("artifacts", []).append(path)
        return "封面已生成:" + os.path.basename(path)
    except Exception:
        refund_cap("workflow_image", ref)
        raise


def _exec_video(st, ctx):
    p = st.get("params") or {}
    script = ctx.get("script") or (ctx.get("topic") or "化妆品种草短视频")
    if _workflow_script_too_short(script):
        script = _workflow_generate_script(ctx, reason="视频生成前剧本内容不足50字")
    if _workflow_script_too_short(script):
        raise RuntimeError("剧本内容不足50字,未调用视频生成")
    try:
        dur = int(str(p.get("duration") or 10).strip() or 10)
    except Exception:
        dur = 10
    aspect = p.get("aspect") or "9:16"
    try:
        cnt = min(max(int(str(p.get("count") or 1).strip() or 1), 1), 2)  # 省额度/省时:真跑最多2条
    except Exception:
        cnt = 1
    made = []
    for k in range(cnt):
        ref = "wf_video:%d_%d" % (int(time.time() * 1000), k)
        okc, cerr = try_charge("workflow_video", ref)
        if not okc:
            raise RuntimeError(cerr or "扣费失败")
        try:
            url = lk888_media_task(
                "vidu-jieshuoman",
                {"prompt": script[:400],
                 "params": {"script_name": "素材%d" % (k + 1), "script_content": script[:800],
                            "duration": dur, "resolution": "720p", "aspect_ratio": aspect,
                            "language": "zh", "enable_lipsync": True}},
                ["mp4", "mov"], tries=220)  # vidu-jieshuoman 解说漫出片慢,放宽超时(~18min)
            path = os.path.join(_wf_out_dir(), "video_%d_%d.mp4" % (int(time.time()), k + 1))
            _wf_download(url, path)
            made.append(path)
            ctx.setdefault("artifacts", []).append(path)
        except Exception:
            refund_cap("workflow_video", ref)
            raise
    ctx["videos"] = made
    return "已裂变 %d 条视频素材(vidu-jieshuoman):%s" % (len(made), ", ".join(os.path.basename(x) for x in made))


def _exec_tts(st, ctx):
    text = (ctx.get("script") or ctx.get("topic") or "大家好").replace("【分镜脚本】", "")[:180]
    ref = "wf_tts:%d" % int(time.time() * 1000)
    okc, cerr = try_charge("workflow_tts", ref)
    if not okc:
        raise RuntimeError(cerr or "扣费失败")
    try:
        url = lk888_tts(text)
        path = os.path.join(_wf_out_dir(), "voice_%d.mp3" % int(time.time()))
        _wf_download(url, path)
        ctx.setdefault("artifacts", []).append(path)
        return "配音已生成(doubao-tts-2.0):" + os.path.basename(path)
    except Exception:
        refund_cap("workflow_tts", ref)
        raise


def _exec_library(st, ctx):
    """把本次工作流产出(封面/视频/配音)真正登记进资产库(ASSETS),供混剪/商品图页复用。
    此前只回一句文案不入库,产物只躺在 wf_out 文件夹里 —— 现按扩展名判类逐个 add_asset。"""
    arts = ctx.get("artifacts") or []
    label = ctx.get("topic") or ctx.get("wfname") or "工作流产物"
    n = 0
    for p in arts:
        if not (p and os.path.isfile(p)):
            continue
        ext = os.path.splitext(p)[1].lower()
        kind = ("video" if ext in (".mp4", ".mov", ".webm", ".m4v")
                else "audio" if ext in (".mp3", ".wav", ".m4a")
                else "image")
        try:
            if add_asset(p, kind=kind, prompt=label, source="自动化工作流"):
                n += 1
        except Exception:
            pass
    return "已入素材库 %d/%d 个素材(可在『资产库』及混剪/商品图页复用)" % (n, len(arts))


def _do_publish(video, caption, account_id, platform, dry=False):
    """真发布:上传素材 → publish.run(本机浏览器执行)。返回 (ok, err)。在工作流后台线程里同步跑。"""
    try:
        _code, j = upload_materials([video], caption or "素材")
        j = j or {}
        mid = j.get("id") or (j.get("material") or {}).get("id") or j.get("materialId")
        if not mid:
            return False, "上传素材到素材库失败"
        payload = {"materialId": mid, "centralMaterialId": mid, "accountId": account_id,
                   "platform": platform, "dryRun": bool(dry)}
        res = submit_local_task("publish.run", payload, 900)
        rr = (res or {}).get("result") or {}
        ok = _publish_result_ok(res, dry=dry)
        if ok:
            return True, ""
        rr_err = rr.get("error") if isinstance(rr, dict) else rr
        return False, str((res or {}).get("error") or rr_err or "发布失败(账号未登录/引擎离线?)")[:120]
    except Exception as e:
        return False, str(e)[:120]


def _publish_result_ok(res, dry=False):
    """统一判断 publish.run 是否真的完成,避免 status=done 但未发布也被当成成功。"""
    rr = (res or {}).get("result") or {}
    if (res or {}).get("status") != "done" or not isinstance(rr, dict):
        return False
    if dry:
        return bool(rr.get("filled") or rr.get("ok"))
    return bool(rr.get("published"))


def _publish_result_message(res):
    rr = (res or {}).get("result") or {}
    rr_err = rr.get("error") if isinstance(rr, dict) else rr
    if _publish_result_ok(res):
        return "发布成功。"
    if isinstance(rr, dict) and rr.get("dryRun") and rr.get("filled") and not rr.get("published"):
        return "试发完成，未真实发布。"
    if isinstance(rr, dict) and rr_err == "security_verify_required":
        return "抖音要求安全验证，请在打开的浏览器中完成验证后重试。"
    if isinstance(rr, dict) and rr_err == "security_appeal_required":
        return "抖音要求账号安全处理，请在打开的浏览器中处理后重试。"
    if isinstance(rr, dict) and rr.get("filled") and not rr.get("published"):
        return "真实发布未完成:" + str((res or {}).get("error") or rr_err or "publish_unconfirmed")
    return "发布失败:" + str((res or {}).get("error") or rr_err or "(检查账号是否已登录/就绪)")


def _exec_publish(st, ctx):
    """默认入『待发布队列』等人工确认;若该工作流开启了『定时自动发送视频』且配了账号,则直接真发布
    (绕过人工确认、有封号风险,由用户在工作流上显式开启)。"""
    p = st.get("params") or {}
    arts = ctx.get("artifacts") or []
    vids = [a for a in arts if str(a).lower().endswith((".mp4", ".mov"))]
    auds = [a for a in arts if str(a).lower().endswith((".mp3", ".wav", ".m4a"))]
    caption = (ctx.get("script") or ctx.get("topic") or "").replace("【分镜脚本】", "").strip()[:140]
    plat = (ctx.get("publishPlatform") or p.get("platform") or "douyin").strip().lower()
    plat = "xhs" if plat in ("xhs", "小红书", "xiaohongshu") else "douyin"
    pname = "抖音" if plat == "douyin" else "小红书"
    account = ctx.get("publishAccountId") or p.get("account") or ""
    if not vids:
        return "未生成视频,未入发布队列(本次无可发布素材)"
    ctx["_publish_done"] = True
    entry = {
        "id": "pp_%s" % uuid.uuid4().hex,
        "wfName": ctx.get("wfname") or "",
        "video": vids[0],
        "audio": auds[0] if auds else "",
        "caption": caption,
        "account": account,
        "platform": plat,
        "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "待确认",
    }
    if ctx.get("autoPublish") and account:
        ok, err = _do_publish(vids[0], caption, account, plat)
        entry["status"] = "已自动发布 ✓" if ok else ("自动发布失败:" + err)
        add_pending(entry)
        return ("✅ 已自动发布到账号「%s」· %s" % (account, pname)) if ok else \
               ("⚠️ 自动发布失败:%s(已入待发布队列,可手动重试)" % err)
    if ctx.get("autoPublish") and not account:
        entry["status"] = "待确认(自动发送未配置账号)"
        add_pending(entry)
        return "已入『待发布队列』(自动发送已开启,但未配置发布账号;请填账号ID后再定时发送)"
    add_pending(entry)
    return "已入『待发布队列』(账号「%s」· %s)—— 未开自动发布则需你人工确认才真发。" % (account or "未指定", pname)


WF_EXECUTORS = {
    "collect": _exec_collect, "text": _exec_text, "vision": _exec_vision,
    "image": _exec_image, "video": _exec_video, "tts": _exec_tts,
    "library": _exec_library, "publish": _exec_publish,
}


def run_workflow(wf, emit):
    """顺序执行工作流各步。emit(i, status, summary) 回调更新 UI(status: running/done/failed)。
    返回 (ctx, all_ok)。步骤失败不中断,继续跑后续以展示尽量多的真实产物。"""
    return _run_workflow_impl(wf, emit, scheduled=False)


def run_scheduled_workflow(wf, emit):
    """定时执行工作流。若开启了自动发送且流程没显式 publish 步骤,生成视频后自动补一次发布/入队。"""
    return _run_workflow_impl(wf, emit, scheduled=True)


def _run_workflow_impl(wf, emit, scheduled=False):
    ctx = {"wfname": wf.get("name") or "", "topic": "", "script": "", "media": [], "artifacts": []}
    _sch = wf.get("schedule") or {}
    ctx["autoPublish"] = bool(_sch.get("autoPublish"))
    ctx["publishAccountId"] = _sch.get("publishAccountId") or ""
    ctx["publishPlatform"] = _sch.get("publishPlatform") or ""
    ctx["scheduledRun"] = bool(scheduled)
    all_ok = True
    for i, st in enumerate(wf.get("steps") or []):
        emit(i, "running", "")
        fn = WF_EXECUTORS.get(st.get("cap"))
        try:
            summary = fn(st, ctx) if fn else "跳过(未支持的步骤)"
            emit(i, "done", summary)
        except Exception as e:
            all_ok = False
            emit(i, "failed", str(e)[:140])
    if scheduled and not ctx.get("_publish_done"):
        arts = ctx.get("artifacts") or []
        has_video = any(str(a).lower().endswith((".mp4", ".mov")) for a in arts)
        if has_video:
            try:
                summary = _exec_publish({"cap": "publish", "params": {}}, ctx)
                ctx["publishSummary"] = summary
                if ctx.get("autoPublish"):
                    ctx["autoPublishSummary"] = summary
                    log("⏰ 定时自动发送视频:" + summary)
                else:
                    ctx["queuePublishSummary"] = summary
                    log("⏰ 定时视频已入待发布队列:" + summary)
            except Exception as e:
                all_ok = False
                ctx["publishSummary"] = "定时发布处理失败:" + str(e)[:140]
                log("⏰ 定时发布处理失败:%s" % str(e)[:140])
    return ctx, all_ok


class ChatBubble(QtWidgets.QFrame):
    def __init__(self, text, role):
        super().__init__()
        me = role == "user"
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lab = QtWidgets.QLabel(text)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        if me:
            lab.setStyleSheet("color:#ffffff;font-size:13px;background:transparent;")
            self.setStyleSheet("QFrame{background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 %s, stop:1 %s);"
                               "border-radius:14px;}" % (TK["accent"], TK["accent2"]))
        else:
            aibg = "#eef1f8" if is_light() else "rgba(255,255,255,0.05)"
            aibd = "#dfe4ee" if is_light() else "rgba(255,255,255,0.08)"
            lab.setStyleSheet("color:%s;font-size:13px;background:transparent;" % TK["text"])
            self.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:14px;}" % (aibg, aibd))
        lay.addWidget(lab)


class AgentChatPage(BasePage):
    """对话式工作流助手:跟总控 LLM(gpt-5.4)对话,自然语言描述需求即可生成自动化工作流。"""

    def __init__(self):
        super().__init__()
        acts = QtWidgets.QLabel("总控:gpt-5.4")
        acts.setObjectName("sub")
        self.v.addWidget(make_header("工作流助手", "跟 AI 对话,描述需求即可自动编排一条视频生产 + 定时发布流水线", [acts]))
        self.history = []  # [{role, content}]
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;}")
        host = QtWidgets.QWidget()
        host.setStyleSheet("background:transparent;")
        self.msgs = QtWidgets.QVBoxLayout(host)
        self.msgs.setContentsMargins(2, 2, 12, 2)
        self.msgs.setSpacing(10)
        self.msgs.addStretch()
        self.scroll.setWidget(host)
        self.v.addWidget(self.scroll, 1)
        self._bubble("你好!我是工作流助手\n\n把你想要的自动化告诉我,比如:\n「从抖音下载最热门的化妆品宣传视频,拆成详细脚本,裂变成多条视频素材存进素材库,每天定时发到我的抖音账号」\n\n我会自动帮你编排成一条可视化流水线。", "ai")
        row = QtWidgets.QHBoxLayout()
        self.inp = QtWidgets.QLineEdit()
        self.inp.setPlaceholderText("描述你想要的自动化工作流…")
        self.inp.returnPressed.connect(self.send)
        self.btn = QtWidgets.QPushButton("发送")
        self.btn.setObjectName("primary")
        self.btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn.clicked.connect(self.send)
        row.addWidget(self.inp, 1)
        row.addWidget(self.btn)
        self.v.addLayout(row)
        BRIDGE.payload.connect(self._on)

    def _bubble(self, text, role):
        b = ChatBubble(text, role)
        wrap = QtWidgets.QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        holder = QtWidgets.QWidget()
        holder.setStyleSheet("background:transparent;")
        holder.setLayout(wrap)
        b.setMaximumWidth(560)
        if role == "user":
            wrap.addStretch()
            wrap.addWidget(b)
        else:
            wrap.addWidget(b)
            wrap.addStretch()
        self.msgs.insertWidget(self.msgs.count() - 1, holder)
        QtCore.QTimer.singleShot(50, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))
        return b

    def _wf_card(self, wf):
        card = HoverCard("card", rest_blur=16, hover_blur=30, rest_dy=7, hover_dy=14, alpha=80)
        inner = QtWidgets.QVBoxLayout(card)
        inner.setContentsMargins(16, 13, 16, 14)
        inner.setSpacing(8)
        top = QtWidgets.QHBoxLayout()
        ic = QtWidgets.QLabel()
        ic.setFixedSize(30, 30)
        ic.setAlignment(QtCore.Qt.AlignCenter)
        ic.setStyleSheet("background:%s;border-radius:8px;" % _rgba("#7c6dff", 0.18))
        ic.setPixmap(_draw_icon("chart", 17, "#7c6dff"))
        t = QtWidgets.QLabel("已生成工作流 · %s" % (wf.get("name") or "未命名"))
        t.setStyleSheet("font-size:14px;font-weight:800;color:#ffffff;background:transparent;")
        top.addWidget(ic)
        top.addWidget(t, 1)
        inner.addLayout(top)
        d = QtWidgets.QLabel("%s  ·  共 %d 个环节" % (wf.get("desc") or "", len(wf.get("steps") or [])))
        d.setStyleSheet("color:#8b93a3;font-size:12px;background:transparent;")
        d.setWordWrap(True)
        inner.addWidget(d)
        chips = QtWidgets.QHBoxLayout()
        chips.setSpacing(6)
        for st in (wf.get("steps") or [])[:6]:
            nm = WF_CAPS.get(st.get("cap"), (st.get("cap") or "步骤",))[0]
            chips.addWidget(pill(nm))
        chips.addStretch()
        inner.addLayout(chips)
        go = QtWidgets.QPushButton("在『自动化工作流』中查看整套流程  →")
        go.setObjectName("primary")
        go.setCursor(QtCore.Qt.PointingHandCursor)
        go.clicked.connect(lambda: BRIDGE.payload.emit("goto_nav", "🔀 自动化工作流"))
        inner.addWidget(go)
        holder = QtWidgets.QWidget()
        holder.setStyleSheet("background:transparent;")
        hl = QtWidgets.QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        card.setMaximumWidth(560)
        hl.addWidget(card)
        hl.addStretch()
        self.msgs.insertWidget(self.msgs.count() - 1, holder)
        QtCore.QTimer.singleShot(60, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def send(self):
        text = self.inp.text().strip()
        if not text:
            return
        self.inp.clear()
        self._bubble(text, "user")
        self.history.append({"role": "user", "content": text})
        self.btn.setEnabled(False)
        thinking = self._bubble("正在思考并编排…", "ai")
        convo = self.history[-8:]

        def work():
            prompt = "\n".join(("用户:" if m["role"] == "user" else "助手:") + m["content"] for m in convo)
            prompt += "\n\n请按系统指示回应;若可成流水线则在末尾附工作流 JSON。"
            try:
                reply = lk888_chat(prompt, system=WF_ORCH_SYSTEM, model="gpt-5.4", max_tokens=1500, temperature=0.6)
                BRIDGE.payload.emit("wf_reply", {"ok": True, "reply": reply})
            except Exception as e:
                BRIDGE.payload.emit("wf_reply", {"ok": False, "error": str(e)[:160]})
        run_bg(work)
        self._thinking = thinking

    def _on(self, tag, d):
        if tag != "wf_reply":
            return
        self.btn.setEnabled(True)
        try:
            if getattr(self, "_thinking", None) is not None:
                self._thinking.parentWidget().deleteLater()
                self._thinking = None
        except Exception:
            pass
        if not (d or {}).get("ok"):
            self._bubble("出错了:" + str((d or {}).get("error") or ""), "ai")
            return
        reply = (d or {}).get("reply") or ""
        wf, display = extract_workflow(reply)
        self.history.append({"role": "assistant", "content": reply})
        self._bubble(display, "ai")
        if wf:
            import time as _t
            wf.setdefault("id", "wf-" + str(int(_t.time())))
            wf.setdefault("enabled", False)
            WORKFLOWS.insert(0, wf)
            save_workflows()
            self._wf_card(wf)
            BRIDGE.payload.emit("wf_created", wf)


class WorkflowPage(BasePage):
    """自动化工作流:查看对话生成的整套流程,显示每个链路的模型与动作,可改参数、暂停/启用。"""

    def __init__(self):
        super().__init__()
        self.b_open = QtWidgets.QPushButton("打开素材库文件夹")
        self.b_open.setObjectName("ghost")
        self.b_open.clicked.connect(lambda: _open_path(_wf_out_dir()))
        self.b_ref = QtWidgets.QPushButton("刷新")
        self.b_ref.setObjectName("ghost")
        self.b_ref.clicked.connect(self._build_list)
        self.v.addWidget(make_header("自动化工作流", "对话生成的流水线在这里查看:每个链路用什么模型、在做什么,可随时改参数、暂停/启用", [self.b_open, self.b_ref]))
        self.v.addWidget(prereq_banner("含采集/发布的工作流需:本机客户端在线 + 平台账号已登录;否则采集/发布步骤只会占位、不真实执行(步骤结果会标注)。"))
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(14)
        # 左:工作流列表
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(8)
        lt = QtWidgets.QLabel("我的工作流")
        lt.setStyleSheet("color:%s;font-size:12px;font-weight:700;background:transparent;" % TK["sub"])
        left.addWidget(lt)
        self.listw = QtWidgets.QListWidget()
        self.listw.setFixedWidth(240)
        _lwbg = "#ffffff" if is_light() else "#10131f"
        _lwbd = TK["cardBorder"] if is_light() else "#222a3a"
        _lwit = TK["text"] if is_light() else "#cfd3de"
        _lwhv = "rgba(99,102,241,0.08)" if is_light() else "rgba(255,255,255,0.05)"
        self.listw.setStyleSheet(
            "QListWidget{background:%s;border:1px solid %s;border-radius:12px;padding:6px;outline:0;}"
            "QListWidget::item{padding:9px 10px;border-radius:8px;margin:1px 0;color:%s;}"
            "QListWidget::item:selected{background:rgba(124,109,255,0.22);color:%s;}"
            "QListWidget::item:hover{background:%s;}"
            % (_lwbg, _lwbd, _lwit, ("#3730a3" if is_light() else "#ffffff"), _lwhv))
        self.listw.currentRowChanged.connect(self._select)
        left.addWidget(self.listw, 1)
        body.addLayout(left)
        # 右:流水线详情(滚动)
        self.detail = QtWidgets.QScrollArea()
        self.detail.setWidgetResizable(True)
        self.detail.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.detail.setStyleSheet("QScrollArea{background:transparent;}")
        body.addWidget(self.detail, 1)
        self.v.addLayout(body, 1)
        BRIDGE.payload.connect(self._on)
        self._build_list()

    def on_show(self):
        self._build_list()

    def _on(self, tag, d):
        if tag == "wf_created":
            self._build_list()
        elif tag == "wf_run":
            self._on_run(d)

    def _run(self):
        wf = getattr(self, "_current_wf", None)
        if not wf:
            return
        self._runbtn.setEnabled(False)
        self._runbtn.setText("运行中…")
        try:
            self._logbox.setPlainText("")
        except Exception:
            pass
        self._log("开始运行:%s(共 %d 步,真实调用各模型)" % (wf.get("name"), len(wf.get("steps") or [])))
        wf_ref = wf

        def emit(i, status, summary):
            BRIDGE.payload.emit("wf_run", {"i": i, "status": status, "summary": summary})

        def work():
            try:
                ctx, ok = run_workflow(wf_ref, emit)
                BRIDGE.payload.emit("wf_run", {"done": True, "ok": ok, "artifacts": ctx.get("artifacts") or []})
            except Exception as e:
                BRIDGE.payload.emit("wf_run", {"done": True, "ok": False, "error": str(e)[:160]})
        run_bg(work)

    def _log(self, msg):
        try:
            self._logbox.appendPlainText(msg)
        except Exception:
            pass

    def _on_run(self, d):
        d = d or {}
        if d.get("done"):
            try:
                self._runbtn.setEnabled(True)
                self._runbtn.setText("运行整条流程")
            except Exception:
                pass
            if d.get("error"):
                self._log("运行出错:" + d["error"])
            else:
                arts = d.get("artifacts") or []
                self._log(("全流程完成" if d.get("ok") else "流程结束(部分步骤失败)") + ",产物 %d 个,已存到 %s" % (len(arts), _wf_out_dir()))
                if arts:
                    try:
                        if getattr(self, "_current_wf", None) is not None:
                            self._current_wf["_artifacts"] = arts
                            save_workflows()
                        self._show_artifacts(arts)
                    except Exception as e:
                        log("show artifacts: %s" % e)
            return
        i = d.get("i")
        status = d.get("status")
        summary = d.get("summary") or ""
        lab = (getattr(self, "_stat", {}) or {}).get(i)
        colors = {"running": ("#f59e0b", "运行中…"), "done": ("#22c55e", "完成"), "failed": ("#ef4444", "失败")}
        col, txt = colors.get(status, ("#6b7488", status or "?"))
        if lab is not None:
            lab.setText(txt)
            lab.setStyleSheet("color:%s;font-size:11px;background:%s;border-radius:8px;padding:3px 9px;" % (col, _rgba(col, 0.16)))
        if status == "running":
            self._log("第 %d 步 运行中…" % ((i or 0) + 1))
        elif summary:
            self._log("  %s第 %d 步:%s" % ("" if status == "done" else "[失败] ", (i or 0) + 1, summary))

    def _build_list(self):
        self.listw.clear()
        for wf in WORKFLOWS:
            it = QtWidgets.QListWidgetItem(("● " if wf.get("enabled") else "○ ") + (wf.get("name") or "未命名"))
            it.setForeground(QtGui.QColor("#22c55e" if wf.get("enabled") else "#8b93a3"))
            self.listw.addItem(it)
        if WORKFLOWS:
            self.listw.setCurrentRow(0)
        else:
            self._show_empty()

    def _show_empty(self):
        w = QtWidgets.QLabel("还没有工作流。去『工作流助手』用对话创建一个吧")
        w.setAlignment(QtCore.Qt.AlignCenter)
        w.setStyleSheet("color:#6b7488;font-size:14px;background:transparent;")
        self.detail.setWidget(w)

    def _select(self, row):
        if row < 0 or row >= len(WORKFLOWS):
            return
        self._render(WORKFLOWS[row])

    def _render(self, wf):
        host = QtWidgets.QWidget()
        host.setStyleSheet("background:transparent;")
        v = QtWidgets.QVBoxLayout(host)
        v.setContentsMargins(4, 2, 12, 8)
        v.setSpacing(12)
        self._current_wf = wf
        self._stat = {}
        # 头:名称 + 启用开关 + 计划
        head = HoverCard("card", rest_blur=14, hover_blur=24, rest_dy=6, hover_dy=11, alpha=70)
        hv = QtWidgets.QVBoxLayout(head)
        hv.setContentsMargins(18, 15, 18, 15)
        hrow = QtWidgets.QHBoxLayout()
        nm = QtWidgets.QLabel(wf.get("name") or "未命名工作流")
        nm.setStyleSheet("font-size:18px;font-weight:800;color:#ffffff;background:transparent;")
        hrow.addWidget(nm, 1)
        state = pill("已启用" if wf.get("enabled") else "已暂停")
        hrow.addWidget(state)
        toggle = QtWidgets.QPushButton("暂停" if wf.get("enabled") else "启用")
        toggle.setObjectName("primary" if not wf.get("enabled") else "ghost")
        toggle.setCursor(QtCore.Qt.PointingHandCursor)

        def _toggle():
            wf["enabled"] = not wf.get("enabled")
            save_workflows()
            self._build_list()
        toggle.clicked.connect(lambda: _toggle())
        hrow.addWidget(toggle)
        runb = QtWidgets.QPushButton("运行整条流程")
        runb.setObjectName("primary")
        runb.setCursor(QtCore.Qt.PointingHandCursor)
        runb.clicked.connect(self._run)
        self._runbtn = runb
        hrow.addWidget(runb)
        hv.addLayout(hrow)
        desc = QtWidgets.QLabel(wf.get("desc") or "")
        desc.setStyleSheet("color:#8b93a3;font-size:12px;background:transparent;")
        desc.setWordWrap(True)
        hv.addWidget(desc)
        sched = wf.get("schedule") or {}
        if sched:
            ap_state = "自动发送:开(%s)" % (sched.get("publishAccountId") or "未填账号") if sched.get("autoPublish") else "自动发送:关"
            sc = QtWidgets.QLabel("计划:%s  ·  每次 %s 条  ·  %s" % (sched.get("text") or "手动", sched.get("perRun") or "-", ap_state))
            sc.setStyleSheet("color:#a5adbb;font-size:12px;background:transparent;")
            hv.addWidget(sc)
        # 定时自动发送(默认关;开启=到点生成视频后直接对外发,失败入待发布队列)
        aprow = QtWidgets.QHBoxLayout()
        aprow.setSpacing(8)
        ap = QtWidgets.QCheckBox("定时自动发送视频")
        ap.setChecked(bool(sched.get("autoPublish")))
        apacc = QtWidgets.QLineEdit(sched.get("publishAccountId") or "")
        apacc.setPlaceholderText("发布账号ID(在『账号矩阵』查看)")
        apacc.setFixedWidth(200)
        applat = QtWidgets.QComboBox()
        applat.addItems(["抖音", "小红书"])
        applat.setCurrentIndex(1 if sched.get("publishPlatform") in ("xhs", "小红书", "xiaohongshu") else 0)

        def _save_ap(*a):
            sc2 = wf.setdefault("schedule", {})
            sc2["autoPublish"] = ap.isChecked()
            sc2["publishAccountId"] = apacc.text().strip()
            sc2["publishPlatform"] = "xhs" if applat.currentIndex() == 1 else "douyin"
            save_workflows()
        ap.toggled.connect(_save_ap)
        apacc.editingFinished.connect(_save_ap)
        applat.currentIndexChanged.connect(_save_ap)
        aprow.addWidget(ap)
        aprow.addWidget(apacc)
        aprow.addWidget(applat)
        apw = QtWidgets.QLabel("开启后到点生成视频会直接公开发布第一条;失败会入待发布队列")
        apw.setStyleSheet("color:#e6b84a;font-size:11px;background:transparent;")
        aprow.addWidget(apw)
        aprow.addStretch()
        hv.addLayout(aprow)
        # 用到的模型
        used = []
        for st in wf.get("steps") or []:
            mk = WF_CAPS.get(st.get("cap"), (None, None, None, None))[3]
            if mk and mk not in used:
                used.append(mk)
        if used:
            mrow = QtWidgets.QHBoxLayout()
            mrow.setSpacing(6)
            ml = QtWidgets.QLabel("使用模型:")
            ml.setStyleSheet("color:#8b93a3;font-size:12px;background:transparent;")
            mrow.addWidget(ml)
            for mk in used:
                name, mid, col = WF_MODELS[mk]
                chip = QtWidgets.QLabel("%s · %s" % (name, mid))
                chip.setStyleSheet("background:%s;color:%s;border:1px solid %s;border-radius:9px;padding:3px 9px;font-size:11px;"
                                   % (_rgba(col, 0.15), col, _rgba(col, 0.45)))
                mrow.addWidget(chip)
            mrow.addStretch()
            hv.addLayout(mrow)
        v.addWidget(head)
        # 步骤链路
        for i, st in enumerate(wf.get("steps") or []):
            v.addWidget(self._step_card(i + 1, st))
            if i < len(wf.get("steps") or []) - 1:
                arr = QtWidgets.QLabel("↓")
                arr.setAlignment(QtCore.Qt.AlignCenter)
                arr.setStyleSheet("color:#6366f1;font-size:20px;font-weight:800;background:transparent;")
                v.addWidget(arr)
        loglab = QtWidgets.QLabel("运行日志")
        loglab.setStyleSheet("color:#8b93a3;font-size:12px;font-weight:700;background:transparent;padding-top:6px;")
        v.addWidget(loglab)
        self._logbox = QtWidgets.QPlainTextEdit()
        self._logbox.setReadOnly(True)
        self._logbox.setFixedHeight(140)
        self._logbox.setPlaceholderText("点『运行整条流程』后,每一步的实时进度会显示在这里…")
        v.addWidget(self._logbox)
        artlab = QtWidgets.QLabel("产物预览")
        artlab.setStyleSheet("color:#8b93a3;font-size:12px;font-weight:700;background:transparent;padding-top:6px;")
        v.addWidget(artlab)
        self._artwrap = QtWidgets.QVBoxLayout()
        self._artwrap.setSpacing(8)
        artc = QtWidgets.QWidget()
        artc.setStyleSheet("background:transparent;")
        artc.setLayout(self._artwrap)
        v.addWidget(artc)
        self._show_artifacts(wf.get("_artifacts") or [])
        v.addStretch()
        self.detail.setWidget(host)
        wire_animations(host)

    def _show_artifacts(self, paths):
        if not hasattr(self, "_artwrap"):
            return
        _clear_layout(self._artwrap)
        if not paths:
            hint = QtWidgets.QLabel("运行后,生成的视频/配音/封面会显示在这里(视频可直接播放)。")
            hint.setStyleSheet("color:#6b7488;font-size:12px;background:transparent;")
            self._artwrap.addWidget(hint)
            return
        # 不内嵌视频播放器:它会在启动/切页时自动播放出声、且加载大视频会卡死 UI。
        # 改成每个产物一行 + 「打开/播放」按钮,点了用系统默认播放器打开。
        for p in paths:
            low = str(p).lower()
            kind = ("视频" if low.endswith((".mp4", ".mov", ".webm")) else
                    ("配音" if low.endswith((".mp3", ".wav", ".ogg")) else "图片"))
            self._artwrap.addWidget(self._art_row(p, kind))

    def _art_row(self, path, kind):
        row = QtWidgets.QFrame()
        row.setObjectName("card")
        row.setMaximumWidth(460)
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(13, 9, 13, 9)
        lab = QtWidgets.QLabel("%s · %s" % (kind, os.path.basename(path)))
        lab.setStyleSheet("color:#e8eaf0;font-size:12px;background:transparent;")
        b = QtWidgets.QPushButton("播放" if kind in ("视频", "配音") else "打开")
        b.setObjectName("ghost")
        b.setCursor(QtCore.Qt.PointingHandCursor)
        b.clicked.connect(lambda _=False, pp=path: _open_path(pp))
        h.addWidget(lab, 1)
        h.addWidget(b)
        return row

    def _step_card(self, idx, st):
        cap = st.get("cap") or "step"
        cname, ckind, ccol, mk = WF_CAPS.get(cap, (cap, "dot", "#6366f1", None))
        card = HoverCard("card", rest_blur=14, hover_blur=26, rest_dy=6, hover_dy=12, alpha=70)
        outer = QtWidgets.QHBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QtWidgets.QFrame()
        bar.setFixedWidth(4)
        bar.setStyleSheet("background:%s;border-top-left-radius:14px;border-bottom-left-radius:14px;" % ccol)
        outer.addWidget(bar)
        inner = QtWidgets.QWidget()
        inner.setStyleSheet("background:transparent;")
        iv = QtWidgets.QVBoxLayout(inner)
        iv.setContentsMargins(16, 13, 16, 14)
        iv.setSpacing(9)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(11)
        chip = QtWidgets.QLabel()
        chip.setFixedSize(34, 34)
        chip.setAlignment(QtCore.Qt.AlignCenter)
        chip.setStyleSheet("background:%s;border:1px solid %s;border-radius:10px;" % (_rgba(ccol, 0.16), _rgba(ccol, 0.42)))
        chip.setPixmap(_draw_icon(ckind, 18, ccol))
        tcol = QtWidgets.QVBoxLayout()
        tcol.setSpacing(1)
        tt = QtWidgets.QLabel("%d. %s" % (idx, st.get("title") or cname))
        tt.setStyleSheet("font-size:14px;font-weight:800;color:#ffffff;background:transparent;")
        sub = QtWidgets.QLabel(cname)
        sub.setStyleSheet("color:%s;font-size:11px;background:transparent;" % ccol)
        tcol.addWidget(tt)
        tcol.addWidget(sub)
        top.addWidget(chip)
        top.addLayout(tcol, 1)
        if mk:
            name, mid, col = WF_MODELS[mk]
            mbadge = QtWidgets.QLabel(mid)
            mbadge.setStyleSheet("background:%s;color:%s;border:1px solid %s;border-radius:9px;padding:4px 10px;font-size:11px;font-weight:700;"
                                 % (_rgba(col, 0.15), col, _rgba(col, 0.45)))
            top.addWidget(mbadge)
        statlab = QtWidgets.QLabel("待运行")
        statlab.setStyleSheet("color:#6b7488;font-size:11px;background:rgba(255,255,255,0.05);border-radius:8px;padding:3px 9px;")
        top.addWidget(statlab)
        if getattr(self, "_stat", None) is not None:
            self._stat[idx - 1] = statlab
        iv.addLayout(top)
        dsc = QtWidgets.QLabel(st.get("desc") or "")
        dsc.setStyleSheet("color:#a5adbb;font-size:12px;background:transparent;")
        dsc.setWordWrap(True)
        iv.addWidget(dsc)
        params = st.get("params") or {}
        if params:
            grid = QtWidgets.QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(7)
            for r, (k, val) in enumerate(list(params.items())[:8]):
                kl = QtWidgets.QLabel(str(k))
                kl.setStyleSheet("color:#8b93a3;font-size:11px;background:transparent;")
                ed = QtWidgets.QLineEdit(str(val))
                ed.setMinimumWidth(160)
                ed.editingFinished.connect(lambda p=params, key=k, e=ed: (p.__setitem__(key, e.text()), save_workflows()))
                grid.addWidget(kl, r, 0)
                grid.addWidget(ed, r, 1)
            grid.setColumnStretch(1, 1)
            iv.addLayout(grid)
        outer.addWidget(inner, 1)
        return card


class KnowledgeBasePage(BasePage):
    """企业知识库:沉淀产品知识 / FAQ / 话术,自动分块入库,供 AI 生成与销售引用;支持知识库问答检索。"""

    TYPES = ["产品知识", "常见问答FAQ", "价格政策", "售后规则", "销售话术", "品牌资料"]

    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("企业知识库", "沉淀产品知识 / FAQ / 话术,自动分块入库,供 AI 生成与销售自动引用;可直接问知识库"))
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(14)
        # 左:添加知识
        addp = Panel("添加知识", "手动录入或上传 txt/md/csv 文件,自动分块入库")
        trow = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLineEdit()
        self.title.setPlaceholderText("资料标题,如:粉底液卖点手册")
        self.ktype = QtWidgets.QComboBox()
        self.ktype.addItems(self.TYPES)
        trow.addWidget(self.title, 1)
        trow.addWidget(self.ktype)
        addp.body.addLayout(trow)
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setPlaceholderText("粘贴产品知识 / 常见问答 / 销售话术正文…")
        self.text.setMinimumHeight(150)
        addp.body.addWidget(self.text)
        brow = QtWidgets.QHBoxLayout()
        self.b_up = QtWidgets.QPushButton("上传文件")
        self.b_up.setObjectName("ghost")
        self.b_up.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_up.clicked.connect(self.upload)
        brow.addWidget(self.b_up)
        brow.addStretch()
        self.b_add = QtWidgets.QPushButton("添加到知识库")
        self.b_add.setObjectName("primary")
        self.b_add.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_add.clicked.connect(self.add)
        brow.addWidget(self.b_add)
        addp.body.addLayout(brow)
        top.addWidget(addp, 1)
        # 右:问知识库
        askp = Panel("问知识库", "输入问题,AI 依据已入库资料作答(有依据、不编造,资料没有会明说)")
        self.q = QtWidgets.QLineEdit()
        self.q.setPlaceholderText("例如:粉底液适合什么肤质?退换货政策?")
        self.q.returnPressed.connect(self.ask)
        qb = QtWidgets.QPushButton("问答")
        qb.setObjectName("primary")
        qb.setCursor(QtCore.Qt.PointingHandCursor)
        qb.clicked.connect(self.ask)
        qrow = QtWidgets.QHBoxLayout()
        qrow.addWidget(self.q, 1)
        qrow.addWidget(qb)
        askp.body.addLayout(qrow)
        self.answer = QtWidgets.QPlainTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setMinimumHeight(150)
        self.answer.setPlaceholderText("AI 依据知识库生成的答案会显示在这里…")
        askp.body.addWidget(self.answer)
        top.addWidget(askp, 1)
        self.v.addLayout(top)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("sub")
        self.v.addWidget(self.status)
        lt = QtWidgets.QLabel("知识库文档")
        lt.setStyleSheet("color:%s;font-size:12px;font-weight:700;background:transparent;" % TK["sub"])
        self.v.addWidget(lt)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["标题", "类型", "分块", "字数", "操作"])
        style_table(self.table)
        self.v.addWidget(self.table, 1)
        BRIDGE.payload.connect(self._on)
        wire_animations(self)

    def on_show(self):
        self.load()

    def load(self):
        def work():
            _c, j = api("GET", "/api/kb/list")
            arr = j if isinstance(j, list) else ((j or {}).get("value") or (j or {}).get("docs") or [])
            BRIDGE.payload.emit("kb_list", arr if isinstance(arr, list) else [])
        run_bg(work)

    def add(self):
        t = self.text.toPlainText().strip()
        if not t:
            self.status.setText("请先填写正文")
            return
        title = self.title.text().strip() or "手工资料"
        ktype = self.ktype.currentText()
        self.b_add.setEnabled(False)
        self.status.setText("添加中…")

        def work():
            _c, j = api("POST", "/api/kb/add", {"title": title, "type": ktype, "text": t})
            BRIDGE.payload.emit("kb_add", {"ok": isinstance(j, dict) and j.get("ok"), "resp": j or {}})
        run_bg(work)

    def upload(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "选择文档(txt/md/csv/json…)", "", "文本文档 (*.txt *.md *.csv *.json *.log);;所有文件 (*.*)")
        if not paths:
            return
        title = self.title.text().strip()
        ktype = self.ktype.currentText()
        self.b_up.setEnabled(False)
        self.status.setText("上传解析中…")

        def work():
            _c, j = kb_upload_files(paths, title, ktype)
            BRIDGE.payload.emit("kb_add", {"ok": isinstance(j, dict) and j.get("ok"), "resp": j or {}})
        run_bg(work)

    def ask(self):
        q = self.q.text().strip()
        if not q:
            return
        self.answer.setPlainText("检索知识库 + AI 作答中…")

        def work():
            # RAG:中心服负责检索(它有知识库数据),客户端拿到片段后用 lk888 生成有依据的自然语言答案。
            try:
                _c, j = api("POST", "/api/kb/ask", {"query": q, "limit": 6})
                srcs = ((j or {}).get("sources") if isinstance(j, dict) else None) or []
                if not srcs:
                    BRIDGE.payload.emit("kb_ask", {"answer": "知识库里暂无相关资料。可先在左侧添加/上传产品知识、FAQ、话术后再问。",
                                                   "sources": []})
                    return
                ctx = "\n".join("【%s】%s" % (s.get("title") or "资料",
                                            (s.get("text") or "").strip().replace("\n", " ")[:900])
                                for s in srcs[:6])
                sysmsg = ("你是企业知识库问答助手。**只依据下面提供的知识库资料**回答用户问题,用简洁准确的中文;"
                          "资料中没有的内容就明说『知识库暂无相关信息』,绝不编造卖点/价格/政策。可归纳提炼,但不要脱离资料。")
                prompt = "知识库资料:\n%s\n\n用户问题:%s\n\n请依据上述资料作答:" % (ctx, q)
                ans = lk888_chat(prompt, system=sysmsg, max_tokens=700, temperature=0.3)
                BRIDGE.payload.emit("kb_ask", {"answer": ans or "(未生成答案)", "sources": srcs})
            except Exception as e:
                BRIDGE.payload.emit("kb_ask", {"answer": "作答失败:" + str(e)[:120], "sources": []})
        run_bg(work)

    def delete(self, doc_id, title):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("删除知识")
        box.setText("确定从知识库删除「%s」吗?" % (title or doc_id))
        yes = box.addButton("删除", QtWidgets.QMessageBox.YesRole)
        box.addButton("取消", QtWidgets.QMessageBox.NoRole)
        box.exec()
        if box.clickedButton() is not yes:
            return

        def work():
            _c, j = api("POST", "/api/kb/delete", {"id": doc_id})
            BRIDGE.payload.emit("kb_del", {"ok": isinstance(j, dict) and j.get("ok")})
        run_bg(work)

    def _on(self, tag, d):
        if tag == "kb_list":
            self._build(d if isinstance(d, list) else [])
        elif tag == "kb_add":
            self.b_add.setEnabled(True)
            self.b_up.setEnabled(True)
            r = (d or {}).get("resp") or {}
            if (d or {}).get("ok"):
                self.status.setText("已入库 ✓  分块 %s · 字数 %s" % (r.get("chunks") or "-", r.get("chars") or "-"))
                self.text.clear()
                self.load()
            else:
                self.status.setText("失败:" + str(r.get("error") or "请检查登录/文件是否为文本"))
        elif tag == "kb_ask":
            ans = (d or {}).get("answer") or "无结果"
            srcs = (d or {}).get("sources") or []
            tail = ""
            if srcs:
                titles, seen = [], set()
                for s in srcs:
                    t = s.get("title") or "资料"
                    if t not in seen:
                        seen.add(t)
                        titles.append(t)
                tail = "\n\n———\n依据知识库:" + "、".join(titles[:5])
            self.answer.setPlainText(ans + tail)
        elif tag == "kb_del":
            if (d or {}).get("ok"):
                self.status.setText("已删除")
                self.load()
            else:
                self.status.setText("删除失败")

    def _build(self, docs):
        self.table.setRowCount(0)
        for k in docs:
            if not isinstance(k, dict):
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(k.get("title") or "-")))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(k.get("type") or "-")))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(str(k.get("chunks") or 0)))
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(k.get("chars") or 0)))
            db = QtWidgets.QPushButton("删除")
            db.setObjectName("ghost")
            db.setCursor(QtCore.Qt.PointingHandCursor)
            db.clicked.connect(lambda _=False, i=k.get("id"), t=k.get("title"): self.delete(i, t))
            self.table.setCellWidget(r, 4, db)


class PendingPublishPage(BasePage):
    """待发布队列:默认承接定时/手动生产的视频素材,预览无误后由你人工确认发布。
    若工作流开启了『定时自动发送视频』并填了账号,到点生成后会自动发布;失败记录仍会落到这里。"""

    def __init__(self):
        super().__init__()
        self._accounts = []
        b_refresh = QtWidgets.QPushButton("刷新")
        b_refresh.setObjectName("ghost")
        b_refresh.setCursor(QtCore.Qt.PointingHandCursor)
        b_refresh.clicked.connect(self.on_show)
        b_open = QtWidgets.QPushButton("打开素材库文件夹")
        b_open.setObjectName("ghost")
        b_open.setCursor(QtCore.Qt.PointingHandCursor)
        b_open.clicked.connect(lambda: _open_path(_wf_out_dir()))
        self.v.addWidget(make_header(
            "待发布队列",
            "默认人工确认发布 · 已开启『定时自动发送视频』的工作流会到点自动公开发布",
            [b_open, b_refresh]))
        tip = Panel("发布须知",
                    "① 未开启自动发送的视频会先入队,由你点『确认发布』。② 已开启『定时自动发送视频』并配置账号的工作流,"
                    "到点生成后会直接公开发布第一条视频;失败会留在队列里便于重试。③ 手动确认时默认『试发布(dry-run)』,"
                    "只打开创作台预填、不点最终发布;勾掉试发布并二次确认才会正式公开发布。")
        self.v.addWidget(tip)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("sub")
        self.v.addWidget(self.status)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["工作流", "文案", "目标账号", "平台", "状态", "操作"])
        style_table(self.table)
        try:
            hh = self.table.horizontalHeader()
            hh.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
            hh.setSectionResizeMode(5, QtWidgets.QHeaderView.Fixed)
            self.table.setColumnWidth(5, 300)
            self.table.verticalHeader().setDefaultSectionSize(48)
        except Exception:
            pass
        self.v.addWidget(self.table, 1)
        BRIDGE.payload.connect(self._on)
        wire_animations(self)

    def on_show(self):
        load_pending()
        self._build()

        def work():
            _c, j = api("GET", "/api/accounts")
            arr = j if isinstance(j, list) else ((j or {}).get("value") or (j or {}).get("accounts") or [])
            BRIDGE.payload.emit("pp_accounts", clean_accounts(arr if isinstance(arr, list) else [], ready_only=True))
        run_bg(work)

    def _on(self, tag, d):
        if tag == "pp_accounts":
            self._accounts = clean_accounts(d or [], ready_only=True)
        elif tag == "pp_pub":
            d = d or {}
            pid = d.get("id")
            if d.get("ok"):
                if d.get("dry"):
                    for x in PENDING:
                        if isinstance(x, dict) and x.get("id") == pid:
                            x["status"] = "已试发布(待你在创作台点发布)"
                    save_pending()
                    self.status.setText("试发布完成:已在创作台预填,请到浏览器核对后手动点发布。")
                else:
                    # 正式发布成功 → 从队列移除,避免同一素材被重复发布
                    remove_pending(pid)
                    self.status.setText("已正式发布 ✓(已移出待发布队列)")
            else:
                self.status.setText("发布失败:" + str(d.get("err") or "请确认已登录对应平台账号且引擎在线"))
            self._build()

    def _build(self):
        self.table.setRowCount(0)
        for e in (PENDING or []):
            if not isinstance(e, dict):
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(e.get("wfName") or "-")))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(e.get("caption") or "")))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(str(e.get("account") or "未指定")))
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem("抖音" if (e.get("platform") == "douyin") else "小红书"))
            self.table.setItem(r, 4, QtWidgets.QTableWidgetItem(str(e.get("status") or "待确认")))
            cell = QtWidgets.QWidget()
            cell.setStyleSheet("background:transparent;")
            hl = QtWidgets.QHBoxLayout(cell)
            hl.setContentsMargins(4, 3, 4, 3)
            hl.setSpacing(6)
            b_play = QtWidgets.QPushButton("播放")
            b_play.setObjectName("ghost")
            b_play.setMinimumWidth(56)
            b_play.setCursor(QtCore.Qt.PointingHandCursor)
            b_play.clicked.connect(lambda _=False, v=e.get("video"): _open_path(v) if v and os.path.isfile(v) else None)
            b_pub = QtWidgets.QPushButton("确认发布")
            b_pub.setObjectName("primary")
            b_pub.setMinimumWidth(96)
            b_pub.setCursor(QtCore.Qt.PointingHandCursor)
            b_pub.clicked.connect(lambda _=False, ent=e: self.confirm(ent))
            already_published = str(e.get("status") or "").startswith("已自动发布")
            if already_published:
                b_pub.setText("已发布")
                b_pub.setEnabled(False)
                b_pub.setCursor(QtCore.Qt.ArrowCursor)
            b_del = QtWidgets.QPushButton("删除")
            b_del.setObjectName("ghost")
            b_del.setMinimumWidth(56)
            b_del.setCursor(QtCore.Qt.PointingHandCursor)
            b_del.clicked.connect(lambda _=False, pid=e.get("id"): (remove_pending(pid), self._build()))
            hl.addWidget(b_play)
            hl.addWidget(b_pub)
            hl.addWidget(b_del)
            self.table.setCellWidget(r, 5, cell)
        if not PENDING:
            self.status.setText("队列为空。到『自动化工作流』运行一条流程,或等定时到点,产物会自动入队。")

    def confirm(self, entry):
        """人工确认发布:选账号 + 默认试发布(dry-run);正式发布需二次确认。Claude 从不代点。"""
        if not entry:
            return
        v = entry.get("video") or ""
        if not (v and os.path.isfile(v)):
            QtWidgets.QMessageBox.warning(self, "无法发布", "视频文件不存在(可能已被清理),建议删除此条。")
            return
        plat = entry.get("platform") or "douyin"
        pname = "抖音" if plat == "douyin" else "小红书"
        accs = [a for a in (self._accounts or []) if isinstance(a, dict)
                and str(a.get("platform") or "douyin").lower() == plat]
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("确认发布")
        dlg.setMinimumWidth(420)
        dv = QtWidgets.QVBoxLayout(dlg)
        dv.setSpacing(9)
        dv.addWidget(QtWidgets.QLabel("目标平台:%s" % pname))
        cap = QtWidgets.QLabel("文案:%s" % (entry.get("caption") or "")[:80])
        cap.setWordWrap(True)
        dv.addWidget(cap)
        dv.addWidget(QtWidgets.QLabel("发布到账号:"))
        combo = QtWidgets.QComboBox()
        if accs:
            for a in accs:
                combo.addItem("%s(%s)" % (a.get("name") or a.get("id"), a.get("status") or ""), a.get("id"))
        else:
            combo.addItem("未找到已登录的%s账号,请先到『账号矩阵』登录" % pname, "")
        dv.addWidget(combo)
        dry = QtWidgets.QCheckBox("试发布(dry-run:只打开创作台预填,不点最终发布) — 推荐先试")
        dry.setChecked(True)
        dv.addWidget(dry)
        row = QtWidgets.QHBoxLayout()
        row.addStretch()
        b_cancel = QtWidgets.QPushButton("取消")
        b_cancel.clicked.connect(dlg.reject)
        b_ok = QtWidgets.QPushButton("发布")
        b_ok.setObjectName("primary")
        b_ok.clicked.connect(dlg.accept)
        row.addWidget(b_cancel)
        row.addWidget(b_ok)
        dv.addLayout(row)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        aid = combo.currentData()
        if not aid:
            QtWidgets.QMessageBox.warning(self, "未选择账号", "请先到『账号矩阵』登录对应平台账号再发布。")
            return
        is_dry = dry.isChecked()
        if not is_dry:
            m = QtWidgets.QMessageBox.question(
                self, "正式发布确认",
                "即将【正式公开发布】到 %s 账号,发布后对外可见且不可撤回。\n\n文案:%s\n\n确定?" % (
                    pname, (entry.get("caption") or "")[:80]),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
            if m != QtWidgets.QMessageBox.Yes:
                return
        self._publish(entry, aid, is_dry)

    def _publish(self, entry, aid, is_dry):
        self.status.setText("上传素材并%s中…(需引擎在线且账号已登录)" % ("试发布" if is_dry else "正式发布"))
        v = entry.get("video")
        cap = entry.get("caption") or entry.get("wfName") or "素材"
        plat = entry.get("platform") or "douyin"
        pid = entry.get("id")

        def work():
            try:
                _code, j = upload_materials([v], cap)
                j = j or {}
                mid = j.get("id") or (j.get("material") or {}).get("id") or j.get("materialId")
                if not mid:
                    BRIDGE.payload.emit("pp_pub", {"id": pid, "ok": False, "err": "上传素材到素材库失败"})
                    return
                # 只传 centralMaterialId;中心的 local_browser_create_task 会自动补上正确的
                # centralMaterial{files:[{name,url}]},本机引擎节点据此跨端暂存素材再发布。
                payload = {"materialId": mid, "centralMaterialId": mid, "accountId": aid,
                           "platform": plat, "dryRun": bool(is_dry)}
                res = submit_local_task("publish.run", payload, 900)
                rr = (res or {}).get("result") or {}
                ok = _publish_result_ok(res, dry=is_dry)
                rr_err = rr.get("error") if isinstance(rr, dict) else rr
                err = "" if ok else str((res or {}).get("error") or rr_err or "发布失败(账号未登录/引擎离线?)")[:140]
                BRIDGE.payload.emit("pp_pub", {"id": pid, "ok": bool(ok), "dry": is_dry, "err": err})
            except Exception as e:
                BRIDGE.payload.emit("pp_pub", {"id": pid, "ok": False, "err": str(e)[:140]})
        run_bg(work)


# ---------- 商品图和视频生成:对话式生成流(gpt-image-2 出商品图 / vidu 出商品视频) ----------
PRODGEN = []


def _prodgen_path():
    return os.path.join(data_dir(), "productgen.json")


def load_prodgen():
    global PRODGEN
    import json as _json
    try:
        p = _prodgen_path()
        PRODGEN = _json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else []
        if not isinstance(PRODGEN, list):
            PRODGEN = []
    except Exception as e:
        log("load prodgen: %s" % e)
        PRODGEN = []
    for e in PRODGEN:  # 上次没跑完的(重启中断)标记出来,避免卡在“生成中”
        if isinstance(e, dict) and e.get("status") == "生成中":
            e["status"] = "已中断"


def save_prodgen():
    import json as _json
    try:
        _atomic_write_json(_prodgen_path(), PRODGEN)
    except Exception as e:
        log("save prodgen: %s" % e)


def add_prodgen(entry):
    PRODGEN.append(entry)
    save_prodgen()
    return entry


def update_prodgen(pid, **kw):
    for e in PRODGEN:
        if e.get("id") == pid:
            e.update(kw)
            break
    save_prodgen()


def remove_prodgen(pid):
    global PRODGEN
    PRODGEN = [x for x in PRODGEN if (x or {}).get("id") != pid]
    save_prodgen()


def _file_to_data_url(path):
    import base64 as _b64
    with open(path, "rb") as f:
        b = f.read()
    ext = os.path.splitext(path)[1].lower()
    mime = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext, "image/jpeg")
    return "data:%s;base64,%s" % (mime, _b64.b64encode(b).decode("ascii"))


def _is_remote_fetchable_media_url(value):
    """Return True only for HTTP(S) URLs a remote model can fetch."""
    try:
        parsed = urlparse(str(value or "").strip())
        host = (parsed.hostname or "").strip().lower()
        if parsed.scheme not in ("http", "https") or not host:
            return False
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return True
        return not any((
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        ))
    except Exception:
        return False


def _replacement_reference_max_bytes():
    try:
        return max(1024, int(os.getenv(
            "VIDEO_REPLACE_REFERENCE_MAX_BYTES", str(20 * 1024 * 1024)) or (20 * 1024 * 1024)))
    except Exception:
        return 20 * 1024 * 1024


def _replacement_keyframe_retry_size():
    value = str(os.getenv("VIDEO_REPLACE_KEYFRAME_RETRY_SIZE", "1024x1024") or "1024x1024").strip()
    return value if re.match(r"^\d+x\d+$", value) else "1024x1024"


def _replacement_keyframe_retry_refs(refs):
    try:
        limit = max(1, int(os.getenv("VIDEO_REPLACE_KEYFRAME_RETRY_REFS", "2") or 2))
    except Exception:
        limit = 2
    return list(refs or [])[:limit]


def _is_replacement_keyframe_transient_error(exc):
    text = str(exc or "").lower()
    return any(key in text for key in (
        "504", "502", "gateway time-out", "gateway timeout",
        "timeout", "timed out", "read operation timed out",
        "lk888_proxy_error", "urlerror", "remote disconnected",
    ))


def _replacement_has_talking_avatar_fallback(job, segment):
    candidates = [
        (segment or {}).get("keyframePath"),
        (job or {}).get("modelFaceUrl"),
    ]
    candidates.extend((job or {}).get("faceSourcePaths") or [])
    for value in candidates:
        value = str(value or "").strip()
        if value and (os.path.isfile(value) or _is_remote_fetchable_media_url(value)):
            return True
    return False


def _central_library_image_to_data_url(value):
    """Load only this client's central-library image URL for legacy jobs."""
    raw_url = str(value or "").strip()
    try:
        target = urlparse(raw_url)
        central = urlparse(CENTRAL)
        target_port = target.port or (443 if target.scheme == "https" else 80)
        central_port = central.port or (443 if central.scheme == "https" else 80)
        same_origin = (
            target.scheme == central.scheme
            and (target.hostname or "").lower() == (central.hostname or "").lower()
            and target_port == central_port
        )
    except Exception:
        return ""
    if not same_origin or not target.path.startswith("/api/library/file/"):
        return ""
    with _SLOCK:
        token = _SHARED.get("token") or ""
        org_id = _SHARED.get("org") or "org-default"
    headers = {"X-Matrix-Org-Id": org_id}
    if token:
        headers["X-Matrix-User-Token"] = token
    try:
        response = requests.get(raw_url, headers=headers, timeout=60)
    except Exception as exc:
        raise RuntimeError("video_replace_reference_download_failed:%s" % type(exc).__name__)
    if int(response.status_code or 0) != 200:
        raise RuntimeError("video_replace_reference_download_failed:http_%s" % response.status_code)
    content = bytes(response.content or b"")
    if not content or len(content) > _replacement_reference_max_bytes():
        raise RuntimeError("video_replace_reference_invalid_size")
    content_type = str((response.headers or {}).get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if not content_type.startswith("image/"):
        content_type = mimetypes.guess_type(target.path)[0] or "image/jpeg"
    if not content_type.startswith("image/"):
        raise RuntimeError("video_replace_reference_not_image")
    import base64 as _b64
    return "data:%s;base64,%s" % (content_type, _b64.b64encode(content).decode("ascii"))


def _prodgen_entry_refs(entry):
    """Return ordered Agent.模式 images: 第1张为待修改图，第2张起为参考图。"""
    entry = entry or {}
    refs = entry.get("refs")
    if not isinstance(refs, list):
        refs = []
    out = []
    for ref in refs + ([entry.get("ref")] if entry.get("ref") else []):
        ref = str(ref or "").strip()
        if ref and ref not in out and os.path.isfile(ref):
            out.append(ref)
        if len(out) >= ProductGenPage.MAX_REFS:
            break
    return out


def _prodgen_refs_desc(refs):
    """把多张参考图喂给多模态模型，按顺序拿到描述。"""
    refs = [str(p or "").strip() for p in (refs or []) if str(p or "").strip() and os.path.isfile(str(p or ""))]
    if not refs:
        return ""
    try:
        prompt = (
            "Describe these ordered generation reference images concisely. "
            "Image 1 is the image to edit. Images 2 and later are references for style, character, scene, material, "
            "or composition. Return one numbered line per image, including main subject, style, colors, scene, "
            "and any visible product/person features useful for generation."
        )
        return lk888_vision(
            prompt,
            [_file_to_data_url(ref) for ref in refs], max_tokens=420).strip()
    except Exception as e:
        log("prodgen vision: %s" % e)
        return ""


def _prodgen_ref_desc(ref):
    """把单张参考图喂给多模态模型,拿到商品的精准英文描述(兼容旧调用)。"""
    return _prodgen_refs_desc([ref])


def _prodgen_expand_prompt(user_desc, style_hint="", ref_desc="", is_video=False, edit=False):
    """① 让 LLM(gpt-5.4-xhigh)把用户中文描述扩写成专业英文出图/出片提示词(提示词工程)。
    edit=True(有参考图·图生图):提示词强调保留原商品主体、只重构场景。
    失败(余额/网络)时返回 "",上层回退到原描述+质量后缀,保证仍能出图。"""
    role = "商品短视频分镜" if is_video else "电商商品图"
    if edit and not is_video:
        sysmsg = ("你是顶尖电商图片编辑提示词工程师。用户提供了一张商品参考图,要在**保留该商品本体不变**"
                  "(外形/材质/logo/文字/颜色都不改)的前提下重构画面。把用户中文需求扩写成一条**英文**提示词,"
                  "只描述:keep the exact same product unchanged,以及新的场景/背景/道具/光影/构图/镜头/画质词"
                  "(如 8k, sharp focus)。绝不要臆造或改变商品本身。只输出这一条英文提示词,不要解释、引号或换行。")
    else:
        sysmsg = ("你是顶尖的%s AI 绘图提示词工程师。把用户的中文需求扩写成一条**英文**图像生成提示词,"
                  "覆盖:主体商品及其材质质感、构图与视角、光影与色调、背景/场景、镜头与画质词(如 8k, sharp focus, "
                  "product photography)。只输出这一条英文提示词本身,不要任何解释、引号或换行。" % role)
    parts = ["用户需求:" + user_desc]
    if ref_desc:
        parts.append("参考图内容:" + ref_desc)
    if style_hint:
        parts.append("风格方向:" + style_hint)
    bc = brand_context()
    if bc:
        parts.append(bc.strip())
    try:
        out = lk888_chat("\n".join(parts) + "\n\n输出英文提示词:", system=sysmsg,
                         model="gpt-5.4-xhigh", max_tokens=400, temperature=0.85)
        out = (out or "").strip().strip('"').strip()
        if out and len(out) >= 12:
            return out
    except Exception as e:
        log("prodgen expand: %s" % e)
    return ""


def _prodgen_optimize_prompt(user_desc, style_hint="", ref_desc="", is_video=False, edit=False):
    """把用户输入优化为可确认、可编辑的中文生成提示词。

    失败时返回空字符串，由 UI 提示用户继续用原输入生成。
    """
    user_desc = str(user_desc or "").strip()
    if not user_desc:
        return ""
    role = "商品短视频" if is_video else "电商商品图"
    keep_ref = (
        "如果用户上传了参考图，必须明确要求保留参考图里的商品主体、logo、文字、颜色、材质和外形，"
        "只优化场景、构图、光影、道具和镜头语言。"
        if edit else
        "如果用户后续上传参考图，提示词应能与参考图约束兼容。"
    )
    sysmsg = (
        "你是资深%s提示词优化师。把用户的粗略需求优化成一段中文提示词，供用户确认后直接生成。"
        "要求：1）只输出中文提示词正文；2）保留用户原意，不新增无关产品、品牌或人群；"
        "3）补充主体、材质质感、构图视角、场景背景、光影色调、镜头/画质、文字排版限制；"
        "4）句子紧凑清晰，120到260字；5）不要输出标题、编号、解释、引号。%s"
        % (role, keep_ref)
    )
    parts = ["用户原始需求：" + user_desc]
    if ref_desc:
        parts.append("参考图识别：" + ref_desc)
    if style_hint:
        parts.append("当前风格方向：" + style_hint)
    bc = brand_context()
    if bc:
        parts.append("品牌资料：" + bc.strip())
    try:
        out = lk888_chat("\n".join(parts) + "\n\n输出中文优化提示词：", system=sysmsg,
                         model="gpt-5.4-xhigh", max_tokens=520, temperature=0.72)
        out = (out or "").strip().strip('"').strip()
        out = re.sub(r"^\s*(优化后提示词|提示词|中文提示词)\s*[:：]\s*", "", out).strip()
        if out and len(out) >= 12:
            return out
    except Exception as e:
        log("prodgen optimize prompt: %s" % e)
    return ""


def _prodgen_visible_prompt(entry):
    return (entry.get("visiblePrompt") or entry.get("prompt") or "").strip()


def _prodgen_run_image(entry, emit=None):
    display_prompt = _prodgen_visible_prompt(entry) or "商品"
    prompt = display_prompt
    style_hint = (entry.get("style") or "").strip()
    refs = _prodgen_entry_refs(entry)
    model = str(entry.get("model") or _LK888_IMAGE_DEFAULT).strip() or _LK888_IMAGE_DEFAULT
    model_label = _lk888_model_label(model)
    has_ref = bool(refs)
    if emit:
        emit("phase", {"phaseText": ("gpt-5.4 正在思考(图生图·保留参考主体)…" if has_ref
                                      else "gpt-5.4 正在思考、提炼英文提示词…")})
    # ① LLM 扩写英文提示词;有参考图 → 走"保留主体、重构场景"口吻(图生图)
    model_prompt = (entry.get("modelPrompt") or "").strip()
    if not model_prompt:
        model_prompt = _prodgen_expand_prompt(prompt, style_hint, "", is_video=False, edit=has_ref)
    if not model_prompt:  # 回退
        base = prompt + ((", " + style_hint) if style_hint else "")
        if has_ref:
            model_prompt = ("Use image 1 as the edit target and keep its editable subject structure coherent. "
                            "Use images 2 and later only as references for requested style, character, scene, "
                            "material, or composition. " + base + ". Professional e-commerce product photography, "
                            "studio lighting, crisp focus, high detail, 8k.")
        else:
            model_prompt = base + (". Professional e-commerce product photography, studio lighting, clean seamless "
                                   "background, crisp focus, high detail, commercial quality, 8k.")
    try:
        update_prodgen(entry.get("id"), expandedPrompt=display_prompt[:700],
                       visiblePrompt=display_prompt, modelPrompt=model_prompt[:700],
                       model=model, modelLabel=model_label)
    except Exception:
            pass
    if emit:
        emit("thinking", {"expandedPrompt": display_prompt})
        emit("phase", {"phaseText": ("%s 多图参考出图中(第1张为待修改图)…" % model_label if has_ref
                                     else "%s 正在出图…" % model_label)})
    # ② 图片模型出图:第1张为待修改图，第2张起为参考图；否则文生图。
    image_urls = [_file_to_data_url(p) for p in refs] if has_ref else None
    size = entry.get("size") or "1024x1024"
    try:
        cnt = max(1, min(int(entry.get("count") or 1), 2))
    except Exception:
        cnt = 1
    files = []
    for k in range(cnt):
        b = lk888_image(model_prompt, size=size, model=model, image_urls=image_urls)
        p = os.path.join(data_dir(), "prodimg_%d_%d_%s.png" % (int(time.time()), k + 1, os.urandom(3).hex()))
        with open(p, "wb") as f:
            f.write(b)
        files.append(p)
    return files


def _prodgen_run_video(entry, emit=None):
    """商品视频:doubao-seedance 文生视频(产品运镜/场景,非数字人主播;约 1 分钟出片)。
    有参考图时把它经 gemini 描述后并入提示词(视频端点不收 data-url,只能靠文字带参考)。"""
    display_prompt = _prodgen_visible_prompt(entry) or "商品展示"
    prompt = display_prompt
    style_hint = (entry.get("style") or "").strip()
    refs = _prodgen_entry_refs(entry)
    has_ref = bool(refs)
    if emit:
        emit("phase", {"phaseText": "gpt-5.4 正在编排商品视频画面…"})
    ref_desc = _prodgen_refs_desc(refs) if has_ref else ""
    model_prompt = (entry.get("modelPrompt") or "").strip()
    if not model_prompt:
        model_prompt = _prodgen_expand_prompt(prompt, style_hint, ref_desc, is_video=True)
    if not model_prompt:
        model_prompt = (("参考商品:%s。" % ref_desc[:160]) if ref_desc else "") + prompt + \
                       ((", " + style_hint) if style_hint else "") + \
                       ", cinematic product video, slow camera motion, studio lighting, 4k"
    dur = _agent_video_duration(entry.get("duration"))
    model = str(entry.get("model") or _LK888_VIDEO_DEFAULT).strip() or _LK888_VIDEO_DEFAULT
    model_label = _lk888_model_label(model)
    try:
        update_prodgen(entry.get("id"), expandedPrompt=display_prompt[:700],
                       visiblePrompt=display_prompt, modelPrompt=model_prompt[:700],
                       duration=dur, model=model, modelLabel=model_label)
    except Exception:
        pass
    if emit:
        emit("thinking", {"expandedPrompt": display_prompt})
        emit("phase", {"phaseText": "%s 正在出片(约 1 分钟)…" % model_label})
    ar = entry.get("aspect_ratio") or "16:9"
    url = lk888_media_task(
        model,
        {"prompt": model_prompt[:600], "params": {"duration": dur, "resolution": "720p", "aspect_ratio": ar}},
        ["mp4", "mov"], tries=150)
    p = os.path.join(data_dir(), "prodvid_%d_%s.mp4" % (int(time.time()), os.urandom(3).hex()))
    _wf_download(url, p)
    return [p]


def _prodgen_generate(entry, emit=None):
    return _prodgen_run_video(entry, emit) if entry.get("mode") == "video" else _prodgen_run_image(entry, emit)


# ---------- 资产库:保存用户生成的图片/视频,生成时可复用为参考图 ----------
ASSETS = []


def _assets_path():
    return os.path.join(data_dir(), "assets.json")


def _assets_dir():
    d = os.path.join(data_dir(), "assets")
    os.makedirs(d, exist_ok=True)
    return d


def load_assets():
    global ASSETS
    import json as _json
    try:
        p = _assets_path()
        ASSETS = _json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else []
        if not isinstance(ASSETS, list):
            ASSETS = []
        ASSETS = [x for x in ASSETS if isinstance(x, dict)]
    except Exception as e:
        log("load assets: %s" % e)
        ASSETS = []


def save_assets():
    import json as _json
    try:
        _atomic_write_json(_assets_path(), ASSETS)
    except Exception as e:
        log("save assets: %s" % e)


def add_asset(path, kind=None, prompt="", source=""):
    """把文件拷进资产库目录(稳定不被清理)并登记。返回 asset dict 或 None。"""
    if not (path and os.path.isfile(path)):
        return None
    import shutil
    ext = os.path.splitext(path)[1].lower()
    if not kind or kind not in ("image", "video", "note_template"):
        kind = "video" if ext in (".mp4", ".mov", ".webm", ".m4v") else "image"
    fname = "as_%d_%s" % (int(time.time() * 1000), os.path.basename(path))
    dst = os.path.join(_assets_dir(), fname)
    try:
        shutil.copyfile(path, dst)
    except Exception as e:
        log("add asset copy: %s" % e)
        return None
    a = {"id": "as_%d_%s" % (int(time.time() * 1000000), os.urandom(3).hex()), "kind": kind, "path": dst,
         "name": os.path.basename(path), "prompt": (prompt or "")[:200], "source": source,
         "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    ASSETS.insert(0, a)
    save_assets()
    return a


def remove_asset(aid, delete_file=True):
    global ASSETS
    a = next((x for x in ASSETS if x.get("id") == aid), None)
    ASSETS = [x for x in ASSETS if x.get("id") != aid]
    save_assets()
    if a and delete_file and a.get("path") and os.path.isfile(a["path"]):
        try:
            os.remove(a["path"])
        except Exception:
            pass


# ---------- 企业资料(品牌定位),生成时统一注入 ----------
BRAND = {}


def _brand_path():
    return os.path.join(data_dir(), "brand_profile.json")


def load_brand():
    global BRAND
    import json as _json
    try:
        p = _brand_path()
        BRAND = _json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}
        if not isinstance(BRAND, dict):
            BRAND = {}
    except Exception as e:
        log("load brand: %s" % e)
        BRAND = {}


def save_brand(d):
    global BRAND
    BRAND = d or {}
    import json as _json
    try:
        _atomic_write_json(_brand_path(), BRAND)
    except Exception as e:
        log("save brand: %s" % e)


def brand_context():
    """把企业资料拼成提示词注入片段,生成时贴合品牌定位。空则返回 ""。"""
    b = BRAND or {}
    label = [("name", "品牌"), ("intro", "简介"), ("category", "主营品类"),
             ("tone", "风格调性"), ("audience", "目标人群"), ("selling", "核心卖点")]
    parts = ["%s:%s" % (lb, str(b.get(k)).strip()) for k, lb in label if str(b.get(k) or "").strip()]
    if not parts:
        return ""
    return "\n【企业品牌资料,生成时请贴合以下品牌定位,不要跑偏】\n" + "；".join(parts)


# ---------- 风控中心:安全限额(发布/评论上限、操作间隔、并发) ----------
RISK = {"dailyPublish": 3, "dailyComment": 30, "minInterval": 45, "concurrency": 2}


def _risk_path():
    return os.path.join(data_dir(), "risk_config.json")


def load_risk():
    global RISK
    import json as _json
    try:
        p = _risk_path()
        if os.path.isfile(p):
            d = _json.load(open(p, encoding="utf-8"))
            if isinstance(d, dict):
                RISK.update(d)
    except Exception as e:
        log("load risk: %s" % e)


def save_risk(d):
    global RISK
    if isinstance(d, dict):
        RISK.update(d)
    import json as _json
    try:
        _atomic_write_json(_risk_path(), RISK)
    except Exception as e:
        log("save risk: %s" % e)


# ---------- 混剪短视频:本地 ffmpeg 把图片/视频片段拼成一条短视频 ----------
def _ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")


def _is_video_path(path):
    return bool(path) and str(path).split("?")[0].lower().endswith(VIDEO_EXTS)


def _localize_download_task_error(error):
    text = str(error or "").strip()
    if not text:
        return ""
    if text in ("douyin_auth_incomplete", "no_auth") or "s_v_web_id" in text:
        return "抖音登录态不完整或已过期，请在账号矩阵重新登录抖音后再分解。"
    if text == "local_browser_offline":
        return "本地客户端未在线，请先启动并登录本地客户端。"
    return text


def _find_video_file_from_download(result):
    """Return the first existing video path from a download response."""
    if not isinstance(result, dict):
        return ""
    candidates = []
    mat = result.get("material")
    if isinstance(mat, dict):
        candidates.extend([mat.get("path"), mat.get("file"), mat.get("localPath")])
        for f in mat.get("files") or []:
            if isinstance(f, dict):
                candidates.extend([f.get("path"), f.get("file"), f.get("localPath")])
    for f in result.get("files") or []:
        if isinstance(f, dict):
            candidates.extend([f.get("path"), f.get("file"), f.get("localPath")])
    sp = result.get("savePath") or result.get("path") or result.get("save_path")
    if sp and os.path.isdir(sp):
        try:
            for root, _dirs, files in os.walk(sp):
                for name in files:
                    candidates.append(os.path.join(root, name))
        except Exception:
            pass
    for p in candidates:
        p = str(p or "").strip()
        if _is_video_path(p) and os.path.isfile(p):
            return p
    return ""


def _strip_breakdown_timestamps(text):
    import re
    text = re.sub(r"\[\d{1,2}:\d{2}(?:\.\d+)?-\d{1,2}:\d{2}(?:\.\d+)?\]\s*", "", str(text or ""))
    text = re.sub(r"\[\d{1,2}:\d{2}:\d{2}(?:\.\d+)?-\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _markdown_section(markdown, title):
    import re
    pattern = re.compile(
        r"^##[ \t]+%s[ \t]*\n(?P<body>.*?)(?=^##[ \t]+|\Z)" % re.escape(title),
        re.M | re.S,
    )
    match = pattern.search(str(markdown or ""))
    return (match.group("body").strip() if match else "")


def _digital_human_seed_from_breakdown(analysis, markdown):
    analysis = analysis or {}
    markdown = str(markdown or "")
    transcript = analysis.get("transcript") or {}
    script = _strip_breakdown_timestamps(transcript.get("text") or "")
    if not script:
        script = _strip_breakdown_timestamps(_markdown_section(markdown, "字幕与口播"))
    if not script:
        script = _strip_breakdown_timestamps(_markdown_section(markdown, "仿拍脚本"))
    if not script:
        script = "请根据分解报告整理一条自然口播稿。"
    source = analysis.get("sourceUrl") or analysis.get("videoPath") or "分解视频"
    visual = _strip_breakdown_timestamps(
        analysis.get("visual") or _markdown_section(markdown, "时间轴镜头拆解") or _markdown_section(markdown, "内容总览")
    )
    avatar_bits = []
    if visual:
        avatar_bits.append(visual[:120])
    avatar_bits.append("正脸清晰，单人出镜，上半身构图，口型自然同步，适合短视频口播")
    return {
        "topic": source,
        "sourceUrl": analysis.get("sourceUrl") or "",
        "script": script[:1200],
        "avatarDescription": "，".join([x for x in avatar_bits if x]).strip("，")[:260],
    }


VIDEO_BREAKDOWN_SECTION_TITLES = (
    "内容总览",
    "时间轴镜头拆解",
    "字幕与口播",
    "营销结构",
    "爆点分析",
    "仿拍脚本",
    "Agent.模式提示词",
)


def _video_breakdown_prompt(meta, frame_notes, ocr_text, transcript):
    meta = meta or {}
    return """你是短视频爆款拆解专家。请基于视频关键帧、OCR字幕和口播转写，输出中文深度拆解报告。

视频信息:
- 时长: {duration}
- 分辨率: {width}x{height}

关键帧观察:
{frame_notes}

OCR字幕:
{ocr_text}

音频/口播转写:
{transcript}

请严格按以下栏目输出。七个栏目必须全部出现，即使输入信息较多也不得省略末尾栏目:
## 内容总览
一句话总结、视频类型、目标用户、核心卖点。

## 时间轴镜头拆解
按时间段列出画面、人物、产品、动作、字幕、道具、场景、节奏。

## 字幕与口播
整理出现的字幕、口播重点和表达风格。

## 营销结构
拆解开头钩子、痛点、解决方案、证据、信任背书、转化动作。

## 爆点分析
说明吸睛点、情绪点、冲突点、可复刻原因。

## 仿拍脚本
给出可直接拍摄的镜头顺序、画面要求、口播参考、拍摄注意事项。

## Agent.模式提示词
给出一段可以用于生成同款风格视频的结构化提示词。
""".format(
        duration=meta.get("duration") or "未知",
        width=meta.get("width") or "未知",
        height=meta.get("height") or "未知",
        frame_notes=(frame_notes or "无"),
        ocr_text=(ocr_text or "未启用 OCR 或未识别到字幕"),
        transcript=(transcript or "未启用音频转写或未识别到口播"),
    )


def _breakdown_evidence_excerpt(value, fallback, limit=900):
    import re
    text = re.sub(r"\n{3,}", "\n\n", str(value or "").strip())
    if not text:
        return fallback
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "...（证据已截取）"


def _video_breakdown_section_fallbacks(data):
    data = data or {}
    meta = data.get("meta") or {}
    ocr = data.get("ocr") or {}
    transcript = data.get("transcript") or {}
    visual = _breakdown_evidence_excerpt(
        data.get("visual"), "未获得视觉模型分析结果", 1200)
    frame_notes = _breakdown_evidence_excerpt(
        data.get("frameNotes"), "未抽取到可用关键帧说明", 800)
    ocr_text = _breakdown_evidence_excerpt(
        ocr.get("text"), ocr.get("message") or "未识别到 OCR 字幕", 900)
    transcript_text = _breakdown_evidence_excerpt(
        transcript.get("text"), transcript.get("message") or "未识别到口播", 1200)
    duration = meta.get("duration") or "未知"
    resolution = "%sx%s" % (meta.get("width") or "未知", meta.get("height") or "未知")
    evidence = (
        "- 视频规格：时长 %s 秒，分辨率 %s\n"
        "- 视觉依据：%s\n"
        "- 关键帧依据：%s\n"
        "- OCR 依据：%s\n"
        "- 口播依据：%s"
        % (duration, resolution, visual, frame_notes, ocr_text, transcript_text)
    )
    return {
        "内容总览": (
            "模型未返回本栏目，以下为可验证证据摘要：\n\n%s" % evidence
        ),
        "时间轴镜头拆解": (
            "模型未返回本栏目。可按下列带时间信息的证据复核镜头：\n\n"
            "### 关键帧与画面\n%s\n\n"
            "### OCR 字幕\n%s\n\n"
            "### 口播时间轴\n%s" % (frame_notes + "\n" + visual, ocr_text, transcript_text)
        ),
        "字幕与口播": (
            "模型未返回本栏目，保留原始识别结果供复核：\n\n"
            "### OCR 字幕\n%s\n\n### 口播转写\n%s" % (ocr_text, transcript_text)
        ),
        "营销结构": (
            "模型未返回本栏目。以下证据可用于重新判断钩子、痛点、解决方案、"
            "实测证据、信任背书和转化动作：\n\n%s" % evidence
        ),
        "爆点分析": (
            "模型未返回本栏目。优先从画面冲突、字幕承诺和口播中的效果验证提炼爆点：\n\n"
            "- 画面与动作：%s\n- 字幕表达：%s\n- 口播表达：%s"
            % (visual, ocr_text, transcript_text)
        ),
        "仿拍脚本": (
            "以下脚本根据已识别证据自动补全，未知细节需在拍摄前确认。\n\n"
            "1. **开场（0-3 秒）**：复用原视频最清晰的主体或产品特写，立即呈现核心测试。\n"
            "2. **过程展示**：按关键帧顺序复现人物动作、使用过程和场景变化。\n"
            "3. **结果验证**：使用近景和前后对比展示可见结果，字幕只保留可验证结论。\n"
            "4. **收尾转化**：用一句明确口播总结体验，并给出与原视频一致的行动指引。\n\n"
            "### 拍摄依据\n- 画面：%s\n- 字幕：%s\n- 口播：%s"
            % (visual, ocr_text, transcript_text)
        ),
        "Agent.模式提示词": (
            "```text\n"
            "你是一名短视频导演和编导。请严格依据下列已识别证据，生成一条同主题、"
            "同节奏但不虚构产品效果的短视频方案。输出分镜时间轴、画面、动作、字幕、"
            "口播、转场、音效和拍摄注意事项；开头 3 秒给出明确钩子，结尾给出自然转化动作。\n\n"
            "视频规格：时长 %s 秒，分辨率 %s\n"
            "视觉与关键帧证据：\n%s\n%s\n"
            "OCR 字幕证据：\n%s\n"
            "口播转写证据：\n%s\n"
            "```" % (duration, resolution, visual, frame_notes, ocr_text, transcript_text)
        ),
    }


def _ensure_video_breakdown_report_sections(report, data):
    import re
    report = str(report or "").strip()
    if report.count("```") % 2:
        report += "\n```"
    fallbacks = _video_breakdown_section_fallbacks(data)
    heading_patterns = {
        title: re.compile(
            r"^##[ \t]+(?:\d+[.、)]\s*)?(?:\*\*)?"
            + re.escape(title)
            + r"(?:\*\*)?[ \t]*(?:[:：][ \t]*)?$"
        )
        for title in VIDEO_BREAKDOWN_SECTION_TITLES
    }
    section_lines = {title: [] for title in VIDEO_BREAKDOWN_SECTION_TITLES}
    heading_counts = {title: 0 for title in VIDEO_BREAKDOWN_SECTION_TITLES}
    heading_order = []
    preamble = []
    current = ""
    in_fence = False

    for line in report.splitlines():
        stripped = line.strip()
        matched = ""
        if not in_fence:
            for title, pattern in heading_patterns.items():
                if pattern.match(stripped):
                    matched = title
                    break
        if matched:
            if heading_counts[matched] and section_lines[matched] and section_lines[matched][-1].strip():
                section_lines[matched].append("")
            heading_counts[matched] += 1
            heading_order.append(matched)
            current = matched
            continue
        (section_lines[current] if current else preamble).append(line)
        if stripped.startswith("```"):
            in_fence = not in_fence

    unique_order = []
    for title in heading_order:
        if title not in unique_order:
            unique_order.append(title)
    expected_present_order = [
        title for title in VIDEO_BREAKDOWN_SECTION_TITLES if heading_counts[title]
    ]
    repaired = ["section_order"] if unique_order != expected_present_order else []
    bodies = {}
    for title in VIDEO_BREAKDOWN_SECTION_TITLES:
        body = "\n".join(section_lines[title]).strip()
        if not heading_counts[title] or not body:
            if title not in repaired:
                repaired.append(title)
            body = fallbacks[title]
        if heading_counts[title] > 1 and title not in repaired:
            repaired.append(title)
        bodies[title] = body

    parts = []
    preamble_text = "\n".join(preamble).strip()
    if preamble_text:
        parts.append(preamble_text)
    parts.extend(
        "## %s\n%s" % (title, bodies[title])
        for title in VIDEO_BREAKDOWN_SECTION_TITLES
    )
    return "\n\n".join(parts), repaired


def _video_breakdown_markdown(data):
    data = data or {}
    meta = data.get("meta") or {}
    ocr = data.get("ocr") or {}
    transcript = data.get("transcript") or {}
    lines = [
        "# 视频深度分解报告",
        "",
        "## 来源",
        "",
        "- 平台: %s" % (data.get("platform") or "-"),
        "- 链接: %s" % (data.get("sourceUrl") or "-"),
        "- 本地文件: %s" % (data.get("videoPath") or "-"),
        "- 时长: %s" % (meta.get("duration") or "-"),
        "- 分辨率: %sx%s" % (meta.get("width") or "-", meta.get("height") or "-"),
        "- OCR: %s" % (ocr.get("status") or "-"),
        "- OCR 引擎: %s" % (ocr.get("engine") or "-"),
        "- 音频转写: %s" % (transcript.get("status") or "-"),
        "- 重试次数: %s" % int(transcript.get("retryCount") or 0),
        "",
    ]
    if transcript.get("truncated"):
        lines.extend(["- 转写范围: 仅分析前 10 分钟（原视频超过上限）", ""])
    failed_ranges = transcript.get("failedRanges") or []
    if failed_ranges:
        lines.extend(["## 转写失败区间", ""])
        for item in failed_ranges:
            line = "- %.1f-%.1fs | code: %s" % (
                float(item.get("start") or 0),
                float(item.get("end") or 0),
                item.get("code") or "transcription_failed",
            )
            if item.get("errorId"):
                line += " | errorId: %s" % item.get("errorId")
            lines.append(line)
        lines.append("")
    lines.extend([data.get("report") or "暂无报告。", ""])
    return "\n".join(lines)


def _breakdown_source_validation(path):
    return validate_video_file(path)


def _transcription_range_key(item):
    return (
        round(float((item or {}).get("start") or 0), 3),
        round(float((item or {}).get("end") or 0), 3),
    )


def _transcription_errors_for_ranges(errors, failed_ranges):
    by_range = {
        _transcription_range_key(item): item
        for item in errors or [] if isinstance(item, dict)
    }
    return [
        dict(by_range.get(_transcription_range_key(item)) or item)
        for item in failed_ranges or [] if isinstance(item, dict)
    ]


def _merge_transcription_retry(previous, retried):
    previous = dict(previous or {})
    retried = dict(retried or {})
    chunks = {
        _transcription_range_key(item): item
        for item in previous.get("chunks") or [] if isinstance(item, dict)
    }
    for item in retried.get("chunks") or []:
        if isinstance(item, dict):
            chunks[_transcription_range_key(item)] = item
    ordered_chunks = [chunks[key] for key in sorted(chunks)]
    merged = merge_transcription_segments(ordered_chunks)
    retry_status = retried.get("status") or "failed"
    failed_ranges = list(retried.get("failedRanges") or [])
    restored_previous_failures = False
    if retry_status not in {"ok", "empty"} and not failed_ranges:
        failed_ranges = list(previous.get("failedRanges") or [])
        restored_previous_failures = bool(failed_ranges)
    if restored_previous_failures:
        errors = _transcription_errors_for_ranges(previous.get("errors"), failed_ranges)
        for item in retried.get("errors") or []:
            if isinstance(item, dict) and item not in errors:
                errors.append(item)
    elif "errors" in retried:
        errors = list(retried.get("errors") or [])
    else:
        errors = list(previous.get("errors") or [])
    if ordered_chunks and failed_ranges:
        status = "partial"
    elif ordered_chunks:
        status = "ok"
    elif failed_ranges:
        status = "failed"
    else:
        status = retry_status
    if status == "ok":
        message = "音频转写完成。"
        code = "ok"
    elif status == "partial":
        message = "音频转写部分完成，可重试失败时间段。"
        code = "transcription_partial"
    else:
        message = retried.get("message") or "音频转写失败，已继续使用画面与 OCR 分析。"
        code = retried.get("code") or "transcription_failed"
    return dict(merged, status=status, code=code, chunks=ordered_chunks,
                failedRanges=failed_ranges,
                errors=errors,
                duration=retried.get("duration") or previous.get("duration"),
                truncated=bool(retried.get("truncated") or previous.get("truncated")),
                retryCount=int(previous.get("retryCount") or 0) + 1,
                message=message)


def _generate_video_breakdown_report(data):
    data = data or {}
    meta = data.get("meta") or {}
    ocr = data.get("ocr") or {}
    transcript = data.get("transcript") or {}
    visual = data.get("visual") or "未获得视觉模型分析结果"
    frame_notes = data.get("frameNotes") or "未抽取到关键帧"
    prompt = _video_breakdown_prompt(
        meta,
        visual + "\n" + frame_notes,
        ocr.get("text") or "",
        transcript.get("text") or "",
    )
    try:
        report = lk888_chat(
            prompt,
            system="你是短视频编导、投流素材分析师和爆款内容拆解专家。",
            model="gpt-5.4-xhigh",
            max_tokens=4800,
            temperature=0.35,
        )
        report, repaired = _ensure_video_breakdown_report_sections(report, data)
        if repaired:
            json_log(
                _CLIENT_JSON_LOGGER,
                "video_breakdown_report_sections_repaired",
                level="info",
                repaired_sections=repaired,
                repair_count=len(repaired),
            )
            return report, "分析完成（已自动修复报告栏目）"
        return report, "分析完成"
    except Exception as exc:
        raw = json_log(
            _CLIENT_JSON_LOGGER,
            "video_breakdown_report_failed",
            exc=exc,
            code="video_breakdown_report_failed",
            video_path=data.get("videoPath") or "",
        )
        import json as _json
        error_id = (_json.loads(raw) or {}).get("errorId")
        report = "## 内容总览\nAI 汇总失败（errorId: %s）:%s" % (
            error_id or "-", str(exc)[:180]
        )
        report, _completed = _ensure_video_breakdown_report_sections(report, data)
        return report, "分析完成（AI汇总已降级）"


def _build_replacement_segments(analysis, duration=None, segment_seconds=8):
    analysis = analysis or {}
    meta = analysis.get("meta") or {}
    try:
        total = float(duration if duration is not None else (meta.get("duration") or 0))
    except Exception:
        total = 0.0
    if total <= 0:
        total = 8.0
    try:
        step = max(2.0, float(segment_seconds or 8))
    except Exception:
        step = 8.0
    segments = []
    start = 0.0
    idx = 1
    while start < total:
        end = min(total, start + step)
        segments.append({
            "index": idx,
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(max(0.1, end - start), 3),
            "status": "pending",
            "prompt": "",
            "sourceFramePath": "",
            "keyframePath": "",
            "keyframeUrl": "",
            "videoPath": "",
            "error": "",
            "errorId": "",
        })
        idx += 1
        start = end
    if len(segments) >= 2 and float(segments[-1].get("duration") or 0) < 3.0:
        tail = segments.pop()
        previous = segments[-1]
        previous["end"] = tail["end"]
        previous["duration"] = round(
            max(0.1, float(previous.get("end") or 0) - float(previous.get("start") or 0)),
            3,
        )
    return segments


def _build_hybrid_replacement_plan(analysis, duration=None, segment_seconds=8, strict_script_audio=False):
    analysis = analysis or {}
    try:
        total = float(duration if duration is not None else ((analysis.get("meta") or {}).get("duration") or 0))
    except (TypeError, ValueError):
        total = 0.0
    segments = _build_replacement_segments(analysis, total, segment_seconds=segment_seconds)
    transcript = analysis.get("transcript") or {}
    spoken = transcript.get("segments") or []
    for segment in segments:
        start = float(segment.get("start") or 0)
        end = float(segment.get("end") or 0)
        lines = []
        for item in spoken:
            if not isinstance(item, dict):
                continue
            try:
                item_start = float(item.get("startSec") if item.get("startSec") is not None else item.get("start") or 0)
                item_end = float(item.get("endSec") if item.get("endSec") is not None else item.get("end") or item_start)
            except (TypeError, ValueError):
                continue
            if item_end > start and item_start < end:
                text = str(item.get("text") or "").strip()
                if text:
                    lines.append(text)
        script = " ".join(lines).strip()
        segment.update({
            "segmentType": "non_talking",
            "script": script,
            "ttsUrl": "",
            "editedVideoPath": "",
            "faceSwapPath": "",
            "audioStatus": "pending",
            "qcStatus": "pending",
            "reviewApproved": False,
            "qcFrames": [],
        })
    return segments


def _replacement_excerpt(text, limit=1200):
    import re
    value = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "...(truncated)"


def _replacement_contains_source_subtitle_or_dialogue(line):
    text = str(line or "").strip()
    if not text:
        return False
    safe_phrases = (
        "字幕安全", "后期字幕", "中文字幕", "用户修改", "用户口播", "口播稿",
        "AI 音色配音", "上传配音", "不要复刻", "不要保留", "不要新增",
    )
    if any(phrase in text for phrase in safe_phrases):
        return False
    markers = (
        "字幕/信息", "字幕与口播", "OCR", "原片字幕", "原视频字幕", "画面字幕",
        "旧字幕", "口播转写", "原片口播", "原视频口播", "原片台词", "原视频台词", "原片动作和台词", "原片动作、台词",
    )
    return any(marker in text for marker in markers)


def _replacement_strip_source_subtitle_dialogue(text):
    lines = str(text or "").splitlines()
    cleaned = []
    skip_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("##"):
            if "字幕与口播" in stripped:
                skip_section = True
                continue
            skip_section = False
        if skip_section:
            continue
        if _replacement_contains_source_subtitle_or_dialogue(stripped):
            continue
        cleaned.append(line)
    return _replacement_excerpt("\n".join(cleaned).strip(), 2400)


def _replacement_time_value_to_seconds(value):
    import re as _re
    text = str(value or "").strip()
    if not text:
        return None
    if ":" not in text:
        match = _re.search(r"\d+(?:\.\d+)?", text)
        return float(match.group(0)) if match else None
    parts = text.split(":")
    try:
        numbers = [float(part) for part in parts]
    except (TypeError, ValueError):
        return None
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    return None


def _replacement_time_range_from_text(text):
    import re as _re
    value = str(text or "")
    patterns = (
        r"(\d+(?:\.\d+)?)\s*(?:-|–|—|~|至|到)\s*(\d+(?:\.\d+)?)\s*秒",
        r"(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\s*(?:-|–|—|~|至|到)\s*(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)",
    )
    for pattern in patterns:
        match = _re.search(pattern, value)
        if not match:
            continue
        start = _replacement_time_value_to_seconds(match.group(1))
        end = _replacement_time_value_to_seconds(match.group(2))
        if start is None or end is None:
            continue
        if end < start:
            start, end = end, start
        return start, end
    return None


def _replacement_time_ranges_overlap(start, end, item_range):
    if not item_range:
        return False
    item_start, item_end = item_range
    return item_end > start and item_start < end


def _replacement_markdown_table_cells(line):
    import re as _re
    text = str(line or "").strip()
    if not text.startswith("|") or "|" not in text.strip("|"):
        return []
    cells = [cell.strip() for cell in text.strip("|").split("|")]
    if not cells:
        return []
    if all(_re.match(r"^:?-{3,}:?$", cell.replace(" ", "")) for cell in cells):
        return []
    return cells


def _replacement_table_value(headers, cells, names):
    for idx, header in enumerate(headers):
        if idx >= len(cells):
            continue
        if any(name in str(header) for name in names):
            value = str(cells[idx] or "").strip()
            if value and not _replacement_contains_source_subtitle_or_dialogue(value):
                return value
    return ""


def _replacement_current_shot_constraints(segment, analysis, limit=900):
    segment = segment or {}
    analysis = analysis or {}
    try:
        start = float(segment.get("start") or 0)
    except (TypeError, ValueError):
        start = 0.0
    try:
        end = float(segment.get("end") or 0)
    except (TypeError, ValueError):
        end = 0.0
    if end <= start:
        try:
            end = start + float(segment.get("duration") or 8)
        except (TypeError, ValueError):
            end = start + 8.0
    report = str(analysis.get("report") or "")
    section = _markdown_section(report, "时间轴镜头拆解") or str(analysis.get("frameNotes") or "")
    headers = []
    rows = []
    fallback_lines = []
    allowed_columns = (
        ("时间",), ("画面",), ("人物",), ("产品",), ("动作",), ("道具",), ("场景",), ("节奏",)
    )
    for raw_line in str(section or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cells = _replacement_markdown_table_cells(line)
        if cells:
            if not headers:
                headers = cells
                continue
            time_text = _replacement_table_value(headers, cells, ("时间",)) or cells[0]
            item_range = _replacement_time_range_from_text(time_text)
            if item_range and not _replacement_time_ranges_overlap(start, end, item_range):
                continue
            if not item_range and rows:
                continue
            parts = []
            for names in allowed_columns:
                value = _replacement_table_value(headers, cells, names)
                if value:
                    parts.append("%s=%s" % (names[0], value))
            if parts:
                rows.append("- " + "；".join(parts))
            continue
        item_range = _replacement_time_range_from_text(line)
        if item_range and not _replacement_time_ranges_overlap(start, end, item_range):
            continue
        if _replacement_contains_source_subtitle_or_dialogue(line):
            continue
        fallback_lines.append(line)
    if not rows and fallback_lines:
        rows = ["- " + _replacement_strip_source_subtitle_dialogue(" ".join(fallback_lines))]
    body = "\n".join(row for row in rows if row).strip()
    if not body:
        body = _replacement_strip_source_subtitle_dialogue(analysis.get("visual") or analysis.get("frameNotes") or "")
    if not body:
        return ""
    return _replacement_excerpt(
        "当前片段原片镜头约束：\n%s\n字幕和人物说话台词不得使用原视频字幕、OCR 或原片口播转写；最终只以同款替换片段表中的用户口播稿为准。" % body,
        limit,
    )


def _replacement_safe_breakdown_evidence(segment, analysis, limit=900):
    analysis = analysis or {}
    report = str(analysis.get("report") or "")
    parts = [
        _markdown_section(report, "内容总览"),
        analysis.get("visual"),
        analysis.get("frameNotes"),
    ]
    cleaned = []
    for part in parts:
        value = _replacement_strip_source_subtitle_dialogue(part)
        if value:
            cleaned.append(value)
    text = "\n".join(cleaned).strip()
    return _replacement_excerpt(text, limit)

def _replacement_source_context_from_analysis(analysis=None):
    analysis = analysis or {}
    evidence = "\n".join([
        _replacement_excerpt(_replacement_strip_source_subtitle_dialogue(analysis.get("report")), 800),
        _replacement_excerpt(_replacement_strip_source_subtitle_dialogue(analysis.get("visual")), 500),
        _replacement_excerpt(_replacement_strip_source_subtitle_dialogue(analysis.get("frameNotes")), 500),
    ]).strip()
    lowered = evidence.lower()

    def clean_label(value, limit=80):
        import re as _re
        text = str(value or "").strip()
        text = _re.sub(r"^[\s>*\-•|]+", "", text)
        text = _re.sub(r"\*\*|`|“|”|\"", "", text)
        text = text.split("|", 1)[0].strip()
        text = _re.split(r"[。；;\n]", text, 1)[0].strip()
        return _replacement_excerpt(text, limit) if text else ""

    def first_match(patterns, limit=80):
        import re as _re
        for pattern in patterns:
            match = _re.search(pattern, evidence, _re.I | _re.S)
            if match:
                value = clean_label(match.group(1), limit)
                if value:
                    return value
        return ""

    explicit_category = first_match((
        r"(?:视频类型|内容类型|素材类型)\s*[:：]\s*([^\n。]+)",
        r"(?:一句话总结)\s*[:：]\s*([^。\n]+)",
    ), 90)
    product = first_match((
        r"(?:主推产品|核心道具|产品名称|目标产品)(?:（[^）]*）)?\s*[:：]\s*([^\n。]+)",
        r"(?:核心卖点)\s*[:：]\s*([^\n。]+)",
        r"(?:介绍|展示|讲解|推荐)\s*([^。\n，,]{2,60})",
        r"(?:这款|这一款|这台|这个)\s*([^。\n，,]{2,40})",
    ), 100)
    scene = first_match((
        r"(?:场景|道具/场景|拍摄场景)(?:（[^）]*）)?\s*[:：]\s*([^\n。]+)",
        r"(?:背景是|场景为|位于)\s*([^。\n]+)",
        r"([^。\n，,]{2,40}(?:展厅|门店|直播间|办公室|棚拍|户外|室内|场景))",
    ), 100)
    role = first_match((
        r"(?:人物|主播|出镜人物|角色)(?:（[^）]*）)?\s*[:：]\s*([^\n。]+)",
        r"(?:一名|一位)([^。\n，,]{2,40})",
    ), 70)

    category = explicit_category or (scene + "相关短视频" if scene else (product + "相关短视频" if product else "原视频类别"))
    product = product or "原视频可见产品"
    role = role or "原视频人物"
    scene = scene or "原视频场景"
    return {
        "sourceCategory": category,
        "sourceRole": role,
        "sourceProductCategory": product,
        "sourceScene": scene,
        "evidence": evidence,
    }


def _replacement_source_entities_from_analysis(analysis=None):
    analysis = analysis or {}
    context = _replacement_source_context_from_analysis(analysis)
    evidence = str(context.get("evidence") or "").strip()
    lowered = evidence.lower()

    def contains_any(words):
        return any(word in evidence or word in lowered for word in words)

    scene_type = context.get("sourceScene") or "源视频场景"

    role = context.get("sourceRole") or "视频人物"
    if contains_any(("男销售", "销售", "顾问", "讲车", "介绍车")):
        role = "销售顾问"
    elif contains_any(("主播", "达人", "模特")):
        role = "带货人物"

    people = []
    if contains_any(("人", "男", "女", "销售", "顾问", "主播", "模特", "讲解")):
        people.append({
            "slot": "person_1",
            "role": role,
            "appearance": _replacement_excerpt(evidence or role, 180),
        })

    product_category = context.get("sourceProductCategory") or "源视频产品"    if product_category in ("源视频产品", "原视频可见产品") and contains_any((
            "车", "汽车", "车型", "新能源车", "轿车", "SUV", "suv", "车身", "车标", "凯美瑞")):
        product_category = "汽车"
    products = [{
        "slot": "product_1",
        "category": product_category,
        "appearance": _replacement_excerpt(evidence or product_category, 220),
    }]
    scenes = [{
        "slot": "scene_1",
        "type": scene_type,
        "appearance": _replacement_excerpt(evidence or scene_type, 220),
    }]
    return {
        "mode": "source_entity_replacement",
        "people": people,
        "products": products,
        "scenes": scenes,
        "replacementRules": (
            "原片人物槽位替换为上传授权人物或虚拟模特的完整外观，包括脸、发型、服装、体型和配饰；动作、职业语境、"
            "站位和镜头关系沿用源视频；人物台词按当前声音来源规则处理；未上传产品图时保留原片产品，上传产品图时强制替换为上传产品；"
            "未上传场景图时保留原片场景，上传场景图时强制替换为上传场景。"
        ),
    }


def _replacement_source_entity_lock_text(job_or_analysis=None):
    value = job_or_analysis or {}
    if "sourceReplacementEntities" in value:
        entities = value.get("sourceReplacementEntities") or {}
    elif "breakdownAnalysis" in value:
        entities = _replacement_source_entities_from_analysis(value.get("breakdownAnalysis") or {})
    else:
        entities = _replacement_source_entities_from_analysis(value)
    if not isinstance(entities, dict):
        return ""

    def summarize(items, key):
        out = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            slot = str(item.get("slot") or "").strip()
            label = str(item.get(key) or item.get("role") or item.get("category") or item.get("type") or "").strip()
            if slot or label:
                out.append("%s=%s" % (slot or "slot", label or "源片实体"))
        return "；".join(out)

    return (
        "源视频实体替换：\n"
        "- 原片人物槽位：%s。替换为上传授权人物或虚拟模特的完整外观，包括脸、发型、服装、体型和配饰；只保留原片动作、职业语境、站位和镜头关系；人物台词按当前声音来源规则处理。\n"
        "- 原片产品槽位：%s。未上传产品图时保留原片产品；上传产品图时必须强制替换为上传产品，产品出现时间、摆放/持握方式、展示节奏和镜头角度按源视频。\n"
        "- 原片场景槽位：%s。未上传场景图时保留原片场景；上传场景图时必须强制替换为上传场景，并尽量沿用源视频镜头节奏和主体关系。\n"
        "- %s"
        % (
            summarize(entities.get("people"), "role") or "无明确人物",
            summarize(entities.get("products"), "category") or "源视频产品",
            summarize(entities.get("scenes"), "type") or "源视频场景",
            str(entities.get("replacementRules") or "").strip(),
        )
    )


def _replacement_source_lock_text(job_or_analysis=None, segment=None):
    value = job_or_analysis or {}
    if "breakdownAnalysis" in value or "referencePreflight" in value:
        preflight = value.get("referencePreflight") or {}
        context = _replacement_source_context_from_analysis(value.get("breakdownAnalysis") or {})
        source_category = preflight.get("sourceCategory") or context.get("sourceCategory") or "源视频类别"
        source_role = preflight.get("sourceRole") or context.get("sourceRole") or "源视频人物角色"
        source_product = preflight.get("sourceProductCategory") or context.get("sourceProductCategory") or "源视频产品类别"
    else:
        context = _replacement_source_context_from_analysis(value)
        source_category = context.get("sourceCategory") or "源视频类别"
        source_role = context.get("sourceRole") or "源视频人物角色"
        source_product = context.get("sourceProductCategory") or "源视频产品类别"
    has_product_ref = bool(value.get("productImageUrls")) if isinstance(value, dict) else False
    scene_fallback_active = _replacement_ai_scene_fallback_active(segment)
    has_scene_ref = bool(value.get("sceneImageUrl")) if isinstance(value, dict) else False
    if scene_fallback_active:
        has_scene_ref = False
    product_lock = (
        "原片产品槽位必须替换为上传产品，不要求保留原片产品类别；产品展示节奏、位置关系和镜头角度尽量沿用源视频。"
        if has_product_ref else "保留原片产品类别：%s。" % source_product
    )
    if scene_fallback_active:
        scene_lock = "上传场景与原片动作冲突时，本段改用 AI 生成同类场景；产品替换仍必须以上传产品图为准。"
    else:
        scene_lock = (
            "原片场景槽位必须替换为上传场景，不要求保留原片场景类型；人物动作、站位和镜头节奏尽量沿用源视频。"
            if has_scene_ref else "保留原片场景类型、镜头节奏、主体数量和营销结构。"
        )
    return (
        "源视频锁定：\n"
        "- 保留原片内容类别：%s。\n"
        "- 保留原片人物角色：%s。\n"
        "- %s\n"
        "- %s\n"
        "- 人物参考图只用于新主角的脸、发型、服装、体型和配饰一致性，不复制参考图里的产品、行业、房间、直播间、化妆品、道具、字幕或背景。\n"
        "- 产品参考图只控制目标产品；场景参考图只控制目标场景。\n"
        "- 未上传产品或场景时保留源视频对应槽位；上传后必须以上传素材为准完成替换。"
        % (source_category, source_role, product_lock, scene_lock)
    )


def _replacement_reference_retry_note(job=None, segment=None):
    job = job or {}
    segment = segment or {}
    if int(segment.get("driftRetryCount") or 0) <= 0:
        return ""
    risks = (job.get("referencePreflight") or {}).get("referenceRisks") or []
    risk_text = "; ".join(str(item.get("type") or "") for item in risks if isinstance(item, dict))
    return (
        "跑偏重试：上一版生成偏离了原片主题或人物角色。请强化源视频锁定，把人物图只当作新主角完整外观参考，并忽略存在风险的参考图上下文%s。"
        % ("：" + risk_text if risk_text else "")
    )


def _replacement_manual_defect_retry_note(segment=None):
    segment = segment or {}
    note = str(segment.get("manualDefectNote") or "").strip()
    if not note:
        return ""
    note = _replacement_excerpt(note, 260)
    return (
        "手动瑕疵重生：上一版该片段存在瑕疵：%s。"
        "本次必须针对该问题修正，不能再次出现；同时保留原片动作、镜头节奏、当前声音来源规则和已上传人物/产品/场景替换规则。"
        % note
    )


def _build_replacement_prompt(segment, analysis, product_notes, model_notes):
    segment = segment or {}
    analysis = analysis or {}
    start = float(segment.get("start") or 0)
    end = float(segment.get("end") or max(start + 8, 8))
    shot_constraints = _replacement_current_shot_constraints(segment, analysis)
    source = _replacement_safe_breakdown_evidence(segment, analysis)
    return (
        "生成一段新的电商短视频片段：匹配原视频的节奏、镜头语言和营销结构，但不要复制原片素材。\n"
        "片段：%.1f-%.1f 秒，竖屏 9:16，720p。\n"
        "%s\n"
        "%s\n"
        "%s\n"
        "上传产品必须保持视觉一致：保留外形、颜色、包装文字和 Logo。只有在生成稳定性需要时，才允许轻微调整场景和手部动作。\n"
        "人物身份：%s。只使用用户提供的授权真人或虚拟模特参考作为人物身份来源。\n"
        "产品参考：%s。\n"
        "原片拆解证据：\n%s\n"
        "只输出该片段的一条连贯镜头。字幕安全：不要复刻、保留或新增原片顶部/底部字幕、营销大字、弹幕式文字或屏幕贴纸文字；"
        "必须出现的品牌和 Logo 只按上传产品参考保留，不能凭空造字。"
        % (
            start,
            end,
            shot_constraints,
            _replacement_source_lock_text(analysis),
            _replacement_source_entity_lock_text(analysis),
            _replacement_excerpt(model_notes or "虚拟模特身份", 360),
            _replacement_excerpt(product_notes or "上传产品参考图", 420),
            source or "没有可用的详细拆解证据。",
        )
    )


def _build_replacement_keyframe_prompt(segment, analysis, product_notes, model_notes, has_previous_anchor=False):
    segment = segment or {}
    analysis = analysis or {}
    start = float(segment.get("start") or 0)
    end = float(segment.get("end") or max(start + 8, 8))
    source = "\n".join(filter(None, [
        _replacement_current_shot_constraints(segment, analysis, limit=700),
        _replacement_safe_breakdown_evidence(segment, analysis, limit=500),
    ])).strip()
    continuity = (
        "与上一段替换关键帧保持连续：人物身份、服装、产品外观和整体色彩不要跳变。"
        if has_previous_anchor else ""
    )
    return (
        "为 %.1f-%.1f 秒片段生成一张竖屏 9:16 电商短视频开场关键帧。"
        "原视频帧只用于构图、机位和大致姿态参考。"
        "可见产品必须替换为上传产品参考，并尽量保留外形、瓶盖或车身结构、材质、包装文字、Logo 和颜色。"
        "人物身份只使用授权真人或虚拟模特参考，不要生成其他人物。%s"
        "%s "
        "输出必须适合作为图生视频第一帧：脸部清晰、产品清晰、不要多余手部、不要扭曲 Logo、不要出现不可读包装。"
        "字幕安全：不要复刻、保留或新增原片顶部/底部中文字幕、营销大字、弹幕式文字或屏幕贴纸文字；需要的口播字幕只由后期字幕层合成。"
        "产品：%s。人物：%s。"
        "原片拆解证据：%s"
        % (
            start,
            end,
            continuity,
            _replacement_source_lock_text(analysis),
            _replacement_excerpt(product_notes or "上传产品参考图", 420),
            _replacement_excerpt(model_notes or "授权真人或虚拟模特参考", 360),
            source or "没有可用的详细拆解证据。",
        )
    )


def _build_replacement_video_prompt(segment, base_prompt, has_keyframe=False, has_previous_anchor=False):
    locks = []
    if has_keyframe:
        locks.append(
            "使用第一张参考图作为开场关键帧，保持其中的人脸、产品包装、服装、场景布局和产品位置一致。"
        )
    if has_previous_anchor:
        locks.append(
            "延续上一段参考图的视觉连续性，避免片段之间出现人物身份、产品设计、服装、光线方向或场景风格跳变。"
        )
    locks.append(
        "不要把上传产品替换成通用物品；在模型能力范围内尽量保留 Logo、包装文字、外形和颜色。"
    )
    locks.append(
        "字幕安全：不要复刻、保留或新增原片顶部/底部中文字幕、营销大字、弹幕式文字或屏幕贴纸文字；需要的口播字幕只由后期字幕层合成。"
    )
    return "\n".join(locks + [_replacement_strip_source_subtitle_dialogue(base_prompt)]).strip()


def _build_replacement_video_request(job, segment, prompt, image_urls):
    """Build a reference-to-video request without falling back to a text-only model.

    The replacement flow relies on its generated keyframe, product photos and authorized
    model reference. Sending them to a text-to-video route silently loses those locks.
    """
    job = job or {}
    segment = segment or {}
    model = _replacement_model_candidates(job)[0]
    refs = [str(url).strip() for url in (image_urls or []) if str(url).strip()]
    if not refs:
        raise RuntimeError("同款替换缺少关键帧参考图")
    duration = max(1, min(int(round(float(segment.get("duration") or 8))), 15))
    return model, {
        "prompt": str(prompt or "")[:1800],
        "image_urls": refs,
        "params": {
            "duration": duration,
            "resolution": job.get("resolution") or "720p",
            "aspect_ratio": job.get("aspectRatio") or "9:16",
        },
    }


def _lk888_video_edit_resolution(value, model=None):
    value = str(value or "").strip()
    model_name = str(model or "").strip().lower()
    if "happyhorse" in model_name:
        if value.lower() == "720p":
            return "720P"
        if value.lower() == "1080p":
            return "1080P"
        return value or "720P"
    if value:
        return value.lower()
    return "720p"


def _principal_actor_min_confidence():
    try:
        value = float(os.getenv("VIDEO_REPLACE_PRINCIPAL_MIN_CONFIDENCE", "0.65") or 0.65)
    except (TypeError, ValueError):
        value = 0.65
    if value > 1:
        value /= 100.0
    return max(0.0, min(value, 1.0))


def _parse_principal_actor_response(raw, frames):
    import json as _json
    import re as _re

    match = _re.search(r"\{[\s\S]*\}", str(raw or ""))
    if not match:
        raise RuntimeError("principal_actor_extract_invalid_response")
    try:
        parsed = _json.loads(match.group(0))
    except Exception as exc:
        raise RuntimeError("principal_actor_extract_invalid_response") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("principal_actor_extract_invalid_response")

    frame_count = len(frames or [])
    if frame_count <= 0:
        raise RuntimeError("principal_actor_frames_missing")
    try:
        frame_index = int(parsed.get("bestFrameIndex", parsed.get("bestFrame", 1)) or 1)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("principal_actor_frame_invalid") from exc
    frame_index = max(1, min(frame_index, frame_count))

    source_box = parsed.get("bbox") or parsed.get("boundingBox") or {}
    if isinstance(source_box, (list, tuple)) and len(source_box) >= 4:
        source_box = {
            "x": source_box[0], "y": source_box[1],
            "width": source_box[2], "height": source_box[3],
        }
    if not isinstance(source_box, dict):
        raise RuntimeError("principal_actor_bbox_invalid")
    try:
        x = float(source_box.get("x", source_box.get("left", 0)) or 0)
        y = float(source_box.get("y", source_box.get("top", 0)) or 0)
        if "width" in source_box or "height" in source_box:
            width = float(source_box.get("width", 0) or 0)
            height = float(source_box.get("height", 0) or 0)
        else:
            width = float(source_box.get("right", 0) or 0) - x
            height = float(source_box.get("bottom", 0) or 0) - y
    except (TypeError, ValueError) as exc:
        raise RuntimeError("principal_actor_bbox_invalid") from exc
    x = max(0.0, min(1000.0, x))
    y = max(0.0, min(1000.0, y))
    width = max(0.0, min(1000.0 - x, width))
    height = max(0.0, min(1000.0 - y, height))
    if width < 1 or height < 1:
        raise RuntimeError("principal_actor_bbox_invalid")

    try:
        confidence = float(parsed.get("confidence", parsed.get("score", 0)) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence > 1:
        confidence /= 100.0
    confidence = max(0.0, min(confidence, 1.0))
    return {
        "status": "detected" if confidence >= _principal_actor_min_confidence() else "manual_required",
        "bestFrameIndex": frame_index,
        "bbox": {
            "x": int(round(x)), "y": int(round(y)),
            "width": int(round(width)), "height": int(round(height)),
        },
        "confidence": round(confidence, 4),
        "description": str(parsed.get("description") or parsed.get("actorDescription") or "").strip()[:500],
        "evidence": str(parsed.get("evidence") or parsed.get("reason") or "").strip()[:500],
        "previewPath": "",
    }


def _crop_principal_actor_preview(actor, frames, out_dir):
    actor = dict(actor or {})
    try:
        from PIL import Image
        frame_index = max(1, min(int(actor.get("bestFrameIndex") or 1), len(frames or [])))
        frame = (frames or [])[frame_index - 1]
        frame_path = str((frame or {}).get("path") or "").strip()
        if not frame_path or not os.path.isfile(frame_path):
            raise RuntimeError("principal_actor_frame_missing")
        with Image.open(frame_path) as source:
            image = source.convert("RGB")
            width, height = image.size
            box = actor.get("bbox") or {}
            x = float(box.get("x") or 0) / 1000.0 * width
            y = float(box.get("y") or 0) / 1000.0 * height
            right = x + float(box.get("width") or 0) / 1000.0 * width
            bottom = y + float(box.get("height") or 0) / 1000.0 * height
            pad_x = max(2.0, (right - x) * 0.08)
            pad_y = max(2.0, (bottom - y) * 0.08)
            crop_box = (
                max(0, int(round(x - pad_x))),
                max(0, int(round(y - pad_y))),
                min(width, int(round(right + pad_x))),
                min(height, int(round(bottom + pad_y))),
            )
            if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
                raise RuntimeError("principal_actor_bbox_invalid")
            os.makedirs(out_dir, exist_ok=True)
            preview_path = os.path.join(out_dir, "principal_actor_preview.jpg")
            image.crop(crop_box).save(preview_path, format="JPEG", quality=92)
        actor["bestFrameIndex"] = frame_index
        actor["framePath"] = frame_path
        actor["previewPath"] = preview_path
        return actor
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("principal_actor_preview_failed") from exc


def _extract_replacement_principal_actor(source_path, analysis, out_dir):
    analysis = analysis or {}
    frames = _extract_breakdown_frames(source_path, os.path.join(out_dir, "principal_actor"), 6)
    if not frames:
        error = RuntimeError("principal_actor_frames_missing")
        _replacement_error_id(
            "video_replace_principal_actor_extract_failed", error,
            source_video=source_path or "",
        )
        return {"status": "failed", "error": str(error), "previewPath": ""}
    media = [_image_data_url(item.get("path")) for item in frames if item.get("path")]
    media = [value for value in media if value]
    prompt = (
        "你是视频主角定位器。以下是同一源视频按时间抽取的画面。只识别一个需要被替换的主角，"
        "不要把产品、背景或其他人物当作主角。输出严格 JSON，不要 Markdown："
        '{"bestFrame":1,"bbox":{"x":0,"y":0,"width":1000,"height":1000},'
        '"confidence":0.0,"description":"主角外观和位置", "evidence":"选择依据"}。'
        "bbox 必须是 0-1000 归一化坐标，bestFrame 从 1 开始。源视频分析上下文：%s"
        % _replacement_excerpt(analysis.get("visual") or analysis.get("report") or "", 700)
    )
    try:
        raw = lk888_vision(prompt, media, max_tokens=500)
        actor = _parse_principal_actor_response(raw, frames)
        actor = _crop_principal_actor_preview(actor, frames, out_dir)
        actor["candidatePaths"] = [
            str(item.get("path") or "").strip() for item in frames if item.get("path")
        ]
        return actor
    except Exception as exc:
        error_id = _replacement_error_id(
            "video_replace_principal_actor_extract_failed", exc,
            source_video=source_path or "",
        )
        if "principal_actor_extract_invalid_response" in str(exc):
            candidate_paths = [
                str(item.get("path") or "").strip()
                for item in frames if item.get("path")
            ]
            return {
                "status": "manual_required",
                "bestFrameIndex": 1,
                "bbox": {"x": 0, "y": 0, "width": 1000, "height": 1000},
                "confidence": 0.0,
                "description": "原片主角需人工确认",
                "evidence": "自动主角识别返回格式异常，请从候选帧中手动选择原片主角。",
                "previewPath": candidate_paths[0] if candidate_paths else "",
                "candidatePaths": candidate_paths,
                "error": "principal_actor_extract_invalid_response",
                "errorId": error_id,
            }
        return {
            "status": "failed",
            "error": str(exc)[:180],
            "errorId": error_id,
            "previewPath": "",
        }


def _validate_person_reference_paths(paths):
    selected = [str(path) for path in (paths or []) if path and os.path.isfile(path)][:3]
    if not selected:
        raise RuntimeError("person_reference_full_body_required")
    for path in selected:
        try:
            from PIL import Image
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            raise RuntimeError("person_reference_invalid") from exc
    return selected


def _replacement_split_script_for_timing(script, max_chars=18):
    text = re.sub(r"\s+", " ", str(script or "").strip())
    if not text:
        return []
    try:
        limit = int(max_chars or 18)
    except (TypeError, ValueError):
        limit = 18
    limit = max(6, min(limit, 32))
    chunks = []
    current = []
    punctuation = set("，。！？；,.!?;:：")
    for char in text:
        current.append(char)
        compact_len = len(re.sub(r"\s+", "", "".join(current)))
        if char in punctuation or compact_len >= limit:
            value = "".join(current).strip()
            if value:
                chunks.append(value)
            current = []
    tail = "".join(current).strip()
    if tail:
        chunks.append(tail)
    return chunks or [text]


def _replacement_build_dialogue_timing(script, duration_sec, max_chars=18):
    parts = _replacement_split_script_for_timing(script, max_chars=max_chars)
    if not parts:
        return []
    try:
        duration = float(duration_sec or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    duration = max(0.01, duration)
    total_cs = max(1, int(round(duration * 100)))
    while len(parts) > total_cs:
        merged = []
        for i in range(0, len(parts), 2):
            value = parts[i]
            if i + 1 < len(parts):
                value = (value + parts[i + 1]).strip()
            merged.append(value)
        parts = merged
    weights = [max(1, len(re.sub(r"\s+", "", item))) for item in parts]
    total_weight = max(1, sum(weights))
    timing = []
    cursor = 0
    cumulative = 0
    for i, item in enumerate(parts):
        cumulative += weights[i]
        if i == len(parts) - 1:
            end_cs = total_cs
        else:
            remaining = len(parts) - i - 1
            target = int(round(total_cs * cumulative / total_weight))
            min_end = cursor + 1
            max_end = total_cs - remaining
            end_cs = max(min_end, min(target, max_end))
        timing.append({
            "startSec": round(cursor / 100.0, 2),
            "endSec": round(end_cs / 100.0, 2),
            "text": str(item or "").strip(),
        })
        cursor = end_cs
    return timing


def _replacement_dialogue_timing_prompt(segment):
    segment = segment or {}
    cached = str(segment.get("dialogueTimingPrompt") or "").strip()
    if cached:
        return cached
    timing = [item for item in (segment.get("dialogueTiming") or []) if isinstance(item, dict)]
    if not timing:
        try:
            duration = float(segment.get("dialogueAudioDurationSec") or segment.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        script = str(segment.get("script") or "").strip()
        if script and duration > 0:
            timing = _replacement_build_dialogue_timing(script, duration)
    if not timing:
        return ""
    try:
        duration = float(segment.get("dialogueAudioDurationSec") or timing[-1].get("endSec") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        duration = float(timing[-1].get("endSec") or 0.0)
    lines = [
        "口播时间表：最终视频人物必须严格按下列时间说话，口型、停顿和说话节奏以用户口播稿为准，不沿用原片台词。",
        "本段最终口播音频时长：%.2f 秒" % duration,
        "严格按下列时间说话：",
    ]
    for item in timing[:24]:
        try:
            start = float(item.get("startSec") or 0.0)
            end = float(item.get("endSec") or 0.0)
        except (TypeError, ValueError):
            continue
        text = _replacement_excerpt(item.get("text") or "", 120)
        if text:
            lines.append("%.2f-%.2f 秒：%s" % (start, end, text))
    if len(timing) > 24:
        lines.append("剩余台词继续按同一音频节奏自然说完。")
    return "\n".join(lines).strip()

def _build_principal_replacement_prompt(job, segment):
    job = job or {}
    segment = segment or {}
    actor = job.get("principalActor") or {}
    actor_description = str(actor.get("description") or "原视频中的唯一主角").strip()
    prompt_audio_mode = str(job.get("promptAudioMode") or job.get("dialogueAudioMode") or "").strip()
    audio_mode = _replacement_audio_mode({"audioMode": prompt_audio_mode or job.get("audioMode")})
    script = str(segment.get("script") or "").strip()
    dialogue_timing = _replacement_dialogue_timing_prompt(segment) if audio_mode in ("tts", "uploaded") else ""
    if audio_mode == "tts" and script:
        dialogue_rule = (
            "保留原片主角的动作、姿势、站位、镜头路径、构图和时长；"
            "本段人物说话台词必须以用户修改后的口播稿为准：%s。"
            "声音由 AI 音色配音生成，后续会按该口播音频同步口型；不要沿用原片台词。"
        ) % _replacement_excerpt(script, 260)
    elif audio_mode == "uploaded" and script:
        dialogue_rule = (
            "保留原片主角的动作、姿势、站位、镜头路径、构图和时长；"
            "本段人物说话台词必须与上传配音和口播稿一致：%s。"
            "后续会裁切上传配音并按该音频同步口型；不要沿用原片台词。"
        ) % _replacement_excerpt(script, 260)
    else:
        dialogue_rule = "保留原片主角的动作、姿势、站位、镜头路径、构图、时长、原音和台词。"
    product_rule = (
        "上传了产品图：必须把原片产品槽位强制替换成上传产品，保持上传产品的外形、颜色、Logo 和主要包装文字；原片产品的出现时间、摆放/持握方式、展示节奏和镜头角度尽量沿用源视频。"
        if job.get("productImageUrls")
        else "未上传产品图：保留原视频里的原产品，不要新增或替换成其他产品。"
    )
    if _replacement_ai_scene_fallback_active(segment):
        scene_rule = _replacement_ai_scene_fallback_note(job, segment)
    elif job.get("sceneImageUrl"):
        scene_rule = "上传了场景图：必须把原片场景槽位强制替换成上传场景，保持上传场景的主要空间、环境、光线和背景特征；源视频动作、站位、镜头节奏尽量沿用。"
    else:
        scene_rule = "未上传场景图：保留原视频里的原场景，不要新增或替换成其他场景。"
    return "\n".join(filter(None, [
        dialogue_timing,
        "单主角整身替换：只替换原视频中的一个主角（%s）。" % actor_description,
        _replacement_manual_defect_retry_note(segment),
        _replacement_ai_scene_fallback_note(job, segment),
        "使用上传人物参考图的完整外观，包括脸、发型、服装、体型和配饰；不要保留原片主角的外观。",
        dialogue_rule,
        product_rule,
        scene_rule,
        "其他人物和道具必须保持原视频一致，不得替换或新增其他人物；只允许保留真实物体上的 Logo、招牌和产品包装文字。",
        "字幕安全：不要复刻、保留或新增原片顶部/底部字幕、营销大字、弹幕式文字或屏幕贴纸文字；需要的中文字幕只由后期字幕层合成。",
        _replacement_strip_source_subtitle_dialogue(segment.get("prompt")),
    ])).strip()


def _build_principal_video_edit_request(job, segment, source_video_url):
    """Build the strict source-video request used for one-protagonist replacement."""
    job = job or {}
    segment = segment or {}
    source_url = str(source_video_url or "").strip()
    if not _is_remote_fetchable_media_url(source_url):
        raise RuntimeError("principal_source_video_required")
    actor_status = str((job.get("principalActor") or {}).get("status") or "").strip()
    if actor_status not in ("detected", "manual"):
        raise RuntimeError("principal_source_actor_required")
    person_refs = [str(value or "").strip() for value in (job.get("personReferenceUrls") or [])]
    person_refs = [value for value in person_refs if value]
    if not person_refs or any(not _is_remote_fetchable_media_url(value) for value in person_refs):
        raise RuntimeError("principal_person_reference_required")
    refs = list(person_refs)
    for value in (job.get("productImageUrls") or []):
        value = str(value or "").strip()
        if value:
            refs.append(value)
    scene_url = str(job.get("sceneImageUrl") or "").strip()
    if scene_url and not _replacement_ai_scene_fallback_active(segment):
        refs.append(scene_url)
    refs = list(dict.fromkeys(refs))
    if any(not _is_remote_fetchable_media_url(value) for value in refs):
        raise RuntimeError("principal_reference_media_required")
    duration = max(1, min(int(round(float(segment.get("duration") or 8))), 15))
    model = _principal_replacement_model(job)
    resolution = _lk888_video_edit_resolution(job.get("resolution") or "720p", model)
    return model, {
        "prompt": _build_principal_replacement_prompt(job, segment)[:3200],
        "video": source_url,
        "images": refs,
        "resolution": resolution,
        "audio_setting": "origin",
        "watermark": False,
        "video_url": source_url,
        "video_urls": [source_url],
        "reference_video": source_url,
        "image_urls": refs,
        "params": {
            "video": source_url,
            "images": refs,
            "video_url": source_url,
            "video_urls": [source_url],
            "reference_video": source_url,
            "duration": duration,
            "resolution": resolution,
            "audio_setting": "origin",
            "watermark": False,
            "aspect_ratio": job.get("aspectRatio") or "9:16",
        },
    }


def _build_hybrid_video_edit_request(job, segment, source_video_url):
    job = job or {}
    segment = segment or {}
    source_url = str(source_video_url or "").strip()
    if not source_url:
        raise RuntimeError("video_replace_source_segment_url_missing")
    if _principal_replacement_enabled(job):
        model, payload = _build_principal_video_edit_request(job, segment, source_url)
        payload["model_candidates"] = _replacement_model_candidates(job)
        return model, payload
    refs = []
    for value in (job.get("productImageUrls") or []):
        value = str(value or "").strip()
        if value:
            refs.append(value)
    if not _replacement_no_person_mode(job):
        for value in [job.get("modelFaceUrl")] + list(job.get("faceSourceUrls") or []):
            value = str(value or "").strip()
            if value:
                refs.append(value)
    if job.get("sceneImageUrl") and not _replacement_ai_scene_fallback_active(segment):
        refs.append(str(job.get("sceneImageUrl")).strip())
    continuity_url = str(segment.get("continuityFrameUrl") or "").strip()
    if continuity_url:
        refs.append(continuity_url)
    product_anchor_url = str(segment.get("productAnchorFrameUrl") or "").strip()
    if product_anchor_url:
        refs.append(product_anchor_url)
    if _replacement_action_control_enabled(job):
        for value in segment.get("actionFrameUrls") or []:
            value = str(value or "").strip()
            if value:
                refs.append(value)
    refs = list(dict.fromkeys(refs))
    if not _is_remote_fetchable_media_url(source_url) or any(
            not _is_remote_fetchable_media_url(value) for value in refs):
        raise RuntimeError("video_replace_remote_media_required")
    prompt_audio_mode = str(job.get("promptAudioMode") or job.get("dialogueAudioMode") or "").strip()
    audio_mode = _replacement_audio_mode({"audioMode": prompt_audio_mode or job.get("audioMode")})
    dialogue_timing = _replacement_dialogue_timing_prompt(segment) if audio_mode in ("tts", "uploaded") else ""
    motion_rule = (
        "保留源视频的产品展示节奏、镜头路径、构图和物体运动。"
        if _replacement_no_person_mode(job)
        else "保留源视频的人物动作、时间节奏、镜头路径和构图。"
    )
    prompt = "\n".join(filter(None, [
        dialogue_timing,
        _replacement_strip_source_subtitle_dialogue(segment.get("prompt")),
        _replacement_source_lock_text(job, segment),
        _replacement_source_entity_lock_text(job),
        _replacement_reference_retry_note(job, segment),
        _replacement_manual_defect_retry_note(segment),
        _replacement_ai_scene_fallback_note(job, segment),
        motion_rule,
        (
            "上一段生成结果参考帧用于跨片段连续性：保持同一个新人设、脸部观感、发型和服装连续，"
            "但仍以用户上传授权人物图作为最终身份来源。"
        ) if continuity_url else "",
        (
            "原片动作关键帧只作为动作、姿态、站位、镜头和构图参考；"
            "不要把原片动作关键帧中的人物脸当作身份参考，人物身份必须以上传授权人物图为准。"
        ) if (_replacement_action_control_enabled(job) and (segment.get("actionFrameUrls") or [])) else "",
        "使用上传的授权人物参考来保持新主角的脸、发型、服装、体型和配饰一致；不要保留原片主角的脸、发型、服装、体型或配饰。" if (not _replacement_no_person_mode(job) and (job.get("modelFaceUrl") or job.get("faceSourceUrls"))) else "",
        "将可见产品替换为上传产品参考，并保留外形、颜色、Logo 和主要包装文字。",
        (
            "产品锚定帧展示了该片段画面中产品被替换后的准确效果：生成视频中产品的外形、颜色、"
            "Logo、包装文字、材质和摆放位置必须与产品锚定帧保持完全一致。"
        ) if product_anchor_url else "",
        "字幕安全：不要复刻、保留或新增原片顶部/底部中文字幕、营销大字、弹幕式文字或屏幕贴纸文字；需要的口播字幕只由后期字幕层合成。",
        (
            "上传了场景图或场景描述时，必须将原片场景槽位替换为上传场景；"
            "未上传场景图时才保留源视频场景。场景提示：" + str(job.get("scenePrompt")).strip()
        ) if ((job.get("sceneImageUrl") or job.get("scenePrompt")) and not _replacement_ai_scene_fallback_active(segment)) else "",
    ])).strip()
    duration = max(1, min(int(round(float(segment.get("duration") or 8))), 15))
    candidates = _replacement_model_candidates(job)
    return candidates[0], {
        "prompt": prompt[:1800],
        "source_video_url": source_url,
        "image_urls": refs,
        "model_candidates": candidates,
        "params": {
            "duration": duration,
            "resolution": job.get("resolution") or "720p",
            "aspect_ratio": job.get("aspectRatio") or "9:16",
        },
    }


def _replacement_remote_video_payload(payload):
    payload = dict(payload or {})
    payload.pop("source_video_url", None)
    payload.pop("model_candidates", None)
    return payload


def _replacement_remote_video_payload_for_model(payload, model):
    remote = _replacement_remote_video_payload(payload)
    params = dict(remote.get("params") or {})
    model_name = str(model or "").strip().lower()
    if "happyhorse" in model_name:
        params["resolution"] = _lk888_video_edit_resolution(params.get("resolution") or "720p", model)
    remote["params"] = params
    return remote


def _run_hybrid_talking_segment(job, segment):
    job = job or {}
    segment = segment or {}
    script = str(segment.get("script") or "").strip()
    avatar_url = str(segment.get("keyframeUrl") or "").strip()
    if not _is_remote_fetchable_media_url(avatar_url):
        avatar_url = str(segment.get("keyframePath") or "").strip()
    if not (avatar_url and (os.path.isfile(avatar_url) or _is_remote_fetchable_media_url(avatar_url))):
        avatar_url = str(job.get("modelFaceUrl") or "").strip()
    if not (avatar_url and (os.path.isfile(avatar_url) or _is_remote_fetchable_media_url(avatar_url))):
        avatar_url = str((job.get("faceSourcePaths") or [""])[0] or "").strip()
    if not script:
        raise RuntimeError("video_replace_talking_script_missing")
    if not (avatar_url and (os.path.isfile(avatar_url) or _is_remote_fetchable_media_url(avatar_url))):
        raise RuntimeError("video_replace_avatar_not_remote_or_local")
    segment["prompt"] = str(segment.get("prompt") or (
        "数字人正对镜头自然口播，保持上传产品、人物身份和场景稳定，口型与音频同步"
    )).strip()
    audio_mode = _replacement_audio_mode(job)
    if audio_mode == "uploaded":
        segment["status"] = "audio_clip"
        _replacement_emit_stage(
            job, segment, "audio_clip",
            "生成片段 %s：裁切上传配音用于口型同步" % (segment.get("index") or 1)
        )
        sound_url = _replacement_uploaded_audio_segment_url(job, segment)
    else:
        segment["status"] = "tts"
        _replacement_emit_stage(job, segment, "tts", "生成片段 %s：合成口播音频" % (segment.get("index") or 1))
        sound_url = lk888_tts_voice(script, job.get("voiceId") or "Zephyr", cancel_check=_replacement_cancel_check(job))
        segment["ttsUrl"] = sound_url
    scene_url = str(job.get("sceneImageUrl") or "").strip()
    if not _is_remote_fetchable_media_url(scene_url):
        scene_url = None
    segment["status"] = "digital_human"
    _replacement_emit_stage(job, segment, "digital_human", "生成片段 %s：生成数字人口播视频" % (segment.get("index") or 1))
    return lk888_digital_human(
        avatar_url,
        sound_url,
        prompt=segment["prompt"],
        mode=job.get("digitalHumanMode") or "std",
        scene_url=scene_url,
        cancel_check=_replacement_cancel_check(job),
    )


def _run_hybrid_lipsynced_replacement_segment(job, segment):
    job = job or {}
    segment = segment or {}
    idx = int(segment.get("index") or 1)
    audio_mode = _replacement_audio_mode(job)
    if audio_mode not in ("tts", "uploaded"):
        return _run_hybrid_non_talking_segment(job, segment)
    video_job = dict(job)
    video_job["promptAudioMode"] = audio_mode
    video_job["audioMode"] = "source"
    video_job["temporaryMaterialIds"] = job.setdefault("temporaryMaterialIds", [])
    segment["lipSyncStatus"] = "skipped_prompt_driven"
    segment["status"] = "dialogue_timing"
    _replacement_emit_stage(
        job, segment, "dialogue_timing",
        "生成片段 %s：准备最终口播音频并计算台词时间表" % idx,
    )
    _replacement_prepare_dialogue_timing_for_prompt(job, segment)
    _replacement_emit_stage(
        job, segment, "video_edit",
        "生成片段 %s：按口播时间表生成同款替换画面" % idx,
    )
    final_path = _run_hybrid_non_talking_segment(video_job, segment)
    segment["lipSyncBaseVideoPath"] = final_path
    segment["audioMode"] = audio_mode
    segment["status"] = "audio_muxing"
    if audio_mode == "tts":
        _replacement_emit_stage(job, segment, "audio_muxing", "生成片段 %s：封装已准备的所选音色配音" % idx)
        _replace_replacement_segment_audio_with_tts(job, segment, final_path)
    else:
        _replacement_emit_stage(job, segment, "audio_muxing", "生成片段 %s：封装已裁切的上传配音片段" % idx)
        _replace_replacement_segment_audio_with_uploaded(job, segment, final_path)
    segment["audioStatus"] = "passed"
    segment["status"] = "qc"
    _replacement_emit_stage(job, segment, "qc", "生成片段 %s：执行换音轨后音频和视觉质检" % idx)
    qc = _run_replacement_segment_qc(job, segment, final_path)
    segment["qcFrames"] = list(qc.get("frames") or [])
    segment["qcChecks"] = dict(qc.get("checks") or {})
    if not qc.get("ok"):
        raise RuntimeError("replacement_qc_failed:%s" % (qc.get("code") or "unknown"))
    segment.update({
        "status": "done",
        "videoPath": final_path,
        "qcStatus": "passed",
        "error": "",
        "errorId": "",
    })
    return {"ok": True, "segment": segment, "path": final_path}

def _replacement_product_normalize_enabled():
    return _env_enabled("VIDEO_REPLACE_PRODUCT_NORMALIZE", "1")


def _replacement_product_normalize_validate_enabled():
    return _env_enabled("VIDEO_REPLACE_PRODUCT_NORMALIZE_VALIDATE", "1")


def _replacement_product_parallelism():
    try:
        value = int(os.getenv("VIDEO_REPLACE_PRODUCT_PARALLEL", "2") or 2)
    except (TypeError, ValueError):
        value = 2
    return max(1, min(value, 3))


def _validate_replacement_product_normalization(source_url, normalized_url):
    result = {
        "ok": True,
        "code": "ok",
        "sourceCategory": "",
        "normalizedCategory": "",
        "reason": "",
    }
    if not _replacement_product_normalize_validate_enabled():
        result["code"] = "disabled"
        return result
    if not (source_url and normalized_url):
        result.update({
            "ok": False,
            "code": "product_normalize_validation_missing_url",
            "reason": "missing source or normalized image url",
        })
        return result
    try:
        import json as _json
        import re as _re
        prompt = (
            "Compare two product reference images. The first image is the user's original product image. "
            "The second image is a normalized white-background output generated from the first image. "
            "Decide whether the second image still shows the same physical product type and main object as the first image. "
            "Reject if the product category changes, the main object changes, or the output introduces a different branded product. "
            "Ignore background, crop, lighting, and canvas size changes. "
            "Return strict JSON only: {\"sameProduct\":true|false,\"sourceCategory\":\"short category\","
            "\"normalizedCategory\":\"short category\",\"reason\":\"short reason\"}."
        )
        raw = lk888_vision(prompt, [source_url, normalized_url], max_tokens=260)
        match = _re.search(r"\{[\s\S]*\}", str(raw or ""))
        if not match:
            raise RuntimeError("product_normalize_validation_invalid_response")
        parsed = _json.loads(match.group(0))
        same = parsed.get("sameProduct")
        if same is None:
            same = parsed.get("same_product")
        same = same is True or str(same).strip().lower() in ("1", "true", "yes")
        result.update({
            "ok": bool(same),
            "code": "ok" if same else "product_normalize_mismatch",
            "sourceCategory": str(parsed.get("sourceCategory") or parsed.get("source_category") or "")[:80],
            "normalizedCategory": str(parsed.get("normalizedCategory") or parsed.get("normalized_category") or "")[:80],
            "reason": str(parsed.get("reason") or "")[:180],
        })
        if not result["reason"] and not same:
            result["reason"] = "normalized result is not the same product"
        return result
    except Exception as exc:
        return {
            "ok": False,
            "code": "product_normalize_validation_failed",
            "sourceCategory": "",
            "normalizedCategory": "",
            "reason": str(exc)[:180],
        }


def _normalize_replacement_product_image(path, out_dir, index):
    """产品图归一化已移除：始终使用用户原图。"""
    report = {
        "source": os.path.basename(str(path or "")),
        "normalized": False,
        "error": "product_normalize_removed",
        "fallbackReason": "using original product image",
        "selectedPath": path,
    }
    if not (path and os.path.isfile(path)):
        report["error"] = "product_image_missing"
        return path, report
    return path, report


def _process_replacement_product_refs(product_paths, norm_root, emit=None):
    paths = list(product_paths or [])[:3]
    if not paths:
        return [], []
    total = len(paths)
    parallelism = min(_replacement_product_parallelism(), total)
    results = [None] * total
    reports = [None] * total

    def notify(message):
        if callable(emit):
            try:
                emit(message)
            except Exception:
                pass

    def process_one(item):
        idx, path = item
        started = time.time()
        notify("正在上传产品图 %d/%d" % (idx, total))
        url, _resp = upload_asset_url(path, "同款替换产品图%d" % idx, "image")
        report = {
            "index": idx,
            "source": os.path.basename(str(path or "")),
            "normalized": False,
            "error": "product_normalize_removed",
            "fallbackReason": "using original product image",
            "selectedPath": path,
        }
        report["uploadUrl"] = url
        report["elapsedSec"] = round(time.time() - started, 3)
        notify("产品图 %d/%d 已完成" % (idx, total))
        return idx, url, report

    indexed = list(enumerate(paths, 1))
    if parallelism <= 1:
        for item in indexed:
            idx, url, report = process_one(item)
            results[idx - 1] = url
            reports[idx - 1] = report
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as pool:
            futures = [pool.submit(process_one, item) for item in indexed]
            for future in concurrent.futures.as_completed(futures):
                idx, url, report = future.result()
                results[idx - 1] = url
                reports[idx - 1] = report
    return [x for x in results if x], [x for x in reports if x]


def _facefusion_config():
    providers = [x.strip() for x in str(
        os.getenv("FACEFUSION_EXECUTION_PROVIDER", "coreml,cpu") or "coreml,cpu"
    ).split(",") if x.strip()]
    return {
        "bin": os.path.abspath(os.path.expanduser(os.getenv("FACEFUSION_BIN", "") or "")) if os.getenv("FACEFUSION_BIN") else "",
        "modelDir": os.path.abspath(os.path.expanduser(os.getenv("FACEFUSION_MODEL_DIR", "") or "")) if os.getenv("FACEFUSION_MODEL_DIR") else "",
        "licenseRef": str(os.getenv("FACEFUSION_LICENSE_REF", "") or "").strip(),
        "providers": providers,
    }


def _facefusion_preflight(config=None):
    config = dict(config or _facefusion_config())
    errors = []
    binary = config.get("bin") or ""
    model_dir = config.get("modelDir") or ""
    if not (binary and os.path.isfile(binary) and os.access(binary, os.X_OK)):
        errors.append("facefusion_not_configured")
    if not (model_dir and os.path.isdir(model_dir)):
        errors.append("facefusion_models_missing")
    if not config.get("licenseRef"):
        errors.append("facefusion_license_missing")
    return {"ok": not errors, "errors": errors, "config": config}


def _uploaded_material_ids(response):
    found = []

    def walk(value):
        if isinstance(value, dict):
            item_id = value.get("id") or value.get("materialId") or value.get("assetId")
            if item_id and any(key in value for key in ("url", "path", "file", "localPath", "type")):
                found.append(str(item_id))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(response)
    if not found and isinstance(response, dict):
        direct = response.get("id") or response.get("materialId") or response.get("assetId")
        if direct:
            found.append(str(direct))
    return list(dict.fromkeys(found))


def _run_facefusion(input_video, output_video, source_faces, target_face_reference, config=None):
    check = _facefusion_preflight(config)
    if not check.get("ok"):
        raise RuntimeError(";".join(check.get("errors") or ["facefusion_preflight_failed"]))
    faces = [os.path.abspath(str(path)) for path in (source_faces or []) if path and os.path.isfile(path)]
    if len(faces) < 3:
        raise RuntimeError("facefusion_requires_three_source_faces")
    target_ref = os.path.abspath(str(target_face_reference or ""))
    if not os.path.isfile(target_ref):
        raise RuntimeError("facefusion_target_reference_missing")
    if not (input_video and os.path.isfile(input_video)):
        raise RuntimeError("facefusion_input_video_missing")
    output_video = os.path.abspath(output_video)
    os.makedirs(os.path.dirname(output_video) or ".", exist_ok=True)
    cfg = check["config"]
    args = [
        cfg["bin"], "headless-run",
        "--source-paths",
    ] + faces + [
        "--target-path", os.path.abspath(input_video),
        "--output-path", output_video,
        "--face-selector-mode", "reference",
        "--reference-face-path", target_ref,
        "--model-dir", cfg["modelDir"],
        "--execution-providers",
    ] + list(cfg.get("providers") or ["cpu"])
    timeout_sec = _facefusion_timeout_sec()
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("facefusion_timeout:%s" % timeout_sec) from exc
    if completed.returncode != 0:
        raise RuntimeError("facefusion_failed:%s" % str(completed.stderr or completed.stdout or "")[:200])
    if not (os.path.isfile(output_video) and os.path.getsize(output_video) > 16):
        raise RuntimeError("facefusion_output_missing")
    return output_video


def _cleanup_replacement_sensitive_materials(job):
    job = job or {}
    deleted = []
    failed = []
    for material_id in list(job.get("sensitiveMaterialIds") or []):
        code, response = api("POST", "/api/library/delete", {"id": material_id})
        if 200 <= int(code or 0) < 300 and isinstance(response, dict) and response.get("ok"):
            deleted.append(material_id)
        else:
            failed.append({"id": material_id, "code": code, "error": str((response or {}).get("error") or "delete_failed")[:80]})
    job["sensitiveMaterialIds"] = [item["id"] for item in failed]
    result = {"ok": not failed, "deleted": deleted, "failed": failed, "cleanedAt": time.time()}
    job["sensitiveCleanup"] = result
    return result


def _cleanup_replacement_temporary_materials(job):
    job = job or {}
    deleted = []
    failed = []
    for material_id in list(job.get("temporaryMaterialIds") or []):
        code, response = api("POST", "/api/library/delete", {"id": material_id})
        if 200 <= int(code or 0) < 300 and isinstance(response, dict) and response.get("ok"):
            deleted.append(material_id)
        else:
            failed.append({"id": material_id, "code": code,
                           "error": str((response or {}).get("error") or "delete_failed")[:80]})
    job["temporaryMaterialIds"] = [item["id"] for item in failed]
    result = {"ok": not failed, "deleted": deleted, "failed": failed, "cleanedAt": time.time()}
    job["temporaryCleanup"] = result
    return result


def _save_replacement_job(job):
    job = job or {}
    out_dir = job.get("outDir") or ""
    if not out_dir:
        raise RuntimeError("video_replace_job_dir_missing")
    os.makedirs(out_dir, exist_ok=True)
    job["updatedAt"] = time.time()
    path = os.path.join(out_dir, "replacement_job.json")
    _atomic_write_json(path, job)
    return path


_REPLACEMENT_ACTIVE_JOB_STATUSES = {
    "running", "editing", "uploading", "video_edit", "principal_video_edit", "downloading",
    "facefusion", "face_swapping", "audio_muxing", "qc", "keyframing",
    "tts", "digital_human", "audio_clip", "lipsync",
}

_REPLACEMENT_ACTIVE_SEGMENT_STATUSES = _REPLACEMENT_ACTIVE_JOB_STATUSES | {"retrying"}

_REPLACEMENT_RETRY_DEMOTABLE_CODES = {
    "role_mismatch",
    "structure_mismatch",
    "reference_mismatch",
}


def _replacement_retry_snapshot(segment):
    segment = segment or {}
    import copy as _copy
    return {
        "ts": time.time(),
        "status": segment.get("status") or "",
        "audioStatus": segment.get("audioStatus") or "",
        "qcStatus": segment.get("qcStatus") or "",
        "error": segment.get("error") or "",
        "errorId": segment.get("errorId") or "",
        "blockedReason": segment.get("blockedReason") or "",
        "videoPath": segment.get("videoPath") or "",
        "editedVideoPath": segment.get("editedVideoPath") or "",
        "faceSwapPath": segment.get("faceSwapPath") or "",
        "qcWarnings": _copy.deepcopy(segment.get("qcWarnings") or []),
        "visualDriftQc": _copy.deepcopy(segment.get("visualDriftQc") or {}),
    }


def _replacement_codes_in_segment(segment):
    segment = segment or {}
    text = " ".join(str(segment.get(key) or "") for key in ("error", "blockedReason"))
    codes = set()
    for code in (
            "role_mismatch", "structure_mismatch", "reference_mismatch",
            "visual_drift_retry_exhausted", "visual_drift_blocked",
            "topic_mismatch"):
        if code in text:
            codes.add(code)
    for warning in list(segment.get("qcWarnings") or []):
        if isinstance(warning, dict) and warning.get("code"):
            codes.add(str(warning.get("code")))
    return codes


def _prepare_replacement_segment_for_retry(segment):
    segment = segment or {}
    history = list(segment.get("retryHistory") or [])
    history.append(_replacement_retry_snapshot(segment))
    segment["retryHistory"] = history
    codes = _replacement_codes_in_segment(segment)
    demoted = [code for code in ("role_mismatch", "structure_mismatch", "reference_mismatch") if code in codes]
    retained_warnings = []
    for warning in list(segment.get("qcWarnings") or []):
        if not isinstance(warning, dict):
            continue
        code = str(warning.get("code") or "")
        if code in _REPLACEMENT_RETRY_DEMOTABLE_CODES:
            item = dict(warning)
            item["severity"] = "review_warning"
            item["legacyRetryDemoted"] = True
            retained_warnings.append(item)
    segment["qcWarnings"] = retained_warnings
    segment.update({
        "status": "pending",
        "audioStatus": "pending",
        "qcStatus": "pending",
        "error": "",
        "errorId": "",
        "blockedReason": "",
        "visualDriftQc": {},
        "qcChecks": {},
        "qcFrames": [],
        "segmentStartedAt": 0,
        "segmentEndedAt": 0,
        "elapsedSec": 0,
        "etaSec": _replacement_segment_baseline_sec(segment),
    })
    return {"retryable": True, "demotedCodes": demoted}


def _prepare_replacement_segment_for_manual_regeneration(segment, defect_note):
    segment = segment or {}
    note = str(defect_note or "").strip()
    if not note:
        return {"retryable": False, "reason": "manual_defect_note_required"}
    history = list(segment.get("retryHistory") or [])
    history.append(_replacement_retry_snapshot(segment))
    segment["retryHistory"] = history
    segment["manualDefectNote"] = note[:500]
    segment["scriptReviewed"] = True
    try:
        segment["manualRegenerationCount"] = int(segment.get("manualRegenerationCount") or 0) + 1
    except (TypeError, ValueError):
        segment["manualRegenerationCount"] = 1
    segment.update({
        "status": "pending",
        "audioStatus": "pending",
        "qcStatus": "pending",
        "reviewApproved": False,
        "error": "",
        "errorId": "",
        "remoteError": "",
        "remoteErrorId": "",
        "blockedReason": "",
        "visualDriftQc": {},
        "qcChecks": {},
        "qcWarnings": [],
        "qcFrames": [],
        "videoPath": "",
        "editedVideoPath": "",
        "faceSwapPath": "",
        "segmentStartedAt": 0,
        "segmentEndedAt": 0,
        "elapsedSec": 0,
        "etaSec": _replacement_segment_baseline_sec(segment),
    })
    return {"retryable": True, "reason": "manual_defect_regeneration"}


def _replacement_segment_duration(segment):
    segment = segment or {}
    try:
        start = float(segment.get("start") or 0)
        end = float(segment.get("end") or 0)
        if end > start:
            return max(0.0, end - start)
    except (TypeError, ValueError):
        pass
    try:
        return max(0.0, float(segment.get("duration") or 0))
    except (TypeError, ValueError):
        return 0.0


def _normalize_replacement_retry_segments(job, failed_segments):
    job = job or {}
    segments = list(job.get("segments") or [])
    selected = list(failed_segments or [])
    summary = {"mergedShortTailSegments": []}
    if len(segments) < 2 or not selected:
        return selected, summary

    tail = segments[-1]
    tail_selected = any(item is tail for item in selected)
    if not tail_selected:
        tail_index = tail.get("index")
        tail_selected = any((item or {}).get("index") == tail_index for item in selected)
    if not tail_selected or _replacement_segment_duration(tail) >= 3.0:
        return selected, summary

    previous = segments[-2]
    previous["end"] = tail.get("end")
    previous["duration"] = round(_replacement_segment_duration(previous), 3)
    previous.update({
        "status": "failed",
        "audioStatus": "failed",
        "qcStatus": "failed",
        "error": tail.get("error") or "principal_video_edit_failed",
        "errorId": tail.get("errorId") or "",
        "blockedReason": tail.get("blockedReason") or "",
        "videoPath": "",
        "editedVideoPath": "",
        "faceSwapPath": "",
        "sourceSegmentPath": "",
        "qcChecks": {},
        "qcFrames": [],
    })
    history = list(previous.get("retryHistory") or [])
    history.extend(list(tail.get("retryHistory") or []))
    history.append(_replacement_retry_snapshot(tail))
    previous["retryHistory"] = history
    previous.setdefault("mergedShortTailSegments", []).append({
        "fromIndex": tail.get("index"),
        "fromStart": tail.get("start"),
        "fromEnd": tail.get("end"),
        "fromDuration": tail.get("duration"),
        "mergedAt": time.time(),
    })
    segments.pop()
    job["segments"] = segments

    normalized = []
    for segment in selected:
        replacement = previous if segment is tail or (segment or {}).get("index") == tail.get("index") else segment
        if not any(item is replacement for item in normalized):
            normalized.append(replacement)
    summary["mergedShortTailSegments"].append({
        "fromIndex": tail.get("index"),
        "intoIndex": previous.get("index"),
    })
    return normalized, summary


def _recover_stale_replacement_job(job, now=None):
    job = job or {}
    status = str(job.get("status") or "").strip().lower()
    if status not in _REPLACEMENT_ACTIVE_JOB_STATUSES:
        return {"changed": False, "job": job, "recoveredSegments": 0}
    now = float(now if now is not None else time.time())
    recovered = 0
    for segment in list(job.get("segments") or []):
        seg_status = str((segment or {}).get("status") or "").strip().lower()
        if seg_status not in _REPLACEMENT_ACTIVE_SEGMENT_STATUSES:
            continue
        error_id = str(segment.get("errorId") or "").strip()
        if not error_id:
            raw = json_log(
                _CLIENT_JSON_LOGGER,
                "video_replace_stale_segment_recovered",
                exc=RuntimeError("stale_running_recovered"),
                code="stale_running_recovered",
                job_id=job.get("id") or "",
                segment_index=segment.get("index"),
                source_video=job.get("sourceVideoPath") or "",
            )
            import json as _json
            try:
                error_id = (_json.loads(raw) or {}).get("errorId") or ""
            except Exception:
                error_id = ""
        segment.update({
            "status": "failed",
            "qcStatus": "failed",
            "error": "stale_running_recovered",
            "errorId": error_id or ("err-" + uuid.uuid4().hex[:16]),
            "recoveredAt": now,
            "recoveryReason": "stale_running_recovered",
            "etaSec": 0,
        })
        if segment.get("audioStatus") != "passed":
            segment["audioStatus"] = "failed"
        recovered += 1
    segments = list(job.get("segments") or [])
    done_count = sum(1 for item in segments if (item or {}).get("status") == "done")
    failed_count = sum(1 for item in segments if (item or {}).get("status") == "failed")
    if done_count and failed_count:
        next_status = "partial"
    elif failed_count:
        next_status = "failed"
    elif done_count and done_count == len(segments):
        next_status = "awaiting_review"
    else:
        next_status = "failed"
    job.update({
        "status": next_status,
        "recoveredAt": now,
        "recoveryReason": "stale_running_recovered",
    })
    if next_status in ("partial", "failed"):
        job.setdefault("error", "stale_running_recovered")
    return {"changed": True, "job": job, "recoveredSegments": recovered}


def recover_stale_video_replacement_jobs(base_dir=None, now=None):
    import json as _json
    root = os.path.join(base_dir or data_dir(), "video_replacements")
    result = {"status": "ok", "root": root, "scanned": 0, "recovered": 0, "errors": []}
    if not os.path.isdir(root):
        return result
    for name in os.listdir(root):
        job_dir = os.path.join(root, name)
        path = os.path.join(job_dir, "replacement_job.json")
        if os.path.islink(job_dir) or not os.path.isfile(path):
            continue
        result["scanned"] += 1
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                job = _json.load(handle)
            if not isinstance(job, dict):
                raise RuntimeError("replacement_job_invalid")
            job.setdefault("outDir", job_dir)
            recovered = _recover_stale_replacement_job(job, now=now)
            if recovered.get("changed"):
                _save_replacement_job(job)
                result["recovered"] += 1
        except Exception as exc:
            raw = json_log(
                _CLIENT_JSON_LOGGER,
                "video_replace_stale_job_recovery_failed",
                exc=exc,
                code="video_replace_stale_job_recovery_failed",
                job=name,
                temp_root=root,
            )
            try:
                error_id = (_json.loads(raw) or {}).get("errorId")
            except Exception:
                error_id = ""
            result["errors"].append({
                "job": name,
                "code": "video_replace_stale_job_recovery_failed",
                "errorId": error_id,
            })
    if result["errors"]:
        result["status"] = "partial"
    return result


def cleanup_video_replacement_temp_root(base_dir=None):
    root = os.path.join(base_dir or data_dir(), "video_replacements")
    result = {"status": "ok", "removed": 0, "retained": 0, "errors": [], "root": root}
    if not os.path.exists(root):
        return result
    if os.path.islink(root) or not os.path.isdir(root):
        result.update({"status": "failed", "errors": [{"code": "video_replace_temp_root_invalid"}]})
        return result
    try:
        retention = max(0.0, float(os.getenv("VIDEO_REPLACE_FACE_RETENTION_SEC", "86400") or 86400))
    except (TypeError, ValueError):
        retention = 86400.0
    now = time.time()
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if os.path.islink(path) or not os.path.isdir(path):
            result["retained"] += 1
            continue
        try:
            age = max(0.0, now - os.path.getmtime(path))
        except OSError:
            age = 0.0
        if age < retention:
            result["retained"] += 1
            continue
        try:
            shutil.rmtree(path)
            result["removed"] += 1
        except Exception as exc:
            raw = json_log(
                _CLIENT_JSON_LOGGER,
                "video_replace_temp_cleanup_failed",
                exc=exc,
                code="video_replace_temp_cleanup_failed",
                job=name,
                temp_root=root,
            )
            import json as _json
            result["errors"].append({
                "code": "video_replace_temp_cleanup_failed",
                "job": name,
                "errorId": (_json.loads(raw) or {}).get("errorId"),
            })
    if result["errors"]:
        result["status"] = "partial"
    return result


def _replacement_audio_qc(path, silence_threshold_db=-45.0):
    """Require a decodable AAC-compatible audio stream with audible content."""
    validation = validate_video_file(path)
    if not validation.get("ok"):
        return {
            "ok": False,
            "code": validation.get("code") or "media_invalid",
            "meanVolumeDb": float("-inf"),
        }
    if not validation.get("hasAudio"):
        return {"ok": False, "code": "audio_missing", "meanVolumeDb": float("-inf")}
    try:
        completed = subprocess.run(
            [
                _ffmpeg_exe(), "-nostdin", "-hide_banner", "-i", path,
                "-af", "volumedetect", "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        return {"ok": False, "code": "audio_probe_failed", "detail": str(exc)[:160],
                "meanVolumeDb": float("-inf")}
    import re as _re
    raw = (completed.stderr or "") + "\n" + (completed.stdout or "")
    match = _re.search(r"mean_volume:\s*(-?(?:inf|\d+(?:\.\d+)?))\s*dB", raw, _re.I)
    if not match:
        return {"ok": False, "code": "audio_volume_unknown", "meanVolumeDb": float("-inf")}
    value = match.group(1).lower()
    mean_db = float("-inf") if value in ("-inf", "inf") else float(value)
    if mean_db <= float(silence_threshold_db):
        return {"ok": False, "code": "audio_silent", "meanVolumeDb": mean_db}
    return {"ok": True, "code": "ok", "meanVolumeDb": mean_db,
            "sampleRate": 48000, "channels": 2}


def _parse_principal_visual_qc(raw):
    import json as _json
    import re as _re

    match = _re.search(r"\{[\s\S]*\}", str(raw or ""))
    if not match:
        return {"ok": False, "code": "principal_visual_qc_invalid_response"}
    try:
        parsed = _json.loads(match.group(0))
    except Exception:
        return {"ok": False, "code": "principal_visual_qc_invalid_response"}
    if not isinstance(parsed, dict):
        return {"ok": False, "code": "principal_visual_qc_invalid_response"}
    result = {
        "principalReplacementMatch": parsed.get("principalReplacementMatch") is True,
        "fullBodyAppearanceMatch": parsed.get("fullBodyAppearanceMatch") is True,
        "otherSubjectsPreserved": parsed.get("otherSubjectsPreserved") is True,
        "motionPreserved": parsed.get("motionPreserved") is True,
        "reason": str(parsed.get("reason") or "")[:240],
    }
    if not result["principalReplacementMatch"]:
        code = "principal_replacement_mismatch"
    elif not result["fullBodyAppearanceMatch"]:
        code = "principal_appearance_mismatch"
    elif not result["otherSubjectsPreserved"]:
        code = "principal_other_subjects_changed"
    elif not result["motionPreserved"]:
        code = "principal_motion_mismatch"
    else:
        code = "ok"
    result.update({"ok": code == "ok", "code": code})
    return result


def _ensure_segment_audio(before_face_swap, after_face_swap):
    """Restore the pre-FaceFusion audio if the face-swapped output lost its stream."""
    if not (after_face_swap and os.path.isfile(after_face_swap)):
        raise RuntimeError("facefusion_output_missing")
    after_meta = validate_video_file(after_face_swap)
    if after_meta.get("ok") and after_meta.get("hasAudio"):
        return after_face_swap
    before_meta = validate_video_file(before_face_swap)
    if not (before_meta.get("ok") and before_meta.get("hasAudio")):
        raise RuntimeError("source_audio_missing")
    repaired = after_face_swap + ".audio-repaired.mp4"
    cmd = [
        _ffmpeg_exe(), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", after_face_swap, "-i", before_face_swap,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-shortest", repaired,
    ]
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=240,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not os.path.isfile(repaired):
        raise RuntimeError("audio_mux_failed:%s" % str(completed.stderr or "")[:160])
    os.replace(repaired, after_face_swap)
    if not validate_video_file(after_face_swap).get("hasAudio"):
        raise RuntimeError("audio_mux_missing_stream")
    return after_face_swap


def _replace_segment_audio_from_source(source_video, edited_video):
    """Atomically replace generated audio with the original source-segment audio."""
    if not (source_video and os.path.isfile(source_video)):
        raise RuntimeError("principal_source_audio_video_missing")
    if not (edited_video and os.path.isfile(edited_video)):
        raise RuntimeError("principal_edited_video_missing")
    source_meta = validate_video_file(source_video)
    if not (source_meta.get("ok") and source_meta.get("hasAudio")):
        raise RuntimeError("principal_source_audio_missing")
    edited_meta = validate_video_file(edited_video)
    if not edited_meta.get("ok"):
        raise RuntimeError("principal_edited_video_invalid")
    repaired = edited_video + ".source-audio.mp4"
    cmd = [
        _ffmpeg_exe(), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", edited_video, "-i", source_video,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-shortest", repaired,
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        repaired_meta = validate_video_file(repaired)
        if completed.returncode != 0 or not (
                repaired_meta.get("ok") and repaired_meta.get("hasAudio")):
            raise RuntimeError(
                "principal_source_audio_mux_failed:%s" % str(completed.stderr or "")[:160])
        os.replace(repaired, edited_video)
        return edited_video
    finally:
        if os.path.isfile(repaired):
            try:
                os.remove(repaired)
            except OSError:
                pass


def _replacement_audio_mode(job):
    mode = str((job or {}).get("audioMode") or (job or {}).get("replacementAudioMode") or "source").strip().lower()
    aliases = {
        "origin": "source",
        "original": "source",
        "source_audio": "source",
        "voice": "tts",
        "ai_voice": "tts",
        "uploaded_audio": "uploaded",
        "upload": "uploaded",
    }
    mode = aliases.get(mode, mode)
    return mode if mode in ("source", "tts", "uploaded") else "source"


def _probe_media_duration(path):
    value = str(path or "").strip()
    if not value:
        return 0.0
    if not (_is_remote_fetchable_media_url(value) or os.path.isfile(value)):
        return 0.0
    try:
        cp = subprocess.run(
            [_ffmpeg_exe(), "-hide_banner", "-i", value],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return float(_parse_ffmpeg_duration((cp.stderr or "") + "\n" + (cp.stdout or "")) or 0.0)
    except Exception as exc:
        log("media duration probe: %s" % str(exc)[:100])
        return 0.0


def _audio_atempo_filter(speed):
    try:
        value = float(speed)
    except (TypeError, ValueError):
        value = 1.0
    value = max(0.5, min(value, 8.0))
    parts = []
    while value > 2.0:
        parts.append("atempo=2.0")
        value /= 2.0
    while value < 0.5:
        parts.append("atempo=0.5")
        value /= 0.5
    parts.append("atempo=%.3f" % value)
    return ",".join(parts)


def _speed_up_audio(audio_path, output_path, speed):
    audio_path = str(audio_path or "").strip()
    output_path = str(output_path or "").strip()
    if not (audio_path and os.path.isfile(audio_path)):
        raise RuntimeError("replacement_tts_audio_missing")
    try:
        speed_value = float(speed)
    except (TypeError, ValueError):
        speed_value = 1.0
    if speed_value <= 1.0 + 1e-6:
        return audio_path
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    completed = subprocess.run(
        [
            _ffmpeg_exe(), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", audio_path,
            "-filter:a", _audio_atempo_filter(speed_value),
            "-vn", "-ar", "48000", "-ac", "2",
            output_path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not (os.path.isfile(output_path) and os.path.getsize(output_path) > 100):
        raise RuntimeError("replacement_tts_speedup_failed:%s" % str(completed.stderr or "")[:160])
    return output_path


def _replacement_prepare_tts_audio_for_prompt(job, segment, target_duration):
    job = job or {}
    segment = segment or {}
    script = str(segment.get("script") or "").strip()
    if not script:
        raise RuntimeError("replacement_tts_script_missing")
    idx = int(segment.get("index") or 1)
    out_dir = job.get("outDir") or data_dir()
    os.makedirs(out_dir, exist_ok=True)
    tts_path = str(segment.get("ttsPath") or "").strip()
    if not (tts_path and os.path.isfile(tts_path)):
        sound_url = str(segment.get("ttsUrl") or "").strip()
        if not _is_remote_fetchable_media_url(sound_url):
            _replacement_emit_stage(job, segment, "tts", "生成片段 %s：先生成口播音频用于时间表" % idx)
            sound_url = lk888_tts_voice(
                script,
                job.get("voiceId") or "Zephyr",
                cancel_check=_replacement_cancel_check(job),
            )
        if not _is_remote_fetchable_media_url(sound_url):
            raise RuntimeError("replacement_tts_audio_not_public")
        segment["ttsUrl"] = sound_url
        tts_path = os.path.join(out_dir, "replacement_tts_%02d.mp3" % idx)
        if not (os.path.isfile(tts_path) and os.path.getsize(tts_path) > 0):
            _wf_download(sound_url, tts_path)
        if not (os.path.isfile(tts_path) and os.path.getsize(tts_path) > 0):
            raise RuntimeError("replacement_tts_audio_missing")
        segment["ttsPath"] = tts_path
    audio_duration = _probe_media_duration(tts_path)
    segment["ttsDurationSec"] = round(audio_duration, 3) if audio_duration > 0 else 0
    final_duration = audio_duration if audio_duration > 0 else float(target_duration or 0.0)
    try:
        video_duration = float(target_duration or 0.0)
    except (TypeError, ValueError):
        video_duration = 0.0
    if video_duration > 0 and audio_duration > video_duration + 0.25:
        required_speed = round(audio_duration / video_duration, 3)
        max_speed = _replacement_tts_max_speed(job)
        segment["ttsRequiredSpeed"] = required_speed
        segment["ttsMaxSpeed"] = max_speed
        if required_speed <= max_speed + 1e-6:
            fit_path = os.path.join(out_dir, "replacement_tts_%02d.fit.mp3" % idx)
            _replacement_emit_stage(
                job, segment, "tts",
                "生成片段 %s：口播音频自动提速 %.2fx 后再约束口型节奏" % (idx, required_speed),
            )
            _speed_up_audio(tts_path, fit_path, required_speed)
            segment["ttsOriginalPath"] = tts_path
            segment["ttsOriginalDurationSec"] = round(audio_duration, 3)
            segment["ttsPath"] = fit_path
            segment["ttsSpeed"] = round(required_speed, 3)
            segment["ttsTimingStatus"] = "sped_up"
            tts_path = fit_path
            final_duration = video_duration
        else:
            segment["ttsTimingStatus"] = "too_long"
            segment["ttsTimingError"] = (
                "AI 音色配音 %.2f 秒长于片段 %.2f 秒，需要 %.2fx 语速，超过自动提速上限 %.2fx；"
                "请缩短该片段口播稿或合并片段后重试。"
                % (audio_duration, video_duration, required_speed, max_speed)
            )
            raise RuntimeError(
                "replacement_tts_audio_too_long:segment=%s,audio=%.2f,video=%.2f,required_speed=%.2f,max_speed=%.2f"
                % (idx, audio_duration, video_duration, required_speed, max_speed)
            )
    else:
        segment["ttsSpeed"] = float(segment.get("ttsSpeed") or 1.0)
        segment["ttsTimingStatus"] = segment.get("ttsTimingStatus") or "normal"
    return tts_path, max(0.01, float(final_duration or video_duration or 0.01))


def _replacement_prepare_uploaded_audio_for_prompt(job, segment, target_duration):
    job = job or {}
    segment = segment or {}
    idx = int(segment.get("index") or 1)
    out_dir = job.get("outDir") or data_dir()
    os.makedirs(out_dir, exist_ok=True)
    try:
        start = float(segment.get("start") or 0.0)
    except (TypeError, ValueError):
        start = 0.0
    try:
        duration = float(target_duration or segment.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        try:
            end = float(segment.get("end") or start)
        except (TypeError, ValueError):
            end = start
        duration = max(0.1, end - start)
    clip_path = str(segment.get("uploadedAudioSegmentPath") or "").strip()
    if not (clip_path and os.path.isfile(clip_path)):
        _replacement_emit_stage(job, segment, "audio_clip", "生成片段 %s：先裁切上传配音用于时间表" % idx)
        source_path = _uploaded_replacement_audio_source_path(job)
        clip_path = os.path.join(out_dir, "replacement_uploaded_audio_%02d.local.mp3" % idx)
        _clip_replacement_uploaded_audio_segment(source_path, clip_path, start, duration)
        segment["uploadedAudioSegmentPath"] = clip_path
    segment["uploadedAudioSegmentStartSec"] = round(start, 3)
    measured = _probe_media_duration(clip_path)
    final_duration = measured if measured > 0 else duration
    segment["uploadedAudioSegmentDurationSec"] = round(final_duration, 3)
    return clip_path, max(0.01, float(final_duration or duration or 0.01))


def _replacement_prepare_dialogue_timing_for_prompt(job, segment):
    job = job or {}
    segment = segment or {}
    audio_mode = _replacement_audio_mode(job)
    if audio_mode not in ("tts", "uploaded"):
        return ""
    script = str(segment.get("script") or "").strip()
    if not script:
        raise RuntimeError("replacement_dialogue_script_missing")
    duration = _replacement_segment_duration(segment) or float(segment.get("duration") or 0.0) or 8.0
    if audio_mode == "uploaded":
        audio_path, audio_duration = _replacement_prepare_uploaded_audio_for_prompt(job, segment, duration)
    else:
        audio_path, audio_duration = _replacement_prepare_tts_audio_for_prompt(job, segment, duration)
    timing = _replacement_build_dialogue_timing(script, round(audio_duration, 2))
    segment["dialogueAudioMode"] = audio_mode
    segment["dialogueAudioPath"] = audio_path
    segment["dialogueAudioDurationSec"] = round(audio_duration, 2)
    segment["dialogueTiming"] = timing
    segment["dialogueTimingPrompt"] = _replacement_dialogue_timing_prompt(segment)
    return segment["dialogueTimingPrompt"]

def _uploaded_replacement_audio_source_path(job):
    job = job or {}
    local_path = str(job.get("replacementAudioPath") or "").strip()
    if local_path and os.path.isfile(local_path):
        return local_path
    url = str(job.get("replacementAudioUrl") or "").strip()
    if not _is_remote_fetchable_media_url(url):
        raise RuntimeError("replacement_uploaded_audio_missing")
    out_dir = job.get("outDir") or data_dir()
    os.makedirs(out_dir, exist_ok=True)
    ext = os.path.splitext(urlparse(url).path)[1].lower() or ".mp3"
    if ext not in (".mp3", ".wav", ".m4a", ".ogg", ".aac"):
        ext = ".mp3"
    local_path = os.path.join(out_dir, "replacement_uploaded_source%s" % ext)
    if not os.path.isfile(local_path) or os.path.getsize(local_path) <= 100:
        _wf_download(url, local_path)
    if not (os.path.isfile(local_path) and os.path.getsize(local_path) > 100):
        raise RuntimeError("replacement_uploaded_audio_missing")
    return local_path


def _clip_replacement_uploaded_audio_segment(audio_path, output_path, start_sec, duration_sec):
    audio_path = str(audio_path or "").strip()
    output_path = str(output_path or "").strip()
    if not (audio_path and os.path.isfile(audio_path)):
        raise RuntimeError("replacement_uploaded_audio_missing")
    try:
        start = max(0.0, float(start_sec or 0.0))
    except (TypeError, ValueError):
        start = 0.0
    try:
        duration = max(0.25, float(duration_sec or 0.0))
    except (TypeError, ValueError):
        duration = 0.25
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    completed = subprocess.run(
        [
            _ffmpeg_exe(), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-ss", "%.3f" % start,
            "-i", audio_path,
            "-t", "%.3f" % duration,
            "-vn", "-ar", "48000", "-ac", "2",
            output_path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not (os.path.isfile(output_path) and os.path.getsize(output_path) > 100):
        raise RuntimeError("replacement_uploaded_audio_clip_failed:%s" % str(completed.stderr or "")[:160])
    return output_path


def _replacement_uploaded_audio_segment_url(job, segment):
    job = job or {}
    segment = segment or {}
    cached = str(segment.get("uploadedAudioSegmentUrl") or "").strip()
    if _is_remote_fetchable_media_url(cached):
        return cached
    out_dir = job.get("outDir") or data_dir()
    os.makedirs(out_dir, exist_ok=True)
    idx = int(segment.get("index") or 1)
    start = float(segment.get("start") or 0.0)
    duration = _replacement_segment_duration(segment) or float(segment.get("duration") or 0.0) or 8.0
    source_path = _uploaded_replacement_audio_source_path(job)
    clip_path = os.path.join(out_dir, "replacement_uploaded_audio_%02d.mp3" % idx)
    _clip_replacement_uploaded_audio_segment(source_path, clip_path, start, duration)
    url, response = upload_asset_url(clip_path, "同款替换片段%d口型同步配音" % idx, "audio")
    if not _is_remote_fetchable_media_url(url):
        raise RuntimeError("replacement_uploaded_audio_clip_not_public")
    segment["uploadedAudioSegmentPath"] = clip_path
    segment["uploadedAudioSegmentUrl"] = str(url or "").strip()
    segment["uploadedAudioSegmentStartSec"] = round(start, 3)
    segment["uploadedAudioSegmentDurationSec"] = round(duration, 3)
    uploaded_id = str((response or {}).get("id") or (response or {}).get("materialId") or "").strip()
    if uploaded_id:
        segment["uploadedAudioSegmentMaterialId"] = uploaded_id
        job.setdefault("temporaryMaterialIds", []).append(uploaded_id)
    return segment["uploadedAudioSegmentUrl"]


def _replacement_segment_audio_url_for_lipsync(job, segment):
    job = job or {}
    segment = segment or {}
    audio_mode = _replacement_audio_mode(job)
    if audio_mode == "uploaded":
        return _replacement_uploaded_audio_segment_url(job, segment)
    script = str(segment.get("script") or "").strip()
    if not script:
        raise RuntimeError("replacement_lipsync_script_missing")
    cached = str(segment.get("ttsUrl") or "").strip()
    if _is_remote_fetchable_media_url(cached):
        return cached
    idx = int(segment.get("index") or 1)
    segment["status"] = "tts"
    _replacement_emit_stage(job, segment, "tts", "生成片段 %s：按口播稿生成口型同步音频" % idx)
    sound_url = lk888_tts_voice(script, job.get("voiceId") or "Zephyr", cancel_check=_replacement_cancel_check(job))
    if not _is_remote_fetchable_media_url(sound_url):
        raise RuntimeError("replacement_lipsync_audio_not_public")
    segment["ttsUrl"] = sound_url
    return sound_url


def _replacement_video_lipsync_model(job=None):
    value = str((job or {}).get("videoLipSyncModel") or "").strip()
    if value:
        return value
    return str(
        os.getenv("VIDEO_REPLACE_LIPSYNC_MODEL")
        or os.getenv("LK888_VIDEO_LIPSYNC_MODEL")
        or ""
    ).strip()


def _run_replacement_video_lipsync(job, segment, video_path, sound_url):
    job = job or {}
    segment = segment or {}
    video_path = str(video_path or "").strip()
    sound_url = str(sound_url or "").strip()
    if not (video_path and os.path.isfile(video_path)):
        raise RuntimeError("replacement_lipsync_video_missing")
    if not _is_remote_fetchable_media_url(sound_url):
        raise RuntimeError("replacement_lipsync_audio_not_public")
    model = _replacement_video_lipsync_model(job)
    if not model:
        raise RuntimeError("replacement_lipsync_model_missing")
    idx = int(segment.get("index") or 1)
    out_dir = job.get("outDir") or os.path.dirname(video_path) or data_dir()
    os.makedirs(out_dir, exist_ok=True)
    video_url = str(segment.get("lipSyncInputVideoUrl") or "").strip()
    if not _is_remote_fetchable_media_url(video_url):
        video_url, response = upload_asset_url(video_path, "同款替换片段%d口型同步视频" % idx, "video")
        if not _is_remote_fetchable_media_url(video_url):
            raise RuntimeError("replacement_lipsync_video_not_public")
        segment["lipSyncInputVideoUrl"] = video_url
        uploaded_id = str((response or {}).get("id") or (response or {}).get("materialId") or "").strip()
        if uploaded_id:
            segment["lipSyncInputVideoMaterialId"] = uploaded_id
            job.setdefault("temporaryMaterialIds", []).append(uploaded_id)
    payload = {
        "prompt": (
            "只同步视频中主角口型到提供的音频；保持原视频画面、动作、镜头、产品、场景、人物身份和时长不变。"
            "不要重新生成整段视频，不要替换产品或背景。"
        ),
        "video": video_url,
        "video_url": video_url,
        "source_video_url": video_url,
        "audio": sound_url,
        "audio_url": sound_url,
        "sound": sound_url,
        "sound_url": sound_url,
        "params": {
            "video": video_url,
            "video_url": video_url,
            "audio": sound_url,
            "audio_url": sound_url,
            "sound_url": sound_url,
            "mode": "lip_sync",
            "preserve_video": True,
            "watermark": False,
        },
    }
    segment["lipSyncModel"] = model
    segment["lipSyncRequestFields"] = sorted(str(key) for key in payload)

    def lipsync_progress(i):
        _replacement_emit_stage(
            job, segment, "lipsync",
            "生成片段 %s：同步替换视频口型（%s，轮询%d次）" % (idx, model, i + 1),
        )

    url = _lk888_media_task_with_cancel(
        model, payload, ["mp4", "mov", "webm"],
        progress=lipsync_progress,
        tries=int(job.get("lipsyncTries") or 150),
        cancel_check=_replacement_cancel_check(job),
    )
    output_path = os.path.join(out_dir, "lipsync_%02d.mp4" % idx)
    _replacement_emit_stage(job, segment, "downloading", "生成片段 %s：下载口型同步结果" % idx)
    _wf_download(url, output_path)
    if not validate_video_file(output_path).get("ok"):
        raise RuntimeError("replacement_lipsync_output_invalid")
    segment["lipSyncUrl"] = url
    segment["lipSyncPath"] = output_path
    segment["lipSyncStatus"] = "passed"
    return output_path


def _replace_video_audio(video_path, audio_input, output_path, require_full_audio=False):
    video_path = str(video_path or "").strip()
    audio_input = str(audio_input or "").strip()
    output_path = str(output_path or "").strip()
    if not (video_path and os.path.isfile(video_path)):
        raise RuntimeError("replacement_audio_video_missing")
    if not (audio_input and (os.path.isfile(audio_input) or _is_remote_fetchable_media_url(audio_input))):
        raise RuntimeError("replacement_audio_missing")
    video_duration = float(_probe_video(video_path).get("duration") or 0.0)
    audio_duration = _probe_media_duration(audio_input)
    if video_duration <= 0:
        raise RuntimeError("replacement_audio_video_duration_missing")
    if require_full_audio and audio_duration + 0.25 < video_duration:
        raise RuntimeError("replacement_uploaded_audio_too_short")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    completed = subprocess.run(
        [
            _ffmpeg_exe(), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", video_path, "-i", audio_input,
            "-map", "0:v:0", "-map", "1:a:0",
            "-t", "%.3f" % video_duration,
            "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2",
            output_path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not validate_video_file(output_path).get("ok"):
        raise RuntimeError("replacement_audio_mux_failed:%s" % str(completed.stderr or "")[:160])
    audio = _replacement_audio_qc(output_path)
    if not audio.get("ok"):
        raise RuntimeError("replacement_audio_mux_invalid:%s" % (audio.get("code") or "unknown"))
    return output_path


def _replace_replacement_segment_audio_with_tts(job, segment, video_path):
    job = job or {}
    segment = segment or {}
    script = str(segment.get("script") or "").strip()
    if not script:
        raise RuntimeError("replacement_tts_script_missing")
    idx = int(segment.get("index") or 1)
    out_dir = job.get("outDir") or os.path.dirname(video_path) or data_dir()
    os.makedirs(out_dir, exist_ok=True)
    tts_path = str(segment.get("ttsPath") or "").strip()
    if tts_path and os.path.isfile(tts_path):
        audio_duration = _probe_media_duration(tts_path)
        if audio_duration > 0 and not segment.get("ttsDurationSec"):
            segment["ttsDurationSec"] = round(audio_duration, 3)
        segment["ttsTimingStatus"] = segment.get("ttsTimingStatus") or "prepared"
        segment["ttsSpeed"] = float(segment.get("ttsSpeed") or 1.0)
    else:
        _replacement_emit_stage(job, segment, "tts", "生成片段 %s：按所选音色生成新配音" % idx)
        sound_url = lk888_tts_voice(script, job.get("voiceId") or "Zephyr")
        segment["ttsUrl"] = sound_url
        tts_path = os.path.join(out_dir, "replacement_tts_%02d.mp3" % idx)
        _wf_download(sound_url, tts_path)
        segment["ttsPath"] = tts_path
        video_duration = float(_probe_video(video_path).get("duration") or 0.0)
        audio_duration = _probe_media_duration(tts_path)
        segment["ttsDurationSec"] = round(audio_duration, 3) if audio_duration > 0 else 0
        if video_duration > 0 and audio_duration > video_duration + 0.25:
            required_speed = round(audio_duration / video_duration, 3)
            max_speed = _replacement_tts_max_speed(job)
            segment["ttsRequiredSpeed"] = required_speed
            segment["ttsMaxSpeed"] = max_speed
            if required_speed <= max_speed + 1e-6:
                fit_path = os.path.join(out_dir, "replacement_tts_%02d.fit.mp3" % idx)
                _replacement_emit_stage(
                    job, segment, "tts",
                    "生成片段 %s：AI 配音自动提速 %.2fx 以匹配 %.1f 秒片段" % (
                        idx, required_speed, video_duration)
                )
                _speed_up_audio(tts_path, fit_path, required_speed)
                segment["ttsOriginalPath"] = tts_path
                segment["ttsOriginalDurationSec"] = round(audio_duration, 3)
                segment["ttsPath"] = fit_path
                segment["ttsSpeed"] = round(required_speed, 3)
                segment["ttsTimingStatus"] = "sped_up"
                tts_path = fit_path
            else:
                segment["ttsTimingStatus"] = "too_long"
                segment["ttsTimingError"] = (
                    "AI 音色配音 %.2f 秒长于片段 %.2f 秒，需要 %.2fx 语速，超过自动提速上限 %.2fx；"
                    "请缩短该片段口播稿或合并片段后重试。"
                    % (audio_duration, video_duration, required_speed, max_speed)
                )
                raise RuntimeError(
                    "replacement_tts_audio_too_long:segment=%s,audio=%.2f,video=%.2f,required_speed=%.2f,max_speed=%.2f"
                    % (idx, audio_duration, video_duration, required_speed, max_speed)
                )
        else:
            segment["ttsSpeed"] = 1.0
            segment["ttsTimingStatus"] = "normal"
    replaced = video_path + ".tts-audio.mp4"
    try:
        _replace_video_audio(video_path, tts_path, replaced, require_full_audio=False)
        os.replace(replaced, video_path)
    finally:
        if os.path.isfile(replaced):
            try:
                os.remove(replaced)
            except OSError:
                pass
    segment["audioMode"] = "tts"
    return video_path

def _replace_replacement_segment_audio_with_uploaded(job, segment, video_path):
    job = job or {}
    segment = segment or {}
    idx = int(segment.get("index") or 1)
    out_dir = job.get("outDir") or os.path.dirname(video_path) or data_dir()
    os.makedirs(out_dir, exist_ok=True)
    try:
        start = float(segment.get("start") or 0.0)
    except (TypeError, ValueError):
        start = 0.0
    try:
        duration = float(segment.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        try:
            end = float(segment.get("end") or start)
        except (TypeError, ValueError):
            end = start
        duration = max(0.1, end - start)
    clip_path = str(segment.get("uploadedAudioSegmentPath") or "").strip()
    if not (clip_path and os.path.isfile(clip_path)):
        source_path = _uploaded_replacement_audio_source_path(job)
        clip_path = os.path.join(out_dir, "replacement_uploaded_audio_%02d.local.mp3" % idx)
        _clip_replacement_uploaded_audio_segment(source_path, clip_path, start, duration)
        segment["uploadedAudioSegmentPath"] = clip_path
    segment["uploadedAudioSegmentStartSec"] = round(start, 3)
    if not segment.get("uploadedAudioSegmentDurationSec"):
        measured = _probe_media_duration(clip_path)
        segment["uploadedAudioSegmentDurationSec"] = round(measured if measured > 0 else duration, 3)
    replaced = video_path + ".uploaded-segment-audio.mp4"
    try:
        _replace_video_audio(video_path, clip_path, replaced, require_full_audio=False)
        os.replace(replaced, video_path)
    finally:
        if os.path.isfile(replaced):
            try:
                os.remove(replaced)
            except OSError:
                pass
    segment["audioMode"] = "uploaded"
    return video_path

def _replace_replacement_final_audio(job, video_path):
    job = job or {}
    audio_input = str(job.get("replacementAudioPath") or "").strip()
    if not (audio_input and os.path.isfile(audio_input)):
        audio_input = str(job.get("replacementAudioUrl") or "").strip()
    if not audio_input:
        raise RuntimeError("replacement_uploaded_audio_missing")
    output_path = os.path.splitext(video_path)[0] + ".uploaded-audio.mp4"
    result = _replace_video_audio(video_path, audio_input, output_path, require_full_audio=True)
    job["finalAudioMode"] = "uploaded"
    job["finalAudioPath"] = result
    return result


def _extract_replacement_segment(video_path, segment, output_path):
    if not (video_path and os.path.isfile(video_path)):
        raise RuntimeError("replacement_source_video_missing")
    start = max(0.0, float((segment or {}).get("start") or 0))
    duration = max(0.1, float((segment or {}).get("duration") or 0.1))
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    completed = subprocess.run(
        [
            _ffmpeg_exe(), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-ss", "%.3f" % start, "-i", video_path, "-t", "%.3f" % duration,
            "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", output_path,
        ],
        capture_output=True,
        text=True,
        timeout=240,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not validate_video_file(output_path).get("ok"):
        raise RuntimeError("replacement_segment_extract_failed:%s" % str(completed.stderr or "")[:160])
    return output_path


def _extract_replacement_qc_frames(video_path, out_dir, segment_index=1):
    meta = _probe_video(video_path)
    duration = float(meta.get("duration") or 0)
    if duration <= 0:
        return []
    os.makedirs(out_dir, exist_ok=True)
    times = [max(0.05, duration * ratio) for ratio in (0.08, 0.5, 0.92)]
    frames = []
    for label, sec in zip(("first", "middle", "last"), times):
        path = os.path.join(out_dir, "qc_%02d_%s.jpg" % (int(segment_index or 1), label))
        completed = subprocess.run(
            [
                _ffmpeg_exe(), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-ss", "%.3f" % sec, "-i", video_path, "-frames:v", "1",
                "-vf", "scale=720:-2", "-q:v", "3", path,
            ],
            capture_output=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode == 0 and os.path.isfile(path) and os.path.getsize(path) > 1000:
            frames.append(path)
    return frames


def _replacement_no_person_mode(job):
    return str((job or {}).get("noPersonMode") or "").strip().lower() in ("1", "true", "yes", "on")


def _replacement_reference_preflight_blocks(job, preflight):
    if not _replacement_reference_preflight_enabled(job):
        return False
    preflight = preflight or {}
    if preflight.get("blocked") is True:
        return True
    return str(preflight.get("status") or "").strip().lower() == "blocked"


def _replacement_reference_preflight_has_blocking_risk(job, risks):
    job = job or {}
    for item in list(risks or []):
        if isinstance(item, dict):
            text = " ".join(str(item.get(key) or "") for key in ("type", "url", "reason"))
        else:
            text = str(item or "")
        lowered = text.lower()
        is_product_risk = any(token in lowered for token in (
            "product", "product_category", "productimage", "product_image",
        )) or any(token in text for token in (
            "产品图", "商品图", "产品参考", "商品参考", "产品类别", "商品类别", "品类冲突",
        ))
        if is_product_risk:
            continue
        is_scene_risk = any(token in lowered for token in ("scene", "background")) or any(
            token in text for token in ("场景图", "场景参考", "背景图", "环境参考")
        )
        if is_scene_risk and _env_enabled("VIDEO_REPLACE_PREFLIGHT_BLOCK_SCENE", "0"):
            return True
    return False


def _run_replacement_reference_preflight(job):
    import json as _json
    import re as _re
    job = job or {}
    if not _replacement_reference_preflight_enabled(job):
        return {"ok": True, "status": "skipped", "blocked": False, "referenceRisks": []}
    context = _replacement_source_context_from_analysis(job.get("breakdownAnalysis") or {})
    media_urls = []
    media_urls.extend(job.get("productImageUrls") or [])
    if not _replacement_no_person_mode(job):
        media_urls.extend(job.get("faceSourceUrls") or [])
        if job.get("modelFaceUrl"):
            media_urls.append(job.get("modelFaceUrl"))
    if job.get("sceneImageUrl"):
        media_urls.append(job.get("sceneImageUrl"))
    media_urls = [str(url).strip() for url in media_urls if str(url).strip()]
    prompt = (
        "你是短视频同款替换的参考图预检器。源视频类别、人物角色、产品类别和镜头结构优先。"
        "人物参考图只允许作为脸、发型、外貌参考，不允许继承其中的行业、商品、直播间、背景或道具。"
        "人物参考图里的制服、Logo、展厅、直播间或背景上下文只能作为 warning，不得作为 blocking。"
        "产品图与源视频产品类别不同只能作为 warning，不能作为 blocking，因为上传产品图表示要强制替换原片产品。"
        "场景图与源视频场景不同只能作为 warning，不能作为 blocking，因为上传场景图表示要强制替换原片场景。"
        "只有参考图不可读取、违规、或会导致无法识别人物/产品/场景槽位时才允许 blocking。"
        "仅输出 JSON："
        '{"ok":true或false,"severity":"passed|warning|blocking","blocked":true或false,'
        '"sourceCategory":"类别","sourceRole":"角色","sourceProductCategory":"产品类别",'
        '"referenceRisks":[{"type":"风险类型","url":"媒体URL","reason":"原因"}],"reason":"简短原因"}。'
        "源视频证据：%s；推断：%s/%s/%s"
        % (
            _replacement_excerpt(context.get("evidence"), 900),
            context.get("sourceCategory") or "",
            context.get("sourceRole") or "",
            context.get("sourceProductCategory") or "",
        )
    )
    try:
        raw = lk888_vision(prompt, media_urls, max_tokens=700)
        match = _re.search(r"\{[\s\S]*\}", str(raw or ""))
        if not match:
            raise RuntimeError("reference_preflight_invalid_response")
        parsed = _json.loads(match.group(0))
    except Exception as exc:
        error_id = _replacement_error_id(
            "video_replace_reference_preflight_failed",
            exc,
            source_video=job.get("sourceVideoPath") or "",
        )
        return {
            "ok": True,
            "status": "deferred",
            "blocked": False,
            "code": "reference_preflight_deferred",
            "errorId": error_id,
            "referenceRisks": [],
            "reason": "参考图预检服务异常，已降级为后置质检",
            **context,
        }
    risks = list(parsed.get("referenceRisks") or [])
    model_blocked = parsed.get("blocked") is True or str(parsed.get("severity") or "").lower() == "blocking"
    blocked = bool(model_blocked and _replacement_reference_preflight_has_blocking_risk(job, risks))
    status = "blocked" if blocked else ("warning" if str(parsed.get("severity") or "").lower() == "warning" else "passed")
    if model_blocked and not blocked:
        status = "warning"
    return {
        "ok": not blocked,
        "status": status,
        "blocked": blocked,
        "code": "reference_mismatch" if blocked else "ok",
        "sourceCategory": str(parsed.get("sourceCategory") or context.get("sourceCategory") or ""),
        "sourceRole": str(parsed.get("sourceRole") or context.get("sourceRole") or ""),
        "sourceProductCategory": str(parsed.get("sourceProductCategory") or context.get("sourceProductCategory") or ""),
        "referenceRisks": risks,
        "reason": str(parsed.get("reason") or "")[:240],
    }


def _replacement_face_similarity_enabled(job=None):
    job = job or {}
    value = job.get("faceSimilarityQcEnabled")
    if value is not None:
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return _env_enabled("VIDEO_REPLACE_FACE_SIMILARITY_QC", "1")


def _replacement_face_similarity_threshold(job=None):
    try:
        base = float(os.getenv("VIDEO_REPLACE_FACE_SIMILARITY_MIN", "70") or 70)
    except (TypeError, ValueError):
        base = 70.0
    if _replacement_identity_mode(job) == "high":
        try:
            high = float(os.getenv("VIDEO_REPLACE_FACE_SIMILARITY_MIN_HIGH", "80") or 80)
        except (TypeError, ValueError):
            high = 80.0
        base = max(base, high)
    return max(0.0, min(100.0, base))


def _score_face_similarity_vision(frame_urls, face_urls):
    """用视觉模型为生成画面与授权人脸的身份相似度打分（0-100）。"""
    import json as _json
    import re as _re
    frame_urls = list(frame_urls or [])
    prompt = (
        "你是人脸身份一致性评分器。前 %d 张图像是生成视频的抽帧画面，后面的图像是用户授权的目标人物照片。"
        "只评估画面中主要人物与授权照片是否为同一身份（脸型、五官、发型观感），"
        "忽略表情、角度、妆容、光照和画质差异。"
        "仅输出 JSON：{\"score\":0到100的整数,\"reason\":\"简短原因\"}。"
        "100=明确同一身份，70=大概率同一身份，40=有明显差异，0=完全不是同一人。"
    ) % max(1, len(frame_urls))
    raw = lk888_vision(prompt, frame_urls + list(face_urls or []), max_tokens=200)
    match = _re.search(r"\{[\s\S]*\}", str(raw or ""))
    if not match:
        raise RuntimeError("face_similarity_invalid_response")
    parsed = _json.loads(match.group(0))
    try:
        score = float(parsed.get("score"))
    except (TypeError, ValueError):
        raise RuntimeError("face_similarity_invalid_score")
    return {"score": max(0.0, min(100.0, score)), "reason": str(parsed.get("reason") or "")[:160]}


def _run_replacement_face_similarity_qc(job, segment, video_path=None, frames=None):
    """人脸相似度量化质检：复用片段 QC 抽帧与授权人脸比对打分，低于阈值返回不通过。
    评分服务异常时降级为通过并标记 deferred，不阻断生成。"""
    job = job or {}
    segment = segment or {}
    result = {"ok": True, "code": "ok", "score": None,
              "threshold": _replacement_face_similarity_threshold(job), "method": "vision"}
    if not _replacement_face_similarity_enabled(job):
        result["code"] = "disabled"
        return result
    if _replacement_no_person_mode(job):
        result["code"] = "skipped_no_person"
        return result
    face_urls = [str(u or "").strip() for u in (job.get("faceSourceUrls") or []) if str(u or "").strip()]
    if not face_urls:
        model_face = str(job.get("modelFaceUrl") or "").strip()
        if model_face:
            face_urls = [model_face]
    if not face_urls:
        result["code"] = "skipped_no_reference"
        return result
    frames = list(frames or segment.get("qcFrames") or [])
    frame_paths = []
    for value in frames:
        value = str(value or "").strip()
        if value and os.path.isfile(value):
            frame_paths.append(value)
    frames = frame_paths
    if not frames:
        result["code"] = "skipped_no_frames"
        return result
    try:
        frame_urls = []
        material_ids = []
        for frame_no, frame_path in enumerate(frames[:2], 1):
            url, response = upload_asset_url(
                frame_path, "同款替换人脸质检帧%d-%d" % (int(segment.get("index") or 1), frame_no), "image")
            url = str(url or "").strip()
            if not _is_remote_fetchable_media_url(url):
                raise RuntimeError("face similarity frame url is not remote fetchable")
            frame_urls.append(url)
            material_ids.extend(_uploaded_material_ids(response))
        if material_ids:
            job["temporaryMaterialIds"] = list(dict.fromkeys(
                list(job.get("temporaryMaterialIds") or []) + material_ids
            ))
        scored = _score_face_similarity_vision(frame_urls, face_urls)
        result["score"] = scored["score"]
        result["reason"] = str(scored.get("reason") or "")[:160]
        if float(scored["score"]) + 1e-6 < float(result["threshold"]):
            result["ok"] = False
            result["code"] = "face_similarity_low"
        return result
    except Exception as exc:
        error_id = _replacement_error_id(
            "video_replace_face_similarity_deferred", exc,
            segment_index=segment.get("index"), source_video=job.get("sourceVideoPath") or "",
        )
        result.update({
            "ok": True,
            "code": "face_similarity_deferred",
            "errorId": error_id,
            "reason": "人脸相似度评分异常，已降级为人工审核",
        })
        return result


def _run_replacement_visual_qc(job, segment, video_path):
    import json as _json
    import re as _re
    job = job or {}
    segment = segment or {}
    principal_mode = _principal_replacement_enabled(job)
    result_url, response = upload_asset_url(
        video_path,
        "同款替换质检片段%d" % int(segment.get("index") or 1),
        "video",
    )
    ids = _uploaded_material_ids(response)
    job["temporaryMaterialIds"] = list(dict.fromkeys(
        list(job.get("temporaryMaterialIds") or []) + ids
    ))
    media_urls = [result_url]
    source_segment_url = str(segment.get("sourceSegmentUrl") or "").strip()
    has_source_segment_ref = bool(source_segment_url and _is_remote_fetchable_media_url(source_segment_url))
    has_product_ref = bool(job.get("productImageUrls"))
    if has_source_segment_ref:
        media_urls.append(source_segment_url)
    if has_product_ref:
        media_urls.extend(job.get("productImageUrls") or [])
    no_person_mode = _replacement_no_person_mode(job)
    if principal_mode and not no_person_mode:
        media_urls.extend(job.get("personReferenceUrls") or [])
    elif job.get("modelFaceUrl") and not no_person_mode:
        media_urls.append(job.get("modelFaceUrl"))
    scene_fallback_active = _replacement_ai_scene_fallback_active(segment)
    if job.get("sceneImageUrl") and not scene_fallback_active:
        media_urls.append(job.get("sceneImageUrl"))
    has_scene_ref = bool(job.get("sceneImageUrl") and not scene_fallback_active)
    if has_source_segment_ref:
        source_product_rule = (
            "第2个媒体是原片片段；先判断原片片段是否本来清楚出现目标产品，输出 sourceProductVisible。"
            "如果 sourceProductVisible 为 false，则 productMatch 和 logoTextReadable 固定视为 true，因为原片没有产品时允许生成结果没有产品。"
        )
    elif has_product_ref:
        source_product_rule = "没有原片片段媒体；sourceProductVisible 固定输出 true，并按目标产品参考检查 productMatch。"
    else:
        source_product_rule = (
            "没有产品参考图；以原片片段和待审核视频的产品为准，检查结果是否保留原片产品，"
            "不要因为没有上传产品参考图就要求生成新产品。"
        )
    provided_media_labels = []
    if has_source_segment_ref:
        provided_media_labels.append("原片片段")
    if has_product_ref:
        provided_media_labels.append("产品参考图")
    if principal_mode and not no_person_mode:
        provided_media_labels.append("主角人物全身参考图")
    elif not no_person_mode:
        provided_media_labels.append("授权人物参考图")
    if has_scene_ref:
        provided_media_labels.append("场景参考图")
    media_order = "第1个媒体是待审核视频；"
    if provided_media_labels:
        media_order += "随后依次是%s。" % "、".join(provided_media_labels)
    else:
        media_order += "没有其他参考媒体。"
    if no_person_mode:
        media_order += "当前是纯产品视频模式，不检查人物人脸。"
    if not has_product_ref and not has_scene_ref:
        media_order += "未提供产品参考图且未提供场景参考图。"
    elif not has_product_ref:
        media_order += "未提供产品参考图。"
    elif not has_scene_ref:
        media_order += "未提供场景参考图，不检查场景。"
    media_order += source_product_rule
    face_rule = (
        "当前没有人物参考，faceMatch 固定输出 true；"
        if no_person_mode
        else "faceMatch 要求人脸身份稳定且与授权人物一致；"
    )
    principal_rule = (
        "主角模式还必须检查 principalReplacementMatch、otherSubjectsPreserved 和 motionPreserved："
        "主角应采用上传人物的完整外观，其他人物不能被替换，动作/站位/镜头时序必须沿用原片。"
        "同时必须检查 fullBodyAppearanceMatch：生成主角的发型、服装、体型和配饰必须来自上传人物参考图；"
        "白衬衫搭配深色职业马甲、西装外套、西装裤或职业半裙属于职业套装，不要误判为吊带裙；"
        "如果仍保留原片主角的长发、休闲装、西装、制服、体型或配饰，则 fullBodyAppearanceMatch=false。"
        if principal_mode else ""
    )
    schema = (
        '{"sourceProductVisible":true或false,"faceMatch":true或false,"productMatch":true或false,'
        '"logoTextReadable":true或false,"sceneMatch":true或false,'
        '"topicMatch":true或false,"roleMatch":true或false,"structureMatch":true或false,'
        '"severeDrift":true或false,"reason":"简短原因"}'
    )
    if principal_mode:
        schema = (
            '{"sourceProductVisible":true或false,"faceMatch":true或false,"productMatch":true或false,'
            '"logoTextReadable":true或false,"sceneMatch":true或false,'
            '"topicMatch":true或false,"roleMatch":true或false,"structureMatch":true或false,'
            '"severeDrift":true或false,"principalReplacementMatch":true或false,'
            '"fullBodyAppearanceMatch":true或false,"otherSubjectsPreserved":true或false,'
            '"motionPreserved":true或false,"reason":"简短原因"}'
        )
    prompt = (
        "你是短视频生成质量审核器。%s"
        "检查待审核视频首中尾全过程，仅输出一个 JSON 对象，不要 Markdown："
        "%s。%s"
        "%sproductMatch 要求形状、颜色、包装一致；"
        "logoTextReadable 要求 logo 和主要包装文字可辨识；sceneMatch 只判断上传场景参考是否被结果采用。"
        "未提供场景参考时 sceneMatch 固定输出 true；提供场景参考后必须检查结果是否替换为上传场景，不允许以源视频场景优先放行。"
        "topicMatch 要求待审核视频仍属于原视频行业和商品主题；roleMatch 要求人物角色仍符合原视频，例如汽车门店销售不能变成美妆主播；"
        "如果原片片段本身是无人物的产品特写、车身、车内或新车预告镜头，不要因为待审核视频没有人物而判 roleMatch=false。"
        "structureMatch 要求镜头结构和营销讲解结构没有严重改变；单纯从车内特写变为车身特写、产品角度变化、字幕缺失或人物有无变化只能作为 warning。"
        "只有跨行业、跨品类或完全无关内容才 severeDrift=true，例如汽车讲解变成化妆品特写、食品带货或无关生活方式视频。"
        "场景描述：%s" % (
            media_order, schema, principal_rule, face_rule,
            str(job.get("scenePrompt") or "与场景参考图一致")[:300]
        )
    )
    raw = lk888_vision(prompt, media_urls, max_tokens=500)
    match = _re.search(r"\{[\s\S]*\}", str(raw or ""))
    if not match:
        return {"ok": False, "code": "visual_qc_invalid_response", "raw": str(raw or "")[:200]}
    try:
        parsed = _json.loads(match.group(0))
    except Exception:
        return {"ok": False, "code": "visual_qc_invalid_response", "raw": str(raw or "")[:200]}
    principal_qc = _parse_principal_visual_qc(match.group(0)) if principal_mode else None
    source_product_visible = parsed.get("sourceProductVisible")
    if source_product_visible is not False:
        source_product_visible = True
    visual_drift = {
        "topicMatch": parsed.get("topicMatch") is not False,
        "roleMatch": parsed.get("roleMatch") is not False,
        "structureMatch": parsed.get("structureMatch") is not False,
        "severeDrift": parsed.get("severeDrift") is True,
        "reason": str(parsed.get("reason") or "")[:240],
    }
    product_check = "skipped_source_absent" if source_product_visible is False else (
        "passed" if parsed.get("productMatch") is True else "failed")
    logo_check = "skipped_source_absent" if source_product_visible is False else (
        "passed" if parsed.get("logoTextReadable") is True else "failed")
    scene_match = parsed.get("sceneMatch") is True
    if not has_scene_ref:
        scene_check = "skipped"
    elif scene_match:
        scene_check = "passed"
    else:
        scene_check = "failed"
    checks = {
        "face": "skipped" if no_person_mode else ("passed" if parsed.get("faceMatch") is True else "failed"),
        "product": product_check,
        "logoText": logo_check,
        "scene": scene_check,
    }
    if principal_qc:
        checks.update({
            "principalReplacement": "passed" if principal_qc["principalReplacementMatch"] else "failed",
            "fullBodyAppearance": "passed" if principal_qc["fullBodyAppearanceMatch"] else "failed",
            "otherSubjects": "passed" if principal_qc["otherSubjectsPreserved"] else "failed",
            "motion": "passed" if principal_qc["motionPreserved"] else "failed",
        })
    if principal_qc and not principal_qc.get("ok"):
        code = principal_qc.get("code") or "principal_visual_qc_failed"
    elif visual_drift["severeDrift"] or not visual_drift["topicMatch"]:
        code = "visual_drift_blocked"
    elif not visual_drift["roleMatch"]:
        code = "role_mismatch"
    elif not visual_drift["structureMatch"]:
        code = "structure_mismatch"
    elif checks["face"] == "failed":
        code = "face_mismatch"
    elif checks["product"] == "failed" or checks["logoText"] == "failed":
        code = "product_mismatch"
    elif checks["scene"] == "failed":
        code = "scene_mismatch"
    else:
        code = "ok"
    return {"ok": code == "ok", "code": code, "checks": checks,
            "visualDriftQc": visual_drift,
            "principalVisualQc": principal_qc,
            "principalReplacementMatch": (
                principal_qc.get("principalReplacementMatch") if principal_qc else None
            ),
            "fullBodyAppearanceMatch": (
                principal_qc.get("fullBodyAppearanceMatch") if principal_qc else None
            ),
            "otherSubjectsPreserved": (
                principal_qc.get("otherSubjectsPreserved") if principal_qc else None
            ),
            "motionPreserved": principal_qc.get("motionPreserved") if principal_qc else None,
            "sourceProductVisible": bool(source_product_visible),
            "reason": str(parsed.get("reason") or "")[:240], "resultUrl": result_url}


def _run_replacement_segment_qc(job, segment, video_path=None):
    """Run deterministic media/audio gates and collect frames for manual visual approval."""
    job = job or {}
    segment = segment or {}
    path = video_path or segment.get("faceSwapPath") or segment.get("videoPath") or ""
    media = _breakdown_source_validation(path)
    if not media.get("ok"):
        return {"ok": False, "code": media.get("code") or "media_invalid", "frames": []}
    audio = _replacement_audio_qc(path)
    if not audio.get("ok"):
        return {"ok": False, "code": audio.get("code") or "audio_failed",
                "audio": audio, "frames": []}
    frames = _extract_replacement_qc_frames(
        path,
        os.path.join(job.get("outDir") or data_dir(), "qc_frames"),
        segment.get("index") or 1,
    )
    if len(frames) != 3:
        return {"ok": False, "code": "qc_frames_incomplete", "audio": audio, "frames": frames}
    visual = None
    no_person_mode = _replacement_no_person_mode(job)
    principal_mode = _principal_replacement_enabled(job)
    if principal_mode:
        has_visual_refs = bool(job.get("personReferenceUrls"))
    elif no_person_mode:
        has_visual_refs = bool(job.get("productImageUrls"))
    else:
        has_visual_refs = bool(job.get("productImageUrls") and job.get("modelFaceUrl"))
    if has_visual_refs and str(os.getenv("VIDEO_REPLACE_VISUAL_QC", "1")).strip().lower() not in ("0", "false", "no"):
        try:
            visual = _run_replacement_visual_qc(job, segment, path)
        except Exception as exc:
            error_id = _replacement_error_id(
                "video_replace_visual_qc_failed", exc,
                segment_index=segment.get("index"), source_video=job.get("sourceVideoPath") or "",
            )
            visual = {
                "ok": True,
                "code": "visual_qc_deferred",
                "errorId": error_id,
                "severity": "deferred",
                "reason": "视觉质检服务异常，已降级为人工审核",
                "checks": {
                    "face": "awaiting_review",
                    "product": "awaiting_review",
                    "logoText": "awaiting_review",
                    "scene": "awaiting_review",
                    **({
                        "principalReplacement": "awaiting_review",
                        "fullBodyAppearance": "awaiting_review",
                        "otherSubjects": "awaiting_review",
                        "motion": "awaiting_review",
                    } if principal_mode else {}),
                },
            }
            return {
                "ok": True,
                "code": "visual_qc_deferred",
                "audio": audio,
                "frames": frames,
                "checks": dict({"media": "passed", "audio": "passed"}, **visual["checks"]),
                "visual": visual,
            }
        if principal_mode and visual.get("code") == "principal_visual_qc_invalid_response":
            return {
                "ok": True,
                "code": "visual_qc_deferred",
                "audio": audio,
                "frames": frames,
                "visual": visual,
                "checks": dict(
                    {"media": "passed", "audio": "passed"},
                    **(visual.get("checks") or {
                        "principalReplacement": "awaiting_review",
                        "fullBodyAppearance": "awaiting_review",
                        "otherSubjects": "awaiting_review",
                        "motion": "awaiting_review",
                    })
                ),
            }
        if not visual.get("ok"):
            if visual.get("visualDriftQc"):
                segment["visualDriftQc"] = dict(visual.get("visualDriftQc") or {})
            warning = {
                "code": visual.get("code") or "visual_qc_failed",
                "reason": str(visual.get("reason") or "")[:240],
                "checks": dict(visual.get("checks") or {}),
                "resultUrl": visual.get("resultUrl") or "",
            }
            warning["severity"] = _replacement_qc_warning_severity(warning["code"])
            segment["qcWarnings"] = list(segment.get("qcWarnings") or []) + [warning]
            if principal_mode and _replacement_principal_visual_qc_blocks(job, warning["code"]):
                return {"ok": False, "code": warning["code"],
                        "audio": audio, "frames": frames, "visual": visual,
                        "warnings": [warning]}
            if _replacement_is_hard_drift_code(warning["code"]) and _replacement_block_severe_drift(job):
                return {"ok": False, "code": warning["code"],
                        "audio": audio, "frames": frames, "visual": visual,
                        "warnings": [warning], "retryableDrift": True}
            if _replacement_visual_qc_blocks(job):
                return {"ok": False, "code": warning["code"],
                        "audio": audio, "frames": frames, "visual": visual,
                        "warnings": [warning]}
            return {
                "ok": True,
                "code": "visual_qc_warning",
                "audio": audio,
                "frames": frames,
                "visual": visual,
                "warnings": [warning],
                "checks": dict({"media": "passed", "audio": "passed"}, **(visual.get("checks") or {})),
            }
    face_similarity = None
    if not no_person_mode and not principal_mode and _replacement_face_similarity_enabled(job):
        visual_face_failed = bool(
            isinstance(visual, dict) and (visual.get("checks") or {}).get("face") == "failed")
        if not visual_face_failed:
            face_similarity = _run_replacement_face_similarity_qc(job, segment, path, frames=frames)
            if face_similarity.get("score") is not None:
                segment["faceSimilarity"] = {
                    "score": face_similarity.get("score"),
                    "threshold": face_similarity.get("threshold"),
                    "method": face_similarity.get("method") or "vision",
                }
            if not face_similarity.get("ok") and face_similarity.get("code") == "face_similarity_low":
                warning = {
                    "code": "face_similarity_low",
                    "reason": ("人脸相似度 %.0f 低于阈值 %.0f：%s" % (
                        float(face_similarity.get("score") or 0),
                        float(face_similarity.get("threshold") or 0),
                        str(face_similarity.get("reason") or "")))[:240],
                    "severity": _replacement_qc_warning_severity("face_similarity_low"),
                }
                segment["qcWarnings"] = list(segment.get("qcWarnings") or []) + [warning]
                if _replacement_visual_qc_blocks(job):
                    return {"ok": False, "code": "face_similarity_low",
                            "audio": audio, "frames": frames, "visual": visual,
                            "faceSimilarity": face_similarity, "warnings": [warning]}
                return {
                    "ok": True,
                    "code": "face_similarity_warning",
                    "audio": audio,
                    "frames": frames,
                    "visual": visual,
                    "faceSimilarity": face_similarity,
                    "warnings": [warning],
                    "checks": dict({"media": "passed", "audio": "passed"}, **((visual or {}).get("checks") or {})),
                }
    return {
        "ok": True,
        "code": "ok",
        "audio": audio,
        "frames": frames,
        "faceSimilarity": face_similarity,
        "checks": dict({
            "media": "passed",
            "audio": "passed",
        }, **((visual or {}).get("checks") or {
            "face": "awaiting_review", "product": "awaiting_review",
            "logoText": "awaiting_review", "scene": "awaiting_review",
        })),
        "visual": visual or {},
        "principalVisualQc": (visual or {}).get("principalVisualQc") if visual else None,
    }


def _subtitle_safe_source_enabled(job=None):
    job = job or {}
    if "subtitleSafeSource" in job:
        return _replacement_truthy(job.get("subtitleSafeSource"))
    return _env_enabled("VIDEO_REPLACE_SUBTITLE_SAFE_SOURCE", "1")


def _prepare_subtitle_safe_source_segment(job, segment, source_segment):
    source_segment = str(source_segment or "").strip()
    if not _subtitle_safe_source_enabled(job):
        return source_segment
    if not (source_segment and os.path.isfile(source_segment)):
        return source_segment
    segment = segment or {}
    out_dir = (job or {}).get("outDir") or os.path.dirname(source_segment) or data_dir()
    try:
        idx = int(segment.get("index") or 1)
    except (TypeError, ValueError):
        idx = 1
    safe_path = os.path.join(out_dir, "source_%02d_subtitle_safe.mp4" % idx)
    os.makedirs(os.path.dirname(safe_path) or ".", exist_ok=True)
    if os.path.abspath(safe_path) == os.path.abspath(source_segment):
        base, ext = os.path.splitext(source_segment)
        safe_path = base + ".subtitle-safe" + (ext or ".mp4")
    filter_expr = (
        "drawbox=x=0:y=0:w=iw:h=ih*0.16:color=black@0.92:t=fill,"
        "drawbox=x=0:y=ih*0.74:w=iw:h=ih*0.26:color=black@0.92:t=fill"
    )
    completed = subprocess.run(
        [
            _ffmpeg_exe(), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", source_segment, "-vf", filter_expr,
            "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "2",
            safe_path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not validate_video_file(safe_path).get("ok"):
        segment["sourceSegmentSubtitleSafeStatus"] = "failed"
        segment["sourceSegmentSubtitleSafeError"] = str(completed.stderr or "")[:180]
        log("subtitle safe source failed: %s" % str(completed.stderr or "")[:160])
        return source_segment
    segment["sourceSegmentSubtitleSafeStatus"] = "masked"
    segment["sourceSegmentUploadPath"] = safe_path
    return safe_path


def _run_hybrid_non_talking_segment(job, segment):
    job = job or {}
    segment = segment or {}
    out_dir = job.get("outDir") or data_dir()
    os.makedirs(out_dir, exist_ok=True)
    idx = int(segment.get("index") or 1)
    def output_path(name):
        path = os.path.join(out_dir, name)
        if "/" in str(out_dir) and "\\" not in str(out_dir):
            return path.replace("\\", "/")
        return path

    source_segment = segment.get("sourceSegmentPath") or output_path("source_%02d.mp4" % idx)
    if not segment.get("sourceSegmentPath"):
        _extract_replacement_segment(job.get("sourceVideoPath") or "", segment, source_segment)
    segment["sourceSegmentPath"] = source_segment
    principal_mode = _principal_replacement_enabled(job)
    edit_stage = "principal_video_edit" if principal_mode else "video_edit"
    try:
        segment["status"] = edit_stage
        edit_message = (
            "生成片段 %s：上传源片段并准备主角整身替换" % idx
            if principal_mode else
            "生成片段 %s：上传源片段并准备远程编辑" % idx
        )
        _replacement_emit_stage(job, segment, edit_stage, edit_message)
        source_upload_path = _prepare_subtitle_safe_source_segment(job, segment, source_segment)
        segment["sourceSegmentUploadPath"] = source_upload_path
        upload_title = (
            "同款替换字幕安全源片段%d" % idx
            if os.path.abspath(str(source_upload_path)) != os.path.abspath(str(source_segment))
            else "同款替换源片段%d" % idx
        )
        source_url, upload_response = upload_asset_url(source_upload_path, upload_title, "video")
        segment["sourceSegmentUrl"] = str(source_url or "").strip()
        uploaded_id = str((upload_response or {}).get("id") or (upload_response or {}).get("materialId") or "").strip()
        if uploaded_id:
            job.setdefault("temporaryMaterialIds", []).append(uploaded_id)
            segment["sourceSegmentMaterialId"] = uploaded_id
        try:
            _save_replacement_job(job)
        except Exception as exc:
            _replacement_error_id(
                "video_replace_source_upload_record_failed", exc,
                segment_index=idx,
                source_video=job.get("sourceVideoPath") or "",
            )
        _prepare_replacement_continuity_frame_ref(job, segment)
        if _replacement_action_control_enabled(job):
            _prepare_replacement_action_frame_refs(job, segment, out_dir)
            try:
                _save_replacement_job(job)
            except Exception:
                pass
        _prepare_replacement_product_anchor(job, segment, out_dir)
        model, payload = _build_hybrid_video_edit_request(job, segment, source_url)
        candidates = list(payload.get("model_candidates") or [model])
        edited_url = ""
        remote_fallbacks = []
        last_exc = None
        for candidate in candidates:
            segment["model"] = candidate
            remote_payload = _replacement_remote_video_payload_for_model(payload, candidate)
            segment["remoteRequestFields"] = sorted(str(key) for key in remote_payload)
            def edit_progress(i, current_model=candidate):
                _replacement_emit_stage(
                    job, segment, edit_stage,
                    "生成片段 %s：远程视频编辑中（%s，轮询%d次）" % (idx, current_model, i + 1),
                )
            try:
                edited_url = _lk888_media_task_with_cancel(
                    candidate, remote_payload, ["mp4", "mov", "webm"],
                    progress=edit_progress,
                    tries=int(job.get("tries") or 150),
                    cancel_check=_replacement_cancel_check(job),
                )
                break
            except Exception as exc:
                if _replacement_cancel_exception(exc) or _replacement_cancel_requested(job):
                    segment.update({"status": "cancel_requested", "stage": "cancel_requested",
                                    "stageLabel": "取消中"})
                    raise
                last_exc = exc
                remote_error_event = (
                    "principal_video_edit_unavailable"
                    if principal_mode and _principal_video_edit_unavailable(exc)
                    else ("principal_video_edit_failed" if principal_mode else "video_replace_remote_model_failed")
                )
                error_id = _replacement_error_id(
                    remote_error_event, exc,
                    segment_index=idx, model=candidate,
                    source_video=job.get("sourceVideoPath") or "",
                )
                item = {"model": candidate, "error": str(exc)[:180], "errorId": error_id}
                remote_fallbacks.append(item)
                segment["remoteModelFallbacks"] = list(remote_fallbacks)
                if not segment.get("remoteError"):
                    segment["remoteError"] = item["error"]
                    segment["remoteErrorId"] = error_id
                try:
                    _save_replacement_job(job)
                except Exception:
                    pass
                _replacement_emit_stage(
                    job, segment, edit_stage,
                    (
                        "生成片段 %s：主角整身替换失败，已停止且未回退其他生成模型" % idx
                        if principal_mode else
                        "生成片段 %s：%s 未返回可用视频，切换下一个模型" % (idx, candidate)
                    ),
                )
        if not edited_url:
            if principal_mode:
                failure_code = (
                    "principal_video_edit_unavailable"
                    if last_exc and _principal_video_edit_unavailable(last_exc)
                    else "principal_video_edit_failed"
                )
                raise RuntimeError(failure_code) from last_exc
            raise last_exc or RuntimeError("video_replace_remote_no_output")
        segment["remoteError"] = ""
        segment["remoteErrorId"] = ""
        edited_path = output_path("edited_%02d.mp4" % idx)
        segment["status"] = "downloading"
        _replacement_emit_stage(job, segment, "downloading", "生成片段 %s：下载远程编辑结果" % idx)
        _wf_download(edited_url, edited_path)
        if os.path.isfile(edited_path) and not _breakdown_source_validation(edited_path).get("ok"):
            raise RuntimeError("edited_video_invalid")
        if _replacement_no_person_mode(job) or not _replacement_enable_facefusion(job):
            segment.update({"status": "audio_muxing", "editedVideoPath": edited_path, "faceSwapPath": ""})
            audio_mode = _replacement_audio_mode(job)
            if audio_mode == "tts":
                _replacement_emit_stage(job, segment, "audio_muxing", "生成片段 %s：替换为所选音色配音" % idx)
                _replace_replacement_segment_audio_with_tts(job, segment, edited_path)
            else:
                _replacement_emit_stage(job, segment, "audio_muxing", "生成片段 %s：回填源片段音频" % idx)
                if principal_mode:
                    _replace_segment_audio_from_source(source_segment, edited_path)
                else:
                    _ensure_segment_audio(source_segment, edited_path)
                segment["audioMode"] = "source"
            segment["audioStatus"] = "passed"
            segment["status"] = "qc"
            _replacement_emit_stage(job, segment, "qc", "生成片段 %s：执行音频和视觉质检" % idx)
            qc = _run_replacement_segment_qc(job, segment, edited_path)
            segment["qcFrames"] = list(qc.get("frames") or [])
            segment["qcChecks"] = dict(qc.get("checks") or {})
            if not qc.get("ok"):
                if _replacement_can_retry_ai_scene_fallback(job, segment, qc):
                    _replacement_mark_ai_scene_fallback(job, segment, qc)
                    _save_replacement_job(job)
                    _replacement_emit_stage(
                        job,
                        segment,
                        edit_stage,
                        "生成片段 %s：场景与动作冲突，降级为 AI 生成场景后重试" % idx,
                    )
                    return _run_hybrid_non_talking_segment(job, segment)
                if _replacement_can_retry_drift(job, segment, qc):
                    _replacement_mark_drift_retry(job, segment, qc)
                    _save_replacement_job(job)
                    _replacement_emit_stage(
                        job,
                        segment,
                        edit_stage,
                        "生成片段 %s：主题跑偏，正在强化原视频锁定后重试" % idx,
                    )
                    return _run_hybrid_non_talking_segment(job, segment)
                if _replacement_is_severe_drift_code(qc.get("code")):
                    _replacement_mark_drift_exhausted(segment, qc)
                    _save_replacement_job(job)
                    raise RuntimeError("replacement_qc_failed:visual_drift_retry_exhausted")
                raise RuntimeError("replacement_qc_failed:%s" % (qc.get("code") or "unknown"))
            segment.update({
                "status": "done",
                "videoPath": edited_path,
                "qcStatus": "passed",
                "error": "",
                "errorId": "",
            })
            return edited_path
        segment.update({"status": "facefusion", "editedVideoPath": edited_path})
        _replacement_emit_stage(job, segment, "facefusion", "生成片段 %s：执行人脸替换" % idx)
        face_path = output_path("face_swap_%02d.mp4" % idx)
        final_path = face_path
        audio_source = edited_path
        try:
            _run_facefusion(
                edited_path,
                face_path,
                job.get("faceSourcePaths") or [],
                job.get("targetFaceReferencePath") or "",
                config=job.get("facefusionConfig"),
            )
            segment["faceSwapPath"] = face_path
            segment["facefusionStatus"] = "passed"
        except Exception as exc:
            error_id = _replacement_error_id(
                "video_replace_non_talking_facefusion_failed",
                exc,
                segment_index=idx,
                source_video=job.get("sourceVideoPath") or "",
            )
            warning = {
                "code": "facefusion_failed",
                "reason": str(exc)[:180],
                "errorId": error_id,
                "severity": "review_warning",
            }
            segment.setdefault("qcWarnings", []).append(warning)
            segment.update({
                "facefusionStatus": "fallback",
                "facefusionError": str(exc)[:180],
                "facefusionErrorId": error_id,
                "faceSwapPath": "",
            })
            final_path = edited_path
            audio_source = source_segment
        segment["status"] = "audio_muxing"
        audio_mode = _replacement_audio_mode(job)
        audio_message = "替换为所选音色配音" if audio_mode == "tts" else (
            "回填换脸后音频" if final_path == face_path else "回填源片段音频")
        _replacement_emit_stage(job, segment, "audio_muxing", "生成片段 %s：%s" % (idx, audio_message))
        if audio_mode == "tts":
            _replace_replacement_segment_audio_with_tts(job, segment, final_path)
        else:
            _ensure_segment_audio(audio_source, final_path)
            segment["audioMode"] = "source"
        segment["audioStatus"] = "passed"
        segment["status"] = "qc"
        _replacement_emit_stage(job, segment, "qc", "生成片段 %s：执行音频和视觉质检" % idx)
        qc = _run_replacement_segment_qc(job, segment, final_path)
        segment["qcFrames"] = list(qc.get("frames") or [])
        segment["qcChecks"] = dict(qc.get("checks") or {})
        if not qc.get("ok"):
            if _replacement_can_retry_ai_scene_fallback(job, segment, qc):
                _replacement_mark_ai_scene_fallback(job, segment, qc)
                _save_replacement_job(job)
                _replacement_emit_stage(
                    job,
                    segment,
                    edit_stage,
                    "生成片段 %s：场景与动作冲突，降级为 AI 生成场景后重试" % idx,
                )
                return _run_hybrid_non_talking_segment(job, segment)
            if _replacement_can_retry_drift(job, segment, qc):
                _replacement_mark_drift_retry(job, segment, qc)
                _save_replacement_job(job)
                _replacement_emit_stage(
                    job,
                    segment,
                    edit_stage,
                    "生成片段 %s：主题跑偏，正在强化原视频锁定后重试" % idx,
                )
                return _run_hybrid_non_talking_segment(job, segment)
            if _replacement_is_severe_drift_code(qc.get("code")):
                _replacement_mark_drift_exhausted(segment, qc)
                _save_replacement_job(job)
                raise RuntimeError("replacement_qc_failed:visual_drift_retry_exhausted")
            raise RuntimeError("replacement_qc_failed:%s" % (qc.get("code") or "unknown"))
        segment.update({
            "status": "done",
            "videoPath": final_path,
            "qcStatus": "passed",
            "error": "",
            "errorId": "",
        })
        return final_path
    except Exception as exc:
        if _replacement_cancel_exception(exc) or _replacement_cancel_requested(job):
            segment.update({"status": "cancel_requested", "stage": "cancel_requested",
                            "stageLabel": "取消中", "error": "", "errorId": ""})
            raise
        failure_event = (
            str(exc).split(":", 1)[0]
            if principal_mode and str(exc).startswith("principal_video_edit_")
            else "video_replace_non_talking_failed"
        )
        error_id = _replacement_error_id(
            failure_event, exc, segment_index=idx,
            source_video=job.get("sourceVideoPath") or "",
        )
        segment.update({"status": "failed", "qcStatus": "failed",
                        "error": str(exc)[:180], "errorId": error_id})
        if segment.get("audioStatus") != "passed":
            segment["audioStatus"] = "failed"
        raise


def _run_hybrid_replacement_segment(job, segment):
    job = job or {}
    segment = segment or {}
    idx = int(segment.get("index") or 1)
    try:
        audio_mode = _replacement_audio_mode(job)
        segment["segmentType"] = (
            "talking"
            if _replacement_segment_should_talk(
                segment, audio_mode=audio_mode, strict_script_audio=job.get("strictScriptAudio"))
            else "non_talking"
        )
        if _replacement_no_person_mode(job):
            segment["segmentType"] = "non_talking"
            path = _run_hybrid_non_talking_segment(job, segment)
            return {"ok": True, "segment": segment, "path": path}
        if segment.get("segmentType") == "talking":
            return _run_hybrid_lipsynced_replacement_segment(job, segment)
        path = _run_hybrid_non_talking_segment(job, segment)
        return {"ok": True, "segment": segment, "path": path}
    except Exception as exc:
        if _replacement_cancel_exception(exc) or _replacement_cancel_requested(job):
            segment.update({"status": "cancel_requested", "stage": "cancel_requested",
                            "stageLabel": "取消中", "error": "", "errorId": ""})
            raise
        if segment.get("status") != "failed":
            error_id = _replacement_error_id(
                "video_replace_segment_failed",
                exc,
                segment_index=idx,
                segment_type=segment.get("segmentType") or "unknown",
                source_video=job.get("sourceVideoPath") or "",
            )
            segment.update({
                "status": "failed",
                "audioStatus": "failed",
                "qcStatus": "failed",
                "error": str(exc)[:180],
                "errorId": error_id,
            })
        return {"ok": False, "segment": segment, "error": segment.get("error") or str(exc)[:180],
                "errorId": segment.get("errorId") or ""}


def _replacement_segments_ready_for_final(segments):
    values = list(segments or [])
    return bool(values) and all(
        item.get("status") == "done"
        and item.get("audioStatus") == "passed"
        and item.get("qcStatus") == "passed"
        and item.get("reviewApproved") is True
        for item in values
    )


def _extract_replacement_source_frame(video_path, segment, out_dir):
    if not (video_path and os.path.isfile(video_path)):
        return ""
    os.makedirs(out_dir, exist_ok=True)
    try:
        start = max(0.0, float((segment or {}).get("start") or 0) + 0.15)
    except Exception:
        start = 0.15
    path = os.path.join(out_dir, "source_frame_%02d.jpg" % int((segment or {}).get("index") or 1))
    cmd = [
        _ffmpeg_exe(), "-y", "-ss", "%.2f" % start, "-i", video_path,
        "-frames:v", "1", "-q:v", "2", path,
    ]
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, creationflags=cflags)
    except Exception as exc:
        log("replacement source frame: %s" % str(exc)[:120])
        return ""
    return path if os.path.isfile(path) and os.path.getsize(path) > 1000 else ""


def _extract_replacement_action_frames(video_path, segment, out_dir, interval_sec=2.0, max_frames=4):
    if not (video_path and os.path.isfile(video_path)):
        return []
    os.makedirs(out_dir, exist_ok=True)
    segment = segment or {}
    try:
        start = max(0.0, float(segment.get("start") or 0))
    except (TypeError, ValueError):
        start = 0.0
    try:
        end = float(segment.get("end") if segment.get("end") is not None else start + float(segment.get("duration") or 8))
    except (TypeError, ValueError):
        end = start + 8.0
    end = max(start + 0.1, end)
    try:
        interval = max(0.5, float(interval_sec or 2.0))
    except (TypeError, ValueError):
        interval = 2.0
    try:
        limit = max(1, int(max_frames or 4))
    except (TypeError, ValueError):
        limit = 4
    idx = int(segment.get("index") or 1)
    timestamps = []
    current = start + 0.15
    while current < end and len(timestamps) < limit:
        timestamps.append(current)
        current += interval
    if not timestamps:
        timestamps = [start + 0.15]
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    frames = []
    for frame_no, timestamp in enumerate(timestamps, 1):
        path = os.path.join(out_dir, "action_frame_%02d_%02d.jpg" % (idx, frame_no))
        cmd = [
            _ffmpeg_exe(), "-y", "-ss", "%.2f" % max(0.0, timestamp), "-i", video_path,
            "-frames:v", "1", "-q:v", "2", path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60, creationflags=cflags)
        except Exception as exc:
            log("replacement action frame: %s" % str(exc)[:120])
            continue
        if os.path.isfile(path) and os.path.getsize(path) > 1000:
            frames.append(path)
    return frames


def _prepare_replacement_action_frame_refs(job, segment, out_dir):
    job = job or {}
    segment = segment or {}
    segment["actionFrameUrls"] = []
    if not _replacement_action_control_enabled(job):
        return []
    idx = int(segment.get("index") or 1)
    try:
        frames = _extract_replacement_action_frames(
            job.get("sourceVideoPath") or "",
            segment,
            out_dir,
            interval_sec=2.0,
            max_frames=4,
        )
        segment["actionFramePaths"] = list(frames)
        if not frames:
            raise RuntimeError("no action frames extracted")
        urls = []
        material_ids = []
        for frame_idx, frame_path in enumerate(frames, 1):
            url, response = upload_asset_url(frame_path, "同款替换动作帧%d-%d" % (idx, frame_idx), "image")
            url = str(url or "").strip()
            if not _is_remote_fetchable_media_url(url):
                raise RuntimeError("action frame url is not remote fetchable")
            urls.append(url)
            material_ids.extend(_uploaded_material_ids(response))
        segment["actionFrameUrls"] = list(urls)
        if material_ids:
            job["temporaryMaterialIds"] = list(dict.fromkeys(
                list(job.get("temporaryMaterialIds") or []) + material_ids
            ))
        segment["actionControlWarning"] = ""
        return urls
    except Exception as exc:
        segment["actionFrameUrls"] = []
        segment["actionControlWarning"] = str(exc)[:180]
        _replacement_error_id(
            "video_replace_action_control_fallback",
            exc,
            segment_index=idx,
            source_video=job.get("sourceVideoPath") or "",
        )
        return []


def _replacement_product_anchor_enabled(job=None):
    job = job or {}
    value = job.get("productAnchorEnabled")
    if value is not None:
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return _env_enabled("VIDEO_REPLACE_PRODUCT_ANCHOR", "1")


def _detect_replacement_product_shot(segment, frame_urls, product_urls):
    """视觉判断源片段抽帧中是否出现参考产品，返回 {visible, bestFrame, reason}。"""
    import json as _json
    import re as _re
    frame_urls = list(frame_urls or [])
    prompt = (
        "你是短视频同款替换的产品镜头检测器。前 %d 张图像是同一源视频片段按时间抽取的画面，"
        "后面的图像是用户上传的目标产品参考图。"
        "判断这些画面中是否出现了与参考图同类别、需要被替换的产品（手持、摆放或特写均可）。"
        "仅输出 JSON："
        '{"visible":true或false,"bestFrame":画面序号(从1开始,产品最大最清晰的一帧,无则0),"reason":"简短原因"}。'
    ) % max(1, len(frame_urls))
    raw = lk888_vision(prompt, frame_urls + list(product_urls or []), max_tokens=300)
    match = _re.search(r"\{[\s\S]*\}", str(raw or ""))
    if not match:
        raise RuntimeError("product_shot_detect_invalid_response")
    parsed = _json.loads(match.group(0))
    try:
        best = int(parsed.get("bestFrame") or 0)
    except (TypeError, ValueError):
        best = 0
    return {
        "visible": parsed.get("visible") is True or str(parsed.get("visible") or "").strip().lower() in ("1", "true", "yes"),
        "bestFrame": max(0, min(best, len(frame_urls))),
        "reason": str(parsed.get("reason") or "")[:160],
    }


def _prepare_replacement_product_anchor(job, segment, out_dir):
    """检测源片段产品镜头并合成『产品已替换』锚定帧，作为强参考注入视频编辑请求。
    检测未命中或任何失败都回退标准链路（仅参考图+提示词约束），不阻断生成。"""
    job = job or {}
    segment = segment or {}
    existing = str(segment.get("productAnchorFrameUrl") or "").strip()
    if existing:
        return existing
    segment["productAnchorFrameUrl"] = ""
    if not _replacement_product_anchor_enabled(job):
        segment["productAnchorStatus"] = "disabled"
        return ""
    if str(segment.get("productAnchorStatus") or "") == "skipped_no_product":
        return ""
    idx = int(segment.get("index") or 1)
    product_urls = [str(u or "").strip() for u in (job.get("productImageUrls") or []) if str(u or "").strip()]
    if not product_urls:
        segment["productAnchorStatus"] = "skipped_no_product"
        return ""
    try:
        anchor_dir = os.path.join(out_dir, "product_anchor")
        try:
            duration = float(segment.get("duration") or 8) or 8.0
        except (TypeError, ValueError):
            duration = 8.0
        frames = _extract_replacement_action_frames(
            job.get("sourceVideoPath") or "",
            segment,
            anchor_dir,
            interval_sec=max(1.0, duration / 3.0),
            max_frames=3,
        )
        if not frames:
            raise RuntimeError("product anchor: no frames extracted")
        frame_urls = []
        material_ids = []
        for frame_no, frame_path in enumerate(frames, 1):
            url, response = upload_asset_url(frame_path, "同款替换产品检测帧%d-%d" % (idx, frame_no), "image")
            url = str(url or "").strip()
            if not _is_remote_fetchable_media_url(url):
                raise RuntimeError("product anchor frame url is not remote fetchable")
            frame_urls.append(url)
            material_ids.extend(_uploaded_material_ids(response))
        detection = _detect_replacement_product_shot(segment, frame_urls, product_urls)
        segment["productAnchorDetection"] = detection
        if not detection.get("visible"):
            segment["productAnchorStatus"] = "skipped_no_product"
            if material_ids:
                job["temporaryMaterialIds"] = list(dict.fromkeys(
                    list(job.get("temporaryMaterialIds") or []) + material_ids
                ))
            return ""
        best = int(detection.get("bestFrame") or 0)
        base_url = frame_urls[best - 1] if 1 <= best <= len(frame_urls) else frame_urls[len(frame_urls) // 2]
        prompt = (
            "将第一张视频画面中的产品替换为后面参考图中的产品。"
            "严格保持视频画面的构图、人物、姿态、背景、光影和镜头角度完全不变，只替换产品本体；"
            "产品的外形、颜色、Logo、包装文字和材质必须以产品参考图为准。"
            "不要添加任何文字、水印或装饰元素。"
        )
        img, public_url = lk888_image_result(
            prompt,
            size=job.get("keyframeSize") or "1024x1792",
            image_urls=[base_url] + product_urls[:2],
        )
        if not img or len(img) < 64:
            raise RuntimeError("product anchor image empty")
        os.makedirs(anchor_dir, exist_ok=True)
        anchor_path = os.path.join(anchor_dir, "product_anchor_%02d.png" % idx)
        with open(anchor_path, "wb") as fh:
            fh.write(img)
        library_url, response = upload_asset_url(anchor_path, "同款替换产品锚定帧%d" % idx, "image")
        material_ids.extend(_uploaded_material_ids(response))
        anchor_url = public_url if _is_remote_fetchable_media_url(public_url) else ""
        if not anchor_url:
            library_url = str(library_url or "").strip()
            if _is_remote_fetchable_media_url(library_url):
                anchor_url = library_url
        if not anchor_url:
            raise RuntimeError("product anchor url is not remote fetchable")
        if material_ids:
            job["temporaryMaterialIds"] = list(dict.fromkeys(
                list(job.get("temporaryMaterialIds") or []) + material_ids
            ))
        segment["productAnchorFramePath"] = anchor_path
        segment["productAnchorFrameUrl"] = anchor_url
        segment["productAnchorStatus"] = "ok"
        segment["productAnchorWarning"] = ""
        return anchor_url
    except Exception as exc:
        segment["productAnchorFrameUrl"] = ""
        segment["productAnchorStatus"] = "failed"
        segment["productAnchorWarning"] = str(exc)[:180]
        _replacement_error_id(
            "video_replace_product_anchor_fallback",
            exc,
            segment_index=idx,
            source_video=job.get("sourceVideoPath") or "",
        )
        return ""


def _prepare_replacement_continuity_frame_ref(job, segment):
    job = job or {}
    segment = segment or {}
    segment["continuityFrameUrl"] = ""
    try:
        idx = int(segment.get("index") or 0)
    except (TypeError, ValueError):
        idx = 0
    if idx <= 1:
        return ""
    previous = None
    for item in job.get("segments") or []:
        try:
            if int(item.get("index") or 0) == idx - 1:
                previous = item
                break
        except (TypeError, ValueError):
            continue
    if not previous:
        return ""
    frame_path = ""
    for value in reversed(list(previous.get("qcFrames") or [])):
        value = str(value or "").strip()
        if value and os.path.isfile(value):
            frame_path = value
            break
    if not frame_path:
        return ""
    try:
        url, response = upload_asset_url(frame_path, "同款替换上一段连续性参考%d" % idx, "image")
        url = str(url or "").strip()
        if not _is_remote_fetchable_media_url(url):
            raise RuntimeError("continuity frame url is not remote fetchable")
        segment["continuityFrameUrl"] = url
        material_ids = _uploaded_material_ids(response)
        if material_ids:
            job["temporaryMaterialIds"] = list(dict.fromkeys(
                list(job.get("temporaryMaterialIds") or []) + material_ids
            ))
        segment["continuityFrameWarning"] = ""
        return url
    except Exception as exc:
        segment["continuityFrameWarning"] = str(exc)[:180]
        _replacement_error_id(
            "video_replace_continuity_frame_fallback",
            exc,
            segment_index=idx,
            source_video=job.get("sourceVideoPath") or "",
        )
        return ""


def _replacement_previous_keyframe_url(job, segment):
    try:
        idx = int((segment or {}).get("index") or 0)
    except Exception:
        idx = 0
    if idx <= 1:
        return ""
    for item in job.get("segments") or []:
        try:
            if int(item.get("index") or 0) == idx - 1:
                value = str(item.get("keyframeUrl") or "").strip()
                return value if _is_remote_fetchable_media_url(value) else ""
        except Exception:
            continue
    return ""


def _replacement_previous_keyframe_path(job, segment):
    try:
        idx = int((segment or {}).get("index") or 0)
    except Exception:
        idx = 0
    if idx <= 1:
        return ""
    for item in job.get("segments") or []:
        try:
            if int(item.get("index") or 0) == idx - 1:
                value = str(item.get("keyframePath") or "").strip()
                return value if os.path.isfile(value) else ""
        except Exception:
            continue
    return ""


def _build_replacement_keyframe_references(job, segment, source_frame="", previous_anchor=""):
    """Build ephemeral image inputs without persisting base64 or loopback URLs."""
    job = job or {}
    refs = []

    def add_path(path):
        value = str(path or "").strip()
        if value and os.path.isfile(value):
            if os.path.getsize(value) > _replacement_reference_max_bytes():
                raise RuntimeError("video_replace_reference_invalid_size")
            refs.append(_file_to_data_url(value))
            return True
        return False

    def add_remote(value):
        value = str(value or "").strip()
        if value.startswith("data:image/") or _is_remote_fetchable_media_url(value):
            refs.append(value)
            return True
        local_data = _central_library_image_to_data_url(value)
        if local_data:
            refs.append(local_data)
            return True
        return False

    add_path(source_frame)
    product_paths = list(job.get("productSourcePaths") or [])
    product_urls = list(job.get("productImageUrls") or [])
    for index in range(max(len(product_paths), len(product_urls))):
        path = product_paths[index] if index < len(product_paths) else ""
        url = product_urls[index] if index < len(product_urls) else ""
        if not add_path(path):
            add_remote(url)
    face_paths = list(job.get("faceSourcePaths") or [])
    if not add_path(face_paths[0] if face_paths else ""):
        add_remote(job.get("modelFaceUrl"))
    if not add_path(job.get("sceneImagePath")):
        add_remote(job.get("sceneImageUrl"))
    previous_path = _replacement_previous_keyframe_path(job, segment)
    if not add_path(previous_path):
        add_remote(previous_anchor)
    return refs


def _ensure_replacement_keyframe(job, segment):
    existing_url = str(segment.get("keyframeUrl") or "").strip()
    if _is_remote_fetchable_media_url(existing_url):
        return existing_url
    existing_path = str(segment.get("keyframePath") or "").strip()
    if existing_path and os.path.isfile(existing_path):
        segment["keyframeUrl"] = ""
        return existing_path
    out_dir = job.get("outDir") or data_dir()
    os.makedirs(out_dir, exist_ok=True)
    previous_anchor = _replacement_previous_keyframe_url(job, segment)
    source_frame = segment.get("sourceFramePath") or _extract_replacement_source_frame(
        job.get("sourceVideoPath") or "", segment, out_dir)
    if source_frame:
        segment["sourceFramePath"] = source_frame
    refs = _build_replacement_keyframe_references(
        job, segment, source_frame, previous_anchor)
    if not refs:
        raise RuntimeError("replacement_keyframe_no_reference")
    prompt = _build_replacement_keyframe_prompt(
        segment,
        job.get("breakdownAnalysis") or {},
        job.get("productNotes") or "",
        job.get("modelNotes") or "",
        has_previous_anchor=bool(previous_anchor),
    )
    size = job.get("keyframeSize") or "1024x1792"
    model = job.get("imageModel") or None
    try:
        img, public_url = lk888_image_result(
            prompt[:1800],
            size=size,
            model=model,
            image_urls=refs,
        )
        segment["keyframeStatus"] = "generated"
    except Exception as exc:
        if not _is_replacement_keyframe_transient_error(exc):
            raise
        retry_refs = _replacement_keyframe_retry_refs(refs)
        if not retry_refs:
            raise
        segment["keyframeStatus"] = "retrying"
        segment["keyframeRetryReason"] = str(exc)[:180]
        img, public_url = lk888_image_result(
            prompt[:1200],
            size=_replacement_keyframe_retry_size(),
            model=model,
            image_urls=retry_refs,
        )
        segment["keyframeStatus"] = "retry_ok"
    if not img or len(img) < 64:
        raise RuntimeError("replacement_keyframe_empty")
    path = os.path.join(out_dir, "replace_keyframe_%02d_%s.png" % (
        int(segment.get("index") or 1), os.urandom(3).hex()))
    with open(path, "wb") as f:
        f.write(img)
    library_url, _resp = upload_asset_url(
        path, "同款替换关键帧%d" % int(segment.get("index") or 1), "image")
    remote_url = public_url if _is_remote_fetchable_media_url(public_url) else ""
    segment.update({
        "keyframePath": path,
        "keyframeUrl": remote_url,
        "keyframeLibraryUrl": library_url,
    })
    return remote_url or path


def _replacement_error_id(event, exc, **ctx):
    raw = json_log(_CLIENT_JSON_LOGGER, event, exc=exc, code=event, **ctx)
    try:
        import json as _json
        return (_json.loads(raw) or {}).get("errorId") or ""
    except Exception:
        return ""


def _run_replacement_segment(job, segment):
    job = job or {}
    segment = segment or {}
    segment["status"] = "running"
    try:
        segment["status"] = "keyframing"
        keyframe_url = _ensure_replacement_keyframe(job, segment)
        previous_anchor = _replacement_previous_keyframe_url(job, segment)
        prompt = segment.get("prompt") or _build_replacement_prompt(
            segment,
            job.get("breakdownAnalysis") or {},
            job.get("productNotes") or "",
            job.get("modelNotes") or "",
        )
        if job.get("breakdownAnalysis") and "源视频锁定：" not in str(prompt):
            prompt = _replacement_source_lock_text(job) + "\n" + str(prompt or "").strip()
        prompt = _build_replacement_video_prompt(
            segment,
            prompt,
            has_keyframe=bool(keyframe_url),
            has_previous_anchor=bool(previous_anchor),
        )
        segment["prompt"] = prompt
        refs = [keyframe_url]
        if previous_anchor:
            refs.append(previous_anchor)
        refs.extend([u for u in (job.get("productImageUrls") or []) if u])
        if job.get("modelFaceUrl"):
            refs.append(job.get("modelFaceUrl"))
        segment["status"] = "running"
        model, payload = _build_replacement_video_request(job, segment, prompt, refs)
        url = _lk888_media_task_with_cancel(
            model,
            payload,
            ["mp4", "mov", "webm"],
            tries=int(job.get("tries") or 150),
            cancel_check=_replacement_cancel_check(job),
        )
        out_dir = job.get("outDir") or data_dir()
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "replace_seg_%02d_%s.mp4" % (
            int(segment.get("index") or 1), os.urandom(3).hex()))
        _wf_download(url, path)
        validation = _breakdown_source_validation(path)
        if not validation.get("ok"):
            raise RuntimeError("segment_invalid:%s" % (validation.get("code") or "media_invalid"))
        segment.update({"status": "done", "videoPath": path, "error": "", "errorId": ""})
        return {"ok": True, "segment": segment, "path": path}
    except Exception as exc:
        if _replacement_cancel_exception(exc) or _replacement_cancel_requested(job):
            segment.update({
                "status": "cancel_requested",
                "stage": "cancel_requested",
                "stageLabel": "取消中",
                "error": "",
                "errorId": "",
            })
            raise
        error_id = _replacement_error_id(
            "video_replace_segment_failed",
            exc,
            segment_index=segment.get("index"),
            source_video=job.get("sourceVideoPath") or "",
        )
        segment.update({
            "status": "failed",
            "error": str(exc)[:180],
            "errorId": error_id,
        })
        return {"ok": False, "segment": segment, "error": segment["error"], "errorId": error_id}


def _replacement_burn_subtitles_enabled(job=None):
    job = job or {}
    if "burnSubtitles" in job:
        return _replacement_truthy(job.get("burnSubtitles"))
    return _replacement_truthy(os.getenv("VIDEO_REPLACE_BURN_SUBTITLES", "1"))


def _ass_timestamp(seconds):
    seconds = max(0.0, float(seconds or 0.0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds - hours * 3600 - minutes * 60
    return "%d:%02d:%05.2f" % (hours, minutes, secs)


def _escape_ass_text(text):
    value = str(text or "").strip()
    value = value.replace("\\", "/").replace("{", "（").replace("}", "）")
    value = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    return value


def _wrap_ass_text(text, max_chars=18):
    value = _escape_ass_text(text)
    if len(value) <= max_chars:
        return value
    lines = []
    current = ""
    for ch in value:
        current += ch
        if len(current) >= max_chars and ch in "，。！？、,.!? ":
            lines.append(current.strip())
            current = ""
        elif len(current) >= max_chars:
            lines.append(current.strip())
            current = ""
    if current.strip():
        lines.append(current.strip())
    return r"\N".join(lines[:3])


def _replacement_subtitle_events(job):
    events = []
    cursor = 0.0
    for segment in (job or {}).get("segments") or []:
        script = str(segment.get("script") or "").strip()
        start = segment.get("start")
        end = segment.get("end")
        duration = 0.0
        try:
            if start is not None and end is not None:
                duration = max(0.1, float(end) - float(start))
            else:
                duration = max(0.1, float(segment.get("duration") or 0))
        except (TypeError, ValueError):
            duration = max(0.1, float(segment.get("duration") or 2.0) if segment.get("duration") else 2.0)
        actual_path = str(segment.get("videoPath") or "").strip()
        if actual_path:
            try:
                actual_duration = float((_probe_video(actual_path) or {}).get("duration") or 0)
                if actual_duration > 0.1:
                    duration = actual_duration
            except Exception:
                pass
        event_start = cursor
        event_end = cursor + duration
        cursor = event_end
        if script:
            events.append({
                "start": round(event_start, 2),
                "end": round(event_end, 2),
                "text": _wrap_ass_text(script),
                "segmentIndex": segment.get("index") or len(events) + 1,
            })
    return events


def _write_replacement_subtitle_ass(job, output_video_path):
    events = _replacement_subtitle_events(job)
    if not events:
        return {"ok": False, "code": "subtitle_no_script", "path": "", "events": []}
    out_dir = os.path.dirname(output_video_path) or (job or {}).get("outDir") or data_dir()
    os.makedirs(out_dir, exist_ok=True)
    ass_path = os.path.join(out_dir, os.path.splitext(os.path.basename(output_video_path))[0] + ".ass")
    font = str(os.getenv("VIDEO_REPLACE_SUBTITLE_FONT", "Microsoft YaHei") or "Microsoft YaHei").strip()
    font_size = int(float(os.getenv("VIDEO_REPLACE_SUBTITLE_FONT_SIZE", "54") or 54))
    margin_v = int(float(os.getenv("VIDEO_REPLACE_SUBTITLE_MARGIN_V", "92") or 92))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 720",
        "PlayResY: 1280",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,"
        "1,0,0,0,100,100,0,0,1,4,1,2,42,42,%d,1" % (font, font_size, margin_v),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for event in events:
        lines.append(
            "Dialogue: 0,%s,%s,Default,,0,0,0,,%s"
            % (_ass_timestamp(event["start"]), _ass_timestamp(event["end"]), event["text"])
        )
    with open(ass_path, "w", encoding="utf-8-sig") as handle:
        handle.write("\n".join(lines) + "\n")
    return {"ok": True, "path": ass_path, "events": events}


def _replacement_subtitle_font_file():
    candidates = []
    env_path = str(os.getenv("VIDEO_REPLACE_SUBTITLE_FONT_FILE") or "").strip()
    if env_path:
        candidates.append(env_path)
    candidates.extend([
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyh.ttf",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\notosanscjksc-regular.otf",
        r"C:\Windows\Fonts\notosanssc-regular.otf",
    ])
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


def _ffmpeg_filter_path(path):
    value = os.path.abspath(path).replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", value):
        value = value[0] + r"\:" + value[2:]
    return value.replace("'", r"\'").replace(",", r"\,")


def _burn_replacement_subtitles(job, video_path):
    job = job or {}
    if not _replacement_burn_subtitles_enabled(job):
        return {"ok": True, "mode": "disabled", "videoPath": video_path, "subtitlePath": ""}
    ass = _write_replacement_subtitle_ass(job, video_path)
    if not ass.get("ok"):
        return {"ok": True, "mode": "skipped", "videoPath": video_path, "subtitlePath": ""}
    base, ext = os.path.splitext(video_path)
    subtitled_path = base + "_subtitled" + (ext or ".mp4")
    font_file = _replacement_subtitle_font_file()
    font_dir = os.path.dirname(font_file) if font_file else ""
    subtitles_filter = "subtitles=filename='%s'" % _ffmpeg_filter_path(ass["path"])
    if font_dir:
        subtitles_filter += ":fontsdir='%s'" % _ffmpeg_filter_path(font_dir)
    cmd = [
        _ffmpeg_exe(), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-vf", subtitles_filter,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
        subtitled_path,
    ]
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=int(os.getenv("VIDEO_REPLACE_SUBTITLE_TIMEOUT_SEC", "240") or 240),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not (os.path.isfile(subtitled_path) and os.path.getsize(subtitled_path) > 1000):
        raise RuntimeError("replacement_subtitle_burn_failed:%s" % str(completed.stderr or "")[:180])
    return {"ok": True, "mode": "burned", "videoPath": subtitled_path, "subtitlePath": ass["path"]}


def _digital_human_burn_subtitles_enabled():
    return _replacement_truthy(os.getenv("DIGITAL_HUMAN_BURN_SUBTITLES", "1"))


def _split_digital_human_subtitle_text(script, max_chars=24):
    value = _escape_ass_text(script)
    if not value:
        return []
    chunks = []
    current = ""
    punctuation = "，。！？；,.!?; "
    for ch in value:
        current += ch
        if len(current) >= max_chars and ch in punctuation:
            chunks.append(current.strip())
            current = ""
        elif len(current) >= max_chars + 8:
            chunks.append(current.strip())
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk]


def _digital_human_subtitle_events(video_path, script):
    chunks = _split_digital_human_subtitle_text(script)
    if not chunks:
        return []
    try:
        duration = float((_probe_video(video_path) or {}).get("duration") or 0)
    except Exception:
        duration = 0.0
    if duration <= 0.1:
        duration = max(2.4, len(chunks) * 2.4)
    per_chunk = max(1.0, duration / max(1, len(chunks)))
    events = []
    cursor = 0.0
    for index, chunk in enumerate(chunks):
        end = duration if index == len(chunks) - 1 else min(duration, cursor + per_chunk)
        if end <= cursor:
            end = cursor + 1.0
        events.append({
            "start": round(cursor, 2),
            "end": round(end, 2),
            "text": _wrap_ass_text(chunk),
        })
        cursor = end
    return events


def _write_digital_human_subtitle_ass(video_path, script):
    events = _digital_human_subtitle_events(video_path, script)
    if not events:
        return {"ok": False, "code": "subtitle_no_script", "path": "", "events": []}
    out_dir = os.path.dirname(video_path) or data_dir()
    os.makedirs(out_dir, exist_ok=True)
    ass_path = os.path.join(out_dir, os.path.splitext(os.path.basename(video_path))[0] + ".ass")
    font = str(os.getenv("DIGITAL_HUMAN_SUBTITLE_FONT") or os.getenv("VIDEO_REPLACE_SUBTITLE_FONT") or "Microsoft YaHei").strip()
    font_size = int(float(os.getenv("DIGITAL_HUMAN_SUBTITLE_FONT_SIZE") or os.getenv("VIDEO_REPLACE_SUBTITLE_FONT_SIZE") or "54"))
    margin_v = int(float(os.getenv("DIGITAL_HUMAN_SUBTITLE_MARGIN_V") or os.getenv("VIDEO_REPLACE_SUBTITLE_MARGIN_V") or "92"))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 720",
        "PlayResY: 1280",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,"
        "1,0,0,0,100,100,0,0,1,4,1,2,42,42,%d,1" % (font, font_size, margin_v),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for event in events:
        lines.append(
            "Dialogue: 0,%s,%s,Default,,0,0,0,,%s"
            % (_ass_timestamp(event["start"]), _ass_timestamp(event["end"]), event["text"])
        )
    with open(ass_path, "w", encoding="utf-8-sig") as handle:
        handle.write("\n".join(lines) + "\n")
    return {"ok": True, "path": ass_path, "events": events}


def _burn_digital_human_subtitles(video_path, script):
    if not _digital_human_burn_subtitles_enabled():
        return {"ok": True, "mode": "disabled", "videoPath": video_path, "subtitlePath": ""}
    ass = _write_digital_human_subtitle_ass(video_path, script)
    if not ass.get("ok"):
        return {"ok": True, "mode": "skipped", "videoPath": video_path, "subtitlePath": ""}
    base, ext = os.path.splitext(video_path)
    subtitled_path = base + "_subtitled" + (ext or ".mp4")
    font_file = _replacement_subtitle_font_file()
    font_dir = os.path.dirname(font_file) if font_file else ""
    subtitles_filter = "subtitles=filename='%s'" % _ffmpeg_filter_path(ass["path"])
    if font_dir:
        subtitles_filter += ":fontsdir='%s'" % _ffmpeg_filter_path(font_dir)
    cmd = [
        _ffmpeg_exe(), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-vf", subtitles_filter,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
        subtitled_path,
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(os.getenv("DIGITAL_HUMAN_SUBTITLE_TIMEOUT_SEC", "240") or 240),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not (os.path.isfile(subtitled_path) and os.path.getsize(subtitled_path) > 1000):
            raise RuntimeError(str(completed.stderr or "")[:180])
        return {"ok": True, "mode": "burned", "videoPath": subtitled_path, "subtitlePath": ass["path"]}
    except Exception as exc:
        json_log(
            _CLIENT_JSON_LOGGER,
            "digital_human_subtitle_burn_failed",
            exc=exc,
            code="digital_human_subtitle_burn_failed",
            video_path=str(video_path or "")[:180],
            subtitle_path=str(ass.get("path") or "")[:180],
        )
        return {"ok": False, "mode": "failed", "videoPath": video_path, "subtitlePath": ass.get("path") or "", "error": str(exc)[:180]}

def _prepare_replacement_final_video(job, segment_paths, output_path):
    raw_path = _concat_replacement_segments(segment_paths, output_path)
    subtitle = _burn_replacement_subtitles(job, raw_path)
    final_path = subtitle.get("videoPath") or raw_path
    job["rawOutputPath"] = raw_path
    job["subtitleStatus"] = subtitle.get("mode") or "unknown"
    if subtitle.get("subtitlePath"):
        job["subtitlePath"] = subtitle.get("subtitlePath")
    if final_path != raw_path:
        job["subtitledOutputPath"] = final_path
    if _replacement_audio_mode(job) == "uploaded":
        job["finalAudioMode"] = "uploaded"
        final_path = _replace_replacement_final_audio(job, final_path)
    return final_path


def _concat_replacement_segments(paths, output_path):
    valid = []
    for path in paths or []:
        if not (path and os.path.isfile(path)):
            raise RuntimeError("segment_missing:%s" % path)
        validation = _breakdown_source_validation(path)
        if not validation.get("ok"):
            raise RuntimeError("segment_invalid:%s" % (validation.get("code") or "media_invalid"))
        valid.append(path)
    if not valid:
        raise RuntimeError("segment_missing:no_valid_segments")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    result = mix_clips(
        valid,
        output_path,
        size_label="竖屏 9:16",
        preserve_source_audio=True,
    )
    audio = _replacement_audio_qc(result)
    if not audio.get("ok"):
        raise RuntimeError("replacement_final_audio_failed:%s" % (audio.get("code") or "unknown"))
    return result


def _save_replacement_to_assets(output_path, job):
    if not (output_path and os.path.isfile(output_path)):
        raise RuntimeError("output_missing")
    job = job or {}
    source = job.get("sourceUrl") or job.get("sourceVideoPath") or ""
    prompt = "同款替换生成" + ((" " + source) if source else "")
    return add_asset(output_path, kind="video", prompt=prompt, source="视频替换生成")


def _parse_ffmpeg_duration(text):
    import re
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text or "")
    if not m:
        return 0.0
    return round(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 3)


def _parse_ffmpeg_size(text):
    import re
    for m in re.finditer(r"(\d{2,5})x(\d{2,5})", text or ""):
        w, h = int(m.group(1)), int(m.group(2))
        if 64 <= w <= 8192 and 64 <= h <= 8192:
            return w, h
    return 0, 0


def _probe_video(path):
    if not (path and os.path.isfile(path)):
        return {"duration": 0.0, "width": 0, "height": 0, "path": path or ""}
    try:
        cp = subprocess.run([_ffmpeg_exe(), "-hide_banner", "-i", path],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        raw = (cp.stderr or "") + "\n" + (cp.stdout or "")
        w, h = _parse_ffmpeg_size(raw)
        return {"duration": _parse_ffmpeg_duration(raw), "width": w, "height": h, "path": path}
    except Exception as e:
        log("video probe: %s" % str(e)[:100])
        return {"duration": 0.0, "width": 0, "height": 0, "path": path or "", "error": str(e)[:160]}


def _extract_breakdown_frames(path, out_dir, max_frames=16):
    if not (path and os.path.isfile(path)):
        return []
    os.makedirs(out_dir, exist_ok=True)
    meta = _probe_video(path)
    duration = float(meta.get("duration") or 0)
    count = max(6, min(int(max_frames or 16), 24))
    if duration <= 0:
        times = [0.2]
    else:
        count = min(count, max(1, int(duration)))
        step = duration / (count + 1)
        times = [max(0.1, step * (i + 1)) for i in range(count)]
    frames = []
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for idx, sec in enumerate(times):
        fp = os.path.join(out_dir, "frame_%02d.jpg" % (idx + 1))
        cmd = [_ffmpeg_exe(), "-y", "-ss", "%.2f" % sec, "-i", path, "-frames:v", "1",
               "-vf", "scale=960:-1", "-q:v", "3", fp]
        try:
            subprocess.run(cmd, capture_output=True, timeout=15, creationflags=flags)
            if os.path.isfile(fp) and os.path.getsize(fp) > 0:
                frames.append({"time": round(sec, 2), "path": fp})
        except Exception as e:
            log("breakdown frame: %s" % str(e)[:100])
    return frames


def _export_audio_for_breakdown(path, out_dir):
    if not (path and os.path.isfile(path)):
        return ""
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "audio.wav")
    cmd = [_ffmpeg_exe(), "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-t", "180", out]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out if os.path.isfile(out) and os.path.getsize(out) > 0 else ""
    except Exception as e:
        log("breakdown audio: %s" % str(e)[:100])
        return ""


def _ocr_breakdown_frames(frames, tesseract_cmd=None, rapid_engine=None,
                          pytesseract_module=None, image_module=None):
    import shutil

    valid_frames = []
    for frame in frames or []:
        path = frame.get("path") if isinstance(frame, dict) else ""
        if path and os.path.isfile(path):
            valid_frames.append(frame)
    if not valid_frames:
        return {"status": "empty", "engine": "none", "text": "", "errors": [],
                "fallbackErrors": [], "message": "未识别到字幕文本。"}

    lang = os.getenv("VIDEO_OCR_LANG", "chi_sim+eng").strip() or "chi_sim+eng"
    config = os.getenv("VIDEO_OCR_CONFIG", "--oem 3 --psm 11").strip() or "--oem 3 --psm 11"
    if tesseract_cmd is None:
        tesseract_cmd = (os.getenv("TESSERACT_CMD") or shutil.which("tesseract") or "").strip()
    engine_name = ""
    if tesseract_cmd:
        try:
            if pytesseract_module is None:
                import pytesseract as pytesseract_module
            if image_module is None:
                from PIL import Image as image_module
            pytesseract_module.pytesseract.tesseract_cmd = tesseract_cmd
            engine_name = "tesseract"
        except Exception as exc:
            json_log(_CLIENT_JSON_LOGGER, "video_ocr_engine_failed", exc=exc,
                     code="ocr_tesseract_unavailable", engine="tesseract")
            tesseract_cmd = ""

    def load_rapid_engine():
        nonlocal rapid_engine
        if rapid_engine is False:
            return None, None
        if rapid_engine is not None:
            return rapid_engine, None
        try:
            from rapidocr_onnxruntime import RapidOCR
            rapid_engine = RapidOCR()
            return rapid_engine, None
        except Exception as exc:
            raw = json_log(_CLIENT_JSON_LOGGER, "video_ocr_engine_failed", exc=exc,
                           code="ocr_engine_unavailable", engine="rapidocr")
            import json as _json
            return None, {
                "code": "ocr_engine_unavailable",
                "engine": "rapidocr",
                "errorId": (_json.loads(raw) or {}).get("errorId"),
            }

    if not engine_name:
        if rapid_engine is False:
            return {"status": "unavailable", "engine": "none", "text": "",
                    "errors": [{"code": "ocr_engine_unavailable"}],
                    "fallbackErrors": [],
                    "message": "OCR 不可用：未找到 Tesseract 或 RapidOCR。"}
        rapid_engine, rapid_error = load_rapid_engine()
        if rapid_engine is None:
            return {"status": "unavailable", "engine": "none", "text": "",
                    "errors": [rapid_error or {"code": "ocr_engine_unavailable"}],
                    "fallbackErrors": [],
                    "message": "OCR 不可用：未找到 Tesseract 或 RapidOCR。"}
        engine_name = "rapidocr"

    def run_frames(selected_engine):
        lines = []
        errors = []
        for frame in valid_frames:
            path = frame.get("path") or ""
            sec = float(frame.get("time") or 0)
            try:
                if selected_engine == "tesseract":
                    txt = pytesseract_module.image_to_string(
                        image_module.open(path), lang=lang, config=config
                    ).strip()
                else:
                    result, _elapsed = rapid_engine(path)
                    txt = " ".join(
                        str(row[1]).strip() for row in (result or [])
                        if isinstance(row, (list, tuple)) and len(row) > 1 and str(row[1]).strip()
                    ).strip()
                if txt:
                    lines.append("[%.2fs] %s" % (sec, txt.replace("\n", " ")))
            except Exception as exc:
                raw = json_log(_CLIENT_JSON_LOGGER, "video_ocr_frame_failed", exc=exc,
                               code="ocr_frame_failed", engine=selected_engine,
                               frame_time=sec, frame_path=path)
                import json as _json
                error_id = (_json.loads(raw) or {}).get("errorId")
                errors.append({"code": "ocr_frame_failed", "engine": selected_engine,
                               "time": sec, "errorId": error_id})
        return lines, errors

    lines, errors = run_frames(engine_name)
    fallback_errors = []
    if (engine_name == "tesseract" and not lines
            and len(errors) == len(valid_frames) and rapid_engine is not False):
        fallback_errors = list(errors)
        rapid_engine, rapid_error = load_rapid_engine()
        if rapid_engine is not None:
            engine_name = "rapidocr"
            lines, errors = run_frames(engine_name)
        elif rapid_error:
            errors = [rapid_error]

    if lines and errors:
        status = "partial"
        message = "OCR 部分完成：%d 帧失败。" % len(errors)
    elif lines:
        status = "ok"
        message = "OCR 完成"
    elif errors:
        status = "failed"
        message = "OCR 失败：所有有效帧均未完成识别。"
    else:
        status = "empty"
        message = "未识别到字幕文本。"
    return {"status": status, "engine": engine_name, "text": "\n".join(lines),
            "errors": errors, "fallbackErrors": fallback_errors, "message": message}


def _transcribe_breakdown_audio(video_path, out_dir=None, only_ranges=None, progress=None):
    if not (video_path and os.path.isfile(video_path)):
        return {"status": "failed", "code": "media_missing_file", "text": "",
                "segments": [], "failedRanges": [], "errors": [],
                "message": "音频转写失败：视频文件不存在。"}
    out_dir = out_dir or os.path.join(data_dir(), "video_breakdowns", "audio-" + uuid.uuid4().hex)
    chunk_sec = max(1, int(os.getenv("VIDEO_TRANSCRIBE_CHUNK_SEC", "60") or 60))
    max_sec = max(chunk_sec, int(os.getenv("VIDEO_TRANSCRIBE_MAX_SEC", "600") or 600))
    timeout = max(10, int(os.getenv("VIDEO_TRANSCRIBE_TIMEOUT_SEC", "180") or 180))
    retries = max(0, int(os.getenv("VIDEO_TRANSCRIBE_RETRIES", "2") or 2))
    model = (os.getenv("VIDEO_TRANSCRIBE_MODEL") or "gemini-3.1-pro-preview").strip()
    exported = export_audio_chunks(
        video_path,
        out_dir,
        chunk_sec=chunk_sec,
        max_sec=max_sec,
        ffmpeg_exe=_ffmpeg_exe(),
        only_ranges=only_ranges,
        logger=_CLIENT_JSON_LOGGER,
    )
    export_failures = list(exported.get("failedRanges") or [])
    export_errors = list(exported.get("errors") or export_failures)
    if exported.get("status") == "no_audio":
        return {"status": "no_audio", "code": "media_missing_audio_stream", "text": "",
                "segments": [], "failedRanges": export_failures, "errors": export_errors,
                "duration": exported.get("duration"), "truncated": exported.get("truncated", False),
                "message": "视频没有可转写的音轨。"}
    if not exported.get("chunks"):
        return {"status": "failed", "code": exported.get("code") or "audio_export_failed", "text": "",
                "segments": [], "chunks": [], "failedRanges": export_failures, "errors": export_errors,
                "duration": exported.get("duration"), "truncated": exported.get("truncated", False),
                "message": "音频导出失败，已继续使用画面与 OCR 分析。"}
    cfg = lk888_config()
    base = (cfg.get("base_url") or "").rstrip("/")
    key = cfg.get("api_key") or ""
    if not base or not key:
        return {"status": "failed", "code": "lk888_not_configured", "text": "",
                "segments": [], "chunks": [], "failedRanges": export_failures,
                "errors": export_errors,
                "duration": exported.get("duration"), "truncated": exported.get("truncated", False),
                "message": "远程转写未配置，已继续使用画面与 OCR 分析。"}
    result = transcribe_audio_chunks(
        chunks=exported.get("chunks") or [],
        base_url=base,
        api_key=key,
        model=model,
        timeout=timeout,
        retries=retries,
        proxies=_lk_proxies(cfg),
        only_ranges=only_ranges,
        progress=progress,
        logger=_CLIENT_JSON_LOGGER,
    )
    remote_failures = list(result.get("failedRanges") or [])
    remote_errors = list(result.get("errors") or remote_failures)
    failed_ranges = export_failures + remote_failures
    errors = export_errors + remote_errors
    has_success = bool(result.get("chunks") or result.get("segments") or result.get("text"))
    if export_failures and has_success:
        status = "partial"
    elif export_failures:
        status = "failed"
    else:
        status = result.get("status") or "failed"
    if status == "ok":
        message = "音频转写完成。"
    elif status == "partial":
        message = "音频转写部分完成，可重试失败时间段。"
    else:
        message = "音频转写失败，已继续使用画面与 OCR 分析。"
    result.update({
        "code": "ok" if status == "ok" else ("transcription_partial" if status == "partial" else "transcription_failed"),
        "status": status,
        "failedRanges": failed_ranges,
        "errors": errors,
        "duration": exported.get("duration"),
        "truncated": bool(exported.get("truncated")),
        "retryCount": 0,
        "message": message,
    })
    return result


def _image_data_url(path):
    if not (path and os.path.isfile(path)):
        return ""
    try:
        import base64
        with open(path, "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return ""


_MIX_SIZES = {"竖屏 9:16": (720, 1280), "横屏 16:9": (1280, 720), "方形 1:1": (720, 720)}


def mix_clips(paths, out_path, size_label="竖屏 9:16", per_image=3, bgm="", progress=None,
              preserve_source_audio=False):
    """把若干图片/视频统一规整后顺序拼接成一条 mp4;可选保留视频音轨或用 BGM 覆盖。
    需要本机 ffmpeg(随 imageio-ffmpeg 附带)。progress(done, total) 回调。"""
    import subprocess
    import tempfile
    import shutil
    W, H = _MIX_SIZES.get(size_label, (720, 1280))
    ff = _ffmpeg_exe()
    tmpdir = tempfile.mkdtemp(prefix="mshipmix_")
    vf = ("scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black,"
          "setsar=1,fps=30" % (W, H, W, H))
    anull = "anullsrc=channel_layout=stereo:sample_rate=48000"
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows GUI 下不弹黑色控制台窗口
    segs = []
    try:
        for i, p in enumerate(paths):
            if not (p and os.path.isfile(p)):
                continue
            seg = os.path.join(tmpdir, "seg_%03d.mp4" % i)
            is_img = os.path.splitext(p)[1].lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp")
            if is_img:
                cmd = [ff, "-y", "-loop", "1", "-t", str(per_image), "-i", p,
                       "-f", "lavfi", "-t", str(per_image), "-i", anull,
                       "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                       "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", seg]
            else:
                has_audio = bool(preserve_source_audio and validate_video_file(p).get("hasAudio"))
                if has_audio:
                    cmd = [ff, "-y", "-i", p,
                           "-map", "0:v:0", "-map", "0:a:0", "-vf", vf,
                           "-af", "aresample=48000,loudnorm=I=-16:TP=-1:LRA=11",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                           "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", seg]
                else:
                    cmd = [ff, "-y", "-i", p, "-f", "lavfi", "-i", anull,
                           "-map", "0:v:0", "-map", "1:a:0", "-vf", vf,
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                           "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", seg]
            try:
                subprocess.run(cmd, capture_output=True, timeout=240, creationflags=cflags)
            except subprocess.TimeoutExpired:
                if progress:
                    progress(i + 1, len(paths))
                continue  # 单个片段超时就跳过它,继续拼其余的,不整体失败
            if os.path.isfile(seg) and os.path.getsize(seg) > 1000:
                segs.append(seg)
            if progress:
                progress(i + 1, len(paths))
        if not segs:
            raise RuntimeError("没有可用片段(检查文件是否存在/ffmpeg 是否可用)")
        listf = os.path.join(tmpdir, "list.txt")
        with open(listf, "w", encoding="utf-8") as f:
            for s in segs:
                # concat demuxer 单引号语法:路径内的 ' 需转义成 '\'' 否则含单引号的路径(用户名带 ')会解析断裂
                sp = s.replace("\\", "/").replace("'", "'\\''")
                f.write("file '%s'\n" % sp)
        concat = os.path.join(tmpdir, "concat.mp4")
        subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", listf, "-c", "copy", concat],
                       capture_output=True, timeout=240, creationflags=cflags)
        if not (os.path.isfile(concat) and os.path.getsize(concat) > 1000):
            raise RuntimeError("拼接失败")
        if bgm and os.path.isfile(bgm):
            # -stream_loop -1 让 BGM 循环铺满;-shortest 以视频时长收尾 → BGM 短则循环、长则截断,画面始终完整
            subprocess.run([ff, "-y", "-i", concat, "-stream_loop", "-1", "-i", bgm,
                            "-map", "0:v:0", "-map", "1:a:0", "-shortest", "-c:v", "copy", "-c:a", "aac",
                            "-ar", "48000", "-ac", "2", out_path],
                           capture_output=True, timeout=240, creationflags=cflags)
            if not (os.path.isfile(out_path) and os.path.getsize(out_path) > 1000):
                shutil.copyfile(concat, out_path)
        else:
            shutil.copyfile(concat, out_path)
        return out_path
    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


# ---- 商品图/视频生成:精致对话式 UI 组件 ----
_PROD_PILL = ("QPushButton{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.10);"
              "border-radius:13px;padding:7px 15px;color:#c2cadb;font-size:12px;font-weight:600;}"
              "QPushButton:hover{border-color:#6b6ff5;background:rgba(99,102,241,0.13);color:#ffffff;}"
              "QPushButton:disabled{color:#586074;border-color:rgba(255,255,255,0.05);}")
_PROD_PILL_SEL = ("QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 rgba(99,102,241,0.34),"
                  "stop:1 rgba(139,92,246,0.34));border:1px solid rgba(139,92,246,0.70);border-radius:13px;"
                  "padding:7px 15px;color:#ffffff;font-size:12px;font-weight:700;}")
_PROD_ACT = ("QPushButton{background:transparent;border:1px solid rgba(255,255,255,0.10);border-radius:10px;"
             "padding:6px 13px;color:#98a2b6;font-size:12px;font-weight:600;}"
             "QPushButton:hover{color:#ffffff;border-color:#6b6ff5;background:rgba(99,102,241,0.10);}"
             "QPushButton:disabled{color:#4b5568;border-color:rgba(255,255,255,0.045);}")


def _grad_circle(size, c1, c2, glyph="", selected=False):
    """渐变圆(模型/风格头像)。selected 时加白色描边环。"""
    r = 2
    pm = QtGui.QPixmap(size * r, size * r)
    pm.setDevicePixelRatio(r)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    grad = QtGui.QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QtGui.QColor(c1))
    grad.setColorAt(1, QtGui.QColor(c2))
    m = 2.5
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(grad)
    p.drawEllipse(QtCore.QRectF(m, m, size - 2 * m, size - 2 * m))
    if glyph:
        p.setPen(QtGui.QColor("#ffffff"))
        f = QtGui.QFont("Microsoft YaHei", int(size * 0.30), QtGui.QFont.Bold)
        p.setFont(f)
        p.drawText(QtCore.QRectF(0, 0, size, size), QtCore.Qt.AlignCenter, glyph)
    if selected:
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2.0))
        p.drawEllipse(QtCore.QRectF(1.2, 1.2, size - 2.4, size - 2.4))
    p.end()
    return pm


def _rounded_pixmap(src, radius=12):
    """把图片裁成圆角(结果图/参考缩略)。"""
    if src is None or src.isNull():
        return src
    out = QtGui.QPixmap(src.size())
    out.setDevicePixelRatio(src.devicePixelRatio())
    out.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(out)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    path = QtGui.QPainterPath()
    path.addRoundedRect(QtCore.QRectF(0, 0, src.width(), src.height()), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, src)
    p.end()
    return out


def _play_badge(size=52):
    pm = _grad_circle(size, "#6366f1", "#8b5cf6")
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    ic = _draw_icon("play", int(size * 0.46), "#ffffff")
    p.drawPixmap(int(size * 0.29), int(size * 0.27), ic)
    p.end()
    return pm


def _thumb_pixmap(path, w, h, radius=10):
    """图片缩略图:填满裁切 + 圆角。"""
    pm = QtGui.QPixmap(path)
    if pm.isNull():
        return pm
    pm = pm.scaled(w, h, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
    x = max(0, (pm.width() - w) // 2)
    y = max(0, (pm.height() - h) // 2)
    pm = pm.copy(x, y, w, h)
    return _rounded_pixmap(pm, radius)


def _video_thumb(w, h, radius=10):
    """视频首帧不可用时的无图标备用海报。"""
    r = 2
    pm = QtGui.QPixmap(w * r, h * r)
    pm.setDevicePixelRatio(r)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    grad = QtGui.QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QtGui.QColor("#1a1f36"))
    grad.setColorAt(1, QtGui.QColor("#0d1020"))
    path = QtGui.QPainterPath()
    path.addRoundedRect(QtCore.QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    p.fillRect(QtCore.QRectF(0, 0, w, h), grad)
    p.end()
    return pm


def _video_thumb_pixmap(path, w, h, radius=10):
    """视频缩略图:优先抽取首帧,失败时回退到播放海报。"""
    if not (path and os.path.isfile(path)):
        return _video_thumb(w, h, radius)
    try:
        import hashlib
        d = os.path.join(data_dir(), "video_thumbs")
        os.makedirs(d, exist_ok=True)
        st = os.stat(path)
        key = hashlib.sha1(("%s:%s:%s:%s:%s" % (path, st.st_mtime_ns, st.st_size, w, h)).encode("utf-8")).hexdigest()
        jpg = os.path.join(d, key + ".jpg")
        if not os.path.isfile(jpg):
            cmd = [_ffmpeg_exe(), "-y", "-ss", "00:00:00.1", "-i", path, "-frames:v", "1",
                   "-vf", "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (w, h, w, h),
                   "-q:v", "3", jpg]
            subprocess.run(cmd, capture_output=True, timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        pm = _thumb_pixmap(jpg, w, h, radius) if os.path.isfile(jpg) else QtGui.QPixmap()
        if not pm.isNull():
            return pm
    except Exception as e:
        log("video thumb: %s" % str(e)[:80])
    return _video_thumb(w, h, radius)


def _chip_pill(icon_kind, text, accent="#96a0b5"):
    f = QtWidgets.QFrame()
    f.setObjectName("cchip")
    f.setStyleSheet("QFrame#cchip{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.09);"
                    "border-radius:11px;}")
    h = QtWidgets.QHBoxLayout(f)
    h.setContentsMargins(9, 3, 12, 3)
    h.setSpacing(6)
    ic = QtWidgets.QLabel()
    ic.setPixmap(_draw_icon(icon_kind, 13, accent))
    ic.setFixedSize(13, 13)
    ic.setScaledContents(True)
    ic.setStyleSheet("background:transparent;border:0;")
    t = QtWidgets.QLabel(text)
    t.setStyleSheet("color:#aeb6c6;font-size:11px;font-weight:600;background:transparent;border:0;")
    h.addWidget(ic)
    h.addWidget(t)
    return f


def _icon_text_btn(icon_kind, text, style, accent="#aab3c5", icon_px=15, cb=None, disabled=False):
    b = QtWidgets.QPushButton("  " + text)
    b._no_press_scale = True
    b.setIcon(QtGui.QIcon(_draw_icon(icon_kind, icon_px, accent)))
    b.setIconSize(QtCore.QSize(icon_px, icon_px))
    b.setStyleSheet(style)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.setEnabled(not disabled)
    if cb:
        b.clicked.connect(lambda _=False: cb())
    return b


def _round_icon_btn(icon_kind, size=38, accent="#8b93a3", cb=None, tip=""):
    b = QtWidgets.QPushButton()
    b.setFixedSize(size, size)
    b.setIcon(QtGui.QIcon(_draw_icon(icon_kind, int(size * 0.42), accent)))
    b.setIconSize(QtCore.QSize(int(size * 0.42), int(size * 0.42)))
    b.setCursor(QtCore.Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    b.setStyleSheet("QPushButton{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.10);"
                    "border-radius:%dpx;}QPushButton:hover{border-color:#6b6ff5;background:rgba(99,102,241,0.12);}"
                    % (size // 2))
    if cb:
        b.clicked.connect(lambda _=False: cb())
    return b


def _fmt_ratio(label):
    """'横版 16:9' → '横版 (16:9)'(对齐参考图胶囊文案)。"""
    parts = str(label or "").rsplit(" ", 1)
    if len(parts) == 2:
        return "%s (%s)" % (parts[0], parts[1])
    return str(label or "")


class GenCard(QtWidgets.QFrame):
    """一条生成记录卡(对话消息式):参考缩略+提示词 → 参数chips → 大图/视频海报 → 操作 + 时间。"""

    def __init__(self, entry, page):
        super().__init__()
        self.entry = entry
        self.page = page
        self.setObjectName("genCard")
        self.setStyleSheet("QFrame#genCard{background:%s;border:1px solid %s;border-radius:16px;}"
                           % (("#ffffff" if is_light() else "rgba(255,255,255,0.028)"),
                              (TK["cardBorder"] if is_light() else "rgba(255,255,255,0.07)")))
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(18, 15, 18, 14)
        self.lay.setSpacing(11)
        self.refresh()

    def _clear(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
            elif it.layout():
                self._clear(it.layout())

    def refresh(self):
        self._stop_typer()
        self._clear(self.lay)
        e = self.entry
        st = e.get("status")
        # ---- 顶部:参考缩略 + 提示词 ----
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(12)
        for i, ref in enumerate(_prodgen_entry_refs(e)):
            th = QtWidgets.QLabel()
            pm = QtGui.QPixmap(ref)
            if not pm.isNull():
                pm = pm.scaled(50, 50, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
                if pm.width() > 50 or pm.height() > 50:
                    pm = pm.copy(0, 0, 50, 50)
                th.setPixmap(_rounded_pixmap(pm, 11))
            th.setFixedSize(50, 50)
            th.setToolTip(("待修改图" if i == 0 else "参考图%d" % i) + ":" + os.path.basename(ref))
            th.setStyleSheet("background:transparent;border:0;")
            tw = QtWidgets.QWidget()
            tw.setStyleSheet("background:transparent;")
            twl = QtWidgets.QVBoxLayout(tw)
            twl.setContentsMargins(0, 1, 0, 0)
            twl.setSpacing(2)
            twl.addWidget(th)
            lab = QtWidgets.QLabel("待修改图" if i == 0 else "参考图%d" % i)
            lab.setAlignment(QtCore.Qt.AlignCenter)
            lab.setStyleSheet("color:#6b7488;font-size:9.5px;background:transparent;border:0;")
            twl.addWidget(lab)
            twl.addStretch()
            top.addWidget(tw, 0)
        prm = QtWidgets.QLabel((e.get("prompt") or "").strip() or "(无提示词)")
        prm.setWordWrap(True)
        prm.setStyleSheet("color:#dce1eb;font-size:13.5px;font-weight:600;background:transparent;border:0;")
        if e.get("expandedPrompt"):
            prm.setToolTip("已确认的中文提示词:\n\n" + str(e.get("expandedPrompt")))
        top.addWidget(prm, 1)
        self.lay.addLayout(top)
        # ---- chips ----
        chips = QtWidgets.QHBoxLayout()
        chips.setSpacing(7)
        if e.get("mode") == "video":
            chips.addWidget(_chip_pill("ratio", "视频比例: " + _fmt_ratio(e.get("aspectLabel"))))
            chips.addWidget(_chip_pill("video", "时长: %ds" % int(e.get("duration") or 5)))
        else:
            chips.addWidget(_chip_pill("ratio", "图片比例: " + _fmt_ratio(e.get("aspectLabel"))))
            chips.addWidget(_chip_pill("sparkle", "图片质量: 自适应"))
        model_text = str(e.get("modelLabel") or _lk888_model_label(e.get("model")) or "").strip()
        if model_text:
            chips.addWidget(_chip_pill("sparkle", "模型: " + model_text))
        chips.addWidget(_chip_pill("layers", "设置分组"))
        chips.addStretch()
        self.lay.addLayout(chips)
        # ---- 结果 ----
        if st == "生成中":
            self._build_gen_panel(e)
        elif st == "失败":
            self.lay.addWidget(self._note("生成失败:" + str(e.get("error") or ""), "#ef5555"))
        elif st == "已中断":
            self.lay.addWidget(self._note("已中断(客户端重启),点『再次生成』重跑。", "#8b93a3"))
        else:  # 完成
            files = [f for f in (e.get("files") or []) if os.path.isfile(f)]
            if not files:
                self.lay.addWidget(self._note("结果文件缺失,可再次生成。", "#8b93a3"))
            elif e.get("mode") == "video":
                self.lay.addWidget(self._video_poster(files[0]))
            else:
                imrow = QtWidgets.QHBoxLayout()
                imrow.setSpacing(12)
                for f in files[:2]:
                    lb = QtWidgets.QLabel()
                    pm = QtGui.QPixmap(f)
                    if not pm.isNull():
                        pm = pm.scaledToHeight(252, QtCore.Qt.SmoothTransformation)
                        lb.setPixmap(_rounded_pixmap(pm, 13))
                    lb.setStyleSheet("background:transparent;border:0;")
                    imrow.addWidget(lb)
                imrow.addStretch()
                holder = QtWidgets.QWidget()
                holder.setStyleSheet("background:transparent;")
                holder.setLayout(imrow)
                self.lay.addWidget(holder)
        # ---- 操作 + 时间 ----
        foot = QtWidgets.QHBoxLayout()
        foot.setSpacing(8)
        busy = st == "生成中"
        if e.get("mode") == "video" and st == "完成":
            foot.addWidget(_icon_text_btn("play", "播放", _PROD_ACT, "#98a2b6", 14, cb=self._play))
        foot.addWidget(_icon_text_btn("edit", "重新编辑", _PROD_ACT, "#98a2b6", 14,
                                      cb=lambda: self.page.reedit(self.entry), disabled=busy))
        foot.addWidget(_icon_text_btn("refresh", "再次生成", _PROD_ACT, "#98a2b6", 14,
                                      cb=lambda: self.page.regen(self.entry), disabled=busy))
        if st == "完成":
            if e.get("saved"):
                sb = _icon_text_btn("star", "已存资产库", _PROD_ACT, "#f5c451", 14)
                sb.setEnabled(False)
                foot.addWidget(sb)
            else:
                foot.addWidget(_icon_text_btn("star", "存资产库", _PROD_ACT, "#f5c451", 14,
                                              cb=lambda: self.page.save_to_assets(self.entry)))
        foot.addWidget(_icon_text_btn("trash", "删除", _PROD_ACT, "#98a2b6", 14,
                                      cb=lambda: self.page.remove(self.entry), disabled=busy))
        foot.addStretch()
        ts = QtWidgets.QLabel(e.get("ts") or "")
        ts.setStyleSheet("color:#5b6577;font-size:11px;background:transparent;border:0;")
        foot.addWidget(ts)
        self.lay.addLayout(foot)

    def _note(self, text, color):
        lb = QtWidgets.QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:%s;font-size:12.5px;font-weight:600;background:transparent;border:0;padding:6px 0;" % color)
        return lb

    def _build_gen_panel(self, e):
        """生成中:实时"思考过程"面板 —— gpt-5.4 提炼的提示词打字机式逐字浮现 + 当前阶段。"""
        box = QtWidgets.QFrame()
        box.setObjectName("thinkBox")
        box.setStyleSheet("QFrame#thinkBox{background:rgba(99,102,241,0.06);"
                          "border:1px solid rgba(139,92,246,0.30);border-radius:12px;}")
        bl = QtWidgets.QVBoxLayout(box)
        bl.setContentsMargins(14, 11, 14, 12)
        bl.setSpacing(8)
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(8)
        ic = QtWidgets.QLabel()
        ic.setPixmap(_draw_icon("sparkle", 15, "#a78bfa"))
        ic.setFixedSize(16, 16)
        ic.setScaledContents(True)
        ic.setStyleSheet("background:transparent;border:0;")
        self._gen_head = QtWidgets.QLabel("gpt-5.4 正在思考…")
        self._gen_head.setStyleSheet("color:#c9a8ff;font-size:12.5px;font-weight:700;background:transparent;border:0;")
        head.addWidget(ic)
        head.addWidget(self._gen_head)
        head.addStretch()
        bl.addLayout(head)
        self._think_body = QtWidgets.QLabel("")
        self._think_body.setWordWrap(True)
        self._think_body.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._think_body.setStyleSheet("color:#8fd3ff;font-size:12px;background:transparent;border:0;"
                                       "font-family:'Consolas','Cascadia Mono','Courier New',monospace;")
        self._think_body.setMinimumHeight(18)
        bl.addWidget(self._think_body)
        self.lay.addWidget(box)
        if e.get("expandedPrompt"):  # 重绘时已有(如切页回来)直接铺满,不再打字
            try:
                self._think_body.setText(str(e.get("expandedPrompt")))
            except Exception:
                pass

    def set_phase(self, text):
        try:
            if getattr(self, "_gen_head", None) is not None:
                self._gen_head.setText(text)
        except RuntimeError:
            pass

    def type_thinking(self, text):
        if getattr(self, "_think_body", None) is None:
            return
        self._type_full = text or ""
        self._type_i = 0
        self._stop_typer()
        self._type_timer = QtCore.QTimer(self)
        self._type_timer.timeout.connect(self._type_step)
        self._type_timer.start(14)  # 打字机:每 14ms 冒 3 个字

    def _type_step(self):
        try:
            self._type_i += 3
            self._think_body.setText(self._type_full[:self._type_i])
            if self._type_i >= len(self._type_full):
                self._stop_typer()
        except RuntimeError:  # 卡片已被 refresh 重建,标签失效
            self._stop_typer()

    def _stop_typer(self):
        t = getattr(self, "_type_timer", None)
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass
            self._type_timer = None

    def _video_poster(self, path):
        box = QtWidgets.QFrame()
        box.setObjectName("vpost")
        box.setFixedSize(320, 182)
        box.setStyleSheet("QFrame#vpost{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #1a1f36,stop:1 #0d1020);"
                          "border:1px solid #2b3350;border-radius:14px;}")
        bl = QtWidgets.QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        pc = QtWidgets.QLabel()
        pc.setFixedSize(320, 182)
        pc.setAlignment(QtCore.Qt.AlignCenter)
        pc.setPixmap(_video_thumb_pixmap(path, 320, 182, 14))
        pc.setStyleSheet("background:transparent;border:0;")
        bl.addWidget(pc)
        return box

    def _play(self):
        files = [f for f in (self.entry.get("files") or []) if os.path.isfile(f)]
        if files:
            _open_path(files[0])

    def _download(self):
        files = [f for f in (self.entry.get("files") or []) if os.path.isfile(f)]
        if not files:
            return
        import shutil
        src = files[0]
        dst, _ = QtWidgets.QFileDialog.getSaveFileName(self, "保存到", os.path.basename(src), "所有文件 (*.*)")
        if dst:
            try:
                shutil.copyfile(src, dst)
            except Exception as ex:
                log("prodgen download: %s" % ex)


class StyleDot(QtWidgets.QLabel):
    """风格/模型头像圆(仿参考图):纯彩色渐变圆、无文字,悬停显名,选中加白环。"""

    def __init__(self, idx, name, colors, page):
        super().__init__()
        self.idx = idx
        self.name = name
        self.colors = colors
        self.page = page
        self.selected = (idx == 0)
        self.setFixedSize(40, 40)
        self.setToolTip(name)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setStyleSheet("background:transparent;border:0;")
        self._render()

    def _render(self):
        self.setPixmap(_grad_circle(40, self.colors[0], self.colors[1], "", self.selected))

    def set_selected(self, on):
        self.selected = on
        self._render()

    def mousePressEvent(self, e):
        self.page._select_style(self.idx)


class PromptConfirmDialog(QtWidgets.QDialog):
    """提示词优化确认窗口：用户可编辑中文提示词后再生成。"""

    def __init__(self, prompt, parent=None):
        super().__init__(parent)
        self.setWindowTitle("确认优化提示词")
        self.setMinimumSize(680, 420)
        self.setStyleSheet(
            "QDialog{background:#0f1320;color:#edf2ff;}"
            "QTextEdit{background:#0b0e17;color:#edf2ff;border:1px solid #283149;"
            "border-radius:12px;padding:11px;font-size:13.5px;line-height:1.6;"
            "selection-background-color:#6366f1;}"
            "QPushButton{border-radius:10px;padding:9px 16px;font-weight:750;}"
        )
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)
        title = QtWidgets.QLabel("已优化为中文提示词，可修改后确认生成")
        title.setStyleSheet("color:#f7f8ff;font-size:15px;font-weight:850;background:transparent;border:0;")
        v.addWidget(title)
        tip = QtWidgets.QLabel("确认后，生成记录和生成过程会显示这段中文提示词。")
        tip.setStyleSheet("color:#8b93a3;font-size:12px;background:transparent;border:0;")
        v.addWidget(tip)
        self.editor = QtWidgets.QTextEdit()
        self.editor.setPlainText(str(prompt or "").strip())
        self.editor.setAcceptRichText(False)
        v.addWidget(self.editor, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch()
        cancel = QtWidgets.QPushButton("取消")
        cancel.setStyleSheet("QPushButton{background:rgba(255,255,255,0.05);"
                             "border:1px solid rgba(255,255,255,0.12);color:#aeb6c6;}"
                             "QPushButton:hover{border-color:#6366f1;color:#ffffff;}")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        confirm = QtWidgets.QPushButton("确认生成")
        confirm.setStyleSheet("QPushButton{background:#6366f1;border:1px solid rgba(255,255,255,0.18);"
                              "color:#ffffff;}QPushButton:hover{background:#7c3aed;}")
        confirm.clicked.connect(self._accept_if_valid)
        row.addWidget(confirm)
        v.addLayout(row)

    def value(self):
        return self.editor.toPlainText().strip()

    def _accept_if_valid(self):
        if not self.value():
            QtWidgets.QMessageBox.warning(self, "提示词优化", "提示词不能为空。")
            return
        self.accept()


class ProductGenPage(BasePage):
    """Agent.模式:对话式生成流。上方一条条生成卡(提示词+参数+结果+操作),
    下方输入区(参考图 / 图像·视频模式 / 比例 / 数量 / 发送)。真实调用 LK888 模型目录。"""

    MAX_REFS = 4
    ASPECTS = [("横版 16:9", "1536x1024", "16:9"), ("方形 1:1", "1024x1024", "1:1"),
               ("竖版 9:16", "1024x1536", "9:16")]
    STYLES = [
        ("综合最优", "", ("#6d5efc", "#c04bf6")),
        ("超写实", "hyper-realistic, ultra detailed, photographic, sharp", ("#f0517a", "#f0a05a")),
        ("影棚白底", "clean white seamless studio background, softbox lighting", ("#28c76f", "#0f9b6c")),
        ("场景氛围", "lifestyle scene, warm ambient environment with props", ("#f6a723", "#f0662a")),
        ("手持展示", "product held in hand, natural daylight, close-up", ("#22b8cf", "#1573d4")),
        ("质感特写", "extreme macro close-up, rich texture, dramatic rim light", ("#ec5aa8", "#a02ce0")),
        ("3D 渲染", "3D product render, C4D octane, glossy high-gloss studio", ("#8a5cf6", "#5b6ef5")),
        ("国潮插画", "chinese-style illustration, festive, vibrant flat art", ("#f24b5b", "#f0a24b")),
    ]

    def __init__(self):
        super().__init__()
        self._mode = "image"
        self._ref = ""
        self._refs = []
        self.ref_buttons = []
        self._cards = {}
        self._style = 0
        self._dots = []
        self.aspect_i = 1
        self.count_i = 0
        self.duration_i = 0
        self._image_model = _LK888_IMAGE_DEFAULT
        self._video_model = _LK888_VIDEO_DEFAULT
        self._image_models = []
        self._video_models = []
        self._models_loaded = False
        self._models_loading = False
        self._prompt_optimizing = False
        self._prompt_opt_req = ""
        self.nav_aliases = ("🛍️ 商品图和视频生成", "🛍️ Agent.模式")
        self.v.addWidget(make_header("Agent.模式",
                                     "对话式生成:描述需求 + 多张图片，可按 LK888 分类模型生成图片或视频"))
        # 生成流(滚动)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;}")
        host = QtWidgets.QWidget()
        host.setStyleSheet("background:transparent;")
        self.msgs = QtWidgets.QVBoxLayout(host)
        self.msgs.setContentsMargins(2, 2, 12, 2)
        self.msgs.setSpacing(12)
        self.msgs.addStretch()
        self.scroll.setWidget(host)
        self.v.addWidget(self.scroll, 1)
        # ---- 输入区(精致 composer) ----
        comp = QtWidgets.QFrame()
        comp.setObjectName("prodComposer")
        comp.setStyleSheet("QFrame#prodComposer{background:%s;border:1px solid %s;border-radius:18px;}"
                           % (("#ffffff" if is_light() else "#0b0e17"),
                              (TK["cardBorder"] if is_light() else "#222b3e")))
        cv = QtWidgets.QVBoxLayout(comp)
        cv.setContentsMargins(16, 13, 16, 14)
        cv.setSpacing(12)
        # (已按用户要求删掉模型/风格头像圆一行)
        # 行1:提示语
        self.hint = QtWidgets.QLabel("描述画面中的物体、风格及文字排版,注重指令精准与细节还原。"
                                     "第1张为待修改图,后续图片可参考风格、人物、场景或材质。")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#6b7488;font-size:11.5px;background:transparent;border:0;")
        cv.addWidget(self.hint)
        # 行3:参考图槽独立成行，避免挤压多行提示词输入区。
        ref_strip = QtWidgets.QHBoxLayout()
        ref_strip.setSpacing(9)
        self.ref_strip = ref_strip
        self._rebuild_ref_slots()
        cv.addLayout(ref_strip)
        self.inp = QtWidgets.QPlainTextEdit()
        self.inp.setPlaceholderText("给我描述你想要的素材…")
        self.inp.setMinimumHeight(78)
        self.inp.setMaximumHeight(138)
        self.inp.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.inp.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.inp.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.inp.setStyleSheet("QPlainTextEdit{background:transparent;border:0;color:%s;font-size:14.5px;"
                               "selection-background-color:#6366f1;padding:0;}" % TK["text"])
        cv.addWidget(self.inp)
        divl = QtWidgets.QFrame()
        divl.setFixedHeight(1)
        divl.setStyleSheet("background:rgba(255,255,255,0.06);border:0;")
        cv.addWidget(divl)
        # 行4:综合最优 / 1条 / 比例 胶囊 + 右侧圆形图标 + 圆形发送
        ctl = QtWidgets.QHBoxLayout()
        ctl.setSpacing(8)
        self.b_img = _icon_text_btn("image", "图片模式", _PROD_PILL_SEL, "#ffffff", 15, cb=lambda: self._mode_set("image"))
        self.b_vid = _icon_text_btn("video", "视频模式", _PROD_PILL, "#aab3c5", 15, cb=lambda: self._mode_set("video"))
        ctl.addWidget(self.b_img)
        ctl.addWidget(self.b_vid)
        self.b_style = _icon_text_btn("sparkle", self.STYLES[0][0], _PROD_PILL, "#c9a8ff", 15, cb=self._cycle_style)
        ctl.addWidget(self.b_style)
        self.b_count = _icon_text_btn("layers", "1 条", _PROD_PILL, "#aab3c5", 15, cb=self._cycle_count)
        ctl.addWidget(self.b_count)
        self.b_aspect = _icon_text_btn("ratio", self.ASPECTS[0][0], _PROD_PILL, "#aab3c5", 15, cb=self._cycle_aspect)
        ctl.addWidget(self.b_aspect)
        self.b_duration = _icon_text_btn("video", "5 秒", _PROD_PILL, "#aab3c5", 15, cb=self._cycle_video_duration)
        self.b_duration.setEnabled(False)
        ctl.addWidget(self.b_duration)
        self.b_model = _icon_text_btn("sparkle", "LK888 模型", _PROD_PILL, "#9bd4ff", 15, cb=self._pick_model)
        ctl.addWidget(self.b_model)
        ctl.addStretch()
        self.optimize_btn = _icon_text_btn("sparkle", "提示词优化", _PROD_PILL, "#c9a8ff", 15, cb=self.optimize_prompt)
        self.optimize_btn.setToolTip("先把当前需求优化为中文提示词，确认后再生成")
        ctl.addWidget(self.optimize_btn)
        ctl.addWidget(_round_icon_btn("grid", 40, "#8b93a3", cb=self.pick_from_assets, tip="从资产库选参考图"))
        ctl.addWidget(_round_icon_btn("trash", 40, "#8b93a3", cb=lambda: self.inp.clear(), tip="清空输入"))
        ctl.addWidget(_round_icon_btn("plus", 40, "#8b93a3", cb=self.pick_ref, tip="上传图片"))
        self.send_btn = QtWidgets.QPushButton()
        self.send_btn.setFixedSize(46, 46)
        self.send_btn.setIcon(QtGui.QIcon(_draw_icon("arrowup", 22, "#ffffff")))
        self.send_btn.setIconSize(QtCore.QSize(22, 22))
        self.send_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self.send)
        self.send_btn.setStyleSheet(
            "QPushButton{background:%s;border:0;border-radius:23px;}"
            "QPushButton:hover{background:%s;}" % (TK["accent"], TK["accent2"]))
        ctl.addWidget(self.send_btn)
        cv.addLayout(ctl)
        self.model_meta = QtWidgets.QLabel("LK888 模型目录待同步")
        self.model_meta.setStyleSheet("color:#6b7488;font-size:11.5px;background:transparent;border:0;")
        cv.addWidget(self.model_meta)
        self.v.addWidget(comp)
        BRIDGE.payload.connect(self._on)

    def on_show(self):
        load_prodgen()
        self._ensure_model_catalog()
        # 清空并重建生成流
        while self.msgs.count() > 1:
            it = self.msgs.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
        self._cards = {}
        if not PRODGEN:
            hint = QtWidgets.QLabel("还没有生成记录。选择『商品图/视频』,可上传参考图,输入描述后点发送即可开始。")
            hint.setStyleSheet("color:#6b7488;font-size:13px;background:transparent;")
            hint.setWordWrap(True)
            self.msgs.insertWidget(0, hint)
        for e in PRODGEN:
            self._add_card(e)
        self._scroll_bottom()
        self._sync_model_ui()

    def _ensure_model_catalog(self, force=False):
        if self._models_loading and not force:
            return
        if self._models_loaded and not force:
            self._sync_model_ui()
            return
        self._models_loading = True
        if getattr(self, "model_meta", None) is not None:
            self.model_meta.setText("同步 LK888 模型目录中…")

        def work():
            imgs = _lk888_models_by_type("image")
            vids = _lk888_models_by_type("video")
            BRIDGE.payload.emit("prodgen_models", {"image": imgs, "video": vids})
        run_bg(work)

    def _current_model(self, mode=None):
        return self._video_model if (mode or self._mode) == "video" else self._image_model

    def _model_rows(self, mode=None):
        if (mode or self._mode) == "video":
            return self._video_models or [x for x in _LK888_FALLBACK_MODELS if x.get("type") == "video"]
        return self._image_models or [x for x in _LK888_FALLBACK_MODELS if x.get("type") == "image"]

    def _set_current_model(self, name, mode=None):
        mode = mode or self._mode
        name = str(name or "").strip()
        if not name:
            return
        if mode == "video":
            self._video_model = name
        else:
            self._image_model = name
        self._sync_model_ui()

    def _sync_model_ui(self):
        rows = self._model_rows()
        cur = self._current_model()
        if rows and cur not in [str(x.get("name") or "") for x in rows]:
            cur = str((rows[0] or {}).get("name") or cur)
            self._set_current_model(cur, self._mode)
            return
        label = _lk888_model_label(cur, rows) or "LK888 模型"
        if getattr(self, "b_model", None) is not None:
            prefix = "视频模型" if self._mode == "video" else "图像模型"
            self.b_model.setText("  %s · %s" % (prefix, label[:20]))
            self.b_model.setToolTip("%s\n%s" % (label, cur))
        if getattr(self, "model_meta", None) is not None:
            ic = len(self._image_models or [])
            vc = len(self._video_models or [])
            base = "LK888 图像模型 %d 个 · 视频模型 %d 个" % (ic, vc)
            if not self._models_loaded:
                base = "LK888 模型目录待同步"
            self.model_meta.setText(base + " · 当前使用 " + label)

    def _pick_model(self):
        rows = self._model_rows()
        if not rows:
            self._ensure_model_catalog(force=True)
            return
        mode = self._mode
        cur = self._current_model(mode)
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#101522;color:#edf2ff;border:1px solid #283149;padding:6px;}"
            "QMenu::item{padding:7px 18px 7px 12px;border-radius:8px;}"
            "QMenu::item:selected{background:rgba(99,102,241,0.18);}"
        )
        title = menu.addAction("选择%s模型" % ("视频" if mode == "video" else "图像"))
        title.setEnabled(False)
        menu.addSeparator()
        for family, items in _lk888_grouped_models(mode):
            sub = menu.addMenu(family)
            for row in items:
                name = str(row.get("name") or "")
                disp = str(row.get("display_name") or name)
                act = sub.addAction(disp)
                act.setCheckable(True)
                act.setChecked(name == cur)
                act.setToolTip(name)
                act.triggered.connect(lambda _=False, nm=name, md=mode: self._set_current_model(nm, md))
        menu.exec(QtGui.QCursor.pos())

    def _add_card(self, entry):
        card = GenCard(entry, self)
        self._cards[entry.get("id")] = card
        self.msgs.insertWidget(self.msgs.count() - 1, card)
        return card

    def _scroll_bottom(self):
        QtCore.QTimer.singleShot(60, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def _mode_set(self, m):
        self._mode = m
        self.b_img.setStyleSheet(_PROD_PILL_SEL if m == "image" else _PROD_PILL)
        self.b_img.setIcon(QtGui.QIcon(_draw_icon("image", 15, "#ffffff" if m == "image" else "#aab3c5")))
        self.b_vid.setStyleSheet(_PROD_PILL_SEL if m == "video" else _PROD_PILL)
        self.b_vid.setIcon(QtGui.QIcon(_draw_icon("video", 15, "#ffffff" if m == "video" else "#aab3c5")))
        self.b_count.setEnabled(m == "image")
        self.b_duration.setEnabled(m == "video")
        self.inp.setPlaceholderText("描述你想要的图片素材…(可先上传参考图)" if m == "image"
                                    else "描述你想要的视频素材…(按所选 LK888 视频模型出片)")
        self._sync_model_ui()

    def _cycle_aspect(self):
        self.aspect_i = (self.aspect_i + 1) % len(self.ASPECTS)
        self.b_aspect.setText("  " + self.ASPECTS[self.aspect_i][0])

    def _cycle_count(self):
        self.count_i = (self.count_i + 1) % 2
        self.b_count.setText("  %d 条" % (self.count_i + 1))

    def _current_video_duration(self):
        try:
            return int(AGENT_VIDEO_DURATIONS[self.duration_i])
        except (IndexError, TypeError):
            return AGENT_VIDEO_DURATIONS[0]

    def _cycle_video_duration(self):
        self.duration_i = (self.duration_i + 1) % len(AGENT_VIDEO_DURATIONS)
        self.b_duration.setText("  %d 秒" % self._current_video_duration())

    def _cycle_style(self):
        self._select_style((self._style + 1) % len(self.STYLES))

    def _select_style(self, i):
        self._style = i
        for d in self._dots:
            d.set_selected(d.idx == i)
        if getattr(self, "b_style", None) is not None:
            self.b_style.setText("  " + self.STYLES[i][0])

    def _set_refs(self, refs):
        cleaned = []
        for p in refs or []:
            p = str(p or "").strip()
            if p and p not in cleaned and os.path.isfile(p):
                cleaned.append(p)
            if len(cleaned) >= self.MAX_REFS:
                break
        self._refs = cleaned
        self._ref = self._refs[0] if self._refs else ""
        self._style_ref_slot()

    def _append_refs(self, refs):
        self._set_refs(list(self._refs) + list(refs or []))

    def _replace_ref_at(self, idx):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "替换图片", "",
                                                          "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not paths:
            return
        refs = list(self._refs)
        if 0 <= idx < len(refs):
            refs[idx] = paths[0]
            refs.extend(paths[1:])
        else:
            refs.extend(paths)
        self._set_refs(refs)

    def _remove_ref_at(self, idx):
        refs = list(self._refs)
        if 0 <= idx < len(refs):
            refs.pop(idx)
            self._set_refs(refs)

    def _ref_label(self, i):
        return "待修改图" if i == 0 else "参考图%d" % i

    def _make_ref_cell(self, path, i):
        cell = QtWidgets.QWidget()
        cell.setStyleSheet("background:transparent;")
        v = QtWidgets.QVBoxLayout(cell)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        btn = QtWidgets.QPushButton()
        btn.setFixedSize(56, 56)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.clicked.connect(lambda _=False, idx=i: self._replace_ref_at(idx))
        btn.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        btn.customContextMenuRequested.connect(lambda _p, idx=i: self._remove_ref_at(idx))
        pm = QtGui.QPixmap(path)
        if not pm.isNull():
            pm = pm.scaled(52, 52, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
            if pm.width() > 52 or pm.height() > 52:
                pm = pm.copy(0, 0, 52, 52)
            btn.setIcon(QtGui.QIcon(_rounded_pixmap(pm, 11)))
            btn.setIconSize(QtCore.QSize(52, 52))
        btn.setToolTip("%s:%s(点击替换 · 右键删除)" % (self._ref_label(i), os.path.basename(path)))
        btn.setStyleSheet("QPushButton{border:1px solid #34405a;border-radius:13px;background:#0c0f17;}"
                          "QPushButton:hover{border-color:#6b6ff5;}")
        lab = QtWidgets.QLabel(self._ref_label(i))
        lab.setAlignment(QtCore.Qt.AlignCenter)
        lab.setStyleSheet("color:#8b93a3;font-size:10px;background:transparent;border:0;")
        v.addWidget(btn, 0, QtCore.Qt.AlignHCenter)
        v.addWidget(lab)
        self.ref_buttons.append(btn)
        return cell

    def _make_ref_add_cell(self):
        cell = QtWidgets.QWidget()
        cell.setStyleSheet("background:transparent;")
        v = QtWidgets.QVBoxLayout(cell)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        btn = QtWidgets.QPushButton()
        btn.setFixedSize(56, 56)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.clicked.connect(self.pick_ref)
        btn.setIcon(QtGui.QIcon(_draw_icon("plus", 20, "#7b86a0")))
        btn.setIconSize(QtCore.QSize(20, 20))
        btn.setToolTip("上传图片(可一次选择多张，最多 4 张)")
        btn.setStyleSheet("QPushButton{border:2px dashed rgba(255,255,255,0.20);border-radius:13px;"
                          "background:rgba(255,255,255,0.03);}"
                          "QPushButton:hover{border-color:#6b6ff5;background:rgba(99,102,241,0.08);}")
        lab = QtWidgets.QLabel("添加图片")
        lab.setAlignment(QtCore.Qt.AlignCenter)
        lab.setStyleSheet("color:#8b93a3;font-size:10px;background:transparent;border:0;")
        v.addWidget(btn, 0, QtCore.Qt.AlignHCenter)
        v.addWidget(lab)
        self.ref_buttons.append(btn)
        return cell

    def _rebuild_ref_slots(self):
        _clear_layout(self.ref_strip)
        self.ref_buttons = []
        for i, path in enumerate(self._refs):
            self.ref_strip.addWidget(self._make_ref_cell(path, i), 0, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        if len(self._refs) < self.MAX_REFS:
            self.ref_strip.addWidget(self._make_ref_add_cell(), 0, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        if self._refs:
            hint = QtWidgets.QLabel("第1张为待修改图，第2张起为参考图")
            hint.setStyleSheet("color:#6b7488;font-size:11px;background:transparent;border:0;")
            self.ref_strip.addWidget(hint, 0, QtCore.Qt.AlignVCenter)
        self.ref_strip.addStretch()

    def _style_ref_slot(self):
        self._rebuild_ref_slots()

    def pick_ref(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "选择图片", "",
                                                          "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if paths:
            self._append_refs(paths)

    def clear_ref(self):
        self._set_refs([])

    def reedit(self, entry):
        """把这条记录的提示词/参数载回输入区,方便微调后再次生成。"""
        self.inp.setPlainText(entry.get("prompt") or "")
        self._mode_set(entry.get("mode") or "image")
        if entry.get("mode") == "video":
            self._video_model = str(entry.get("model") or self._video_model or _LK888_VIDEO_DEFAULT)
        else:
            self._image_model = str(entry.get("model") or self._image_model or _LK888_IMAGE_DEFAULT)
        for i, (lb, sz, ar) in enumerate(self.ASPECTS):
            if lb == entry.get("aspectLabel"):
                self.aspect_i = i
                self.b_aspect.setText("  " + lb)
                break
        duration = _agent_video_duration(entry.get("duration"))
        self.duration_i = AGENT_VIDEO_DURATIONS.index(duration)
        self.b_duration.setText("  %d 秒" % duration)
        self._set_refs(entry.get("refs") or ([entry.get("ref")] if entry.get("ref") else []))
        self._sync_model_ui()
        try:
            self.inp.setFocus()
        except Exception:
            pass

    def send(self):
        prompt = self.inp.toPlainText().strip()
        if not prompt:
            return
        self._send_confirmed(prompt)

    def _send_confirmed(self, prompt):
        prompt = str(prompt or "").strip()
        if not prompt:
            return
        # 扣费集中到 _start(送生成前扣、失败退),send/regen 共用同一处,避免『再次生成』绕过计费。
        lb, size, ar = self.ASPECTS[self.aspect_i]
        sname, sprompt, _c = self.STYLES[self._style]
        entry = {
            "id": "pg_%d" % int(time.time() * 1000),
            "mode": self._mode,
            "prompt": prompt,
            "visiblePrompt": prompt,
            "style": sprompt, "styleName": sname,
            "aspectLabel": lb, "size": size, "aspect_ratio": ar,
            "count": (self.count_i + 1) if self._mode == "image" else 1,
            "duration": self._current_video_duration(),
            "refs": list(self._refs),
            "ref": (self._refs[0] if self._refs else ""),
            "model": (self._image_model if self._mode == "image" else self._video_model),
            "modelLabel": _lk888_model_label(self._image_model if self._mode == "image" else self._video_model,
                                             self._image_models if self._mode == "image" else self._video_models),
            "status": "生成中", "files": [], "error": "",
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        add_prodgen(entry)
        # 移除空态提示(若在)
        first = self.msgs.itemAt(0)
        if first and first.widget() and isinstance(first.widget(), QtWidgets.QLabel):
            first.widget().setParent(None)
        self._add_card(entry)
        self._scroll_bottom()
        self.inp.clear()
        self._start(entry)

    def optimize_prompt(self):
        prompt = self.inp.toPlainText().strip()
        if not prompt or self._prompt_optimizing:
            return
        self._prompt_optimizing = True
        self._prompt_opt_req = "po_%d_%s" % (int(time.time() * 1000), os.urandom(3).hex())
        req_id = self._prompt_opt_req
        mode = self._mode
        style_hint = (self.STYLES[self._style][1] or "").strip()
        refs = list(self._refs)
        if getattr(self, "optimize_btn", None) is not None:
            self.optimize_btn.setEnabled(False)
            self.optimize_btn.setText("  优化中…")
        if getattr(self, "model_meta", None) is not None:
            self.model_meta.setText("正在优化中文提示词，请稍候…")

        def work():
            try:
                has_ref = bool(refs)
                ref_desc = _prodgen_refs_desc(refs) if has_ref else ""
                optimized = _prodgen_optimize_prompt(
                    prompt, style_hint, ref_desc,
                    is_video=(mode == "video"), edit=(has_ref and mode == "image"))
                BRIDGE.payload.emit("prodgen_prompt_opt", {
                    "id": req_id, "ok": bool(optimized), "prompt": optimized,
                    "error": "" if optimized else "提示词优化失败，请稍后重试或直接生成。",
                })
            except Exception as ex:
                BRIDGE.payload.emit("prodgen_prompt_opt", {
                    "id": req_id, "ok": False, "prompt": "",
                    "error": str(ex)[:160] or "提示词优化失败",
                })
        run_bg(work)

    def _start(self, entry):
        pid = entry.get("id")
        e = dict(entry)  # 传副本给线程,避免主线程后续改动竞争
        cap = "product_video" if e.get("mode") == "video" else "product_image"
        ref = "prodgen:%s" % pid

        def emit(stage, data):
            payload = {"id": pid, "stage": stage}
            payload.update(data or {})
            BRIDGE.payload.emit("prodgen", payload)

        def work():
            okc, cerr = try_charge(cap, ref)  # 生成前扣费(单价=0 时放行)
            if not okc:
                update_prodgen(pid, status="失败", error=cerr or "扣费失败")
                BRIDGE.payload.emit("prodgen", {"id": pid, "status": "失败", "error": cerr or "扣费失败"})
                return
            try:
                files = _prodgen_generate(e, emit)
                update_prodgen(pid, status="完成", files=files, error="")
                BRIDGE.payload.emit("prodgen", {"id": pid, "status": "完成", "files": files})
            except Exception as ex:
                refund_cap(cap, ref)  # 生成失败:退回本次扣费
                update_prodgen(pid, status="失败", error=str(ex)[:160])
                BRIDGE.payload.emit("prodgen", {"id": pid, "status": "失败", "error": str(ex)[:160]})
        run_bg(work)

    def _on(self, tag, d):
        if tag == "prodgen_prompt_opt":
            data = d or {}
            if data.get("id") != self._prompt_opt_req:
                return
            self._prompt_optimizing = False
            if getattr(self, "optimize_btn", None) is not None:
                self.optimize_btn.setEnabled(True)
                self.optimize_btn.setText("  提示词优化")
            self._sync_model_ui()
            if not data.get("ok"):
                QtWidgets.QMessageBox.warning(self, "提示词优化", data.get("error") or "提示词优化失败，请直接生成或稍后重试。")
                return
            dlg = PromptConfirmDialog(data.get("prompt") or self.inp.toPlainText().strip(), self)
            if dlg.exec() == QtWidgets.QDialog.Accepted:
                self._send_confirmed(dlg.value())
            return
        if tag == "prodgen_models":
            data = d or {}
            self._image_models = list(data.get("image") or [])
            self._video_models = list(data.get("video") or [])
            self._models_loaded = bool(self._image_models or self._video_models)
            self._models_loading = False
            self._sync_model_ui()
            return
        if tag == "use_asset_ref":  # 从资产库"用作参考图"跳转过来
            self._append_refs([(d or {}).get("path") or ""])
            return
        if tag != "prodgen":
            return
        d = d or {}
        pid = d.get("id")
        card = self._cards.get(pid)
        stage = d.get("stage")
        if stage == "phase":  # 阶段变化:只更新思考面板标题,不重绘卡片(保住打字机)
            if card:
                card.set_phase(d.get("phaseText") or "")
            return
        if stage == "thinking":  # gpt-5.4 提炼出的提示词 → 打字机逐字浮现
            txt = d.get("expandedPrompt") or ""
            for e in PRODGEN:
                if e.get("id") == pid:
                    e["expandedPrompt"] = txt
                    break
            save_prodgen()
            if card:
                card.type_thinking(txt)
            return
        # ---- 最终状态(完成/失败)才重绘卡片 ----
        for e in PRODGEN:
            if e.get("id") == pid:
                e["status"] = d.get("status") or e.get("status")
                if d.get("files") is not None:
                    e["files"] = d.get("files")
                if d.get("error"):
                    e["error"] = d.get("error")
                if card:
                    card.entry = e
                break
        if card:
            card.refresh()
            self._scroll_bottom()

    def regen(self, entry):
        ne = {k: entry.get(k) for k in ("mode", "prompt", "aspectLabel", "size", "aspect_ratio",
                                        "count", "ref", "refs", "model", "modelLabel", "style", "styleName")}
        ne["id"] = "pg_%d" % int(time.time() * 1000)
        ne["status"] = "生成中"
        ne["files"] = []
        ne["error"] = ""
        ne["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        add_prodgen(ne)
        self._add_card(ne)
        self._scroll_bottom()
        self._start(ne)

    def remove(self, entry):
        pid = entry.get("id")
        remove_prodgen(pid)
        card = self._cards.pop(pid, None)
        if card:
            card.setParent(None)

    def save_to_assets(self, entry):
        files = [f for f in (entry.get("files") or []) if os.path.isfile(f)]
        n = 0
        for f in files:
            if add_asset(f, kind=entry.get("mode"), prompt=entry.get("prompt") or "", source="商品图视频生成"):
                n += 1
        if n:
            entry["saved"] = True
            save_prodgen()
            card = self._cards.get(entry.get("id"))
            if card:
                card.refresh()

    def pick_from_assets(self):
        load_assets()
        imgs = [a for a in ASSETS if a.get("kind") == "image" and os.path.isfile(a.get("path") or "")]
        if not imgs:
            QtWidgets.QMessageBox.information(self, "资产库",
                                             "资产库还没有图片。先在生成结果上点『存资产库』,或到『资产库』页添加。")
            return
        dlg = AssetPickerDialog(imgs, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.selected:
            self._append_refs([dlg.selected])


class AssetPickerDialog(QtWidgets.QDialog):
    """从资产库挑一张图片作为参考图。"""

    def __init__(self, imgs, parent=None):
        super().__init__(parent)
        self.selected = None
        self.setWindowTitle("从资产库选参考图")
        self.setMinimumSize(720, 480)
        self.setStyleSheet("QDialog{background:#0f1320;}")
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 16)
        v.setSpacing(10)
        tip = QtWidgets.QLabel("点击一张图片作为参考图")
        tip.setStyleSheet("color:#c9d1e6;font-size:13px;font-weight:600;background:transparent;")
        v.addWidget(tip)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;}")
        host = QtWidgets.QWidget()
        host.setStyleSheet("background:transparent;")
        grid = QtWidgets.QGridLayout(host)
        grid.setSpacing(12)
        grid.setAlignment(QtCore.Qt.AlignTop)
        cols = 4
        for i, a in enumerate(imgs):
            b = QtWidgets.QPushButton()
            b.setFixedSize(158, 120)
            b.setCursor(QtCore.Qt.PointingHandCursor)
            pm = _thumb_pixmap(a.get("path") or "", 158, 120, 8)
            if not pm.isNull():
                b.setIcon(QtGui.QIcon(pm))
                b.setIconSize(QtCore.QSize(158, 120))
            b.setStyleSheet("QPushButton{border:1px solid rgba(255,255,255,0.12);border-radius:10px;background:#0c0f17;}"
                            "QPushButton:hover{border:2px solid #7376f6;}")
            b.setToolTip(a.get("prompt") or a.get("name") or "")
            b.clicked.connect(lambda _=False, pth=a.get("path"): self._pick(pth))
            grid.addWidget(b, i // cols, i % cols)
        scroll.setWidget(host)
        v.addWidget(scroll, 1)

    def _pick(self, path):
        self.selected = path
        self.accept()


class AssetLibraryPage(BasePage):
    """资产库:本地收藏(你生成的图片/视频)+ 漫剧共享库(角色/主体/场景/风格)双源。
    本地资产可预览/下载/删除/用作参考图;漫剧共享资产可『用作参考图』回生成页图生图 + 复制提示词。"""

    SHARED_TYPE_LABELS = {"character": "角色", "prop": "道具", "scene": "场景",
                          "style_template": "风格", "voice": "音色"}

    def __init__(self):
        super().__init__()
        self._filter = "all"
        self._source = "local"          # local | shared
        self._shared = []               # 漫剧共享资产缓存
        self._shared_loaded = False
        self._shared_err = None
        self._req_gen = 0               # 请求代号,丢弃切换视图后返回的过期缩略图
        self._thumb_labels = {}         # {key: QLabel} 异步网络缩略图回填
        b_open = QtWidgets.QPushButton("打开文件夹")
        b_open.setObjectName("ghost")
        b_open.setCursor(QtCore.Qt.PointingHandCursor)
        b_open.clicked.connect(lambda: _open_path(_assets_dir()))
        b_refresh = QtWidgets.QPushButton("刷新")
        b_refresh.setObjectName("ghost")
        b_refresh.setCursor(QtCore.Qt.PointingHandCursor)
        b_refresh.clicked.connect(self.on_show)
        self.v.addWidget(make_header("资产库", "本地收藏 · 一键用作参考图生成", [b_open, b_refresh]))
        # 数据源切换:本地 / 漫剧共享库
        srow = QtWidgets.QHBoxLayout()
        srow.setSpacing(8)
        self._sbtns = {}
        for key, lbl, ic in (("local", "本地资产", "grid"),):
            b = _icon_text_btn(ic, lbl, _PROD_PILL_SEL if key == "local" else _PROD_PILL,
                               "#ffffff" if key == "local" else "#aab3c5", 15, cb=lambda k=key: self._set_source(k))
            self._sbtns[key] = b
            srow.addWidget(b)
        srow.addStretch()
        self.count_lab = QtWidgets.QLabel("")
        self.count_lab.setObjectName("sub")
        srow.addWidget(self.count_lab)
        self.v.addLayout(srow)
        # 本地过滤(全部/图片/视频)—— 仅本地源显示
        self._filter_w = QtWidgets.QWidget()
        self._filter_w.setStyleSheet("background:transparent;")
        frow = QtWidgets.QHBoxLayout(self._filter_w)
        frow.setContentsMargins(0, 0, 0, 0)
        frow.setSpacing(8)
        self._fbtns = {}
        for key, lbl, ic in (("all", "全部", "grid"), ("image", "图片", "image"), ("video", "视频", "video"), ("note_template", "图文模板", "grid")):
            b = _icon_text_btn(ic, lbl, _PROD_PILL_SEL if key == "all" else _PROD_PILL,
                               "#ffffff" if key == "all" else "#aab3c5", 14, cb=lambda k=key: self._set_filter(k))
            self._fbtns[key] = b
            frow.addWidget(b)
        frow.addStretch()
        self.v.addWidget(self._filter_w)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;}")
        host = QtWidgets.QWidget()
        host.setStyleSheet("background:transparent;")
        self.grid = QtWidgets.QGridLayout(host)
        self.grid.setContentsMargins(2, 4, 12, 4)
        self.grid.setSpacing(14)
        self.grid.setAlignment(QtCore.Qt.AlignTop)
        self.scroll.setWidget(host)
        self.v.addWidget(self.scroll, 1)
        BRIDGE.payload.connect(self._on)

    def on_show(self):
        if self._source == "local":
            load_assets()
            self._build_local()
        else:
            self._build_shared_loading()
            self._load_shared()

    def _set_source(self, src):
        self._source = src
        for k, b in self._sbtns.items():
            b.setStyleSheet(_PROD_PILL_SEL if k == src else _PROD_PILL)
        self._filter_w.setVisible(src == "local")
        self.on_show()

    def _set_filter(self, f):
        self._filter = f
        for k, b in self._fbtns.items():
            b.setStyleSheet(_PROD_PILL_SEL if k == f else _PROD_PILL)
        self._build_local()

    def _clear_grid(self):
        self._thumb_labels = {}
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)

    # ---------- 本地资产 ----------
    def _build_local(self):
        self._clear_grid()
        items = [a for a in ASSETS if isinstance(a, dict)]
        if self._filter != "all":
            items = [a for a in items if a.get("kind") == self._filter]
        self.count_lab.setText("本地 %d 个资产" % len(items))
        if not items:
            empty = QtWidgets.QLabel("本地资产库还是空的。到『商品图和视频生成』出图后点『存资产库』,即可收藏到这里。")
            empty.setStyleSheet("color:#6b7488;font-size:13px;background:transparent;")
            empty.setWordWrap(True)
            self.grid.addWidget(empty, 0, 0)
            return
        cols = 4
        for i, a in enumerate(items):
            self.grid.addWidget(self._asset_card(a), i // cols, i % cols)

    def _asset_card(self, a):
        card = QtWidgets.QFrame()
        card.setObjectName("assetCard")
        card.setStyleSheet("QFrame#assetCard{background:rgba(255,255,255,0.03);"
                           "border:1px solid rgba(255,255,255,0.08);border-radius:14px;}")
        card.setFixedWidth(232)
        v = QtWidgets.QVBoxLayout(card)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)
        thumb = QtWidgets.QLabel()
        thumb.setFixedSize(212, 158)
        thumb.setAlignment(QtCore.Qt.AlignCenter)
        thumb.setStyleSheet("background:#0c0f17;border-radius:10px;")
        path = a.get("path") or ""
        if a.get("kind") == "video":
            thumb.setPixmap(_video_thumb_pixmap(path, 212, 158, 10))
        else:
            pm = _thumb_pixmap(path, 212, 158, 10)
            if not pm.isNull():
                thumb.setPixmap(pm)
            else:
                thumb.setText("图片缺失")
        v.addWidget(thumb)
        cap = QtWidgets.QLabel((a.get("prompt") or a.get("name") or "").strip() or "(无描述)")
        cap.setWordWrap(True)
        cap.setMaximumHeight(34)
        cap.setStyleSheet("color:#aeb6c6;font-size:11px;background:transparent;border:0;")
        v.addWidget(cap)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        if a.get("kind") == "image":
            row.addWidget(_icon_text_btn("image", "参考", _PROD_ACT, "#8fd3ff", 13, cb=lambda: self.use_ref(a)))
        row.addWidget(_icon_text_btn("play", "播放" if a.get("kind") == "video" else "打开", _PROD_ACT, "#98a2b6", 13,
                                     cb=lambda: self.open_asset(a)))
        row.addStretch()
        row.addWidget(_round_icon_btn("trash", 30, "#8b93a3", cb=lambda: self.delete(a.get("id")), tip="删除"))
        v.addLayout(row)
        return card

    def use_ref(self, a):
        BRIDGE.payload.emit("use_asset_ref", {"path": a.get("path")})
        BRIDGE.payload.emit("goto_nav", "🛍️ 商品图和视频生成")

    def open_asset(self, a):
        path = (a or {}).get("path") or ""
        if not (path and os.path.isfile(path)):
            QtWidgets.QMessageBox.warning(self, "资产库", "文件不存在或已被移动。")
            return
        if not _open_path(path):
            QtWidgets.QMessageBox.warning(self, "资产库", "无法打开文件，请检查系统默认播放器。")

    def delete(self, aid):
        remove_asset(aid)
        self._build_local()

    # ---------- 漫剧共享库 ----------
    def _build_shared_loading(self):
        self._clear_grid()
        self.count_lab.setText("正在加载漫剧共享库…")
        tip = QtWidgets.QLabel("正在从漫剧共享资产库加载你的角色/主体/场景/风格…")
        tip.setStyleSheet("color:#6b7488;font-size:13px;background:transparent;")
        tip.setWordWrap(True)
        self.grid.addWidget(tip, 0, 0)

    def _load_shared(self):
        self._req_gen += 1
        gen = self._req_gen

        def work():
            code, j = api("GET", "/api/shared-assets")
            ok = isinstance(j, dict) and j.get("ok")
            BRIDGE.payload.emit("shared_list", {
                "gen": gen,
                "assets": (j.get("assets") if ok else []) or [],
                "shared": (j.get("shared") if isinstance(j, dict) else None),
                "error": None if ok else ((j or {}).get("error") or "load_failed"),
            })
        run_bg(work)

    def _build_shared(self):
        self._clear_grid()
        if self._shared_err:
            msg = "漫剧共享库未启用" if self._shared_err == "shared_disabled" else "加载失败,请点右上角『刷新』重试"
            lab = QtWidgets.QLabel(msg)
            lab.setStyleSheet("color:#c9705f;font-size:13px;background:transparent;")
            self.grid.addWidget(lab, 0, 0)
            self.count_lab.setText("")
            return
        items = [a for a in (self._shared or []) if isinstance(a, dict)]
        self.count_lab.setText("漫剧共享 %d 个资产" % len(items))
        if not items:
            empty = QtWidgets.QLabel("漫剧共享库里还没有资产。你在漫剧画布里创建的角色/主体/场景/风格会出现在这里,可直接用作参考图生成。")
            empty.setStyleSheet("color:#6b7488;font-size:13px;background:transparent;")
            empty.setWordWrap(True)
            self.grid.addWidget(empty, 0, 0)
            return
        cols = 4
        for i, a in enumerate(items):
            self.grid.addWidget(self._shared_card(a, i), i // cols, i % cols)

    def _shared_card(self, a, idx):
        card = QtWidgets.QFrame()
        card.setObjectName("assetCard")
        card.setStyleSheet("QFrame#assetCard{background:rgba(255,255,255,0.03);"
                           "border:1px solid rgba(255,255,255,0.08);border-radius:14px;}")
        card.setFixedWidth(232)
        v = QtWidgets.QVBoxLayout(card)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)
        thumb = QtWidgets.QLabel()
        thumb.setFixedSize(212, 158)
        thumb.setAlignment(QtCore.Qt.AlignCenter)
        thumb.setStyleSheet("background:#0c0f17;border-radius:10px;color:#5b6577;font-size:12px;")
        url = a.get("thumbnail") or ""
        if url:
            thumb.setText("加载中…")
            key = "%d_%s" % (self._req_gen, a.get("id"))
            self._thumb_labels[key] = thumb
            self._fetch_thumb(self._req_gen, key, url, 212, 158)
        else:
            thumb.setText("仅提示词 · 无图")
        v.addWidget(thumb)
        # 类型徽标 + 名称
        trow = QtWidgets.QHBoxLayout()
        trow.setSpacing(6)
        badge = QtWidgets.QLabel(self.SHARED_TYPE_LABELS.get(a.get("type"), a.get("type") or "素材"))
        badge.setStyleSheet("color:#c9b8ff;background:rgba(139,92,246,0.18);border-radius:6px;"
                            "padding:1px 7px;font-size:10px;font-weight:700;")
        trow.addWidget(badge)
        nm = QtWidgets.QLabel((a.get("name") or "").strip() or "未命名")
        nm.setStyleSheet("color:#e8eaf0;font-size:12px;font-weight:700;background:transparent;border:0;")
        nm.setMaximumHeight(18)
        trow.addWidget(nm, 1)
        v.addLayout(trow)
        cap = QtWidgets.QLabel((a.get("prompt") or a.get("description") or "").strip() or "(无提示词)")
        cap.setWordWrap(True)
        cap.setMaximumHeight(30)
        cap.setStyleSheet("color:#8b93a3;font-size:10px;background:transparent;border:0;")
        v.addWidget(cap)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        if url:
            row.addWidget(_icon_text_btn("image", "参考图", _PROD_ACT, "#8fd3ff", 13, cb=lambda a=a: self.use_shared_ref(a)))
        if a.get("prompt"):
            row.addWidget(_icon_text_btn("edit", "提示词", _PROD_ACT, "#98a2b6", 13, cb=lambda a=a: self.copy_prompt(a)))
        row.addStretch()
        v.addLayout(row)
        return card

    def _fetch_thumb(self, gen, key, url, w, h):
        def work():
            b = b""
            try:
                import requests as _rq
                r = _rq.get(url, timeout=25)
                if r.status_code == 200:
                    b = r.content
            except Exception:
                b = b""
            BRIDGE.payload.emit("shared_thumb", {"gen": gen, "key": key, "bytes": b, "w": w, "h": h})
        run_bg(work)

    def use_shared_ref(self, a):
        url = a.get("thumbnail") or ""
        if not url:
            refs = a.get("referenceImages") or []
            url = refs[0] if refs else ""
        if not url:
            return
        self.count_lab.setText("正在下载参考图…")
        gen = self._req_gen

        def work():
            p = ""
            try:
                p = os.path.join(_assets_dir(), "manjuref_%d_%s.png" % (int(time.time()), os.urandom(3).hex()))
                _wf_download(url, p)
            except Exception as e:
                log("shared ref download: %s" % e)
                p = ""
            BRIDGE.payload.emit("shared_ref_ready", {"gen": gen, "path": p})
        run_bg(work)

    def copy_prompt(self, a):
        try:
            QtWidgets.QApplication.clipboard().setText(a.get("prompt") or "")
            self.count_lab.setText("已复制提示词 ✓")
        except Exception:
            pass

    def _on(self, tag, d):
        d = d or {}
        if tag == "shared_list":
            if d.get("gen") != self._req_gen:
                return
            self._shared = d.get("assets") or []
            self._shared_loaded = True
            self._shared_err = ("shared_disabled" if d.get("shared") is False else d.get("error"))
            if self._source == "shared":
                self._build_shared()
        elif tag == "shared_thumb":
            if d.get("gen") != self._req_gen:
                return
            lbl = self._thumb_labels.get(d.get("key"))
            if lbl is not None:
                try:
                    if d.get("bytes"):
                        pm = QtGui.QPixmap()
                        pm.loadFromData(d["bytes"])
                        if not pm.isNull():
                            pm = pm.scaled(d["w"], d["h"], QtCore.Qt.KeepAspectRatioByExpanding,
                                           QtCore.Qt.SmoothTransformation)
                            lbl.setPixmap(_rounded_pixmap(pm, 10))
                        else:
                            lbl.setText("图片加载失败")
                    else:
                        lbl.setText("图片加载失败")
                except Exception:
                    pass
        elif tag == "shared_ref_ready":
            if d.get("gen") != self._req_gen:
                return
            if d.get("path"):
                self.count_lab.setText("")
                BRIDGE.payload.emit("use_asset_ref", {"path": d["path"]})
                BRIDGE.payload.emit("goto_nav", "🛍️ 商品图和视频生成")
            else:
                self.count_lab.setText("参考图下载失败,请重试")


class EnterpriseProfilePage(BasePage):
    """企业资料:维护品牌定位(名称/简介/主营/调性/人群/卖点/签名),生成时统一注入,内容更贴品牌。"""

    FIELDS = [
        ("name", "品牌名", "如:LUMIÈRE 露觅", False),
        ("company", "公司主体", "如:XX 化妆品有限公司", False),
        ("category", "主营品类", "如:护肤 / 彩妆 / 家清", False),
        ("audience", "目标人群", "如:25-35 都市女性,成分党", False),
        ("tone", "风格调性", "如:高级简约 / 国潮 / 活力年轻", False),
        ("intro", "一句话简介", "品牌是做什么的、给谁、差异点", True),
        ("selling", "核心卖点", "逗号分隔:成分党、平价大碗、敏感肌可用…", True),
        ("sign", "统一签名/话术", "发布/私信统一落款(可选)", True),
        ("contact", "联系方式", "官网 / 客服 / 门店(可选)", True),
    ]

    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("企业资料", "维护品牌定位,商品图/软文/文案生成时自动贴合品牌,不跑偏"))
        p = Panel("品牌资料", "填得越全,AI 生成越贴合你的品牌调性(会作为上下文注入生成)")
        form = QtWidgets.QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.inputs = {}
        for key, lbl, ph, multi in self.FIELDS:
            if multi:
                w = QtWidgets.QPlainTextEdit()
                w.setPlaceholderText(ph)
                w.setFixedHeight(58)
            else:
                w = QtWidgets.QLineEdit()
                w.setPlaceholderText(ph)
            self.inputs[key] = w
            lab = QtWidgets.QLabel(lbl)
            lab.setStyleSheet("color:#aeb6c6;font-size:12px;background:transparent;")
            form.addRow(lab, w)
        p.body.addLayout(form)
        brow = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("sub")
        brow.addWidget(self.status)
        brow.addStretch()
        b_save = QtWidgets.QPushButton("保存品牌资料")
        b_save.setObjectName("primary")
        b_save.setCursor(QtCore.Qt.PointingHandCursor)
        b_save.clicked.connect(self.save)
        brow.addWidget(b_save)
        p.body.addLayout(brow)
        self.v.addWidget(p)
        self.v.addStretch()

    def on_show(self):
        load_brand()
        for key, w in self.inputs.items():
            val = str((BRAND or {}).get(key) or "")
            if isinstance(w, QtWidgets.QPlainTextEdit):
                w.setPlainText(val)
            else:
                w.setText(val)

    def _val(self, w):
        return (w.toPlainText() if isinstance(w, QtWidgets.QPlainTextEdit) else w.text()).strip()

    def save(self):
        save_brand({key: self._val(w) for key, w in self.inputs.items()})
        self.status.setText("已保存 ✓  生成时会自动引用品牌定位")


class RiskControlPage(BasePage):
    """风控中心:账号健康总览 + 安全限额(每日发布/评论上限、操作最小间隔、单机并发)。
    『每日发布上限』会约束定时生产每次条数,降低多账号被限流封号风险。"""

    def __init__(self):
        super().__init__()
        self.v.addWidget(make_header("风控中心", "账号健康总览 + 发布/评论安全限额,降低多账号被限流封号风险"))
        p1 = Panel("账号健康", "在线/离线 · Cookie 状态(来自本地引擎与中心)")
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["账号", "平台", "状态", "风险"])
        style_table(self.table)
        self.table.setMinimumHeight(170)
        p1.body.addWidget(self.table)
        self.v.addWidget(p1)
        p2 = Panel("安全限额", "按平台风控经验设置;定时生产会遵循『每日发布上限』")
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        self.spins = {}
        specs = [("dailyPublish", "每日发布上限 / 账号", 1, 50), ("dailyComment", "每日评论上限 / 账号", 1, 300),
                 ("minInterval", "操作最小间隔(秒)", 5, 600), ("concurrency", "单机并发上限", 1, 8)]
        for i, (key, lbl, mn, mx) in enumerate(specs):
            lab = QtWidgets.QLabel(lbl)
            lab.setStyleSheet("color:#aeb6c6;font-size:12px;background:transparent;")
            sp = QtWidgets.QSpinBox()
            sp.setRange(mn, mx)
            sp.setValue(int(RISK.get(key) or mn))
            sp.setFixedWidth(110)
            self.spins[key] = sp
            grid.addWidget(lab, i // 2, (i % 2) * 2)
            grid.addWidget(sp, i // 2, (i % 2) * 2 + 1)
        p2.body.addLayout(grid)
        srow = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("sub")
        srow.addWidget(self.status)
        srow.addStretch()
        b_save = QtWidgets.QPushButton("保存限额")
        b_save.setObjectName("primary")
        b_save.setCursor(QtCore.Qt.PointingHandCursor)
        b_save.clicked.connect(self.save)
        srow.addWidget(b_save)
        p2.body.addLayout(srow)
        self.v.addWidget(p2)
        p3 = Panel("风控建议", "")
        for t in ["同一账号发布间隔建议 ≥ 30 分钟,评论/私信间隔 ≥ 45 秒,并做拟人化随机化",
                  "新号养号期每日操作宜少、逐步加量;避免短时间大量重复内容",
                  "一机一号一 IP 最稳;本客户端用你本机 Edge + 住宅 IP,天然更安全",
                  "发布内容规避明显营销词/违禁词;失败频繁先停手排查 Cookie / 限流"]:
            l = QtWidgets.QLabel("·  " + t)
            l.setWordWrap(True)
            l.setStyleSheet("color:#aeb6c6;font-size:12px;background:transparent;padding:2px 0;")
            p3.body.addWidget(l)
        self.v.addWidget(p3)
        self.v.addStretch()
        BRIDGE.payload.connect(self._on)

    def on_show(self):
        load_risk()
        for key, sp in self.spins.items():
            sp.setValue(int(RISK.get(key) or sp.value()))

        def work():
            _c, j = api("GET", "/api/accounts")
            arr = j if isinstance(j, list) else ((j or {}).get("value") or (j or {}).get("accounts") or [])
            BRIDGE.payload.emit("risk_accounts", clean_accounts(arr if isinstance(arr, list) else []))
        run_bg(work)

    def _on(self, tag, d):
        if tag != "risk_accounts":
            return
        rows = clean_accounts(d or [])
        self.table.setRowCount(0)
        for x in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            name = x.get("name") or x.get("nickname") or x.get("id") or "-"
            plat = "抖音" if str(x.get("platform") or "").lower() == "douyin" else (
                "小红书" if "xhs" in str(x.get("platform") or "").lower() else (x.get("platform") or "-"))
            status = str(x.get("status") or x.get("state") or "-")
            online = ("在线" in status) or (str(x.get("online")).lower() == "true")
            cookie_bad = "失效" in str(x.get("cookie") or "") or "无" in str(x.get("cookie") or "")
            risk = "高风险" if cookie_bad else ("低风险" if online else "中风险")
            for c, val in enumerate([name, plat, status, risk]):
                it = QtWidgets.QTableWidgetItem(str(val))
                if c == 3:
                    it.setForeground(QtGui.QColor("#ef5555" if risk == "高风险"
                                                  else ("#22c55e" if risk == "低风险" else "#f5a623")))
                self.table.setItem(r, c, it)

    def save(self):
        save_risk({k: sp.value() for k, sp in self.spins.items()})
        self.status.setText("已保存 ✓  定时生产将遵循每日发布上限")


class AssetMultiPicker(QtWidgets.QDialog):
    """从资产库多选素材(图片+视频),按行序返回路径列表。"""

    def __init__(self, assets, parent=None):
        super().__init__(parent)
        self.selected = []
        self.setWindowTitle("从资产库选素材(可多选)")
        self.setMinimumSize(780, 520)
        self.setStyleSheet("QDialog{background:#0f1320;}")
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 16)
        v.setSpacing(10)
        tip = QtWidgets.QLabel("按住 Ctrl / Shift 多选;确定后按顺序加入混剪时间线")
        tip.setStyleSheet("color:#c9d1e6;font-size:13px;font-weight:600;background:transparent;")
        v.addWidget(tip)
        self.lw = QtWidgets.QListWidget()
        self.lw.setViewMode(QtWidgets.QListView.IconMode)
        self.lw.setIconSize(QtCore.QSize(150, 110))
        self.lw.setResizeMode(QtWidgets.QListView.Adjust)
        self.lw.setMovement(QtWidgets.QListView.Static)
        self.lw.setSpacing(10)
        self.lw.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        _lwbg = "#ffffff" if is_light() else "#0b0e17"
        _lwbd = TK["cardBorder"]
        _lwtx = TK["text"]
        self.lw.setStyleSheet("QListWidget{background:%s;border:1px solid %s;border-radius:12px;color:%s;}" % (_lwbg, _lwbd, _lwtx)
                              + "QListWidget::item{border-radius:8px;padding:4px;}"
                              + "QListWidget::item:selected{background:rgba(99,102,241,0.28);border:1px solid #7376f6;}")
        for a in [x for x in (assets or []) if isinstance(x, dict) and os.path.isfile(x.get("path") or "")]:
            it = QtWidgets.QListWidgetItem()
            pm = _video_thumb_pixmap(a.get("path"), 150, 110, 8) if a.get("kind") == "video" else _thumb_pixmap(a.get("path"), 150, 110, 8)
            if not pm.isNull():
                it.setIcon(QtGui.QIcon(pm))
            it.setData(QtCore.Qt.UserRole, a.get("path"))
            it.setText(("🎬 " if a.get("kind") == "video" else "🖼 ") + (a.get("prompt") or a.get("name") or "")[:14])
            self.lw.addItem(it)
        v.addWidget(self.lw, 1)
        brow = QtWidgets.QHBoxLayout()
        brow.addStretch()
        b_cancel = QtWidgets.QPushButton("取消")
        b_cancel.clicked.connect(self.reject)
        b_ok = QtWidgets.QPushButton("确定")
        b_ok.setObjectName("primary")
        b_ok.clicked.connect(self._ok)
        brow.addWidget(b_cancel)
        brow.addWidget(b_ok)
        v.addLayout(brow)

    def _ok(self):
        self.selected = [self.lw.item(i).data(QtCore.Qt.UserRole)
                         for i in range(self.lw.count()) if self.lw.item(i).isSelected()]
        self.accept()


class MixPage(BasePage):
    """混剪短视频:从资产库/本地选多个图片+视频片段,本机 ffmpeg 规整拼接成一条短视频(可加 BGM)。"""

    def __init__(self):
        super().__init__()
        self.clips = []
        self.bgm = ""
        self.result = ""
        self.v.addWidget(make_header("混剪短视频", "选多个图片/视频片段 → 本机 ffmpeg 规整拼接成一条短视频(可加背景音乐)"))
        tool = QtWidgets.QHBoxLayout()
        tool.setSpacing(8)
        b_ast = _icon_text_btn("grid", "从资产库添加", _PROD_PILL, "#aab3c5", 15, cb=self.add_from_assets)
        b_loc = _icon_text_btn("plus", "本地文件", _PROD_PILL, "#aab3c5", 15, cb=self.add_local)
        tool.addWidget(b_ast)
        tool.addWidget(b_loc)
        tool.addWidget(QtWidgets.QLabel("画幅"))
        self.size_cb = QtWidgets.QComboBox()
        self.size_cb.addItems(list(_MIX_SIZES.keys()))
        tool.addWidget(self.size_cb)
        tool.addWidget(QtWidgets.QLabel("每图秒数"))
        self.per_sp = QtWidgets.QSpinBox()
        self.per_sp.setRange(1, 8)
        self.per_sp.setValue(3)
        self.per_sp.setFixedWidth(64)
        tool.addWidget(self.per_sp)
        self.bgm_btn = _icon_text_btn("play", "背景音乐", _PROD_PILL, "#aab3c5", 15, cb=self.pick_bgm)
        tool.addWidget(self.bgm_btn)
        tool.addStretch()
        self.mix_btn = QtWidgets.QPushButton("开始混剪")
        self.mix_btn.setObjectName("primary")
        self.mix_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.mix_btn.clicked.connect(self.start_mix)
        tool.addWidget(self.mix_btn)
        self.v.addLayout(tool)
        self.status = QtWidgets.QLabel("时间线为空。先『从资产库添加』或『本地文件』选至少 2 个片段。")
        self.status.setObjectName("sub")
        self.v.addWidget(self.status)
        # 时间线
        self.tl_scroll = QtWidgets.QScrollArea()
        self.tl_scroll.setWidgetResizable(True)
        self.tl_scroll.setFixedHeight(148)
        self.tl_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.tl_scroll.setStyleSheet("QScrollArea{background:rgba(255,255,255,0.02);border:1px solid #1c2233;border-radius:12px;}")
        host = QtWidgets.QWidget()
        host.setStyleSheet("background:transparent;")
        self.tl = QtWidgets.QHBoxLayout(host)
        self.tl.setContentsMargins(10, 8, 10, 8)
        self.tl.setSpacing(10)
        self.tl.addStretch()
        self.tl_scroll.setWidget(host)
        self.v.addWidget(self.tl_scroll)
        # 结果
        self.result_box = QtWidgets.QWidget()
        self.result_box.setStyleSheet("background:transparent;")
        self.rl = QtWidgets.QHBoxLayout(self.result_box)
        self.rl.setContentsMargins(0, 6, 0, 0)
        self.v.addWidget(self.result_box)
        self.v.addStretch()
        BRIDGE.payload.connect(self._on)

    def on_show(self):
        self._rebuild()

    def add_from_assets(self):
        load_assets()
        if not ASSETS:
            QtWidgets.QMessageBox.information(self, "资产库", "资产库还没有素材。先到『商品图和视频生成』出图/出片并『存资产库』。")
            return
        dlg = AssetMultiPicker(ASSETS, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.selected:
            self.clips += [p for p in dlg.selected if p]
            self._rebuild()

    def add_local(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "选择图片/视频", "", "图片视频 (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mov *.webm)")
        if paths:
            self.clips += list(paths)
            self._rebuild()

    def pick_bgm(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择背景音乐", "", "音频 (*.mp3 *.wav *.m4a *.aac)")
        if p:
            self.bgm = p
            self.bgm_btn.setText("  BGM:" + os.path.basename(p)[:12])

    def remove_clip(self, i):
        if 0 <= i < len(self.clips):
            del self.clips[i]
            self._rebuild()

    def _rebuild(self):
        while self.tl.count() > 1:
            it = self.tl.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
        for i, p in enumerate(self.clips):
            self.tl.insertWidget(i, self._clip_card(i, p))
        n = len(self.clips)
        if n:
            self.status.setText("已选 %d 个片段 · 顺序即拼接顺序 · 点素材右上角 × 移除" % n)
        else:
            self.status.setText("时间线为空。先『从资产库添加』或『本地文件』选至少 2 个片段。")

    def _clip_card(self, i, path):
        card = QtWidgets.QFrame()
        card.setFixedSize(126, 128)
        card.setStyleSheet("QFrame{background:transparent;}")
        vv = QtWidgets.QVBoxLayout(card)
        vv.setContentsMargins(0, 0, 0, 0)
        vv.setSpacing(4)
        thumb = QtWidgets.QLabel()
        thumb.setFixedSize(126, 94)
        is_vid = os.path.splitext(path)[1].lower() in (".mp4", ".mov", ".webm", ".m4v")
        pm = _video_thumb_pixmap(path, 126, 94, 8) if is_vid else _thumb_pixmap(path, 126, 94, 8)
        if not pm.isNull():
            thumb.setPixmap(pm)
        thumb.setStyleSheet("background:#0c0f17;border-radius:8px;")
        vv.addWidget(thumb)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 0)
        idx = QtWidgets.QLabel("%d" % (i + 1))
        idx.setStyleSheet("color:#8b93a3;font-size:11px;font-weight:700;background:transparent;")
        row.addWidget(idx)
        row.addStretch()
        x = _round_icon_btn("trash", 24, "#8b93a3", cb=lambda: self.remove_clip(i), tip="移除")
        row.addWidget(x)
        vv.addLayout(row)
        return card

    def start_mix(self):
        clips = list(self.clips)
        if len(clips) < 2:
            self.status.setText("至少选 2 个片段才能混剪。")
            return
        self.mix_btn.setEnabled(False)
        self.mix_btn.setText("混剪中…")
        self.status.setText("① ffmpeg 规整片段…")
        size_label = self.size_cb.currentText()
        per = self.per_sp.value()
        bgm = self.bgm
        out = os.path.join(data_dir(), "mix_%d.mp4" % int(time.time()))

        def prog(done, total):
            BRIDGE.payload.emit("mix", {"stage": "prog", "done": done, "total": total})

        def work():
            ref = "mix:%d" % int(time.time() * 1000)
            okc, cerr = try_charge("mix", ref)
            if not okc:
                BRIDGE.payload.emit("mix", {"stage": "error", "error": cerr})
                return
            try:
                mix_clips(clips, out, size_label=size_label, per_image=per, bgm=bgm, progress=prog)
                BRIDGE.payload.emit("mix", {"stage": "done", "out": out})
            except Exception as ex:
                refund_cap("mix", ref)
                BRIDGE.payload.emit("mix", {"stage": "error", "error": str(ex)[:200]})
        run_bg(work)

    def _on(self, tag, d):
        if tag != "mix":
            return
        d = d or {}
        st = d.get("stage")
        if st == "prog":
            self.status.setText("① ffmpeg 规整片段… %s/%s" % (d.get("done"), d.get("total")))
        elif st == "error":
            self.mix_btn.setEnabled(True)
            self.mix_btn.setText("开始混剪")
            self.status.setText("混剪失败:" + str(d.get("error")))
        elif st == "done":
            self.mix_btn.setEnabled(True)
            self.mix_btn.setText("开始混剪")
            self.result = d.get("out") or ""
            self.status.setText("混剪完成 ✓ → " + os.path.basename(self.result))
            self._show_result()

    def _show_result(self):
        while self.rl.count():
            it = self.rl.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
        if not (self.result and os.path.isfile(self.result)):
            return
        poster = QtWidgets.QLabel()
        poster.setFixedSize(150, 112)
        poster.setPixmap(_video_thumb_pixmap(self.result, 150, 112, 10))
        poster.setStyleSheet("background:transparent;")
        self.rl.addWidget(poster)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(8)
        lab = QtWidgets.QLabel("成片已生成")
        lab.setStyleSheet("color:#e8eaf0;font-size:13px;font-weight:700;background:transparent;")
        col.addWidget(lab)
        brow = QtWidgets.QHBoxLayout()
        brow.setSpacing(8)
        brow.addWidget(_icon_text_btn("play", "播放", _PROD_ACT, "#98a2b6", 14, cb=lambda: _open_path(self.result)))
        brow.addWidget(_icon_text_btn("star", "存资产库", _PROD_ACT, "#f5c451", 14, cb=self._save_asset))
        brow.addStretch()
        col.addLayout(brow)
        col.addStretch()
        wrap = QtWidgets.QWidget()
        wrap.setStyleSheet("background:transparent;")
        wrap.setLayout(col)
        self.rl.addWidget(wrap, 1)

    def _save_asset(self):
        if self.result and os.path.isfile(self.result):
            add_asset(self.result, kind="video", prompt="混剪 %d 个素材" % len(self.clips), source="混剪短视频")
            self.status.setText("已存入资产库 ✓")


class RechargeDialog(QtWidgets.QDialog):
    """微信扫码充值云豆:选档位/自定义金额 → 生成二维码 → 轮询订单到账(服务端查微信,无需回调)。"""
    PACKAGES = [(6, 60), (30, 300), (68, 680), (128, 1280), (298, 2980), (648, 6480)]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("微信扫码充值")
        self.setModal(True)
        self.setMinimumWidth(384)
        self._order = None
        self._sel_yuan = 30
        self._deadline = 0
        self._poll = QtCore.QTimer(self)
        self._poll.timeout.connect(self._poll_once)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(12)
        t = QtWidgets.QLabel("选择充值金额(1 元 = 10 云豆)")
        t.setStyleSheet("font-size:14px;font-weight:700;background:transparent;")
        v.addWidget(t)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(8)
        self._pkg_btns = []
        for i, (yuan, yd) in enumerate(self.PACKAGES):
            b = QtWidgets.QPushButton("¥%d\n%d 云豆" % (yuan, yd))
            b.setCheckable(True)
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setMinimumHeight(52)
            b.clicked.connect(lambda _=False, y=yuan: self._pick(y))
            grid.addWidget(b, i // 3, i % 3)
            self._pkg_btns.append((yuan, b))
        v.addLayout(grid)
        crow = QtWidgets.QHBoxLayout()
        crow.setSpacing(8)
        lab = QtWidgets.QLabel("自定义")
        lab.setStyleSheet("background:transparent;")
        crow.addWidget(lab)
        self.custom_in = QtWidgets.QLineEdit()
        self.custom_in.setPlaceholderText("1~5000 元")
        self.custom_in.setValidator(QtGui.QIntValidator(1, 5000, self))
        self.custom_in.textEdited.connect(self._custom_edited)
        crow.addWidget(self.custom_in, 1)
        yl = QtWidgets.QLabel("元")
        yl.setStyleSheet("background:transparent;")
        crow.addWidget(yl)
        v.addLayout(crow)
        self.gen_btn = QtWidgets.QPushButton("生成支付二维码")
        self.gen_btn.setObjectName("primary")
        self.gen_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.gen_btn.setMinimumHeight(42)
        self.gen_btn.clicked.connect(self._create)
        v.addWidget(self.gen_btn)
        self.qr_lab = QtWidgets.QLabel()
        self.qr_lab.setAlignment(QtCore.Qt.AlignCenter)
        self.qr_lab.setFixedHeight(0)
        v.addWidget(self.qr_lab)
        self.msg = QtWidgets.QLabel("")
        self.msg.setAlignment(QtCore.Qt.AlignCenter)
        self.msg.setWordWrap(True)
        self.msg.setObjectName("sub")
        v.addWidget(self.msg)
        BRIDGE.payload.connect(self._on_payload)
        self._pick(30)

    def _pick(self, yuan):
        self._sel_yuan = yuan
        self.custom_in.clear()
        for y, b in self._pkg_btns:
            b.setChecked(y == yuan)

    def _custom_edited(self, txt):
        for _y, b in self._pkg_btns:
            b.setChecked(False)
        try:
            self._sel_yuan = int(txt) if txt else 0
        except Exception:
            self._sel_yuan = 0

    def _create(self):
        yuan = self._sel_yuan
        if not (1 <= yuan <= 5000):
            self.msg.setText("请输入 1~5000 元的金额")
            return
        self.gen_btn.setEnabled(False)
        self.msg.setText("正在向微信下单…")

        def work():
            _c, j = api("POST", "/api/billing/recharge/create", {"amountYuan": yuan})
            BRIDGE.payload.emit("recharge_created", {"j": j or {}})
        run_bg(work)

    def _on_payload(self, tag, d):
        if tag == "recharge_created":
            j = (d or {}).get("j") or {}
            self.gen_btn.setEnabled(True)
            if j.get("ok") and j.get("codeUrl"):
                self._order = j
                self._render_qr(j["codeUrl"])
                self.msg.setText("请用微信扫码支付 ¥%.2f(到账 %d 云豆)" % (j.get("amountFen", 0) / 100.0, j.get("yundou", 0)))
                self._deadline = time.time() + 300
                self._poll.start(3000)
            else:
                self.msg.setText("下单失败:%s" % (j.get("error") or "请稍后重试"))
            return
        if tag == "recharge_status":
            j = (d or {}).get("j") or {}
            if not j.get("ok"):
                return
            st = j.get("status")
            if st == "SUCCESS" or j.get("credited"):
                self._poll.stop()
                self.qr_lab.clear()
                self.qr_lab.setFixedHeight(0)
                self.msg.setText("✅ 支付成功,已到账 %d 云豆!" % (self._order or {}).get("yundou", 0))
                QtCore.QTimer.singleShot(1600, self.accept)
            elif st in ("CLOSED", "REVOKED", "PAYERROR"):
                self._poll.stop()
                self.msg.setText("订单已关闭,请重新发起充值")
            return

    def _poll_once(self):
        if time.time() > self._deadline:
            self._poll.stop()
            self.msg.setText("二维码已超时,请重新生成")
            return
        ono = (self._order or {}).get("orderNo")
        if not ono:
            return

        def work():
            _c, j = api("GET", "/api/billing/recharge/status?orderNo=" + str(ono))
            BRIDGE.payload.emit("recharge_status", {"j": j or {}})
        run_bg(work)

    def _render_qr(self, code_url):
        try:
            import qrcode
            from io import BytesIO
            qr = qrcode.QRCode(border=2, box_size=8)
            qr.add_data(code_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#111111", back_color="white").convert("RGB")
            buf = BytesIO()
            img.save(buf, "PNG")
            pm = QtGui.QPixmap()
            pm.loadFromData(buf.getvalue())
            self.qr_lab.setFixedHeight(240)
            self.qr_lab.setPixmap(pm.scaled(220, 220, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        except Exception as e:
            self.qr_lab.setFixedHeight(40)
            self.qr_lab.setText("二维码生成失败:%s" % e)

    def closeEvent(self, e):
        self._poll.stop()
        try:
            BRIDGE.payload.disconnect(self._on_payload)
        except Exception:
            pass
        super().closeEvent(e)


class AccountPage(BasePage):
    """账户中心:云豆余额、消费流水、手机号绑定;管理员可管理用户与充值。"""

    def __init__(self):
        super().__init__()
        self._cd = 0
        self.v.addWidget(make_header("账户中心", "云豆余额 · 消费流水 · 手机绑定(管理员可管理用户/充值)"))
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(14)
        balp = Panel("云豆余额", "生成商品图/视频等按云豆计费(单价上线后生效)")
        self.bal_lab = QtWidgets.QLabel("—")
        self.bal_lab.setStyleSheet("color:#f5c451;font-size:34px;font-weight:800;background:transparent;border:0;")
        balp.body.addWidget(self.bal_lab)
        self.billing_box = QtWidgets.QWidget()
        billing_layout = QtWidgets.QVBoxLayout(self.billing_box)
        billing_layout.setContentsMargins(0, 0, 0, 0)
        billing_layout.setSpacing(8)
        brow = QtWidgets.QHBoxLayout()
        b_ref = QtWidgets.QPushButton("刷新余额")
        b_ref.setObjectName("ghost")
        b_ref.setCursor(QtCore.Qt.PointingHandCursor)
        b_ref.clicked.connect(self.load_balance)
        self.b_recharge = QtWidgets.QPushButton("微信充值")
        self.b_recharge.setObjectName("primary")
        self.b_recharge.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_recharge.clicked.connect(self.open_recharge)
        brow.addWidget(b_ref)
        brow.addWidget(self.b_recharge)
        brow.addStretch()
        billing_layout.addLayout(brow)
        # 自助充值:兑换码
        rrow = QtWidgets.QHBoxLayout()
        rrow.setSpacing(8)
        self.redeem_in = QtWidgets.QLineEdit()
        self.redeem_in.setPlaceholderText("输入兑换码充值,如 MXxx-xxxx-xxxx-xxxx")
        self.redeem_in.returnPressed.connect(self.do_redeem)
        self.b_redeem = QtWidgets.QPushButton("兑换")
        self.b_redeem.setObjectName("primary")
        self.b_redeem.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_redeem.clicked.connect(self.do_redeem)
        rrow.addWidget(self.redeem_in, 1)
        rrow.addWidget(self.b_redeem)
        billing_layout.addLayout(rrow)
        self.redeem_msg = QtWidgets.QLabel("兑换码可联系运营方获取(计费单价由运营方设定)")
        self.redeem_msg.setObjectName("sub")
        billing_layout.addWidget(self.redeem_msg)
        self.billing_box.setVisible(product_role() == "platform_admin")
        balp.body.addWidget(self.billing_box)
        top.addWidget(balp, 1)
        bindp = Panel("手机号", "绑定 / 更换登录手机号")
        self.phone_in = QtWidgets.QLineEdit()
        self.phone_in.setPlaceholderText("手机号")
        self.phone_in.setMaxLength(11)
        bindp.body.addWidget(self.phone_in)
        crow = QtWidgets.QHBoxLayout()
        crow.setSpacing(8)
        self.code_in = QtWidgets.QLineEdit()
        self.code_in.setPlaceholderText("短信验证码")
        self.code_in.setMaxLength(6)
        self.getcode_btn = QtWidgets.QPushButton("获取验证码")
        self.getcode_btn.setObjectName("ghost")
        self.getcode_btn.setFixedWidth(108)
        self.getcode_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.getcode_btn.clicked.connect(self.send_code)
        crow.addWidget(self.code_in, 1)
        crow.addWidget(self.getcode_btn)
        bindp.body.addLayout(crow)
        b_bind = QtWidgets.QPushButton("绑定手机号")
        b_bind.setObjectName("primary")
        b_bind.setCursor(QtCore.Qt.PointingHandCursor)
        b_bind.clicked.connect(self.bind)
        bindp.body.addWidget(b_bind)
        self.bind_msg = QtWidgets.QLabel("")
        self.bind_msg.setObjectName("sub")
        bindp.body.addWidget(self.bind_msg)
        top.addWidget(bindp, 1)
        self.v.addLayout(top)
        lt = QtWidgets.QLabel("消费流水")
        lt.setStyleSheet("color:%s;font-size:12px;font-weight:700;background:transparent;" % TK["sub"])
        self.v.addWidget(lt)
        self.ltable = QtWidgets.QTableWidget(0, 4)
        self.ltable.setHorizontalHeaderLabels(["时间", "项目", "变动", "余额后"])
        style_table(self.ltable)
        self.v.addWidget(self.ltable, 1)
        self.admin_box = QtWidgets.QWidget()
        self.admin_box.setObjectName("adminBox")
        # 用 objectName 作用域,避免裸 background:transparent 级联到子控件(会把内部 primary 按钮背景也抹成透明)
        self.admin_box.setStyleSheet("#adminBox{background:transparent;}")
        avl = QtWidgets.QVBoxLayout(self.admin_box)
        avl.setContentsMargins(0, 6, 0, 0)
        at = QtWidgets.QLabel("用户管理(管理员)")
        at.setStyleSheet("color:%s;font-size:12px;font-weight:700;background:transparent;" % TK["sub"])
        avl.addWidget(at)
        self.utable = QtWidgets.QTableWidget(0, 4)
        self.utable.setHorizontalHeaderLabels(["账号", "手机号", "云豆余额", "操作"])
        style_table(self.utable)
        avl.addWidget(self.utable)
        # 兑换码生成(管理员):批量生成 → 弹窗展示可复制
        ct = QtWidgets.QLabel("兑换码生成(管理员)")
        ct.setStyleSheet("color:%s;font-size:12px;font-weight:700;background:transparent;" % TK["sub"])
        avl.addWidget(ct)
        crow2 = QtWidgets.QHBoxLayout()
        crow2.setSpacing(8)
        self.gc_count = QtWidgets.QSpinBox()
        self.gc_count.setRange(1, 2000)
        self.gc_count.setValue(10)
        self.gc_count.setPrefix("数量 ")
        self.gc_amount = QtWidgets.QSpinBox()
        self.gc_amount.setRange(1, 1000000)
        self.gc_amount.setValue(100)
        self.gc_amount.setPrefix("面值 ")
        self.gc_amount.setSuffix(" 云豆")
        self.gc_note = QtWidgets.QLineEdit()
        self.gc_note.setPlaceholderText("备注(可选,如:双十一活动)")
        self.b_gencodes = QtWidgets.QPushButton("生成兑换码")
        self.b_gencodes.setObjectName("primary")
        self.b_gencodes.setCursor(QtCore.Qt.PointingHandCursor)
        self.b_gencodes.clicked.connect(self.gen_codes)
        crow2.addWidget(self.gc_count)
        crow2.addWidget(self.gc_amount)
        crow2.addWidget(self.gc_note, 1)
        crow2.addWidget(self.b_gencodes)
        avl.addLayout(crow2)
        self.gc_msg = QtWidgets.QLabel("")
        self.gc_msg.setObjectName("sub")
        avl.addWidget(self.gc_msg)
        self.admin_box.setVisible(False)
        self.v.addWidget(self.admin_box, 1)
        BRIDGE.payload.connect(self._on)
        self._cd_timer = QtCore.QTimer(self)
        self._cd_timer.timeout.connect(self._tick)

    def on_show(self):
        self.billing_box.setVisible(product_role() == "platform_admin")
        self.load_balance()
        self.load_ledger()
        if product_role() == "platform_admin":
            self.load_users()
        else:
            self.admin_box.setVisible(False)

    def load_balance(self):
        def work():
            bal = fetch_balance()
            BRIDGE.payload.emit("acct_bal", {"balance": bal})
        run_bg(work)

    def load_ledger(self):
        def work():
            _c, j = api("GET", "/api/billing/ledger")
            BRIDGE.payload.emit("acct_ledger", {"rows": (j or {}).get("ledger") or []})
        run_bg(work)

    def load_users(self):
        if product_role() != "platform_admin":
            self.admin_box.setVisible(False)
            return
        def work():
            c, j = api("GET", "/api/admin/users")
            BRIDGE.payload.emit("acct_users", {"ok": isinstance(j, dict) and j.get("ok"),
                                               "users": (j or {}).get("users") or []})
        run_bg(work)

    def send_code(self):
        phone = self.phone_in.text().strip()
        if not (phone.isdigit() and len(phone) == 11):
            self.bind_msg.setText("请输入 11 位手机号")
            return
        if self._cd > 0:
            return
        self.getcode_btn.setEnabled(False)
        self.bind_msg.setText("发送中…")

        def work():
            _c, j = api("POST", "/api/auth/send-code", {"phone": phone, "scene": "register"})
            BRIDGE.payload.emit("acct_sendcode", {"ok": bool(isinstance(j, dict) and j.get("ok")), "j": j or {}})
        run_bg(work)

    def bind(self):
        phone = self.phone_in.text().strip()
        code = self.code_in.text().strip()
        if not (phone.isdigit() and len(phone) == 11) or not code:
            self.bind_msg.setText("请输入手机号和验证码")
            return
        self.bind_msg.setText("绑定中…")

        def work():
            _c, j = api("POST", "/api/auth/bind-phone", {"phone": phone, "code": code})
            BRIDGE.payload.emit("acct_bind", {"ok": isinstance(j, dict) and j.get("ok"),
                                              "err": (j or {}).get("error")})
        run_bg(work)

    def _tick(self):
        self._cd -= 1
        if self._cd <= 0:
            self._cd_timer.stop()
            self.getcode_btn.setText("获取验证码")
            self.getcode_btn.setEnabled(True)
        else:
            self.getcode_btn.setText("%ds" % self._cd)

    def topup(self, uid, name):
        amt, ok = QtWidgets.QInputDialog.getDouble(self, "充值云豆", "给「%s」充值云豆数量:" % name, 100, 0, 1000000, 0)
        if not ok:
            return

        def work():
            _c, j = api("POST", "/api/billing/topup", {"userId": uid, "amount": amt, "reason": "管理员充值"})
            BRIDGE.payload.emit("acct_topup", {"ok": isinstance(j, dict) and j.get("ok"), "err": (j or {}).get("error")})
        run_bg(work)

    def do_redeem(self):
        code = self.redeem_in.text().strip()
        if not code:
            self.redeem_msg.setText("请输入兑换码")
            return
        self.b_redeem.setEnabled(False)
        self.redeem_msg.setText("兑换中…")

        def work():
            _c, j = api("POST", "/api/billing/redeem", {"code": code})
            BRIDGE.payload.emit("acct_redeem", {"ok": isinstance(j, dict) and j.get("ok"), "j": j or {}})
        run_bg(work)

    def open_recharge(self):
        try:
            RechargeDialog(self).exec()
        except Exception as e:
            log("recharge dialog: %s" % e)
            QtWidgets.QMessageBox.warning(self, "微信充值", "打开充值失败:%s" % e)
        self.load_balance()
        try:
            fetch_balance()  # 同步刷新侧栏余额
        except Exception:
            pass

    def gen_codes(self):
        count = self.gc_count.value()
        amount = self.gc_amount.value()
        note = self.gc_note.text().strip()
        self.b_gencodes.setEnabled(False)
        self.gc_msg.setText("生成中…")

        def work():
            _c, j = api("POST", "/api/admin/redeem-codes/generate",
                        {"count": count, "amount": amount, "note": note})
            BRIDGE.payload.emit("acct_gencodes", {"ok": isinstance(j, dict) and j.get("ok"),
                                                  "codes": (j or {}).get("codes") or [],
                                                  "amount": amount, "err": (j or {}).get("error")})
        run_bg(work)

    def _show_codes_dialog(self, codes, amount):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("兑换码 · 每张 %s 云豆 · 共 %d 张" % (amount, len(codes)))
        dlg.resize(380, 440)
        v = QtWidgets.QVBoxLayout(dlg)
        tip = QtWidgets.QLabel("请复制保存,发给用户在『账户中心』兑换。每张仅能使用一次。")
        tip.setWordWrap(True)
        v.addWidget(tip)
        te = QtWidgets.QPlainTextEdit()
        te.setReadOnly(True)
        te.setPlainText("\n".join(codes))
        v.addWidget(te, 1)
        h = QtWidgets.QHBoxLayout()
        h.addStretch()
        cp = QtWidgets.QPushButton("复制全部")
        cp.setCursor(QtCore.Qt.PointingHandCursor)
        cp.clicked.connect(lambda: (QtWidgets.QApplication.clipboard().setText("\n".join(codes)),
                                    cp.setText("已复制 ✓")))
        cl = QtWidgets.QPushButton("关闭")
        cl.clicked.connect(dlg.accept)
        h.addWidget(cp)
        h.addWidget(cl)
        v.addLayout(h)
        dlg.exec()

    def _on(self, tag, d):
        d = d or {}
        if tag == "acct_bal":
            bal = d.get("balance")
            if bal is None:
                self.bal_lab.setText("—")
            elif bal == float("inf") or str(bal) == "inf":
                self.bal_lab.setText("∞  运营方")
            else:
                self.bal_lab.setText("%s" % (int(bal) if float(bal) == int(bal) else round(float(bal), 2)))
        elif tag == "acct_ledger":
            rows = d.get("rows") or []
            self.ltable.setRowCount(0)
            for x in rows:
                if not isinstance(x, dict):
                    continue
                r = self.ltable.rowCount()
                self.ltable.insertRow(r)
                ts = time.strftime("%m-%d %H:%M", time.localtime(float(x.get("ts") or 0)))
                delta = x.get("delta") or 0
                self.ltable.setItem(r, 0, QtWidgets.QTableWidgetItem(ts))
                self.ltable.setItem(r, 1, QtWidgets.QTableWidgetItem(str(x.get("reason") or "-")))
                di = QtWidgets.QTableWidgetItem(("+%s" % delta) if float(delta) >= 0 else str(delta))
                di.setForeground(QtGui.QColor("#22c55e" if float(delta) >= 0 else "#ef5555"))
                self.ltable.setItem(r, 2, di)
                self.ltable.setItem(r, 3, QtWidgets.QTableWidgetItem(str(x.get("balanceAfter"))))
        elif tag == "acct_users":
            self.admin_box.setVisible(bool(d.get("ok")))
            if not d.get("ok"):
                return
            users = d.get("users") or []
            self.utable.setRowCount(0)
            for u in users:
                if not isinstance(u, dict):
                    continue
                r = self.utable.rowCount()
                self.utable.insertRow(r)
                self.utable.setItem(r, 0, QtWidgets.QTableWidgetItem(str(u.get("name") or u.get("id"))))
                self.utable.setItem(r, 1, QtWidgets.QTableWidgetItem(str(u.get("phone") or "-")))
                self.utable.setItem(r, 2, QtWidgets.QTableWidgetItem(str(u.get("balance"))))
                tb = QtWidgets.QPushButton("充值")
                tb.setObjectName("ghost")
                tb.setCursor(QtCore.Qt.PointingHandCursor)
                tb.clicked.connect(lambda _=False, i=u.get("id"), n=(u.get("name") or u.get("id")): self.topup(i, n))
                self.utable.setCellWidget(r, 3, tb)
        elif tag == "acct_sendcode":
            self.getcode_btn.setEnabled(True)
            if d.get("ok"):
                j = d.get("j") or {}
                if j.get("devCode"):
                    self.code_in.setText(str(j["devCode"]))
                    self.bind_msg.setText("开发模式:已自动填入验证码")
                else:
                    self.bind_msg.setText("验证码已发送")
                self._cd = 60
                self._cd_timer.start(1000)
                self.getcode_btn.setText("60s")
                self.getcode_btn.setEnabled(False)
            else:
                self.bind_msg.setText("发送失败:" + str((d.get("j") or {}).get("error") or ""))
        elif tag == "acct_bind":
            if d.get("ok"):
                self.bind_msg.setText("绑定成功 ✓")
                self.code_in.clear()
            else:
                self.bind_msg.setText("绑定失败:" + str(d.get("err") or ""))
        elif tag == "acct_topup":
            if d.get("ok"):
                self.load_users()
                self.load_balance()
            else:
                QtWidgets.QMessageBox.warning(self, "充值失败", str(d.get("err") or ""))
        elif tag == "acct_redeem":
            self.b_redeem.setEnabled(True)
            if d.get("ok"):
                amt = (d.get("j") or {}).get("amount")
                try:
                    amt_s = str(int(amt) if float(amt) == int(amt) else round(float(amt), 2))
                except Exception:
                    amt_s = str(amt)
                self.redeem_in.clear()
                self.redeem_msg.setText("充值成功  +%s 云豆 ✓" % amt_s)
                self.load_balance()
                self.load_ledger()
            else:
                err = (d.get("j") or {}).get("error") or ""
                self.redeem_msg.setText({
                    "code_not_found": "兑换码无效",
                    "code_used": "该兑换码已被使用",
                    "code_void": "该兑换码已作废",
                    "code_empty": "请输入兑换码",
                    "not_authenticated": "请先登录",
                }.get(err, "兑换失败:" + str(err)))
        elif tag == "acct_gencodes":
            self.b_gencodes.setEnabled(True)
            if d.get("ok"):
                codes = d.get("codes") or []
                self.gc_msg.setText("已生成 %d 张兑换码(见弹窗,请复制保存)" % len(codes))
                self._show_codes_dialog(codes, d.get("amount"))
            else:
                self.gc_msg.setText("生成失败:" + str(d.get("err") or ""))


COMIC_TOOL_URL = "http://120.26.194.174"


class ComicToolPage(BasePage):
    def __init__(self):
        super().__init__()
        self.open_btn = QtWidgets.QPushButton("打开漫剧工具")
        self.open_btn.setObjectName("primary")
        self.open_btn.clicked.connect(self.open_comic_tool)
        self.v.addWidget(make_header("漫剧工具", "打开 http://120.26.194.174", [self.open_btn]))
        panel = Panel("漫剧工具", COMIC_TOOL_URL)
        btn = QtWidgets.QPushButton("打开漫剧工具")
        btn.setObjectName("primary")
        btn.setMinimumHeight(44)
        btn.clicked.connect(self.open_comic_tool)
        panel.body.addWidget(btn)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("sub")
        panel.body.addWidget(self.status)
        self.v.addWidget(panel)
        self.v.addStretch()

    def open_comic_tool(self):
        _open_url(COMIC_TOOL_URL)
        self.status.setText("已打开漫剧工具。")


class TabbedWorkspacePage(BasePage):
    """左侧导航的组合工作区:用标签页收拢同类功能,保留原页面逻辑。"""

    nav_aliases = ()

    def __init__(self, tabs):
        super().__init__()
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self._tab_pages = []
        for label, factory in tabs:
            page = factory()
            self._tab_pages.append(page)
            self.tabs.addTab(page, label)
        self.tabs.currentChanged.connect(lambda _i: self._show_current())
        self.v.addWidget(self.tabs, 1)

    def on_show(self):
        self._show_current()

    def _show_current(self):
        page = self.tabs.currentWidget()
        if hasattr(page, "on_show"):
            try:
                page.on_show()
            except Exception as e:
                log("tab page on_show: %s" % e)


class PublishWorkspacePage(TabbedWorkspacePage):
    nav_aliases = ("🎬 素材与发布", "📤 待发布队列")

    def __init__(self):
        super().__init__([
            ("素材库与发布", lambda: PublishPage()),
            ("待发布队列", lambda: PendingPublishPage()),
        ])


class KnowledgeWorkspacePage(TabbedWorkspacePage):
    nav_aliases = ("📁 企业资料", "📚 企业知识库")

    def __init__(self):
        super().__init__([
            ("企业资料", lambda: EnterpriseProfilePage()),
            ("企业知识库", lambda: KnowledgeBasePage()),
        ])


class EnterpriseCenterPage(TabbedWorkspacePage):
    nav_aliases = ("👥 团队成员",)

    def __init__(self):
        super().__init__([
            ("总览", lambda: DashboardPage()),
            ("团队成员", lambda: EnterpriseMembersPage()),
        ])


NAV = [
    ("账号与配置", [
        ("🏢 企业中心", lambda: EnterpriseCenterPage()),
        ("👤 账号矩阵", lambda: AccountsPage()),
        ("💰 账户中心", lambda: AccountPage()),
    ]),
    ("自动化发布", [
        ("🎬 素材发布", lambda: PublishWorkspacePage()),
        ("📚 资料知识库", lambda: KnowledgeWorkspacePage()),
    ]),
    ("内容生产", [
        ("🔎 内容采集", lambda: ContentPage()),
        ("🔬 分解视频", lambda: VideoBreakdownPage()),
        ("🧬 同款替换", lambda: VideoReplacementPage()),
        ("🧩 图文同款", lambda: XhsNoteReplacementPage()),
        ("🛍️ Agent.模式", lambda: ProductGenPage()),
        ("🗂️ 资产库", lambda: AssetLibraryPage()),
        ("🧑 数字人口播", lambda: DigitalHumanPage()),
    ]),
    ("安全与自动化", [
        ("🤖 工作流助手", lambda: AgentChatPage()),
        ("🔀 自动化工作流", lambda: WorkflowPage()),
        ("🛡️ 风控中心", lambda: RiskControlPage()),
        ("✅ 任务中心", lambda: TaskCenterPage()),
    ]),
    ("增长与转化", [
        ("📈 获客中心", lambda: GrowthPage()),
        ("💬 私信 / AI 销售", lambda: DMPage()),
    ]),
]


# ---------- 登录页(影院级电商视频背景 + 玻璃拟态登录卡,仿 comic-tool) ----------

_LOGIN_INPUT_QSS = (
    "QLineEdit{background:rgba(255,255,255,0.055);border:1px solid rgba(255,255,255,0.13);"
    "border-radius:12px;padding:11px 14px;color:#eef1f8;font-size:14px;}"
    "QLineEdit:focus{border:1px solid #8b8ff8;background:rgba(255,255,255,0.09);}")

# 登录页勾选框:暗底玻璃上默认 Qt 勾选框几乎看不见 —— 给清晰边框 + 选中紫色填充 + 白色对勾
_CHECK_ICON = os.path.join(_ASSETS_DIR, "check.png").replace("\\", "/")
EVIL_EYE_LOGIN_PATH = os.path.join(_ASSETS_DIR, "evil_eye_login.png").replace("\\", "/")
_LOGIN_CHECK_QSS = (
    "QCheckBox{color:#c7cee0;font-size:12.5px;background:transparent;spacing:8px;}"
    "QCheckBox::indicator{width:18px;height:18px;border-radius:5px;"
    "border:1.4px solid rgba(255,255,255,0.55);background:rgba(255,255,255,0.10);}"
    "QCheckBox::indicator:hover{border-color:#9aa0f8;background:rgba(139,143,248,0.20);}"
    "QCheckBox::indicator:checked{border:1.4px solid #8b8ff8;"
    "background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #6366f1,stop:1 #8b5cf6);"
    "image:url('%s');}"
    "QCheckBox::indicator:checked:hover{"
    "background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #7679f5,stop:1 #9a6cf8);}"
) % _CHECK_ICON


def _login_ph(le):
    """给玻璃输入框设置柔和的占位符颜色(QSS 不支持 ::placeholder,走 palette)。"""
    pal = le.palette()
    pal.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor(150, 160, 185))
    le.setPalette(pal)


def _dpapi(data, unprotect):
    """Windows DPAPI 加/解密(CryptProtectData/CryptUnprotectData,绑定当前 Windows 用户)。
    拷到别的机器或别的用户下无法解密。非 Windows 或失败返回 None。"""
    if os.name != "nt" or not data:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        buf = ctypes.create_string_buffer(bytes(data), len(data))
        blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        fn = ctypes.windll.crypt32.CryptUnprotectData if unprotect else ctypes.windll.crypt32.CryptProtectData
        if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _secure_encode(s):
    """敏感串(密码/token)落盘前加密:优先 DPAPI(前缀 d:),不可用则退回 base64 遮挡(前缀 b:)。"""
    import base64 as _b64
    if not s:
        return ""
    raw = str(s).encode("utf-8")
    enc = _dpapi(raw, unprotect=False)
    if enc is not None:
        return "d:" + _b64.b64encode(enc).decode("ascii")
    return "b:" + _b64.b64encode(raw).decode("ascii")


def _secure_decode(v):
    import base64 as _b64
    if not v:
        return ""
    try:
        v = str(v)
        if v.startswith("d:"):
            dec = _dpapi(_b64.b64decode(v[2:]), unprotect=True)
            return dec.decode("utf-8") if dec is not None else ""
        if v.startswith("b:"):
            return _b64.b64decode(v[2:]).decode("utf-8")
        return _b64.b64decode(v).decode("utf-8")  # 兼容旧的裸 base64
    except Exception:
        return ""


def _auth_pref_path():
    return os.path.join(data_dir(), "auth.json")


def load_auth_pref():
    """登录记忆:{account, password, remember, autologin, token, org}。密码与 token 均 DPAPI 加密落盘(绑定当前 Windows 用户,拷走无法解密),不可用时退回 base64。"""
    import json as _json
    try:
        p = _auth_pref_path()
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as handle:
                d = _json.load(handle)
            if isinstance(d, dict):
                if d.get("password"):
                    d["password"] = _secure_decode(d["password"])
                if d.get("token"):
                    d["token"] = _secure_decode(d["token"])
                return d
    except Exception:
        pass
    return {}


def save_auth_pref(d):
    try:
        dd = dict(d or {})
        if dd.get("password"):
            dd["password"] = _secure_encode(dd["password"])
        if dd.get("token"):
            dd["token"] = _secure_encode(dd["token"])
        _atomic_write_json(_auth_pref_path(), dd)
    except Exception:
        pass


def clear_auth_autologin():
    """自动登录失效时清掉 token,避免下次卡在无效自动登录(保留记住的账号密码)。"""
    d = load_auth_pref()
    d["token"] = ""
    d["autologin"] = False
    save_auth_pref(d)


class GradientLabel(QtWidgets.QLabel):
    """文字用水平线性渐变填充绘制(仿 comic-tool 标题的 cyan→purple 渐变字)。"""

    def __init__(self, text="", c1="#22d3ee", c2="#a78bfa", parent=None):
        super().__init__(text, parent)
        self._c1 = QtGui.QColor(c1)
        self._c2 = QtGui.QColor(c2)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing)
        g = QtGui.QLinearGradient(0, 0, max(1, self.width()), 0)
        g.setColorAt(0.0, self._c1)
        g.setColorAt(1.0, self._c2)
        p.setPen(QtGui.QPen(QtGui.QBrush(g), 1))
        p.setFont(self.font())
        p.drawText(self.rect(), int(self.alignment()) | int(QtCore.Qt.TextSingleLine), self.text())


class LoginBackground(QtCore.QObject):
    """登录页背景媒体引擎:低分辨率电商产品视频轮播,铺满窗口(cover-fit),带交叉淡入。
    视频经 QVideoSink 解码为 QImage,由 LoginView.paintEvent 作为背景绘制 —— 从而可在其之上
    叠加半透明玻璃卡(真实透出视频)。**事件驱动重绘**(仅在新帧/淡入时请求 update,不跑固定
    30fps 定时器)+ 480p 低码率素材,避免叠加半透明控件时的卡顿。"""

    FADE_MS = 760        # 交叉淡入时长

    def __init__(self, notify=None, parent=None):
        super().__init__(parent)
        self._notify = notify or (lambda: None)   # 请求重绘的回调(事件驱动)
        self.items = self._playlist()
        self.idx = 0
        self._frame = None            # 当前视频最新帧(QImage)
        self._pixcache = {}
        self._fade = 1.0
        self._prev_src = None
        self._started = False
        self.player = None
        self.sink = None
        self._init_player()
        self._fadeanim = QtCore.QVariantAnimation(self)
        self._fadeanim.setStartValue(0.0)
        self._fadeanim.setEndValue(1.0)
        self._fadeanim.setDuration(self.FADE_MS)
        self._fadeanim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._fadeanim.valueChanged.connect(self._set_fade)

    def _playlist(self):
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
        d = os.path.join(base, "assets", "login_bg")
        out = []
        seen = set()

        def add(fn):
            p = os.path.join(d, fn)
            if os.path.isfile(p) and p not in seen:
                seen.add(p)
                poster = os.path.join(d, os.path.splitext(fn)[0] + ".jpg")
                out.append({"path": p, "poster": (poster if os.path.isfile(poster) else None)})
        # 登录页只轮播指定的无水印背景视频；第一条必须是 gen-liquid-lo.mp4。
        for fn in ("gen-liquid-lo.mp4", "car.mp4", "ecom-serum-lo.mp4", "phone.mp4"):
            add(fn)
        return out

    def _init_player(self):
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
            self.sink = QVideoSink(self)
            self.player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._audio.setMuted(True)
            self.player.setAudioOutput(self._audio)
            self.player.setVideoSink(self.sink)
            try:
                self.player.setLoops(1)
            except Exception:
                pass
            try:
                self.player.mediaStatusChanged.connect(self._on_media_status)
            except Exception:
                pass
            self.sink.videoFrameChanged.connect(self._on_frame)
        except Exception:
            self.player = None
            self.sink = None

    def _set_fade(self, v):
        try:
            self._fade = float(v)
        except Exception:
            self._fade = 1.0
        self._notify()   # 淡入过程中请求重绘

    def _pixmap(self, path):
        if not path:
            return None
        pm = self._pixcache.get(path)
        if pm is None:
            pm = QtGui.QPixmap(path)
            self._pixcache[path] = pm
        return pm if (pm is not None and not pm.isNull()) else None

    def _live_src(self):
        if not self.items:
            return None
        it = self.items[self.idx]
        return self._frame if self._frame is not None else self._pixmap(it.get("poster"))

    def start(self):
        if not self.items:
            return
        if self._started:
            # 从最小化 / 隐藏恢复:续播 + 恢复淡入
            if self.player:
                try:
                    self.player.play()
                except Exception:
                    pass
            if self._fadeanim.state() == QtCore.QAbstractAnimation.Paused:
                self._fadeanim.resume()
            self._notify()
            return
        self._started = True
        self._go(0, first=True)

    def pause(self):
        if self.player:
            try:
                self.player.pause()
            except Exception:
                pass
        if self._fadeanim.state() == QtCore.QAbstractAnimation.Running:
            self._fadeanim.pause()

    def stop(self):
        self._fadeanim.stop()
        if self.player:
            try:
                self.player.stop()
            except Exception:
                pass

    def release(self):
        """登录成功后彻底释放媒体管线与缓存(避免会话期常驻 ~10MB 图像与解码器)。"""
        self.stop()
        try:
            if self.sink is not None:
                self.sink.videoFrameChanged.disconnect(self._on_frame)
        except Exception:
            pass
        try:
            if self.player is not None:
                self.player.mediaStatusChanged.disconnect(self._on_media_status)
        except Exception:
            pass
        if self.player is not None:
            try:
                self.player.setSource(QtCore.QUrl())
            except Exception:
                pass
            try:
                self.player.setVideoSink(None)
            except Exception:
                pass
            try:
                self.player.deleteLater()
            except Exception:
                pass
        self.player = None
        self.sink = None
        self._frame = None
        self._prev_src = None
        self._pixcache.clear()

    def _advance(self):
        if len(self.items) > 1:
            self._go((self.idx + 1) % len(self.items))
        elif self.items:
            self._go(self.idx)

    def _go(self, i, first=False):
        if not self.items:
            return
        self._prev_src = None if first else self._live_src()
        self.idx = i % len(self.items)
        self._frame = None
        self._fade = 0.0
        it = self.items[self.idx]
        if self.player is not None:
            try:
                self.player.stop()
                self.player.setSource(QtCore.QUrl.fromLocalFile(it["path"]))
                self.player.play()
            except Exception:
                pass
        self._fadeanim.stop()
        self._fadeanim.start()
        self._notify()

    def _on_media_status(self, st):
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            if st == QMediaPlayer.MediaStatus.EndOfMedia:
                self._advance()
        except Exception:
            pass

    def _on_frame(self, frame):
        try:
            if not frame.isValid():
                return
            img = frame.toImage()
            if not img.isNull():
                self._frame = img
                self._notify()   # 新帧到达才请求重绘(事件驱动,省 CPU)
        except Exception:
            pass

    @staticmethod
    def _cover(p, rect, src, opacity):
        if src is None:
            return
        iw = src.width()
        ih = src.height()
        if iw <= 0 or ih <= 0:
            return
        rw = rect.width()
        rh = rect.height()
        sc = max(rw / iw, rh / ih)
        dw = iw * sc
        dh = ih * sc
        dx = rect.x() + (rw - dw) / 2.0
        dy = rect.y() + (rh - dh) / 2.0
        target = QtCore.QRectF(dx, dy, dw, dh)
        p.setOpacity(max(0.0, min(1.0, opacity)))
        if isinstance(src, QtGui.QImage):
            p.drawImage(target, src)
        else:
            p.drawPixmap(target, src, QtCore.QRectF(0, 0, iw, ih))
        p.setOpacity(1.0)

    def paint(self, p, rect):
        p.fillRect(rect, QtGui.QColor("#050914"))
        if not self.items:
            return
        it = self.items[self.idx]
        cur = self._frame if self._frame is not None else self._pixmap(it.get("poster"))
        fading = self._fade < 0.999
        if fading and self._prev_src is not None:
            self._cover(p, rect, self._prev_src, 1.0)
        self._cover(p, rect, cur, self._fade if fading else 1.0)


class LegalAgreementDialog(QtWidgets.QDialog):
    def __init__(self, initial_kind="terms", parent=None):
        super().__init__(parent)
        self.setWindowTitle("用户协议与隐私政策")
        self.setModal(True)
        self.resize(820, 680)
        self.setMinimumSize(660, 520)
        self.setStyleSheet(
            "QDialog{background:#0b1020;color:#e7ecf8;}"
            "QTabWidget::pane{border:1px solid #28324a;border-radius:6px;background:#0f1628;}"
            "QTabBar::tab{background:#151d31;color:#aeb9d3;padding:9px 18px;border:1px solid #28324a;}"
            "QTabBar::tab:selected{background:#273254;color:#ffffff;border-color:#6978e8;}"
            "QTextBrowser{background:#0f1628;color:#dbe3f5;border:0;padding:14px;selection-background-color:#5565c9;}"
            "QLabel{color:#99a8c5;}"
            "QPushButton{min-width:82px;min-height:34px;background:#5967d8;color:white;border:0;border-radius:6px;font-weight:700;}"
            "QPushButton:hover{background:#6c79e8;}"
        )
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        meta = QtWidgets.QLabel(
            "用户协议 v%s  |  隐私政策 v%s  |  生效日期 %s"
            % (LEGAL_TERMS_VERSION, LEGAL_PRIVACY_VERSION, LEGAL_EFFECTIVE_DATE)
        )
        meta.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(meta)

        self.tabs = QtWidgets.QTabWidget()
        for kind, title in (("terms", "用户协议"), ("privacy", "隐私政策")):
            browser = QtWidgets.QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setMarkdown(_load_legal_document(kind))
            browser.document().setDefaultStyleSheet(
                "body{font-family:'PingFang SC','Microsoft YaHei',sans-serif;font-size:14px;line-height:1.75;}"
                "h1{font-size:24px;color:#ffffff;} h2{font-size:18px;color:#cdd6ff;margin-top:22px;}"
                "h3{font-size:15px;color:#b8c4e8;} a{color:#8da2ff;}"
            )
            self.tabs.addTab(browser, title)
        self.tabs.setCurrentIndex(1 if str(initial_kind) == "privacy" else 0)
        layout.addWidget(self.tabs, 1)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.button(QtWidgets.QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


_ENTERPRISE_INVITE_CODE_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def normalize_enterprise_invite_code(value):
    raw = str(value or "").strip()
    if "://" in raw:
        parsed = urlparse(raw)
        raw = str((parse_qs(parsed.query).get("token") or [""])[0]).strip()
    return raw.lower() if _ENTERPRISE_INVITE_CODE_RE.fullmatch(raw) else ""


def enterprise_invite_error_message(error):
    return {
        "missing_token": "请输入有效邀请码",
        "invalid_invite": "邀请码无效，请检查后重试",
        "invite_expired": "邀请码已过期，请联系管理员重新创建",
        "invite_revoked": "邀请已撤销，请联系管理员",
        "invite_accepted": "邀请已使用，请直接登录或联系管理员",
        "organization_inactive": "企业当前不可加入，请联系管理员",
        "existing_user_login_required": "该账号已存在，请输入当前密码",
        "missing_name": "请填写姓名",
        "missing_identifier": "请填写手机号或邮箱",
        "password_too_short": "密码至少 8 位",
    }.get(str(error or ""), "加入企业失败，请稍后重试")


class LoginView(QtWidgets.QWidget):
    LOGIN_SUCCESS_TRANSITION_MS = 900
    LOGIN_SUCCESS_FULL_SCREEN_SCALE = 1.0

    def __init__(self, on_success):
        super().__init__()
        self.on_success = on_success
        self.setObjectName("loginRoot")
        self._mode = "login"
        self._cd = 0
        self._hero = None
        self._card = None
        self._success_overlay = None
        self._success_eye = None
        self._success_effect = None
        self._success_anim = None
        self._success_info = None
        # 背景媒体引擎(低分辨率电商产品视频轮播)。事件驱动:引擎在新帧/淡入时回调 _bg_update
        # 请求重绘 —— 不跑固定 30fps 定时器,省 CPU、避免叠加半透明控件时卡顿。
        self.bg = LoginBackground(self._bg_update, self)
        self._build_ui()
        BRIDGE.logged_in.connect(self._done)
        BRIDGE.payload.connect(self._on_payload)
        self._cd_timer = QtCore.QTimer(self)
        self._cd_timer.timeout.connect(self._tick)

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(52, 42, 52, 42)
        root.setSpacing(0)
        root.addStretch(1)
        content = QtWidgets.QWidget()
        content.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        row = QtWidgets.QHBoxLayout(content)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(46)
        self._hero = self._build_hero()
        self._hero.setVisible(self.width() >= 940)
        self._card = self._build_card()
        row.addWidget(self._hero)
        row.addWidget(self._card)
        root.addWidget(content, 0, QtCore.Qt.AlignCenter)
        root.addStretch(1)
        self._build_success_overlay()
        wire_animations(self)

    def _build_hero(self):
        hero = QtWidgets.QWidget()
        hero.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        hero.setFixedWidth(520)
        hv = QtWidgets.QVBoxLayout(hero)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(0)
        hv.addStretch(1)

        brow = QtWidgets.QHBoxLayout()
        brow.setSpacing(12)
        chip = QtWidgets.QLabel()
        chip.setFixedSize(46, 46)
        chip.setAlignment(QtCore.Qt.AlignCenter)
        chip.setStyleSheet("background:transparent;")
        mark_pm = QtGui.QPixmap(YUNLING_MARK_PATH)
        if not mark_pm.isNull():
            chip.setPixmap(mark_pm.scaled(46, 46, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        wm = QtWidgets.QVBoxLayout()
        wm.setSpacing(1)
        wmt = QtWidgets.QLabel("云灵星图")
        wmt.setStyleSheet("color:#f4f7ff;font-size:20px;font-weight:800;background:transparent;")
        wms = QtWidgets.QLabel("AI爆款复刻平台")
        wms.setStyleSheet("color:rgba(180,190,215,0.72);font-size:11px;font-weight:600;"
                          "background:transparent;")
        wm.addWidget(wmt)
        wm.addWidget(wms)
        brow.addWidget(chip)
        brow.addLayout(wm)
        brow.addStretch()
        hv.addLayout(brow)
        hv.addSpacing(30)

        pill = QtWidgets.QLabel("✦  多平台矩阵 · 真机真 IP · 一键成片")
        pill.setStyleSheet("background:rgba(34,211,238,0.10);border:1px solid rgba(34,211,238,0.32);"
                           "border-radius:15px;color:#7de3f4;font-size:12.5px;font-weight:600;padding:7px 15px;")
        pill.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        hv.addWidget(pill, 0, QtCore.Qt.AlignLeft)
        hv.addSpacing(22)

        h1 = QtWidgets.QLabel("从选题到成片")
        h1.setStyleSheet("color:#ffffff;background:transparent;")
        f1 = QtGui.QFont()
        f1.setPixelSize(46)
        f1.setWeight(QtGui.QFont.Black)
        h1.setFont(f1)
        hv.addWidget(h1, 0, QtCore.Qt.AlignLeft)

        h2 = GradientLabel("一个人就是一支运营团队", "#22d3ee", "#a78bfa")
        f2 = QtGui.QFont()
        f2.setPixelSize(46)
        f2.setWeight(QtGui.QFont.Black)
        h2.setFont(f2)
        h2.setFixedHeight(64)
        hv.addWidget(h2, 0, QtCore.Qt.AlignLeft)
        hv.addSpacing(18)

        st = QtWidgets.QLabel("抖音 · 小红书多账号托管,AI 一键生成商品图与短视频;\n真实浏览器 · 真实住宅 IP,批量发布不惧封号。")
        st.setStyleSheet("color:rgba(203,213,225,0.88);font-size:15px;background:transparent;")
        st.setWordWrap(True)
        st.setFixedWidth(470)
        hv.addWidget(st, 0, QtCore.Qt.AlignLeft)
        hv.addSpacing(26)

        frow = QtWidgets.QHBoxLayout()
        frow.setSpacing(10)
        for t in ("🛍️  Agent.模式", "🎞️  混剪短视频", "🤖  自动化工作流"):
            fc = QtWidgets.QLabel(t)
            fc.setStyleSheet("background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);"
                             "border-radius:10px;color:#dfe5f2;font-size:12.5px;padding:8px 13px;")
            frow.addWidget(fc)
        frow.addStretch()
        hv.addLayout(frow)
        hv.addStretch(1)
        return hero

    def _build_success_overlay(self):
        overlay = QtWidgets.QWidget(self)
        overlay.setObjectName("loginSuccessOverlay")
        overlay.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        overlay.setStyleSheet("#loginSuccessOverlay{background:rgba(0,0,0,166);}")
        overlay.hide()

        eye = QtWidgets.QLabel(overlay)
        eye.setAlignment(QtCore.Qt.AlignCenter)
        eye.setScaledContents(True)
        eye.setStyleSheet("background:transparent;")
        eye_pm = QtGui.QPixmap(EVIL_EYE_LOGIN_PATH)
        if not eye_pm.isNull():
            eye.setPixmap(eye_pm)

        effect = QtWidgets.QGraphicsOpacityEffect(overlay)
        effect.setOpacity(0.0)
        overlay.setGraphicsEffect(effect)

        self._success_overlay = overlay
        self._success_eye = eye
        self._success_effect = effect
        self._layout_success_overlay(0.58)

    def _success_eye_rect(self, scale):
        scale = float(scale)
        if scale >= 1.0:
            return self.rect()
        base = min(self.width(), self.height())
        side = int(max(220, base * scale))
        side = min(side, max(240, self.width()), max(240, self.height()))
        return QtCore.QRect((self.width() - side) // 2, (self.height() - side) // 2, side, side)

    def _layout_success_overlay(self, scale=None):
        if self._success_overlay is None or self._success_eye is None:
            return
        self._success_overlay.setGeometry(self.rect())
        self._success_eye.setGeometry(self._success_eye_rect(0.70 if scale is None else scale))
        self._success_overlay.raise_()

    def _build_card(self):
        card = QtWidgets.QFrame()
        card.setObjectName("glassCard")
        card.setFixedWidth(392)
        card.setStyleSheet("#glassCard{background:rgba(15,21,34,0.66);"
                           "border:1px solid rgba(255,255,255,0.11);border-radius:22px;}")
        cv = QtWidgets.QVBoxLayout(card)
        self._card_layout = cv
        cv.setContentsMargins(32, 30, 32, 28)
        cv.setSpacing(13)
        title = QtWidgets.QLabel("登录 / 注册")
        title.setStyleSheet("color:#f4f7ff;font-size:21px;font-weight:800;background:transparent;")
        self.sub = QtWidgets.QLabel("未注册手机号用验证码登录即自动创建账号")
        self.sub.setStyleSheet("color:rgba(160,172,196,0.9);font-size:12.5px;background:transparent;")
        cv.addWidget(title)
        cv.addWidget(self.sub)
        cv.addSpacing(4)
        # 顶部切换:登录 / 注册 / 加入企业
        tabrow = QtWidgets.QHBoxLayout()
        tabrow.setSpacing(8)
        self.tab_login = QtWidgets.QPushButton("登录")
        self.tab_reg = QtWidgets.QPushButton("注册")
        self.tab_invite = QtWidgets.QPushButton("加入企业")
        for tb in (self.tab_login, self.tab_reg, self.tab_invite):
            tb.setCursor(QtCore.Qt.PointingHandCursor)
            tb.setMinimumHeight(34)
        self.tab_login.clicked.connect(lambda: self._set_mode("login"))
        self.tab_reg.clicked.connect(lambda: self._set_mode("register"))
        self.tab_invite.clicked.connect(lambda: self._set_mode("invite"))
        tabrow.addWidget(self.tab_login, 1)
        tabrow.addWidget(self.tab_reg, 1)
        tabrow.addWidget(self.tab_invite, 1)
        cv.addLayout(tabrow)
        self.invite_code_row = QtWidgets.QWidget()
        self.invite_code_row.setStyleSheet("background:transparent;")
        invite_code_layout = QtWidgets.QHBoxLayout(self.invite_code_row)
        invite_code_layout.setContentsMargins(0, 0, 0, 0)
        invite_code_layout.setSpacing(9)
        self.invite_code_in = QtWidgets.QLineEdit()
        self.invite_code_in.setPlaceholderText("邀请码")
        self.invite_code_in.setStyleSheet(_LOGIN_INPUT_QSS)
        self.invite_code_in.setMinimumHeight(46)
        _login_ph(self.invite_code_in)
        self.invite_code_in.returnPressed.connect(self.verify_enterprise_invite)
        self.invite_verify_btn = QtWidgets.QPushButton("校验")
        self.invite_verify_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.invite_verify_btn.setFixedSize(82, 46)
        self.invite_verify_btn.clicked.connect(self.verify_enterprise_invite)
        invite_code_layout.addWidget(self.invite_code_in, 1)
        invite_code_layout.addWidget(self.invite_verify_btn)
        cv.addWidget(self.invite_code_row)
        self.invite_org = QtWidgets.QLabel("")
        self.invite_org.setWordWrap(True)
        self.invite_org.setStyleSheet("color:#aeb6cc;font-size:12px;background:transparent;")
        cv.addWidget(self.invite_org)
        self.invite_name_in = QtWidgets.QLineEdit()
        self.invite_name_in.setPlaceholderText("姓名")
        self.invite_name_in.setStyleSheet(_LOGIN_INPUT_QSS)
        self.invite_name_in.setMinimumHeight(46)
        _login_ph(self.invite_name_in)
        cv.addWidget(self.invite_name_in)
        # 手机号 / 账号
        self.phone_in = QtWidgets.QLineEdit()
        self.phone_in.setPlaceholderText("手机号 / 用户名")
        self.phone_in.setMaxLength(64)
        self.phone_in.setStyleSheet(_LOGIN_INPUT_QSS)
        self.phone_in.setMinimumHeight(46)
        _login_ph(self.phone_in)
        self.phone_in.textChanged.connect(self._sync_login_code_ui)
        cv.addWidget(self.phone_in)
        self.invite_email_in = QtWidgets.QLineEdit()
        self.invite_email_in.setPlaceholderText("邮箱（手机号和邮箱至少填写一项）")
        self.invite_email_in.setStyleSheet(_LOGIN_INPUT_QSS)
        self.invite_email_in.setMinimumHeight(46)
        _login_ph(self.invite_email_in)
        cv.addWidget(self.invite_email_in)
        # 密码
        self.pw_in = QtWidgets.QLineEdit()
        self.pw_in.setPlaceholderText("密码")
        self.pw_in.setEchoMode(QtWidgets.QLineEdit.Password)
        self.pw_in.setStyleSheet(_LOGIN_INPUT_QSS)
        self.pw_in.setMinimumHeight(46)
        _login_ph(self.pw_in)
        self.pw_in.returnPressed.connect(self.do_login)
        cv.addWidget(self.pw_in)
        # 确认密码(仅注册:密码需输入两次一致)
        self.pw2_in = QtWidgets.QLineEdit()
        self.pw2_in.setPlaceholderText("确认密码")
        self.pw2_in.setEchoMode(QtWidgets.QLineEdit.Password)
        self.pw2_in.setStyleSheet(_LOGIN_INPUT_QSS)
        self.pw2_in.setMinimumHeight(46)
        _login_ph(self.pw2_in)
        self.pw2_in.returnPressed.connect(self.do_login)
        self.pw2_in.setVisible(False)
        cv.addWidget(self.pw2_in)
        self.invite_current_pw_in = QtWidgets.QLineEdit()
        self.invite_current_pw_in.setPlaceholderText("已有账号的当前密码")
        self.invite_current_pw_in.setEchoMode(QtWidgets.QLineEdit.Password)
        self.invite_current_pw_in.setStyleSheet(_LOGIN_INPUT_QSS)
        self.invite_current_pw_in.setMinimumHeight(46)
        _login_ph(self.invite_current_pw_in)
        self.invite_current_pw_in.returnPressed.connect(self.do_login)
        self.invite_current_pw_in.hide()
        cv.addWidget(self.invite_current_pw_in)
        self._invite_verified_code = ""
        self._invite_request_generation = 0
        # 手机验证码(登录=账号密码后二次验证 2FA / 注册=验证手机号)
        self.code_row = QtWidgets.QWidget()
        self.code_row.setStyleSheet("background:transparent;")
        crl = QtWidgets.QHBoxLayout(self.code_row)
        crl.setContentsMargins(0, 0, 0, 0)
        crl.setSpacing(9)
        self.code_in = QtWidgets.QLineEdit()
        self.code_in.setPlaceholderText("短信验证码")
        self.code_in.setMaxLength(6)
        self.code_in.setStyleSheet(_LOGIN_INPUT_QSS)
        self.code_in.setMinimumHeight(46)
        _login_ph(self.code_in)
        self.code_in.returnPressed.connect(self.do_login)
        self.getcode_btn = QtWidgets.QPushButton("获取验证码")
        self.getcode_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.getcode_btn.setFixedSize(112, 46)
        self.getcode_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.17);"
            "color:#cdd6ea;border-radius:12px;font-size:12.5px;font-weight:600;}"
            "QPushButton:hover{border:1px solid #8b8ff8;color:#ffffff;}"
            "QPushButton:disabled{color:#6b7488;border:1px solid rgba(255,255,255,0.08);}")
        self.getcode_btn.clicked.connect(self.send_code)
        crl.addWidget(self.code_in, 1)
        crl.addWidget(self.getcode_btn)
        cv.addWidget(self.code_row)
        # 记住密码 / 自动登录(仅登录)
        self.opt_row = QtWidgets.QWidget()
        self.opt_row.setStyleSheet("background:transparent;")
        orl = QtWidgets.QHBoxLayout(self.opt_row)
        orl.setContentsMargins(2, 0, 0, 0)
        orl.setSpacing(18)
        self.remember_cb = QtWidgets.QCheckBox("记住密码")
        self.autologin_cb = QtWidgets.QCheckBox("自动登录")
        self.remember_cb.setToolTip("下次打开自动填入账号和密码(仍需输入短信验证码)")
        self.autologin_cb.setToolTip("登录状态有效期内(约 7 天)下次打开免登录直接进入;过期后需重新验证")
        for c in (self.remember_cb, self.autologin_cb):
            c.setCursor(QtCore.Qt.PointingHandCursor)
            c.setStyleSheet(_LOGIN_CHECK_QSS)
        # 不变式:自动登录 ⟹ 记住密码。勾自动登录强制勾记住;取消记住则同时取消自动登录。
        self.autologin_cb.toggled.connect(lambda on: self.remember_cb.setChecked(True) if on else None)
        self.remember_cb.toggled.connect(lambda on: None if on else self.autologin_cb.setChecked(False))
        orl.addWidget(self.remember_cb)
        orl.addWidget(self.autologin_cb)
        orl.addStretch()
        self.opt_row.setVisible(False)
        cv.addWidget(self.opt_row)
        self.btn = QtWidgets.QPushButton("登 录")
        self.btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn.setMinimumHeight(48)
        self.btn.setStyleSheet(
            "QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #6366f1,stop:1 #8b5cf6);"
            "color:#ffffff;border:0;border-radius:13px;font-size:15px;font-weight:800;}"
            "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #7679f5,stop:1 #9a6cf8);}"
            "QPushButton:disabled{background:rgba(120,126,160,0.35);color:#9298b4;}")
        self.btn.clicked.connect(self.do_login)
        cv.addSpacing(2)
        cv.addWidget(self.btn)
        arow = QtWidgets.QHBoxLayout()
        arow.setContentsMargins(2, 0, 0, 0)
        arow.setSpacing(7)
        self.agree = QtWidgets.QCheckBox()
        self.agree.setCursor(QtCore.Qt.PointingHandCursor)
        self.agree.setStyleSheet(_LOGIN_CHECK_QSS)
        alab = QtWidgets.QLabel('<span style="color:rgba(170,180,205,0.9);">我已阅读并同意</span>'
                                '<a href="terms" style="color:#8b8ff8;text-decoration:none;">《用户协议》</a>'
                                '<a href="privacy" style="color:#8b8ff8;text-decoration:none;">《隐私政策》</a>')
        alab.setStyleSheet("font-size:12px;background:transparent;")
        alab.setOpenExternalLinks(False)
        alab.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        alab.setCursor(QtCore.Qt.PointingHandCursor)
        alab.linkActivated.connect(self._show_legal_document)
        arow.addWidget(self.agree)
        arow.addWidget(alab)
        arow.addStretch()
        cv.addLayout(arow)
        self.msg = QtWidgets.QLabel("")
        self.msg.setAlignment(QtCore.Qt.AlignCenter)
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color:#aeb6cc;font-size:12px;background:transparent;")
        cv.addWidget(self.msg)
        self._set_mode("login")
        return card

    def _show_legal_document(self, kind):
        try:
            LegalAgreementDialog(str(kind or "terms"), self).exec()
        except Exception as exc:
            error_id = "err-" + uuid.uuid4().hex[:16]
            json_log(
                _CLIENT_JSON_LOGGER,
                "legal_document_open_failed",
                errorId=error_id,
                exc=exc,
                document=str(kind or ""),
            )
            self._set_msg("协议文档无法打开（%s）" % error_id, "err")

    def _style_tab(self, btn, on):
        if on:
            btn.setStyleSheet("QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #6366f1,stop:1 #8b5cf6);"
                              "color:#fff;border:0;border-radius:10px;font-size:13px;font-weight:700;}")
        else:
            btn.setStyleSheet("QPushButton{background:rgba(255,255,255,0.05);color:#aeb6cc;"
                              "border:1px solid rgba(255,255,255,0.12);border-radius:10px;font-size:13px;}"
                              "QPushButton:hover{color:#fff;border-color:#8b8ff8;}")

    def _set_mode(self, m):
        # login=账号登录, register=手机注册, invite=邀请码加入企业。
        previous_mode = self._mode
        self._mode = m
        is_login = m == "login"
        is_reg = m == "register"
        is_invite = m == "invite"
        if previous_mode != m:
            self._invite_request_generation += 1
            self._invite_verified_code = ""
            self.invite_org.clear()
            self._set_invite_submission_enabled(True)
            self.btn.setEnabled(True)
        self._style_tab(self.tab_login, is_login)
        self._style_tab(self.tab_reg, is_reg)
        self._style_tab(self.tab_invite, is_invite)
        if is_invite:
            self.phone_in.setPlaceholderText("手机号（与邮箱至少填写一项）")
            self.phone_in.setMaxLength(40)
        else:
            self.phone_in.setPlaceholderText("手机号" if is_reg else "手机号 / 用户名")
            self.phone_in.setMaxLength(11 if is_reg else 64)
        self.pw_in.setVisible(True)
        self.pw_in.setPlaceholderText("设置密码(至少 8 位)" if is_invite else ("设置密码(至少 6 位)" if is_reg else "密码"))
        self.pw2_in.setVisible(is_reg or is_invite)
        if is_invite and previous_mode != "invite":
            self.pw_in.clear()
            self.pw2_in.clear()
        if not (is_reg or is_invite):
            self.pw2_in.clear()
        self.invite_code_row.setVisible(is_invite)
        self.invite_org.setVisible(is_invite)
        self.invite_name_in.setVisible(is_invite)
        self.invite_email_in.setVisible(is_invite)
        if not is_invite:
            self.invite_current_pw_in.clear()
        self.invite_current_pw_in.setVisible(False)
        self.code_row.setVisible(not is_invite)
        self.opt_row.setVisible(is_login)
        self.btn.setText("加入企业" if is_invite else ("注 册" if is_reg else "登 录"))
        self.sub.setText("校验邀请码后填写账号信息" if is_invite else (
            "手机号验证 + 设置密码,即可开始使用" if is_reg
            else "手机号登录需验证码;用户名登录只需密码"
        ))
        if is_invite:
            self._card_layout.setContentsMargins(28, 20, 28, 20)
            self._card_layout.setSpacing(8)
        else:
            self._card_layout.setContentsMargins(32, 30, 32, 28)
            self._card_layout.setSpacing(13)
        # 切换模式:清掉上一模式的验证码(登录/注册码 scene 不通用)并复位倒计时,避免误用旧码
        self.code_in.clear()
        self._cd = 0
        if getattr(self, "_cd_timer", None) is not None:
            self._cd_timer.stop()
        self.getcode_btn.setText("获取验证码")
        self.getcode_btn.setEnabled(True)
        self._set_msg("")
        if is_login:
            self._prefill_remembered()
        self._sync_login_code_ui()

    def _sync_login_code_ui(self):
        if not hasattr(self, "code_row"):
            return
        need_code = self._mode != "invite" and (
            self._mode == "register" or login_needs_phone_code(self.phone_in.text().strip())
        )
        self.code_row.setVisible(need_code)
        if not need_code:
            self.code_in.clear()

    def _prefill_remembered(self):
        pref = load_auth_pref()
        if pref.get("remember"):
            # 只回填空字段,避免切换模式时覆盖用户刚输入的内容
            if pref.get("account") and not self.phone_in.text().strip():
                self.phone_in.setText(pref.get("account"))
            if pref.get("password") and not self.pw_in.text():
                self.pw_in.setText(pref.get("password"))
            self.remember_cb.setChecked(True)
            self.autologin_cb.setChecked(bool(pref.get("autologin")))

    def _set_msg(self, text, kind="info"):
        """按状态给提示上色:错误=红,成功=绿,普通=灰(修复成功/失败同色难分辨)。"""
        color = {"err": "#f87171", "ok": "#34d399", "info": "#aeb6cc"}.get(kind, "#aeb6cc")
        self.msg.setStyleSheet("color:%s;font-size:12px;background:transparent;" % color)
        self.msg.setText(text)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 窄屏隐藏左侧标语,让登录卡居中(隐藏的控件在布局中占 0 宽)
        if self._hero is not None:
            self._hero.setVisible(self.width() >= 940)
        self._layout_success_overlay()

    def _bg_update(self):
        # 引擎回调:仅在可见时请求重绘(Qt 会合并多次 update 为一次 paint)
        if self.isVisible():
            self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self.bg.start()
        if not getattr(self, "_shown_once", False):
            self._shown_once = True
            fade_in(self, dur=340)

    def hideEvent(self, e):
        super().hideEvent(e)
        self.bg.pause()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        r = self.rect()
        w = r.width()
        h = r.height()
        # 背景:低分辨率电商产品视频(cover 铺满 + 交叉淡入)
        self.bg.paint(p, r)
        # 1) 整体压暗
        p.fillRect(r, QtGui.QColor(4, 8, 20, 78))
        # 2) 左侧文案区加强压暗:标语/副标题都在左,视频亮帧下也保证可读(修复对比度不足)
        gl = QtGui.QLinearGradient(0, 0, w, 0)
        gl.setColorAt(0.0, QtGui.QColor(3, 7, 18, 150))
        gl.setColorAt(0.42, QtGui.QColor(3, 7, 18, 20))
        gl.setColorAt(1.0, QtGui.QColor(3, 7, 18, 0))
        p.fillRect(r, QtGui.QBrush(gl))
        # 3) 右侧登录卡区压暗
        gr = QtGui.QLinearGradient(0, 0, w, 0)
        gr.setColorAt(0.0, QtGui.QColor(4, 8, 20, 0))
        gr.setColorAt(0.55, QtGui.QColor(4, 8, 20, 24))
        gr.setColorAt(1.0, QtGui.QColor(4, 8, 20, 150))
        p.fillRect(r, QtGui.QBrush(gr))
        # 4) 纵向影院暗角
        gv = QtGui.QLinearGradient(0, 0, 0, h)
        gv.setColorAt(0.0, QtGui.QColor(4, 8, 20, 70))
        gv.setColorAt(0.45, QtGui.QColor(0, 0, 0, 0))
        gv.setColorAt(1.0, QtGui.QColor(4, 8, 20, 132))
        p.fillRect(r, QtGui.QBrush(gv))
        # 5) 青色辉光(呼应品牌渐变)
        rg = QtGui.QRadialGradient(w * 0.28, h * 0.30, max(w, h) * 0.5)
        rg.setColorAt(0.0, QtGui.QColor(34, 211, 238, 30))
        rg.setColorAt(1.0, QtGui.QColor(34, 211, 238, 0))
        p.fillRect(r, QtGui.QBrush(rg))
        p.end()

    def _set_invite_submission_enabled(self, enabled):
        for widget in (
            self.tab_login, self.tab_reg, self.tab_invite, self.invite_code_in,
            self.invite_verify_btn, self.invite_name_in, self.phone_in,
            self.invite_email_in, self.pw_in, self.pw2_in,
            self.invite_current_pw_in, self.agree,
        ):
            widget.setEnabled(bool(enabled))

    def verify_enterprise_invite(self):
        if not self.btn.isEnabled():
            return
        code = normalize_enterprise_invite_code(self.invite_code_in.text())
        if not code:
            self._invite_verified_code = ""
            self.invite_org.clear()
            self._set_msg("邀请码无效，请检查后重试", "err")
            return
        self._invite_request_generation += 1
        request_generation = self._invite_request_generation
        self.invite_verify_btn.setEnabled(False)
        self._set_msg("正在校验邀请码…", "info")

        def work():
            status, response = api("POST", "/api/enterprise/invites/verify", {"token": code})
            BRIDGE.payload.emit("login_invite_verify", {
                "httpStatus": status,
                "response": response if isinstance(response, dict) else {},
                "code": code,
                "requestGeneration": request_generation,
            })

        run_bg(work)

    def submit_enterprise_invite(self):
        code = self._invite_verified_code
        if not code or normalize_enterprise_invite_code(self.invite_code_in.text()) != code:
            self._invite_verified_code = ""
            self._set_msg("请先校验邀请码", "err")
            return
        name = self.invite_name_in.text().strip()
        phone = self.phone_in.text().strip()
        email = self.invite_email_in.text().strip()
        password = self.pw_in.text()
        if not name or not (phone or email):
            self._set_msg("请填写姓名及手机号或邮箱", "err")
            return
        if len(password) < 8:
            self._set_msg("密码至少 8 位", "err")
            return
        if self.pw2_in.text() != password:
            self._set_msg("两次输入的密码不一致", "err")
            return
        self._set_invite_submission_enabled(False)
        self.btn.setEnabled(False)
        self._set_msg("正在加入企业…", "info")
        self._invite_request_generation += 1
        request_generation = self._invite_request_generation
        body = {
            "token": code,
            "name": name,
            "phone": phone,
            "email": email,
            "password": password,
            "currentPassword": self.invite_current_pw_in.text(),
        }

        def work():
            status, response = api("POST", "/api/enterprise/invites/accept", body)
            BRIDGE.payload.emit("login_invite_accept", {
                "httpStatus": status,
                "response": response if isinstance(response, dict) else {},
                "requestGeneration": request_generation,
                "code": code,
            })

        run_bg(work)

    def send_code(self):
        phone = self.phone_in.text().strip()
        if self._mode == "login" and not login_needs_phone_code(phone):
            self._set_msg("用户名登录无需验证码", "info")
            return
        if not (phone.isdigit() and len(phone) == 11):
            self._set_msg("请输入 11 位手机号", "err")
            return
        if self._cd > 0:
            return
        self.getcode_btn.setEnabled(False)
        self._set_msg("发送中…", "info")
        scene = "register" if self._mode == "register" else "login"

        def work():
            code, j = api("POST", "/api/auth/send-code", {"phone": phone, "scene": scene})
            BRIDGE.payload.emit("login_sendcode", {"ok": bool(isinstance(j, dict) and j.get("ok")), "j": j or {}})
        run_bg(work)

    def _on_payload(self, tag, d):
        if tag == "autologin_failed":
            # 自动登录失效:恢复登录页可用,回填账号密码
            self.btn.setEnabled(True)
            for w in (self.phone_in, self.pw_in, self.code_in):
                w.setEnabled(True)
            try:
                self._set_mode("login")   # 内部已复位验证码/倒计时并回填账号密码
            except Exception:
                pass
            self._set_msg("登录已过期,请重新获取验证码后登录", "err")
            return
        if tag == "login_invite_verify":
            d = d or {}
            if self._mode != "invite" or d.get("requestGeneration") != self._invite_request_generation:
                return
            self.invite_verify_btn.setEnabled(True)
            response = d.get("response") if isinstance(d.get("response"), dict) else {}
            code = str(d.get("code") or "")
            if code != normalize_enterprise_invite_code(self.invite_code_in.text()):
                self._invite_verified_code = ""
                self.invite_org.clear()
                self._set_msg("邀请码已变更，请重新校验", "err")
                return
            if response.get("ok"):
                invite = response.get("invite") if isinstance(response.get("invite"), dict) else {}
                organization = response.get("organization") if isinstance(response.get("organization"), dict) else {}
                self._invite_verified_code = code
                self.invite_name_in.setText(str(invite.get("recipientName") or ""))
                self.phone_in.setText(str(invite.get("recipientPhone") or ""))
                self.invite_email_in.setText(str(invite.get("recipientEmail") or ""))
                self.invite_current_pw_in.clear()
                self.invite_current_pw_in.hide()
                role_name = {
                    "owner": "企业所有者",
                    "admin": "企业管理员",
                    "member": "普通成员",
                    "auditor": "审计员",
                }.get(str(invite.get("role") or "member"), "普通成员")
                try:
                    expires_at = time.strftime(
                        "%Y-%m-%d %H:%M", time.localtime(float(invite.get("expiresAt") or 0))
                    )
                except (TypeError, ValueError, OSError, OverflowError):
                    expires_at = "-"
                self.invite_org.setText(
                    "企业：%s · 角色：%s · 有效至：%s"
                    % (organization.get("name") or organization.get("id") or "-", role_name, expires_at)
                )
                self._set_msg("邀请码已验证，请填写账号信息", "ok")
            else:
                self._invite_verified_code = ""
                self.invite_org.clear()
                self._set_msg(enterprise_invite_error_message(response.get("error")), "err")
            return
        if tag == "login_invite_accept":
            d = d or {}
            if self._mode != "invite" or d.get("requestGeneration") != self._invite_request_generation:
                return
            submitted_code = str(d.get("code") or "")
            if (
                submitted_code != self._invite_verified_code
                or submitted_code != normalize_enterprise_invite_code(self.invite_code_in.text())
            ):
                self._invite_verified_code = ""
                self._set_invite_submission_enabled(True)
                self.btn.setEnabled(True)
                self._set_msg("邀请码已变更，请重新校验", "err")
                return
            response = d.get("response") if isinstance(d.get("response"), dict) else {}
            if response.get("ok") and response.get("token"):
                org_id = str(response.get("orgId") or "").strip()
                organizations = response.get("organizations") or []
                if not org_id and organizations and isinstance(organizations[0], dict):
                    org_id = str(organizations[0].get("id") or "").strip()
                org_id = org_id or "org-default"
                user = response.get("user") if isinstance(response.get("user"), dict) else {}
                account = user.get("id") or user.get("phone") or user.get("email") or self.phone_in.text().strip()
                set_session(response.get("token"), org_id, account=account)
                with _SLOCK:
                    _SHARED["balance"] = response.get("balance")
                set_auth_context(response)
                legal_consent = _legal_consent_payload()
                save_auth_pref({
                    "account": account,
                    "remember": False,
                    "autologin": False,
                    "password": "",
                    "token": "",
                    "org": org_id,
                    "legalTermsVersion": LEGAL_TERMS_VERSION,
                    "legalPrivacyVersion": LEGAL_PRIVACY_VERSION,
                    "legalAcceptedAt": legal_consent.get("acceptedAt"),
                })
                self._invite_verified_code = ""
                BRIDGE.logged_in.emit(True, org_id)
                return
            self._set_invite_submission_enabled(True)
            self.btn.setEnabled(True)
            error = str(response.get("error") or "")
            if error == "existing_user_login_required":
                self.invite_current_pw_in.show()
                self.invite_current_pw_in.setFocus(QtCore.Qt.OtherFocusReason)
            self._set_msg(enterprise_invite_error_message(error), "err")
            return
        if tag != "login_sendcode":
            return
        d = d or {}
        self.getcode_btn.setEnabled(True)
        if d.get("ok"):
            j = d.get("j") or {}
            if j.get("devCode"):
                self.code_in.setText(str(j["devCode"]))
                self._set_msg("开发模式:已自动填入验证码", "ok")
            else:
                self._set_msg("验证码已发送,5 分钟内有效", "ok")
            self._cd = 60
            self._cd_timer.start(1000)
            self.getcode_btn.setText("60s")
            self.getcode_btn.setEnabled(False)
        else:
            self._set_msg("发送失败:" + str((d.get("j") or {}).get("error") or "请稍后重试"), "err")

    def _tick(self):
        self._cd -= 1
        if self._cd <= 0:
            self._cd_timer.stop()
            self.getcode_btn.setText("获取验证码")
            self.getcode_btn.setEnabled(True)
        else:
            self.getcode_btn.setText("%ds" % self._cd)

    def do_login(self):
        if not self.agree.isChecked():
            self._set_msg("请先阅读并勾选同意相关协议", "err")
            return
        if self._mode == "invite":
            self.submit_enterprise_invite()
            return
        acct = self.phone_in.text().strip()
        code = self.code_in.text().strip()
        pw = self.pw_in.text()
        if self._mode == "register":
            if not (acct.isdigit() and len(acct) == 11):
                self._set_msg("请输入 11 位手机号", "err")
                return
            if len(pw) < 6:
                self._set_msg("密码至少 6 位", "err")
                return
            if self.pw2_in.text() != pw:
                self._set_msg("两次输入的密码不一致", "err")
                return
            if not code:
                self._set_msg("请输入短信验证码", "err")
                return
            path, body = "/api/auth/register", {
                "phone": acct,
                "code": code,
                "password": pw,
                "legalConsent": _legal_consent_payload(),
            }
        else:  # login:手机号 + 密码 + 验证码, 或用户名 + 密码
            if not acct:
                self._set_msg("请输入手机号或用户名", "err")
                return
            if not pw:
                self._set_msg("请输入密码", "err")
                return
            if login_needs_phone_code(acct) and not code:
                self._set_msg("请输入短信验证码(账号密码需二次验证)", "err")
                return
            path, body = "/api/auth/login", {
                "identifier": acct,
                "password": pw,
                "code": code,
                "legalConsent": _legal_consent_payload(),
            }
        remember = self._mode == "login" and self.remember_cb.isChecked()
        autologin = self._mode == "login" and self.autologin_cb.isChecked()
        pw_text = pw
        self.btn.setEnabled(False)
        self._set_msg("注册中…" if self._mode == "register" else "登录中…", "info")

        def work():
            code_, j = api("POST", path, body)
            if isinstance(j, dict) and j.get("ok") and j.get("token"):
                org = "org-default"
                orgs = j.get("organizations") or []
                if orgs and isinstance(orgs[0], dict):
                    org = orgs[0].get("id") or "org-default"
                user = j.get("user") if isinstance(j.get("user"), dict) else {}
                acc2 = user.get("id") or user.get("phone") or acct
                set_session(j.get("token"), org, account=acc2)
                with _SLOCK:
                    _SHARED["balance"] = j.get("balance")
                set_auth_context(j)
                try:
                    save_auth_pref({"account": acct, "remember": bool(remember), "autologin": bool(autologin),
                                    "password": pw_text if remember else "",
                                    "token": j.get("token") if autologin else "", "org": org,
                                    "legalTermsVersion": LEGAL_TERMS_VERSION,
                                    "legalPrivacyVersion": LEGAL_PRIVACY_VERSION,
                                    "legalAcceptedAt": (body.get("legalConsent") or {}).get("acceptedAt")})
                except Exception:
                    pass
                BRIDGE.logged_in.emit(True, org)
            else:
                BRIDGE.logged_in.emit(False, (j or {}).get("error") or ("http_%s" % code_))
        run_bg(work)

    def _play_success_transition(self, info):
        self._success_info = info
        self.btn.setEnabled(False)
        for w in (self.phone_in, self.pw_in, self.pw2_in, self.code_in, self.getcode_btn,
                  self.invite_code_in, self.invite_verify_btn, self.invite_name_in,
                  self.invite_email_in, self.invite_current_pw_in, self.tab_login,
                  self.tab_reg, self.tab_invite, self.remember_cb, self.autologin_cb, self.agree):
            try:
                w.setEnabled(False)
            except Exception:
                pass

        if self._success_overlay is None or self._success_eye is None or self._success_effect is None:
            self._finish_success_transition()
            return

        self._layout_success_overlay(0.52)
        self._success_effect.setOpacity(0.0)
        self._success_overlay.show()
        self._success_overlay.raise_()

        opacity = QtCore.QPropertyAnimation(self._success_effect, b"opacity", self)
        opacity.setDuration(self.LOGIN_SUCCESS_TRANSITION_MS)
        opacity.setStartValue(0.0)
        opacity.setKeyValueAt(0.62, 0.55)
        opacity.setEndValue(0.55)
        opacity.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        zoom = QtCore.QPropertyAnimation(self._success_eye, b"geometry", self)
        zoom.setDuration(self.LOGIN_SUCCESS_TRANSITION_MS)
        zoom.setStartValue(self._success_eye_rect(0.50))
        zoom.setEndValue(self._success_eye_rect(self.LOGIN_SUCCESS_FULL_SCREEN_SCALE))
        zoom.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        group = QtCore.QParallelAnimationGroup(self)
        group.addAnimation(opacity)
        group.addAnimation(zoom)
        group.finished.connect(self._finish_success_transition)
        self._success_anim = group
        group.start(QtCore.QAbstractAnimation.DeleteWhenStopped)

    def _finish_success_transition(self):
        info = self._success_info
        self._success_info = None
        self._success_anim = None
        if self._success_overlay is not None:
            self._success_overlay.hide()
        # 登录成功:彻底释放背景视频管线与图像缓存(避免会话期常驻内存)
        self.bg.release()
        self.on_success(info)

    def _done(self, ok, info):
        self.btn.setEnabled(True)
        legal_errors = {
            "legal_consent_required": "请阅读并同意当前版本的用户协议和隐私政策",
            "legal_consent_outdated": "协议版本已更新，请重新阅读并同意",
        }
        message = legal_errors.get(str(info or ""), str(info or ""))
        self._set_msg("登录成功" if ok else ("登录失败:" + message), "ok" if ok else "err")
        if ok:
            self._play_success_transition(info)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("云灵星图 本地客户端")
        self.resize(1240, 780)
        self.stack = QtWidgets.QStackedWidget()
        self.login = LoginView(self.on_login)
        self.stack.addWidget(self.login)
        self.shell = self._build_shell()
        self.stack.addWidget(self.shell)
        self.stack.setCurrentWidget(self.login)
        self.setCentralWidget(self.stack)
        BRIDGE.payload.connect(self._on_update_payload)
        QtCore.QTimer.singleShot(3500, self._check_update)
        QtCore.QTimer.singleShot(350, self._try_autologin)

    def _try_autologin(self):
        try:
            pref = load_auth_pref() or {}
        except Exception:
            pref = {}
        if not (pref.get("autologin") and pref.get("token")):
            return
        if not _auth_pref_has_current_legal_consent(pref):
            try:
                clear_auth_autologin()
            except Exception:
                pass
            lv = getattr(self, "login", None)
            if lv is not None:
                lv._set_msg("协议或隐私政策已更新，请阅读后重新登录", "info")
            return
        set_session(pref.get("token"), pref.get("org") or "org-default", account=pref.get("account"))
        lv = getattr(self, "login", None)
        if lv is not None:
            try:
                lv._set_msg("正在自动登录…", "info")
                lv.btn.setEnabled(False)
                for w in (lv.phone_in, lv.pw_in, lv.code_in):
                    w.setEnabled(False)
            except Exception:
                pass

        def work():
            try:
                _c, j = api("POST", "/api/auth/refresh", {})
            except Exception:
                j = None
            if isinstance(j, dict) and j.get("ok"):
                org = pref.get("org") or "org-default"
                orgs = j.get("organizations") or []
                if orgs and isinstance(orgs[0], dict):
                    org = orgs[0].get("id") or org
                user = j.get("user") if isinstance(j.get("user"), dict) else {}
                acc2 = user.get("id") or user.get("phone") or pref.get("account")
                set_session(j.get("token") or pref.get("token"), org, account=acc2)
                set_auth_context(j)
                BRIDGE.logged_in.emit(True, org)
            else:
                # token 失效:清掉自动登录、回到登录页(账号密码会由 _prefill_remembered 回填)
                try:
                    clear_auth_autologin()
                except Exception:
                    pass
                set_session("", "org-default")
                BRIDGE.payload.emit("autologin_failed", {})
        run_bg(work)

    def _check_update(self):
        def work():
            try:
                _c, j = api("GET", "/api/version")
                if isinstance(j, dict):
                    latest = str(j.get("latest") or "").strip()
                    if latest and _version_gt(latest, APP_VERSION):
                        BRIDGE.payload.emit("update_available", {
                            "latest": latest, "notice": j.get("notice") or "",
                            "url": j.get("downloadUrl") or "", "force": bool(j.get("force"))})
            except Exception:
                pass
        run_bg(work)

    def _on_update_payload(self, tag, d):
        if tag != "update_available" or getattr(self, "_update_shown", False):
            return
        self._update_shown = True
        d = d or {}
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("发现新版本 " + str(d.get("latest") or ""))
        box.setText(("云灵星图有新版本可用(当前 %s → 最新 %s)。\n\n%s"
                     % (APP_VERSION, d.get("latest"), d.get("notice") or "")).strip())
        if d.get("force"):
            box.setInformativeText("⚠️ 本次为强制更新,请下载安装最新版后再使用。")
        dl = box.addButton("下载更新", QtWidgets.QMessageBox.AcceptRole)
        box.addButton("稍后" if not d.get("force") else "退出", QtWidgets.QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is dl and d.get("url"):
            try:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl(d.get("url")))
            except Exception:
                pass
        if d.get("force"):
            QtWidgets.QApplication.quit()

    def _build_shell(self):
        root = QtWidgets.QWidget()
        root.setObjectName("root")
        h = QtWidgets.QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QtWidgets.QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        sv = QtWidgets.QVBoxLayout(side)
        sv.setContentsMargins(14, 16, 12, 14)
        sv.setSpacing(4)
        brandrow = QtWidgets.QHBoxLayout()
        brandrow.setSpacing(11)
        mark = QtWidgets.QLabel()
        mark.setFixedSize(40, 40)
        mark.setAlignment(QtCore.Qt.AlignCenter)
        mark.setStyleSheet("background:transparent;")
        mark_pm = QtGui.QPixmap(YUNLING_MARK_PATH)
        if not mark_pm.isNull():
            mark.setPixmap(mark_pm.scaled(40, 40, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        btext = QtWidgets.QVBoxLayout()
        btext.setSpacing(1)
        brand = QtWidgets.QLabel("云灵星图")
        brand.setObjectName("brand")
        bsub = QtWidgets.QLabel("AI爆款复刻平台")
        bsub.setObjectName("brandSub")
        btext.addWidget(brand)
        btext.addWidget(bsub)
        brandrow.addWidget(mark)
        brandrow.addLayout(btext)
        brandrow.addStretch()
        sv.addLayout(brandrow)
        sv.addSpacing(12)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        navw = QtWidgets.QWidget()
        nvl = QtWidgets.QVBoxLayout(navw)
        nvl.setContentsMargins(0, 0, 0, 0)
        nvl.setSpacing(3)

        self.pages = QtWidgets.QStackedWidget()
        self.nav_btns = []
        self._page_widgets = []
        self._page_hosts = []
        self._nav_names = []
        self._nav_labels = {}
        idx = 0
        for group, items in NAV:
            gl = QtWidgets.QLabel(group)
            gl.setObjectName("group")
            gl.setContentsMargins(6, 10, 0, 2)
            nvl.addWidget(gl)
            for name, factory in items:
                page = factory()
                page.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
                host = QtWidgets.QScrollArea()
                host.setWidgetResizable(True)
                host.setFrameShape(QtWidgets.QFrame.NoFrame)
                host.setStyleSheet("QScrollArea{background:transparent;border:0;}")
                body = QtWidgets.QWidget()
                body.setStyleSheet("background:transparent;")
                body_layout = QtWidgets.QVBoxLayout(body)
                body_layout.setContentsMargins(0, 0, 0, 0)
                body_layout.setSpacing(0)
                body_layout.addWidget(page)
                host.setWidget(body)
                self.pages.addWidget(host)
                self._page_widgets.append(page)
                self._page_hosts.append(host)
                b = NavButton(name)
                b.clicked.connect(lambda _=False, i=idx: self._nav(i))
                nvl.addWidget(b)
                self.nav_btns.append(b)
                self._nav_names.append(name)
                self._nav_labels[name] = idx
                for alias in getattr(page, "nav_aliases", ()):
                    self._nav_labels[alias] = idx
                idx += 1
        self._apply_role_visibility()
        BRIDGE.payload.connect(self._goto_nav)
        BRIDGE.payload.connect(self._on_warmup)
        nvl.addStretch()
        scroll.setWidget(navw)
        sv.addWidget(scroll, 1)
        div = QtWidgets.QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet("background:#1c2233;")
        sv.addWidget(div)
        sv.addSpacing(9)
        foot = QtWidgets.QVBoxLayout()
        foot.setSpacing(7)
        user_row = QtWidgets.QHBoxLayout()
        user_row.setSpacing(9)
        self.avatar = QtWidgets.QLabel("·")
        self.avatar.setFixedSize(32, 32)
        self.avatar.setAlignment(QtCore.Qt.AlignCenter)
        self.avatar.setStyleSheet("background:%s;color:#c9b8ff;border:1px solid %s;border-radius:16px;"
                                  "font-weight:800;font-size:14px;" % (_rgba("#8b5cf6", 0.18), _rgba("#8b5cf6", 0.5)))
        acol = QtWidgets.QVBoxLayout()
        acol.setSpacing(0)
        self.conn_name = QtWidgets.QLabel("未登录")
        self.conn_name.setStyleSheet("color:#e8eaf0;font-size:12px;font-weight:700;background:transparent;")
        self.conn_name.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.conn = QtWidgets.QLabel("● 未连接")
        self.conn.setObjectName("conn")
        acol.addWidget(self.conn_name)
        acol.addWidget(self.conn)
        user_row.addWidget(self.avatar)
        user_row.addLayout(acol, 1)
        foot.addLayout(user_row)

        control_row = QtWidgets.QHBoxLayout()
        control_row.setSpacing(8)
        self.balance_lab = QtWidgets.QLabel("")
        self.balance_lab.setStyleSheet("color:#f5c451;font-size:12px;font-weight:800;background:transparent;")
        self.balance_lab.setCursor(QtCore.Qt.PointingHandCursor)
        control_row.addWidget(self.balance_lab)
        control_row.addStretch()
        self._theme_btn = QtWidgets.QPushButton("☀" if CURRENT_THEME == "dark" else "☾")
        self._theme_btn.setObjectName("iconbtn")
        self._theme_btn.setFixedSize(30, 30)
        self._theme_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._theme_btn.setToolTip("切换 暗黑 / 白天 主题")
        self._theme_btn.clicked.connect(self.toggle_theme)
        control_row.addWidget(self._theme_btn)
        self._logout_btn = QtWidgets.QPushButton()
        self._logout_btn.setObjectName("iconbtn")
        self._logout_btn.setFixedSize(30, 30)
        self._logout_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._logout_btn.setToolTip("退出登录")
        self._logout_btn.setIcon(QtGui.QIcon(_draw_icon("logout", 15, TK["iconText"])))
        self._logout_btn.setIconSize(QtCore.QSize(15, 15))
        self._logout_btn.clicked.connect(self.logout)
        control_row.addWidget(self._logout_btn)
        foot.addLayout(control_row)
        sv.addLayout(foot)

        h.addWidget(side)
        pagew = AuroraBg()
        pagew.setObjectName("page")
        pl = QtWidgets.QVBoxLayout(pagew)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.pages)
        h.addWidget(pagew, 1)
        wire_animations(root)
        return root

    def _goto_nav(self, tag, d):
        if tag == "goto_nav":
            i = self._nav_labels.get(d)
            if i is not None and (i >= len(getattr(self, "_nav_names", [])) or nav_allowed(self._nav_names[i])):
                self._nav(i)

    def _apply_role_visibility(self):
        for i, b in enumerate(getattr(self, "nav_btns", [])):
            name = self._nav_names[i] if i < len(getattr(self, "_nav_names", [])) else ""
            if not nav_allowed(name):
                b.setVisible(False)
                b.setEnabled(False)
            else:
                b.setVisible(True)
                b.setEnabled(True)

    def _toast(self, msg, ms=6200):
        """Small non-blocking in-window notice for background actions."""
        try:
            old = getattr(self, "_toast_label", None)
            if old is not None:
                old.hide()
                old.deleteLater()
            lab = QtWidgets.QLabel(str(msg), self.shell)
            lab.setObjectName("toast")
            lab.setWordWrap(True)
            lab.setStyleSheet(
                "QLabel#toast{background:rgba(13,18,32,232);color:#edf2ff;"
                "border:1px solid rgba(125,144,255,150);border-radius:10px;"
                "padding:10px 14px;font-size:13px;font-weight:700;}"
            )
            max_w = max(260, min(520, self.shell.width() - 80))
            lab.setFixedWidth(max_w)
            lab.adjustSize()
            lab.move(max(24, self.shell.width() - lab.width() - 28), 26)
            lab.raise_()
            lab.show()
            self._toast_label = lab

            def close(label=lab):
                try:
                    if getattr(self, "_toast_label", None) is label:
                        self._toast_label = None
                    label.hide()
                    label.deleteLater()
                except Exception:
                    pass
            QtCore.QTimer.singleShot(ms, close)
        except Exception:
            log(msg)

    def _on_warmup(self, tag, d):
        if tag != "warmup":
            return
        d = d or {}
        st = d.get("status")
        msg = d.get("msg") or ""
        if st == "starting":
            self.conn.setText("● 已连接 · 正在预热抖音")
            self.conn.setToolTip(msg)
            self._toast(msg, 7600)
        elif st == "done":
            self.conn.setText("● 已连接 · 抖音预热完成")
            self.conn.setToolTip(msg)
            self._toast(msg, 5200)
            QtCore.QTimer.singleShot(5200, lambda: self.conn.setText("● 已连接 · 数据隔离"))
        elif st == "skipped":
            self.conn.setText("● 已连接 · 已跳过抖音预热")
            self.conn.setToolTip(msg)
            self._toast(msg, 7600)
            QtCore.QTimer.singleShot(7600, lambda: self.conn.setText("● 已连接 · 数据隔离"))
        elif st == "error":
            self.conn.setText("● 已连接 · 抖音预热未完成")
            self.conn.setToolTip(msg)
            self._toast(msg, 6200)
            QtCore.QTimer.singleShot(6200, lambda: self.conn.setText("● 已连接 · 数据隔离"))

    def _nav(self, i):
        if i < len(getattr(self, "_nav_names", [])) and not nav_allowed(self._nav_names[i]):
            for j, name in enumerate(getattr(self, "_nav_names", [])):
                if nav_allowed(name):
                    i = j
                    break
        self.pages.setCurrentIndex(i)
        for k, b in enumerate(self.nav_btns):
            b.setChecked(k == i)
        w = self._page_widgets[i]
        host = self._page_hosts[i] if i < len(self._page_hosts) else w
        if hasattr(w, "on_show"):
            try:
                w.on_show()
            except Exception as e:
                log("page on_show: %s" % e)
        # 页面淡入;含原生视频窗口的页面(如仪表盘)跳过,graphics effect 会破坏原生渲染
        if not getattr(w, "_no_fade", False):
            fade_in(host, dur=240)

    def on_login(self, org):
        # 账号隔离:按登录账号锁定本地引擎数据目录,再启动引擎(只启一次)。
        acc = current_account()
        try:
            apply_account_scope(acc)
        except Exception as e:
            log("账号隔离失败: %s" % e)
        if not getattr(self, "_engine_started", False):
            self._engine_started = True
            start_engine()
        start_worker_manager()
        warmup_engine()  # 登录后后台预热抖音/小红书浏览器,首次冷启动不落在用户第一次点击上
        self.stack.setCurrentWidget(self.shell)
        self._apply_role_visibility()
        # 释放登录页(含背景视频/解码器/图像缓存),整页回收,避免会话期常驻内存
        try:
            if getattr(self, "login", None) is not None:
                self.stack.removeWidget(self.login)
                self.login.deleteLater()
                self.login = None
        except Exception:
            pass
        self._nav(0)
        with _SLOCK:
            user = _SHARED.get("user") or {}
        disp = user.get("name") or user.get("phone") or str(acc)
        self.conn_name.setText(str(disp))
        self.avatar.setText((str(disp)[:1] or "·").upper())
        self.conn.setText("● 已连接 · 数据隔离")
        BRIDGE.payload.connect(self._on_balance)
        self.refresh_balance()
        self._start_balance_timer()
        self._start_scheduler()

    def _start_balance_timer(self):
        if getattr(self, "_balance_timer", None) is None:
            self._balance_timer = QtCore.QTimer(self)
            self._balance_timer.setInterval(30000)
            self._balance_timer.timeout.connect(self.refresh_balance)
        if not self._balance_timer.isActive():
            self._balance_timer.start()

    def refresh_balance(self):
        def work():
            bal = fetch_balance()
            BRIDGE.payload.emit("balance", {"balance": bal})
        run_bg(work)

    def _on_balance(self, tag, d):
        if tag != "balance":
            return
        bal = (d or {}).get("balance")
        try:
            if bal is None:
                self.balance_lab.setText("")
            elif bal == float("inf") or str(bal) == "inf":
                self.balance_lab.setText("☁ 运营方")
            else:
                self.balance_lab.setText("☁ %s 云豆" % (int(bal) if float(bal) == int(bal) else round(float(bal), 2)))
        except Exception:
            self.balance_lab.setText("")

    def logout(self):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("退出登录")
        box.setText("确定退出当前云灵星图账号吗？")
        box.setInformativeText("会清除本次会话和自动登录状态，账号密码记忆仍会保留。")
        cancel = box.addButton("取消", QtWidgets.QMessageBox.RejectRole)
        ok = box.addButton("退出登录", QtWidgets.QMessageBox.AcceptRole)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is not ok:
            return
        try:
            clear_auth_autologin()
        except Exception:
            pass
        clear_session()
        try:
            if getattr(self, "_balance_timer", None) is not None:
                self._balance_timer.stop()
                self._balance_timer = None
        except Exception:
            pass
        try:
            if getattr(self, "_sched_timer", None) is not None:
                self._sched_timer.stop()
                self._sched_timer = None
        except Exception:
            pass
        log("用户退出登录，独立重启客户端回到登录页")
        restarted, error_id = _restart_client_detached()
        if not restarted:
            QtWidgets.QMessageBox.critical(
                self,
                "退出登录失败",
                "无法重新打开登录界面，当前窗口已保留。\n"
                "错误编号：%s" % error_id,
            )
            return
        QtWidgets.QApplication.quit()

    def toggle_theme(self):
        busy_breakdowns = [
            page for page in getattr(self, "_page_widgets", [])
            if isinstance(page, VideoBreakdownPage) and bool(getattr(page, "_busy", False))
        ]
        if busy_breakdowns:
            message = "视频分解任务正在运行，完成后再切换主题。"
            try:
                notify = getattr(self, "_toast", None)
                if callable(notify):
                    notify(message, 5200)
                else:
                    log(message)
            except Exception:
                log(message)
            return False
        new = "light" if CURRENT_THEME == "dark" else "dark"
        apply_theme(new)
        save_theme_pref(new)
        try:
            self._theme_btn.setText("☀" if new == "dark" else "☾")
            self.conn_name.setStyleSheet("color:%s;font-size:12px;font-weight:700;background:transparent;" % TK["text"])
            if getattr(self, "_logout_btn", None) is not None:
                self._logout_btn.setIcon(QtGui.QIcon(_draw_icon("logout", 15, TK["iconText"])))
        except Exception:
            pass
        self._rebuild_pages()
        return True

    def _rebuild_pages(self):
        """主题切换后重建所有页面(内联样式读 TK 的控件随之更新);侧栏/chrome 已随 setStyleSheet 生效。"""
        try:
            cur = self.pages.currentIndex()
        except Exception:
            cur = 0
        try:
            for i in reversed(range(self.pages.count())):
                w = self.pages.widget(i)
                self.pages.removeWidget(w)
                w.setParent(None)
            self._page_widgets = []
            self._page_hosts = []
            for group, items in NAV:
                for name, factory in items:
                    page = factory()
                    page.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
                    host = QtWidgets.QScrollArea()
                    host.setWidgetResizable(True)
                    host.setFrameShape(QtWidgets.QFrame.NoFrame)
                    host.setStyleSheet("QScrollArea{background:transparent;border:0;}")
                    body = QtWidgets.QWidget()
                    body.setStyleSheet("background:transparent;")
                    body_layout = QtWidgets.QVBoxLayout(body)
                    body_layout.setContentsMargins(0, 0, 0, 0)
                    body_layout.setSpacing(0)
                    body_layout.addWidget(page)
                    host.setWidget(body)
                    self.pages.addWidget(host)
                    self._page_widgets.append(page)
                    self._page_hosts.append(host)
            self._nav(max(0, min(cur, self.pages.count() - 1)))
        except Exception as e:
            log("theme rebuild: %s" % e)
        try:
            self.update()
            for w in self.findChildren(AuroraBg):
                w.update()
        except Exception:
            pass

    # ---------- 定时生产调度器:到点自动跑工作流生产内容,可选自动发送视频 ----------
    def _start_scheduler(self):
        if getattr(self, "_sched_timer", None) is not None:
            return
        self._sched_busy = False
        self._sched_timer = QtCore.QTimer(self)
        self._sched_timer.timeout.connect(self._check_schedules)
        self._sched_timer.start(60000)  # 每分钟检查一次计划
        QtCore.QTimer.singleShot(4000, self._check_schedules)

    def _check_schedules(self):
        try:
            today = time.strftime("%Y-%m-%d")
            now_hm = time.strftime("%H:%M")
            due = [wf for wf in list(WORKFLOWS) if _should_fire(wf, now_hm, today)]
            if getattr(self, "_sched_busy", False):
                if due:  # 引擎忙(上一条还在生产),到点的先延后,下一轮空闲再补跑,不丢失
                    log("⏰ 引擎忙,%d 条到点计划延后,空闲后自动补跑" % len(due))
                return
            if due:
                wf = due[0]
                wf["_last_run_date"] = today
                save_workflows()
                self._sched_run(wf)  # 一次只起一条,避免并发抢额度;其余留待下一轮(120分钟窗口内补跑)
        except Exception as e:
            log("scheduler: %s" % e)

    def _sched_run(self, wf):
        self._sched_busy = True
        sch = wf.get("schedule") or {}
        try:
            per = max(1, min(int(str(sch.get("perRun") or 1).strip() or 1), 3))
        except Exception:
            per = 1
        try:
            per = min(per, max(1, int(RISK.get("dailyPublish") or per)))  # 遵循风控每日发布上限
        except Exception:
            pass
        name = wf.get("name") or "工作流"
        if sch.get("autoPublish"):
            log("⏰ 定时触发生产:%s(本次 %d 条)→ 生成后自动发送视频到%s账号「%s」;失败入待发布队列" %
                (name, per, "小红书" if sch.get("publishPlatform") in ("xhs", "小红书", "xiaohongshu") else "抖音",
                 sch.get("publishAccountId") or "未填"))
        else:
            log("⏰ 定时触发生产:%s(本次 %d 条)→ 产物将入待发布队列" % (name, per))

        def work():
            made = 0
            try:
                for _ in range(per):
                    ctx, _ok = run_scheduled_workflow(wf, lambda i, s, summ: None)
                    if ctx.get("artifacts"):
                        made += 1
            except Exception as e:
                log("定时生产出错:%s" % str(e)[:120])
            finally:
                self._sched_busy = False
            if sch.get("autoPublish"):
                log("⏰ 定时生产完成:%s,%d 条已处理自动发送/入队" % (name, made))
            else:
                log("⏰ 定时生产完成:%s,%d 条已入待发布队列(等你人工确认发布)" % (name, made))
        run_bg(work)


def main():
    setup_env()
    _open_logfile()          # 日志落盘
    install_crash_handler()  # 全局异常兜底
    log("MatrixShipAgent 启动 v%s · 中心服 %s" % (APP_VERSION, CENTRAL))
    load_workflows()  # 载入已保存的对话工作流(供 AgentChatPage / WorkflowPage 显示)
    load_pending()    # 载入待发布队列
    load_assets()     # 载入资产库
    load_brand()      # 载入企业品牌资料
    load_risk()       # 载入风控限额
    # 引擎不在这里起 —— 改到登录后 on_login 里,按登录账号做数据隔离再启动本地引擎。
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        _icf = os.path.join(_ASSETS_DIR, "app.ico")
        if os.path.isfile(_icf):
            app.setWindowIcon(QtGui.QIcon(_icf))
    except Exception:
        pass
    apply_theme(load_theme_pref())
    global BRIDGE
    BRIDGE = Bridge()
    timer = QtCore.QTimer()

    def drain():
        try:
            while True:
                BRIDGE.log_line.emit(_LOGQ.get_nowait())
        except queue.Empty:
            pass
    timer.timeout.connect(drain)
    timer.start(400)
    win = MainWindow()
    win.show()
    log("客户端启动;中心 %s" % CENTRAL)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
