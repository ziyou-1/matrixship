# -*- coding: utf-8 -*-
"""测试套件护栏:任何测试都不许拉起真实浏览器。

为什么需要它
------------
`publish_comment_to_douyin` 通往可见浏览器有**两条**独立的路:

  1. preflight 之前 —— `browser_comment_preflight()` (api_server.py:4414)
  2. 发布失败之后 —— `should_edge_ui_fallback()` → `publish_comment_via_cloud_ui()`
     → `CloudLoginSession(headless=False)` (api_server.py:4684 → :4543)

测试作者很自然地只 mock 掉第 1 条(preflight),第 2 条却在
`status_code` 为 8/9(平台风控)时照样触发。于是测试是绿的,屏幕上却弹出
真实的抖音窗口,还用的是 `backend/datas/cloud_profiles/` 里的真账号 profile。

这个模块在**任何测试模块被导入之前**执行(unittest 先导入 tests 包),把
Playwright 的入口换成抛异常,并让抢占本机 Edge 的桌面自动化直接短路。
调用链照常跑完,断言语义不变,只是永远开不出窗口。

需要真浏览器时(极少数手工验证),设 MATRIX_TESTS_ALLOW_REAL_BROWSER=1 绕过。
"""

import os
import sys
import traceback
from pathlib import Path

_OPT_OUT = (os.getenv("MATRIX_TESTS_ALLOW_REAL_BROWSER") or "").strip().lower()

if _OPT_OUT not in ("1", "true", "yes", "on"):

    _BACKEND = Path(__file__).resolve().parent.parent / "backend"
    if _BACKEND.is_dir() and str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))

    class RealBrowserBlockedInTests(RuntimeError):
        """测试里试图打开真实浏览器时抛出。"""

    def _blocker(what):
        def _raise(*args, **kwargs):
            # 指出是哪一行想开浏览器，方便直接定位到漏 mock 的测试。
            where = [
                line.strip()
                for line in traceback.format_stack()[:-1]
                if "tests" + os.sep in line or "backend" + os.sep in line
            ]
            sys.stderr.write(
                "\n[tests guard] 拦截真实浏览器启动: %s\n%s\n"
                "  该测试漏了 mock。参考 tests/test_douyin_comment_cooldown.py 里\n"
                "  对 publish_comment_via_cloud_ui / CloudLoginSession 的打桩写法。\n\n"
                % (what, "\n".join("    " + w for w in where[-3:]))
            )
            raise RealBrowserBlockedInTests(
                "%s blocked: tests must not open a real browser" % what
            )
        return _raise

    # Playwright:覆盖搜索、私信、preflight、云登录会话等所有启动点。
    # backend 里的 playwright 都是函数内导入，所以替换模块属性即可生效。
    try:
        import playwright.sync_api as _pw_sync
        _pw_sync.sync_playwright = _blocker("playwright.sync_playwright")
    except Exception:
        pass
    try:
        import playwright.async_api as _pw_async
        _pw_async.async_playwright = _blocker("playwright.async_playwright")
    except Exception:
        pass

    # 桌面自动化:这条会抢占用户正在用的 Edge 窗口并代为点击，比弹窗更糟。
    # api_server 在模块级 `from edge_ui_comment import ...`，而本文件先于它执行，
    # 所以在这里替换能被它的 import 取到。
    try:
        import edge_ui_comment as _edge

        def _blocked_edge_ui(*args, **kwargs):
            return {
                "ok": False,
                "error": "real_browser_blocked_in_tests",
                "channel": "edge-ui",
            }

        _edge.send_comment_via_edge_ui = _blocked_edge_ui
        _edge._open_edge = _blocker("edge_ui_comment._open_edge")
    except Exception:
        pass
