import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SERVER_PATH = ROOT / "tools" / "aicanvas_remote" / "server_current.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_remote_server():
    install_remote_dependency_stubs()
    test_root = Path(tempfile.mkdtemp(prefix="aicanvas-h3-test-"))
    for key, suffix in {
        "LOCALAPPDATA": "local-app-data",
        "AIC_USER_DIR": "user",
        "AIC_CANVAS_DIR": "user/Canvas Project",
        "AIC_OUTPUT_DIR": "output",
        "AIC_DATA_DIR": "data",
        "AIC_ACCOUNT_STORAGE_ROOT": "accounts",
        "AICANVAS_ACCOUNT_STORAGE_ROOT": "accounts",
    }.items():
        value = str(test_root / suffix)
        if key == "LOCALAPPDATA":
            sys.modules.setdefault("_aicanvas_h3_temp_root", types.SimpleNamespace(path=test_root))
        import os
        os.environ[key] = value
    spec = importlib.util.spec_from_file_location(
        "aicanvas_remote_server_current_test", SERVER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_remote_dependency_stubs():
    services = types.ModuleType("backend.services")
    services.__path__ = []
    sys.modules.setdefault("backend.services", services)

    service_classes = {
        "backend.services.hot_update_service": "HotUpdateService",
        "backend.services.http_route_dispatcher": "HttpRouteDispatcher",
        "backend.services.json_file_route_service": "JsonFileRouteService",
        "backend.services.library_file_route_service": "LibraryFileRouteService",
        "backend.services.media_file_route_service": "MediaFileRouteService",
        "backend.services.local_media_processing_route_service": "LocalMediaProcessingRouteService",
        "backend.services.remote_proxy_route_service": "RemoteProxyRouteService",
        "backend.services.subscription_gate_service": "SubscriptionGateService",
        "backend.services.subscription_client": "SubscriptionRemoteClient",
        "backend.services.dreamina_cli_service": "DreaminaCliService",
        "backend.services.dreamina_route_service": "DreaminaRouteService",
        "backend.services.comic_readiness_service": "ComicReadinessService",
        "backend.services.agent_template_service": "AgentTemplateService",
        "backend.services.agent_task_service": "AgentTaskService",
        "backend.services.agent_orchestration_service": "AgentOrchestrationService",
    }
    for module_name, class_name in service_classes.items():
        module = types.ModuleType(module_name)
        setattr(module, class_name, type(class_name, (), {"__init__": lambda self, *a, **k: None}))
        sys.modules.setdefault(module_name, module)

    config_module = types.ModuleType("backend.services.config_route_service")
    config_module.ConfigRouteService = type("ConfigRouteService", (), {"__init__": lambda self, *a, **k: None})
    config_module.API_KEY_PLACEHOLDER = "__API_KEY_PLACEHOLDER__"
    sys.modules.setdefault("backend.services.config_route_service", config_module)

    prompt_module = types.ModuleType("backend.services.comic_storyboard_prompt_service")
    prompt_module._apply_ai_comic_task_result_to_project = lambda *a, **k: None
    prompt_module._keyframe_prompts = lambda *a, **k: []
    prompt_module._local_comic_storyboard_reference_binding_prompt = lambda *a, **k: ""
    prompt_module._seven_frame_prompts = lambda *a, **k: []
    sys.modules.setdefault("backend.services.comic_storyboard_prompt_service", prompt_module)

    ai_module = types.ModuleType("backend.services.ai_api_service")

    class StubAiApiService:
        @staticmethod
        def sanitize_error(value):
            return str(value or "")

        def __init__(self, *args, **kwargs):
            pass

    ai_module.AiApiService = StubAiApiService
    ai_module.DEFAULT_MODEL_BY_KIND = {}
    sys.modules.setdefault("backend.services.ai_api_service", ai_module)

    matrix_sso = types.ModuleType("matrix_sso")
    matrix_sso.MatrixSsoError = RuntimeError
    matrix_sso.verify_ticket = lambda *a, **k: {}
    sys.modules.setdefault("matrix_sso", matrix_sso)


class MiniMaxH3RemoteComicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.remote = load_remote_server()

    def test_catalog_exposes_minimax_h3_as_direct_video_model(self):
        videos = self.remote.COMIC_LOCAL_MODEL_CATALOG["video"]
        h3 = next((item for item in videos if item.get("id") == "minimax-h3"), None)

        self.assertIsNotNone(h3)
        self.assertEqual(h3["provider"], "minimax-direct")
        self.assertEqual(h3["actual_model"], "MiniMax-H3")
        self.assertEqual(h3["supported_resolutions"], ["768P", "2K"])
        self.assertEqual(h3["duration_range"], [4, 15])
        self.assertEqual(
            self.remote._comic_adapter_for_model("video", "minimax-h3"),
            "minimax-h3-video",
        )

    def test_storyboard_video_submits_h3_direct_without_gateway_or_precharge(self):
        calls = []

        def fake_json_request(method, path, payload=None, timeout=60):
            calls.append(
                {
                    "method": method,
                    "path": path,
                    "payload": payload,
                    "timeout": timeout,
                }
            )
            return {"task_id": "h3-provider-task"}

        with patch.object(self.remote, "MINIMAX_ENABLED", True, create=True):
            with patch.object(self.remote, "MINIMAX_COMIC_API_KEY", "comic-key", create=True):
                with patch.object(
                    self.remote,
                    "_minimax_h3_json_request",
                    side_effect=fake_json_request,
                    create=True,
                ):
                    with patch.object(
                        self.remote,
                        "_charge_local_ai_model_call",
                        side_effect=AssertionError("H3 must not precharge"),
                    ):
                        with patch.object(
                            self.remote,
                            "_submit_comic_gateway_video_task",
                            side_effect=AssertionError("H3 must not use LK888 gateway"),
                        ):
                            with patch.object(self.remote, "_save_local_comic_state"):
                                task = self.remote._submit_ai_comic_media_task(
                                    model="minimax-h3",
                                    prompt="walk through a station",
                                    params={
                                        "duration": 4,
                                        "resolution": "2K",
                                        "reference_image_urls": [
                                            "https://assets.test/start.png"
                                        ],
                                    },
                                    project_id=10,
                                    task_type="generate_video",
                                    task_name="generate storyboard video",
                                    target_id=20,
                                    target_type="storyboard",
                                )

        self.assertEqual(task["remote_task_id"], "h3-provider-task")
        self.assertEqual(task["model"], "minimax-h3")
        self.assertEqual(task["provider"], "minimax-direct")
        self.assertEqual(task["actual_model"], "MiniMax-H3")
        self.assertEqual(task["billing_status"], "awaiting_actual_cost")
        self.assertNotIn("billing_request_id", task)
        self.assertEqual(calls[0]["method"], "POST")
        self.assertEqual(calls[0]["path"], "/v2/video_generation")
        self.assertEqual(calls[0]["payload"]["model"], "MiniMax-H3")
        self.assertEqual(calls[0]["payload"]["duration"], 4)
        self.assertEqual(calls[0]["payload"]["resolution"], "2K")
        self.assertEqual(
            calls[0]["payload"]["content"][0]["image_url"]["url"],
            "https://assets.test/start.png",
        )

    def test_h3_direct_refresh_polls_official_query_and_records_result_url(self):
        calls = []
        task = {
            "id": "ai-h3-provider-task",
            "task_id": "ai-h3-provider-task",
            "remote_task_id": "h3-provider-task",
            "task_type": "generate_video",
            "task_name": "generate storyboard video",
            "status": "pending",
            "state": "pending",
            "progress_percent": 0,
            "provider": "minimax-direct",
            "model": "minimax-h3",
            "actual_model": "MiniMax-H3",
            "billing_status": "awaiting_actual_cost",
            "project_id": 10,
            "target_id": 20,
            "target_type": "storyboard",
        }

        def fake_json_request(method, path, payload=None, timeout=60):
            calls.append(
                {
                    "method": method,
                    "path": path,
                    "payload": payload,
                    "timeout": timeout,
                }
            )
            return {
                "status": "success",
                "task": {
                    "content": {
                        "url": "https://assets.test/final.mp4",
                    }
                },
            }

        with patch.object(self.remote, "MINIMAX_ENABLED", True, create=True):
            with patch.object(self.remote, "MINIMAX_COMIC_API_KEY", "comic-key", create=True):
                with patch.object(
                    self.remote,
                    "_minimax_h3_json_request",
                    side_effect=fake_json_request,
                    create=True,
                ):
                    with patch.object(
                        self.remote.AI_API_SERVICE,
                        "get_task_status",
                        side_effect=AssertionError("H3 must use MiniMax query"),
                        create=True,
                    ):
                        with patch.object(self.remote, "_save_local_comic_state"):
                            with patch.object(
                                self.remote,
                                "_finalize_ai_comic_fallback_video_audio",
                                return_value=task,
                            ):
                                with patch.object(
                                    self.remote,
                                    "_apply_ai_comic_task_result_to_project",
                                ):
                                    with patch.object(
                                        self.remote,
                                        "_sync_ai_comic_task_actual_billing_cost",
                                        return_value=False,
                                    ):
                                        refreshed = self.remote._refresh_ai_comic_task(task)

        self.assertEqual(calls[0]["method"], "GET")
        self.assertEqual(
            calls[0]["path"],
            "/v2/query/video_generation/h3-provider-task",
        )
        self.assertEqual(refreshed["status"], "completed")
        self.assertEqual(refreshed["result_url"], "https://assets.test/final.mp4")
        self.assertEqual(refreshed["billing_status"], "awaiting_actual_cost")

    def test_h3_direct_rejects_local_reference_urls_before_submit(self):
        request = Mock()

        with patch.object(self.remote, "MINIMAX_ENABLED", True, create=True):
            with patch.object(self.remote, "MINIMAX_COMIC_API_KEY", "comic-key", create=True):
                with patch.object(
                    self.remote,
                    "_minimax_h3_json_request",
                    request,
                    create=True,
                ):
                    with self.assertRaisesRegex(ValueError, "public HTTPS"):
                        self.remote._submit_minimax_h3_comic_video_task(
                            "move",
                            {
                                "duration": 4,
                                "resolution": "768P",
                                "reference_image_urls": [r"C:\\temp\\start.png"],
                            },
                        )

        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
