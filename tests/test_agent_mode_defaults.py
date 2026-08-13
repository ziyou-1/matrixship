from pathlib import Path
import importlib.util
import os
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CLIENT = ROOT / "backend" / "matrix_native_client.py"
RUNTIME_PATHS = BACKEND / "runtime_paths.py"


def load_runtime_paths_module():
    spec = importlib.util.spec_from_file_location("runtime_paths_under_test", RUNTIME_PATHS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_client_module(name="matrix_native_client_under_test"):
    spec = importlib.util.spec_from_file_location(name, CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentModeDefaultsTest(unittest.TestCase):
    def test_windows_agent_data_defaults_to_project_backend_datas(self):
        module = load_runtime_paths_module()

        with mock.patch.object(module.os, "name", "nt"), mock.patch.dict(
            os.environ,
            {
                "APPDATA": r"C:\Users\Administrator\AppData\Roaming",
                "MATRIX_AGENT_DATA_DIR": "",
                "DY_DATA_DIR": "",
            },
            clear=False,
        ):
            expected = str(BACKEND / "datas")

            self.assertEqual(os.path.normcase(expected), os.path.normcase(module.agent_data_dir()))

    def test_agent_data_dir_env_override_still_wins(self):
        module = load_runtime_paths_module()

        with mock.patch.dict(
            os.environ,
            {
                "MATRIX_AGENT_DATA_DIR": r"E:\MatrixShipRuntime\data",
                "DY_DATA_DIR": "",
            },
            clear=False,
        ):
            self.assertEqual(
                os.path.normcase(r"E:\MatrixShipRuntime\data"),
                os.path.normcase(module.agent_data_dir()),
            )

    def test_account_scope_uses_stable_project_data_root(self):
        module = load_client_module("matrix_native_client_account_scope_test")

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {
                    "MATRIX_AGENT_DATA_DIR": tmp,
                    "DY_DATA_DIR": "",
                    "DY_PROFILE_DIR": "",
                    "XHS_PROFILE_DIR": "",
                    "MATRIX_AGENT_TOKEN": "",
                },
                clear=False,
            ):
                first_dir, _ = module.apply_account_scope("user-owner")
                second_dir, _ = module.apply_account_scope("boss")

            expected_first = os.path.join(tmp, "accounts", "user-owner")
            expected_second = os.path.join(tmp, "accounts", "boss")
            nested_second = os.path.join(expected_first, "accounts", "boss")
            self.assertEqual(os.path.normcase(expected_first), os.path.normcase(first_dir))
            self.assertEqual(os.path.normcase(expected_second), os.path.normcase(second_dir))
            self.assertNotEqual(os.path.normcase(nested_second), os.path.normcase(second_dir))

    def test_local_task_error_message_explains_xhs_ip_risk(self):
        module = load_client_module("matrix_native_client_xhs_ip_risk_message_test")

        message = module._local_task_error_message({
            "error": "xhs_ip_risk",
            "result": {"riskCode": "300012"},
        })

        self.assertIn("小红书安全限制", message)
        self.assertIn("网络", message)
        self.assertIn("300012", message)

    def test_risk_summary_marks_xhs_account_violation_as_high_risk(self):
        module = load_client_module("matrix_native_client_xhs_account_violation_risk_test")

        summary = module._account_risk_summary({
            "platform": "xhs",
            "online": True,
            "cookieReady": True,
            "riskEvents": [{
                "title": "\u8d26\u53f7\u8fdd\u89c4\u63d0\u793a",
                "reason": "\u60a8\u7684\u8d26\u53f7\u6d89\u53ca\u4f7f\u7528\u7b2c\u4e09\u65b9\u5de5\u5177\u6216\u811a\u672c\uff08\u5982AI\uff09\u81ea\u52a8\u6d4f\u89c8\u3001\u67e5\u770b\u6216\u53d1\u5e03\u5185\u5bb9\u6765\u8fd0\u8425\u8d26\u53f7\u7684\u884c\u4e3a",
            }],
        })

        self.assertEqual("\u9ad8\u98ce\u9669", summary["risk"])
        self.assertIn("\u8d26\u53f7\u8fdd\u89c4", summary["reason"])
        self.assertIn("\u6682\u505c", summary["advice"])

    def test_risk_summary_applies_persisted_xhs_task_risk_to_same_platform(self):
        module = load_client_module("matrix_native_client_xhs_persisted_risk_test")

        event = module._account_risk_event_from_task("xhs.search", {
            "status": "failed",
            "error": "xhs_ip_risk",
            "result": {"riskCode": "300012"},
        })
        summary = module._account_risk_summary({
            "platform": "xhs",
            "online": True,
            "cookieReady": True,
        }, [event])

        self.assertEqual("\u9ad8\u98ce\u9669", summary["risk"])
        self.assertIn("300012", summary["reason"])

    def test_windows_start_script_sets_project_agent_data_dir(self):
        script = (ROOT / "start-local-test.ps1").read_text(encoding="utf-8")

        self.assertIn("$AgentData = Join-Path $Backend 'datas'", script)
        self.assertIn("$env:MATRIX_AGENT_DATA_DIR = $AgentData", script)
        self.assertIn("$env:DY_DATA_DIR = $AgentData", script)
        self.assertIn("Client log: backend\\datas\\logs", script)

    def test_visible_client_batch_starts_central_before_client(self):
        script = (ROOT / "start-visible-client.bat").read_text(encoding="utf-8")

        self.assertIn('set "PYTHON=%ROOT%\\.venv-win\\Scripts\\python.exe"', script)
        self.assertIn('set "PYTHONW=%ROOT%\\.venv-win\\Scripts\\pythonw.exe"', script)
        self.assertIn('set "MATRIX_CENTRAL=http://127.0.0.1:9080"', script)
        self.assertIn('set "CENTRAL_PORT=9080"', script)
        self.assertIn('start "MatrixShip Central" /min "%PYTHON%" central_server.py', script)
        self.assertIn('http://127.0.0.1:9080/api/health', script)
        self.assertIn('"%PYTHONW%" matrix_native_client.py', script)

    def test_agent_batch_launcher_avoids_appdata_data_default(self):
        script = (BACKEND / "start-matrix-agent.bat").read_text(encoding="utf-8")

        self.assertIn('set "APPDATA_DIR=%~dp0datas"', script)
        self.assertNotIn("%APPDATA%\\MatrixShipAgent\\data", script)

    def test_task_center_table_uses_shared_style_without_grid_boxes(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class TaskCenterPage")
        end = src.index("class LogPage", start)
        block = src[start:end]

        self.assertIn("style_table(self.table)", block)

    def test_task_center_time_text_prefers_existing_text_fields(self):
        module = load_client_module("matrix_native_client_task_center_time_text_test")

        self.assertEqual("刚刚", module._task_center_time_text({
            "updatedAtText": "刚刚",
            "updatedAt": 1800000000,
        }))
        self.assertEqual("14:20", module._task_center_time_text({
            "createdAtText": "14:20",
            "createdAt": 1800000000,
        }))

    def test_task_center_time_text_formats_numeric_timestamp(self):
        module = load_client_module("matrix_native_client_task_center_numeric_time_test")
        stamp = module.time.mktime((2026, 7, 31, 15, 4, 0, 0, 0, -1))

        self.assertEqual("07-31 15:04", module._task_center_time_text({
            "updatedAt": stamp,
        }))
        self.assertEqual("07-31 15:04", module._task_center_time_text({
            "createdAt": stamp,
        }))

    def test_enterprise_overview_task_trend_uses_real_usage_buckets(self):
        module = load_client_module("matrix_native_client_enterprise_task_trend_test")

        values, labels = module._enterprise_task_trend_series({
            "taskTrend7d": [
                {"date": "2026-07-25", "label": "07-25", "count": 0},
                {"date": "2026-07-26", "label": "07-26", "count": 3},
            ],
        })
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class DashboardPage")
        end = src.index("class EnterpriseMembersPage", start)
        block = src[start:end]

        self.assertEqual(values, [0, 3])
        self.assertEqual(labels, ["07-25", "07-26"])
        self.assertIn("_enterprise_task_trend_series(u)", block)
        self.assertIn("taskTrend7d", src)
        self.assertNotIn("or 280", block)
        self.assertNotIn("0.72, 0.88, 1.05", block)

    def test_enterprise_overview_uses_custom_hover_explanations(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class DashboardPage")
        end = src.index("class EnterpriseMembersPage", start)
        block = src[start:end]

        self.assertIn("class HoverInfoPopup", src)
        self.assertIn("def attach_hover_info(", src)
        self.assertIn("ENTERPRISE_METRIC_HELP = {", src)
        for label in ("客户企业", "企业用户", "团队成员", "在线节点", "授权账号", "可用账号",
                      "离线账号", "调度任务", "素材", "发布队列", "任务趋势", "运行健康", "账号分布"):
            self.assertIn('"%s"' % label, src)
        self.assertIn("kpi_card(num, lbl, info=enterprise_kpi_info(lbl, num, s, u))", block)
        self.assertIn('Panel("任务趋势", "近 7 天真实任务量", info=ENTERPRISE_METRIC_HELP.get("任务趋势"))', block)
        self.assertIn('Panel("运行健康", "近 24 小时", info=ENTERPRISE_METRIC_HELP.get("运行健康"))', block)
        self.assertIn('Panel("账号分布", "授权 / 可用 / 离线", info=ENTERPRISE_METRIC_HELP.get("账号分布"))', block)

    def test_agent_mode_image_timeout_and_default_aspect_are_stable(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("def _agent_image_payload(", src)
        self.assertIn('params["size"] = size', src)
        self.assertIn("refs = refs[:_agent_image_reference_limit(model)]", src)
        self.assertIn("self.aspect_i = 1", src)
        self.assertIn('("方形 1:1", "1024x1024", "1:1")', src)

    def test_enterprise_overview_kpis_are_fixed_to_confirmed_business_metrics(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class DashboardPage")
        end = src.index("class EnterpriseMembersPage", start)
        block = src[start:end]

        self.assertIn("ENTERPRISE_OVERVIEW_KPI_LABELS = (", src)
        for label in ("客户企业", "企业用户", "授权账号", "可用账号", "在线节点", "调度任务"):
            self.assertIn('"%s"' % label, src)
        self.assertIn("shown = [(cnt(lbl), lbl) for lbl in ENTERPRISE_OVERVIEW_KPI_LABELS]", block)
        self.assertNotIn("shown = cards[:8]", block)

    def test_enterprise_overview_kpi_hover_copy_and_grid_are_business_specific(self):
        module = load_client_module("matrix_native_client_enterprise_kpi_info_test")
        summary = {
            "organizations": [{"id": "org-toyota", "name": "丰田汽车"}],
            "counts": {"users": 3, "tasks": 7},
        }

        self.assertIn("丰田汽车", module.enterprise_kpi_info("客户企业", 1, summary, {}))
        self.assertIn("已加入企业的用户数量：3 人", module.enterprise_kpi_info("企业用户", 3, summary, {}))
        self.assertIn("超过约 45 秒未上报心跳", module.enterprise_kpi_info("在线节点", 1, summary, {}))
        self.assertIn("任务总数：7 个", module.enterprise_kpi_info("调度任务", 7, summary, {}))

        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class DashboardPage")
        end = src.index("class EnterpriseMembersPage", start)
        block = src[start:end]
        self.assertIn("enterprise_kpi_info(lbl, num, s, u)", block)
        self.assertIn("i // 3, i % 3", block)
        self.assertIn("for c in range(3):", block)

    def test_agent_mode_prompt_optimization_confirms_chinese_before_generation(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn("class PromptConfirmDialog", src)
        self.assertIn('self.optimize_btn = _icon_text_btn("sparkle", "提示词优化"', src)
        self.assertIn("def optimize_prompt(self):", src)
        self.assertIn("def _send_confirmed(self, prompt):", src)
        self.assertIn("def _prodgen_optimize_prompt(", src)
        self.assertIn("visiblePrompt=display_prompt", src)
        self.assertIn('emit("thinking", {"expandedPrompt": display_prompt})', src)
        self.assertIn("modelPrompt=model_prompt[:700]", src)
        self.assertNotIn("优化后的英文提示词(送给图片模型)", src)

    def test_agent_mode_prompt_input_is_multiline_below_reference_strip(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn("ref_strip = QtWidgets.QHBoxLayout()", src)
        self.assertIn("body.addLayout(ref_strip)", src)
        self.assertIn("body.addLayout(prompt_col, 1)", src)
        self.assertIn("self.inp = QtWidgets.QPlainTextEdit()", src)
        self.assertIn("self.inp.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)", src)
        self.assertIn("self.inp.setMinimumHeight(78)", src)
        self.assertIn("self.inp.setMaximumHeight(138)", src)
        self.assertIn("prompt_col.addWidget(self.inp)", src)
        self.assertNotIn("midrow.addWidget(self.ref_slot", src)
        self.assertIn("self.inp.setPlainText(entry.get(\"prompt\") or \"\")", src)
        self.assertIn("prompt = self.inp.toPlainText().strip()", src)
        self.assertIn("data.get(\"prompt\") or self.inp.toPlainText().strip()", src)

    def test_agent_video_placeholder_does_not_show_lk888_output_hint(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn('else "描述你想要的视频素材…")', src)
        self.assertNotIn("按所选 LK888 视频模型出片", src)
        self.assertNotIn("按所选 LK888视频模型出片", src)

    def test_agent_mode_supports_ordered_multi_image_references(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn("MAX_REFS = 4", src)
        self.assertIn("self._refs = []", src)
        self.assertIn("self.ref_strip = ref_strip", src)
        self.assertIn("self.ref_buttons = []", src)
        self.assertIn("def _set_refs(self, refs):", src)
        self.assertIn("def _append_refs(self, refs):", src)
        self.assertIn("def _replace_ref_at(self, idx):", src)
        self.assertIn("def _remove_ref_at(self, idx):", src)
        self.assertIn("def _rebuild_ref_slots(self):", src)
        self.assertIn("QtWidgets.QFileDialog.getOpenFileNames", src)
        module = load_client_module("matrix_native_client_agent_ref_labels_test")
        self.assertEqual(module._prodgen_ref_label_for("image", "qwen-image", 0), "待修改图")
        self.assertEqual(module._prodgen_ref_label_for("image", "qwen-image", 1), "参考图1")
        self.assertEqual(module._prodgen_ref_label_for("video", "vidu2.0", 0), "参考图1")
        self.assertEqual(module._prodgen_ref_label_for("video", "vidu2.0", 1), "参考图2")
        self.assertIn("\"refs\": list(self._refs)", src)
        self.assertIn("\"ref\": (self._refs[0] if self._refs else \"\")", src)
        self.assertIn("self._set_refs(entry.get(\"refs\") or ([entry.get(\"ref\")] if entry.get(\"ref\") else []))", src)

    def test_agent_mode_video_uploads_are_all_reference_images(self):
        src = CLIENT.read_text(encoding="utf-8")
        desc_start = src.index("def _prodgen_refs_desc(")
        desc_end = src.index("def _prodgen_ref_desc(", desc_start)
        desc_block = src[desc_start:desc_end]
        page_start = src.index("class ProductGenPage")
        page_end = src.index("class AssetPickerDialog", page_start)
        page_block = src[page_start:page_end]
        label_block = page_block[page_block.index("def _ref_label(self, i):"):page_block.index("def _make_ref_cell(self, path, i):")]
        rebuild_block = page_block[page_block.index("def _rebuild_ref_slots(self):"):page_block.index("def _style_ref_slot(self):")]
        mode_block = page_block[page_block.index("def _mode_set(self, m):"):page_block.index("def _menu_choice(")]
        video_block = src[src.index("def _prodgen_run_video(entry, emit=None):"):src.index("def _prodgen_generate(entry, emit=None):")]
        card_start = src.index("class GenCard")
        card_end = src.index("class ProductGenPage", card_start)
        card_block = src[card_start:card_end]

        self.assertIn("def _prodgen_refs_desc(refs, is_video=False):", desc_block)
        self.assertIn("All images are visual references for video generation", desc_block)
        self.assertIn("No image is an edit target", desc_block)
        self.assertIn("_prodgen_refs_desc(refs, is_video=True)", video_block)
        self.assertIn("_prodgen_ref_label_for(self._mode, self._current_model(), i)", label_block)
        module = load_client_module("matrix_native_client_agent_video_ref_labels_test")
        self.assertEqual(module._prodgen_ref_label_for("video", "vidu2.0", 0), "参考图1")
        self.assertEqual(module._prodgen_ref_label_for("video", "vidu2.0", 1), "参考图2")
        self.assertIn('hint_text = ("视频模式：上传图片全部作为参考图，不会当作待修改图。"', rebuild_block)
        self.assertIn('else "图片模式：第1张为待修改图，第2张起为参考图。")', rebuild_block)
        self.assertIn("self._style_ref_slot()", mode_block)
        self.assertIn('if e.get("mode") == "video":', card_block)
        self.assertIn('ref_label = _prodgen_ref_label_for(e.get("mode"), e.get("model"), i)', card_block)
        self.assertIn("lab = QtWidgets.QLabel(ref_label)", card_block)

    def test_agent_mode_reference_slots_fill_horizontal_content_area(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("def _make_ref_cell(self, path, i):")
        end = src.index("def _rebuild_ref_slots(self):", start)
        block = src[start:end]

        self.assertIn("REF_SLOT_W = 84", src)
        self.assertIn("REF_SLOT_H = 84", src)
        self.assertIn("REF_SLOT_RADIUS = 14", src)
        self.assertIn("btn.setFixedSize(REF_SLOT_W, REF_SLOT_H)", block)
        self.assertIn("pm.scaled(REF_SLOT_W, REF_SLOT_H, QtCore.Qt.KeepAspectRatioByExpanding", block)
        self.assertIn("crop_x = max(0, (pm.width() - REF_SLOT_W) // 2)", block)
        self.assertIn("crop_y = max(0, (pm.height() - REF_SLOT_H) // 2)", block)
        self.assertIn("pm.copy(crop_x, crop_y, REF_SLOT_W, REF_SLOT_H)", block)
        self.assertIn("btn.setIconSize(QtCore.QSize(REF_SLOT_W, REF_SLOT_H))", block)
        self.assertNotIn("pm.scaled(52, 52", block)
        self.assertNotIn("btn.setIconSize(QtCore.QSize(52, 52))", block)

    def test_agent_mode_generation_uses_all_uploaded_images_in_order(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn("def _prodgen_entry_refs(entry):", src)
        self.assertIn("refs = _prodgen_entry_refs(entry)", src)
        self.assertIn("image_urls = _prodgen_image_reference_urls(refs, display_prompt) if has_ref else None", src)
        self.assertIn("def _agent_image_payload(", src)
        self.assertIn("payload = _agent_image_payload(model, model_prompt, size=size, image_urls=image_urls)", src)
        self.assertIn("url = lk888_media_task(model, payload, [\"png\", \"jpg\", \"jpeg\", \"webp\"], tries=150,", src)
        self.assertIn("exclude_urls=image_urls", src)
        self.assertIn("ref_desc = _prodgen_refs_desc(refs, is_video=True) if has_ref else \"\"", src)
        self.assertIn("第1张为待修改图", src)
        self.assertIn("第2张起为参考图", src)
        self.assertIn("\"refs\"", src[src.index("def regen(self, entry):"):src.index("def remove(self, entry):")])

    def test_agent_completed_video_can_be_added_to_douyin_pending_publish_once(self):
        module = load_client_module("matrix_native_client_agent_pending_publish_test")
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "agent-result.mp4"
            video.write_bytes(b"video")
            entry = {
                "id": "pg-agent-1",
                "mode": "video",
                "status": "完成",
                "prompt": "丰田汽车展示视频",
                "files": [str(video)],
            }
            with mock.patch.object(module, "PENDING", []), \
                    mock.patch.object(module, "save_pending"), \
                    mock.patch.object(module, "save_prodgen"):
                first = module.add_prodgen_video_to_pending(entry)
                second = module.add_prodgen_video_to_pending(entry)
                self.assertIsNotNone(first)
                self.assertIs(first, second)
                self.assertEqual(1, len(module.PENDING))
                self.assertEqual("douyin", first["platform"])
                self.assertEqual("Agent.模式", first["wfName"])
                self.assertEqual(str(video), first["video"])
                self.assertEqual("pg-agent-1", first["sourceProdgenId"])

    def test_agent_completed_video_is_uploaded_to_publish_material_library_once(self):
        module = load_client_module("matrix_native_client_agent_publish_material_test")
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "agent-result.mp4"
            video.write_bytes(b"video")
            entry = {
                "id": "pg-agent-1",
                "mode": "video",
                "status": "完成",
                "prompt": "丰田汽车展示视频",
                "files": [str(video)],
            }
            with mock.patch.object(module, "upload_materials", return_value=(200, {
                "ok": True,
                "id": "mat-agent-1",
            })) as upload, mock.patch.object(module, "save_prodgen"):
                first = module.add_prodgen_video_to_publish_library(entry)
                second = module.add_prodgen_video_to_publish_library(entry)

                self.assertEqual("mat-agent-1", first)
                self.assertEqual("mat-agent-1", second)
                self.assertEqual("mat-agent-1", entry["publishMaterialId"])
                upload.assert_called_once_with(
                    [str(video)],
                    "丰田汽车展示视频",
                    mtype="video",
                    metadata={"source": "agent_mode", "sourceProdgenId": "pg-agent-1"},
                )

    def test_agent_video_card_requires_publish_material_before_marking_joined(self):
        src = CLIENT.read_text(encoding="utf-8")
        card_start = src.index("class GenCard")
        card_end = src.index("class StyleDot", card_start)
        card = src[card_start:card_end]

        self.assertIn("prodgen_video_publish_material_id(e)", card)
        self.assertNotIn("pending = prodgen_video_pending_entry(e)", card)

    def test_agent_video_publish_button_is_only_available_after_generation(self):
        src = CLIENT.read_text(encoding="utf-8")
        card_start = src.index("class GenCard")
        card_end = src.index("class StyleDot", card_start)
        card = src[card_start:card_end]

        self.assertIn("def add_to_publish(self, entry):", src)
        self.assertIn("add_prodgen_video_to_publish_library(entry)", src)
        self.assertIn("add_prodgen_video_to_pending(entry", src)
        self.assertIn('if e.get("mode") == "video" and st == "完成":', card)
        self.assertIn('"加入发布"', card)
        self.assertIn('"已加入"', card)

    def test_agent_mode_canonical_model_label_overrides_lk888_catalog_mismatch(self):
        module = load_client_module("matrix_native_client_agent_model_mapping_test")
        rows = [{
            "name": "doubao-seedance-1-5-pro-251215",
            "display_name": "Seedream 3.5 Pro",
            "type": "video",
        }]

        self.assertEqual(
            module._lk888_model_label("doubao-seedance-1-5-pro-251215", rows),
            "Seedance 1.5 Pro",
        )

    def test_agent_mode_video_models_keep_canonical_defaults_before_catalog_additions(self):
        module = load_client_module("matrix_native_client_agent_model_catalog_test")
        catalog = [{
            "name": "jimeng-3-5-pro",
            "display_name": "即梦 3.5 Pro",
            "type": "video",
        }]

        with mock.patch.object(module, "_lk888_skill_models", return_value=catalog):
            rows = module._lk888_models_by_type("video")

        names = [row.get("name") for row in rows]
        self.assertIn("doubao-seedance-1-5-pro-251215", names)
        self.assertIn("jimeng-3-5-pro", names)
        self.assertLess(
            names.index("doubao-seedance-1-5-pro-251215"),
            names.index("jimeng-3-5-pro"),
        )

    def test_icon_text_buttons_skip_geometry_press_animation(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn('getattr(obj, "_no_press_scale", False)', src)
        self.assertIn("b._no_press_scale = True", src)
        self.assertIn("self.b_style = _icon_text_btn(", src)
        self.assertIn("self.b_count = _icon_text_btn(", src)
        self.assertIn("self.b_aspect = _icon_text_btn(", src)
        self.assertIn("self.b_model = _icon_text_btn(", src)
        self.assertIn("self.optimize_btn = _icon_text_btn(", src)

    def test_all_qpushbuttons_skip_geometry_press_animation(self):
        src = CLIENT.read_text(encoding="utf-8")
        scale_src = src[src.index("def _scale(self, obj, factor):"):src.index("\n\n\n_INTERACT = None")]

        self.assertIn("isinstance(obj, QtWidgets.QPushButton)", scale_src)
        self.assertLess(
            scale_src.index("isinstance(obj, QtWidgets.QPushButton)"),
            scale_src.index("obj.geometry()"),
        )
        self.assertIn("全局按钮不再使用 geometry 缩放", scale_src)

    def test_enterprise_hero_video_is_fixed_without_regenerate_button(self):
        src = CLIENT.read_text(encoding="utf-8")
        hero = src[src.index("class VideoHero"):src.index("\n\ndef _clear_layout")]

        self.assertIn("selected = _hero_video_path()", hero)
        self.assertIn("self.player.setSource(QtCore.QUrl.fromLocalFile(selected))", hero)
        self.assertIn("self.player.play()", hero)
        self.assertNotIn("self.genbtn", hero)
        self.assertNotIn("def _gen(self):", hero)
        self.assertNotIn("generate_hero_video()", hero)
        self.assertNotIn("def generate_hero_video(", src)

    def test_enterprise_hero_video_has_bundled_fallbacks_and_poster(self):
        module = load_client_module("matrix_native_client_hero_assets_test")

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {
                    "MATRIX_AGENT_DATA_DIR": tmp,
                    "DY_DATA_DIR": "",
                },
                clear=False,
            ):
                candidates = module._hero_video_candidates()

        normalized = {os.path.normcase(path) for path in candidates}
        self.assertIn(os.path.normcase(str(BACKEND / "datas" / "hero.mp4")), normalized)
        self.assertIn(os.path.normcase(str(BACKEND / "assets" / "login_bg" / "car-shouye.mp4")), normalized)
        self.assertEqual(
            os.path.normcase(str(BACKEND / "assets" / "login_bg" / "car-shouye.png")),
            os.path.normcase(module.HERO_POSTER),
        )

    def test_comic_tool_url_points_to_local_server(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn('COMIC_TOOL_URL = "http://120.26.194.174"', src)
        self.assertNotIn("gongju.eknowhub.cn/comic-tool", src)

    def test_native_sidebar_hides_comic_tool_and_mix_entries(self):
        src = CLIENT.read_text(encoding="utf-8")
        nav_src = src[src.index("NAV = ["):src.index("# ---------- 登录页")]

        self.assertNotIn("漫剧工具", nav_src)
        self.assertNotIn("混剪短视频", nav_src)
        self.assertIn("class ComicToolPage", src)
        self.assertIn("class MixPage", src)

    def test_native_asset_video_playback_uses_platform_open_command(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("def _open_path_cmd(", src)
        self.assertIn('sys.platform == "darwin"', src)
        self.assertIn('return ["open", path]', src)
        self.assertIn('return ["xdg-open", path]', src)
        asset_card = src[src.index("def _asset_card(self, a):"):src.index("def use_ref(self, a):")]
        self.assertIn('self._asset_action_btn("play", "播放", lambda: self.open_asset(a))', asset_card)

    def test_native_asset_video_cards_use_real_video_thumbnail(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("def _video_thumb_pixmap(", src)
        self.assertIn('_video_thumb_pixmap(path, 212, 158, 10)', src)
        self.assertIn('_video_thumb_pixmap(path, 126, 94, 8)', src)
        self.assertIn('_video_thumb_pixmap(path, 320, 182, 14)', src)
        self.assertIn('_video_thumb_pixmap(a.get("path"), 150, 110, 8)', src)
        fallback_func = src[src.index("def _video_thumb("):src.index("def _video_thumb_pixmap(")]
        thumb_func = src[src.index("def _video_thumb_pixmap("):src.index("def _chip_pill(")]
        self.assertNotIn("_play_badge", fallback_func)
        self.assertNotIn("_play_badge", thumb_func)


if __name__ == "__main__":
    unittest.main()
