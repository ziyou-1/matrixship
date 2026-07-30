"""
基于 Playwright 的抖音登录态 / 票据采集。

通过驱动真实浏览器（Edge / Chromium）访问抖音页面，捕获登录后的
cookies、msToken、ttwid、webid，供爬虫与 API 服务复用。

对外稳定接口：
    get_new_cookies(...)  -> dict
    cookies_to_str(dict)  -> str

设计要点（相比早期版本的改进）：
  * 不再使用模块级全局变量保存结果，多次调用互不污染、可并发复用。
  * webid 的等待加入超时（默认 30s），headless / 沙箱环境下不会再无限挂起。
  * 即使没有抓到 webid 也会返回已采集到的 cookies（msToken / ttwid 等通常已足够）。
  * 浏览器可执行路径、headless、目标页、超时均可通过环境变量或入参覆盖。
"""

import asyncio
import os
from urllib.parse import urlparse, parse_qs
from runtime_paths import agent_data_dir

# 默认访问一个公开用户主页，加载时会自动触发 profile/other 接口（从中拿 webid）
DEFAULT_TARGET_URL = (
    'https://www.douyin.com/user/'
    'MS4wLjABAAAAEpmH344CkCw2M58T33Q8TuFpdvJsOyaZcbWxAMc6H03wOVFf1Ow4mPP94TDUS4Us'
)
DEFAULT_EDGE_EXE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
# 抖音主站负责搜索/评论/互动登录态，创作者中心负责发布能力。
#
# 产品上必须表现为“一次抖音账号授权”，不能让用户理解成多个入口分别登录。
# 正确实现是：一个账号一个持久化浏览器 Profile，先在主站完成登录，再用同一个
# Profile 访问创作者中心做能力预热。若平台触发二次校验，那是同一次授权流程里的
# step-up verification，不是第二套 Cookie。
DEFAULT_MAIN_LOGIN_URL = 'https://www.douyin.com/?recommend=1'
DEFAULT_CREATOR_LOGIN_URL = 'https://creator.douyin.com/creator-micro/content/upload'
# 默认先打开主站，保证评论/搜索/互动链路拿到真实登录态。
DEFAULT_LOGIN_URL = DEFAULT_MAIN_LOGIN_URL
# 持久化浏览器用户目录：商业本地 Agent 默认放到用户 AppData，避免多用户
# 或安装目录覆盖；设置 MATRIX_AGENT_PORTABLE=1 可退回项目 datas 便携模式。
def _default_profile_dir():
    data_dir = os.getenv('MATRIX_AGENT_DATA_DIR') or os.getenv('DY_DATA_DIR')
    if data_dir:
        return os.path.abspath(os.path.join(os.path.expandvars(data_dir), 'dy_profile'))
    return os.path.join(agent_data_dir(), 'dy_profile')


PROFILE_DIR = _default_profile_dir()


def _profile_dir():
    """发布/登录共用的持久化浏览器目录，可用 DY_PROFILE_DIR 覆盖。"""
    return os.path.abspath(os.getenv('DY_PROFILE_DIR', PROFILE_DIR))

LOGIN_STEALTH_INIT_JS = r"""
(() => {
  const def = (o, k, v) => { try { Object.defineProperty(o, k, { get: () => v, configurable: true }); } catch (_) {} };
  try { def(Navigator.prototype, 'webdriver', undefined); def(navigator, 'webdriver', undefined); } catch (_) {}
  def(Navigator.prototype, 'languages', ['zh-CN','zh','en-US','en']);
  def(Navigator.prototype, 'language', 'zh-CN');
  def(Navigator.prototype, 'platform', 'Win32');
  try { window.chrome = window.chrome || { runtime: {} }; window.chrome.runtime = window.chrome.runtime || {}; } catch (_) {}
})();
"""


def _browser_args():
    args = ['--disable-blink-features=AutomationControlled', '--disable-infobars', '--no-first-run', '--no-default-browser-check', '--lang=zh-CN']
    port = os.getenv('DY_REMOTE_DEBUG_PORT', '').strip()
    if port:
        args.append('--remote-debugging-port=' + port)
    extra = os.getenv('DY_BROWSER_ARGS', '').strip()
    if extra:
        args.extend([x for x in extra.split(' ') if x])
    return args


