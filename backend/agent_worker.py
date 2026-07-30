# coding: utf-8
"""Execution-node worker for MatrixShip scheme #3.

Run this on every execution node.  It polls central_server for queued tasks and
executes them through the node-local api_server, so every node uses its own IP,
browser profile, cookies and risk/cooldown state.
"""

import argparse
import os.path
import json
import os
import platform
import socket
import sys
import time
import traceback
from typing import Any, Dict
from urllib.parse import urljoin

import requests
from runtime_paths import agent_data_dir


VERSION = "1.0.0-exec-node"


def stdout_utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def read_local_token() -> str:
    tok = (os.getenv("MATRIX_AGENT_TOKEN") or os.getenv("DY_AGENT_TOKEN") or "").strip()
    if tok:
        return tok
    try:
        p = os.path.join(agent_data_dir(), "agent_token.txt")
        if os.path.isfile(p):
            return open(p, "r", encoding="utf-8").read().strip()
    except Exception:
        pass
    return ""


def post_json(url: str, payload: Dict[str, Any], headers=None, timeout=60) -> Dict[str, Any]:
    r = requests.post(url, json=payload, headers=headers or {}, timeout=timeout)
    try:
        data = r.json()
    except Exception:
        data = {"ok": False, "statusCode": r.status_code, "raw": r.text[:2000]}
    if r.status_code >= 400:
        data.setdefault("ok", False)
        data.setdefault("httpStatus", r.status_code)
    return data


def get_json(url: str, headers=None, timeout=20) -> Dict[str, Any]:
    r = requests.get(url, headers=headers or {}, timeout=timeout)
    try:
        data = r.json()
    except Exception:
        data = {"ok": False, "statusCode": r.status_code, "raw": r.text[:2000]}
    if r.status_code >= 400:
        data.setdefault("ok", False)
        data.setdefault("httpStatus", r.status_code)
    return data


