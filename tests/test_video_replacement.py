from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_client():
    spec = importlib.util.spec_from_file_location("matrix_native_client_for_video_replacement", CLIENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class VideoReplacementHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client()

    def setUp(self):
        self.try_charge_patch = mock.patch.object(self.client, "try_charge", return_value=(True, None))
        self.refund_cap_patch = mock.patch.object(self.client, "refund_cap", return_value=(True, None))
        self.try_charge_patch.start()
        self.refund_cap_patch.start()
        self.addCleanup(self.try_charge_patch.stop)
        self.addCleanup(self.refund_cap_patch.stop)

    def test_comic_extract_task_ids_keeps_start_and_end_order(self):
        payload = {"data": {"task_ids": ["frame-start", "frame-end"]}}

        self.assertEqual(
            self.client._comic_extract_task_ids(payload),
            ["frame-start", "frame-end"],
        )
        self.assertEqual(self.client._comic_extract_task_id(payload), "frame-start")

    def test_comic_adapter_single_frame_payload_uses_frame_index(self):
        adapter = self.client.ComicProjectAdapter.__new__(self.client.ComicProjectAdapter)
        adapter.comic_json = mock.Mock(return_value={"data": {"task_id": "frame-task"}})

        adapter.submit_storyboard_image(201, {"comicProjectId": 88}, {"index": 1}, frame_index=2)

        body = adapter.comic_json.call_args.args[2]
        self.assertEqual(body["frameIndex"], 2)
        self.assertEqual(body["frame_index"], 2)

    def test_comic_adapter_image_payload_omits_audio_for_initial_and_single_frames(self):
        def contains_audio_field(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if any(marker in str(key).lower() for marker in ("audio", "voice", "tts")):
                        return True
                    if contains_audio_field(child):
                        return True
            if isinstance(value, list):
                return any(contains_audio_field(child) for child in value)
            return False

        for frame_index in (None, 1, 2):
            with self.subTest(frame_index=frame_index):
                adapter = self.client.ComicProjectAdapter.__new__(self.client.ComicProjectAdapter)
                adapter.comic_json = mock.Mock(return_value={"data": {"task_id": "frame-task"}})
                job = {"comicProjectId": 88, "voiceId": "voice-42"}
                segment = {
                    "index": 1,
                    "script": "current script",
                    "startFrameUrl": "https://cdn.example/start.png",
                    "referenceImageUrls": ["https://cdn.example/reference.png"],
                }

                adapter.submit_storyboard_image(201, job, segment, frame_index=frame_index)

                body = adapter.comic_json.call_args.args[2]
                self.assertTrue(body["prompt"].startswith(
                    self.client._comic_visual_prompt_text(segment, job=job)
                ))
                self.assertIn("gpt-image-2", body["prompt"])
                self.assertIn("彩铅", body["prompt"])
                self.assertIn("https://cdn.example/start.png", body["reference_image_urls"])
                self.assertIn("https://cdn.example/reference.png", body["image_urls"])
                self.assertFalse(contains_audio_field(body))
                if frame_index is None:
                    self.assertNotIn("frameIndex", body)
                    self.assertNotIn("frame_index", body)
                else:
                    self.assertEqual(body["frameIndex"], frame_index)
                    self.assertEqual(body["frame_index"], frame_index)

    def test_comic_adapter_image_post_keeps_current_bindings_and_visual_fields_only(self):
        adapter = self.client.ComicProjectAdapter.__new__(self.client.ComicProjectAdapter)
        adapter.comic_json = mock.Mock(return_value={"data": {"task_id": "frame-task"}})
        job = {
            "comicProjectId": 88,
            "model": "current-video-model",
            "aspectRatio": "16:9",
            "voiceId": "voice-must-not-leak",
            "audioMode": "tts",
            "duration": 12,
            "comicAssets": {
                "characters": [{"id": "character-current", "voice": "nested-voice"}],
                "scenes": [{"id": "scene-current", "duration": 8}],
                "props": [{"id": "prop-current", "ttsVoice": "nested-tts"}],
            },
        }
        segment = {
            "index": 3,
            "script": "current dialogue",
            "visualPrompt": "current visual prompt",
            "flowchartUrl": "https://cdn.example/flow.png",
            "startFrameUrl": "https://cdn.example/start.png",
            "endFrameUrl": "https://cdn.example/end.png",
            "keyframeUrl": "https://cdn.example/keyframe.png",
            "referenceImageUrls": ["https://cdn.example/reference-a.png", "https://cdn.example/reference-b.png"],
            "audioDurationSeconds": 9,
        }

        adapter.submit_storyboard_image(201, job, segment, frame_index=2)

        method, endpoint, body, timeout = adapter.comic_json.call_args.args
        prompt = self.client._comic_visual_prompt_text(segment, job=job)
        references = [
            "https://cdn.example/flow.png",
            "https://cdn.example/start.png",
            "https://cdn.example/end.png",
            "https://cdn.example/keyframe.png",
            "https://cdn.example/reference-a.png",
            "https://cdn.example/reference-b.png",
        ]
        self.assertEqual((method, endpoint, timeout), (
            "POST", "/api/v1/comic-drama/storyboards/201/generate-image", 120,
        ))
        self.assertEqual(body.get("characters"), ["character-current"])
        self.assertEqual(body.get("character_ids"), ["character-current"])
        self.assertEqual(body.get("scene_id"), "scene-current")
        self.assertEqual(body.get("props"), ["prop-current"])
        self.assertEqual(body.get("prop_ids"), ["prop-current"])
        self.assertEqual({key: body[key] for key in (
            "workflow_mode", "video_model", "aspect_ratio", "force_regenerate",
            "keyframes_video_prompt", "video_prompt", "prompt", "reference_image_urls",
            "image_urls", "project_id", "projectId", "description", "camera_movement",
            "frameIndex", "frame_index",
        )}, {
            "workflow_mode": "keyframes",
            "video_model": "current-video-model",
            "aspect_ratio": "16:9",
            "force_regenerate": True,
            "keyframes_video_prompt": prompt,
            "video_prompt": prompt,
            "prompt": prompt,
            "reference_image_urls": references,
            "image_urls": references,
            "project_id": 88,
            "projectId": 88,
            "description": prompt,
            "camera_movement": "静态镜头",
            "frameIndex": 2,
            "frame_index": 2,
        })

        def forbidden_keys(value):
            found = []
            if isinstance(value, dict):
                for key, child in value.items():
                    if any(marker in str(key).lower() for marker in ("audio", "voice", "tts", "duration")):
                        found.append(str(key))
                    found.extend(forbidden_keys(child))
            elif isinstance(value, list):
                for child in value:
                    found.extend(forbidden_keys(child))
            return found

        self.assertEqual(forbidden_keys(body), [])

    def test_comic_adapter_video_post_keeps_endpoint_and_adds_duration_asset_contract(self):
        adapter = self.client.ComicProjectAdapter.__new__(self.client.ComicProjectAdapter)
        adapter.comic_json = mock.Mock(return_value={"data": {"task_id": "video-task"}})
        job = {
            "comicProjectId": 88,
            "model": "current-video-model",
            "aspectRatio": "16:9",
            "audioMode": "tts",
            "voiceId": "current-voice",
        }
        segment = {
            "script": "current dialogue",
            "visualPrompt": "current visual prompt",
            "videoDurationSec": 12,
            "startFrameUrl": "https://cdn.example/start.png",
            "endFrameUrl": "https://cdn.example/end.png",
            "referenceImageUrls": ["https://cdn.example/reference.png"],
        }

        adapter.submit_storyboard_video(201, job, segment)

        prompt = self.client._comic_visual_prompt_text(segment, job=job)
        references = [
            "https://cdn.example/start.png",
            "https://cdn.example/end.png",
        ]
        adapter.comic_json.assert_called_once_with(
            "POST",
            "/api/v1/comic-drama/storyboards/201/generate-video",
            {
                "workflow_mode": "keyframes",
                "video_model": "current-video-model",
                "aspect_ratio": "16:9",
                "force_regenerate": True,
                "auto_match_audio_duration": True,
                "audio_mode": "tts",
                "duration": 12,
                "video_duration": 12,
                "videoDuration": 12,
                "keyframes_video_prompt": prompt,
                "video_prompt": prompt,
                "prompt": prompt,
                "reference_image_urls": references,
                "image_urls": references,
                "character_reference_images": [],
                "scene_reference_images": [],
                "prop_reference_images": [],
                "subject_reference_images": [],
                "negative_prompt": "不要生成字幕、对白文字、台词文字、促销文字；不要复刻原视频人物外观、原视频产品、原视频道具或原视频场景。",
                "audio_prompt": {"dialogue": {"text": "current dialogue", "voice": "current-voice"}},
                "project_id": 88,
                "projectId": 88,
            },
            120,
        )

    def test_comic_video_payload_prefers_current_frames_and_excludes_stale_flowchart(self):
        segment = {
            "script": "current dialogue",
            "flowchartUrl": "https://cdn.example/stale-flowchart.png",
            "startFrameUrl": "https://cdn.example/current-start.png",
            "endFrameUrl": "https://cdn.example/current-end.png",
            "keyframeUrl": "https://cdn.example/stale-keyframe.png",
            "referenceImageUrls": [
                "https://cdn.example/supplemental.png",
                "https://cdn.example/current-start.png",
            ],
        }

        video_payload = self.client._comic_storyboard_video_payload({}, segment)
        image_payload = self.client._comic_storyboard_image_payload({}, segment)

        self.assertEqual(video_payload["reference_image_urls"], [
            "https://cdn.example/current-start.png",
            "https://cdn.example/current-end.png",
        ])
        self.assertEqual(video_payload["image_urls"], video_payload["reference_image_urls"])
        self.assertEqual(image_payload["reference_image_urls"], [
            "https://cdn.example/stale-flowchart.png",
            "https://cdn.example/current-start.png",
            "https://cdn.example/current-end.png",
            "https://cdn.example/stale-keyframe.png",
            "https://cdn.example/supplemental.png",
        ])
        self.assertEqual(image_payload["image_urls"], image_payload["reference_image_urls"])

    def test_comic_video_payload_uses_flowchart_only_when_current_frames_are_unavailable(self):
        payload = self.client._comic_storyboard_video_payload({}, {
            "flowchartUrl": "https://cdn.example/flowchart.png",
            "keyframeUrl": "https://cdn.example/keyframe.png",
            "referenceImageUrls": ["https://cdn.example/supplemental.png"],
        })

        self.assertEqual(payload["reference_image_urls"], [
            "https://cdn.example/flowchart.png",
            "https://cdn.example/keyframe.png",
        ])

    def test_regenerate_start_frame_only_updates_start_and_marks_video_stale(self):
        segment = {
            "startFrameTaskId": "old-start", "startFrameUrl": "old-start.png", "startFramePath": "old-start.local",
            "endFrameTaskId": "old-end", "endFrameUrl": "old-end.png", "endFramePath": "old-end.local",
            "videoPath": "old.mp4", "status": "done",
        }

        self.client._apply_comic_frame_regeneration_result(
            segment, "start", "new-start", "new-start.png", "new-start.local"
        )

        self.assertEqual(segment["startFrameTaskId"], "new-start")
        self.assertEqual(segment["endFrameTaskId"], "old-end")
        self.assertEqual(segment["status"], "video_stale")
        self.assertNotIn("videoPath", segment)
        self.assertEqual(segment["retryHistory"][-1]["videoPath"], "old.mp4")

    def test_regenerate_end_frame_only_updates_end_and_marks_video_stale(self):
        segment = {
            "startFrameTaskId": "old-start", "endFrameTaskId": "old-end",
            "videoPath": "old.mp4", "status": "done",
        }

        self.client._apply_comic_frame_regeneration_result(
            segment, "end", "new-end", "new-end.png", "new-end.local"
        )

        self.assertEqual(segment["startFrameTaskId"], "old-start")
        self.assertEqual(segment["endFrameTaskId"], "new-end")
        self.assertEqual(segment["endFramePath"], "new-end.local")
        self.assertEqual(segment["status"], "video_stale")

    def test_archive_comic_video_attempt_redacts_url_and_preserves_local_media(self):
        segment = {
            "comicVideoTaskId": "old-video-task",
            "videoUrl": "https://comic.example/uploads/video.mp4?token=secret",
            "videoPath": "old.mp4",
            "actualModel": "seedance",
        }

        archived = self.client._archive_comic_media_attempt(segment, "video", "start")

        self.assertEqual(archived["taskId"], "old-video-task")
        self.assertEqual(archived["path"], "old.mp4")
        self.assertRegex(archived["urlSummary"], r"^comic\.example/sha256:[0-9a-f]{12}\.mp4$")
        self.assertNotIn("video.mp4", archived["urlSummary"])
        self.assertNotIn("secret", str(archived))
        self.assertEqual(segment["videoPath"], "old.mp4")

    def test_comic_frame_runner_submits_only_selected_frame_and_never_submits_video(self):
        class FrameOnlyAdapter:
            def __init__(self):
                self.submit_calls = []
                self.updated = []
                self.waited_task_id = ""

            def get_project(self, project_id):
                return {"data": {"id": project_id, "storyboards": [{"id": 201, "sequence": 1}]}}

            def update_storyboard(self, storyboard_id, job, segment, assets, include_audio=True):
                self.updated.append((storyboard_id, segment["script"], assets, include_audio))

            def submit_storyboard_image(self, storyboard_id, job, segment, frame_index=None):
                self.submit_calls.append((storyboard_id, frame_index))
                return {"data": {"task_id": "new-start-task"}}

            def wait_task_result(self, task_id, **_kwargs):
                self.waited_task_id = task_id
                return "https://comic.example/uploads/new-start.png", {"data": {"status": "completed"}}

        adapter = FrameOnlyAdapter()
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        job = {"comicProjectId": 88, "comicAssets": {"characters": ["latest"]}, "outDir": "/tmp"}
        segment = {
            "index": 1, "comicStoryboardId": 201, "script": "latest script",
            "startFrameTaskId": "old-start", "endFrameTaskId": "old-end",
            "endFrameUrl": "old-end.png", "endFramePath": "old-end.local",
            "videoPath": "old.mp4", "status": "done",
        }

        with mock.patch.object(self.client, "ComicProjectAdapter", return_value=adapter), \
                mock.patch.object(self.client, "_comic_download_frame_image", return_value="new-start.local"):
            page._run_comic_frame_regeneration(job, segment, "start")

        self.assertEqual(adapter.submit_calls, [(201, 1)])
        self.assertEqual(adapter.waited_task_id, "new-start-task")
        self.assertEqual(adapter.updated, [(201, "latest script", {"characters": ["latest"]}, False)])
        self.assertEqual(segment["startFrameTaskId"], "new-start-task")
        self.assertEqual(segment["endFrameTaskId"], "old-end")
        self.assertNotIn("videoPath", segment)
        self.assertEqual(segment["status"], "video_stale")

    def test_comic_frame_runner_uses_visual_only_update_payload_for_auto_and_tts(self):
        for audio_mode, voice_id in (("auto", ""), ("tts", "voice-42")):
            with self.subTest(audio_mode=audio_mode):
                adapter = self.client.ComicProjectAdapter.__new__(self.client.ComicProjectAdapter)
                adapter.comic_json = mock.Mock(side_effect=[
                    {"ok": True}, {"data": {"task_id": "frame-task"}},
                ])
                adapter.get_project = mock.Mock(return_value={
                    "data": {"id": 88, "storyboards": [{"id": 201, "sequence": 1}]}
                })
                adapter.wait_task_result = mock.Mock(return_value=(
                    "https://comic.example/uploads/frame.png", {"data": {"status": "completed"}}
                ))
                page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
                page._cancel_requested = False
                job = {
                    "comicProjectId": 88,
                    "comicAssets": {"characters": [{"id": "character-1"}]},
                    "audioMode": audio_mode,
                    "voiceId": voice_id,
                    "outDir": "/tmp",
                }
                segment = {"index": 1, "comicStoryboardId": 201, "script": "current script"}

                with mock.patch.object(self.client, "ComicProjectAdapter", return_value=adapter), \
                        mock.patch.object(self.client, "_comic_download_frame_image", return_value="frame.local"):
                    page._run_comic_frame_regeneration(job, segment, "start")

                update_payload = adapter.comic_json.call_args_list[0].args[2]
                self.assertEqual(update_payload["description"], self.client._comic_visual_prompt_text(segment, job=job))
                self.assertEqual(update_payload["dialogue"], "current script")
                self.assertEqual(update_payload["characters"], ["character-1"])
                self.assertNotIn("audio_prompt", update_payload)
                self.assertNotIn("auto_match_audio_duration", update_payload)
                self.assertFalse(any(
                    any(marker in key.lower() for marker in ("audio", "voice", "tts"))
                    for key in update_payload
                ))
                image_payload = adapter.comic_json.call_args_list[1].args[2]
                self.assertEqual(adapter.comic_json.call_args_list[1].args[0], "POST")
                self.assertEqual(image_payload["frameIndex"], 1)
                self.assertFalse(any(
                    any(marker in key.lower() for marker in ("audio", "voice", "tts"))
                    for key in image_payload
                ))

    def test_comic_end_frame_runner_uses_index_two_and_preserves_start_frame(self):
        class EndFrameAdapter:
            def get_project(self, project_id):
                return {"data": {"id": project_id, "storyboards": [{"id": 201, "sequence": 1}]}}

            def update_storyboard(self, *_args, **_kwargs):
                return {"ok": True}

            def submit_storyboard_image(self, storyboard_id, _job, _segment, frame_index=None):
                self.submitted = (storyboard_id, frame_index)
                return {"data": {"task_id": "new-end-task"}}

            def wait_task_result(self, _task_id, **_kwargs):
                return "https://comic.example/uploads/new-end.png", {"data": {"status": "completed"}}

        adapter = EndFrameAdapter()
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        job = {"comicProjectId": 88, "comicAssets": {"characters": []}, "outDir": "/tmp"}
        segment = {
            "index": 1, "comicStoryboardId": 201,
            "startFrameTaskId": "old-start", "startFrameUrl": "old-start.png", "startFramePath": "old-start.local",
            "endFrameTaskId": "old-end", "endFrameUrl": "old-end.png", "endFramePath": "old-end.local",
            "videoPath": "old.mp4", "status": "done",
        }

        with mock.patch.object(self.client, "ComicProjectAdapter", return_value=adapter), \
                mock.patch.object(self.client, "_comic_download_frame_image", return_value="new-end.local"):
            page._run_comic_frame_regeneration(job, segment, "end")

        self.assertEqual(adapter.submitted, (201, 2))
        self.assertEqual(segment["startFrameTaskId"], "old-start")
        self.assertEqual(segment["startFrameUrl"], "old-start.png")
        self.assertEqual(segment["startFramePath"], "old-start.local")
        self.assertEqual(segment["endFrameTaskId"], "new-end-task")
        self.assertEqual(segment["endFrameUrl"], "https://comic.example/uploads/new-end.png")
        self.assertEqual(segment["endFramePath"], "new-end.local")
        self.assertEqual(segment["status"], "video_stale")

    def test_final_composition_rejects_video_stale_segment(self):
        self.assertFalse(self.client._replacement_segments_ready_for_final([{
            "status": "video_stale",
            "audioStatus": "passed",
            "qcStatus": "passed",
            "reviewApproved": True,
        }]))

    def test_comic_frame_regeneration_busy_click_has_visible_feedback_and_log(self):
        class Status:
            value = ""

            def setText(self, value):
                self.value = str(value or "")

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._busy = True
        page.status = Status()
        page._job = {
            "id": "job-busy-frame",
            "replacementMode": "comic_project",
            "comicProjectId": 303,
            "segments": [{"index": 2, "comicStoryboardId": 303002}],
        }

        with mock.patch.object(self.client, "json_log") as structured_log:
            page.regenerate_comic_frame(0, "start")

        self.assertIn("正在处理", page.status.value)
        event = structured_log.call_args.args[1]
        fields = structured_log.call_args.kwargs
        self.assertEqual(event, "video_replace_comic_regeneration_requested")
        self.assertEqual(fields["job_id"], "job-busy-frame")
        self.assertEqual(fields["project_id"], 303)
        self.assertEqual(fields["segment_index"], 2)
        self.assertEqual(fields["media_kind"], "start_frame")
        self.assertTrue(fields["busy"])

    def test_comic_video_regeneration_busy_click_has_visible_feedback_and_log(self):
        class Status:
            value = ""

            def setText(self, value):
                self.value = str(value or "")

        class Table:
            @staticmethod
            def currentRow():
                return 0

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._busy = True
        page.status = Status()
        page.table = Table()
        page._job = {
            "id": "job-busy-video",
            "replacementMode": "comic_project",
            "comicProjectId": 303,
            "segments": [{"index": 3, "comicStoryboardId": 303003}],
        }

        with mock.patch.object(self.client, "json_log") as structured_log:
            page.regenerate_selected_segment()

        self.assertIn("正在处理", page.status.value)
        event = structured_log.call_args.args[1]
        fields = structured_log.call_args.kwargs
        self.assertEqual(event, "video_replace_comic_regeneration_requested")
        self.assertEqual(fields["segment_index"], 3)
        self.assertEqual(fields["media_kind"], "video")
        self.assertTrue(fields["busy"])

    def test_comic_row_regeneration_buttons_remain_clickable_for_busy_feedback(self):
        src = CLIENT.read_text(encoding="utf-8")
        block = src[
            src.index("def _make_comic_frame_cell"):
            src.index("def _make_segment_script_editor")
        ] + src[
            src.index("def refresh_segments(self):"):
            src.index("def open_output(self):")
        ]

        self.assertNotIn("regenerate.setEnabled((not self._busy)", block)
        self.assertNotIn("regen_btn.setEnabled(not self._busy)", block)

    def test_comic_frame_regeneration_failure_keeps_old_media_and_exposes_error_id(self):
        class Status:
            value = ""

            def setText(self, value):
                self.value = value

            def text(self):
                return self.value

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._busy = False
        page._sync_segment_scripts_from_table = lambda: False
        page._set_generation_feedback = lambda *_args: None
        page.status = Status()
        page.b_review = mock.Mock()
        segment = {
            "index": 1, "comicStoryboardId": 201, "status": "done",
            "videoPath": "old.mp4", "videoUrl": "https://comic.example/video.mp4?token=secret",
        }
        page._job = {"id": "job-frame-failure", "replacementMode": "comic_project", "segments": [segment]}
        bridge_events = []
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda tag, payload: bridge_events.append((tag, payload)))})()
        })()

        with mock.patch.object(page, "_run_comic_frame_regeneration", side_effect=RuntimeError("token=secret")), \
                mock.patch.object(self.client, "_replacement_error_id", return_value="err-frame"), \
                mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                mock.patch.object(self.client, "run_bg", side_effect=lambda work: work()), \
                mock.patch.object(
                    self.client.QtWidgets.QMessageBox,
                    "question",
                    return_value=self.client.QtWidgets.QMessageBox.Yes,
                ), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            page.regenerate_comic_frame(0, "start")

        self.assertEqual(segment["videoPath"], "old.mp4")
        self.assertEqual(segment["status"], "failed")
        self.assertEqual(segment["error"], "comic_frame_regeneration_failed")
        self.assertEqual(segment["errorId"], "err-frame")
        self.assertNotIn("secret", str(bridge_events))

    def test_comic_video_regeneration_never_regenerates_frames(self):
        class VideoOnlyAdapter:
            def __init__(self):
                self.updated = []
                self.submitted_payloads = []

            def update_storyboard(self, storyboard_id, job, segment, assets, include_audio=True):
                self.updated.append((storyboard_id, segment["script"], assets, include_audio))

            def submit_storyboard_image(self, *_args, **_kwargs):
                raise AssertionError("video regeneration must not submit images")

            def submit_storyboard_video(self, _storyboard_id, job, segment):
                self.submitted_payloads.append(
                    self_client._comic_storyboard_video_payload(job, segment)
                )
                return {"data": {"task_id": "new-video-task"}}

            def wait_task_result(self, task_id, **_kwargs):
                self.waited_task_id = task_id
                return "/data/new.mp4", {
                    "data": {"status": "completed", "actual_model": "seedance-new"}
                }

            def download_media(self, _url, path, **_kwargs):
                Path(path).write_bytes(b"video")
                return path

        self_client = self.client
        adapter = VideoOnlyAdapter()
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda *_args: None)})()
        })()
        with tempfile.TemporaryDirectory() as td:
            old_video = Path(td) / "old.mp4"
            old_video.write_bytes(b"old-video")
            segment = {
                "index": 1,
                "comicStoryboardId": 201,
                "script": "最新口播稿",
                "startFrameUrl": "new-start.png",
                "endFrameUrl": "new-end.png",
                "status": "download_failed",
                "comicVideoTaskId": "old-video-task",
                "videoUrl": "https://comic.example/old.mp4?token=secret",
                "videoPath": str(old_video),
                "actualModel": "seedance-old",
                "comicVideoResult": {"status": "completed"},
                "pendingComicVideoRecovery": {
                    "taskId": "superseded-pending-task",
                    "videoUrl": "https://comic.example/superseded.mp4",
                    "status": "completed",
                },
            }
            job = {
                "id": "job-comic-video-regeneration",
                "replacementMode": "comic_project",
                "comicProjectId": 88,
                "comicAssets": {"characters": [{"id": "character-1"}]},
                "audioMode": "source",
                "outDir": td,
                "segments": [segment],
            }
            with mock.patch.object(self.client, "ComicProjectAdapter", return_value=adapter), \
                    mock.patch.object(self.client, "_comic_recover_completed_media", side_effect=AssertionError("old recovery must not run")), \
                    mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                    mock.patch.object(self.client, "_save_replacement_job", return_value=None), \
                    mock.patch.object(self.client, "json_log") as structured_log, \
                    mock.patch.object(self.client, "BRIDGE", bridge):
                page._run_comic_video_regeneration(job, [segment])

            self.assertEqual(segment["status"], "done")
            self.assertEqual(segment["comicVideoTaskId"], "new-video-task")
            self.assertNotIn("pendingComicVideoRecovery", segment)
            self.assertEqual(adapter.waited_task_id, "new-video-task")
            self.assertEqual(adapter.updated, [(
                201,
                "最新口播稿",
                {"characters": [{"id": "character-1"}]},
                True,
            )])
            self.assertEqual(len(adapter.submitted_payloads), 1)
            self.assertTrue(adapter.submitted_payloads[0]["force_regenerate"])
            self.assertEqual(adapter.submitted_payloads[0]["audio_mode"], "auto")
            self.assertIn("new-start.png", adapter.submitted_payloads[0]["reference_image_urls"])
            self.assertIn("new-end.png", adapter.submitted_payloads[0]["reference_image_urls"])
            self.assertTrue(old_video.is_file())
            self.assertEqual(segment["retryHistory"][-1]["taskId"], "old-video-task")
            self.assertEqual(segment["retryHistory"][-1]["operationType"], "comic_video_regeneration")
            self.assertNotIn("secret", str(segment["retryHistory"][-1]))
            completed = [
                call for call in structured_log.call_args_list
                if call.args[1] == "video_replace_comic_regeneration_completed"
            ]
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0].kwargs["job_id"], "job-comic-video-regeneration")
            self.assertEqual(completed[0].kwargs["project_id"], 88)
            self.assertEqual(completed[0].kwargs["segment_index"], 1)
            self.assertEqual(completed[0].kwargs["media_kind"], "video")

    def test_comic_video_regeneration_uses_latest_frames_script_and_audio(self):
        segment = {
            "startFrameUrl": "new-start.png",
            "endFrameUrl": "new-end.png",
            "script": "最新口播稿",
            "audioUrl": "new-audio.mp3",
        }

        payload = self.client._comic_storyboard_video_payload({"audioMode": "tts"}, segment)
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertIn("new-start.png", serialized)
        self.assertIn("new-end.png", serialized)
        self.assertIn("最新口播稿", serialized)
        self.assertEqual(payload["audio_mode"], "tts")

    def test_comic_video_prompt_does_not_claim_lk888_receives_source_video_motion(self):
        job = {
            "modelFaceUrl": "https://cdn.example/person.png",
            "sceneImageUrl": "https://cdn.example/scene.png",
            "productImageUrls": ["https://cdn.example/product.png"],
        }
        segment = {
            "prompt": (
                "人物：男销售，白衬衫黑领带，动作和站位沿用原片\n"
                "画面：展厅中景，保留原片动作、原片站位和镜头关系"
            ),
            "startFrameUrl": "https://cdn.example/start.png",
            "endFrameUrl": "https://cdn.example/end.png",
        }

        payload = self.client._comic_storyboard_video_payload(job, segment)
        prompt = payload["prompt"]

        for forbidden in ("沿用原片", "原视频只提供", "保留原片动作", "原片站位"):
            self.assertNotIn(forbidden, prompt)
        self.assertIn("参考分镜拆解文本", prompt)
        self.assertNotIn("sourceVideoUrl", payload)
        self.assertNotIn("source_video_url", payload)

    def test_seedance_comic_image_payload_uses_gpt_image_colored_pencil_style(self):
        job = {
            "model": "doubao-seedance-2-0-260128",
            "modelFaceUrl": "https://cdn.example/person.png",
            "sceneImageUrl": "https://cdn.example/scene.png",
            "productImageUrls": ["https://cdn.example/product.png"],
        }
        segment = {
            "prompt": "\u4e3b\u89d2\u5728\u5c55\u5385\u5c55\u793a\u4ea7\u54c1",
            "startFrameUrl": "https://cdn.example/start.png",
            "endFrameUrl": "https://cdn.example/end.png",
        }

        image_payload = self.client._comic_storyboard_image_payload(job, segment)
        prompt = image_payload["prompt"]

        self.assertEqual(image_payload["image_model"], "gpt-image-2")
        self.assertEqual(image_payload["imageModel"], "gpt-image-2")
        self.assertEqual(image_payload["frame_style_mode"], "colored_pencil")
        self.assertEqual(image_payload["frameStyleMode"], "colored_pencil")
        self.assertIn("\u5f69\u94c5", prompt)
        self.assertIn("\u624b\u7ed8", prompt)
        self.assertNotIn("\u771f\u4eba\u5199\u5b9e", prompt)

    def test_seedance_comic_video_payload_requests_realistic_style_after_colored_pencil_frames(self):
        seedance_job = {
            "model": "doubao-seedance-2-0-260128",
            "modelFaceUrl": "https://cdn.example/person.png",
        }
        non_seedance_job = {
            "model": "viduq3-cankaosheng",
            "modelFaceUrl": "https://cdn.example/person.png",
        }
        segment = {
            "prompt": "\u4e3b\u89d2\u5728\u5c55\u5385\u5c55\u793a\u4ea7\u54c1",
            "startFrameUrl": "https://cdn.example/start.png",
            "endFrameUrl": "https://cdn.example/end.png",
        }

        seedance_payload = self.client._comic_storyboard_video_payload(seedance_job, segment)
        non_seedance_payload = self.client._comic_storyboard_video_payload(non_seedance_job, segment)

        self.assertIn("\u771f\u4eba\u5199\u5b9e", seedance_payload["prompt"])
        self.assertIn("\u771f\u4eba\u5199\u5b9e", seedance_payload["keyframes_video_prompt"])
        self.assertNotIn("\u5f69\u94c5", seedance_payload["prompt"])
        self.assertNotIn("\u771f\u4eba\u5199\u5b9e", non_seedance_payload["prompt"])

    def test_sd20_all_reference_comic_payload_uses_colored_pencil_chain(self):
        job = {
            "model": "kwvideo-v2-quannengcankao",
            "modelFaceUrl": "https://cdn.example/person.png",
            "sceneImageUrl": "https://cdn.example/scene.png",
            "productImageUrls": ["https://cdn.example/product.png"],
        }
        segment = {
            "prompt": "\u4e3b\u89d2\u5728\u5c55\u5385\u5c55\u793a\u4ea7\u54c1",
            "startFrameUrl": "https://cdn.example/start.png",
            "endFrameUrl": "https://cdn.example/end.png",
        }

        image_payload = self.client._comic_storyboard_image_payload(job, segment)
        video_payload = self.client._comic_storyboard_video_payload(job, segment)

        self.assertEqual(image_payload["image_model"], "gpt-image-2")
        self.assertEqual(image_payload["frame_style_mode"], "colored_pencil")
        self.assertIn("\u5f69\u94c5", image_payload["prompt"])
        self.assertIn("\u771f\u4eba\u5199\u5b9e", video_payload["prompt"])

    def test_comic_video_payload_prefers_hidden_colored_pencil_references(self):
        job = {
            "model": "kwvideo-v2-quannengcankao",
            "modelFaceUrl": "https://cdn.example/person-original.png",
            "sceneImageUrl": "https://cdn.example/scene-original.png",
            "productImageUrls": ["https://cdn.example/product-original.png"],
        }
        segment = {
            "prompt": "\u4e3b\u89d2\u5728\u5c55\u5385\u5c55\u793a\u4ea7\u54c1",
            "startFrameUrl": "https://cdn.example/start-original.png",
            "endFrameUrl": "https://cdn.example/end-original.png",
            "coloredPencilStartFrameUrl": "https://cdn.example/start-pencil.png",
            "coloredPencilEndFrameUrl": "https://cdn.example/end-pencil.png",
            "coloredPencilReferenceImageUrls": [
                "https://cdn.example/person-pencil.png",
                "https://cdn.example/scene-pencil.png",
                "https://cdn.example/product-pencil.png",
            ],
        }

        payload = self.client._comic_storyboard_video_payload(job, segment)

        self.assertEqual(payload["reference_image_urls"], [
            "https://cdn.example/start-pencil.png",
            "https://cdn.example/end-pencil.png",
            "https://cdn.example/person-pencil.png",
            "https://cdn.example/scene-pencil.png",
            "https://cdn.example/product-pencil.png",
        ])
        self.assertEqual(payload["image_urls"], payload["reference_image_urls"])
        self.assertEqual(payload["character_reference_images"], [])
        self.assertEqual(payload["scene_reference_images"], [])
        self.assertEqual(payload["prop_reference_images"], [])
        self.assertNotIn("https://cdn.example/start-original.png", payload["reference_image_urls"])
        self.assertNotIn("https://cdn.example/person-original.png", payload["subject_reference_images"])

    def test_prepare_colored_pencil_references_calls_gpt_image_without_replacing_visible_frames(self):
        job = {
            "model": "kwvideo-v2-quannengcankao",
            "modelFaceUrl": "https://cdn.example/person-original.png",
            "sceneImageUrl": "https://cdn.example/scene-original.png",
            "productImageUrls": ["https://cdn.example/product-original.png"],
        }
        segment = {
            "prompt": "\u4e3b\u89d2\u5728\u5c55\u5385\u5c55\u793a\u4ea7\u54c1",
            "startFrameUrl": "https://cdn.example/start-original.png",
            "endFrameUrl": "https://cdn.example/end-original.png",
        }
        generated = [
            (b"start", "https://cdn.example/start-pencil.png"),
            (b"end", "https://cdn.example/end-pencil.png"),
            (b"person", "https://cdn.example/person-pencil.png"),
            (b"scene", "https://cdn.example/scene-pencil.png"),
            (b"product", "https://cdn.example/product-pencil.png"),
        ]

        with mock.patch.object(
                self.client, "_lk888_image_result_download", side_effect=generated
        ) as image_result:
            self.client._prepare_comic_colored_pencil_references(job, segment)

        self.assertEqual(image_result.call_count, 5)
        for call in image_result.call_args_list:
            self.assertEqual(call.kwargs.get("model"), "gpt-image-2")
            self.assertIn("\u5f69\u94c5", call.args[0])
            self.assertEqual(len(call.kwargs.get("image_urls") or []), 1)
        self.assertEqual(segment["startFrameUrl"], "https://cdn.example/start-original.png")
        self.assertEqual(segment["endFrameUrl"], "https://cdn.example/end-original.png")
        self.assertEqual(segment["coloredPencilStartFrameUrl"], "https://cdn.example/start-pencil.png")
        self.assertEqual(segment["coloredPencilEndFrameUrl"], "https://cdn.example/end-pencil.png")
        self.assertEqual(segment["coloredPencilReferenceImageUrls"], [
            "https://cdn.example/person-pencil.png",
            "https://cdn.example/scene-pencil.png",
            "https://cdn.example/product-pencil.png",
        ])

    def test_prepare_colored_pencil_references_blocks_video_when_keyframes_missing(self):
        job = {"model": "kwvideo-v2-quannengcankao"}
        segment = {
            "index": 3,
            "prompt": "\u4e3b\u89d2\u5728\u5c55\u5385\u5c55\u793a\u4ea7\u54c1",
            "startFrameUrl": "https://cdn.example/start-original.png",
            "endFrameUrl": "https://cdn.example/end-original.png",
        }

        def fake_image_result(_prompt, **kwargs):
            source_url = (kwargs.get("image_urls") or [""])[0]
            if "start-original" in source_url:
                return b"start", "https://cdn.example/start-pencil.png"
            raise RuntimeError("lk888 image failed")

        with mock.patch.object(
                self.client, "_lk888_image_result_download", side_effect=fake_image_result
        ):
            with self.assertRaises(RuntimeError):
                self.client._prepare_comic_colored_pencil_references(job, segment)

        self.assertEqual(segment["coloredPencilStatus"], "failed")
        self.assertEqual(segment["coloredPencilStartFrameUrl"], "https://cdn.example/start-pencil.png")
        self.assertNotIn("coloredPencilEndFrameUrl", segment)

    def test_comic_project_video_model_candidates_keep_user_selected_model_only(self):
        candidates = self.client._comic_project_video_model_candidates({
            "comicVideoModel": "doubao-seedance-2-0-260128",
            "model": "doubao-seedance-2-0-260128",
        })

        self.assertEqual(candidates, ["doubao-seedance-2-0-260128"])

    def test_comic_video_payload_auto_mode_preserves_provider_audio(self):
        for legacy_mode in ("auto", "source", "origin", "original", "source_audio"):
            with self.subTest(audio_mode=legacy_mode):
                payload = self.client._comic_storyboard_video_payload(
                    {"audioMode": legacy_mode},
                    {
                        "script": "只作为剧本文字",
                        "startFrameUrl": "start.png",
                        "endFrameUrl": "end.png",
                    },
                )
                update_payload = self.client._comic_storyboard_update_payload(
                    {"audioMode": legacy_mode},
                    {
                        "script": "只作为剧本文字",
                        "startFrameUrl": "start.png",
                        "endFrameUrl": "end.png",
                    },
                    {},
                )
                self.assertEqual(payload["audio_mode"], "auto")
                self.assertNotIn("audio_prompt", payload)
                self.assertEqual(update_payload["audio_mode"], "auto")
                self.assertNotIn("audio_prompt", update_payload)

    def test_comic_video_payload_without_dialogue_requests_no_environment_audio(self):
        payload = self.client._comic_storyboard_video_payload(
            {"audioMode": "auto"},
            {"script": "", "startFrameUrl": "start.png", "endFrameUrl": "end.png"},
        )

        self.assertEqual(payload["audio_mode"], "auto")
        self.assertNotIn("audio_prompt", payload)

    def test_comic_video_payload_enables_tts_only_for_tts_mode(self):
        payload = self.client._comic_storyboard_video_payload(
            {"audioMode": "tts", "voiceId": "xiaosi"},
            {
                "script": "需要配音的口播稿",
                "startFrameUrl": "start.png",
                "endFrameUrl": "end.png",
            },
        )

        self.assertEqual(payload["audio_mode"], "tts")
        self.assertEqual(payload["audio_prompt"]["dialogue"]["text"], "需要配音的口播稿")

    def test_comic_batch_retry_skips_missing_frames_and_continues_valid_segments(self):
        missing_start = {
            "index": 1, "status": "failed", "endFrameUrl": "end.png", "errorId": "err-existing"
        }
        missing_end = {
            "index": 2, "status": "download_failed", "startFrameUrl": "start.png"
        }
        ready = {
            "index": 3,
            "status": "failed",
            "startFrameUrl": "start.png",
            "endFrameUrl": "end.png",
        }
        ignored = {
            "index": 4,
            "status": "done",
            "startFrameUrl": "start.png",
            "endFrameUrl": "end.png",
        }

        runnable, skipped = self.client._comic_segments_ready_for_video_retry(
            [missing_start, missing_end, ready, ignored]
        )

        self.assertEqual(runnable, [ready])
        self.assertEqual(skipped, [missing_start, missing_end])
        self.assertEqual(missing_start["error"], "请先重新生成缺失的首帧")
        self.assertEqual(missing_end["error"], "请先重新生成缺失的尾帧")
        self.assertEqual(missing_start["errorId"], "err-existing")

    def test_comic_video_regeneration_download_failure_preserves_current_media_and_error_id(self):
        class FailingVideoAdapter:
            def update_storyboard(self, *_args, **_kwargs):
                return {"ok": True}

            def submit_storyboard_video(self, *_args, **_kwargs):
                return {"data": {"task_id": "new-video-task"}}

            def wait_task_result(self, *_args, **_kwargs):
                return "https://comic.example/new.mp4?token=new-secret", {"data": {"status": "completed"}}

            def download_media(self, *_args, **_kwargs):
                raise RuntimeError("token=new-secret")

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {
            "index": 1,
            "comicStoryboardId": 201,
            "startFrameUrl": "start.png",
            "endFrameUrl": "end.png",
            "status": "failed",
            "comicVideoTaskId": "old-video-task",
            "videoUrl": "https://comic.example/old.mp4?token=old-secret",
            "videoPath": "old.mp4",
        }
        job = {
            "id": "job-comic-video-failure",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "comicAssets": {},
            "outDir": "/tmp",
            "segments": [segment],
        }
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda *_args: None)})()
        })()

        with mock.patch.object(self.client, "ComicProjectAdapter", FailingVideoAdapter), \
                mock.patch.object(self.client, "_replacement_error_id", return_value="err-video-download"), \
                mock.patch.object(self.client, "_save_replacement_job", return_value=None), \
                mock.patch.object(self.client, "json_log") as structured_log, \
                mock.patch.object(self.client, "BRIDGE", bridge):
            page._run_comic_video_regeneration(job, [segment])

        self.assertEqual(segment["status"], "download_failed")
        self.assertEqual(segment["errorId"], "err-video-download")
        self.assertEqual(segment["videoPath"], "old.mp4")
        self.assertIn("old.mp4", segment["videoUrl"])
        self.assertEqual(segment["comicVideoTaskId"], "old-video-task")
        self.assertIn("new-secret", segment["pendingComicVideoRecovery"]["videoUrl"])
        self.assertNotIn("new-secret", str(segment["retryHistory"]))
        failed = [
            call for call in structured_log.call_args_list
            if call.args[1] == "video_replace_comic_regeneration_failed"
        ]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].kwargs["job_id"], "job-comic-video-failure")
        self.assertEqual(failed[0].kwargs["project_id"], 88)
        self.assertEqual(failed[0].kwargs["segment_index"], 1)
        self.assertEqual(failed[0].kwargs["media_kind"], "video")
        self.assertEqual(failed[0].kwargs["error_id"], "err-video-download")

    def test_comic_batch_download_recovery_retries_without_resubmit_or_rebill(self):
        class RecoverableVideoAdapter:
            def __init__(self):
                self.submit_count = 0
                self.update_count = 0
                self.wait_count = 0
                self.download_count = 0

            def update_storyboard(self, *_args, **_kwargs):
                self.update_count += 1
                return {"ok": True}

            def submit_storyboard_video(self, *_args, **_kwargs):
                self.submit_count += 1
                return {"data": {"task_id": "new-video-task"}}

            def wait_task_result(self, *_args, **_kwargs):
                self.wait_count += 1
                return "https://comic.example/new.mp4", {
                    "data": {
                        "status": "completed",
                        "requested_model": "seedance-requested",
                        "actual_model": "kling-fallback",
                        "fallback_model": "kling-fallback",
                        "fallback_reason": "provider-rejected",
                        "fallback_applied": True,
                        "audioSource": "provider_generated",
                        "audioMixStatus": "not_requested",
                    }
                }

            def download_media(self, _url, path, **_kwargs):
                self.download_count += 1
                if self.download_count < 3:
                    raise RuntimeError("temporary authenticated download failure")
                Path(path).write_bytes(b"new-video")
                return path

        adapter = RecoverableVideoAdapter()
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda *_args: None)})()
        })()
        with tempfile.TemporaryDirectory() as td:
            old_video = Path(td) / "old.mp4"
            old_video.write_bytes(b"old-video")
            segment = {
                "index": 1,
                "comicStoryboardId": 201,
                "script": "current script",
                "startFrameUrl": "start.png",
                "endFrameUrl": "end.png",
                "status": "failed",
                "comicVideoTaskId": "old-video-task",
                "videoUrl": "https://comic.example/old.mp4",
                "videoPath": str(old_video),
                "actualModel": "seedance-old",
            }
            job = {
                "id": "job-comic-download-recovery",
                "replacementMode": "comic_project",
                "comicProjectId": 88,
                "comicAssets": {},
                "audioMode": "auto",
                "outDir": td,
                "segments": [segment],
            }
            saved = []
            error_ids = iter(("err-download-1", "err-download-2"))

            with mock.patch.object(self.client, "ComicProjectAdapter", return_value=adapter), \
                    mock.patch.object(self.client, "_replacement_error_id", side_effect=lambda *_args, **_kwargs: next(error_ids)), \
                    mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                    mock.patch.object(
                        self.client,
                        "_save_replacement_job",
                        side_effect=lambda value: saved.append(json.loads(json.dumps(value))),
                    ), \
                    mock.patch.object(self.client, "BRIDGE", bridge):
                page._run_comic_video_regeneration(job, [segment])
                self.assertEqual(segment["status"], "download_failed")
                self.assertEqual(segment["videoPath"], str(old_video))
                self.assertEqual(segment["comicVideoTaskId"], "old-video-task")
                pending = segment["pendingComicVideoRecovery"]
                self.assertEqual(pending["taskId"], "new-video-task")
                self.assertEqual(pending["videoUrl"], "https://comic.example/new.mp4")
                self.assertEqual(pending["urlSummary"], self.client._comic_media_url_summary(pending["videoUrl"]))
                self.assertEqual(pending["result"]["status"], "completed")
                self.assertEqual(pending["requestedModel"], "seedance-requested")
                self.assertEqual(pending["actualModel"], "kling-fallback")
                self.assertEqual(pending["audioSource"], "provider_generated")
                self.assertEqual(pending["audioMixStatus"], "not_requested")
                self.assertEqual(pending["lastErrorId"], "err-download-1")
                self.assertTrue(any(
                    item["segments"][0].get("pendingComicVideoRecovery", {}).get("taskId") == "new-video-task"
                    for item in saved
                ))

                page._run_comic_video_regeneration(job, [segment], allow_pending_recovery=True)
                self.assertEqual(segment["status"], "download_failed")
                self.assertEqual(segment["videoPath"], str(old_video))
                self.assertEqual(segment["pendingComicVideoRecovery"]["lastErrorId"], "err-download-2")

                page._run_comic_video_regeneration(job, [segment], allow_pending_recovery=True)

            self.assertEqual(adapter.submit_count, 1)
            self.assertEqual(adapter.update_count, 1)
            self.assertEqual(adapter.wait_count, 1)
            self.assertEqual(adapter.download_count, 3)
            self.assertEqual(segment["status"], "done")
            self.assertEqual(segment["comicVideoTaskId"], "new-video-task")
            self.assertEqual(segment["videoUrl"], "https://comic.example/new.mp4")
            self.assertNotEqual(segment["videoPath"], str(old_video))
            self.assertTrue(Path(segment["videoPath"]).is_file())
            self.assertNotIn("pendingComicVideoRecovery", segment)
            self.assertEqual(segment["requestedModel"], "seedance-requested")
            self.assertEqual(segment["actualModel"], "kling-fallback")
            self.assertEqual(segment["audioSource"], "provider_generated")
            self.assertEqual(segment["audioMixStatus"], "not_requested")
            self.assertTrue(old_video.is_file())

    def test_comic_retry_entries_use_video_only_runner_and_keep_legacy_runner(self):
        src = CLIENT.read_text(encoding="utf-8")
        retry_block = src[
            src.index("    def retry_failed_segments(self):"):
            src.index("    def regenerate_comic_frame", src.index("    def retry_failed_segments(self):"))
        ]
        regenerate_block = src[
            src.index("    def regenerate_selected_segment(self):"):
            src.index("    def cancel_generation", src.index("    def regenerate_selected_segment(self):"))
        ]

        self.assertIn('status") in ("failed", "download_failed")', retry_block)
        self.assertIn("_comic_segments_ready_for_video_retry", retry_block)
        self.assertIn("_run_comic_video_regeneration", retry_block)
        self.assertIn("allow_pending_recovery=True", retry_block)
        self.assertIn("_run_job_segments", retry_block)
        self.assertIn("_sync_segment_scripts_from_table", regenerate_block)
        self.assertIn('QMessageBox.question(', regenerate_block)
        self.assertIn('"重新生成视频"', regenerate_block)
        self.assertIn("_run_comic_video_regeneration", regenerate_block)
        self.assertIn("_run_job_segments", regenerate_block)
        self.assertIn(
            'retry_statuses = ("failed", "download_failed") if '
            '_replacement_job_mode(self._job) == "comic_project" else ("failed",)',
            src,
        )
        for unreliable_copy in ("预计金额", "按实际模型计费", "预计费用"):
            self.assertNotIn(unreliable_copy, regenerate_block)

    def test_comic_regenerate_video_entry_uses_ordinary_confirmation_and_current_script(self):
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._busy = False
        page._cancel_requested = False
        page._job = {
            "id": "job-comic-entry",
            "replacementMode": "comic_project",
            "segments": [{
                "index": 1,
                "status": "failed",
                "comicStoryboardId": 201,
                "script": "old script",
                "startFrameUrl": "start.png",
                "endFrameUrl": "end.png",
            }],
        }
        page.table = mock.Mock()
        page.table.currentRow.return_value = 0
        page.status = mock.Mock()
        page.status.text.return_value = "正在重新生成片段 1 的视频…"
        page.b_retry_failed = mock.Mock()
        page.b_regen_segment = mock.Mock()
        page.b_review = mock.Mock()
        page._set_generation_feedback = mock.Mock()
        page._sync_segment_scripts_from_table = mock.Mock(side_effect=lambda: page._job["segments"][0].update({
            "script": "current script"
        }))

        with mock.patch.object(
                self.client.QtWidgets.QMessageBox,
                "question",
                return_value=self.client.QtWidgets.QMessageBox.Yes,
        ) as question, \
                mock.patch.object(self.client, "_save_replacement_job", return_value=None), \
                mock.patch.object(self.client, "run_bg") as run_bg:
            page.regenerate_selected_segment()

        self.assertEqual(page._job["segments"][0]["script"], "current script")
        self.assertEqual(question.call_args.args[1:], (
            "重新生成视频",
            "确定重新生成片段 1 的视频吗？",
        ))
        run_bg.assert_called_once()

    def test_comic_absolute_media_url_joins_remote_upload_path(self):
        with mock.patch.object(
            self.client,
            "_comic_base_url",
            return_value="https://manju.yunlingai.net",
        ):
            self.assertEqual(
                self.client._comic_absolute_media_url("/uploads/2026/07/clip.mp4"),
                "https://manju.yunlingai.net/uploads/2026/07/clip.mp4",
            )
        self.assertEqual(
            self.client._comic_absolute_media_url("https://cdn.example/frame.png"),
            "https://cdn.example/frame.png",
        )

    def test_comic_protected_video_download_requires_adapter_auth(self):
        class RecordingAdapter:
            def __init__(self):
                self.attempts = []

            def download_media(self, url, path):
                self.attempts.extend([
                    {"status": 401, "headers": {}},
                    {"status": 200, "headers": {"Authorization": "placeholder-auth"}},
                ])
                Path(path).write_bytes(b"video")
                return path

        adapter = RecordingAdapter()
        segment = {"index": 1, "status": "failed"}
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}):
            path = self.client._comic_download_segment_video(
                {"outDir": td}, segment,
                "http://comic.test/data/uploads/comic-drama/result.mp4",
                adapter=adapter,
            )
        self.assertEqual([attempt["status"] for attempt in adapter.attempts], [401, 200])
        self.assertNotIn("Authorization", adapter.attempts[0]["headers"])
        self.assertEqual(adapter.attempts[1]["headers"]["Authorization"], "placeholder-auth")
        self.assertEqual(segment["status"], "done")
        self.assertEqual(path, segment["videoPath"])

    def test_comic_media_download_sends_bearer_and_retries_401_once(self):
        adapter = self.client.ComicProjectAdapter.__new__(self.client.ComicProjectAdapter)
        adapter.comic_base = "http://comic"
        adapter._comic_token = "old-token"
        adapter._comic_token_expires_at = 9999999999
        adapter._ensure_comic_token = mock.Mock(side_effect=["old-token", "new-token"])
        unauthorized = mock.Mock(status_code=401)
        success = mock.Mock(status_code=200)
        success.raise_for_status.return_value = None
        success.iter_content.return_value = [b"video"]
        adapter._media_get = mock.Mock(side_effect=[unauthorized, success])
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "result.mp4")
            self.assertEqual(adapter.download_media("http://comic/data/result.mp4", path), path)
            self.assertEqual(Path(path).read_bytes(), b"video")
        self.assertEqual(adapter._media_get.call_count, 2)
        self.assertEqual(
            adapter._media_get.call_args_list[0].kwargs["headers"]["Authorization"],
            "Bearer old-token",
        )
        self.assertEqual(
            adapter._media_get.call_args_list[1].kwargs["headers"]["Authorization"],
            "Bearer new-token",
        )

    def test_comic_media_download_omits_bearer_for_external_cdn(self):
        adapter = self.client.ComicProjectAdapter.__new__(self.client.ComicProjectAdapter)
        adapter.comic_base = "https://comic.example"
        adapter._ensure_comic_token = mock.Mock()
        success = mock.Mock(status_code=200)
        success.raise_for_status.return_value = None
        success.iter_content.return_value = [b"video"]
        adapter._media_get = mock.Mock(return_value=success)
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "result.mp4")
            self.assertEqual(adapter.download_media("https://cdn.example/result.mp4", path), path)
        self.assertEqual(adapter._media_get.call_args.kwargs["headers"], {})
        adapter._ensure_comic_token.assert_not_called()

    def test_comic_media_download_closes_session_when_get_raises(self):
        adapter = self.client.ComicProjectAdapter(comic_base="https://comic.example")
        adapter._ensure_comic_token = mock.Mock(return_value="comic-token")
        session = mock.Mock()
        session.get.side_effect = RuntimeError("network unavailable")
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client.requests, "Session", return_value=session):
            with self.assertRaisesRegex(RuntimeError, "network unavailable"):
                adapter.download_media("/uploads/result.mp4", str(Path(td) / "result.mp4"))
        self.assertIs(session.trust_env, False)
        session.close.assert_called_once()

    def test_comic_video_download_failure_uses_download_failed_status(self):
        adapter = mock.Mock()
        adapter.download_media.side_effect = RuntimeError("comic_media_unauthorized")
        segment = {"index": 1, "status": "running"}
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError, "comic_media_unauthorized"):
                self.client._comic_download_segment_video(
                    {"outDir": td}, segment, "http://comic/data/result.mp4", adapter=adapter
                )
        self.assertEqual(segment["status"], "download_failed")
        self.assertEqual(segment["stage"], "download_failed")

    def test_comic_video_recovery_rejects_storyboard_image_url(self):
        adapter = mock.Mock()
        adapter.get_project.return_value = {
            "data": {
                "id": 314,
                "storyboards": [{
                    "id": 314001,
                    "startFrameUrl": "/uploads/start.png",
                    "endFrameUrl": "/uploads/end.png",
                    "resultUrl": "/uploads/end.png",
                    "url": "/uploads/end.png",
                }],
            },
        }

        with self.assertRaisesRegex(RuntimeError, "comic_video_recovery_missing:storyboard_314001"):
            self.client._comic_recover_storyboard_media(
                adapter,
                314,
                314001,
                "video",
                RuntimeError("Read timed out"),
            )

    def test_comic_download_failure_preserves_existing_audio_status(self):
        class FailingDownloadAdapter:
            def get_project(self, project_id):
                return {"data": {"id": project_id, "storyboards": [{"id": 201, "sequence": 1}]}}

            def upsert_manual_assets(self, *_args, **_kwargs):
                return {}

            def download_media(self, *_args, **_kwargs):
                raise RuntimeError("comic_media_unauthorized")

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {
            "index": 1,
            "status": "download_failed",
            "comicStoryboardId": 201,
            "videoUrl": "https://comic.example/uploads/result.mp4",
            "comicVideoResult": {"status": "completed"},
            "audioStatus": "provider_generated",
        }
        job = {
            "id": "job-comic-preserve-audio",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "comicAssets": {},
            "outDir": "/tmp",
            "segments": [segment],
        }
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda *_args: None)})()
        })()
        with mock.patch.object(self.client, "ComicProjectAdapter", FailingDownloadAdapter), \
                mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                mock.patch.object(self.client, "_replacement_error_id", return_value="err-comic-download"), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            page._run_comic_project_segments(job, [segment], lambda *_args, **_kwargs: None)
        self.assertEqual(segment["status"], "failed")
        self.assertEqual(segment["audioStatus"], "provider_generated")

    def test_comic_completed_remote_video_recovers_without_resubmit(self):
        adapter = mock.Mock()
        adapter.download_media.side_effect = (
            lambda _url, path, **_kwargs: Path(path).write_bytes(b"video") or path
        )
        segment = {
            "index": 1,
            "status": "download_failed",
            "videoUrl": "http://comic/data/result.mp4",
            "comicVideoResult": {"status": "completed"},
        }
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}):
            recovered = self.client._comic_recover_completed_media({"outDir": td}, segment, adapter)
            self.assertTrue(Path(segment["videoPath"]).is_file())
        self.assertTrue(recovered)
        self.assertEqual(segment["status"], "done")
        adapter.submit_storyboard_video.assert_not_called()

    def test_comic_task_progress_keeps_default_message_without_model_fallback(self):
        payload = {
            "data": {
                "status": "pending",
                "requested_model": "doubao-seedance-2-0-260128",
                "actual_model": "kling-avatar-image2video",
                "fallback_reason": "InputImageSensitiveContentDetected.PrivacyInformation",
                "fallback_applied": True,
            }
        }

        message = self.client._comic_task_progress_message(payload, "视频生成中…")

        self.assertEqual(message, "视频生成中…")

    def test_comic_task_progress_keeps_default_message_for_policy_violation_without_model_fallback(self):
        payload = {
            "data": {
                "status": "pending",
                "requested_model": "doubao-seedance-2-0-260128",
                "actual_model": "vidu/viduq3-mix_reference2video",
                "fallback_reason": "InputImageSensitiveContentDetected.PolicyViolation",
                "fallback_applied": True,
            }
        }

        message = self.client._comic_task_progress_message(payload, "视频生成中…")

        self.assertEqual(message, "视频生成中…")

    def test_comic_task_failure_keeps_fallback_reason(self):
        payload = {
            "data": {
                "status": "failed",
                "requestedModel": "doubao-seedance-2-0-260128",
                "actualModel": "kling-avatar-image2video",
                "fallbackReason": "InputImageSensitiveContentDetected.PrivacyInformation",
                "fallbackApplied": True,
                "errorMessage": "Kling Avatar 上游返回参数错误",
            }
        }

        message = self.client._comic_task_failure_message(payload)

        self.assertIn("Seedance 拒绝真人参考图", message)
        self.assertIn("Kling Avatar 上游返回参数错误", message)

    def test_comic_task_failure_explains_policy_violation_material_risk(self):
        payload = {
            "data": {
                "status": "failed",
                "requestedModel": "doubao-seedance-2-0-260128",
                "actualModel": "vidu/viduq3-mix_reference2video",
                "fallbackReason": "InputImageSensitiveContentDetected.PolicyViolation",
                "fallbackApplied": True,
                "errorMessage": "Vidu 上游返回参数错误",
            }
        }

        message = self.client._comic_task_failure_message(payload)

        self.assertIn("Seedance 拒绝素材版权/品牌风险", message)
        self.assertIn("Vidu 上游返回参数错误", message)

    def test_comic_task_fallback_metadata_accepts_remote_aliases(self):
        payload = {
            "data": {
                "requestedModel": "doubao-seedance-2-0-260128",
                "actual_model": "kling-avatar-image2video",
                "fallbackModel": "kling-avatar-image2video",
                "fallback_reason": "InputImageSensitiveContentDetected.PrivacyInformation",
                "fallbackApplied": True,
            }
        }

        metadata = self.client._comic_task_fallback_metadata(payload)

        self.assertEqual(metadata["requestedModel"], "doubao-seedance-2-0-260128")
        self.assertEqual(metadata["actualModel"], "kling-avatar-image2video")
        self.assertEqual(metadata["fallbackModel"], "kling-avatar-image2video")
        self.assertTrue(metadata["modelFallbackApplied"])

    def test_comic_seedance_policy_violation_is_retryable_fallback_reason(self):
        text = (
            "ark 400 Bad Request: {\"error\":{\"code\":"
            "\"InputImageSensitiveContentDetected.PolicyViolation\","
            "\"message\":\"input image may be related to copyright restriction\"}}"
        )

        self.assertTrue(self.client._comic_seedance_safety_fallback_reason(text))
        self.assertEqual(
            self.client._comic_seedance_safety_fallback_reason(text),
            "InputImageSensitiveContentDetected.PolicyViolation",
        )

    def test_comic_project_video_wait_policy_violation_fails_without_model_fallback(self):
        class PolicyFailureAdapter:
            submitted_models = []
            waited_tasks = []

            def get_project(self, project_id):
                return {"data": {"id": project_id, "storyboards": [{"id": 201, "sequence": 1}]}}

            def update_storyboard(self, *_args, **_kwargs):
                return {"ok": True}

            def submit_storyboard_image(self, *_args, **_kwargs):
                return {"data": {"task_ids": ["start-frame-task", "end-frame-task"]}}

            def submit_storyboard_video(self, _storyboard_id, job, _segment):
                model = str(job.get("comicVideoModel") or job.get("model") or "")
                self.__class__.submitted_models.append(model)
                return {"data": {"task_id": "video-task-%s" % model}}

            def wait_task_result(self, task_id, **_kwargs):
                self.__class__.waited_tasks.append(task_id)
                if str(task_id).startswith("start-frame") or str(task_id).startswith("end-frame"):
                    return "https://example.test/%s.png" % task_id, {"data": {"status": "completed"}}
                raise RuntimeError(
                    "comic_task_failed:ark 400 Bad Request: "
                    "{\"error\":{\"code\":\"InputImageSensitiveContentDetected.PolicyViolation\","
                    "\"message\":\"The request failed because the input image 'content[1]' "
                    "may be related to copyright restrictions.\"}}"
                )

            def download_media(self, _url, path, **_kwargs):
                Path(path).write_bytes(b"video")
                return path

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {"index": 1, "status": "pending", "script": "test script", "comicStoryboardId": 201, "duration": 8.0}
        job = {
            "id": "job-policy-fallback",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "comicAssets": {},
            "comicVideoModel": "doubao-seedance-2-0-260128",
            "model": "doubao-seedance-2-0-260128",
            "outDir": "/tmp",
            "segments": [segment],
        }
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda *_args: None)})()
        })()

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "ComicProjectAdapter", PolicyFailureAdapter), \
                mock.patch.object(self.client, "try_charge", return_value=(True, None)) as precharge_call, \
                mock.patch.object(self.client, "refund_cap") as refund_call, \
                mock.patch.object(self.client, "_prepare_comic_colored_pencil_references", lambda _job, _segment: _segment), \
                mock.patch.object(self.client, "_comic_download_frame_image", return_value="frame.local"), \
                mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            job["outDir"] = td
            page._run_comic_project_segments(job, [segment], lambda *_args, **_kwargs: None)

        self.assertEqual(segment["status"], "failed")
        self.assertEqual(PolicyFailureAdapter.submitted_models, ["doubao-seedance-2-0-260128"])
        precharge_call.assert_not_called()
        refund_call.assert_not_called()
        self.assertEqual(job["comicVideoModel"], "doubao-seedance-2-0-260128")
        self.assertEqual(job["model"], "doubao-seedance-2-0-260128")
        self.assertEqual(segment["model"], "doubao-seedance-2-0-260128")
        self.assertEqual(segment["comicVideoFallbacks"][0]["fallbackReason"], "InputImageSensitiveContentDetected.PolicyViolation")
        self.assertIn("Seedance 生成失败：素材版权/品牌风险", segment["error"])

    def test_build_replacement_segments_follow_original_duration(self):
        segments = self.client._build_replacement_segments(
            {"meta": {"duration": 20.5}},
            20.5,
            segment_seconds=8,
        )

        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0]["start"], 0.0)
        self.assertEqual(segments[0]["end"], 8.0)
        self.assertEqual(segments[1]["start"], 8.0)
        self.assertEqual(segments[1]["end"], 16.0)
        self.assertEqual(segments[2]["start"], 16.0)
        self.assertEqual(segments[2]["end"], 20.5)
        self.assertEqual([s["status"] for s in segments], ["pending", "pending", "pending"])

    def test_hybrid_plan_removes_script_overlap_between_adjacent_segments(self):
        first_repeat = "就这个法汀妮的粉底液啊，我自用三四年了，真的巨好用。"
        second_repeat = "这个粉底液之前都是要卖79块9一瓶的，它现在这个价格啊，还送了个气垫粉扑和试用装，并且有运费险啊。"
        plan = self.client._build_hybrid_replacement_plan(
            {
                "meta": {"duration": 24.0},
                "transcript": {
                    "segments": [
                        {
                            "startSec": 0.0,
                            "endSec": 8.0,
                            "text": "我想过它会卖69、59、49啊，但是没想到它居然能便宜到这个价格。" + first_repeat,
                        },
                        {
                            "startSec": 8.0,
                            "endSec": 16.0,
                            "text": first_repeat + "你们看它上脸这个流动性啊，特别的水润。" + second_repeat,
                        },
                        {
                            "startSec": 16.0,
                            "endSec": 24.0,
                            "text": second_repeat + "你到了可以先试用那个试用装。",
                        },
                    ]
                },
            },
            24.0,
            segment_seconds=8,
        )

        self.assertNotIn(first_repeat, plan[1]["script"])
        self.assertNotIn(second_repeat, plan[2]["script"])
        combined = "\n".join(item["script"] for item in plan)
        self.assertEqual(combined.count(first_repeat), 1)
        self.assertEqual(combined.count(second_repeat), 1)
        self.assertTrue(plan[1]["script"].startswith("你们看它上脸"))
        self.assertTrue(plan[2]["script"].startswith("你到了可以先试用"))

    def test_replacement_prompt_preserves_product_and_model_identity(self):
        segment = {"index": 1, "start": 0.0, "end": 8.0}
        analysis = {
            "report": "## 时间轴镜头拆解\n00:00 人物手持粉底液近景展示，字幕强调全天持妆。\n"
                      "## 仿拍脚本\n近景开场，产品 2 秒内出现。",
            "visual": "人物在室内展示产品并进行暴汗测试。",
            "ocr": {"text": "全天不补妆挑战"},
            "transcript": {"text": "[00:01.000-00:03.000] 今天测试这款粉底液"},
        }

        prompt = self.client._build_replacement_prompt(
            segment,
            analysis,
            "uploaded product: white liquid foundation bottle, red logo",
            "authorized model face: young adult woman",
        )

        self.assertIn("上传产品必须保持视觉一致", prompt)
        self.assertIn("外形、颜色、包装文字和 Logo", prompt)
        self.assertIn("authorized model face", prompt)
        self.assertIn("00:00 人物手持粉底液近景展示", prompt)
        self.assertIn("0.0-8.0 秒", prompt)

    def test_replacement_prompt_is_chinese_for_segment_display(self):
        prompt = self.client._build_replacement_prompt(
            {"index": 1, "start": 0.0, "end": 8.0},
            {"report": "原片是汽车销售短视频，节奏快，先给卖点再给保障。"},
            "上传产品图：银色新能源车",
            "授权真人脸图",
        )

        self.assertIn("生成一段新的电商短视频片段", prompt)
        self.assertIn("源视频锁定", prompt)
        self.assertIn("片段：0.0-8.0 秒", prompt)
        self.assertNotIn("Create a new e-commerce short-video segment", prompt)

    def test_run_replacement_segment_keeps_failed_segment_retryable(self):
        segment = {
            "index": 1,
            "start": 0.0,
            "end": 8.0,
            "prompt": "shot prompt",
            "keyframeUrl": "https://example.test/keyframe.png",
            "status": "pending",
        }
        job = {
            "model": "viduq3-turbo-cankaosheng",
            "productImageUrls": ["https://example.test/product.png"],
            "modelFaceUrl": "https://example.test/face.png",
            "outDir": "/tmp",
            "segments": [segment],
        }

        with mock.patch.object(self.client, "lk888_media_task", side_effect=RuntimeError("upstream failed")), \
                mock.patch.object(self.client, "json_log", return_value='{"errorId":"err-seg-1"}'):
            result = self.client._run_replacement_segment(job, segment)

        self.assertFalse(result["ok"])
        self.assertEqual(segment["status"], "failed")
        self.assertEqual(segment["errorId"], "err-seg-1")
        self.assertIn("upstream failed", segment["error"])

    def test_replacement_segment_generates_keyframe_before_video(self):
        segment = {"index": 1, "start": 0.0, "end": 8.0, "duration": 8.0, "status": "pending"}
        job = {
            "model": "viduq3-turbo-cankaosheng",
            "sourceVideoPath": "/tmp/source.mp4",
            "productImageUrls": ["https://example.test/product.png"],
            "modelFaceUrl": "https://example.test/face.png",
            "productNotes": "uploaded product: red eyebrow pencil",
            "modelNotes": "authorized model face",
            "outDir": "/tmp",
            "segments": [segment],
        }
        payloads = []

        def fake_media_task(model, payload, exts, progress=None, tries=110):
            payloads.append(payload)
            return "https://example.test/generated.mp4"

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.jpg"
            source.write_bytes(b"jpg-bytes")
            video = Path(td) / "seg.mp4"
            job["outDir"] = td

            with mock.patch.object(self.client, "_extract_replacement_source_frame",
                                   return_value=str(source)), \
                    mock.patch.object(self.client, "lk888_image_result", return_value=(
                        b"png-bytes" * 10, "https://example.test/keyframe.png"
                    )) as image_gen, \
                    mock.patch.object(self.client, "upload_asset_url",
                                      side_effect=[("http://127.0.0.1:9080/keyframe.png", {"ok": True})]), \
                    mock.patch.object(self.client, "lk888_media_task", side_effect=fake_media_task), \
                    mock.patch.object(self.client, "_wf_download", side_effect=lambda url, path: video.write_bytes(b"mp4")), \
                    mock.patch.object(self.client, "_breakdown_source_validation",
                                      return_value={"ok": True, "duration": 8, "width": 720, "height": 1280}):
                result = self.client._run_replacement_segment(job, segment)

            self.assertTrue(result["ok"])
            self.assertEqual(segment["keyframeUrl"], "https://example.test/keyframe.png")
            self.assertEqual(segment["keyframeLibraryUrl"], "http://127.0.0.1:9080/keyframe.png")
            self.assertTrue(Path(segment["keyframePath"]).name.startswith("replace_keyframe_01_"))
            image_gen.assert_called_once()
            self.assertEqual(payloads[0]["image_urls"][0], "https://example.test/keyframe.png")
            self.assertIn("https://example.test/product.png", payloads[0]["image_urls"])
            self.assertIn("https://example.test/face.png", payloads[0]["image_urls"])

    def test_replacement_video_prompt_uses_keyframe_as_first_frame_anchor(self):
        segment = {"index": 1, "start": 0.0, "end": 8.0, "keyframeUrl": "https://example.test/keyframe.png"}
        prompt = self.client._build_replacement_video_prompt(
            segment,
            "base segment prompt",
            has_keyframe=True,
            has_previous_anchor=True,
        )

        self.assertIn("使用第一张参考图作为开场关键帧", prompt)
        self.assertIn("人脸、产品包装、服装", prompt)
        self.assertIn("延续上一段参考图的视觉连续性", prompt)
        self.assertIn("base segment prompt", prompt)

    def test_replacement_uses_reference_video_model_with_all_identity_references(self):
        segment = {"index": 1, "start": 0.0, "end": 8.0, "duration": 8.0}
        job = {
            "productImageUrls": ["https://example.test/product.png"],
            "modelFaceUrl": "https://example.test/face.png",
        }

        model, payload = self.client._build_replacement_video_request(
            job,
            segment,
            "replacement video prompt",
            [
                "https://example.test/keyframe.png",
                "https://example.test/product.png",
                "https://example.test/face.png",
            ],
        )

        self.assertEqual(model, "viduq3-turbo-cankaosheng")
        self.assertEqual(payload["image_urls"][0], "https://example.test/keyframe.png")
        self.assertIn("https://example.test/product.png", payload["image_urls"])
        self.assertIn("https://example.test/face.png", payload["image_urls"])
        self.assertEqual(payload["params"]["duration"], 8)

    def test_comic_project_payload_uses_keyframes_and_manual_assets(self):
        job = {
            "id": "job-1",
            "title": "同款替换-job-1",
            "segments": [
                {"index": 1, "script": "第一句台词", "prompt": "镜头一"},
                {"index": 2, "script": "第二句台词", "prompt": "镜头二"},
            ],
            "model": "doubao-seedance-2-0-260128",
            "aspectRatio": "9:16",
            "audioMode": "tts",
            "voiceId": "xiaosi",
        }

        payload = self.client._comic_project_create_payload(job)

        self.assertEqual(payload["config"]["storyboard_workflow_mode"], "keyframes")
        self.assertEqual(payload["config"]["video_model"], "doubao-seedance-2-0-260128")
        self.assertFalse(payload["auto_generate_media"])
        self.assertFalse(payload["config"]["autoGenerateAssets"])
        self.assertEqual(payload["source_mode"], "matrix_video_replacement")
        self.assertTrue(payload["config"]["manualAssetsOnly"])
        self.assertEqual(payload["config"]["storyboardCount"], 2)
        self.assertEqual(len(payload["storyboards"]), 2)
        self.assertEqual(payload["storyboards"][0]["sequence"], 1)
        self.assertEqual(payload["storyboards"][0]["audio_prompt"]["dialogue"]["text"], "第一句台词")
        self.assertEqual(payload["storyboards"][1]["description"], "镜头二")
        self.assertNotIn("第一句台词", payload["source_text"])
        self.assertNotIn("口播：", payload["source_text"])
        self.assertIn("镜头二", payload["source_text"])

    def test_comic_project_markdown_motion_prompt_keeps_only_motion_contract(self):
        segment = {
            "index": 1,
            "script": "我想过它会卖69、59、49啊",
            "continuationPrompt": "与同组相邻片段保持连续；这是连续口播的第1/2段。",
            "prompt": (
                "生成一段新的电商短视频片段：匹配原视频的节奏。\n"
                "片段：0.0-15.0 秒，竖屏 9:16，720p。\n"
                "当前片段原片镜头约束：\n"
                "- ### 0s-4.8s - **画面：** 主观自拍近景，年轻女性对镜头口播，手持粉底液/开始展示产品。 "
                "- **人物：** 年轻女性，长发，浅绿色吊带，彩色美甲。 "
                "- **产品：** 粉底液。 "
                "- **动作：** 挤出粉底液到面颊，进入产品讲解。 "
                "- **字幕：** “它居然能便宜到这个价格” "
                "- **道具：** 粉底液瓶。 "
                "- **场景：** 卧室/衣帽间，浅色衣柜背景。 "
                "- **节奏：** 开场钩子快切，直接抛价格反差。\n"
                "- ### 4.8s-9s - **画面：** 近景展示粉底液瓶身，镜头聚焦产品。 "
                "- **人物：** 女主继续对镜头讲解。 "
                "- **产品：** 粉底液瓶。 "
                "- **动作：** 举瓶强调“自用三四年”。 "
                "- **道具：** 粉底液瓶盖、瓶身。 "
                "- **场景：** 原卧室背景。 "
                "- **节奏：** 稳定口播，建立信任。\n"
                "- ### 9s-14s - **画面：** 促销海报全屏贴图，信息密集。 "
                "- **人物：** 人物被信息覆盖。 "
                "- **产品：** 粉底液。 "
                "- **动作：** 讲活动价格、赠品、运费险。 "
                "- **道具：** 海报贴图、活动信息卡。 "
                "- **场景：** 原场景。 "
                "- **节奏：** 强信息点输出，形成价格锚定。\n"
                "以下是按要求精简提取的逐帧关键信息：\n"
                "| 帧数 | 动作 | 产品/道具 | 字幕 | 镜头节奏 |\n"
                "| 图1 | 将粉底液挤在左侧面颊。 | 粉底液 | 它居然能便宜到这个价格 | 近景，平视，静态。 |"
            ),
        }
        job = {
            "segments": [segment],
            "personReferenceUrls": ["https://cdn.example/person.png"],
            "productImageUrls": ["https://cdn.example/prop.png"],
        }

        payload = self.client._comic_project_create_payload(job)
        source_text = payload["source_text"]
        video_payload = self.client._comic_storyboard_video_payload(job, segment)

        for text in (source_text, video_payload["prompt"]):
            self.assertIn("镜头1：", text)
            self.assertIn("人物=项目库角色“主角”", text)
            self.assertIn("道具=项目库道具“道具1”", text)
            self.assertIn("动作=挤出上传道具到面颊", text)
            self.assertIn("节奏=开场钩子快切", text)
            self.assertNotIn("粉底液", text)
            self.assertNotIn("自用三四年", text)
            self.assertNotIn("活动价格", text)
            self.assertNotIn("运费险", text)
            self.assertNotIn("信息点", text)
            self.assertNotIn("价格锚定", text)
            self.assertNotIn("浅绿色吊带", text)
            self.assertNotIn("卧室", text)
            self.assertNotIn("口播", text)
            self.assertNotIn("它居然能便宜到这个价格", text)
            self.assertNotIn("| 帧数 |", text)
            self.assertNotIn(segment["script"], text)

    def test_comic_script_planner_keeps_15_second_boundary(self):
        segment = {
            "index": 1,
            "start": 0.0,
            "end": 8.0,
            "duration": 8.0,
            "script": "十五秒边界口播",
            "prompt": "人物面向镜头介绍产品",
        }

        with mock.patch.object(
                self.client,
                "_estimate_replacement_tts_duration_sec",
                return_value=15.0,
        ):
            planned = self.client._comic_plan_script_segments([segment])

        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]["speechDurationSec"], 15.0)
        self.assertEqual(planned[0]["videoDurationSec"], 15)
        self.assertEqual(planned[0]["index"], 1)
        self.assertEqual(planned[0]["sourceStart"], 0.0)
        self.assertEqual(planned[0]["sourceEnd"], 8.0)
        self.assertEqual(planned[0]["sourceDuration"], 8.0)

    def test_comic_script_planner_recursively_splits_without_text_loss(self):
        script = "".join(
            "第%d句介绍当前产品卖点和使用场景。" % index
            for index in range(1, 13)
        )
        segment = {
            "index": 4,
            "start": 24.0,
            "end": 32.0,
            "duration": 8.0,
            "script": script,
            "prompt": "人物连续讲解，镜头缓慢推进",
        }

        planned = self.client._comic_plan_script_segments([segment])

        self.assertGreater(len(planned), 1)
        self.assertTrue(all(item["speechDurationSec"] <= 15.0 for item in planned))
        self.assertEqual(
            "".join(item["script"] for item in planned).replace(" ", ""),
            script.replace(" ", ""),
        )
        self.assertEqual([item["index"] for item in planned], list(range(1, len(planned) + 1)))
        self.assertEqual([item["continuationIndex"] for item in planned], list(range(1, len(planned) + 1)))
        self.assertTrue(all(item["continuationCount"] == len(planned) for item in planned))
        self.assertTrue(all(
            planned[pos]["start"] == planned[pos - 1]["end"]
            for pos in range(1, len(planned))
        ))
        self.assertTrue(all(item["sourceStart"] == 24.0 for item in planned))
        self.assertTrue(all(item["sourceEnd"] == 32.0 for item in planned))
        self.assertTrue(all(item["sourceDuration"] == 8.0 for item in planned))

    def test_comic_duration_payload_uses_upper_supported_slot_and_auto_script_uses_tts(self):
        job = {
            "audioMode": "auto",
            "model": "doubao-seedance-2-0-260128",
            "segments": [{
                "index": 1,
                "script": "最终口播稿",
                "prompt": "人物展示上传道具",
                "speechDurationSec": 12.7,
                "videoDurationSec": 15,
            }],
        }

        project_payload = self.client._comic_project_create_payload(job)
        video_payload = self.client._comic_storyboard_video_payload(job, job["segments"][0])

        storyboard = project_payload["storyboards"][0]
        self.assertEqual(storyboard["duration"], 15)
        self.assertEqual(storyboard["video_duration"], 15)
        self.assertNotIn("audio_prompt", storyboard)
        self.assertEqual(video_payload["duration"], 15)
        self.assertEqual(video_payload["video_duration"], 15)
        self.assertEqual(video_payload["audio_mode"], "auto")
        self.assertNotIn("audio_prompt", video_payload)

    def test_hybrid_plan_assigns_each_transcript_segment_by_midpoint_once(self):
        analysis = {
            "meta": {"duration": 20.03},
            "transcript": {"segments": [
                {"startSec": 0.0, "endSec": 3.0, "text": "第一句"},
                {"startSec": 7.5, "endSec": 8.5, "text": "跨边界但属于第二段"},
                {"startSec": 15.0, "endSec": 19.0, "text": "最后一句"},
            ]},
        }

        planned = self.client._build_hybrid_replacement_plan(
            analysis, duration=20.03, segment_seconds=8
        )

        self.assertEqual(len(planned), 3)
        self.assertEqual(planned[0]["script"], "第一句")
        self.assertEqual(planned[1]["script"], "跨边界但属于第二段")
        self.assertEqual(planned[2]["script"], "最后一句")
        combined = " ".join(item["script"] for item in planned)
        self.assertEqual(combined.count("跨边界但属于第二段"), 1)

    def test_comic_project_source_text_strips_lk888_prompt_boilerplate(self):
        job = {
            "id": "job-clean-script",
            "segments": [{
                "index": 1,
                "script": "用户最终确认的台词",
                "prompt": "\n".join([
                    "生成一段新的电商短视频片段，必须严格参考源视频。",
                    "源视频锁定：原片动作、台词、字幕都要复刻。",
                    "原片拆解证据：字幕 OCR 显示旧口播。",
                    "字幕安全：不要保留原视频中文字幕。",
                    "画面：主播站在展厅车旁，右手指向车头，镜头缓慢推进。",
                    "口播对应：用户最终确认的台词",
                    "人物参考图只用于替换主角，不改变衣服。",
                    "上传产品必须保持一致。",
                    "只输出视频。",
                ]),
            }],
        }

        payload = self.client._comic_project_create_payload(job)
        source_text = payload["source_text"]
        update_payload = self.client._comic_storyboard_update_payload(job, job["segments"][0], {})

        self.assertIn("分镜 1", source_text)
        self.assertIn("画面：主播站在展厅车旁", source_text)
        self.assertNotIn("用户最终确认的台词", source_text)
        self.assertNotIn("源视频锁定", source_text)
        self.assertNotIn("原片拆解证据", source_text)
        self.assertNotIn("字幕安全", source_text)
        self.assertNotIn("人物参考图只用于", source_text)
        self.assertNotIn("生成一段新的电商短视频片段", source_text)
        self.assertNotIn("用户最终确认的台词", update_payload["description"])
        self.assertEqual(update_payload["dialogue"], "用户最终确认的台词")

    def test_comic_project_remote_prompt_uses_uploaded_assets_and_motion_only(self):
        segment = {
            "index": 1,
            "script": "这段最终口播稿只用于配音，不能写进画面提示词。",
            "prompt": "\n".join([
                "当前片段原片镜头约束：",
                "- 时间=0:00-0:04；画面=汽车展厅中景，男销售站在白色凯美瑞旁；人物=男销售，白衬衫黑领带；产品=白色丰田凯美瑞；动作=人物从正面中景转身，右手扶车门并指向车头；道具=汽车宣传牌；场景=广汽丰田4S店展厅；节奏=开场直接亮相，动作连贯流畅",
                "- 时间=0:04-0:08；画面=继续展示凯美瑞车头；人物=男销售；动作=向前一步并自然抬手展示重点位置；场景=汽车展厅；节奏=稳定讲解",
                "原片拆解证据：这是一条凯美瑞汽车销售视频，字幕 OCR 有优惠政策。",
            ]),
        }
        job = {
            "audioMode": "tts",
            "voiceId": "xiaosi",
            "personReferenceUrls": ["https://cdn.example/person.png"],
            "sceneImageUrl": "https://cdn.example/scene.png",
            "productImageUrls": ["https://cdn.example/prop.png"],
            "segments": [segment],
        }

        project_payload = self.client._comic_project_create_payload(job)
        image_payload = self.client._comic_storyboard_image_payload(job, segment)
        video_payload = self.client._comic_storyboard_video_payload(job, segment)
        generated_texts = [
            project_payload["source_text"],
            project_payload["storyboards"][0]["description"],
            image_payload["description"],
            image_payload["prompt"],
            video_payload["prompt"],
            video_payload["keyframes_video_prompt"],
        ]

        for text in generated_texts:
            self.assertIn("项目库角色“主角”", text)
            self.assertIn("项目库场景“场景1”", text)
            self.assertIn("项目库道具“道具1”", text)
            self.assertIn("动作连贯流畅", text)
            self.assertIn("向前一步并自然抬手", text)
            self.assertNotIn("这段最终口播稿", text)
            self.assertNotIn("男销售", text)
            self.assertNotIn("白衬衫", text)
            self.assertNotIn("黑领带", text)
            self.assertNotIn("凯美瑞", text)
            self.assertNotIn("丰田", text)
            self.assertNotIn("汽车展厅", text)
            self.assertNotIn("4S店", text)
            self.assertNotIn("汽车宣传牌", text)
            self.assertNotIn("OCR", text)
            self.assertNotIn("原片拆解证据", text)

        self.assertEqual(
            project_payload["storyboards"][0]["audio_prompt"]["dialogue"]["text"],
            "这段最终口播稿只用于配音，不能写进画面提示词。",
        )

    def test_comic_uploaded_assets_replace_old_entities_in_visual_contract(self):
        segment = {
            "index": 1,
            "script": "只使用最终口播稿",
            "prompt": "\n".join([
                "生成一段新的电商短视频片段",
                "当前片段原片镜头约束：",
                "- 时间=0:00-0:02；画面=汽车展厅中景；人物=男销售；产品=白色丰田凯美瑞；动作=手扶车门并指向车头；道具=汽车宣传牌；场景=汽车展厅；节奏=开场直接怼脸",
                "- 时间=0:02-0:05；画面=展厅中景；人物=男销售；产品=凯美瑞；动作=抚摸车头；场景=汽车展厅；节奏=稳定讲解",
                "原片拆解证据：这是一条凯美瑞汽车销售视频",
                "| 帧数 | 人物 | 产品 | 场景 | OCR |",
                "| 1 | 男销售 | 凯美瑞 | 汽车展厅 | 老板看车 |",
            ]),
            "startFrameUrl": "https://cdn.example/start.png",
            "endFrameUrl": "https://cdn.example/end.png",
        }
        job = {
            "audioMode": "auto",
            "personReferenceUrls": ["https://cdn.example/uploaded-person.png"],
            "productImageUrls": ["https://cdn.example/uploaded-prop.png"],
            "sceneImageUrl": "https://cdn.example/uploaded-scene.png",
            "segments": [segment],
        }

        visual = self.client._comic_visual_prompt_text(segment, job=job)
        image_payload = self.client._comic_storyboard_image_payload(job, segment)
        video_payload = self.client._comic_storyboard_video_payload(job, segment)

        self.assertIn("项目库角色“主角”", visual)
        self.assertIn("项目库场景“场景1”", visual)
        self.assertIn("项目库道具“道具1”", visual)
        for forbidden in ("凯美瑞", "汽车展厅", "男销售", "OCR", "| 帧数"):
            self.assertNotIn(forbidden, visual)
        self.assertIn("开场直接怼脸", visual)
        self.assertIn("稳定展示", visual)

        self.assertEqual(
            image_payload["character_reference_images"],
            ["https://cdn.example/uploaded-person.png"],
        )
        self.assertEqual(
            image_payload["scene_reference_images"],
            ["https://cdn.example/uploaded-scene.png"],
        )
        self.assertEqual(
            image_payload["prop_reference_images"],
            ["https://cdn.example/uploaded-prop.png"],
        )
        self.assertEqual(
            video_payload["character_reference_images"],
            ["https://cdn.example/uploaded-person.png"],
        )
        self.assertEqual(
            video_payload["scene_reference_images"],
            ["https://cdn.example/uploaded-scene.png"],
        )
        self.assertEqual(
            video_payload["prop_reference_images"],
            ["https://cdn.example/uploaded-prop.png"],
        )
        self.assertEqual(video_payload["reference_image_urls"][:2], [
            "https://cdn.example/start.png",
            "https://cdn.example/end.png",
        ])
        self.assertEqual(video_payload["reference_image_urls"], [
            "https://cdn.example/start.png",
            "https://cdn.example/end.png",
        ])

    def test_comic_project_visual_prompt_extracts_embedded_breakdown_without_subtitles(self):
        segment = {
            "index": 1,
            "script": "凯美瑞七月政策我来报",
            "prompt": (
                "当前片段原片镜头约束：\n"
                "- > 整体为固定机位中景 - **画面：** 女销售站在白色凯美瑞车头前，手扶车盖讲解 "
                "- **人物：** 女销售正面出镜 - **产品：** 2026款凯美瑞 "
                "- **动作：** 轻拍车盖 - **字幕：** 凯美瑞7月最新优惠 "
                "- **场景：** 广汽丰田4S店展厅 - **节奏：** 强钩子快速入题\n"
                "源视频锁定：保留原片台词和字幕。"
            ),
        }

        visual = self.client._comic_visual_prompt_text(segment)
        payload = self.client._comic_project_create_payload({"segments": [segment]})

        self.assertIn("女销售站在白色凯美瑞车头前", visual)
        self.assertIn("2026款凯美瑞", visual)
        self.assertIn("广汽丰田4S店展厅", visual)
        self.assertNotIn("当前片段原片镜头约束", visual)
        self.assertNotIn("字幕", visual)
        self.assertNotIn("凯美瑞7月最新优惠", visual)
        self.assertLess(len(payload["source_text"]), 700)

    def test_comic_project_person_reference_overrides_source_person_appearance(self):
        long_motion = "\n".join([
            "\u753b\u9762\uff1a\u5c55\u5385\u4e2d\u666f\uff0c\u9500\u552e\u987e\u95ee\u7ad9\u5728\u767d\u8272\u5c55\u8f66\u65c1\uff0c\u955c\u5934\u5c45\u4e2d\uff0c\u753b\u9762\u660e\u4eae\u3002",
            "\u4eba\u7269\uff1a\u7537\u9500\u552e\uff0c\u767d\u886c\u886b\u3001\u9ed1\u9886\u5e26\u3001\u773c\u955c\uff0c\u77ed\u53d1\uff0c\u4e13\u4e1a\u95e8\u5e97\u4e3b\u64ad\u5f62\u8c61\u3002",
            "\u52a8\u4f5c\uff1a\u4eba\u7269\u9762\u5bf9\u955c\u5934\u53e3\u64ad\uff0c\u53f3\u624b\u642d\u5728\u8f66\u8eab\u9644\u8fd1\uff0c\u968f\u540e\u624b\u6276\u8f66\u95e8\u5e76\u6307\u5411\u8f66\u5934\u3002",
            "\u573a\u666f\uff1a\u660e\u4eae4S\u5e97\u5c55\u5385\uff0c\u80cc\u666f\u6709\u5c55\u8f66\u3001\u7535\u5b50\u5c55\u793a\u53f0\u548c\u5e97\u5185\u5927\u5c4f\u3002",
            "\u8282\u594f\uff1a\u5f00\u95e8\u89c1\u5c71\uff0c\u5f3a\u94a9\u5b50\uff0c\u8bed\u901f\u5feb\uff0c\u7ee7\u7eed\u5c55\u793a\u8f66\u8eab\u7ec6\u8282\u548c\u9500\u552e\u624b\u52bf\uff0c\u4fdd\u6301\u6c7d\u8f66\u9500\u552e\u53e3\u64ad\u8282\u594f\u3002",
            "\u955c\u5934\uff1a\u4ece\u9500\u552e\u987e\u95ee\u6b63\u9762\u4e2d\u666f\u8f6c\u5230\u8f66\u5934\u4e09\u5206\u4e4b\u4e00\u6784\u56fe\uff0c\u4eba\u7269\u59cb\u7ec8\u4e0e\u5c55\u8f66\u4fdd\u6301\u6e05\u6670\u5173\u7cfb\u3002",
            "\u4ea7\u54c1\uff1a\u767d\u8272\u5c55\u8f66\u5c40\u90e8\u5165\u955c\uff0c\u8f66\u5934\u3001\u8f66\u95e8\u548c\u5c55\u793a\u53f0\u4f5c\u4e3a\u9500\u552e\u8bb2\u89e3\u7684\u4e3b\u8981\u89c6\u89c9\u652f\u70b9\u3002",
            "### 0:04.3 - 0:08.5",
            "- \u4fdd\u7559\u539f\u7247\u4eba\u7269\u89d2\u8272\uff1a\u7537\u9500\u552e\uff0c\u767d\u886c\u886b\u9ed1\u9886\u5e26\u3002",
            "- \u539f\u7247\u4eba\u7269\u69fd\u4f4d\uff1aperson_1=\u9500\u552e\u987e\u95ee\u3002\u66ff\u6362\u4e3a\u4e0a\u4f20\u6388\u6743\u4eba\u7269\u7684\u5b8c\u6574\u5916\u89c2\uff0c\u5305\u62ec\u8138\u3001\u53d1\u578b\u3001\u670d\u88c5\u3001\u4f53\u578b\u548c\u914d\u9970\u3002",
        ])
        job = {
            "id": "job-person-ref",
            "personReferenceUrls": ["https://example.test/female-character.png"],
            "segments": [{
                "index": 1,
                "script": "\u8fd9\u53f0\u8f66\u9002\u5408\u5bb6\u7528\u901a\u52e4\u3002",
                "prompt": long_motion,
            }],
        }

        payload = self.client._comic_project_create_payload(job)
        video_payload = self.client._comic_storyboard_video_payload(job, job["segments"][0])
        source_text = payload["source_text"]
        description = payload["storyboards"][0]["description"]

        for text in (source_text, description, video_payload["prompt"]):
            self.assertNotIn("\u7537\u9500\u552e", text)
            self.assertNotIn("\u767d\u886c\u886b", text)
            self.assertNotIn("\u9ed1\u9886\u5e26", text)
            self.assertNotIn("\u773c\u955c", text)
            self.assertNotIn("\u77ed\u53d1", text)
            self.assertNotIn("###", text)
            self.assertNotIn("\u4fdd\u7559\u539f\u7247\u4eba\u7269\u89d2\u8272", text)
            self.assertNotIn("\u539f\u7247\u4eba\u7269\u69fd\u4f4d", text)
            self.assertNotIn("truncated", text)
            self.assertIn("\u4eba\u7269\u5b8c\u6574\u5916\u89c2\u4ee5\u4e0a\u4f20\u89d2\u8272\u53c2\u8003\u56fe\u4e3a\u51c6", text)
            self.assertIn("\u9500\u552e\u987e\u95ee", text)
            self.assertIn("\u7ee7\u7eed\u5c55\u793a\u8f66\u8eab\u7ec6\u8282", text)

        self.assertGreater(len(description), 240)

    def test_comic_project_adapter_exchanges_matrix_ticket_once(self):
        calls = []

        class Response:
            def __init__(self, status_code, data):
                self.status_code = status_code
                self._data = data
                self.text = str(data)

            def json(self):
                return self._data

        def request_fn(method, url, headers=None, json=None, timeout=None):
            calls.append({"method": method, "url": url, "headers": headers or {}, "json": json or {}})
            if url == "http://central/api/comic/auth/ticket":
                return Response(200, {
                    "ok": True,
                    "ticket": "matrix-ticket",
                    "exchangePath": "/api/v2/auth/exchange-matrix-ticket",
                })
            if url == "http://comic/api/v2/auth/exchange-matrix-ticket":
                self.assertEqual(json["ticket"], "matrix-ticket")
                return Response(200, {"ok": True, "token": "comic-token", "expires_in": 3600})
            return Response(404, {"ok": False})

        adapter = self.client.ComicProjectAdapter(
            central_base="http://central",
            comic_base="http://comic",
            request_fn=request_fn,
            now_fn=lambda: 1000,
        )

        first = adapter._comic_headers()
        second = adapter._comic_headers()

        self.assertEqual(first["Authorization"], "Bearer comic-token")
        self.assertEqual(second["Authorization"], "Bearer comic-token")
        self.assertEqual([call["url"] for call in calls], [
            "http://central/api/comic/auth/ticket",
            "http://comic/api/v2/auth/exchange-matrix-ticket",
        ])

    def test_comic_project_default_request_ignores_environment_proxy(self):
        sessions = []

        class Response:
            status_code = 200
            text = "{}"

            def json(self):
                return {"ok": True}

        class SessionStub:
            def __init__(self):
                self.trust_env = True
                sessions.append(self)

            def request(self, method, url, **kwargs):
                self.method = method
                self.url = url
                self.kwargs = kwargs
                self.trust_env_at_request = self.trust_env
                return Response()

            def close(self):
                self.closed = True

        with mock.patch.object(self.client.requests, "Session", SessionStub):
            response = self.client._comic_request_no_proxy(
                "GET",
                "http://comic/api/v1/probe",
                headers={"X-Test": "1"},
                json={"ok": True},
                timeout=3,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(sessions), 1)
        self.assertFalse(sessions[0].trust_env_at_request)
        self.assertTrue(getattr(sessions[0], "closed", False))

    def test_comic_project_adapter_upserts_manual_assets(self):
        calls = []

        class Response:
            status_code = 200
            text = "{}"

            def __init__(self, asset_id):
                self.asset_id = asset_id

            def json(self):
                return {"ok": True, "data": {"id": self.asset_id}}

        def request_fn(method, url, headers=None, json=None, timeout=None):
            calls.append({"method": method, "url": url, "json": json or {}})
            return Response(100 + len(calls))

        adapter = self.client.ComicProjectAdapter(
            central_base="http://central",
            comic_base="http://comic",
            request_fn=request_fn,
            now_fn=lambda: 1000,
        )
        adapter._comic_token = "comic-token"
        adapter._comic_token_expires_at = 9999999999

        assets = adapter.upsert_manual_assets(88, {
            "faceSourceUrls": ["https://example.test/person.png"],
            "sceneImageUrl": "https://example.test/scene.png",
            "productImageUrls": ["https://example.test/product.png"],
            "voiceId": "xiaosi",
        })

        self.assertEqual([call["method"] for call in calls], ["POST", "POST", "POST"])
        self.assertEqual(calls[0]["url"], "http://comic/api/v1/comic-drama/projects/88/characters")
        self.assertEqual(calls[1]["url"], "http://comic/api/v1/comic-drama/projects/88/scenes")
        self.assertEqual(calls[2]["url"], "http://comic/api/v1/comic-drama/projects/88/props")
        self.assertEqual(calls[0]["json"]["reference_image"], "https://example.test/person.png")
        self.assertEqual(calls[1]["json"]["reference_images"], ["https://example.test/scene.png"])
        self.assertEqual(calls[2]["json"]["name"], "道具1")
        self.assertEqual(assets["characters"][0]["id"], "101")
        self.assertEqual(assets["scenes"][0]["id"], "102")
        self.assertEqual(assets["props"][0]["id"], "103")

    def test_comic_project_create_uses_long_timeout_for_remote_project_build(self):
        calls = []

        class Response:
            status_code = 200
            text = "{}"

            def json(self):
                return {"data": {"id": 88}}

        def request_fn(method, url, headers=None, json=None, timeout=None):
            calls.append({"method": method, "url": url, "timeout": timeout})
            return Response()

        adapter = self.client.ComicProjectAdapter(
            central_base="http://central",
            comic_base="http://comic",
            request_fn=request_fn,
        )
        adapter._comic_token = "comic-token"
        adapter._comic_token_expires_at = 9999999999

        adapter.create_project({"id": "job-slow-create", "segments": [{"index": 1, "prompt": "镜头一"}]})

        self.assertEqual(calls[0]["url"], "http://comic/api/v1/comic-drama/projects")
        self.assertGreaterEqual(calls[0]["timeout"], 240)

    def test_comic_project_manual_assets_map_products_to_props(self):
        job = {
            "faceSourceUrls": ["https://example.test/person.png"],
            "sceneImageUrl": "https://example.test/scene.png",
            "productImageUrls": ["https://example.test/product-a.png", "https://example.test/product-b.png"],
            "voiceId": "xiaosi",
        }

        assets = self.client._comic_project_manual_assets(job)

        self.assertEqual(assets["characters"][0]["reference_image_url"], "https://example.test/person.png")
        self.assertEqual(assets["characters"][0]["voice"], "xiaosi")
        self.assertEqual(assets["characters"][0]["reference_image"], "https://example.test/person.png")
        self.assertEqual(assets["characters"][0]["reference_images"], ["https://example.test/person.png"])
        self.assertEqual(assets["characters"][0]["voiceName"], "xiaosi")
        self.assertEqual(assets["characters"][0]["ttsVoice"], "xiaosi")
        self.assertEqual(assets["characters"][0]["voiceStatus"], "text_only")
        self.assertEqual(assets["characters"][0]["voiceType"], "text_note")
        self.assertEqual(assets["characters"][0]["voiceProvider"], "matrix")
        self.assertIn("xiaosi", assets["characters"][0]["voiceDescription"])
        self.assertEqual(assets["scenes"][0]["reference_image_url"], "https://example.test/scene.png")
        self.assertEqual([item["reference_image_url"] for item in assets["props"]], [
            "https://example.test/product-a.png",
            "https://example.test/product-b.png",
        ])
        self.assertEqual([item["name"] for item in assets["props"]], ["道具1", "道具2"])

    def test_comic_project_manual_assets_use_only_first_person_reference(self):
        assets = self.client._comic_project_manual_assets({
            "personReferenceUrls": [
                "https://example.test/person-front.png",
                "https://example.test/person-side.png",
                "https://example.test/person-back.png",
            ],
            "voiceId": "Zephyr",
        })

        self.assertEqual(len(assets["characters"]), 1)
        self.assertEqual(assets["characters"][0]["name"], "主角")
        self.assertEqual(
            assets["characters"][0]["reference_images"],
            ["https://example.test/person-front.png"],
        )
        self.assertEqual(assets["characters"][0]["voice"], "Zephyr")

    def test_comic_project_storyboard_payload_uses_script_and_keyframes(self):
        job = {
            "model": "doubao-seedance-2-0-260128",
            "audioMode": "tts",
            "voiceId": "xiaosi",
            "aspectRatio": "9:16",
            "comicProjectId": 88,
        }
        segment = {
            "index": 1,
            "script": "按用户最终口播稿说话",
            "prompt": "主角在门店介绍产品",
            "flowchartUrl": "https://example.test/flow.png",
        }

        payload = self.client._comic_storyboard_video_payload(job, segment)

        self.assertTrue(payload["auto_match_audio_duration"])
        self.assertTrue(payload["force_regenerate"])
        self.assertEqual(payload["workflow_mode"], "keyframes")
        self.assertEqual(payload["video_model"], "doubao-seedance-2-0-260128")
        self.assertEqual(payload["project_id"], 88)
        self.assertEqual(payload["projectId"], 88)
        self.assertEqual(payload["audio_prompt"]["dialogue"]["text"], "按用户最终口播稿说话")
        self.assertIn("主角在门店介绍产品", payload["keyframes_video_prompt"])
        self.assertIn("https://example.test/flow.png", payload["reference_image_urls"])

    def test_comic_project_storyboard_payload_keeps_dialogue_out_of_visual_prompt(self):
        job = {"audioMode": "tts", "voiceId": "xiaosi"}
        segment = {
            "index": 1,
            "script": "第一句台词",
            "prompt": "口播：第一句台词\n画面：主播站在车旁，右手指向车头，展厅灯光明亮。",
        }

        payload = self.client._comic_storyboard_video_payload(job, segment)
        update_payload = self.client._comic_storyboard_update_payload(job, segment, {})

        self.assertNotIn("第一句台词", payload["prompt"])
        self.assertNotIn("口播：", update_payload["description"])
        self.assertIn("主播站在车旁", update_payload["description"])
        self.assertEqual(update_payload["dialogue"], "第一句台词")
        self.assertEqual(update_payload["audio_prompt"]["dialogue"]["text"], "第一句台词")

    def test_video_replacement_mode_defaults_new_jobs_to_comic_project(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            self.assertEqual(self.client._video_replacement_default_mode(), "comic_project")
        with mock.patch.dict("os.environ", {"VIDEO_REPLACE_DEFAULT_MODE": "legacy"}):
            self.assertEqual(self.client._video_replacement_default_mode(), "legacy")

    def test_video_replacement_mode_keeps_old_json_legacy(self):
        self.assertEqual(self.client._replacement_job_mode({}), "legacy")
        self.assertEqual(self.client._replacement_job_mode({"replacementMode": "hybrid_v2"}), "legacy")
        self.assertEqual(self.client._replacement_job_mode({"replacementMode": "comic_project"}), "comic_project")

    def test_comic_project_audio_mode_allows_generated_video_sound(self):
        self.assertEqual(self.client._comic_project_audio_mode_block_reason("auto"), "")
        self.assertEqual(self.client._comic_project_audio_mode_block_reason("tts"), "")
        self.assertEqual(self.client._comic_project_audio_mode_block_reason("source"), "")
        self.assertIn("暂不支持", self.client._comic_project_audio_mode_block_reason("uploaded"))

    def test_comic_project_segment_failure_marks_partial_without_raising(self):
        class FailingComicAdapter:
            def update_storyboard(self, *_args, **_kwargs):
                raise RuntimeError("storyboard update failed")

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {
            "index": 1,
            "status": "planned",
            "comicStoryboardId": 101,
        }
        job = {
            "id": "job-comic-partial",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "comicAssets": {},
            "sourceVideoPath": "source.mp4",
            "outDir": "/tmp",
            "segments": [segment],
        }
        saved = []
        emitted = []

        def emit_progress(segment=None, stage="", message="", prompt=None):
            emitted.append(("progress", stage, message, segment))

        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {
                "emit": staticmethod(lambda tag, payload: emitted.append((tag, payload)))
            })()
        })()

        with mock.patch.object(self.client, "ComicProjectAdapter", FailingComicAdapter), \
                mock.patch.object(self.client, "_replacement_error_id", return_value="err-comic-seg"), \
                mock.patch.object(self.client, "_save_replacement_job", side_effect=lambda value: saved.append(dict(value))), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            page._run_comic_project_segments(job, [segment], emit_progress)

        self.assertEqual(job["status"], "partial")
        self.assertEqual(segment["status"], "failed")
        self.assertEqual(segment["stage"], "failed")
        self.assertEqual(segment["errorId"], "err-comic-seg")
        self.assertIn("storyboard update failed", segment["error"])
        self.assertEqual(saved[-1]["status"], "partial")
        self.assertEqual(emitted[-1][0], "video_replace_done")
        self.assertEqual(emitted[-1][1]["failedSegments"][0]["errorId"], "err-comic-seg")

    def test_comic_project_existing_project_recovers_missing_storyboard_ids(self):
        class RecoveringComicAdapter:
            updated_storyboard_ids = []

            def get_project(self, project_id):
                return {"data": {"id": project_id, "storyboards": [{"id": 201, "sequence": 1}]}}

            def upsert_manual_assets(self, *_args, **_kwargs):
                return {}

            def update_storyboard(self, storyboard_id, *_args, **_kwargs):
                self.updated_storyboard_ids.append(storyboard_id)

            def prepare_dialogue_audio(self, *_args, **_kwargs):
                return {"data": {"audio_url": "https://example.test/audio.mp3", "duration": 8.0}}

            def submit_storyboard_image(self, *_args, **_kwargs):
                return {"data": {"task_id": "image-task"}}

            def submit_storyboard_video(self, *_args, **_kwargs):
                return {"data": {"task_id": "video-task"}}

            def wait_task_result(self, task_id, **_kwargs):
                return "https://example.test/%s.mp4" % task_id, {"data": {"status": "completed"}}

            def download_media(self, _url, path, **_kwargs):
                Path(path).write_bytes(b"video")
                return path

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {"index": 1, "status": "failed", "script": "按新口播稿讲解", "duration": 8.0}
        job = {
            "id": "job-comic-recover-storyboard",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "comicVideoModel": "viduq3-cankaosheng",
            "model": "viduq3-cankaosheng",
            "sourceVideoPath": "source.mp4",
            "outDir": "/tmp",
            "segments": [segment],
        }
        emitted = []

        def emit_progress(segment=None, stage="", message="", prompt=None):
            emitted.append(("progress", stage, message, segment))

        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {
                "emit": staticmethod(lambda tag, payload: emitted.append((tag, payload)))
            })()
        })()

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "ComicProjectAdapter", RecoveringComicAdapter), \
                mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                mock.patch.object(self.client, "_wf_download", lambda _url, path: Path(path).write_bytes(b"video")), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            job["outDir"] = td
            page._run_comic_project_segments(job, [segment], emit_progress)

        self.assertEqual(segment["comicStoryboardId"], 201)
        self.assertEqual(RecoveringComicAdapter.updated_storyboard_ids, [201])
        self.assertEqual(segment["status"], "done")

    def test_comic_project_waits_for_both_frames_and_normalizes_media_urls(self):
        class DualFrameComicAdapter:
            calls = []

            def get_project(self, project_id):
                return {"data": {"id": project_id, "storyboards": [{"id": 201, "sequence": 1}]}}

            def upsert_manual_assets(self, *_args, **_kwargs):
                return {}

            def update_storyboard(self, *_args, **_kwargs):
                return {"ok": True}

            def submit_storyboard_image(self, *_args, **_kwargs):
                return {"data": {"task_ids": ["start-task", "end-task"]}}

            def submit_storyboard_video(self, *_args, **_kwargs):
                self.__class__.calls.append("submit:video")
                return {"data": {"task_id": "video-task"}}

            def wait_task_result(self, task_id, **_kwargs):
                self.__class__.calls.append("wait:%s" % task_id)
                urls = {
                    "start-task": "/uploads/start.png",
                    "end-task": "/uploads/end.png",
                    "video-task": "/uploads/video.mp4",
                }
                return urls[task_id], {"data": {"status": "completed", "url": urls[task_id]}}

            def download_media(self, url, path, **_kwargs):
                downloads.append(url)
                Path(path).write_bytes(b"video")
                return path

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {
            "index": 1,
            "status": "pending",
            "script": "test script",
            "comicStoryboardId": 201,
        }
        job = {
            "id": "job-comic-dual-frame",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "comicVideoModel": "viduq3-cankaosheng",
            "model": "viduq3-cankaosheng",
            "sourceVideoPath": "source.mp4",
            "outDir": "/tmp",
            "segments": [segment],
        }
        downloads = []
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda *_args: None)})()
        })()

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "ComicProjectAdapter", DualFrameComicAdapter), \
                mock.patch.object(self.client, "_comic_base_url", return_value="https://manju.yunlingai.net"), \
                mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            job["outDir"] = td
            page._run_comic_project_segments(job, [segment], lambda *_args, **_kwargs: None)

        self.assertEqual(DualFrameComicAdapter.calls, [
            "wait:start-task",
            "wait:end-task",
            "submit:video",
            "wait:video-task",
        ])
        self.assertEqual(segment["startFrameTaskId"], "start-task")
        self.assertEqual(segment["endFrameTaskId"], "end-task")
        self.assertEqual(segment["startFrameUrl"], "https://manju.yunlingai.net/uploads/start.png")
        self.assertEqual(segment["endFrameUrl"], "https://manju.yunlingai.net/uploads/end.png")
        self.assertEqual(segment["videoUrl"], "https://manju.yunlingai.net/uploads/video.mp4")
        self.assertEqual(downloads, [
            "https://manju.yunlingai.net/uploads/start.png",
            "https://manju.yunlingai.net/uploads/end.png",
            "https://manju.yunlingai.net/uploads/video.mp4",
        ])
        self.assertEqual(segment["status"], "done")

    def test_comic_project_charges_only_after_remote_actual_cost_is_returned(self):
        events = []

        class BillingComicAdapter:
            calls = []

            def get_project(self, project_id):
                return {"data": {"id": project_id, "storyboards": [{"id": 201, "sequence": 1}]}}

            def upsert_manual_assets(self, *_args, **_kwargs):
                return {}

            def update_storyboard(self, *_args, **_kwargs):
                return {"ok": True}

            def submit_storyboard_image(self, *_args, **_kwargs):
                events.append("submit:image")
                self.__class__.calls.append("submit:image")
                return {"data": {"task_ids": ["start-task", "end-task"]}}

            def submit_storyboard_video(self, *_args, **_kwargs):
                return {"data": {"task_id": "video-task"}}

            def wait_task_result(self, task_id, **_kwargs):
                if task_id in ("start-task", "end-task"):
                    return "https://example.test/%s.png" % task_id, {
                        "data": {
                            "status": "completed",
                            "task_id": task_id,
                            "actual_model": "gpt-image-2",
                            "cost": 0.0371,
                        }
                    }
                return "https://example.test/%s.mp4" % task_id, {
                    "data": {
                        "status": "completed",
                        "task_id": task_id,
                        "actual_model": "vidu/viduq3-mix_reference2video",
                        "cost": 10.898,
                    }
                }

            def download_media(self, _url, path, **_kwargs):
                Path(path).write_bytes(b"video")
                return path

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {"index": 1, "status": "pending", "script": "test script", "comicStoryboardId": 201}
        job = {
            "id": "job-comic-frame-billing",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "comicVideoModel": "viduq3-cankaosheng",
            "model": "viduq3-cankaosheng",
            "sourceVideoPath": "source.mp4",
            "outDir": "/tmp",
            "segments": [segment],
        }
        charged = []
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda *_args: None)})()
        })()

        def fake_charge(amount, **kwargs):
            charged.append((amount, dict(kwargs)))
            events.append("charge:%s" % kwargs.get("capability"))
            return True, 88.0, None

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "ComicProjectAdapter", BillingComicAdapter), \
                mock.patch.object(self.client, "try_charge", return_value=(True, None)) as precharge_call, \
                mock.patch.object(self.client, "charge", side_effect=fake_charge), \
                mock.patch.object(self.client, "refund_cap") as refund_cap, \
                mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            job["outDir"] = td
            page._run_comic_project_segments(job, [segment], lambda *_args, **_kwargs: None)

        precharge_call.assert_not_called()
        self.assertEqual([item[1]["capability"] for item in charged], [
            "comic_keyframe_image",
            "comic_keyframe_image",
            "comic_video_generation",
        ])
        self.assertEqual([item[0] for item in charged], [0.0371, 0.0371, 10.898])
        self.assertTrue(charged[0][1]["ref"].endswith(":frame:1:actual"))
        self.assertTrue(charged[1][1]["ref"].endswith(":frame:2:actual"))
        self.assertEqual(events[:3], [
            "submit:image",
            "charge:comic_keyframe_image",
            "charge:comic_keyframe_image",
        ])
        refund_cap.assert_not_called()

    def test_comic_project_frame_failure_keeps_only_lk888_successful_frame_charge(self):
        class FailingFrameComicAdapter:
            def get_project(self, project_id):
                return {"data": {"id": project_id, "storyboards": [{"id": 201, "sequence": 1}]}}

            def upsert_manual_assets(self, *_args, **_kwargs):
                return {}

            def update_storyboard(self, *_args, **_kwargs):
                return {"ok": True}

            def submit_storyboard_image(self, *_args, **_kwargs):
                return {"data": {"task_ids": ["start-task", "end-task"]}}

            def wait_task_result(self, task_id, **_kwargs):
                if task_id == "end-task":
                    raise RuntimeError("end frame failed")
                return "https://example.test/start.png", {
                    "data": {
                        "status": "completed",
                        "task_id": "start-task",
                        "actual_model": "gpt-image-2",
                        "cost": 0.0371,
                    }
                }

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {"index": 1, "status": "pending", "script": "test script", "comicStoryboardId": 201}
        job = {
            "id": "job-comic-frame-refund",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "comicVideoModel": "viduq3-cankaosheng",
            "model": "viduq3-cankaosheng",
            "sourceVideoPath": "source.mp4",
            "outDir": "/tmp",
            "segments": [segment],
        }
        charged = []
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda *_args: None)})()
        })()

        def fake_charge(amount, **kwargs):
            charged.append((amount, dict(kwargs)))
            return True, 88.0, None

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "ComicProjectAdapter", FailingFrameComicAdapter), \
                mock.patch.object(self.client, "try_charge", return_value=(True, None)) as precharge_call, \
                mock.patch.object(self.client, "charge", side_effect=fake_charge), \
                mock.patch.object(self.client, "refund_cap") as refund_cap, \
                mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            job["outDir"] = td
            page._run_comic_project_segments(job, [segment], lambda *_args, **_kwargs: None)

        self.assertEqual(segment["status"], "failed")
        precharge_call.assert_not_called()
        self.assertEqual(len(charged), 1)
        self.assertEqual(charged[0][0], 0.0371)
        self.assertEqual(charged[0][1]["capability"], "comic_keyframe_image")
        refund_cap.assert_not_called()

    def test_comic_project_reuses_saved_remote_video_without_resubmit(self):
        class ExistingVideoComicAdapter:
            def get_project(self, project_id):
                return {"data": {"id": project_id, "storyboards": [{
                    "id": 201,
                    "sequence": 1,
                    "start_frame_url": "/uploads/existing-start.png",
                    "end_frame_url": "/uploads/existing-end.png",
                    "video_url": "/uploads/existing-video.mp4",
                }]}}

            def upsert_manual_assets(self, *_args, **_kwargs):
                return {}

            def submit_storyboard_image(self, *_args, **_kwargs):
                raise AssertionError("existing video must not regenerate images")

            def submit_storyboard_video(self, *_args, **_kwargs):
                raise AssertionError("existing video must not be resubmitted")

            def download_media(self, url, path, **_kwargs):
                downloads.append(url)
                Path(path).write_bytes(b"video")
                return path

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {
            "index": 1,
            "status": "failed",
            "script": "test script",
            "comicStoryboardId": 201,
            "videoUrl": "/uploads/existing-video.mp4",
        }
        job = {
            "id": "job-comic-existing-video",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "sourceVideoPath": "source.mp4",
            "outDir": "/tmp",
            "comicAssets": {},
            "segments": [segment],
        }
        downloads = []
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda *_args: None)})()
        })()

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "ComicProjectAdapter", ExistingVideoComicAdapter), \
                mock.patch.object(self.client, "_comic_base_url", return_value="https://manju.yunlingai.net"), \
                mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            job["outDir"] = td
            page._run_comic_project_segments(job, [segment], lambda *_args, **_kwargs: None)

        self.assertEqual(segment["status"], "done")
        self.assertEqual(segment["startFrameUrl"], "https://manju.yunlingai.net/uploads/existing-start.png")
        self.assertEqual(segment["endFrameUrl"], "https://manju.yunlingai.net/uploads/existing-end.png")
        self.assertEqual(segment["videoUrl"], "https://manju.yunlingai.net/uploads/existing-video.mp4")
        self.assertEqual(downloads, [
            "https://manju.yunlingai.net/uploads/existing-start.png",
            "https://manju.yunlingai.net/uploads/existing-end.png",
            "https://manju.yunlingai.net/uploads/existing-video.mp4",
        ])

    def test_comic_project_segment_skips_local_audio_preparation(self):
        class NoLocalAudioComicAdapter:
            prepare_calls = 0

            def get_project(self, project_id):
                return {"data": {"id": project_id, "storyboards": [{"id": 201, "sequence": 1}]}}

            def upsert_manual_assets(self, *_args, **_kwargs):
                return {}

            def update_storyboard(self, *_args, **_kwargs):
                return {"ok": True}

            def prepare_dialogue_audio(self, *_args, **_kwargs):
                self.__class__.prepare_calls += 1
                raise AssertionError("local dialogue audio preparation must not be called")

            def submit_storyboard_image(self, *_args, **_kwargs):
                return {"data": {"task_id": "image-task"}}

            def submit_storyboard_video(self, *_args, **_kwargs):
                return {"data": {"task_id": "video-task"}}

            def wait_task_result(self, task_id, **_kwargs):
                return "https://example.test/%s.mp4" % task_id, {"data": {"status": "completed"}}

            def download_media(self, _url, path, **_kwargs):
                Path(path).write_bytes(b"video")
                return path

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {"index": 1, "status": "pending", "script": "按新口播稿讲解", "comicStoryboardId": 201}
        job = {
            "id": "job-comic-remote-auto-duration",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "comicVideoModel": "viduq3-cankaosheng",
            "model": "viduq3-cankaosheng",
            "sourceVideoPath": "source.mp4",
            "outDir": "/tmp",
            "segments": [segment],
        }
        emitted = []

        def emit_progress(segment=None, stage="", message="", prompt=None):
            emitted.append(("progress", stage, message, segment))

        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {
                "emit": staticmethod(lambda tag, payload: emitted.append((tag, payload)))
            })()
        })()

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "ComicProjectAdapter", NoLocalAudioComicAdapter), \
                mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                mock.patch.object(self.client, "_wf_download", lambda _url, path: Path(path).write_bytes(b"video")), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            job["outDir"] = td
            page._run_comic_project_segments(job, [segment], emit_progress)

        self.assertEqual(segment["status"], "done")
        self.assertEqual(NoLocalAudioComicAdapter.prepare_calls, 0)
        self.assertNotIn("audioPrepareStatus", segment)
        self.assertFalse(any(
            item[0] == "progress" and item[1] == "comic_prepare_audio"
            for item in emitted
        ))

    def test_comic_project_recovers_duplicate_billing_image_submit_from_storyboard_task(self):
        class DuplicateBillingComicAdapter:
            calls = []

            def get_project(self, project_id):
                self.calls.append("get_project:%s" % project_id)
                return {"data": {"id": project_id, "storyboards": [{
                    "id": 201,
                    "sequence": 1,
                    "flowchartTaskId": "image-task-recovered",
                }]}}

            def upsert_manual_assets(self, *_args, **_kwargs):
                return {}

            def update_storyboard(self, *_args, **_kwargs):
                return {"ok": True}

            def prepare_dialogue_audio(self, *_args, **_kwargs):
                return {"data": {"audio_url": "https://example.test/audio.mp3", "duration": 8.0}}

            def submit_storyboard_image(self, *_args, **_kwargs):
                self.calls.append("submit_storyboard_image")
                raise RuntimeError("comic_api_http_502:{'detail': '计费请求重复'}")

            def submit_storyboard_video(self, *_args, **_kwargs):
                return {"data": {"task_id": "video-task"}}

            def wait_task_result(self, task_id, **_kwargs):
                self.calls.append("wait_task_result:%s" % task_id)
                return "https://example.test/%s.mp4" % task_id, {"data": {"status": "completed"}}

            def download_media(self, _url, path, **_kwargs):
                Path(path).write_bytes(b"video")
                return path

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {"index": 1, "status": "pending", "script": "按新口播稿讲解", "comicStoryboardId": 201}
        job = {
            "id": "job-comic-duplicate-billing",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "comicVideoModel": "viduq3-cankaosheng",
            "model": "viduq3-cankaosheng",
            "sourceVideoPath": "source.mp4",
            "outDir": "/tmp",
            "segments": [segment],
        }
        emitted = []

        def emit_progress(segment=None, stage="", message="", prompt=None):
            emitted.append(("progress", stage, message, segment))

        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {
                "emit": staticmethod(lambda tag, payload: emitted.append((tag, payload)))
            })()
        })()

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "ComicProjectAdapter", DuplicateBillingComicAdapter), \
                mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                mock.patch.object(self.client, "_wf_download", lambda _url, path: Path(path).write_bytes(b"video")), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            job["outDir"] = td
            page._run_comic_project_segments(job, [segment], emit_progress)

        self.assertEqual(segment["status"], "done")
        self.assertEqual(segment["flowchartTaskId"], "image-task-recovered")
        self.assertEqual(segment["comicRecoveryStatus"], "recovered")
        self.assertIn("wait_task_result:image-task-recovered", DuplicateBillingComicAdapter.calls)

    def test_comic_project_preserves_submit_error_when_recovery_has_no_task(self):
        class MissingRecoveryComicAdapter:
            def get_project(self, project_id):
                return {"data": {"id": project_id, "storyboards": [{
                    "id": 201,
                    "sequence": 1,
                }]}}

            def upsert_manual_assets(self, *_args, **_kwargs):
                return {}

            def update_storyboard(self, *_args, **_kwargs):
                return {"ok": True}

            def submit_storyboard_image(self, *_args, **_kwargs):
                raise RuntimeError(
                    "comic_api_http_502:{'detail': '\u8ba1\u8d39\u8bf7\u6c42\u91cd\u590d'}"
                )

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {"index": 1, "status": "pending", "script": "test", "comicStoryboardId": 201}
        job = {
            "id": "job-comic-missing-recovery",
            "replacementMode": "comic_project",
            "comicProjectId": 296,
            "sourceVideoPath": "source.mp4",
            "outDir": "/tmp",
            "segments": [segment],
        }
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda *_args: None)})()
        })()

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "ComicProjectAdapter", MissingRecoveryComicAdapter), \
                mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            job["outDir"] = td
            page._run_comic_project_segments(job, [segment], lambda *_args, **_kwargs: None)

        self.assertEqual(segment["status"], "failed")
        self.assertIn("comic_api_http_502", segment["error"])
        self.assertIn("comic_image_recovery_missing", segment["error"])

    def test_comic_project_recovers_proxy_timeout_image_submit_from_storyboard_task(self):
        self.assertTrue(self.client._comic_generation_submit_can_recover(
            RuntimeError("HTTPConnectionPool(host='127.0.0.1', port=7897): Read timed out. (read timeout=120)")
        ))

    def test_comic_project_waits_async_analyze_task_before_using_storyboards(self):
        class AsyncAnalyzeComicAdapter:
            waited = False
            calls = []

            def create_project(self, _job):
                self.calls.append("create_project")
                return {"data": {"id": 88}}

            def get_project(self, project_id):
                self.calls.append("get_project")
                if not self.waited:
                    return {"data": {"id": project_id, "storyboards": []}}
                return {"data": {"id": project_id, "storyboards": [{"id": 301, "sequence": 1}]}}

            def analyze_project(self, project_id):
                self.calls.append("analyze_project")
                return {"data": {"task_id": "analyze-task-%s" % project_id}}

            def wait_task_done(self, task_id, **_kwargs):
                self.calls.append("wait_task_done:%s" % task_id)
                self.waited = True
                return {"data": {"status": "completed"}}

            def upsert_manual_assets(self, *_args, **_kwargs):
                self.calls.append("upsert_manual_assets")
                return {}

            def update_storyboard(self, storyboard_id, *_args, **_kwargs):
                self.calls.append("update_storyboard:%s" % storyboard_id)

            def prepare_dialogue_audio(self, *_args, **_kwargs):
                return {"data": {"audio_url": "https://example.test/audio.mp3", "duration": 8.0}}

            def submit_storyboard_image(self, *_args, **_kwargs):
                return {"data": {"task_id": "image-task"}}

            def submit_storyboard_video(self, *_args, **_kwargs):
                return {"data": {"task_id": "video-task"}}

            def wait_task_result(self, task_id, **_kwargs):
                return "https://example.test/%s.mp4" % task_id, {"data": {"status": "completed"}}

            def download_media(self, _url, path, **_kwargs):
                Path(path).write_bytes(b"video")
                return path

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {"index": 1, "status": "pending", "script": "按新口播稿讲解", "duration": 8.0}
        job = {
            "id": "job-comic-async-storyboard",
            "replacementMode": "comic_project",
            "comicVideoModel": "viduq3-cankaosheng",
            "model": "viduq3-cankaosheng",
            "sourceVideoPath": "source.mp4",
            "segments": [segment],
        }
        emitted = []

        def emit_progress(segment=None, stage="", message="", prompt=None):
            emitted.append(("progress", stage, message, segment))

        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {
                "emit": staticmethod(lambda tag, payload: emitted.append((tag, payload)))
            })()
        })()

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "ComicProjectAdapter", AsyncAnalyzeComicAdapter), \
                mock.patch.object(self.client, "_comic_base_url", return_value="http://comic"), \
                mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                mock.patch.object(self.client, "_wf_download", lambda _url, path: Path(path).write_bytes(b"video")), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            job["outDir"] = td
            page._run_comic_project_segments(job, [segment], emit_progress)

        self.assertEqual(segment["comicStoryboardId"], 301)
        self.assertIn("wait_task_done:analyze-task-88", AsyncAnalyzeComicAdapter.calls)
        self.assertIn("update_storyboard:301", AsyncAnalyzeComicAdapter.calls)
        self.assertEqual(segment["status"], "done")

    def test_replacement_rejects_text_to_video_model_before_spending_generation_credit(self):
        with self.assertRaisesRegex(RuntimeError, "不支持参考图"):
            self.client._build_replacement_video_request(
                {"model": "doubao-seedance-1-5-pro-251215"},
                {"duration": 8.0},
                "replacement video prompt",
                ["https://example.test/keyframe.png"],
            )

    def test_concat_requires_all_segments_to_pass_validation(self):
        with tempfile.TemporaryDirectory() as td:
            ok = Path(td) / "ok.mp4"
            bad = Path(td) / "bad.mp4"
            out = Path(td) / "out.mp4"
            ok.write_bytes(b"ok")
            bad.write_bytes(b"bad")

            validations = {
                str(ok): {"ok": True, "duration": 1, "width": 720, "height": 1280},
                str(bad): {"ok": False, "code": "download_html_body"},
            }

            with mock.patch.object(self.client, "_breakdown_source_validation",
                                   side_effect=lambda p: validations[p]), \
                    mock.patch.object(self.client, "mix_clips") as mix:
                with self.assertRaisesRegex(RuntimeError, "segment_invalid"):
                    self.client._concat_replacement_segments([str(ok), str(bad)], str(out))

            mix.assert_not_called()

    def test_save_replacement_to_assets_registers_video(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "final.mp4"
            video.write_bytes(b"video")
            job = {"sourceUrl": "https://www.douyin.com/video/1"}
            asset = {"id": "asset-1", "path": str(video)}

            with mock.patch.object(self.client, "add_asset", return_value=asset) as add:
                saved = self.client._save_replacement_to_assets(str(video), job)

        self.assertEqual(saved, asset)
        add.assert_called_once_with(
            str(video),
            kind="video",
            prompt="同款替换生成 https://www.douyin.com/video/1",
            source="视频替换生成",
        )

    def test_native_ui_has_video_replacement_entry_points(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn('("🧬 同款替换", lambda: VideoReplacementPage())', src)
        self.assertIn('self.b_replace = QtWidgets.QPushButton("替换生成")', src)
        self.assertIn('BRIDGE.payload.emit("goto_nav", "🧬 同款替换")', src)
        self.assertIn('"video_replace_start"', src)
        self.assertIn('class VideoReplacementPage(BasePage):', src)
        self.assertIn('self.face_authorized = QtWidgets.QCheckBox("我确认已获得该人物素材授权")', src)
        self.assertIn('self.b_face = QtWidgets.QPushButton("上传主角正脸全身照")', src)
        self.assertIn('self.person_full_body = QtWidgets.QCheckBox("该人物图为清晰正脸全身照（已确认）")', src)
        self.assertNotIn('self.principal_actor_lab = QtWidgets.QLabel("原片主角：尚未提取")', src)
        self.assertNotIn('self.principal_actor_preview = QtWidgets.QLabel("暂无预览")', src)
        self.assertNotIn('refs_l.addWidget(QtWidgets.QLabel("原片主角确认")', src)
        self.assertNotIn('self.target_person = QtWidgets.QComboBox()', src)
        self.assertIn('"principal_video_edit"', src)
        self.assertIn('self.b_virtual = QtWidgets.QPushButton("生成虚拟模特")', src)
        self.assertIn('self.b_retry_failed = QtWidgets.QPushButton("重试失败片段")', src)
        self.assertIn('"audioValidation": "disabled"', src)
        self.assertNotIn('"audioCheck": _replacement_audio_qc', src)

    def test_video_replacement_uses_one_person_reference_in_every_mode(self):
        src = CLIENT.read_text(encoding="utf-8")
        picker = src[src.index("    def pick_face(self):"):src.index("    def pick_scene(self):")]
        upload = src[src.index("    def _upload_refs(self, emit=None):"):src.index("    def _build_job(self):")]
        start = src[src.index("    def start_generation(self):"):src.index("        def work():", src.index("    def start_generation(self):"))]

        self.assertIn("QFileDialog.getOpenFileName(", picker)
        self.assertNotIn("QFileDialog.getOpenFileNames(", picker)
        self.assertIn("face_paths = list(self._face_paths[:1])", upload)
        self.assertNotIn("len(self._face_paths) != 3", start)
        self.assertNotIn("三张授权人脸照片", src)
        self.assertNotIn("self._face_paths[:3]", src)
        self.assertNotIn("self._face_urls[:3]", src)

    def test_replacement_start_has_visible_feedback(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn("self.progress = QtWidgets.QProgressBar()", src)
        self.assertIn('start_button.setText("生成中…")', src)
        self.assertIn('start_button.setText("开始替换生成")', src)
        self.assertIn("QtWidgets.QMessageBox.warning(self, \"替换生成\"", src)
        self.assertIn("QtWidgets.QMessageBox.information(self, \"替换生成\"", src)
    def test_comic_video_actual_billing_uses_only_remote_cost_and_model(self):
        job = {"id": "job-actual", "comicProjectId": 9}
        segment = {"index": 4, "comicVideoTaskId": "task-vidu-q3"}
        payload = {
            "data": {
                "status": "completed",
                "task_id": "task-vidu-q3",
                "requested_model": "doubao-seedance-2-0-260128",
                "actual_model": "vidu/viduq3-mix_reference2video",
                "cost": 10.898,
            }
        }

        with mock.patch.object(self.client, "refund_cap", return_value=(True, None)) as refund_call, \
                mock.patch.object(self.client, "charge", return_value=(True, 88.0, None)) as charge_call:
            settled = self.client._settle_comic_video_actual_billing({}, job, segment, payload)

        refund_call.assert_not_called()
        charge_call.assert_called_once()
        self.assertEqual(charge_call.call_args.args[0], 10.898)
        self.assertEqual(charge_call.call_args.kwargs["capability"], "comic_video_generation")
        self.assertTrue(charge_call.call_args.kwargs["allow_arrears"])
        self.assertEqual(charge_call.call_args.kwargs["meta"]["modelId"], "viduq3-cankaosheng")
        self.assertIn("viduq3-cankaosheng", charge_call.call_args.kwargs["reason"])
        self.assertNotIn("prechargedAmount", charge_call.call_args.kwargs["meta"])
        self.assertNotIn("prechargedRef", charge_call.call_args.kwargs["meta"])
        self.assertEqual(settled["model"], "viduq3-cankaosheng")
        self.assertEqual(settled["actualAmount"], 10.898)
        self.assertNotIn("prechargedAmount", settled)
        self.assertNotIn("prechargedRef", settled)

    def test_comic_keyframe_actual_billing_uses_remote_cost_and_model(self):
        self.assertTrue(hasattr(self.client, "_settle_comic_keyframe_actual_billing"))
        job = {"id": "job-frame-actual", "comicProjectId": 9}
        segment = {"index": 4}
        payload = {
            "data": {
                "status": "completed",
                "task_id": "task-image-1",
                "actual_model": "gpt-image-2",
                "cost": 0.0371,
            }
        }

        with mock.patch.object(self.client, "charge", return_value=(True, 88.0, None)) as charge_call:
            settled = self.client._settle_comic_keyframe_actual_billing(
                job, segment, payload, frame_index=1, task_id="task-image-1"
            )

        charge_call.assert_called_once()
        self.assertEqual(charge_call.call_args.args[0], 0.0371)
        self.assertEqual(charge_call.call_args.kwargs["meta"]["modelId"], "gpt-image-2")
        self.assertEqual(charge_call.call_args.kwargs["meta"]["actualAmount"], 0.0371)
        self.assertTrue(charge_call.call_args.kwargs["allow_arrears"])
        self.assertEqual(settled["status"], "settled")
        self.assertEqual(settled["model"], "gpt-image-2")

    def test_comic_video_regeneration_submit_failure_never_charges_or_refunds(self):
        class SubmitFailureAdapter:
            def model_prices(self):
                return {
                    "success": True,
                    "prices": [{
                        "model_id": "pixverse-v6-shouweizhen",
                        "model_type": "video",
                        "billing_method": "per_call",
                        "price_per_call": 0.2639,
                    }],
                }

            def update_storyboard(self, *_args, **_kwargs):
                return {}

            def submit_storyboard_video(self, *_args, **_kwargs):
                raise RuntimeError("provider submit failed")

        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {
            "index": 1,
            "comicStoryboardId": 201,
            "startFrameUrl": "https://comic.example/start.png",
            "endFrameUrl": "https://comic.example/end.png",
            "status": "done",
        }
        job = {
            "id": "job-refund",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "comicVideoModel": "pixverse-v6-shouweizhen",
            "segments": [segment],
        }
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda *_args: None)})()
        })()

        with mock.patch.object(self.client, "ComicProjectAdapter", return_value=SubmitFailureAdapter()), \
                mock.patch.object(self.client, "_save_replacement_job"), \
                mock.patch.object(self.client, "_replacement_error_id", return_value="err-submit"), \
                mock.patch.object(self.client, "try_charge", return_value=(True, None)) as precharge_call, \
                mock.patch.object(self.client, "refund_cap", return_value=(True, None)) as refund_call, \
                mock.patch.object(self.client, "BRIDGE", bridge):
            page._run_comic_video_regeneration(job, [segment])

        self.assertEqual(segment["status"], "failed")
        precharge_call.assert_not_called()
        refund_call.assert_not_called()

    def test_comic_video_download_recovery_never_charges_again(self):
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._cancel_requested = False
        segment = {
            "index": 1,
            "comicStoryboardId": 201,
            "status": "download_failed",
            "pendingComicVideoRecovery": {
                "taskId": "existing-task",
                "videoUrl": "https://comic.example/video.mp4",
                "status": "completed",
            },
        }
        job = {
            "id": "job-recovery",
            "replacementMode": "comic_project",
            "comicProjectId": 88,
            "segments": [segment],
        }
        bridge = type("BridgeStub", (), {
            "payload": type("PayloadStub", (), {"emit": staticmethod(lambda *_args: None)})()
        })()

        def complete_download(_job, candidate, _url, _adapter):
            candidate.update({"status": "done", "videoPath": "recovered.mp4"})

        with mock.patch.object(self.client, "ComicProjectAdapter", return_value=mock.Mock()), \
                mock.patch.object(self.client, "charge") as charge_call, \
                mock.patch.object(
                    self.client, "_comic_download_segment_video", side_effect=complete_download
                ), \
                mock.patch.object(self.client, "_save_replacement_job"), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            page._run_comic_video_regeneration(
                job, [segment], allow_pending_recovery=True
            )

        self.assertEqual(segment["status"], "done")
        charge_call.assert_not_called()

    def test_comic_video_billing_reference_is_readable_in_account_ledger(self):
        detail = self.client._billing_ref_display(
            "comic_video:job-billing:project:303:seg:2:1712345678_abcd1234"
        )

        self.assertIn("项目 303", detail)
        self.assertIn("片段 2", detail)
        self.assertNotIn("1712345678_abcd1234", detail)

    def test_comic_auto_final_gate_ignores_audio_and_legacy_qc_status(self):
        job = {"replacementMode": "comic_project", "audioMode": "auto"}
        segment = {
            "index": 1,
            "status": "done",
            "videoPath": "segment.mp4",
            "reviewApproved": True,
            "audioStatus": "failed",
            "qcStatus": "failed",
        }
        with mock.patch.object(
            self.client,
            "_comic_local_video_validation",
            return_value={"ok": True},
        ):
            self.assertTrue(
                self.client._replacement_segments_ready_for_final([segment], job=job)
            )

    def test_comic_auto_final_gate_allows_missing_audio_but_blocks_invalid_video(self):
        job = {"replacementMode": "comic_project", "audioMode": "auto"}
        segment = {
            "index": 1,
            "status": "done",
            "videoPath": "segment.mp4",
            "reviewApproved": True,
        }
        with mock.patch.object(
            self.client,
            "_comic_local_video_validation",
            return_value={"ok": True, "hasAudio": False},
        ):
            self.assertTrue(
                self.client._replacement_segments_ready_for_final([segment], job=job)
            )
        with mock.patch.object(
            self.client,
            "_comic_local_video_validation",
            return_value={"ok": False, "hasAudio": True, "code": "media_decode_failed"},
        ):
            self.assertFalse(
                self.client._replacement_segments_ready_for_final([segment], job=job)
            )


if __name__ == "__main__":
    unittest.main()
