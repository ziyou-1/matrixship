# -*- coding: utf-8 -*-
"""一次性登录抖音创作者中心(creator.douyin.com)。

www.douyin.com 的登录态不会自动带入 creator.douyin.com(独立 passport aid=2906),
发布视频必须在 creator 单独登录一次。这里用与发布/主登录共用的持久化 profile
(DY_PROFILE_DIR)打开 creator 登录页,用户扫码后登录态即写入该 profile,后续
publish_to_douyin 复用同一 profile 便无需再扫。

用法: python creator_login.py    (会弹出 Edge 窗口显示二维码，扫码后自动检测成功并关闭)
"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from runtime_paths import ensure_agent_data_dir

DATA_DIR = ensure_agent_data_dir(migrate_legacy=True)
PROFILE = os.path.abspath(os.getenv('DY_PROFILE_DIR', os.path.join(DATA_DIR, 'dy_profile')))
EDGE = os.getenv('DY_EDGE_PATH', r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
RESULT = os.path.join(DATA_DIR, 'creator_login_result.json')
# 登录成功后导出的持久登录态(cookie+localStorage);发布时重新注入以规避会话 cookie 易失
CREATOR_STATE = os.path.join(DATA_DIR, 'creator_state.json')
LOGIN_WALL = ['扫码登录', '验证码登录', '手机号登录', '扫码授权登录', '登录/注册']


def _write(res):
    try:
        json.dump(res, open(RESULT, 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception:
        pass


def main():
    from playwright.sync_api import sync_playwright
    timeout = int(os.getenv('CREATOR_LOGIN_TIMEOUT', '240') or '240')
    _write({'status': 'waiting', 'startedAt': int(time.time())})
    with sync_playwright() as p:
        kw = dict(headless=False,
                  args=['--no-sandbox', '--disable-blink-features=AutomationControlled',
                        '--disable-infobars', '--no-first-run', '--no-default-browser-check', '--lang=zh-CN'],
                  ignore_default_args=['--enable-automation'], locale='zh-CN',
                  timezone_id='Asia/Shanghai', viewport={'width': 1180, 'height': 820})
        if os.path.exists(EDGE):
            kw['executable_path'] = EDGE
        ctx = p.chromium.launch_persistent_context(PROFILE, **kw)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto('https://creator.douyin.com/', wait_until='domcontentloaded', timeout=45000)
        except Exception:
            pass
        ok = False
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(3)
            try:
                body = page.content()
            except Exception:
                continue
            url = page.url or ''
            wall = any(t in body for t in LOGIN_WALL)
            # 登录成功信号：进入 creator-micro 工作台 / 出现「发布视频」「作品管理」等，且登录墙消失
            entered = ('creator-micro' in url) or any(t in body for t in ['发布视频', '作品管理', '内容管理', '创作灵感'])
            if entered and not wall:
                ok = True
                break
        saved_state = False
        if ok:
            # 导出 storage_state(含 creator 会话 cookie + localStorage),并把会话 cookie
            # (无过期时间)的过期时间硬化成 1 年后,使其可跨浏览器重启/重放持久生效。
            try:
                time.sleep(2)  # 给页面写完登录态一点时间
                state = ctx.storage_state()
                future = int(time.time()) + 365 * 24 * 3600
                for c in state.get('cookies', []):
                    exp = c.get('expires', -1)
                    if exp in (-1, 0) or exp is None:
                        c['expires'] = future
                json.dump(state, open(CREATOR_STATE, 'w', encoding='utf-8'), ensure_ascii=False)
                saved_state = True
            except Exception as e:
                print('CREATOR_STATE_SAVE_ERR ' + str(e))
        result = {'status': 'success' if ok else 'timeout', 'url': (page.url or '')[:120],
                  'finishedAt': int(time.time()), 'savedState': saved_state, 'statePath': CREATOR_STATE}
        _write(result)
        print('CREATOR_LOGIN_RESULT ' + json.dumps(result, ensure_ascii=False))
        time.sleep(1)
        ctx.close()


if __name__ == '__main__':
    main()
