from pathlib import Path
import ast
import copy
import datetime
import hashlib
import inspect
import json
import re
import secrets
import types
import unittest
import urllib
import urllib.error
import urllib.request
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "tools/aicanvas_remote/server_current.py"


def load_server():
    source = SERVER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SERVER))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {
            "_comic_storyboard_requested_image_frame_index",
            "_comic_storyboard_image_generation_workflow_mode",
            "_comic_storyboard_batch_payload",
            "_expand_comic_storyboard_image_submit_kwargs",
            "_apply_strict_storyboard_references_to_params",
            "_merge_reference_urls_into_params",
            "_dedupe_urls",
            "_apimart_publicize_ref",
            "_extend_url_list",
            "_set_url_at_index",
            "_apply_comic_frame_task_overlays",
            "_normalize_comic_storyboard_audio_mode",
            "_is_matrix_video_replacement_project",
            "_find_recent_duplicate_storyboard_video_task",
            "_apply_comic_storyboard_audio_mode_metadata",
            "_comic_storyboard_video_params_with_dialogue_audio",
            "_comic_storyboard_tts_url_from_task",
            "_finalize_ai_comic_fallback_video_audio",
            "_ai_comic_task_response",
            "_handle_ai_comic_api_request",
            "_handle_comic_frame_generate_image_proxy",
            "_handle_platform_api_proxy",
            "_is_file_descriptor_exhaustion_error",
            "_platform_json_request",
        }
    ]
    module = types.ModuleType("aicanvas_frame_billing_under_test")
    module.__dict__.update({
        "json": json,
        "copy": copy,
        "datetime": datetime,
        "re": re,
        "hashlib": hashlib,
        "urllib": urllib,
        "secrets": secrets,
        "PLATFORM_API_PROXY_TIMEOUT_SECONDS": 120,
        "AICANVAS_INTERNAL_SECRET": "",
        "COMIC_DEFAULT_IMAGE_MODEL": "gpt-image-2-guan",
        "_normalize_comic_storyboard_workflow_mode": lambda value: value,
        "_comic_storyboard_workflow_mode": lambda project, payload: "",
        "_first_non_empty": lambda *values: next((value for value in values if value), ""),
        "_comic_proxy_task_id_from_response": lambda value: value.get("data", {}).get("task_id", ""),
        "LOCAL_COMIC_TASKS": {},
        "LOCAL_COMIC_PROJECTS": {},
        "_json_log": lambda *args, **kwargs: None,
        "_comic_frame_image_model_error": lambda *args, **kwargs: "",
        "_comic_storyboard_frame_prompt_source": lambda *args, **kwargs: "",
        "_comic_storyboard_image_frame_prompts": lambda *args, **kwargs: [],
        "_platform_api_proxy_headers": lambda *args, **kwargs: {},
        "_platform_url": lambda path: "https://platform.example" + path,
        "_register_comic_frame_task_overlay": lambda *args, **kwargs: None,
        "_load_comic_frame_task_overlays": lambda: {},
        "_send_json_with_headers": lambda *args, **kwargs: None,
        "_comic_display_media_payload": lambda value: value,
        "_fallback_ai_comic_task_result_url": lambda task: "",
        "_is_local_comic_auto_edit_task": lambda task: False,
        "_local_comic_billing_amount": lambda task: 0,
        "_aic_looks_like_image_url": lambda value: False,
        "_comic_display_task_step": lambda value: value,
        "_use_ai_api_provider": lambda: True,
        "_comic_truthy": lambda value: str(value or "").strip().lower() in {"1", "true", "yes", "on"},
        "_comic_video_model_needs_storyboard_dialogue_audio": lambda model: True,
        "_find_recent_duplicate_storyboard_video_task": lambda *args: None,
        "_comic_storyboard_dialogue_text_for_tts": lambda storyboard: str(storyboard.get("dialogue") or ""),
        "_local_comic_storyboard_character_audio_reference_context": lambda *args: ["https://media.example/voice.mp3"],
        "_local_comic_storyboard_character_voice_hint": lambda *args: "Zephyr",
        "_AIC_GEMINI_TTS_VOICES": {"zephyr"},
        "_submit_comic_storyboard_dialogue_audio": lambda *args, **kwargs: "https://media.example/tts.mp3",
        "_merge_audio_refs_into_params": lambda params, refs: {**params, "audio_urls": list(refs)},
        "_comic_nearest_video_duration_for_model": lambda *args: None,
        "_comic_remux_video_with_storyboard_tts": lambda *args: {
            "url": "/data/uploads/comic-drama/remuxed.mp4",
            "video_duration_seconds": 5.0,
            "audio_duration_seconds": 6.0,
            "final_duration_seconds": 6.0,
        },
        "_save_local_comic_state": lambda: None,
        "AiApiService": types.SimpleNamespace(sanitize_error=lambda value: str(value)),
    })
    ast.fix_missing_locations(tree)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SERVER), "exec"), module.__dict__)
    return module


