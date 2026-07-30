import json
import os
import re
import tempfile
import threading
import time
import warnings
from contextlib import contextmanager
import openpyxl
import requests
from loguru import logger

from utils.media_validation import validate_video_file
from utils.structured_log import json_log


_FINAL_PATH_LOCKS = {}
_FINAL_PATH_LOCKS_GUARD = threading.Lock()


class MediaDownloadError(RuntimeError):
    def __init__(self, code, context=None):
        self.code = str(code or 'media_download_failed')
        self.context = dict(context or {})
        super().__init__(self.code)


def _browser_user_agent():
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', ResourceWarning)
        from builder.header import HeaderBuilder
    return HeaderBuilder.ua


@contextmanager
def _final_path_lock(path):
    key = os.path.realpath(os.path.abspath(path))
    with _FINAL_PATH_LOCKS_GUARD:
        entry = _FINAL_PATH_LOCKS.get(key)
        if entry is None:
            entry = [threading.Lock(), 0]
            _FINAL_PATH_LOCKS[key] = entry
        entry[1] += 1

    acquired = False
    try:
        entry[0].acquire()
        acquired = True
        yield
    finally:
        if acquired:
            entry[0].release()
        with _FINAL_PATH_LOCKS_GUARD:
            entry[1] -= 1
            if entry[1] == 0 and _FINAL_PATH_LOCKS.get(key) is entry:
                del _FINAL_PATH_LOCKS[key]


def _remove_temp_file(path):
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        json_log(
            logger,
            'media_temp_cleanup_failed',
            exc=exc,
            path=path,
        )


def norm_str(str):
    new_str = re.sub(r"|[\\/:*?\"<>| ]+", "", str).replace('\n', '').replace('\r', '')
    return new_str

def norm_text(text):
    ILLEGAL_CHARACTERS_RE = re.compile(r'[\000-\010]|[\013-\014]|[\016-\037]')
    text = ILLEGAL_CHARACTERS_RE.sub(r'', text)
    return text


def timestamp_to_str(timestamp):
    time_local = time.localtime(timestamp / 1000)
    dt = time.strftime("%Y-%m-%d %H:%M:%S", time_local)
    return dt



def handle_work_info(data):
    sec_uid = data['author']['sec_uid']
    user_url = f'https://www.douyin.com/user/{sec_uid}'
    user_desc = data['author']['signature'] if 'signature' in data['author'] else '未知'
    following_count = data['author']['following_count'] if 'following_count' in data['author'] else '未知'
    follower_count = data['author']['follower_count'] if 'follower_count' in data['author'] else '未知'
    total_favorited = data['author']['total_favorited'] if 'total_favorited' in data['author'] else '未知'
    aweme_count = data['author']['aweme_count'] if 'aweme_count' in data['author'] else '未知'
    user_id = data['author']['unique_id'] if 'unique_id' in data['author'] else '未知'
    user_age = data['author']['user_age'] if 'user_age' in data['author'] else '未知'
    gender = data['author']['gender'] if 'gender' in data['author'] else '未知'
    if gender == 1:
        gender = '男'
    elif gender == 0:
        gender = '女'
    else:
        gender = '未知'
    try:
        ip_location = data['user']['ip_location']
    except:
        ip_location = '未知'
    aweme_id = data['aweme_id']
    nickname = data['author']['nickname']
    author_avatar = data['author']['avatar_thumb']['url_list'][0]
    video_cover = data['video']['cover']['url_list'][0]
    title = data['desc']
    desc = data['desc']
    duration = data.get('duration') or data.get('duration_sec') or data.get('video', {}).get('duration') or data.get('video', {}).get('duration_sec') or 0
    try:
        duration = float(duration or 0)
        if duration > 10000:
            duration = duration / 1000.0
    except (TypeError, ValueError):
        duration = 0
    admire_count = data['statistics']['admire_count'] if 'admire_count' in data['statistics'] else 0
    digg_count = data['statistics']['digg_count']
    commnet_count = data['statistics']['comment_count']
    collect_count = data['statistics']['collect_count']
    share_count = data['statistics']['share_count']
    video_addr = data['video']['play_addr']['url_list'][0]
    images = data['images']
    if not isinstance(images, list):
        images = []
    create_time = data['create_time']

    text_extra = data['text_extra'] if 'text_extra' in data else []
    text_extra = text_extra if text_extra else []
    topics = []
    for item in text_extra:
        hashtag_name = item['hashtag_name'] if 'hashtag_name' in item else ''
        if hashtag_name:
            topics.append(hashtag_name)

    work_type = '未知'
    if 'aweme_type' in data:
        if data['aweme_type'] == 68:
            work_type = '图集'
        elif data['aweme_type'] == 0:
            work_type = '视频'

    return {
        'work_id': aweme_id,
        'work_url': f'https://www.douyin.com/video/{aweme_id}',
        'work_type': work_type,
        'title': title,
        'desc': desc,
        'admire_count': admire_count,
        'digg_count': digg_count,
        'comment_count': commnet_count,
        'collect_count': collect_count,
        'share_count': share_count,
        'duration': duration,
        'video_addr': video_addr,
        'images': images,
        'topics': topics,
        'create_time': create_time,
        'video_cover': video_cover,
        'user_url': user_url,
        'user_id': user_id,
        'nickname': nickname,
        'author_avatar': author_avatar,
        'user_desc': user_desc,
        'following_count': following_count,
        'follower_count': follower_count,
        'total_favorited': total_favorited,
        'aweme_count': aweme_count,
        'user_age': user_age,
        'gender': gender,
        'ip_location': ip_location
    }


