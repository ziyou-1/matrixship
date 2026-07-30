#!/usr/bin/env python3
"""Export MatrixShip JSON scheduler state to a SQLite preview database.

This is a P3.0 migration scaffold. It does not mutate production state and is safe to run offline:
  python export_state_to_sqlite.py --state /opt/matrixship/central_data/scheduler_state.json --out /tmp/matrixship-preview.db
"""
import argparse
import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA = ROOT / "001_enterprise_core_schema.sql"

def org_id(item):
    if not isinstance(item, dict):
        return "org-default"
    return str(item.get("orgId") or item.get("org_id") or ((item.get("meta") or {}).get("orgId")) or "org-default")

def ts(item, *keys):
    for k in keys:
        try:
            v = item.get(k)
            if v is not None:
                return float(v)
        except Exception:
            pass
    return None

def dumps(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)

def load_state(path):
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"state file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))

def exec_schema(conn):
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))

def upsert(conn, table, row):
    keys = list(row.keys())
    placeholders = ",".join(["?"] * len(keys))
    cols = ",".join(keys)
    updates = ",".join([f"{k}=excluded.{k}" for k in keys if k != "id"])
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}"
    conn.execute(sql, [row[k] for k in keys])

def export(state, out):
    out = Path(out)
    if out.exists():
        out.unlink()
    conn = sqlite3.connect(str(out))
    exec_schema(conn)
    now = time.time()

    for o in state.get("organizations") or []:
        oid = str(o.get("id") or "org-default")
        upsert(conn, "organizations", {"id": oid, "name": o.get("name") or oid, "plan_code": o.get("plan") or o.get("planCode") or "standard", "status": o.get("status") or "active", "created_at": ts(o,"createdAt","created_at") or now, "updated_at": ts(o,"updatedAt","updated_at") or now, "meta_json": dumps(o.get("meta") or {})})
    if not (state.get("organizations") or []):
        upsert(conn, "organizations", {"id":"org-default","name":"Default Workspace","plan_code":"standard","status":"active","created_at":now,"updated_at":now,"meta_json":"{}"})

    for u in state.get("users") or []:
        uid = str(u.get("id") or u.get("phone") or "user-unknown")
        upsert(conn, "users", {"id":uid,"name":u.get("name") or uid,"phone":u.get("phone") or "","email":u.get("email") or "","password_hash":u.get("passwordHash") or u.get("password_hash") or "","status":u.get("status") or "active","created_at":ts(u,"createdAt") or now,"updated_at":ts(u,"updatedAt") or now,"meta_json":dumps(u.get("meta") or {})})

    for m in state.get("memberships") or []:
        mid = str(m.get("id") or (str(m.get("orgId") or "org-default") + ":" + str(m.get("userId") or "user")))
        upsert(conn, "memberships", {"id":mid,"org_id":org_id(m),"user_id":str(m.get("userId") or ""),"role":m.get("role") or "member","status":m.get("status") or "active","created_at":ts(m,"createdAt") or now,"updated_at":ts(m,"updatedAt") or now})

    for n in (state.get("nodes") or {}).values():
        nid = str(n.get("id") or n.get("nodeId") or "node-unknown")
        upsert(conn, "nodes", {"id":nid,"org_id":org_id(n),"name":n.get("name") or nid,"host":n.get("host") or n.get("ip") or "","online":0 if n.get("online") is False else 1,"capacity_json":dumps(n.get("capacity") or {}),"last_seen":ts(n,"lastSeen","updatedAt"),"created_at":ts(n,"createdAt") or now,"updated_at":ts(n,"updatedAt") or now,"meta_json":dumps(n.get("meta") or {})})

    for m in state.get("library") or []:
        mid = str(m.get("id") or "material-unknown")
        files = m.get("files") or []
        upsert(conn, "materials", {"id":mid,"org_id":org_id(m),"title":m.get("title") or mid,"type":m.get("type") or "video","file_count":len(files),"files_json":dumps(files),"urls_json":dumps(m.get("urls") or []),"created_at":ts(m,"createdAt") or now,"updated_at":ts(m,"updatedAt") or now,"meta_json":dumps(m.get("meta") or {})})

    for q in state.get("queue") or []:
        qid = str(q.get("id") or q.get("queueId") or "queue-unknown")
        upsert(conn, "publish_queue_items", {"id":qid,"org_id":org_id(q),"account_id":q.get("accountId") or "","material_id":q.get("materialId") or "","status":q.get("status") or "pending","receipt_id":q.get("receiptId") or "","task_id":q.get("centralTaskId") or q.get("taskId") or "","last_error":q.get("lastError") or "","preflight_json":dumps(q.get("preflight") or {}),"events_json":dumps(q.get("events") or []),"created_at":ts(q,"createdAt") or now,"updated_at":ts(q,"updatedAt") or now,"meta_json":dumps(q.get("meta") or {})})

    for t in (state.get("tasks") or {}).values():
        tid = str(t.get("id") or "task-unknown")
        upsert(conn, "central_tasks", {"id":tid,"org_id":org_id(t),"type":t.get("type") or "","path":t.get("path") or "","status":t.get("status") or "queued","queue_id":t.get("queueId") or "","account_id":t.get("accountId") or "","node_id":t.get("nodeId") or "","payload_json":dumps(t.get("payload") or {}),"result_json":dumps(t.get("result") or {}),"error":t.get("error") or t.get("lastError") or "","created_at":ts(t,"createdAt") or now,"started_at":ts(t,"startedAt"),"finished_at":ts(t,"finishedAt"),"updated_at":ts(t,"updatedAt") or now})

    for a in state.get("auditLogs") or []:
        aid = str(a.get("id") or f"audit-{len(a)}-{time.time_ns()}")
        upsert(conn, "audit_logs", {"id":aid,"org_id":org_id(a),"actor_id":a.get("actorId") or a.get("userId") or "","action":a.get("action") or a.get("event") or "unknown","resource_type":a.get("resourceType") or "","resource_id":a.get("resourceId") or "","summary":a.get("summary") or "","meta_json":dumps(a.get("meta") or {}),"created_at":ts(a,"ts","createdAt") or now})

    conn.commit()
    counts = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in ["organizations","users","memberships","nodes","materials","publish_queue_items","central_tasks","audit_logs"]}
    conn.close()
    return counts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    counts = export(load_state(args.state), args.out)
    print(json.dumps({"ok": True, "out": args.out, "counts": counts}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