def load_storyboard_video_submit_server():
    source = SERVER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SERVER))
    names = {
        "_normalize_comic_storyboard_audio_mode",
        "_is_matrix_video_replacement_project",
        "_comic_storyboard_video_params_with_dialogue_audio",
        "_find_recent_duplicate_storyboard_video_task",
        "_submit_ai_comic_media_task",
    }
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = types.ModuleType("aicanvas_storyboard_video_submit_under_test")
    local_tasks = {}
    gateway_calls = []
    tts_calls = []

    def submit_gateway(model, prompt, params=None, count=1):
        gateway_calls.append({
            "model": model,
            "prompt": prompt,
            "params": copy.deepcopy(params or {}),
            "count": count,
        })
        return {"task_id": "gateway-%d" % len(gateway_calls)}

    def register_task(**kwargs):
        task = {
            "id": "ai-%s" % kwargs["remote_task_id"],
            "task_type": kwargs["task_type"],
            "target_type": kwargs["target_type"],
            "project_id": kwargs["project_id"],
            "target_id": kwargs["target_id"],
            "model": kwargs["model"],
            "status": "pending",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "params": copy.deepcopy(kwargs.get("params") or {}),
        }
        local_tasks[task["id"]] = task
        return task

    def submit_tts(*args, **kwargs):
        tts_calls.append((args, kwargs))
        return "https://media.example/prepared-tts.mp3"

    module.__dict__.update({
        "copy": copy,
        "datetime": datetime,
        "LOCAL_COMIC_TASKS": local_tasks,
        "LOCAL_COMIC_PROJECTS": {},
        "_comic_truthy": lambda value: str(value or "").strip().lower() in {"1", "true", "yes", "on"},
        "_normalize_video_size_keys": lambda value: dict(value or {}),
        "_truncate_comic_video_submit_prompt": lambda prompt, limit: prompt,
        "_comic_video_submit_prompt_limit": lambda model: 2000,
        "_comic_storyboard_workflow_mode": lambda project, params: params.get("workflow_mode") or "keyframes",
        "_local_comic_project_for_current_scope": lambda project_id: None,
        "_find_recent_duplicate_character_task": lambda *args, **kwargs: None,
        "_charge_local_ai_model_call": lambda *args, **kwargs: {"request_id": "charge-1"},
        "_ark_should_route": lambda model: False,
        "_submit_comic_gateway_video_task": submit_gateway,
        "_register_ai_comic_task": register_task,
        "_register_ai_comic_failed_task": lambda **kwargs: {},
        "_refund_canvas_model_call": lambda *args, **kwargs: None,
        "_comic_real_person_video_fallback_models": lambda: [],
        "_is_minimax_h3_comic_model": lambda model: str(model or "").strip().lower() == "minimax-h3",
        "_ark_storyboard_video_fallback_reason": lambda error: "",
        "_save_local_comic_state": lambda: None,
        "_json_log": lambda *args, **kwargs: None,
        "_comic_video_model_needs_storyboard_dialogue_audio": lambda model: True,
        "_comic_storyboard_dialogue_text_for_tts": lambda storyboard: str(storyboard.get("dialogue") or ""),
        "_local_comic_storyboard_character_audio_reference_context": lambda *args: ["https://media.example/voice.mp3"],
        "_local_comic_storyboard_character_voice_hint": lambda *args: "Zephyr",
        "_AIC_GEMINI_TTS_VOICES": {"zephyr"},
        "_submit_comic_storyboard_dialogue_audio": submit_tts,
        "_merge_audio_refs_into_params": lambda params, refs: {**params, "audio_urls": list(refs)},
        "_comic_nearest_video_duration_for_model": lambda *args: None,
        "AiApiService": types.SimpleNamespace(sanitize_error=lambda value: str(value)),
    })
    ast.fix_missing_locations(tree)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SERVER), "exec"), module.__dict__)
    module.gateway_calls = gateway_calls
    module.tts_calls = tts_calls
    return module


