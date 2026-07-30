# coding: utf-8
"""Use the already logged-in desktop Edge window as the final comment channel.

Why this exists:
    The spider/API cookie cache can read Douyin pages and comments, but recent
    web comment writes may be gated by the *interactive* passport state that only
    exists inside the user's normal Edge session.  This module deliberately uses
    that visible session instead of forcing another QR login in the isolated
    Playwright profile.

It is intentionally conservative: one target video per call, paste text from the
clipboard, click the visible send button, then save a screenshot as proof.
"""

import os
import re
import subprocess
import time
from typing import Dict

from runtime_paths import agent_data_dir


def _agent_data_dir() -> str:
    data_dir = os.getenv("MATRIX_AGENT_DATA_DIR") or os.getenv("DY_DATA_DIR")
    if data_dir:
        return os.path.abspath(os.path.expandvars(data_dir))
    return agent_data_dir()


DATA_DIR = _agent_data_dir()


def _clean_id(value: str) -> str:
    m = re.search(r"(\d{10,})", str(value or ""))
    return m.group(1) if m else str(value or "").strip()


def _shot_path(prefix: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, "%s_%d.png" % (prefix, int(time.time())))


def _find_edge_window(gw):
    wins = []
    for w in gw.getAllWindows():
        title = w.title or ""
        if "Edge" not in title:
            continue
        # Ignore minimized/tool windows.
        if getattr(w, "width", 0) < 500 or getattr(w, "height", 0) < 500:
            continue
        wins.append(w)
    # Prefer a window that is already on Douyin, otherwise use the largest Edge.
    douyin = [w for w in wins if ("\u6296\u97f3" in (w.title or "") or "douyin" in (w.title or "").lower())]
    if douyin:
        return sorted(douyin, key=lambda w: w.width * w.height, reverse=True)[0]
    if wins:
        return sorted(wins, key=lambda w: w.width * w.height, reverse=True)[0]
    return None


def _activate_window(w):
    try:
        if getattr(w, "isMinimized", False):
            w.restore()
    except Exception:
        pass
    try:
        w.activate()
    except Exception:
        pass
    time.sleep(0.6)
    return w


def _open_edge(url: str):
    edge = os.getenv("DY_EDGE_PATH", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if os.path.exists(edge):
        subprocess.Popen([edge, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.startfile(url)  # noqa: S606 - user-requested desktop automation


def send_comment_via_edge_ui(aweme_id: str, content: str, reply_id: str = "", wait_sec: float = 7.0) -> Dict:
    """Send one comment through the user's visible Edge Douyin session.

    Returns a serializable dict.  The method is top-level-comment oriented; when
    reply_id is supplied we record that it was not used because reliable reply
    targeting requires DOM/CDP access to the normal Edge profile.
    """
    aweme_id = _clean_id(aweme_id)
    content = str(content or "").strip()
    if not aweme_id:
        return {"ok": False, "error": "missing_aweme_id", "channel": "edge-ui"}
    if not content:
        return {"ok": False, "error": "missing_content", "channel": "edge-ui"}

    try:
        import pyautogui
        import pygetwindow as gw
        import pyperclip
    except Exception as e:
        return {"ok": False, "error": "desktop_automation_unavailable", "detail": str(e), "channel": "edge-ui"}

    url = "https://www.douyin.com/video/%s" % aweme_id
    shot = ""
    try:
        w = _find_edge_window(gw)
        if not w:
            _open_edge(url)
            time.sleep(4)
            w = _find_edge_window(gw)
        if not w:
            return {"ok": False, "error": "edge_window_not_found", "channel": "edge-ui"}

        _activate_window(w)

        # Always navigate the existing logged-in Edge session to the target.
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.15)
        pyperclip.copy(url)
        pyautogui.hotkey("ctrl", "v")
        pyautogui.press("enter")
        time.sleep(max(3.0, float(wait_sec)))

        # On the PC detail page, the comment counter row is below the video.
        # Coordinates are relative to the current Edge window so they adapt to
        # common snapped/maximized layouts.
        left, top, width, height = int(w.left), int(w.top), int(w.width), int(w.height)
        comment_x = left + max(120, min(int(width * 0.21), width - 80))
        comment_y = top + max(420, min(int(height * 0.745), height - 120))
        pyautogui.click(comment_x, comment_y)
        time.sleep(2.0)

        # Comment input is displayed near the top of the comments panel.
        input_x = left + max(170, min(int(width * 0.42), width - 120))
        input_y = top + max(250, min(int(height * 0.325), height - 120))
        send_x = left + width - 38
        send_y = input_y

        pyautogui.click(input_x, input_y)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        pyperclip.copy(content)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.6)
        pyautogui.click(send_x, send_y)
        time.sleep(3.0)

        shot = _shot_path("edge_ui_comment_sent")
        pyautogui.screenshot().save(shot)
        return {
            "ok": True,
            "channel": "edge-ui",
            "awemeId": aweme_id,
            "content": content,
            "replyIdIgnored": bool(str(reply_id or "").strip()),
            "screenshot": shot,
            "verification": "visible_edge_screenshot",
        }
    except Exception as e:
        try:
            if not shot:
                shot = _shot_path("edge_ui_comment_error")
                pyautogui.screenshot().save(shot)
        except Exception:
            shot = ""
        return {"ok": False, "error": str(e), "channel": "edge-ui", "screenshot": shot}
