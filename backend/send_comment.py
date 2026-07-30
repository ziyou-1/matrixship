# coding: utf-8
"""
?????? / AI ????????? 9080 ????

?????
  python send_comment.py --url "https://www.douyin.com/video/123" --content "????"
  python send_comment.py --aweme-id 123 --reply-id 456 --content "????????????????"

AI ?????????? -> ??? -> AI ???? -> ??/????
  python send_comment.py --keyword "???" --template "?????{comment}??{keyword}????????????????" --limit 3

????????? --dry-run ??? payload??????
"""
import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict

import requests
from runtime_paths import agent_data_dir


DEFAULT_API = os.getenv('DY_API_BASE', 'http://127.0.0.1:9080')


def local_agent_token() -> str:
    tok = (os.getenv('MATRIX_AGENT_TOKEN') or os.getenv('DY_AGENT_TOKEN') or '').strip()
    if tok:
        return tok
    try:
        p = os.path.join(agent_data_dir(), 'agent_token.txt')
        if os.path.isfile(p):
            return open(p, 'r', encoding='utf-8').read().strip()
    except Exception:
        pass
    return ''


def configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass


def post_json(api_base: str, path: str, payload: Dict[str, Any], timeout: int = 300) -> Dict[str, Any]:
    url = api_base.rstrip('/') + path
    headers = {}
    tok = local_agent_token()
    if tok:
        headers['X-Matrix-Agent-Token'] = tok
    r = requests.post(url, json=payload, timeout=timeout, headers=headers)
    try:
        data = r.json()
    except Exception:
        data = {'ok': False, 'statusCode': r.status_code, 'raw': r.text[:2000]}
    if r.status_code >= 400:
        data.setdefault('ok', False)
        data.setdefault('httpStatus', r.status_code)
    return data


def print_result(data: Dict[str, Any]) -> int:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if data.get('results') is not None:
        sent = data.get('sentCount', 0)
        target = data.get('targetCount', 0)
        print(f"\n[summary] targets={target} sent_or_preview_ok={sent} dryRun={data.get('dryRun')}")
        for item in data.get('results') or []:
            mark = 'OK' if item.get('ok') else 'FAIL'
            mode = 'reply' if item.get('replyId') else 'comment'
            print(f"[{mark}] {mode} aweme={item.get('awemeId')} lead={item.get('leadUser') or '-'} text={item.get('content')}")
        return 0 if data.get('ok') else 2
    mark = 'OK' if data.get('ok') else 'FAIL'
    print(f"\n[{mark}] aweme={data.get('awemeId') or (data.get('request') or {}).get('awemeId')} reply={data.get('replyId') or (data.get('request') or {}).get('replyId') or '-'}")
    return 0 if data.get('ok') else 2


def main() -> int:
    configure_stdout()
    ap = argparse.ArgumentParser(description='?????? / AI ????')
    ap.add_argument('--api', default=DEFAULT_API, help='????????? http://127.0.0.1:9080')
    ap.add_argument('--url', default='', help='?? URL??? /video/ID ? modal_id=ID')
    ap.add_argument('--aweme-id', '--aweme_id', dest='aweme_id', default='', help='?? aweme_id')
    ap.add_argument('--reply-id', '--reply_id', dest='reply_id', default='', help='????? cid??????????')
    ap.add_argument('--content', '--text', default='', help='????????')
    ap.add_argument('--dry-run', action='store_true', help='?????????')
    ap.add_argument('--no-safe-mode', action='store_true', help='?????????????????? status_code=8?')
    ap.add_argument('--no-preflight', action='store_true', help='??????????')
    ap.add_argument('--force', action='store_true', help='??????????')
    ap.add_argument('--channel', choices=['auto', 'api', 'edge-ui'], default='auto',
                    help='auto=API失败/登录门控时回落到当前Edge窗口；api=只走接口；edge-ui=强制走当前Edge窗口')

    ap.add_argument('--keyword', default='', help='AI ??????????????/??/????')
    ap.add_argument('--template', default='', help='AI ??????? {keyword}/{comment}/{title}/{author}/{user}/{intent}')
    ap.add_argument('--video-num', type=int, default=5, help='??????')
    ap.add_argument('--limit', type=int, default=5, help='????/????')
    ap.add_argument('--send-mode', choices=['reply', 'comment'], default='reply', help='reply=???????comment=???????')
    ap.add_argument('--interval-sec', type=float, default=0.8, help='???????????')
    args = ap.parse_args()

    if args.keyword:
        payload = {
            'keyword': args.keyword,
            'template': args.template,
            'videoNum': args.video_num,
            'limit': args.limit,
            'sendMode': args.send_mode,
            'intervalSec': args.interval_sec,
            'dryRun': args.dry_run,
            'safeMode': not args.no_safe_mode,
            'preflight': not args.no_preflight,
            'force': args.force,
            'channel': args.channel,
        }
        print('[request] POST /api/outreach/run')
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        data = post_json(args.api, '/api/outreach/run', payload, timeout=600)
        return print_result(data)

    if not (args.url or args.aweme_id):
        print('ERROR: ?? --url ? --aweme-id??? AI ????? --keyword', file=sys.stderr)
        return 64
    if not args.content:
        print('ERROR: ?? --content', file=sys.stderr)
        return 64
    payload = {
        'url': args.url,
        'awemeId': args.aweme_id,
        'replyId': args.reply_id,
        'content': args.content,
        'dryRun': args.dry_run,
        'safeMode': not args.no_safe_mode,
        'preflight': not args.no_preflight,
        'force': args.force,
        'channel': args.channel,
    }
    print('[request] POST /api/douyin/comment/publish')
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    data = post_json(args.api, '/api/douyin/comment/publish', payload, timeout=300)
    return print_result(data)


if __name__ == '__main__':
    raise SystemExit(main())
