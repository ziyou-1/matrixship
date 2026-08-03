from pathlib import Path
import ast
import os
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_assistant_helpers():
    src = CLIENT.read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    wanted = {
        "_assistant_chinese_count",
        "_assistant_build_direct_breakdown_reply",
        "_assistant_guess_collect_request",
        "_assistant_reference_info_lines",
        "_reference_breakdown_to_replacement_payload",
        "_reference_breakdown_text_to_transcript_segments",
        "_assistant_read_text_file",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    found = {node.name for node in nodes}
    missing = wanted - found
    if missing:
        raise AssertionError("missing helper(s): " + ", ".join(sorted(missing)))
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {"os": os}
    exec(compile(module, str(CLIENT), "exec"), ns)
    return ns


class WorkflowAssistantHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_assistant_helpers()

    def test_guess_collect_request_extracts_platform_keyword_and_topn(self):
        params = self.client["_assistant_guess_collect_request"](
            "从抖音上采集热门前三的丰田汽车宣传视频，告诉我这条视频是怎么拍摄的"
        )

        self.assertEqual("douyin", params["platform"])
        self.assertEqual("丰田汽车宣传", params["keyword"])
        self.assertEqual(3, params["topN"])

    def test_direct_breakdown_reply_includes_each_reference_text_and_shooting_advice(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "toyota.mp4")
            breakdown = os.path.join(tmp, "toyota.txt")
            Path(video).write_bytes(b"video")
            Path(breakdown).write_text(
                "镜头 1｜车头开场｜4秒\n画面：销售站在车头前。\n台词：今天直接交底。\n节奏：极快。\n可借鉴点：用价格悬念留住用户。",
                encoding="utf-8",
            )
            ctx = {
                "topic": "丰田汽车宣传",
                "collected": [{"title": "2027款赛那四驱臻享版最新落地价"}],
                "referenceArtifacts": [video],
                "referenceTextArtifacts": {video: breakdown},
            }

            reply = self.client["_assistant_build_direct_breakdown_reply"](
                ctx,
                "采集到 1 条『丰田汽车宣传』抖音热门,已下载 1/1 到采集参考素材",
                "已入素材库:绑定文本 1/1,生成素材 0/0,采集参考视频 1/1",
            )

            self.assertIn("采集结果", reply)
            self.assertIn("2027款赛那四驱臻享版最新落地价", reply)
            self.assertIn("镜头 1｜车头开场｜4秒", reply)
            self.assertIn("如何拍出同等价值的视频", reply)
            self.assertIn("按这条改造生成", reply)
            self.assertIn("同款替换", reply)
            self.assertNotIn("Agent.模式", reply)

    def test_reference_breakdown_payload_matches_video_replacement_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "toyota.mp4")
            Path(video).write_bytes(b"video")
            text = "镜头 1｜车头开场｜4秒\n画面：销售站在车头前。\n台词：今天直接交底。"

            payload = self.client["_reference_breakdown_to_replacement_payload"]({
                "path": video,
                "text": text,
                "title": "2027款赛那四驱臻享版最新落地价",
                "platform": "douyin",
                "sourceUrl": "https://www.douyin.com/video/1",
            })

            self.assertEqual(video, payload["sourceVideoPath"])
            self.assertEqual("https://www.douyin.com/video/1", payload["sourceUrl"])
            self.assertEqual("douyin", payload["platform"])
            self.assertEqual(text, payload["markdown"])
            self.assertEqual(video, payload["breakdownAnalysis"]["meta"]["path"])
            self.assertIn("2027款赛那四驱臻享版最新落地价", payload["breakdownAnalysis"]["visual"])
            self.assertIn("今天直接交底", payload["breakdownAnalysis"]["transcript"]["text"])


    def test_reference_breakdown_payload_builds_transcript_segments_for_replacement_scripts(self):
        text = (
            "\u955c\u5934 1\uff5c\u8f66\u5934\u5f00\u573a\uff5c4\u79d2\n"
            "\u753b\u9762\uff1a\u9500\u552e\u7ad9\u5728\u8f66\u5934\u524d\u3002\n"
            "\u53f0\u8bcd\uff1a\u4eca\u5929\u76f4\u63a5\u4ea4\u5e95\u3002\n"
            "\u8282\u594f\uff1a\u6781\u5feb\u3002\n\n"
            "\u955c\u5934 2\uff5c\u5ea7\u6905\u5c55\u793a\uff5c5\u79d2\n"
            "\u753b\u9762\uff1a\u62c9\u5f00\u4fa7\u6ed1\u95e8\u3002\n"
            "\u53f0\u8bcd\uff1a\u4e8c\u6392\u5934\u7b49\u8231\u5f88\u8212\u670d\u3002\n"
        )

        payload = self.client["_reference_breakdown_to_replacement_payload"]({
            "path": "toyota.mp4",
            "text": text,
            "title": "toyota",
        })

        segments = payload["breakdownAnalysis"]["transcript"]["segments"]
        self.assertEqual(2, len(segments))
        self.assertEqual(
            {"start": 0.0, "end": 4.0, "text": "\u4eca\u5929\u76f4\u63a5\u4ea4\u5e95\u3002"},
            segments[0],
        )
        self.assertEqual(
            {"start": 4.0, "end": 9.0, "text": "\u4e8c\u6392\u5934\u7b49\u8231\u5f88\u8212\u670d\u3002"},
            segments[1],
        )

    def test_direct_breakdown_reply_shows_collected_video_basic_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "toyota.mp4")
            breakdown = os.path.join(tmp, "toyota.txt")
            Path(video).write_bytes(b"video")
            Path(breakdown).write_text("\u955c\u5934 1\uff5c\u8f66\u5934\u5f00\u573a\uff5c4\u79d2", encoding="utf-8")
            ctx = {
                "platform": "douyin",
                "topic": "toyota",
                "collected": [{
                    "title": "Toyota demo",
                    "author": {"nickname": "\u4e30\u7530\u9500\u552e"},
                    "work_url": "https://www.douyin.com/video/123",
                    "digg_count": 1234,
                    "comment_count": 56,
                    "collect_count": 78,
                    "share_count": 9,
                    "duration": 12.5,
                }],
                "referenceArtifacts": [video],
                "referenceTextArtifacts": {video: breakdown},
            }

            reply = self.client["_assistant_build_direct_breakdown_reply"](ctx, "\u91c7\u96c6\u5b8c\u6210", "")

            self.assertIn("\u57fa\u7840\u4fe1\u606f", reply)
            self.assertIn("\u5e73\u53f0\uff1a\u6296\u97f3", reply)
            self.assertIn("\u4f5c\u8005\uff1a\u4e30\u7530\u9500\u552e", reply)
            self.assertIn("\u70b9\u8d5e\uff1a1234\uff5c\u8bc4\u8bba\uff1a56\uff5c\u6536\u85cf\uff1a78\uff5c\u5206\u4eab\uff1a9", reply)
            self.assertIn("\u65f6\u957f\uff1a12.5 \u79d2", reply)
            self.assertIn("\u94fe\u63a5\uff1ahttps://www.douyin.com/video/123", reply)
            self.assertIn("\u672c\u5730\u53c2\u8003\u89c6\u9891\uff1atoyota.mp4", reply)


if __name__ == "__main__":
    unittest.main()
