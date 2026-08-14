import io
import json
import importlib
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

from backend import xhs_note_replacement as note


ROOT = os.path.dirname(os.path.dirname(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
NATIVE_CLIENT = os.path.join(ROOT, "backend", "matrix_native_client.py")


def load_native_client(name="matrix_native_client_for_xhs_note_display"):
    spec = importlib.util.spec_from_file_location(name, NATIVE_CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class XhsNoteReplacementSmokeTests(unittest.TestCase):
    def test_feature_enabled_defaults_true_and_env_can_disable(self):
        self.assertTrue(note.feature_enabled({}))
        self.assertFalse(note.feature_enabled({"XHS_NOTE_REPLACEMENT_ENABLED": "0"}))
        self.assertFalse(note.feature_enabled({"XHS_NOTE_REPLACEMENT_ENABLED": "false"}))
        self.assertTrue(note.feature_enabled({"XHS_NOTE_REPLACEMENT_ENABLED": "1"}))

    def test_job_root_is_inside_data_dir(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(note.job_root(td), os.path.join(td, "xhs_note_replacements"))

    def test_new_job_id_is_traceable(self):
        self.assertRegex(note.new_job_id(), r"^xnr_[0-9a-f]{24}$")


class XhsNoteTemplateTests(unittest.TestCase):
    def test_build_template_uses_material_files_and_source_fields(self):
        material = {
            "id": "mat-xhs-1",
            "type": "image",
            "platform": "xhs",
            "title": "原始标题",
            "body": "原始正文",
            "tags": ["#汽车", "#昆山"],
            "sourceUrl": "https://www.xiaohongshu.com/explore/abc",
            "files": ["01.jpg", "02.jpg", "03.jpg", "04.jpg"],
        }
        tpl = note.build_template(material)
        self.assertEqual(tpl["sourcePlatform"], "xhs")
        self.assertEqual(tpl["sourceMaterialId"], "mat-xhs-1")
        self.assertEqual(tpl["sourceNoteId"], "abc")
        self.assertEqual([s["role"] for s in tpl["imageSlots"]], ["cover", "product", "detail", "cta"])
        self.assertEqual(tpl["originalCopy"]["title"], "原始标题")

    def test_infer_slot_role_for_short_and_long_notes(self):
        self.assertEqual(note.infer_slot_role(1, 1), "cover")
        self.assertEqual(note.infer_slot_role(2, 6), "product")
        self.assertEqual(note.infer_slot_role(5, 6), "result")
        self.assertEqual(note.infer_slot_role(6, 6), "cta")
    def test_template_text_is_not_mojibake_and_chinese_names_infer_scene(self):
        material = {
            "id": "mat-xhs-2",
            "platform": "xhs",
            "title": "\u539f\u59cb\u6807\u9898",
            "body": "\u539f\u59cb\u6b63\u6587",
            "sourceUrl": "https://www.xiaohongshu.com/explore/scene-note",
            "files": ["01.jpg", "\u95e8\u5e97.jpg", "03.jpg"],
        }
        tpl = note.build_template(material)
        rendered = repr(tpl)
        self.assertNotIn("\ufffd", rendered)
        self.assertIn("\u69fd\u4f4d", tpl["imageSlots"][0]["analysis"])
        self.assertIn("\u539f\u56fe", tpl["imageSlots"][0]["analysis"])
        self.assertEqual(tpl["originalCopy"]["title"], "\u539f\u59cb\u6807\u9898")
        self.assertEqual(note.infer_slot_role(3, 4, "\u95e8\u5e97.jpg"), "scene")

    def test_build_template_preserves_source_download_path(self):
        material = {
            "id": "mat-xhs-path",
            "platform": "xhs",
            "sourceUrl": "https://www.xiaohongshu.com/explore/path-note",
            "sourceDownloadPath": r"E:\Desktop\project\backend\datas\accounts\user-owner\media_datas\xhs_path-note",
            "files": ["01.jpg"],
        }

        tpl = note.build_template(material)

        self.assertEqual(
            tpl["sourceDownloadPath"],
            r"E:\Desktop\project\backend\datas\accounts\user-owner\media_datas\xhs_path-note",
        )

class XhsNotePreviewTests(unittest.TestCase):
    def test_preview_prefers_assets_and_marks_missing_slots_ai_pending(self):
        tpl = {
            "id": "tpl-1",
            "imageSlots": [
                {"index": 1, "role": "cover", "ratio": "3:4"},
                {"index": 2, "role": "product", "ratio": "1:1"},
            ],
        }
        preview = note.build_replacement_preview(
            tpl,
            {
                "name": "\u5e7f\u6c7d\u4e30\u7530",
                "sellingPoints": ["\u7701\u6cb9", "\u5230\u5e97\u8bd5\u9a7e"],
                "region": "\u6606\u5c71",
                "audience": "\u5bb6\u7528\u8f66\u5ba2\u6237",
                "tone": "\u771f\u5b9e\u79cd\u8349",
            },
            [{"slotRole": "cover", "assetId": "as-1", "filePath": "cover.jpg"}],
        )
        self.assertEqual(preview["slotMappings"][0]["source"], "asset")
        self.assertEqual(preview["slotMappings"][1]["source"], "ai_placeholder")
        self.assertEqual(preview["slotMappings"][1]["confirmationStatus"], "pending")
        self.assertEqual(preview["aiSlotCount"], 1)
        self.assertEqual(len(preview["copyCandidates"]), 3)

    def test_copy_candidates_avoid_fixed_template_phrases(self):
        preview = note.build_replacement_preview(
            {"id": "tpl-1", "imageSlots": []},
            {
                "name": "丰田汽车",
                "sellingPoints": ["省油", "到店试驾"],
                "region": "昆山",
                "audience": "家用车客户",
            },
            [],
        )
        bodies = [str(item.get("body") or "") for item in preview["copyCandidates"]]
        joined = "\n".join(bodies)
        for phrase in (
            "这组图文按真实体验整理",
            "这次把重点放在",
            "图片里按封面、细节和行动引导整理",
            "先收藏再对比",
            "别只看表面",
        ):
            self.assertNotIn(phrase, joined)
        self.assertTrue(any("丰田汽车" in body for body in bodies))
        self.assertTrue(any("省油" in body for body in bodies))
        self.assertTrue(all("#" not in body for body in bodies))

    def test_copy_candidates_generate_longer_bodies(self):
        preview = note.build_replacement_preview(
            {"id": "tpl-1", "imageSlots": []},
            {
                "name": "丰田汽车",
                "sellingPoints": ["省油", "保养省心", "到店试驾"],
                "region": "昆山",
                "audience": "准备买家用车的人",
            },
            [],
        )
        bodies = [str(item.get("body") or "") for item in preview["copyCandidates"]]
        self.assertEqual(len(bodies), 3)
        for body in bodies:
            self.assertGreaterEqual(len(body), 120)
            self.assertLessEqual(len(body), 220)
            self.assertNotIn("#", body)


    def test_copy_candidate_titles_fit_xhs_title_limit(self):
        preview = note.build_replacement_preview(
            {"id": "tpl-1", "imageSlots": []},
            {
                "name": "广汽丰田智能家用汽车体验中心",
                "sellingPoints": ["省油耐用售后省心", "到店试驾"],
                "region": "昆山花桥核心商圈",
                "audience": "准备买家用车的人",
            },
            [],
        )

        titles = [str(item.get("title") or "") for item in preview["copyCandidates"]]
        self.assertEqual(len(titles), 3)
        for title in titles:
            self.assertLessEqual(len(title), 20)
            self.assertTrue(title.strip())


class XhsNoteJobPersistenceTests(unittest.TestCase):
    def test_save_and_load_job_is_atomic_json(self):
        with tempfile.TemporaryDirectory() as td:
            job = {"id": "xnr_1234567890abcdef12345678", "status": "draft", "slotMappings": []}
            path = note.save_job(td, job)
            self.assertTrue(path.endswith("replacement_job.json"))
            self.assertEqual(note.load_job(td, job["id"])["id"], job["id"])

    def test_draft_material_payload_marks_image_note_and_ai_review(self):
        job = {
            "id": "xnr_1234567890abcdef12345678",
            "templateId": "tpl-1",
            "slotMappings": [
                {"slotIndex": 1, "source": "asset", "filePath": "01.jpg", "confirmationStatus": "confirmed"},
                {"slotIndex": 2, "source": "ai_placeholder", "filePath": "02.jpg", "confirmationStatus": "pending"},
            ],
            "copyCandidates": [{"title": "\u6807\u9898", "body": "\u6b63\u6587", "tags": ["#\u6807\u7b7e"]}],
            "selectedCopyIndex": 0,
        }
        payload = note.build_draft_material_payload(job, ["01.jpg", "02.jpg"])
        self.assertEqual(payload["type"], "image_note")
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["aiImageReview"]["pendingSlots"], [2])

    def test_draft_material_payload_honors_selected_copy_index(self):
        job = {
            "id": "xnr_1234567890abcdef12345678",
            "templateId": "tpl-1",
            "slotMappings": [
                {"slotIndex": 1, "source": "asset", "filePath": "01.jpg", "confirmationStatus": "confirmed"},
            ],
            "copyCandidates": [
                {"title": "方案一", "body": "正文一", "tags": ["#一"]},
                {"title": "方案二", "body": "正文二", "tags": ["#二"]},
                {"title": "方案三", "body": "正文三", "tags": ["#三"]},
            ],
            "selectedCopyIndex": 2,
        }

        payload = note.build_draft_material_payload(job, ["01.jpg"])

        self.assertEqual(payload["title"], "方案三")
        self.assertEqual(payload["body"], "正文三")
        self.assertEqual(payload["tags"], ["#三"])


class XhsNoteSaveDraftApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = importlib.import_module("backend.api_server")

    def setUp(self):
        self.xhs_enabled_patch = mock.patch.dict(os.environ, {"MATRIX_XHS_ENABLED": "1"})
        self.xhs_enabled_patch.start()
        self.addCleanup(self.xhs_enabled_patch.stop)

    def make_handler(self, payload):
        body = json.dumps(payload).encode("utf-8")
        handler = object.__new__(self.api.Handler)
        handler.path = "/api/xhs-note-replacement/save-draft"
        handler.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        handler.rfile = io.BytesIO(body)
        return handler

    def test_save_draft_rejects_job_without_real_replacement_images(self):
        job = {
            "id": "xnr_1234567890abcdef12345678",
            "templateId": "tpl-1",
            "template": {"imageSlots": [{"index": 1, "role": "cover", "sourceFile": "01.jpg"}]},
            "slotMappings": [
                {
                    "slotIndex": 1,
                    "slotRole": "cover",
                    "source": "ai_placeholder",
                    "filePath": "",
                    "confirmationStatus": "pending",
                }
            ],
            "copyCandidates": [{"title": "标题", "body": "正文", "tags": ["#标签"]}],
            "selectedCopyIndex": 0,
        }
        handler = self.make_handler({"jobId": job["id"]})
        saved_libraries = []
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                mock.patch.object(self.api, "MATERIALS_DIR", temp_dir), \
                mock.patch.object(self.api.xhs_note_replacement, "load_job", return_value=job), \
                mock.patch.object(self.api, "load_library", return_value=[]), \
                mock.patch.object(self.api, "save_library", side_effect=lambda lib: saved_libraries.append(lib)), \
                mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
            status, payload = handler.do_POST()

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "xhs_note_replacement_missing_images")
        self.assertEqual(saved_libraries, [])

    def test_save_draft_falls_back_when_metadata_copy_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            source = os.path.join(temp_dir, "中文替换图.png")
            Image.new("RGB", (2, 2), (255, 0, 0)).save(source)
            job = {
                "id": "xnr_1234567890abcdef12345678",
                "templateId": "tpl-1",
                "template": {
                    "imageSlots": [{"index": 1, "role": "cover", "sourceFile": "01.jpg"}],
                    "originalCopy": {"title": "原标题", "body": "原正文", "tags": ["#原标签"]},
                },
                "slotMappings": [
                    {
                        "slotIndex": 1,
                        "slotRole": "cover",
                        "source": "asset",
                        "filePath": source,
                        "confirmationStatus": "confirmed",
                    }
                ],
                "copyCandidates": [{"title": "方案标题", "body": "方案正文", "tags": ["#标签"]}],
                "selectedCopyIndex": 0,
            }
            handler = self.make_handler({"jobId": job["id"]})
            saved_libraries = []
            saved_jobs = []
            material_dir = os.path.join(temp_dir, "materials")

            with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                    mock.patch.object(self.api, "MATERIALS_DIR", material_dir), \
                    mock.patch.object(self.api.xhs_note_replacement, "load_job", return_value=job), \
                    mock.patch.object(self.api.xhs_note_replacement, "save_job", side_effect=lambda _data_dir, saved: saved_jobs.append(saved)), \
                    mock.patch.object(self.api, "load_library", return_value=[]), \
                    mock.patch.object(self.api, "save_library", side_effect=lambda lib: saved_libraries.append(lib)), \
                    mock.patch.object(self.api.shutil, "copy2", side_effect=OSError("metadata copy failed")), \
                    mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
                status, payload = handler.do_POST()

            self.assertEqual(status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(len(saved_libraries), 1)
            self.assertEqual(saved_libraries[0][0]["files"], ["01_中文替换图.png"])
            self.assertTrue(os.path.isfile(os.path.join(material_dir, payload["id"], "01_中文替换图.png")))
            self.assertEqual(saved_jobs[0]["status"], "draft")

    def test_save_draft_applies_edited_copy_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from PIL import Image

            source = os.path.join(temp_dir, "replace.png")
            Image.new("RGB", (2, 2), (0, 255, 0)).save(source)
            job = {
                "id": "xnr_1234567890abcdef12345678",
                "templateId": "tpl-1",
                "template": {
                    "imageSlots": [{"index": 1, "role": "cover", "sourceFile": "01.jpg"}],
                    "originalCopy": {"title": "Original", "body": "Original body", "tags": ["#original"]},
                },
                "slotMappings": [
                    {
                        "slotIndex": 1,
                        "slotRole": "cover",
                        "source": "asset",
                        "filePath": source,
                        "confirmationStatus": "confirmed",
                    }
                ],
                "copyCandidates": [
                    {"title": "Plan A", "body": "Body A", "tags": ["#a"]},
                    {"title": "Plan B", "body": "Body B", "tags": ["#b"]},
                ],
                "selectedCopyIndex": 0,
            }
            handler = self.make_handler({
                "jobId": job["id"],
                "selectedCopyIndex": 1,
                "copyOverride": {
                    "title": "Edited title",
                    "body": "Edited body",
                    "tags": ["#edited", "second"],
                },
            })
            saved_libraries = []
            saved_jobs = []
            material_dir = os.path.join(temp_dir, "materials")

            with mock.patch.object(self.api, "ensure_agent_request", return_value=True), \
                    mock.patch.object(self.api, "MATERIALS_DIR", material_dir), \
                    mock.patch.object(self.api.xhs_note_replacement, "load_job", return_value=job), \
                    mock.patch.object(self.api.xhs_note_replacement, "save_job", side_effect=lambda _data_dir, saved: saved_jobs.append(saved)), \
                    mock.patch.object(self.api, "load_library", return_value=[]), \
                    mock.patch.object(self.api, "save_library", side_effect=lambda lib: saved_libraries.append(lib)), \
                    mock.patch.object(self.api, "json_response", side_effect=lambda _handler, payload, status=200: (status, payload)):
                status, payload = handler.do_POST()

            self.assertEqual(status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["material"]["title"], "Edited title")
            self.assertEqual(payload["material"]["body"], "Edited body")
            self.assertEqual(payload["material"]["tags"], ["#edited", "#second"])
            self.assertEqual(saved_libraries[0][0]["title"], "Edited title")
            self.assertEqual(saved_jobs[0]["copyCandidates"][1]["title"], "Edited title")
            self.assertEqual(saved_jobs[0]["copyCandidates"][1]["tags"], ["#edited", "#second"])


class XhsNoteApiSourceTests(unittest.TestCase):
    def test_local_api_declares_xhs_note_replacement_routes(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, "backend", "api_server.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("/api/xhs-note-replacement/template", src)
        self.assertIn("/api/xhs-note-replacement/save-draft", src)


class XhsNoteLibraryMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = importlib.import_module("backend.api_server")
        cls.central = importlib.import_module("backend.central_server")

    def test_local_library_upload_metadata_preserves_image_note_copy_fields(self):
        meta = self.api.library_upload_metadata({
            "platform": "xhs",
            "body": "\u65b9\u6848\u6b63\u6587",
            "tags": '["#\u6807\u7b7e"]',
            "status": "draft",
            "localDraftMaterialId": "local-mid",
            "importedFromXhsNoteReplacement": "1",
        })

        self.assertEqual(meta["platform"], "xhs")
        self.assertEqual(meta["body"], "\u65b9\u6848\u6b63\u6587")
        self.assertEqual(meta["tags"], ["#\u6807\u7b7e"])
        self.assertEqual(meta["status"], "draft")
        self.assertEqual(meta["localDraftMaterialId"], "local-mid")
        self.assertTrue(meta["importedFromXhsNoteReplacement"])

    def test_central_material_payload_preserves_image_note_metadata_for_publish(self):
        state = {
            "library": [{
                "id": "central-mid",
                "orgId": "org-default",
                "title": "\u65b9\u6848\u6807\u9898",
                "type": "image_note",
                "files": ["01.png"],
                "platform": "xhs",
                "body": "\u65b9\u6848\u6b63\u6587",
                "tags": ["#\u6807\u7b7e"],
                "status": "draft",
                "localDraftMaterialId": "local-mid",
                "importedFromXhsNoteReplacement": True,
            }]
        }

        with mock.patch.object(self.central, "STATE", state):
            payload = self.central.material_payload("central-mid")

        self.assertEqual(payload["type"], "image_note")
        self.assertEqual(payload["platform"], "xhs")
        self.assertEqual(payload["body"], "\u65b9\u6848\u6b63\u6587")
        self.assertEqual(payload["tags"], ["#\u6807\u7b7e"])
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["localDraftMaterialId"], "local-mid")
        self.assertTrue(payload["importedFromXhsNoteReplacement"])


class XhsNotePublishGateTests(unittest.TestCase):
    def test_xhs_note_publish_feature_flag_defaults_true(self):
        self.assertTrue(note.publish_feature_enabled({}))
        self.assertFalse(note.publish_feature_enabled({"XHS_NOTE_PUBLISH_ENABLED": "0"}))
        self.assertFalse(note.publish_feature_enabled({"XHS_NOTE_PUBLISH_ENABLED": "false"}))
        self.assertTrue(note.publish_feature_enabled({"XHS_NOTE_PUBLISH_ENABLED": "1"}))

    def test_confirmed_xhs_image_note_is_publishable(self):
        material = {
            "type": "image_note",
            "platform": "xhs",
            "files": ["01.jpg"],
            "aiImageReview": {"pendingSlots": [], "confirmedSlots": [1]},
        }
        self.assertEqual(note.image_note_publish_blocker(material), "")

    def test_xhs_image_note_requires_files_and_platform(self):
        self.assertEqual(
            note.image_note_publish_blocker({"type": "image_note", "platform": "douyin", "files": ["01.jpg"]}),
            "xhs_note_platform_unsupported",
        )
        self.assertEqual(
            note.image_note_publish_blocker({"type": "image_note", "platform": "xhs", "files": []}),
            "no_files",
        )
    def test_xhs_image_note_rejects_blank_files(self):
        material = {"type": "image_note", "platform": "xhs", "files": ["", "  ", None]}
        self.assertEqual(note.image_note_publish_blocker(material), "no_files")

    def test_xhs_image_note_rejects_more_than_18_valid_files(self):
        material = {
            "type": "image_note",
            "platform": "xhs",
            "files": ["%02d.jpg" % index for index in range(19)] + ["", "  "],
        }
        self.assertEqual(note.image_note_publish_blocker(material), "xhs_note_too_many_images")

    def test_required_ai_image_review_requires_confirmed_slots(self):
        material = {
            "type": "image_note",
            "platform": "xhs",
            "files": ["01.jpg"],
            "aiImageReview": {"required": True, "pendingSlots": []},
        }
        self.assertEqual(note.image_note_publish_blocker(material), "xhs_note_ai_image_unconfirmed")

    def test_normalize_publish_tags_adds_hash_and_deduplicates(self):
        self.assertEqual(
            note.normalize_publish_tags(["本地门店", " #试驾 ", "##本地门店", "", None]),
            ["#本地门店", "#试驾"],
        )

    def test_apply_publish_result_marks_dry_run_without_published(self):
        material = {"id": "mat-1", "type": "image_note", "platform": "xhs", "published": 0, "status": "draft"}
        updated = note.apply_publish_result(
            material,
            {"ok": True, "filled": True, "published": False, "final_url": "https://creator.xiaohongshu.com/publish"},
            account_id="xhs-self",
            dry_run=True,
        )
        self.assertEqual(updated["status"], "draft")
        self.assertEqual(updated["published"], 0)
        self.assertTrue(updated["publishResult"]["dryRun"])

    def test_apply_publish_result_marks_live_publish_success(self):
        material = {"id": "mat-1", "type": "image_note", "platform": "xhs", "published": 0, "status": "draft"}
        updated = note.apply_publish_result(
            material,
            {"ok": True, "filled": True, "published": True, "final_url": "https://creator.xiaohongshu.com/publish"},
            account_id="xhs-self",
            dry_run=False,
        )
        self.assertEqual(updated["status"], "published")
        self.assertEqual(updated["published"], 1)
        self.assertEqual(updated["publishResult"]["accountId"], "xhs-self")
    def test_apply_publish_result_does_not_mark_published_when_ok_is_false(self):
        material = {"id": "mat-1", "type": "image_note", "platform": "xhs", "published": 0, "status": "draft"}
        updated = note.apply_publish_result(
            material,
            {"ok": False, "filled": True, "published": True},
            account_id="xhs-self",
            dry_run=False,
        )
        self.assertNotEqual(updated["status"], "published")
        self.assertEqual(updated["published"], 0)

    def test_unconfirmed_ai_image_has_specific_blocker(self):
        material = {"type": "image_note", "platform": "xhs", "files": ["01.jpg"], "aiImageReview": {"required": True, "pendingSlots": [1]}}
        self.assertEqual(note.image_note_publish_blocker(material), "xhs_note_ai_image_unconfirmed")

    def test_image_note_publish_no_longer_returns_v1_not_supported(self):
        material = {
            "type": "image_note",
            "platform": "xhs",
            "files": ["01.jpg"],
            "aiImageReview": {"pendingSlots": [], "confirmedSlots": [1]},
        }
        self.assertNotEqual(note.image_note_publish_blocker(material), "xhs_note_publish_not_supported")
class XhsNoteNativeUiTests(unittest.TestCase):
    def test_native_client_keeps_note_page_but_gates_nav_and_asset_filter(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, "backend", "matrix_native_client.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("class XhsNoteReplacementPage", src)
        self.assertNotIn("b_ai_fill", src)
        self.assertNotIn("generate_missing_images", src)
        self.assertNotIn("ai_fill", src)
        self.assertNotIn("AI \u5360\u4f4d\u56fe", src)
        self.assertIn("XHS_NOTE_NAV_ITEM", src)
        self.assertIn("if xhs_enabled() else []", src)
        asset_start = src.index("class AssetLibraryPage")
        asset_end = src.index("class ", asset_start + 1)
        asset_block = src[asset_start:asset_end]
        filter_start = asset_block.index("# 本地过滤")
        filter_end = asset_block.index("self.scroll = QtWidgets.QScrollArea()", filter_start)
        filter_block = asset_block[filter_start:filter_end]
        self.assertNotIn('"note_template"', filter_block)
        self.assertIn('elif kind == "note_template":', asset_block)
class XhsNoteFourImageSmokeTests(unittest.TestCase):
    def test_four_image_note_replacement_smoke_builds_draft_and_blocks_publish(self):
        self.assertTrue(hasattr(note, "smoke_four_image_replacement"), "missing four-image smoke helper")
        result = note.smoke_four_image_replacement()
        self.assertEqual(len(result["template"]["imageSlots"]), 4)
        self.assertEqual([slot["role"] for slot in result["template"]["imageSlots"]], ["cover", "product", "detail", "cta"])
        self.assertEqual(len(result["preview"]["slotMappings"]), 4)
        self.assertEqual(result["preview"]["aiSlotCount"], 2)
        self.assertEqual(len(result["preview"]["copyCandidates"]), 3)
        self.assertEqual(result["draft"]["type"], "image_note")
        self.assertEqual(result["draft"]["status"], "draft")
        self.assertEqual(result["publishBlocker"], "xhs_note_ai_image_unconfirmed")


class XhsNoteNativeFlowTests(unittest.TestCase):
    def test_native_collection_keeps_note_replace_entry_and_handoff_handler(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, "backend", "matrix_native_client.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("def note_replace", src)
        self.assertIn("self.b_note_replace.setVisible(xhs_enabled())", src)
        self.assertIn('submit_local_task("xhs.download", payload, 600)', src)
        self.assertIn('"c_note_replace"', src)
        self.assertIn('elif tag == "c_note_replace"', src)
        self.assertIn('BRIDGE.payload.emit("goto_nav", "🧩 图文同款")', src)
        self.assertIn('_xhs_note_material_from_download', src)
        self.assertIn("xhs_note_replace_start", src)
        self.assertIn("读取图文结构超时", src)
        self.assertIn("未找到图片素材，请先下载笔记", src)


class XhsNoteNativeDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.client = load_native_client()
        cls.app = cls.client.QtWidgets.QApplication.instance() or cls.client.QtWidgets.QApplication([])

    def setUp(self):
        self.client.BRIDGE = self.client.Bridge()

    def test_content_page_shows_note_replacement_button_by_default(self):
        page = self.client.ContentPage()
        try:
            button_texts = [
                button.text()
                for button in page.findChildren(self.client.QtWidgets.QPushButton)
            ]
            self.assertIn("\u56fe\u6587\u540c\u6b3e", button_texts)
            self.assertTrue(page.b_note_replace.isVisibleTo(page))
        finally:
            page.deleteLater()

    def test_content_page_hides_note_replacement_button_when_xhs_disabled(self):
        with mock.patch.dict(os.environ, {"MATRIX_XHS_ENABLED": "0"}, clear=False):
            page = self.client.ContentPage()
        try:
            self.assertFalse(page.b_note_replace.isVisibleTo(page))
        finally:
            page.deleteLater()

    def test_note_replace_rejects_non_xhs_link_without_submitting_a_task(self):
        page = self.client.ContentPage()
        try:
            page.url.setText("https://www.douyin.com/video/123")
            with mock.patch.object(self.client, "submit_local_task") as submit:
                page.note_replace()
            submit.assert_not_called()
            self.assertIn("\u4ec5\u652f\u6301\u5c0f\u7ea2\u4e66\u7b14\u8bb0", page.status.text())
        finally:
            page.deleteLater()

    def test_source_image_entries_filter_media_and_resolve_central_urls(self):
        self.assertTrue(
            hasattr(self.client, "_xhs_note_source_image_entries"),
            "native XHS note source-image resolver is missing",
        )
        entries = self.client._xhs_note_source_image_entries(
            {
                "id": "mat-xhs-1",
                "files": ["01.jpg", "clip.mp4", {"name": "02.PNG"}],
                "urls": [
                    "/api/library/file/mat-xhs-1/01.jpg",
                    "/api/library/file/mat-xhs-1/clip.mp4",
                    "/api/library/file/mat-xhs-1/02.PNG",
                ],
            },
            central_base="http://127.0.0.1:9080",
        )

        self.assertEqual([entry["name"] for entry in entries], ["01.jpg", "02.PNG"])
        self.assertEqual(
            [entry["url"] for entry in entries],
            [
                "http://127.0.0.1:9080/api/library/file/mat-xhs-1/01.jpg",
                "http://127.0.0.1:9080/api/library/file/mat-xhs-1/02.PNG",
            ],
        )

    def test_source_image_entries_accept_url_only_signed_images(self):
        entries = self.client._xhs_note_source_image_entries(
            {
                "files": [
                    {"url": "https://cdn.example/notes/03.webp?token=secret"},
                    {"url": "https://cdn.example/video/clip.mp4?token=secret"},
                ]
            }
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "03.webp")
        self.assertEqual(entries[0]["url"], "https://cdn.example/notes/03.webp?token=secret")

    def test_download_handoff_preserves_signed_url_when_file_item_has_name(self):
        signed_url = "https://cdn.example/notes/03.webp?token=signed"
        material = self.client._xhs_note_material_from_download(
            {
                "result": {
                    "material": {
                        "platform": "xhs",
                        "files": [{"name": "03.webp", "url": signed_url}],
                    }
                }
            }
        )

        self.assertEqual(material.get("files"), ["03.webp"])
        self.assertEqual(material.get("urls"), [signed_url])
        self.assertNotIn("token=signed", repr(material.get("files")))
        entries = self.client._xhs_note_source_image_entries(material)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "03.webp")
        self.assertEqual(entries[0]["url"], signed_url)

    def test_download_handoff_preserves_note_copy_and_source_download_path(self):
        material = self.client._xhs_note_material_from_download(
            {
                "result": {
                    "savePath": r"E:\Desktop\project\backend\datas\accounts\user-owner\media_datas\xhs_note-copy",
                    "note": {
                        "title": "原始标题",
                        "body": "原始正文",
                        "tags": ["#试驾", "#昆山"],
                    },
                    "files": [{"name": "01.webp", "url": "https://cdn.example/notes/01.webp"}],
                }
            },
            source_url="https://www.xiaohongshu.com/explore/note-copy",
        )

        self.assertEqual(
            material.get("sourceDownloadPath"),
            r"E:\Desktop\project\backend\datas\accounts\user-owner\media_datas\xhs_note-copy",
        )
        self.assertEqual(material.get("sourceUrl"), "https://www.xiaohongshu.com/explore/note-copy")
        self.assertEqual(material.get("title"), "原始标题")
        self.assertEqual(material.get("body"), "原始正文")
        self.assertEqual(material.get("tags"), ["#试驾", "#昆山"])

    def test_limited_source_image_reader_stops_when_stream_exceeds_limit(self):
        class Response:
            headers = {}

            def __init__(self):
                self.yielded = 0

            def iter_content(self, chunk_size=0):
                del chunk_size
                for chunk in (b"123456", b"abcdef", b"unused"):
                    self.yielded += 1
                    yield chunk

        response = Response()
        with self.assertRaisesRegex(RuntimeError, "image_response_too_large"):
            self.client._xhs_note_read_limited_response(response, max_bytes=10)
        self.assertEqual(response.yielded, 2)

    def test_external_signed_source_image_does_not_receive_central_auth_headers(self):
        page = self.client.XhsNoteReplacementPage()
        page.load_template = lambda: None

        class Response:
            content = b"not-an-image"

            @staticmethod
            def raise_for_status():
                return None

        with mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), mock.patch.object(
            self.client,
            "_headers",
            return_value={"X-Matrix-User-Token": "secret-token", "X-Matrix-Org-Id": "org-secret"},
        ), mock.patch.object(self.client.requests, "get", return_value=Response()) as request_get:
            self.client.BRIDGE.payload.emit(
                "xhs_note_replace_start",
                {
                    "material": {
                        "files": [{"url": "https://cdn.example/notes/03.webp?token=signed"}],
                    }
                },
            )
            self.app.processEvents()

        self.assertEqual(request_get.call_args.kwargs.get("headers"), {})
        self.assertTrue(request_get.call_args.kwargs.get("stream"))
        self.assertNotIn("allow_redirects", request_get.call_args.kwargs)
        page.deleteLater()

    def test_collection_handoff_reaches_note_page_and_starts_template_read(self):
        page = self.client.XhsNoteReplacementPage()
        template_reads = []
        page.load_template = lambda: template_reads.append(True)

        self.client.BRIDGE.payload.emit(
            "xhs_note_replace_start",
            {
                "material": {
                    "id": "mat-xhs-bridge",
                    "platform": "xhs",
                    "files": ["01.jpg", "02.jpg"],
                },
                "sourceUrl": "https://www.xiaohongshu.com/explore/bridge-note",
            },
        )
        self.app.processEvents()

        self.assertEqual(page.material_id.text(), "mat-xhs-bridge")
        self.assertEqual(page.source_url.text(), "https://www.xiaohongshu.com/explore/bridge-note")
        self.assertEqual(template_reads, [True])
        page.deleteLater()

    def test_content_download_result_navigates_and_reaches_prebuilt_note_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "01.png")
            image = self.client.QtGui.QImage(24, 32, self.client.QtGui.QImage.Format_RGB32)
            image.fill(self.client.QtGui.QColor("#16a34a"))
            self.assertTrue(image.save(image_path))

            content_page = self.client.ContentPage()
            note_page = self.client.XhsNoteReplacementPage()
            template_reads = []
            note_page.load_template = lambda: template_reads.append(True)

            class NavHarness:
                _nav_labels = {"🧩 图文同款": 0}
                _nav_names = []

                def __init__(self):
                    self.selected = []

                def _nav(self, index):
                    self.selected.append(index)

            nav = NavHarness()
            self.client.BRIDGE.payload.connect(
                lambda tag, data: self.client.MainWindow._goto_nav(nav, tag, data)
            )

            content_page._on(
                "c_note_replace",
                {
                    "url": "https://www.xiaohongshu.com/explore/navigation-note",
                    "task": {
                        "status": "done",
                        "result": {
                            "ok": True,
                            "material": {
                                "id": "mat-xhs-navigation",
                                "sourceDownloadPath": temp_dir,
                                "files": ["01.png"],
                            },
                        },
                    },
                },
            )
            self.app.processEvents()

            self.assertEqual(nav.selected, [0])
            self.assertEqual(note_page.material_id.text(), "mat-xhs-navigation")
            self.assertEqual(note_page.source_image_count.text(), "1 张")
            self.assertEqual(template_reads, [True])
            content_page.deleteLater()
            note_page.deleteLater()

    def test_collection_handoff_renders_downloaded_source_thumbnails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for index, color in enumerate(("#d946ef", "#22c55e"), start=1):
                image = self.client.QtGui.QImage(24, 32, self.client.QtGui.QImage.Format_RGB32)
                image.fill(self.client.QtGui.QColor(color))
                self.assertTrue(image.save(os.path.join(temp_dir, "%02d.png" % index)))

            page = self.client.XhsNoteReplacementPage()
            page.load_template = lambda: None
            self.client.BRIDGE.payload.emit(
                "xhs_note_replace_start",
                {
                    "material": {
                        "id": "mat-xhs-thumbs",
                        "platform": "xhs",
                        "sourceDownloadPath": temp_dir,
                        "files": ["01.png", "02.png"],
                    }
                },
            )
            self.app.processEvents()

            self.assertTrue(hasattr(page, "source_image_count"), "source image count is not rendered")
            self.assertTrue(hasattr(page, "source_image_layout"), "source thumbnail layout is not rendered")
            self.assertEqual(page.source_image_count.text(), "2 张")
            self.assertEqual(page.source_image_layout.count(), 2)
            self.assertEqual(page.source_image_layout.itemAt(0).widget().toolTip(), "")
            self.assertEqual(page.source_image_layout.itemAt(1).widget().toolTip(), "")
            page.deleteLater()

    def test_source_thumbnail_click_opens_the_matching_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "01.png")
            image = self.client.QtGui.QImage(24, 32, self.client.QtGui.QImage.Format_RGB32)
            image.fill(self.client.QtGui.QColor("#0ea5e9"))
            self.assertTrue(image.save(image_path))

            page = self.client.XhsNoteReplacementPage()
            page.load_template = lambda: None
            opened = []
            page._show_source_image = lambda entry: opened.append(entry.get("name"))
            self.client.BRIDGE.payload.emit(
                "xhs_note_replace_start",
                {"material": {"id": "mat-xhs-open", "sourceDownloadPath": temp_dir, "files": ["01.png"]}},
            )
            self.app.processEvents()

            page.source_image_layout.itemAt(0).widget().click()
            self.app.processEvents()
            self.assertEqual(opened, ["01.png"])
            page.deleteLater()

    def test_remote_source_image_is_fetched_and_rendered_with_auth_headers(self):
        image = self.client.QtGui.QImage(24, 32, self.client.QtGui.QImage.Format_RGB32)
        image.fill(self.client.QtGui.QColor("#f59e0b"))
        payload = self.client.QtCore.QByteArray()
        buffer = self.client.QtCore.QBuffer(payload)
        buffer.open(self.client.QtCore.QIODevice.WriteOnly)
        self.assertTrue(image.save(buffer, "PNG"))
        png_bytes = bytes(payload)

        class Response:
            content = png_bytes

            @staticmethod
            def raise_for_status():
                return None

        page = self.client.XhsNoteReplacementPage()
        page.load_template = lambda: None
        auth_headers = {"X-Matrix-User-Token": "user-token", "X-Matrix-Org-Id": "org-1"}
        with mock.patch.object(self.client, "CENTRAL", "https://central.example"), mock.patch.object(
            self.client, "_headers", return_value=auth_headers
        ), mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), mock.patch.object(
            self.client.requests, "get", return_value=Response()
        ) as request_get:
            self.client.BRIDGE.payload.emit(
                "xhs_note_replace_start",
                {
                    "material": {
                        "id": "mat-xhs-remote",
                        "files": ["01.png"],
                        "urls": ["https://central.example/api/library/file/mat-xhs-remote/01.png"],
                    }
                },
            )
            self.app.processEvents()

        self.assertEqual(page._source_image_bytes.get(1), png_bytes)
        self.assertFalse(page.source_image_layout.itemAt(0).widget().icon().isNull())
        request_get.assert_called_once()
        self.assertEqual(request_get.call_args.args[0], "https://central.example/api/library/file/mat-xhs-remote/01.png")
        self.assertEqual(request_get.call_args.kwargs.get("headers"), auth_headers)
        self.assertTrue(request_get.call_args.kwargs.get("stream"))
        self.assertFalse(request_get.call_args.kwargs.get("allow_redirects"))
        page.deleteLater()

    def test_template_slots_render_before_replacement_preview_exists(self):
        page = self.client.XhsNoteReplacementPage()
        page._job = {
            "template": {
                "imageSlots": [
                    {"index": 1, "role": "cover", "sourceFile": "01.jpg", "ratio": "3:4"},
                    {"index": 2, "role": "product", "sourceFile": "02.jpg", "ratio": "1:1"},
                ]
            }
        }
        page._preview = {}

        page._render_job()

        self.assertTrue(hasattr(page, "replacement_image_layout"))
        self.assertEqual(page.replacement_image_layout.count(), 2)
        self.assertEqual(page._replacement_slots[0]["slotRole"], "cover")
        self.assertEqual(page._replacement_slots[1]["slotRole"], "product")
        page.deleteLater()

    def test_replacement_page_uses_image_slots_not_path_textbox_or_debug_table(self):
        page = self.client.XhsNoteReplacementPage()

        self.assertTrue(hasattr(page, "source_path"))
        self.assertTrue(hasattr(page, "replacement_image_layout"))
        self.assertFalse(hasattr(page, "asset_paths"))
        self.assertFalse(hasattr(page, "slot_table"))
        buttons = [child.text() for child in page.findChildren(self.client.QtWidgets.QPushButton)]
        self.assertNotIn("AI生成缺图", buttons)
        self.assertFalse(hasattr(page, "b_ai_fill"))
        self.assertFalse(hasattr(page, "generate_missing_images"))
        labels = [child.text() for child in page.findChildren(self.client.QtWidgets.QLabel)]
        self.assertIn("标题（必填）", labels)
        self.assertIn("所在地（必填）", labels)
        self.assertIn("目标客户（必填）", labels)
        self.assertIn("卖点（可编辑）", labels)
        self.assertNotIn("AI 占位图必须人工确认后，后续版本才允许进入真实发布。", labels)
        page.deleteLater()

    def test_new_collection_handoff_clears_previous_note_and_replacement_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = self.client.QtGui.QImage(24, 32, self.client.QtGui.QImage.Format_RGB32)
            image.fill(self.client.QtGui.QColor("#ef4444"))
            self.assertTrue(image.save(os.path.join(temp_dir, "new.png")))

            page = self.client.XhsNoteReplacementPage()
            page.load_template = lambda: None
            page.material_id.setText("old-material")
            page.source_url.setText("https://www.xiaohongshu.com/explore/old")
            page.source_title.setText("旧标题")
            page.source_body.setPlainText("旧正文")
            page.source_tags.setText("#旧标签")
            page.biz_name.setText("旧业务")
            page.biz_region.setText("旧地区")
            page.biz_audience.setText("旧客户")
            page.biz_selling.setPlainText("旧卖点")
            page._replacement_slots = [{"filePath": "old-replacement.png"}]
            page._job = {"id": "old-job"}
            page._preview = {"copyCandidates": [{"title": "旧方案"}]}
            page.copy_view.setPlainText("旧文案")
            old_request_id = page._template_req_id

            page._start_from_collection(
                {
                    "material": {
                        "id": "new-material",
                        "sourceDownloadPath": temp_dir,
                        "title": "新标题",
                        "body": "第一卖点\n第二卖点 #旧标签",
                        "tags": ["#旧标签"],
                        "files": ["new.png"],
                    },
                    "sourceUrl": "https://www.xiaohongshu.com/explore/new",
                }
            )

            self.assertGreater(page._template_req_id, old_request_id)
            self.assertEqual(page.material_id.text(), "new-material")
            self.assertEqual(page.source_path.text(), temp_dir)
            self.assertEqual(page.source_url.text(), "https://www.xiaohongshu.com/explore/new")
            self.assertEqual(page.source_title.text(), "新标题")
            self.assertEqual(page.source_body.toPlainText(), "第一卖点\n第二卖点 #旧标签")
            self.assertEqual(page.source_tags.text(), "#旧标签")
            self.assertEqual(page.biz_name.text(), "")
            self.assertEqual(page.biz_region.text(), "")
            self.assertEqual(page.biz_audience.text(), "")
            self.assertEqual(page.biz_selling.toPlainText(), "")
            self.assertEqual(page._job, {})
            self.assertEqual(page._preview, {})
            self.assertEqual(page._replacement_slots, [])
            self.assertEqual(page.copy_view.toPlainText(), "")
            self.assertEqual(page.source_image_count.text(), "1 张")
            page.deleteLater()

    def test_collection_handoff_ai_prefills_editable_business_fields(self):
        page = self.client.XhsNoteReplacementPage()
        page.load_template = lambda: None
        ai_payload = json.dumps({
            "title": "昆山家用车怎么选更稳",
            "region": "昆山",
            "audience": "准备买家用车的人",
            "sellingPoints": ["省油", "到店试驾", "保养省心"],
        }, ensure_ascii=False)

        with mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                mock.patch.object(self.client, "lk888_chat", return_value=ai_payload):
            page._start_from_collection({
                "material": {
                    "id": "new-material",
                    "title": "原笔记标题不能当卖点",
                    "body": "原文说到省油、通勤、到店试驾，适合家用车客户。",
                    "tags": ["#昆山", "#家用车"],
                    "files": ["new.png"],
                },
                "sourceUrl": "https://www.xiaohongshu.com/explore/new",
            })
            self.app.processEvents()

        self.assertEqual(page.biz_name.text(), "昆山家用车怎么选更稳")
        self.assertEqual(page.biz_region.text(), "昆山")
        self.assertEqual(page.biz_audience.text(), "准备买家用车的人")
        selling_text = page.biz_selling.toPlainText()
        self.assertIn("省油", selling_text)
        self.assertIn("到店试驾", selling_text)
        self.assertNotIn("原笔记标题不能当卖点", selling_text)
        page.biz_name.setText("用户改过的标题")
        self.assertEqual(page.biz_name.text(), "用户改过的标题")
        page.deleteLater()

    def test_collection_handoff_ai_prefill_title_fits_xhs_limit(self):
        page = self.client.XhsNoteReplacementPage.__new__(self.client.XhsNoteReplacementPage)
        raw = json.dumps({
            "title": "这是一个明显超过二十个字的小红书图文同款标题",
            "region": "",
            "audience": "本地客户",
            "sellingPoints": ["省心"],
        }, ensure_ascii=False)

        parsed = page._parse_ai_business_prefill(raw, {})

        self.assertLessEqual(len(parsed["title"]), 20)
        self.assertTrue(parsed["title"])

    def test_collection_handoff_ai_leaves_unknown_region_blank(self):
        page = self.client.XhsNoteReplacementPage()
        page.load_template = lambda: None
        ai_payload = json.dumps({
            "title": "家用车选择前先看这几点",
            "region": "",
            "audience": "准备买家用车的人",
            "sellingPoints": ["省油", "通勤方便"],
        }, ensure_ascii=False)

        with mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                mock.patch.object(self.client, "lk888_chat", return_value=ai_payload):
            page._start_from_collection({
                "material": {
                    "id": "new-material",
                    "title": "没有地区的原笔记",
                    "body": "只提到省油和通勤，没有城市或门店位置。",
                    "tags": ["#家用车"],
                    "files": ["new.png"],
                },
            })
            self.app.processEvents()

        self.assertEqual(page.biz_name.text(), "家用车选择前先看这几点")
        self.assertEqual(page.biz_region.text(), "")
        self.assertEqual(page.biz_audience.text(), "准备买家用车的人")
        self.assertIn("省油", page.biz_selling.toPlainText())
        page.deleteLater()

    def test_new_collection_handoff_ignores_old_preview_confirm_and_save_responses(self):
        page = self.client.XhsNoteReplacementPage()
        page.load_template = lambda: None
        old_generation = getattr(page, "_request_generation", 0)

        page._start_from_collection(
            {
                "material": {"id": "new-material", "files": ["new.jpg"]},
                "sourceUrl": "https://www.xiaohongshu.com/explore/new",
            }
        )
        new_generation = getattr(page, "_request_generation", 0)
        self.assertGreater(new_generation, old_generation)
        expected_status = page.status.text()

        for action in ("preview", "confirm_ai", "save"):
            page._on(
                "xhs_note_replace",
                {
                    "action": action,
                    "generation": old_generation,
                    "code": 200,
                    "data": {
                        "ok": True,
                        "job": {"id": "old-job"},
                        "preview": {"copyCandidates": [{"title": "old-copy"}]},
                    },
                },
            )
            self.assertEqual(page._job, {})
            self.assertEqual(page._preview, {})
            self.assertEqual(page.status.text(), expected_status)
        page.deleteLater()

    def test_replacement_slots_fill_multiple_files_in_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = []
            for name, color in (("cover.png", "#0284c7"), ("product.png", "#16a34a")):
                image = self.client.QtGui.QImage(24, 32, self.client.QtGui.QImage.Format_RGB32)
                image.fill(self.client.QtGui.QColor(color))
                path = os.path.join(temp_dir, name)
                self.assertTrue(image.save(path))
                paths.append(path)

            page = self.client.XhsNoteReplacementPage()
            page._job = {
                "template": {
                    "imageSlots": [
                        {"index": 1, "role": "cover", "sourceFile": "01.jpg", "ratio": "3:4"},
                        {"index": 2, "role": "product", "sourceFile": "02.jpg", "ratio": "1:1"},
                        {"index": 3, "role": "cta", "sourceFile": "03.jpg", "ratio": "3:4"},
                    ]
                }
            }
            page._preview = {}
            page._render_job()
            self.assertEqual([slot["button"].toolTip() for slot in page._replacement_slots], ["", "", ""])

            page._fill_replacement_paths(paths, start_slot=2)

            self.assertEqual([slot.get("filePath") for slot in page._replacement_slots], ["", paths[0], paths[1]])
            self.assertEqual([slot["button"].toolTip() for slot in page._replacement_slots], ["", "", ""])
            page.deleteLater()

    def test_generate_preview_requires_required_fields_and_all_replacement_images(self):
        page = self.client.XhsNoteReplacementPage()
        page._job = {
            "id": "xnr_1234567890abcdef12345678",
            "template": {"imageSlots": [{"index": 1, "role": "cover", "sourceFile": "01.jpg"}]},
        }
        page._render_job()

        page.generate_preview()

        self.assertIn("请填写标题、所在地和目标客户", page.status.text())
        page.biz_name.setText("标题")
        page.biz_region.setText("昆山")
        page.biz_audience.setText("家用车客户")
        page.generate_preview()
        self.assertIn("请先补齐所有替换图片", page.status.text())
        page.deleteLater()

    def test_save_draft_captures_job_id_before_background_work(self):
        page = self.client.XhsNoteReplacementPage()
        page._job = {"id": "job-old"}
        queued = []
        requests_seen = []

        def local_api(method, path, body=None, timeout=60):
            requests_seen.append((method, path, dict(body or {}), timeout))
            return 200, {"ok": True}

        page._local_api = local_api
        with mock.patch.object(self.client, "run_bg", side_effect=lambda fn: queued.append(fn)):
            page.save_draft()

        self.assertEqual(len(queued), 1)
        page._job = {"id": "job-new"}
        queued[0]()

        self.assertEqual(requests_seen[0][2].get("jobId"), "job-old")
        page.deleteLater()

    def test_save_draft_uses_selected_copy_index(self):
        page = self.client.XhsNoteReplacementPage()
        page._job = {"id": "job-old"}
        page.copy_selector.addItems(["方案一", "方案二", "方案三"])
        page.copy_selector.setCurrentIndex(2)
        queued = []
        requests_seen = []

        def local_api(method, path, body=None, timeout=60):
            requests_seen.append((method, path, dict(body or {}), timeout))
            return 200, {"ok": True}

        page._local_api = local_api
        with mock.patch.object(self.client, "run_bg", side_effect=lambda fn: queued.append(fn)):
            page.save_draft()

        self.assertEqual(len(queued), 1)
        queued[0]()

        self.assertEqual(requests_seen[0][2].get("selectedCopyIndex"), 2)
        page.deleteLater()

    def test_template_summary_hides_technical_ids(self):
        page = self.client.XhsNoteReplacementPage()
        page._job = {
            "id": "job-old",
            "template": {
                "id": "tpl_5de16fff67814fae840789ad",
                "sourceNoteId": "6a5b797300000000110115b0",
                "imageSlots": [{"index": 1}, {"index": 2}],
            },
        }

        page._render_job()

        summary = page.template_summary.text()
        self.assertNotIn("tpl_5de16fff67814fae840789ad", summary)
        self.assertNotIn("6a5b797300000000110115b0", summary)
        self.assertNotIn("模板：", summary)
        self.assertNotIn("来源笔记：", summary)
        self.assertIn("2", summary)
        page.deleteLater()

    def test_save_draft_sends_edited_selected_copy(self):
        page = self.client.XhsNoteReplacementPage()
        page._job = {
            "id": "job-old",
            "template": {"imageSlots": []},
            "copyCandidates": [
                {"title": "Plan A", "body": "Body A", "tags": ["#a"]},
                {"title": "Plan B", "body": "Body B", "tags": ["#b"]},
            ],
        }
        page._render_job()
        page.copy_title.setText("Edited A")
        page.copy_view.setPlainText("Edited body A")
        page.copy_tags.setText("#editedA")
        page.copy_selector.setCurrentIndex(1)
        page.copy_title.setText("Edited B")
        page.copy_view.setPlainText("Edited body B")
        page.copy_tags.setText("#editedB #second")
        queued = []
        requests_seen = []

        def local_api(method, path, body=None, timeout=60):
            requests_seen.append((method, path, dict(body or {}), timeout))
            return 200, {"ok": True}

        page._local_api = local_api
        with mock.patch.object(self.client, "run_bg", side_effect=lambda fn: queued.append(fn)):
            page.save_draft()

        self.assertEqual(len(queued), 1)
        queued[0]()

        request_body = requests_seen[0][2]
        self.assertEqual(request_body.get("selectedCopyIndex"), 1)
        self.assertEqual(request_body.get("copyOverride"), {
            "title": "Edited B",
            "body": "Edited body B",
            "tags": ["#editedB", "#second"],
        })
        page.copy_selector.setCurrentIndex(0)
        self.assertEqual(page.copy_title.text(), "Edited A")
        self.assertEqual(page.copy_view.toPlainText(), "Edited body A")
        page.deleteLater()

    def test_save_draft_syncs_saved_material_to_central_library(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            material_dir = os.path.join(temp_dir, "materials", "local-mid")
            os.makedirs(material_dir, exist_ok=True)
            image_path = os.path.join(material_dir, "01.png")
            with open(image_path, "wb") as fh:
                fh.write(b"png")

            page = self.client.XhsNoteReplacementPage()
            page._job = {"id": "job-old"}
            queued = []
            uploads = []

            def local_api(method, path, body=None, timeout=60):
                return 200, {
                    "ok": True,
                    "id": "local-mid",
                    "material": {
                        "id": "local-mid",
                        "title": "\u65b9\u6848\u6807\u9898",
                        "type": "image_note",
                        "platform": "xhs",
                        "body": "\u65b9\u6848\u6b63\u6587",
                        "tags": ["#\u6807\u7b7e"],
                        "files": ["01.png"],
                    },
                }

            def fake_upload(paths, title, mtype="video", metadata=None):
                uploads.append((list(paths), title, mtype, dict(metadata or {})))
                return 200, {"ok": True, "id": "central-mid"}

            page._local_api = local_api
            with mock.patch.object(self.client, "run_bg", side_effect=lambda fn: queued.append(fn)), \
                    mock.patch.object(self.client, "data_dir", return_value=temp_dir), \
                    mock.patch.object(self.client, "upload_materials", side_effect=fake_upload):
                page.save_draft()
                queued[0]()

            self.assertEqual(uploads, [(
                [image_path],
                "\u65b9\u6848\u6807\u9898",
                "image_note",
                {
                    "platform": "xhs",
                    "body": "\u65b9\u6848\u6b63\u6587",
                    "tags": ["#\u6807\u7b7e"],
                    "status": "draft",
                    "localDraftMaterialId": "local-mid",
                },
            )])
            page.deleteLater()

    def test_save_draft_registers_note_template_asset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            material_dir = os.path.join(temp_dir, "materials", "local-mid")
            os.makedirs(material_dir, exist_ok=True)
            image_path = os.path.join(material_dir, "01.png")
            with open(image_path, "wb") as fh:
                fh.write(b"png")

            page = self.client.XhsNoteReplacementPage()
            page._job = {"id": "job-old"}
            queued = []
            added_assets = []

            def local_api(method, path, body=None, timeout=60):
                return 200, {
                    "ok": True,
                    "id": "local-mid",
                    "material": {
                        "id": "local-mid",
                        "title": "\u65b9\u6848\u6807\u9898",
                        "type": "image_note",
                        "platform": "xhs",
                        "body": "\u65b9\u6848\u6b63\u6587",
                        "tags": ["#\u6807\u7b7e"],
                        "sourceTitle": "\u539f\u7b14\u8bb0\u6807\u9898",
                        "sourceBody": "\u539f\u7b14\u8bb0\u6b63\u6587",
                        "sourceTags": ["#\u539f\u6807\u7b7e"],
                        "replacementJobId": "xnr_1234567890abcdef12345678",
                        "sourceTemplateId": "tpl-1",
                        "importedFromXhsNoteReplacement": True,
                        "files": ["01.png"],
                    },
                    "job": {
                        "id": "xnr_1234567890abcdef12345678",
                        "templateId": "tpl-1",
                        "template": {
                            "id": "tpl-1",
                            "sourceUrl": "https://www.xiaohongshu.com/explore/abc",
                            "sourceNoteId": "abc",
                            "imageSlots": [{"index": 1, "role": "cover", "sourceFile": "old.jpg"}],
                        },
                    },
                }

            def fake_add(path, kind=None, prompt="", source="", category="", thumbnail="", preview=""):
                added_assets.append({
                    "path": path,
                    "kind": kind,
                    "prompt": prompt,
                    "source": source,
                    "category": category,
                    "thumbnail": thumbnail,
                    "preview": preview,
                })
                return {"id": "as-template", "kind": kind}

            page._local_api = local_api
            with mock.patch.object(self.client, "run_bg", side_effect=lambda fn: queued.append(fn)), \
                    mock.patch.object(self.client, "data_dir", return_value=temp_dir), \
                    mock.patch.object(self.client, "upload_materials", return_value=(200, {"ok": True, "id": "central-mid"})), \
                    mock.patch.object(self.client, "add_asset", side_effect=fake_add):
                page.save_draft()
                queued[0]()

            self.assertEqual(len(added_assets), 1)
            asset = added_assets[0]
            self.assertEqual(asset["kind"], "note_template")
            self.assertEqual(asset["source"], "图文同款")
            self.assertEqual(asset["category"], "图文模板")
            self.assertEqual(asset["thumbnail"], image_path)
            self.assertTrue(os.path.isfile(asset["path"]))
            with open(asset["path"], encoding="utf-8") as handle:
                template_asset = json.load(handle)
            self.assertEqual(template_asset["material"]["title"], "\u65b9\u6848\u6807\u9898")
            self.assertEqual(template_asset["material"]["body"], "\u65b9\u6848\u6b63\u6587")
            self.assertEqual(template_asset["material"]["tags"], ["#\u6807\u7b7e"])
            self.assertEqual(template_asset["source"]["url"], "https://www.xiaohongshu.com/explore/abc")
            self.assertEqual(template_asset["template"]["imageSlots"][0]["role"], "cover")
            page.deleteLater()
