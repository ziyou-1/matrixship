"""2026-08-06 回归:转写这一步失败不得让整份分解报告失败,且失败原因必须可见。

事故背景:客户端默认中心服改成公网地址后,转写服务地址变成非回环的明文 http,
utils.video_transcription.validate_service_url() 抛 ValueError。这个异常一路冒到
分解主流程,用户看到的是"分解失败(错误编号 err-...)"和一份没有任何分析内容的报告,
尽管抽帧和视觉分析本可以正常完成。
"""
import contextlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_client():
    backend = str(ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    spec = importlib.util.spec_from_file_location("client_transcribe_degrade", CLIENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EXPORTED_OK = {
    "status": "ok",
    "chunks": [{"path": "c0.mp3", "start": 0.0, "end": 60.0}],
    "failedRanges": [],
    "errors": [],
    "duration": 20.7,
    "limit": 20.7,
    "truncated": False,
}


class TranscribeDegradeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client()

    def _run_with(self, side_effect_target, exc):
        """跑一次转写,让指定环节抛异常,返回转写结果字典。

        注意:测试环境没有登录会话,真实 lk888_config() 拿不到 api_key,会在到达
        转写器之前就走 lk888_not_configured 分支。所以除非本次就是要让
        lk888_config 抛异常,否则必须先把它替换成一份可用配置。
        """
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
            fh.write(b"fake")
            video = fh.name
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                self.client, "export_audio_chunks", return_value=dict(EXPORTED_OK)))
            stack.enter_context(mock.patch.object(
                self.client, "_ffmpeg_exe", return_value="ffmpeg"))
            if side_effect_target != "lk888_config":
                stack.enter_context(mock.patch.object(
                    self.client, "lk888_config",
                    return_value={"base_url": "https://central.yunlingai.net/lk888",
                                  "api_key": "probe-key", "proxy": None}))
            stack.enter_context(mock.patch.object(
                self.client, side_effect_target, side_effect=exc))
            return self.client._transcribe_breakdown_audio(video)

    def test_bad_service_url_degrades_instead_of_aborting_the_breakdown(self):
        exc = ValueError("remote service URL must use https; http is allowed only for loopback hosts")

        result = self._run_with("lk888_config", exc)

        self.assertIsInstance(result, dict, "必须返回结果字典,而不是把异常抛给分解主流程")
        self.assertEqual(result.get("status"), "failed")
        self.assertEqual(result.get("code"), "transcribe_service_url_invalid")

    def test_the_reason_is_carried_back_not_swallowed(self):
        exc = ValueError("remote service URL must use https; http is allowed only for loopback hosts")

        result = self._run_with("lk888_config", exc)

        self.assertIn("https", result.get("message") or "",
                      "失败原因必须带回来,否则配置错误会被一个 failed 盖掉")

    def test_failure_inside_the_transcriber_also_degrades(self):
        """校验发生在 transcribe_audio_chunks 内部时同样不能炸掉整个分解。"""
        result = self._run_with("transcribe_audio_chunks", ValueError("service URL must be an absolute http/https URL"))

        self.assertEqual(result.get("status"), "failed")
        self.assertEqual(result.get("code"), "transcribe_service_url_invalid")

    def test_unrelated_exceptions_are_not_swallowed(self):
        """只降级 ValueError;别的异常照旧冒出去,不要把真 bug 藏起来。"""
        with self.assertRaises(RuntimeError):
            self._run_with("lk888_config", RuntimeError("boom"))


class ReportRendersTranscribeFailureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client()

    def test_report_shows_the_failure_reason_and_code(self):
        md = self.client._video_breakdown_markdown({
            "platform": "douyin",
            "sourceUrl": "https://www.douyin.com/video/1",
            "videoPath": r"D:\x\video.mp4",
            "meta": {"duration": 20.7, "width": 720, "height": 1280},
            "ocr": {"status": "unavailable", "engine": "none"},
            "transcript": {
                "status": "failed",
                "code": "transcribe_service_url_invalid",
                "message": "远程转写服务地址不合法：remote service URL must use https，已继续使用画面与 OCR 分析。",
                "retryCount": 0,
            },
        })

        self.assertIn("- 音频转写: failed", md)
        self.assertIn("转写失败原因", md)
        self.assertIn("transcribe_service_url_invalid", md)

    def test_successful_transcription_adds_no_failure_noise(self):
        md = self.client._video_breakdown_markdown({
            "platform": "douyin",
            "meta": {},
            "ocr": {},
            "transcript": {"status": "ok", "retryCount": 0, "text": "hello"},
        })

        self.assertIn("- 音频转写: ok", md)
        self.assertNotIn("转写失败原因", md)
        self.assertNotIn("转写失败代码", md)


if __name__ == "__main__":
    unittest.main()
