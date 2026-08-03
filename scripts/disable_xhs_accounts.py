"""Remove persisted Xiaohongshu account state without touching Douyin data."""

import argparse
import json
import os
import shutil
from pathlib import Path


def _is_xhs_row(row):
    if not isinstance(row, dict):
        return False
    values = (
        row.get("platform"),
        row.get("id"),
        row.get("localAccountId"),
        row.get("accountId"),
    )
    return any(
        str(value or "").strip().lower() in {"xhs", "xiaohongshu", "rednote", "小红书"}
        or "xhs" in str(value or "").strip().lower()
        for value in values
    )


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
        return value
    except FileNotFoundError:
        return default


def _write_json(path, value):
    temporary = str(path) + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _filter_rows(rows):
    kept = []
    removed = 0
    for row in rows if isinstance(rows, list) else []:
        if _is_xhs_row(row):
            removed += 1
        else:
            kept.append(row)
    return kept, removed


def cleanup_xhs_state(data_dir, central_state_path=None, dry_run=False):
    data_dir = Path(data_dir).resolve()
    if not data_dir.is_dir():
        raise ValueError("data_dir must be an existing directory")
    local_removed = 0
    removed_paths = []

    for name in ("xhs_profile", "xhs_auth_state.json", "xhs_safety_state.json"):
        path = data_dir / name
        if path.exists():
            removed_paths.append(str(path))
            if not dry_run:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()

    for path in data_dir.glob("*.json"):
        if path.name in {"xhs_auth_state.json", "xhs_safety_state.json"}:
            continue
        value = _load_json(path, None)
        if isinstance(value, list):
            kept, removed = _filter_rows(value)
            if removed:
                local_removed += removed
                if not dry_run:
                    _write_json(path, kept)

    central_removed = 0
    central_path = Path(central_state_path).resolve() if central_state_path else None
    if central_path and central_path.exists():
        state = _load_json(central_path, {})
        if not isinstance(state, dict):
            raise ValueError("central state must be a JSON object")
        registry, removed = _filter_rows(state.get("accountsRegistry"))
        central_removed += removed
        state["accountsRegistry"] = registry
        for node in (state.get("nodes") or {}).values():
            if isinstance(node, dict) and isinstance(node.get("accounts"), list):
                kept, removed = _filter_rows(node.get("accounts"))
                central_removed += removed
                node["accounts"] = kept
        if central_removed and not dry_run:
            _write_json(central_path, state)

    return {
        "ok": True,
        "dryRun": bool(dry_run),
        "removedLocalAccounts": local_removed,
        "removedCentralAccounts": central_removed,
        "removedPaths": removed_paths,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--central-state")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = cleanup_xhs_state(args.data_dir, args.central_state, args.dry_run)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
