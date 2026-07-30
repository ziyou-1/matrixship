# coding: utf-8
"""Platform adapters used by the local execution node.

The business API stays stable (`finder`, `outreach`, `publish`).  Platform
specific code lives here so Douyin/Xiaohongshu implementations can later be
replaced by a stronger open-source crawler without touching client flows.
"""

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, quote, urljoin, urlparse

from loguru import logger

try:
    from utils.structured_log import json_log
except ModuleNotFoundError:
    from backend.utils.structured_log import json_log


PLATFORM_ALIASES = {
    "douyin": "douyin",
    "dy": "douyin",
    "抖音": "douyin",
    "xhs": "xhs",
    "xiaohongshu": "xhs",
    "rednote": "xhs",
    "小红书": "xhs",
}


def platform_code(value, default="douyin"):
    text = str(value or "").strip().lower()
    return PLATFORM_ALIASES.get(text, default)


def platform_label(code):
    return "小红书" if platform_code(code) == "xhs" else "抖音"


def compact_text(text, max_len=160):
    text = re.sub(r"\s+", " ", str(text or "").replace("\u200b", "")).strip()
    if max_len and len(text) > max_len:
        text = text[: max_len - 1].rstrip("，。,. ") + "…"
    return text


def classify_intent(text):
    t = (text or "").lower()
    high = ["求链接", "链接", "怎么买", "哪里买", "在哪买", "多少钱", "价格", "优惠", "下单", "购买", "同款", "店铺", "怎么买"]
    mid = ["收藏", "蹲", "想试", "想要", "不错", "种草", "看着", "心动", "安排", "求推荐"]
    consult = ["吗", "？", "?", "怎么", "能用", "适合", "敏感肌", "会不会", "哪个", "区别", "多久"]
    if any(k in t for k in high):
        return "高意向"
    if any(k in t for k in mid):
        return "中意向"
    if any(k in t for k in consult):
        return "咨询"
    return "普通"


def _browser_kwargs(profile_dir, headless_env="XHS_HEADLESS", default_headless=True):
    default = "1" if default_headless else "0"
    headless = str(os.getenv(headless_env, default)).strip().lower() not in ("0", "false", "no", "off")
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
        "--lang=zh-CN",
    ]
    kw = {
        "headless": headless,
        "args": args,
        "ignore_default_args": ["--enable-automation"],
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "viewport": {"width": 1280, "height": 900},
    }
    exe = os.getenv("XHS_BROWSER_PATH") or os.getenv("DY_EDGE_PATH")
    if not exe:
        # 默认用本机 Edge(自带 Playwright chromium 在部分机器 spawn UNKNOWN);抖音登录同样走 Edge。
        for cand in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                     r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
            if os.path.exists(cand):
                exe = cand
                break
    if exe and os.path.exists(exe):
        kw["executable_path"] = exe
    os.makedirs(profile_dir, exist_ok=True)
    return kw


