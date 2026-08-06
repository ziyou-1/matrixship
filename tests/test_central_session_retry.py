"""2026-08-06 回归:中心服请求必须复用连接,并且只在建连阶段重试。

现象:账户中心间歇报"账单数据暂时不可用"。客户端日志的原始错误是
HTTPSConnectionPool(host='central.yunlingai.net', port=443): Max retries exceeded,
即 TLS 握手失败,几秒后自愈。

实测(与客户端同栈的 requests):HTTPS 443 失败率在 10%~42% 之间波动,而直连
9080(不经 nginx)12/12 全通,服务器自测 15/15 全通,img/www/central 三站失败率一致
——说明是链路层的间歇故障,不是某个站点或中心服的问题。

原实现每次调用都新建 TCP+TLS 连接,所以每个请求都独立暴露在握手失败概率下;
账户中心一屏要发多个请求,命中概率被放大。
"""
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_client():
    backend = str(ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    spec = importlib.util.spec_from_file_location("client_session_retry", CLIENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CentralSessionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client()

    def test_requests_go_through_a_pooled_session(self):
        """连接复用能大幅减少握手次数,是这次修复的主要收益。"""
        import requests

        self.assertIsInstance(self.client._CENTRAL_SESSION, requests.Session)
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("_CENTRAL_SESSION.request(", src,
                      "api() 必须走共享 Session,否则每次调用都重新握手")

    def test_https_and_http_are_both_mounted(self):
        for prefix in ("https://", "http://"):
            self.assertIn(prefix, self.client._CENTRAL_SESSION.adapters)

    def test_retry_is_limited_to_connection_setup(self):
        """只重试 connect。read/status 重试会重发可能已被处理的请求 —— 重复扣费。"""
        adapter = self.client._CENTRAL_SESSION.get_adapter("https://central.yunlingai.net")
        retry = adapter.max_retries

        self.assertGreaterEqual(retry.connect, 2, "握手失败必须重试")
        self.assertEqual(retry.read, 0, "读阶段失败不得重试:服务端可能已经处理过")
        self.assertEqual(retry.status, 0, "不得按状态码重试:POST 可能已扣费")
        self.assertGreater(retry.backoff_factor, 0, "必须退避,否则瞬时故障期间空转")

    def test_retry_does_not_exclude_post(self):
        """allowed_methods=None 表示不按方法过滤;安全性由 read=0/status=0 保证。"""
        adapter = self.client._CENTRAL_SESSION.get_adapter("https://central.yunlingai.net")

        self.assertIsNone(adapter.max_retries.allowed_methods)


if __name__ == "__main__":
    unittest.main()