def _env_bool(name, default=False):
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on')


def _dedup_urls(urls):
    out = []
    seen = set()
    for url in urls:
        url = (url or '').strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _douyin_warmup_urls(primary_url=None):
    """URLs to visit with the same persistent profile after login.

    This is intentionally not a second login. It only lets Douyin's SSO/session
    materialize cookies/localStorage for both the main interaction surface and
    creator publishing surface.
    """
    extra = []
    env_extra = os.getenv('DY_WARMUP_URLS', '').strip()
    if env_extra:
        extra.extend([x.strip() for x in env_extra.split(',') if x.strip()])
    return _dedup_urls([
        primary_url,
        os.getenv('DY_INTERACT_URL') or DEFAULT_MAIN_LOGIN_URL,
        os.getenv('DY_CREATOR_URL') or DEFAULT_CREATOR_LOGIN_URL,
        DEFAULT_MAIN_LOGIN_URL,
        DEFAULT_CREATOR_LOGIN_URL,
        *extra,
    ])


def cookies_to_str(cookies_dict):
    """把 {name: value} 形式的 cookie 字典拼成请求头用的 cookie 字符串。"""
    if not cookies_dict:
        return ''
    return '; '.join([f'{k}={v}' for k, v in cookies_dict.items()])


# 抖音登录态 cookie 关键字段：出现其中之一即视为已登录
LOGIN_COOKIE_KEYS = ('sessionid', 'sessionid_ss', 'sid_guard', 'uid_tt', 'sid_tt')


def _has_login_cookie(cookies):
    """判断 cookie 字典里是否含有登录态字段。"""
    if not cookies:
        return False
    if str(cookies.get('LOGIN_STATUS', '')) == '1':
        return True
    return any(cookies.get(k) for k in LOGIN_COOKIE_KEYS)


async def _capture(target_url, headless, edge_exe, webid_timeout,
                   wait_for_login=False, login_timeout=180.0):
    """实际驱动浏览器采集，返回 (cookies_dict, webid)。所有状态都是局部的。"""
    from playwright.async_api import async_playwright

    state = {'webid': None}

    def handle_request(request):
        url = request.url
        if url.startswith('https://www.douyin.com/aweme/v1/web/user/profile/other/'):
            query_params = parse_qs(urlparse(url).query)
            if 'webid' in query_params:
                state['webid'] = query_params['webid'][0]

    async def wait_webid():
        # 轮询等待 webid，最长 webid_timeout 秒后放弃（不阻塞返回 cookies）
        waited = 0.0
        while state['webid'] is None and waited < webid_timeout:
            await asyncio.sleep(0.5)
            waited += 0.5

    async def wait_login(page):
        # 轮询页面 cookie，直到检测到登录态或超时；给用户充分的手动登录时间。
        waited = 0.0
        while waited < login_timeout:
            cks = {c['name']: c['value'] for c in await page.context.cookies()}
            if _has_login_cookie(cks):
                return True
            await asyncio.sleep(1.5)
            waited += 1.5
        return False

    async with async_playwright() as p:
        launch_kwargs = dict(
            headless=headless,
            args=_browser_args(),
            ignore_default_args=['--enable-automation'],
        )
        if edge_exe and os.path.exists(edge_exe):
            launch_kwargs['executable_path'] = edge_exe
        browser = await p.chromium.launch(**launch_kwargs)
        try:
            page = await browser.new_page()
            try:
                await page.add_init_script(LOGIN_STEALTH_INIT_JS)
            except Exception:
                pass
            page.on('request', handle_request)
            await page.goto(target_url, wait_until='domcontentloaded')
            # 给页面留时间触发接口 & 完成可能的人工验证
            await asyncio.sleep(3)
            if wait_for_login:
                # 等用户在弹出的浏览器里手动登录，检测到登录态 cookie 后再收集
                await wait_login(page)
                await asyncio.sleep(1.5)
            else:
                await wait_webid()
            page_cookies = await page.context.cookies()
        finally:
            await browser.close()

    cookies = {c['name']: c['value'] for c in page_cookies}
    return cookies, state['webid']


