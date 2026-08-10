import importlib.util
import io
import os
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


class AiCanvasComicToolDownloadEntryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.remote = load_remote_server()

    def test_comic_tool_download_card_script_links_installer_as_fourth_tool(self):
        script = self.remote._comic_tool_download_card_script()

        self.assertIn("Windows 客户端", script)
        self.assertIn("AI爆款复刻平台", script)
        self.assertIn("下载客户端", script)
        self.assertIn("下载的是客户端安装包", script)
        self.assertIn("不包含漫剧项目文件", script)
        self.assertIn("/MatrixShipAgent-Setup.exe", script)
        self.assertIn("MutationObserver", script)
        self.assertIn("data-yunling-download-card", script)

    def test_comic_tool_download_card_does_not_clone_or_reorder_existing_tools(self):
        script = self.remote._comic_tool_download_card_script()

        self.assertNotIn("cloneNode", script)
        self.assertNotIn("insertBefore", script)
        self.assertIn("findToolContainer", script)

    def test_comic_tool_index_html_is_injected_idempotently(self):
        html = "<!doctype html><html><body><main>创作工具</main></body></html>"

        injected = self.remote._inject_comic_tool_download_card_html(html)
        reinjected = self.remote._inject_comic_tool_download_card_html(injected)

        self.assertIn("yunling-download-card-injector", injected)
        self.assertIn("Windows 客户端", injected)
        self.assertEqual(injected, reinjected)

    def test_installer_path_resolver_honors_environment_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "MatrixShipAgent-Setup.exe"
            installer.write_bytes(b"installer")
            previous = os.environ.get("AICANVAS_AGENT_INSTALLER")
            os.environ["AICANVAS_AGENT_INSTALLER"] = str(installer)
            try:
                self.assertEqual(
                    self.remote._resolve_agent_installer_path(),
                    str(installer.resolve()),
                )
            finally:
                if previous is None:
                    os.environ.pop("AICANVAS_AGENT_INSTALLER", None)
                else:
                    os.environ["AICANVAS_AGENT_INSTALLER"] = previous

    def test_handler_serves_installer_without_auth_gate(self):
        source = SERVER_PATH.read_text(encoding="utf-8")
        route_index = source.index('if path == "/MatrixShipAgent-Setup.exe":')
        auth_index = source.index(
            "if not _prepare_request_storage_context(self, path):",
            route_index,
        )

        self.assertLess(route_index, auth_index)

    def test_installer_response_is_attachment(self):
        handler = object.__new__(self.remote.Handler)
        handler.wfile = io.BytesIO()
        handler.headers = {}
        sent = []

        def send_response(status):
            sent.append(("status", status))

        def send_header(name, value):
            sent.append(("header", name, value))

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = lambda: sent.append(("end",))

        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "MatrixShipAgent-Setup.exe"
            installer.write_bytes(b"installer")
            with patch.object(
                self.remote,
                "_resolve_agent_installer_path",
                return_value=str(installer),
            ):
                self.remote.Handler.serve_agent_installer(handler)

        self.assertIn(("status", 200), sent)
        self.assertIn(("header", "Content-Type", "application/octet-stream"), sent)
        self.assertIn(
            ("header", "Content-Disposition", 'attachment; filename="MatrixShipAgent-Setup.exe"'),
            sent,
        )
        self.assertEqual(handler.wfile.getvalue(), b"installer")


class LK888VersionedPathJoinTest(unittest.TestCase):
    """Regression for /v1/v1/... double-versioning that caused hailuo H3
    schema fetch to 404, which cascaded into 'please upload at least 1
    reference image' errors even when references were uploaded.
    """

    @classmethod
    def setUpClass(cls):
        cls.remote = load_remote_server()

    def test_join_dedupes_v1_when_base_already_ends_with_v1(self):
        joined = self.remote._join_versioned_api_path(
            "https://api.lk888.ai/v1",
            "/v1/skills/models/hailuo-h3-quannengcankao",
        )
        self.assertEqual(
            joined,
            "https://api.lk888.ai/v1/skills/models/hailuo-h3-quannengcankao",
        )

    def test_join_preserves_v1_when_base_has_no_version(self):
        joined = self.remote._join_versioned_api_path(
            "https://api.lk888.ai",
            "/v1/skills/models/hailuo-h3-quannengcankao",
        )
        self.assertEqual(
            joined,
            "https://api.lk888.ai/v1/skills/models/hailuo-h3-quannengcankao",
        )

    def test_join_dedupes_v2_the_same_way(self):
        joined = self.remote._join_versioned_api_path(
            "https://api.lk888.ai/v2",
            "/v2/query/video_generation/abc",
        )
        self.assertEqual(joined, "https://api.lk888.ai/v2/query/video_generation/abc")

    def test_join_leaves_non_versioned_paths_alone(self):
        joined = self.remote._join_versioned_api_path(
            "https://api.lk888.ai/v1",
            "/skills/models/hailuo-h3-quannengcankao",
        )
        # No de-dup when path lacks its own version prefix — pure concatenation.
        self.assertEqual(
            joined,
            "https://api.lk888.ai/v1/skills/models/hailuo-h3-quannengcankao",
        )

    def test_apimart_json_request_uses_joined_url_not_raw_concat(self):
        """When base=.../v1 and path=/v1/..., the request URL must NOT have /v1/v1/."""
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"models": []}'

        def fake_urlopen(req, timeout=60):
            captured["url"] = req.full_url
            return FakeResponse()

        with patch.object(self.remote.urllib.request, "urlopen", fake_urlopen):
            self.remote._apimart_json_request(
                "https://api.lk888.ai/v1",
                "sk-thisisalongenoughapikeyfortest",
                "/v1/skills/models?type=video",
                None,
                30,
            )
        self.assertEqual(
            captured["url"],
            "https://api.lk888.ai/v1/skills/models?type=video",
        )
        # Explicit anti-regression: NO /v1/v1/ substring anywhere.
        self.assertNotIn("/v1/v1/", captured["url"])


