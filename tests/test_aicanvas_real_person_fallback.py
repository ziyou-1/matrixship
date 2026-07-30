from pathlib import Path
import ast
import copy
import datetime
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / ".tmp-aicanvas-server-current.py"
PRIVACY_ERROR = (
    "InputImageSensitiveContentDetected.PrivacyInformation: "
    "The request failed because the input image may contain real person."
)
AUDIO_DURATION_ERROR = (
    "ark 400 Bad Request: {\"error\":{\"code\":\"InvalidParameter\","
    "\"message\":\"The parameter audio duration (seconds) specified in the request "
    "must be less than or equal to 15.2 for model doubao-seedance-2-0 in r2v.\"}}"
)
POLICY_VIOLATION_ERROR = (
    "ark 400 Bad Request: {\"error\":{\"code\":"
    "\"InputImageSensitiveContentDetected.PolicyViolation\","
    "\"message\":\"The request failed because the input image 'content[1]' 'content[3]' "
    "'content[5]' may be related to copyright restriction.\"}}"
)


class _AiApiServiceStub:
    @staticmethod
    def sanitize_error(value):
        return str(value)

    @staticmethod
    def submit_media_task(model, prompt, params=None, count=1):
        return {"task_id": "image-task"}


def load_server(ark_error=PRIVACY_ERROR, gateway_error="", gateway_outcomes=None, status_payload=None):
    source = SERVER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SERVER))
    names = {
        "_ai_comic_task_response",
        "_is_ark_real_person_privacy_error",
        "_ark_storyboard_video_fallback_reason",
        "_comic_real_person_video_fallback_model",
        "_comic_real_person_video_fallback_models",
        "_comic_video_fallback_params",
        "_advance_ai_comic_video_fallback",
        "_comic_storyboard_tts_url_from_task",
        "_comic_remux_video_with_storyboard_tts",
        "_finalize_ai_comic_fallback_video_audio",
        "_refresh_ai_comic_task",
        "_submit_ai_comic_media_task",
    }
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = types.ModuleType("aicanvas_real_person_fallback_under_test")
    gateway_calls = []
    charges = []
    refunds = []
    logs = []

    def register_task(**kwargs):
        task = {
            "id": "ai-%s" % kwargs["remote_task_id"],
            "status": "pending",
            "model": kwargs["model"],
            "params": copy.deepcopy(kwargs.get("params") or {}),
            "billing_request_id": (kwargs.get("billing_ctx") or {}).get("request_id", ""),
        }
        ai_tasks[task["id"]] = task
        local_tasks[task["id"]] = task
        return task

    def register_failed(**kwargs):
        task = {
            "id": "ai-failed-test",
            "status": "failed",
            "model": kwargs["model"],
            "error_message": str(kwargs.get("message") or ""),
            "current_step": str(kwargs.get("message") or ""),
            "params": copy.deepcopy(kwargs.get("params") or {}),
        }
        ai_tasks[task["id"]] = task
        local_tasks[task["id"]] = task
        return task

    gateway_outcomes = dict(gateway_outcomes or {})

    def gateway_submit(model, prompt, params=None, count=1):
        gateway_calls.append({
            "model": model,
            "prompt": prompt,
            "params": copy.deepcopy(params or {}),
            "count": count,
        })
        outcome = gateway_outcomes.get(model)
        if isinstance(outcome, list):
            outcome = outcome.pop(0) if outcome else None
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, dict):
            return outcome
        if gateway_error:
            raise RuntimeError(gateway_error)
        return {"task_id": "gateway-task-%d" % len(gateway_calls)}

    def charge(model_type, model, payload, **kwargs):
        context = {"request_id": "charge-%d-%s" % (len(charges) + 1, model)}
        charges.append({"model_type": model_type, "model": model, "payload": copy.deepcopy(payload), "context": context})
        return context

    ai_tasks = {}
    local_tasks = {}

    def fail_task(task, message):
        request_id = str(task.get("billing_request_id") or "")
        if request_id:
            refunds.append({"context": {"request_id": request_id}, "reason": str(message)})
        task.update({"status": "failed", "state": "failed", "error_message": str(message)})
        return task

    ai_api_service = _AiApiServiceStub()
    ai_api_service.get_task_status = lambda remote_task_id: copy.deepcopy(
        status_payload or {"state": "running", "status": "running"}
    )
    module.__dict__.update({
        "copy": copy,
        "datetime": datetime,
        "os": os,
        "re": re,
        "sys": sys,
        "time": time,
        "secrets": secrets,
        "shutil": shutil,
        "subprocess": subprocess,
        "tempfile": tempfile,
        "AI_API_SERVICE": ai_api_service,
        "AiApiService": _AiApiServiceStub,
        "LOCAL_COMIC_PROJECTS": {},
        "AI_COMIC_TASKS": ai_tasks,
        "LOCAL_COMIC_TASKS": local_tasks,
        "COMIC_REAL_PERSON_VIDEO_FALLBACK_MODELS": (
            "vidu/viduq3-mix_reference2video",
            "wan2.7-shouweizhen",
            "kling-v3-omni-shouweizhen",
            "pixverse-v6-shouweizhen",
        ),
        "_comic_truthy": bool,
        "_first_non_empty": lambda *values: next((value for value in values if value not in (None, "")), ""),
        "_fallback_ai_comic_task_result_url": lambda task: "",
        "_is_local_comic_analysis_task": lambda task: False,
        "_is_local_comic_auto_edit_task": lambda task: False,
        "_ai_comic_task_project_result_needs_sync": lambda task: False,
        "_ai_comic_remote_id": lambda task: str(task.get("remote_task_id") or ""),
        "_ai_comic_task_recently_refreshed": lambda task, now_ts=None: False,
        "AI_COMIC_TASK_REFRESH_LOCK": mock.MagicMock(
            __enter__=lambda self: self,
            __exit__=lambda self, *args: None,
        ),
        "AI_COMIC_TASK_REFRESH_IN_FLIGHT": set(),
        "ARK_TASK_ID_PREFIX": "ark:",
        "FFMPEG_EXE": "ffmpeg",
        "_current_uploads_dir": lambda: "",
        "_local_comic_auto_edit_resolve_source": lambda value: value,
        "_local_comic_auto_edit_probe": lambda value: {"duration": 0.0, "has_audio": False},
        "_normalize_ai_task_status": lambda payload: (
            ("failed", 100)
            if str(payload.get("state") or payload.get("status") or "").lower() in {"failed", "error"}
            else (
                ("completed", 100)
                if str(payload.get("state") or payload.get("status") or "").lower() in {"success", "completed"}
                else ("running", 10)
            )
        ),
        "_extract_ai_result_url": lambda payload: str(payload.get("result_url") or ""),
        "_ai_comic_task_has_applyable_result": lambda task: bool(
            str(task.get("result_url") or "").strip()
            and str(task.get("status") or "").strip().lower() not in {"failed", "cancelled", "canceled"}
        ),
        "_ai_comic_task_is_stale": lambda task: False,
        "_local_comic_billing_amount": lambda task: 0,
        "_aic_looks_like_image_url": lambda url: False,
        "_comic_display_task_step": lambda step: str(step or ""),
        "_normalize_video_size_keys": lambda value: dict(value or {}),
        "_truncate_comic_video_submit_prompt": lambda prompt, limit: prompt,
        "_comic_video_submit_prompt_limit": lambda model: 2000,
        "_comic_storyboard_workflow_mode": lambda project, params: params.get("workflow_mode", "keyframes"),
        "_local_comic_project_for_current_scope": lambda project_id: None,
        "_find_recent_duplicate_character_task": lambda *args, **kwargs: None,
        "_find_recent_duplicate_storyboard_video_task": lambda *args, **kwargs: None,
        "_charge_local_ai_model_call": charge,
        "_ark_should_route": lambda model: str(model).startswith("doubao-seedance"),
        "_comic_collect_video_reference_urls": lambda data: (
            list(data.get("action_flow_images") or []),
            list(data.get("additional_reference_images") or []),
            list(data.get("images") or []),
        ),
        "_dedupe_urls": lambda values: list(dict.fromkeys(values)),
        "_ark_create_video": lambda data: (_ for _ in ()).throw(RuntimeError(ark_error)),
        "_submit_comic_gateway_video_task": gateway_submit,
        "_refund_canvas_model_call": lambda context, reason: refunds.append({"context": context, "reason": reason}),
        "_register_ai_comic_failed_task": register_failed,
        "_register_ai_comic_task": register_task,
        "_ai_comic_fail_task": fail_task,
        "_save_local_comic_state": lambda: None,
        "_json_log": lambda event, **fields: logs.append({"event": event, **fields}),
    })
    ast.fix_missing_locations(tree)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SERVER), "exec"), module.__dict__)
    module.gateway_calls = gateway_calls
    module.charges = charges
    module.refunds = refunds
    module.logs = logs
    return module


