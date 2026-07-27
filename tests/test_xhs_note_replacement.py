import os
import tempfile
import unittest

from backend import xhs_note_replacement as note


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
class XhsNoteApiSourceTests(unittest.TestCase):
    def test_local_api_declares_xhs_note_replacement_routes(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, "backend", "api_server.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("/api/xhs-note-replacement/template", src)
        self.assertIn("/api/xhs-note-replacement/save-draft", src)
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
class XhsNoteWebUiTests(unittest.TestCase):
    def test_frontend_has_two_entry_points_page_and_filter(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, "frontend", "index.html"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("openXhsNoteReplaceFromResult", src)
        self.assertIn("openXhsNoteReplaceFromMaterial", src)
        self.assertIn("xhsNoteGeneratePreview", src)
        self.assertIn("xhsNoteSaveDraft", src)
        self.assertIn("图文同款", src)
class XhsNoteNativeUiTests(unittest.TestCase):
    def test_native_client_has_note_replacement_nav_and_asset_template_filter(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, "backend", "matrix_native_client.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("class XhsNoteReplacementPage", src)
        self.assertIn('(" 图文同款", lambda: XhsNoteReplacementPage())'.replace("\u0001", "🧩"), src)
        self.assertIn('("", "图文模板"'.replace("\u0001", "note_template"), src)
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
    def test_native_collection_has_one_click_note_replace_and_timeout_errors(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, "backend", "matrix_native_client.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("self.b_note_replace", src)
        self.assertIn("def note_replace", src)
        self.assertIn('"c_note_replace"', src)
        self.assertIn('elif tag == "c_note_replace"', src)
        self.assertIn('BRIDGE.payload.emit("goto_nav", "🧩 图文同款")', src)
        self.assertIn('_xhs_note_material_from_download', src)
        self.assertIn("xhs_note_replace_start", src)
        self.assertIn("读取图文结构超时", src)
        self.assertIn("未找到图片素材，请先下载笔记", src)
