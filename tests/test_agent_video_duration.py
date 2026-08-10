from pathlib import Path
import importlib.util
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_client_module(name="matrix_native_client_agent_video_duration_test"):
    spec = importlib.util.spec_from_file_location(name, CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentVideoDurationTest(unittest.TestCase):
    def test_agent_video_duration_is_selectable(self):
        source = CLIENT.read_text(encoding="utf-8-sig")

        self.assertIn("AGENT_VIDEO_DURATIONS = (5, 10)", source)
        self.assertIn("self.b_duration = _icon_text_btn", source)
        self.assertIn("def _cycle_video_duration(self):", source)
        self.assertIn('"duration": self._current_video_duration()', source)
        self.assertIn("dur = _agent_video_request_duration(model, entry.get(\"duration\"))", source)
        self.assertNotIn("dur = 5\n    model =", source)

    def test_agent_image_generation_passes_chinese_prompt_without_hidden_expansion(self):
        module = load_client_module("matrix_native_client_agent_image_chinese_prompt_test")
        entry = {
            "id": "agent-image-chinese-prompt",
            "mode": "image",
            "prompt": "保留商品包装文字，生成白底电商主图",
            "style": "简洁商业摄影",
            "count": 1,
            "size": "1024x1024",
            "model": module._LK888_IMAGE_DEFAULT,
        }

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(module, "data_dir", return_value=tmp), \
                mock.patch.object(module, "_prodgen_expand_prompt", return_value="unexpected english prompt") as expand, \
                mock.patch.object(module, "update_prodgen"), \
                mock.patch.object(module, "lk888_media_task", return_value="https://cdn.example.com/image.png") as image, \
                mock.patch.object(module, "_wf_download"):
            module._prodgen_run_image(entry)

        expand.assert_not_called()
        self.assertEqual(
            "保留商品包装文字，生成白底电商主图\n风格方向：简洁商业摄影",
            image.call_args.args[1]["prompt"],
        )

    def test_agent_video_generation_passes_confirmed_chinese_prompt_without_hidden_expansion(self):
        module = load_client_module("matrix_native_client_agent_video_chinese_prompt_test")
        entry = {
            "id": "agent-video-chinese-prompt",
            "mode": "video",
            "prompt": "原始输入",
            "visiblePrompt": "展示车辆内饰和驾驶动作",
            "style": "写实广告片",
            "duration": 5,
            "model": module._LK888_VIDEO_DEFAULT,
            "aspect_ratio": "16:9",
        }

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(module, "data_dir", return_value=tmp), \
                mock.patch.object(module, "_prodgen_expand_prompt", return_value="unexpected english prompt") as expand, \
                mock.patch.object(module, "update_prodgen"), \
                mock.patch.object(module, "lk888_media_task", return_value="https://cdn.example.com/video.mp4") as media, \
                mock.patch.object(module, "_wf_download"):
            module._prodgen_run_video(entry)

        expand.assert_not_called()
        self.assertEqual(
            "展示车辆内饰和驾驶动作\n风格方向：写实广告片",
            media.call_args.args[1]["prompt"],
        )

    def test_agent_prompt_model_calls_include_business_billing_metadata(self):
        module = load_client_module("matrix_native_client_agent_prompt_billing_meta_test")

        with mock.patch.object(module, "brand_context", return_value=""), \
                mock.patch.object(module, "lk888_chat", return_value="优化后的中文提示词内容足够长") as chat:
            module._prodgen_optimize_prompt("生成商品主图")
        optimize_kwargs = chat.call_args.kwargs
        self.assertEqual("agent_mode", optimize_kwargs.get("billing_scenario"))
        self.assertEqual("prompt_optimization", optimize_kwargs.get("billing_stage"))
        self.assertEqual("agent prompt optimization", optimize_kwargs.get("billing_detail"))

        with mock.patch.object(module, "brand_context", return_value=""), \
                mock.patch.object(module, "lk888_chat", return_value="professional product image prompt") as chat:
            module._prodgen_expand_prompt("生成商品主图")
        translation_kwargs = chat.call_args.kwargs
        self.assertEqual("agent_mode", translation_kwargs.get("billing_scenario"))
        self.assertEqual("prompt_translation", translation_kwargs.get("billing_stage"))
        self.assertEqual("model compatibility prompt translation", translation_kwargs.get("billing_detail"))

    def test_agent_reference_analysis_includes_business_billing_metadata(self):
        module = load_client_module("matrix_native_client_agent_reference_billing_meta_test")

        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "reference.png"
            ref.write_bytes(b"png")
            with mock.patch.object(module, "_file_to_data_url", return_value="data:image/png;base64,cG5n"), \
                    mock.patch.object(module, "lk888_vision", return_value="reference description") as vision:
                module._prodgen_refs_desc([str(ref)])

        kwargs = vision.call_args.kwargs
        self.assertEqual("agent_mode", kwargs.get("billing_scenario"))
        self.assertEqual("reference_analysis", kwargs.get("billing_stage"))
        self.assertEqual("agent reference image understanding", kwargs.get("billing_detail"))

    def test_vidu_q3_agent_video_duration_is_coerced_to_supported_slot(self):
        module = load_client_module()
        entry = {
            "id": "agent-video-1",
            "mode": "video",
            "prompt": "生成一个商品短视频",
            "duration": 5,
            "model": "viduq3",
            "aspect_ratio": "9:16",
        }

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(module, "data_dir", return_value=tmp), \
                mock.patch.object(module, "_prodgen_expand_prompt", return_value="video prompt"), \
                mock.patch.object(module, "update_prodgen") as update, \
                mock.patch.object(module, "lk888_media_task", return_value="https://cdn.example.com/video.mp4") as media, \
                mock.patch.object(module, "_wf_download") as download:
            module._prodgen_run_video(entry)

        payload = media.call_args.args[1]
        self.assertEqual("viduq3", media.call_args.args[0])
        self.assertEqual(4, payload["params"]["duration"])
        self.assertEqual("720p", payload["params"]["resolution"])
        update.assert_called()
        self.assertEqual(4, update.call_args.kwargs["duration"])
        download.assert_called_once()

    def test_agent_video_submission_rejects_image_model_state(self):
        module = load_client_module("matrix_native_client_agent_video_model_normalize_test")
        entry = {
            "id": "agent-video-image-model",
            "mode": "video",
            "prompt": "生成一条商品短视频",
            "duration": 5,
            "model": module._LK888_IMAGE_DEFAULT,
            "aspect_ratio": "16:9",
        }

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(module, "data_dir", return_value=tmp), \
                mock.patch.object(module, "_prodgen_expand_prompt", return_value="video prompt"), \
                mock.patch.object(module, "update_prodgen") as update, \
                mock.patch.object(module, "lk888_media_task", return_value="https://cdn.example.com/video.mp4") as media, \
                mock.patch.object(module, "_wf_download") as download:
            module._prodgen_run_video(entry)

        self.assertEqual(module._LK888_VIDEO_DEFAULT, media.call_args.args[0])
        self.assertEqual(module._LK888_VIDEO_DEFAULT, update.call_args.kwargs["model"])
        download.assert_called_once()

    def test_agent_image_submission_rejects_video_model_state(self):
        module = load_client_module("matrix_native_client_agent_image_model_normalize_test")
        entry = {
            "id": "agent-image-video-model",
            "mode": "image",
            "prompt": "生成商品主图",
            "count": 1,
            "size": "1024x1024",
            "model": module._LK888_VIDEO_DEFAULT,
        }

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(module, "data_dir", return_value=tmp), \
                mock.patch.object(module, "_prodgen_expand_prompt", return_value="image prompt"), \
                mock.patch.object(module, "update_prodgen") as update, \
                mock.patch.object(module, "lk888_media_task", return_value="https://cdn.example.com/image.png") as image, \
                mock.patch.object(module, "_wf_download"):
            files = module._prodgen_run_image(entry)

        self.assertEqual(1, len(files))
        self.assertEqual(module._LK888_IMAGE_DEFAULT, image.call_args.args[0])
        self.assertEqual(module._LK888_IMAGE_DEFAULT, update.call_args.kwargs["model"])

    def test_agent_image_uploads_reference_images_to_lk888_image_model(self):
        module = load_client_module("matrix_native_client_agent_image_refs_payload_test")

        with tempfile.TemporaryDirectory() as tmp:
            ref1 = Path(tmp) / "edit-target.png"
            ref2 = Path(tmp) / "style-ref.jpg"
            ref1.write_bytes(b"png-1")
            ref2.write_bytes(b"jpg-2")
            entry = {
                "id": "agent-image-refs",
                "mode": "image",
                "prompt": "淇濇寔浜虹墿涓嶅彉锛岃浆鎴愮嚎鏉℃彃鐢",
                "count": 1,
                "size": "1024x1024",
                "model": module._LK888_IMAGE_DEFAULT,
                "refs": [str(ref1), str(ref2)],
            }
            uploaded = [
                "https://assets.example/agent/edit-target.png",
                "https://assets.example/agent/style-ref.jpg",
            ]

            with mock.patch.object(module, "data_dir", return_value=tmp), \
                    mock.patch.object(module, "_prodgen_expand_prompt", return_value="image prompt"), \
                    mock.patch.object(module, "upload_asset_url", side_effect=[(uploaded[0], {}), (uploaded[1], {})]) as upload, \
                    mock.patch.object(module, "update_prodgen"), \
                    mock.patch.object(module, "lk888_media_task", return_value="https://cdn.example.com/image.png") as image, \
                    mock.patch.object(module, "_wf_download"):
                files = module._prodgen_run_image(entry)

        self.assertEqual(1, len(files))
        payload = image.call_args.args[1]
        self.assertEqual(uploaded, payload["image_urls"])
        self.assertEqual(uploaded, payload["params"]["images"])
        self.assertEqual(2, upload.call_count)
        self.assertEqual("image", upload.call_args_list[0].args[2])
        self.assertIn("agent_image_reference", upload.call_args_list[0].kwargs["metadata"]["source"])

    def test_agent_gemini_image_preview_uses_lk888_media_endpoint(self):
        module = load_client_module("matrix_native_client_agent_gemini_image_endpoint_test")
        entry = {
            "id": "agent-gemini-image",
            "mode": "image",
            "prompt": "生成一张电商商品主图",
            "count": 1,
            "size": "1024x1024",
            "model": "gemini-3-pro-image-preview",
        }

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(module, "data_dir", return_value=tmp), \
                mock.patch.object(module, "_prodgen_expand_prompt", return_value="image prompt"), \
                mock.patch.object(module, "update_prodgen") as update, \
                mock.patch.object(module, "lk888_image", return_value=b"png-bytes") as image, \
                mock.patch.object(module, "lk888_media_task", return_value="https://cdn.example.com/image.png") as media, \
                mock.patch.object(module, "_wf_download") as download:
            files = module._prodgen_run_image(entry)

        self.assertEqual(1, len(files))
        image.assert_not_called()
        media.assert_called_once()
        self.assertEqual("gemini-3-pro-image-preview", media.call_args.args[0])
        payload = media.call_args.args[1]
        self.assertEqual("生成一张电商商品主图", payload["prompt"])
        self.assertEqual("1:1", payload["params"]["aspectRatio"])
        self.assertEqual("1K", payload["params"]["imageSize"])
        download.assert_called_once_with("https://cdn.example.com/image.png", files[0])
        self.assertEqual("gemini-3-pro-image-preview", update.call_args.kwargs["model"])

    def test_agent_image_reference_upload_failure_does_not_submit_lk888_task(self):
        module = load_client_module("matrix_native_client_agent_image_refs_upload_fail_test")

        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "edit-target.png"
            ref.write_bytes(b"png")
            entry = {
                "id": "agent-image-ref-fail",
                "mode": "image",
                "prompt": "淇濇寔浜虹墿涓嶅彉锛岃浆鎴愮嚎鏉℃彃鐢",
                "count": 1,
                "size": "1024x1024",
                "model": module._LK888_IMAGE_DEFAULT,
                "refs": [str(ref)],
            }

            with mock.patch.object(module, "_prodgen_expand_prompt", return_value="image prompt"), \
                    mock.patch.object(module, "upload_asset_url", side_effect=RuntimeError("upload down")), \
                    mock.patch.object(module, "lk888_media_task", return_value="https://cdn.example.com/image.png") as image:
                with self.assertRaisesRegex(RuntimeError, "参考图上传失败"):
                    module._prodgen_run_image(entry)

        image.assert_not_called()

    def test_agent_video_rule_table_exposes_known_duration_slots(self):
        module = load_client_module("matrix_native_client_agent_video_rules_test")

        seedance = module._agent_model_rule("doubao-seedance-1-5-pro-251215")
        vidu = module._agent_model_rule("viduq3")

        self.assertEqual((4, 8, 12), seedance.get("duration_slots"))
        self.assertEqual((4, 8, 12, 16), vidu.get("duration_slots"))
        self.assertEqual(4, module._agent_video_request_duration("viduq3", 5))
        self.assertEqual(8, module._agent_video_request_duration("doubao-seedance-1-5-pro-251215", 10))

    def test_agent_image_rule_table_exposes_endpoint_slots(self):
        module = load_client_module("matrix_native_client_agent_image_endpoint_rules_test")

        self.assertEqual("media", module._agent_image_endpoint("gpt-image-2"))
        self.assertEqual("media", module._agent_image_endpoint("gemini-3-pro-image-preview"))
        self.assertEqual("media", module._agent_image_endpoint("gemini-3.1-flash-image-preview"))

    def test_agent_all_image_models_route_to_lk888_media_generate(self):
        module = load_client_module("matrix_native_client_agent_all_image_media_test")

        for row in module._LK888_FALLBACK_MODELS:
            if row.get("type") == "image":
                self.assertEqual("media", module._agent_image_endpoint(row["name"]), row["name"])

    def test_agent_image_payload_adds_required_lk888_media_params(self):
        module = load_client_module("matrix_native_client_agent_image_media_params_test")

        gemini = module._agent_image_payload("gemini-3-pro-image-preview", "prompt", "1024x1024", [])
        seedream = module._agent_image_payload(
            "doubao-seedream-5-0-260128", "prompt", "1024x1024",
            ["https://assets.example/ref.png"])
        mj = module._agent_image_payload("mj_imagine", "prompt", "1920x1088", [])
        kling = module._agent_image_payload("kling-v3", "prompt", "1024x1024", [])
        vidu = module._agent_image_payload("vidu-image-2", "prompt", "1024x1024", [])

        self.assertEqual("1:1", gemini["params"]["aspectRatio"])
        self.assertEqual("1K", gemini["params"]["imageSize"])
        self.assertEqual("2K", seedream["params"]["size"])
        self.assertEqual("1:1", seedream["params"]["aspect_ratio"])
        self.assertEqual(["https://assets.example/ref.png"], seedream["params"]["images"])
        self.assertEqual("MID_JOURNEY", mj["params"]["botType"])
        self.assertEqual("16:9", mj["params"]["aspectRatio"])
        self.assertEqual("1k", kling["params"]["resolution"])
        self.assertEqual("1:1", kling["params"]["aspect_ratio"])
        self.assertEqual("1:1", vidu["params"]["aspect_ratio"])
        self.assertEqual("1K", vidu["params"]["resolution"])
        self.assertEqual("medium", vidu["params"]["quality"])

    def test_agent_video_payload_maps_required_lk888_model_params(self):
        module = load_client_module("matrix_native_client_agent_video_param_rules_test")

        seedance = module._agent_video_payload(
            "doubao-seedance-1-5-pro-251215", "video prompt", 10, "16:9", [])
        vidu = module._agent_video_payload("viduq3", "video prompt", 5, "9:16", [])
        kling = module._agent_video_payload("kling-v3-video", "video prompt", 5, "1:1", [])
        kling26 = module._agent_video_payload("kling-v2-6", "video prompt", 5, "16:9", [])
        sora = module._agent_video_payload("sora-2", "video prompt", 10, "9:16", [])

        self.assertEqual(8, seedance["params"]["audio_duration"])
        self.assertNotIn("duration", seedance["params"])
        self.assertEqual("16:9", seedance["params"]["ratio"])
        self.assertEqual("false", seedance["params"]["generate_audio"])
        self.assertEqual(4, vidu["params"]["duration"])
        self.assertEqual("turbo", vidu["params"]["model_variant"])
        self.assertEqual("false", vidu["params"]["off_peak"])
        self.assertEqual("std", kling["params"]["mode"])
        self.assertEqual("on", kling26["params"]["sound"])
        self.assertEqual("portrait", sora["params"]["orientation"])

    def test_agent_motion_control_payload_uses_one_image_and_one_video(self):
        module = load_client_module("matrix_native_client_agent_motion_control_test")

        payload = module._agent_video_payload(
            "kling-motion-control-v3",
            "动作控制视频",
            10,
            "16:9",
            ["https://assets.example/person.png", "https://assets.example/extra.png"],
            "https://assets.example/motion.mp4",
        )

        self.assertEqual("https://assets.example/person.png", payload["params"]["image_url"])
        self.assertEqual("https://assets.example/motion.mp4", payload["params"]["video_url"])
        self.assertEqual("video", payload["params"]["character_orientation"])
        self.assertEqual("std", payload["params"]["mode"])
        self.assertEqual("no", payload["params"]["keep_original_sound"])
        self.assertNotIn("duration", payload["params"])

    def test_agent_motion_control_uploads_reference_video_before_submit(self):
        module = load_client_module("matrix_native_client_agent_motion_control_upload_test")
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "person.png"
            video = Path(tmp) / "motion.mp4"
            image.write_bytes(b"image")
            video.write_bytes(b"video")
            entry = {
                "id": "agent-motion-control",
                "mode": "video",
                "prompt": "动作控制",
                "visiblePrompt": "动作控制",
                "model": "kling-motion-control-v3",
                "duration": 10,
                "aspect_ratio": "16:9",
                "refs": [str(image)],
                "referenceVideo": str(video),
            }
            with mock.patch.object(module, "data_dir", return_value=tmp), \
                    mock.patch.object(module, "_prodgen_refs_desc", return_value="参考图"), \
                    mock.patch.object(module, "upload_asset_url", side_effect=[
                        ("https://assets.example/person.png", {}),
                        ("https://assets.example/motion.mp4", {}),
                    ]) as upload, \
                    mock.patch.object(module, "update_prodgen"), \
                    mock.patch.object(module, "lk888_media_task", return_value="https://cdn.example.com/out.mp4") as media, \
                    mock.patch.object(module, "_wf_download"):
                module._prodgen_run_video(entry)

        payload = media.call_args.args[1]
        self.assertEqual("https://assets.example/person.png", payload["params"]["image_url"])
        self.assertEqual("https://assets.example/motion.mp4", payload["params"]["video_url"])
        self.assertEqual(2, upload.call_count)

    def test_agent_payload_preserves_all_uploaded_reference_images(self):
        module = load_client_module("matrix_native_client_agent_all_reference_images_test")
        refs = [
            "https://assets.example/one.png",
            "https://assets.example/two.png",
            "https://assets.example/three.png",
        ]

        payload = module._agent_image_payload("mj_imagine", "多图参考", image_urls=refs)

        self.assertEqual(refs, payload["params"]["images"])
        self.assertEqual(refs, payload["images"])

    def test_agent_image_reference_limit_matches_lk888_model_rules(self):
        module = load_client_module("matrix_native_client_agent_image_reference_limits_test")

        self.assertEqual(10, module._agent_image_reference_limit("kling-image-o1"))
        self.assertEqual(4, module._agent_image_reference_limit("qwen-image"))
        self.assertEqual(4, module._agent_image_reference_limit("kling-v3"))
        self.assertEqual(4, module._agent_image_reference_limit("kling-v3-omni"))
        self.assertEqual(4, module._agent_image_reference_limit("wan2.7-image"))
        self.assertEqual(4, module._agent_image_reference_limit("mj_imagine"))
        self.assertEqual(1, module._agent_video_reference_limit("kling-v2-6"))
        self.assertEqual(2, module._agent_video_reference_limit("kling-v3-omni-shouweizhen"))

    def test_agent_named_video_reference_limits_match_lk888_rules(self):
        module = load_client_module("matrix_native_client_agent_video_reference_limits_test")

        expected = {
            "viduq3": 2,
            "viduq3-turbo": 2,
            "viduq3-turbo-cankaosheng": 7,
            "wan2.7-cankaosheng": 4,
            "wan2.7-shouweizhen": 2,
            "sora-2": 2,
            "veo3.1": 3,
            "pixverse-v6-shouweizhen": 2,
            "grok-video-3": 0,
            "grok-imagine-video-1.5-preview": 1,
            "happyhorse-i2v": 1,
            "hailuo-2.3": 1,
        }

        for model, limit in expected.items():
            with self.subTest(model=model):
                self.assertEqual(limit, module._agent_video_reference_limit(model))

    def test_agent_first_last_frame_models_are_limited_to_two_visible_refs(self):
        module = load_client_module("matrix_native_client_agent_first_last_ref_limit_test")

        first_last_models = [
            row["name"]
            for row in module._LK888_FALLBACK_MODELS
            if row.get("type") == "video"
            and (
                "shouweizhen" in str(row.get("name") or "")
                or "首尾帧" in str(row.get("display_name") or "")
                or "First/Last" in str(row.get("display_name") or "")
            )
        ]

        self.assertIn("kling-v3-omni-shouweizhen", first_last_models)
        self.assertIn("pixverse-v6-shouweizhen", first_last_models)
        self.assertIn("wan2.7-shouweizhen", first_last_models)
        for model in first_last_models:
            with self.subTest(model=model):
                self.assertEqual(2, module._agent_video_reference_limit(model))
                self.assertEqual(2, module._prodgen_entry_ref_limit({"mode": "video", "model": model}))
        self.assertEqual(2, module._agent_video_reference_limit("pixverse-c1-shouweizhen"))
        self.assertEqual(2, module._agent_video_reference_limit("pixverse-v5.6-shouweizhen"))

    def test_agent_entry_refs_hide_extra_refs_for_first_last_frame_video_model(self):
        module = load_client_module("matrix_native_client_agent_entry_first_last_visible_refs_test")

        with tempfile.TemporaryDirectory() as tmp:
            refs = []
            for name in ("first.png", "second.png", "third.png"):
                path = Path(tmp) / name
                path.write_bytes(b"image")
                refs.append(str(path))

            visible_refs = module._prodgen_entry_refs({
                "mode": "video",
                "model": "kling-v3-omni-shouweizhen",
                "refs": refs,
            })

        self.assertEqual(refs[:2], visible_refs)

    def test_agent_viduq3_family_duration_slots_match_lk888(self):
        module = load_client_module("matrix_native_client_agent_viduq3_slots_test")

        expected_slots = {
            "viduq3": (4, 8, 12, 16),
            "viduq3-turbo": tuple(range(1, 17)),
            "viduq3-turbo-cankaosheng": tuple(range(3, 17)),
        }
        expected_request = {
            "viduq3": (4, 8),
            "viduq3-turbo": (5, 10),
            "viduq3-turbo-cankaosheng": (5, 10),
        }
        for model in expected_slots:
            with self.subTest(model=model):
                self.assertEqual(expected_slots[model], module._agent_video_duration_slots(model))
                self.assertEqual(expected_request[model][0], module._agent_video_request_duration(model, 5))
                self.assertEqual(expected_request[model][1], module._agent_video_request_duration(model, 10))

    def test_agent_wan27_family_duration_slots_match_lk888(self):
        module = load_client_module("matrix_native_client_agent_wan27_slots_test")

        for model in ("wan2.7-cankaosheng", "wan2.7-shouweizhen"):
            with self.subTest(model=model):
                self.assertEqual((3, 6, 9, 12, 15), module._agent_video_duration_slots(model))
                self.assertEqual(3, module._agent_video_request_duration(model, 5))
                self.assertEqual(9, module._agent_video_request_duration(model, 10))

    def test_agent_sora2_duration_slots_match_lk888(self):
        module = load_client_module("matrix_native_client_agent_sora2_slots_test")

        self.assertEqual((4, 8, 12), module._agent_video_duration_slots("sora-2"))
        self.assertEqual(4, module._agent_video_request_duration("sora-2", 5))
        self.assertEqual(8, module._agent_video_request_duration("sora-2", 10))
        payload = module._agent_video_payload("sora-2", "prompt", 5, "9:16", [])
        self.assertEqual(4, payload["params"]["duration"])

    def test_agent_special_video_payload_fields_match_lk888(self):
        module = load_client_module("matrix_native_client_agent_special_video_payloads_test")
        refs = [
            "https://assets.example/first.png",
            "https://assets.example/last.png",
            "https://assets.example/extra.png",
        ]

        vidu_ref = module._agent_video_payload("viduq3-turbo-cankaosheng", "prompt", 10, "9:16", refs)
        wan_ref = module._agent_video_payload("wan2.7-cankaosheng", "prompt", 10, "9:16", refs)
        wan_frames = module._agent_video_payload("wan2.7-shouweizhen", "prompt", 10, "9:16", refs)
        sora = module._agent_video_payload("sora-2", "prompt", 10, "9:16", refs)
        veo = module._agent_video_payload("veo3.1", "prompt", 10, "16:9", refs)
        pixverse = module._agent_video_payload("pixverse-v6-shouweizhen", "prompt", 10, "16:9", refs)
        happyhorse = module._agent_video_payload("happyhorse-i2v", "prompt", 10, "16:9", refs)
        hailuo = module._agent_video_payload("hailuo-2.3", "prompt", 10, "16:9", refs)

        self.assertEqual(10, vidu_ref["params"]["duration"])
        self.assertEqual(refs, vidu_ref["params"]["images"])
        self.assertEqual("false", vidu_ref["params"]["off_peak"])

        self.assertEqual(9, wan_ref["params"]["duration"])
        self.assertEqual("720P", wan_ref["params"]["resolution"])
        self.assertEqual("9:16", wan_ref["params"]["ratio"])
        # 万相 2.7 参考生真实字段是 reference_urls（此前误写 images，模型收不到参考图）。
        self.assertEqual(refs[:4], wan_ref["params"]["reference_urls"])
        self.assertNotIn("images", wan_ref["params"])

        self.assertEqual(9, wan_frames["params"]["duration"])
        self.assertEqual("720P", wan_frames["params"]["resolution"])
        self.assertEqual(refs[0], wan_frames["params"]["first_frame_image"])
        self.assertEqual(refs[1], wan_frames["params"]["last_frame_image"])
        self.assertEqual(refs[:2], wan_frames["params"]["images"])
        self.assertNotIn("aspect_ratio", wan_frames["params"])

        self.assertEqual(refs[:2], sora["params"]["input_reference"])
        self.assertNotIn("images", sora["params"])
        self.assertEqual("portrait", sora["params"]["orientation"])

        self.assertEqual(8, veo["params"]["duration"])
        self.assertEqual(refs[:3], veo["params"]["images"])
        self.assertEqual("components", veo["params"]["generation_mode"])
        self.assertEqual("REFERENCE", veo["params"]["generation_type"])
        self.assertEqual("true", veo["params"]["enhance_prompt"])
        self.assertEqual("true", veo["params"]["enable_upsample"])
        self.assertEqual("1080p", veo["params"]["quality"])
        self.assertEqual(refs[:2], pixverse["params"]["images"])
        self.assertEqual([refs[0]], happyhorse["params"]["images"])
        self.assertEqual("720P", happyhorse["params"]["resolution"])
        self.assertEqual(refs[:1], hailuo["params"]["images"])
        self.assertEqual("768P", hailuo["params"]["resolution"])

    def test_agent_veo31_duration_slots_match_lk888(self):
        module = load_client_module("matrix_native_client_agent_veo31_slots_test")

        self.assertEqual((8,), module._agent_video_duration_slots("veo3.1"))
        self.assertEqual(8, module._agent_video_request_duration("veo3.1", 5))
        self.assertEqual(8, module._agent_video_request_duration("veo3.1", 10))

    def test_agent_veo31_payload_uses_reference_mode_when_refs_are_present(self):
        module = load_client_module("matrix_native_client_agent_veo31_reference_payload_test")
        refs = [
            "https://assets.example/first.png",
            "https://assets.example/second.png",
            "https://assets.example/extra.png",
            "https://assets.example/fourth.png",
        ]

        payload = module._agent_video_payload("veo3.1", "prompt", 10, "16:9", refs)

        self.assertEqual(8, payload["params"]["duration"])
        self.assertEqual(refs[:3], payload["params"]["images"])
        self.assertEqual("components", payload["params"]["generation_mode"])
        self.assertEqual("REFERENCE", payload["params"]["generation_type"])
        self.assertEqual("1080p", payload["params"]["quality"])

    def test_agent_veo31_payload_keeps_text_mode_without_refs(self):
        module = load_client_module("matrix_native_client_agent_veo31_text_payload_test")

        payload = module._agent_video_payload("veo3.1", "prompt", 5, "16:9", [])

        self.assertEqual(8, payload["params"]["duration"])
        self.assertEqual("fast", payload["params"]["generation_mode"])
        self.assertEqual("TEXT", payload["params"]["generation_type"])
        self.assertNotIn("images", payload["params"])

    def test_agent_grok_video3_payload_matches_lk888(self):
        module = load_client_module("matrix_native_client_agent_grok_video3_payload_test")

        self.assertEqual((10,), module._agent_video_duration_slots("grok-video-3"))
        self.assertEqual(10, module._agent_video_request_duration("grok-video-3", 5))
        payload = module._agent_video_payload("grok-video-3", "prompt", 5, "9:16", [
            "https://assets.example/ref.png",
        ])

        self.assertEqual(10, payload["params"]["duration"])
        self.assertEqual("vertical_hd", payload["params"]["size"])
        self.assertNotIn("aspect_ratio", payload["params"])
        self.assertNotIn("resolution", payload["params"])
        self.assertNotIn("images", payload["params"])

    def test_agent_grok_imagine_video15_catalog_and_payload_match_lk888(self):
        module = load_client_module("matrix_native_client_agent_grok_imagine_video15_payload_test")
        catalog = [{
            "name": "grok-imagine-video-1.5-preview",
            "display_name": "grok Imagine video1.5",
            "type": "video",
            "duration_slots": [999],
        }]

        with mock.patch.object(module, "_lk888_skill_models", return_value=catalog):
            rows = module._lk888_models_by_type("video")

        row = next(item for item in rows if item["name"] == "grok-imagine-video-1.5-preview")
        self.assertEqual("grok Imagine video1.5", row["display_name"])
        self.assertEqual(tuple(range(1, 16)), row["duration_slots"])
        refs = [
            "https://assets.example/first.png",
            "https://assets.example/extra.png",
        ]
        payload = module._agent_video_payload(row["name"], "prompt", 16, "16:9", refs)

        self.assertEqual(15, payload["params"]["duration"])
        self.assertEqual([refs[0]], payload["params"]["images"])
        self.assertEqual("16:9", payload["params"]["aspect_ratio"])
        self.assertEqual("720p", payload["params"]["resolution"])
        self.assertNotIn("size", payload["params"])

    def test_agent_grok_imagine_video15_requires_first_frame(self):
        module = load_client_module("matrix_native_client_agent_grok_imagine_video15_refs_test")

        with self.assertRaisesRegex(RuntimeError, "需要上传参考图"):
            module._agent_video_payload("grok-imagine-video-1.5-preview", "prompt", 10, "16:9", [])

    def test_agent_happyhorse_online_models_stay_video_models(self):
        module = load_client_module("matrix_native_client_agent_happyhorse_catalog_test")
        catalog = [
            {
                "name": "happyhorse-r2v",
                "display_name": "HappyHorse 参考视频",
                "type": "video",
                "duration_slots": [999],
            },
            {
                "name": "happyhorse-1.1-r2v",
                "display_name": "HappyHorse 1.1 参考视频",
                "type": "video",
                "duration_slots": [999],
            },
            {
                "name": "happyhorse-video-edit",
                "display_name": "HappyHorse Video Edit",
                "type": "video",
                "duration_slots": [999],
            },
        ]

        with mock.patch.object(module, "_lk888_skill_models", return_value=catalog):
            rows = module._lk888_models_by_type("video")

        by_name = {row["name"]: row for row in rows}
        for model in ("happyhorse-r2v", "happyhorse-1.1-r2v", "happyhorse-video-edit"):
            with self.subTest(model=model):
                self.assertIn(model, by_name)
                self.assertEqual(model, module._agent_model_for_type(model, "video"))
                self.assertEqual("video", by_name[model]["type"])
                self.assertEqual(tuple(range(3, 16)), tuple(by_name[model]["duration_slots"]))

    def test_agent_happyhorse_reference_video_payload_uses_happyhorse_fields(self):
        module = load_client_module("matrix_native_client_agent_happyhorse_r2v_payload_test")
        refs = [
            "https://assets.example/ref1.png",
            "https://assets.example/ref2.png",
        ]

        payload = module._agent_video_payload("happyhorse-r2v", "prompt", 10, "9:16", refs)

        self.assertEqual(10, payload["params"]["duration"])
        self.assertEqual("9:16", payload["params"]["ratio"])
        self.assertEqual("720P", payload["params"]["resolution"])
        self.assertEqual(refs[:2], payload["params"]["images"])
        self.assertEqual(5, module._agent_video_reference_limit("happyhorse-r2v"))
        self.assertNotIn("image_urls", payload["params"])
        self.assertNotIn("reference_images", payload["params"])

    def test_agent_happyhorse_video_edit_requires_reference_video(self):
        module = load_client_module("matrix_native_client_agent_happyhorse_edit_refs_test")

        with self.assertRaisesRegex(RuntimeError, "需要上传参考视频"):
            module._agent_video_payload("happyhorse-video-edit", "prompt", 10, "16:9", [])

    def test_agent_video_media_requirements_match_lk888(self):
        module = load_client_module("matrix_native_client_agent_video_media_rules_contract_test")

        motion = module._agent_video_media_requirements("kling-motion-control-v3")
        happy_edit = module._agent_video_media_requirements("happyhorse-video-edit")
        wan_ref = module._agent_video_media_requirements("wan2.7-cankaosheng")
        vidu_turbo = module._agent_video_media_requirements("viduq3-turbo")
        vidu_ref = module._agent_video_media_requirements("viduq3-turbo-cankaosheng")

        self.assertTrue(motion["image_required"])
        self.assertTrue(motion["video_required"])
        self.assertEqual(1, motion["image_limit"])
        self.assertEqual(1, motion["video_limit"])
        self.assertEqual("video_url", motion["video_field"])

        self.assertTrue(happy_edit["video_required"])
        self.assertEqual(5, happy_edit["image_limit"])
        self.assertEqual("video", happy_edit["video_field"])

        self.assertFalse(wan_ref["video_required"])
        self.assertEqual(1, wan_ref["video_limit"])
        # 真实 LK888 字段：参考图 reference_urls、参考视频 reference_video（此前误写 images/video）。
        self.assertEqual("reference_video", wan_ref["video_field"])
        self.assertEqual("reference_urls", wan_ref["image_field"])

        self.assertTrue(vidu_turbo["image_required"])
        self.assertEqual(2, vidu_turbo["image_limit"])
        self.assertFalse(vidu_ref["image_required"])
        self.assertEqual(7, vidu_ref["image_limit"])

    def test_agent_reference_video_button_follows_model_media_contract(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn("_agent_video_media_requirements(cur)", src)
        self.assertIn("supports_reference_video", src)
        self.assertIn("self.ref_video_btn.setVisible(supports_reference_video)", src)
        self.assertNotIn("is_motion = self._mode == \"video\"", src)

    def test_agent_hailuo23_contract_matches_lk888(self):
        module = load_client_module("matrix_native_client_agent_hailuo23_contract_test")
        refs = ["https://assets.example/one.png", "https://assets.example/two.png"]

        self.assertEqual((6, 10), module._agent_video_duration_slots("hailuo-2.3"))
        self.assertEqual(6, module._agent_video_request_duration("hailuo-2.3", 5))
        self.assertEqual(1, module._agent_video_reference_limit("hailuo-2.3"))

        payload = module._agent_video_payload("hailuo-2.3", "prompt", 5, "16:9", refs)

        self.assertEqual(6, payload["params"]["duration"])
        self.assertEqual("2.3", payload["params"]["model_version"])
        self.assertEqual("Disabled", payload["params"]["enhance_prompt"])
        self.assertEqual("768P", payload["params"]["resolution"])
        self.assertEqual([refs[0]], payload["params"]["images"])

    def test_agent_viduq3_family_contract_matches_lk888(self):
        module = load_client_module("matrix_native_client_agent_viduq3_contract_test")
        refs = ["https://assets.example/one.png", "https://assets.example/two.png", "https://assets.example/three.png"]

        self.assertEqual(2, module._agent_video_reference_limit("viduq3"))
        self.assertEqual(tuple(range(1, 17)), module._agent_video_duration_slots("viduq3-turbo"))
        self.assertEqual(tuple(range(3, 17)), module._agent_video_duration_slots("viduq3-turbo-cankaosheng"))

        q3 = module._agent_video_payload("viduq3", "prompt", 5, "9:16", refs)
        turbo = module._agent_video_payload("viduq3-turbo", "prompt", 5, "9:16", refs)
        cankao = module._agent_video_payload("viduq3-turbo-cankaosheng", "prompt", 5, "9:16", refs)

        self.assertEqual(refs[:2], q3["params"]["images"])
        self.assertEqual("720p", q3["params"]["resolution"])
        self.assertEqual(5, turbo["params"]["duration"])
        self.assertEqual(refs[:2], turbo["params"]["images"])
        self.assertEqual(5, cankao["params"]["duration"])
        self.assertEqual(refs, cankao["params"]["images"])

        with self.assertRaisesRegex(RuntimeError, "需要上传参考图"):
            module._agent_video_payload("viduq3-turbo", "prompt", 5, "9:16", [])

    def test_agent_happyhorse_video_models_contract_match_lk888(self):
        module = load_client_module("matrix_native_client_agent_happyhorse_contract_test")
        refs = [
            "https://assets.example/ref1.png",
            "https://assets.example/ref2.png",
            "https://assets.example/ref3.png",
            "https://assets.example/ref4.png",
            "https://assets.example/ref5.png",
            "https://assets.example/ref6.png",
        ]
        source_video = "https://assets.example/source.mp4"

        for model in ("happyhorse-r2v", "happyhorse-1.1-r2v"):
            with self.subTest(model=model):
                self.assertEqual(tuple(range(3, 16)), module._agent_video_duration_slots(model))
                self.assertEqual(5, module._agent_video_reference_limit(model))
                payload = module._agent_video_payload(model, "prompt", 10, "9:16", refs)
                self.assertEqual(10, payload["params"]["duration"])
                self.assertEqual("720P", payload["params"]["resolution"])
                self.assertEqual("9:16", payload["params"]["ratio"])
                self.assertEqual(refs[:5], payload["params"]["images"])
                self.assertNotIn("aspect_ratio", payload["params"])

        edit = module._agent_video_payload(
            "happyhorse-video-edit", "prompt", 10, "9:16", refs,
            reference_video_url=source_video,
        )
        self.assertEqual(source_video, edit["video"])
        self.assertEqual(source_video, edit["video_url"])
        self.assertEqual([source_video], edit["video_urls"])
        self.assertEqual(source_video, edit["reference_video"])
        self.assertEqual(refs[:5], edit["images"])
        self.assertEqual(refs[:5], edit["params"]["images"])
        self.assertEqual("720P", edit["params"]["resolution"])
        self.assertEqual("origin", edit["params"]["audio_setting"])

        with self.assertRaisesRegex(RuntimeError, "需要上传参考视频"):
            module._agent_video_payload("happyhorse-video-edit", "prompt", 10, "16:9", refs)

    def test_agent_wan27_reference_video_uploads_to_lk888_payload(self):
        module = load_client_module("matrix_native_client_agent_wan27_reference_video_upload_test")

        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "reference.mp4"
            video.write_bytes(b"video")
            entry = {
                "id": "agent-wan-reference-video",
                "mode": "video",
                "prompt": "reference video generation",
                "visiblePrompt": "reference video generation",
                "model": "wan2.7-cankaosheng",
                "duration": 12,
                "aspect_ratio": "9:16",
                "referenceVideo": str(video),
            }
            with mock.patch.object(module, "data_dir", return_value=tmp), \
                    mock.patch.object(module, "_prodgen_refs_desc", return_value=""), \
                    mock.patch.object(module, "upload_asset_url", return_value=("https://assets.example/reference.mp4", {})) as upload, \
                    mock.patch.object(module, "update_prodgen"), \
                    mock.patch.object(module, "lk888_media_task", return_value="https://cdn.example.com/video.mp4") as media, \
                    mock.patch.object(module, "_wf_download"):
                module._prodgen_run_video(entry)

        payload = media.call_args.args[1]
        # 参考视频写进真实字段 reference_video（此前误写 video）。
        self.assertEqual("https://assets.example/reference.mp4", payload["params"]["reference_video"])
        self.assertNotIn("video", payload["params"])
        self.assertEqual(12, payload["params"]["duration"])
        self.assertEqual("video", upload.call_args.args[2])

    def test_agent_kling_v26_defaults_to_sound_on(self):
        module = load_client_module("matrix_native_client_agent_kling_v26_sound_test")

        payload = module._agent_video_payload("kling-v2-6", "有声视频", 5, "16:9", [])

        self.assertEqual("on", payload["params"]["sound"])
        self.assertNotIn("resolution", payload["params"])

    def test_legacy_image_entry_submits_media_task_and_returns_raw_json(self):
        module = load_client_module("matrix_native_client_legacy_image_submit_test")
        response = mock.Mock(status_code=200, ok=True, text='{"data":{"task_id":123}}')
        response.json.return_value = {"data": {"task_id": 123}, "message": "accepted"}

        with mock.patch.object(module, "lk888_config", return_value={
            "base_url": "https://api.example.com",
            "api_key": "secret-not-logged",
            "image_model": "gpt-image-2",
        }), mock.patch.object(module.requests, "post", return_value=response) as post:
            result = module.lk888_image_result("一张商品图")

        self.assertEqual({"data": {"task_id": 123}, "message": "accepted"}, result)
        post.assert_called_once()
        self.assertTrue(post.call_args.args[0].endswith("/v1/media/generate"))
        self.assertEqual("gpt-image-2", post.call_args.kwargs["json"]["model"])

    def test_agent_known_model_rules_survive_lk888_catalog_mismatch(self):
        module = load_client_module("matrix_native_client_agent_catalog_rules_test")
        catalog = [{
            "name": "doubao-seedance-1-5-pro-251215",
            "display_name": "GPT Image 2",
            "type": "image",
            "duration_slots": [999],
        }]

        with mock.patch.object(module, "_lk888_skill_models", return_value=catalog):
            rows = module._lk888_models_by_type("video")

        seedance = next(row for row in rows if row["name"] == "doubao-seedance-1-5-pro-251215")
        self.assertEqual("Seedance 1.5 Pro", seedance["display_name"])
        self.assertEqual("video", seedance["type"])
        self.assertEqual((4, 8, 12), seedance["duration_slots"])

    def test_agent_video_menu_uses_same_rows_as_current_model_validation(self):
        src = CLIENT.read_text(encoding="utf-8")
        pick_start = src.index("    def _pick_model(self):")
        pick_end = src.index("\n    def _add_card", pick_start)
        pick_src = src[pick_start:pick_end]

        self.assertIn("rows = self._model_rows()", pick_src)
        self.assertIn("_lk888_grouped_models(mode, rows)", pick_src)
        self.assertNotIn("_lk888_grouped_models(mode):", pick_src)

    def test_agent_grouped_models_can_group_loaded_online_only_video_rows(self):
        module = load_client_module("matrix_native_client_agent_loaded_rows_group_test")
        loaded_rows = [
            {"name": "omni-reference-video", "display_name": "Omni Reference Video", "type": "video"},
            {"name": "vendor-x-video", "display_name": "Vendor X Video", "type": "video"},
        ]

        groups = module._lk888_grouped_models("video", loaded_rows)

        by_family = {family: [row["name"] for row in rows] for family, rows in groups}
        self.assertIn("omni-reference-video", by_family["Omni"])
        self.assertIn("vendor-x-video", by_family["其他"])

    def test_agent_video_catalog_excludes_digital_human_only_model(self):
        module = load_client_module("matrix_native_client_agent_video_catalog_scope_test")
        catalog = [{
            "name": "kling-avatar-image2video",
            "display_name": "Kling Digital Human",
            "type": "video",
        }]

        with mock.patch.object(module, "_lk888_skill_models", return_value=catalog):
            rows = module._lk888_models_by_type("video")

        names = [row.get("name") for row in rows]
        self.assertNotIn("kling-avatar-image2video", names)

    def test_agent_video_catalog_excludes_vidu_narrated_comic_model(self):
        module = load_client_module("matrix_native_client_agent_video_catalog_vidu_comic_scope_test")
        catalog = [{
            "name": "vidu-jieshuoman",
            "display_name": "VIDU Narrated Comic",
            "type": "video",
        }]

        with mock.patch.object(module, "_lk888_skill_models", return_value=catalog):
            rows = module._lk888_models_by_type("video")

        names = [row.get("name") for row in rows]
        labels = [row.get("display_name") for row in rows]
        self.assertNotIn("vidu-jieshuoman", names)
        self.assertNotIn("VIDU Narrated Comic", labels)

    def test_agent_video_catalog_excludes_vidu_music_mv_model(self):
        module = load_client_module("matrix_native_client_agent_video_catalog_vidu_mv_scope_test")
        catalog = [{
            "name": "vidu-mv",
            "display_name": "VIDU-Music MV",
            "type": "video",
        }]

        with mock.patch.object(module, "_lk888_skill_models", return_value=catalog):
            rows = module._lk888_models_by_type("video")

        names = [row.get("name") for row in rows]
        labels = [row.get("display_name") for row in rows]
        self.assertNotIn("vidu-mv", names)
        self.assertNotIn("VIDU-Music MV", labels)

    def test_agent_video_catalog_excludes_kling_motion_control_v3_model(self):
        module = load_client_module("matrix_native_client_agent_video_catalog_kling_motion_scope_test")
        catalog = [{
            "name": "kling-motion-control-v3",
            "display_name": "Kling Motion Control V3",
            "type": "video",
        }]

        fallback_rows = module._lk888_fallback_models_by_type("video")
        with mock.patch.object(module, "_lk888_skill_models", return_value=catalog):
            rows = module._lk888_models_by_type("video")
        groups = module._lk888_grouped_models("video", catalog)

        fallback_names = [row.get("name") for row in fallback_rows]
        names = [row.get("name") for row in rows]
        labels = [row.get("display_name") for row in rows]
        grouped_names = [row.get("name") for _family, items in groups for row in items]
        self.assertNotIn("kling-motion-control-v3", fallback_names)
        self.assertNotIn("kling-motion-control-v3", names)
        self.assertNotIn("Kling Motion Control V3", labels)
        self.assertNotIn("kling-motion-control-v3", grouped_names)

    def test_agent_video_uploads_reference_images_to_lk888_payload(self):
        module = load_client_module("matrix_native_client_agent_video_refs_payload_test")

        with tempfile.TemporaryDirectory() as tmp:
            ref1 = Path(tmp) / "ref1.png"
            ref2 = Path(tmp) / "ref2.jpg"
            ref1.write_bytes(b"png-1")
            ref2.write_bytes(b"jpg-2")
            entry = {
                "id": "agent-video-refs",
                "mode": "video",
                "prompt": "生成商品展示视频",
                "duration": 10,
                "model": module._LK888_VIDEO_DEFAULT,
                "aspect_ratio": "9:16",
                "refs": [str(ref1), str(ref2)],
            }
            uploaded = [
                "https://assets.example/agent/ref1.png",
                "https://assets.example/agent/ref2.jpg",
            ]

            with mock.patch.object(module, "data_dir", return_value=tmp), \
                    mock.patch.object(module, "_prodgen_refs_desc", return_value="reference descriptions"), \
                    mock.patch.object(module, "_prodgen_expand_prompt", return_value="video prompt"), \
                    mock.patch.object(module, "upload_asset_url", side_effect=[(uploaded[0], {}), (uploaded[1], {})]) as upload, \
                    mock.patch.object(module, "update_prodgen"), \
                    mock.patch.object(module, "lk888_media_task", return_value="https://cdn.example.com/video.mp4") as media, \
                    mock.patch.object(module, "_wf_download"):
                module._prodgen_run_video(entry)

        payload = media.call_args.args[1]
        self.assertEqual(uploaded, payload["image_urls"])
        self.assertEqual(uploaded, payload["images"])
        self.assertEqual(uploaded, payload["reference_images"])
        self.assertEqual(uploaded, payload["referenceImages"])
        self.assertEqual(uploaded, payload["params"]["images"])
        self.assertEqual(uploaded, payload["params"]["image_urls"])
        self.assertEqual(uploaded, payload["params"]["reference_images"])
        self.assertEqual(2, upload.call_count)
        self.assertEqual("image", upload.call_args_list[0].args[2])

    def test_agent_video_reference_upload_failure_does_not_submit_lk888_task(self):
        module = load_client_module("matrix_native_client_agent_video_refs_upload_fail_test")

        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "ref.png"
            ref.write_bytes(b"png")
            entry = {
                "id": "agent-video-ref-fail",
                "mode": "video",
                "prompt": "生成商品展示视频",
                "duration": 5,
                "model": module._LK888_VIDEO_DEFAULT,
                "refs": [str(ref)],
            }

            with mock.patch.object(module, "_prodgen_refs_desc", return_value="reference descriptions"), \
                    mock.patch.object(module, "_prodgen_expand_prompt", return_value="video prompt"), \
                    mock.patch.object(module, "upload_asset_url", side_effect=RuntimeError("upload down")), \
                    mock.patch.object(module, "lk888_media_task", return_value="https://cdn.example.com/video.mp4") as media, \
                    mock.patch.object(module, "_wf_download"):
                with self.assertRaisesRegex(RuntimeError, "参考图上传失败"):
                    module._prodgen_run_video(entry)

        media.assert_not_called()

    def test_agent_generation_error_text_hides_lk888_status_fields(self):
        module = load_client_module("matrix_native_client_agent_error_display_text_test")
        raw = "kling-image-o1 生成失败:status=Error; message=当前分组上游负载已饱和，请稍后再试"

        display = module._prodgen_user_error_text(raw)

        self.assertEqual("当前分组上游负载已饱和，请稍后再试", display)
        self.assertNotIn("status=", display)
        self.assertNotIn("message=", display)
        self.assertNotIn("Error", display)
        self.assertNotIn("kling-image-o1", display)

    def test_agent_generation_error_text_handles_chinese_colon_and_compact_message(self):
        module = load_client_module("matrix_native_client_agent_error_display_compact_test")
        timeout_raw = (
            "kling-image-o1生成失败：status=Error;message=HTTP请求失败：请求失败："
            "网络异常：连接超时，请稍后重试"
        )
        maintenance_raw = "kling-v3生成失败：status=Error;message=上游渠道维护中，请稍后再试"

        timeout_display = module._prodgen_user_error_text(timeout_raw)
        maintenance_display = module._prodgen_user_error_text(maintenance_raw)

        self.assertEqual("网络异常：连接超时，请稍后重试", timeout_display)
        self.assertEqual("上游渠道维护中，请稍后再试", maintenance_display)
        for display in (timeout_display, maintenance_display):
            self.assertNotIn("status=", display)
            self.assertNotIn("message=", display)
            self.assertNotIn("Error", display)
            self.assertNotIn("kling-", display)

    def test_agent_generation_error_text_localizes_status_style_variants(self):
        module = load_client_module("matrix_native_client_agent_error_display_variants_test")
        cases = [
            (
                "mj_imagine 生成失败:status=failed;msg=upstream request timeout",
                "网络连接超时，请稍后重试",
            ),
            (
                "vidu-image-2 生成失败：status=Error;error=Connection refused",
                "无法连接上游服务，请稍后重试",
            ),
            (
                "gpt-image-2 生成失败：status=Error;detail=HTTP 500 Internal Server Error",
                "上游服务暂时异常，请稍后重试",
            ),
            (
                "wan2.7-image 生成失败：status=Error;reason=上游服务繁忙",
                "上游服务繁忙",
            ),
            (
                "kling-v3 生成失败：status=Error",
                "生成失败，请稍后重试。",
            ),
        ]

        for raw, expected in cases:
            with self.subTest(raw=raw):
                display = module._prodgen_user_error_text(raw)
                self.assertEqual(expected, display)
                self.assertNotIn("status=", display)
                self.assertNotIn("message=", display)
                self.assertNotIn("msg=", display)
                self.assertNotIn("error=", display)
                self.assertNotIn("detail=", display)
                self.assertNotIn("reason=", display)
                self.assertNotIn("Error", display)

    def test_agent_generation_error_text_extracts_json_msg_from_missing_task_id(self):
        module = load_client_module("matrix_native_client_agent_error_display_json_msg_test")
        raw = 'vidu-mv未拿到任务ID："code"：400,"msg"："请上传1个音频文件"'

        display = module._prodgen_user_error_text(raw)

        self.assertEqual("请上传1个音频文件", display)
        self.assertNotIn("code", display)
        self.assertNotIn("400", display)
        self.assertNotIn("msg", display)
        self.assertNotIn("vidu-mv", display)

    def test_agent_generation_error_text_prefers_json_detail_over_generic_msg(self):
        module = load_client_module("matrix_native_client_agent_error_display_json_detail_test")
        raw = (
            'kling-v2-6 未拿到任务ID:"code":400,'
            '"data":{"详情":"参数sound 的值false 不合法"},"msg":"参数验证失败"}'
        )

        display = module._prodgen_user_error_text(raw)

        self.assertEqual("参数 sound 的值 false 不合法", display)
        self.assertNotIn("code", display)
        self.assertNotIn("400", display)
        self.assertNotIn("msg", display)
        self.assertNotIn("data", display)
        self.assertNotIn("kling-v2-6", display)

    def test_agent_generation_error_text_extracts_msg_from_unquoted_code_shape(self):
        module = load_client_module("matrix_native_client_agent_error_display_unquoted_code_test")
        raw = '{code":400,"data":null,"msg"："参考图像（image_url)不能为空"}'

        display = module._prodgen_user_error_text(raw)

        self.assertEqual("参考图像（image_url）不能为空", display)
        self.assertNotIn("code", display)
        self.assertNotIn("400", display)
        self.assertNotIn("msg", display)
        self.assertNotIn("data", display)

    def test_agent_generation_error_text_extracts_msg_from_mixed_quotes_json_shape(self):
        module = load_client_module("matrix_native_client_agent_error_display_mixed_quotes_test")
        raw = '{”code"：400,"data":null,"msg"："首尾帧模式最多支持2张图片"}'

        display = module._prodgen_user_error_text(raw)

        self.assertEqual("首尾帧模式最多支持2张图片", display)
        self.assertNotIn("code", display)
        self.assertNotIn("400", display)
        self.assertNotIn("msg", display)
        self.assertNotIn("data", display)


if __name__ == "__main__":
    unittest.main()