class AICanvasRealPersonFallbackTest(unittest.TestCase):
    def _submit(self, module):
        return module._submit_ai_comic_media_task(
            model="doubao-seedance-2-0-260128",
            prompt="主播展示产品并朗读完整台词",
            params={
                "images": [
                    "https://assets.example/first-frame.png",
                    "https://assets.example/end-frame.png",
                    "https://assets.example/character.png",
                ],
                "first_frame_image": "https://assets.example/first-frame.png",
                "last_frame_image": "https://assets.example/end-frame.png",
                "sound_file": "https://assets.example/dialogue.mp3",
                "audio_file": "https://assets.example/dialogue.mp3",
                "reference_audio_file": "https://assets.example/dialogue.mp3",
                "lip_sync_required": True,
                "workflow_mode": "keyframes",
            },
            count=1,
            project_id=294,
            task_type="generate_video",
            task_name="分镜视频",
            target_id=294001,
            target_type="storyboard",
        )

    def test_exact_ark_privacy_error_falls_back_to_vidu_first(self):
        module = load_server()

        task = self._submit(module)

        self.assertEqual(len(module.gateway_calls), 1)
        fallback = module.gateway_calls[0]
        self.assertEqual(fallback["model"], "vidu/viduq3-mix_reference2video")
        self.assertEqual(fallback["params"]["first_frame_image"], "https://assets.example/first-frame.png")
        self.assertNotIn("sound_file", fallback["params"])
        self.assertNotIn("audio_file", fallback["params"])
        self.assertNotIn("reference_audio_file", fallback["params"])
        self.assertNotIn("lip_sync_required", fallback["params"])
        self.assertEqual([item["model"] for item in module.charges], [
            "doubao-seedance-2-0-260128",
            "vidu/viduq3-mix_reference2video",
        ])
        self.assertEqual(len(module.refunds), 1)
        self.assertEqual(task["requested_model"], "doubao-seedance-2-0-260128")
        self.assertEqual(task["actual_model"], "vidu/viduq3-mix_reference2video")
        self.assertEqual(task["fallback_model"], "vidu/viduq3-mix_reference2video")
        self.assertEqual(task["fallback_reason"], "InputImageSensitiveContentDetected.PrivacyInformation")
        self.assertTrue(task["fallback_applied"])
        response = module._ai_comic_task_response(task)
        self.assertEqual(response["requested_model"], "doubao-seedance-2-0-260128")
        self.assertEqual(response["actualModel"], "vidu/viduq3-mix_reference2video")
        self.assertEqual(response["fallback_reason"], "InputImageSensitiveContentDetected.PrivacyInformation")
        self.assertTrue(response["fallbackApplied"])
        self.assertEqual(response["fallback_candidates"], list(module.COMIC_REAL_PERSON_VIDEO_FALLBACK_MODELS))
        self.assertEqual(response["fallbackIndex"], 0)
        self.assertEqual(response["fallback_history"][-1]["model"], "vidu/viduq3-mix_reference2video")

    def test_privacy_rejection_falls_back_through_models_in_order(self):
        module = load_server(gateway_outcomes={
            "vidu/viduq3-mix_reference2video": RuntimeError("Vidu rejected"),
            "wan2.7-shouweizhen": RuntimeError("Wan rejected"),
            "kling-v3-omni-shouweizhen": RuntimeError("Kling rejected"),
            "pixverse-v6-shouweizhen": {"task_id": "pixverse-task"},
        })

        task = self._submit(module)

        self.assertEqual([item["model"] for item in module.gateway_calls], [
            "vidu/viduq3-mix_reference2video",
            "wan2.7-shouweizhen",
            "kling-v3-omni-shouweizhen",
            "pixverse-v6-shouweizhen",
        ])
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["actual_model"], "pixverse-v6-shouweizhen")
        self.assertEqual(task["fallback_index"], 3)
        self.assertEqual([item["model"] for item in task["fallback_history"]], [
            "doubao-seedance-2-0-260128",
            "vidu/viduq3-mix_reference2video",
            "wan2.7-shouweizhen",
            "kling-v3-omni-shouweizhen",
            "pixverse-v6-shouweizhen",
        ])
        self.assertEqual(len(module.refunds), 4)

    def test_seedance_audio_duration_limit_falls_back_to_vidu(self):
        module = load_server(AUDIO_DURATION_ERROR)

        task = self._submit(module)

        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["requested_model"], "doubao-seedance-2-0-260128")
        self.assertEqual(task["actual_model"], "vidu/viduq3-mix_reference2video")
        self.assertEqual(task["fallback_reason"], "InvalidParameter.AudioDurationExceeded")
        self.assertEqual([item["model"] for item in module.gateway_calls], [
            "vidu/viduq3-mix_reference2video",
        ])

    def test_seedance_policy_violation_falls_back_to_vidu(self):
        module = load_server(POLICY_VIOLATION_ERROR)

        task = self._submit(module)

        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["requested_model"], "doubao-seedance-2-0-260128")
        self.assertEqual(task["actual_model"], "vidu/viduq3-mix_reference2video")
        self.assertEqual(task["fallback_reason"], "InputImageSensitiveContentDetected.PolicyViolation")
        self.assertEqual([item["model"] for item in module.gateway_calls], [
            "vidu/viduq3-mix_reference2video",
        ])
        self.assertNotIn("sound_file", module.gateway_calls[0]["params"])
        self.assertEqual(len(module.refunds), 1)

    def test_first_last_frame_fallback_models_drop_audio_and_extra_images(self):
        module = load_server()
        original = {
            "images": ["first.png", "end.png", "character.png", "scene.png"],
            "first_frame_image": "first.png",
            "last_frame_image": "end.png",
            "sound_file": "dialogue.mp3",
            "audio_file": "dialogue.mp3",
            "reference_audio_file": "dialogue.mp3",
            "lip_sync_required": True,
        }

        for model in (
            "wan2.7-shouweizhen",
            "kling-v3-omni-shouweizhen",
            "pixverse-v6-shouweizhen",
        ):
            params = module._comic_video_fallback_params(model, original)
            self.assertEqual(params["images"], ["first.png", "end.png"])
            self.assertEqual(params["first_frame_image"], "first.png")
            self.assertEqual(params["last_frame_image"], "end.png")
            self.assertNotIn("sound_file", params)
            self.assertNotIn("audio_file", params)
            self.assertNotIn("reference_audio_file", params)
            self.assertNotIn("lip_sync_required", params)

    def test_accepted_fallback_task_advances_in_place_after_remote_failure(self):
        module = load_server()
        task = {
            "id": "ai-original-task",
            "remote_task_id": "vidu-task",
            "status": "running",
            "state": "running",
            "model": "vidu/viduq3-mix_reference2video",
            "requested_model": "doubao-seedance-2-0-260128",
            "actual_model": "vidu/viduq3-mix_reference2video",
            "fallback_candidates": list(module.COMIC_REAL_PERSON_VIDEO_FALLBACK_MODELS),
            "fallback_index": 0,
            "fallback_source_params": {"images": ["first.png", "end.png"]},
            "fallback_history": [],
            "project_id": 294,
            "target_id": 294001,
            "target_type": "storyboard",
            "task_type": "generate_video",
            "task_name": "storyboard video",
            "prompt": "test prompt",
            "count": 1,
            "billing_request_id": "charge-vidu",
        }
        module.AI_COMIC_TASKS[task["id"]] = task
        module.LOCAL_COMIC_TASKS[task["id"]] = task

        advanced = module._advance_ai_comic_video_fallback(task, "Vidu remote task failed")

        self.assertIs(advanced, task)
        self.assertEqual(task["id"], "ai-original-task")
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["actual_model"], "wan2.7-shouweizhen")
        self.assertEqual(task["fallback_index"], 1)
        self.assertEqual(module.gateway_calls[-1]["model"], "wan2.7-shouweizhen")

    def test_refresh_remote_failure_advances_fallback_without_changing_local_task_id(self):
        module = load_server(status_payload={
            "state": "failed",
            "status": "failed",
            "error": "Vidu remote task failed",
        })
        task = {
            "id": "ai-original-task",
            "remote_task_id": "vidu-task",
            "status": "running",
            "state": "running",
            "model": "vidu/viduq3-mix_reference2video",
            "requested_model": "doubao-seedance-2-0-260128",
            "actual_model": "vidu/viduq3-mix_reference2video",
            "fallback_reason": "InputImageSensitiveContentDetected.PrivacyInformation",
            "fallback_candidates": list(module.COMIC_REAL_PERSON_VIDEO_FALLBACK_MODELS),
            "fallback_index": 0,
            "fallback_source_params": {"images": ["first.png", "end.png"]},
            "fallback_history": [{"model": "vidu/viduq3-mix_reference2video", "status": "submitted"}],
            "project_id": 294,
            "target_id": 294001,
            "target_type": "storyboard",
            "task_type": "generate_video",
            "task_name": "storyboard video",
            "prompt": "test prompt",
            "count": 1,
            "billing_request_id": "charge-vidu",
        }
        module.AI_COMIC_TASKS[task["id"]] = task
        module.LOCAL_COMIC_TASKS[task["id"]] = task

        refreshed = module._refresh_ai_comic_task(task)

        self.assertIs(refreshed, task)
        self.assertEqual(task["id"], "ai-original-task")
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["actual_model"], "wan2.7-shouweizhen")
        self.assertEqual(task["fallback_index"], 1)
        self.assertEqual(module.gateway_calls[-1]["model"], "wan2.7-shouweizhen")

    def test_unrelated_ark_error_does_not_fallback(self):
        module = load_server("InvalidParameter: resolution is invalid")

        task = self._submit(module)

        self.assertEqual(task["status"], "failed")
        self.assertEqual(module.gateway_calls, [])
        self.assertEqual(len(module.charges), 1)
        self.assertEqual(len(module.refunds), 1)

    def test_empty_fallback_environment_disables_retry(self):
        module = load_server()

        with mock.patch.dict(os.environ, {"COMIC_REAL_PERSON_VIDEO_FALLBACK_MODELS": ""}):
            task = self._submit(module)

        self.assertEqual(task["status"], "failed")
        self.assertEqual(module.gateway_calls, [])
        self.assertEqual(len(module.charges), 1)
        self.assertEqual(len(module.refunds), 1)

    def test_fallback_task_keeps_storyboard_tts_source_for_post_mix(self):
        module = load_server()
        task = self._submit(module)

        self.assertEqual(
            module._comic_storyboard_tts_url_from_task(task),
            "https://assets.example/dialogue.mp3",
        )

    def test_fallback_post_mix_freezes_last_frame_when_tts_is_longer(self):
        module = load_server()
        run_calls = []

        def fake_probe(source):
            if str(source).endswith("dialogue.mp3"):
                return {"duration": 8.0, "has_audio": True}
            if str(source).endswith("model-video.mp4"):
                return {"duration": 5.0, "has_audio": True}
            return {"duration": 8.0, "has_audio": True}

        def fake_run(cmd, **kwargs):
            run_calls.append(list(cmd))
            Path(cmd[-1]).write_bytes(b"remuxed")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(module, "_current_uploads_dir", return_value=temp_dir), \
                mock.patch.object(module, "_local_comic_auto_edit_resolve_source", side_effect=lambda value: value), \
                mock.patch.object(module, "_local_comic_auto_edit_probe", side_effect=fake_probe), \
                mock.patch.object(module.subprocess, "run", side_effect=fake_run):
            result = module._comic_remux_video_with_storyboard_tts(
                "https://assets.example/model-video.mp4",
                "https://assets.example/dialogue.mp3",
                299,
                299002,
            )

        self.assertEqual(result["video_duration_seconds"], 5.0)
        self.assertEqual(result["audio_duration_seconds"], 8.0)
        self.assertEqual(result["final_duration_seconds"], 8.0)
        self.assertTrue(result["url"].startswith("/data/uploads/comic-drama/"))
        command = run_calls[0]
        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn("tpad=stop_mode=clone:stop_duration=3.000", filter_graph)
        self.assertIn("apad=pad_dur=0.000", filter_graph)
        self.assertIn("[0:v:0]", filter_graph)
        self.assertIn("[1:a:0]", filter_graph)
        self.assertNotIn("0:a:0", command)

    def test_fallback_post_mix_pads_silence_when_video_is_longer(self):
        module = load_server()
        run_calls = []

        def fake_probe(source):
            if str(source).endswith("dialogue.mp3"):
                return {"duration": 5.0, "has_audio": True}
            return {"duration": 8.0, "has_audio": True}

        def fake_run(cmd, **kwargs):
            run_calls.append(list(cmd))
            Path(cmd[-1]).write_bytes(b"remuxed")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(module, "_current_uploads_dir", return_value=temp_dir), \
                mock.patch.object(module, "_local_comic_auto_edit_resolve_source", side_effect=lambda value: value), \
                mock.patch.object(module, "_local_comic_auto_edit_probe", side_effect=fake_probe), \
                mock.patch.object(module.subprocess, "run", side_effect=fake_run):
            result = module._comic_remux_video_with_storyboard_tts(
                "https://assets.example/model-video.mp4",
                "https://assets.example/dialogue.mp3",
                299,
                299002,
            )

        self.assertEqual(result["final_duration_seconds"], 8.0)
        filter_graph = run_calls[0][run_calls[0].index("-filter_complex") + 1]
        self.assertIn("tpad=stop_mode=clone:stop_duration=0.000", filter_graph)
        self.assertIn("apad=pad_dur=3.000", filter_graph)

    def test_completed_fallback_replaces_provider_result_with_storyboard_tts_mix(self):
        module = load_server()
        task = {
            "id": "ai-fallback-completed",
            "status": "completed",
            "state": "completed",
            "project_id": 299,
            "target_id": 299002,
            "target_type": "storyboard",
            "task_type": "generate_video",
            "fallback_applied": True,
            "actual_model": "vidu/viduq3-mix_reference2video",
            "result_url": "https://assets.example/model-video.mp4",
            "fallback_source_params": {"sound_file": "https://assets.example/dialogue.mp3"},
        }
        mix_result = {
            "url": "/data/uploads/comic-drama/storyboard_299002_tts.mp4",
            "video_duration_seconds": 5.0,
            "audio_duration_seconds": 8.0,
            "final_duration_seconds": 8.0,
        }

        with mock.patch.object(
            module,
            "_comic_remux_video_with_storyboard_tts",
            return_value=mix_result,
        ) as remux:
            result = module._finalize_ai_comic_fallback_video_audio(task)

        self.assertIs(result, task)
        remux.assert_called_once_with(
            "https://assets.example/model-video.mp4",
            "https://assets.example/dialogue.mp3",
            299,
            299002,
        )
        self.assertEqual(task["provider_result_url"], "https://assets.example/model-video.mp4")
        self.assertEqual(task["result_url"], mix_result["url"])
        self.assertEqual(task["audio_source"], "storyboard_tts")
        self.assertEqual(task["audioSource"], "storyboard_tts")
        self.assertEqual(task["audio_mix_status"], "completed")

    def test_completed_fallback_fails_instead_of_using_provider_audio_when_mix_fails(self):
        module = load_server(status_payload={
            "state": "completed",
            "status": "completed",
            "result_url": "https://assets.example/model-video.mp4",
        })
        task = {
            "id": "ai-fallback-completed",
            "remote_task_id": "vidu-task",
            "status": "running",
            "state": "running",
            "project_id": 299,
            "target_id": 299002,
            "target_type": "storyboard",
            "task_type": "generate_video",
            "fallback_applied": True,
            "actual_model": "vidu/viduq3-mix_reference2video",
            "fallback_source_params": {"sound_file": "https://assets.example/dialogue.mp3"},
        }

        with mock.patch.object(
            module,
            "_finalize_ai_comic_fallback_video_audio",
            side_effect=RuntimeError("ffmpeg mix failed"),
        ):
            result = module._refresh_ai_comic_task(task)

        self.assertIs(result, task)
        self.assertEqual(task["status"], "failed")
        self.assertIn("ffmpeg mix failed", task["error_message"])
        self.assertNotEqual(task.get("project_result_applied"), True)


if __name__ == "__main__":
    unittest.main()
