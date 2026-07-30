# coding: utf-8
"""MatrixShip local-browser worker (post-migration primary execution loop).

Runs on the USER's own Windows PC. It:
  1. registers with the central server as a per-user local-browser client
     (auth = SaaS user token + orgId, NOT the legacy per-node X-Node-Secret),
  2. long-polls central /api/local-browser/poll for queued tasks,
  3. maps task.type -> the local engine's api_server path and forwards the task
     to http://127.0.0.1:9081 (the engine drives the user's real Edge + IP),
  4. posts the result back to central /api/local-browser/result.

This replaces the cloud-node model (agent_worker.py, kept for transition): every
action now runs in the user's own browser + residential IP, so the central IP is
never what platforms see.

Config (env or %APPDATA%/MatrixShipAgent/data/client_config.json):
  MATRIX_CENTRAL   central base url        (default http://39.105.120.104)
  MATRIX_USER_TOKEN  SaaS user session token (required; set via pairing in Phase 3)
  MATRIX_ORG_ID    organization id        (default org-default)
  LOCAL_API        local engine base url   (default http://127.0.0.1:9081)
  MATRIX_CLIENT_NAME / MATRIX_CLIENT_ID
"""

import argparse
import json
import os
import platform
import socket
import sys
import threading
import time
import traceback
from typing import Any, Dict

import requests
from runtime_paths import agent_data_dir

VERSION = "2.0.0-local-browser"