def get_new_cookies(target_url=None, headless=None, edge_exe=None, webid_timeout=None):
    """
    采集一份新的抖音登录态 / 票据。

    :param target_url:    要打开的抖音页面，默认一个公开用户主页。
    :param headless:      是否无头运行；默认读环境变量 DY_CAPTURE_HEADLESS（默认 False，便于人工过验证码）。
    :param edge_exe:      Edge 可执行路径；默认读 DY_EDGE_PATH，否则尝试系统默认安装路径。
    :param webid_timeout: 等待 webid 的最长秒数；默认读 DY_CAPTURE_TIMEOUT（默认 30）。
    :return: dict — {webid, msToken, ttwid, cookies, cookie_str}
    """
    target_url = target_url or os.getenv('DY_CAPTURE_URL') or DEFAULT_TARGET_URL
    if headless is None:
        headless = _env_bool('DY_CAPTURE_HEADLESS', False)
    if edge_exe is None:
        edge_exe = os.getenv('DY_EDGE_PATH', DEFAULT_EDGE_EXE)
    if webid_timeout is None:
        try:
            webid_timeout = float(os.getenv('DY_CAPTURE_TIMEOUT', '30'))
        except ValueError:
            webid_timeout = 30.0

    if not headless:
        print('如出现验证过程，请在弹出的浏览器中手动完成验证')

    cookies, webid = asyncio.run(
        _capture(target_url, headless, edge_exe, webid_timeout)
    )

    return {
        'webid': webid,
        'msToken': cookies.get('msToken'),
        'ttwid': cookies.get('ttwid'),
        'cookies': cookies,
        'cookie_str': cookies_to_str(cookies),
    }


def get_login_cookies(login_url=None, edge_exe=None, login_timeout=None, webid_timeout=None):
    """
    打开一个可见浏览器，等用户手动登录抖音后采集登录态 cookie。

    与 get_new_cookies 的区别：浏览器会一直开着，直到检测到登录态 cookie
    （或 login_timeout 秒超时），因此用户有充足时间扫码 / 输入手机号完成登录。

    :param login_url:     打开的登录页，默认抖音首页。
    :param edge_exe:      Edge 可执行路径；默认读 DY_EDGE_PATH，否则系统默认安装路径。
    :param login_timeout: 等待用户登录的最长秒数；默认读 DY_LOGIN_TIMEOUT（默认 180）。
    :param webid_timeout: 兼容参数（登录模式下不长时间等待 webid）。
    :return: dict — {webid, msToken, ttwid, cookies, cookie_str, logged_in}
    """
    login_url = login_url or os.getenv('DY_LOGIN_URL') or DEFAULT_LOGIN_URL
    if edge_exe is None:
        edge_exe = os.getenv('DY_EDGE_PATH', DEFAULT_EDGE_EXE)
    if login_timeout is None:
        try:
            login_timeout = float(os.getenv('DY_LOGIN_TIMEOUT', '180'))
        except ValueError:
            login_timeout = 180.0
    if webid_timeout is None:
        try:
            webid_timeout = float(os.getenv('DY_CAPTURE_TIMEOUT', '30'))
        except ValueError:
            webid_timeout = 30.0

    print('请在弹出的浏览器中完成抖音登录（扫码或手机号），登录成功后窗口会自动关闭')

    cookies, webid = asyncio.run(
        _capture(login_url, False, edge_exe, webid_timeout,
                 wait_for_login=True, login_timeout=login_timeout)
    )

    return {
        'webid': webid,
        'msToken': cookies.get('msToken'),
        'ttwid': cookies.get('ttwid'),
        'cookies': cookies,
        'cookie_str': cookies_to_str(cookies),
        'logged_in': _has_login_cookie(cookies),
    }


