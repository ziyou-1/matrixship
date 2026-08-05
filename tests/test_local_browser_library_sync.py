"""2026-08-05 回归:中心素材库同步失败不得把已完成的下载判成失败。

事故背景:本地浏览器链路里,视频是在用户自己机器上下载的,中心服(Linux 容器)
拿不到用户内网的文件,mirror_download_material_to_library() 必然返回 None。旧实现
把整个任务结果改写成 ok=False / error=library_import_failed,客户端因此显示
"下载失败",分解入口显示"分解失败:下载未完成 library_import_failed",而视频其实
已经完整地在用户磁盘上。
"""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SERVER = BACKEND / "central_server.py"


def load_module(name, path):
    backend_text = str(BACKEND)
    if backend_text not in sys.path:
        sys.path.insert(0, backend_text)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def download_result():
    """本地执行器成功下载后回传的结果形状(含用户机器上的本地路径)。"""
    return {
        "ok": True,
        "accountId": "douyin-1",
        "savePath": r"D:\app\_internal\datas\accounts\44\media_datas\author\title_7657461958106915953",
        "files": [
            {"name": "video.mp4", "path": r"D:\app\...\title_765\video.mp4", "size": 6692456},
            {"name": "cover.jpg", "path": r"D:\app\...\title_765\cover.jpg", "size": 24498},
        ],
        "material": {
            "id": "local-mat-1",
            "type": "video",
            "files": ["video.mp4", "cover.jpg"],
            "sourceDownloadPath": r"D:\app\...\title_765",
        },
    }


class LibrarySyncFailureTest(unittest.TestCase):
    def setUp(self):
        self.central = load_module("central_server_library_sync", SERVER)
        self.task = {
            "id": "lbt-1",
            "type": "douyin.download",
            "orgId": "org-default",
            "clientId": "lb-ch-202607151456",
            "payload": {"url": "https://www.douyin.com/video/7657461958106915953"},
        }

    def _apply(self, result, mirrored):
        with mock.patch.object(self.central, "mirror_download_material_to_library", return_value=mirrored), \
                mock.patch.object(self.central, "item_org_id", return_value="org-default"), \
                mock.patch.object(self.central, "json_log", return_value='{"errorId": "err-test-1234"}'):
            return self.central.local_browser_apply_side_effects(None, self.task, result)

    def test_sync_failure_keeps_the_download_successful(self):
        result = download_result()

        returned = self._apply(result, None)

        # 上层 local_browser_result() 用 `side_effect_ok is False or result["ok"] is False`
        # 决定任务是 done 还是 failed —— 两个条件都必须不成立。
        self.assertTrue(returned, "同步失败不能让 side effect 返回 False")
        self.assertIsNot(result.get("ok"), False, "已完成的下载不能被改写成 ok=False")
        self.assertNotEqual(result.get("error"), "library_import_failed",
                            "同步失败不能占用 error 字段,客户端会把它当成下载错误")

    def test_sync_failure_is_still_reported_as_a_distinct_marker(self):
        result = download_result()

        self._apply(result, None)

        self.assertIs(result.get("libraryImported"), False)
        self.assertEqual(result.get("libraryError"), "library_import_failed")
        self.assertEqual(result.get("libraryErrorId"), "err-test-1234")

    def test_local_file_paths_survive_for_the_client(self):
        """客户端 _find_video_file_from_download() 靠这些字段找本地视频去分解。"""
        result = download_result()

        self._apply(result, None)

        self.assertTrue(result.get("savePath"))
        self.assertTrue(any(f.get("path") for f in result.get("files") or []))

    def test_successful_mirror_still_attaches_the_central_material(self):
        result = download_result()

        returned = self._apply(result, {"id": "central-mat-9", "type": "video"})

        self.assertTrue(returned)
        self.assertIs(result.get("libraryImported"), True)
        self.assertEqual(result.get("materialId"), "central-mat-9")
        self.assertNotIn("libraryError", result)

    def test_a_real_download_failure_is_still_a_failure(self):
        """下载本身失败仍要按失败处理,不能被这次放宽顺带放过。"""
        result = {"ok": False, "error": "download_failed"}

        returned = self._apply(result, None)

        self.assertTrue(returned)  # 提前返回,不做镜像
        self.assertIs(result.get("ok"), False)


if __name__ == "__main__":
    unittest.main()
