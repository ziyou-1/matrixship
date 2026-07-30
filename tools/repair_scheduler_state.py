# coding: utf-8
"""Validate, normalize, or restore MatrixShip central scheduler state safely.

This tool never writes unless --normalize or --restore is provided. All writes use
UTF-8 without BOM and keep a timestamped backup of the previous state file.
"""

import argparse
import json
import os
import shutil
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "backend" / "central_data" / "scheduler_state.json"


def load_state(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("state_not_object")
    return value


def counts(state):
    return {
        "organizations": len(state.get("organizations") or []),
        "users": len(state.get("users") or []),
        "memberships": len(state.get("memberships") or []),
        "ledger": len(state.get("ledger") or []),
        "gen_charges": len(state.get("gen_charges") or {}),
    }


def backup_file(path, suffix):
    backup = Path(str(path) + ".bak-" + suffix + "-" + time.strftime("%Y%m%d%H%M%S"))
    shutil.copy2(path, backup)
    return backup


def write_state_no_bom(path, state):
    tmp = Path(str(path) + ".repair.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description="Safely repair MatrixShip scheduler_state.json")
    parser.add_argument("--state", default=str(DEFAULT_STATE), help="scheduler_state.json path")
    parser.add_argument("--restore", help="backup file to validate and restore")
    parser.add_argument("--normalize", action="store_true", help="rewrite current state as UTF-8 without BOM")
    args = parser.parse_args()

    state_path = Path(args.state).resolve()
    result = {"ok": True, "state": str(state_path), "wrote": False}

    if args.restore:
        restore_path = Path(args.restore).resolve()
        restored = load_state(restore_path)
        result["restoreCounts"] = counts(restored)
        if state_path.exists():
            result["backup"] = str(backup_file(state_path, "before-repair-restore"))
        state_path.parent.mkdir(parents=True, exist_ok=True)
        write_state_no_bom(state_path, restored)
        result["wrote"] = True
        result["counts"] = counts(restored)
    else:
        current = load_state(state_path)
        result["counts"] = counts(current)
        if args.normalize:
            result["backup"] = str(backup_file(state_path, "before-repair-normalize"))
            write_state_no_bom(state_path, current)
            result["wrote"] = True

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