async def _persistent_login(login_url, login_timeout, edge_exe):
    """用持久化用户目录登录：登录态(含 localStorage)会留在 PROFILE_DIR，
    供发布复用同一会话/指纹。返回采集到的 cookies dict。"""
    from playwright.async_api import async_playwright

    profile_dir = _profile_dir()
    os.makedirs(profile_dir, exist_ok=True)
    cookies = {}
    storage = {}
    warmup = {'visited': [], 'errors': []}
    async with async_playwright() as p:
        kw = dict(headless=False, args=_browser_args(), ignore_default_args=['--enable-automation'], locale='zh-CN', timezone_id='Asia/Shanghai')
        if edge_exe and os.path.exists(edge_exe):
            kw['executable_path'] = edge_exe
        ctx = await p.chromium.launch_persistent_context(profile_dir, **kw)
        await ctx.add_init_script(LOGIN_STEALTH_INIT_JS)
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            try:
                await page.evaluate(LOGIN_STEALTH_INIT_JS)
            except Exception:
                pass
            await page.goto(login_url, wait_until='domcontentloaded')
            await asyncio.sleep(3)
            waited = 0.0
            while waited < login_timeout:
                cks = {c['name']: c['value'] for c in await ctx.cookies()}
                if _has_login_cookie(cks):
                    break
                await asyncio.sleep(1.5)
                waited += 1.5
            # 主站登录成功后，在同一窗口打开创作者中心，让用户把创作者中心也登上/开通
            # （发布视频需要 creator.douyin.com 的登录态；主站登录不一定自动带上）。
            try:
                await page.goto(DEFAULT_CREATOR_LOGIN_URL, wait_until='domcontentloaded', timeout=25000)
            except Exception:
                pass
            await asyncio.sleep(2)
            cwait = 0.0
            creator_timeout = min(login_timeout, 180.0)
            while cwait < creator_timeout:
                u = page.url or ''
                if 'creator.douyin.com' in u and 'passport' not in u and '/login' not in u:
                    try:
                        el = await page.query_selector('input[type="file"], [class*="upload"], [class*="publish"], [class*="content-upload"]')
                    except Exception:
                        el = None
                    if el:
                        break
                await asyncio.sleep(2)
                cwait += 2
            # 单 Profile 多域名预热：同一登录态访问主站和创作者中心，补齐
            # www.douyin.com / creator.douyin.com / passport 域名下的 Cookie 和
            # security-sdk localStorage。这里不要求用户再登录，只做同会话激活。
            for warm_url in _douyin_warmup_urls(login_url):
                try:
                    await page.goto(warm_url, wait_until='domcontentloaded', timeout=20000)
                    await asyncio.sleep(1.2)
                    warmup['visited'].append(warm_url)
                except Exception as e:
                    warmup['errors'].append({'url': warm_url, 'error': str(e)[:300]})
            await asyncio.sleep(1.5)
            cookies = {c['name']: c['value'] for c in await ctx.cookies()}
            storage = await page.evaluate("""() => ({
                web_protect: localStorage.getItem('security-sdk/s_sdk_sign_data_key/web_protect') || '',
                keys: localStorage.getItem('security-sdk/s_sdk_crypt_sdk') || ''
            })""")
        finally:
            await ctx.close()
    storage = storage or {}
    storage['warmup'] = warmup
    return cookies, storage


