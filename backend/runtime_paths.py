# coding: utf-8
"""Runtime path helpers for the packaged MatrixShip local client.

The Douyin request signing (a_bogus / X-Bogus / login) runs the bundled
static/*.js through PyExecJS, which shells out to a Node runtime.  End-user
machines frequently do NOT have Node installed, so the client ships its own
node.exe under <bundle>/node/ and this module puts it on PATH *before* anything
imports utils.dy_util (which compiles the JS at import time).

Call ensure_node_on_path() at the very top of the executable entrypoint.
"""

import os
import shutil
import sys


APP_NAME = "MatrixShipAgent"
_MIGRATED_LEGACY_DATA = False


def bundle_base() -> str:
    """Directory where bundled data lives (PyInstaller _MEIPASS when frozen)."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def backend_base() -> str:
    """Directory that contains backend source/runtime files."""
    return os.path.dirname(os.path.abspath(__file__))


def project_agent_data_dir() -> str:
    """Project-local runtime data directory used by Windows source deployments."""
    return os.path.abspath(os.path.join(backend_base(), "datas"))


def legacy_appdata_data_dir() -> str:
    """Previous Windows default data directory kept as a read-only migration source."""
    return os.path.abspath(os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), APP_NAME, "data"))


def _truthy_env(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def agent_data_dir() -> str:
    """Resolve the local-agent data directory.

    Explicit environment variables always win. On Windows source deployments,
    the default is backend/datas so downloaded media, browser profiles, logs and
    generation outputs stay with the project instead of C:\\Users\\...\\AppData.
    Operators can temporarily restore the legacy default with
    MATRIX_AGENT_USE_APPDATA=1 for rollback.
    """
    explicit = os.getenv("MATRIX_AGENT_DATA_DIR") or os.getenv("DY_DATA_DIR")
    if explicit:
        return os.path.abspath(os.path.expandvars(explicit))
    if os.name == "nt":
        if _truthy_env("MATRIX_AGENT_USE_APPDATA"):
            return legacy_appdata_data_dir()
        return project_agent_data_dir()
    if _truthy_env("MATRIX_AGENT_PORTABLE"):
        return project_agent_data_dir()
    return os.path.abspath(os.path.join(os.path.expanduser("~"), ".matrix_ship_agent", "data"))


def migrate_legacy_appdata_data(new_dir: str) -> None:
    """Best-effort non-destructive copy from the old Windows AppData location."""
    global _MIGRATED_LEGACY_DATA
    if _MIGRATED_LEGACY_DATA or os.name != "nt" or _truthy_env("MATRIX_AGENT_SKIP_APPDATA_MIGRATION"):
        return
    _MIGRATED_LEGACY_DATA = True
    old_dir = legacy_appdata_data_dir()
    if os.path.normcase(old_dir) == os.path.normcase(new_dir) or not os.path.isdir(old_dir):
        return
    os.makedirs(new_dir, exist_ok=True)
    for name in os.listdir(old_dir):
        src = os.path.join(old_dir, name)
        dst = os.path.join(new_dir, name)
        if os.path.exists(dst):
            continue
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            elif os.path.isfile(src):
                shutil.copy2(src, dst)
        except Exception:
            continue


def ensure_agent_data_dir(migrate_legacy: bool = False) -> str:
    """Create and return the resolved local-agent data directory."""
    data_dir = agent_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    if migrate_legacy:
        migrate_legacy_appdata_data(data_dir)
    return data_dir


def ensure_node_on_path() -> str:
    """Prepend the bundled node/ dir to PATH so PyExecJS can find node.exe.

    Returns the resolved node executable path if a bundled one was found,
    else "" (in which case a system Node on PATH is used, as in dev)."""
    base = bundle_base()
    node_dir = os.path.join(base, "node")
    exe = "node.exe" if os.name == "nt" else "node"
    node_exe = os.path.join(node_dir, exe)
    if os.path.isfile(node_exe):
        os.environ["PATH"] = node_dir + os.pathsep + os.environ.get("PATH", "")
        os.environ.setdefault("EXECJS_RUNTIME", "Node")
        return node_exe
    # Dev / system-Node fallback: still pin the runtime to Node if present.
    os.environ.setdefault("EXECJS_RUNTIME", "Node")
    return ""
