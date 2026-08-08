"""远程已出片、本地没下到,不能当成「生成失败」丢掉。

事故:Agent.模式视频生成成功(成品 4.55MB 确实在 cos.lingkeai.vip 上),
下载时 TLS 被掐断抛 SSLEOFError,整条被标记为「失败」。
而扣费发生在 lk888 返回结果那一刻(中心服按实际用量结算),比下载早;
客户端的 refund_cap 对 _SERVER_CHARGED_CAPS 是空操作。
结果就是:钱花了、片子在服务器上、UI 上却没有任何办法拿回来。
"""
from pathlib import Path
import importlib.util
import os
import tempfile
import unittest
from unittest import mock

import requests


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_client_module(name="matrix_native_client_download_recovery_test"):
    spec = importlib.util.spec_from_file_location(name, CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WfDownloadRetryTest(unittest.TestCase):
    def setUp(self):
        self.module = load_client_module()

    def test_a_signature_expiry_is_never_retried(self):
        """403 手里只有一个死 URL,重试一百次还是 403,只会掩盖真实原因。"""
        response = mock.Mock(status_code=403)
        self.assertFalse(self.module._wf_download_should_retry(
            requests.exceptions.HTTPError(response=response)))

    def test_transient_connection_failures_are_retried(self):
        for exc in (requests.exceptions.SSLError("EOF"),
                    requests.exceptions.ConnectionError("reset"),
                    requests.exceptions.Timeout("read timed out"),
                    requests.exceptions.ChunkedEncodingError("broken")):
            with self.subTest(exc=type(exc).__name__):
                self.assertTrue(self.module._wf_download_should_retry(exc))
        for code in (500, 502, 503, 504, 429, 408):
            with self.subTest(status=code):
                self.assertTrue(self.module._wf_download_should_retry(
                    requests.exceptions.HTTPError(response=mock.Mock(status_code=code))))

    def test_a_local_disk_error_is_not_a_network_retry(self):
        self.assertFalse(self.module._wf_download_should_retry(OSError("no space left")))

    def test_a_transient_failure_then_success_still_delivers_the_file(self):
        calls = {"n": 0}

        def fake_get(url, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")
            return _ok_response(b"video-bytes")

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "out.mp4")
            with mock.patch.object(self.module.requests.Session, "get", side_effect=fake_get), \
                    mock.patch.object(self.module.time, "sleep"):
                self.module._wf_download("https://x/a.mp4", target)

            self.assertEqual(2, calls["n"], "第一次 SSL 断开后必须重试")
            self.assertEqual(b"video-bytes", open(target, "rb").read())

    def test_a_failed_download_leaves_no_half_written_file(self):
        """半截文件会骗过调用方「已存在且非空就跳过重下」的判断。"""
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "out.mp4")
            with mock.patch.object(self.module.requests.Session, "get",
                                   side_effect=requests.exceptions.SSLError("EOF")), \
                    mock.patch.object(self.module.time, "sleep"):
                with self.assertRaises(requests.exceptions.SSLError):
                    self.module._wf_download("https://x/a.mp4", target)

            self.assertFalse(os.path.exists(target))
            self.assertFalse(os.path.exists(target + ".part"))


class DownloadRecoveryEntryTest(unittest.TestCase):
    def setUp(self):
        self.module = load_client_module()

    def test_regen_must_not_carry_the_previous_result_url(self):
        """regen 是黑名单复制。漏掉这个字段,「再次生成」出来的新卡片会带着上一条的
        结果 URL,点「恢复下载」拿到的是上一次的视频 —— 静默的错误结果。"""
        self.assertIn("pendingDownloadRecovery", self.module._PRODGEN_RUNTIME_KEYS)

    def test_recovery_needs_a_result_url_to_be_usable(self):
        self.assertEqual({}, self.module._prodgen_download_recovery({}))
        self.assertEqual({}, self.module._prodgen_download_recovery(
            {"pendingDownloadRecovery": {"taskId": "97267053"}}), "没有 URL 就不是可恢复状态")
        pending = {"resultUrl": "https://cdn/a.mp4", "taskId": "97267053"}
        self.assertEqual(pending, self.module._prodgen_download_recovery(
            {"pendingDownloadRecovery": pending}))

    def test_the_result_url_and_task_id_are_stored_before_downloading(self):
        """必须在下载之前落盘 —— 下载失败之后就再也拿不到了。"""
        saved = {}
        entry = {"id": "pg_1", "mode": "video"}
        with mock.patch.object(self.module, "update_prodgen",
                               side_effect=lambda pid, **kw: saved.update(kw)):
            self.module._prodgen_remember_result(entry, "https://cdn/a.mp4", "97267053",
                                                 "doubao-seedance-1-5-pro-251215", ["C:/out.mp4"])

        pending = saved["pendingDownloadRecovery"]
        self.assertEqual("https://cdn/a.mp4", pending["resultUrl"])
        self.assertEqual("97267053", pending["taskId"], "签名过期后只能靠 task_id 换新链接")
        self.assertEqual(["C:/out.mp4"], pending["targets"])

    def test_media_task_hands_the_url_over_before_returning(self):
        import inspect

        src = inspect.getsource(self.module.lk888_media_task)
        self.assertIn("on_result", inspect.signature(self.module.lk888_media_task).parameters)
        self.assertLess(src.index("on_result(url, task)"), src.index("return url"),
                        "必须在 return 之前回调,否则下载失败时 URL 已经丢了")

        for name in ("_prodgen_run_image", "_prodgen_run_video"):
            with self.subTest(fn=name):
                self.assertIn("_prodgen_remember_result", inspect.getsource(getattr(self.module, name)))

    def test_recovering_a_download_never_starts_a_new_paid_generation(self):
        """看真正被调用的函数,不看注释里提到的名字。"""
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(self.module.ProductGenPage.recover_download)))
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    called.add(fn.id)
                elif isinstance(fn, ast.Attribute):
                    called.add(fn.attr)

        self.assertIn("_wf_download", called, "恢复下载就是重新拉一次文件")
        for forbidden in ("_prodgen_generate", "try_charge", "_start", "lk888_media_task"):
            with self.subTest(call=forbidden):
                self.assertNotIn(forbidden, called, "恢复下载不能重新跑模型,那会再扣一次钱")

    def test_the_user_never_sees_a_raw_ssl_stack(self):
        raw = ("HTTPSConnectionPool(host='cos.lingkeai.vip', port=443): Max retries exceeded with url: "
               "/uploads/2026.08/07/x.mp4 (Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF...")

        text = self.module._prodgen_download_error_text(raw)

        self.assertNotIn("cos.lingkeai.vip", text)
        self.assertNotIn("SSL", text)
        self.assertIn("恢复下载", text)
        self.assertIn("不再扣费", text)

    def test_an_expired_link_tells_the_user_to_regenerate_instead(self):
        text = self.module._prodgen_download_error_text("403 Client Error: Forbidden")

        self.assertIn("过期", text)
        self.assertNotIn("恢复下载", text, "链接过期时重下没用,别引导用户白点")


def _ok_response(body):
    response = mock.MagicMock()
    response.__enter__ = lambda s: s
    response.__exit__ = lambda s, *a: False
    response.raise_for_status = lambda: None
    response.iter_content = lambda chunk_size=0: [body]
    return response


if __name__ == "__main__":
    unittest.main()
