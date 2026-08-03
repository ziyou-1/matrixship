from pathlib import Path
import ast
import os
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_workflow_helpers():
    src = CLIENT.read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    wanted = {
        "_workflow_script_too_short",
        "_workflow_filename_part",
        "_workflow_generate_script",
        "_workflow_save_script_artifact",
        "_workflow_skip_media_summary",
        "_workflow_is_video_artifact",
        "_workflow_is_image_artifact",
        "_workflow_split_reference_downloads",
        "_workflow_clean_breakdown_cell",
        "_workflow_ensure_reference_text_artifacts",
        "_workflow_normalize_reference_breakdown_text",
        "_exec_vision",
        "_exec_image",
        "_exec_video",
        "_exec_tts",
        "_workflow_downloaded_paths",
        "_workflow_artifact_kind",
        "_exec_collect",
        "_exec_library",
        "_exec_publish",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {"os": os, "time": time}
    exec(compile(module, str(CLIENT), "exec"), ns)
    return ns


class WorkflowResilienceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_workflow_helpers()

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.client["_wf_out_dir"] = mock.Mock(return_value=self._tmpdir.name)
        for key in ("lk888_vision", "lk888_chat", "kb_context", "add_asset"):
            self.client.pop(key, None)

        def fake_reference_analysis(path, item=None, topic="", out_dir=None, progress=None):
            del item, topic, out_dir
            if callable(progress):
                progress("stub reference analysis")
            vision = self.client.get("lk888_vision")
            visual = vision("stub reference analysis", [path]) if callable(vision) else "镜头1：参考画面"
            return {
                "analysis": {
                    "meta": {"duration": 8.0, "path": path},
                    "visual": str(visual),
                    "transcript": {"status": "ok", "text": "", "segments": []},
                },
                "markdown": "镜头1：参考画面\n" + str(visual),
            }

        def fake_save_reference_analysis_artifact(ctx, path, analysis):
            ctx.setdefault("referenceAnalyses", {})[path] = analysis
            return ""

        def add_reference_asset(path, **kwargs):
            kwargs.pop("analysis_path", None)
            kwargs.setdefault("kind", self.client["_workflow_artifact_kind"](path))
            kwargs.setdefault("text_path", kwargs.get("breakdown_path") or "")
            kwargs.setdefault("preview", kwargs.get("thumbnail") or "")
            return self.client["add_asset"](path, **kwargs)

        self.client["_workflow_analyze_reference_video"] = fake_reference_analysis
        self.client["_workflow_save_reference_analysis_artifact"] = fake_save_reference_analysis_artifact
        self.client["_workflow_add_reference_asset"] = add_reference_asset

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_vision_failure_falls_back_to_text_script(self):
        fallback = "保温杯带货脚本：开场展示早八通勤喝水场景，强调保温持久、防漏便携和高颜值，再补充办公室热水测试，结尾引导点击购物车。"
        ctx = {
            "topic": "保温杯带货",
            "script": "",
            "media": ["https://www.douyin.com/video/123"],
            "collected": [{"title": "AI真人出镜保温杯带货短视频制作", "desc": "#多喝水 #网红保温杯"}],
        }

        self.client["lk888_vision"] = mock.Mock(side_effect=RuntimeError("contents is required"))
        self.client["lk888_chat"] = mock.Mock(return_value=fallback)
        self.client["kb_context"] = mock.Mock(return_value="")
        summary = self.client["_exec_vision"]({"cap": "vision", "params": {}}, ctx)

        self.assertIn(fallback, ctx["script"])
        self.assertIn("兜底", summary)
        self.client["lk888_chat"].assert_called_once()

    def test_vision_failure_persists_fallback_script_file(self):
        fallback = "Toyota fallback script: opening hook, product proof, driving scene, safety benefit, closing call to action. This is long enough."
        with tempfile.TemporaryDirectory() as tmp:
            ctx = {
                "wfname": "Toyota workflow",
                "topic": "Toyota",
                "script": "",
                "media": ["https://www.douyin.com/video/123"],
                "collected": [{"title": "Toyota demo"}],
                "artifacts": [],
            }

            self.client["_wf_out_dir"] = mock.Mock(return_value=tmp)
            self.client["lk888_vision"] = mock.Mock(side_effect=RuntimeError("contents is required"))
            self.client["lk888_chat"] = mock.Mock(return_value=fallback)
            self.client["kb_context"] = mock.Mock(return_value="")

            summary = self.client["_exec_vision"]({"cap": "vision", "params": {}}, ctx)

            path = ctx.get("scriptPath")
            self.assertTrue(path, "scriptPath should be recorded in workflow context")
            self.assertTrue(os.path.isfile(path))
            self.assertIn(fallback, Path(path).read_text(encoding="utf-8"))
            self.assertIn(os.path.basename(path), summary)
            self.assertEqual([path], ctx.get("scriptArtifacts"))
            self.assertEqual([], ctx["artifacts"])

    def test_vision_success_persists_detailed_storyboard_file(self):
        storyboard = "Shot 1: showroom exterior and Toyota logo. Shot 2: presenter explains battery safety. Shot 3: cabin detail. Shot 4: call to action."
        with tempfile.TemporaryDirectory() as tmp:
            ctx = {
                "wfname": "Toyota workflow",
                "topic": "Toyota",
                "script": "Existing intro",
                "media": ["https://www.douyin.com/video/123"],
                "artifacts": [],
            }

            self.client["_wf_out_dir"] = mock.Mock(return_value=tmp)
            self.client["lk888_vision"] = mock.Mock(return_value=storyboard)

            summary = self.client["_exec_vision"]({"cap": "vision", "params": {}}, ctx)

            path = ctx.get("scriptPath")
            self.assertTrue(os.path.isfile(path))
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("Existing intro", content)
            self.assertIn(storyboard, content)
            self.assertIn(os.path.basename(path), summary)
            self.assertEqual([path], ctx.get("scriptArtifacts"))
            self.assertEqual([], ctx["artifacts"])

    def test_video_generation_expands_short_script_before_charging(self):
        ctx = {"topic": "Text workflow", "script": "short", "media": [], "artifacts": []}
        self.client["lk888_chat"] = mock.Mock()
        self.client["try_charge"] = mock.Mock()
        self.client["lk888_media_task"] = mock.Mock()

        summary = self.client["_exec_video"]({"cap": "video", "params": {"count": 1}}, ctx)

        self.assertIn("文本型工作流", summary)
        self.assertEqual([], ctx["artifacts"])
        self.client["lk888_chat"].assert_not_called()
        self.client["try_charge"].assert_not_called()
        self.client["lk888_media_task"].assert_not_called()
        return
        fallback = "保温杯带货脚本：开场把杯子倒扣进包里展示不漏水，再切到户外热水保温测试，突出容量、颜值和便携，最后提示限时福利。"
        captured = {}

        def fake_media_task(model, payload, exts, progress=None, tries=110):
            captured["payload"] = payload
            return "https://cdn.example.com/video.mp4"

        ctx = {"topic": "保温杯带货", "script": "短", "media": [], "artifacts": []}
        self.client["lk888_chat"] = mock.Mock(return_value=fallback)
        self.client["kb_context"] = mock.Mock(return_value="")
        self.client["try_charge"] = mock.Mock(return_value=(True, ""))
        self.client["lk888_media_task"] = mock.Mock(side_effect=fake_media_task)
        self.client["_wf_download"] = mock.Mock(return_value="/tmp/video.mp4")
        self.client["_wf_out_dir"] = mock.Mock(return_value=self._tmpdir.name)
        self.client["_workflow_refund_video"] = mock.Mock()
        self.client["refund_cap"] = mock.Mock()

        self.client["_exec_video"]({"cap": "video", "params": {"count": 1, "duration": 10, "aspect": "9:16"}}, ctx)

        script_content = captured["payload"]["params"]["script_content"]
        self.assertGreaterEqual(len(script_content), 50)
        self.assertIn("保温杯带货脚本", script_content)
        self.client["lk888_chat"].assert_called_once()
        self.client["try_charge"].assert_called_once()

    def test_collect_downloaded_video_is_reference_artifact_not_publish_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloaded = os.path.join(tmp, "source.mp4")
            Path(downloaded).write_bytes(b"video")

            def fake_local_task(ttype, payload, timeout_poll=280):
                if ttype == "douyin.search":
                    return {
                        "status": "done",
                        "items": [{"title": "Toyota demo", "url": "https://example.com/video"}],
                    }
                if ttype == "douyin.download":
                    return {"status": "done", "result": {"files": [downloaded]}}
                raise AssertionError(ttype)

            ctx = {"artifacts": []}
            self.client["submit_local_task"] = mock.Mock(side_effect=fake_local_task)
            summary = self.client["_exec_collect"](
                {"cap": "collect", "params": {"platform": "douyin", "keyword": "Toyota", "topN": 1}},
                ctx,
            )

            self.assertIn("已下载 1/1 到采集参考素材", summary)
            self.assertEqual([], ctx["artifacts"])
            self.assertEqual([downloaded], ctx["referenceArtifacts"])
            self.assertEqual([downloaded], ctx["collectedArtifacts"])

    def test_collect_downloads_each_collected_top_item_as_reference_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i in range(3):
                path = os.path.join(tmp, "source_%d.mp4" % (i + 1))
                Path(path).write_bytes(b"video")
                paths.append(path)

            urls = ["https://example.com/video/%d" % (i + 1) for i in range(3)]

            def fake_local_task(ttype, payload, timeout_poll=280):
                if ttype == "douyin.search":
                    return {
                        "status": "done",
                        "items": [{"title": "Toyota demo %d" % (i + 1), "url": urls[i]} for i in range(3)],
                    }
                if ttype == "douyin.download":
                    idx = urls.index(payload["url"])
                    return {"status": "done", "result": {"files": [paths[idx]]}}
                raise AssertionError(ttype)

            ctx = {"artifacts": []}
            self.client["submit_local_task"] = mock.Mock(side_effect=fake_local_task)
            summary = self.client["_exec_collect"](
                {"cap": "collect", "params": {"platform": "douyin", "keyword": "Toyota", "topN": 3}},
                ctx,
            )

            self.assertIn("3/3", summary)
            self.assertEqual([], ctx["artifacts"])
            self.assertEqual(paths, ctx["referenceArtifacts"])
            self.assertEqual(paths, ctx["collectedArtifacts"])
            download_calls = [c for c in self.client["submit_local_task"].call_args_list
                              if c.args and c.args[0] == "douyin.download"]
            self.assertEqual(3, len(download_calls))

    def test_collect_keeps_cover_as_video_thumbnail_not_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloaded = os.path.join(tmp, "video.mp4")
            cover = os.path.join(tmp, "cover.jpg")
            Path(downloaded).write_bytes(b"video")
            Path(cover).write_bytes(b"image")

            def fake_local_task(ttype, payload, timeout_poll=280):
                if ttype == "douyin.search":
                    return {
                        "status": "done",
                        "items": [{"title": "Toyota demo", "url": "https://example.com/video"}],
                    }
                if ttype == "douyin.download":
                    return {"status": "done", "result": {"files": [downloaded, cover]}}
                raise AssertionError(ttype)

            ctx = {"artifacts": []}
            self.client["submit_local_task"] = mock.Mock(side_effect=fake_local_task)

            self.client["_exec_collect"](
                {"cap": "collect", "params": {"platform": "douyin", "keyword": "Toyota", "topN": 1}},
                ctx,
            )

            self.assertEqual([downloaded], ctx["referenceArtifacts"])
            self.assertEqual([downloaded], ctx["collectedArtifacts"])
            self.assertEqual(cover, ctx["referenceThumbnails"][downloaded])

    def test_library_stores_reference_video_thumbnail_without_image_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            reference = os.path.join(tmp, "video.mp4")
            thumbnail = os.path.join(tmp, "cover.jpg")
            Path(reference).write_bytes(b"video")
            Path(thumbnail).write_bytes(b"image")
            calls = []

            def fake_add_asset(path, kind=None, prompt="", source="", category="", thumbnail="", preview="",
                               text_path="", breakdown_path=""):
                calls.append({
                    "path": path,
                    "kind": kind,
                    "prompt": prompt,
                    "source": source,
                    "category": category,
                    "thumbnail": thumbnail,
                    "preview": preview,
                    "text_path": text_path,
                    "breakdown_path": breakdown_path,
                })
                return {"id": "asset"}

            ctx = {
                "topic": "Toyota",
                "artifacts": [],
                "referenceArtifacts": [reference],
                "referenceThumbnails": {reference: thumbnail},
            }
            self.client["add_asset"] = mock.Mock(side_effect=fake_add_asset)
            summary = self.client["_exec_library"]({"cap": "library", "params": {}}, ctx)

            self.assertIn("采集参考视频 1/1", summary)
            self.assertEqual(1, len(calls))
            self.assertEqual(reference, calls[0]["path"])
            self.assertEqual("video", calls[0]["kind"])
            self.assertEqual(thumbnail, calls[0]["thumbnail"])
            self.assertEqual(thumbnail, calls[0]["preview"])

    def test_library_generates_and_attaches_reference_breakdown_text_per_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            refs = []
            for i in range(2):
                path = os.path.join(tmp, "video_%d.mp4" % (i + 1))
                Path(path).write_bytes(b"video")
                refs.append(path)
            calls = []

            def fake_add_asset(path, kind=None, prompt="", source="", category="", thumbnail="", preview="",
                               text_path="", breakdown_path=""):
                calls.append({
                    "path": path,
                    "kind": kind,
                    "source": source,
                    "category": category,
                    "text_path": text_path,
                    "breakdown_path": breakdown_path,
                })
                return {"id": "asset"}

            self.client["lk888_vision"] = mock.Mock(side_effect=[
                "镜头1：第一条视频开场展示车头和品牌标识，用三秒建立车型记忆。镜头2：讲解安全配置和辅助驾驶能力。镜头3：切到路面驾驶体验，强调稳定感。镜头4：收尾引导关注。",
                "镜头1：第二条视频强调座舱空间和家庭出行需求。镜头2：展示内饰细节、储物和乘坐舒适度。镜头3：切到多人出行场景。镜头4：总结车型卖点并引导咨询。",
            ])
            self.client["lk888_chat"] = mock.Mock()
            self.client["kb_context"] = mock.Mock(return_value="")
            self.client["add_asset"] = mock.Mock(side_effect=fake_add_asset)
            ctx = {
                "wfname": "Toyota workflow",
                "topic": "Toyota",
                "artifacts": [],
                "referenceArtifacts": refs,
                "collected": [{"title": "Toyota one"}, {"title": "Toyota two"}],
            }

            summary = self.client["_exec_library"]({"cap": "library", "params": {}}, ctx)

            self.assertIn("绑定文本 2/2", summary)
            self.assertEqual(2, len(calls))
            for i, call in enumerate(calls):
                self.assertEqual(refs[i], call["path"])
                self.assertEqual("video", call["kind"])
                self.assertEqual("采集参考视频", call["source"])
                self.assertEqual("采集参考视频", call["category"])
                self.assertTrue(os.path.isfile(call["text_path"]))
                self.assertEqual(call["text_path"], call["breakdown_path"])
                self.assertIn("镜头1", Path(call["text_path"]).read_text(encoding="utf-8"))
            self.assertEqual(2, self.client["lk888_vision"].call_count)

    def test_reference_breakdown_markdown_table_is_normalized_to_readable_cards(self):
        table = (
            "| 镜头序号 | 画面内容 | 台词/字幕 | 节奏 | 预估时长 | 可借鉴卖点 |\n"
            "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
            "| 1 | **全景转中景**：销售站在车头前，镜头快速推进。 | **台词/字幕**：“直接交底最新落地价！” | 极快、抓人 | 4秒 | **痛点前置**：价格悬念留住用户。 |\n"
            "| 2 | **特写**：车尾 E-Four 四驱标识。 | **台词/字幕**：“电四驱赛那，稳如泰山。” | 明快、干脆 | 5秒 | **核心差异化**：解决雨雪天安全痛点。 |\n"
        )

        text = self.client["_workflow_normalize_reference_breakdown_text"](table)

        self.assertIn("镜头 1｜全景转中景｜4秒", text)
        self.assertIn("画面：销售站在车头前，镜头快速推进。", text)
        self.assertIn("台词：直接交底最新落地价！", text)
        self.assertIn("节奏：极快、抓人。", text)
        self.assertIn("可借鉴点：价格悬念留住用户。", text)
        self.assertIn("镜头 2｜特写｜5秒", text)
        self.assertNotIn("| 镜头序号 |", text)
        self.assertNotIn("**", text)

    def test_library_stores_reference_artifacts_in_collection_category(self):
        generated = os.path.abspath(__file__)
        reference = os.path.abspath(CLIENT)
        calls = []

        def fake_add_asset(path, kind=None, prompt="", source="", category="", thumbnail="", preview="",
                           text_path="", breakdown_path=""):
            calls.append({"path": path, "kind": kind, "prompt": prompt, "source": source, "category": category})
            return {"id": "asset"}

        ctx = {
            "topic": "Toyota",
            "artifacts": [generated],
            "referenceArtifacts": [reference],
        }
        self.client["add_asset"] = mock.Mock(side_effect=fake_add_asset)
        summary = self.client["_exec_library"]({"cap": "library", "params": {}}, ctx)

        self.assertIn("生成素材 1/1", summary)
        self.assertIn("采集参考视频 1/1", summary)
        self.assertEqual("自动化工作流", calls[0]["source"])
        self.assertEqual("", calls[0]["category"])
        self.assertEqual("采集参考视频", calls[1]["source"])
        self.assertEqual("采集参考视频", calls[1]["category"])
        self.assertIn("采集参考视频", calls[1]["prompt"])

    def test_text_artifact_kind_is_not_standalone_asset(self):
        self.assertEqual("", self.client["_workflow_artifact_kind"]("script.txt"))
        self.assertEqual("", self.client["_workflow_artifact_kind"]("storyboard.md"))

    def test_library_does_not_store_text_artifacts_as_standalone_assets(self):
        text_path = os.path.join(self._tmpdir.name, "storyboard.txt")
        Path(text_path).write_text("Shot 1: opening hook\nShot 2: product proof\n", encoding="utf-8")
        calls = []

        def fake_add_asset(path, kind=None, prompt="", source="", category="", thumbnail="", preview="",
                           text_path="", breakdown_path=""):
            calls.append({
                "path": path,
                "kind": kind,
                "prompt": prompt,
                "source": source,
                "category": category,
            })
            return {"id": "asset"}

        ctx = {
            "wfname": "Text workflow",
            "topic": "Cosmetics",
            "artifacts": [],
            "textArtifacts": [text_path],
        }
        self.client["add_asset"] = mock.Mock(side_effect=fake_add_asset)

        summary = self.client["_exec_library"]({"cap": "library", "params": {}}, ctx)

        self.assertIn("生成素材 0/0", summary)
        self.assertEqual([], calls)

    def test_media_generation_steps_are_skipped_for_text_only_workflow(self):
        ctx = {
            "wfname": "Text workflow",
            "topic": "Cosmetics",
            "script": "This is a long enough script for a text-only workflow result.",
            "artifacts": [],
        }
        self.client["try_charge"] = mock.Mock(return_value=(False, "should not charge"))
        self.client["lk888_image"] = mock.Mock()
        self.client["lk888_media_task"] = mock.Mock()
        self.client["lk888_tts"] = mock.Mock()

        image_summary = self.client["_exec_image"]({"cap": "image", "params": {}}, ctx)
        video_summary = self.client["_exec_video"]({"cap": "video", "params": {"count": 1}}, ctx)
        tts_summary = self.client["_exec_tts"]({"cap": "tts", "params": {}}, ctx)

        self.assertIn("文本型工作流", image_summary)
        self.assertIn("文本型工作流", video_summary)
        self.assertIn("文本型工作流", tts_summary)
        self.assertEqual([], ctx["artifacts"])
        self.client["try_charge"].assert_not_called()
        self.client["lk888_image"].assert_not_called()
        self.client["lk888_media_task"].assert_not_called()
        self.client["lk888_tts"].assert_not_called()

    def test_publish_ignores_reference_artifacts(self):
        ctx = {
            "wfname": "Toyota workflow",
            "topic": "Toyota",
            "script": "script",
            "artifacts": [],
            "referenceArtifacts": [os.path.abspath(__file__)],
        }
        self.client["add_pending"] = mock.Mock()

        summary = self.client["_exec_publish"]({"cap": "publish", "params": {"platform": "douyin"}}, ctx)

        self.assertIn("只有采集参考素材", summary)
        self.assertNotIn("_publish_done", ctx)
        self.client["add_pending"].assert_not_called()

    def test_direct_assistant_prompt_forbids_workflow_json_and_source_video_publish(self):
        src = CLIENT.read_text(encoding="utf-8-sig")
        self.assertIn("不得输出工作流 JSON", src)
        self.assertIn("不得引导用户进入自动化工作流页面", src)
        self.assertIn("不得把采集到的原视频当成可发布素材", src)


if __name__ == "__main__":
    unittest.main()