async def _read_persistent_profile_cookies(login_url, read_timeout, edge_exe, headless=True):
    """无交互读取持久化 profile 中已有 Cookie。

    用于后端重启后从本地 profile 恢复登录态，避免用户已经登录过还要再次扫码。
    默认 headless=True，不弹窗；如果 profile 被其它发布/登录任务占用会抛异常，由调用方降级。
    """
    from playwright.async_api import async_playwright

    profile_dir = _profile_dir()
    os.makedirs(profile_dir, exist_ok=True)
    cookies = {}
    storage = {}
    warmup = {'visited': [], 'errors': []}
    async with async_playwright() as p:
        kw = dict(
            headless=headless,
            args=_browser_args(),
            ignore_default_args=['--enable-automation'],
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
        )
        if edge_exe and os.path.exists(edge_exe):
            kw['executable_path'] = edge_exe
        ctx = await p.chromium.launch_persistent_context(profile_dir, **kw)
        try:
            try:
                await ctx.add_init_script(LOGIN_STEALTH_INIT_JS)
            except Exception:
                pass
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            if login_url:
                try:
                    await page.goto(login_url, wait_until='domcontentloaded', timeout=int(read_timeout * 1000))
                except Exception:
                    pass
                await asyncio.sleep(min(2.0, max(0.2, read_timeout / 3.0)))
            # 读取 Profile 时也轻量访问两个域名，避免服务重启后只恢复到一个
            # origin 的 Cookie，导致客户端误判“还要登录一次”。
            for warm_url in _douyin_warmup_urls(login_url):
                try:
                    await page.goto(warm_url, wait_until='domcontentloaded', timeout=int(read_timeout * 1000))
                    await asyncio.sleep(min(1.0, max(0.2, read_timeout / 4.0)))
                    warmup['visited'].append(warm_url)
                except Exception as e:
                    warmup['errors'].append({'url': warm_url, 'error': str(e)[:300]})
            cookies = {c['name']: c['value'] for c in await ctx.cookies()}
            storage = await page.evaluate("""() => ({
                web_protect: localStorage.getItem('security-sdk/s_sdk_sign_data_key/web_protect') || '',
                keys: localStorage.getItem('security-sdk/s_sdk_crypt_sdk') || ''
            })""")
        finally:
            await ctx.close()
    storage = storage or {}
    storage['warmup'] = warmup
    return cookies, storage


def get_login_cookies_persistent(login_url=None, login_timeout=None):
    """打开持久化 Chromium 让用户登录抖音；登录态留存到 PROFILE_DIR 供发布复用。
    同时返回 cookies（写入后端 auth，供爬虫 API 复用）。"""
    login_url = login_url or os.getenv('DY_LOGIN_URL') or DEFAULT_LOGIN_URL
    edge_exe = os.getenv('DY_EDGE_PATH', DEFAULT_EDGE_EXE)
    if login_timeout is None:
        try:
            login_timeout = float(os.getenv('DY_LOGIN_TIMEOUT', '180'))
        except ValueError:
            login_timeout = 180.0
    print('请在弹出的浏览器中完成抖音登录；登录态会保存到本地浏览器配置，供发布复用')
    cookies, storage = asyncio.run(_persistent_login(login_url, login_timeout, edge_exe))
    return {
        'webid': None,
        'msToken': cookies.get('msToken'),
        'ttwid': cookies.get('ttwid'),
        'cookies': cookies,
        'cookie_str': cookies_to_str(cookies),
        'logged_in': _has_login_cookie(cookies),
        'web_protect': (storage or {}).get('web_protect', ''),
        'keys': (storage or {}).get('keys', ''),
        'warmup': (storage or {}).get('warmup') or {},
    }


def get_persistent_profile_cookies(login_url=None, edge_exe=None, read_timeout=None, headless=True):
    """读取已保存的持久化 profile Cookie；不要求扫码。

    返回结构与 get_login_cookies_persistent 一致，额外用于：
      1) API 服务重启后自动恢复 STATE['auth']；
      2) 客户端刷新后 /api/health?sync=1 自动同步本地登录态；
      3) 自动发布前兜底刷新 Cookie。
    """
    login_url = login_url or os.getenv('DY_LOGIN_URL') or DEFAULT_LOGIN_URL
    if edge_exe is None:
        edge_exe = os.getenv('DY_EDGE_PATH', DEFAULT_EDGE_EXE)
    if read_timeout is None:
        try:
            read_timeout = float(os.getenv('DY_PROFILE_READ_TIMEOUT', '8'))
        except ValueError:
            read_timeout = 8.0
    cookies, storage = asyncio.run(_read_persistent_profile_cookies(login_url, read_timeout, edge_exe, headless=headless))
    return {
        'webid': None,
        'msToken': cookies.get('msToken'),
        'ttwid': cookies.get('ttwid'),
        'cookies': cookies,
        'cookie_str': cookies_to_str(cookies),
        'logged_in': _has_login_cookie(cookies),
        'web_protect': (storage or {}).get('web_protect', ''),
        'keys': (storage or {}).get('keys', ''),
        'warmup': (storage or {}).get('warmup') or {},
    }


if __name__ == '__main__':
    import json
    print(json.dumps(get_new_cookies(), ensure_ascii=False, indent=2))
