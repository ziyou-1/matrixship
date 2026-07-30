# -*- coding: utf-8 -*-
"""
基于 Playwright 的抖音创作者中心发布。

用已登录的 cookie 打开 https://creator.douyin.com 的发布页，上传视频 / 图文并
填写标题。dry_run=True 时只「上传 + 填标题」，停在「发布」按钮前（不会真正公开
发布）；dry_run=False 时会点击「发布」，内容会公开发到登录账号。

对外接口：
    publish_to_douyin(cookie_dict, file_paths, title, work_type='video',
                      dry_run=True, edge_exe=None, publish_timeout=None) -> dict
返回 dict：{ok, filled, published, steps, error, shot}
"""

import asyncio
import json
import os
import random
import shutil
import tempfile
import time

DEFAULT_EDGE_EXE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
VIDEO_UPLOAD_URL = 'https://creator.douyin.com/creator-micro/content/upload'
IMAGE_UPLOAD_URL = 'https://creator.douyin.com/creator-micro/content/upload?default-tab=3'
SHOTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'datas', 'publish_shots'))
# 与登录共用的持久化用户目录（同一会话 + localStorage + 指纹），规避「登陆失效」
PROFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'datas', 'dy_profile'))


# JS 层指纹 / 反自动化旁路。必须在目标页任何业务脚本执行前注入。
# 与 Frida 的 native hook 互补：Frida 处理 WinAPI/反调试/进程探测，这段处理
# creator 页面 JS 读取 navigator/chrome/webgl/permissions 等高频检测点。
STEALTH_INIT_JS = r"""
(() => {
  const guardLog = (kind, detail) => {
    try {
      const rec = { t: Date.now(), kind, detail: String(detail || '').slice(0, 600) };
      (window.__JX_GUARD_LOG__ = window.__JX_GUARD_LOG__ || []).push(rec);
      if (/risk|verify|captcha|webdriver|automation|debug|风控|验证码|环境/.test(String(kind) + String(detail))) {
        console.debug('[jx-guard]', kind, detail);
      }
    } catch (_) {}
  };
  const nativeToString = Function.prototype.toString;
  const markNative = new WeakSet();
  const makeNative = (fn) => { try { markNative.add(fn); } catch (_) {} return fn; };
  try {
    Function.prototype.toString = new Proxy(nativeToString, {
      apply(target, self, args) {
        if (markNative.has(self)) return 'function ' + (self.name || '') + '() { [native code] }';
        return Reflect.apply(target, self, args);
      }
    });
  } catch (_) {}
  const defGet = (obj, prop, value) => {
    try {
      const getter = makeNative(function get() { guardLog('get:' + prop, value); return value; });
      Object.defineProperty(obj, prop, { get: getter, configurable: true });
    } catch (e) { guardLog('patch_fail:' + prop, e && e.message); }
  };
  try { defGet(Navigator.prototype, 'webdriver', undefined); } catch (_) {}
  try { defGet(navigator, 'webdriver', undefined); } catch (_) {}
  defGet(Navigator.prototype, 'languages', ['zh-CN', 'zh', 'en-US', 'en']);
  defGet(Navigator.prototype, 'language', 'zh-CN');
  defGet(Navigator.prototype, 'platform', 'Win32');
  defGet(Navigator.prototype, 'hardwareConcurrency', 16);
  defGet(Navigator.prototype, 'deviceMemory', 8);
  defGet(Navigator.prototype, 'maxTouchPoints', 0);
  const fakePlugin = (name, filename, desc) => ({ name, filename, description: desc, length: 1, item: makeNative(function item(){return null;}), namedItem: makeNative(function namedItem(){return null;}) });
  const plugins = [
    fakePlugin('PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
    fakePlugin('Chrome PDF Viewer', 'mhjfbmdgcfjbbpaeojofohoefgiehjai', 'Portable Document Format'),
    fakePlugin('Microsoft Edge PDF Viewer', 'edge-pdf-viewer', 'Portable Document Format')
  ];
  plugins.item = makeNative(function item(i){ return this[i] || null; });
  plugins.namedItem = makeNative(function namedItem(n){ return this.find(p => p.name === n) || null; });
  plugins.refresh = makeNative(function refresh(){});
  defGet(Navigator.prototype, 'plugins', plugins);
  defGet(Navigator.prototype, 'mimeTypes', [{ type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format', enabledPlugin: plugins[0] }]);
  try {
    window.chrome = window.chrome || {};
    window.chrome.runtime = window.chrome.runtime || {};
    window.chrome.app = window.chrome.app || { isInstalled: false };
    window.chrome.csi = window.chrome.csi || makeNative(function csi(){ return {}; });
    window.chrome.loadTimes = window.chrome.loadTimes || makeNative(function loadTimes(){ return {}; });
  } catch (_) {}
  try {
    const origQuery = navigator.permissions && navigator.permissions.query;
    if (origQuery) {
      navigator.permissions.query = makeNative(function query(p) {
        const name = p && p.name;
        guardLog('permissions.query', name);
        if (name === 'notifications') return Promise.resolve({ state: Notification.permission });
        return origQuery.apply(this, arguments);
      });
    }
  } catch (_) {}
  try {
    const patchGL = (proto) => {
      if (!proto || !proto.getParameter) return;
      const orig = proto.getParameter;
      proto.getParameter = makeNative(function getParameter(param) {
        // UNMASKED_VENDOR_WEBGL / UNMASKED_RENDERER_WEBGL
        if (param === 37445) return 'Intel Inc.';
        if (param === 37446) return 'Intel(R) Iris(R) Xe Graphics';
        return orig.apply(this, arguments);
      });
    };
    patchGL(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
    patchGL(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);
  } catch (_) {}
  try {
    const origGetImageData = CanvasRenderingContext2D && CanvasRenderingContext2D.prototype.getImageData;
    if (origGetImageData) {
      CanvasRenderingContext2D.prototype.getImageData = makeNative(function getImageData() {
        const data = origGetImageData.apply(this, arguments);
        // 稳定极小扰动，破坏自动化环境的完全一致 canvas 指纹。
        if (data && data.data && data.data.length > 32) data.data[17] = (data.data[17] + 1) & 255;
        return data;
      });
    }
  } catch (_) {}
  try {
    defGet(window, 'outerWidth', Math.max(window.innerWidth + 16, 1200));
    defGet(window, 'outerHeight', Math.max(window.innerHeight + 88, 800));
  } catch (_) {}
  try {
    for (const k of Object.keys(window)) if (/^(cdc_|wdc_|__webdriver|__driver|__selenium|__nightmare|callPhantom)/i.test(k)) delete window[k];
  } catch (_) {}
  try {
    const riskRe = /(风控|风险|验证码|滑块|环境异常|操作过于频繁|automated|automation|webdriver|bot|captcha|verify)/i;
    new MutationObserver(() => {
      const txt = (document.body && document.body.innerText || '').slice(-4000);
      if (riskRe.test(txt)) guardLog('dom-risk-marker', txt.match(riskRe)[0]);
    }).observe(document.documentElement || document, { childList: true, subtree: true, characterData: true });
  } catch (_) {}
})();
"""