class ComicFallbackTtsDegradeTest(unittest.TestCase):
    """Regression for trap D failure #12 variant: a post-video TTS-mix step
    used to hard-fail with comic_storyboard_tts_missing and discard an
    already-paid provider video. Fix degrades to skipped_missing_tts and
    keeps provider_result_url as the surfaced result_url.
    """

    @classmethod
    def setUpClass(cls):
        cls.remote = load_remote_server()

    def _matrix_replacement_completed_task(self, audio_mode):
        # source_mode on the task itself satisfies _is_matrix_video_replacement_project(task);
        # no LOCAL_COMIC_PROJECTS entry required.
        task = {
            "id": "ai-99999999",
            "remote_task_id": "99999999",
            "task_type": "generate_video",
            "target_type": "storyboard",
            "target_id": 999001,
            "project_id": 0,
            "status": "completed",
            "state": "completed",
            "progress_percent": 100,
            "provider": "ai",
            "provider_result_url": "https://lk888.example/paid-video.mp4",
            "result_url": "https://lk888.example/paid-video.mp4",
            "source_mode": "matrix_video_replacement",
            "audio_mode": audio_mode,
            "fallback_applied": True,
        }
        return task

    def test_missing_tts_no_longer_raises_and_preserves_provider_video(self):
        task = self._matrix_replacement_completed_task(audio_mode="tts")
        with patch.object(self.remote, "_save_local_comic_state"):
            returned = self.remote._finalize_ai_comic_fallback_video_audio(task)
        self.assertIs(returned, task)
        self.assertEqual(returned["result_url"], "https://lk888.example/paid-video.mp4")
        self.assertEqual(
            returned["provider_result_url"], "https://lk888.example/paid-video.mp4"
        )
        self.assertEqual(returned["audio_mix_status"], "skipped_missing_tts")
        self.assertEqual(returned["audioMixStatus"], "skipped_missing_tts")
        self.assertEqual(returned["audio_source"], "provider_generated")
        self.assertEqual(returned["audio_mix_error"], "comic_storyboard_tts_missing")
        # Explicit anti-regression: status stays "completed", never gets flipped
        # to "failed" by the outer caller because we didn't raise.
        self.assertEqual(returned["status"], "completed")

    def test_missing_tts_with_empty_audio_mode_also_degrades(self):
        # audio_mode not set at all used to fall through to the raise branch too.
        task = self._matrix_replacement_completed_task(audio_mode="")
        with patch.object(self.remote, "_save_local_comic_state"):
            returned = self.remote._finalize_ai_comic_fallback_video_audio(task)
        self.assertEqual(returned["audio_mix_status"], "skipped_missing_tts")
        self.assertEqual(returned["result_url"], "https://lk888.example/paid-video.mp4")

    def test_auto_audio_mode_still_short_circuits_without_touching_tts(self):
        # Regression guard: the pre-existing auto branch must not regress.
        task = self._matrix_replacement_completed_task(audio_mode="auto")
        with patch.object(self.remote, "_save_local_comic_state"):
            returned = self.remote._finalize_ai_comic_fallback_video_audio(task)
        self.assertEqual(returned["audio_mix_status"], "not_requested")
        self.assertEqual(returned["result_url"], "https://lk888.example/paid-video.mp4")

    def test_tts_url_present_still_triggers_real_mux(self):
        # When a TTS URL IS attached, we must still call the mux — the degrade
        # path must not swallow it silently.
        task = self._matrix_replacement_completed_task(audio_mode="tts")
        task["storyboard_tts_url"] = "https://lk888.example/tts.mp3"

        mux_calls = []

        def fake_mux(video_url, tts_url, project_id, storyboard_id):
            mux_calls.append((video_url, tts_url, project_id, storyboard_id))
            return {
                "url": "https://lk888.example/muxed.mp4",
                "video_duration_seconds": 8,
                "audio_duration_seconds": 8,
                "final_duration_seconds": 8,
            }

        with patch.object(self.remote, "_save_local_comic_state"), patch.object(
            self.remote, "_comic_remux_video_with_storyboard_tts", fake_mux
        ):
            returned = self.remote._finalize_ai_comic_fallback_video_audio(task)
        self.assertEqual(len(mux_calls), 1)
        self.assertEqual(returned["audio_mix_status"], "completed")
        self.assertEqual(returned["result_url"], "https://lk888.example/muxed.mp4")
        self.assertEqual(returned["audio_source"], "storyboard_tts")

    def test_missing_provider_url_still_hard_fails(self):
        # If the provider video really is missing, we still can't fabricate one.
        # Hard fail is correct here (no paid content to lose).
        task = self._matrix_replacement_completed_task(audio_mode="tts")
        task["provider_result_url"] = ""
        task["result_url"] = ""
        with patch.object(self.remote, "_save_local_comic_state"):
            with self.assertRaises(RuntimeError) as cm:
                self.remote._finalize_ai_comic_fallback_video_audio(task)
        self.assertIn("comic_fallback_video_url_missing", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
