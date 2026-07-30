# coding: utf-8
"""Frozen-bundle self-test for the Douyin signer.

Built as a tiny PyInstaller exe to PROVE that a_bogus/X-Bogus signing still
works after freezing (bundled static/*.js + node_modules + node.exe). If this
passes, the full MatrixShipAgent bundle recipe is sound.
"""
import sys, traceback


def main() -> int:
    try:
        from runtime_paths import ensure_node_on_path
        node_exe = ensure_node_on_path()
        print("node runtime:", node_exe or "(system PATH)")
    except Exception as e:
        print("node shim error:", e)
    try:
        from utils.dy_util import generate_a_bogus
        ab = generate_a_bogus('device_platform=webapp&aid=6383&channel=channel_pc_web', '')
        print("a_bogus:", (ab[:48] + '...') if ab else ab)
        print("FROZEN_SIGNER_OK" if ab else "FROZEN_SIGNER_EMPTY")
        return 0 if ab else 2
    except Exception:
        traceback.print_exc()
        print("FROZEN_SIGNER_FAIL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