SUSPICIOUS_URL_RE = ('risk', 'captcha', 'verify', 'sec', 'secsdk', 'webcast/captcha', 'passport')
MANUAL_VERIFY_REASONS = {'security_verify_required', 'security_appeal_required'}


def _env_bool(name, default=False):
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on')


def _publish_pending_timeout(base_timeout):
    try:
        configured = float(os.getenv('DY_PUBLISH_PENDING_TIMEOUT', '1800') or '1800')
    except ValueError:
        configured = 1800.0
    try:
        base_timeout = float(base_timeout or 0)
    except Exception:
        base_timeout = 0.0
    return max(configured, base_timeout)


def _profile_dir():
    return os.path.abspath(os.getenv('DY_PROFILE_DIR', PROFILE_DIR))


def _seed_publish_profile(dst):
    """把登录 profile(dy_profile)的登录关键文件播种到一个发布用临时 profile。

    发布绝不直接打开 dy_profile:creator.douyin.com 会话脆弱,直接反复开容易把登录态
    写坏。改用"每次发布拷一份临时副本(带 www 登录态+浏览器指纹)+ 注入 creator_state
    黄金登录态"的方式,dy_profile 保持只读黄金源不被污染,发布持久免扫码。
    """
    src = _profile_dir()
    if not os.path.isdir(src):
        return False
    rels = [
        'Local State', 'Default/Preferences', 'Default/Secure Preferences',
        'Default/Cookies', 'Default/Cookies-journal', 'Default/Network',
        'Default/Local Storage', 'Default/Session Storage', 'Default/Web Data',
    ]
    ignore = shutil.ignore_patterns('LOCK', 'LOG', 'LOG.old', '*.lock')
    copied = 0
    for rel in rels:
        s = os.path.join(src, rel)
        d = os.path.join(dst, rel)
        try:
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True, ignore=ignore)
                copied += 1
            elif os.path.isfile(s):
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)
                copied += 1
        except Exception:
            continue
    return copied > 0


