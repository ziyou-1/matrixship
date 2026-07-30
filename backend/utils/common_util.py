import os
# from loguru import logger
from dotenv import load_dotenv
from runtime_paths import agent_data_dir

dy_auth = None
dy_live_auth = None


def build_auth(cookie_str):
    """用一段 cookie 字符串构造 DouyinAuth。"""
    from builder.auth import DouyinAuth
    auth = DouyinAuth()
    auth.perepare_auth(cookie_str or '', '', '')
    return auth


def capture_cookie_str():
    """
    调用 cookie_util 的浏览器登录逻辑，采集一份新的 cookie 字符串。
    采集失败时返回空串，由调用方决定如何回退。
    """
    try:
        from utils.cookie_util import get_new_cookies
        res = get_new_cookies()
        return res.get('cookie_str') or ''
    except Exception as e:
        print(f'[cookie capture] 采集失败: {e}')
        return ''


def load_env():
    """
    准备爬虫认证信息。

    cookie 来源优先级：
      1. .env 中的 DY_COOKIES（手动粘贴的登录 cookie）。
      2. 若 DY_COOKIES 为空且 DY_AUTO_CAPTURE 为真，则走 cookie_util 浏览器登录采集。
    直播认证仍只读 DY_LIVE_COOKIES。
    """
    global dy_auth, dy_live_auth
    load_dotenv()
    cookies_dy = os.getenv('DY_COOKIES') or ''
    cookies_live = os.getenv('DY_LIVE_COOKIES') or ''

    auto_capture = (os.getenv('DY_AUTO_CAPTURE') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    if not cookies_dy and auto_capture:
        print('[auth] DY_COOKIES 为空，启动浏览器登录采集 cookie...')
        cookies_dy = capture_cookie_str()
        if cookies_dy:
            print(f'[auth] 采集到 cookie（{len(cookies_dy)} 字符）')

    dy_auth = build_auth(cookies_dy)
    dy_live_auth = build_auth(cookies_live)
    return dy_auth


def init():
    data_dir = os.getenv('MATRIX_AGENT_DATA_DIR') or os.getenv('DY_DATA_DIR')
    if data_dir:
        data_dir = os.path.abspath(os.path.expandvars(data_dir))
    else:
        data_dir = agent_data_dir()
    media_base_path = os.path.join(data_dir, 'media_datas')
    excel_base_path = os.path.join(data_dir, 'excel_datas')
    for base_path in [media_base_path, excel_base_path]:
        if not os.path.exists(base_path):
            os.makedirs(base_path)
            # logger.info(f'create {base_path}')
    cookies = load_env()
    base_path = {
        'media': media_base_path,
        'excel': excel_base_path,
    }
    return cookies, base_path