class Worker:
    def __init__(self, central_url, node_secret, node_id, name, local_api, region="", tags=None, local_token=""):
        self.central = central_url.rstrip("/")
        self.node_secret = node_secret
        self.node_id = node_id
        self.name = name or node_id
        self.local_api = local_api.rstrip("/")
        self.region = region
        self.tags = tags or []
        self.local_token = local_token
        self.busy = False
        self.last_health = {}
        self.last_accounts = {}
        self.stats = {"done": 0, "failed": 0, "startedAt": time.time()}
        self.material_map = {}

    @property
    def central_headers(self):
        return {"X-Node-Secret": self.node_secret}

    @property
    def local_headers(self):
        h = {}
        if self.local_token:
            h["X-Matrix-Agent-Token"] = self.local_token
        return h

    def collect_local_status(self):
        try:
            # Do not use sync=1 in the worker heartbeat.  Profile sync can open
            # Chromium and block interactive login tasks for tens of seconds.
            # Login/profile sync is performed by explicit auth/status flows.
            self.last_health = get_json(self.local_api + "/api/health", headers=self.local_headers, timeout=8)
        except Exception as e:
            self.last_health = {"ok": False, "error": str(e)}
        try:
            self.last_accounts = get_json(self.local_api + "/api/accounts", headers=self.local_headers, timeout=8)
        except Exception as e:
            self.last_accounts = {"ok": False, "error": str(e)}
        accounts = []
        raw = self.last_accounts
        if isinstance(raw, list):
            accounts = raw
        elif isinstance(raw, dict):
            val = raw.get("value")
            if isinstance(val, list):
                accounts = val
            elif isinstance(raw.get("accounts"), list):
                accounts = raw.get("accounts")
        return {
            "nodeId": self.node_id,
            "name": self.name,
            "region": self.region,
            "tags": self.tags,
            "version": VERSION,
            "localApi": self.local_api,
            "host": socket.gethostname(),
            "platform": platform.platform(),
            "cookieReady": bool(self.last_health.get("cookieReady")),
            "cookieCount": self.last_health.get("cookieCount", 0),
            "accounts": accounts,
            "busy": self.busy,
            "stats": self.stats,
        }

    def register(self):
        payload = self.collect_local_status()
        data = post_json(self.central + "/api/node/register", payload, headers=self.central_headers, timeout=30)
        if not data.get("ok"):
            raise RuntimeError("register_failed: " + json.dumps(data, ensure_ascii=False))
        self.node_id = data.get("nodeId") or self.node_id
        print("[registered]", self.node_id, self.name)

    def heartbeat(self):
        payload = self.collect_local_status()
        data = post_json(self.central + "/api/node/heartbeat", payload, headers=self.central_headers, timeout=20)
        if not data.get("ok"):
            print("[heartbeat failed]", data)
        return data

    def poll(self):
        return post_json(self.central + "/api/node/tasks/poll", {"nodeId": self.node_id}, headers=self.central_headers, timeout=30)

    def report_result(self, task_id, ok, result=None, error=""):
        payload = {"nodeId": self.node_id, "taskId": task_id, "ok": bool(ok), "result": result or {}, "error": error}
        return post_json(self.central + "/api/node/tasks/result", payload, headers=self.central_headers, timeout=30)

    def ensure_central_material(self, body):
        """Mirror a central material into this node's local api_server library.

        The native client uploads materials through central_server. Before a publish task
        reaches the node-local /api/publish/run, the worker downloads those
        central files and uploads them to the local node library, then rewrites
        body.materialId to the node-local id.
        """
        body = dict(body or {})
        cm = body.get("centralMaterial") or {}
        cid = cm.get("id") or body.get("centralMaterialId")
        if not cid:
            return body
        if cid in self.material_map:
            body["materialId"] = self.material_map[cid]
            body.pop("centralMaterial", None)
            return body
        upload_files = []
        handles = []
        try:
            for idx, f in enumerate(cm.get("files") or []):
                name = f.get("name") or ("file_%d" % idx)
                u = f.get("url") or ""
                if u.startswith("/"):
                    url = self.central + u
                else:
                    url = u or urljoin(self.central + "/", u)
                r = requests.get(url, headers=self.central_headers, timeout=180)
                r.raise_for_status()
                upload_files.append(("files", (name, r.content, "application/octet-stream")))
            if not upload_files:
                raise RuntimeError("central_material_has_no_files")
            data = {"title": cm.get("title") or body.get("title") or cid, "type": cm.get("type") or "video"}
            res = requests.post(self.local_api + "/api/library/upload", data=data, files=upload_files, headers=self.local_headers, timeout=300)
            try:
                j = res.json()
            except Exception:
                j = {"ok": False, "raw": res.text[:1000], "httpStatus": res.status_code}
            if res.status_code >= 400 or not j.get("ok"):
                raise RuntimeError("local_material_upload_failed: " + json.dumps(j, ensure_ascii=False))
            local_id = j.get("id")
            if not local_id:
                raise RuntimeError("local_material_upload_missing_id")
            self.material_map[cid] = local_id
            body["materialId"] = local_id
            body.pop("centralMaterial", None)
            return body
        finally:
            for h in handles:
                try:
                    h.close()
                except Exception:
                    pass

    def execute_task(self, task):
        tid = task.get("id")
        path = task.get("path")
        body = task.get("body") or {}
        method = (task.get("method") or "POST").upper()
        print("[task]", tid, method, path)
        self.busy = True
        started = time.time()
        try:
            timeout = 900 if path in ("/api/outreach/run", "/api/finder/discover", "/api/publish/run", "/api/douyin/download", "/api/xhs/download") else 300
            if path == "/api/publish/run":
                body = self.ensure_central_material(body)
            if method == "POST":
                data = post_json(self.local_api + path, body, headers=self.local_headers, timeout=timeout)
            else:
                data = get_json(self.local_api + path, headers=self.local_headers, timeout=timeout)
            data.setdefault("executionNode", {"id": self.node_id, "name": self.name, "region": self.region})
            data.setdefault("executionElapsedSec", round(time.time() - started, 3))
            ok = bool(data.get("ok", True))
            self.stats["done" if ok else "failed"] = self.stats.get("done" if ok else "failed", 0) + 1
            self.report_result(tid, ok, result=data, error="" if ok else str(data.get("error") or "local_task_failed"))
        except Exception as e:
            self.stats["failed"] = self.stats.get("failed", 0) + 1
            self.report_result(tid, False, result={"ok": False, "trace": traceback.format_exc()}, error=str(e))
        finally:
            self.busy = False

    def loop(self, poll_interval=2.0, heartbeat_interval=15.0):
        self.register()
        next_hb = 0
        while True:
            try:
                if time.time() >= next_hb:
                    self.heartbeat()
                    next_hb = time.time() + heartbeat_interval
                data = self.poll()
                task = data.get("task") if isinstance(data, dict) else None
                if task:
                    self.execute_task(task)
                    next_hb = 0
                else:
                    time.sleep(poll_interval)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print("[worker error]", repr(e))
                time.sleep(max(3.0, poll_interval))


def main():
    stdout_utf8()
    ap = argparse.ArgumentParser(description="MatrixShip execution-node worker")
    ap.add_argument("--central", default=os.getenv("CENTRAL_URL", "http://127.0.0.1:9080"))
    ap.add_argument("--node-secret", default=os.getenv("CENTRAL_NODE_SECRET", "matrix-node-secret-change-me"))
    ap.add_argument("--node-id", default=os.getenv("NODE_ID", socket.gethostname().lower().replace("_", "-")))
    ap.add_argument("--name", default=os.getenv("NODE_NAME", socket.gethostname()))
    ap.add_argument("--region", default=os.getenv("NODE_REGION", ""))
    ap.add_argument("--tags", default=os.getenv("NODE_TAGS", ""))
    ap.add_argument("--local-api", default=os.getenv("LOCAL_API", "http://127.0.0.1:9081"))
    ap.add_argument("--local-token", default=os.getenv("LOCAL_AGENT_TOKEN", read_local_token()))
    ap.add_argument("--poll-interval", type=float, default=float(os.getenv("NODE_POLL_INTERVAL", "0.5") or 0.5))
    args = ap.parse_args()
    tags = [x.strip() for x in (args.tags or "").split(",") if x.strip()]
    print("=" * 72)
    print("MatrixShip execution node")
    print("central  :", args.central)
    print("node id  :", args.node_id)
    print("local api:", args.local_api)
    print("=" * 72)
    Worker(args.central, args.node_secret, args.node_id, args.name, args.local_api, args.region, tags, args.local_token).loop(args.poll_interval)


if __name__ == "__main__":
    main()