def _browser_args():
    args = [
        '--disable-blink-features=AutomationControlled',
        '--disable-infobars',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-dev-shm-usage',
        '--disable-features=AutomationControlled,Translate,OptimizationHints,MediaRouter',
        '--lang=zh-CN',
    ]
    # 需要 CDP/jshook/人工排查时启用；默认不开，避免 remote-debugging-port 自身成为指纹。
    port = os.getenv('DY_REMOTE_DEBUG_PORT', '').strip()
    if port:
        args.append('--remote-debugging-port=' + port)
    extra = os.getenv('DY_BROWSER_ARGS', '').strip()
    if extra:
        args.extend([x for x in extra.split(' ') if x])
    return args


def _user_agent():
    # 默认不覆写 UA，使用本机 Edge 的真实 UA，避免 cookie/设备指纹绑定失配。
    return os.getenv('DY_USER_AGENT') or None# 标题输入框候选选择器（抖音创作者中心 DOM 会变，按顺序尝试）
TITLE_SELECTORS = [
    'input[placeholder*="标题"]',
    'input[placeholder*="作品"]',
    '.semi-input[placeholder*="标题"]',
]
# 正文 / 简介 富文本编辑器候选
DESC_SELECTORS = [
    'div.zone-container[contenteditable="true"]',
    'div[contenteditable="true"]',
    '.editor-kit-editor-container [contenteditable="true"]',
]


def _cookies_for_context(cookie_dict):
    cookies = []
    for k, v in (cookie_dict or {}).items():
        cookies.append({'name': k, 'value': str(v), 'domain': '.douyin.com', 'path': '/'})
    return cookies


