"""
本机浏览器登录抖音 → 抓取完整登录态 → 推送到线上账号矩阵。

用途：替代线上 :9080 服务器端扫码（抖音风控下常年 qr_not_found）。
本脚本在你自己的电脑上打开 Edge，让你像平时一样手动登录（扫码 / 密码 /
短信验证都在真实浏览器里完成），登录成功后自动抓取 cookies + localStorage
（Playwright storageState），上传到 juzhen-api 的 /api/login/import，
账号随即出现在「账号矩阵」里，供搜索 / 评论 / 发布等功能复用。

用法：
    python local_login.py
环境变量（可选）：
    JUZHEN_API        线上后端地址，默认 http://118.178.32.71:9080
    DY_EDGE_PATH      Edge 可执行路径，默认系统安装路径
    DY_LOGIN_TIMEOUT  等待登录的最长秒数，默认 300
    DY_ACCOUNT_ID     指定账号 id（不填则服务器随机生成）
"""

import asyncio
import json
import os
import sys

import requests
from playwright.async_api import async_playwright

SERVER = os.getenv('MATRIX_CENTRAL', os.getenv('JUZHEN_API', 'https://central.yunlingai.net')).rstrip('/')
EDGE = os.getenv('DY_EDGE_PATH', r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
LOGIN_TIMEOUT = int(os.getenv('DY_LOGIN_TIMEOUT', '300'))
ACCOUNT_ID = os.getenv('DY_ACCOUNT_ID', '')

HOME = 'https://www.douyin.com/'
# 这些 cookie 出现 = 已登录（与服务器 PLAT.douyin.auth 对齐）
AUTH_MARKERS = ['sessionid', 'sessionid_ss', 'sid_guard', 'uid_tt', 'passport_csrf_token']
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'datas', 'douyin_storage_state.json')


async def login_and_capture():
    async with async_playwright() as p:
        launch_kwargs = dict(
            headless=False,  # 必须有头：你要在真实窗口里登录
            args=['--disable-blink-features=AutomationControlled'],
        )
        if os.path.exists(EDGE):
            launch_kwargs['executable_path'] = EDGE
        browser = await p.chromium.launch(**launch_kwargs)
        ctx = await browser.new_context(locale='zh-CN', timezone_id='Asia/Shanghai')
        page = await ctx.new_page()
        await page.goto(HOME, wait_until='domcontentloaded')
        print('>> 已打开抖音。请在弹出的浏览器窗口里完成登录（扫码 / 密码 / 短信验证都在这里做）。')
        print(f'>> 登录成功后脚本会自动检测并抓取登录态…（最多等待 {LOGIN_TIMEOUT} 秒）')

        captured = None
        waited = 0
        while waited < LOGIN_TIMEOUT:
            try:
                cookies = await ctx.cookies()
            except Exception:
                cookies = []
            names = {c['name'] for c in cookies if c.get('value')}
            if any(m in names for m in AUTH_MARKERS):
                print('>> 检测到登录态，3 秒后抓取完整 cookie + localStorage…')
                await asyncio.sleep(3)
                captured = await ctx.storage_state()
                break
            await asyncio.sleep(2)
            waited += 2

        await browser.close()
        return captured


def upload(state):
    payload = {'platform': 'douyin', 'storageState': state}
    if ACCOUNT_ID:
        payload['id'] = ACCOUNT_ID
    print(f'>> 正在上传到线上账号矩阵 {SERVER}/api/login/import …')
    r = requests.post(SERVER + '/api/login/import', json=payload, timeout=120)
    print('<< 服务器响应:', r.status_code, r.text[:400])
    try:
        data = r.json()
    except Exception:
        data = {}
    if r.ok and data.get('ok'):
        acc = data.get('account', {})
        print(f'账号已加入矩阵：{acc.get("id")}（cookie {data.get("cookieCount")} 条），刷新客户端即可看到。')
        return True
    print('!! 上传未成功，登录态已本地备份，可重试。')
    return False


def main():
    state = asyncio.run(login_and_capture())
    if not state:
        print('!! 等待登录超时，未捕获到登录态。请重新运行重试。')
        sys.exit(1)

    names = [c['name'] for c in state.get('cookies', [])]
    if not any(m in names for m in AUTH_MARKERS):
        print('!! 抓到的 cookie 里没有 sessionid 等登录标记，判定未登录，未上传。')
        sys.exit(1)

    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    with open(BACKUP, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)
    print(f'>> 已本地备份登录态 -> {BACKUP}（cookie {len(names)} 条）')

    try:
        upload(state)
    except Exception as e:
        print('!! 上传失败：', e)
        print(f'   修复网络后可重跑本脚本，或把 {BACKUP} 手动导入。')


if __name__ == '__main__':
    main()
