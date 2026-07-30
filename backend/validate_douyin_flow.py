# coding: utf-8
"""Douyin commercial flow validator.

Default mode is non-destructive:
- no real comment is sent
- no real publish button is clicked

It validates through the central scheduler because that is what business users
use from the native client.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests


def now_ms():
    return int(time.time() * 1000)


class CheckRun:
    def __init__(self, base, token, keyword, timeout=180):
        self.base = base.rstrip("/")
        self.token = token
        self.keyword = keyword
        self.timeout = timeout
        self.steps = []

    def headers(self, json_body=True):
        h = {}
        if self.token:
            h["X-Matrix-User-Token"] = self.token
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def record(self, name, ok, **data):
        item = {"name": name, "ok": bool(ok), **data}
        self.steps.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
        return item

    def get(self, path, **params):
        r = requests.get(self.base + path, headers=self.headers(False), params=params, timeout=self.timeout)
        try:
            data = r.json()
        except Exception:
            data = {"ok": False, "raw": r.text[:1000]}
        return r.status_code, data

    def post(self, path, body, timeout=None):
        r = requests.post(self.base + path, headers=self.headers(True), json=body, timeout=timeout or self.timeout)
        try:
            data = r.json()
        except Exception:
            data = {"ok": False, "raw": r.text[:1000]}
        return r.status_code, data

    def upload_material(self, file_path, title):
        with open(file_path, "rb") as f:
            files = {"file": (Path(file_path).name, f, "application/octet-stream")}
            data = {"title": title, "type": "video"}
            h = self.headers(False)
            r = requests.post(self.base + "/api/library/upload", headers=h, data=data, files=files, timeout=self.timeout)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"ok": False, "raw": r.text[:1000]}

    def run(self, allow_write=False, skip_download=False, skip_publish=False):
        status, health = self.get("/api/health", sync="1")
        self.record("health", status < 400 and bool(health.get("ok")), status=status, authorized=health.get("authorized"), cookieReady=health.get("cookieReady"), onlineNodes=health.get("onlineNodes"))

        status, accounts = self.get("/api/accounts")
        douyin_accounts = [a for a in accounts if isinstance(a, dict) and a.get("platform") == "douyin"] if isinstance(accounts, list) else []
        ready_accounts = [a for a in douyin_accounts if a.get("usable") or a.get("cookieReady")]
        self.record("accounts", status < 400 and isinstance(accounts, list), status=status, total=len(accounts) if isinstance(accounts, list) else 0, douyin=len(douyin_accounts), ready=len(ready_accounts))
        if not ready_accounts:
            self.record("precondition", False, error="douyin_auth_required", message="请先在账号矩阵完成抖音授权，然后重新运行验证脚本")
            return {"ok": False, "error": "douyin_auth_required", "steps": self.steps}

        status, search = self.post("/api/douyin/search", {"query": self.keyword, "keyword": self.keyword, "num": 3, "content_type": "0"}, timeout=180)
        items = search.get("items") or []
        self.record("search", status < 400 and bool(search.get("ok")) and len(items) > 0, status=status, count=len(items), errors=search.get("errors") or [])
        if not items:
            return {"ok": False, "error": "douyin_search_empty", "steps": self.steps, "search": search}

        first = items[0]
        url = first.get("work_url") or ("https://www.douyin.com/video/" + str(first.get("work_id") or ""))
        self.record("select_video", bool(url), url=url, title=first.get("title") or "")

        status, comments = self.post("/api/douyin/comments", {"url": url, "mode": "page", "cursor": "0"}, timeout=120)
        comment_items = comments.get("items") or []
        self.record("comments_page", status < 400 and bool(comments.get("ok")), status=status, count=len(comment_items))

        status, finder = self.post("/api/finder/discover", {"platform": "douyin", "keyword": self.keyword, "videoNum": 1, "commentMode": "page", "source": "validator"}, timeout=220)
        self.record("finder_discover", status < 500 and bool(finder.get("ok")), status=status, videoCount=finder.get("videoCount"), commentCount=finder.get("commentCount"), leadCount=finder.get("leadCount"), error=finder.get("error"))

        status, outreach = self.post("/api/outreach/run", {
            "platform": "douyin",
            "keyword": self.keyword,
            "template": "围绕用户问题做友好答复，不引导站外，不重复刷屏。",
            "videoNum": 1,
            "limit": 1,
            "sendMode": "comment",
            "dryRun": not allow_write,
            "safeMode": True,
            "preflight": True,
            "channel": "auto",
        }, timeout=240)
        self.record("outreach_" + ("real" if allow_write else "dry_run"), status < 500 and bool(outreach.get("ok")), status=status, targetCount=outreach.get("targetCount"), sentCount=outreach.get("sentCount"), dryRun=not allow_write, error=outreach.get("error"))

        downloaded_file = ""
        if not skip_download:
            status, download = self.post("/api/douyin/download", {"url": url, "save_choice": "video"}, timeout=260)
            files = [f for f in (download.get("files") or []) if f.get("path") and f.get("size", 0) > 0]
            downloaded_file = files[0]["path"] if files else ""
            self.record("download", status < 500 and bool(download.get("ok")) and bool(files), status=status, savePath=download.get("savePath"), files=len(files), error=download.get("error"))

        if not skip_publish:
            material_id = ""
            if downloaded_file and os.path.exists(downloaded_file):
                status, uploaded = self.upload_material(downloaded_file, "validator-douyin-%s" % now_ms())
                material_id = uploaded.get("id") or ""
                self.record("library_upload", status < 400 and bool(uploaded.get("ok")) and bool(material_id), status=status, materialId=material_id, error=uploaded.get("error"))
            else:
                status, lib = self.get("/api/library")
                rows = lib if isinstance(lib, list) else (lib.get("items") or [] if isinstance(lib, dict) else [])
                usable = [x for x in rows if isinstance(x, dict) and x.get("id")]
                material_id = usable[0].get("id") if usable else ""
                self.record("library_existing", bool(material_id), status=status, materialId=material_id)
            if material_id:
                status, pub = self.post("/api/publish/run", {"materialId": material_id, "accountId": "douyin-self", "dryRun": True}, timeout=360)
                self.record("publish_dry_run", status < 500 and bool(pub.get("ok")), status=status, filled=pub.get("filled"), published=pub.get("published"), error=pub.get("error"))

        ok = all(x.get("ok") for x in self.steps if x["name"] not in ("finder_discover", "comments_page"))
        return {"ok": ok, "steps": self.steps}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.getenv("MATRIX_BASE_URL") or "http://127.0.0.1:9080")
    ap.add_argument("--token", default=os.getenv("MATRIX_USER_TOKEN") or os.getenv("MATRIX_ROOT_TOKEN") or "")
    ap.add_argument("--keyword", default=os.getenv("DOUYIN_VALIDATE_KEYWORD") or "化妆品")
    ap.add_argument("--allow-write", action="store_true", help="真实发送一条评论；默认不发送")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--skip-publish", action="store_true")
    args = ap.parse_args()
    result = CheckRun(args.base, args.token, args.keyword).run(allow_write=args.allow_write, skip_download=args.skip_download, skip_publish=args.skip_publish)
    print("SUMMARY=" + json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