def _xhs_open_context(p, data_dir="", headless_env="XHS_HEADLESS", persistent=False, default_headless=True):
    """Open a Xiaohongshu browser context.

    Read-only jobs (search/comment scraping/download) should prefer an
    ephemeral context to avoid locking the user's login profile.  Mutating jobs
    (send comment/publish/login) use the persistent profile.
    """
    profile = xhs_profile_dir(data_dir or os.getcwd())
    kw = _browser_kwargs(profile, headless_env, default_headless=default_headless)
    if persistent:
        return p.chromium.launch_persistent_context(profile, **kw), None

    launch_keys = ("headless", "args", "ignore_default_args", "executable_path")
    launch_kw = {k: kw[k] for k in launch_keys if k in kw}
    browser = p.chromium.launch(**launch_kw)
    ctx = browser.new_context(
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        extra_http_headers={
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    return ctx, browser


def _safe_close_context(ctx, browser=None):
    for obj in (ctx, browser):
        if not obj:
            continue
        try:
            obj.close()
        except Exception:
            pass


XHS_LOGIN_COOKIE_KEYS = ("web_session", "customerClientId", "galaxy_creator_session_id", "access-token-creator.xiaohongshu.com")
# 强登录 cookie(仅真登录后出现;web_session 游客也有,不能作数)。
# 只认可靠的 id_token(登录 auth token);creator 系列为创作者中心登录。
# ⚠️不要用 unread:它是未读通知数,会话降级/禁言后仍残留,会导致"点登录秒关"误判。
XHS_STRONG_LOGIN_COOKIES = ("id_token", "customerClientId",
                            "galaxy_creator_session_id", "access-token-creator.xiaohongshu.com")
# 用页面 DOM 判断真实登录态(游客有登录弹窗/"登录"按钮;登录后有头像/个人主页入口)
_XHS_LOGIN_JS = r"""() => {
  const t = (document.body && document.body.innerText) || '';
  const loginPrompt = /扫码登录|手机号登录|新用户扫码|登录后查看|一键登录|登录小红书/.test(t);
  const loginBtn = Array.from(document.querySelectorAll('button,a,span,div')).some(e => {
    const s = (e.innerText || '').trim();
    return s === '登录' || s === '登录/注册' || s === '立即登录';
  });
  const avatar = !!document.querySelector('img.user-image, .reds-avatar, li.user .channel, [class*="avatar"] img, a[href*="/user/profile/"] img');
  const meLink = !!document.querySelector('a[href*="/user/profile/"]');
  const loggedIn = (avatar || meLink) && !loginPrompt && !loginBtn;
  return { loggedIn: loggedIn, loginPrompt: loginPrompt, loginBtn: loginBtn, avatar: avatar, meLink: meLink };
}"""


_XHS_CLOSE_GUEST_LOGIN_MODAL_JS = r"""() => {
  const visible = el => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 8 && r.height > 8 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
  };
  const textOf = el => String(el && (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '') || '').replace(/\s+/g, ' ').trim();
  const loginRe = /手机号登录|扫码登录|登录后推荐更懂你的笔记|登录探索更多内容|新用户扫码|获取验证码|登录小红书|小红书如何扫码/;
  const bodyText = textOf(document.body);
  const loginWall = loginRe.test(bodyText);
  if (!loginWall) return {loginWall:false, closed:false};
  const roots = Array.from(document.querySelectorAll('div,section,[role=dialog],[class*="login"],[class*="modal"],[class*="Modal"]'))
    .filter(el => visible(el) && loginRe.test(textOf(el)));
  const scopes = roots.length ? roots : [document.body];
  const closeRe = /^(×|x|X|关闭|取消)$/;
  const closeSelectors = [
    '[aria-label*="关闭"]', '[title*="关闭"]',
    '[class*="close"]', '[class*="Close"]',
    'button', '[role=button]', 'svg', 'span'
  ];
  const candidates = [];
  for (const root of scopes) {
    for (const sel of closeSelectors) {
      for (const el of Array.from(root.querySelectorAll(sel))) {
        if (!visible(el)) continue;
        const label = textOf(el);
        const cls = String(el.className || '');
        const aria = String(el.getAttribute('aria-label') || el.getAttribute('title') || '');
        const r = el.getBoundingClientRect();
        const rootBox = root.getBoundingClientRect ? root.getBoundingClientRect() : {right: innerWidth, top: 0};
        const nearTopRight = r.left > rootBox.right - 90 && r.top < rootBox.top + 90;
        if (closeRe.test(label) || /close|Close/.test(cls) || /关闭/.test(aria) || (nearTopRight && r.width <= 60 && r.height <= 60)) {
          candidates.push(el);
        }
      }
    }
  }
  const target = candidates[0];
  if (!target) return {loginWall:true, closed:false};
  target.click();
  return {loginWall:true, closed:true};
}"""


def _xhs_close_guest_login_modal(page):
    try:
        result = page.evaluate(_XHS_CLOSE_GUEST_LOGIN_MODAL_JS)
        result = result if isinstance(result, dict) else {}
        if result.get("closed"):
            try:
                page.wait_for_timeout(800)
            except Exception:
                pass
        return {
            "loginWall": bool(result.get("loginWall")),
            "closed": bool(result.get("closed")),
        }
    except Exception:
        return {"loginWall": False, "closed": False}


def xhs_login(data_dir="", login_timeout=None):
    """Open a visible persistent Xiaohongshu browser and wait for the user to log
    in (QR/phone). Login state stays in the local xhs_profile; only status is
    returned. Mirrors cookie_util's Douyin persistent login."""
    from playwright.sync_api import sync_playwright
    import time as _t
    if login_timeout is None:
        try:
            login_timeout = float(os.getenv("XHS_LOGIN_TIMEOUT", "180"))
        except ValueError:
            login_timeout = 180.0
    profile = xhs_profile_dir(data_dir or os.getcwd())
    os.makedirs(profile, exist_ok=True)
    kw = _browser_kwargs(profile, "XHS_LOGIN_HEADLESS")
    kw["headless"] = False  # login must be visible so the user can scan/enter code
    logged = False
    count = 0
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(profile, **kw)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
            deadline = _t.time() + login_timeout
            dom_stable = 0
            while _t.time() < deadline:
                cks = {c["name"]: c.get("value") for c in ctx.cookies()}
                # 主判据:登录专属 cookie 一出现即判定(立即、可靠、不误判游客)
                if any(cks.get(k) for k in XHS_STRONG_LOGIN_COOKIES):
                    logged = True
                    _t.sleep(1.5)  # 等 cookie/localStorage 落盘到 profile
                    cks = {c["name"]: c.get("value") for c in ctx.cookies()}
                    count = len([1 for v in cks.values() if v])
                    break
                # 兜底:DOM 真实登录态(连续两次稳定,防瞬态)
                try:
                    dom_ok = bool(page.evaluate(_XHS_LOGIN_JS).get("loggedIn"))
                except Exception:
                    dom_ok = False
                if dom_ok:
                    dom_stable += 1
                    if dom_stable >= 2:
                        logged = True
                        _t.sleep(1.5)
                        cks = {c["name"]: c.get("value") for c in ctx.cookies()}
                        count = len([1 for v in cks.values() if v])
                        break
                else:
                    dom_stable = 0
                _t.sleep(2.0)
            if not logged:
                cks = {c["name"]: c.get("value") for c in ctx.cookies()}
                count = len([1 for v in cks.values() if v])
                logged = any(cks.get(k) for k in XHS_STRONG_LOGIN_COOKIES)
        finally:
            _safe_close_context(ctx)
    return {"ok": logged, "logged_in": logged, "cookieCount": count, "platform": "xhs"}


def xhs_profile_dir(data_dir):
    return os.path.abspath(os.getenv("XHS_PROFILE_DIR") or os.path.join(data_dir, "xhs_profile"))


def _is_xhs_creator_login_url(url):
    text = str(url or "").lower()
    return "creator.xiaohongshu.com/login" in text or "redirectreason=401" in text


def _wait_for_xhs_creator_login(page, ctx, creator_url):
    _ = (ctx, creator_url)
    try:
        timeout = float(os.getenv("XHS_CREATOR_LOGIN_TIMEOUT", os.getenv("XHS_LOGIN_TIMEOUT", "180")))
    except ValueError:
        timeout = 180.0
    timeout = max(5.0, timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if page.locator("input[type=file]").count() > 0:
                return True
        except Exception:
            pass
        try:
            if not _is_xhs_creator_login_url(page.url):
                return True
        except Exception:
            pass
        page.wait_for_timeout(2000)
    return False


def _xhs_profile_has_login_cookie(data_dir):
    """廉价判断 xhs_profile 是否已登录:直接读 profile 的 Cookies sqlite,看有无登录专属
    cookie(id_token/unread 等)。不启动浏览器,可安全用于 /api/accounts 就绪探测。"""
    import glob
    import shutil
    import sqlite3
    import tempfile
    prof = xhs_profile_dir(data_dir or os.getcwd())
    dbs = [os.path.join(prof, "Default", "Network", "Cookies"), os.path.join(prof, "Network", "Cookies")]
    try:
        dbs += glob.glob(os.path.join(prof, "**", "Cookies"), recursive=True)
    except Exception:
        pass
    for db in dict.fromkeys(dbs):
        if not os.path.isfile(db):
            continue
        tmp = os.path.join(tempfile.gettempdir(), "xhs_ready_%d.db" % (abs(hash(db)) % 100000))
        try:
            shutil.copy(db, tmp)
            con = sqlite3.connect(tmp)
            try:
                names = {r[0] for r in con.execute(
                    "select name from cookies where host_key like '%xiaohongshu%'").fetchall()}
            finally:
                con.close()
            if names & set(XHS_STRONG_LOGIN_COOKIES):
                return True
        except Exception:
            pass
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
    return False


def xhs_profile_ready(data_dir):
    """Fast, non-invasive readiness signal for account matrix.

    不启动浏览器:优先看 XHS_ACCOUNT_ENABLED / xhs_auth_state.json 标记,再直接读 profile
    的 Cookies 库看有无登录专属 cookie(客户端登录小红书后搜索/评论即自动认登录态)。
    """
    if str(os.getenv("XHS_ACCOUNT_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on"):
        return True
    marker = Path(data_dir or os.getcwd()) / "xhs_auth_state.json"
    try:
        if marker.exists():
            data = json.loads(marker.read_text(encoding="utf-8"))
            if data.get("disabled"):
                return False
            if data.get("loggedIn") and data.get("cookieCount"):
                return True
    except Exception:
        pass
    try:
        return _xhs_profile_has_login_cookie(data_dir)
    except Exception:
        return False


def xhs_guest_collection_default(env=None):
    env = env or os.environ
    return str(env.get("XHS_GUEST_COLLECTION_DEFAULT", "1")).strip().lower() not in ("0", "false", "no", "off")


def xhs_guest_collection_block_error(result, action=""):
    result = result if isinstance(result, dict) else {}
    if not result.get("guestMode"):
        return result
    if result.get("loginWall") or result.get("needLogin") or result.get("error") == "xhs_login_required":
        result["ok"] = False
        result["needLogin"] = True
        result["error"] = "xhs_guest_login_required"
        return result
    if result.get("blocked") and not str(result.get("error") or "").startswith("xhs_guest_"):
        if not result.get("riskCode"):
            result["error"] = "xhs_guest_access_limited"
        result["ok"] = False
    return result


def extract_xhs_note_id(value):
    text = str(value or "").strip()
    if not text:
        return ""
    for pat in (
        r"/explore/([0-9a-fA-F]{8,32})",
        r"[?&]note_id=([0-9a-fA-F]{8,32})",
        r"(^|[^0-9a-fA-F])([0-9a-fA-F]{24})([^0-9a-fA-F]|$)",
    ):
        m = re.search(pat, text)
        if m:
            return m.group(1 if "explore" in pat or "note_id" in pat else 2)
    return ""


def _xhs_note_url(note_id_or_url):
    val = str(note_id_or_url or "").strip()
    if val.startswith("http"):
        return val
    note_id = extract_xhs_note_id(val) or val
    return "https://www.xiaohongshu.com/explore/" + note_id if note_id else ""


def _first_url(obj):
    try:
        urls = obj.get("url_list") if isinstance(obj, dict) else obj
        if isinstance(urls, str):
            return urls.split()[0]
        return urls[0] if urls else ""
    except Exception:
        return ""


def _debug_page_snapshot(page, data_dir, prefix):
    debug = {"url": "", "title": "", "bodyText": ""}
    try:
        debug["url"] = page.url
    except Exception:
        pass
    try:
        debug["title"] = page.title()
    except Exception:
        pass
    try:
        debug["bodyText"] = compact_text(page.locator("body").inner_text(timeout=2500), 700)
    except Exception:
        try:
            debug["bodyText"] = compact_text(page.evaluate("document.body && document.body.innerText || ''"), 700)
        except Exception:
            pass
    try:
        base = Path(data_dir or os.getcwd()) / "debug"
        base.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        png = base / ("%s-%s.png" % (prefix, stamp))
        html = base / ("%s-%s.html" % (prefix, stamp))
        page.screenshot(path=str(png), full_page=True, timeout=7000)
        html.write_text(page.content(), encoding="utf-8", errors="ignore")
        debug["screenshot"] = str(png)
        debug["html"] = str(html)
    except Exception as e:
        debug["snapshotError"] = str(e)
    return debug


def _xhs_apply_risk_from_debug(result, debug):
    text = chr(10).join([
        ((debug or {}).get("url") or ""),
        ((debug or {}).get("title") or ""),
        ((debug or {}).get("bodyText") or ""),
    ])
    if "300012" in text:
        result["ok"] = False
        result["blocked"] = True
        result["riskCode"] = "300012"
        result["error"] = "xhs_ip_risk"
        result["message"] = "xhs_content_ip_risk"
    elif "300031" in text:
        result["ok"] = False
        result["blocked"] = True
        result["riskCode"] = "300031"
        result["error"] = "xhs_note_unavailable"
        result["message"] = "xhs_note_temporarily_unavailable"
    return result


def _xhs_search_count(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    multiplier = 1
    if text[-1:] in ("万", "w", "W"):
        multiplier = 10000
        text = text[:-1]
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return int(float(match.group(0)) * multiplier)
    except Exception:
        return None


def _xhs_first_dict(*values):
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _xhs_first_text(*values):
    for value in values:
        text = compact_text(value or "", 0)
        if text:
            return text
    return ""


def _xhs_search_note_meta(raw):
    raw = raw if isinstance(raw, dict) else {}
    card = _xhs_first_dict(
        raw.get("note_card"),
        raw.get("noteCard"),
        raw.get("note"),
        raw.get("card"),
        raw,
    )
    note_id = _xhs_first_text(
        raw.get("note_id"),
        raw.get("noteId"),
        raw.get("id"),
        card.get("note_id"),
        card.get("noteId"),
        card.get("id"),
    )
    if not note_id:
        return {}
    user = _xhs_first_dict(
        card.get("user"),
        card.get("user_info"),
        card.get("userInfo"),
        raw.get("user"),
        raw.get("user_info"),
        raw.get("userInfo"),
    )
    interact = _xhs_first_dict(
        card.get("interact_info"),
        card.get("interactInfo"),
        raw.get("interact_info"),
        raw.get("interactInfo"),
        card.get("statistics"),
        raw.get("statistics"),
    )
    title = _xhs_first_text(card.get("display_title"), card.get("title"), raw.get("display_title"), raw.get("title"))
    author = _xhs_first_text(user.get("nickname"), user.get("nickName"), user.get("name"), card.get("nickname"), raw.get("nickname"))
    like_count = _xhs_search_count(
        interact.get("liked_count")
        or interact.get("likedCount")
        or interact.get("like_count")
        or interact.get("likeCount")
        or interact.get("digg_count")
        or interact.get("diggCount")
    )
    collect_count = _xhs_search_count(
        interact.get("collected_count")
        or interact.get("collectedCount")
        or interact.get("collect_count")
        or interact.get("collectCount")
        or interact.get("favorite_count")
        or interact.get("favoriteCount")
        or interact.get("fav_count")
        or interact.get("favCount")
    )
    out = {"note_id": note_id, "work_id": note_id}
    if title:
        out["title"] = title
        out["desc"] = title
    if author:
        out["author"] = author
        out["nickname"] = author
    if like_count is not None:
        out["diggCount"] = like_count
        out["digg_count"] = like_count
    if collect_count is not None:
        out["collectCount"] = collect_count
        out["collect_count"] = collect_count
    return out


def _xhs_search_note_meta_map(payload):
    found = {}
    stack = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            meta = _xhs_search_note_meta(current)
            note_id = meta.get("note_id") if meta else ""
            if note_id:
                merged = dict(found.get(note_id) or {})
                merged.update({k: v for k, v in meta.items() if v is not None and v != ""})
                found[note_id] = merged
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return found


def _xhs_search_page_matches_keyword(page_url, keyword):
    target = compact_text(keyword, 0).lower()
    if not target:
        return False
    try:
        parsed = urlparse(str(page_url or ""))
    except Exception:
        return False
    if "search_result" not in (parsed.path or ""):
        return False
    query = parse_qs(parsed.query or "")
    values = []
    for key in ("keyword", "query", "q", "search_key", "searchKey"):
        values.extend(query.get(key) or [])
    if not values:
        return False
    return any(compact_text(value, 0).lower() == target for value in values)


def xhs_search_notes(keyword, limit=10, data_dir="", guest_mode=True):
    from playwright.sync_api import sync_playwright

    keyword = (keyword or "").strip()
    if not keyword:
        raise RuntimeError("missing_keyword")
    limit = max(1, min(int(limit or 10), 30))
    search_url = "https://www.xiaohongshu.com/search_result?keyword=%s" % quote(keyword)
    notes = []
    debug = {}
    login_state = {}
    search_verified = False
    with sync_playwright() as p:
        ctx, browser = _xhs_open_context(
            p,
            data_dir=data_dir or os.getcwd(),
            headless_env="XHS_SEARCH_HEADLESS",
            persistent=(not guest_mode) and xhs_profile_ready(data_dir or os.getcwd()),
            default_headless=False,
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            # 截获搜索 API(/search/notes)响应里的 xsec_token —— 笔记页需要它才能直连打开
            # (裸 /explore/<id> 会被反爬重定向到 300031「当前笔记暂时无法浏览」)。
            token_map = {}
            note_meta_map = {}
            search_api_state = {"seen": False}

            def _cap_tokens(resp):
                try:
                    if "/search/notes" not in resp.url:
                        return
                    search_api_state["seen"] = True
                    j = resp.json()
                except Exception:
                    return
                try:
                    note_meta_map.update(_xhs_search_note_meta_map(j))
                except Exception:
                    pass
                stack = [j]
                while stack:
                    o = stack.pop()
                    if isinstance(o, dict):
                        nid = o.get("id") or o.get("note_id")
                        tok = o.get("xsec_token")
                        if nid and tok:
                            token_map[str(nid)] = tok
                        stack.extend(o.values())
                    elif isinstance(o, list):
                        stack.extend(o)
            try:
                page.on("response", _cap_tokens)
            except Exception:
                pass
            # 小红书对直接 goto 搜索结果页有反爬(常年卡在 Loading,domcontentloaded 45s 超时,
            # 页面停在 about:blank)。改走站内 SPA 路由:先进 explore,再用顶部搜索框输入关键词
            # 回车后由小红书页面路由跳到 search_result(实测能返回真实笔记)。
            try:
                page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=40000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
            login_state = _xhs_close_guest_login_modal(page)
            searched = False
            try:
                sbox = None
                for s in ('input#search-input', 'input[placeholder*="搜索"]',
                          '.search-input input', '#global-search-box input', 'input[type="text"]'):
                    if page.query_selector(s):
                        sbox = s
                        break
                if sbox:
                    page.click(sbox)
                    page.fill(sbox, keyword)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(4000)
                    searched = "search_result" in (page.url or "")
            except Exception:
                searched = False
            if not searched:
                # 兜底:直接导航(用 commit 更快返回,可能仍被挂但尽力)
                try:
                    page.goto(search_url, wait_until="commit", timeout=20000)
                except Exception:
                    pass
            page.wait_for_timeout(3000)
            next_login_state = _xhs_close_guest_login_modal(page)
            if next_login_state.get("loginWall") and (not next_login_state.get("closed") or not login_state):
                login_state = next_login_state
            search_verified = bool(
                search_api_state.get("seen") or _xhs_search_page_matches_keyword(page.url, keyword)
            )
            for _ in range(5):
                found = page.evaluate(
                    """(maxN) => {
                      const out = [];
                      const seen = new Set();
                      const pickImg = (el) => {
                        const img = el.querySelector('img');
                        return img && (img.currentSrc || img.src) || '';
                      };
                      const pickText = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g,' ').trim();
                      const push = (href, title, cover, author) => {
                        if (!href) return;
                        let u;
                        try { u = new URL(href, location.href); } catch (_) { return; }
                        const m = u.href.match(/\\/explore\\/([0-9a-fA-F]{8,32})/);
                        const id = m && m[1] || '';
                        if (!id || seen.has(id)) return;
                        seen.add(id);
                        out.push({
                          note_id: id,
                          work_id: id,
                          note_url: 'https://www.xiaohongshu.com/explore/' + id,
                          work_url: 'https://www.xiaohongshu.com/explore/' + id,
                          title: (title || id).slice(0, 120),
                          desc: title || '',
                          video_cover: cover || '',
                          nickname: author || '',
                          platform: 'xhs',
                          work_type: '笔记'
                        });
                      };
                      const pushId = (id, title = '', cover = '', author = '') => {
                        if (!id || seen.has(id)) return;
                        seen.add(id);
                        out.push({
                          note_id: id,
                          work_id: id,
                          note_url: 'https://www.xiaohongshu.com/explore/' + id,
                          work_url: 'https://www.xiaohongshu.com/explore/' + id,
                          title: (title || id).slice(0, 120),
                          desc: title || '',
                          video_cover: cover || '',
                          nickname: author || '',
                          platform: 'xhs',
                          work_type: '笔记'
                        });
                      };
                      for (const a of Array.from(document.querySelectorAll('a[href*="/explore/"]'))) {
                        const card = a.closest('section,div') || a;
                        const text = pickText(card) || pickText(a);
                        const cover = pickImg(card) || pickImg(a);
                        push(a.href, text, cover, '');
                        if (out.length >= maxN) break;
                      }
                      if (out.length < maxN) {
                        const html = document.documentElement.innerHTML || '';
                        const pats = [
                          /\\/explore\\/([0-9a-fA-F]{8,32})/g,
                          /["']noteId["']\\s*[:=]\\s*["']([0-9a-fA-F]{8,32})["']/g,
                          /["']note_id["']\\s*[:=]\\s*["']([0-9a-fA-F]{8,32})["']/g,
                          /["']id["']\\s*:\\s*["']([0-9a-fA-F]{24})["']/g
                        ];
                        for (const pat of pats) {
                          let m;
                          while ((m = pat.exec(html)) && out.length < maxN) {
                            pushId(m[1]);
                          }
                          if (out.length >= maxN) break;
                        }
                      }
                      return out;
                    }""",
                    limit,
                )
                for item in found or []:
                    if not any(x.get("note_id") == item.get("note_id") for x in notes):
                        notes.append(item)
                if len(notes) >= limit:
                    break
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(1200)
            # 给每条笔记拼上截获到的 xsec_token,使评论/下载能直连打开笔记页(否则 300031)
            for it in notes:
                meta = note_meta_map.get(str(it.get("note_id") or ""))
                if meta:
                    for key, value in meta.items():
                        if key not in ("note_id", "work_id") and value is not None and value != "":
                            it[key] = value
                tok = token_map.get(str(it.get("note_id") or ""))
                if tok:
                    turl = ("https://www.xiaohongshu.com/explore/%s?xsec_token=%s&xsec_source=pc_search"
                            % (it.get("note_id"), tok))
                    it["note_url"] = turl
                    it["work_url"] = turl
                    it["xsecToken"] = tok
            if not search_verified:
                notes = []
                debug = _debug_page_snapshot(page, data_dir or os.getcwd(), "xhs-search-unverified")
            elif not notes:
                debug = _debug_page_snapshot(page, data_dir or os.getcwd(), "xhs-search")
        finally:
            _safe_close_context(ctx, browser)
    result = {"ok": True, "platform": "xhs", "keyword": keyword, "count": len(notes[:limit]), "items": notes[:limit], "guestMode": bool(guest_mode), "searchVerified": bool(search_verified)}
    if guest_mode and login_state.get("loginWall") and not login_state.get("closed"):
        result["loginWall"] = True
    if guest_mode and not search_verified and debug and not _xhs_apply_risk_from_debug(dict(result), debug).get("riskCode"):
        body = debug.get("bodyText") or ""
        if "登录后查看搜索结果" not in body and "手机号登录" not in body and "获取验证码" not in body:
            result["blocked"] = True
            result["message"] = "xhs_search_result_unverified"
    if debug:
        result["debug"] = debug
        result = _xhs_apply_risk_from_debug(result, debug)
        body = debug.get("bodyText") or ""
        if "登录后查看搜索结果" in body or "手机号登录" in body or "获取验证码" in body:
            result["ok"] = False
            result["needLogin"] = True
            result["error"] = "xhs_login_required"
    return xhs_guest_collection_block_error(result, "search")


XHS_STRICT_LEAD_FILTER_ENV = "XHS_STRICT_LEAD_FILTER_ENABLED"
_XHS_COMMENT_METADATA_LINE_RE = re.compile(
    r"(?:"
    r"作者(?:\s*[·•.]?\s*(?:赞(?:\s*\d+)?|回复)(?:\s+(?:赞(?:\s*\d+)?|回复))*)?"
    r"|(?:赞(?:\s*\d+)?|回复)(?:\s*(?:赞(?:\s*\d+)?|回复))*"
    r"|(?:刚刚|\d+\s*(?:秒|分钟|小时|天|周|月|年)前|(?:\d{4}-)?\d{1,2}-\d{1,2})"
    r"(?:\s*[\u4e00-\u9fff]{1,8})?"
    r"(?:\s+(?:作者\s*[·•.]?\s*)?(?:赞(?:\s*\d+)?|回复))*"
    r")"
)
_XHS_COMMENT_TIME_TAIL_RE = re.compile(
    r"\s+(?:作者\s*[·•.]?\s*)?"
    r"(?:刚刚|\d+\s*(?:秒|分钟|小时|天|周|月|年)前|(?:\d{4}-)?\d{1,2}-\d{1,2})"
    r"(?:\s*[\u4e00-\u9fff]{1,8})?"
    r"(?:\s+(?:作者\s*[·•.]?\s*)?(?:赞(?:\s*\d+)?|回复))*\s*$"
)


def xhs_strict_lead_filter_enabled(env=None):
    env = os.environ if env is None else env
    return str(env.get(XHS_STRICT_LEAD_FILTER_ENV, "1")).strip().lower() not in (
        "0", "false", "no", "off"
    )


def _xhs_clean_comment_text(value):
    lines = [compact_text(line, 0) for line in str(value or "").replace("\u200b", "").splitlines()]
    lines = [line for line in lines if line]
    while lines and _XHS_COMMENT_METADATA_LINE_RE.fullmatch(lines[-1]):
        lines.pop()
    text = compact_text("\n".join(lines), 0)
    while text:
        cleaned = _XHS_COMMENT_TIME_TAIL_RE.sub("", text).strip()
        if cleaned == text:
            break
        text = cleaned
    return text


def _xhs_canonical_profile_url(value):
    raw = str(value or "").strip()
    if not raw or raw == "-":
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() not in ("http", "https"):
        return ""
    if host != "xiaohongshu.com" and not host.endswith(".xiaohongshu.com"):
        return ""
    match = re.fullmatch(r"/user/profile/([^/?#]+)/?", parsed.path or "")
    if not match:
        return ""
    user_id = match.group(1).strip()
    if not user_id:
        return ""
    return "https://www.xiaohongshu.com/user/profile/" + quote(user_id, safe="-._~")


def _xhs_comment_fields(raw):
    raw = raw or {}
    user = compact_text(raw.get("user") or raw.get("u") or "", 120)
    text = compact_text(_xhs_clean_comment_text(raw.get("text") or raw.get("c") or ""), 500)
    raw_text = str(raw.get("rawText") or raw.get("raw_text") or "")
    lines = [compact_text(line, 0) for line in raw_text.splitlines()]
    lines = [line for line in lines if line]
    if not user and lines:
        user = compact_text(lines[0], 120)
    if not text and len(lines) > 1:
        text = compact_text(_xhs_clean_comment_text(lines[1]), 500)
    return user, text


def _xhs_raw_text_digg_count(value):
    lines = [compact_text(line, 0) for line in str(value or "").splitlines()]
    lines = [line for line in lines if line]
    for line in lines[2:]:
        if not _XHS_COMMENT_METADATA_LINE_RE.fullmatch(line):
            break
        match = re.search(r"赞\s*(\d+)", line)
        if match:
            return int(match.group(1))
    return None


def _xhs_normalize_comment(raw, note_id="", source=None, idx=0):
    raw = raw or {}
    source = source or {}
    user, text = _xhs_comment_fields(raw)
    profile = str(
        raw.get("profile")
        or raw.get("profileUrl")
        or raw.get("userUrl")
        or raw.get("user_url")
        or ""
    ).strip()
    digg_count = raw.get("diggCount")
    if digg_count is None or (isinstance(digg_count, str) and not digg_count.strip()):
        parsed_digg_count = _xhs_raw_text_digg_count(raw.get("rawText") or raw.get("raw_text"))
        digg_count = 0 if parsed_digg_count is None else parsed_digg_count
    effective_note_id = str(note_id or raw.get("noteId") or raw.get("awemeId") or "")
    cid = str(raw.get("id") or raw.get("commentId") or ("xhsc_" + str(idx) + "_" + uuid.uuid4().hex[:8]))
    return {
        "id": cid,
        "commentId": cid,
        "text": text,
        "c": text,
        "user": user,
        "u": user,
        "uniqueId": profile,
        "profileUrl": profile,
        "userUrl": profile,
        "user_url": profile,
        "fans": raw.get("fans") or "",
        "intent": raw.get("intent") or classify_intent(text),
        "diggCount": int(digg_count),
        "replyCount": int(raw.get("replyCount") or 0),
        "ip": raw.get("ip") or "",
        "createTime": raw.get("createTime") or 0,
        "platform": "xhs",
        "noteId": effective_note_id,
        "awemeId": effective_note_id,
        "sourceAwemeId": str(raw.get("sourceAwemeId") or effective_note_id),
        "sourceVideoUrl": raw.get("sourceVideoUrl") or source.get("work_url") or source.get("note_url") or _xhs_note_url(effective_note_id),
        "sourceVideoTitle": raw.get("sourceVideoTitle") or source.get("title") or "",
        "sourceAuthor": raw.get("sourceAuthor") or source.get("nickname") or source.get("author") or "",
    }


def _xhs_prepare_comment(raw, note_id="", source=None, idx=0, strict=None):
    item = _xhs_normalize_comment(raw, note_id=note_id, source=source, idx=idx)
    strict = xhs_strict_lead_filter_enabled() if strict is None else bool(strict)
    if not strict:
        if not item.get("user"):
            item["user"] = item["u"] = "小红书用户"
        return item, ""

    raw_profile = str(item.get("profileUrl") or "").strip()
    if not raw_profile or raw_profile == "-":
        return item, "missing_profile_url"
    profile = _xhs_canonical_profile_url(raw_profile)
    if not profile:
        return item, "invalid_profile_url"
    item["uniqueId"] = profile
    item["profileUrl"] = profile
    item["userUrl"] = profile
    item["user_url"] = profile
    user = compact_text(item.get("user"), 120)
    text = compact_text(item.get("text"), 500)
    item["user"] = item["u"] = user
    item["text"] = item["c"] = text
    if not user:
        return item, "empty_user"
    if user.casefold() == text.casefold():
        return item, "user_equals_comment"
    return item, ""


_XHS_INTENT_PRIORITY = {"高意向": 0, "中意向": 1, "咨询": 2, "普通": 3}
_XHS_FILTER_RESULT_LIMIT = 300


def _xhs_comment_rank(item):
    return (
        _XHS_INTENT_PRIORITY.get(item.get("intent"), 9),
        -int(item.get("diggCount") or 0),
    )


def _xhs_fingerprint(*values):
    raw = "\x1f".join(str(value or "") for value in values)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _xhs_redacted_exception(exc, message="xhs_comment_parse_failed"):
    try:
        redacted = type(exc)(message)
    except Exception:
        redacted = RuntimeError(message)
    try:
        raise redacted from None
    except Exception as raised:
        return raised


def _xhs_public_note_url(value):
    try:
        parsed = urlparse(str(value or "").strip())
    except Exception:
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    match = re.fullmatch(r"/explore/([^/?#]+)/?", parsed.path or "")
    if parsed.scheme.lower() not in ("http", "https") or not match:
        return ""
    if host != "xiaohongshu.com" and not host.endswith(".xiaohongshu.com"):
        return ""
    note_id = match.group(1).strip()
    return "https://www.xiaohongshu.com/explore/" + quote(note_id, safe="-._~")


def _xhs_log_collection_error(event, exc, note_id="", note_url="", log=None):
    error_id = "err-" + uuid.uuid4().hex[:16]
    context = {
        "errorId": error_id,
        "noteId": str(note_id or ""),
    }
    if note_url:
        context["noteUrlFingerprint"] = _xhs_fingerprint(note_url)
    json_log(
        log or logger,
        event,
        level="error",
        exc=_xhs_redacted_exception(exc, "xhs_collection_failed"),
        **context,
    )
    return error_id


def _xhs_log_search_failure(search, keyword="", log=None):
    search = search if isinstance(search, dict) else {}
    error_id = "err-" + uuid.uuid4().hex[:16]
    debug = search.get("debug") if isinstance(search.get("debug"), dict) else {}
    context = {
        "errorId": error_id,
        "error": str(search.get("error") or "xhs_search_failed"),
        "riskCode": str(search.get("riskCode") or ""),
        "blocked": bool(search.get("blocked")),
        "needLogin": bool(search.get("needLogin")),
        "keywordLength": len(str(keyword or "")),
        "keywordFingerprint": _xhs_fingerprint(keyword),
        "debugUrlFingerprint": _xhs_fingerprint(debug.get("url") or ""),
        "debugSnapshotAvailable": bool(debug.get("html") or debug.get("screenshot")),
    }
    json_log(
        log or logger,
        "xhs_collection_search_failed",
        level="warning",
        **context,
    )
    return error_id


def _xhs_log_discard(event, item, reason, note_id, candidate_index, log=None, exc=None):
    item = item or {}
    user = compact_text(item.get("user") or item.get("u") or "", 0)
    text = compact_text(item.get("text") or item.get("c") or "", 0)
    profile = str(
        item.get("profileUrl")
        or item.get("profile")
        or item.get("userUrl")
        or item.get("user_url")
        or ""
    )
    context = {
        "reason": reason,
        "noteId": str(note_id or item.get("noteId") or ""),
        "candidateIndex": int(candidate_index),
        "userLength": len(user),
        "commentLength": len(text),
        "recordFingerprint": _xhs_fingerprint(profile, user, text),
    }
    if profile:
        context["profileFingerprint"] = _xhs_fingerprint(profile)
    json_log(
        log or logger,
        event,
        level="error" if exc is not None else "warning",
        exc=_xhs_redacted_exception(exc) if exc is not None else None,
        **context,
    )


def _xhs_filter_comment_candidates(
    raw_items,
    note_id="",
    source=None,
    log=None,
    strict=None,
    result_limit=None,
    candidate_limit=None,
    candidate_limit_reached=False,
    candidate_duplicate_count=0,
):
    strict = xhs_strict_lead_filter_enabled() if strict is None else bool(strict)
    result_limit = (
        _XHS_FILTER_RESULT_LIMIT
        if result_limit is None
        else max(1, min(int(result_limit), _XHS_FILTER_RESULT_LIMIT))
    )
    source = source or {}
    kept = {}
    legacy_seen = set()
    legacy_items = []
    reason_counts = {}

    for idx, raw in enumerate(raw_items or []):
        try:
            item, reason = _xhs_prepare_comment(
                raw,
                note_id=note_id,
                source=source,
                idx=idx,
                strict=strict,
            )
        except Exception as exc:
            reason = "parse_failed"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            _xhs_log_discard(
                "xhs_collected_record_parse_failed",
                raw if isinstance(raw, dict) else {},
                reason,
                note_id,
                idx,
                log=log,
                exc=exc,
            )
            continue

        if strict and reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            _xhs_log_discard(
                "xhs_collected_record_filtered",
                item,
                reason,
                note_id,
                idx,
                log=log,
            )
            continue

        if not item.get("text"):
            reason = "empty_comment"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            _xhs_log_discard(
                "xhs_collected_record_filtered",
                item,
                reason,
                note_id,
                idx,
                log=log,
            )
            continue

        if not strict:
            key = (item.get("user") or "") + "|" + (item.get("text") or "")
            if key in legacy_seen:
                reason = "duplicate_user_comment"
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                _xhs_log_discard(
                    "xhs_collected_record_deduplicated",
                    item,
                    reason,
                    note_id,
                    idx,
                    log=log,
                )
                continue
            legacy_seen.add(key)
            legacy_items.append((item, idx))
            continue

        profile = item["profileUrl"]
        previous = kept.get(profile)
        if previous is None:
            kept[profile] = (item, idx)
            continue
        previous_item, previous_index = previous
        if _xhs_comment_rank(item) < _xhs_comment_rank(previous_item):
            reason = "duplicate_profile_replaced"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            _xhs_log_discard(
                "xhs_collected_record_deduplicated",
                previous_item,
                reason,
                note_id,
                previous_index,
                log=log,
            )
            kept[profile] = (item, idx)
        else:
            reason = "duplicate_profile"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            _xhs_log_discard(
                "xhs_collected_record_deduplicated",
                item,
                reason,
                note_id,
                idx,
                log=log,
            )

    if strict:
        ranked_items = sorted(
            kept.values(),
            key=lambda entry: (_xhs_comment_rank(entry[0]), entry[1]),
        )
        selected_entries = ranked_items[:result_limit]
        selected_indices = {entry[1] for entry in selected_entries}
        discarded_entries = [entry for entry in kept.values() if entry[1] not in selected_indices]
        selected_entries.sort(key=lambda entry: entry[1])
    else:
        selected_entries = legacy_items[:result_limit]
        discarded_entries = legacy_items[result_limit:]

    for discarded_item, discarded_index in discarded_entries:
        reason = "result_limit_exceeded"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        _xhs_log_discard(
            "xhs_collected_record_filtered",
            discarded_item,
            reason,
            note_id,
            discarded_index,
            log=log,
        )

    accepted = [entry[0] for entry in selected_entries]
    summary_context = {
        "noteId": str(note_id or ""),
        "candidateCount": len(raw_items or []),
        "acceptedCount": len(accepted),
        "filteredCount": sum(reason_counts.values()),
        "reasonCounts": reason_counts,
        "scope": "note" if candidate_limit is not None else "aggregate",
        "candidateLimit": int(candidate_limit) if candidate_limit is not None else None,
        "candidateLimitReached": bool(candidate_limit_reached),
        "candidateDuplicateCount": max(0, int(candidate_duplicate_count or 0)),
    }
    json_log(
        log or logger,
        "xhs_collection_filter_summary",
        level="info",
        **summary_context,
    )
    return accepted


def xhs_get_comments(note_url, limit=120, data_dir="", source=None, guest_mode=True):
    from playwright.sync_api import sync_playwright

    note_url = _xhs_note_url(note_url)
    note_id = extract_xhs_note_id(note_url)
    if not note_url:
        raise RuntimeError("missing_url")
    limit = max(1, min(int(limit or 120), 300))
    raw_candidates = []
    candidate_seen = set()
    candidate_duplicate_count = 0
    candidate_limit = 900
    comments = []
    debug = {}
    login_state = {}
    with sync_playwright() as p:
        ctx, browser = _xhs_open_context(
            p,
            data_dir=data_dir or os.getcwd(),
            headless_env="XHS_COMMENT_HEADLESS",
            persistent=(not guest_mode) and xhs_profile_ready(data_dir or os.getcwd()),
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(note_url, wait_until="domcontentloaded", timeout=45000)
            except Exception as exc:
                _xhs_log_collection_error(
                    "xhs_collection_page_navigation_failed",
                    exc,
                    note_id=note_id,
                    note_url=note_url,
                    log=logger,
                )
            page.wait_for_timeout(4500)
            login_state = _xhs_close_guest_login_modal(page)
            for _ in range(6):
                found = page.evaluate(
                    r"""(maxN) => {
                      const clean = s => (s || '').replace(/[\t\r ]+/g, ' ').trim();
                      const visible = el => {
                        const r = el.getBoundingClientRect();
                        const st = getComputedStyle(el);
                        return r.width > 40 && r.height > 10 && st.display !== 'none' && st.visibility !== 'hidden';
                      };
                      const rows = [];
                      const selectors = [
                        '[class*="comment-item"]',
                        '[class*="CommentItem"]',
                        '[data-e2e*="comment"]'
                      ];
                      const nodes = Array.from(document.querySelectorAll(selectors.join(','))).filter(visible);
                      for (const el of nodes) {
                        const rawText = (el.innerText || el.textContent || '').trim();
                        const flatText = clean(rawText.replace(/\n+/g, ' '));
                        if (!flatText || flatText.length < 2 || flatText.length > 600) continue;
                        if (/登录|打开小红书|验证码|隐私政策|服务协议/.test(flatText)) continue;
                        const link = el.querySelector('a[href*="/user/profile/"]') || el.closest('a[href*="/user/profile/"]');
                        let profile = '';
                        try {
                          profile = link ? new URL(link.getAttribute('href') || link.href, location.href).href : '';
                        } catch (_) {}
                        rows.push({rawText, profile});
                        if (rows.length >= maxN) break;
                      }
                      return rows;
                    }""",
                    candidate_limit,
                )
                for raw in found or []:
                    signature = (
                        str(raw.get("profile") or ""),
                        str(raw.get("rawText") or ""),
                    )
                    if signature in candidate_seen:
                        candidate_duplicate_count += 1
                        continue
                    candidate_seen.add(signature)
                    raw_candidates.append(raw)
                    if len(raw_candidates) >= candidate_limit:
                        break
                if len(raw_candidates) >= candidate_limit:
                    break
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(1200)
            comments = _xhs_filter_comment_candidates(
                raw_candidates,
                note_id=note_id,
                source=source or {},
                log=logger,
                result_limit=limit,
                candidate_limit=candidate_limit,
                candidate_limit_reached=len(raw_candidates) >= candidate_limit,
                candidate_duplicate_count=candidate_duplicate_count,
            )
            if not comments:
                debug = _debug_page_snapshot(page, data_dir or os.getcwd(), "xhs-comments")
        finally:
            _safe_close_context(ctx, browser)
    result = {"ok": True, "platform": "xhs", "noteId": note_id, "items": comments, "count": len(comments), "guestMode": bool(guest_mode)}
    if guest_mode and login_state.get("loginWall") and not login_state.get("closed"):
        result["loginWall"] = True
    if debug:
        result["debug"] = debug
        result = _xhs_apply_risk_from_debug(result, debug)
        body = debug.get("bodyText") or ""
        if "登录" in body and ("手机号" in body or "验证码" in body or "扫码" in body):
            result["ok"] = False
            result["needLogin"] = True
            result["error"] = "xhs_login_required"
    return xhs_guest_collection_block_error(result, "comment_read")


def discover_xhs_leads_by_keyword(keyword, video_num=5, comment_mode="page", data_dir="", guest_mode=True):
    keyword = (keyword or "").strip()
    if not keyword:
        raise RuntimeError("missing_keyword")
    video_num = max(1, min(int(video_num or 5), 20))
    errors = []
    search = xhs_search_notes(keyword, video_num, data_dir=data_dir, guest_mode=guest_mode)
    if search.get("needLogin"):
        error_id = _xhs_log_search_failure(search, keyword=keyword, log=logger)
        return {
            "ok": False,
            "needLogin": True,
            "error": search.get("error") or "xhs_login_required",
            "errorId": error_id,
            "platform": "xhs",
            "keyword": keyword,
            "videos": [],
            "videoCount": 0,
            "comments": [],
            "commentCount": 0,
            "leads": [],
            "leadCount": 0,
            "debug": search.get("debug") or {},
            "guestMode": bool(guest_mode),
        }
    if search.get("ok") is False:
        error_id = _xhs_log_search_failure(search, keyword=keyword, log=logger)
        return {
            "ok": False,
            "blocked": bool(search.get("blocked")),
            "riskCode": str(search.get("riskCode") or ""),
            "error": search.get("error") or "xhs_search_failed",
            "errorId": error_id,
            "platform": "xhs",
            "keyword": keyword,
            "videos": [],
            "videoCount": 0,
            "comments": [],
            "commentCount": 0,
            "leads": [],
            "leadCount": 0,
            "errors": [{
                "error": search.get("error") or "xhs_search_failed",
                "errorId": error_id,
                "riskCode": str(search.get("riskCode") or ""),
            }],
            "guestMode": bool(guest_mode),
        }
    videos = search.get("items") or []
    comments = []
    for v in videos[:video_num]:
        raw_note_url = v.get("work_url") or v.get("note_url")
        try:
            res = xhs_get_comments(raw_note_url, limit=80 if comment_mode != "all" else 160, data_dir=data_dir, source=v, guest_mode=guest_mode)
            comments.extend(res.get("items") or [])
        except Exception as e:
            error_id = _xhs_log_collection_error(
                "xhs_note_collection_failed",
                e,
                note_id=extract_xhs_note_id(raw_note_url),
                note_url=raw_note_url,
                log=logger,
            )
            errors.append({
                "url": _xhs_public_note_url(raw_note_url),
                "error": "xhs_comment_collection_failed",
                "errorId": error_id,
            })
    comments = _xhs_filter_comment_candidates(comments, note_id="", log=logger)
    priority = {"高意向": 0, "中意向": 1, "咨询": 2, "普通": 3}
    comments.sort(key=lambda x: (priority.get(x.get("intent"), 9), -int(x.get("diggCount") or 0)))
    leads = [x for x in comments if x.get("intent") in ("高意向", "中意向", "咨询")]
    return {
        "ok": True,
        "platform": "xhs",
        "keyword": keyword,
        "videos": videos[:video_num],
        "videoCount": len(videos[:video_num]),
        "comments": comments,
        "commentCount": len(comments),
        "leads": leads,
        "leadCount": len(leads),
        "errors": errors,
        "guestMode": bool(guest_mode),
    }


_XHS_STATIC_MEDIA_HOSTS = (
    "fe-platform.xhscdn.com",
    "picasso-static.xiaohongshu.com",
    "static.xiaohongshu.com",
)
_XHS_STATIC_MEDIA_PATTERNS = (
    "/fe-platform/",
    "/platform/",
    "/comment/",
    "/comments/",
    "avatar",
    "profile",
    "emoji",
    "icon",
    "sprite",
    "logo",
)


def _xhs_static_media_reason(url):
    u = str(url or "").strip()
    if not u:
        return "missing_url"
    low = u.lower()
    if low.startswith(("data:", "blob:", "chrome:", "about:")):
        return "unsupported_inline_image"
    if low.startswith("//"):
        low = "https:" + low
    try:
        parsed = urlparse(low)
    except Exception:
        return "invalid_url"
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if any(host == h or host.endswith("." + h) for h in _XHS_STATIC_MEDIA_HOSTS):
        return "xhs_static_media_host"
    if any(p in path for p in _XHS_STATIC_MEDIA_PATTERNS):
        return "xhs_static_media_path"
    return ""


def _xhs_filter_note_media(media, max_files=20):
    out = []
    seen = set()
    for raw in media or []:
        if not isinstance(raw, dict):
            continue
        u = str(raw.get("url") or "").strip()
        if u.startswith("//"):
            u = "https:" + u
        if _xhs_static_media_reason(u):
            continue
        kind = "video" if str(raw.get("kind") or "").lower() == "video" else "image"
        try:
            parsed = urlparse(u)
        except Exception:
            continue
        host = (parsed.netloc or "").lower()
        if not ("xhscdn.com" in host or "xiaohongshu.com" in host):
            continue
        if kind == "image":
            width = int(float(raw.get("width") or raw.get("naturalWidth") or 0))
            height = int(float(raw.get("height") or raw.get("naturalHeight") or 0))
            if width and height and (width < 160 or height < 160 or width * height < 50000):
                continue
        if u in seen:
            continue
        seen.add(u)
        item = dict(raw)
        item["url"] = u
        item["kind"] = kind
        out.append(item)
        if len(out) >= max(1, int(max_files or 20)):
            break
    return out


def _xhs_normalize_tags(*values):
    out = []
    seen = set()
    for value in values:
        if isinstance(value, str):
            parts = re.split(r"[,，\s]+", value)
        elif isinstance(value, (list, tuple, set)):
            parts = list(value)
        else:
            parts = []
        for item in parts:
            tag = str(item or "").strip()
            if not tag:
                continue
            tag = re.sub(r"^#+", "", tag).strip()
            tag = re.sub(r"\s+", "", tag)
            if not tag:
                continue
            normalized = "#" + tag
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(normalized)
    return out


def _xhs_normalize_note_copy(title="", body="", tags=None):
    title = compact_text(title, 120)
    raw_body = str(body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    embedded_tags = re.findall(r"#[^\s#，,。；;：:、]+", raw_body)
    body_without_tags = re.sub(r"#[^\s#，,。；;：:、]+", "", raw_body)
    lines = [compact_text(line, 0) for line in body_without_tags.split("\n")]
    clean_body = "\n".join(line for line in lines if line).strip()
    normalized_tags = _xhs_normalize_tags(tags or [], embedded_tags)
    return {"title": title, "body": clean_body, "tags": normalized_tags}


def _xhs_download_meta(note_id, note_url, out_dir, files, note_copy=None):
    raw_copy = note_copy if isinstance(note_copy, dict) else {}
    note_copy = _xhs_normalize_note_copy(
        title=raw_copy.get("title") or "",
        body=raw_copy.get("body") or "",
        tags=raw_copy.get("tags") or [],
    )
    valid_files = [
        f for f in (files or [])
        if isinstance(f, dict) and f.get("path") and int(f.get("size") or 0) > 0 and not f.get("error")
    ]
    meta = {
        "ok": bool(valid_files),
        "platform": "xhs",
        "noteId": note_id,
        "url": note_url,
        "savePath": out_dir,
        "files": valid_files,
        "note": dict(note_copy),
        "title": note_copy.get("title") or "",
        "body": note_copy.get("body") or "",
        "tags": note_copy.get("tags") or [],
    }
    skipped = [f for f in (files or []) if f not in valid_files]
    if skipped:
        meta["skippedFiles"] = skipped
    if not valid_files:
        meta.update({
            "error": "xhs_no_note_media",
            "stage": "download",
            "message": "no_valid_note_media",
        })
    return meta

def xhs_download_note(note_url, base_dir, data_dir="", max_files=20, guest_mode=True):
    from playwright.sync_api import sync_playwright
    import requests

    note_url = _xhs_note_url(note_url)
    note_id = extract_xhs_note_id(note_url) or uuid.uuid4().hex[:12]
    if not note_url:
        raise RuntimeError("missing_url")
    out_dir = os.path.join(base_dir, "xhs_" + note_id)
    os.makedirs(out_dir, exist_ok=True)
    media = []
    note_copy = {}
    login_state = {}
    with sync_playwright() as p:
        ctx, browser = _xhs_open_context(
            p,
            data_dir=data_dir or os.getcwd(),
            headless_env="XHS_DOWNLOAD_HEADLESS",
            persistent=(not guest_mode) and xhs_profile_ready(data_dir or os.getcwd()),
            default_headless=False,
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(note_url, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                pass
            page.wait_for_timeout(4000)
            login_state = _xhs_close_guest_login_modal(page)
            page_data = page.evaluate(
                """(args) => {
                  const maxN = Math.max(1, Number(args.maxN || 20));
                  const clean = s => String(s || '').replace(/\u200b/g, '').replace(/[ \\t]+/g, ' ').replace(/\\n{3,}/g, '\\n\\n').trim();
                  const roots = Array.from(document.querySelectorAll([
                    '#noteContainer', '.note-detail-mask', '.note-container', '.media-container',
                    '[class*="note-detail"]', '[class*="NoteDetail"]', '[class*="noteDetail"]',
                    '[class*="media-container"]', '[class*="MediaContainer"]', '[class*="swiper"]',
                    '[class*="slider"]', 'main'
                  ].join(','))).filter(el => {
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return r.width > 120 && r.height > 120 && st.display !== 'none' && st.visibility !== 'hidden';
                  });
                  const scopes = roots.length ? roots : [];
                  const urls = [];
                  const textScope = scopes.find(el => clean(el.innerText || el.textContent || '').length > 10) || document.body;
                  const add = (el, kind) => {
                    const u = el.currentSrc || el.src || el.getAttribute('src') || '';
                    if (!u || urls.some(x => x.url === u)) return;
                    const r = el.getBoundingClientRect ? el.getBoundingClientRect() : {width: 0, height: 0};
                    urls.push({
                      url: u,
                      kind,
                      width: Number(el.naturalWidth || el.videoWidth || r.width || 0),
                      height: Number(el.naturalHeight || el.videoHeight || r.height || 0),
                      className: String(el.className || '').slice(0, 120)
                    });
                  };
                  for (const root of scopes) {
                    for (const img of Array.from(root.querySelectorAll('img'))) add(img, 'image');
                    for (const v of Array.from(root.querySelectorAll('video, source'))) add(v, 'video');
                    if (urls.length >= maxN) break;
                  }
                  const firstText = selectors => {
                    for (const sel of selectors) {
                      const el = (textScope || document).querySelector(sel) || document.querySelector(sel);
                      const text = clean(el && (el.innerText || el.textContent || el.getAttribute('content')));
                      if (text) return text;
                    }
                    return '';
                  };
                  const metaTitle = clean(document.querySelector('meta[property="og:title"],meta[name="og:title"]')?.getAttribute('content') || '');
                  const metaDesc = clean(document.querySelector('meta[property="og:description"],meta[name="description"]')?.getAttribute('content') || '');
                  const title = firstText(['#detail-title', '[class*="title"]', 'h1', 'h2']) || metaTitle;
                  const body = firstText(['#detail-desc', '[class*="desc"]', '[class*="content"]', 'article']) || metaDesc;
                  const tagNodes = Array.from((textScope || document).querySelectorAll('a,span')).slice(0, 240);
                  const tags = [];
                  for (const el of tagNodes) {
                    const text = clean(el.innerText || el.textContent || '');
                    const href = String(el.getAttribute('href') || '');
                    if ((text.startsWith('#') || href.includes('keyword=') || href.includes('/hashtag/')) && text.length <= 40) {
                      tags.push(text);
                    }
                  }
                  return {media: urls.slice(0, maxN), note: {title, body, tags}};
                }""",
                {"maxN": max_files * 3, "noteId": note_id},
            )
            if isinstance(page_data, dict):
                media = page_data.get("media") or []
                note_copy = _xhs_normalize_note_copy(**(page_data.get("note") if isinstance(page_data.get("note"), dict) else {}))
            else:
                media = page_data
            media = _xhs_filter_note_media(media, max_files=max_files)
        finally:
            _safe_close_context(ctx, browser)
    files = []
    headers = {"User-Agent": "Mozilla/5.0", "Referer": note_url}
    for idx, item in enumerate(media or []):
        u = item.get("url") or ""
        if not u:
            continue
        if u.startswith("//"):
            u = "https:" + u
        try:
            r = requests.get(u, headers=headers, timeout=45)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            ext = ".mp4" if "video" in ctype or item.get("kind") == "video" else ".jpg"
            name = "%02d%s" % (idx + 1, ext)
            fp = os.path.join(out_dir, name)
            with open(fp, "wb") as f:
                f.write(r.content)
            files.append({"name": name, "path": fp, "size": os.path.getsize(fp), "url": u, "kind": item.get("kind")})
        except Exception as e:
            files.append({"name": "", "path": "", "size": 0, "url": u, "kind": item.get("kind"), "error": str(e)})
    meta = _xhs_download_meta(note_id, note_url, out_dir, files, note_copy)
    meta["guestMode"] = bool(guest_mode)
    if guest_mode and login_state.get("loginWall") and not login_state.get("closed"):
        meta["loginWall"] = True
        meta["ok"] = False
        meta["needLogin"] = True
        meta["error"] = "xhs_guest_login_required"
    try:
        with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return meta


def xhs_publish_comment(note_url, content, dry_run=False, safe_mode=True, data_dir=""):
    from playwright.sync_api import sync_playwright

    note_url = _xhs_note_url(note_url)
    note_id = extract_xhs_note_id(note_url)
    content = compact_text(content, 120 if safe_mode else 300)
    if not note_url:
        raise RuntimeError("missing_url")
    if not content:
        raise RuntimeError("missing_content")
    # 注意:note_url 需带 xsec_token(用搜索返回的 note_url);裸 /explore/<id> 会被 300031 拦。
    profile = xhs_profile_dir(data_dir or os.getcwd())
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(profile, **_browser_kwargs(profile, "XHS_COMMENT_POST_HEADLESS"))
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(note_url, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                pass
            page.wait_for_timeout(3500)
            try:
                risk_text = (page.url or "") + chr(10) + page.locator("body").inner_text(timeout=2500)
                if "300012" in risk_text or "300031" in risk_text:
                    risk_debug = _debug_page_snapshot(page, data_dir or os.getcwd(), "xhs-comment-risk")
                    return {"ok": False, "error": "xhs_ip_risk" if "300012" in risk_text else "xhs_note_unavailable",
                            "blocked": True, "riskCode": "300012" if "300012" in risk_text else "300031",
                            "hint": "笔记页需带 xsec_token(用搜索返回的 note_url);裸链接会被 300031 拦",
                            "url": page.url, "debug": risk_debug, "platform": "xhs", "noteId": note_id, "content": content}
            except Exception:
                pass
            # 滚一下让评论区/输入框渲染出来
            try:
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(1200)
            except Exception:
                pass
            if "about:blank" in (page.url or ""):
                return {"ok": False, "error": "xhs_note_unavailable", "blocked": True,
                        "hint": "笔记页未打开(token 失效/网络);note_url 需带有效 xsec_token",
                        "url": page.url, "platform": "xhs", "noteId": note_id, "content": content}
            # 定位评论框(必要时点“说点什么”触发),给它打标记,以便用 Playwright 真实事件操作。
            loc = page.evaluate(
                """async () => {
                  const visible = el => { const r=el.getBoundingClientRect(); const st=getComputedStyle(el);
                    return r.width>20 && r.height>12 && st.display!=='none' && st.visibility!=='hidden'; };
                  const pickBox = () => {
                    // 小红书 PC 评论框是 <p class="content-input" contenteditable>(占位“说点什么”是 CSS 渲染,不在文本里)
                    const cand = Array.from(document.querySelectorAll('p.content-input,[class*="content-input"],[class*="content-edit"],textarea,[contenteditable=true],[role="textbox"]')).filter(visible);
                    return cand.find(el => /content-input|content-edit|comment/i.test((el.className||'').toString()))
                        || cand.find(el => /评论|回复|说点什么/i.test((el.placeholder||el.getAttribute('aria-label')||el.innerText||'') + ' ' + (el.className||'')))
                        || cand[0] || null;
                  };
                  let box = pickBox();
                  if (!box) {
                    const trig = Array.from(document.querySelectorAll('*')).filter(visible)
                      .find(el => /说点什么|发表评论|写评论|说两句/.test((el.innerText||el.textContent||'').slice(0,24)));
                    if (trig) { trig.click(); await new Promise(r=>setTimeout(r,700)); box = pickBox(); }
                  }
                  if (!box) return {found:false};
                  box.setAttribute('data-mship-cbox','1');
                  return {found:true, isCE: !!box.isContentEditable};
                }""")
            if not (loc and loc.get("found")):
                return {"ok": False, "error": "comment_input_not_found", "url": page.url,
                        "platform": "xhs", "noteId": note_id, "content": content}
            # dry_run:只确认评论框可用,【绝不填内容、绝不点击】——写操作安全,零副作用
            if dry_run:
                return {"ok": True, "dryRun": True, "ready": True, "boxFound": True,
                        "url": page.url, "platform": "xhs", "noteId": note_id, "content": content}
            # 真发:用 Playwright 真实 pointer/键盘事件(小红书是 React,JS 的 .click()/execCommand 常不触发提交),
            # 并截获评论提交 API 响应作为“真的发出去了”的确切凭据。
            posted = {"resp": None}

            def _on_comment_resp(r):
                try:
                    if r.request.method == "POST" and "/comment/" in r.url and any(k in r.url for k in ("post", "add", "create")):
                        try:
                            posted["resp"] = {"status": r.status, "url": r.url, "body": r.json()}
                        except Exception:
                            posted["resp"] = {"status": r.status, "url": r.url}
                except Exception:
                    pass
            page.on("response", _on_comment_resp)
            clicked = False
            try:
                box = page.locator("[data-mship-cbox='1']").first
                box.click(timeout=4000)
                page.wait_for_timeout(400)
                page.keyboard.type(content, delay=45)
                page.wait_for_timeout(700)
                try:
                    sbtn = page.get_by_text("发送", exact=True)
                    if sbtn.count():
                        sbtn.first.click(timeout=3500)
                        clicked = True
                except Exception:
                    clicked = False
                if not clicked:
                    page.keyboard.press("Enter")  # 小红书评论框回车即发
                page.wait_for_timeout(3000)
            except Exception as e:
                return {"ok": False, "error": "send_interaction_failed", "detail": str(e)[:200],
                        "platform": "xhs", "noteId": note_id, "content": content, "url": page.url}
            box_empty = False
            try:
                box_empty = bool(page.evaluate(
                    "() => { const b=document.querySelector(\"[data-mship-cbox='1']\"); if(!b) return true;"
                    " return !((b.isContentEditable?b.innerText:b.value)||'').trim(); }"))
            except Exception:
                pass
            resp = posted["resp"]
            api_ok = bool(resp and 200 <= int(resp.get("status", 0)) < 300
                          and (not isinstance(resp.get("body"), dict) or resp["body"].get("success") is True))
            api_reject = None
            if resp and isinstance(resp.get("body"), dict) and resp["body"].get("success") is False:
                api_reject = resp["body"].get("msg") or ("code_%s" % resp["body"].get("code"))
            # 有评论提交 API 响应就以它为权威(禁言/风控会返回 success:false);没抓到才退而看框是否清空
            ok = api_ok if resp is not None else box_empty
            return {"ok": ok, "clicked": clicked, "viaEnter": (not clicked), "boxEmpty": box_empty,
                    "apiConfirmed": api_ok, "rejected": api_reject, "apiResp": resp,
                    "error": (None if ok else (api_reject or "send_unconfirmed")),
                    "platform": "xhs", "noteId": note_id, "content": content, "url": page.url}
        finally:
            ctx.close()


def _xhs_normalize_publish_tags(tags):
    raw = tags
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = re.split(r"[,，\s]+", raw)
        raw = parsed
    if not isinstance(raw, (list, tuple, set)):
        raw = []
    out = []
    seen = set()
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        text = re.sub(r"^[#＃]+", "", text).strip()
        if not text:
            continue
        tag = "#" + text
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            out.append(tag)
    return out


def _xhs_select_image_note_tab(page):
    try:
        clicked = page.evaluate(
            """async () => {
              const visible = el => {
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 20 && r.height > 12 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
              };
              const textOf = el => String(el.innerText || el.textContent || el.value || '').replace(/\\s+/g, ' ').trim();
              const nodes = Array.from(document.querySelectorAll('button,[role=button],a,div,span,li')).filter(visible);
              const labels = ['上传图文', '图文', '图片', '发布图文'];
              const candidates = nodes.map(el => ({el, txt:textOf(el)})).filter(x => labels.includes(x.txt));
              const target = candidates[0] || nodes.map(el => ({el, txt:textOf(el)})).find(x => /上传图文|图文|图片/.test(x.txt) && !/视频/.test(x.txt));
              if (!target) return {ok:false, error:'xhs_image_tab_not_found'};
              target.el.click();
              await new Promise(r => setTimeout(r, 1500));
              return {ok:true, text:target.txt};
            }"""
        )
        return clicked if isinstance(clicked, dict) else {"ok": bool(clicked)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def xhs_publish_material(files, title, material_type="video", dry_run=True, data_dir="", body="", tags=None):
    from playwright.sync_api import sync_playwright

    files = [f for f in (files or []) if f and os.path.exists(f)]
    if not files:
        return {"ok": False, "published": False, "error": "no_files", "platform": "xhs"}
    title = compact_text(title or Path(files[0]).stem, 80)
    material_type_code = str(material_type or "").strip().lower()
    body_text = str(body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized_tags = _xhs_normalize_publish_tags(tags)
    tag_text = " ".join(normalized_tags)
    fallbackWithTags = (body_text + ("\n\n" if body_text and tag_text else "") + tag_text).strip()
    profile = xhs_profile_dir(data_dir or os.getcwd())
    creator_url = os.getenv("XHS_CREATOR_URL") or "https://creator.xiaohongshu.com/publish/publish?source=official"
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(profile, **_browser_kwargs(profile, "XHS_PUBLISH_HEADLESS", default_headless=False))
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(creator_url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            page.wait_for_timeout(5000)
            if _is_xhs_creator_login_url(page.url):
                if not _wait_for_xhs_creator_login(page, ctx, creator_url):
                    return {"ok": False, "published": False, "error": "xhs_creator_login_required", "platform": "xhs", "final_url": page.url}
                try:
                    if page.locator("input[type=file]").count() <= 0:
                        page.goto(creator_url, wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_timeout(3000)
                except Exception:
                    pass
                if _is_xhs_creator_login_url(page.url):
                    return {"ok": False, "published": False, "error": "xhs_creator_login_required", "platform": "xhs", "final_url": page.url}
            if material_type_code == "image_note":
                # image_note must use the Xiaohongshu "上传图文" tab before file upload.
                _xhs_select_image_note_tab(page)
            inputs = page.locator("input[type=file]")
            if inputs.count() <= 0:
                return {"ok": False, "published": False, "error": "upload_input_not_found", "platform": "xhs", "final_url": page.url}
            try:
                inputs.first.set_input_files(files)
            except Exception:
                inputs.nth(0).set_input_files(files[:1])
            page.wait_for_timeout(12000)
            page.evaluate(
                """({title}) => {
                  const visible = el => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el); return r.width>20 && r.height>12 && st.display!=='none' && st.visibility!=='hidden'; };
                  const boxes = Array.from(document.querySelectorAll('input:not([type=file]):not([type=hidden]),textarea')).filter(visible);
                  for (const el of boxes.slice(0, 8)) {
                    const tag = (el.tagName || '').toUpperCase();
                    const type = String(el.getAttribute('type') || el.type || '').toLowerCase();
                    if (tag === 'INPUT' && (type === 'file' || type === 'hidden' || type === 'checkbox' || type === 'radio')) continue;
                    const current = String(el.value || el.innerText || el.textContent || '').trim();
                    const hint = ((el.placeholder||el.getAttribute('aria-label')||el.getAttribute('title')||el.innerText||'') + ' ' + (el.className||'')).toString();
                    if (/\u6807\u9898|title/i.test(hint) || (tag === 'INPUT' && !current)) {
                      el.focus();
                      const proto = tag === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                      if (desc && desc.set) desc.set.call(el, title); else el.value = title;
                      el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:title}));
                      el.dispatchEvent(new Event('change',{bubbles:true}));
                      break;
                    }
                  }
                }""",
                {"title": title},
            )
            try:
                title_inputs = page.locator("input.d-text:not([type=file]):not([type=hidden]), input[type=text]")
                for i in range(min(title_inputs.count(), 10)):
                    el = title_inputs.nth(i)
                    box = el.bounding_box()
                    if box and box.get("width", 0) > 100 and box.get("height", 0) > 10:
                        el.fill(title, timeout=5000)
                        break
            except Exception:
                pass
            tag_fill = {"ok": False}
            if tag_text:
                try:
                    tag_fill = page.evaluate(
                        """async ({tagText}) => {
                          const visible = el => {
                            const r = el.getBoundingClientRect();
                            const st = getComputedStyle(el);
                            return r.width > 20 && r.height > 12 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
                          };
                          const controls = Array.from(document.querySelectorAll('input:not([type=file]):not([type=hidden]),textarea,[contenteditable=true],[role=textbox]')).filter(visible);
                          const target = controls.find(el => {
                            const hint = String((el.placeholder || el.getAttribute('aria-label') || el.getAttribute('title') || '') + ' ' + (el.className || '')).toLowerCase();
                            return /\u8bdd\u9898|\u6807\u7b7e|tag|topic/.test(hint);
                          });
                          if (!target) return {ok:false, error:'tag_input_not_found'};
                          target.focus();
                          if (target.isContentEditable) document.execCommand('insertText', false, tagText);
                          else {
                            const tag = (target.tagName || '').toUpperCase();
                            const proto = tag === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                            const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                            if (desc && desc.set) desc.set.call(target, tagText); else target.value = tagText;
                            target.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:tagText}));
                            target.dispatchEvent(new Event('change',{bubbles:true}));
                          }
                          await new Promise(r => setTimeout(r, 500));
                          return {ok:true};
                        }""",
                        {"tagText": tag_text},
                    )
                except Exception:
                    tag_fill = {"ok": False}
            if tag_text and not (isinstance(tag_fill, dict) and tag_fill.get("ok")):
                body_text = fallbackWithTags
            try:
                editors = page.locator('[contenteditable=true].ProseMirror, .ProseMirror[contenteditable=true], [role=textbox][contenteditable=true]')
                for i in range(min(editors.count(), 5)):
                    el = editors.nth(i)
                    box = el.bounding_box()
                    if body_text and box and box.get("width", 0) > 100 and box.get("height", 0) > 30:
                        el.click(timeout=5000)
                        try:
                            page.keyboard.press("Control+A")
                        except Exception:
                            pass
                        page.keyboard.type(body_text, delay=10)
                        break
            except Exception:
                pass
            if dry_run:
                return {"ok": True, "filled": True, "published": False, "dryRun": True, "platform": "xhs", "final_url": page.url}
            clicked = page.evaluate(
                """async () => {
                  const visible = el => {
                    const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
                    return r.width > 20 && r.height > 12 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
                  };
                  const textOf = el => String(el.innerText || el.textContent || el.value || '').replace(/\s+/g, ' ').trim();
                  window.scrollTo(0, document.body.scrollHeight);
                  await new Promise(r => setTimeout(r, 800));
                  const nodes = Array.from(document.querySelectorAll('button,[role=button],a,div,span')).filter(visible).map(el => {
                    const r = el.getBoundingClientRect();
                    const txt = textOf(el);
                    return {el, txt, x:r.x, y:r.y, w:r.width, h:r.height, disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true'};
                  }).filter(x => x.txt && !x.disabled);
                  const exactPublishLabels = ['\u53d1\u5e03', '发布笔记'];
                  const submitRe = /\u53d1\u5e03|\u63d0\u4ea4|\u5b8c\u6210/;
                  let candidates = nodes.filter(x => exactPublishLabels.includes(x.txt) && x.x > 200);
                  if (!candidates.length) candidates = nodes.filter(x => submitRe.test(x.txt) && !/\u5b9a\u65f6\u53d1\u5e03|\u91cd\u65b0\u4e0a\u4f20/.test(x.txt) && x.x > 200);
                  candidates.sort((a,b) => (b.y - a.y) || (b.x - a.x));
                  const target = candidates[0];
                  if (!target) return {ok:false, error:'publish_button_not_found', seen:nodes.map(x=>({txt:x.txt,x:x.x,y:x.y,w:x.w,h:x.h})).slice(-40)};
                  target.el.click();
                  await new Promise(r=>setTimeout(r,7000));
                  return {ok:true, text:target.txt, x:target.x, y:target.y, url:location.href};
                }"""
            )
            clicked_ok = bool(clicked.get("ok") if isinstance(clicked, dict) else clicked)
            if (not clicked_ok) and isinstance(clicked, dict) and clicked.get("error") == "publish_button_not_found":
                try:
                    # XHS renders the bottom publish control outside the normal button list
                    # in the current 1280x900 creator layout.  Use a coordinate fallback
                    # only after form fill and DOM lookup have both completed.
                    viewport = page.viewport_size or {"width": 1280, "height": 900}
                    click_x = max(240, int(viewport.get("width", 1280) * 0.55))
                    click_y = max(120, int(viewport.get("height", 900) - 44))
                    page.mouse.click(click_x, click_y)
                    page.wait_for_timeout(10000)
                    coord_ok = "published=true" in (page.url or "")
                    clicked = {
                        "ok": bool(coord_ok),
                        "fallback": "coordinate",
                        "x": click_x,
                        "y": click_y,
                        "url": page.url,
                        "error": "" if coord_ok else "publish_unconfirmed",
                    }
                    clicked_ok = bool(coord_ok)
                except Exception as e:
                    clicked = {"ok": False, "fallback": "coordinate", "error": str(e), "previous": clicked}
                    clicked_ok = False
            error = ""
            if not clicked_ok:
                error = (clicked.get("error") or "publish_unconfirmed") if isinstance(clicked, dict) else "publish_button_not_found"
            return {"ok": clicked_ok, "filled": True, "published": clicked_ok, "platform": "xhs", "final_url": page.url, "button": clicked, "error": error}
        finally:
            ctx.close()
