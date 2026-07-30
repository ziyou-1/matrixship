# coding: utf-8
"""One-time local-state migration for 1 cloud bean = 1 yuan.

Default mode is a dry run. Use --apply after stopping the central server and
native clients. The script creates a timestamped .bak file before writing.
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import central_server  # noqa: E402


def load_state(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_state(path, state):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Migrate legacy cloud-bean balances from 100:1 to 1:1.")
    parser.add_argument("--state", default=central_server.STORE_JSON, help="Path to scheduler_state.json")
    parser.add_argument("--apply", action="store_true", help="Write the migrated state. Omit for dry-run.")
    args = parser.parse_args(argv)

    state_path = Path(args.state).resolve()
    state = load_state(state_path)
    label = time.strftime("%Y%m%d%H%M%S")
    summary = central_server.migrate_yundou_state_to_one_to_one(state, now_label=label)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not summary.get("migrated"):
        return 0
    if not args.apply:
        print("dry_run=true; rerun with --apply after stopping the server to write changes.")
        return 0

    backup_path = state_path.with_name(state_path.name + ".bak-yundou-1to1-" + label)
    shutil.copy2(state_path, backup_path)
    save_state(state_path, state)
    print("backup=" + str(backup_path))
    print("updated=" + str(state_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