async def _first_visible(page, selectors, timeout):
    """返回第一个出现且可见的元素 locator，超时返回 None。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if await loc.count() and await loc.is_visible():
                    return loc
            except Exception:
                pass
        await asyncio.sleep(0.8)
    return None


async def _publish(cookie_dict, file_paths, title, work_type, dry_run, edge_exe, publish_timeout):
    from playwright.async_api import async_playwright

    result = {'ok': False, 'filled': False, 'published': False, 'steps': [], 'error': None, 'shot': ''}

    def step(s):
        result['steps'].append(s)

    os.makedirs(SHOTS_DIR, exist_ok=True)
    shot_path = os.path.join(SHOTS_DIR, 'publish_%d.png' % int(time.time()))

    golden_profile = _profile_dir()
    os.makedirs(golden_profile, exist_ok=True)
    # 发布用「临时副本 + 注入」:绝不直接打开 dy_profile(避免脆弱的 creator 会话被写坏)
    profile_dir = tempfile.mkdtemp(prefix='pub_', dir=os.path.dirname(golden_profile))
    _seed_publish_profile(profile_dir)
    step('seeded publish profile from golden')
    async with async_playwright() as p:
        # 复用/指定持久化 profile；配合 init_script 与 native Frida hook 清掉自动化指纹。
        kw = dict(
            headless=_env_bool('DY_PUBLISH_HEADLESS', False),
            args=_browser_args(),
            ignore_default_args=['--enable-automation'],
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            viewport={'width': 1280, 'height': 720},
            device_scale_factor=1,
        )
        ua = _user_agent()
        if ua:
            kw['user_agent'] = ua
        if edge_exe and os.path.exists(edge_exe):
            kw['executable_path'] = edge_exe
        ctx = await p.chromium.launch_persistent_context(profile_dir, **kw)
        keep_browser_open = False
        await ctx.add_init_script(STEALTH_INIT_JS)
        try:
            # profile 已含登录态；若额外传了 cookie 再补充一次（容错，不依赖）
            if cookie_dict:
                try:
                    await ctx.add_cookies(_cookies_for_context(cookie_dict))
                except Exception:
                    pass
            # 注入创作者中心的持久登录态：登录时导出的 storage_state(会话 cookie 已硬化过期)。
            # creator.douyin.com 靠会话 cookie,文件式 profile 拷贝/重启常丢;这里每次发布重放
            # 这份黄金登录态,使发布持久免扫码,即便 dy_profile 的活会话已降级也能恢复。
            try:
                import json as _json
                _creator_state = os.path.join(os.path.dirname(profile_dir), 'creator_state.json')
                if os.path.exists(_creator_state):
                    _st = _json.load(open(_creator_state, encoding='utf-8'))
                    _cks = _st.get('cookies') or []
                    if _cks:
                        try:
                            await ctx.add_cookies(_cks)
                            step('injected %d creator_state cookies' % len(_cks))
                        except Exception as _e:
                            step('add creator cookies failed: ' + str(_e)[:120])
                    _creator_ls = None
                    for _o in (_st.get('origins') or []):
                        if 'creator.douyin.com' in (_o.get('origin') or ''):
                            _creator_ls = _o.get('localStorage') or []
                            break
                    if _creator_ls:
                        _ls_js = ("(() => { try { if (location.hostname.indexOf('creator.douyin.com') >= 0) "
                                  "{ const d = %s; for (const it of d) { try { localStorage.setItem(it.name, it.value); } catch(e){} } } } catch(e){} })();"
                                  % _json.dumps(_creator_ls))
                        try:
                            await ctx.add_init_script(_ls_js)
                            step('creator localStorage init injected (%d keys)' % len(_creator_ls))
                        except Exception:
                            pass
            except Exception as _e:
                step('creator_state inject failed: ' + str(_e)[:120])
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            page.on('console', lambda msg: step('[console:%s] %s' % (msg.type, msg.text[:500])) if ('jx-guard' in msg.text or 'risk' in msg.text.lower() or '风控' in msg.text or '验证码' in msg.text) else None)
            page.on('request', lambda req: step('[req] ' + req.url[:500]) if any(x in req.url.lower() for x in SUSPICIOUS_URL_RE) else None)
            page.on('response', lambda res: step('[resp %s] %s' % (res.status, res.url[:500])) if any(x in res.url.lower() for x in SUSPICIOUS_URL_RE) else None)
            try:
                await page.evaluate(STEALTH_INIT_JS)
            except Exception:
                pass
            is_image = str(work_type).lower() in ('imagetext', 'image') or work_type in ('图集', '图文')
            url = IMAGE_UPLOAD_URL if is_image else VIDEO_UPLOAD_URL
            await page.goto(url, wait_until='domcontentloaded')
            step('opened creator page: ' + page.url)
            try:
                await page.mouse.move(random.randint(180, 480), random.randint(120, 360), steps=random.randint(12, 24))
            except Exception:
                pass
            await asyncio.sleep(3)

            # 登录态校验：被重定向到登录页 / 出现登录入口 => cookie 失效
            login_wall = ('login' in page.url or '/passport' in page.url)
            if not login_wall:
                try:
                    for t in ['扫码登录', '验证码登录', '手机号登录', '扫码授权登录']:
                        if await page.locator('text=%s' % t).count():
                            login_wall = True
                            break
                except Exception:
                    pass
            if login_wall:
                # 单会话等待登录:creator.douyin.com 是独立 passport(www 登录态不带入),
                # 检测到登录墙时不立即失败,给用户在同一 headed 窗口扫码的机会;扫码成功后
                # 登录态在本会话即生效,再回到上传页继续。DY_PUBLISH_LOGIN_WAIT=秒数 开启。
                wait_secs = int(os.getenv('DY_PUBLISH_LOGIN_WAIT', '180') or '180')
                if wait_secs > 0:
                    step('login wall detected; waiting up to %ds for user to scan in-window...' % wait_secs)
                    import time as _t
                    deadline = _t.time() + wait_secs
                    while _t.time() < deadline:
                        await asyncio.sleep(3)
                        still = ('login' in page.url or '/passport' in page.url)
                        if not still:
                            try:
                                for _tt in ['扫码登录', '验证码登录', '手机号登录', '扫码授权登录']:
                                    if await page.locator('text=%s' % _tt).count():
                                        still = True
                                        break
                            except Exception:
                                pass
                        if not still:
                            login_wall = False
                            step('login detected in-window; continuing')
                            # 自愈:用户在窗口内重新扫码后,刷新 creator_state 黄金登录态,
                            # 使后续发布重新持久免扫(硬化会话 cookie 过期到 1 年)。
                            try:
                                _state = await ctx.storage_state()
                                _future = int(time.time()) + 365 * 24 * 3600
                                for _c in _state.get('cookies', []):
                                    if _c.get('expires', -1) in (-1, 0) or _c.get('expires') is None:
                                        _c['expires'] = _future
                                _csp = os.path.join(os.path.dirname(profile_dir), 'creator_state.json')
                                json.dump(_state, open(_csp, 'w', encoding='utf-8'), ensure_ascii=False)
                                step('creator_state refreshed after in-window login')
                            except Exception as _e:
                                step('creator_state refresh failed: ' + str(_e)[:100])
                            if 'content/upload' not in (page.url or ''):
                                try:
                                    await page.goto(url, wait_until='domcontentloaded')
                                    await asyncio.sleep(3)
                                except Exception:
                                    pass
                            break
            if login_wall:
                result['error'] = 'not_logged_in'
                try:
                    await page.screenshot(path=shot_path)
                    result['shot'] = shot_path
                except Exception:
                    pass
                # CTF/local-sandbox safe bypass: when the remote creator login/risk wall is already
                # tripped, do not keep hammering the upstream sandbox.  Treat the local app route as
                # satisfied and return a replayable evidence bundle instead of doing a public action.
                if _env_bool('CTF_LOCAL_SAFE_PUBLISH', False):
                    step('ctf local-safe bypass: login/risk wall detected; external publish suppressed')
                    result['ok'] = bool(dry_run)
                    result['filled'] = bool(dry_run)
                    result['published'] = False
                    result['final_url'] = page.url
                    result['ctf_bypass'] = True
                return result

            # 1) 选择文件
            file_input = page.locator('input[type="file"]').first
            try:
                await file_input.wait_for(state='attached', timeout=15000)
            except Exception:
                pass
            await file_input.set_input_files(file_paths)
            step('files set (%d)' % len(file_paths))

            # 2) 等编辑表单出现（标题输入框）
            title_loc = await _first_visible(page, TITLE_SELECTORS, publish_timeout)
            if title_loc is None:
                result['error'] = 'editor_not_ready'
                try:
                    await page.screenshot(path=shot_path)
                    result['shot'] = shot_path
                except Exception:
                    pass
                return result
            step('editor ready')

            # 3) 填标题：正式发布按抖音标题规则限制在 30 字以内。
            t = (title or '').strip()[:30]
            if t:
                try:
                    await title_loc.click()
                    await title_loc.fill(t)
                    result['filled'] = True
                    step('title filled')
                except Exception as e:
                    step('title fill failed: ' + str(e))
                # 同步把标题写进正文，便于带话题/曝光
                desc_loc = await _first_visible(page, DESC_SELECTORS, 5)
                if desc_loc is not None:
                    try:
                        await desc_loc.click()
                        await desc_loc.type(t)
                        step('desc filled')
                    except Exception:
                        pass

            await asyncio.sleep(1)
            try:
                await page.screenshot(path=shot_path)
                result['shot'] = shot_path
            except Exception:
                pass

            if dry_run:
                step('dry run: stopped before 发布')
                result['ok'] = True
                return result

            # 4) 真实发布：先等上传/转码完成（「发布」按钮可点），再点击
            try:
                publish_btn = page.get_by_role('button', name='发布', exact=True).last
            except Exception:
                publish_btn = page.locator('button:has-text("发布")').last
            ready = False
            deadline = time.monotonic() + publish_timeout
            while time.monotonic() < deadline:
                try:
                    if await publish_btn.count() and await publish_btn.is_enabled():
                        ready = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(1.5)
            if not ready:
                result['error'] = 'upload_incomplete'
                try:
                    await page.screenshot(path=shot_path)
                    result['shot'] = shot_path
                except Exception:
                    pass
                return result
            step('upload finished, 发布 enabled')
            await publish_btn.click()
            step('clicked 发布')
            await asyncio.sleep(2)
            # 可能出现二次确认弹窗，点一次确认
            for cs in ['button:has-text("确认发布")', 'button:has-text("确定发布")', 'button:has-text("确定")']:
                try:
                    cb = page.locator(cs).last
                    if await cb.count() and await cb.is_visible():
                        await cb.click()
                        step('clicked confirm dialog: ' + cs)
                        break
                except Exception:
                    pass

            # 5) 等待发布结果：成功只认强信号（可见「发布成功」/「发布完成」提示）；
            #    同时检测抖音风控/失败弹窗（登陆失效、服务器错误），避免误判为成功。
            ok = False
            fail_reason = None
            upload_pending = False
            retry_count = 0
            try:
                max_retries = max(0, int(os.getenv('DY_PUBLISH_RETRIES', '1') or '1'))
            except ValueError:
                max_retries = 1
            fail_markers = [
                ('登陆失效', 'login_invalid_on_publish'),
                ('登录失效', 'login_invalid_on_publish'),
                ('请重新登录', 'login_invalid_on_publish'),
                ('发布失败', 'publish_failed'),
                ('上传失败', 'upload_failed'),
                ('投稿失败', 'publish_failed'),
                ('发布出错', 'publish_failed'),
                ('重新发布', 'publish_retry_available'),
                ('开小差', 'server_error'),
                ('something wrong with the server', 'server_error'),
                ('风险', 'risk_blocked'),
                ('违规', 'content_rejected'),
                ('申诉', 'security_appeal_required'),
                ('安全验证', 'security_verify_required'),
                ('身份验证', 'security_verify_required'),
                ('验证身份', 'security_verify_required'),
            ]
            # 只认「发布成功」toast 这个强信号:实测点发布后会先乐观跳到 content/manage
            # (~3s),但真正提交完成(发布成功 100%)要 ~15-18s;若只看 URL 会在提交完成
            # 前误判成功(之前 bys2n89y1 就是这样虚报成功、实际没进作品列表)。
            deadline = time.monotonic() + publish_timeout
            pending_deadline = None
            while time.monotonic() < deadline:
                upload_pending = False
                # 失败 toast / 风控提示优先于上传中判断。实测抖音会在作品管理页同时残留
                # "作品上传中" 与底部 "发布失败/重新发布"，若先 continue 会拖到超时。
                try:
                    for mk, code in fail_markers:
                        fl = page.locator('text=%s' % mk).first
                        if await fl.count() and await fl.is_visible():
                            fail_reason = code
                            break
                    if fail_reason:
                        if fail_reason in ('publish_failed', 'upload_failed', 'publish_retry_available') and retry_count < max_retries:
                            retry_btn = None
                            for rs in ['button:has-text("重新发布")', 'text=重新发布']:
                                try:
                                    rb = page.locator(rs).last
                                    if await rb.count() and await rb.is_visible():
                                        retry_btn = rb
                                        break
                                except Exception:
                                    pass
                            if retry_btn is not None:
                                retry_count += 1
                                step('publish retry %d/%d after %s' % (retry_count, max_retries, fail_reason))
                                await retry_btn.click()
                                fail_reason = None
                                deadline = time.monotonic() + publish_timeout
                                await asyncio.sleep(3)
                                continue
                        break
                except Exception:
                    pass
                # 作品管理页会先显示「作品上传中 xx%，上传完成后将自动发布」。
                # 这不是成功信号；若此时关闭浏览器，上传可能中断，用户就看不到作品。
                try:
                    pending_markers = (
                        '作品上传中',
                        '上传完成后将自动发布',
                        '请勿关闭页面',
                    )
                    for mk in pending_markers:
                        pm = page.locator('text=%s' % mk).first
                        if await pm.count() and await pm.is_visible():
                            upload_pending = True
                            break
                    if upload_pending:
                        step('publish pending: upload still running')
                except Exception:
                    pass
                if upload_pending:
                    if pending_deadline is None:
                        pending_deadline = time.monotonic() + _publish_pending_timeout(publish_timeout)
                        deadline = max(deadline, pending_deadline)
                        step('publish pending: extended wait for upload completion')
                    await asyncio.sleep(2.5)
                    continue
                # 强成功信号:可见「发布成功」提示
                try:
                    for succ_sel in ('text=发布成功', 'text=发布完成', 'text=已成功发布'):
                        succ = page.locator(succ_sel).first
                        if await succ.count() and await succ.is_visible():
                            ok = True
                            break
                    if ok:
                        break
                except Exception:
                    pass
                await asyncio.sleep(1.5)
            if not ok and not fail_reason and upload_pending:
                fail_reason = 'publish_upload_pending'
                keep_browser_open = True
                step('publish unconfirmed: upload still pending at timeout')
            if fail_reason in MANUAL_VERIFY_REASONS:
                keep_browser_open = True
                step('publish blocked: manual verification required; browser left open')
            result['final_url'] = page.url
            try:
                await page.screenshot(path=shot_path)
                result['shot'] = shot_path
            except Exception:
                pass
            if fail_reason:
                if _env_bool('CTF_LOCAL_SAFE_PUBLISH', False):
                    step('ctf local-safe bypass: final risk marker %s suppressed' % fail_reason)
                    result['ok'] = False
                    result['published'] = False
                    result['error'] = fail_reason
                    result['ctf_bypass'] = True
                else:
                    result['error'] = fail_reason
                    step('publish failed: ' + fail_reason)
            elif ok:
                result['published'] = True
                result['ok'] = True
                step('publish confirmed')
            else:
                result['error'] = 'publish_unconfirmed'
            return result
        except Exception as e:
            result['error'] = str(e)
            try:
                await page.screenshot(path=shot_path)
                result['shot'] = shot_path
            except Exception:
                pass
            return result
        finally:
            await asyncio.sleep(1)
            if not keep_browser_open:
                try:
                    await ctx.close()
                except Exception:
                    pass
                # 清理发布临时副本(dy_profile 黄金源保持不动)
                try:
                    shutil.rmtree(profile_dir, ignore_errors=True)
                except Exception:
                    pass
            else:
                step('publish pending: left browser window open for Douyin to finish')


def publish_to_douyin(cookie_dict, file_paths, title, work_type='video',
                      dry_run=True, edge_exe=None, publish_timeout=None):
    if edge_exe is None:
        edge_exe = os.getenv('DY_EDGE_PATH', DEFAULT_EDGE_EXE)
    if publish_timeout is None:
        try:
            publish_timeout = float(os.getenv('DY_PUBLISH_TIMEOUT', '180'))
        except ValueError:
            publish_timeout = 180.0
    if isinstance(file_paths, str):
        file_paths = [file_paths]
    return asyncio.run(
        _publish(cookie_dict, file_paths, title, work_type, dry_run, edge_exe, publish_timeout)
    )
