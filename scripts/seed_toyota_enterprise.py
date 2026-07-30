import argparse
import json
import os
import shutil
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = ROOT / "backend" / "central_data" / "scheduler_state.json"
TOYOTA_ORG = {"id": "org-toyota", "name": "丰田汽车", "status": "active", "plan": "standard"}
TARGET_MEMBERS = {
    "boss": {"role": "admin", "name": "企业家"},
    "user01": {"role": "member", "name": "普通用户01"},
    "user02": {"role": "member", "name": "普通用户02"},
}


def _now():
    return time.time()


def _upsert_org(organizations):
    for org in organizations:
        if org.get("id") == TOYOTA_ORG["id"]:
            changed = False
            for key, value in TOYOTA_ORG.items():
                if org.get(key) != value:
                    org[key] = value
                    changed = True
            if changed:
                org["updatedAt"] = _now()
            return changed
    item = dict(TOYOTA_ORG)
    item["createdAt"] = _now()
    item["updatedAt"] = item["createdAt"]
    organizations.append(item)
    return True


def _ensure_user_names(users):
    changed = False
    by_id = {str(user.get("id") or ""): user for user in users if isinstance(user, dict)}
    for user_id, spec in TARGET_MEMBERS.items():
        user = by_id.get(user_id)
        if not user:
            continue
        if not user.get("name"):
            user["name"] = spec["name"]
            user["updatedAt"] = _now()
            changed = True
    return changed


def _replace_target_memberships(memberships):
    next_memberships = []
    existing = {}
    changed = False
    for item in memberships:
        user_id = str(item.get("userId") or "")
        if user_id not in TARGET_MEMBERS:
            next_memberships.append(item)
            continue
        spec = TARGET_MEMBERS[user_id]
        is_expected = (
            item.get("orgId") == TOYOTA_ORG["id"]
            and item.get("role") == spec["role"]
            and item.get("status", "active") == "active"
        )
        if is_expected and user_id not in existing:
            existing[user_id] = item
            next_memberships.append(item)
        else:
            changed = True
    for user_id, spec in TARGET_MEMBERS.items():
        if user_id in existing:
            continue
        item = {
            "id": "m-org-toyota-%s" % user_id,
            "orgId": TOYOTA_ORG["id"],
            "userId": user_id,
            "role": spec["role"],
            "status": "active",
            "createdAt": _now(),
            "updatedAt": _now(),
        }
        next_memberships.append(item)
        changed = True
    if changed:
        memberships[:] = next_memberships
    return changed


def _append_audit(state):
    logs = state.setdefault("auditLogs", [])
    audit_id = "audit-toyota-seed-%d" % int(_now())
    if any(item.get("id") == audit_id for item in logs if isinstance(item, dict)):
        return False
    logs.append({
        "id": audit_id,
        "action": "enterprise.toyota.seed",
        "path": "scripts/seed_toyota_enterprise.py",
        "ok": True,
        "createdAt": _now(),
        "meta": {
            "orgId": TOYOTA_ORG["id"],
            "movedUsers": sorted(TARGET_MEMBERS),
            "leftInDefault": ["user-owner"],
        },
    })
    return True


def apply_toyota_seed(state):
    organizations = state.setdefault("organizations", [])
    users = state.setdefault("users", [])
    memberships = state.setdefault("memberships", [])
    changed = False
    changed = _upsert_org(organizations) or changed
    changed = _ensure_user_names(users) or changed
    changed = _replace_target_memberships(memberships) or changed
    if changed:
        _append_audit(state)
    return changed


def _atomic_write_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def run(path, dry_run=False):
    path = Path(path)
    with path.open("r", encoding="utf-8-sig") as handle:
        state = json.load(handle)
    changed = apply_toyota_seed(state)
    if dry_run or not changed:
        return {"changed": changed, "backup": None, "path": str(path)}
    backup = path.with_name("%s.bak-%s" % (path.name, time.strftime("%Y%m%d%H%M%S")))
    shutil.copy2(path, backup)
    _atomic_write_json(path, state)
    return {"changed": True, "backup": str(backup), "path": str(path)}


def main():
    parser = argparse.ArgumentParser(description="Seed Toyota enterprise membership data.")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = run(args.state, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
