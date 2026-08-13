"""生成结果绝不能是本次传进去的参考图。

现象:Agent.模式改图,页面上两张「生成结果」与上传的原图 sha1 完全一致。
原因:LK888 任务状态里会回显请求参数,而参考图和成品都是 .png,
`_extract_lk888_media_url` 只按后缀挑第一个 URL,就把用户自己的图当成结果下载了。
后果比报错更糟 —— 不报错、照常扣费、用户拿回自己的图。
"""
from pathlib import Path
import importlib.util
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"

REF = "https://img.yunlingai.net/agent/ref-1.png"
OUT = "https://cdn.lk888.ai/output/generated-9527.png"


def load_client_module(name="matrix_native_client_result_echo_test"):
    spec = importlib.util.spec_from_file_location(name, CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentResultNotInputEchoTest(unittest.TestCase):
    def setUp(self):
        self.module = load_client_module()
        self.exts = ["png", "jpg", "jpeg", "webp"]

    def extract(self, obj, exclude=None):
        return self.module._extract_lk888_media_url(obj, self.exts, exclude=exclude)

    def test_echoed_reference_image_is_not_mistaken_for_the_result(self):
        """任务状态回显了请求参数,成品在更后面的字段里。

        `images` / `image_urls` / `reference_images` 都不在优先键名表里,所以走的是「遍历所有键、
        遇到第一个 .png 就返回」那条路 —— 回显的参考图排在前面就赢了。
        """
        status = {
            "data": {
                "params": {"images": [REF], "image_urls": [REF], "reference_images": [REF]},
                "outputs": [{"image": OUT}],
            }
        }

        self.assertEqual(REF, self.extract(status), "旧行为:第一个 .png 就返回,拿到的是输入")
        self.assertEqual(OUT, self.extract(status, exclude=[REF]))

    def test_a_preferred_result_key_already_wins_today(self):
        """响应里带 result_url 这类优先键名时本来就不会出错,排除逻辑不能把它弄坏。"""
        status = {"data": {"params": {"images": [REF]}, "result_url": OUT}}

        self.assertEqual(OUT, self.extract(status))
        self.assertEqual(OUT, self.extract(status, exclude=[REF]))

    def test_signed_reference_url_still_matches_after_the_signature_changes(self):
        """参考图 URL 带签名,每次查状态签名都不同,比对必须忽略 query。"""
        status = {"data": {"images": [REF + "?sign=aaa&t=1"], "result_url": OUT}}

        self.assertEqual(OUT, self.extract(status, exclude=[REF + "?sign=bbb&t=2"]))

    def test_no_result_is_better_than_returning_the_users_own_picture(self):
        """只有输入、没有成品时必须返回空,让轮询继续/最终报错 ——
        绝不能把用户上传的图当成结果下载下来还照常扣费。"""
        status = {"data": {"params": {"images": [REF]}, "image_urls": [REF]}}

        self.assertEqual("", self.extract(status, exclude=[REF]))

    def test_reference_video_is_excluded_too(self):
        src = "https://img.yunlingai.net/agent/source.mp4"
        out = "https://cdn.lk888.ai/output/final.mp4"
        status = {"data": {"video_url": src, "result": {"videoUrl": out}}}

        self.assertEqual(out, self.module._extract_lk888_media_url(status, ["mp4", "mov"], exclude=[src]))

    def test_without_an_exclude_list_behaviour_is_unchanged(self):
        """没有参考图的纯文生图不受影响。"""
        status = {"data": {"result_url": OUT}}

        self.assertEqual(OUT, self.extract(status))
        self.assertEqual(OUT, self.extract(status, exclude=[]))

    def test_matching_ignores_query_fragment_and_case(self):
        """通过行为验证归一化,而不是去测内部实现。"""
        status = {"data": {"params": {"images": ["https://IMG.example.com/Ref.PNG?sign=x#f"]},
                           "outputs": [{"image": OUT}]}}

        self.assertEqual(OUT, self.extract(status, exclude=["https://img.example.com/Ref.png"]))

    def test_a_different_file_on_the_same_host_is_still_a_valid_result(self):
        other = "https://img.yunlingai.net/agent/ref-2.png"
        status = {"data": {"params": {"images": [REF]}, "outputs": [{"image": other}]}}

        self.assertEqual(other, self.extract(status, exclude=[REF]), "只排除本次传进去的那几个 URL")

    def test_media_task_passes_the_exclude_list_through(self):
        import inspect

        sig = inspect.signature(self.module.lk888_media_task)
        self.assertIn("exclude_urls", sig.parameters)
        src = inspect.getsource(self.module.lk888_media_task)
        self.assertIn("exclude=exclude_urls", src)

        for name in ("_prodgen_run_image", "_prodgen_run_video"):
            with self.subTest(fn=name):
                self.assertIn("exclude_urls=", inspect.getsource(getattr(self.module, name)),
                              "%s 必须把本次上传的素材传下去" % name)


if __name__ == "__main__":
    unittest.main()