class _FakeResponse:
    def __init__(self, task_id):
        self._body = json.dumps({"data": {"task_id": task_id}}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._body


class ComicFrameBillingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = load_server()

    def test_platform_json_request_reports_file_descriptor_exhaustion_without_python_detail(self):
        logs = []

        with mock.patch.object(
                self.server.urllib.request,
                "urlopen",
                side_effect=urllib.error.URLError(OSError(24, "Too many open files")),
        ), mock.patch.object(
                self.server,
                "_json_log",
                side_effect=lambda event, **fields: logs.append({"event": event, **fields}),
        ):
            status, data = self.server._platform_json_request(
                "/aicanvas/billing/charge",
                {"request_id": "req-1"},
                timeout=30,
            )

        self.assertEqual(status, 503)
        self.assertEqual(data["code"], "platform_fd_exhausted")
        self.assertIn("远程平台连接资源耗尽", data["detail"])
        self.assertNotIn("URLError", data["detail"])
        self.assertNotIn("Too many open files", data["detail"])
        self.assertEqual(logs[-1]["event"], "platform_json_request_fd_exhausted")
        self.assertEqual(logs[-1]["path"], "/aicanvas/billing/charge")

    def _storyboard_video_params(self, params):
        return self.server._comic_storyboard_video_params_with_dialogue_audio(
            params,
            {"id": 293},
            {"id": 293001, "dialogue": "A short line"},
            "digital-human-video-model",
            293,
            293001,
        )

    def test_explicit_auto_skips_storyboard_tts_and_removes_internal_audio_mode(self):
        logs = []
        params = {
            "audio_mode": "auto",
            "duration": 5,
            "source_url": "https://private.example/video.mp4",
            "token": "secret-token",
            "headers": {"Authorization": "Bearer secret-token"},
        }

        with mock.patch.object(
                self.server,
                "_submit_comic_storyboard_dialogue_audio",
                side_effect=AssertionError("auto must not prepare TTS"),
        ) as submit_tts, mock.patch.object(
                self.server,
                "_json_log",
                side_effect=lambda event, **fields: logs.append((event, fields)),
        ):
            result = self._storyboard_video_params(params)

        submit_tts.assert_not_called()
        self.assertNotIn("audio_mode", result)
        for key in ("sound_file", "soundFile", "audio", "audio_file", "audioFile", "reference_audio_file"):
            self.assertNotIn(key, result)
        self.assertEqual(result["duration"], 5)
        self.assertEqual(logs[-1][0], "comic_storyboard_dialogue_audio_skipped")
        self.assertEqual(logs[-1][1]["audio_mode"], "auto")
        serialized_logs = json.dumps(logs, ensure_ascii=False).lower()
        self.assertNotIn("https://", serialized_logs)
        self.assertNotIn("secret-token", serialized_logs)
        self.assertNotIn("authorization", serialized_logs)
        self.assertNotIn("headers", serialized_logs)

    def test_matrix_replacement_auto_with_dialogue_prepares_storyboard_tts(self):
        project = {"id": 293, "source_mode": "matrix_video_replacement"}
        storyboard = {"id": 293001, "dialogue": "用户最终口播稿"}

        with mock.patch.object(
                self.server,
                "_submit_comic_storyboard_dialogue_audio",
                return_value="https://media.example/matrix-tts.mp3",
        ) as submit_tts:
            result = self.server._comic_storyboard_video_params_with_dialogue_audio(
                {"audio_mode": "auto", "duration": 5},
                project,
                storyboard,
                "digital-human-video-model",
                293,
                293001,
            )

        submit_tts.assert_called_once()
        self.assertNotIn("audio_mode", result)
        self.assertEqual(result["sound_file"], "https://media.example/matrix-tts.mp3")

    def test_explicit_tts_prepares_storyboard_audio_and_removes_internal_audio_mode(self):
        with mock.patch.object(
                self.server,
                "_submit_comic_storyboard_dialogue_audio",
                return_value="https://media.example/prepared-tts.mp3",
        ) as submit_tts:
            result = self._storyboard_video_params({"audio_mode": "tts", "duration": 5})

        submit_tts.assert_called_once()
        self.assertNotIn("audio_mode", result)
        self.assertEqual(result["sound_file"], "https://media.example/prepared-tts.mp3")
        self.assertEqual(result["audio"], "https://media.example/prepared-tts.mp3")

    def test_missing_audio_mode_preserves_legacy_storyboard_tts(self):
        with mock.patch.object(
                self.server,
                "_submit_comic_storyboard_dialogue_audio",
                return_value="https://media.example/legacy-tts.mp3",
        ) as submit_tts:
            result = self._storyboard_video_params({"duration": 5})

        submit_tts.assert_called_once()
        self.assertEqual(result["sound_file"], "https://media.example/legacy-tts.mp3")

        task = {}
        self.server._apply_comic_storyboard_audio_mode_metadata(task, None)
        self.assertEqual(task.get("audio_mode"), "legacy")
        self.assertEqual(task.get("audioMode"), "legacy")

    def test_storyboard_video_duplicates_are_isolated_by_audio_semantics(self):
        signature = inspect.signature(self.server._find_recent_duplicate_storyboard_video_task)
        if "audio_mode" not in signature.parameters:
            self.fail("duplicate matcher does not accept audio_mode")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        modes = ("auto", "tts", "legacy")
        for existing_mode in modes:
            for requested_mode in modes:
                with self.subTest(existing_mode=existing_mode, requested_mode=requested_mode):
                    task = {
                        "id": "task-%s" % existing_mode,
                        "task_type": "generate_video",
                        "target_type": "storyboard",
                        "project_id": 293,
                        "target_id": 293001,
                        "model": "video-model",
                        "status": "pending",
                        "created_at": now,
                        "audio_mode": existing_mode,
                        "audioMode": existing_mode,
                    }
                    self.server.LOCAL_COMIC_TASKS = {task["id"]: task}
                    duplicate = self.server._find_recent_duplicate_storyboard_video_task(
                        293,
                        293001,
                        "video-model",
                        audio_mode=None if requested_mode == "legacy" else requested_mode,
                    )
                    if requested_mode == existing_mode:
                        self.assertIs(duplicate, task)
                    else:
                        self.assertIsNone(duplicate)

    def test_old_storyboard_video_task_without_mode_only_matches_legacy_request(self):
        signature = inspect.signature(self.server._find_recent_duplicate_storyboard_video_task)
        if "audio_mode" not in signature.parameters:
            self.fail("duplicate matcher does not accept audio_mode")

        task = {
            "id": "old-task",
            "task_type": "generate_video",
            "target_type": "storyboard",
            "project_id": 293,
            "target_id": 293001,
            "model": "video-model",
            "status": "pending",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self.server.LOCAL_COMIC_TASKS = {task["id"]: task}

        self.assertIs(
            self.server._find_recent_duplicate_storyboard_video_task(
                293, 293001, "video-model", audio_mode=None,
            ),
            task,
        )
        self.assertIsNone(self.server._find_recent_duplicate_storyboard_video_task(
            293, 293001, "video-model", audio_mode="auto",
        ))
        self.assertIsNone(self.server._find_recent_duplicate_storyboard_video_task(
            293, 293001, "video-model", audio_mode="tts",
        ))

    def test_reused_task_audio_mode_metadata_is_never_overwritten_by_mismatch(self):
        task = {"audio_mode": "auto", "audioMode": "auto"}

        result = self.server._apply_comic_storyboard_audio_mode_metadata(task, "tts")

        self.assertIs(result, task)
        self.assertEqual(task["audio_mode"], "auto")
        self.assertEqual(task["audioMode"], "auto")

    def test_task_response_exposes_both_audio_mode_aliases(self):
        response = self.server._ai_comic_task_response({
            "id": "task-legacy",
            "task_type": "generate_video",
            "target_type": "storyboard",
            "status": "pending",
            "audio_mode": "legacy",
        })

        self.assertEqual(response.get("audio_mode"), "legacy")
        self.assertEqual(response.get("audioMode"), "legacy")

    def _active_storyboard_video_task(self, task_type, audio_mode):
        return {
            "id": "existing-%s-%s" % (task_type, audio_mode),
            "task_type": task_type,
            "target_type": "storyboard",
            "project_id": 293,
            "target_id": 293001,
            "model": "video-model",
            "status": "pending",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "audio_mode": audio_mode,
            "audioMode": audio_mode,
        }

    def _submit_storyboard_video(self, module, task_type, audio_mode):
        return module._submit_ai_comic_media_task(
            model="video-model",
            prompt="shot",
            params={"duration": 5},
            count=1,
            project_id=293,
            task_type=task_type,
            task_name="storyboard video",
            target_id=293001,
            target_type="storyboard",
            audio_mode=None if audio_mode == "legacy" else audio_mode,
        )

    def test_direct_and_batch_storyboard_video_submission_reuse_matrix(self):
        task_types = ("generate_video", "batch_storyboard_videos")
        modes = ("auto", "tts", "legacy")
        module = load_storyboard_video_submit_server()
        for existing_task_type in task_types:
            for requested_task_type in task_types:
                for existing_mode in modes:
                    for requested_mode in modes:
                        with self.subTest(
                                existing_task_type=existing_task_type,
                                requested_task_type=requested_task_type,
                                existing_mode=existing_mode,
                                requested_mode=requested_mode,
                        ):
                            existing = self._active_storyboard_video_task(existing_task_type, existing_mode)
                            module.LOCAL_COMIC_TASKS.clear()
                            module.LOCAL_COMIC_TASKS[existing["id"]] = existing
                            module.gateway_calls.clear()

                            result = self._submit_storyboard_video(module, requested_task_type, requested_mode)

                            if existing_mode == requested_mode:
                                self.assertIs(result, existing)
                                self.assertEqual(module.gateway_calls, [])
                            else:
                                self.assertIsNot(result, existing)
                                self.assertEqual(len(module.gateway_calls), 1)

    def test_storyboard_video_submission_persists_project_source_mode(self):
        module = load_storyboard_video_submit_server()
        module.LOCAL_COMIC_PROJECTS[293] = {"id": 293, "source_mode": "matrix_video_replacement"}

        result = self._submit_storyboard_video(module, "generate_video", "auto")

        self.assertEqual(result.get("project_source_mode"), "matrix_video_replacement")
        self.assertEqual(result.get("projectSourceMode"), "matrix_video_replacement")

    def test_tts_duplicate_short_circuit_and_submission_share_storyboard_video_family(self):
        task_types = ("generate_video", "batch_storyboard_videos")
        module = load_storyboard_video_submit_server()
        for existing_task_type in task_types:
            for requested_task_type in task_types:
                for audio_mode in ("tts", "legacy"):
                    with self.subTest(
                            existing_task_type=existing_task_type,
                            requested_task_type=requested_task_type,
                            audio_mode=audio_mode,
                    ):
                        existing = self._active_storyboard_video_task(existing_task_type, audio_mode)
                        module.LOCAL_COMIC_TASKS.clear()
                        module.LOCAL_COMIC_TASKS[existing["id"]] = existing
                        module.gateway_calls.clear()
                        module.tts_calls.clear()
                        params = {} if audio_mode == "legacy" else {"audio_mode": "tts"}

                        prepared = module._comic_storyboard_video_params_with_dialogue_audio(
                            params,
                            {"id": 293},
                            {"id": 293001, "dialogue": "A short line"},
                            "video-model",
                            293,
                            293001,
                        )
                        result = self._submit_storyboard_video(module, requested_task_type, audio_mode)

                        self.assertEqual(module.tts_calls, [])
                        self.assertNotIn("sound_file", prepared)
                        self.assertIs(result, existing)
                        self.assertEqual(module.gateway_calls, [])

    def test_batch_storyboard_video_duplicate_keeps_old_positional_seconds_compatible(self):
        module = load_storyboard_video_submit_server()
        existing = self._active_storyboard_video_task("batch_storyboard_videos", "legacy")
        module.LOCAL_COMIC_TASKS[existing["id"]] = existing

        duplicate = module._find_recent_duplicate_storyboard_video_task(
            293, 293001, "video-model", 900,
        )

        self.assertIs(duplicate, existing)

    def test_unrelated_batch_target_types_do_not_join_storyboard_video_family(self):
        module = load_storyboard_video_submit_server()
        unrelated = {
            **self._active_storyboard_video_task("batch_character_videos", "auto"),
            "target_type": "character",
        }
        module.LOCAL_COMIC_TASKS[unrelated["id"]] = unrelated

        duplicate = module._find_recent_duplicate_storyboard_video_task(
            293, 293001, "video-model", audio_mode="auto",
        )
        result = module._submit_ai_comic_media_task(
            model="video-model",
            prompt="character",
            params={},
            count=1,
            project_id=293,
            task_type="batch_character_videos",
            task_name="character video",
            target_id=293001,
            target_type="character",
            audio_mode="auto",
        )

        self.assertIsNone(duplicate)
        self.assertNotIn("audio_mode", result)
        self.assertNotIn("audioMode", result)

    def test_explicit_auto_fallback_preserves_provider_audio_without_remux(self):
        logs = []
        provider_url = "https://private.example/provider-result.mp4"
        task = {
            "id": "ai-fallback-auto",
            "status": "completed",
            "state": "completed",
            "project_id": 293,
            "target_id": 293001,
            "target_type": "storyboard",
            "task_type": "generate_video",
            "fallback_applied": True,
            "actual_model": "fallback-video-model",
            "result_url": provider_url,
            "fallback_source_params": {
                "audio_mode": "auto",
                "sound_file": "https://private.example/tts.mp3",
                "token": "secret-token",
            },
        }

        with mock.patch.object(
                self.server,
                "_comic_remux_video_with_storyboard_tts",
                side_effect=AssertionError("auto must not invoke FFmpeg/TTS remux"),
        ) as remux, mock.patch.object(
                self.server,
                "_json_log",
                side_effect=lambda event, **fields: logs.append((event, fields)),
        ):
            result = self.server._finalize_ai_comic_fallback_video_audio(task)

        self.assertIs(result, task)
        remux.assert_not_called()
        self.assertEqual(task["result_url"], provider_url)
        self.assertEqual(task["audio_source"], "provider_generated")
        self.assertEqual(task["audioSource"], "provider_generated")
        self.assertEqual(task["audio_mix_status"], "not_requested")
        self.assertEqual(task["audioMixStatus"], "not_requested")
        self.assertEqual(logs[-1][0], "comic_storyboard_fallback_audio_mix_skipped")
        serialized_logs = json.dumps(logs, ensure_ascii=False).lower()
        self.assertNotIn("https://", serialized_logs)
        self.assertNotIn("secret-token", serialized_logs)
        self.assertNotIn("authorization", serialized_logs)
        self.assertNotIn("headers", serialized_logs)

    def test_explicit_tts_fallback_keeps_forced_storyboard_tts_remux(self):
        provider_url = "https://private.example/provider-result.mp4"
        tts_url = "https://private.example/tts.mp3"
        task = {
            "id": "ai-fallback-tts",
            "status": "completed",
            "state": "completed",
            "project_id": 293,
            "target_id": 293001,
            "target_type": "storyboard",
            "task_type": "generate_video",
            "fallback_applied": True,
            "actual_model": "fallback-video-model",
            "result_url": provider_url,
            "fallback_source_params": {"audio_mode": "tts", "sound_file": tts_url},
        }
        mix_result = {
            "url": "/data/uploads/comic-drama/remuxed.mp4",
            "video_duration_seconds": 5.0,
            "audio_duration_seconds": 6.0,
            "final_duration_seconds": 6.0,
        }

        with mock.patch.object(
                self.server,
                "_comic_remux_video_with_storyboard_tts",
                return_value=mix_result,
        ) as remux:
            result = self.server._finalize_ai_comic_fallback_video_audio(task)

        self.assertIs(result, task)
        remux.assert_called_once_with(provider_url, tts_url, 293, 293001)
        self.assertEqual(task["result_url"], mix_result["url"])
        self.assertEqual(task["audio_source"], "storyboard_tts")
        self.assertEqual(task["audio_mix_status"], "completed")

    def test_matrix_primary_video_replaces_provider_audio_with_storyboard_tts(self):
        provider_url = "https://private.example/provider-result.mp4"
        tts_url = "https://private.example/tts.mp3"
        self.server.LOCAL_COMIC_PROJECTS = {
            293: {"id": 293, "source_mode": "matrix_video_replacement"}
        }
        task = {
            "id": "ai-matrix-primary-tts",
            "status": "completed",
            "state": "completed",
            "project_id": 293,
            "target_id": 293001,
            "target_type": "storyboard",
            "task_type": "generate_video",
            "result_url": provider_url,
            "params": {"audio_mode": "tts", "sound_file": tts_url},
        }
        mix_result = {
            "url": "/data/uploads/comic-drama/matrix-remuxed.mp4",
            "video_duration_seconds": 5.0,
            "audio_duration_seconds": 5.0,
            "final_duration_seconds": 5.0,
        }

        with mock.patch.object(
                self.server,
                "_comic_remux_video_with_storyboard_tts",
                return_value=mix_result,
        ) as remux:
            result = self.server._finalize_ai_comic_fallback_video_audio(task)

        self.assertIs(result, task)
        remux.assert_called_once_with(provider_url, tts_url, 293, 293001)
        self.assertEqual(task["result_url"], mix_result["url"])
        self.assertEqual(task["audio_source"], "storyboard_tts")
        self.assertEqual(task["audio_mix_status"], "completed")

    def test_matrix_primary_video_uses_task_source_mode_after_project_cache_miss(self):
        provider_url = "https://private.example/provider-result.mp4"
        tts_url = "https://private.example/tts.mp3"
        self.server.LOCAL_COMIC_PROJECTS = {}
        task = {
            "id": "ai-matrix-primary-cache-miss",
            "status": "completed",
            "state": "completed",
            "project_id": 293,
            "target_id": 293001,
            "target_type": "storyboard",
            "task_type": "generate_video",
            "result_url": provider_url,
            "project_source_mode": "matrix_video_replacement",
            "params": {"audio_mode": "tts", "sound_file": tts_url},
        }
        mix_result = {
            "url": "/data/uploads/comic-drama/matrix-cache-miss-remuxed.mp4",
            "video_duration_seconds": 5.0,
            "audio_duration_seconds": 5.0,
            "final_duration_seconds": 5.0,
        }

        with mock.patch.object(
                self.server,
                "_comic_remux_video_with_storyboard_tts",
                return_value=mix_result,
        ) as remux:
            result = self.server._finalize_ai_comic_fallback_video_audio(task)

        self.assertIs(result, task)
        remux.assert_called_once_with(provider_url, tts_url, 293, 293001)
        self.assertEqual(task["result_url"], mix_result["url"])
        self.assertEqual(task["audio_source"], "storyboard_tts")
        self.assertEqual(task["audio_mix_status"], "completed")

    def test_batch_storyboard_auto_fallback_preserves_provider_audio_without_remux(self):
        provider_url = "https://private.example/batch-provider-result.mp4"
        task = {
            "id": "ai-batch-fallback-auto",
            "status": "completed",
            "state": "completed",
            "project_id": 293,
            "target_id": 293001,
            "target_type": "storyboard",
            "task_type": "batch_storyboard_videos",
            "fallback_applied": True,
            "actual_model": "fallback-video-model",
            "result_url": provider_url,
            "fallback_source_params": {"audio_mode": "auto"},
        }

        with mock.patch.object(
                self.server,
                "_comic_remux_video_with_storyboard_tts",
                side_effect=AssertionError("batch auto must not remux"),
        ) as remux:
            result = self.server._finalize_ai_comic_fallback_video_audio(task)

        self.assertIs(result, task)
        remux.assert_not_called()
        self.assertEqual(task["result_url"], provider_url)
        self.assertEqual(task.get("audio_source"), "provider_generated")
        self.assertEqual(task.get("audioSource"), "provider_generated")
        self.assertEqual(task.get("audio_mix_status"), "not_requested")
        self.assertEqual(task.get("audioMixStatus"), "not_requested")

    def test_batch_storyboard_tts_and_legacy_fallback_keep_forced_remux(self):
        provider_url = "https://private.example/batch-provider-result.mp4"
        tts_url = "https://private.example/batch-tts.mp3"
        mix_result = {
            "url": "/data/uploads/comic-drama/batch-remuxed.mp4",
            "video_duration_seconds": 5.0,
            "audio_duration_seconds": 6.0,
            "final_duration_seconds": 6.0,
        }
        for audio_mode in ("tts", "legacy"):
            with self.subTest(audio_mode=audio_mode):
                source_params = {"sound_file": tts_url}
                if audio_mode == "tts":
                    source_params["audio_mode"] = "tts"
                task = {
                    "id": "ai-batch-fallback-%s" % audio_mode,
                    "status": "completed",
                    "state": "completed",
                    "project_id": 293,
                    "target_id": 293001,
                    "target_type": "storyboard",
                    "task_type": "batch_storyboard_videos",
                    "fallback_applied": True,
                    "actual_model": "fallback-video-model",
                    "result_url": provider_url,
                    "fallback_source_params": source_params,
                }

                with mock.patch.object(
                        self.server,
                        "_comic_remux_video_with_storyboard_tts",
                        return_value=mix_result,
                ) as remux:
                    result = self.server._finalize_ai_comic_fallback_video_audio(task)

                self.assertIs(result, task)
                remux.assert_called_once_with(provider_url, tts_url, 293, 293001)
                self.assertEqual(task["result_url"], mix_result["url"])
                self.assertEqual(task["audio_source"], "storyboard_tts")
                self.assertEqual(task["audio_mix_status"], "completed")

    def test_unrelated_batch_fallback_target_is_unchanged(self):
        task = {
            "id": "ai-batch-character-fallback",
            "target_type": "character",
            "task_type": "batch_character_videos",
            "fallback_applied": True,
            "result_url": "https://private.example/character.mp4",
            "fallback_source_params": {"audio_mode": "auto"},
        }
        original = copy.deepcopy(task)

        with mock.patch.object(
                self.server,
                "_comic_remux_video_with_storyboard_tts",
                side_effect=AssertionError("unrelated batch target must not remux"),
        ) as remux:
            result = self.server._finalize_ai_comic_fallback_video_audio(task)

        self.assertIs(result, task)
        self.assertEqual(task, original)
        remux.assert_not_called()

    def test_keyframe_subrequests_use_distinct_traceable_billing_ids(self):
        submitted_payloads = []

        def fake_urlopen(request, timeout=None):
            submitted_payloads.append(json.loads(request.data.decode("utf-8")))
            return _FakeResponse(f"task-{len(submitted_payloads)}")

        payload = {
            "workflow_mode": "keyframes",
            "quantity": 2,
            "model": "gpt-image-2-guan",
            "prompt": "shot prompt",
            "billingRequestId": "comic-project-293-storyboard-293001-attempt-1",
        }

        with mock.patch.object(self.server, "_comic_frame_image_model_error", return_value=""), \
                mock.patch.object(self.server, "_comic_storyboard_frame_prompt_source", return_value="shot prompt"), \
                mock.patch.object(self.server, "_comic_storyboard_image_frame_prompts", return_value=["start", "end"]), \
                mock.patch.object(self.server, "_platform_api_proxy_headers", return_value={}), \
                mock.patch.object(self.server.urllib.request, "urlopen", side_effect=fake_urlopen), \
                mock.patch.object(self.server, "_register_comic_frame_task_overlay"), \
                mock.patch.object(self.server, "_send_json_with_headers"), \
                mock.patch.object(self.server, "_comic_display_media_payload", side_effect=lambda value: value):
            handled = self.server._handle_comic_frame_generate_image_proxy(
                object(),
                "/api/v1/comic-drama/storyboards/293001/generate-image",
                "https://platform.example.test/generate-image",
                json.dumps(payload).encode("utf-8"),
                "keyframes",
            )

        self.assertTrue(handled)
        self.assertEqual(len(submitted_payloads), 2)
        billing_ids = [item["billingRequestId"] for item in submitted_payloads]
        self.assertNotEqual(billing_ids[0], billing_ids[1])
        self.assertTrue(billing_ids[0].startswith(payload["billingRequestId"]))
        self.assertTrue(billing_ids[1].startswith(payload["billingRequestId"]))
        self.assertTrue(billing_ids[0].endswith(":frame:1"))
        self.assertTrue(billing_ids[1].endswith(":frame:2"))

    def _submit_via_generic_proxy_without_explicit_workflow(self, payload, frame_prompts):
        submitted = []
        sent = []
        route = "/api/v1/comic-drama/storyboards/293001/generate-image"
        body = json.dumps(payload).encode("utf-8")
        handler = types.SimpleNamespace(path=route)

        def fake_urlopen(request, timeout=None):
            submitted.append(json.loads(request.data.decode("utf-8")))
            return _FakeResponse("task-%d" % len(submitted))

        with mock.patch.multiple(
                self.server,
                create=True,
                _platform_api_proxy_target=lambda path: path,
                _platform_url=lambda path: "https://platform.example.test%s" % path,
                _read_body=lambda _handler, max_bytes: body,
                _rewrite_comic_workflow_request=lambda path, method, value: (value, ""),
                _comic_storyboard_image_frame_prompts=lambda workflow, value, prompt: list(frame_prompts),
                _platform_api_proxy_headers=lambda *args, **kwargs: {},
                _register_comic_frame_task_overlay=lambda *args, **kwargs: None,
                _send_json_with_headers=lambda *args: sent.append(args),
                _comic_display_media_payload=lambda value: value,
        ), mock.patch.object(self.server.urllib.request, "urlopen", side_effect=fake_urlopen):
            handled = self.server._handle_platform_api_proxy(handler, route, "POST")
        return handled, submitted, sent

    def test_generic_proxy_quantity_two_without_workflow_submits_both_keyframes(self):
        handled, submitted, sent = self._submit_via_generic_proxy_without_explicit_workflow(
            {"quantity": 2, "prompt": "shot"},
            ["start", "end"],
        )

        self.assertTrue(handled)
        self.assertEqual([item["workflow_mode"] for item in submitted], ["keyframes", "keyframes"])
        self.assertEqual([item["frame_index"] for item in submitted], [1, 2])
        self.assertEqual([item["prompt"] for item in submitted], ["start", "end"])
        self.assertEqual([item["quantity"] for item in submitted], [1, 1])
        self.assertEqual(sent[-1][1], 200)
        self.assertEqual(sent[-1][2]["data"]["task_ids"], ["task-1", "task-2"])

    def test_generic_proxy_count_seven_without_workflow_submits_multiframe(self):
        prompts = ["frame-%d" % index for index in range(1, 8)]
        handled, submitted, sent = self._submit_via_generic_proxy_without_explicit_workflow(
            {"count": 7, "prompt": "shot"},
            prompts,
        )

        self.assertTrue(handled)
        self.assertEqual(len(submitted), 7)
        self.assertEqual([item["workflow_mode"] for item in submitted], ["multiframe"] * 7)
        self.assertEqual([item["frame_index"] for item in submitted], list(range(1, 8)))
        self.assertEqual([item["prompt"] for item in submitted], prompts)
        self.assertEqual([item["count"] for item in submitted], [1] * 7)
        self.assertEqual(sent[-1][1], 200)
        self.assertEqual(sent[-1][2]["data"]["task_ids"], [
            "task-%d" % index for index in range(1, 8)
        ])

    def _submit_keyframes(self, frame_index_marker, key="frameIndex", extra_payload=None):
        submitted = []
        sent = []
        payload = {
            "workflow_mode": "keyframes",
            "quantity": 2,
            "prompt": "shot",
            "billingRequestId": "comic-project-293-storyboard-293001-attempt-1",
        }
        if frame_index_marker is not None:
            payload[key] = frame_index_marker
        if isinstance(extra_payload, dict):
            payload.update(extra_payload)

        def fake_urlopen(request, timeout=None):
            submitted.append(json.loads(request.data.decode("utf-8")))
            return _FakeResponse("task-%d" % len(submitted))

        with mock.patch.object(self.server, "_comic_storyboard_image_frame_prompts", return_value=["start", "end"]), \
                mock.patch.object(self.server.urllib.request, "urlopen", side_effect=fake_urlopen), \
                mock.patch.object(self.server, "_send_json_with_headers", side_effect=lambda *args: sent.append(args)):
            self.server._handle_comic_frame_generate_image_proxy(
                object(), "/api/v1/comic-drama/storyboards/293001/generate-image",
                "https://platform.example.test/generate-image",
                json.dumps(payload).encode("utf-8"), "keyframes",
            )
        return submitted, sent

    def test_keyframes_without_frame_index_still_submit_both_frames(self):
        submitted, _sent = self._submit_keyframes(None)

        self.assertEqual([item["frame_index"] for item in submitted], [1, 2])

    def test_keyframes_frame_index_one_submits_only_start_frame(self):
        submitted, _sent = self._submit_keyframes(1)

        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0]["frame_index"], 1)
        self.assertEqual(submitted[0]["frameIndex"], 1)
        self.assertTrue(submitted[0]["billingRequestId"].endswith(":frame:1"))

    def test_keyframes_frame_index_two_submits_only_end_frame(self):
        submitted, _sent = self._submit_keyframes(2)

        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0]["frame_index"], 2)
        self.assertEqual(submitted[0]["frameIndex"], 2)
        self.assertTrue(submitted[0]["billingRequestId"].endswith(":frame:2"))

    def test_keyframes_frame_index_alias_submits_only_requested_frame(self):
        submitted, _sent = self._submit_keyframes(2, key="frame_index")

        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0]["frame_index"], 2)
        self.assertEqual(submitted[0]["frameIndex"], 2)

    def test_keyframes_equal_dual_aliases_submit_the_selected_frame_once(self):
        submitted, _sent = self._submit_keyframes(1, extra_payload={"frame_index": 1})

        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0]["frame_index"], 1)
        self.assertEqual(submitted[0]["frameIndex"], 1)

    def test_keyframes_invalid_frame_index_rejects_without_upstream_or_billing(self):
        for value in (3, 1.5, True):
            with self.subTest(value=value):
                submitted, sent = self._submit_keyframes(value)

                self.assertEqual(submitted, [])
                self.assertEqual(sent[-1][1], 400)
                self.assertIn("frameIndex", sent[-1][2]["detail"])

    def test_proxy_rejects_non_json_integer_before_prompt_expansion_or_submission(self):
        for key, value in (
                ("frameIndex", ""),
                ("frameIndex", "1"),
                ("frame_index", "1"),
                ("frameIndex", True),
                ("frameIndex", 1.5),
                ("frameIndex", 3),
        ):
            with self.subTest(key=key, value=value):
                submitted = []
                sent = []
                prompt_expansions = []
                payload = {
                    "workflow_mode": "keyframes",
                    "quantity": 2,
                    "prompt": "shot",
                }
                payload[key] = value

                def fake_urlopen(request, timeout=None):
                    submitted.append(request)
                    return _FakeResponse("unexpected-task")

                def unexpected_prompt_expansion(*args):
                    prompt_expansions.append(args)
                    return ["start", "end"]

                with mock.patch.object(self.server, "_comic_storyboard_image_frame_prompts", side_effect=unexpected_prompt_expansion), \
                        mock.patch.object(self.server.urllib.request, "urlopen", side_effect=fake_urlopen), \
                        mock.patch.object(self.server, "_send_json_with_headers", side_effect=lambda *args: sent.append(args)):
                    handled = self.server._handle_comic_frame_generate_image_proxy(
                        object(), "/api/v1/comic-drama/storyboards/293001/generate-image",
                        "https://platform.example.test/generate-image",
                        json.dumps(payload).encode("utf-8"), "keyframes",
                    )

                self.assertTrue(handled)
                self.assertEqual(prompt_expansions, [])
                self.assertEqual(submitted, [])
                self.assertEqual(sent[-1][1], 400)

    def test_proxy_rejects_invalid_frame_index_before_bad_prompt_split(self):
        sent = []
        payload = {"workflow_mode": "keyframes", "quantity": 2, "frameIndex": "1"}

        with mock.patch.object(self.server, "_comic_storyboard_image_frame_prompts", return_value=[]), \
                mock.patch.object(self.server, "_send_json_with_headers", side_effect=lambda *args: sent.append(args)):
            handled = self.server._handle_comic_frame_generate_image_proxy(
                object(), "/api/v1/comic-drama/storyboards/293001/generate-image",
                "https://platform.example.test/generate-image",
                json.dumps(payload).encode("utf-8"), "keyframes",
            )

        self.assertTrue(handled)
        self.assertEqual(sent[-1][1], 400)

    def test_proxy_rejects_frame_index_on_non_keyframes_before_generic_forwarding(self):
        sent = []
        payload = {"workflow_mode": "action_flow", "frameIndex": 1}

        with mock.patch.object(self.server, "_comic_storyboard_image_frame_prompts", side_effect=AssertionError("must not expand")), \
                mock.patch.object(self.server, "_send_json_with_headers", side_effect=lambda *args: sent.append(args)):
            handled = self.server._handle_comic_frame_generate_image_proxy(
                object(), "/api/v1/comic-drama/storyboards/293001/generate-image",
                "https://platform.example.test/generate-image",
                json.dumps(payload).encode("utf-8"), "action_flow",
            )

        self.assertTrue(handled)
        self.assertEqual(sent[-1][1], 400)

    def test_direct_single_storyboard_rejects_invalid_frame_index_before_expansion_or_submit(self):
        sent = []
        submitted = []
        expansions = []
        payload = {
            "project_id": 293,
            "workflow_mode": "keyframes",
            "prompt": "shot",
            "frameIndex": "1",
        }

        def expand(*args):
            expansions.append(args)
            return [{
                "model": "image-model",
                "prompt": "shot",
                "params": {},
                "count": 1,
                "project_id": 293,
                "task_type": "generate_image",
                "task_name": "shot",
                "target_id": 293001,
                "target_type": "storyboard",
                "_task_metadata": {"workflow_mode": "keyframes", "frame_index": 1},
            }]

        with mock.patch.multiple(
                self.server,
                create=True,
                _read_json_body_object=lambda handler: dict(payload),
                _ensure_subject_refs_in_media_payload=lambda value: value,
                _reject_missing_local_comic_target=lambda *args: False,
                _comic_project_for_generation=lambda *args: {"storyboards": []},
                _comic_media_model_for_project=lambda *args: "image-model",
                _local_comic_find_by_id=lambda *args: None,
                _comic_storyboard_workflow_mode=lambda project, request: request.get("workflow_mode"),
                _comic_storyboard_frame_prompt_source=lambda *args: "shot",
                _compose_local_comic_storyboard_prompt=lambda project, storyboard, prompt, media_kind: prompt,
                _ai_media_params_from_payload=lambda value: {},
                _reference_urls_from_payload=lambda value: [],
                _local_comic_storyboard_character_refs_for_prompt=lambda *args: ([], []),
                _dedupe_urls=lambda values: list(values),
                _local_comic_storyboard_reference_context=lambda *args: [],
                _local_comic_storyboard_typed_reference_context=lambda *args: {},
                _merge_reference_urls_into_params=lambda params, urls: dict(params),
                _apply_strict_storyboard_references_to_params=lambda params, refs: params,
                _with_character_binding_prompt=lambda prompt, names: prompt,
                _local_comic_storyboard_reference_binding_prompt=lambda *args: "",
                _ai_image_params_with_size=lambda params, request, target: params,
                _ai_comic_strengthen_reference_request=lambda model, prompt, params: (prompt, params),
                _comic_frame_image_model_or_default=lambda workflow, model: model,
                _comic_frame_image_model_error=lambda *args: "",
                _expand_comic_storyboard_image_submit_kwargs=expand,
                _submit_ai_comic_media_task=lambda **kwargs: submitted.append(kwargs) or {"id": "unexpected-task"},
                _apply_comic_frame_task_metadata=lambda task, workflow, index: task,
                _save_local_comic_state=lambda: None,
                _json_log=lambda *args, **kwargs: None,
                _send_json_with_headers=lambda *args: sent.append(args),
        ):
            handled = self.server._handle_ai_comic_api_request(
                object(), "/api/v1/comic-drama/storyboards/293001/generate-image", "POST",
            )

        self.assertTrue(handled)
        self.assertEqual(expansions, [])
        self.assertEqual(submitted, [])
        self.assertEqual(sent[-1][1], 400)

    def _submit_direct_storyboard_image_without_explicit_workflow(self, payload):
        sent = []
        submitted = []
        logs = []

        def fake_submit(**kwargs):
            submitted.append(kwargs)
            return {"id": "task-%d" % len(submitted)}

        with mock.patch.multiple(
                self.server,
                create=True,
                _read_json_body_object=lambda handler: dict(payload),
                _ensure_subject_refs_in_media_payload=lambda value: value,
                _reject_missing_local_comic_target=lambda *args: False,
                _comic_project_for_generation=lambda *args: {"storyboards": []},
                _comic_media_model_for_project=lambda *args: "image-model",
                _local_comic_find_by_id=lambda *args: None,
                _comic_storyboard_workflow_mode=lambda project, request: "",
                _comic_storyboard_frame_prompt_source=lambda *args: "shot",
                _comic_storyboard_image_frame_prompts=lambda *args: ["start", "end"],
                _compose_local_comic_storyboard_prompt=lambda project, storyboard, prompt, media_kind: prompt,
                _ai_media_params_from_payload=lambda value: {},
                _reference_urls_from_payload=lambda value: [],
                _local_comic_storyboard_character_refs_for_prompt=lambda *args: ([], []),
                _dedupe_urls=lambda values: list(values),
                _local_comic_storyboard_reference_context=lambda *args: [],
                _local_comic_storyboard_typed_reference_context=lambda *args: {},
                _merge_reference_urls_into_params=lambda params, urls: dict(params),
                _apply_strict_storyboard_references_to_params=lambda params, refs: params,
                _with_character_binding_prompt=lambda prompt, names: prompt,
                _local_comic_storyboard_reference_binding_prompt=lambda *args: "",
                _ai_image_params_with_size=lambda params, request, target: params,
                _ai_comic_strengthen_reference_request=lambda model, prompt, params: (prompt, params),
                _comic_frame_image_model_or_default=lambda workflow, model: model,
                _comic_frame_image_model_error=lambda *args: "",
                _submit_ai_comic_media_task=fake_submit,
                _apply_comic_frame_task_metadata=lambda task, workflow, index: task,
                _save_local_comic_state=lambda: None,
                _json_log=lambda *args, **kwargs: logs.append((args, kwargs)),
                _send_json_with_headers=lambda *args: sent.append(args),
        ):
            handled = self.server._handle_ai_comic_api_request(
                object(), "/api/v1/comic-drama/storyboards/293001/generate-image", "POST",
            )
        return handled, submitted, sent, logs

    def test_direct_quantity_two_infers_keyframes_and_submits_selected_frame(self):
        handled, submitted, sent, _logs = self._submit_direct_storyboard_image_without_explicit_workflow({
            "project_id": 293,
            "quantity": 2,
            "frameIndex": 1,
            "prompt": "shot",
        })

        self.assertTrue(handled)
        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0]["prompt"], "start")
        self.assertEqual(submitted[0]["count"], 1)
        self.assertEqual(sent[-1][1], 200)

    def test_direct_count_seven_infers_multiframe_and_rejects_frame_index_before_submit(self):
        handled, submitted, sent, logs = self._submit_direct_storyboard_image_without_explicit_workflow({
            "project_id": 293,
            "count": 7,
            "frameIndex": 1,
            "prompt": "shot",
        })

        self.assertTrue(handled)
        self.assertEqual(submitted, [])
        self.assertEqual(sent[-1][1], 400)
        self.assertEqual(logs[-1][1]["workflow_mode"], "multiframe")

    def test_direct_quantity_two_without_frame_index_submits_both_keyframes(self):
        handled, submitted, sent, _logs = self._submit_direct_storyboard_image_without_explicit_workflow({
            "project_id": 293,
            "quantity": 2,
            "prompt": "shot",
        })

        self.assertTrue(handled)
        self.assertEqual([item["prompt"] for item in submitted], ["start", "end"])
        self.assertEqual([item["count"] for item in submitted], [1, 1])
        self.assertEqual(sent[-1][1], 200)

    def test_direct_frame_index_validator_rejects_all_non_json_integer_inputs(self):
        for workflow_mode, key, value in (
                ("keyframes", "frameIndex", ""),
                ("keyframes", "frameIndex", "1"),
                ("keyframes", "frame_index", "1"),
                ("keyframes", "frameIndex", True),
                ("keyframes", "frameIndex", 1.5),
                ("keyframes", "frameIndex", 3),
                ("action_flow", "frameIndex", 1),
        ):
            with self.subTest(workflow_mode=workflow_mode, key=key, value=value):
                with self.assertRaisesRegex(ValueError, "frameIndex must be 1 or 2 for keyframes"):
                    self.server._comic_storyboard_requested_image_frame_index(
                        workflow_mode, {key: value},
                    )

    def test_direct_frame_index_validator_accepts_equal_dual_aliases_once(self):
        self.assertEqual(
            self.server._comic_storyboard_requested_image_frame_index(
                "keyframes", {"frameIndex": 2, "frame_index": 2},
            ),
            2,
        )

    def test_direct_frame_index_validator_rejects_conflicting_or_invalid_dual_aliases(self):
        for payload in (
                {"frameIndex": 1, "frame_index": 2},
                {"frameIndex": 1, "frame_index": "1"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "frameIndex must be 1 or 2 for keyframes"):
                    self.server._comic_storyboard_requested_image_frame_index("keyframes", payload)

    def test_proxy_rejects_conflicting_or_invalid_dual_aliases_before_submission(self):
        for extra_payload in ({"frame_index": 2}, {"frame_index": "1"}):
            with self.subTest(extra_payload=extra_payload):
                submitted, sent = self._submit_keyframes(1, extra_payload=extra_payload)

                self.assertEqual(submitted, [])
                self.assertEqual(sent[-1][1], 400)

    def test_batch_frame_index_is_removed_before_keyframe_expansion(self):
        payload = {"workflow_mode": "keyframes", "frameIndex": 1, "frame_index": 2}
        base_kwargs = {"params": {}, "task_name": "batch", "_frame_prompt_source": "shot"}

        with mock.patch.object(self.server, "_comic_storyboard_image_frame_prompts", return_value=["start", "end"]):
            batch_payload = self.server._comic_storyboard_batch_payload(payload)
            expanded = self.server._expand_comic_storyboard_image_submit_kwargs(
                base_kwargs, "keyframes", batch_payload, "shot",
            )

        self.assertNotIn("frameIndex", batch_payload)
        self.assertNotIn("frame_index", batch_payload)
        self.assertEqual([item["_task_metadata"]["frame_index"] for item in expanded], [1, 2])

    def test_colored_pencil_keyframes_do_not_inject_realistic_reference_lock(self):
        payload = {
            "workflow_mode": "keyframes",
            "frame_style_mode": "colored_pencil",
        }
        base_kwargs = {
            "params": {
                "_strict_typed_reference_bundle": {
                    "all": ["https://media.example/person.png"],
                    "characters": ["https://media.example/person.png"],
                },
            },
            "task_name": "batch",
            "_frame_prompt_source": "shot",
        }

        with mock.patch.object(
            self.server,
            "_comic_storyboard_image_frame_prompts",
            return_value=["彩铅手绘风格首帧", "彩铅手绘风格尾帧"],
        ), mock.patch.object(
            self.server,
            "_apply_strict_storyboard_references_to_params",
            side_effect=lambda params, _refs: dict(params),
        ):
            expanded = self.server._expand_comic_storyboard_image_submit_kwargs(
                base_kwargs, "keyframes", payload, "shot",
            )

        self.assertEqual(len(expanded), 2)
        for item in expanded:
            prompt = item["prompt"]
            self.assertIn("彩铅", prompt)
            self.assertIn("手绘", prompt)
            self.assertNotIn("禁止动漫", prompt)
            self.assertNotIn("禁止手绘", prompt)

    def test_local_overlay_updates_only_selected_keyframe(self):
        payload = {
            "storyboards": [{
                "id": 293001,
                "start_frame_url": "https://media.example/start-old.png",
                "end_frame_url": "https://media.example/end-old.png",
                "generatedImages": ["https://media.example/start-old.png", "https://media.example/end-old.png"],
            }],
        }
        overlays = {
            "task-end": {
                "storyboard_id": "293001",
                "workflow_mode": "keyframes",
                "frame_index": 2,
                "result_url": "https://media.example/end-new.png",
            },
        }

        with mock.patch.object(self.server, "_load_comic_frame_task_overlays", return_value=overlays):
            updated = self.server._apply_comic_frame_task_overlays(payload)

        storyboard = updated["storyboards"][0]
        self.assertEqual(storyboard["start_frame_url"], "https://media.example/start-old.png")
        self.assertEqual(storyboard["end_frame_url"], "https://media.example/end-new.png")
        self.assertEqual(storyboard["generatedImages"], ["https://media.example/start-old.png", "https://media.example/end-new.png"])


if __name__ == "__main__":
    unittest.main()
