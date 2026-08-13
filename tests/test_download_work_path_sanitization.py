# coding: utf-8
"""Regression tests for video-breakdown download path sanitization.

Root cause of "分解失败:下载未完成 [WinError 267] 目录名称无效":
`download_work` interpolates the douyin `user_id`/`work_id` fields straight into
a Windows save path. Only `title`/`nickname` were run through `norm_str`, so a
colon (or control char) in the remote-controlled id fields produced an invalid
directory name and an uncaught OSError that leaked to the user verbatim.

These tests drive the REAL `download_work` (network download stubbed) and assert
the save path is always a creatable directory.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import utils.data_util as data_util  # noqa: E402


def _work_info(**overrides):
    info = {
        "work_id": "7412345678901234567",
        "user_id": "creator.handle",
        "title": "普通标题",
        "nickname": "达人昵称",
        "work_type": "视频",
        "desc": "普通标题",
        "video_addr": "https://example.test/v.mp4",
        "video_cover": "https://example.test/c.jpg",
        "images": [],
        "topics": [],
        "work_url": "https://www.douyin.com/video/7412345678901234567",
        "admire_count": 0, "digg_count": 0, "comment_count": 0,
        "collect_count": 0, "share_count": 0, "create_time": 0,
        "user_url": "u", "author_avatar": "a", "user_desc": "d",
        "following_count": 0, "follower_count": 0, "total_favorited": 0,
        "aweme_count": 0, "user_age": 0, "gender": 0, "ip_location": "x",
    }
    info.update(overrides)
    return info


class DownloadWorkPathSanitizationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Stub the network media download; we only exercise path/dir/file setup.
        patcher = mock.patch.object(
            data_util, "download_media", return_value={"ok": True, "path": ""}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, **overrides):
        save_path = data_util.download_work(
            _work_info(**overrides), self.tmp.name, "all", auth=None
        )
        # download_work must return a real, existing directory (never crash).
        self.assertTrue(os.path.isdir(save_path), save_path)
        # info.json / detail.txt must have been written into it.
        self.assertTrue(os.path.isfile(os.path.join(save_path, "info.json")))
        return save_path

    def test_colon_in_work_id_does_not_raise_winerror_267(self):
        # The exact reported failure: a ':' in an unsanitized id field made
        # Windows read the path as an NTFS alternate data stream -> WinError 267.
        self._run(work_id="7412:0")

    def test_colon_in_user_id_does_not_raise_winerror_267(self):
        self._run(user_id="creator:handle")

    def test_control_char_in_title_does_not_raise(self):
        # Sibling defect: control chars survived norm_str -> WinError 123.
        self._run(title="教程\t进阶\x01技巧")

    def test_reserved_windows_chars_in_all_fields(self):
        save_path = self._run(
            work_id='7412<>:"|?*',
            user_id='a:b/c\\d',
            title='标题:测试<非法>字符',
            nickname='昵称|作者',
        )
        # Nothing but the temp root, two nested dirs, and safe separators remain.
        leaf = os.path.basename(save_path)
        for bad in '<>:"/\\|?*':
            self.assertNotIn(bad, leaf, f"illegal char {bad!r} leaked into {leaf!r}")

    def test_normal_title_still_produces_readable_folder(self):
        save_path = self._run(title="夏日穿搭分享", nickname="小美", user_id="xiaomei")
        leaf = os.path.basename(save_path)
        self.assertIn("夏日穿搭分享", leaf)


if __name__ == "__main__":
    unittest.main()