def save_to_xlsx(datas, file_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = ['作品id', '作品url', '作品类型', '作品标题', '描述', 'admire数量', '点赞数量', '评论数量', '收藏数量', '分享数量', '视频地址url', '图片地址url列表', '标签', '上传时间', '视频封面url', '用户主页url', '用户id', '昵称', '头像url', '用户描述', '关注数量', '粉丝数量', '作品被赞和收藏数量', '作品数量', '用户年龄', '性别', 'ip归属地']
    ws.append(headers)
    for data in datas:
        data = {k: norm_text(str(v)) for k, v in data.items()}
        ws.append(list(data.values()))
    wb.save(file_path)
    logger.info(f'数据保存至 {file_path}')

def download_media(path, name, url, type, auth=None, source_url='', timeout=None):
    os.makedirs(path, exist_ok=True)
    is_video = type == 'video'
    ext = '.mp4' if is_video else '.jpg'
    final_path = os.path.join(path, name + ext)
    part_path = ''
    response = None
    try:
        headers = {
            'User-Agent': _browser_user_agent(),
            'Referer': 'https://www.douyin.com/',
            'Accept': 'video/*,*/*;q=0.8' if is_video else 'image/avif,image/webp,image/*,*/*;q=0.8',
        }
        if is_video:
            headers['Range'] = 'bytes=0-'
        cookies = getattr(auth, 'cookie', None) if auth is not None else None
        read_timeout = int(timeout or os.getenv('DOUYIN_MEDIA_TIMEOUT_SEC', '180') or 180)
        response = requests.get(
            url,
            stream=True,
            headers=headers,
            cookies=cookies or None,
            timeout=(20, read_timeout),
        )
        status = int(getattr(response, 'status_code', 0) or 0)
        content_type = str((getattr(response, 'headers', {}) or {}).get('Content-Type') or '')
        if status == 403:
            raise MediaDownloadError('download_http_403', {'httpStatus': status, 'contentType': content_type})
        if status not in (200, 206):
            raise MediaDownloadError('download_http_error', {'httpStatus': status, 'contentType': content_type})
        temp_fd, part_path = tempfile.mkstemp(
            prefix=os.path.basename(final_path) + '.',
            suffix='.part',
            dir=path,
        )
        with os.fdopen(temp_fd, mode='wb') as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        with _final_path_lock(final_path):
            if is_video:
                validation = validate_video_file(part_path, content_type)
                if not validation.get('ok'):
                    raise MediaDownloadError(validation.get('code') or 'media_invalid', validation)
            else:
                if not os.path.isfile(part_path) or os.path.getsize(part_path) <= 0:
                    raise MediaDownloadError('download_empty_file', {'contentType': content_type})
                validation = {'ok': True, 'code': 'ok', 'size': os.path.getsize(part_path)}
            os.replace(part_path, final_path)
        return dict(validation, path=final_path, contentType=content_type, httpStatus=status)
    except MediaDownloadError as exc:
        _remove_temp_file(part_path)
        log_context = dict(exc.context)
        log_context.pop('code', None)
        json_log(
            logger,
            'media_download_rejected',
            exc=exc,
            code=exc.code,
            signed_url=url,
            source_url=source_url,
            media_type=type,
            **log_context,
        )
        raise
    except Exception as exc:
        _remove_temp_file(part_path)
        json_log(
            logger,
            'media_download_failed',
            exc=exc,
            code='download_exception',
            signed_url=url,
            source_url=source_url,
            media_type=type,
        )
        raise MediaDownloadError('download_exception', {'detail': str(exc)[:160]}) from exc
    finally:
        if response is not None:
            try:
                response.close()
            except Exception as exc:
                json_log(
                    logger,
                    'media_download_response_close_failed',
                    exc=exc,
                    signed_url=url,
                    source_url=source_url,
                    media_type=type,
                )


def save_wrok_detail(work, path):
    with open(f'{path}/detail.txt', mode="w", encoding="utf-8") as f:
        # 逐行输出到txt里
        f.write(f"作品id: {work['work_id']}\n")
        f.write(f"作品url: {work['work_url']}\n")
        f.write(f"作品类型: {work['work_type']}\n")
        f.write(f"作品标题: {work['title']}\n")
        f.write(f"描述: {work['desc']}\n")
        f.write(f"admire数量: {work['admire_count']}\n")
        f.write(f"点赞数量: {work['digg_count']}\n")
        f.write(f"评论数量: {work['comment_count']}\n")
        f.write(f"收藏数量: {work['collect_count']}\n")
        f.write(f"分享数量: {work['share_count']}\n")
        f.write(f"视频地址url: {work['video_addr']}\n")
        f.write(f"图片地址url列表: {', '.join(work['images'])}\n")
        f.write(f"标签: {', '.join(work['topics'])}\n")
        f.write(f"上传时间: {timestamp_to_str(work['create_time'])}\n")
        f.write(f"视频封面url: {work['video_cover']}\n")
        f.write(f"用户主页url: {work['user_url']}\n")
        f.write(f"用户id: {work['user_id']}\n")
        f.write(f"昵称: {work['nickname']}\n")
        f.write(f"头像url: {work['author_avatar']}\n")
        f.write(f"用户描述: {work['user_desc']}\n")
        f.write(f"关注数量: {work['following_count']}\n")
        f.write(f"粉丝数量: {work['follower_count']}\n")
        f.write(f"作品被赞和收藏数量: {work['total_favorited']}\n")
        f.write(f"作品数量: {work['aweme_count']}\n")
        f.write(f"用户年龄: {work['user_age']}\n")
        f.write(f"用户性别: {work['gender']}\n")
        f.write(f"ip归属地: {work['ip_location']}\n")


def download_work(work_info, path, save_choice, auth=None):
    work_id = work_info['work_id']
    user_id = work_info['user_id']
    title = work_info['title']
    title = norm_str(title)[:40]
    nickname = work_info['nickname']
    nickname = norm_str(nickname)[:20]
    if title.strip() == '':
        title = f'无标题'
    save_path = f'{path}/{nickname}_{user_id}/{title}_{work_id}'
    check_and_create_path(save_path)
    with open(f'{save_path}/info.json', mode='w', encoding='utf-8') as f:
        f.write(json.dumps(work_info) + '\n')
    work_type = work_info['work_type']
    save_wrok_detail(work_info, save_path)
    if work_type == '图集' and save_choice in ['media', 'media-image', 'all']:
        for img_index, img_url in enumerate(work_info['images']):
            download_media(save_path, f'image_{img_index}', img_url, 'image', auth=auth,
                           source_url=work_info.get('work_url') or '')
    elif work_type == '视频' and save_choice in ['media', 'media-video', 'all']:
        download_media(save_path, 'cover', work_info['video_cover'], 'image', auth=auth,
                       source_url=work_info.get('work_url') or '')
        download_media(save_path, 'video', work_info['video_addr'], 'video', auth=auth,
                       source_url=work_info.get('work_url') or '')
    logger.info(f'作品 {work_info["work_id"]} 下载完成，保存路径: {save_path}')
    return save_path



def check_and_create_path(path):
    if not os.path.exists(path):
        os.makedirs(path)
