# coding: utf-8
"""Commercial local-agent entrypoint.

This is the executable entry used by MatrixShipAgent.exe.  It forces safe local
defaults so the native client always drives the user's own machine:

    native client -> http://127.0.0.1:9080 -> local engine -> Douyin

No LAN bind is used unless the operator explicitly overrides API_HOST.
"""

import os
import sys

from runtime_paths import agent_data_dir, ensure_agent_data_dir

APP_NAME = "MatrixShipAgent"


def appdata_data_dir() -> str:
    return agent_data_dir()


def main() -> int:
    data_dir = ensure_agent_data_dir(migrate_legacy=True)
    os.environ.setdefault("MATRIX_AGENT_DATA_DIR", data_dir)
    os.environ.setdefault("DY_PROFILE_DIR", os.path.join(data_dir, "dy_profile"))
    os.environ.setdefault("API_HOST", "127.0.0.1")
    # Local automation engine port (internal). Central owns 9080; the client's
    # api_server engine owns 9081 and is only reached by the local worker.
    os.environ.setdefault("API_PORT", "9081")
    os.environ.setdefault("MATRIX_AGENT_TOKEN_AUTH", "1")
    os.environ.setdefault("DY_COMMENT_EDGE_UI_FALLBACK", "1")

    # Put the bundled Node runtime on PATH BEFORE importing api_server, because
    # importing it transitively imports utils.dy_util, which compiles the
    # Douyin signer JS via PyExecJS (needs node) at import time.
    try:
        from runtime_paths import ensure_node_on_path
        node_exe = ensure_node_on_path()
        print("Node runtime:", node_exe or "(system PATH)")
    except Exception as _e:
        print("WARN: node path shim failed:", _e)

    # Start the central-coordinated local-browser worker in the background. It
    # polls the SaaS for tasks and executes them against this local engine, so
    # every action runs in the user's own browser + residential IP.
    try:
        import threading
        from local_browser_worker import LocalBrowserWorker, load_config, ensure_paired
        wcfg = load_config()
        if not wcfg.get("token"):
            print("首次使用：需要把本客户端与中心服账号配对。")
            print("请在本地客户端的账号配置中输入中心服提供的 6 位配对码。")
            try:
                wcfg = ensure_paired(wcfg)
            except Exception as pe:
                print("WARN: 配对未完成:", pe)
        if wcfg.get("token"):
            def _run_worker():
                import time as _t
                _t.sleep(3)  # let the local engine bind first
                try:
                    LocalBrowserWorker(wcfg).loop()
                except Exception as we:
                    print("WARN: local-browser worker exited:", we)
            threading.Thread(target=_run_worker, name="local-browser-worker", daemon=True).start()
            print("local-browser worker: starting (central=%s org=%s)" % (wcfg.get("central"), wcfg.get("orgId")))
        else:
            print("local-browser worker: idle — 未配对(稍后重启客户端并输入配对码即可)")
    except Exception as we:
        print("WARN: could not start local-browser worker:", we)

    from api_server import main as api_main

    print("=" * 72)
    print("MatrixShipAgent 本地助手")
    print("本地执行引擎(内部): http://127.0.0.1:" + os.environ.get("API_PORT", "9081"))
    print("本地客户端连接中心服务器，本机 9081 仅供内部执行引擎使用")
    print("用户数据目录:", data_dir)
    print("授权码文件:", os.path.join(data_dir, "agent_token.txt"))
    print("=" * 72)
    api_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