# task.type -> local engine api_server path (all POST). Mirrors
# central_server.LOCAL_BROWSER_TASK_PATHS; keep the two in sync.
TASK_PATHS = {
    "douyin.search": "/api/douyin/search",
    "douyin.work": "/api/douyin/work",
    "douyin.comments": "/api/douyin/comments",
    "douyin.comment.publish": "/api/douyin/comment/publish",
    "douyin.dm": "/api/douyin/dm",
    "douyin.dm.inbox": "/api/douyin/dm/inbox",
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
LOGIN_TYPES = ("douyin.login", "xhs.login")
CAPABILITIES = sorted(set(TASK_PATHS.keys()) | set(LOGIN_TYPES))
LONG_TASKS = {
    "/api/finder/discover", "/api/outreach/run", "/api/publish/run",
    "/api/douyin/download", "/api/xhs/download",
}


def stdout_utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def appdata_data_dir() -> str:
    return agent_data_dir()


def read_local_token() -> str:
    tok = (os.getenv("MATRIX_AGENT_TOKEN") or os.getenv("LOCAL_AGENT_TOKEN") or "").strip()
    if tok:
        return tok
    try:
        p = os.path.join(appdata_data_dir(), "agent_token.txt")
        if os.path.isfile(p):
            return open(p, "r", encoding="utf-8").read().strip()
    except Exception:
        pass
    return ""


def load_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    try:
        p = os.path.join(appdata_data_dir(), "client_config.json")
        if os.path.isfile(p):
            cfg = json.load(open(p, "r", encoding="utf-8-sig")) or {}  # utf-8-sig tolerates a BOM
    except Exception:
        cfg = {}
    cfg["central"] = (os.getenv("MATRIX_CENTRAL") or cfg.get("central") or "http://39.105.120.104").rstrip("/")
    cfg["token"] = (os.getenv("MATRIX_USER_TOKEN") or cfg.get("token") or "").strip()
    cfg["orgId"] = (os.getenv("MATRIX_ORG_ID") or cfg.get("orgId") or "org-default").strip()
    cfg["localApi"] = (os.getenv("LOCAL_API") or cfg.get("localApi") or "http://127.0.0.1:9081").rstrip("/")
    cfg["clientId"] = (os.getenv("MATRIX_CLIENT_ID") or cfg.get("clientId") or ("lb-" + socket.gethostname().lower().replace("_", "-"))).strip()
    cfg["name"] = (os.getenv("MATRIX_CLIENT_NAME") or cfg.get("name") or socket.gethostname()).strip()
    return cfg


def config_path() -> str:
    return os.path.join(appdata_data_dir(), "client_config.json")


def save_config(cfg) -> bool:
    try:
        os.makedirs(appdata_data_dir(), exist_ok=True)
        keep = {k: cfg.get(k) for k in ("central", "token", "orgId", "localApi", "clientId", "name")}
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(keep, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("WARN: save_config failed:", e)
        return False


def redeem_pairing(central, code) -> Dict[str, Any]:
    return post_json(central.rstrip("/") + "/api/local-browser/pair/redeem", {"code": code}, timeout=30)


def ensure_paired(cfg, code=""):
    """If no token yet, redeem a pairing code (from arg or interactive prompt) and
    persist the resulting client config. Returns the (possibly updated) cfg."""
    if cfg.get("token"):
        return cfg
    code = (code or "").strip()
    if not code:
        try:
            code = input("请输入中心服/本地客户端生成的 6 位配对码(直接回车跳过): ").strip()
        except Exception:
            code = ""
    if not code:
        return cfg
    res = redeem_pairing(cfg.get("central") or "http://39.105.120.104", code)
    if res.get("ok"):
        cfg["token"] = res.get("token") or cfg.get("token")
        cfg["orgId"] = res.get("orgId") or cfg.get("orgId")
        if res.get("clientId"):
            cfg["clientId"] = res.get("clientId")
        save_config(cfg)
        print("配对成功，客户端已连接。")
    else:
        print("配对失败：", res.get("error"))
    return cfg


def post_json(url, payload, headers=None, timeout=60) -> Dict[str, Any]:
    r = requests.post(url, json=payload, headers=headers or {}, timeout=timeout)
    try:
        data = r.json()
    except Exception:
        data = {"ok": False, "statusCode": r.status_code, "raw": r.text[:2000]}
    if r.status_code >= 400:
        data.setdefault("ok", False)
        data.setdefault("httpStatus", r.status_code)
    return data


def get_json(url, headers=None, timeout=20) -> Dict[str, Any]:
    r = requests.get(url, headers=headers or {}, timeout=timeout)
    try:
        data = r.json()
    except Exception:
        data = {"ok": False, "statusCode": r.status_code, "raw": r.text[:2000]}
    if r.status_code >= 400:
        data.setdefault("ok", False)
        data.setdefault("httpStatus", r.status_code)
    return data


class LocalBrowserWorker:
    def __init__(self, cfg):
        self.central = cfg["central"]
        self.token = cfg["token"]
        self.org_id = cfg["orgId"]
        self.local_api = cfg["localApi"]
        self.client_id = cfg["clientId"]
        self.name = cfg["name"]
        self.local_token = read_local_token()
        self.material_map = {}

    @property
    def central_headers(self):
        return {"X-Matrix-User-Token": self.token, "X-Matrix-Org-Id": self.org_id}

    @property
    def local_headers(self):
        return {"X-Matrix-Agent-Token": self.local_token} if self.local_token else {}

    def register(self):
        payload = {
            "clientId": self.client_id, "name": self.name, "version": VERSION,
            "browser": "local-engine", "platform": platform.platform(),
            "capabilities": CAPABILITIES, "status": "registered", "orgId": self.org_id,
        }
        data = post_json(self.central + "/api/local-browser/register", payload, headers=self.central_headers, timeout=30)
        if not data.get("ok"):
            raise RuntimeError("register_failed: " + json.dumps(data, ensure_ascii=False)[:400])
        self.client_id = data.get("clientId") or self.client_id
        print("[registered]", self.client_id, self.name)
        return data

    def poll(self):
        payload = {"clientId": self.client_id, "name": self.name, "version": VERSION,
                   "capabilities": CAPABILITIES, "status": "polling", "orgId": self.org_id}
        return post_json(self.central + "/api/local-browser/poll", payload, headers=self.central_headers, timeout=40)

    def report(self, task_id, ok, result=None, error=""):
        payload = {"clientId": self.client_id, "taskId": task_id, "ok": bool(ok),
                   "error": error or "", "result": result or {}, "orgId": self.org_id}
        return post_json(self.central + "/api/local-browser/result", payload, headers=self.central_headers, timeout=60)

    def ensure_local_material(self, payload):
        """Publish tasks reference a central materialId; download those files and
        upload them to the local engine library, rewriting materialId."""
        payload = dict(payload or {})
        cm = payload.get("centralMaterial") or {}
        cid = cm.get("id") or payload.get("centralMaterialId")
        if not cid:
            return payload
        if cid in self.material_map:
            payload["materialId"] = self.material_map[cid]
            payload.pop("centralMaterial", None)
            return payload
        upload_files = []
        for idx, f in enumerate(cm.get("files") or []):
            name = f.get("name") or ("file_%d" % idx)
            u = f.get("url") or ""
            url = (self.central + u) if u.startswith("/") else u
            r = requests.get(url, headers=self.central_headers, timeout=180)
            r.raise_for_status()
            upload_files.append(("files", (name, r.content, "application/octet-stream")))
        if not upload_files:
            raise RuntimeError("central_material_has_no_files")
        data = {"title": cm.get("title") or payload.get("title") or cid, "type": cm.get("type") or "video"}
        for key in (
            "platform", "body", "status", "sourceTitle", "sourceBody",
            "replacementJobId", "sourceTemplateId", "localDraftMaterialId",
        ):
            value = str(cm.get(key) or "").strip()
            if value:
                data[key] = value
        for key in ("tags", "sourceTags"):
            value = cm.get(key)
            if value:
                data[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, tuple, dict)) else str(value)
        if cm.get("importedFromXhsNoteReplacement"):
            data["importedFromXhsNoteReplacement"] = "1"
        res = requests.post(self.local_api + "/api/library/upload", data=data, files=upload_files, headers=self.local_headers, timeout=300)
        j = res.json()
        if res.status_code >= 400 or not j.get("ok"):
            raise RuntimeError("local_material_upload_failed: " + json.dumps(j, ensure_ascii=False)[:300])
        local_id = j.get("id")
        self.material_map[cid] = local_id
        payload["materialId"] = local_id
        payload.pop("centralMaterial", None)
        return payload

    def _pick_account(self, accounts, platform):
        """Best-effort extract an account identity from the local engine /api/accounts."""
        try:
            arr = accounts
            if isinstance(accounts, dict):
                arr = accounts.get("value") or accounts.get("accounts") or accounts.get("items") or []
            if not isinstance(arr, list):
                return {}
            for a in arr:
                if not isinstance(a, dict):
                    continue
                if platform and (a.get("platform") or "douyin") != platform:
                    continue
                return {"id": a.get("id") or a.get("uid") or a.get("sec_uid") or "",
                        "name": a.get("name") or a.get("nickname") or a.get("n") or "",
                        "handle": a.get("handle") or a.get("h") or "",
                        "fans": a.get("fans") or "", "avatar": a.get("avatar") or ""}
        except Exception:
            pass
        return {}

    def run_login(self, task):
        ttype = (task.get("type") or "").strip()
        platform = "xhs" if ttype.startswith("xhs") else "douyin"
        start_path = "/api/xhs/login" if platform == "xhs" else "/api/login/start"
        fresh = bool((task.get("payload") or {}).get("fresh"))
        start = post_json(self.local_api + start_path, {"platform": platform, "fresh": fresh}, headers=self.local_headers, timeout=30)
        sid = start.get("sessionId")
        if not sid:
            return {"ok": False, "error": start.get("error") or "login_start_failed", "platform": platform}
        timeout_sec = max(60, int((task.get("payload") or {}).get("timeoutSec") or 220))
        deadline = time.time() + timeout_sec
        status = {}
        while time.time() < deadline:
            time.sleep(3)
            status = get_json(self.local_api + "/api/login/status?sessionId=" + sid, headers=self.local_headers, timeout=15)
            if (status or {}).get("status") in ("success", "error"):
                break
        logged = bool(status.get("loggedIn") or status.get("status") == "success")
        account = {}
        try:
            account = self._pick_account(get_json(self.local_api + "/api/accounts", headers=self.local_headers, timeout=15), platform)
        except Exception:
            account = {}
        return {"ok": logged, "loggedIn": logged, "platform": platform,
                "cookieCount": status.get("cookieCount", 0), "account": account,
                "error": "" if logged else (status.get("error") or "login_not_detected")}

    def run_task(self, task):
        ttype = (task.get("type") or "").strip()
        payload = task.get("payload") or {}
        if ttype in LOGIN_TYPES:
            return self.run_login(task)
        path = TASK_PATHS.get(ttype)
        if not path:
            return {"ok": False, "error": "unsupported_task_type", "type": ttype}
        if path == "/api/publish/run":
            payload = self.ensure_local_material(payload)
        timeout = 900 if path in LONG_TASKS else 300
        started = time.time()
        data = post_json(self.local_api + path, payload, headers=self.local_headers, timeout=timeout)
        if isinstance(data, dict):
            data.setdefault("executionClient", {"id": self.client_id, "name": self.name, "local": True})
            data.setdefault("executionElapsedSec", round(time.time() - started, 3))
        return data

    def _run_and_report(self, task):
        tid = task.get("id") or task.get("taskId")
        try:
            result = self.run_task(task)
            ok = bool(result.get("ok", True)) if isinstance(result, dict) else False
            self.report(tid, ok, result=result, error="" if ok else str((result or {}).get("error") or "task_failed"))
        except Exception as e:
            self.report(tid, False, result={"ok": False, "trace": traceback.format_exc()[:2000]}, error=str(e))

    def loop(self, idle_sleep=2.0, max_concurrent=4):
        """并发执行:API 类任务(搜索/评论/私信/下载/寻客)彼此不阻塞,可同时进行;
        需要浏览器的任务(发布/登录)由本机引擎内的锁自然串行(同一账号一次一个)。"""
        self.register()
        try:
            max_concurrent = max(1, int(os.getenv("MATRIX_MAX_CONCURRENT", str(max_concurrent)) or max_concurrent))
        except Exception:
            pass
        sem = threading.Semaphore(max_concurrent)
        while True:
            if not self.token:
                return
            try:
                data = self.poll()
                task = data.get("task") if isinstance(data, dict) else None
                if not task:
                    time.sleep(float(data.get("pollIntervalSec") or idle_sleep) if isinstance(data, dict) else idle_sleep)
                    continue
                tid = task.get("id") or task.get("taskId")
                print("[task]", tid, task.get("type"))
                sem.acquire()

                def worker_run(t=task):
                    try:
                        self._run_and_report(t)
                    finally:
                        sem.release()
                threading.Thread(target=worker_run, name="task-" + str(tid), daemon=True).start()
                time.sleep(0.2)  # yield, then poll again quickly to pick up more concurrent tasks
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print("[worker error]", repr(e))
                time.sleep(max(3.0, idle_sleep))


def main():
    stdout_utf8()
    ap = argparse.ArgumentParser(description="MatrixShip local-browser worker")
    ap.add_argument("--central", default="")
    ap.add_argument("--token", default="")
    ap.add_argument("--org", default="")
    ap.add_argument("--local-api", default="")
    ap.add_argument("--pair", default="", help="legacy pairing code from the operator")
    args = ap.parse_args()
    cfg = load_config()
    if args.central:
        cfg["central"] = args.central.rstrip("/")
    if args.token:
        cfg["token"] = args.token
    if args.org:
        cfg["orgId"] = args.org
    if args.local_api:
        cfg["localApi"] = args.local_api.rstrip("/")
    if args.token:
        save_config(cfg)
    cfg = ensure_paired(cfg, args.pair)
    print("=" * 72)
    print("MatrixShip local-browser worker", VERSION)
    print("central  :", cfg["central"])
    print("orgId    :", cfg["orgId"])
    print("local api:", cfg["localApi"])
    print("token    :", "(set)" if cfg["token"] else "(MISSING - set MATRIX_USER_TOKEN or pair the client)")
    print("=" * 72)
    if not cfg["token"]:
        print("未配对：请在中心服/本地客户端生成配对码，用 --pair <码> 运行或按提示输入。")
        return 1
    LocalBrowserWorker(cfg).loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
